"""Security Review and Permission Fixes Test Suite.

Week 4 Security Audit verification covering:
1. Unauthenticated access enforcement across views and APIs.
2. Multi-tenant user ownership and IDOR prevention (User A vs User B).
3. Report and document access controls.
4. Path traversal prevention and media confinement.
5. Symbolic link and non-regular file rejection (TOCTOU mitigation).
6. Filename sanitization against directory traversal and dot sequences.
7. Unsafe Content-Type and CRLF header injection mitigation.
8. Upload size limit handling and handler integration.
9. Sensitive information omission in logs and error responses.
10. Temporary file and extraction lifecycle security.
"""

import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import pytest

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.http import Http404
from django.urls import reverse

from processing_jobs.models import ProcessingJob
from processing_jobs.security import (
    InvalidMediaPathError,
    sanitize_error_message,
    sanitize_filename,
    serve_secure_file,
    validate_media_path,
)

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice_sec", email="alice_sec@example.com", password="password123"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob_sec", email="bob_sec@example.com", password="password123"
    )


def basic_auth(username, password="password123"):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


# ==============================================================================
# 1. Filename Sanitization & Header Injection Tests
# ==============================================================================

def test_sanitize_filename_rejects_dot_sequences_and_traversal():
    """Verify sanitize_filename blocks directory traversal, standalone dots, and trailing chars."""
    assert sanitize_filename("..") == "download"
    assert sanitize_filename(".") == "download"
    assert sanitize_filename("...") == "download"
    assert sanitize_filename("... ") == "download"
    assert sanitize_filename("..\\..\\Windows\\win.ini") == "win.ini"
    assert sanitize_filename("../../etc/shadow") == "shadow"
    assert sanitize_filename("test.pdf.") == "test.pdf"
    assert sanitize_filename("test.pdf   ") == "test.pdf"
    assert sanitize_filename("safe_document.pdf") == "safe_document.pdf"
    assert sanitize_filename("report (2026).xlsx") == "report 2026.xlsx"
    assert sanitize_filename("in\r\njection.pdf") == "injection.pdf"
    assert sanitize_filename("") == "download"
    assert sanitize_filename(None) == "download"


def test_serve_secure_file_sanitizes_crlf_in_content_type(isolated_media):
    """Verify serve_secure_file strips CRLF characters from caller-supplied content_type."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "clean_test.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    response = serve_secure_file(
        file_path="clean_test.pdf",
        download_filename="clean_test.pdf",
        content_type="application/pdf\r\nInjected-Header: evil",
        base_dir=media_dir,
    )
    assert response.status_code == 200
    assert "\r" not in response["Content-Type"]
    assert "\n" not in response["Content-Type"]
    assert "Injected-Header" not in response.headers
    assert response["X-Content-Type-Options"] == "nosniff"


def test_serve_secure_file_rejects_non_regular_file_descriptor(isolated_media, monkeypatch):
    """Verify TOCTOU race condition defense: non-regular file descriptors are rejected."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "regular.pdf"
    target.write_bytes(b"%PDF-1.4 dummy")

    from django.http import Http404

    # Simulate descriptor resolving to a FIFO / directory / pipe via fstat
    real_fstat = os.fstat

    def mock_fstat(fd):
        orig = real_fstat(fd)
        # Flip mode from S_IFREG to S_IFIFO
        class FakeStat:
            st_mode = stat.S_IFIFO | 0o644
            st_size = orig.st_size
        return FakeStat()

    monkeypatch.setattr(os, "fstat", mock_fstat)

    with pytest.raises(Http404, match="File not found"):
        serve_secure_file(
            file_path="regular.pdf",
            download_filename="regular.pdf",
            base_dir=media_dir,
        )


# ==============================================================================
# 2. Extraction Review Authentication & Object-Level Authorization
# ==============================================================================

