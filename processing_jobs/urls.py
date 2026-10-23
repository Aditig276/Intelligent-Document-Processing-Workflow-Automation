
from django.urls import path
from . import views

app_name = "processing_jobs"


urlpatterns = [
    path("", views.job_dashboard, name="dashboard"),
    path("upload/", views.upload_document, name="upload"),
    path("jobs/<int:job_id>/", views.extract_job, name="extract"),
    path(
        "jobs/<int:job_id>/download/",
        views.download_extraction_json,
        name="download_json",
    ),
    path(
        "jobs/<int:job_id>/data/",
        views.view_extracted_data,
        name="view_extracted_data",
    ),
]
