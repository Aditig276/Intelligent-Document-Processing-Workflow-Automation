import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile


class UploadAPITests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.temp_dir.name
        )
        self.settings_override.enable()
        self.upload_url = "/api/upload/"

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
