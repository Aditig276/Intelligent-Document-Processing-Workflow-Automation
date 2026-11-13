
import csv
import json
import logging
from pathlib import Path
import zipfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from app.security.django_adapter import (
    can_django_user_access_document,
    can_django_user_access_history,
    can_django_user_access_job,
    can_django_user_download_report,
    can_django_user_upload,
    filter_user_processing_history,
    get_authorized_job_or_404,
)

from .extractors import extract_document
from .models import ProcessingJob
from .reports import normalize_report_type, resolve_report_for_job
from .security import (
    InvalidMediaPathError,
    get_validated_extracted_result_path,
    sanitize_error_message,
    serve_secure_file,
    validate_media_path,
)
from .services import check_rate_limit, ingest_document


EXTRACTION_EXCEPTIONS = (
    OSError,
    ValueError,
    RuntimeError,
    UnicodeError,
    LookupError,
    EOFError,
    csv.Error,
    zipfile.BadZipFile,
    json.JSONDecodeError,
)


logger = logging.getLogger("processing_jobs")
auth_logger = logging.getLogger("processing_jobs.auth")


def safe_log(log_fn, *args, **kwargs):
    """Safely log without raising exceptions if logging fails."""
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
}

MAX_FILE_SIZE = 10 * 1024 * 1024


@login_required
def upload_document(request):
    if request.method == "POST":

        if not can_django_user_upload(request.user):
            safe_log(
                auth_logger.warning,
                "Unauthorized upload attempt by user '%s'.",
                request.user.username if request.user else "Anonymous",
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "You do not have permission to upload documents."},
            )

        # Upload rate limiting
        is_limited, retry_after = check_rate_limit(request, request.user)

        if is_limited:
            messages.error(
                request,
                "Rate limit exceeded. Please try again later."
            )

            response = render(
                request,
                "processing_jobs/upload.html",
                {"error": "Rate limit exceeded. Please try again later."},
                status=429,
            )

            response["Retry-After"] = str(retry_after)
            return response

        uploaded_file = request.FILES.get("file")

        # Check if file upload was rejected early by LimitUploadSizeHandler
        if getattr(request, "upload_too_large", False):
            safe_log(
                logger.warning,
                "Browser upload rejected: File exceeds the 10 MB size limit. User=%s",
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "File size must not exceed 10 MB."},
            )

        if not uploaded_file:
            safe_log(
                logger.warning,
                "Browser upload rejected: No file provided. User=%s",
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Please select a file to upload."},
            )

        safe_name = Path(uploaded_file.name).name
        extension = Path(safe_name).suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            safe_log(
                logger.warning,
                "Browser upload rejected for file %s: Unsupported file type. User=%s",
                safe_name,
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Unsupported file type."},
            )

        if uploaded_file.size == 0:
            safe_log(
                logger.warning,
                "Browser upload rejected for file %s: Empty files are not allowed. User=%s",
                safe_name,
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Empty files are not allowed."},
            )

        if uploaded_file.size > MAX_FILE_SIZE:
            safe_log(
                logger.warning,
                "Browser upload rejected for file %s: File size exceeds 10 MB. User=%s",
                safe_name,
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "File size must not exceed 10 MB."},
            )

        # Ingest document via shared ingestion service
        try:
            job = ingest_document(
                uploaded_file=uploaded_file,
                original_filename=safe_name,
                owner=request.user,
            )

        except Exception as exc:
            safe_log(
                logger.error,
                "Browser upload failed to ingest document %s: %s",
                safe_name,
                exc,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Unable to store the uploaded file."},
                status=500,
            )

        safe_log(
            logger.info,
            "Browser document uploaded: job_id=%s, file_name=%s, size=%s, user=%s",
            job.id,
            job.file_name,
            job.file_size,
            request.user.username,
        )

        messages.success(request, "Document uploaded successfully.")
        return redirect("processing_jobs:dashboard")

    return render(request, "processing_jobs/upload.html")


@login_required
@require_GET
def dashboard(request):
    safe_log(
        logger.debug,
        "Dashboard accessed by user %s",
        request.user.username,
    )

    # Get only jobs the logged-in user is authorized to access.
    all_jobs = filter_user_processing_history(request.user)

    # Calculate dashboard counts using authorized jobs only.
    total_jobs = all_jobs.count()

    completed_jobs = all_jobs.filter(
        status=ProcessingJob.Status.COMPLETED
    ).count()

    pending_jobs = all_jobs.filter(
        status=ProcessingJob.Status.PENDING
    ).count()

    processing_count = all_jobs.filter(
        status=ProcessingJob.Status.PROCESSING
    ).count()

    failed_jobs = all_jobs.filter(
        status=ProcessingJob.Status.FAILED
    ).count()

    # Read search and status filters.
    search = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip().lower()

    # Apply filters only to authorized jobs.
    jobs = all_jobs

    if search:
        jobs = jobs.filter(file_name__icontains=search)

    valid_statuses = [
        status.value for status in ProcessingJob.Status
    ]

    if status_filter in valid_statuses:
        jobs = jobs.filter(status=status_filter)

    # Prepare dashboard context.
    context = {
        "jobs": jobs.order_by("-created_at")[:100],
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "pending_jobs": pending_jobs,
        "processing_jobs": processing_count,
        "failed_jobs": failed_jobs,
        "search": search,
        "status_filter": status_filter,
    }

    return render(
        request,
        "processing_jobs/dashboard.html",
        context,
    )


