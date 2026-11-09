"""Comprehensive tests for the logging system."""

import json
import logging
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse

import sample_factory as sf
from processing_jobs.models import ProcessingJob

pytestmark = [pytest.mark.django_db]

UPLOAD_LOGGER = "documents.upload"
JOB_LOGGER = "processing_jobs"
AUTH_LOGGER = "processing_jobs.auth"


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", email="alice@example.com", password="password123"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob", email="bob@example.com", password="password123"
    )


def _records_text(records):
    return "\n".join(r.getMessage() for r in records)


# ---------------------------------------------------- 1. Document upload events
def test_browser_upload_event_is_logged_at_info(client, alice, caplog):
    caplog.set_level(logging.INFO)
    client.force_login(alice)
    csv_file = SimpleUploadedFile("orders.csv", sf.csv_bytes(), content_type="text/csv")
    response = client.post(reverse("upload_document"), {"file": csv_file})
    assert response.status_code == 302

    records = [r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.INFO]
    assert records
    text = _records_text(records)
    assert "orders.csv" in text
    assert "alice" in text


def test_browser_upload_rejection_is_logged_at_warning(client, alice, caplog):
    caplog.set_level(logging.WARNING)
    client.force_login(alice)
    bad_file = SimpleUploadedFile("malware.exe", b"binary", content_type="application/octet-stream")
    response = client.post(reverse("upload_document"), {"file": bad_file})
    assert response.status_code == 200

    records = [r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.WARNING]
    assert records
    text = _records_text(records)
    assert "Unsupported file type" in text


# ---------------------------------------------------- 2. Job start, completion, failure
def test_job_extraction_start_and_completion_logged_with_job_id(client, alice, caplog):
    caplog.set_level(logging.INFO)
    path = default_storage.save("uploads/invoice.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="invoice.csv",
        file_type="csv",
        file_size=len(sf.csv_bytes()),
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(alice)
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302

    records = [r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.INFO]
    text = _records_text(records)
    assert f"Job {job.id}" in text
    assert "processing" in text
    assert "completed" in text


def test_job_extraction_failure_logged_at_error_with_job_id_and_reason(client, alice, caplog):
    caplog.set_level(logging.ERROR)
    path = default_storage.save("uploads/bad.pdf", ContentFile(b"not a valid pdf"))
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="bad.pdf",
        file_type="pdf",
        file_size=14,
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(alice)
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302

    error_records = [r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.ERROR]
    assert error_records
    text = _records_text(error_records)
    assert f"Job {job.id}" in text
    assert "failed" in text.lower()


# ---------------------------------------------------- 3. Auth and unauthorized access events
def test_unauthorized_job_access_is_logged_at_warning(client, alice, bob, caplog):
    caplog.set_level(logging.WARNING)
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_confidential.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(bob)

    # 1. Detail access attempt
    client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    # 2. Extract access attempt
    client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    # 3. Download access attempt
    client.get(reverse("download_result", kwargs={"job_id": job.id}))

    warning_records = [
        r for r in caplog.records if r.name == AUTH_LOGGER and r.levelno == logging.WARNING
    ]
    assert len(warning_records) >= 3
    text = _records_text(warning_records)
    assert "bob" in text
    assert f"job {job.id}" in text.lower()
    assert "alice" in text


def test_auth_signals_log_login_logout_and_failed_login(caplog, alice):
    caplog.set_level(logging.INFO)
    factory = RequestFactory()
    request = factory.get("/")

    # Successful login signal
    user_logged_in.send(sender=alice.__class__, request=request, user=alice)
    # Logout signal
    user_logged_out.send(sender=alice.__class__, request=request, user=alice)
    # Failed login signal
    user_login_failed.send(
        sender=alice.__class__,
        credentials={"username": "hacker", "password": "supersecretpassword123"},
        request=request,
    )

    text = _records_text(caplog.records)
    assert "User 'alice' logged in successfully" in text
    assert "User 'alice' logged out" in text
    assert "Failed login attempt for username 'hacker'" in text
    # Sensitive information check: password must NEVER be logged
    assert "supersecretpassword123" not in text


# ---------------------------------------------------- 4. Document download events
def test_document_download_event_is_logged_at_info(client, alice, caplog):
    caplog.set_level(logging.INFO)
    result_dir = Path(settings.MEDIA_ROOT) / "extracted"
    result_dir.mkdir(parents=True, exist_ok=True)

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="annual_data.csv",
        file_type="csv",
        file_size=200,
        status=ProcessingJob.Status.COMPLETED,
    )
    result_file = result_dir / f"job_{job.id}.json"
    result_file.write_text(json.dumps({"rows": 5}), encoding="utf-8")

    client.force_login(alice)
    response = client.get(reverse("download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 200

    info_records = [r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.INFO]
    text = _records_text(info_records)
    assert "downloaded" in text.lower()
    assert f"job_id={job.id}" in text
    assert "annual_data.csv" in text


def test_download_incomplete_job_is_logged_at_warning(client, alice, caplog):
    caplog.set_level(logging.WARNING)
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="pending_data.csv",
        file_type="csv",
        file_size=200,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(alice)
    response = client.get(reverse("download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 404

    warning_records = [
        r for r in caplog.records if r.name == JOB_LOGGER and r.levelno == logging.WARNING
    ]
    text = _records_text(warning_records)
    assert "incomplete job" in text.lower()
    assert str(job.id) in text


# ---------------------------------------------------- 5. Log levels & Rotating file verification
def test_rotating_file_handler_configured_and_writes_to_file():
    logger = logging.getLogger("processing_jobs")
    test_msg = "TEST_ROTATING_HANDLER_LOG_ENTRY"
    logger.info(test_msg)

    log_file = settings.LOGS_DIR / "app.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert test_msg in content


# ---------------------------------------------------- 6. Resilience: Logging failures do not break processing
def test_logging_failure_does_not_break_extraction(client, alice, monkeypatch):
    path = default_storage.save("uploads/resilient.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="resilient.csv",
        file_type="csv",
        file_size=len(sf.csv_bytes()),
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(alice)

    # Force logging to raise an exception
    def broken_log(*args, **kwargs):
        raise RuntimeError("Logging infrastructure failure")

    monkeypatch.setattr(logging.Logger, "info", broken_log)
    monkeypatch.setattr(logging.Logger, "warning", broken_log)
    monkeypatch.setattr(logging.Logger, "error", broken_log)

    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302
    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED
