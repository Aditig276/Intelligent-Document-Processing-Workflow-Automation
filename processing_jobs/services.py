import hashlib
import logging
from pathlib import Path
import threading
import time
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from app.security.django_adapter import can_django_user_upload
from .models import ProcessingJob

logger = logging.getLogger("processing_jobs")
auth_logger = logging.getLogger("processing_jobs.auth")

_rate_limit_lock = threading.Lock()


def safe_log(log_fn, *args, **kwargs):
    """Safely log without raising exceptions if logging fails."""
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


def ingest_document(
    uploaded_file,
    original_filename: str | None = None,
    owner=None,
    content: bytes | None = None,
) -> ProcessingJob:
    """Shared document ingestion service.

    Accepts a validated uploaded file or bytes, safely stores it on disk
    using a server-generated UUID4 filename, calculates file size and SHA-256,
    and creates a ProcessingJob in PENDING status.
    Associates the authenticated owner if available.
    Ensures that any database error during job creation unlinks the written
    file, preventing orphaned files on disk.
    """
    raw_name = original_filename or getattr(uploaded_file, "name", "document")
    # Sanitize filename and prevent directory traversal
    safe_original_name = Path(raw_name).name.replace("\\", "/").split("/")[-1]
    ext = Path(safe_original_name).suffix.lower()

    # Read content if not provided
    if content is None:
        if hasattr(uploaded_file, "read"):
            content = uploaded_file.read()
            if hasattr(uploaded_file, "seek"):
                try:
                    uploaded_file.seek(0)
                except Exception:
                    pass
        elif hasattr(uploaded_file, "chunks"):
            content = b"".join(uploaded_file.chunks())
        else:
            content = bytes(uploaded_file)

    file_size = len(content)
    sha256 = hashlib.sha256(content).hexdigest()

    # Ensure MEDIA_ROOT directory exists
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)

    # Server-generated unique UUID4 hex filename with normalized extension
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = media_root / stored_filename

    # Store file to disk safely
    try:
        with file_path.open("wb") as destination:
            destination.write(content)
    except Exception as exc:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        raise OSError(f"Unable to store the uploaded file: {exc}") from exc

    # Determine job owner
    job_owner = None
    if owner and getattr(owner, "is_authenticated", False):
        job_owner = owner

    # Atomically create ProcessingJob; cleanup file on failure
    try:
        with transaction.atomic():
            job = ProcessingJob.objects.create(
                owner=job_owner,
                file_name=safe_original_name,
                file_type=ext.lstrip("."),
                file_size=file_size,
                storage_reference=stored_filename,
                status=ProcessingJob.Status.PENDING,
            )
    except Exception:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        raise

    # Attach dynamic properties for callers (API responses, etc.)
    job.sha256 = sha256
    job.stored_filename = stored_filename

    safe_log(
        logger.info,
        "Document ingested: job_id=%s, file_name=%s, stored_filename=%s, size=%s, sha256=%s, owner=%s",
        job.id,
        safe_original_name,
        stored_filename,
        file_size,
        sha256,
        job_owner.username if job_owner else "Anonymous",
    )

    return job


def check_rate_limit(request, user=None):
    """Check if the upload request exceeds the configured upload rate limit.

    Uses a sliding window tracked in Django's cache backend.
    Thread-safe and concurrency-safe across workers via local mutex and
    distributed cache-lock synchronization.
    Prevents IP spoofing by refusing to trust X-Forwarded-For headers
    unless SECURE_TRUST_FORWARDED_FOR is explicitly enabled for trusted reverse proxies.

    Multi-instance deployment note:
    In multi-server deployments, configure a shared Redis cache backend (e.g.,
    REDIS_URL=redis://...) in Django settings so rate limit counters and locks
    synchronize atomically across all worker nodes.

    Returns (is_limited: bool, retry_after: int).
    """
    if not getattr(settings, "UPLOAD_RATE_LIMIT_ENABLED", True):
        return False, 0

    max_requests = getattr(settings, "UPLOAD_RATE_LIMIT_REQUESTS", 100)
    window = getattr(settings, "UPLOAD_RATE_LIMIT_WINDOW", 60)

    # Resolve client identity safely
    if user and getattr(user, "is_authenticated", False):
        identifier = f"user:{user.id}"
    else:
        if getattr(settings, "SECURE_TRUST_FORWARDED_FOR", False):
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            ip = (
                forwarded.split(",")[0].strip()
                if forwarded
                else request.META.get("REMOTE_ADDR", "unknown")
            )
        else:
            ip = request.META.get("REMOTE_ADDR", "unknown")
        identifier = f"ip:{ip}"

    cache_key = f"ratelimit_upload:{identifier}"
    lock_key = f"lock_{cache_key}"

    with _rate_limit_lock:
        # Acquire cache-level lock for cross-process synchronization
        acquired_lock = False
        for _ in range(50):  # Retry up to 500ms
            if cache.add(lock_key, "1", timeout=5):
                acquired_lock = True
                break
            time.sleep(0.01)

        try:
            now = time.time()
            timestamps = cache.get(cache_key, [])
            cutoff = now - window
            # Keep only timestamps within the active sliding window
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= max_requests:
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + window - now))
                return True, retry_after

            timestamps.append(now)
            cache.set(cache_key, timestamps, timeout=window + 1)
            return False, 0
        finally:
            if acquired_lock:
                cache.delete(lock_key)
