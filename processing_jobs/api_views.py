import csv
import hashlib
import io
import logging
from pathlib import Path
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from .api_auth import authenticate_api_request
from .services import check_rate_limit, ingest_document


logger = logging.getLogger("documents.upload")

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".xls",
    ".xlsx",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
}

IMAGE_FORMAT_MAP = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB


@require_http_methods(["GET"])
def health_check(request):
    """Health check endpoint: GET /api/health/ -> 200 {"status": "healthy"}."""
    return JsonResponse({"status": "healthy"})


@require_POST
def upload_file(request):
    """File upload API: POST /api/upload/."""
    # 1. IP rate limit check (protects against anonymous or DoS flooding)
    is_limited, retry_after = check_rate_limit(request, None)
    if is_limited:
        logger.warning("Upload rate limit exceeded for client IP.")
        response = JsonResponse(
            {"error": "Rate limit exceeded. Please try again later."},
            status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response

    # 2. Authenticate API request
    user, auth_error = authenticate_api_request(request)
    if auth_error is not None:
        return auth_error

    # 3. User quota rate limit check (protects against authenticated flooding)
    is_limited, retry_after = check_rate_limit(request, user)
    if is_limited:
        logger.warning(
            "Upload rate limit exceeded for user %s.",
            user.username,
        )
        response = JsonResponse(
            {"error": "Rate limit exceeded. Please try again later."},
            status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response

    uploaded_file = request.FILES.get("file")
    if getattr(request, "upload_too_large", False):
        logger.warning("Upload rejected: File exceeds the 10 MiB size limit.")
        return JsonResponse(
            {"error": "File exceeds the 10 MiB size limit."},
            status=413,
        )

    if uploaded_file is None:
        logger.warning("Upload rejected: No file provided.")
        return JsonResponse({"error": "No file provided."}, status=400)

    # Prevent directory traversal and normalize filename
    raw_name = uploaded_file.name or ""
    safe_original_name = Path(raw_name).name.replace("\\", "/").split("/")[-1]

    # Validate file extension
    ext = Path(safe_original_name).suffix.lower()
    if not ext or safe_original_name.startswith(".") or ext not in ALLOWED_EXTENSIONS:
        logger.warning("Upload rejected for file %s: Unsupported file format.", safe_original_name)
        return JsonResponse({"error": "Unsupported file format."}, status=400)

    # Check reported file size
    if uploaded_file.size > MAX_FILE_SIZE:
        logger.warning(
            "Upload rejected for file %s: File size exceeds 10 MiB limit (%s bytes).",
            safe_original_name,
            uploaded_file.size,
        )
        return JsonResponse(
            {"error": "File size exceeds 10 MiB limit."},
            status=413,
        )

    if uploaded_file.size == 0:
        logger.warning("Upload rejected for file %s: Empty files are not allowed.", safe_original_name)
        return JsonResponse({"error": "Empty files are not allowed."}, status=400)

    # Read uploaded bytes for content validation and hashing
    content = uploaded_file.read()

    if len(content) == 0:
        logger.warning("Upload rejected for file %s: Empty files are not allowed.", safe_original_name)
        return JsonResponse({"error": "Empty files are not allowed."}, status=400)

    if len(content) > MAX_FILE_SIZE:
        logger.warning(
            "Upload rejected for file %s: File size exceeds 10 MiB limit (%s bytes).",
            safe_original_name,
            len(content),
        )
        return JsonResponse(
            {"error": "File size exceeds 10 MiB limit."},
            status=413,
        )

    # Content validation
    if ext == ".pdf":
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            if doc.page_count == 0:
                logger.warning("Upload rejected for file %s: Invalid or corrupted PDF file.", safe_original_name)
                return JsonResponse(
                    {"error": "Invalid or corrupted PDF file."},
                    status=400,
                )
            doc.close()
        except Exception:
            logger.warning("Upload rejected for file %s: Invalid or corrupted PDF file.", safe_original_name)
            return JsonResponse(
                {"error": "Invalid or corrupted PDF file."},
                status=400,
            )

    elif ext in IMAGE_FORMAT_MAP:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(content))
            img.verify()
            actual_format = img.format
        except Exception:
            logger.warning("Upload rejected for file %s: Invalid or corrupted image file.", safe_original_name)
            return JsonResponse(
                {"error": "Invalid or corrupted image file."},
                status=400,
            )

        if actual_format != IMAGE_FORMAT_MAP[ext]:
            logger.warning("Upload rejected for file %s: File content and extension do not match.", safe_original_name)
            return JsonResponse(
                {"error": "File content and extension do not match."},
                status=400,
            )

    elif ext == ".csv":
        try:
            if b"\x00" in content:
                logger.warning("Upload rejected for file %s: Invalid CSV file.", safe_original_name)
                return JsonResponse({"error": "Invalid CSV file."}, status=400)
            text = content.decode("utf-8-sig")
            if not text.strip():
                logger.warning("Upload rejected for file %s: Empty files are not allowed.", safe_original_name)
                return JsonResponse(
                    {"error": "Empty files are not allowed."},
                    status=400,
                )
            reader = csv.reader(io.StringIO(text[:4096]))
            rows = list(reader)
            if not rows or not any(rows):
                logger.warning("Upload rejected for file %s: Invalid CSV file.", safe_original_name)
                return JsonResponse({"error": "Invalid CSV file."}, status=400)
        except Exception:
            logger.warning("Upload rejected for file %s: Invalid CSV file.", safe_original_name)
            return JsonResponse({"error": "Invalid CSV file."}, status=400)

    elif ext == ".xls":
        try:
            import xlrd

            wb = xlrd.open_workbook(file_contents=content)
            if wb.nsheets == 0:
                logger.warning("Upload rejected for file %s: Invalid or corrupted Excel file.", safe_original_name)
                return JsonResponse(
                    {"error": "Invalid or corrupted Excel file."},
                    status=400,
                )
        except Exception:
            logger.warning("Upload rejected for file %s: Invalid or corrupted Excel file.", safe_original_name)
            return JsonResponse(
                {"error": "Invalid or corrupted Excel file."},
                status=400,
            )

    elif ext == ".xlsx":
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
            wb.close()
        except (KeyError, Exception) as exc:
            logger.warning(
                "Upload rejected for file %s: Invalid or corrupted Excel file (%s).",
                safe_original_name,
                exc,
            )
            return JsonResponse(
                {"error": "Invalid or corrupted Excel file."},
                status=400,
            )

    # Ingest document via shared ingestion service
    try:
        job = ingest_document(
            uploaded_file=uploaded_file,
            original_filename=safe_original_name,
            owner=user,
            content=content,
        )
    except Exception as exc:
        logger.error(
            "Failed to store uploaded file %s: %s", safe_original_name, exc
        )
        return JsonResponse(
            {"error": "Unable to store the uploaded file."},
            status=500,
        )

    logger.info(
        "File upload accepted: original_name=%s, stored_filename=%s, size=%s, sha256=%s, job_id=%s, user=%s",
        job.file_name,
        job.stored_filename,
        job.file_size,
        job.sha256,
        job.id,
        user.username,
    )

    return JsonResponse(
        {
            "message": "File uploaded successfully.",
            "job_id": job.id,
            "status": job.status,
            "original_filename": job.file_name,
            "stored_filename": job.stored_filename,
            "size_bytes": job.file_size,
            "sha256": job.sha256,
        },
        status=201,
    )