@login_required
def extract_job(request, job_id):

    if request.method == "GET":
        return job_detail(request, job_id)

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        safe_log(
            logger.warning,
            "Job %s not found for extraction. User=%s",
            job_id,
            request.user.username,
        )
        raise Http404("Job not found.")

    if not can_django_user_access_job(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized access attempt: User '%s' attempted to extract job %s owned by '%s'.",
            request.user.username,
            job.id,
            job.owner.username if job.owner else "None",
        )
        raise Http404("Job not found.")

    if job.status == ProcessingJob.Status.COMPLETED:
        safe_log(
            logger.info,
            "Job %s already completed. Skipping extraction. User=%s",
            job.id,
            request.user.username,
        )

        messages.info(request, "This job has already been completed.")

        return redirect(
            "processing_jobs:job_detail",
            job_id=job.id,
        )

    job.status = ProcessingJob.Status.PROCESSING
    job.error_message = ""
    job.save()

    safe_log(
        logger.info,
        "Job %s status changed to processing.",
        job.id,
    )

    try:
        file_path = validate_media_path(
            job.storage_reference,
            must_exist=True,
            expect_file=True,
        )

        file_data = file_path.read_bytes()

        result = extract_document(file_data, job.file_name)

        result_path = get_validated_extracted_result_path(
            job.id,
            must_exist=False,
            create_dir=True,
        )

        result_path.write_text(
            json.dumps(result, indent=4, default=str),
            encoding="utf-8",
        )

        job.status = ProcessingJob.Status.COMPLETED
        job.error_message = ""
        job.save()

        safe_log(
            logger.info,
            "Job %s status changed to completed. Extracted document %s.",
            job.id,
            job.file_name,
        )

        messages.success(
            request,
            "Document extraction completed."
        )

    except Exception as error:
        job.status = ProcessingJob.Status.FAILED
        clean_msg = sanitize_error_message(error)
        job.error_message = clean_msg[:2000]
        job.save()

        safe_log(
            logger.error,
            "Job %s failed: %s",
            job.id,
            error,
            exc_info=True,
        )

        messages.error(
            request,
            f"Extraction failed: {clean_msg}"
        )

    return redirect(
        "processing_jobs:job_detail",
        job_id=job.id,
    )


@login_required
def job_detail(request, job_id):

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        safe_log(
            logger.warning,
            "Job %s not found. User=%s",
            job_id,
            request.user.username,
        )
        raise Http404("Job not found.")

    if not can_django_user_access_job(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized access attempt: User '%s' attempted to view job %s owned by '%s'.",
            request.user.username,
            job.id,
            job.owner.username if job.owner else "None",
        )
        raise Http404("Job not found.")

    result = None
    result_error = None

    if job.status == ProcessingJob.Status.COMPLETED:
        try:
            result_path = get_validated_extracted_result_path(
                job.id,
                must_exist=True,
            )
        except InvalidMediaPathError:
            result_error = (
                "Saved extraction result was not found."
            )

            safe_log(
                logger.error,
                "Extraction result file missing or invalid for completed job %s.",
                job.id,
            )
        else:
            try:
                result = json.loads(
                    result_path.read_text(encoding="utf-8")
                )

            except (OSError, UnicodeError, json.JSONDecodeError):
                result_error = (
                    "Could not read the saved extraction result."
                )

                safe_log(
                    logger.error,
                    "Failed to decode extraction result for job %s.",
                    job.id,
                )

    safe_log(
        logger.debug,
        "Job %s viewed by user %s",
        job.id,
        request.user.username,
    )

    return render(
        request,
        "processing_jobs/job_detail.html",
        {
            "job": job,
            "result": result,
            "result_error": result_error,
        },
    )


