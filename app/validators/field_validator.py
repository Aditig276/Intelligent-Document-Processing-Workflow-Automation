"""Required-field, generic field, and invoice identifier validation.

This module provides validation for required fields, blank/whitespace detection,
invoice number string-preservation, and an orchestrating DocumentValidator.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping, Pattern

from app.validators.base import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    extract_field_value_and_confidence,
)


def validate_required_fields(
    data: Mapping[str, Any],
    required_fields: Iterable[str],
    confidence_threshold: float | None = None,
) -> tuple[list[ValidationError], list[ValidationWarning]]:
    """Validate that all configured required fields are present and non-empty.

    Validation rules:
    - Missing field key: flags 'required_field_missing'
    - Value is None: flags 'required_field_missing'
    - Empty string "": flags 'empty_value'
    - Whitespace-only string "   ": flags 'whitespace_value'
    - Optional fields not in required_fields are never flagged for being absent.
    - If field contains confidence metadata below threshold, logs a 'low_confidence' warning.

    Args:
        data: Mapping of field names to extracted values or value/confidence dicts.
        required_fields: Iterable of field names that must be present.
        confidence_threshold: Optional float threshold. If extraction confidence
            is present and below this threshold, a warning is emitted.

    Returns:
        tuple of (errors, warnings)
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    for field_name in required_fields:
        if field_name not in data:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="required_field_missing",
                    message=f"Required field '{field_name}' is missing.",
                )
            )
            continue

        raw_entry = data[field_name]
        val, confidence = extract_field_value_and_confidence(raw_entry)

        if val is None:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="required_field_missing",
                    message=f"Required field '{field_name}' cannot be null.",
                )
            )
            continue

        if isinstance(val, str):
            if len(val) == 0:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="empty_value",
                        message=f"Field '{field_name}' cannot be empty.",
                    )
                )
                continue
            if len(val.strip()) == 0:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="whitespace_value",
                        message=f"Field '{field_name}' cannot consist only of whitespace.",
                    )
                )
                continue

        # Check confidence warning if metadata was provided
        if confidence is not None and confidence_threshold is not None:
            if confidence < confidence_threshold:
                warnings.append(
                    ValidationWarning(
                        field=field_name,
                        code="low_confidence",
                        message=(
                            f"Field '{field_name}' has low extraction confidence "
                            f"({confidence:.2f} < {confidence_threshold:.2f})."
                        ),
                    )
                )

    return errors, warnings