def test_extraction_review_requires_authentication(client):
    """Anonymous access to /api/extraction-review/ redirects to login."""
    get_resp = client.get("/api/extraction-review/")
    assert get_resp.status_code == 302
    assert "/accounts/login/" in get_resp.headers["Location"]

    post_resp = client.post("/api/extraction-review/", {"job_id": "1"})
    assert post_resp.status_code == 302
    assert "/accounts/login/" in post_resp.headers["Location"]


def test_extraction_review_user_a_cannot_access_user_b_job(client, alice, bob, isolated_media):
    """User B cannot view or modify User A's extraction review job."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    doc_file = media_dir / "alice_review.pdf"
    doc_file.write_bytes(b"%PDF-1.4 dummy content")

    alice_job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_review.pdf",
        file_type="pdf",
        file_size=len(b"%PDF-1.4 dummy content"),
        storage_reference="alice_review.pdf",
        status=ProcessingJob.Status.COMPLETED,
    )

    client.force_login(bob)
    response = client.post(
        "/api/extraction-review/",
        {
            "job_id": str(alice_job.id),
            "document_name": "Tampered",
            "invoice_number": "HACKED",
            "document_date": "2026-01-01",
            "customer_name": "Intruder",
            "total_amount": "99999",
        },
    )
    assert response.status_code == 200
    assert "You cannot access this document." in response.content.decode()

    alice_job.refresh_from_db()
    assert alice_job.reviewed_data == {}


def test_extraction_review_unowned_job_cannot_be_accessed(client, alice, isolated_media):
    """Unowned/legacy jobs cannot be accessed or modified via extraction review."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    doc_file = media_dir / "legacy_review.pdf"
    doc_file.write_bytes(b"%PDF-1.4 legacy")

    legacy_job = ProcessingJob.objects.create(
        owner=None,
        file_name="legacy_review.pdf",
        file_type="pdf",
        file_size=10,
        storage_reference="legacy_review.pdf",
        status=ProcessingJob.Status.COMPLETED,
    )

    client.force_login(alice)
    response = client.post(
        "/api/extraction-review/",
        {"job_id": str(legacy_job.id)},
    )
    assert response.status_code == 200
    assert "You cannot access this document." in response.content.decode()


