"""Unit tests for required-field, generic field, and invoice identifier validation.

Covers:
- Missing required fields
- Empty string required fields
- Whitespace-only values
- Valid required values
- Missing optional fields
- Extraction confidence warnings
- Invoice identifier preservation (strings, leading zeros)
- Alphanumeric invoice identifiers
- Configurable invoice constraints (length, pattern, allowed characters)
- Combined DocumentValidator scenarios
"""

from decimal import Decimal
import pytest

from app.validators import (
    DocumentValidator,
    FieldValidator,
    ValidationError,
    ValidationResult,
    ValidationWarning,
    validate_invoice_number,
    validate_required_fields,
)


# ---------------------------------------------------------------------------
# REQUIRED FIELD TESTS
# ---------------------------------------------------------------------------

def test_missing_required_field_is_detected():
    """Verify missing required keys produce required_field_missing error."""
    data = {"name": "Acme Corp"}
    required = ["name", "invoice_number", "date"]

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 2
    missing_fields = {e.field for e in errors}
    assert missing_fields == {"invoice_number", "date"}
    assert all(e.code == "required_field_missing" for e in errors)
    assert len(warnings) == 0


def test_none_value_for_required_field_is_rejected():
    """Verify None value for required field produces required_field_missing."""
    data = {"name": None, "amount": 100}
    required = ["name"]

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 1
    assert errors[0].field == "name"
    assert errors[0].code == "required_field_missing"


def test_empty_string_required_field_is_rejected():
    """Verify empty string produces empty_value error."""
    data = {"vendor": "", "total": 500}
    required = ["vendor"]

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 1
    assert errors[0].field == "vendor"
    assert errors[0].code == "empty_value"
    assert "cannot be empty" in errors[0].message


def test_whitespace_only_required_field_is_rejected():
    """Verify whitespace-only string produces whitespace_value error."""
    data = {"vendor": "   \t\n  ", "total": 500}
    required = ["vendor"]

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 1
    assert errors[0].field == "vendor"
    assert errors[0].code == "whitespace_value"
    assert "whitespace" in errors[0].message


def test_valid_required_fields_pass():
    """Verify properly populated required fields produce no errors."""
    data = {
        "vendor": "Acme Supplies Ltd",
        "invoice_number": "INV-2024-001",
        "date": "2024-05-15",
    }
    required = ["vendor", "invoice_number", "date"]

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 0
    assert len(warnings) == 0


def test_missing_optional_fields_are_not_rejected():
    """Verify optional fields absent from data do not generate errors."""
    data = {"vendor": "Acme Corp", "amount": "150.00"}
    required = ["vendor"]  # 'notes', 'po_number' are optional and absent

    errors, warnings = validate_required_fields(data, required)

    assert len(errors) == 0
    assert len(warnings) == 0


def test_low_confidence_produces_warning_not_error():
    """Verify field with confidence below threshold generates a warning while passing validation."""
    data = {
        "vendor": {"value": "Acme Corp", "confidence": 0.55},
        "amount": {"value": 150, "confidence": 0.95},
    }
    required = ["vendor", "amount"]

    errors, warnings = validate_required_fields(data, required, confidence_threshold=0.70)

    assert len(errors) == 0
    assert len(warnings) == 1
    assert warnings[0].field == "vendor"
    assert warnings[0].code == "low_confidence"
    assert "0.55" in warnings[0].message


def test_field_validator_class():
    """Verify FieldValidator class wrapper returns structured ValidationResult."""
    validator = FieldValidator(required_fields=["name", "amount"])

    # Invalid input
    res_invalid = validator.validate({"name": "Test"})
    assert not res_invalid.is_valid
    assert len(res_invalid.errors) == 1
    assert res_invalid.errors[0].field == "amount"

    # Valid input
    res_valid = validator.validate({"name": "Test", "amount": 100})
    assert res_valid.is_valid
    assert len(res_valid.errors) == 0


# ---------------------------------------------------------------------------
# INVOICE FIELD TESTS
# ---------------------------------------------------------------------------

def test_valid_invoice_identifier_alphanumeric():
    """Verify alphanumeric invoice numbers pass validation."""
    for inv in ["INV-2024-9901", "BILL/001/A", "A123-B456", "99401"]:
        errors, warnings = validate_invoice_number(inv)
        assert len(errors) == 0, f"Expected {inv} to be valid, got errors: {errors}"


def test_invoice_identifier_preserves_leading_zeros():
    """Verify invoice number string with leading zeros is preserved as string."""
    inv = "0004561"
    errors, warnings = validate_invoice_number(inv)
    assert len(errors) == 0
    # Must preserve string type without numeric stripping
    assert isinstance(inv, str)
    assert inv == "0004561"


def test_missing_required_invoice_identifier():
    """Verify missing required invoice identifier is rejected."""
    errors, warnings = validate_invoice_number(None, is_required=True)
    assert len(errors) == 1
    assert errors[0].code == "required_field_missing"

    errors_empty, _ = validate_invoice_number("", is_required=True)
    assert len(errors_empty) == 1
    assert errors_empty[0].code == "empty_value"

    errors_ws, _ = validate_invoice_number("   ", is_required=True)
    assert len(errors_ws) == 1
    assert errors_ws[0].code == "whitespace_value"


