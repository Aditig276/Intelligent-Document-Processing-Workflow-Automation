from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health_check, name="health_check"),
    path("csrf/", views.csrf_token, name="csrf_token"),
    path("upload/", views.upload_file, name="upload_file"),
    path("extract/", views.extract_file, name="extract_file"),
    
]
