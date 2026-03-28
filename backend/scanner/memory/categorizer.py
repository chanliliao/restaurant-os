"""Error categorization for user corrections.

Pure functions -- no I/O, no state. Classifies each correction into one of:
  - "misread"      : OCR read it wrong (both original and corrected are non-empty)
  - "missing"      : OCR missed it (original is empty/null/zero, corrected is not)
  - "hallucinated" : OCR made it up (original is non-empty, corrected is empty/null/"deleted_row")
"""

from __future__ import annotations


def _is_empty(value) -> bool:
    """Return True if value is considered empty/absent.

    Zero is treated as empty because invoice fields default to 0 when the
    scanner cannot extract a value. A genuine zero (e.g. tax-exempt tax=0)
    is rare and would be classified as "missing" → user correction records
    it correctly either way.
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _is_deletion(value) -> bool:
    """Return True if the corrected value signals a deletion.

    Unlike _is_empty, zero is NOT treated as deletion — correcting a value
    to 0 (e.g. a complimentary item) is a "misread", not "hallucinated".
    """
    if value is None:
        return True
    if isinstance(value, str) and (value.strip() == "" or value.strip() == "deleted_row"):
        return True
    return False


def categorize_error(field: str, original_value, corrected_value) -> str:
    """Classify a single field correction into an error type.

    Args:
        field: The field name/path that was corrected.
        original_value: The value the scanner produced.
        corrected_value: The value the user corrected it to.

    Returns:
        One of "misread", "missing", or "hallucinated".
    """
    original_empty = _is_empty(original_value)
    corrected_is_deletion = _is_deletion(corrected_value)

    if not original_empty and corrected_is_deletion:
        return "hallucinated"
    if original_empty and not corrected_is_deletion:
        return "missing"
    return "misread"


def categorize_corrections(corrections: list[dict]) -> list[dict]:
    """Add ``error_type`` to each correction dict. Returns new list (no mutation).

    Each input dict must have ``field``, ``original_value``, ``corrected_value``.
    """
    result = []
    for correction in corrections:
        enriched = {**correction}
        enriched["error_type"] = categorize_error(
            correction["field"],
            correction["original_value"],
            correction["corrected_value"],
        )
        result.append(enriched)
    return result
