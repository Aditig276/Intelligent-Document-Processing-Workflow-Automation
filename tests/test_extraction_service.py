
import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.extractors.extraction_service import extract_document_text


@pytest.fixture
def sample_image(tmp_path):
    """Create a sample invoice image."""
    image_path = tmp_path / "invoice.png"

    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)

    draw.text((60, 60), "INVOICE", fill="black")
    draw.text((60, 150), "Invoice Number: INV-2026-002", fill="black")
    draw.text((60, 230), "Customer: Mallikarjun", fill="black")
    draw.text((60, 310), "Total Amount: 7500", fill="black")

    image.save(image_path)
    return image_path


@pytest.fixture
def digital_pdf(tmp_path):
    """Create a digital PDF containing selectable text."""
    pdf_path = tmp_path / "digital_invoice.pdf"

    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Digital PDF Invoice")
        document.save(pdf_path)

    return pdf_path


@pytest.fixture
def scanned_pdf(tmp_path, sample_image):
    """Create an image-only scanned PDF."""
    pdf_path = tmp_path / "scanned_invoice.pdf"

    with pymupdf.open() as document:
        page = document.new_page(width=600, height=250)
        page.insert_image(page.rect, filename=str(sample_image))
        document.save(pdf_path)

    return pdf_path


def test_digital_pdf_selection(digital_pdf):
    result = extract_document_text(str(digital_pdf))

    assert result["status"] == "success"
    assert result["extraction_method"] == "pymupdf"
    assert "Digital PDF Invoice" in result["full_text"]


def test_scanned_pdf_fallback(scanned_pdf):
    result = extract_document_text(str(scanned_pdf))

    assert result["status"] == "success"
    assert result["extraction_method"] == "tesseract_ocr"
    assert "INVOICE" in result["full_text"]


def test_image_selection(sample_image):
    result = extract_document_text(str(sample_image))

    assert result["status"] == "success"
    assert result["extraction_method"] == "tesseract_ocr"
    assert "INVOICE" in result["full_text"]


def test_unsupported_file_format(tmp_path):
    file_path = tmp_path / "document.txt"
    file_path.write_text("Sample document")

    with pytest.raises(ValueError):
        extract_document_text(str(file_path))


def test_missing_pdf():
    with pytest.raises(FileNotFoundError):
        extract_document_text("missing_document.pdf")
