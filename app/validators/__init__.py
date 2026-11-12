"""Validation engine package for Intelligent Document Processing.

This package provides modular, framework-independent validation for structured data
extracted from documents, covering required fields, dates, numeric amounts,
invoice identifiers, and non-destructive duplicate detection.
"""

from app.validators.base import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    extract_field_value_and_confidence,
)
from app.validators.date_validator import (
    DEFAULT_ALLOWED_DATE_FORMATS,
    DateValidator,
    validate_date,
)
from app.validators.duplicate_validator import (
    DuplicateDetector,
    DuplicateValidator,
    validate_duplicates,
)
from app.validators.field_validator import (
    DocumentValidator,
    FieldValidator,
    validate_invoice_number,
    validate_required_fields,
)
from app.validators.numeric_validator import (
    NumericValidator,
    validate_numeric,
)

__all__ = [
    "ValidationError",
    "ValidationWarning",
    "ValidationResult",
    "extract_field_value_and_confidence",
    "validate_required_fields",
    "validate_invoice_number",
    "FieldValidator",
    "DocumentValidator",
    "validate_date",
    "DateValidator",
    "DEFAULT_ALLOWED_DATE_FORMATS",
    "validate_numeric",
    "NumericValidator",
    "validate_duplicates",
    "DuplicateDetector",
    "DuplicateValidator",
]
