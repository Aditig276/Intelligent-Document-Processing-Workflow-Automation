"""Security utilities for safe file downloads and path traversal prevention."""

import logging
import mimetypes
import os
from pathlib import Path
import stat

from django.conf import settings
from django.http import FileResponse, Http404

logger = logging.getLogger("processing_jobs.auth")


class InvalidMediaPathError(Exception):
    """Raised when a file or directory path fails confinement or safety validation."""


def safe_log(log_fn, *args, **kwargs):
    """Safely log without raising exceptions if logging fails."""
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


CONTENT_TYPE_MAPPING = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

ALLOWED_SERVE_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "text/csv; charset=utf-8",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "application/octet-stream",
}


GENERIC_USER_ERROR = "An error occurred while processing the document."


def sanitize_error_message(error: Exception | str) -> str:
    r"""Sanitize error messages to prevent disclosing internal server filesystem paths.

    Strips:
    - settings.MEDIA_ROOT and settings.BASE_DIR.
    - Windows drive paths (including paths with spaces and unusual characters).
    - Windows UNC network paths (e.g. \\server\share\...).
    - Unix/POSIX absolute directory hierarchies (including paths with spaces).
    - Internal traceback lines.

    If path remnants or raw system tracebacks cannot be safely sanitized,
    falls back to a generic user-facing error message.
    """
    if not error:
        return ""

    text = str(error).strip()
    if not text:
        return ""

    # Check for raw traceback headers
    if "Traceback (most recent call last):" in text:
        return GENERIC_USER_ERROR

    media_root = str(getattr(settings, "MEDIA_ROOT", "")).strip()
    base_dir = str(getattr(settings, "BASE_DIR", "")).strip()

    if media_root:
        text = text.replace(media_root, "[MEDIA_ROOT]")
        text = text.replace(media_root.replace("\\", "/"), "[MEDIA_ROOT]")
    if base_dir:
        text = text.replace(base_dir, "[BASE_DIR]")
        text = text.replace(base_dir.replace("\\", "/"), "[BASE_DIR]")

    import re

    # 1. Sanitize Windows UNC paths (e.g. \\server\share\folder with spaces\file.pdf)
    def _clean_unc(m):
        raw = m.group(0).rstrip(".,;)'\"")
        parts = [p for p in raw.replace("/", "\\").split("\\") if p]
        return parts[-1] if parts else "[FILE]"

    text = re.sub(r"\\\\[^:*?\"<>|\r\n\t]+", _clean_unc, text)
    text = re.sub(r"//[^:*?\"<>|\r\n\t]+", _clean_unc, text)

    # 2. Sanitize Windows drive paths (e.g. C:\folder with spaces\file.pdf)
    def _clean_win(m):
        raw = m.group(0).rstrip(".,;)'\"")
        parts = [p for p in raw.replace("/", "\\").split("\\") if p]
        return parts[-1] if parts else "[FILE]"

    text = re.sub(r"[A-Za-z]:[\\/][^:*?\"<>|\r\n\t]+", _clean_win, text)

    # 3. Sanitize Unix/POSIX paths (e.g. /var/log/secret folder/file.pdf)
    def _clean_unix(m):
        raw = m.group(0).rstrip(".,;)'\"")
        parts = [p for p in raw.split("/") if p]
        return parts[-1] if parts else "[FILE]"

    text = re.sub(r"/(?:[^/\0\r\n\t]+/)+[^/\0\r\n\t]+", _clean_unix, text)

    # Normalize double spaces
    text = re.sub(r"\s+", " ", text).strip()

    # If any raw path separators remain attached to drive letters or UNC prefixes,
    # fall back to generic error message
    if re.search(r"[A-Za-z]:[\\/]|\\\\", text):
        return GENERIC_USER_ERROR

    return text


