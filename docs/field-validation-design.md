# Field Validation Module Design & Specification

**Module:** Field Validation Engine (`app/validators`)  
**Project:** Intelligent Document Processing & Workflow Automation  
**Author:** Week 2 Backend / Validation Contributor  
**Branch:** `feature/field-validation`  

---

## 1. Module Purpose

The Field Validation Module provides a reusable, modular, framework-independent Python validation engine for structured data extracted from uploaded documents (invoices, receipts, spreadsheets, etc.).

The engine verifies:
1. **Required Fields & Blank Checks:** Detects missing keys, nulls, empty strings, and whitespace-only values without rejecting optional fields.
2. **Date Validation:** Enforces configured date formats, detects malformed strings, identifies impossible calendar dates (e.g. Feb 30, April 31, non-leap year Feb 29), handles ambiguous date formats without guessing, and checks date range bounds.
3. **Numeric & Amount Validation:** Uses `Decimal` arithmetic for financial precision, strictly rejects `NaN` and `Infinity`, verifies range boundaries (e.g., non-negative amounts), integer constraints, and decimal place limits.
4. **Invoice Identifiers:** Preserves invoice identifiers as strings to prevent truncation of leading zeros, supports alphanumeric/special-character formats, and allows configurable rules without imposing a fictional universal pattern.
5. **Duplicate Detection:** Identifies duplicate documents based on single or composite keys, safely handles missing comparison keys (never treats two missing keys as duplicates), operates non-destructively, and supports configurable warning or error policies.
6. **Structured Errors & Warnings:** Returns standardized results distinguishing blocking errors (`errors`) from non-blocking issues or extraction uncertainties (`warnings`).

---

## 2. Package & File Structure

```
app/
    validators/
        __init__.py              # Public package exports
        base.py                  # Core data classes (ValidationError, ValidationWarning, ValidationResult)
        field_validator.py       # Required fields, invoice identifiers, and DocumentValidator orchestrator
        date_validator.py        # Date parsing, impossible date checks, and ambiguity warnings
        numeric_validator.py     # Numeric & amount validation, Decimal handling, NaN/infinity checks
        duplicate_validator.py   # Single & composite key duplicate detection with warning/error policies

tests/
    test_field_validation.py     # Tests for required fields, invoice rules, and DocumentValidator
    test_date_validation.py      # Tests for date parsing, impossible dates, ambiguity, and ranges
    test_numeric_validation.py   # Tests for numbers, amounts, blanks, NaN/inf, ranges, and types
    test_duplicate_validation.py # Tests for duplicate invoice numbers, composite keys, and policies

docs/
    field-validation-design.md   # This design document
```

---

## 3. How to Call the Validation Engine

The module can be invoked either through the high-level `DocumentValidator` orchestrator or via targeted functional validators.

### High-Level Orchestrator Example

```python
from decimal import Decimal
from app.validators import DocumentValidator

validator = DocumentValidator(
    required_fields=["invoice_number", "date", "amount"],
    date_fields={
        "date": {
            "allowed_formats": ["%Y-%m-%d"],
            "warn_on_ambiguity": True,
        }
    },
    numeric_fields={
        "amount": {
            "min_value": Decimal("0.01"),
            "decimal_places": 2,
            "allow_negative": False,
        }
    },
    invoice_fields={
        "invoice_number": {
            "min_length": 3,
            "max_length": 50,
        }
    },
    confidence_threshold=0.75,
)

document_data = {
    "invoice_number": "INV-2024-001",
    "date": "2024-11-03",
    "amount": "1450.50",
    "vendor": "Acme Supplies",
}

result = validator.validate(document_data)

if result.is_valid:
    print("Document is valid!")
else:
    print(f"Validation failed with {len(result.errors)} errors: {result.errors}")
```

### Targeted Validator Functions

