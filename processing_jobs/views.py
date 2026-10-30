
import json
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import (
    Http404,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .extractors import extract_document
from .models import ProcessingJob


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


def upload_document(request):
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")

        if not uploaded_file:
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Please select a file to upload."},
            )

        extension = Path(uploaded_file.name).suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "Unsupported file type."},
            )

        if uploaded_file.size > MAX_FILE_SIZE:
            return render(
                request,
                "processing_jobs/upload.html",
                {"error": "File size must not exceed 10 MB."},
            )

        upload_dir = Path(settings.MEDIA_ROOT) / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(uploaded_file.name).name
        file_path = upload_dir / safe_name

        counter = 1
        while file_path.exists():
            file_path = upload_dir / (
                f"{Path(safe_name).stem}_{counter}{extension}"
            )
            counter += 1

        with file_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        job = ProcessingJob.objects.create(
            file_name=uploaded_file.name,
            file_type=extension.lstrip("."),
            file_size=uploaded_file.size,
            storage_reference=str(file_path.relative_to(settings.MEDIA_ROOT)),
            status=ProcessingJob.Status.PENDING,
        )

        messages.success(request, "Document uploaded successfully.")
        return redirect("job_detail", job_id=job.id)

    return render(request, "processing_jobs/upload.html")


def dashboard(request):
    jobs = ProcessingJob.objects.all()[:100]

    return render(
        request,
        "processing_jobs/dashboard.html",
        {"jobs": jobs},
    )


@require_POST
def extract_job(request, job_id):
    job = get_object_or_404(ProcessingJob, id=job_id)

    if job.status == ProcessingJob.Status.COMPLETED:
        messages.info(request, "This job has already been completed.")
        return redirect("job_detail", job_id=job.id)

    job.status = ProcessingJob.Status.PROCESSING
    job.error_message = ""
    job.save()

    try:
        file_path = Path(job.storage_reference)

        if not file_path.is_absolute():
            file_path = Path(settings.MEDIA_ROOT) / file_path

        if not file_path.exists():
            raise FileNotFoundError("Stored document was not found.")

        file_data = file_path.read_bytes()

        result = extract_document(file_data, job.file_name)

        result_dir = Path(settings.MEDIA_ROOT) / "extracted"
        result_dir.mkdir(parents=True, exist_ok=True)

        result_path = result_dir / f"job_{job.id}.json"

        result_path.write_text(
            json.dumps(result, indent=4, default=str),
            encoding="utf-8",
        )

        job.status = ProcessingJob.Status.COMPLETED
        job.error_message = ""
        job.save()

        messages.success(request, "Document extraction completed.")

    except Exception as error:
        job.status = ProcessingJob.Status.FAILED
        job.error_message = str(error)[:2000]
        job.save()

        messages.error(request, f"Extraction failed: {error}")

    return redirect("job_detail", job_id=job.id)


def job_detail(request, job_id):
    job = get_object_or_404(ProcessingJob, id=job_id)

    result = None
    result_error = None

    if job.status == ProcessingJob.Status.PENDING:
        job.status = ProcessingJob.Status.PROCESSING
        job.save()

    if job.status == ProcessingJob.Status.COMPLETED:
        result_path = (
            Path(settings.MEDIA_ROOT)
            / "extracted"
            / f"job_{job.id}.json"
        )

        if result_path.exists():
            try:
                result = json.loads(
                    result_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                result_error = "Could not read the saved extraction result."
        else:
            result_error = "Saved extraction result was not found."

    return render(
        request,
        "processing_jobs/job_detail.html",
        {
            "job": job,
            "result": result,
            "result_error": result_error,
        },
    )


def download_result(request, job_id):
    job = get_object_or_404(ProcessingJob, id=job_id)

    if job.status != ProcessingJob.Status.COMPLETED:
        raise Http404("Extraction result is not available.")

    result_path = (
        Path(settings.MEDIA_ROOT)
        / "extracted"
        / f"job_{job.id}.json"
    )

    if not result_path.exists():
        raise Http404("Extraction result was not found.")

    try:
        content = result_path.read_text(encoding="utf-8")
        json.loads(content)
    except (OSError, json.JSONDecodeError):
        raise Http404("Extraction result is unreadable.")

    response = HttpResponse(
        content,
        content_type="application/json",
    )

    response["Content-Disposition"] = (
        f'attachment; filename="job_{job.id}_extraction.json"'
    )

    return response

