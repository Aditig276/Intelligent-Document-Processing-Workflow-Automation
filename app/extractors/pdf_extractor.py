
from pathlib import Path
import pymupdf


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be processed."""


def extract_pdf_text(file_path: str) -> dict:
    """
    Extract text page by page from a digital PDF.

    Returns a consistent dictionary containing document
    information and extracted page text.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path.name}")

    if not path.is_file():
        raise PDFExtractionError("The provided path is not a file.")

    if path.suffix.lower() != ".pdf":
        raise PDFExtractionError("Unsupported file format. Expected PDF.")

    if path.stat().st_size == 0:
        raise PDFExtractionError("The PDF file is empty.")

    try:
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:

            if document.is_encrypted:
                raise PDFExtractionError("Password-protected PDFs are not supported.")

            if len(document) == 0:
                raise PDFExtractionError("The PDF contains no pages.")

            pages = []
            full_text = []

            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()

                pages.append({
                    "page_number": page_number,
                    "text": text
                })

                full_text.append(text)

            combined_text = "\n\n".join(full_text).strip()

            return {
                "filename": path.name,
                "total_pages": len(document),
                "extraction_method": "pymupdf",
                "status": "success" if combined_text else "no_text",
                "full_text": combined_text,
                "pages": pages
            }

    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(
            f"Unable to extract PDF text: {exc}"
        ) from exc
