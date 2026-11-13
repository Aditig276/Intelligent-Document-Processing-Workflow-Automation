"""Week 3 Report Access Control & Authorization Test Suite.

Project: Intelligent Document Processing & Workflow Automation
Assigned Module: Report Access Control (Member 4 - Brijesh)
Branch: feature/report-access-control

Test Coverage:
- A. Authentication tests (Anonymous/Inactive vs Authenticated Users)
- B. Report permission tests (Excel and PDF report protection, IDOR prevention)
- C. Source-document permission tests (Original file protection, path traversal)
- D. Processing history tests (UI and API multi-tenant isolation, filtering, pagination)
- E. Authorization edge cases (Unowned legacy jobs, invalid IDs, malformed inputs)
"""

import base64
import json
import os
from pathlib import Path
import pytest
from django.conf import settings
from django.db import DatabaseError
from django.urls import reverse

from processing_jobs.models import ProcessingJob
from processing_jobs.reports import (
    normalize_report_type,
    register_report_resolver,
    resolve_report_for_job,
    unregister_report_resolver,
)
from processing_jobs.security import (
    InvalidMediaPathError,
    get_validated_extracted_result_path,
    sanitize_filename,
    serve_secure_file,
    validate_media_path,
)

pytestmark = [pytest.mark.django_db]


# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------

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


@pytest.fixture
def inactive_user(django_user_model):
    return django_user_model.objects.create_user(
        username="charlie", email="charlie@example.com", password="password123", is_active=False
    )


def basic_auth_header(username, password="password123"):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


@pytest.fixture
def alice_job_with_files(alice, isolated_media):
    """Create Alice's job with uploaded document, excel report, and pdf report."""
    media_dir = Path(isolated_media)
    reports_dir = media_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Source document file
    source_filename = "uuid_alice_source.csv"
    source_file = media_dir / source_filename
    source_file.write_bytes(b"id,val\n1,100\n")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_original.csv",
        file_type="csv",
        file_size=len("id,val\n1,100\n"),
        storage_reference=source_filename,
        status=ProcessingJob.Status.COMPLETED,
    )

    # 2. Generated Excel report
    excel_file = reports_dir / f"job_{job.id}_report.xlsx"
    excel_file.write_bytes(b"PK\x03\x04fake_excel_binary_content")

    # 3. Generated PDF summary
    pdf_file = reports_dir / f"job_{job.id}_summary.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake_pdf_binary_content")

    return job


@pytest.fixture
def bob_job_with_files(bob, isolated_media):
    """Create Bob's job with uploaded document, excel report, and pdf report."""
    media_dir = Path(isolated_media)
    reports_dir = media_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    source_filename = "uuid_bob_source.pdf"
    source_file = media_dir / source_filename
    source_file.write_bytes(b"%PDF-1.4 bob_source_doc")

    job = ProcessingJob.objects.create(
        owner=bob,
        file_name="bob_sensitive.pdf",
        file_type="pdf",
        file_size=len(b"%PDF-1.4 bob_source_doc"),
        storage_reference=source_filename,
        status=ProcessingJob.Status.COMPLETED,
    )

    excel_file = reports_dir / f"job_{job.id}_report.xlsx"
    excel_file.write_bytes(b"PK\x03\x04bob_excel_binary")

    pdf_file = reports_dir / f"job_{job.id}_summary.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 bob_pdf_binary")

    return job


# ------------------------------------------------------------------------------
# A. Authentication Tests
# ------------------------------------------------------------------------------

def test_a1_anonymous_user_cannot_download_reports(client, alice_job_with_files):
    """Anonymous browser requests to download reports must be redirected to login."""
    # Excel report
    resp_excel = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert resp_excel.status_code == 302
    assert "/accounts/login/" in resp_excel.headers.get("Location", "")

    # PDF report
    resp_pdf = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "pdf"})
    )
    assert resp_pdf.status_code == 302
    assert "/accounts/login/" in resp_pdf.headers.get("Location", "")


def test_a2_anonymous_user_cannot_download_source_documents(client, alice_job_with_files):
    """Anonymous browser requests to download source documents must redirect to login."""
    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


def test_a3_anonymous_user_cannot_access_processing_history(client):
    """Anonymous browser request to dashboard redirects to login; API returns 401."""
    # Browser
    resp_ui = client.get(reverse("processing_jobs:dashboard"))
    assert resp_ui.status_code == 302
    assert "/accounts/login/" in resp_ui.headers.get("Location", "")

    # API
    resp_api = client.get(reverse("processing_jobs:api_processing_history"))
    assert resp_api.status_code == 401
    assert "error" in resp_api.json()


