"""Adapter unit tests. These are NOT live Django view or database tests."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.security.django_adapter import (
    actor_from_django_user,
    can_django_user_access_job,
    can_django_user_upload,
)


def user(pk=101, authenticated=True, active=True):
    """Django-like stub; the production adapter must get real request.user."""
    return SimpleNamespace(
        pk=pk, is_authenticated=authenticated, is_active=active
    )


def job(pk=501, owner_id=101):
    """Django-like stub; production must use a job loaded from the DB."""
    return SimpleNamespace(pk=pk, owner_id=owner_id)


@pytest.mark.parametrize(
    "django_user,expected",
    [
        (user(), True),
        (user(authenticated=False), False),
        (user(active=False), False),
        (None, False),
        (user(pk=None), False),
        (user(pk=" "), False),
        (user(pk=True), False),
    ],
)
def test_upload_permissions(django_user, expected):
    assert can_django_user_upload(django_user) is expected


@pytest.mark.parametrize(
    "django_user,processing_job,expected",
    [
        (user(101), job(owner_id=101), True),
        (user(102), job(owner_id=101), False),
        (user(101, authenticated=False), job(owner_id=101), False),
        (user(101, active=False), job(owner_id=101), False),
        (None, job(owner_id=101), False),
        (user(101), None, False),
        (user(101), job(owner_id=None), False),
        (user(101), job(pk=None), False),
        (user(101), object(), False),
        (user(101), job(owner_id=True), False),
        (user("a"), job(owner_id="a"), True),
        (user(UUID("12345678-1234-5678-1234-567812345678")),
         job(owner_id=UUID("12345678-1234-5678-1234-567812345678")), True),
    ],
)
def test_job_access_permissions(django_user, processing_job, expected):
    assert can_django_user_access_job(django_user, processing_job) is expected


def test_missing_owner_field_is_denied():
    """Matches the current ProcessingJob model with no owner field."""
    existing_job = SimpleNamespace(pk=100, file_name="invoice.pdf")
    assert can_django_user_access_job(user(101), existing_job) is False


def test_adapter_creates_expected_actor_from_verified_context():
    actor = actor_from_django_user(user(pk=101))
    assert actor is not None and actor.user_id == "101" and actor.is_active
