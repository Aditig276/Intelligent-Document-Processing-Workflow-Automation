from pathlib import Path
import shutil

import pymupdf
import pytesseract
from PIL import Image, UnidentifiedImageError


class OCRExtractionError(Exception):
    """Raised when OCR processing fails."""


# Configure Tesseract OCR
windows_tesseract = Path(
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
tesseract_path = shutil.which("tesseract")

if windows_tesseract.is_file():
    pytesseract.pytesseract.tesseract_cmd = str(windows_tesseract)
elif tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path


def extract_image_text(file_path: str) -> dict:
    """Extract text from an image using Tesseract OCR."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path.name}")

    if not path.is_file():
        raise OCRExtractionError("The provided path is not a file.")

    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise OCRExtractionError("Unsupported image format.")

    if path.stat().st_size == 0:
        raise OCRExtractionError("The image file is empty.")

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            extracted_text = pytesseract.image_to_string(
                image, lang="eng"
            ).strip()

        return {
            "filename": path.name,
            "total_pages": 1,
            "extraction_method": "tesseract_ocr",
            "status": "success" if extracted_text else "no_text",
            "full_text": extracted_text,
            "pages": [
                {
                    "page_number": 1,
                    "text": extracted_text
                }
            ]
        }

    except (UnidentifiedImageError, OSError) as exc:
        raise OCRExtractionError(
            f"Unable to process image: {exc}"
        ) from exc
    except Exception as exc:
        raise OCRExtractionError(
            f"Image OCR failed: {exc}"
        ) from exc


def extract_scanned_pdf_text(file_path: str) -> dict:
    """Extract text from a scanned PDF using Tesseract OCR."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path.name}")

    if not path.is_file():
        raise OCRExtractionError("The provided path is not a file.")

    if path.suffix.lower() != ".pdf":
        raise OCRExtractionError("Unsupported file format. Expected PDF.")

    if path.stat().st_size == 0:
        raise OCRExtractionError("The PDF file is empty.")

    try:
        with pymupdf.open(
            stream=path.read_bytes(),
            filetype="pdf"
        ) as document:

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
                    colorspace=pymupdf.csRGB,
                    alpha=False
                )

                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples
                )

                extracted_text = pytesseract.image_to_string(
                    image, lang="eng"
                ).strip()

                pages.append({
                    "page_number": page_number,
                    "text": extracted_text
                })

                full_text.append(extracted_text)

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
            f"Unable to extract scanned PDF text: {exc}"
        ) from exc
