import warnings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from processing_jobs import api_views

# Backward compatibility module attributes matching processing_jobs.api_views
MAX_FILE_SIZE = api_views.MAX_FILE_SIZE  # 10 MiB
ALLOWED_EXTENSIONS = api_views.ALLOWED_EXTENSIONS


@require_http_methods(["GET"])
def health_check(request):
    """Health check endpoint: GET /api/health/ -> 200 {"status": "healthy"}."""
    return JsonResponse({"status": "healthy"})


def upload_file(request, *args, **kwargs):
    """Deprecated: Unauthenticated documents.views.upload_file is deprecated.

    All file uploads must route through processing_jobs.api_views.upload_file
    to enforce authentication, authorization, rate limiting, upload validation,
    and ProcessingJob creation.
    """
    warnings.warn(
        "documents.views.upload_file is deprecated; use processing_jobs.api_views.upload_file instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return api_views.upload_file(request, *args, **kwargs)
