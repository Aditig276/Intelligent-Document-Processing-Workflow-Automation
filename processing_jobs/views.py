
import json

from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_GET

import json
from django.http import Http404
from django.core.files.storage import default_storage
from django.shortcuts import render, get_object_or_404


from .forms import DocumentUploadForm
from .models import ProcessingJob
from .extractors import extract_document


@require_http_methods(["GET", "POST"])
def upload_document(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            saved_path = default_storage.save(
                f"uploads/{uploaded_file.name}",
                uploaded_file,
            )

            job = ProcessingJob.objects.create(
                file_name=uploaded_file.name,
                file_type=uploaded_file.name.rsplit(".", 1)[-1].lower(),
                file_size=uploaded_file.size,
                storage_reference=saved_path,
                status=ProcessingJob.Status.PENDING,
            )

            return redirect("processing_jobs:dashboard")
    else:
        form = DocumentUploadForm()

    return render(
        request,
        "processing_jobs/upload.html",
        {"form": form},
    )
@require_GET
def job_dashboard(request):
    jobs = ProcessingJob.objects.all()[:100]

    return render(
        request,
        "processing_jobs/dashboard.html",
        {"jobs": jobs},
    )


def extract_job(request, job_id):
    job = get_object_or_404(ProcessingJob, pk=job_id)

    if request.method == "POST":
        if job.status == ProcessingJob.Status.COMPLETED:
            return redirect(
                "processing_jobs:view_extracted_data",
                job_id=job.id,
            )

        try:
            job.status = ProcessingJob.Status.PROCESSING
            job.error_message = ""
            job.save()

            with default_storage.open(
                job.storage_reference, "rb"
            ) as stored_file:
                file_bytes = stored_file.read()

            result = extract_document(file_bytes, job.file_name)

            result_path = f"extracted/job_{job.id}.json"

            # Replace an old result, if one exists.
            if default_storage.exists(result_path):
                default_storage.delete(result_path)

            import io

            result_bytes = json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            ).encode("utf-8")

            default_storage.save(
                result_path,
                io.BytesIO(result_bytes),
            )

            job.status = ProcessingJob.Status.COMPLETED
            job.save()

            return redirect(
                "processing_jobs:view_extracted_data",
                job_id=job.id,
            )

        except Exception as exc:
            job.status = ProcessingJob.Status.FAILED
            job.error_message = str(exc)[:2000]
            job.save()

            return render(
                request,
                "processing_jobs/results.html",
                {
                    "job": job,
                    "result": None,
                    "error": "Extraction failed: " + job.error_message,
                },
            )

    # GET: open the results page without extracting.
    if job.status == ProcessingJob.Status.PENDING:
        job.status = ProcessingJob.Status.PROCESSING
        job.save()

    result = None
    error = None

    if job.status == ProcessingJob.Status.COMPLETED:
        result_path = f"extracted/job_{job.id}.json"

        if default_storage.exists(result_path):
            with default_storage.open(result_path, "r") as result_file:
                result = json.load(result_file)
        else:
            error = "The saved extraction result was not found."

    elif job.status == ProcessingJob.Status.FAILED:
        error = "Previous extraction failed: " + job.error_message

    return render(
        request,
        "processing_jobs/results.html",
        {"job": job, "result": result, "error": error},
    )


def view_extracted_data(request, job_id):
    return extract_job(request, job_id)



def download_extraction_json(request, job_id):
    job = get_object_or_404(ProcessingJob, pk=job_id)

    try:
        with default_storage.open(job.storage_reference, "rb") as stored_file:
            file_bytes = stored_file.read()

        result = extract_document(file_bytes, job.file_name)

    except Exception as exc:
        raise Http404("Could not extract this document.") from exc

    response = HttpResponse(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="job_{job.id}_extraction.json"'
    )
    return response
 
 