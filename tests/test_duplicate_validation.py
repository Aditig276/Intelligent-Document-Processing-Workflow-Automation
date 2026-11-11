"""Unit tests for duplicate detection.

Covers:
- Duplicate invoice numbers (single field key)
- Unique invoice numbers
- Duplicate records via composite comparison keys
- Safe handling of missing duplicate keys (missing keys are never flagged as duplicates)
- Configurable duplicate policies ('warning' vs 'error')
- Non-destructive operation (no records altered or removed)
- Stateful DuplicateDetector (check, add, reset)
- Batch DuplicateValidator
"""

import pytest

from app.validators import (
    DuplicateDetector,
    DuplicateValidator,
    ValidationError,
    ValidationResult,
    ValidationWarning,
    validate_duplicates,
)


def test_unique_records_pass_without_duplicates():
    """Verify distinct records produce no duplicate warnings or errors."""
    records = [
        {"invoice_number": "INV-001", "vendor": "Acme"},
        {"invoice_number": "INV-002", "vendor": "Beta"},
        {"invoice_number": "INV-003", "vendor": "Acme"},
    ]

    results = validate_duplicates(records, key_fields=["invoice_number"])

    assert len(results) == 3
    for res in results:
        assert res.is_valid
        assert len(res.errors) == 0
        assert len(res.warnings) == 0


def test_duplicate_invoice_number_warning_policy():
    """Verify duplicate invoice numbers produce warnings under default 'warning' policy."""
    records = [
        {"invoice_number": "INV-001", "amount": 100},
        {"invoice_number": "INV-002", "amount": 200},
        {"invoice_number": "inv-001", "amount": 150},  # Case-insensitive duplicate
    ]

    results = validate_duplicates(records, key_fields=["invoice_number"], policy="warning")

    # First record: valid, no warning
    assert results[0].is_valid
    assert len(results[0].warnings) == 0

    # Second record: valid, no warning
    assert results[1].is_valid
    assert len(results[1].warnings) == 0

    # Third record: duplicate of first record
    assert results[2].is_valid  # Under warning policy, record remains is_valid=True
    assert len(results[2].warnings) == 1
    assert results[2].warnings[0].code == "duplicate_value"
    assert "duplicate" in results[2].warnings[0].message.lower()


def test_duplicate_invoice_number_error_policy():
    """Verify duplicate invoice numbers produce errors under 'error' policy."""
    records = [
        {"invoice_number": "INV-100", "vendor": "Acme"},
        {"invoice_number": "INV-100", "vendor": "Beta"},  # Duplicate
    ]

    results = validate_duplicates(records, key_fields=["invoice_number"], policy="error")

    assert results[0].is_valid
    assert len(results[0].errors) == 0

    # Second record fails validation
    assert not results[1].is_valid
    assert len(results[1].errors) == 1
    assert results[1].errors[0].code == "duplicate_value"
    assert results[1].errors[0].field == "invoice_number"


def test_composite_key_duplicate_detection():
    """Verify duplicate detection across multi-field composite keys."""
    key_fields = ["invoice_number", "vendor", "date"]

    records = [
        # Record 1: Base
        {"invoice_number": "INV-01", "vendor": "Acme", "date": "2024-01-01"},
        # Record 2: Same invoice number, DIFFERENT vendor -> NOT a duplicate
        {"invoice_number": "INV-01", "vendor": "Beta", "date": "2024-01-01"},
        # Record 3: Same invoice number and vendor, DIFFERENT date -> NOT a duplicate
        {"invoice_number": "INV-01", "vendor": "Acme", "date": "2024-02-01"},
        # Record 4: Exact match with Record 1 on all composite fields -> DUPLICATE
        {"invoice_number": "INV-01", "vendor": "Acme", "date": "2024-01-01"},
    ]

    results = validate_duplicates(records, key_fields=key_fields, policy="error")

    assert results[0].is_valid
    assert results[1].is_valid
    assert results[2].is_valid
    assert not results[3].is_valid
    assert results[3].errors[0].code == "duplicate_value"


def test_missing_duplicate_keys_are_safely_ignored():
    """Verify two records missing comparison keys are NEVER treated as duplicates of each other."""
    records = [
        {"vendor": "Acme", "amount": 100},              # Missing invoice_number
        {"vendor": "Beta", "amount": 200},              # Missing invoice_number
        {"invoice_number": None, "amount": 300},        # None invoice_number
        {"invoice_number": "", "amount": 400},          # Empty invoice_number
        {"invoice_number": "   ", "amount": 500},       # Whitespace invoice_number
    ]

    results = validate_duplicates(records, key_fields=["invoice_number"], policy="error")

    for idx, res in enumerate(results):
        assert res.is_valid, f"Record {idx} was falsely flagged as a duplicate"
        assert len(res.errors) == 0
        assert len(res.warnings) == 0


def test_records_are_not_modified_or_deleted():
    """Verify duplicate validation does not mutate, drop, or alter input records."""
    records = [
        {"invoice_number": "INV-001", "amount": 100},
        {"invoice_number": "INV-001", "amount": 100},
    ]
    original_len = len(records)
    rec1_copy = dict(records[0])
    rec2_copy = dict(records[1])

    validate_duplicates(records, key_fields=["invoice_number"])

    assert len(records) == original_len
    assert records[0] == rec1_copy
    assert records[1] == rec2_copy


def test_unconfigured_duplicate_keys_raise_error():
    """Verify initializing detector with empty key fields raises ValueError."""
    with pytest.raises(ValueError, match="must be configured"):
        DuplicateDetector(key_fields=[])


def test_invalid_policy_raises_error():
    """Verify invalid policy raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported duplicate policy"):
        DuplicateDetector(key_fields=["invoice_number"], policy="invalid_policy")


def test_stateful_duplicate_detector():
    """Verify stateful DuplicateDetector methods (check, add, reset)."""
    detector = DuplicateDetector(key_fields=["invoice_number"], policy="error")

    rec1 = {"invoice_number": "INV-1"}
    rec2 = {"invoice_number": "INV-2"}

    # check rec1 before adding: not duplicate
    assert detector.check(rec1).is_valid

    # add rec1
    assert detector.add(rec1, record_id="rec_1") is True

    # check rec1 again: now duplicate
    res_dup = detector.check(rec1)
    assert not res_dup.is_valid
    assert res_dup.errors[0].code == "duplicate_value"

    # check rec2: not duplicate
    assert detector.check(rec2).is_valid

    # reset
    detector.reset()
    assert detector.check(rec1).is_valid


def test_duplicate_validator_class():
    """Verify DuplicateValidator batch class wrapper."""
    validator = DuplicateValidator(key_fields=["invoice_number"], policy="warning")
    records = [
        {"invoice_number": "INV-A"},
        {"invoice_number": "INV-A"},
    ]

    results = validator.validate(records)
    assert len(results) == 2
    assert results[0].is_valid and len(results[0].warnings) == 0
    assert results[1].is_valid and len(results[1].warnings) == 1
