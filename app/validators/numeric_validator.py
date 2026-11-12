"""Numeric and amount validation module.

Validates numeric fields using Decimal arithmetic, strictly rejects NaN and Infinity,
verifies min/max range constraints, checks decimal place limits, and avoids assuming
all numeric values represent currency while preserving raw input data.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.validators.base import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    extract_field_value_and_confidence,
)

SPECIAL_NUMERIC_STRINGS = {
    "nan",
    "+nan",
    "-nan",
    "inf",
    "+inf",
    "-inf",
    "infinity",
    "+infinity",
    "-infinity",
}


def _is_nan_or_infinity(val: Any) -> bool:
    """Check whether a value represents NaN or Infinity."""
    if isinstance(val, float):
        return math.isnan(val) or math.isinf(val)
    if isinstance(val, Decimal):
        return val.is_nan() or val.is_infinite()
    if isinstance(val, str):
        cleaned = val.strip().lower()
        return cleaned in SPECIAL_NUMERIC_STRINGS
    return False


def validate_numeric(
    value: Any,
    field_name: str = "amount",
    is_required: bool = True,
    min_value: Decimal | int | float | None = None,
    max_value: Decimal | int | float | None = None,
    allow_negative: bool = True,
    integer_only: bool = False,
    decimal_places: int | None = None,
    strip_currency_symbols: bool = False,
    confidence_threshold: float | None = None,
) -> tuple[list[ValidationError], list[ValidationWarning]]:
    """Validate a numeric or amount field.

    Preserves the raw extracted value without silently modifying the caller's data.

    Args:
        value: Numeric value (int, float, Decimal, str) or entry mapping.
        field_name: Name of the field being validated.
        is_required: Whether the field is mandatory.
        min_value: Optional minimum inclusive limit.
        max_value: Optional maximum inclusive limit.
        allow_negative: If False, values < 0 are rejected.
        integer_only: If True, only whole numbers are allowed.
        decimal_places: Optional maximum number of digits after the decimal point.
        strip_currency_symbols: If True, allows leading/trailing currency symbols
            ($, €, £, etc.) and commas. If False (default), non-numeric currency
            strings are rejected to avoid unconfigured assumptions.
        confidence_threshold: Optional threshold for confidence warning.

    Returns:
        tuple of (errors, warnings)
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    val, confidence = extract_field_value_and_confidence(value)

    # 1. Blank / Missing check
    if val is None or (isinstance(val, str) and len(val.strip()) == 0):
        if is_required:
            if val is None:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="required_field_missing",
                        message=f"Numeric field '{field_name}' is required.",
                    )
                )
            elif len(val) == 0:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="empty_value",
                        message=f"Numeric field '{field_name}' cannot be empty.",
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        field=field_name,
                        code="whitespace_value",
                        message=f"Numeric field '{field_name}' cannot consist only of whitespace.",
                    )
                )
        return errors, warnings

    # In Python, bool is a subclass of int (isinstance(True, int) is True).
    # Explicitly reject boolean values for numeric fields.
    if isinstance(val, bool):
        errors.append(
            ValidationError(
                field=field_name,
                code="invalid_numeric",
                message=f"Field '{field_name}' cannot be a boolean value.",
            )
        )
        return errors, warnings

    # 2. Strict rejection of NaN and Infinity
    if _is_nan_or_infinity(val):
        errors.append(
            ValidationError(
                field=field_name,
                code="nan_or_infinity",
                message=f"Field '{field_name}' cannot be NaN or Infinity.",
            )
        )
        return errors, warnings

    # 3. Parse to Decimal
    parsed_decimal: Decimal | None = None

    if isinstance(val, (int, float, Decimal)):
        try:
            parsed_decimal = Decimal(str(val))
        except (InvalidOperation, ValueError):
            errors.append(
                ValidationError(
                    field=field_name,
                    code="invalid_numeric",
                    message=f"Field '{field_name}' contains an invalid numeric value: {val}.",
                )
            )
            return errors, warnings
    elif isinstance(val, str):
        val_str = val.strip()

        if strip_currency_symbols:
            for symbol in ("$", "€", "£", "¥", "₹", ","):
                val_str = val_str.replace(symbol, "")
            val_str = val_str.strip()

        try:
            parsed_decimal = Decimal(val_str)
        except (InvalidOperation, ValueError):
            errors.append(
                ValidationError(
                    field=field_name,
                    code="invalid_numeric",
                    message=f"Field '{field_name}' contains a non-numeric string: '{val}'.",
                )
            )
            return errors, warnings
    else:
        errors.append(
            ValidationError(
                field=field_name,
                code="invalid_numeric",
                message=(
                    f"Field '{field_name}' must be numeric (int, float, Decimal, str), "
                    f"got {type(val).__name__}."
                ),
            )
        )
        return errors, warnings

    if parsed_decimal is None or parsed_decimal.is_nan() or parsed_decimal.is_infinite():
        errors.append(
            ValidationError(
                field=field_name,
                code="nan_or_infinity",
                message=f"Field '{field_name}' cannot be NaN or Infinity.",
            )
        )
        return errors, warnings

    # 4. Integer only check
    if integer_only:
        if parsed_decimal % 1 != 0:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="integer_required",
                    message=f"Field '{field_name}' must be an integer, got {parsed_decimal}.",
                )
            )
            return errors, warnings

    # 5. Decimal places check
    if decimal_places is not None:
        # Normalize and get exponent (number of digits after decimal)
        # Using string representation after decimal point to accurately count
        parts = str(parsed_decimal).split(".")
        if len(parts) == 2 and len(parts[1]) > decimal_places:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="excess_decimal_places",
                    message=(
                        f"Field '{field_name}' exceeds maximum allowed decimal places "
                        f"({len(parts[1])} > {decimal_places})."
                    ),
                )
            )

    # 6. Negative values check
    if not allow_negative and parsed_decimal < 0:
        errors.append(
            ValidationError(
                field=field_name,
                code="numeric_out_of_range",
                message=f"Field '{field_name}' cannot be negative ({parsed_decimal} < 0).",
            )
        )

    # 7. Range checks (min_value, max_value)
    if min_value is not None:
        min_dec = Decimal(str(min_value))
        if parsed_decimal < min_dec:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="numeric_out_of_range",
                    message=f"Field '{field_name}' cannot be less than {min_dec} ({parsed_decimal} < {min_dec}).",
                )
            )

    if max_value is not None:
        max_dec = Decimal(str(max_value))
        if parsed_decimal > max_dec:
            errors.append(
                ValidationError(
                    field=field_name,
                    code="numeric_out_of_range",
                    message=f"Field '{field_name}' cannot be greater than {max_dec} ({parsed_decimal} > {max_dec}).",
                )
            )

    # 8. Confidence check
    if confidence is not None and confidence_threshold is not None:
        if confidence < confidence_threshold:
            warnings.append(
                ValidationWarning(
                    field=field_name,
                    code="low_confidence",
                    message=(
                        f"Numeric field '{field_name}' has low extraction confidence "
                        f"({confidence:.2f} < {confidence_threshold:.2f})."
                    ),
                )
            )

    return errors, warnings


class NumericValidator:
    """Configurable standalone validator for numeric and amount fields."""

    def __init__(
        self,
        is_required: bool = True,
        min_value: Decimal | int | float | None = None,
        max_value: Decimal | int | float | None = None,
        allow_negative: bool = True,
        integer_only: bool = False,
        decimal_places: int | None = None,
        strip_currency_symbols: bool = False,
        confidence_threshold: float | None = None,
    ) -> None:
        self.is_required = is_required
        self.min_value = min_value
        self.max_value = max_value
        self.allow_negative = allow_negative
        self.integer_only = integer_only
        self.decimal_places = decimal_places
        self.strip_currency_symbols = strip_currency_symbols
        self.confidence_threshold = confidence_threshold

    def validate(self, value: Any, field_name: str = "amount") -> ValidationResult:
        """Validate a single numeric value."""
        errors, warnings = validate_numeric(
            value=value,
            field_name=field_name,
            is_required=self.is_required,
            min_value=self.min_value,
            max_value=self.max_value,
            allow_negative=self.allow_negative,
            integer_only=self.integer_only,
            decimal_places=self.decimal_places,
            strip_currency_symbols=self.strip_currency_symbols,
            confidence_threshold=self.confidence_threshold,
        )
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=warnings,
        )
