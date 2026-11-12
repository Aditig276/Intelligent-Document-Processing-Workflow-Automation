import hashlib
import uuid
import pymupdf
from pathlib import Path
from PIL import Image, UnidentifiedImageError
import io
import openpyxl
import xlrd
import zipfile
import csv
import tempfile
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.middleware.csrf import get_token
from django.shortcuts import render
from datetime import datetime
from decimal import Decimal, InvalidOperation

from processing_jobs.models import ProcessingJob

from app.extractors.extraction_service import extract_document_text
from app.extractors.pdf_extractor import PDFExtractionError
from app.extractors.ocr_extractor import OCRExtractionError

logger = logging.getLogger(__name__)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}


def health_check(request):
    return JsonResponse({"status": "healthy"})

@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({
        "message": "CSRF cookie set",
        "csrfToken": get_token(request),
    })

@require_POST
def upload_file(request):
    uploaded_file = request.FILES.get("file")
    if getattr(request, "upload_too_large", False):
        return JsonResponse(
            {"error": "File exceeds the 10 MiB size limit."},
            status=413,
        )

    if uploaded_file is None:
        return JsonResponse(
            {"error": "No file provided. Use the 'file' field."},
            status=400,
        )

    original_name = Path(uploaded_file.name).name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        return JsonResponse(
            {"error": "Unsupported file format."},
            status=400,
        )

    if uploaded_file.size == 0:
        return JsonResponse(
            {"error": "Empty files are not allowed."},
            status=400,
        )

    if uploaded_file.size > MAX_FILE_SIZE:
        return JsonResponse(
            {"error": "File exceeds the 10 MB size limit."},
            status=413,
        )

    # Validate the actual contents of PDF files.
    if extension == ".pdf":
        try:
            pdf_bytes = uploaded_file.read()
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
                if pdf.page_count < 1:
                    return JsonResponse(
                        {"error": "PDF must contain at least one page."},
                        status=400,
                    )
        except (pymupdf.FileDataError, ValueError, RuntimeError):
            return JsonResponse(
                {"error": "Invalid or corrupted PDF file."},
                status=400,
            )
        finally:
            uploaded_file.seek(0)

    # Validate the actual contents of image files.
    image_extensions = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}

    if extension in image_extensions:
        try:
            image_bytes = uploaded_file.read()

            with Image.open(io.BytesIO(image_bytes)) as image:
                image.verify()

            # Ensure the image format matches the filename extension.
            with Image.open(io.BytesIO(image_bytes)) as image:
                expected_formats = {
                    ".png": {"PNG"},
                    ".jpg": {"JPEG"},
                    ".jpeg": {"JPEG"},
                    ".tif": {"TIFF"},
                    ".tiff": {"TIFF"},
                }

                if image.format not in expected_formats[extension]:
                    return JsonResponse(
                        {"error": "Image contents do not match the file extension."},
                        status=400,
                    )

        except (UnidentifiedImageError, OSError, ValueError):
            return JsonResponse(
                {"error": "Invalid or corrupted image file."},
                status=400,
            )
        finally:
            uploaded_file.seek(0)

    # Validate actual Excel workbook contents.
    if extension in {".xlsx", ".xls"}:
        try:
            excel_bytes = uploaded_file.read()

            if extension == ".xlsx":
                # XLSX files must be valid ZIP-based Excel workbooks.
                if not zipfile.is_zipfile(io.BytesIO(excel_bytes)):
                    raise ValueError("Invalid XLSX archive.")

                workbook = openpyxl.load_workbook(
                    io.BytesIO(excel_bytes),
                    read_only=True,
                    data_only=True,
                )
                workbook.close()

            else:
                # XLS files must be readable by the legacy Excel parser.
                workbook = xlrd.open_workbook(
                    file_contents=excel_bytes,
                    on_demand=True,
                )
                workbook.release_resources()

        except (
            ValueError,
            OSError,
            zipfile.BadZipFile,
            openpyxl.utils.exceptions.InvalidFileException,
            xlrd.XLRDError,
        ):
            return JsonResponse(
                {"error": "Invalid or corrupted Excel file."},
                status=400,
            )
        finally:
            uploaded_file.seek(0)

    # Validate CSV content as UTF-8 text.
    if extension == ".csv":
        try:
            csv_bytes = uploaded_file.read()
            csv_text = csv_bytes.decode("utf-8-sig")

            # Check that the text can be parsed as CSV.
            csv_reader = csv.reader(io.StringIO(csv_text))
            next(csv_reader, None)

        except (UnicodeDecodeError, csv.Error):
            return JsonResponse(
                {"error": "Invalid CSV file. Expected UTF-8 text."},
                status=400,
            )
        finally:
            uploaded_file.seek(0)

    # Generate a server-side filename instead of trusting the user's filename.
    stored_name = f"{uuid.uuid4().hex}{extension}"
    upload_dir = Path(settings.MEDIA_ROOT)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / stored_name

    checksum = hashlib.sha256()

    try:
        with destination.open("xb") as output:
            for chunk in uploaded_file.chunks():
                checksum.update(chunk)
                output.write(chunk)

    except OSError:
        destination.unlink(missing_ok=True)
        return JsonResponse(
            {"error": "Unable to store the uploaded file."},
            status=500,
        )

    return JsonResponse(
        {
            "message": "File uploaded successfully.",
            "original_filename": original_name,
            "stored_filename": stored_name,
            "size_bytes": uploaded_file.size,
            "sha256": checksum.hexdigest(),
        },
        status=201,
    )



