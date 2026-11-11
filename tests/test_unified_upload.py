import base64
import hashlib
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.urls import reverse
import pytest

from processing_jobs.models import ProcessingJob
from processing_jobs.services import ingest_document

pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.fixture
def user_a(django_user_model):
    return django_user_model.objects.create_user(
        username="user_a",
        password="password_a",
        email="user_a@example.com",
        is_active=True,
    )


@pytest.fixture
def user_b(django_user_model):
    return django_user_model.objects.create_user(
        username="user_b",
        password="password_b",
        email="user_b@example.com",
        is_active=True,
    )


def basic_auth(username, password):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


# 1. Browser upload creates a ProcessingJob
def test_01_browser_upload_creates_processing_job(client, user_a):
    client.force_login(user_a)
    upload_url = reverse("processing_jobs:upload")
    csv_content = b"header1,header2\nvalue1,value2\n"

    response = client.post(
        upload_url,
        {"file": SimpleUploadedFile("browser_test.csv", csv_content, content_type="text/csv")},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("processing_jobs:dashboard")

    job = ProcessingJob.objects.filter(owner=user_a, file_name="browser_test.csv").first()
    assert job is not None
    assert job.status == ProcessingJob.Status.PENDING
    assert job.file_size == len(csv_content)
    assert job.file_type == "csv"
    assert job.storage_reference != ""


# 2. API upload creates a ProcessingJob
def test_02_api_upload_creates_processing_job(client, user_a):
    csv_content = b"account,balance\nacc_001,1500\n"
    auth_header = basic_auth("user_a", "password_a")

    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("api_invoice.csv", csv_content, content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )

    assert response.status_code == 201
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "pending"
    assert body["original_filename"] == "api_invoice.csv"
    assert body["size_bytes"] == len(csv_content)

    job = ProcessingJob.objects.get(id=body["job_id"])
    assert job.owner == user_a
    assert job.status == ProcessingJob.Status.PENDING
    assert job.file_name == "api_invoice.csv"
    assert job.file_size == len(csv_content)


# 3. API-created jobs are visible to their owner and isolated from other users
def test_03_api_created_jobs_are_visible_only_to_owner(client, user_a, user_b):
    auth_header = basic_auth("user_a", "password_a")
    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("confidential_a.csv", b"id,val\n1,100\n", content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]

    # Owner accesses dashboard: job is visible
    client.force_login(user_a)
    dashboard_a = client.get(reverse("processing_jobs:dashboard"))
    assert dashboard_a.status_code == 200
    assert "confidential_a.csv" in dashboard_a.content.decode("utf-8")

    # Another user accesses dashboard: job is NOT visible
    client.force_login(user_b)
    dashboard_b = client.get(reverse("processing_jobs:dashboard"))
    assert dashboard_b.status_code == 200
    assert "confidential_a.csv" not in dashboard_b.content.decode("utf-8")

    # Another user attempts to access job detail / extraction directly: forbidden
    extract_url = reverse("processing_jobs:extract", kwargs={"job_id": job_id})
    res_b = client.get(extract_url)
    assert res_b.status_code in (403, 404)


# 4. API-created jobs are processed by the background worker
def test_04_api_created_jobs_are_processed_by_background_worker(client, user_a):
    csv_content = b"item,amount\nWidget,42.50\n"
    auth_header = basic_auth("user_a", "password_a")

    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("worker_target.csv", csv_content, content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]

    job = ProcessingJob.objects.get(id=job_id)
    assert job.status == ProcessingJob.Status.PENDING

    # Run the background worker management command
    call_command("process_pending_jobs", once=True)

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED
    assert job.error_message == ""

    # Verify extracted JSON result was generated
    result_path = Path(settings.MEDIA_ROOT) / "extracted" / f"job_{job.id}.json"
    assert result_path.exists()
    assert "Widget" in result_path.read_text(encoding="utf-8")


# 5. Uploaded files are stored correctly
def test_05_uploaded_files_are_stored_correctly(client, user_a):
    csv_content = b"col1,col2,col3\nval1,val2,val3\n"
    expected_sha256 = hashlib.sha256(csv_content).hexdigest()
    auth_header = basic_auth("user_a", "password_a")

    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("storage_check.csv", csv_content, content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["sha256"] == expected_sha256

    job = ProcessingJob.objects.get(id=body["job_id"])
    file_on_disk = Path(settings.MEDIA_ROOT) / job.storage_reference
    assert file_on_disk.exists()
    assert file_on_disk.read_bytes() == csv_content


# 6. Failed database creation does not leave orphaned files
def test_06_failed_database_creation_does_not_leave_orphaned_files(isolated_media, user_a):
    content = b"transaction_integrity_test\n"
    initial_files = list(isolated_media.rglob("*"))

    with patch.object(ProcessingJob.objects, "create", side_effect=DatabaseError("DB connection dropped")):
        with pytest.raises(DatabaseError, match="DB connection dropped"):
            ingest_document(
                uploaded_file=None,
                original_filename="fail_cleanup.csv",
                owner=user_a,
                content=content,
            )

    # Ensure no orphaned files were left in the media root
    current_files = [p for p in isolated_media.rglob("*") if p.is_file()]
    assert current_files == [p for p in initial_files if p.is_file()]


# 7. Missing credentials are rejected
def test_07_missing_credentials_are_rejected(client):
    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("no_auth.csv", b"a,b\n1,2\n", content_type="text/csv")},
    )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response
    assert response.json()["error"] == "Authentication credentials were not provided."
    assert ProcessingJob.objects.count() == 0


