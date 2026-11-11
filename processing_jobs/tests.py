
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
