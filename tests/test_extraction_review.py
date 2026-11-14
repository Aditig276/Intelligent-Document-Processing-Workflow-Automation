"""Regression tests for the document extraction review workflow."""

from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from processing_jobs.models import ProcessingJob


pytestmark = pytest.mark.django_db

REVIEW_URL = "extraction_review"

VALID_REVIEW_DATA = {
    "document_name": "invoice.pdf",
    "invoice_number": "INV-1001",
    "document_date": "2026-11-10",
    "customer_name": "Acme Ltd",
    "total_amount": "1250.50",
}


@pytest.fixture
def review_user(django_user_model):
    return django_user_model.objects.create_user(
        username="review_user",
        password="test-password-123",
    )


@pytest.fixture
def review_client(client, review_user):
    client.force_login(review_user)
    return client


@pytest.fixture
def review_job(review_user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    file_path = Path(settings.MEDIA_ROOT) / "review-invoice.pdf"
    file_path.write_bytes(b"synthetic test PDF content")

    return ProcessingJob.objects.create(
        owner=review_user,
        file_name="invoice.pdf",
        file_type="pdf",
        file_size=file_path.stat().st_size,
        storage_reference=file_path.name,
        status=ProcessingJob.Status.COMPLETED,
    )


def test_review_page_loads(review_client):
    response = review_client.get(reverse(REVIEW_URL))

    assert response.status_code == 200
    assert "Review Extracted Document Data" in response.content.decode()


@patch("documents.views.extract_document_text")
def test_upload_creates_job_and_displays_extracted_text(
    mock_extract, review_client
):
    mock_extract.return_value = {"full_text": "Invoice INV-1001"}

    uploaded_file = SimpleUploadedFile(
        "invoice.pdf",
        b"synthetic PDF content",
        content_type="application/pdf",
    )

    response = review_client.post(
        reverse(REVIEW_URL),
        {"file": uploaded_file},
    )

    assert response.status_code == 200
    assert "Invoice INV-1001" in response.content.decode()

    job = ProcessingJob.objects.get(file_name="invoice.pdf")
    assert job.status == ProcessingJob.Status.COMPLETED
    assert str(job.owner_id) == review_client.session.get("_auth_user_id")
    assert job.reviewed_data == {}


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("invoice_number", "", "This field is required."),
        ("document_date", "10-11-2026", "Enter date in YYYY-MM-DD format."),
        ("total_amount", "-10", "Enter a valid non-negative amount."),
        ("total_amount", "not-a-number", "Enter a valid non-negative amount."),
    ],
)
@patch("documents.views.extract_document_text")
def test_invalid_review_data_is_not_saved(
    mock_extract,
    field,
    value,
    expected_error,
    review_client,
    review_job,
):
    mock_extract.return_value = {"full_text": "Invoice text"}

    data = {
        "job_id": str(review_job.id),
        **VALID_REVIEW_DATA,
    }
    data[field] = value

    response = review_client.post(reverse(REVIEW_URL), data)

    review_job.refresh_from_db()

    assert response.status_code == 200
    assert expected_error in response.content.decode()
    assert review_job.reviewed_data == {}


@patch("documents.views.extract_document_text")
def test_valid_review_data_is_saved(
    mock_extract, review_client, review_job
):
    mock_extract.return_value = {"full_text": "Invoice text"}

    response = review_client.post(
        reverse(REVIEW_URL),
        {"job_id": str(review_job.id), **VALID_REVIEW_DATA},
    )

    review_job.refresh_from_db()

    assert response.status_code == 200
    assert "Reviewed data saved successfully." in response.content.decode()
    assert review_job.reviewed_data == VALID_REVIEW_DATA


def test_user_cannot_review_another_users_job(
    review_client, django_user_model, settings, tmp_path
):
    other_user = django_user_model.objects.create_user(
        username="another_review_user",
        password="test-password-123",
    )

    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    file_path = Path(settings.MEDIA_ROOT) / "other-invoice.pdf"
    file_path.write_bytes(b"synthetic test PDF content")

    other_job = ProcessingJob.objects.create(
        owner=other_user,
        file_name="other-invoice.pdf",
        file_type="pdf",
        storage_reference=file_path.name,
    )

    response = review_client.post(
        reverse(REVIEW_URL),
        {"job_id": str(other_job.id), **VALID_REVIEW_DATA},
    )

    other_job.refresh_from_db()

    assert response.status_code == 200
    assert "You cannot access this document." in response.content.decode()
    assert other_job.reviewed_data == {}


def test_review_returns_error_for_missing_job(review_client):
    response = review_client.post(
        reverse(REVIEW_URL),
        {"job_id": "999999", **VALID_REVIEW_DATA},
    )

    assert response.status_code == 200
    assert "Processing job not found." in response.content.decode()


@patch("documents.views.extract_document_text")
def test_review_returns_error_when_stored_file_is_missing(
    mock_extract, review_client, review_job, settings
):
    stored_file = Path(settings.MEDIA_ROOT) / review_job.storage_reference
    stored_file.unlink()

    response = review_client.post(
        reverse(REVIEW_URL),
        {"job_id": str(review_job.id), **VALID_REVIEW_DATA},
    )

    assert response.status_code == 200
    assert "Uploaded document not found." in response.content.decode()
    mock_extract.assert_not_called()
