"""Logging tests (see docs/logging-plan.md).

No logging exists in the code yet, so every test here is xfail(strict=True):
  * today they fail  -> reported as "xfailed" (expected)
  * once logging is added they pass -> "XPASS(strict)" turns the run red,
    which tells you to delete the xfail mark and keep the test as a guard.

Logger names and message fields are the contract proposed in the plan.
"""
import logging

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

import sample_factory as sf

pytestmark = [pytest.mark.logging, pytest.mark.django_db]

NOT_YET = "LOGGING-GAP: logging is not implemented yet (see docs/logging-plan.md)"
needs_logging = pytest.mark.xfail(strict=True, reason=NOT_YET)

UPLOAD_LOGGER = "documents.upload"
JOB_LOGGER = "processing_jobs"


def _upload(client, name, content):
    return client.post("/api/upload/", {"file": SimpleUploadedFile(name, content)})


def _text(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


@needs_logging
def test_tc_log_01_accepted_upload_is_logged_at_info(client, caplog):
    caplog.set_level(logging.INFO)
    body = _upload(client, "invoice.csv", sf.csv_bytes()).json()
    records = [r for r in caplog.records if r.name == UPLOAD_LOGGER and r.levelno == logging.INFO]
    assert records, "expected an INFO record from documents.upload"
    text = _text(caplog)
    assert body["stored_filename"] in text and body["sha256"] in text


@needs_logging
def test_tc_log_02_rejected_upload_is_logged_at_warning_with_reason(client, caplog):
    caplog.set_level(logging.INFO)
    _upload(client, "notes.txt", b"hello")
    records = [r for r in caplog.records if r.name == UPLOAD_LOGGER and r.levelno == logging.WARNING]
    assert records
    assert "Unsupported file format" in records[0].getMessage()


@needs_logging
def test_tc_log_03_oversized_upload_is_logged(client, caplog):
    caplog.set_level(logging.INFO)
    _upload(client, "big.csv", sf.exact_size_csv(sf.MAX_FILE_SIZE + 1))
    assert any(r.name == UPLOAD_LOGGER and r.levelno == logging.WARNING for r in caplog.records)


@needs_logging
def test_tc_log_04_storage_failure_is_logged_at_error(client, caplog, monkeypatch):
    from pathlib import Path

    caplog.set_level(logging.INFO)

    def boom(self, *a, **k):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(Path, "open", boom)
        _upload(client, "a.csv", sf.csv_bytes())
    assert any(r.name == UPLOAD_LOGGER and r.levelno >= logging.ERROR for r in caplog.records)


@needs_logging
def test_tc_log_05_status_changes_are_logged_with_job_id(client, caplog, require_url):
    from processing_jobs.models import ProcessingJob

    caplog.set_level(logging.INFO)
    path = default_storage.save("uploads/a.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        file_name="a.csv", file_type="csv", storage_reference=path
    )
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    text = _text(caplog)
    assert f"job {job.id}" in text.lower()
    assert "processing" in text and "completed" in text


@needs_logging
def test_tc_log_06_failed_job_is_logged_at_error_with_reason(client, caplog, require_url):
    from processing_jobs.models import ProcessingJob

    caplog.set_level(logging.INFO)
    path = default_storage.save("uploads/b.pdf", ContentFile(b"not a pdf"))
    job = ProcessingJob.objects.create(
        file_name="b.pdf", file_type="pdf", storage_reference=path
    )
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    errors = [r for r in caplog.records if r.name.startswith(JOB_LOGGER) and r.levelno >= logging.ERROR]
    assert errors and str(job.id) in errors[0].getMessage()


@needs_logging
def test_tc_log_07_logs_never_contain_document_contents(client, caplog):
    caplog.set_level(logging.DEBUG)
    secret = b"name,amount\nTOP-SECRET-CUSTOMER,999999\n"
    _upload(client, "secret.csv", secret)
    assert any(r.name == UPLOAD_LOGGER for r in caplog.records), "nothing was logged"
    assert "TOP-SECRET-CUSTOMER" not in _text(caplog)
    assert "999999" not in _text(caplog)


@needs_logging
def test_tc_log_08_logs_use_the_original_name_not_a_user_supplied_path(client, caplog):
    caplog.set_level(logging.INFO)
    _upload(client, "../../etc/passwd.csv", sf.csv_bytes())
    assert any(r.name == UPLOAD_LOGGER for r in caplog.records), "nothing was logged"
    assert "../" not in _text(caplog)
