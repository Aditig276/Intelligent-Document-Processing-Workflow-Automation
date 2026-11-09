"""Tests for the file upload API (documents app): POST /api/upload/.

Test IDs (TC-UP-xx) match docs/test-plan.md.
"""
import hashlib
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

import sample_factory as sf

pytestmark = [pytest.mark.upload, pytest.mark.django_db]

UPLOAD_URL = "/api/upload/"
HEALTH_URL = "/api/health/"


def get_or_create_api_user():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="api_test_user",
        defaults={"email": "api_test@example.com", "is_active": True},
    )
    return user


@pytest.fixture(autouse=True)
def authenticate_upload_client(client):
    user = get_or_create_api_user()
    client.force_login(user)
    return client


def upload(client, name, content, content_type="application/octet-stream"):
    return client.post(
        UPLOAD_URL,
        {"file": SimpleUploadedFile(name, content, content_type=content_type)},
    )




# ---------------------------------------------------------------- health
def test_tc_up_01_health_check(client):
    response = client.get(HEALTH_URL)
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# ------------------------------------------------------- valid uploads
VALID = sf.valid_samples()


@pytest.mark.parametrize("name", sorted(VALID))
def test_tc_up_02_valid_file_of_every_supported_type_is_accepted(
    client, media_files, name
):
    response = upload(client, name, VALID[name])
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["message"] == "File uploaded successfully."
    assert body["original_filename"] == name
    assert body["stored_filename"].endswith(Path(name).suffix)
    assert len(media_files()) == 1


@pytest.mark.skipif(sf.xls_bytes() is None, reason="xlwt not installed")
def test_tc_up_02b_legacy_xls_is_accepted(client):
    assert upload(client, "old.xls", sf.xls_bytes()).status_code == 201


