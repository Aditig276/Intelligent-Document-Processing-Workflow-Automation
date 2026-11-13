"""Django integration adapter for the owner-only Week 1 permission policy.

SECURITY CONTRACT:
- Pass only `request.user` from Django's configured authentication middleware.
- Pass only a real ProcessingJob retrieved from the server-side database.
- Do not use IDs from request bodies, query strings, or custom headers as proof
  of user identity or resource ownership.
- This adapter DOES NOT protect Django routes until the views call it.
- All checks deny access if the user, job, or ownership data is missing.
"""

from uuid import UUID

from .permissions import (
    AuthenticatedUser,
    OwnedResource,
    can_access_document,
    can_access_owned_resource,
    can_access_result,
    can_download_report,
    can_upload_document,
)


def _identifier(value: object) -> str | None:
    """Normalize supported PK types; reject absent or malformed identifiers."""
    if isinstance(value, bool) or not isinstance(value, (str, int, UUID)):
        return None
    text = str(value).strip()
    return text or None


def actor_from_django_user(django_user: object) -> AuthenticatedUser | None:
    """Adapt an already authenticated Django request.user to the policy.

    Checking `is_authenticated` here does not validate a password/session.
    Django middleware must have already established request.user.
    """
    if getattr(django_user, "is_authenticated", False) is not True:
        return None
    if getattr(django_user, "is_active", False) is not True:
        return None
    user_id = _identifier(getattr(django_user, "pk", None))
    if user_id is None:
        return None
    return AuthenticatedUser(user_id=user_id, is_active=True)


def can_django_user_upload(django_user: object) -> bool:
    """Allow only active, already authenticated Django users to upload."""
    return can_upload_document(actor_from_django_user(django_user))


def can_django_user_access_job(django_user: object, job: object) -> bool:
    """Only the job owner may access its document, results, or reports.

    `job.owner_id` must be populated from a trusted Django database model.
    Until the owner field is added, this deliberately returns False.
    """
    actor = actor_from_django_user(django_user)
    job_id = _identifier(getattr(job, "pk", None))
    owner_id = _identifier(getattr(job, "owner_id", None))
    if job_id is None or owner_id is None:
        return False
    return can_access_owned_resource(
        actor,
        OwnedResource(resource_id=job_id, owner_user_id=owner_id),
    )


def can_django_user_access_document(django_user: object, job_or_doc: object) -> bool:
    """Only the authenticated owner may access or download the source document."""
    actor = actor_from_django_user(django_user)
    doc_id = _identifier(getattr(job_or_doc, "resource_id", getattr(job_or_doc, "pk", None)))
    owner_id = _identifier(getattr(job_or_doc, "owner_user_id", getattr(job_or_doc, "owner_id", None)))
    if doc_id is None or owner_id is None:
        return False
    return can_access_document(
        actor,
        OwnedResource(resource_id=doc_id, owner_user_id=owner_id),
    )


def can_django_user_download_report(django_user: object, job_or_report: object) -> bool:
    """Only the authenticated owner may download a generated report."""
    actor = actor_from_django_user(django_user)
    report_id = _identifier(getattr(job_or_report, "resource_id", getattr(job_or_report, "pk", None)))
    owner_id = _identifier(getattr(job_or_report, "owner_user_id", getattr(job_or_report, "owner_id", None)))
    if report_id is None or owner_id is None:
        return False
    return can_download_report(
        actor,
        OwnedResource(resource_id=report_id, owner_user_id=owner_id),
    )


def can_django_user_access_history(django_user: object, job_or_record: object) -> bool:
    """Only the authenticated owner may access processing history details."""
    actor = actor_from_django_user(django_user)
    record_id = _identifier(getattr(job_or_record, "resource_id", getattr(job_or_record, "pk", None)))
    owner_id = _identifier(getattr(job_or_record, "owner_user_id", getattr(job_or_record, "owner_id", None)))
    if record_id is None or owner_id is None:
        return False
    return can_access_result(
        actor,
        OwnedResource(resource_id=record_id, owner_user_id=owner_id),
    )


def get_authorized_job_or_404(django_user: object, job_id: object):
    """Retrieve a job by PK strictly verifying that the authenticated user is the owner.

    Raises Http404 on missing, unowned, or foreign jobs to prevent resource enumeration/IDOR.
    """
    from django.http import Http404
    from processing_jobs.models import ProcessingJob

    clean_id = _identifier(job_id)
    if clean_id is None:
        raise Http404("Job not found.")

    try:
        job = ProcessingJob.objects.select_related("owner").get(pk=clean_id)
    except (ProcessingJob.DoesNotExist, ValueError):
        raise Http404("Job not found.")

    if not can_django_user_access_job(django_user, job):
        raise Http404("Job not found.")

    return job


def filter_user_processing_history(django_user: object, queryset=None):
    """Return a ProcessingJob queryset strictly isolated to the authenticated user.

    If the user is anonymous or inactive, returns an empty queryset (none()).
    """
    from processing_jobs.models import ProcessingJob

    if queryset is None:
        queryset = ProcessingJob.objects.all()

    actor = actor_from_django_user(django_user)
    if actor is None:
        return queryset.none()

    return queryset.filter(owner__pk=actor.user_id)
