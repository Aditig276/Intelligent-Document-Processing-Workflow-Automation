
import time

from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.db import close_old_connections

from processing_jobs.models import ProcessingJob
from processing_jobs.extractors import extract_document


class Command(BaseCommand):
    help = "Process pending document extraction jobs"

    def handle(self, *args, **options):
        self.stdout.write("Document worker started. Waiting for jobs...")

        while True:
            close_old_connections()

            try:
                job = (
                    ProcessingJob.objects
                    .filter(status=ProcessingJob.Status.PENDING)
                    .order_by("created_at")
                    .first()
                )

                if job is None:
                    time.sleep(2)
                    continue

                # Mark the job as processing
                job.status = ProcessingJob.Status.PROCESSING
                job.error_message = ""
                job.save()

                self.stdout.write(f"Processing job {job.id}: {job.file_name}")

                try:
                    with default_storage.open(
                        job.storage_reference, "rb"
                    ) as stored_file:
                        file_bytes = stored_file.read()

                    # Run extraction
                    result = extract_document(file_bytes, job.file_name)

                    # Save extracted JSON to media/extracted/
                    import json

                    result_path = default_storage.save(
                        f"extracted/job_{job.id}.json",
                        __import__("io").BytesIO(
                            json.dumps(
                                result,
                                ensure_ascii=False,
                                indent=2,
                                default=str,
                            ).encode("utf-8")
                        ),
                    )

                    job.status = ProcessingJob.Status.COMPLETED
                    job.save()

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Job {job.id} completed. Result: {result_path}"
                        )
                    )

                except Exception as exc:
                    job.status = ProcessingJob.Status.FAILED
                    job.error_message = str(exc)[:2000]
                    job.save()

                    self.stderr.write(
                        self.style.ERROR(f"Job {job.id} failed: {exc}")
                    )

            finally:
                close_old_connections()
