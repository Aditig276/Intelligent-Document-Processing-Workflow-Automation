from django.contrib import admin
from django.urls import include, path

import processing_jobs.urls

# Root patterns without app namespace for backwards-compatible unnamespaced reversals of UI routes
root_patterns = list(processing_jobs.urls.urlpatterns)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("api/", include("documents.urls")),
    path("", include("processing_jobs.urls", namespace="processing_jobs")),
    path("", include((root_patterns, None))),
]