def test_a4_authenticated_authorized_user_can_access_permitted_resources(client, alice, alice_job_with_files):
    """An authenticated owner can access their own document, reports, and history."""
    client.force_login(alice)

    # 1. Dashboard history
    resp_dash = client.get(reverse("processing_jobs:dashboard"))
    assert resp_dash.status_code == 200
    assert alice_job_with_files in resp_dash.context["jobs"]

    # 2. Source document download
    resp_doc = client.get(reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id}))
    assert resp_doc.status_code == 200
    assert resp_doc.getvalue() == b"id,val\n1,100\n"

    # 3. Excel report download
    resp_excel = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert resp_excel.status_code == 200
    assert resp_excel.getvalue() == b"PK\x03\x04fake_excel_binary_content"

    # 4. PDF report download
    resp_pdf = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "pdf"})
    )
    assert resp_pdf.status_code == 200
    assert resp_pdf.getvalue() == b"%PDF-1.4 fake_pdf_binary_content"


# ------------------------------------------------------------------------------
# B. Report Permission Tests
# ------------------------------------------------------------------------------

def test_b1_report_owner_can_download_own_excel_report(client, alice, alice_job_with_files):
    """Alice can download her own generated Excel report."""
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in response.headers["Content-Disposition"]
    assert f"job_{alice_job_with_files.id}_report.xlsx" in response.headers["Content-Disposition"]
    assert response.getvalue() == b"PK\x03\x04fake_excel_binary_content"


def test_b2_report_owner_can_download_own_pdf_report(client, alice, alice_job_with_files):
    """Alice can download her own generated PDF report."""
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "pdf"})
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/pdf"
    assert "attachment" in response.headers["Content-Disposition"]
    assert f"job_{alice_job_with_files.id}_summary.pdf" in response.headers["Content-Disposition"]
    assert response.getvalue() == b"%PDF-1.4 fake_pdf_binary_content"


def test_b3_user_a_cannot_download_user_b_excel_report(client, bob, alice_job_with_files):
    """Bob cannot download Alice's Excel report (returns 404 to avoid leaking existence)."""
    client.force_login(bob)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert response.status_code == 404


def test_b4_user_a_cannot_download_user_b_pdf_report(client, bob, alice_job_with_files):
    """Bob cannot download Alice's PDF report."""
    client.force_login(bob)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "pdf"})
    )
    assert response.status_code == 404


def test_b5_changing_report_id_does_not_bypass_ownership(client, bob, alice_job_with_files, bob_job_with_files):
    """Bob attempting IDOR by swapping job ID in report URL gets 404 for Alice's report."""
    client.force_login(bob)

    # Bob accesses his own report: OK
    resp_bob = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": bob_job_with_files.id, "report_type": "excel"})
    )
    assert resp_bob.status_code == 200

    # Bob changes job_id to Alice's: Denied (404)
    resp_tamper = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert resp_tamper.status_code == 404


def test_b6_missing_report_file_handled_safely(client, alice, alice_job_with_files, isolated_media):
    """When report is not yet generated or file is missing on disk, return safe 404."""
    client.force_login(alice)

    # Delete the excel file
    excel_file = Path(isolated_media) / "reports" / f"job_{alice_job_with_files.id}_report.xlsx"
    excel_file.unlink(missing_ok=True)

    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"})
    )
    assert response.status_code == 404


def test_b7_invalid_report_type_handled_safely(client, alice, alice_job_with_files):
    """Requesting an unsupported report type (e.g., 'exe', 'docx') safely returns 404."""
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "malicious"})
    )
    assert response.status_code == 404


def test_b8_invalid_job_id_handled_safely(client, alice):
    """Non-existent job ID returns 404."""
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": 999999, "report_type": "excel"})
    )
    assert response.status_code == 404


# ------------------------------------------------------------------------------
# C. Source-Document Permission Tests
# ------------------------------------------------------------------------------

def test_c1_document_owner_can_access_own_source_document(client, alice, alice_job_with_files):
    """Alice can download her own original source document with correct filename."""
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert response.status_code == 200
    assert response.getvalue() == b"id,val\n1,100\n"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "alice_original.csv" in response.headers["Content-Disposition"]


def test_c2_user_a_cannot_download_user_b_source_document(client, bob, alice_job_with_files):
    """Bob cannot access Alice's source document."""
    client.force_login(bob)
    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert response.status_code == 404


def test_c3_anonymous_user_cannot_download_protected_document(client, alice_job_with_files):
    """Anonymous user is redirected to login when trying to download document."""
    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers["Location"]


def test_c4_changing_document_id_does_not_bypass_ownership(client, bob, alice_job_with_files, bob_job_with_files):
    """Manipulating the job ID in source document URL fails."""
    client.force_login(bob)
    # Bob's own doc: 200
    resp_bob = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": bob_job_with_files.id})
    )
    assert resp_bob.status_code == 200

    # Alice's doc: 404
    resp_alice = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert resp_alice.status_code == 404


