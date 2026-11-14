
from django.conf import settings
from django.db import models


class ProcessingJob(models.Model):

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="processing_jobs",
        null=True,
        blank=True,
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    file_size = models.PositiveBigIntegerField(default=0)

    storage_reference = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    reviewed_data = models.JSONField(
        default=dict,
        blank=True,
    )

    extracted_data = models.JSONField(
        null=True,
        blank=True,
        default=None,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    error_message = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} - {self.status}"