@require_POST
def extract_file(request):
    """Extract text from an uploaded PDF or image."""

    uploaded_file = request.FILES.get("file")

    if getattr(request, "upload_too_large", False):
        return JsonResponse(
            {"error": "File exceeds the 10 MB size limit."},
            status=413,
        )

    if uploaded_file is None:
        return JsonResponse(
            {"error": "No file provided. Use the 'file' field."},
            status=400,
        )

    if uploaded_file.size == 0:
        return JsonResponse(
            {"error": "Empty files are not allowed."},
            status=400,
        )

    if uploaded_file.size > MAX_FILE_SIZE:
        return JsonResponse(
            {"error": "File exceeds the 10 MB size limit."},
            status=413,
        )

    original_name = Path(uploaded_file.name).name
    extension = Path(original_name).suffix.lower()

    supported_formats = {".pdf", ".png", ".jpg", ".jpeg"}

    if extension not in supported_formats:
        return JsonResponse(
            {
                "error": (
                    "Extraction supports PDF, PNG, JPG and JPEG files."
                )
            },
            status=400,
        )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:

            temp_path = Path(temp_dir) / f"document{extension}"

            with temp_path.open("wb") as output:
                for chunk in uploaded_file.chunks():
                    output.write(chunk)

            result = extract_document_text(str(temp_path))

            result["filename"] = original_name

            return JsonResponse(result, status=200)

    except (
        PDFExtractionError,
        OCRExtractionError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        return JsonResponse(
            {"error": str(exc)},
            status=400,
        )
    except Exception:
        logger.exception("Document extraction failed")
        return JsonResponse(
            {"error": "Document extraction failed."},
            status=500,
        )
 



def extraction_review(request):
    extracted_data = {
        "document_name": "",
        "invoice_number": "",
        "document_date": "",
        "customer_name": "",
        "total_amount": "",
    }

    extracted_text = ""
    errors = {}
    message = ""
    job_id = ""

    if request.method == "POST":

        uploaded_file = request.FILES.get("file")

        # Upload and extract document
        if uploaded_file:
            original_name = Path(uploaded_file.name).name
            extension = Path(original_name).suffix.lower()

            if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
                errors["document"] = "Unsupported file format."

            elif uploaded_file.size == 0:
                errors["document"] = "Empty files are not allowed."

            elif uploaded_file.size > MAX_FILE_SIZE:
                errors["document"] = "File exceeds the 10 MB size limit."

            else:
                stored_filename = f"{uuid.uuid4().hex}{extension}"
                upload_dir = Path(settings.MEDIA_ROOT)
                upload_dir.mkdir(parents=True, exist_ok=True)
                file_path = upload_dir / stored_filename

                try:
                    with file_path.open("xb") as output:
                        for chunk in uploaded_file.chunks():
                            output.write(chunk)

                    result = extract_document_text(str(file_path))
                    extracted_text = result.get("full_text", "")

                    job = ProcessingJob.objects.create(
                        owner=request.user if request.user.is_authenticated else None,
                        file_name=original_name,
                        file_type=extension.lstrip("."),
                        file_size=uploaded_file.size,
                        storage_reference=stored_filename,
                        status=ProcessingJob.Status.COMPLETED,
                    )

                    job_id = str(job.id)
                    extracted_data["document_name"] = original_name
                    message = "Document extracted successfully."

                except Exception:
                    logger.exception("Document extraction failed")
                    file_path.unlink(missing_ok=True)
                    errors["document"] = "Document extraction failed."

        # Save reviewed fields
        elif request.POST.get("job_id"):
            try:
                job = ProcessingJob.objects.get(
                    id=request.POST.get("job_id")
                )

                if job.owner_id and job.owner_id != request.user.id:
                    errors["document"] = "You cannot access this document."
                else:
                    file_path = Path(settings.MEDIA_ROOT) / Path(
                        job.storage_reference
                    ).name

                    if not file_path.is_file():
                        errors["document"] = "Uploaded document not found."
                    else:
                        result = extract_document_text(str(file_path))
                        extracted_text = result.get("full_text", "")
                        job_id = str(job.id)

                        for field in extracted_data:
                            extracted_data[field] = request.POST.get(
                                field, ""
                            ).strip()

                        for field, value in extracted_data.items():
                            if not value:
                                errors[field] = "This field is required."

                        if extracted_data["document_date"]:
                            try:
                                datetime.strptime(
                                    extracted_data["document_date"],
                                    "%Y-%m-%d"
                                )
                            except ValueError:
                                errors["document_date"] = (
                                    "Enter date in YYYY-MM-DD format."
                                )

                        if extracted_data["total_amount"]:
                            try:
                                amount = Decimal(
                                    extracted_data["total_amount"]
                                )
                                if not amount.is_finite() or amount < 0:
                                    raise InvalidOperation
                            except (InvalidOperation, ValueError):
                                errors["total_amount"] = (
                                    "Enter a valid non-negative amount."
                                )

                        if errors:
                            message = "Please correct the highlighted fields."
                        else:
                            job.reviewed_data = extracted_data
                            job.save(update_fields=[
                                "reviewed_data",
                                "updated_at",
                            ])
                            message = "Reviewed data saved successfully."

            except ProcessingJob.DoesNotExist:
                errors["document"] = "Processing job not found."

            except Exception:
                logger.exception("Review saving failed")
                errors["document"] = "Unable to save reviewed data."

    return render(
        request,
        "documents/extraction_review.html",
        {
            "job_id": job_id,
            "extracted_data": extracted_data,
            "extracted_text": extracted_text,
            "errors": errors,
            "message": message,
        },
    )
