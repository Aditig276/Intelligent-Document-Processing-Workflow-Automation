from django.urls import path

from . import views

app_name = "processing_jobs"

urlpatterns = [
    # Document upload
    path("", views.upload_document, name="upload_document"),
    path("upload/", views.upload_document, name="upload"),

    # Processing dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # Job detail & extraction result view
    path("job/<int:job_id>/", views.job_detail, name="job_detail"),
    path("jobs/<int:job_id>/data/", views.job_detail, name="view_extracted_data"),

    # Manual extraction trigger
    path("job/<int:job_id>/extract/", views.extract_job, name="extract_job"),
    path("jobs/<int:job_id>/", views.extract_job, name="extract"),

    # Result download
    path("job/<int:job_id>/download/", views.download_result, name="download_result"),
    path("jobs/<int:job_id>/download/", views.download_result, name="download_json"),
]