```python
from app.validators import (
    validate_required_fields,
    validate_date,
    validate_numeric,
    validate_invoice_number,
    validate_duplicates,
)

# 1. Required fields
errors, warnings = validate_required_fields(
    data={"vendor": "Acme Corp"},
    required_fields=["vendor", "invoice_number"],
)

# 2. Date validation
errors, warnings = validate_date(
    value="2024-02-29",
    field_name="invoice_date",
    allowed_formats=["%Y-%m-%d"],
)

# 3. Numeric validation
errors, warnings = validate_numeric(
    value="250.75",
    field_name="total_amount",
    min_value=0,
    decimal_places=2,
)

# 4. Duplicate validation
results = validate_duplicates(
    records=documents_list,
    key_fields=["invoice_number", "vendor"],
    policy="warning",  # or "error"
)
```

---

## 4. Input & Output Formats

### Input Format
The validation engine accepts standard Python `Mapping[str, Any]` instances (e.g. dictionaries).

Fields can be provided in two forms:
1. **Raw scalar value:**
   ```json
   {
       "invoice_number": "INV-00123",
       "date": "2024-11-03",
       "amount": 450.00
   }
   ```
2. **Value with extraction metadata/confidence:**
   ```json
   {
       "invoice_number": {
           "value": "INV-00123",
           "confidence": 0.94
       },
       "date": {
           "value": "2024-11-03",
           "confidence": 0.62
       }
   }
   ```
   *Note:* The engine does not invent confidence scores. If confidence metadata is present and below the configured `confidence_threshold`, a non-blocking `low_confidence` warning is emitted.

### Output Format
Every validation check outputs or serializes to the agreed structured schema:

```json
{
    "is_valid": false,
    "errors": [
        {
            "field": "invoice_number",
            "code": "required_field_missing",
            "message": "Required field 'invoice_number' is missing."
        }
    ],
    "warnings": [
        {
            "field": "date",
            "code": "ambiguous_date_format",
            "message": "Date value '01/02/2024' for field 'date' is ambiguous: parses differently across formats ('%d/%m/%Y' -> 2024-02-01, '%m/%d/%Y' -> 2024-01-02)."
        }
    ]
}
```

---

## 5. Configuration Options

### `DocumentValidator`
| Option | Type | Default | Description |
|---|---|---|---|
| `required_fields` | `Iterable[str]` | `[]` | List of field names that must be present and non-blank. |
| `date_fields` | `dict[str, dict]` | `{}` | Per-field date rules (`allowed_formats`, `min_date`, `max_date`, `warn_on_ambiguity`). |
| `numeric_fields` | `dict[str, dict]` | `{}` | Per-field numeric rules (`min_value`, `max_value`, `allow_negative`, `integer_only`, `decimal_places`, `strip_currency_symbols`). |
| `invoice_fields` | `dict[str, dict]` | `{}` | Per-field invoice identifier rules (`min_length`, `max_length`, `pattern`, `allowed_characters`). |
| `confidence_threshold` | `float` | `None` | Optional threshold below which extraction generates a `low_confidence` warning. |
| `custom_validators` | `dict[str, Callable]` | `{}` | Custom per-field validation callables `(val) -> (errors, warnings)`. |

### `validate_date` / `DateValidator`
| Option | Type | Default | Description |
|---|---|---|---|
| `allowed_formats` | `list[str]` | `["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"]` | Allowed strptime date formats. |
| `is_required` | `bool` | `True` | Whether the date field is mandatory. |
| `min_date` | `date` | `None` | Earliest permissible date. |
| `max_date` | `date` | `None` | Latest permissible date. |
| `warn_on_ambiguity`| `bool` | `True` | Whether to emit a warning when multiple formats parse to different calendar dates. |

### `validate_numeric` / `NumericValidator`
| Option | Type | Default | Description |
|---|---|---|---|
| `is_required` | `bool` | `True` | Whether the numeric field is mandatory. |
| `min_value` | `Decimal/float/int` | `None` | Minimum permissible value (inclusive). |
| `max_value` | `Decimal/float/int` | `None` | Maximum permissible value (inclusive). |
| `allow_negative` | `bool` | `True` | Whether negative numbers are permitted. |
| `integer_only` | `bool` | `False` | Whether fractional decimal values are rejected. |
| `decimal_places` | `int` | `None` | Maximum allowed digits after decimal separator. |
| `strip_currency_symbols` | `bool` | `False` | Opt-in stripping of currency signs (`$`, `€`, `£`, `,`). Default is False to prevent unconfirmed assumptions. |

