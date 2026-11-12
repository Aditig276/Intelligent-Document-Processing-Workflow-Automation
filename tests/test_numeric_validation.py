"""Unit tests for numeric and amount validation.

Covers:
- Valid integers and decimals (int, float, Decimal, str)
- Non-numeric strings
- Blank optional vs required numeric fields
- Strict rejection of NaN and Infinity (float, Decimal, string)
- Configured min/max range violations and negative checks
- Integer-only constraints
- Decimal places constraints
- Boolean rejection (ensures True/False is not treated as 1/0)
- Currency symbol handling (opt-in stripping vs. default rejection)
- NumericValidator class
"""

from decimal import Decimal
import math
import pytest

from app.validators import (
    NumericValidator,
    ValidationError,
    ValidationResult,
    ValidationWarning,
    validate_numeric,
)


def test_valid_integers_and_decimals():
    """Verify various valid numeric representations pass validation."""
    test_cases = [100, 0, -50, 99.95, Decimal("1250.75"), "100", "0.01", "-25.50"]
    for val in test_cases:
        errors, warnings = validate_numeric(val, field_name="amount")
        assert len(errors) == 0, f"Expected {val} to be valid, got errors: {errors}"


def test_non_numeric_strings_are_rejected():
    """Verify non-numeric strings produce invalid_numeric error."""
    for bad_val in ["abc", "12a3", "one hundred", "12.34.56", "--5"]:
        errors, warnings = validate_numeric(bad_val, field_name="amount")
        assert len(errors) == 1, f"Expected 1 error for '{bad_val}'"
        assert errors[0].code == "invalid_numeric"


def test_booleans_are_strictly_rejected():
    """Verify True and False booleans are not treated as valid integers."""
    errors_true, _ = validate_numeric(True, field_name="amount")
    assert len(errors_true) == 1
    assert errors_true[0].code == "invalid_numeric"

    errors_false, _ = validate_numeric(False, field_name="amount")
    assert len(errors_false) == 1
    assert errors_false[0].code == "invalid_numeric"


def test_nan_and_infinity_strictly_rejected():
    """Verify float, Decimal, and string NaN/Infinity are rejected with nan_or_infinity code."""
    nan_inf_cases = [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        "NaN",
        "nan",
        "+inf",
        "-inf",
        "infinity",
        "-Infinity",
    ]

    for val in nan_inf_cases:
        errors, warnings = validate_numeric(val, field_name="total")
        assert len(errors) == 1, f"Expected nan_or_infinity error for {val}"
        assert errors[0].code == "nan_or_infinity"
        assert "cannot be NaN or Infinity" in errors[0].message


def test_blank_optional_numeric_passes():
    """Verify absent or blank optional numeric field passes without error."""
    for blank in [None, "", "   "]:
        errors, warnings = validate_numeric(blank, is_required=False)
        assert len(errors) == 0, f"Expected {blank!r} to pass as optional"


def test_blank_required_numeric_fails():
    """Verify absent or blank required numeric field fails with appropriate codes."""
    errors_none, _ = validate_numeric(None, is_required=True)
    assert len(errors_none) == 1
    assert errors_none[0].code == "required_field_missing"

    errors_empty, _ = validate_numeric("", is_required=True)
    assert len(errors_empty) == 1
    assert errors_empty[0].code == "empty_value"

    errors_ws, _ = validate_numeric("   ", is_required=True)
    assert len(errors_ws) == 1
    assert errors_ws[0].code == "whitespace_value"


def test_min_and_max_range_violations():
    """Verify min_value and max_value constraints."""
    # Min value violation
    errors_min, _ = validate_numeric("5.00", min_value=10)
    assert len(errors_min) == 1
    assert errors_min[0].code == "numeric_out_of_range"
    assert "cannot be less than" in errors_min[0].message

    # Max value violation
    errors_max, _ = validate_numeric(1050, max_value=1000)
    assert len(errors_max) == 1
    assert errors_max[0].code == "numeric_out_of_range"
    assert "cannot be greater than" in errors_max[0].message

    # Within bounds
    errors_ok, _ = validate_numeric(500, min_value=10, max_value=1000)
    assert len(errors_ok) == 0


def test_negative_disallowed():
    """Verify allow_negative=False rejects negative numbers."""
    errors_neg, _ = validate_numeric(-10.50, allow_negative=False)
    assert len(errors_neg) == 1
    assert errors_neg[0].code == "numeric_out_of_range"
    assert "cannot be negative" in errors_neg[0].message

    errors_pos, _ = validate_numeric(10.50, allow_negative=False)
    assert len(errors_pos) == 0


def test_integer_only_constraint():
    """Verify integer_only=True rejects decimal fractions."""
    errors_dec, _ = validate_numeric(10.75, integer_only=True)
    assert len(errors_dec) == 1
    assert errors_dec[0].code == "integer_required"

    errors_int, _ = validate_numeric(10, integer_only=True)
    assert len(errors_int) == 0

    errors_int_str, _ = validate_numeric("42", integer_only=True)
    assert len(errors_int_str) == 0


def test_decimal_places_constraint():
    """Verify decimal_places constraint."""
    # 2 decimal places allowed, 3 provided
    errors_3dec, _ = validate_numeric("10.125", decimal_places=2)
    assert len(errors_3dec) == 1
    assert errors_3dec[0].code == "excess_decimal_places"
    assert "exceeds maximum allowed decimal places" in errors_3dec[0].message

    # 2 decimal places allowed, 2 provided
    errors_2dec, _ = validate_numeric("10.12", decimal_places=2)
    assert len(errors_2dec) == 0

    # Whole number passes
    errors_whole, _ = validate_numeric("10", decimal_places=2)
    assert len(errors_whole) == 0


def test_currency_symbol_handling():
    """Verify currency symbol behavior (rejected by default, allowed if strip_currency_symbols=True)."""
    # By default, currency symbols should not be assumed and are rejected as non-numeric
    errors_default, _ = validate_numeric("$150.00", strip_currency_symbols=False)
    assert len(errors_default) == 1
    assert errors_default[0].code == "invalid_numeric"

    # When explicitly opted in to strip symbols
    errors_stripped, _ = validate_numeric("$1,250.00", strip_currency_symbols=True)
    assert len(errors_stripped) == 0


def test_raw_value_preservation():
    """Verify input data object is not mutated by the validator."""
    doc = {"amount": "$100.00"}
    original_val = doc["amount"]

    validate_numeric(doc["amount"], strip_currency_symbols=True)
    assert doc["amount"] == original_val  # Still original unstripped string


def test_numeric_validator_class():
    """Verify NumericValidator class returns structured ValidationResult."""
    validator = NumericValidator(
        is_required=True,
        min_value=0,
        decimal_places=2,
    )

    # Valid
    res_valid = validator.validate("99.99")
    assert res_valid.is_valid
    assert len(res_valid.errors) == 0

    # Out of range
    res_invalid = validator.validate("-5.00")
    assert not res_invalid.is_valid
    assert res_invalid.errors[0].code == "numeric_out_of_range"
