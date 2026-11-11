"""Tests for authentication and document ownership across browser views and models."""

import json
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

import sample_factory as sf
from processing_jobs.models import ProcessingJob

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", email="alice@example.com", password="password123"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob", email="bob@example.com", password="password123"
    )


# ---------------------------------------------------- Anonymous access redirects
def test_anonymous_user_cannot_access_upload_page(client):
    response = client.get(reverse("upload_document"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


def test_anonymous_user_cannot_post_upload(client):
    csv_file = SimpleUploadedFile("test.csv", sf.csv_bytes(), content_type="text/csv")
    response = client.post(reverse("upload_document"), {"file": csv_file})
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")
    assert ProcessingJob.objects.count() == 0


def test_anonymous_user_cannot_access_dashboard(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


def test_anonymous_user_cannot_access_job_detail(client, alice):
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_doc.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )
    response = client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


def test_anonymous_user_cannot_extract_job(client, alice):
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_doc.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.PENDING,
    )
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


def test_anonymous_user_cannot_download_result(client, alice):
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="alice_doc.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.COMPLETED,
    )
    response = client.get(reverse("download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers.get("Location", "")


# ---------------------------------------------------- Authenticated upload ownership
def test_authenticated_upload_associates_job_with_user(client, alice):
    client.force_login(alice)
    csv_file = SimpleUploadedFile("alice_report.csv", sf.csv_bytes(), content_type="text/csv")

    response = client.post(reverse("upload_document"), {"file": csv_file})
    assert response.status_code == 302

    job = ProcessingJob.objects.get(file_name="alice_report.csv")
    assert job.owner == alice
    assert response.headers["Location"] in (
        reverse("dashboard"),
        reverse("job_detail", kwargs={"job_id": job.id}),
    )


# ---------------------------------------------------- Dashboard isolation
def test_dashboard_displays_only_current_users_jobs(client, alice, bob):
    job_alice1 = ProcessingJob.objects.create(
        owner=alice, file_name="alice_doc_1.csv", file_type="csv", file_size=100
    )
    job_alice2 = ProcessingJob.objects.create(
        owner=alice, file_name="alice_doc_2.csv", file_type="csv", file_size=100
    )
    job_bob = ProcessingJob.objects.create(
        owner=bob, file_name="bob_secret.csv", file_type="csv", file_size=100
    )

    client.force_login(alice)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200

    dashboard_jobs = list(response.context["jobs"])
    assert job_alice1 in dashboard_jobs
    assert job_alice2 in dashboard_jobs
    assert job_bob not in dashboard_jobs

    content = response.content.decode()
    assert "alice_doc_1.csv" in content
    assert "alice_doc_2.csv" in content
    assert "bob_secret.csv" not in content


# ---------------------------------------------------- Job detail & unauthorized access
def test_user_can_access_own_job_detail(client, alice):
    job = ProcessingJob.objects.create(
        owner=alice, file_name="alice.csv", file_type="csv", file_size=100
    )
    client.force_login(alice)
    response = client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    assert response.status_code == 200
    assert response.context["job"] == job


def test_user_cannot_access_other_users_job_detail(client, alice, bob):
    job = ProcessingJob.objects.create(
        owner=alice, file_name="alice_private.csv", file_type="csv", file_size=100
    )
    client.force_login(bob)
    response = client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    assert response.status_code == 404


# ---------------------------------------------------- Extraction isolation
def test_user_cannot_extract_other_users_job(client, alice, bob):
    job = ProcessingJob.objects.create(
        owner=alice, file_name="alice_file.csv", file_type="csv", file_size=100
    )
    client.force_login(bob)
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 404


def test_user_can_extract_own_job(client, alice, settings):
    path = default_storage.save("uploads/valid.csv", ContentFile(sf.csv_bytes()))
    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="valid.csv",
        file_type="csv",
        file_size=len(sf.csv_bytes()),
        storage_reference=path,
        status=ProcessingJob.Status.PENDING,
    )
    client.force_login(alice)
    response = client.post(reverse("extract_job", kwargs={"job_id": job.id}))
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("job_detail", kwargs={"job_id": job.id})

    job.refresh_from_db()
    assert job.status == ProcessingJob.Status.COMPLETED


# ---------------------------------------------------- Download isolation
def test_user_can_download_own_completed_job(client, alice, settings):
    result_dir = Path(settings.MEDIA_ROOT) / "extracted"
    result_dir.mkdir(parents=True, exist_ok=True)

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="doc.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.COMPLETED,
    )
    result_file = result_dir / f"job_{job.id}.json"
    result_file.write_text(json.dumps({"rows": 10}), encoding="utf-8")

    client.force_login(alice)
    response = client.get(reverse("download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == f'attachment; filename="job_{job.id}_extraction.json"'
    assert json.loads(response.content) == {"rows": 10}


def test_user_cannot_download_other_users_completed_job(client, alice, bob, settings):
    result_dir = Path(settings.MEDIA_ROOT) / "extracted"
    result_dir.mkdir(parents=True, exist_ok=True)

    job = ProcessingJob.objects.create(
        owner=alice,
        file_name="doc.csv",
        file_type="csv",
        file_size=100,
        status=ProcessingJob.Status.COMPLETED,
    )
    result_file = result_dir / f"job_{job.id}.json"
    result_file.write_text(json.dumps({"rows": 10}), encoding="utf-8")

    client.force_login(bob)
    response = client.get(reverse("download_result", kwargs={"job_id": job.id}))
    assert response.status_code == 404


# ---------------------------------------------------- Backward compatibility
def test_nullable_owner_field_allows_null():
    job = ProcessingJob.objects.create(
        owner=None,
        file_name="legacy.csv",
        file_type="csv",
        file_size=50,
    )
    assert job.owner is None
    job.refresh_from_db()
    assert job.owner is None


def test_legacy_jobs_without_owner_not_visible_to_users(client, alice):
    job = ProcessingJob.objects.create(
        owner=None,
        file_name="unowned.csv",
        file_type="csv",
        file_size=50,
    )
    client.force_login(alice)

    dash_resp = client.get(reverse("dashboard"))
    assert job not in dash_resp.context["jobs"]

    detail_resp = client.get(reverse("job_detail", kwargs={"job_id": job.id}))
    assert detail_resp.status_code == 404
