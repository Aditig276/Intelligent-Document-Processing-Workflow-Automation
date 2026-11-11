"""Tests for P1 fixes: Background Worker Concurrency, Job Detail GET Immobility, and XLSX Upload Validation."""

import json
from pathlib import Path
import threading

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.urls import reverse

import sample_factory as sf
from processing_jobs.management.commands.process_pending_jobs import claim_next_job, process_claimed_job
from processing_jobs.models import ProcessingJob

pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.fixture
def test_user(django_user_model):
    return django_user_model.objects.create_user(
        username="test_auditor", password="password123"
    )


# ---------------------------------------------------- TASK 1: Worker Concurrency
def test_claim_next_job_atomically_transitions_status():
    job = ProcessingJob.objects.create(
        file_name="worker_test.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )
    claimed = claim_next_job()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == ProcessingJob.Status.PROCESSING

    # Reload from DB
    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.PROCESSING


def test_concurrent_worker_claiming_prevents_duplicate_processing():
    """Two workers attempting to claim the same single job: exactly one succeeds."""
    job = ProcessingJob.objects.create(
        file_name="race_test.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )

    claimed_jobs = []
    lock = threading.Lock()

    def worker_claim():
        try:
            claimed = claim_next_job()
            if claimed:
                with lock:
                    claimed_jobs.append(claimed.id)
        finally:
            connection.close()

    t1 = threading.Thread(target=worker_claim)
    t2 = threading.Thread(target=worker_claim)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one thread claimed the job
    assert len(claimed_jobs) == 1
    assert claimed_jobs[0] == job.id

    # Secondary claim returns None
    second_claim = claim_next_job()
    assert second_claim is None


def test_concurrent_worker_claiming_with_multiple_jobs():
    """Two workers claiming from a queue of two jobs: neither processes the same job."""
    job1 = ProcessingJob.objects.create(
        file_name="job1.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )
    job2 = ProcessingJob.objects.create(
        file_name="job2.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )

    results = []
    lock = threading.Lock()

    def worker():
        try:
            claimed = claim_next_job()
            if claimed:
                with lock:
                    results.append(claimed.id)
        finally:
            connection.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # No duplicate IDs claimed
    assert len(results) == len(set(results))
    for job_id in results:
        assert job_id in (job1.id, job2.id)


def test_process_pending_jobs_command_once_option(settings):
    path = default_storage.save("uploads/cmd_test.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        file_name="cmd_test.csv",
        file_type="csv",
        file_size=len(sf.csv_bytes()),
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )

    call_command("process_pending_jobs", once=True)

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED

    result_file = Path(settings.MEDIA_ROOT) / "extracted" / f"job_{job.id}.json"
    assert result_file.exists()


# ---------------------------------------------------- TASK 2: Job Detail Status Immobility
def test_job_detail_get_does_not_mutate_pending_job_status(client, test_user):
    job = ProcessingJob.objects.create(
        owner=test_user,
        file_name="pending_doc.csv",
        file_type="csv",
        file_size=120,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(test_user)
    response = client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    assert response.status_code == 200

    job.refresh_from_db()
    # Status MUST remain PENDING on GET
    assert job.status == ProcessingJob.Status.PENDING


def test_job_manual_extraction_workflow_still_functional(client, test_user, settings):
    path = default_storage.save("uploads/manual_extract.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        owner=test_user,
        file_name="manual_extract.csv",
        file_type="csv",
        file_size=len(sf.csv_bytes()),
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(test_user)

    # 1. GET detail view: status stays pending
    client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.PENDING

    # 2. POST extract view: status moves to completed
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED


# ---------------------------------------------------- TASK 3: XLSX Upload Validation
def test_zip_renamed_to_xlsx_returns_400(client, test_user):
    client.force_login(test_user)
    zip_bytes = sf.zip_not_excel_bytes()
    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("invalid.xlsx", zip_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Invalid or corrupted Excel file."


def test_valid_xlsx_upload_still_succeeds(client, test_user):
    client.force_login(test_user)
    xlsx_bytes = sf.xlsx_bytes()
    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("valid.xlsx", xlsx_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "File uploaded successfully."
    assert body["stored_filename"].endswith(".xlsx")
