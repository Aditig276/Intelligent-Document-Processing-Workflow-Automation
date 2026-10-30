from django.apps import AppConfig


class ProcessingJobsConfig(AppConfig):
    name = 'processing_jobs'

    def ready(self):
        import processing_jobs.signals  # noqa: F401