### `DuplicateDetector` / `DuplicateValidator`
| Option | Type | Default | Description |
|---|---|---|---|
| `key_fields` | `list[str]` | *Required* | Field name or list of field names that form the comparison key. |
| `policy` | `str` | `"warning"` | `"warning"` (emits warning, `is_valid=True`) or `"error"` (emits error, `is_valid=False`). |
| `id_field` | `str` | `None` | Record identifier field used in duplicate report messages. |

---

## 6. Error and Warning Codes

### Error Codes (`errors`)
| Error Code | Meaning |
|---|---|
| `required_field_missing` | Required field is missing from dictionary or is `None`. |
| `empty_value` | String field is empty (`""`). |
| `whitespace_value` | String field contains only whitespace characters (`"   "`). |
| `invalid_date_format` | Date string does not match any configured format or is not a date. |
| `impossible_date` | Date violates calendar logic (e.g. Feb 30, April 31, non-leap Feb 29). |
| `date_out_of_range` | Date is earlier than `min_date` or later than `max_date`. |
| `invalid_numeric` | Value cannot be parsed as a number or is an invalid type (e.g. boolean, non-numeric text). |
| `nan_or_infinity` | Value is `NaN`, `Infinity`, or `-Infinity`. |
| `numeric_out_of_range` | Number is below `min_value`, exceeds `max_value`, or is negative when `allow_negative=False`. |
| `integer_required` | Number contains fractional decimal digits when `integer_only=True`. |
| `excess_decimal_places` | Number has more decimal places than `decimal_places`. |
| `invalid_invoice_format` | Invoice identifier does not match regex pattern or contains disallowed characters. |
| `invoice_too_short` | Invoice identifier length is less than `min_length`. |
| `invoice_too_long` | Invoice identifier length exceeds `max_length`. |
| `duplicate_value` | Record matches an earlier record under `policy="error"`. |

### Warning Codes (`warnings`)
| Warning Code | Meaning |
|---|---|
| `low_confidence` | Extracted field has a confidence score below the configured `confidence_threshold`. |
| `ambiguous_date_format` | Date matches multiple allowed formats that resolve to different calendar dates (e.g. `01/02/2024`). |
| `duplicate_value` | Record matches an earlier record under default `policy="warning"`. |

---

## 7. Duplicate Detection Behavior

1. **Comparison Rule Requirement:** A duplicate check cannot be performed without a defined `key_fields` list. Calling the detector without key fields raises `ValueError`.
2. **Missing Key Safety:** If a record is missing any field in the composite key, or if the field is `None` or blank, the record is **not** treated as a duplicate. Two records both missing an invoice number will never falsely match as duplicates of each other.
3. **Non-Destructive:** The duplicate detector never deletes, modifies, reorders, or drops duplicate records. It merely tags the result with an error or warning according to policy.
4. **Case-Insensitive String Keys:** String keys are trimmed and normalized to lowercase to prevent trivial bypasses (e.g., `"INV-001"` and `"inv-001"` are detected as duplicates).
5. **Policy Choice:**
   - `policy="warning"`: Allows downstream processing while alerting human auditors of the potential duplicate.
   - `policy="error"`: Immediately blocks the duplicate record from processing.

---

## 8. Assumptions Awaiting Team Confirmation

| Topic | Proposed Default in this Module | Status / Awaiting Team Approval |
|---|---|---|
| **Document Types & Schemas** | Configurable via `DocumentValidator` without hardcoded schemas | Pending extraction team confirmation of document types (e.g. invoices, receipts, utility bills). |
| **Supported Date Formats** | `["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"]` | Pending team confirmation of standard date formats output by OCR/extraction. |
| **Currency Handling** | `strip_currency_symbols=False` (rejected unless explicitly opted in) | Pending confirmation of whether extraction returns clean numbers or currency symbols. |
| **Invoice Number Format** | Preserved as string, alphanumeric allowed, no rigid regex imposed | Pending confirmation of client-specific invoice numbering conventions. |
| **Duplicate Policy** | Default `"warning"` (flagged for review without dropping records) | Pending business workflow confirmation on whether duplicates should be rejected or flagged. |
| **Extraction Confidence** | Supported via `{"value": ..., "confidence": ...}` | Pending confirmation of OCR engine confidence score format. |