def test_extraction_review_invalid_job_id_handled_safely(client, alice):
    """Non-integer, negative, or non-existent job IDs return clean validation errors."""
    client.force_login(alice)

    for invalid_id in ["abc", "-1", "99999999", ""]:
        response = client.post(
            "/api/extraction-review/",
            {"job_id": invalid_id},
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Processing job not found." in content or "Invalid processing job identifier." in content


def test_extraction_review_valid_owner_can_save_review(client, alice, isolated_media, monkeypatch):
    """Owner can review and save field modifications safely."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    doc_file = media_dir / "valid_doc.pdf"
    doc_file.write_bytes(b"%PDF-1.4 test")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_doc.pdf",
        file_type="pdf",
        file_size=len(b"%PDF-1.4 test"),
        storage_reference="valid_doc.pdf",
        status=ProcessingJob.Status.COMPLETED,
    )

    # Mock text extraction to return structured text
    monkeypatch.setattr(
        "documents.views.extract_document_text",
        lambda path: {"full_text": "Invoice Number: INV-001\nTotal: 1500"},
    )

    client.force_login(alice)
    response = client.post(
        "/api/extraction-review/",
        {
            "job_id": str(job.id),
            "document_name": "valid_doc.pdf",
            "invoice_number": "INV-001",
            "document_date": "2026-05-15",
            "customer_name": "Acme Corp",
            "total_amount": "1500.00",
        },
    )
    assert response.status_code == 200
    assert "Reviewed data saved successfully." in response.content.decode()

    job.refresh_from_db()
    assert job.reviewed_data["invoice_number"] == "INV-001"
    assert job.reviewed_data["total_amount"] == "1500.00"


# ==============================================================================
# 3. Extract API Authentication & Path Disclosure Tests
# ==============================================================================

def test_extract_file_api_requires_authentication(client):
    """POST /api/extract/ rejects unauthenticated requests with 401."""
    pdf_content = b"%PDF-1.4 minimal"
    response = client.post(
        "/api/extract/",
        {"file": SimpleUploadedFile("doc.pdf", pdf_content, content_type="application/pdf")},
    )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response


def test_extract_file_api_filenotfound_does_not_leak_server_paths(client, alice, monkeypatch):
    """Verify FileNotFoundError does not expose internal server filesystem paths."""
    auth_hdr = basic_auth("alice_sec", "password123")

    def mock_extract(path):
        raise FileNotFoundError(r"C:\SecretInternal\Backend\documents\temp1234\document.pdf")

    monkeypatch.setattr("documents.views.extract_document_text", mock_extract)

    response = client.post(
        "/api/extract/",
        {"file": SimpleUploadedFile("doc.pdf", b"%PDF-1.4 valid", content_type="application/pdf")},
        HTTP_AUTHORIZATION=auth_hdr,
    )
    assert response.status_code == 400
    data = response.json()
    assert "SecretInternal" not in data["error"]
    assert "temp1234" not in data["error"]
    assert data["error"] == "Requested file could not be found."


# ==============================================================================
# 4. Browser Upload Size Exceeded Handling
# ==============================================================================

def test_browser_upload_too_large_handled_gracefully(client, alice):
    """Verify browser upload handles request.upload_too_large with clear 10 MB rejection."""
    client.force_login(alice)

    # Simulate LimitUploadSizeHandler marking upload_too_large
    with pytest.MonkeyPatch.context() as m:
        from django.core.handlers.wsgi import WSGIRequest
        orig_get = WSGIRequest.FILES.fget

        def mock_files(self):
            self.upload_too_large = True
            return orig_get(self)

        m.setattr(WSGIRequest, "FILES", property(mock_files))

        response = client.post(
            reverse("processing_jobs:upload_document"),
            {"file": SimpleUploadedFile("oversized.csv", b"a" * 100, content_type="text/csv")},
        )
        assert response.status_code == 200
        assert "File size must not exceed 10 MB." in response.content.decode()


# ==============================================================================
# 5. Result Download MIME & Security Headers
# ==============================================================================

def test_download_result_sets_nosniff_header(client, alice, isolated_media):
    """Verify download_result sets X-Content-Type-Options: nosniff."""
    media_dir = Path(isolated_media)
    extracted_dir = media_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="invoice.csv",
        file_type="csv",
        file_size=50,
        status=ProcessingJob.Status.COMPLETED,
    )
    result_file = extracted_dir / f"job_{job.id}.json"
    result_file.write_text('{"status": "ok"}', encoding="utf-8")

    client.force_login(alice)
    response = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Type"] == "application/json"


# ==============================================================================
# 6. Django Settings Security Hardening Verification
# ==============================================================================

def test_cookie_and_frame_security_settings():
    """Verify security settings: SESSION_COOKIE_HTTPONLY is True and X_FRAME_OPTIONS is DENY."""
    assert getattr(settings, "SESSION_COOKIE_HTTPONLY", False) is True
    assert getattr(settings, "X_FRAME_OPTIONS", "") == "DENY"


# ==============================================================================
# 7. TOCTOU & Descriptor Confinement Tests
# ==============================================================================

def test_serve_secure_file_rejects_descriptor_escaping_permitted_root(isolated_media, monkeypatch, tmp_path):
    """Verify TOCTOU defense: open file descriptor pointing outside permitted root is rejected."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "confined.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(b"%PDF-1.4 malicious outside file")

    # Simulate descriptor resolving to outside_file via _get_descriptor_path
    monkeypatch.setattr(
        "processing_jobs.security._get_descriptor_path",
        lambda handle: outside_file.resolve(),
    )

    with pytest.raises(Http404, match="File not found"):
        serve_secure_file(
            file_path="confined.pdf",
            download_filename="confined.pdf",
            base_dir=media_dir,
        )


def test_serve_secure_file_rejects_descriptor_identity_mismatch(isolated_media, monkeypatch):
    """Verify TOCTOU defense: os.path.samestat mismatch between path and opened fd is rejected."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "target.pdf"
    target.write_bytes(b"%PDF-1.4 valid")

    # Simulate TOCTOU swap where opened descriptor is a different file (samestat returns False)
    monkeypatch.setattr(os.path, "samestat", lambda stat1, stat2: False)

    with pytest.raises(Http404, match="File not found"):
        serve_secure_file(
            file_path="target.pdf",
            download_filename="target.pdf",
            base_dir=media_dir,
        )


def test_serve_secure_file_confines_legitimate_descriptor(isolated_media):
    """Verify legitimate file descriptor inside MEDIA_ROOT is verified and served with 200."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "safe.pdf"
    target.write_bytes(b"%PDF-1.4 legitimate")

    response = serve_secure_file(
        file_path="safe.pdf",
        download_filename="safe.pdf",
        base_dir=media_dir,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["X-Content-Type-Options"] == "nosniff"
    response.close()


def test_serve_secure_file_fails_closed_when_descriptor_resolution_returns_none(isolated_media, monkeypatch):
    """Verify fail-closed defense: if descriptor-path resolution returns None, serve_secure_file raises Http404."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "safe.pdf"
    target.write_bytes(b"%PDF-1.4 legitimate")

    # Force descriptor resolution to return None (simulating unsupported or failed kernel query)
    monkeypatch.setattr(
        "processing_jobs.security._get_descriptor_path",
        lambda handle: None,
    )

    with pytest.raises(Http404, match="File not found"):
        serve_secure_file(
            file_path="safe.pdf",
            download_filename="safe.pdf",
            base_dir=media_dir,
        )


# ==============================================================================
# 8. Content-Type Whitelisting & Malformed Input Handling
# ==============================================================================

def test_serve_secure_file_rejects_malformed_and_untrusted_content_types(isolated_media):
    """Verify untrusted/malformed content types fall back to trusted CONTENT_TYPE_MAPPING."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "document.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    untrusted_types = [
        "text/html",
        "<script>alert(1)</script>",
        "application/x-sh",
        "random/untrusted-type",
        "application/pdf\r\nInjected-Header: evil",
        "text/html; charset=utf-8",
    ]

    for untrusted in untrusted_types:
        response = serve_secure_file(
            file_path="document.pdf",
            download_filename="document.pdf",
            content_type=untrusted,
            base_dir=media_dir,
        )
        assert response.status_code == 200
        # Untrusted type must be rejected and replaced by safe mapping for .pdf
        assert response["Content-Type"] == "application/pdf"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "Injected-Header" not in response.headers
        response.close()


def test_serve_secure_file_accepts_whitelisted_content_types(isolated_media):
    """Verify whitelisted Content-Types are accepted and served."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target_csv = media_dir / "data.csv"
    target_csv.write_text("a,b,c\n1,2,3", encoding="utf-8")

    response = serve_secure_file(
        file_path="data.csv",
        download_filename="data.csv",
        content_type="text/csv; charset=utf-8",
        base_dir=media_dir,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["X-Content-Type-Options"] == "nosniff"
    response.close()


# ==============================================================================
# 9. Exception Information Disclosure & Path Sanitization
# ==============================================================================

def test_download_result_failure_stores_generic_error_message(client, alice, isolated_media, monkeypatch):
    """Verify download_result extraction failure stores a generic user-facing error message without path disclosure."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    doc_file = media_dir / "fail_doc.pdf"
    doc_file.write_bytes(b"%PDF-1.4 content")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="fail_doc.pdf",
        file_type="pdf",
        file_size=len(b"%PDF-1.4 content"),
        storage_reference="fail_doc.pdf",
        status=ProcessingJob.Status.PENDING,
    )

    def mock_extract_fail(file_data, filename):
        raise RuntimeError(r"Internal crash at C:\inetpub\wwwroot\media\confidential\raw.pdf")

    monkeypatch.setattr("processing_jobs.views.extract_document", mock_extract_fail)

    client.force_login(alice)
    response = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 404

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.FAILED
    assert job.error_message == "Document extraction failed. Please verify the file and try again."
    assert "inetpub" not in job.error_message
    assert "confidential" not in job.error_message
    assert "Internal crash" not in job.error_message


def test_sanitize_error_message_strips_internal_paths():
    """Verify sanitize_error_message replaces server directories and drive letters."""
    raw_error_win = r"Failed to process C:\Server\Confidential\backend\data\invoice.pdf: parsing error"
    clean_win = sanitize_error_message(raw_error_win)
    assert "C:\\Server" not in clean_win
    assert "Confidential" not in clean_win
    assert clean_win == "Failed to process invoice.pdf: parsing error"

    raw_error_nix = "/var/www/internal/app/documents/receipt.pdf not found"
    clean_nix = sanitize_error_message(raw_error_nix)
    assert "/var/www" not in clean_nix
    assert clean_nix == "receipt.pdf not found"


def test_sanitize_error_message_handles_spaces_unc_and_tracebacks():
    """Verify sanitize_error_message removes paths with spaces, UNC network paths, and tracebacks."""
    # Windows path with spaces and special characters
    raw_win_spaces = r"Error opening C:\Users\HP\My Documents\client data (2026)\report_v1.pdf: permission denied"
    clean_win = sanitize_error_message(raw_win_spaces)
    assert "C:\\Users" not in clean_win
    assert "My Documents" not in clean_win
    assert clean_win == "Error opening report_v1.pdf: permission denied"

    # UNC network path with spaces
    raw_unc = r"Unable to read \\fileserver.corp\shared finance\secret payroll\summary.xlsx: IO error"
    clean_unc = sanitize_error_message(raw_unc)
    assert "\\\\fileserver.corp" not in clean_unc
    assert "secret payroll" not in clean_unc
    assert clean_unc == "Unable to read summary.xlsx: IO error"

    # Unix path with spaces and unusual characters
    raw_unix_spaces = "/opt/backend apps/storage/user uploads (tmp)/scan_01.png is corrupted"
    clean_unix = sanitize_error_message(raw_unix_spaces)
    assert "/opt/backend" not in clean_unix
    assert clean_unix == "scan_01.png is corrupted"

    # Raw unhandled Python traceback falls back to generic user message
    raw_traceback = (
        "Traceback (most recent call last):\n"
        '  File "C:\\inetpub\\wwwroot\\app\\views.py", line 45, in extract\n'
        "    raise OSError('Database disk image is malformed')\n"
        "OSError: Database disk image is malformed"
    )
    clean_tb = sanitize_error_message(raw_traceback)
    assert "Traceback" not in clean_tb
    assert "inetpub" not in clean_tb
    assert clean_tb == "An error occurred while processing the document."


def test_job_detail_api_does_not_leak_internal_paths(client, alice):
    """Verify job_detail_api does not disclose raw internal paths in error_message."""
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="test.pdf",
        file_type="pdf",
        file_size=100,
        storage_reference="test.pdf",
        status=ProcessingJob.Status.FAILED,
        error_message="Document extraction failed. Please verify the file and try again.",
    )

    client.force_login(alice)
    response = client.get(reverse("processing_jobs:api_job_detail", kwargs={"job_id": job.id}))
    assert response.status_code == 200
    data = response.json()
    assert data["error_message"] == "Document extraction failed. Please verify the file and try again."
    assert "C:\\" not in data["error_message"]
    assert "/var/" not in data["error_message"]


