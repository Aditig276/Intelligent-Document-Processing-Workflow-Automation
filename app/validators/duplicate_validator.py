"""Duplicate detection module.

Provides configurable duplicate detection for single fields (e.g. invoice_number)
or composite comparison keys (e.g. ['invoice_number', 'vendor', 'date']).
Safely handles missing comparison values (never treats two missing keys as duplicates),
operates in a strictly non-destructive manner (no deletions or modifications), and
supports configurable warning vs. error policies.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.validators.base import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    extract_field_value_and_confidence,
)


def _build_record_key(
    record: Mapping[str, Any],
    key_fields: Sequence[str],
) -> tuple[Any, ...] | None:
    """Extract a normalized comparison key tuple from a record.

    If ANY of the configured key fields is absent, null, or empty/whitespace,
    returns None to indicate the record cannot form a complete comparison key.
    This guarantees that two records missing key values are NEVER treated as duplicates.
    """
    key_parts: list[Any] = []
    for field_name in key_fields:
        if field_name not in record:
            return None
        raw_val = record[field_name]
        val, _ = extract_field_value_and_confidence(raw_val)

        if val is None:
            return None
        if isinstance(val, str):
            val_clean = val.strip()
            if len(val_clean) == 0:
                return None
            key_parts.append(val_clean.lower())  # case-insensitive key comparison
        else:
            key_parts.append(val)

    return tuple(key_parts)


class DuplicateDetector:
    """Stateful duplicate detector for streaming records or cumulative batches."""

    def __init__(
        self,
        key_fields: Iterable[str],
        policy: str = "warning",
    ) -> None:
        """Initialize duplicate detector.

        Args:
            key_fields: Iterable of field names composing the comparison key.
            policy: 'warning' (emits a non-blocking warning) or 'error' (fails validation).

        Raises:
            ValueError: If key_fields is empty or policy is unsupported.
        """
        self.key_fields = list(key_fields)
        if not self.key_fields:
            raise ValueError(
                "A duplicate comparison key or list of fields must be configured."
            )

        policy_clean = policy.strip().lower()
        if policy_clean not in {"warning", "error"}:
            raise ValueError(
                f"Unsupported duplicate policy: '{policy}'. Expected 'warning' or 'error'."
            )
        self.policy = policy_clean

        # Maps normalized key tuple -> list of record references (e.g. index or ID)
        self._seen: dict[tuple[Any, ...], list[Any]] = {}

    def reset(self) -> None:
        """Clear all previously recorded keys."""
        self._seen.clear()

    def check(
        self,
        record: Mapping[str, Any],
        record_id: Any | None = None,
    ) -> ValidationResult:
        """Check whether a record duplicates an already observed record without adding it.

        Args:
            record: Data mapping for the document/record.
            record_id: Optional identifier or index for reporting.

        Returns:
            ValidationResult with duplicate warning or error if duplicated.
        """
        result = ValidationResult(is_valid=True)
        key = _build_record_key(record, self.key_fields)

        # Missing key fields are safely ignored for duplicate checking
        if key is None:
            return result

        if key in self._seen:
            field_desc = ", ".join(self.key_fields)
            seen_refs = self._seen[key]
            first_ref = seen_refs[0] if seen_refs else "earlier record"
            msg = (
                f"Duplicate record detected on [{field_desc}]: key {key} "
                f"was already observed in {first_ref}."
            )
            target_field = self.key_fields[0] if len(self.key_fields) == 1 else "record"

            if self.policy == "error":
                result.add_error(
                    field_name=target_field,
                    code="duplicate_value",
                    message=msg,
                )
            else:
                result.add_warning(
                    field_name=target_field,
                    code="duplicate_value",
                    message=msg,
                )

        return result

    def add(
        self,
        record: Mapping[str, Any],
        record_id: Any | None = None,
    ) -> bool:
        """Record the key of a record. Returns True if successfully stored, False if key was incomplete."""
        key = _build_record_key(record, self.key_fields)
        if key is None:
            return False

        if key not in self._seen:
            self._seen[key] = []
        self._seen[key].append(record_id if record_id is not None else len(self._seen[key]))
        return True

    def check_and_add(
        self,
        record: Mapping[str, Any],
        record_id: Any | None = None,
    ) -> ValidationResult:
        """Check whether a record is a duplicate, and then add it to the seen registry."""
        result = self.check(record, record_id=record_id)
        self.add(record, record_id=record_id)
        return result


def validate_duplicates(
    records: Sequence[Mapping[str, Any]],
    key_fields: Iterable[str],
    policy: str = "warning",
    id_field: str | None = None,
) -> list[ValidationResult]:
    """Validate a batch of records for duplicates.

    Returns a list of ValidationResults matching the order of input records.
    Never alters, drops, or re-orders the original records.

    Args:
        records: Sequence of document or record mappings.
        key_fields: List or iterable of field names forming the comparison key.
        policy: 'warning' (default) or 'error'.
        id_field: Optional field name within each record to use as identifier.

    Returns:
        list of ValidationResult objects for each record.
    """
    detector = DuplicateDetector(key_fields=key_fields, policy=policy)
    results: list[ValidationResult] = []

    for idx, rec in enumerate(records):
        rec_id = rec.get(id_field) if id_field and id_field in rec else f"record #{idx + 1}"
        result = detector.check_and_add(rec, record_id=rec_id)
        results.append(result)

    return results


class DuplicateValidator:
    """Configurable batch duplicate validator."""

    def __init__(
        self,
        key_fields: Iterable[str],
        policy: str = "warning",
        id_field: str | None = None,
    ) -> None:
        self.key_fields = list(key_fields)
        self.policy = policy
        self.id_field = id_field

    def validate(
        self,
        records: Sequence[Mapping[str, Any]],
    ) -> list[ValidationResult]:
        """Validate a collection of records for duplicates."""
        return validate_duplicates(
            records=records,
            key_fields=self.key_fields,
            policy=self.policy,
            id_field=self.id_field,
        )
