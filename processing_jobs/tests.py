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


import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

from .extractors import extract_document


class PDFOCRIntegrationTests(TestCase):

    def create_digital_pdf(self):
        document = pymupdf.open()
        page = document.new_page()

        page.insert_text((72, 72), "INVOICE")
        page.insert_text((72, 110), "Invoice Number: INV-2026-001")
        page.insert_text((72, 140), "Customer: Mallikarjun")
        page.insert_text((72, 170), "Total Amount: 5000")

        pdf_bytes = document.tobytes()
        document.close()

        return pdf_bytes

    
    def create_scanned_pdf(self):
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (1600, 900), "white")
        draw = ImageDraw.Draw(image)

        font_path = r"C:\Windows\Fonts\arial.ttf"
        title_font = ImageFont.truetype(font_path, 60)
        text_font = ImageFont.truetype(font_path, 42)

        draw.text((100, 80), "INVOICE", fill="black", font=title_font)
        draw.text(
            (100, 250),
            "Invoice Number: INV-2026-002",
            fill="black",
            font=text_font
        )
        draw.text(
            (100, 370),
            "Customer: Mallikarjun",
            fill="black",
            font=text_font
        )
        draw.text(
            (100, 490),
            "Total Amount: 7500",
            fill="black",
            font=text_font
        )

        image_bytes = tempfile.SpooledTemporaryFile()
        image.save(image_bytes, format="PNG")
        image_bytes.seek(0)

        document = pymupdf.open()
        page = document.new_page(width=595, height=842)

        page.insert_image(
            pymupdf.Rect(30, 30, 565, 812),
            stream=image_bytes.read()
        )

        pdf_bytes = document.tobytes()
        document.close()
        image_bytes.close()

        return pdf_bytes


    def test_digital_pdf_extraction(self):
        pdf_bytes = self.create_digital_pdf()

        result = extract_document(pdf_bytes, "digital.pdf")

        self.assertEqual(result["file_type"], "pdf")
        self.assertEqual(result["page_count"], 1)
        self.assertIn("INV-2026-001", result["text"])
        self.assertIn("Mallikarjun", result["text"])
        self.assertIn("5000", result["text"])

    def test_scanned_pdf_uses_ocr(self):
        pdf_bytes = self.create_scanned_pdf()

        result = extract_document(pdf_bytes, "scanned.pdf")

        self.assertEqual(result["file_type"], "pdf")
        self.assertEqual(result["page_count"], 1)
        self.assertIn("INV-2026-002", result["text"])
        self.assertIn("Mallikarjun", result["text"])
        self.assertIn("7500", result["text"])

    def test_corrupted_pdf_is_rejected(self):
        with self.assertRaises(Exception):
            extract_document(b"not a valid PDF", "corrupted.pdf")

    def test_empty_pdf_is_rejected(self):
        with self.assertRaises(Exception):
            extract_document(b"", "empty.pdf")

    @patch(
        "processing_jobs.extractors.extract_document_text"
    )
    def test_temporary_pdf_is_removed_after_extraction(
        self,
        mock_extraction
    ):
        mock_extraction.return_value = {
            "total_pages": 1,
            "full_text": "Test document",
            "pages": [
                {
                    "page_number": 1,
                    "text": "Test document"
                }
            ]
        }

        with patch(
            "processing_jobs.extractors.os.remove"
        ) as mock_remove:

            extract_document(b"test PDF bytes", "test.pdf")

            self.assertEqual(mock_remove.call_count, 1)

            temporary_path = mock_remove.call_args[0][0]

            self.assertTrue(
                temporary_path.endswith(".pdf")
            )