# ==============================================================================
# 10. Symlink Rejection & Temporary File Lifecycle Tests
# ==============================================================================

def test_validate_media_path_rejects_symbolic_link(isolated_media, monkeypatch):
    """Verify validate_media_path deterministically detects and rejects symbolic links."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "symlink_test.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "symlink_test.pdf")

    with pytest.raises(InvalidMediaPathError, match="Symbolic links are not permitted"):
        validate_media_path("symlink_test.pdf", base_dir=media_dir)


def test_serve_secure_file_rejects_symbolic_link(isolated_media, monkeypatch):
    """Verify serve_secure_file rejects symbolic links with Http404."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "symlink_file.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "symlink_file.pdf")

    with pytest.raises(Http404, match="File not found"):
        serve_secure_file(
            file_path="symlink_file.pdf",
            download_filename="symlink_file.pdf",
            base_dir=media_dir,
        )


def test_extract_api_temporary_directory_cleaned_up_on_success(client, alice, monkeypatch):
    """Verify /api/extract/ cleans up temporary directory after successful extraction."""
    created_dirs = []
    real_tempdir = tempfile.TemporaryDirectory

    class TrackedTempDir:
        def __init__(self, *args, **kwargs):
            self._td = real_tempdir(*args, **kwargs)
            created_dirs.append(Path(self._td.name))

        def __enter__(self):
            return self._td.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._td.__exit__(exc_type, exc_val, exc_tb)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", TrackedTempDir)
    monkeypatch.setattr(
        "documents.views.extract_document_text",
        lambda path: {"invoice_number": "INV-101"},
    )

    auth_hdr = basic_auth("alice_sec", "password123")
    response = client.post(
        "/api/extract/",
        {"file": SimpleUploadedFile("clean.pdf", b"%PDF-1.4 sample", content_type="application/pdf")},
        HTTP_AUTHORIZATION=auth_hdr,
    )
    assert response.status_code == 200
    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()


