"""Tests for the upload form, job views, extractors and background worker.

Test IDs (TC-WF-xx) match docs/test-plan.md.
"""
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

import sample_factory as sf

pytest.importorskip("processing_jobs")
from processing_jobs import extractors  # noqa: E402
from processing_jobs.models import ProcessingJob  # noqa: E402

pytestmark = [pytest.mark.jobs, pytest.mark.django_db]


# ------------------------------------------------------------ helpers
@pytest.fixture(autouse=True)
def workflow_auth_user(client, django_user_model):
    """Authenticate client and provide a default owner for workflow tests."""
    user = django_user_model.objects.create_user(
        username="workflow_test_user", email="workflow@example.com", password="password123"
    )
    client.force_login(user)
    return user


def get_default_owner():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="workflow_test_user",
        defaults={"email": "workflow@example.com"}
    )
    return user


def post_upload(client, url, name, content):
    return client.post(
        url, {"file": SimpleUploadedFile(name, content)}
    )


def stored_job(name, content, status="pending", owner=None):
    """A job whose file is already saved in storage (as the upload view does)."""
    if owner is None:
        owner = get_default_owner()
    path = default_storage.save(f"uploads/{name}", ContentFile(content))
    return ProcessingJob.objects.create(
        owner=owner,
        file_name=name,
        file_type=name.rsplit(".", 1)[-1].lower(),
        file_size=len(content),
        storage_reference=path,
        status=status,
    )


# ====================================================== extractors
def test_tc_wf_01_extract_csv_rows_and_columns():
    result = extractors.extract_document(sf.csv_bytes(), "a.csv")
    assert result["file_type"] == "csv"
    assert result["columns"] == ["name", "date", "invoice_number", "amount"]
    assert result["row_count"] == 2
    assert result["data"][0]["invoice_number"] == "INV-0001"


def test_tc_wf_02_csv_missing_values_become_null():
    csv = b"name,amount\nAcme,\n,20\n"
    data = extractors.extract_document(csv, "a.csv")["data"]
    assert data[0]["amount"] is None
    assert data[1]["name"] is None


def test_tc_wf_03_extract_pdf_text_and_pages():
    pdf = sf.pdf_bytes(text="Invoice INV-0042", pages=2)
    result = extractors.extract_document(pdf, "a.pdf")
    assert result["file_type"] == "pdf"
    assert result["page_count"] == 2
    assert "INV-0042" in result["text"]
    assert result["pages"][1]["page"] == 2


def test_tc_wf_04_extract_every_worksheet_of_an_xlsx():
    book = sf.xlsx_bytes({"Jan": sf.INVOICE_ROWS, "Feb": sf.INVOICE_ROWS[:2]})
    result = extractors.extract_document(book, "a.xlsx")
    assert result["file_type"] == "excel"
    assert result["sheet_count"] == 2
    assert result["sheets"]["Jan"]["row_count"] == 2
    assert result["sheets"]["Feb"]["row_count"] == 1


@pytest.mark.parametrize("name", ["scan.png", "scan.jpg", "x.docx", "noext"])
def test_tc_wf_05_unsupported_types_raise_a_clear_error(name):
    with pytest.raises(ValueError, match="Unsupported file type"):
        extractors.extract_document(b"data", name)


def test_tc_wf_06_corrupt_pdf_raises():
    with pytest.raises(Exception):
        extractors.extract_document(b"not a pdf", "a.pdf")


def test_tc_wf_07_empty_csv_raises():
    with pytest.raises(Exception):
        extractors.extract_document(b"", "a.csv")


# ================================================ upload form + view
@pytest.fixture
def upload_url(require_url):
    return require_url("processing_jobs:upload")


def test_tc_wf_08_upload_page_loads(client, upload_url):
    assert client.get(upload_url).status_code == 200


def test_tc_wf_09_valid_upload_creates_a_pending_job(client, upload_url, require_url):
    response = post_upload(client, upload_url, "invoice.csv", sf.csv_bytes())
    assert response.status_code == 302
    assert response["Location"] == require_url("processing_jobs:dashboard")

    job = ProcessingJob.objects.get()
    assert job.status == "pending"
    assert job.file_name == "invoice.csv"
    assert job.file_type == "csv"
    assert job.file_size == len(sf.csv_bytes())
    assert default_storage.exists(job.storage_reference)


@pytest.mark.parametrize("name", ["a.pdf", "a.csv", "a.xlsx", "a.xls", "a.png", "a.jpg", "a.jpeg"])
def test_tc_wf_10_form_accepts_every_allowed_extension(client, upload_url, name):
    response = post_upload(client, upload_url, name, b"x")
    assert response.status_code == 302
    assert ProcessingJob.objects.count() == 1


