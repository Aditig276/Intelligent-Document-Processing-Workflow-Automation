"""Extra access-control tests, written from the point of view of the tester.

Brijesh's branch already has unit tests (tests/test_permissions.py and
tests/test_django_adapter.py). This file adds:
  * edge cases of the policy that those tests do not cover (TC-AC-01..08)
  * end-to-end checks that the policy is actually enforced by the HTTP
    endpoints (TC-AC-09..13). The policy is not wired into any view yet, so
    these are marked xfail(strict=True): they document the gap, and they will
    start failing loudly ("XPASS strict") when someone wires it up, which is
    the signal to delete the xfail mark.
"""
import dataclasses
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

import sample_factory as sf

pytestmark = pytest.mark.access


# ---------------------------------------------------- policy edge cases
@pytest.fixture
def policy():
    pytest.importorskip("app.security.permissions")
    from app.security import permissions

    return permissions


def test_tc_ac_01_actor_and_resource_objects_are_immutable(policy):
    actor = policy.AuthenticatedUser("u1", True)
    resource = policy.OwnedResource("r1", "u1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        actor.user_id = "u2"
    with pytest.raises(dataclasses.FrozenInstanceError):
        resource.owner_user_id = "u2"


@pytest.mark.parametrize("flag", ["True", 1, "yes", None])
def test_tc_ac_02_is_active_must_be_the_boolean_true(policy, flag):
    assert policy.is_authenticated_actor(policy.AuthenticatedUser("u1", flag)) is False


@pytest.mark.parametrize("user_id", ["   ", "\t", "", None, 101])
def test_tc_ac_03_blank_or_non_string_user_ids_are_denied(policy, user_id):
    actor = policy.AuthenticatedUser(user_id, True)
    assert policy.can_upload_document(actor) is False


def test_tc_ac_04_user_id_comparison_is_case_sensitive(policy):
    actor = policy.AuthenticatedUser("User_101", True)
    doc = policy.OwnedResource("d1", "user_101")
    assert policy.can_access_document(actor, doc) is False


def test_tc_ac_05_admin_name_gives_no_special_access(policy):
    admin = policy.AuthenticatedUser("admin", True)
    doc = policy.OwnedResource("d1", "user_101")
    assert policy.can_access_document(admin, doc) is False
    assert policy.can_access_result(admin, doc) is False
    assert policy.can_download_report(admin, doc) is False


@pytest.mark.parametrize("fake", [{"resource_id": "d", "owner_user_id": "u1"}, ("d", "u1")])
def test_tc_ac_06_lookalike_resources_are_denied(policy, fake):
    actor = policy.AuthenticatedUser("u1", True)
    assert policy.can_access_document(actor, fake) is False


def test_tc_ac_07_lookalike_actors_are_denied(policy):
    fake = SimpleNamespace(user_id="u1", is_active=True)
    doc = policy.OwnedResource("d1", "u1")
    assert policy.can_upload_document(fake) is False
    assert policy.can_access_document(fake, doc) is False


def test_tc_ac_08_same_owner_rule_applies_to_document_result_and_report(policy):
    owner = policy.AuthenticatedUser("u1", True)
    other = policy.AuthenticatedUser("u2", True)
    res = policy.OwnedResource("x", "u1")
    for check in (policy.can_access_document, policy.can_access_result, policy.can_download_report):
        assert check(owner, res) is True
        assert check(other, res) is False


# ------------------------------------------- is the policy enforced?
GAP = "ACCESS-GAP: access control is not wired into the views yet"


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=GAP + " (upload API accepts anonymous users)")
def test_tc_ac_09_anonymous_user_cannot_use_upload_api(client):
    response = client.post(
        "/api/upload/", {"file": SimpleUploadedFile("a.csv", sf.csv_bytes())}
    )
    assert response.status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=GAP + " (dashboard is public)")
def test_tc_ac_10_anonymous_user_cannot_see_dashboard(client, require_url):
    response = client.get(require_url("processing_jobs:dashboard"))
    assert response.status_code in (302, 401, 403)


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=GAP + " (download endpoint is public)")
def test_tc_ac_11_anonymous_user_cannot_download_results(client, require_url):
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from processing_jobs.models import ProcessingJob

    path = default_storage.save("uploads/a.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        file_name="a.csv", file_type="csv", storage_reference=path
    )
    response = client.get(require_url("processing_jobs:download_json", job_id=job.id))
    assert response.status_code in (302, 401, 403, 404)


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=GAP + " (ProcessingJob has no owner field)")
def test_tc_ac_12_job_records_who_owns_them():
    from processing_jobs.models import ProcessingJob

    assert "owner" in {f.name for f in ProcessingJob._meta.get_fields()}


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=GAP + " (any user can open any job by id)")
def test_tc_ac_13_user_cannot_open_another_users_job(client, django_user_model, require_url):
    from processing_jobs.models import ProcessingJob

    owner = django_user_model.objects.create_user("alice", password="pw-alice-123")
    intruder = django_user_model.objects.create_user("bob", password="pw-bob-123")
    job = ProcessingJob.objects.create(file_name="a.csv", file_type="csv", owner=owner)

    client.force_login(intruder)
    response = client.get(require_url("processing_jobs:extract", job_id=job.id))
    assert response.status_code in (403, 404)