def test_c5_missing_source_file_handled_safely(client, alice, alice_job_with_files, isolated_media):
    """If stored source file was removed or missing on disk, return 404."""
    client.force_login(alice)
    source_file = Path(isolated_media) / alice_job_with_files.storage_reference
    source_file.unlink(missing_ok=True)

    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": alice_job_with_files.id})
    )
    assert response.status_code == 404


def test_c6_path_traversal_in_storage_reference_prevented(client, alice, isolated_media):
    """Path traversal sequences (e.g. ../../etc/passwd) in storage_reference are blocked."""
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="traversal_test.csv",
        file_type="csv",
        storage_reference="../../secret.txt",
        status=ProcessingJob.Status.COMPLETED,
    )
    client.force_login(alice)
    response = client.get(
        reverse("processing_jobs:download_document", kwargs={"job_id": job.id})
    )
    assert response.status_code == 404


# ------------------------------------------------------------------------------
# D. Processing History Tests
# ------------------------------------------------------------------------------

def test_d1_user_can_access_own_processing_history(client, alice, alice_job_with_files):
    """Alice sees only her jobs on the dashboard."""
    client.force_login(alice)
    response = client.get(reverse("processing_jobs:dashboard"))
    assert response.status_code == 200
    assert alice_job_with_files in response.context["jobs"]


def test_d2_user_cannot_see_other_user_processing_history(client, bob, alice_job_with_files, bob_job_with_files):
    """Bob's dashboard contains Bob's jobs and never Alice's jobs."""
    client.force_login(bob)
    response = client.get(reverse("processing_jobs:dashboard"))
    assert response.status_code == 200
    assert bob_job_with_files in response.context["jobs"]
    assert alice_job_with_files not in response.context["jobs"]
    assert alice_job_with_files.file_name not in response.content.decode("utf-8")


def test_d3_user_cannot_access_other_user_job_detail(client, bob, alice_job_with_files):
    """Bob cannot access job_detail for Alice's job."""
    client.force_login(bob)
    response = client.get(reverse("processing_jobs:job_detail", kwargs={"job_id": alice_job_with_files.id}))
    assert response.status_code == 404


def test_d4_processing_history_api_multi_tenant_isolation(client, alice, bob, alice_job_with_files, bob_job_with_files):
    """API endpoint /api/jobs/ returns only the authenticated user's records."""
    headers = {"HTTP_AUTHORIZATION": basic_auth_header("alice", "password123")}
    response = client.get(reverse("processing_jobs:api_processing_history"), **headers)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    job_ids = [j["id"] for j in data["results"]]
    assert alice_job_with_files.id in job_ids
    assert bob_job_with_files.id not in job_ids


def test_d5_processing_history_api_pagination_and_filtering(client, alice):
    """API pagination and filtering are strictly scoped to the owner."""
    # Create 5 pending CSVs and 3 completed PDFs for Alice
    for i in range(5):
        ProcessingJob.objects.create(
            owner=alice,
            file_name=f"alice_{i}.csv",
            file_type="csv",
            status=ProcessingJob.Status.PENDING,
        )
    for i in range(3):
        ProcessingJob.objects.create(
            owner=alice,
            file_name=f"alice_{i}.pdf",
            file_type="pdf",
            status=ProcessingJob.Status.COMPLETED,
        )

    headers = {"HTTP_AUTHORIZATION": basic_auth_header("alice", "password123")}

    # Filter by status=completed
    resp_status = client.get(
        reverse("processing_jobs:api_processing_history") + "?status=completed",
        **headers,
    )
    assert resp_status.status_code == 200
    assert resp_status.json()["count"] == 3

    # Filter by file_type=csv
    resp_type = client.get(
        reverse("processing_jobs:api_processing_history") + "?file_type=csv",
        **headers,
    )
    assert resp_type.status_code == 200
    assert resp_type.json()["count"] == 5

    # Pagination: page_size=2
    resp_page = client.get(
        reverse("processing_jobs:api_processing_history") + "?page=1&page_size=2",
        **headers,
    )
    assert resp_page.status_code == 200
    assert len(resp_page.json()["results"]) == 2
    assert resp_page.json()["count"] == 8


def test_d6_single_job_api_detail_multi_tenant_isolation(client, bob, alice_job_with_files, bob_job_with_files):
    """Bob can read his own job via API, but gets 404 when querying Alice's job."""
    headers = {"HTTP_AUTHORIZATION": basic_auth_header("bob", "password123")}

    # Own job: 200
    resp_bob = client.get(
        reverse("processing_jobs:api_job_detail", kwargs={"job_id": bob_job_with_files.id}),
        **headers,
    )
    assert resp_bob.status_code == 200
    assert resp_bob.json()["id"] == bob_job_with_files.id

    # Alice's job: 404
    resp_alice = client.get(
        reverse("processing_jobs:api_job_detail", kwargs={"job_id": alice_job_with_files.id}),
        **headers,
    )
    assert resp_alice.status_code == 404


