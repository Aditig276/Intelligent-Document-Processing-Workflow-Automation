
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.extractors.ocr_extractor import (
    OCRExtractionError,
    extract_image_text,
    extract_scanned_pdf_text,
)


@pytest.fixture
def sample_image(tmp_path):
    """Create a sample invoice image for OCR testing."""
    image_path = tmp_path / "sample_invoice.png"

    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)

    draw.text((60, 60), "INVOICE", fill="black")
    draw.text((60, 150), "Invoice Number: INV-2026-002", fill="black")
    draw.text((60, 230), "Customer: Mallikarjun", fill="black")
    draw.text((60, 310), "Total Amount: 7500", fill="black")

    image.save(image_path)
    return image_path


@pytest.fixture
def sample_scanned_pdf(tmp_path, sample_image):
    """Create a scanned PDF containing the sample invoice image."""
    pdf_path = tmp_path / "sample_scanned_invoice.pdf"

    with pymupdf.open() as document:
        page = document.new_page(width=600, height=250)
        page.insert_image(page.rect, filename=str(sample_image))
        document.save(pdf_path)

    return pdf_path


def test_extract_image_text(sample_image):
    result = extract_image_text(str(sample_image))

    assert result["status"] == "success"
    assert result["extraction_method"] == "tesseract_ocr"
    assert "INVOICE" in result["full_text"]
    assert result["total_pages"] == 1


def test_extract_scanned_pdf_text(sample_scanned_pdf):
    result = extract_scanned_pdf_text(str(sample_scanned_pdf))

    assert result["status"] == "success"
    assert result["extraction_method"] == "tesseract_ocr"
    assert "INVOICE" in result["full_text"]
    assert result["total_pages"] == 1


def test_missing_image():
    with pytest.raises(FileNotFoundError):
        extract_image_text("missing_image.png")


def test_missing_pdf():
    with pytest.raises(FileNotFoundError):
        extract_scanned_pdf_text("missing_document.pdf")


def test_invalid_image(tmp_path):
    invalid_image = tmp_path / "invalid.png"
    invalid_image.write_text("This is not an image")

    with pytest.raises(OCRExtractionError):
        extract_image_text(str(invalid_image))


def test_invalid_pdf(tmp_path):
    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_text("This is not a PDF")

    with pytest.raises(OCRExtractionError):
        extract_scanned_pdf_text(str(invalid_pdf))