# 8. Invalid credentials are rejected
def test_08_invalid_credentials_are_rejected(client, user_a):
    # Wrong password
    bad_auth = basic_auth("user_a", "wrong_secret_123")
    response_wrong = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("bad_pw.csv", b"a,b\n1,2\n", content_type="text/csv")},
        HTTP_AUTHORIZATION=bad_auth,
    )
    assert response_wrong.status_code == 401
    assert response_wrong.json()["error"] == "Invalid credentials."

    # Malformed base64
    response_malformed = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("malformed.csv", b"a,b\n1,2\n", content_type="text/csv")},
        HTTP_AUTHORIZATION="Basic ???not-valid-base64???",
    )
    assert response_malformed.status_code == 401
    assert "Invalid authorization header format" in response_malformed.json()["error"]

    # Unsupported authentication scheme
    response_scheme = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("scheme.csv", b"a,b\n1,2\n", content_type="text/csv")},
        HTTP_AUTHORIZATION="Bearer token_12345",
    )
    assert response_scheme.status_code == 401
    assert "Basic authentication is required" in response_scheme.json()["error"]


# 9. Valid credentials allow uploads
def test_09_valid_credentials_allow_uploads(client, user_a):
    auth_header = basic_auth("user_a", "password_a")
    content = b"valid_auth,success\n1,yes\n"

    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("success.csv", content, content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "File uploaded successfully."
    assert body["original_filename"] == "success.csv"
    assert body["status"] == "pending"
    assert body["job_id"] > 0


# 10. Rate limiting works
def test_10_rate_limiting_works(client, user_a, settings):
    settings.UPLOAD_RATE_LIMIT_ENABLED = True
    settings.UPLOAD_RATE_LIMIT_REQUESTS = 3
    settings.UPLOAD_RATE_LIMIT_WINDOW = 60
    cache.clear()

    auth_header = basic_auth("user_a", "password_a")

    for i in range(3):
        res = client.post(
            "/api/upload/",
            {"file": SimpleUploadedFile(f"file_{i}.csv", b"x,y\n1,2\n", content_type="text/csv")},
            HTTP_AUTHORIZATION=auth_header,
        )
        assert res.status_code == 201, f"Request {i+1} failed"

    # 4th request must be rate limited with HTTP 429
    res_limited = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("file_overflow.csv", b"x,y\n1,2\n", content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert res_limited.status_code == 429
    assert "Retry-After" in res_limited
    assert "Rate limit exceeded" in res_limited.json()["error"]


# 11. Inactive users cannot upload via API
def test_11_inactive_user_cannot_upload_via_api(client, user_a):
    user_a.is_active = False
    user_a.save()

    auth_header = basic_auth("user_a", "password_a")
    response = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("inactive.csv", b"a,b\n1,2\n", content_type="text/csv")},
        HTTP_AUTHORIZATION=auth_header,
    )
    assert response.status_code == 403
    assert response.json()["error"] == "User account is disabled."


# 12. User without upload permission cannot upload
def test_12_user_without_upload_permission_is_rejected(client, user_a):
    auth_header = basic_auth("user_a", "password_a")

    with patch("processing_jobs.api_auth.can_django_user_upload", return_value=False):
        response = client.post(
            "/api/upload/",
            {"file": SimpleUploadedFile("denied.csv", b"a,b\n1,2\n", content_type="text/csv")},
            HTTP_AUTHORIZATION=auth_header,
        )
        assert response.status_code == 403
        assert response.json()["error"] == "Permission denied."


# 13. Spoofed X-Forwarded-For cannot bypass rate limiting without proxy config
def test_13_spoofed_forwarded_for_cannot_bypass_rate_limiting(client, settings):
    settings.UPLOAD_RATE_LIMIT_ENABLED = True
    settings.UPLOAD_RATE_LIMIT_REQUESTS = 2
    settings.UPLOAD_RATE_LIMIT_WINDOW = 60
    settings.SECURE_TRUST_FORWARDED_FOR = False
    cache.clear()

    # Anonymous user attempts multiple requests with spoofed X-Forwarded-For IPs
    for i in range(2):
        res = client.post(
            "/api/upload/",
            {"file": SimpleUploadedFile(f"fake_{i}.csv", b"a,b\n1,2\n", content_type="text/csv")},
            HTTP_X_FORWARDED_FOR=f"198.51.100.{i+10}",
            REMOTE_ADDR="203.0.113.5",
        )
        assert res.status_code == 401  # Rejected as anonymous, but rate limit counts the IP

    # 3rd request from same REMOTE_ADDR with a new spoofed header must be 429
    res_limited = client.post(
        "/api/upload/",
        {"file": SimpleUploadedFile("fake_overflow.csv", b"a,b\n1,2\n", content_type="text/csv")},
        HTTP_X_FORWARDED_FOR="198.51.100.99",
        REMOTE_ADDR="203.0.113.5",
    )
    assert res_limited.status_code == 429
    assert "Rate limit exceeded" in res_limited.json()["error"]


# 14. Browser upload rejects empty files (0 bytes)
def test_14_browser_upload_empty_file_rejected(client, user_a):
    client.force_login(user_a)
    upload_url = reverse("processing_jobs:upload")

    response = client.post(
        upload_url,
        {"file": SimpleUploadedFile("empty.csv", b"", content_type="text/csv")},
    )
    assert response.status_code == 200
    assert "Empty files are not allowed" in response.content.decode("utf-8")
    assert ProcessingJob.objects.filter(file_name="empty.csv").count() == 0
