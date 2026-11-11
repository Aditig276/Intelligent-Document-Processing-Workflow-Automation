
from pathlib import Path

import pymupdf

from app.extractors.pdf_extractor import extract_pdf_text
from app.extractors.ocr_extractor import (
    extract_image_text,
    extract_scanned_pdf_text,
)


def extract_document_text(file_path: str) -> dict:
    """Select the appropriate extraction method for a document."""

    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".pdf":
        result = extract_pdf_text(str(path))

        if result["status"] == "no_text":
            return extract_scanned_pdf_text(str(path))

        return result

    if extension in {".png", ".jpg", ".jpeg"}:
        return extract_image_text(str(path))

    raise ValueError(
        f"Unsupported extraction format: {extension}"
    )
