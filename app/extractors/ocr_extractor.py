from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image, UnidentifiedImageError

import shutil

windows_tesseract = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

if windows_tesseract.exists():
    pytesseract.pytesseract.tesseract_cmd = str(windows_tesseract)
else:
    linux_tesseract = shutil.which("tesseract")
    if linux_tesseract:
        pytesseract.pytesseract.tesseract_cmd = linux_tesseract

class OCRExtractionError(Exception):
    """Raised when OCR extraction fails."""


def extract_image_text(file_path: str) -> dict:
    """Extract text from JPG, JPEG or PNG images using Tesseract."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path.name}")

    if not path.is_file():
        raise OCRExtractionError("The provided path is not a file.")

    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise OCRExtractionError("Unsupported image format.")

    if path.stat().st_size == 0:
        raise OCRExtractionError("The image file is empty.")

    try:
        with Image.open(path) as image:
            image.verify()

        with Image.open(path) as image:
            text = pytesseract.image_to_string(
                image.convert("RGB"),
                lang="eng"
            ).strip()

        return {
            "filename": path.name,
            "total_pages": 1,
            "extraction_method": "tesseract_ocr",
            "status": "success" if text else "no_text",
            "full_text": text,
            "pages": [
                {
                    "page_number": 1,
                    "text": text
                }
            ]
        }

    except UnidentifiedImageError as exc:
        raise OCRExtractionError("Invalid or unreadable image.") from exc
    except OCRExtractionError:
        raise
    except Exception as exc:
        raise OCRExtractionError(f"Image OCR failed: {exc}") from exc


def extract_scanned_pdf_text(file_path: str) -> dict:
    """Extract text from scanned PDF pages using Tesseract."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path.name}")

    if not path.is_file():
        raise OCRExtractionError("The provided path is not a file.")

    if path.suffix.lower() != ".pdf":
        raise OCRExtractionError("Expected a PDF file.")

    if path.stat().st_size == 0:
        raise OCRExtractionError("The PDF file is empty.")

    try:
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:

            if document.is_encrypted:
                raise OCRExtractionError(
                    "Password-protected PDFs are not supported."
                )

            if len(document) == 0:
                raise OCRExtractionError("The PDF contains no pages.")

            pages = []
            full_text = []

            for page_number, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    alpha=False
                )

                image = Image.frombytes(
                    "RGB",
                    [pixmap.width, pixmap.height],
                    pixmap.samples
                )

                text = pytesseract.image_to_string(
                    image,
                    lang="eng"
                ).strip()

                pages.append({
                    "page_number": page_number,
                    "text": text
                })

                full_text.append(text)

            combined_text = "\n\n".join(full_text).strip()

            return {
                "filename": path.name,
                "total_pages": len(document),
                "extraction_method": "tesseract_ocr",
                "status": "success" if combined_text else "no_text",
                "full_text": combined_text,
                "pages": pages
            }

    except OCRExtractionError:
        raise
    except Exception as exc:
        raise OCRExtractionError(
            f"Scanned PDF OCR failed: {exc}"
        ) from exc
