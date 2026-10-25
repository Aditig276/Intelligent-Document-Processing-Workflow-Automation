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
    can_access_owned_resource,
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
