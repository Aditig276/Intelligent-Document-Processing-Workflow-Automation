
import csv
import json
import logging
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from app.report_generators.excel_generator import generate_excel_report
from app.report_generators.document_excel_generator import generate_document_excel_report
from app.report_generators.pdf_generator import generate_pdf_report
from app.security.django_adapter import (
    can_django_user_access_document,
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


logger = logging.getLogger("processing_jobs")
auth_logger = logging.getLogger("processing_jobs.auth")


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


def safe_log(log_fn, *args, **kwargs):
    """Safely log without allowing logging failures to break a request."""
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


# ============================================================
# DOCUMENT UPLOAD
# ============================================================

@login_required
def upload_document(request):

    if request.method == "POST":

        if not can_django_user_upload(request.user):
            safe_log(
                auth_logger.warning,
                "Unauthorized upload attempt by user '%s'.",
                request.user.username,
            )

            return render(
                request,
                "processing_jobs/upload.html",
                {
                    "error": "You do not have permission to upload documents."
                },
                status=403,
            )

        # Rate limiting
        is_limited, retry_after = check_rate_limit(
            request,
            request.user,
        )

        if is_limited:
            messages.error(
                request,
                "Rate limit exceeded. Please try again later.",
            )

            response = render(
                request,
                "processing_jobs/upload.html",
                {
                    "error": "Rate limit exceeded. Please try again later."
                },
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
                "Unsupported file type rejected. File=%s, User=%s",
                safe_name,
                request.user.username,
            )
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Unsupported file type."},
            )

        if uploaded_file.size == 0:
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Empty files are not allowed."},
            )

        if uploaded_file.size > MAX_FILE_SIZE:
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "File size must not exceed 10 MB."},
                status=400,
            )

        try:
            job = ingest_document(
                uploaded_file=uploaded_file,
                original_filename=safe_name,
                owner=request.user,
            )

        except Exception:
            safe_log(
                logger.exception,
                "Browser upload failed for document %s. User=%s",
                safe_name,
                request.user.username,
            )

            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Unable to store the uploaded file."},
                status=500,
            )

        safe_log(
            logger.info,
            "Document uploaded: job_id=%s, file_name=%s, size=%s, user=%s",
            job.id,
            job.file_name,
            job.file_size,
            request.user.username,
        )

        messages.success(
            request,
            "Document uploaded successfully.",
        )

        return redirect("processing_jobs:dashboard")

    return render(request, "processing_jobs/upload.html")


# ============================================================
# DASHBOARD AND PROCESSING HISTORY
# ============================================================

@login_required
@require_GET
def dashboard(request):

    safe_log(
        logger.debug,
        "Dashboard accessed by user %s",
        request.user.username,
    )

    # Only show jobs the current user is authorized to access.
    all_jobs = filter_user_processing_history(request.user)

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

    # Search and status filters
    search = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip().lower()

    jobs = all_jobs

    if search:
        jobs = jobs.filter(
            file_name__icontains=search
        )

    valid_statuses = [
        status.value for status in ProcessingJob.Status
    ]

    if status_filter in valid_statuses:
        jobs = jobs.filter(
            status=status_filter
        )

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


# ============================================================
# DOCUMENT EXTRACTION
# ============================================================

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

    # Authorization check
    if not can_django_user_access_job(request.user, job):

        safe_log(
            auth_logger.warning,
            "Unauthorized extraction attempt by user %s for job %s",
            request.user.username,
            job.id,
        )

        raise Http404("Job not found.")

    if job.status == ProcessingJob.Status.COMPLETED:

        messages.info(
            request,
            "This job has already been completed.",
        )

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

        # Validate uploaded document path
        file_path = validate_media_path(
            job.storage_reference,
            must_exist=True,
            expect_file=True,
        )

        file_data = file_path.read_bytes()

        # Extract document information
        result = extract_document(
            file_data,
            job.file_name,
        )

        # Validate output location
        result_path = get_validated_extracted_result_path(
            job.id,
            must_exist=False,
            create_dir=True,
        )

        # Save extracted JSON
        result_path.write_text(
            json.dumps(
                result,
                indent=4,
                default=str,
            ),
            encoding="utf-8",
        )

        job.extracted_data = result
        job.status = ProcessingJob.Status.COMPLETED
        job.error_message = ""
        job.save()

        safe_log(
            logger.info,
            "Job %s extraction completed.",
            job.id,
        )

        messages.success(
            request,
            "Document extraction completed.",
        )

    except Exception as error:

        job.status = ProcessingJob.Status.FAILED
        clean_msg = sanitize_error_message(error)
        job.error_message = clean_msg[:2000]
        job.save()

        safe_log(
            logger.exception,
            "Job %s extraction failed: %s",
            job.id,
            error,
            exc_info=True,
        )

        messages.error(
            request,
            f"Extraction failed: {clean_msg}",
        )

    return redirect(
        "processing_jobs:job_detail",
        job_id=job.id,
    )


