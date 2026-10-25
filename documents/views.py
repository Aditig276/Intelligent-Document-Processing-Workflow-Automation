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
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST

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
