"""Unit tests for date validation.

Covers:
- Valid dates across configured formats
- Malformed / non-date strings
- Impossible calendar dates (Feb 30, April 31, non-leap Feb 29)
- Custom format configurations
- Ambiguous date detection and warnings
- Optional blank dates vs required blank dates
- Min and max date range bounds
- DateValidator class
"""

import datetime
import pytest

from app.validators import (
    DateValidator,
    ValidationError,
    ValidationResult,
    ValidationWarning,
    validate_date,
)


def test_valid_iso_date():
    """Verify standard ISO 8601 date passes validation."""
    errors, warnings = validate_date("2024-11-03", field_name="invoice_date")
    assert len(errors) == 0
    assert len(warnings) == 0


def test_valid_date_objects():
    """Verify datetime.date and datetime.datetime instances pass validation."""
    dt_date = datetime.date(2024, 5, 20)
    errors, warnings = validate_date(dt_date)
    assert len(errors) == 0

    dt_datetime = datetime.datetime(2024, 5, 20, 14, 30)
    errors, warnings = validate_date(dt_datetime)
    assert len(errors) == 0


def test_invalid_malformed_date():
    """Verify non-date strings produce invalid_date_format error."""
    for malformed in ["not-a-date", "2024-abc-01", "2024/99/99", "12345"]:
        errors, warnings = validate_date(malformed, allowed_formats=["%Y-%m-%d"])
        assert len(errors) == 1, f"Expected 1 error for '{malformed}'"
        assert errors[0].code in {"invalid_date_format", "impossible_date"}


def test_impossible_calendar_dates():
    """Verify impossible calendar dates produce impossible_date error."""
    # February 30 does not exist in any calendar
    errors_feb30, _ = validate_date("2024-02-30", allowed_formats=["%Y-%m-%d"])
    assert len(errors_feb30) == 1
    assert errors_feb30[0].code == "impossible_date"
    assert "impossible" in errors_feb30[0].message

    # April 31 (April has only 30 days)
    errors_apr31, _ = validate_date("2024-04-31", allowed_formats=["%Y-%m-%d"])
    assert len(errors_apr31) == 1
    assert errors_apr31[0].code == "impossible_date"

    # February 29 on a non-leap year (2023 is not a leap year)
    errors_leap, _ = validate_date("2023-02-29", allowed_formats=["%Y-%m-%d"])
    assert len(errors_leap) == 1
    assert errors_leap[0].code == "impossible_date"

    # February 29 on a leap year (2024 IS a leap year) should pass
    errors_leap_ok, _ = validate_date("2024-02-29", allowed_formats=["%Y-%m-%d"])
    assert len(errors_leap_ok) == 0


def test_custom_configured_date_formats():
    """Verify custom date formats can be specified."""
    custom_formats = ["%d.%m.%Y", "%Y/%m/%d"]

    # Dot-separated format
    errors1, _ = validate_date("25.12.2024", allowed_formats=custom_formats)
    assert len(errors1) == 0

    # Slash-separated format
    errors2, _ = validate_date("2024/12/25", allowed_formats=custom_formats)
    assert len(errors2) == 0

    # ISO format not in custom list should fail
    errors3, _ = validate_date("2024-12-25", allowed_formats=custom_formats)
    assert len(errors3) == 1
    assert errors3[0].code == "invalid_date_format"


def test_ambiguous_date_generates_warning():
    """Verify date that can parse differently under multiple formats emits ambiguous warning."""
    # "03/04/2024" can be 3rd of April or 4th of March
    formats = ["%d/%m/%Y", "%m/%d/%Y"]

    errors, warnings = validate_date("03/04/2024", allowed_formats=formats, warn_on_ambiguity=True)
    assert len(errors) == 0  # Still parses successfully
    assert len(warnings) == 1
    assert warnings[0].code == "ambiguous_date_format"
    assert "ambiguous" in warnings[0].message


def test_unambiguous_day_exceeding_12_does_not_warn_on_ambiguity():
    """Verify unambiguous date (day > 12) does not trigger ambiguity warning."""
    # "25/04/2024" cannot be interpreted as month 25
    formats = ["%d/%m/%Y", "%m/%d/%Y"]

    errors, warnings = validate_date("25/04/2024", allowed_formats=formats, warn_on_ambiguity=True)
    assert len(errors) == 0
    assert len(warnings) == 0


def test_blank_optional_date_passes():
    """Verify blank optional date produces no errors."""
    errors_none, _ = validate_date(None, is_required=False)
    assert len(errors_none) == 0

    errors_empty, _ = validate_date("", is_required=False)
    assert len(errors_empty) == 0

    errors_ws, _ = validate_date("   ", is_required=False)
    assert len(errors_ws) == 0


def test_blank_required_date_fails():
    """Verify blank required date produces appropriate errors."""
    errors_none, _ = validate_date(None, is_required=True)
    assert len(errors_none) == 1
    assert errors_none[0].code == "required_field_missing"

    errors_empty, _ = validate_date("", is_required=True)
    assert len(errors_empty) == 1
    assert errors_empty[0].code == "empty_value"

    errors_ws, _ = validate_date("   ", is_required=True)
    assert len(errors_ws) == 1
    assert errors_ws[0].code == "whitespace_value"


def test_date_range_bounds():
    """Verify min_date and max_date constraints."""
    min_bound = datetime.date(2020, 1, 1)
    max_bound = datetime.date(2025, 12, 31)

    # Date earlier than min_bound
    errors_early, _ = validate_date(
        "2019-12-31",
        allowed_formats=["%Y-%m-%d"],
        min_date=min_bound,
        max_date=max_bound,
    )
    assert len(errors_early) == 1
    assert errors_early[0].code == "date_out_of_range"
    assert "cannot be earlier" in errors_early[0].message

    # Date later than max_bound
    errors_late, _ = validate_date(
        "2026-01-01",
        allowed_formats=["%Y-%m-%d"],
        min_date=min_bound,
        max_date=max_bound,
    )
    assert len(errors_late) == 1
    assert errors_late[0].code == "date_out_of_range"
    assert "cannot be later" in errors_late[0].message

    # Date within bounds
    errors_ok, _ = validate_date(
        "2024-06-15",
        allowed_formats=["%Y-%m-%d"],
        min_date=min_bound,
        max_date=max_bound,
    )
    assert len(errors_ok) == 0


def test_date_validator_class():
    """Verify DateValidator class provides structured ValidationResult."""
    validator = DateValidator(
        allowed_formats=["%Y-%m-%d"],
        min_date=datetime.date(2024, 1, 1),
    )

    # Valid
    res_valid = validator.validate("2024-06-01")
    assert res_valid.is_valid
    assert len(res_valid.errors) == 0

    # Invalid range
    res_invalid = validator.validate("2023-12-31")
    assert not res_invalid.is_valid
    assert res_invalid.errors[0].code == "date_out_of_range"
