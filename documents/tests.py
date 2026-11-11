import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings


class UploadAPITests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.temp_dir.name
        )
        self.settings_override.enable()
        self.upload_url = "/api/upload/"

        User = get_user_model()
        self.user = User.objects.create_user(
            username="doc_test_user",
            email="doc_test@example.com",
            password="testpassword123",
            is_active=True,
        )
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_valid_csv_upload(self):
        file = SimpleUploadedFile(
            "sample.csv",
            b"name,amount\nMalli,100\n",
            content_type="text/csv",
        )
        response = self.client.post(
            self.upload_url, {"file": file}
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["original_filename"], "sample.csv")
        self.assertTrue(data["stored_filename"].endswith(".csv"))
        self.assertEqual(len(data["sha256"]), 64)

        stored_path = Path(self.temp_dir.name) / data["stored_filename"]
        self.assertTrue(stored_path.exists())

    def test_unsupported_format_is_rejected(self):
        file = SimpleUploadedFile("sample.txt", b"hello")
        response = self.client.post(
            self.upload_url, {"file": file}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"], "Unsupported file format."
        )

    def test_missing_file_is_rejected(self):
        response = self.client.post(self.upload_url, {})
        self.assertEqual(response.status_code, 400)

    def test_empty_allowed_file_is_rejected(self):
        file = SimpleUploadedFile("empty.pdf", b"")
        response = self.client.post(
            self.upload_url, {"file": file}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"], "Empty files are not allowed."
        )

    def test_file_over_10_mb_is_rejected(self):
        file = SimpleUploadedFile(
            "large.csv",
            b"a" * (10 * 1024 * 1024 + 1),
            content_type="text/csv",
        )
        response = self.client.post(
            self.upload_url, {"file": file}
        )

        self.assertEqual(response.status_code, 413)

    def test_rejects_fake_pdf(self):
        fake_pdf = SimpleUploadedFile(
            "fake.pdf",
            b"This is not a real PDF file",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/upload/",
            {"file": fake_pdf},
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_fake_png(self):
        fake_png = SimpleUploadedFile(
            "fake.png",
            b"This is not a real PNG image",
            content_type="image/png",
        )

        response = self.client.post(
            "/api/upload/",
            {"file": fake_png},
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_fake_xlsx(self):
        fake_xlsx = SimpleUploadedFile(
            "fake.xlsx",
            b"This is not a valid Excel workbook",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            "/api/upload/",
            {"file": fake_xlsx},
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_binary_file_named_csv(self):
        fake_csv = SimpleUploadedFile(
            "fake.csv",
            b"\xff\xfe\xfa\x00\x01",
            content_type="text/csv",
        )

        response = self.client.post(
            "/api/upload/",
            {"file": fake_csv},
        )

        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_request_without_csrf_token(self):
        from django.test import Client

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            "/api/upload/",
            {},
        )

        self.assertEqual(response.status_code, 403)
