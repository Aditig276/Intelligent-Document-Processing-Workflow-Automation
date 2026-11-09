import tempfile
import warnings
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

import documents.views
import processing_jobs.api_views
from processing_jobs.models import ProcessingJob


class UploadAPITests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.temp_dir.name
        )
        self.settings_override.enable()
        self.upload_url = "/api/upload/"
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user, _ = User.objects.get_or_create(
            username="upload_test_user",
            defaults={"email": "upload_test@example.com", "is_active": True},
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

        response = csrf_client.post(
            "/api/upload/",
            {},
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_upload_is_rejected(self):
        self.client.logout()
        file = SimpleUploadedFile("anon.csv", b"a,b\n1,2\n", content_type="text/csv")
        response = self.client.post(self.upload_url, {"file": file})
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response)
        self.assertEqual(
            response.json()["error"],
            "Authentication credentials were not provided.",
        )
        self.assertEqual(ProcessingJob.objects.count(), 0)

    def test_authenticated_upload_creates_processing_job(self):
        file = SimpleUploadedFile(
            "job_sample.csv",
            b"col1,col2\nval1,val2\n",
            content_type="text/csv",
        )
        response = self.client.post(self.upload_url, {"file": file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["original_filename"], "job_sample.csv")

        job = ProcessingJob.objects.get(id=data["job_id"])
        self.assertEqual(job.owner, self.user)
        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(job.file_name, "job_sample.csv")
        self.assertEqual(job.file_type, "csv")

    def test_rate_limiting_works(self):
        from django.core.cache import cache

        with self.settings(
            UPLOAD_RATE_LIMIT_ENABLED=True,
            UPLOAD_RATE_LIMIT_REQUESTS=2,
            UPLOAD_RATE_LIMIT_WINDOW=60,
        ):
            cache.clear()
            for i in range(2):
                file = SimpleUploadedFile(
                    f"rate_{i}.csv",
                    b"a,b\n1,2\n",
                    content_type="text/csv",
                )
                res = self.client.post(self.upload_url, {"file": file})
                self.assertEqual(res.status_code, 201)

            # Exceed quota
            overflow_file = SimpleUploadedFile(
                "overflow.csv",
                b"a,b\n1,2\n",
                content_type="text/csv",
            )
            res_overflow = self.client.post(
                self.upload_url, {"file": overflow_file}
            )
            self.assertEqual(res_overflow.status_code, 429)
            self.assertIn("Retry-After", res_overflow)
            self.assertIn("Rate limit exceeded", res_overflow.json()["error"])

    def test_api_endpoints_resolve_to_intended_views(self):
        health_match = resolve("/api/health/")
        self.assertEqual(health_match.func, documents.views.health_check)
        self.assertEqual(health_match.url_name, "health_check")

        upload_match = resolve("/api/upload/")
        self.assertEqual(
            upload_match.func, processing_jobs.api_views.upload_file
        )
        self.assertEqual(upload_match.url_name, "upload_file")

    def test_url_reverse_compatibility(self):
        from django.urls.exceptions import NoReverseMatch

        # Canonical documents API routes (unnamespaced canonical and legacy names)
        self.assertEqual(reverse("health_check"), "/api/health/")
        self.assertEqual(reverse("api_health"), "/api/health/")
        self.assertEqual(reverse("upload_file"), "/api/upload/")
        self.assertEqual(reverse("api_upload"), "/api/upload/")

        # Verify API routes no longer belong to processing_jobs namespace
        with self.assertRaises(NoReverseMatch):
            reverse("processing_jobs:health_check")
        with self.assertRaises(NoReverseMatch):
            reverse("processing_jobs:api_health")
        with self.assertRaises(NoReverseMatch):
            reverse("processing_jobs:upload_file")
        with self.assertRaises(NoReverseMatch):
            reverse("processing_jobs:api_upload")

        # UI routes (unnamespaced and namespaced)
        self.assertEqual(reverse("dashboard"), "/dashboard/")
        self.assertEqual(reverse("processing_jobs:dashboard"), "/dashboard/")
        self.assertEqual(reverse("upload"), "/upload/")
        self.assertEqual(reverse("processing_jobs:upload"), "/upload/")
        self.assertEqual(reverse("upload_document"), "/")
        self.assertEqual(reverse("processing_jobs:upload_document"), "/")

        self.assertEqual(
            reverse("job_detail", kwargs={"job_id": 1}), "/job/1/"
        )
        self.assertEqual(
            reverse("processing_jobs:job_detail", kwargs={"job_id": 1}),
            "/job/1/",
        )
        self.assertEqual(
            reverse("view_extracted_data", kwargs={"job_id": 1}),
            "/jobs/1/data/",
        )
        self.assertEqual(
            reverse(
                "processing_jobs:view_extracted_data", kwargs={"job_id": 1}
            ),
            "/jobs/1/data/",
        )
        self.assertEqual(
            reverse("extract_job", kwargs={"job_id": 1}), "/job/1/extract/"
        )
        self.assertEqual(
            reverse("processing_jobs:extract_job", kwargs={"job_id": 1}),
            "/job/1/extract/",
        )
        self.assertEqual(
            reverse("extract", kwargs={"job_id": 1}), "/jobs/1/"
        )
        self.assertEqual(
            reverse("processing_jobs:extract", kwargs={"job_id": 1}),
            "/jobs/1/",
        )
        self.assertEqual(
            reverse("download_result", kwargs={"job_id": 1}), "/job/1/download/"
        )
        self.assertEqual(
            reverse(
                "processing_jobs:download_result", kwargs={"job_id": 1}
            ),
            "/job/1/download/",
        )
        self.assertEqual(
            reverse("download_json", kwargs={"job_id": 1}), "/jobs/1/download/"
        )
        self.assertEqual(
            reverse(
                "processing_jobs:download_json", kwargs={"job_id": 1}
            ),
            "/jobs/1/download/",
        )

    def test_documents_views_upload_file_deprecation(self):
        rf = RequestFactory()
        request = rf.post("/api/upload/")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            response = documents.views.upload_file(request)
            self.assertTrue(
                any(issubclass(item.category, DeprecationWarning) for item in w)
            )
            # Confirms that anonymous upload attempt is safely rejected with 401
            self.assertEqual(response.status_code, 401)
