"""Regression test for repeated uploads of identical file content."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from processing_jobs.models import ProcessingJob

pytestmark = pytest.mark.django_db

UPLOAD_URL = "/api/upload/"


def test_identical_file_submissions_create_separate_jobs(client):
    user = get_user_model().objects.create_user(
        username="duplicate_upload_user",
        password="test-password-123",
    )
    client.force_login(user)

    content = b"invoice_number,amount\nINV-1001,1250\n"

    responses = [
        client.post(
            UPLOAD_URL,
            {"file": SimpleUploadedFile("invoice.csv", content, content_type="text/csv")},
        )
        for _ in range(2)
    ]

    assert all(response.status_code == 201 for response in responses)

    first, second = [response.json() for response in responses]

    assert first["sha256"] == second["sha256"]
    assert first["job_id"] != second["job_id"]
    assert first["stored_filename"] != second["stored_filename"]
    assert ProcessingJob.objects.filter(owner=user).count() == 2
