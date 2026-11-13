import csv
import hashlib
import io
import logging
from pathlib import Path
import uuid

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from app.security.django_adapter import (
    can_django_user_access_document,
    can_django_user_access_history,
    can_django_user_download_report,
    filter_user_processing_history,
    get_authorized_job_or_404,
)
from .api_auth import authenticate_api_request
from .models import ProcessingJob
from .reports import normalize_report_type, resolve_report_for_job
from .security import serve_secure_file
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

    # Access request.FILES to trigger upload handlers (such as LimitUploadSizeHandler)
    _ = request.FILES

    if getattr(request, "upload_too_large", False):
        logger.warning("Upload rejected: File exceeds the 10 MiB size limit.")
        return JsonResponse(
            {"error": "File exceeds the 10 MiB size limit."},
            status=413,
        )

    if "file" not in request.FILES:

        logger.warning("Upload rejected: No file provided.")
        return JsonResponse({"error": "No file provided."}, status=400)


    uploaded_file = request.FILES["file"]

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



@require_http_methods(["GET"])
def processing_history_api(request):
    """Processing history API: GET /api/jobs/ or /api/history/.

    Returns the authenticated user's processing history with optional status/file_type
    filtering and pagination. Multi-tenant isolated: never returns another user's jobs.
    """
    user, auth_error = authenticate_api_request(request)
    if auth_error is not None:
        return auth_error

    queryset = filter_user_processing_history(user)

    # Filtering by status
    status_filter = request.GET.get("status")
    if status_filter:
        normalized_status = status_filter.strip().lower()
        if normalized_status in ProcessingJob.Status.values:
            queryset = queryset.filter(status=normalized_status)

    # Filtering by file type
    file_type_filter = request.GET.get("file_type")
    if file_type_filter:
        clean_ext = file_type_filter.strip().lower().lstrip(".")
        queryset = queryset.filter(file_type=clean_ext)

    # Pagination
    total = queryset.count()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        page_size = min(100, max(1, int(request.GET.get("page_size", 20))))
    except (ValueError, TypeError):
        page_size = 20

    start = (page - 1) * page_size
    end = start + page_size
    page_jobs = queryset[start:end]

    results = []
    for job in page_jobs:
        results.append({
            "id": job.id,
            "file_name": job.file_name,
            "file_type": job.file_type,
            "file_size": job.file_size,
            "status": job.status,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "document_url": f"/job/{job.id}/document/",
            "result_url": f"/job/{job.id}/download/" if job.status == ProcessingJob.Status.COMPLETED else None,
            "reports": {
                "excel": f"/job/{job.id}/report/excel/",
                "pdf": f"/job/{job.id}/report/pdf/",
            } if job.status == ProcessingJob.Status.COMPLETED else None,
        })

    return JsonResponse({
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    })


@require_http_methods(["GET"])
def job_detail_api(request, job_id):
    """Processing job detail API: GET /api/jobs/<job_id>/.

    Multi-tenant isolated: returns 404 if the job does not exist or belongs to another user.
    """
    user, auth_error = authenticate_api_request(request)
    if auth_error is not None:
        return auth_error

    try:
        job = get_authorized_job_or_404(user, job_id)
    except Http404:
        return JsonResponse({"error": "Job not found."}, status=404)

    if not can_django_user_access_history(user, job):
        return JsonResponse({"error": "Job not found."}, status=404)

    data = {
        "id": job.id,
        "file_name": job.file_name,
        "file_type": job.file_type,
        "file_size": job.file_size,
        "status": job.status,
        "error_message": job.error_message if job.status == ProcessingJob.Status.FAILED else "",
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "document_url": f"/job/{job.id}/document/",
        "result_url": f"/job/{job.id}/download/" if job.status == ProcessingJob.Status.COMPLETED else None,
        "reports": {
            "excel": f"/job/{job.id}/report/excel/",
            "pdf": f"/job/{job.id}/report/pdf/",
        } if job.status == ProcessingJob.Status.COMPLETED else None,
    }
    return JsonResponse(data)


@require_http_methods(["GET"])
def download_document_api(request, job_id):
    """Source document download API: GET /api/jobs/<job_id>/document/.

    Multi-tenant isolated and path-traversal protected.
    """
    user, auth_error = authenticate_api_request(request)
    if auth_error is not None:
        return auth_error

    try:
        job = get_authorized_job_or_404(user, job_id)
    except Http404:
        return JsonResponse({"error": "Document not found."}, status=404)

    if not can_django_user_access_document(user, job):
        return JsonResponse({"error": "Document not found."}, status=404)

    if not job.storage_reference:
        return JsonResponse({"error": "Document not found."}, status=404)

    try:
        return serve_secure_file(
            file_path=job.storage_reference,
            download_filename=job.file_name,
        )
    except Http404:
        return JsonResponse({"error": "Document not found."}, status=404)


@require_http_methods(["GET"])
def download_report_api(request, job_id, report_type):
    """Report download API: GET /api/jobs/<job_id>/report/<report_type>/.

    Supports report_type in ('excel', 'pdf', 'xlsx').
    Multi-tenant isolated and path-traversal protected.
    """
    user, auth_error = authenticate_api_request(request)
    if auth_error is not None:
        return auth_error

    try:
        job = get_authorized_job_or_404(user, job_id)
    except Http404:
        return JsonResponse({"error": "Report not found."}, status=404)

    if not can_django_user_download_report(user, job):
        return JsonResponse({"error": "Report not found."}, status=404)

    canonical = normalize_report_type(report_type)
    if canonical is None:
        return JsonResponse({"error": f"Invalid report type '{report_type}'."}, status=400)

    try:
        file_path, download_filename, content_type = resolve_report_for_job(job, canonical)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if file_path is None:
        return JsonResponse({"error": "Report has not been generated yet."}, status=404)

    try:
        return serve_secure_file(
            file_path=file_path,
            download_filename=download_filename,
            content_type=content_type,
        )
    except Http404:
        return JsonResponse({"error": "Report not found."}, status=404)
