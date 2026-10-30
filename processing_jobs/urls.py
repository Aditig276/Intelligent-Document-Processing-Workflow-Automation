from django.urls import path

from . import api_views, views


urlpatterns = [
    path("", views.upload_document, name="upload_document"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("job/<int:job_id>/", views.job_detail, name="job_detail"),
    path(
        "job/<int:job_id>/extract/",
        views.extract_job,
        name="extract_job",
    ),
    path(
        "job/<int:job_id>/download/",
        views.download_result,
        name="download_result",
    ),
    path("api/health/", api_views.health_check, name="api_health"),
    path("api/upload/", api_views.upload_file, name="api_upload"),
]
