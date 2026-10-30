from django.contrib import admin
from .models import ProcessingJob


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "file_name",
        "file_type",
        "owner",
        "status",
        "created_at",
    )

    list_filter = ("status", "file_type", "owner")
    search_fields = ("file_name", "owner__username")
    ordering = ("-created_at",)
