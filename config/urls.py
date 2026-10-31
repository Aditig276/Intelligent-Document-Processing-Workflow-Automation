from django.contrib import admin
from django.urls import include, path

import processing_jobs.urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("processing_jobs.urls", namespace="processing_jobs")),
    *processing_jobs.urls.urlpatterns,
]
