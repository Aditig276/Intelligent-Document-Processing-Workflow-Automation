from django.urls import path

from . import api_views, views

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
    path("job/<int:job_id>/download/excel/",views.download_excel_report,name="download_excel_report",),

    # Source document download (protected)
    path("job/<int:job_id>/document/", views.download_document, name="download_document"),
    path("jobs/<int:job_id>/document/", views.download_document, name="download_source_document"),

    # Generated reports download (protected: Excel & PDF)
    path("job/<int:job_id>/report/<str:report_type>/", views.download_report, name="download_report"),
    path("jobs/<int:job_id>/report/<str:report_type>/", views.download_report, name="download_report_alias"),
    path("job/<int:job_id>/report/excel/", views.download_report, {"report_type": "excel"}, name="download_report_excel"),
    path("job/<int:job_id>/report/pdf/", views.download_report, {"report_type": "pdf"}, name="download_report_pdf"),

    # API endpoints
    path("api/health/", api_views.health_check, name="api_health"),
    path("api/upload/", api_views.upload_file, name="api_upload"),

    # API processing history and job detail (protected)
    path("api/jobs/", api_views.processing_history_api, name="api_processing_history"),
    path("api/history/", api_views.processing_history_api, name="api_history"),
    path("api/jobs/<int:job_id>/", api_views.job_detail_api, name="api_job_detail"),
    path("api/jobs/<int:job_id>/document/", api_views.download_document_api, name="api_download_document"),
    path("api/jobs/<int:job_id>/report/<str:report_type>/", api_views.download_report_api, name="api_download_report"),
    path("api/jobs/<int:job_id>/report/excel/", api_views.download_report_api, {"report_type": "excel"}, name="api_download_report_excel"),
    path("api/jobs/<int:job_id>/report/pdf/", api_views.download_report_api, {"report_type": "pdf"}, name="api_download_report_pdf"),
]
