"""Executable regression tests for Mallikarjun's PDF text and Tesseract OCR extractors.

These tests create synthetic documents in tmp_path (no private invoice files).
Tesseract must be installed and available on PATH or configured by the project.
"""
from pathlib import Path

import pytest
import pymupdf
from PIL import Image, ImageDraw

from app.extractors.pdf_extractor import PDFExtractionError, extract_pdf_text
from app.extractors.ocr_extractor import (
    OCRExtractionError,
    extract_image_text,
    extract_scanned_pdf_text,
)
from app.extractors.extraction_service import extract_document_text


def make_text_pdf(path: Path, page_texts):
    with pymupdf.open() as doc:
        for text in page_texts:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(path)


@pytest.fixture
def digital_pdf(tmp_path):
    path = tmp_path / "digital_invoice.pdf"
    make_text_pdf(path, ["Invoice Number: INV-TEST-001", "Total Amount: 1250.50"])
    return path


@pytest.fixture
def invoice_image(tmp_path):
    path = tmp_path / "invoice_scan.png"
    image = Image.new("RGB", (1400, 600), "white")
    draw = ImageDraw.Draw(image)
    # Use a large, clear font-free drawing for robust basic OCR assertions.
    draw.text((80, 80), "INVOICE", fill="black", stroke_width=1)
    draw.text((80, 220), "Invoice Number: INV-TEST-002", fill="black", stroke_width=1)
    draw.text((80, 360), "Total Amount: 7500", fill="black", stroke_width=1)
    image.save(path)
    return path


@pytest.fixture
def scanned_pdf(tmp_path, invoice_image):
    path = tmp_path / "scanned_invoice.pdf"
    with Image.open(invoice_image) as image:
        with pymupdf.open() as doc:
            page = doc.new_page(width=700, height=300)
            page.insert_image(page.rect, filename=str(invoice_image))
            doc.save(path)
    return path


def test_digital_pdf_extracts_text_and_page_metadata(digital_pdf):
    result = extract_pdf_text(str(digital_pdf))
    assert result["status"] == "success"
    assert result["extraction_method"] == "pymupdf"
    assert result["total_pages"] == 2
    assert [p["page_number"] for p in result["pages"]] == [1, 2]
    assert "INV-TEST-001" in result["full_text"]
    assert "1250.50" in result["full_text"]


def test_empty_text_pdf_returns_no_text(digital_pdf, tmp_path):
    blank = tmp_path / "blank.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(blank)
    result = extract_pdf_text(str(blank))
    assert result["status"] == "no_text"
    assert result["full_text"] == ""


def test_scanned_pdf_ocr_extracts_invoice_content(scanned_pdf):
    result = extract_scanned_pdf_text(str(scanned_pdf))
    assert result["status"] == "success"
    assert result["extraction_method"] == "tesseract_ocr"
    assert result["total_pages"] == 1
    assert "INVOICE" in result["full_text"].upper()
    assert "INV-TEST-002" in result["full_text"]


def test_png_ocr_extracts_invoice_content(invoice_image):
    result = extract_image_text(str(invoice_image))
    assert result["status"] == "success"
    assert result["total_pages"] == 1
    assert "INV-TEST-002" in result["full_text"]


def test_extraction_service_routes_digital_pdf(digital_pdf):
    result = extract_document_text(str(digital_pdf))
    assert result["extraction_method"] == "pymupdf"
    assert "INV-TEST-001" in result["full_text"]


def test_extraction_service_routes_image(invoice_image):
    result = extract_document_text(str(invoice_image))
    assert result["extraction_method"] == "tesseract_ocr"
    assert "INVOICE" in result["full_text"].upper()


def test_missing_pdf_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_pdf_text(str(tmp_path / "not_here.pdf"))


def test_missing_image_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_image_text(str(tmp_path / "not_here.png"))


@pytest.mark.parametrize("extractor", [extract_pdf_text, extract_scanned_pdf_text])
def test_empty_pdf_file_is_rejected(tmp_path, extractor):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises((PDFExtractionError, OCRExtractionError)):
        extractor(str(path))


def test_corrupt_pdf_is_rejected(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a PDF document")
    with pytest.raises((PDFExtractionError, OCRExtractionError)):
        extract_pdf_text(str(path))


def test_corrupt_image_is_rejected(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(OCRExtractionError):
        extract_image_text(str(path))


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("unsupported")
    with pytest.raises(ValueError, match="Unsupported extraction format"):
        extract_document_text(str(path))


def test_scanned_pdf_multi_page_preserves_page_order(tmp_path, invoice_image):
    path = tmp_path / "two_page_scan.pdf"
    with pymupdf.open() as doc:
        for _ in range(2):
            page = doc.new_page(width=700, height=300)
            page.insert_image(page.rect, filename=str(invoice_image))
        doc.save(path)
    result = extract_scanned_pdf_text(str(path))
    assert result["total_pages"] == 2
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert all("INV-TEST-002" in page["text"] for page in result["pages"])
