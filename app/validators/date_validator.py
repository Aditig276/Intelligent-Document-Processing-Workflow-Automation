"""Date validation module.

Validates configurable date fields, detects malformed dates, detects impossible
calendar dates (e.g. February 30, April 31, non-leap year Feb 29), handles ambiguous
date formats without guessing, and verifies optional date range constraints.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable, Mapping

from app.validators.base import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    extract_field_value_and_confidence,
)

DEFAULT_ALLOWED_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
]


def _is_impossible_date_error(error_message: str) -> bool:
    """Check if strptime ValueError indicates an impossible calendar date."""
    msg = error_message.lower()
    return (
        "day is out of range for month" in msg
        or "month must be in 1..12" in msg
        or "day must be in 1..31" in msg
        or "out of range" in msg
    )


def validate_date(
    value: Any,
    field_name: str = "date",
    allowed_formats: Iterable[str] | None = None,
    is_required: bool = True,
    min_date: datetime.date | None = None,
    max_date: datetime.date | None = None,
    warn_on_ambiguity: bool = True,
    confidence_threshold: float | None = None,
) -> tuple[list[ValidationError], list[ValidationWarning]]:
    """Validate a date field against allowed formats, calendar rules, and range bounds.

    Args:
        value: Date string, datetime/date object, or entry mapping.
        field_name: Name of the field.
        allowed_formats: Iterable of strftime/strptime format strings.
            If None, uses DEFAULT_ALLOWED_DATE_FORMATS.
        is_required: Whether the field is required.
        min_date: Optional minimum permissible date.
        max_date: Optional maximum permissible date.
        warn_on_ambiguity: If True, emits a warning when the input can be parsed
            differently under multiple allowed formats (e.g. '01/02/2024').
        confidence_threshold: Optional threshold for confidence warning.

    Returns:
        tuple of (errors, warnings)
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    formats = list(allowed_formats) if allowed_formats else DEFAULT_ALLOWED_DATE_FORMATS

    val, confidence = extract_field_value_and_confidence(value)

    # 1. Blank / Missing handling
    if val is None or (isinstance(val, str) and len(val.strip()) == 0):
        if is_required:
            if val is None:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="required_field_missing",
                        message=f"Date field '{field_name}' is required.",
                    )
                )
            elif len(val) == 0:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="empty_value",
                        message=f"Date field '{field_name}' cannot be empty.",
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="whitespace_value",
                        message=f"Date field '{field_name}' cannot consist only of whitespace.",
                    )
                )
        return errors, warnings

    # 2. Already a date or datetime object
    parsed_date: datetime.date | None = None

    if isinstance(val, datetime.datetime):
        parsed_date = val.date()
    elif isinstance(val, datetime.date):
        parsed_date = val
    elif isinstance(val, str):
        val_str = val.strip()

        # Try parsing against configured formats
        matching_dates: list[tuple[datetime.date, str]] = []
        impossible_detected = False
        last_impossible_message = ""

        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(val_str, fmt)
                matching_dates.append((dt.date(), fmt))
            except ValueError as exc:
                msg = str(exc)
                if _is_impossible_date_error(msg):
                    impossible_detected = True
                    last_impossible_message = msg

        if matching_dates:
            parsed_date = matching_dates[0][0]

            # Check for ambiguity among allowed formats
            if warn_on_ambiguity and len(matching_dates) > 1:
                distinct_dates = {d for d, _ in matching_dates}
                if len(distinct_dates) > 1:
                    fmt_descriptions = ", ".join(
                        f"'{fmt}' -> {d.isoformat()}" for d, fmt in matching_dates
                    )
                    warnings.append(
                        ValidationWarning(
                            field=field_name,
                            code="ambiguous_date_format",
                            message=(
                                f"Date value '{val_str}' for field '{field_name}' is ambiguous: "
                                f"parses differently across formats ({fmt_descriptions})."
                            ),
                        )
                    )
        else:
            if impossible_detected:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="impossible_date",
                        message=(
                            f"Date '{val_str}' for field '{field_name}' is an impossible calendar date "
                            f"({last_impossible_message or 'day or month out of range'})."
                        ),
                    )
                )
            else:
                accepted_str = ", ".join(formats)
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="invalid_date_format",
                        message=(
                            f"Date value '{val_str}' for field '{field_name}' is malformed. "
                            f"Expected format in: [{accepted_str}]."
                        ),
                    )
                )
            return errors, warnings
    else:
        errors.append(
            ValidationError(
                field=field_name,
                code="invalid_date_format",
                message=(
                    f"Date value for field '{field_name}' must be a string or date object, "
                    f"got {type(val).__name__}."
                ),
            )
        )
        return errors, warnings

    # 3. Range checks
    if parsed_date is not None:
        if min_date is not None and parsed_date < min_date:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="date_out_of_range",
                    message=(
                        f"Date '{parsed_date.isoformat()}' for field '{field_name}' "
                        f"cannot be earlier than {min_date.isoformat()}."
                    ),
                )
            )
        if max_date is not None and parsed_date > max_date:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="date_out_of_range",
                    message=(
                        f"Date '{parsed_date.isoformat()}' for field '{field_name}' "
                        f"cannot be later than {max_date.isoformat()}."
                    ),
                )
            )

    # 4. Check confidence warning if present
    if confidence is not None and confidence_threshold is not None:
        if confidence < confidence_threshold:
            warnings.append(
                ValidationWarning(
                    field=field_name,
                    code="low_confidence",
                    message=(
                        f"Date field '{field_name}' has low extraction confidence "
                        f"({confidence:.2f} < {confidence_threshold:.2f})."
                    ),
                )
            )

    return errors, warnings


class DateValidator:
    """Configurable standalone validator for date fields."""

    def __init__(
        self,
        allowed_formats: Iterable[str] | None = None,
        is_required: bool = True,
        min_date: datetime.date | None = None,
        max_date: datetime.date | None = None,
        warn_on_ambiguity: bool = True,
        confidence_threshold: float | None = None,
    ) -> None:
        self.allowed_formats = list(allowed_formats) if allowed_formats else DEFAULT_ALLOWED_DATE_FORMATS
        self.is_required = is_required
        self.min_date = min_date
        self.max_date = max_date
        self.warn_on_ambiguity = warn_on_ambiguity
        self.confidence_threshold = confidence_threshold

    def validate(self, value: Any, field_name: str = "date") -> ValidationResult:
        """Validate a single date value."""
        errors, warnings = validate_date(
            value=value,
            field_name=field_name,
            allowed_formats=self.allowed_formats,
            is_required=self.is_required,
            min_date=self.min_date,
            max_date=self.max_date,
            warn_on_ambiguity=self.warn_on_ambiguity,
            confidence_threshold=self.confidence_threshold,
        )
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=warnings,
        )