# ============================================================
# JOB DETAILS
# ============================================================

@login_required
def job_detail(request, job_id):

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        raise Http404("Job not found.")

    if not can_django_user_access_job(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized detail access attempt by user %s for job %s owned by %s",
            request.user.username,
            job.id,
            job.owner.username if job.owner else "unowned",
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
                "Extraction result missing for job %s.",
                job.id,
            )

        else:

            try:
                result = json.loads(
                    result_path.read_text(
                        encoding="utf-8"
                    )
                )

            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
            ):

                result_error = (
                    "Could not read the saved extraction result."
                )

                safe_log(
                    logger.exception,
                    "Failed to read extraction result for job %s.",
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


# ============================================================
# DOWNLOAD EXTRACTED JSON RESULT
# ============================================================

@login_required
def download_result(request, job_id):

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        raise Http404(
            "Extraction result was not found."
        )

    if not can_django_user_access_job(request.user, job):
        safe_log(
            auth_logger.warning,
            "Unauthorized download attempt by user %s for job %s owned by %s",
            request.user.username,
            job.id,
            job.owner.username if job.owner else "unowned",
        )
        raise Http404(
            "Extraction result was not found."
        )

    # If the job is still pending, perform extraction on demand.
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

                target_result_path = (
                    get_validated_extracted_result_path(
                        job.id,
                        must_exist=False,
                        create_dir=True,
                    )
                )

                file_data = file_path.read_bytes()

                result = extract_document(
                    file_data,
                    job.file_name,
                )

                serialized = json.dumps(
                    result,
                    indent=4,
                    default=str,
                )

                target_result_path.write_text(
                    serialized,
                    encoding="utf-8",
                )

                job.extracted_data = result
                job.status = ProcessingJob.Status.COMPLETED
                job.error_message = ""
                job.save()

                extracted = True

            except Exception as error:
                job.status = ProcessingJob.Status.FAILED
                job.error_message = (
                    "Document extraction failed. "
                    "Please verify the file and try again."
                )
                job.save()

                safe_log(
                    logger.exception,
                    "On-demand extraction failed for job %s.",
                    job.id,
                    error,
                    exc_info=True,
                )

                raise Http404(
                    "Extraction result is not available."
                )


        if not extracted:

            safe_log(
                logger.warning,
                "Download rejected for incomplete job %s.",
                job.id,
            )

            raise Http404(
                "Extraction result is not available."
            )

    # Validate saved result path
    try:
        result_path = get_validated_extracted_result_path(
            job.id,
            must_exist=True,
        )

    except InvalidMediaPathError:

        raise Http404(
            "Extraction result was not found."
        )

    # Read and validate JSON
    try:
        content = result_path.read_text(
            encoding="utf-8"
        )

        json.loads(content)

    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ):

        safe_log(
            logger.exception,
            "Unreadable extraction result for job %s.",
            job.id,
        )

        raise Http404(
            "Extraction result is unreadable."
        )

    safe_log(
        logger.info,
        "Extraction result downloaded: job_id=%s, user=%s, filename=%s",
        job.id,
        request.user.username,
        job.file_name,
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


# ============================================================
# BACKWARD-COMPATIBLE VIEW ALIASES
# ============================================================

job_dashboard = dashboard
view_extracted_data = job_detail
download_extraction_json = download_result


# ============================================================
# EXCEL REPORT GENERATION
# ============================================================

@login_required
def download_excel_report(request, job_id):

    try:
        job = ProcessingJob.objects.get(id=job_id)

    except ProcessingJob.DoesNotExist:
        raise Http404(
            "Processing job was not found."
        )

    if not can_django_user_access_job(request.user, job):
        raise Http404(
            "Processing job was not found."
        )

    if (
        not isinstance(job.reviewed_data, dict)
        or not job.reviewed_data
    ):

        raise Http404(
            "Reviewed data is not available for this report."
        )

    try:

        excel_file = generate_excel_report(
            reviewed_data=job.reviewed_data,
            job_id=job.id,
            original_file_name=job.file_name,
            processing_status=job.status,
            created_at=job.created_at,
            generated_at=timezone.now(),
        )

        response = HttpResponse(
            excel_file.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response["Content-Disposition"] = (
            f'attachment; filename="job_{job.id}_report.xlsx"'
        )

        return response

    except Exception:

        safe_log(
            logger.exception,
            "Excel report generation failed for job %s.",
            job.id,
        )

        raise Http404(
            "Unable to generate the Excel report."
        )


# ============================================================
# DOWNLOAD ORIGINAL DOCUMENT
# ============================================================

@login_required
@require_GET
def download_document(request, job_id):

    job = get_authorized_job_or_404(
        request.user,
        job_id,
    )

    if not can_django_user_access_document(
        request.user,
        job,
    ):
        raise Http404(
            "Document was not found."
        )

    if not job.storage_reference:
        raise Http404(
            "Document was not found."
        )

    return serve_secure_file(
        file_path=job.storage_reference,
        download_filename=job.file_name,
    )


# ============================================================
# DOWNLOAD GENERATED REPORT
# ============================================================

@login_required
@require_GET
def download_report(request, job_id, report_type):

    job = get_authorized_job_or_404(
        request.user,
        job_id,
    )

    if not can_django_user_download_report(
        request.user,
        job,
    ):
        raise Http404("Report not found.")

    canonical = normalize_report_type(report_type)

    if canonical is None:
        raise Http404("Report not found.")

    # Generate PDF report directly from the stored extraction.
    if canonical == "pdf":

        if job.status != ProcessingJob.Status.COMPLETED:
            raise Http404("Document processing is not completed.")

        if not isinstance(job.extracted_data, dict):
            raise Http404("Extracted document data is unavailable.")

        try:
            pdf_file = generate_pdf_report(
                extracted_data=job.extracted_data,
                job_id=job.id,
                original_file_name=job.file_name,
                processing_status=job.status,
                created_at=job.created_at,
                reviewed_data=job.reviewed_data,
            )

        except (ValueError, TypeError):
            logger.exception(
                "PDF report generation failed for job %s",
                job.id,
            )
            raise Http404("PDF report could not be generated.")

        response = HttpResponse(
            pdf_file.getvalue(),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="job_{job.id}_report.pdf"'
        )
        return response

    # Generate Excel reports for invoices and general documents.
    if canonical == "excel":

        if job.status != ProcessingJob.Status.COMPLETED:
            raise Http404("Document processing is not completed.")

        try:
            if (
                isinstance(job.reviewed_data, dict)
                and job.reviewed_data
            ):
                # Preserve the existing invoice Excel format.
                excel_file = generate_excel_report(
                    reviewed_data=job.reviewed_data,
                    job_id=job.id,
                    original_file_name=job.file_name,
                    processing_status=job.status,
                    created_at=job.created_at,
                    generated_at=timezone.now(),
                )

            else:
                # Generate a general-purpose document Excel report.
                if not isinstance(job.extracted_data, dict):
                    raise Http404(
                        "Extracted document data is unavailable."
                    )

                excel_file = generate_document_excel_report(
                    extracted_data=job.extracted_data,
                    job_id=job.id,
                    original_file_name=job.file_name,
                    processing_status=job.status,
                    created_at=job.created_at,
                    reviewed_data=job.reviewed_data,
                    generated_at=timezone.now(),
                )

            response = HttpResponse(
                excel_file.getvalue(),
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )

            response["Content-Disposition"] = (
                f'attachment; filename="job_{job.id}_report.xlsx"'
            )

            return response

        except Http404:
            raise

        except Exception:
            logger.exception(
                "Excel report generation failed for job %s.",
                job.id,
            )
            raise Http404(
                "Unable to generate the Excel report."
            )

    # Preserve the existing resolver for other report types.
    try:
        file_path, download_filename, content_type = (
            resolve_report_for_job(job, canonical)
        )


    except ValueError:
        raise Http404("Report not found.")

    if file_path is None:
        raise Http404("Report has not been generated yet.")

    return serve_secure_file(
        file_path=file_path,
        download_filename=download_filename,
        content_type=content_type,
    )

# ============================================================
# ADDITIONAL BACKWARD-COMPATIBLE ALIASES
# ============================================================

download_source_document = download_document
download_report_alias = download_report