def _get_descriptor_path(file_handle) -> Path | None:
    """Resolve the canonical filesystem path of an open file descriptor across platforms."""
    try:
        fd = file_handle.fileno()
    except Exception:
        return None

    # Windows: resolve real target path of the open file handle via Kernel32
    if os.name == "nt":
        try:
            import msvcrt
            import ctypes
            handle = msvcrt.get_osfhandle(fd)
            buf = ctypes.create_unicode_buffer(1024)
            ret = ctypes.windll.kernel32.GetFinalPathNameByHandleW(handle, buf, 1024, 0)
            if ret > 0:
                p = buf.value
                if p.startswith("\\\\?\\"):
                    p = p[4:]
                return Path(p).resolve()
        except Exception:
            pass
    # Linux: resolve canonical target from /proc/self/fd
    elif hasattr(os, "readlink"):
        try:
            proc_path = f"/proc/self/fd/{fd}"
            if os.path.exists(proc_path):
                return Path(os.readlink(proc_path)).resolve()
        except Exception:
            pass
    return None


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for safe HTTP Content-Disposition headers.

    Prevents HTTP header injection and path traversal in the suggested download filename.
    """
    if not filename:
        return "download"
    # Take only the base name (no directories)
    base = Path(str(filename)).name.replace("\\", "/").split("/")[-1]
    # Remove control characters, quotes, and newlines
    clean = "".join(c for c in base if c.isalnum() or c in ("-", "_", ".", " ")).strip()
    # Strip leading/trailing dots and spaces to prevent traversal or extension masking
    clean = clean.strip(". ")
    if not clean or clean in (".", ".."):
        return "download"
    return clean


def validate_media_path(
    file_path: Path | str,
    *,
    base_dir: Path | str | None = None,
    must_exist: bool = True,
    expect_file: bool = True,
    expect_dir: bool = False,
) -> Path:
    """Resolve and validate that a path is safely confined within MEDIA_ROOT (or base_dir).

    Rejects:
    - Empty/null/malformed paths and null bytes.
    - Absolute paths or traversal sequences resolving outside the base directory.
    - Symbolic links (including parent directory symlinks inside the base directory).
    - Missing paths (when must_exist=True) or non-regular files / wrong entry types.
    """
    if expect_file and expect_dir:
        raise ValueError("expect_file and expect_dir cannot both be True.")

    if not file_path or not isinstance(file_path, (str, Path)):
        raise InvalidMediaPathError("Empty or invalid file path.")

    raw_str = str(file_path)
    if not raw_str.strip() or "\x00" in raw_str:
        raise InvalidMediaPathError("Malformed or empty file path.")

    configured_root = base_dir if base_dir is not None else getattr(settings, "MEDIA_ROOT", None)
    if not configured_root:
        raise InvalidMediaPathError("MEDIA_ROOT is not configured.")

    try:
        base = Path(configured_root)
        root = base.resolve()
        raw_path = Path(file_path)
        if raw_path.is_absolute():
            unresolved = raw_path
            candidate = raw_path.resolve()
        else:
            unresolved = root / raw_path
            candidate = unresolved.resolve()
    except (ValueError, TypeError, OSError) as exc:
        raise InvalidMediaPathError(f"Malformed file path rejected: {exc}") from exc

    # Confinement check against resolved base directory
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise InvalidMediaPathError(
            f"Path escapes permitted base directory: {file_path}"
        ) from exc

    # Reject symlinks anywhere along the path below the base directory
    for parent in (unresolved, *unresolved.parents):
        if parent == root or parent == base:
            break
        try:
            if parent.is_symlink():
                raise InvalidMediaPathError(
                    f"Symbolic links are not permitted: {parent}"
                )
            if parent.exists() and parent.resolve() == root:
                break
        except OSError as exc:
            raise InvalidMediaPathError(f"Invalid path component: {exc}") from exc
        if parent == parent.parent:
            break

    if expect_file and candidate == root:
        raise InvalidMediaPathError("File path cannot resolve to the root directory itself.")

    if must_exist:
        if not candidate.exists():
            raise InvalidMediaPathError(f"Requested path does not exist: {candidate.name}")
        try:
            st_mode = candidate.lstat().st_mode
        except OSError as exc:
            raise InvalidMediaPathError(f"Unable to stat path: {exc}") from exc
        if expect_file and (not stat.S_ISREG(st_mode) or not candidate.is_file()):
            raise InvalidMediaPathError(f"Requested path is not a regular file: {candidate.name}")
        if expect_dir and (not stat.S_ISDIR(st_mode) or not candidate.is_dir()):
            raise InvalidMediaPathError(f"Requested path is not a directory: {candidate.name}")
    elif candidate.exists():
        try:
            st_mode = candidate.lstat().st_mode
        except OSError as exc:
            raise InvalidMediaPathError(f"Unable to stat path: {exc}") from exc
        if expect_file and (not stat.S_ISREG(st_mode) or not candidate.is_file()):
            raise InvalidMediaPathError(f"Target path is not a regular file: {candidate.name}")
        if expect_dir and (not stat.S_ISDIR(st_mode) or not candidate.is_dir()):
            raise InvalidMediaPathError(f"Target path is not a directory: {candidate.name}")

    return candidate


def get_validated_extracted_result_path(
    job_id: int,
    *,
    base_dir: Path | str | None = None,
    must_exist: bool = True,
    create_dir: bool = False,
) -> Path:
    """Validate and return the confined extracted JSON result path for a job."""
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise InvalidMediaPathError("Invalid job identifier for extracted result.")

    extracted_dir = validate_media_path(
        "extracted",
        base_dir=base_dir,
        must_exist=not create_dir and must_exist,
        expect_file=False,
        expect_dir=True,
    )
    if create_dir:
        try:
            extracted_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InvalidMediaPathError(f"Unable to prepare extracted directory: {exc}") from exc
        validate_media_path(
            "extracted",
            base_dir=base_dir,
            must_exist=True,
            expect_file=False,
            expect_dir=True,
        )

    return validate_media_path(
        Path("extracted") / f"job_{job_id}.json",
        base_dir=base_dir,
        must_exist=must_exist,
        expect_file=True,
        expect_dir=False,
    )


def serve_secure_file(
    file_path: Path | str,
    download_filename: str,
    content_type: str | None = None,
    base_dir: Path | None = None,
) -> FileResponse:
    """Safely resolve, validate, and serve a file from the server storage.

    Enforces:
    1. Base directory confinement to prevent path traversal vulnerabilities.
    2. Rejection of symlinks and non-regular files.
    3. Verification that the file exists on disk.
    4. Safe Content-Type headers preserving correct MIME type.
    5. Sanitized Content-Disposition headers.
    6. Clean 404 responses without leaking internal filesystem paths or stack traces.
    """
    try:
        candidate = validate_media_path(
            file_path,
            base_dir=base_dir,
            must_exist=True,
            expect_file=True,
        )
    except InvalidMediaPathError as exc:
        safe_log(
            logger.warning,
            "Security validation rejected file serve request (%s): %s",
            file_path,
            exc,
        )
        raise Http404("File not found.")

    safe_name = sanitize_filename(download_filename)
    ext = candidate.suffix.lower()

    # Validate caller-supplied content_type against trusted whitelist
    valid_content_type = None
    if content_type:
        normalized_type = str(content_type).strip().lower()
        if (
            "\r" not in normalized_type
            and "\n" not in normalized_type
            and normalized_type in ALLOWED_SERVE_CONTENT_TYPES
        ):
            valid_content_type = normalized_type
        else:
            safe_log(
                logger.warning,
                "Untrusted or malformed Content-Type '%s' rejected for %s; using safe mapping.",
                content_type,
                candidate.name,
            )

    if not valid_content_type:
        valid_content_type = (
            CONTENT_TYPE_MAPPING.get(ext)
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )

    # Determine base confinement directory
    configured_root = base_dir if base_dir is not None else getattr(settings, "MEDIA_ROOT", None)
    root = Path(configured_root).resolve() if configured_root else None

    try:
        expected_stat = candidate.stat()
        file_handle = candidate.open("rb")
        fd_stat = os.fstat(file_handle.fileno())

        # 1. Validate that the opened descriptor represents a regular file
        if not stat.S_ISREG(fd_stat.st_mode):
            file_handle.close()
            safe_log(logger.error, "Opened descriptor for %s is not a regular file", candidate.name)
            raise Http404("File not found.")

        # 2. Validate descriptor identity matches pre-validated file (detects TOCTOU file replacement)
        if hasattr(os.path, "samestat") and expected_stat.st_ino != 0 and fd_stat.st_ino != 0:
            if not os.path.samestat(expected_stat, fd_stat):
                file_handle.close()
                safe_log(logger.error, "File descriptor identity mismatch for %s", candidate.name)
                raise Http404("File not found.")

        # 3. Validate that the opened descriptor is strictly confined to MEDIA_ROOT (fail closed)
        if root is not None:
            real_fd_path = _get_descriptor_path(file_handle)
            if real_fd_path is None:
                file_handle.close()
                safe_log(
                    logger.error,
                    "Failed closed: descriptor-path resolution returned None for %s",
                    candidate.name,
                )
                raise Http404("File not found.")
            try:
                real_fd_path.relative_to(root)
            except ValueError:
                file_handle.close()
                safe_log(
                    logger.error,
                    "Open descriptor escapes permitted root (%s): %s",
                    root,
                    real_fd_path,
                )
                raise Http404("File not found.")

    except OSError as exc:
        safe_log(logger.error, "Failed to open file %s: %s", candidate.name, exc)
        raise Http404("File not found.")

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=safe_name,
        content_type=valid_content_type,
    )
    # Ensure X-Content-Type-Options is set
    response["X-Content-Type-Options"] = "nosniff"
    return response
