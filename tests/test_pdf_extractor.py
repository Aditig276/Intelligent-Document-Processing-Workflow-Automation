
import pytest
import pymupdf

from app.extractors.pdf_extractor import (
    extract_pdf_text,
    PDFExtractionError,
)


def create_pdf(path, pages):
    doc = pymupdf.open()

    for content in pages:
        page = doc.new_page()
        page.insert_text((72, 72), content)

    doc.save(path)
    doc.close()


def test_extract_digital_pdf(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    create_pdf(pdf, ["Invoice Number: INV001"])

    result = extract_pdf_text(str(pdf))

    assert result["status"] == "success"
    assert result["total_pages"] == 1
    assert "INV001" in result["full_text"]


def test_extract_multiple_pages(tmp_path):
    pdf = tmp_path / "multiple.pdf"
    create_pdf(pdf, ["Page One", "Page Two"])

    result = extract_pdf_text(str(pdf))

    assert result["total_pages"] == 2
    assert len(result["pages"]) == 2
    assert "Page One" in result["full_text"]
    assert "Page Two" in result["full_text"]


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        extract_pdf_text("missing.pdf")


def test_empty_file(tmp_path):
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"")

    with pytest.raises(PDFExtractionError):
        extract_pdf_text(str(pdf))


def test_corrupted_pdf(tmp_path):
    pdf = tmp_path / "corrupted.pdf"
    pdf.write_bytes(b"This is not a valid PDF")

    with pytest.raises(PDFExtractionError):
        extract_pdf_text(str(pdf))


def test_scanned_pdf_without_text(tmp_path):
    pdf = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    doc.close()

    result = extract_pdf_text(str(pdf))

    assert result["status"] == "no_text"
    assert result["full_text"] == ""