def validate_invoice_number(
    value: Any,
    field_name: str = "invoice_number",
    is_required: bool = True,
    min_length: int | None = None,
    max_length: int | None = None,
    pattern: str | Pattern[str] | None = None,
    allowed_characters: str | None = None,
    confidence_threshold: float | None = None,
) -> tuple[list[ValidationError], list[ValidationWarning]]:
    """Validate an invoice number identifier without imposing an artificial universal format.

    Preserves invoice numbers as strings so leading zeros (e.g. '00123') and
    alphanumeric/hyphenated identifiers (e.g. 'INV-2024-001', 'AB/89') are retained.

    Args:
        value: Extracted invoice number or entry dictionary.
        field_name: Name of the field being validated.
        is_required: Whether the invoice number is required.
        min_length: Optional minimum character length.
        max_length: Optional maximum character length.
        pattern: Optional regex pattern string or compiled regex pattern.
        allowed_characters: Optional string of allowed characters.
        confidence_threshold: Optional threshold for confidence warning.

    Returns:
        tuple of (errors, warnings)
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    val, confidence = extract_field_value_and_confidence(value)

    # Blank / missing check
    if val is None or (isinstance(val, str) and len(val.strip()) == 0):
        if is_required:
            if val is None:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="required_field_missing",
                        message=f"Invoice identifier '{field_name}' is required.",
                    )
                )
            elif len(val) == 0:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="empty_value",
                        message=f"Invoice identifier '{field_name}' cannot be empty.",
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="whitespace_value",
                        message=f"Invoice identifier '{field_name}' cannot consist only of whitespace.",
                    )
                )
        return errors, warnings

    # Preserve invoice identifier as string
    if not isinstance(val, (str, int)):
        errors.append(
            ValidationError(
                field=field_name,
                code="invalid_invoice_format",
                message=f"Invoice identifier '{field_name}' must be a string or integer identifier.",
            )
        )
        return errors, warnings

    val_str = str(val).strip()

    # Check min length constraint
    if min_length is not None and len(val_str) < min_length:
        errors.append(
            ValidationError(
                field=field_name,
                code="invoice_too_short",
                message=f"Invoice identifier '{field_name}' must be at least {min_length} characters.",
            )
        )

    # Check max length constraint
    if max_length is not None and len(val_str) > max_length:
        errors.append(
            ValidationError(
                field=field_name,
                code="invoice_too_long",
                message=f"Invoice identifier '{field_name}' cannot exceed {max_length} characters.",
            )
        )

    # Check pattern if configured
    if pattern is not None:
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        if not regex.search(val_str):
            errors.append(
                ValidationError(
                    field=field_name,
                    code="invalid_invoice_format",
                    message=f"Invoice identifier '{field_name}' does not match required format pattern.",
                )
            )

    # Check allowed characters if configured
    if allowed_characters is not None:
        allowed_set = set(allowed_characters)
        disallowed = [ch for ch in val_str if ch not in allowed_set]
        if disallowed:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="invalid_invoice_format",
                    message=(
                        f"Invoice identifier '{field_name}' contains disallowed characters: "
                        f"{''.join(sorted(set(disallowed)))}"
                    ),
                )
            )

    # Check confidence warning if present
    if confidence is not None and confidence_threshold is not None:
        if confidence < confidence_threshold:
            warnings.append(
                ValidationWarning(
                    field=field_name,
                    code="low_confidence",
                    message=(
                        f"Invoice identifier '{field_name}' has low extraction confidence "
                        f"({confidence:.2f} < {confidence_threshold:.2f})."
                    ),
                )
            )

    return errors, warnings


class FieldValidator:
    """Validator for basic required and optional field constraints."""

    def __init__(
        self,
        required_fields: Iterable[str] | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self.required_fields = list(required_fields) if required_fields else []
        self.confidence_threshold = confidence_threshold

    def validate(self, data: Mapping[str, Any]) -> ValidationResult:
        """Validate required fields in data dictionary."""
        errors, warnings = validate_required_fields(
            data=data,
            required_fields=self.required_fields,
            confidence_threshold=self.confidence_threshold,
        )
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=warnings,
        )


class DocumentValidator:
    """Configurable orchestrator for document field validation.

    Allows configuring required fields, date field rules, numeric rules,
    invoice rules, confidence warnings, and custom field validators.
    """

    def __init__(
        self,
        required_fields: Iterable[str] | None = None,
        date_fields: Mapping[str, Mapping[str, Any]] | None = None,
        numeric_fields: Mapping[str, Mapping[str, Any]] | None = None,
        invoice_fields: Mapping[str, Mapping[str, Any]] | None = None,
        confidence_threshold: float | None = None,
        custom_validators: Mapping[str, Callable[[Any], tuple[list[ValidationError], list[ValidationWarning]]]] | None = None,
    ) -> None:
        self.required_fields = list(required_fields) if required_fields else []
        self.date_fields = dict(date_fields) if date_fields else {}
        self.numeric_fields = dict(numeric_fields) if numeric_fields else {}
        self.invoice_fields = dict(invoice_fields) if invoice_fields else {}
        self.confidence_threshold = confidence_threshold
        self.custom_validators = dict(custom_validators) if custom_validators else {}

    def validate(self, data: Mapping[str, Any]) -> ValidationResult:
        """Validate a single document data dictionary across all configured rules."""
        # Avoid local circular import by importing here
        from app.validators.date_validator import validate_date
        from app.validators.numeric_validator import validate_numeric

        result = ValidationResult(is_valid=True)

        # 1. Required fields
        req_errors, req_warnings = validate_required_fields(
            data=data,
            required_fields=self.required_fields,
            confidence_threshold=self.confidence_threshold,
        )
        result.errors.extend(req_errors)
        result.warnings.extend(req_warnings)

        # 2. Invoice fields
        for field_name, config in self.invoice_fields.items():
            if field_name not in data and not config.get("is_required", False):
                continue
            val = data.get(field_name)
            inv_errors, inv_warnings = validate_invoice_number(
                value=val,
                field_name=field_name,
                is_required=config.get("is_required", field_name in self.required_fields),
                min_length=config.get("min_length"),
                max_length=config.get("max_length"),
                pattern=config.get("pattern"),
                allowed_characters=config.get("allowed_characters"),
                confidence_threshold=self.confidence_threshold,
            )
            result.errors.extend(inv_errors)
            result.warnings.extend(inv_warnings)

        # 3. Date fields
        for field_name, config in self.date_fields.items():
            if field_name not in data and not config.get("is_required", False):
                continue
            val = data.get(field_name)
            date_errors, date_warnings = validate_date(
                value=val,
                field_name=field_name,
                allowed_formats=config.get("allowed_formats"),
                is_required=config.get("is_required", field_name in self.required_fields),
                min_date=config.get("min_date"),
                max_date=config.get("max_date"),
                warn_on_ambiguity=config.get("warn_on_ambiguity", True),
                confidence_threshold=self.confidence_threshold,
            )
            result.errors.extend(date_errors)
            result.warnings.extend(date_warnings)

        # 4. Numeric fields
        for field_name, config in self.numeric_fields.items():
            if field_name not in data and not config.get("is_required", False):
                continue
            val = data.get(field_name)
            num_errors, num_warnings = validate_numeric(
                value=val,
                field_name=field_name,
                is_required=config.get("is_required", field_name in self.required_fields),
                min_value=config.get("min_value"),
                max_value=config.get("max_value"),
                allow_negative=config.get("allow_negative", True),
                integer_only=config.get("integer_only", False),
                decimal_places=config.get("decimal_places"),
                strip_currency_symbols=config.get("strip_currency_symbols", False),
                confidence_threshold=self.confidence_threshold,
            )
            result.errors.extend(num_errors)
            result.warnings.extend(num_warnings)

        # 5. Custom validators
        for field_name, custom_func in self.custom_validators.items():
            if field_name in data:
                c_errors, c_warnings = custom_func(data[field_name])
                result.errors.extend(c_errors)
                result.warnings.extend(c_warnings)

        if result.errors:
            result.is_valid = False

        return result
