import json
import logging
from pathlib import Path
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import (
    DatabaseError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)

from processing_jobs.extractors import extract_document
from processing_jobs.models import ProcessingJob

logger = logging.getLogger("processing_jobs")


def claim_next_job():
    """Atomically claim the next pending ProcessingJob for processing.

    Uses transaction.atomic() and select_for_update() row-level locking where supported
    by the database backend (with skip_locked=True on engines that support it like PostgreSQL).
    Handles database-specific limitations (such as SQLite database table locks) gracefully.
    Atomically updates status to PROCESSING so that concurrent workers cannot claim the same job.
    """
    try:
        with transaction.atomic():
            qs = ProcessingJob.objects.filter(status=ProcessingJob.Status.PENDING)

            if connection.features.has_select_for_update_skip_locked:
                qs = qs.select_for_update(skip_locked=True)
            elif connection.features.has_select_for_update:
                qs = qs.select_for_update()

            job = qs.order_by("created_at").first()
            if job is None:
                return None

            # Double check status inside the atomic transaction block
            if job.status != ProcessingJob.Status.PENDING:
                return None

            job.status = ProcessingJob.Status.PROCESSING
            job.error_message = ""
            job.save(update_fields=["status", "error_message", "updated_at"])

            try:
                logger.info("Job %s status changed to processing.", job.id)
            except Exception:
                pass

            return job
    except OperationalError as exc:
        # On SQLite or engines under lock contention, another worker holds the lock
        try:
            logger.debug("Database locked or contention during claim_next_job: %s", exc)
        except Exception:
            pass
        return None


def process_claimed_job(job, stdout=None, stderr=None):
    """Execute document extraction and result storage for a claimed job."""
    try:
        # Resolve stored file path
        file_path = Path(job.storage_reference)

        if not file_path.is_absolute():
            file_path = Path(settings.MEDIA_ROOT) / file_path

        if not file_path.exists():
            raise FileNotFoundError("Stored document was not found.")

        # Read document
        file_data = file_path.read_bytes()

        # Extract document data
        result = extract_document(file_data, job.file_name)
        job.extracted_data = result

        # Save extraction result
        result_dir = Path(settings.MEDIA_ROOT) / "extracted"
        result_dir.mkdir(parents=True, exist_ok=True)

        result_path = result_dir / f"job_{job.id}.json"

        result_path.write_text(
            json.dumps(result, indent=4, default=str),
            encoding="utf-8",
        )

        # Mark job as completed
        job.status = ProcessingJob.Status.COMPLETED
        job.error_message = ""
        job.save(update_fields=["status", "error_message", "updated_at", "extracted_data"])

        try:
            logger.info(
                "Job %s status changed to completed. Extracted document %s.",
                job.id,
                job.file_name,
            )
        except Exception:
            pass

        if stdout:
            stdout.write(f"Completed job {job.id}: {job.file_name}")

        return True

    except Exception as error:
        # Mark failed jobs and continue processing
        job.status = ProcessingJob.Status.FAILED
        job.error_message = str(error)[:2000]
        job.save(update_fields=["status", "error_message", "updated_at"])

        try:
            logger.error("Job %s failed: %s", job.id, error)
        except Exception:
            pass

        if stderr:
            stderr.write(f"Failed job {job.id}: {error}")

        return False


class Command(BaseCommand):
    help = "Process pending document extraction jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one job and exit immediately.",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=None,
            help="Process up to N jobs and exit.",
        )

    def handle(self, *args, **options):
        once = options.get("once", False)
        max_jobs = options.get("max_jobs")
        jobs_processed = 0

        self.stdout.write("Document processing worker started.")
        try:
            logger.info("Document processing worker started.")
        except Exception:
            pass

        while True:
            close_old_connections()

            job = claim_next_job()

            if job is None:
                if once or (max_jobs is not None and jobs_processed >= max_jobs):
                    break
                time.sleep(2)
                continue

            process_claimed_job(
                job,
                stdout=self.stdout,
                stderr=self.stderr,
            )
            jobs_processed += 1

            if once or (max_jobs is not None and jobs_processed >= max_jobs):
                break
