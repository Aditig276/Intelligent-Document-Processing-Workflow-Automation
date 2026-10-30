from django.urls import path

from . import api_views, views

app_name = "processing_jobs"

urlpatterns = [
    # Document upload
    path("", views.upload_document, name="upload_document"),
    path("", views.upload_document, name="upload"),

    # Processing dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # Job detail & extraction result view
    path("job/<int:job_id>/", views.job_detail, name="job_detail"),
    path("job/<int:job_id>/", views.job_detail, name="view_extracted_data"),

    # Manual extraction trigger (and job page on GET)
    path(
        "job/<int:job_id>/extract/",
        views.extract_job,
        name="extract_job",
    ),
    path(
        "job/<int:job_id>/extract/",
        views.extract_job,
        name="extract",
    ),

    # Result download
    path(
        "job/<int:job_id>/download/",
        views.download_result,
        name="download_result",
    ),
    path(
        "job/<int:job_id>/download/",
        views.download_result,
        name="download_json",
    ),

    # API endpoints
    path("api/health/", api_views.health_check, name="api_health"),
    path("api/upload/", api_views.upload_file, name="api_upload"),
]
