"""Base validation models and shared data structures.

This module defines framework-independent data structures for representing
validation errors, warnings, and complete validation results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationError:
    """Represents a specific validation error on a field."""

    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Serialize error to a standard dictionary format."""
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationWarning:
    """Represents a non-blocking validation warning or uncertainty on a field."""

    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Serialize warning to a standard dictionary format."""
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """Structured result of a validation check on a document or record.

    Attributes:
        is_valid: Boolean indicating whether validation passed with no errors.
        errors: List of ValidationError objects.
        warnings: List of ValidationWarning objects.
    """

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)

    def add_error(self, field_name: str, code: str, message: str) -> None:
        """Append an error and mark the result as invalid."""
        self.errors.append(
            ValidationError(field=field_name, code=code, message=message)
        )
        self.is_valid = False

    def add_warning(self, field_name: str, code: str, message: str) -> None:
        """Append a non-blocking warning without marking the result invalid."""
        self.warnings.append(
            ValidationWarning(field=field_name, code=code, message=message)
        )

    def merge(self, other: ValidationResult) -> ValidationResult:
        """Merge another ValidationResult into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.is_valid:
            self.is_valid = False
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to the standard JSON-serializable dictionary format."""
        return {
            "is_valid": self.is_valid,
            "errors": [err.to_dict() for err in self.errors],
            "warnings": [warn.to_dict() for warn in self.warnings],
        }


def extract_field_value_and_confidence(
    raw_entry: Any,
) -> tuple[Any, float | None]:
    """Extract raw value and optional extraction confidence score.

    Supports both raw scalar values (e.g. "INV-101") and dictionary wrappers
    with confidence metadata (e.g. {"value": "INV-101", "confidence": 0.85}).
    Does not invent or assume confidence when not present.

    Returns:
        tuple of (extracted_value, confidence_or_none)
    """
    if isinstance(raw_entry, Mapping) and "value" in raw_entry:
        value = raw_entry.get("value")
        raw_conf = raw_entry.get("confidence")
        confidence = None
        if raw_conf is not None:
            try:
                confidence = float(raw_conf)
            except (ValueError, TypeError):
                confidence = None
        return value, confidence
    return raw_entry, None
