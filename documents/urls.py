from django.urls import path

from processing_jobs import api_views
from . import views

urlpatterns = [
    # Health check endpoints
    path("health/", views.health_check, name="health_check"),
    path("health/", views.health_check, name="api_health"),
    # Canonical document upload endpoints
    path("upload/", api_views.upload_file, name="upload_file"),
    path("upload/", api_views.upload_file, name="api_upload"),
]
