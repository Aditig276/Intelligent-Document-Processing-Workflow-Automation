import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

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

@csrf_exempt
@require_POST
def upload_file(request):
    uploaded_file = request.FILES.get("file")

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