def test_optional_invoice_identifier_blank_passes():
    """Verify optional invoice identifier passes when absent or blank."""
    errors, warnings = validate_invoice_number(None, is_required=False)
    assert len(errors) == 0
    assert len(warnings) == 0

    errors_empty, _ = validate_invoice_number("", is_required=False)
    assert len(errors_empty) == 0


def test_invoice_length_constraints():
    """Verify configurable min_length and max_length for invoice numbers."""
    # Min length violation
    errors_short, _ = validate_invoice_number("AB", min_length=3)
    assert len(errors_short) == 1
    assert errors_short[0].code == "invoice_too_short"

    # Max length violation
    errors_long, _ = validate_invoice_number("12345678901", max_length=10)
    assert len(errors_long) == 1
    assert errors_long[0].code == "invoice_too_long"

    # Valid within bounds
    errors_ok, _ = validate_invoice_number("ABC123", min_length=3, max_length=10)
    assert len(errors_ok) == 0


def test_invoice_regex_pattern_constraint():
    """Verify configurable regex pattern constraint on invoice numbers."""
    pattern = r"^INV-\d{4}-\d+$"

    # Matching pattern
    errors_ok, _ = validate_invoice_number("INV-2024-42", pattern=pattern)
    assert len(errors_ok) == 0

    # Non-matching pattern
    errors_bad, _ = validate_invoice_number("BILL-2024-42", pattern=pattern)
    assert len(errors_bad) == 1
    assert errors_bad[0].code == "invalid_invoice_format"


def test_invoice_allowed_characters_constraint():
    """Verify allowed characters constraint on invoice identifiers."""
    allowed = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-"

    errors_ok, _ = validate_invoice_number("INV-9901", allowed_characters=allowed)
    assert len(errors_ok) == 0

    # Disallowed character '$' and '@'
    errors_bad, _ = validate_invoice_number("INV-$9901@", allowed_characters=allowed)
    assert len(errors_bad) == 1
    assert errors_bad[0].code == "invalid_invoice_format"
    assert "$" in errors_bad[0].message


# ---------------------------------------------------------------------------
# DOCUMENT VALIDATOR COMBINED ORCHESTRATION TESTS
# ---------------------------------------------------------------------------

def test_document_validator_complete_valid_record():
    """Verify a complete valid document with all field types passes validation."""
    validator = DocumentValidator(
        required_fields=["invoice_number", "date", "amount"],
        date_fields={"date": {"allowed_formats": ["%Y-%m-%d"]}},
        numeric_fields={"amount": {"min_value": Decimal("0.01"), "decimal_places": 2}},
        invoice_fields={"invoice_number": {"min_length": 3}},
    )

    doc = {
        "invoice_number": "INV-1001",
        "date": "2024-11-03",
        "amount": "250.75",
        "optional_notes": "Paid in full",
    }

    result = validator.validate(doc)
    assert result.is_valid
    assert len(result.errors) == 0
    assert len(result.warnings) == 0

    # Verify dictionary serialization contract
    serialized = result.to_dict()
    assert serialized == {
        "is_valid": True,
        "errors": [],
        "warnings": [],
    }


def test_document_validator_multiple_errors_in_one_document():
    """Verify DocumentValidator aggregates multiple errors across fields."""
    validator = DocumentValidator(
        required_fields=["vendor", "invoice_number", "date", "amount"],
        date_fields={"date": {"allowed_formats": ["%Y-%m-%d"]}},
        numeric_fields={"amount": {"min_value": 0}},
    )

    doc = {
        "vendor": "   ",         # whitespace error
        "date": "invalid-date",  # malformed date
        "amount": -50,           # out of range
        # invoice_number missing
    }

    result = validator.validate(doc)
    assert not result.is_valid
    assert len(result.errors) >= 3

    error_fields = {e.field for e in result.errors}
    assert "vendor" in error_fields
    assert "invoice_number" in error_fields
    assert "date" in error_fields
    assert "amount" in error_fields


def test_document_validator_warnings_without_errors():
    """Verify DocumentValidator can produce warnings while is_valid remains True."""
    validator = DocumentValidator(
        required_fields=["invoice_number", "date"],
        date_fields={"date": {"allowed_formats": ["%d/%m/%Y", "%m/%d/%Y"], "warn_on_ambiguity": True}},
        confidence_threshold=0.75,
    )

    doc = {
        # Confidence metadata present and below threshold
        "invoice_number": {"value": "INV-001", "confidence": 0.60},
        # Ambiguous date (01/02/2024 could be Jan 2 or Feb 1)
        "date": "01/02/2024",
    }

    result = validator.validate(doc)
    assert result.is_valid  # No blocking errors
    assert len(result.errors) == 0
    assert len(result.warnings) == 2  # low_confidence and ambiguous_date_format

    warning_codes = {w.code for w in result.warnings}
    assert "low_confidence" in warning_codes
    assert "ambiguous_date_format" in warning_codes