@login_required
def download_result(request, job_id):

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        safe_log(
            logger.warning,
            "Job %s not found for download. User=%s",
            job_id,
            request.user.username,
        )
        raise Http404("Extraction result was not found.")

    if not can_django_user_access_job(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized access attempt: User '%s' attempted to download result for job %s owned by '%s'.",
            request.user.username,
            job.id,
            job.owner.username if job.owner else "None",
        )
        raise Http404("Extraction result was not found.")

    if job.status != ProcessingJob.Status.COMPLETED:

        extracted = False

        if (
            job.storage_reference
            and job.status == ProcessingJob.Status.PENDING
        ):
            try:
                file_path = validate_media_path(
                    job.storage_reference,
                    must_exist=True,
                    expect_file=True,
                )
            except InvalidMediaPathError as exc:
                safe_log(
                    auth_logger.warning,
                    "Rejected invalid source document path for job %s: %s",
                    job.id,
                    exc,
                )
                raise Http404(
                    "Extraction result is not available."
                )

            try:
                target_result_path = get_validated_extracted_result_path(
                    job.id,
                    must_exist=False,
                    create_dir=True,
                )
            except InvalidMediaPathError as exc:
                safe_log(
                    auth_logger.warning,
                    "Rejected invalid extracted result path for job %s: %s",
                    job.id,
                    exc,
                )
                raise Http404(
                    "Extraction result is not available."
                )

            try:
                file_data = file_path.read_bytes()

                result = extract_document(
                    file_data,
                    job.file_name,
                )

                serialized = json.dumps(result, indent=4, default=str)

                target_result_path.write_text(
                    serialized,
                    encoding="utf-8",
                )
            except Exception as error:
                job.status = ProcessingJob.Status.FAILED
                job.error_message = "Document extraction failed. Please verify the file and try again."
                job.save()

                safe_log(
                    logger.error,
                    "On-demand extraction failed during download for job %s: %s",
                    job.id,
                    error,
                    exc_info=True,
                )

                raise Http404(
                    "Extraction result is not available."
                )

            job.status = ProcessingJob.Status.COMPLETED
            job.error_message = ""
            job.save()

            extracted = True

        if not extracted:
            safe_log(
                logger.warning,
                "Download rejected for incomplete job %s (status=%s). User=%s",
                job.id,
                job.status,
                request.user.username,
            )

            raise Http404(
                "Extraction result is not available."
            )

    try:
        result_path = get_validated_extracted_result_path(
            job.id,
            must_exist=True,
        )
    except InvalidMediaPathError:
        safe_log(
            logger.error,
            "Download failed for job %s: result file not found or invalid. User=%s",
            job.id,
            request.user.username,
        )

        raise Http404(
            "Extraction result was not found."
        )

    try:
        content = result_path.read_text(encoding="utf-8")
        json.loads(content)

    except (OSError, UnicodeError, json.JSONDecodeError):
        safe_log(
            logger.error,
            "Download failed for job %s: result file is unreadable. User=%s",
            job.id,
            request.user.username,
        )

        raise Http404(
            "Extraction result is unreadable."
        )

    safe_log(
        logger.info,
        "Document extraction result downloaded: job_id=%s, file_name=%s, user=%s",
        job.id,
        job.file_name,
        request.user.username,
    )

    response = HttpResponse(
        content,
        content_type="application/json",
    )

    response["Content-Disposition"] = (
        f'attachment; filename="job_{job.id}_extraction.json"'
    )
    response["X-Content-Type-Options"] = "nosniff"

    return response


# Backward-compatible view aliases for Bhanu's implementation

job_dashboard = dashboard
view_extracted_data = job_detail
download_extraction_json = download_result


@login_required
@require_GET
def download_document(request, job_id):
    """Download the original uploaded source document for an owned processing job."""
    job = get_authorized_job_or_404(request.user, job_id)

    if not can_django_user_access_document(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized source document download attempt: User '%s' requested job %s.",
            request.user.username,
            job_id,
        )
        raise Http404("Document was not found.")

    if not job.storage_reference:
        safe_log(
            logger.warning,
            "Source document missing storage reference for job %s.",
            job.id,
        )
        raise Http404("Document was not found.")

    safe_log(
        logger.info,
        "Source document download initiated: job_id=%s, file_name=%s, user=%s",
        job.id,
        job.file_name,
        request.user.username,
    )

    return serve_secure_file(
        file_path=job.storage_reference,
        download_filename=job.file_name,
    )


@login_required
@require_GET
def download_report(request, job_id, report_type):
    """Download a generated Excel or PDF report for an owned processing job."""
    job = get_authorized_job_or_404(request.user, job_id)

    if not can_django_user_download_report(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized report download attempt: User '%s' requested job %s report '%s'.",
            request.user.username,
            job_id,
            report_type,
        )
        raise Http404("Report not found.")

    canonical = normalize_report_type(report_type)

    if canonical is None:
        safe_log(
            logger.warning,
            "Invalid report type '%s' requested for job %s.",
            report_type,
            job_id,
        )
        raise Http404("Report not found.")

    try:
        file_path, download_filename, content_type = resolve_report_for_job(
            job,
            canonical,
        )
    except ValueError:
        raise Http404("Report not found.")

    if file_path is None:
        safe_log(
            logger.info,
            "Report of type '%s' for job %s has not been generated or file is missing.",
            canonical,
            job.id,
        )
        raise Http404("Report has not been generated yet.")

    safe_log(
        logger.info,
        "Report download initiated: job_id=%s, type=%s, user=%s",
        job.id,
        canonical,
        request.user.username,
    )

    return serve_secure_file(
        file_path=file_path,
        download_filename=download_filename,
        content_type=content_type,
    )


# Additional aliases for views

download_source_document = download_document
download_report_alias = download_report
