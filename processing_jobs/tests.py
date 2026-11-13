
from django.test import TestCase
from .models import ProcessingJob


class ProcessingJobTests(TestCase):

    def test_job_defaults_to_pending(self):
        job = ProcessingJob.objects.create(
            file_name="invoice.pdf",
            file_type="pdf",
            file_size=1024,
        )

        self.assertEqual(
            job.status,
            ProcessingJob.Status.PENDING,
        )

    def test_status_can_be_updated(self):
        job = ProcessingJob.objects.create(
            file_name="report.xlsx",
            file_type="xlsx",
            file_size=2048,
        )

        job.status = ProcessingJob.Status.PROCESSING
        job.save()
        job.refresh_from_db()

        self.assertEqual(
            job.status,
            ProcessingJob.Status.PROCESSING,
        )

    def test_failed_job_stores_error(self):
        job = ProcessingJob.objects.create(
            file_name="broken.pdf",
            file_type="pdf",
            status=ProcessingJob.Status.FAILED,
            error_message="Unable to read document",
        )

        self.assertEqual(job.status, "failed")
        self.assertEqual(
            job.error_message,
            "Unable to read document",
        )


from io import BytesIO

from django.contrib.auth import get_user_model
from django.urls import reverse
from openpyxl import load_workbook


class ExcelReportDownloadTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="report_owner",
            password="TestPassword123!"
        )

        self.other_user = User.objects.create_user(
            username="another_user",
            password="TestPassword123!"
        )

        self.job = ProcessingJob.objects.create(
            owner=self.user,
            file_name="invoice.pdf",
            file_type="pdf",
            file_size=1024,
            status=ProcessingJob.Status.COMPLETED,
            reviewed_data={
                "document_name": "invoice.pdf",
                "invoice_number": "INV-2028-002",
                "document_date": "2026-11-12",
                "customer_name": "Mallikarjun",
                "total_amount": "7500",
            },
        )

        self.url = reverse(
            "processing_jobs:download_excel_report",
            kwargs={"job_id": self.job.id},
        )

    def test_owner_can_download_excel_report(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
        )
        self.assertIn(
            f"job_{self.job.id}_report.xlsx",
            response["Content-Disposition"],
        )

        workbook = load_workbook(BytesIO(response.content))

        self.assertEqual(
            workbook.sheetnames,
            [
                "Invoice Details",
                "Processing Summary",
                "Extraction Details",
            ],
        )

    def test_empty_reviewed_data_returns_404(self):
        self.job.reviewed_data = {}
        self.job.save(update_fields=["reviewed_data"])

        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_cannot_download(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_other_user_cannot_download_report(self):
        self.client.force_login(self.other_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