def test_d7_api_download_endpoints_multi_tenant_isolation(client, bob, alice_job_with_files):
    """API endpoints for document and report downloads enforce multi-tenant isolation."""
    headers = {"HTTP_AUTHORIZATION": basic_auth_header("bob", "password123")}

    # API document download for Alice's job -> 404
    resp_doc = client.get(
        reverse("processing_jobs:api_download_document", kwargs={"job_id": alice_job_with_files.id}),
        **headers,
    )
    assert resp_doc.status_code == 404

    # API report download for Alice's job -> 404
    resp_report = client.get(
        reverse("processing_jobs:api_download_report", kwargs={"job_id": alice_job_with_files.id, "report_type": "excel"}),
        **headers,
    )
    assert resp_report.status_code == 404


# ------------------------------------------------------------------------------
# E. Authorization Edge Cases
# ------------------------------------------------------------------------------

def test_e1_unowned_legacy_job_is_inaccessible_to_any_user(client, alice):
    """Legacy jobs with owner=None cannot be viewed or downloaded by normal users."""
    job = ProcessingJob.objects.create(
        owner=None,
        file_name="legacy_unowned.csv",
        file_type="csv",
        status=ProcessingJob.Status.COMPLETED,
    )
    client.force_login(alice)

    # Dashboard: not visible
    resp_dash = client.get(reverse("processing_jobs:dashboard"))
    assert job not in resp_dash.context["jobs"]

    # Detail: 404
    resp_detail = client.get(reverse("processing_jobs:job_detail", kwargs={"job_id": job.id}))
    assert resp_detail.status_code == 404

    # Source document download: 404
    resp_doc = client.get(reverse("processing_jobs:download_document", kwargs={"job_id": job.id}))
    assert resp_doc.status_code == 404

    # Report download: 404
    resp_report = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": job.id, "report_type": "excel"})
    )
    assert resp_report.status_code == 404


def test_e2_inactive_user_is_denied_access_everywhere(client, inactive_user, alice_job_with_files):
    """Inactive users are denied API and view access."""
    headers = {"HTTP_AUTHORIZATION": basic_auth_header("charlie", "password123")}

    # API history
    resp_history = client.get(reverse("processing_jobs:api_processing_history"), **headers)
    assert resp_history.status_code == 403

    # API upload
    resp_upload = client.post(reverse("processing_jobs:api_upload"), **headers)
    assert resp_upload.status_code == 403


def test_e3_sanitize_filename_utility():
    """Verify filename sanitization removes headers injection and path traversal characters."""
    assert sanitize_filename("safe.pdf") == "safe.pdf"
    assert sanitize_filename("../../malicious.pdf") == "malicious.pdf"
    assert sanitize_filename('test\r\nSet-Cookie: evil="1".pdf') == "testSet-Cookie evil1.pdf"
    assert sanitize_filename("") == "download"


def test_e4_custom_report_resolver_integration(alice_job_with_files, isolated_media):
    """Verify the pluggable report resolver interface contract."""
    test_pdf = Path(isolated_media) / "custom_location.pdf"
    test_pdf.write_bytes(b"%PDF-1.4 custom_report")

    def mock_resolver(job, canonical_type):
        if canonical_type == "pdf":
            return test_pdf
        return None

    register_report_resolver(mock_resolver)
    try:
        path, fname, mime = resolve_report_for_job(alice_job_with_files, "pdf")
        assert path == test_pdf.resolve()
        assert mime == "application/pdf"
    finally:
        unregister_report_resolver(mock_resolver)


# ------------------------------------------------------------------------------
# F. Path Confinement, Symlink Escape, Report Resolver & Exception Tests
# ------------------------------------------------------------------------------