def test_extract_api_temporary_directory_cleaned_up_on_failure(client, alice, monkeypatch):
    """Verify /api/extract/ cleans up temporary directory after extraction failure."""
    created_dirs = []
    real_tempdir = tempfile.TemporaryDirectory

    class TrackedTempDir:
        def __init__(self, *args, **kwargs):
            self._td = real_tempdir(*args, **kwargs)
            created_dirs.append(Path(self._td.name))

        def __enter__(self):
            return self._td.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._td.__exit__(exc_type, exc_val, exc_tb)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", TrackedTempDir)

    def mock_broken_extract(path):
        raise ValueError("Corrupt PDF structure")

    monkeypatch.setattr("documents.views.extract_document_text", mock_broken_extract)

    auth_hdr = basic_auth("alice_sec", "password123")
    response = client.post(
        "/api/extract/",
        {"file": SimpleUploadedFile("broken.pdf", b"%PDF-1.4 sample", content_type="application/pdf")},
        HTTP_AUTHORIZATION=auth_hdr,
    )
    assert response.status_code == 400
    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()


def test_extraction_review_uploaded_file_cleaned_up_on_extraction_failure(client, alice, isolated_media, monkeypatch):
    """Verify /api/extraction-review/ unlinks uploaded file if extraction fails."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    initial_files = set(media_dir.iterdir())

    def mock_failing_extract(path):
        raise RuntimeError("Extractor crashed unexpectedly")

    monkeypatch.setattr("documents.views.extract_document_text", mock_failing_extract)

    client.force_login(alice)
    response = client.post(
        "/api/extraction-review/",
        {"file": SimpleUploadedFile("fail.pdf", b"%PDF-1.4 sample", content_type="application/pdf")},
    )
    assert response.status_code == 200
    assert "Document extraction failed." in response.content.decode()

    # The uploaded file must have been unlinked
    final_files = set(media_dir.iterdir())
    assert initial_files == final_files


def test_services_ingest_document_cleans_up_on_database_error(isolated_media, monkeypatch, alice):
    """Verify ingest_document unlinks uploaded file if job database creation fails."""
    from processing_jobs.services import ingest_document

    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    initial_files = set(media_dir.iterdir())

    def mock_db_error(*args, **kwargs):
        raise DatabaseError("Simulated database failure during job creation")

    monkeypatch.setattr(ProcessingJob.objects, "create", mock_db_error)

    uploaded_file = SimpleUploadedFile("ingest_fail.pdf", b"%PDF-1.4 content", content_type="application/pdf")

    with pytest.raises(DatabaseError, match="Simulated database failure"):
        ingest_document(
            uploaded_file=uploaded_file,
            original_filename="ingest_fail.pdf",
            owner=alice,
        )

    # File must be cleaned up on error
    final_files = set(media_dir.iterdir())
    assert initial_files == final_files
