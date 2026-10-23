
from django.contrib import admin
from .models import ProcessingJob


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "file_name",
        "file_type",
        "status",
        "created_at",
        "updated_at",
    )

    list_filter = ("status", "file_type")
    search_fields = ("file_name", "error_message")
    readonly_fields = ("created_at", "updated_at")