def test_tc_up_03_response_metadata_and_stored_bytes_are_correct(
    client, isolated_media
):
    content = sf.csv_bytes()
    body = upload(client, "invoice.csv", content, "text/csv").json()

    assert body["size_bytes"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    stored = isolated_media / body["stored_filename"]
    assert stored.read_bytes() == content


def test_tc_up_04_stored_name_is_server_generated_and_unique(client):
    a = upload(client, "same.csv", sf.csv_bytes()).json()["stored_filename"]
    b = upload(client, "same.csv", sf.csv_bytes()).json()["stored_filename"]
    assert a != b
    assert "same" not in a
    stem = Path(a).stem
    assert len(stem) == 32 and int(stem, 16) >= 0  # uuid4 hex


def test_tc_up_05_uppercase_extension_is_accepted_and_normalised(client):
    response = upload(client, "REPORT.PDF", sf.pdf_bytes())
    assert response.status_code == 201
    assert response.json()["stored_filename"].endswith(".pdf")


def test_tc_up_06_path_in_filename_cannot_escape_media_root(
    client, isolated_media
):
    response = upload(client, "../../etc/evil.csv", sf.csv_bytes())
    assert response.status_code == 201
    body = response.json()
    assert "/" not in body["original_filename"]
    assert "\\" not in body["original_filename"]
    stored = (isolated_media / body["stored_filename"]).resolve()
    assert stored.parent == Path(isolated_media).resolve()


def test_tc_up_07_unicode_filename_is_kept_in_response(client):
    response = upload(client, "factura_ñandú.csv", sf.csv_bytes())
    assert response.status_code == 201
    assert response.json()["original_filename"] == "factura_ñandú.csv"


def test_tc_up_08_upload_directory_is_created_when_missing(
    client, isolated_media
):
    assert not isolated_media.exists()
    assert upload(client, "a.csv", sf.csv_bytes()).status_code == 201
    assert isolated_media.is_dir()


# ------------------------------------------------- rejected: file type
@pytest.mark.parametrize(
    "name",
    [
        "notes.txt", "run.exe", "page.html", "logo.svg", "anim.gif",
        "letter.docx", "archive.zip", "invoice.pdf.exe", "invoice.csv.txt",
        "noextension", ".csv",
    ],
)
def test_tc_up_09_unsupported_extensions_are_rejected(
    client, media_files, name
):
    response = upload(client, name, b"some bytes")
    assert response.status_code == 400
    assert response.json()["error"] == "Unsupported file format."
    assert media_files() == []


# ---------------------------------------------- rejected: request shape
def test_tc_up_10_missing_file_field_is_rejected(client):
    response = client.post(UPLOAD_URL, {})
    assert response.status_code == 400
    assert "No file provided" in response.json()["error"]


def test_tc_up_11_wrong_field_name_is_rejected(client):
    response = client.post(
        UPLOAD_URL,
        {"document": SimpleUploadedFile("a.csv", sf.csv_bytes())},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("method", ["get", "put", "delete", "patch"])
def test_tc_up_12_only_post_is_allowed(client, method):
    response = getattr(client, method)(UPLOAD_URL)
    assert response.status_code == 405


def test_tc_up_13_csrf_token_is_required_for_browser_clients():
    from django.test import Client

    response = Client(enforce_csrf_checks=True).post(UPLOAD_URL, {})
    assert response.status_code == 403


def test_tc_up_14_two_files_in_one_request_store_exactly_one(
    client, media_files
):
    response = client.post(
        UPLOAD_URL,
        {
            "file": [
                SimpleUploadedFile("one.csv", sf.csv_bytes()),
                SimpleUploadedFile("two.csv", sf.csv_bytes()),
            ]
        },
    )
    assert response.status_code == 201
    assert len(media_files()) == 1


# ------------------------------------------------- rejected: file size
@pytest.mark.parametrize("name", ["e.pdf", "e.csv", "e.xlsx", "e.png"])
def test_tc_up_15_empty_files_are_rejected(client, media_files, name):
    response = upload(client, name, b"")
    assert response.status_code == 400
    assert response.json()["error"] == "Empty files are not allowed."
    assert media_files() == []


@pytest.mark.slow
def test_tc_up_16_file_of_exactly_10_mib_is_accepted(client):
    response = upload(client, "limit.csv", sf.exact_size_csv(sf.MAX_FILE_SIZE))
    assert response.status_code == 201
    assert response.json()["size_bytes"] == sf.MAX_FILE_SIZE


@pytest.mark.slow
def test_tc_up_17_file_one_byte_over_10_mib_is_rejected(client, media_files):
    response = upload(
        client, "toobig.csv", sf.exact_size_csv(sf.MAX_FILE_SIZE + 1)
    )
    assert response.status_code == 413
    assert "10" in response.json()["error"]
    assert media_files() == []


def test_tc_up_17b_limit_upload_size_handler_rejection_returns_413(rf):
    """Regression test: verify upload_too_large attribute triggers 413 before checking request.FILES."""
    from processing_jobs import api_views

    request = rf.post(UPLOAD_URL)
    user = get_or_create_api_user()
    request.user = user
    request.upload_too_large = True

    response = api_views.upload_file(request)
    assert response.status_code == 413
    assert "10" in response.content.decode("utf-8")


# ------------------------------------- rejected: content != extension
@pytest.mark.parametrize(
    "name,content,message",
    [
        ("fake.pdf", b"This is not a real PDF file", "Invalid or corrupted PDF"),
        ("fake.png", b"not an image", "Invalid or corrupted image"),
        ("fake.jpg", b"not an image", "Invalid or corrupted image"),
        ("fake.tif", b"not an image", "Invalid or corrupted image"),
        ("fake.xlsx", b"not a workbook", "Invalid or corrupted Excel"),
        ("fake.xls", b"not a workbook", "Invalid or corrupted Excel"),
        ("fake.csv", b"\xff\xfe\xfa\x00\x01", "Invalid CSV file"),
    ],
)
def test_tc_up_18_corrupt_content_is_rejected(
    client, media_files, name, content, message
):
    response = upload(client, name, content)
    assert response.status_code == 400
    assert message in response.json()["error"]
    assert media_files() == []


@pytest.mark.parametrize(
    "name,content_fn",
    [
        ("a.jpg", sf.png_bytes),
        ("a.jpeg", sf.png_bytes),
        ("a.png", sf.jpeg_bytes),
        ("a.png", sf.tiff_bytes),
        ("a.tif", sf.png_bytes),
    ],
)
def test_tc_up_19_image_content_must_match_extension(
    client, media_files, name, content_fn
):
    response = upload(client, name, content_fn())
    assert response.status_code == 400
    assert "do not match" in response.json()["error"]
    assert media_files() == []


def test_tc_up_20_utf16_csv_is_rejected(client):
    response = upload(client, "u16.csv", sf.csv_bytes(encoding="utf-16"))
    assert response.status_code == 400


def test_tc_up_21_utf8_csv_with_bom_and_header_only_csv_are_accepted(client):
    with_bom = b"\xef\xbb\xbf" + sf.csv_bytes()
    assert upload(client, "bom.csv", with_bom).status_code == 201
    assert upload(client, "h.csv", b"name,amount\n").status_code == 201


def test_tc_up_22_pdf_with_several_pages_is_accepted(client):
    assert upload(client, "m.pdf", sf.pdf_bytes(pages=3)).status_code == 201


# -------------------------------------------------- storage failure
def test_tc_up_23_disk_error_returns_500_and_leaves_no_partial_file(
    client, monkeypatch, media_files
):
    def boom(self, *args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(Path, "open", boom)
        response = upload(client, "a.csv", sf.csv_bytes())

    assert response.status_code == 500
    assert response.json()["error"] == "Unable to store the uploaded file."
    assert media_files() == []


# ---------------------- FIXED DEFECT ---------------------------------
def test_tc_up_24_zip_renamed_to_xlsx_is_rejected_with_400(client):
    response = upload(client, "zip.xlsx", sf.zip_not_excel_bytes())
    assert response.status_code == 400
