"""Tests for required-field, invoice, date, numeric and duplicate validation.

Run after feature/field-validation is merged into this branch.
"""
import pytest

validators = pytest.importorskip("app.validators")
FieldValidator = validators.FieldValidator
DocumentValidator = validators.DocumentValidator
validate_invoice_number = validators.validate_invoice_number
validate_numeric = validators.validate_numeric
validate_date = validators.validate_date
validate_duplicates = validators.validate_duplicates


def error_codes(errors):
    return {error.code for error in errors}


def test_required_fields_accept_complete_record():
    validator = FieldValidator(required_fields=["invoice_number", "vendor", "amount"])
    result = validator.validate(
        {"invoice_number": "INV-001", "vendor": "Acme Test", "amount": 1200}
    )
    assert result.is_valid is True
    assert result.errors == []


@pytest.mark.parametrize(
    ("record", "expected_code"),
    [
        ({"vendor": "Acme"}, "required_field_missing"),
        ({"invoice_number": None}, "required_field_missing"),
        ({"invoice_number": ""}, "empty_value"),
        ({"invoice_number": "   "}, "whitespace_value"),
    ],
)
def test_required_field_rejects_missing_or_blank_values(record, expected_code):
    errors, _ = validators.validate_required_fields(record, ["invoice_number"])
    assert expected_code in error_codes(errors)


def test_optional_field_can_be_absent():
    result = FieldValidator(required_fields=["invoice_number"]).validate(
        {"invoice_number": "INV-002"}
    )
    assert result.is_valid is True


def test_invoice_number_preserves_leading_zeroes():
    errors, warnings = validate_invoice_number("000123")
    assert errors == []
    assert warnings == []


def test_invoice_number_supports_configured_pattern():
    errors, _ = validate_invoice_number(
        "INV-2026-001", pattern=r"^INV-\d{4}-\d{3}$"
    )
    assert errors == []


def test_invoice_number_rejects_wrong_pattern():
    errors, _ = validate_invoice_number(
        "BAD-001", pattern=r"^INV-\d{4}-\d{3}$"
    )
    assert "invalid_invoice_format" in error_codes(errors)


def test_numeric_accepts_valid_amount_and_configured_currency():
    errors, _ = validate_numeric(
        "₹1,250.50", strip_currency_symbols=True, min_value=0
    )
    assert errors == []


def test_numeric_rejects_non_numeric_value():
    errors, _ = validate_numeric("twelve hundred")
    assert "invalid_numeric" in error_codes(errors)


def test_numeric_rejects_negative_when_disallowed():
    errors, _ = validate_numeric(-10, allow_negative=False)
    assert "numeric_out_of_range" in error_codes(errors)


def test_numeric_rejects_amount_above_maximum():
    errors, _ = validate_numeric(1500, max_value=1000)
    assert "numeric_out_of_range" in error_codes(errors)


def test_numeric_rejects_boolean_value():
    errors, _ = validate_numeric(True)
    assert "invalid_numeric" in error_codes(errors)


def test_date_accepts_iso_date():
    errors, _ = validate_date("2026-11-10", allowed_formats=["%Y-%m-%d"])
    assert errors == []


def test_date_rejects_impossible_calendar_date():
    errors, _ = validate_date("2026-02-30", allowed_formats=["%Y-%m-%d"])
    assert errors


def test_document_validator_combines_required_date_and_numeric_rules():
    validator = DocumentValidator(
        required_fields=["invoice_number", "invoice_date", "amount"],
        date_fields={"invoice_date": {"allowed_formats": ["%Y-%m-%d"]}},
        numeric_fields={"amount": {"min_value": 0, "allow_negative": False}},
    )
    result = validator.validate(
        {"invoice_number": "INV-003", "invoice_date": "2026-11-10", "amount": 500}
    )
    assert result.is_valid is True
    assert result.errors == []


def test_duplicate_detection_flags_duplicate_without_deleting_records():
    records = [
        {"invoice_number": "INV-004", "vendor": "Acme"},
        {"invoice_number": "inv-004", "vendor": "Acme"},
    ]
    original = [dict(record) for record in records]

    results = validate_duplicates(records, key_fields=["invoice_number"])

    assert results[0].is_valid is True
    assert len(results[1].warnings) == 1
    assert records == original


def test_duplicate_detection_does_not_treat_missing_keys_as_duplicates():
    records = [{"invoice_number": None}, {"invoice_number": None}]
    results = validate_duplicates(records, key_fields=["invoice_number"])

    assert all(result.is_valid for result in results)
    assert all(result.warnings == [] for result in results)