def _create_symlink_or_skip(link_path: Path, target_path: Path, target_is_directory: bool = False) -> None:
    """Create a symlink for testing, skipping if the OS/user lacks symlink privileges."""
    try:
        os.symlink(target_path, link_path, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation not supported in this environment: {exc}")


def test_f1_validate_media_path_accepts_valid_files_inside_media_root(isolated_media):
    """Valid relative and absolute paths confined to MEDIA_ROOT succeed."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    sample = media_dir / "uploads" / "valid.csv"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("col\n1\n", encoding="utf-8")

    assert validate_media_path("uploads/valid.csv") == sample.resolve()
    assert validate_media_path(sample) == sample.resolve()


def test_f2_validate_media_path_rejects_outside_traversal_missing_and_directories(isolated_media, tmp_path):
    """Paths outside MEDIA_ROOT, traversals, missing files, and directories are rejected."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    subdir = media_dir / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)

    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    # Outside absolute path
    with pytest.raises(InvalidMediaPathError):
        validate_media_path(outside_file)

    # Parent directory traversal
    with pytest.raises(InvalidMediaPathError):
        validate_media_path("../outside_secret.txt")

    # Missing file
    with pytest.raises(InvalidMediaPathError):
        validate_media_path("missing.csv")

    # Directory instead of file
    with pytest.raises(InvalidMediaPathError):
        validate_media_path("subdir")


def test_f3_download_result_valid_pending_and_completed_json_owner_vs_non_owner(client, alice, bob, isolated_media):
    """Owner can download valid on-demand and pre-extracted JSON; non-owner gets 404."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "alice_data.csv"
    src.write_bytes(b"name,amount\nAcme,100\n")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_data.csv",
        file_type="csv",
        file_size=src.stat().st_size,
        storage_reference="alice_data.csv",
        status=ProcessingJob.Status.PENDING,
    )

    # Non-owner denied (404)
    client.force_login(bob)
    resp_bob = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))
    assert resp_bob.status_code == 404

    # Owner succeeds on pending job (on-demand extraction + confined write + JSON response)
    client.force_login(alice)
    resp_alice = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))
    assert resp_alice.status_code == 200
    assert resp_alice["Content-Type"] == "application/json"
    assert f'filename="job_{job.id}_extraction.json"' in resp_alice["Content-Disposition"]
    payload = json.loads(resp_alice.content)
    assert payload["row_count"] == 1
    assert (media_dir / "extracted" / f"job_{job.id}.json").is_file()

    # Owner succeeds again now that job is completed
    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED
    resp_again = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))
    assert resp_again.status_code == 200
    assert json.loads(resp_again.content)["row_count"] == 1


def test_f4_download_result_rejects_traversal_and_absolute_paths_outside_media_root(client, alice, isolated_media, tmp_path):
    """download_result must never read source files via traversal or arbitrary absolute paths."""
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)

    outside_csv = tmp_path / "outside_sensitive.csv"
    outside_csv.write_bytes(b"secret,token\n1,TOP_SECRET_DATA\n")

    job_traversal = ProcessingJob.objects.create(
        owner=alice,
        file_name="evil.csv",
        file_type="csv",
        storage_reference="../outside_sensitive.csv",
        status=ProcessingJob.Status.PENDING,
    )
    job_abs = ProcessingJob.objects.create(
        owner=alice,
        file_name="evil_abs.csv",
        file_type="csv",
        storage_reference=str(outside_csv),
        status=ProcessingJob.Status.PENDING,
    )

    client.force_login(alice)

    resp_trav = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_traversal.id}))
    assert resp_trav.status_code == 404
    assert not (media_dir / "extracted" / f"job_{job_traversal.id}.json").exists()

    resp_abs = client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_abs.id}))
    assert resp_abs.status_code == 404
    assert not (media_dir / "extracted" / f"job_{job_abs.id}.json").exists()


def test_f5_download_result_rejects_missing_directory_and_corrupt_json(client, alice, isolated_media):
    """download_result rejects missing source/result files, directories, and invalid JSON."""
    media_dir = Path(isolated_media)
    extracted_dir = media_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pending job with missing source file
    job_missing_src = ProcessingJob.objects.create(
        owner=alice,
        file_name="missing.csv",
        file_type="csv",
        storage_reference="does_not_exist.csv",
        status=ProcessingJob.Status.PENDING,
    )

    # 2. Pending job pointing to a directory instead of a regular file
    src_dir = media_dir / "some_dir"
    src_dir.mkdir(parents=True, exist_ok=True)
    job_dir_src = ProcessingJob.objects.create(
        owner=alice,
        file_name="dir.csv",
        file_type="csv",
        storage_reference="some_dir",
        status=ProcessingJob.Status.PENDING,
    )

    # 3. Completed job whose result path is a directory instead of a file
    job_dir_res = ProcessingJob.objects.create(
        owner=alice,
        file_name="res_dir.csv",
        file_type="csv",
        status=ProcessingJob.Status.COMPLETED,
    )
    (extracted_dir / f"job_{job_dir_res.id}.json").mkdir(parents=True, exist_ok=True)

    # 4. Completed job whose result JSON is corrupt
    job_bad_json = ProcessingJob.objects.create(
        owner=alice,
        file_name="bad.csv",
        file_type="csv",
        status=ProcessingJob.Status.COMPLETED,
    )
    (extracted_dir / f"job_{job_bad_json.id}.json").write_text("{not valid json", encoding="utf-8")

    client.force_login(alice)
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_missing_src.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_dir_src.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_dir_res.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_bad_json.id})).status_code == 404


def test_f6_download_document_rejects_absolute_outside_and_directory(client, alice, isolated_media, tmp_path):
    """download_document rejects arbitrary outside absolute paths and directories."""
    media_dir = Path(isolated_media)
    (media_dir / "folder").mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.csv"
    outside.write_text("a,b\n1,2\n", encoding="utf-8")

    job_abs = ProcessingJob.objects.create(
        owner=alice,
        file_name="outside.csv",
        file_type="csv",
        storage_reference=str(outside),
        status=ProcessingJob.Status.COMPLETED,
    )
    job_dir = ProcessingJob.objects.create(
        owner=alice,
        file_name="folder.csv",
        file_type="csv",
        storage_reference="folder",
        status=ProcessingJob.Status.COMPLETED,
    )

    client.force_login(alice)
    assert client.get(reverse("processing_jobs:download_document", kwargs={"job_id": job_abs.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_document", kwargs={"job_id": job_dir.id})).status_code == 404


def test_f7_report_resolver_rejects_paths_outside_media_root_and_directories(client, alice, isolated_media, tmp_path):
    """resolve_report_for_job rejects custom resolvers, model attrs, and directories outside MEDIA_ROOT."""
    media_dir = Path(isolated_media)
    reports_dir = media_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    outside_pdf = tmp_path / "secret_report.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4 outside_secret")
    outside_xlsx = tmp_path / "secret_report.xlsx"
    outside_xlsx.write_bytes(b"PK\x03\x04outside_excel")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="doc.csv",
        file_type="csv",
        status=ProcessingJob.Status.COMPLETED,
    )

    # 1. Custom resolver returning outside absolute path and traversal path
    def evil_resolver(target_job, canonical_type):
        if canonical_type == "pdf":
            return outside_pdf
        return Path("../secret_report.xlsx")

    register_report_resolver(evil_resolver)
    try:
        pdf_path, _, _ = resolve_report_for_job(job, "pdf")
        xlsx_path, _, _ = resolve_report_for_job(job, "excel")
        assert pdf_path is None
        assert xlsx_path is None
    finally:
        unregister_report_resolver(evil_resolver)

    # 2. Model attribute pointing outside MEDIA_ROOT (absolute and traversal)
    job.report_pdf_path = str(outside_pdf)
    job.report_excel_path = "../secret_report.xlsx"
    pdf_path, _, _ = resolve_report_for_job(job, "pdf")
    xlsx_path, _, _ = resolve_report_for_job(job, "excel")
    assert pdf_path is None
    assert xlsx_path is None

    # 3. Conventional report path is a directory instead of a file
    del job.report_pdf_path
    del job.report_excel_path
    (reports_dir / f"job_{job.id}_summary.pdf").mkdir(parents=True, exist_ok=True)
    pdf_path, _, _ = resolve_report_for_job(job, "pdf")
    assert pdf_path is None

    # View also returns 404
    client.force_login(alice)
    resp = client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": job.id, "report_type": "pdf"})
    )
    assert resp.status_code == 404


def test_f8_symlink_escape_attempts_rejected_os_level(client, alice, isolated_media, tmp_path):
    """OS-level symlink escapes in source docs, extracted results, and reports are blocked."""
    media_dir = Path(isolated_media)
    reports_dir = media_dir / "reports"
    extracted_dir = media_dir / "extracted"
    reports_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    outside_csv = tmp_path / "outside_source.csv"
    outside_csv.write_bytes(b"col\nsecret\n")
    outside_json = tmp_path / "outside_result.json"
    outside_json.write_text('{"secret": true}', encoding="utf-8")
    outside_pdf = tmp_path / "outside_report.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4 outside")

    src_link = media_dir / "link_source.csv"
    _create_symlink_or_skip(src_link, outside_csv)

    json_link = extracted_dir / "job_99901.json"
    _create_symlink_or_skip(json_link, outside_json)

    pdf_link = reports_dir / "link_report.pdf"
    _create_symlink_or_skip(pdf_link, outside_pdf)

    job_src_link = ProcessingJob.objects.create(
        owner=alice,
        file_name="link_source.csv",
        file_type="csv",
        storage_reference="link_source.csv",
        status=ProcessingJob.Status.PENDING,
    )
    job_json_link = ProcessingJob.objects.create(
        id=99901,
        owner=alice,
        file_name="res.csv",
        file_type="csv",
        status=ProcessingJob.Status.COMPLETED,
    )
    job_json_link.report_pdf_path = "reports/link_report.pdf"

    assert resolve_report_for_job(job_json_link, "pdf")[0] is None

    client.force_login(alice)
    assert client.get(reverse("processing_jobs:download_document", kwargs={"job_id": job_src_link.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_src_link.id})).status_code == 404
    assert client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job_json_link.id})).status_code == 404
    assert client.get(
        reverse("processing_jobs:download_report", kwargs={"job_id": job_json_link.id, "report_type": "pdf"})
    ).status_code == 404


def test_f9_symlink_rejection_simulated_deterministically(isolated_media, monkeypatch):
    """Symlink rejection is enforced even on platforms without OS symlink privileges."""
    media_dir = Path(isolated_media)
    extracted_dir = media_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    target = extracted_dir / "job_42.json"
    target.write_text('{"ok": true}', encoding="utf-8")

    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "job_42.json")

    with pytest.raises(InvalidMediaPathError, match="Symbolic links"):
        get_validated_extracted_result_path(42, must_exist=True)


def test_f10_database_errors_not_hidden_as_404(client, alice, isolated_media, monkeypatch):
    """Database failures in API/download views must propagate rather than returning 404."""
    headers = {"HTTP_AUTHORIZATION": basic_auth_header("alice", "password123")}

    def fail_db(*args, **kwargs):
        raise DatabaseError("simulated database failure")

    monkeypatch.setattr("processing_jobs.api_views.get_authorized_job_or_404", fail_db)

    with pytest.raises(DatabaseError):
        client.get(reverse("processing_jobs:api_job_detail", kwargs={"job_id": 1}), **headers)
    with pytest.raises(DatabaseError):
        client.get(reverse("processing_jobs:api_download_document", kwargs={"job_id": 1}), **headers)
    with pytest.raises(DatabaseError):
        client.get(
            reverse("processing_jobs:api_download_report", kwargs={"job_id": 1, "report_type": "excel"}),
            **headers,
        )

    # Also verify download_result does not swallow DatabaseError during job.save()
    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "db_fail.csv"
    src.write_bytes(b"a,b\n1,2\n")
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="db_fail.csv",
        file_type="csv",
        storage_reference="db_fail.csv",
        status=ProcessingJob.Status.PENDING,
    )
    monkeypatch.setattr(ProcessingJob, "save", fail_db)
    client.force_login(alice)
    with pytest.raises(DatabaseError):
        client.get(reverse("processing_jobs:download_result", kwargs={"job_id": job.id}))


# ------------------------------------------------------------------------------
# G. Background Worker Security Integration Tests
# ------------------------------------------------------------------------------

def test_g1_worker_processes_valid_source_file_inside_media_root(alice, isolated_media):
    """process_claimed_job processes valid source files inside MEDIA_ROOT and writes confined JSON."""
    from io import StringIO
    from processing_jobs.management.commands.process_pending_jobs import claim_next_job, process_claimed_job

    media_dir = Path(isolated_media)
    uploads_dir = media_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    src = uploads_dir / "valid_worker.csv"
    src.write_bytes(b"item,price\nBook,12.50\n")

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_worker.csv",
        file_type="csv",
        file_size=src.stat().st_size,
        storage_reference="uploads/valid_worker.csv",
        status=ProcessingJob.Status.PENDING,
    )

    claimed = claim_next_job()
    assert claimed is not None and claimed.id == job.id

    stdout = StringIO()
    stderr = StringIO()
    ok = process_claimed_job(claimed, stdout=stdout, stderr=stderr)
    assert ok is True
    assert stderr.getvalue() == ""
    assert f"Completed job {job.id}" in stdout.getvalue()

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED
    assert job.error_message == ""

    result_path = media_dir / "extracted" / f"job_{job.id}.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1


def test_g2_worker_rejects_traversal_and_absolute_paths_outside_media_root(alice, isolated_media, tmp_path):
    """process_claimed_job marks jobs failed and refuses to read traversal or outside absolute paths."""
    from io import StringIO
    from processing_jobs.management.commands.process_pending_jobs import process_claimed_job

    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)

    outside_csv = tmp_path / "worker_outside_secret.csv"
    outside_csv.write_bytes(b"secret,value\nkey,TOP_SECRET\n")

    job_traversal = ProcessingJob.objects.create(
        owner=alice,
        file_name="trav.csv",
        file_type="csv",
        storage_reference="../worker_outside_secret.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    job_abs = ProcessingJob.objects.create(
        owner=alice,
        file_name="abs.csv",
        file_type="csv",
        storage_reference=str(outside_csv),
        status=ProcessingJob.Status.PROCESSING,
    )

    stderr_trav = StringIO()
    assert process_claimed_job(job_traversal, stderr=stderr_trav) is False
    job_traversal.refresh_from_db()
    assert job_traversal.status == ProcessingJob.Status.FAILED
    assert job_traversal.error_message
    assert f"Failed job {job_traversal.id}" in stderr_trav.getvalue()
    assert not (media_dir / "extracted" / f"job_{job_traversal.id}.json").exists()

    stderr_abs = StringIO()
    assert process_claimed_job(job_abs, stderr=stderr_abs) is False
    job_abs.refresh_from_db()
    assert job_abs.status == ProcessingJob.Status.FAILED
    assert job_abs.error_message
    assert f"Failed job {job_abs.id}" in stderr_abs.getvalue()
    assert not (media_dir / "extracted" / f"job_{job_abs.id}.json").exists()


def test_g3_worker_rejects_symlink_source_and_extracted_paths_os_level(alice, isolated_media, tmp_path):
    """process_claimed_job rejects OS-level symlink escapes on source files and extracted destinations."""
    from processing_jobs.management.commands.process_pending_jobs import process_claimed_job

    media_dir = Path(isolated_media)
    extracted_dir = media_dir / "extracted"
    media_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    outside_csv = tmp_path / "outside_worker.csv"
    outside_csv.write_bytes(b"a,b\n1,2\n")
    src_link = media_dir / "worker_link.csv"
    _create_symlink_or_skip(src_link, outside_csv)

    job_src_link = ProcessingJob.objects.create(
        owner=alice,
        file_name="worker_link.csv",
        file_type="csv",
        storage_reference="worker_link.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    assert process_claimed_job(job_src_link) is False
    job_src_link.refresh_from_db()
    assert job_src_link.status == ProcessingJob.Status.FAILED
    assert not (extracted_dir / f"job_{job_src_link.id}.json").exists()

    # Symlink destination inside extracted/ pointing outside MEDIA_ROOT
    valid_src = media_dir / "valid_src.csv"
    valid_src.write_bytes(b"a,b\n1,2\n")
    outside_target = tmp_path / "outside_write.json"
    outside_target.write_text("UNTOUCHED", encoding="utf-8")

    job_dest_link = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_src.csv",
        file_type="csv",
        storage_reference="valid_src.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    dest_link = extracted_dir / f"job_{job_dest_link.id}.json"
    _create_symlink_or_skip(dest_link, outside_target)

    assert process_claimed_job(job_dest_link) is False
    job_dest_link.refresh_from_db()
    assert job_dest_link.status == ProcessingJob.Status.FAILED
    assert outside_target.read_text(encoding="utf-8") == "UNTOUCHED"


def test_g4_worker_rejects_symlink_and_invalid_extracted_paths_deterministically(alice, isolated_media, monkeypatch):
    """process_claimed_job rejects simulated symlinks and invalid extracted directory/file targets."""
    from processing_jobs.management.commands.process_pending_jobs import process_claimed_job

    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "valid_for_worker.csv"
    src.write_bytes(b"col\nval\n")

    # 1. Invalid extracted target: pre-existing directory where job_<id>.json should be written
    extracted_dir = media_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    job_dir_target = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_for_worker.csv",
        file_type="csv",
        storage_reference="valid_for_worker.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    (extracted_dir / f"job_{job_dir_target.id}.json").mkdir(parents=True, exist_ok=True)

    assert process_claimed_job(job_dir_target) is False
    job_dir_target.refresh_from_db()
    assert job_dir_target.status == ProcessingJob.Status.FAILED
    assert "not a regular file" in job_dir_target.error_message

    # 2. Invalid extracted directory: regular file named 'extracted'
    (extracted_dir / f"job_{job_dir_target.id}.json").rmdir()
    extracted_dir.rmdir()
    extracted_dir.write_text("not a directory", encoding="utf-8")
    job_bad_dir = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_for_worker.csv",
        file_type="csv",
        storage_reference="valid_for_worker.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    assert process_claimed_job(job_bad_dir) is False
    job_bad_dir.refresh_from_db()
    assert job_bad_dir.status == ProcessingJob.Status.FAILED
    extracted_dir.unlink()

    # 3. Simulated symlink on source file
    job_sym = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid_for_worker.csv",
        file_type="csv",
        storage_reference="valid_for_worker.csv",
        status=ProcessingJob.Status.PROCESSING,
    )
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "valid_for_worker.csv")
    assert process_claimed_job(job_sym) is False
    job_sym.refresh_from_db()
    assert job_sym.status == ProcessingJob.Status.FAILED
    assert "Symbolic links" in job_sym.error_message


def test_g5_worker_marks_invalid_job_failed_and_continues_to_next_job(alice, isolated_media):
    """Worker failure handling marks invalid-path jobs FAILED and still processes subsequent valid jobs."""
    from django.core.management import call_command

    media_dir = Path(isolated_media)
    media_dir.mkdir(parents=True, exist_ok=True)
    good_src = media_dir / "good_next.csv"
    good_src.write_bytes(b"name,qty\nPen,5\n")

    bad_job = ProcessingJob.objects.create(
        owner=alice,
        file_name="missing_or_dir.csv",
        file_type="csv",
        storage_reference="../escape.csv",
        status=ProcessingJob.Status.PENDING,
    )
    good_job = ProcessingJob.objects.create(
        owner=alice,
        file_name="good_next.csv",
        file_type="csv",
        storage_reference="good_next.csv",
        status=ProcessingJob.Status.PENDING,
    )

    call_command("process_pending_jobs", max_jobs=2)

    bad_job.refresh_from_db()
    good_job.refresh_from_db()
    assert bad_job.status == ProcessingJob.Status.FAILED
    assert bad_job.error_message
    assert good_job.status == ProcessingJob.Status.COMPLETED
    assert (media_dir / "extracted" / f"job_{good_job.id}.json").is_file()
