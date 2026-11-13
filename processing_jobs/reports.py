"""Report integration contract and file resolution service.

This module provides the integration contract between the Access Control module
(Member 4 - Brijesh) and the Report Generation module (Mallikarjun - feature/report-generation).

Integration Contract:
- Report generators store generated reports in settings.MEDIA_ROOT / 'reports'
  or link them via model attributes (e.g., job.report_excel, job.report_pdf, job.reports).
- When a report is requested, resolve_report_for_job(...) checks the model reference
  and conventional storage paths, validating that the file exists and is confined
  to the media root.
- If a custom resolver is registered via register_report_resolver(), it is queried first.
"""

import logging
from pathlib import Path
from typing import Callable

from django.conf import settings
from django.db import DatabaseError

from .security import InvalidMediaPathError, validate_media_path

logger = logging.getLogger("processing_jobs")

# Type alias for custom resolver: (job, canonical_type) -> Path | None
ReportResolver = Callable[[object, str], Path | None]
_custom_resolvers: list[ReportResolver] = []


def register_report_resolver(resolver: ReportResolver) -> None:
    """Register a custom report resolution function for seamless team integration."""
    if resolver not in _custom_resolvers:
        _custom_resolvers.append(resolver)


def unregister_report_resolver(resolver: ReportResolver) -> None:
    """Unregister a custom report resolver."""
    if resolver in _custom_resolvers:
        _custom_resolvers.remove(resolver)


REPORT_CONFIG = {
    "excel": {
        "aliases": {"excel", "xlsx", "xls"},
        "canonical": "excel",
        "default_ext": ".xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "filename_pattern": "job_{job_id}_report.xlsx",
        "candidate_patterns": [
            "reports/job_{job_id}_report.xlsx",
            "reports/job_{job_id}.xlsx",
            "reports/report_{job_id}.xlsx",
            "reports/{job_id}_excel.xlsx",
            "reports/job_{job_id}_report.xls",
            "reports/job_{job_id}.xls",
        ],
        "attr_candidates": [
            "report_excel",
            "excel_report",
            "report_excel_path",
            "excel_report_path",
            "report_excel_reference",
        ],
    },
    "pdf": {
        "aliases": {"pdf"},
        "canonical": "pdf",
        "default_ext": ".pdf",
        "content_type": "application/pdf",
        "filename_pattern": "job_{job_id}_summary.pdf",
        "candidate_patterns": [
            "reports/job_{job_id}_summary.pdf",
            "reports/job_{job_id}_report.pdf",
            "reports/job_{job_id}.pdf",
            "reports/report_{job_id}.pdf",
            "reports/{job_id}_pdf.pdf",
        ],
        "attr_candidates": [
            "report_pdf",
            "pdf_report",
            "report_pdf_path",
            "pdf_report_path",
            "report_pdf_reference",
        ],
    },
}


def normalize_report_type(report_type: str) -> str | None:
    """Normalize input report type string to canonical type ('excel' or 'pdf')."""
    if not isinstance(report_type, str):
        return None
    raw = report_type.strip().lower()
    for canonical, config in REPORT_CONFIG.items():
        if raw == canonical or raw in config["aliases"]:
            return canonical
    return None


def _validate_report_candidate(candidate_path: object, media_root: Path | str | None) -> Path | None:
    """Validate that a candidate report path is a regular file confined to MEDIA_ROOT."""
    if not candidate_path or isinstance(candidate_path, bool):
        return None
    path_value = candidate_path if isinstance(candidate_path, Path) else str(candidate_path)
    try:
        return validate_media_path(
            path_value,
            base_dir=media_root,
            must_exist=True,
            expect_file=True,
        )
    except InvalidMediaPathError as exc:
        logger.warning("Rejected invalid report path candidate '%s': %s", candidate_path, exc)
        return None


def resolve_report_for_job(job: object, report_type: str) -> tuple[Path | None, str, str]:
    """Resolve the report file path, suggested download filename, and content type.

    Returns:
        (resolved_file_path_or_None, download_filename, content_type)
    Raises:
        ValueError if report_type is not supported.
    """
    canonical = normalize_report_type(report_type)
    if canonical is None:
        raise ValueError(f"Unsupported report type: '{report_type}'. Supported types: excel, pdf.")

    config = REPORT_CONFIG[canonical]
    job_id = getattr(job, "pk", getattr(job, "id", None))
    download_filename = config["filename_pattern"].format(job_id=job_id)
    content_type = config["content_type"]

    media_root = getattr(settings, "MEDIA_ROOT", None)

    # 1. Check custom resolvers registered by team members
    for custom_resolver in _custom_resolvers:
        try:
            custom_path = custom_resolver(job, canonical)
        except DatabaseError:
            raise
        except Exception as exc:
            logger.warning("Custom report resolver error: %s", exc)
            continue

        validated = _validate_report_candidate(custom_path, media_root)
        if validated is not None:
            return validated, download_filename, content_type

    # 2. Check model attributes on job instance
    for attr in config["attr_candidates"]:
        val = getattr(job, attr, None)
        if val:
            validated = _validate_report_candidate(val, media_root)
            if validated is not None:
                return validated, download_filename, content_type

    # 3. Check conventional candidate locations on disk
    if job_id is not None and not isinstance(job_id, bool):
        for pattern in config["candidate_patterns"]:
            rel_path = pattern.format(job_id=job_id)
            validated = _validate_report_candidate(rel_path, media_root)
            if validated is not None:
                return validated, download_filename, content_type

    # Report has not been generated yet or is missing
    return None, download_filename, content_type
