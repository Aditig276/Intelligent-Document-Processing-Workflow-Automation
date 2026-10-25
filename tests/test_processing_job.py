"""Tests for the ProcessingJob model (processing_jobs app).

Test IDs (TC-JOB-xx) match docs/test-plan.md.
"""
import pytest
from django.core.exceptions import ValidationError

pytest.importorskip("processing_jobs")
from processing_jobs.models import ProcessingJob  # noqa: E402

pytestmark = [pytest.mark.jobs, pytest.mark.django_db]


def make_job(**overrides):
    data = dict(file_name="invoice.pdf", file_type="pdf", file_size=1024)
    data.update(overrides)
    return ProcessingJob.objects.create(**data)


def test_tc_job_01_new_job_defaults_to_pending():
    job = make_job()
    assert job.status == ProcessingJob.Status.PENDING == "pending"
    assert job.error_message == ""
    assert job.storage_reference == ""


def test_tc_job_02_only_the_four_required_statuses_exist():
    assert {s.value for s in ProcessingJob.Status} == {
        "pending", "processing", "completed", "failed",
    }


@pytest.mark.parametrize(
    "status",
    [s for s in ("pending", "processing", "completed", "failed")],
)
def test_tc_job_03_each_status_can_be_saved_and_reloaded(status):
    job = make_job()
    job.status = status
    job.save()
    job.refresh_from_db()
    assert job.status == status


def test_tc_job_04_normal_lifecycle_pending_processing_completed():
    job = make_job()
    for status in ("processing", "completed"):
        job.status = status
        job.save()
        job.refresh_from_db()
        assert job.status == status


def test_tc_job_05_failed_job_keeps_its_error_message():
    job = make_job(status="failed", error_message="Unable to read document")
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.error_message == "Unable to read document"


def test_tc_job_06_unknown_status_is_rejected_by_validation():
    job = make_job()
    job.status = "done"
    with pytest.raises(ValidationError):
        job.full_clean()


def test_tc_job_07_file_name_longer_than_255_chars_is_rejected():
    job = ProcessingJob(file_name="a" * 256 + ".pdf", file_type="pdf")
    with pytest.raises(ValidationError):
        job.full_clean()


def test_tc_job_08_negative_file_size_is_rejected():
    job = ProcessingJob(file_name="a.pdf", file_type="pdf", file_size=-1)
    with pytest.raises(ValidationError):
        job.full_clean()


def test_tc_job_09_timestamps_are_set_and_updated_at_moves_on_save():
    job = make_job()
    assert job.created_at is not None
    first_update = job.updated_at
    job.status = "processing"
    job.save()
    assert job.updated_at >= first_update
    assert job.created_at <= job.updated_at


def test_tc_job_10_jobs_are_listed_newest_first():
    first = make_job(file_name="first.pdf")
    second = make_job(file_name="second.pdf")
    assert list(ProcessingJob.objects.all()) == [second, first]


def test_tc_job_11_str_shows_file_name_and_status():
    assert str(make_job(file_name="r.csv", file_type="csv")) == "r.csv - pending"


def test_tc_job_12_status_can_be_filtered():
    make_job()
    make_job(status="failed", error_message="x")
    assert ProcessingJob.objects.filter(status="failed").count() == 1
    assert ProcessingJob.objects.filter(status="pending").count() == 1
