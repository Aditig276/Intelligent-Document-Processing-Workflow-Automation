
import json
import time

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from processing_jobs.models import ProcessingJob
from processing_jobs.extractors import extract_document


class Command(BaseCommand):
    help = "Process pending document extraction jobs."

    def handle(self, *args, **options):
        self.stdout.write("Document processing worker started.")

        while True:
            close_old_connections()

            job = (
                ProcessingJob.objects
                .filter(status=ProcessingJob.Status.PENDING)
                .order_by("created_at")
                .first()
            )

            if job is None:
                time.sleep(2)
                continue

            try:
                # Mark job as processing
                job.status = ProcessingJob.Status.PROCESSING
                job.error_message = ""
                job.save()

                # Resolve stored file path
                file_path = Path(job.storage_reference)

                if not file_path.is_absolute():
                    file_path = Path(settings.MEDIA_ROOT) / file_path

                if not file_path.exists():
                    raise FileNotFoundError(
                        "Stored document was not found."
                    )

                # Read document
                file_data = file_path.read_bytes()

                # Extract document data
                result = extract_document(
                    file_data,
                    job.file_name
                )

                # Save extraction result
                result_dir = Path(settings.MEDIA_ROOT) / "extracted"
                result_dir.mkdir(parents=True, exist_ok=True)

                result_path = result_dir / f"job_{job.id}.json"

                result_path.write_text(
                    json.dumps(
                        result,
                        indent=4,
                        default=str
                    ),
                    encoding="utf-8"
                )

                # Mark job as completed
                job.status = ProcessingJob.Status.COMPLETED
                job.error_message = ""
                job.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed job {job.id}: {job.file_name}"
                    )
                )

            except Exception as error:
                # Mark failed jobs and continue processing
                job.status = ProcessingJob.Status.FAILED
                job.error_message = str(error)[:2000]
                job.save()

                self.stderr.write(
                    self.style.ERROR(
                        f"Failed job {job.id}: {error}"
                    )
                )
