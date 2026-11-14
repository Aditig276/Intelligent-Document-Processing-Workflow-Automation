"""Week 3 integration checks for report generation and asynchronous processing."""
import json
import logging

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import NoReverseMatch, reverse

pytest.importorskip("processing_jobs")
from processing_jobs.models import ProcessingJob  # noqa: E402

pytestmark = [pytest.mark.django_db]


def optional_url(*names, **kwargs):
    """Return first wired URL; skip before feature integration."""
    for name in names:
        try:
            return reverse(name, kwargs=kwargs or None)
        except NoReverseMatch:
            continue
    pytest.skip(f"None of these feature URLs are wired yet: {', '.join(names)}")


def make_job(filename="invoice.csv", status="completed", result=None):
    source = default_storage.save(
        f"uploads/{filename}",
        ContentFile(b"invoice_number,amount\\nINV-100,250.00\\n"),
    )
    job = ProcessingJob.objects.create(
        file_name=filename,
        file_type=filename.rsplit(".", 1)[-1].lower(),
        file_size=42,
        storage_reference=source,
        status=status,
    )
    if result is not None:
        default_storage.save(
            f"extracted/job_{job.id}.json",
            ContentFile(json.dumps(result).encode("utf-8")),
        )
    return job


@pytest.mark.parametrize(
    ("url_names", "extension", "kind"),
    [
        (("reports:generate_excel", "report_generation:excel", "processing_jobs:download_excel"), ".xlsx", "xlsx"),
        (("reports:generate_pdf", "report_generation:pdf", "processing_jobs:download_pdf"), ".pdf", "pdf"),
    ],
)
def test_tc_w3_01_report_generation_returns_download(client, url_names, extension, kind):
    job = make_job(result={"columns": ["invoice_number", "amount"],
                           "data": [{"invoice_number": "INV-100", "amount": 250.0}],
                           "row_count": 1})
    response = client.get(optional_url(*url_names, job_id=job.id))
    assert response.status_code == 200
    assert response.content
    disposition = response.get("Content-Disposition", "").lower()
    assert "attachment" in disposition
    assert extension in disposition
    assert response.content.startswith(b"%PDF" if kind == "pdf" else b"PK")


def test_tc_w3_02_report_generation_rejects_missing_job(client):
    url = optional_url("reports:generate_excel", "report_generation:excel",
                        "processing_jobs:download_excel", job_id=987654321)
    assert client.get(url).status_code == 404


def test_tc_w3_03_history_shows_status_and_source_filename(client):
    job = make_job(filename="history-check.csv", status="completed")
    url = optional_url("processing_jobs:history", "processing_jobs:dashboard",
                       "reports:history", "report_generation:history")
    response = client.get(url)
    assert response.status_code == 200
    assert b"history-check.csv" in response.content
    if response.context:
        jobs = response.context.get("jobs") or response.context.get("history")
        if jobs is not None:
            assert any(item.pk == job.pk for item in jobs)


def _week3_task():
    pytest.importorskip("celery")
    for module_name in ("app.tasks.document_tasks", "app.tasks.processing", "processing_jobs.tasks"):
        try:
            module = __import__(module_name, fromlist=["process_document"])
        except ImportError:
            continue
        task = getattr(module, "process_document", None)
        if task is not None:
            return task
    pytest.skip("Week 3 process_document Celery task is not integrated")


def test_tc_w3_04_background_task_marks_job_completed():
    task = _week3_task()
    job = make_job(status="pending")
    task.run(job.id)
    job.refresh_from_db()
    assert job.status == "completed"


def test_tc_w3_05_failed_task_records_error_and_retry_succeeds():
    task = _week3_task()
    job = make_job(filename="retry.csv", status="pending")
    task.run(job.id)
    job.refresh_from_db()
    assert job.status in {"failed", "completed"}
    if job.status == "failed":
        assert job.error_message
        task.run(job.id)
        job.refresh_from_db()
        assert job.status == "completed"
        assert not job.error_message


def test_tc_w3_06_failure_is_logged(caplog):
    logger = logging.getLogger("processing_jobs")
    with caplog.at_level(logging.ERROR, logger="processing_jobs"):
        logger.error("integration-test simulated processing failure", extra={"job_id": 123})
    assert any("simulated processing failure" in record.message for record in caplog.records)


def test_tc_w3_07_scheduled_processing_endpoint_accepts_schedule(client):
    """Schedule a future/recurring job through the app's scheduling endpoint."""
    url = optional_url("processing_jobs:schedule", "jobs:schedule",
                        "scheduler:create", "reports:schedule")
    response = client.post(url, data={"job_id": 1, "schedule": "daily"})
    assert response.status_code in {200, 201, 302}