@pytest.mark.parametrize("name", ["a.txt", "a.exe", "a.docx", "noextension", "a.pdf.exe"])
def test_tc_wf_11_form_rejects_unsupported_extensions(client, upload_url, name):
    response = post_upload(client, upload_url, name, b"x")
    assert response.status_code == 200
    assert b"Unsupported file type" in response.content
    assert ProcessingJob.objects.count() == 0


def test_tc_wf_12_form_rejects_files_over_10_mb(client, upload_url):
    response = post_upload(
        client, upload_url, "big.csv", b"a" * (sf.MAX_FILE_SIZE + 1)
    )
    assert response.status_code == 200
    assert b"10 MB" in response.content
    assert ProcessingJob.objects.count() == 0


def test_tc_wf_13_form_accepts_a_file_of_exactly_10_mb(client, upload_url):
    response = post_upload(
        client, upload_url, "limit.csv", b"a" * sf.MAX_FILE_SIZE
    )
    assert response.status_code == 302


def test_tc_wf_14_post_without_a_file_shows_an_error(client, upload_url):
    response = client.post(upload_url, {})
    assert response.status_code == 200
    assert ProcessingJob.objects.count() == 0


# ======================================================== dashboard
def test_tc_wf_15_dashboard_lists_jobs_with_their_status(client, require_url):
    user = get_default_owner()
    ProcessingJob.objects.create(owner=user, file_name="p.pdf", file_type="pdf")
    ProcessingJob.objects.create(owner=user, file_name="f.csv", file_type="csv", status="failed")
    response = client.get(require_url("processing_jobs:dashboard"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "p.pdf" in html and "f.csv" in html
    assert "Pending" in html and "Failed" in html


def test_tc_wf_16_dashboard_shows_at_most_100_jobs(client, require_url):
    user = get_default_owner()
    ProcessingJob.objects.bulk_create(
        [ProcessingJob(owner=user, file_name=f"f{i}.csv", file_type="csv") for i in range(105)]
    )
    response = client.get(require_url("processing_jobs:dashboard"))
    assert len(response.context["jobs"]) == 100


def test_tc_wf_17_dashboard_rejects_post(client, require_url):
    assert client.post(require_url("processing_jobs:dashboard")).status_code == 405


# ================================================ extraction view
def test_tc_wf_18_post_extract_completes_job_and_saves_result(client, require_url):
    job = stored_job("invoice.csv", sf.csv_bytes())
    response = client.post(require_url("processing_jobs:extract", job_id=job.id))

    assert response.status_code == 302
    job.refresh_from_db()
    assert job.status == "completed"
    assert job.error_message == ""
    saved = json.loads(default_storage.open(f"extracted/job_{job.id}.json").read())
    assert saved["row_count"] == 2


def test_tc_wf_19_post_extract_on_corrupt_file_marks_job_failed(client, require_url):
    job = stored_job("broken.pdf", b"this is not a pdf")
    response = client.post(require_url("processing_jobs:extract", job_id=job.id), follow=True)

    assert response.status_code == 200
    assert b"Extraction failed" in response.content
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.error_message


def test_tc_wf_20_image_job_fails_with_clear_message_until_ocr_exists(client, require_url):
    """Images pass the upload form but the extractor has no OCR yet."""
    job = stored_job("scan.png", sf.png_bytes())
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    job.refresh_from_db()
    assert job.status == "failed"
    assert "Unsupported file type" in job.error_message


def test_tc_wf_21_missing_stored_file_marks_job_failed(client, require_url):
    user = get_default_owner()
    job = ProcessingJob.objects.create(
        owner=user, file_name="gone.csv", file_type="csv", storage_reference="uploads/gone.csv"
    )
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.error_message


def test_tc_wf_22_error_message_is_capped_at_2000_chars(client, require_url, monkeypatch):
    job = stored_job("a.csv", sf.csv_bytes())

    def boom(*args, **kwargs):
        raise RuntimeError("x" * 5000)

    monkeypatch.setattr("processing_jobs.views.extract_document", boom)
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    job.refresh_from_db()
    assert job.status == "failed"
    assert len(job.error_message) == 2000


def test_tc_wf_23_extracting_a_completed_job_does_not_run_again(client, require_url, monkeypatch):
    job = stored_job("a.csv", sf.csv_bytes(), status="completed")
    calls = []
    monkeypatch.setattr(
        "processing_jobs.views.extract_document", lambda *a, **k: calls.append(1)
    )
    response = client.post(require_url("processing_jobs:extract", job_id=job.id))
    assert response.status_code == 302
    assert calls == []


def test_tc_wf_24_failed_job_can_be_retried_and_error_is_cleared(client, require_url):
    job = stored_job("a.csv", sf.csv_bytes(), status="failed")
    job.error_message = "old error"
    job.save()
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    job.refresh_from_db()
    assert job.status == "completed"
    assert job.error_message == ""


def test_tc_wf_25_unknown_job_id_returns_404(client, require_url):
    assert client.get(require_url("processing_jobs:extract", job_id=99999)).status_code == 404
    assert client.get(require_url("processing_jobs:download_json", job_id=99999)).status_code == 404


def test_tc_wf_26_completed_job_page_shows_saved_result(client, require_url):
    job = stored_job("a.csv", sf.csv_bytes())
    client.post(require_url("processing_jobs:extract", job_id=job.id))
    response = client.get(require_url("processing_jobs:view_extracted_data", job_id=job.id))
    assert response.status_code == 200
    assert b"Extraction completed successfully" in response.content
    assert b"INV-0001" in response.content


def test_tc_wf_27_completed_job_with_missing_result_file_shows_error(client, require_url):
    job = stored_job("a.csv", sf.csv_bytes(), status="completed")
    response = client.get(require_url("processing_jobs:extract", job_id=job.id))
    assert b"saved extraction result was not found" in response.content


def test_tc_wf_28_failed_job_page_shows_previous_error(client, require_url):
    job = stored_job("a.csv", sf.csv_bytes(), status="failed")
    job.error_message = "boom"
    job.save()
    response = client.get(require_url("processing_jobs:extract", job_id=job.id))
    assert b"Previous extraction failed: boom" in response.content


def test_tc_wf_29_opening_the_job_page_does_not_move_pending_to_processing(client, require_url):
    """Verifies fix for FINDING-03: opening job page does not change pending to processing."""
    job = stored_job("a.csv", sf.csv_bytes())
    client.get(require_url("processing_jobs:extract", job_id=job.id))
    job.refresh_from_db()
    assert job.status == "pending"


# ============================================== download endpoint
def test_tc_wf_30_download_returns_json_attachment(client, require_url):
    job = stored_job("a.csv", sf.csv_bytes())
    response = client.get(require_url("processing_jobs:download_json", job_id=job.id))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert f"job_{job.id}_extraction.json" in response["Content-Disposition"]
    assert json.loads(response.content)["row_count"] == 2


def test_tc_wf_31_download_of_unreadable_document_returns_404(client, require_url):
    job = stored_job("broken.pdf", b"not a pdf")
    assert client.get(require_url("processing_jobs:download_json", job_id=job.id)).status_code == 404


# ===================================================== worker command
class _StopWorker(Exception):
    pass


def run_worker(monkeypatch):
    """Run process_pending_jobs until it first goes idle, then stop it."""
    from types import SimpleNamespace

    from django.core.management import call_command

    module = "processing_jobs.management.commands.process_pending_jobs"

    def stop(_seconds):
        raise _StopWorker

    monkeypatch.setattr(f"{module}.time", SimpleNamespace(sleep=stop))
    # keep the test database connection open (the worker closes stale ones)
    monkeypatch.setattr(f"{module}.close_old_connections", lambda: None)
    with pytest.raises(_StopWorker):
        call_command("process_pending_jobs")


def test_tc_wf_32_worker_completes_pending_jobs_oldest_first(monkeypatch):
    first = stored_job("one.csv", sf.csv_bytes())
    second = stored_job("two.csv", sf.csv_bytes())
    order = []
    real = extractors.extract_document

    def spy(data, name):
        order.append(name)
        return real(data, name)

    monkeypatch.setattr(
        "processing_jobs.management.commands.process_pending_jobs.extract_document", spy
    )
    run_worker(monkeypatch)

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == ("completed", "completed")
    assert order == ["one.csv", "two.csv"]


def test_tc_wf_33_worker_marks_bad_documents_failed_and_keeps_going(monkeypatch):
    bad = stored_job("bad.pdf", b"not a pdf")
    good = stored_job("good.csv", sf.csv_bytes())
    run_worker(monkeypatch)

    bad.refresh_from_db()
    good.refresh_from_db()
    assert bad.status == "failed" and bad.error_message
    assert good.status == "completed"


def test_tc_wf_34_worker_ignores_jobs_that_are_not_pending(monkeypatch):
    done = stored_job("a.csv", sf.csv_bytes(), status="completed")
    busy = stored_job("b.csv", sf.csv_bytes(), status="processing")
    run_worker(monkeypatch)
    done.refresh_from_db()
    busy.refresh_from_db()
    assert (done.status, busy.status) == ("completed", "processing")
