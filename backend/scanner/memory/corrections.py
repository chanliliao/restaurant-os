"""Apply user corrections to scan data to produce the canonical "truth" result.

Pure functions -- no I/O, no state.
"""

from __future__ import annotations

import copy
import re


def _parse_item_field(field: str) -> tuple[int, str | None] | None:
    """Parse ``items[N]`` or ``items[N].subfield`` into (index, subfield|None).

    Returns None if the field does not match the items pattern.
    """
    m = re.match(r"^items\[(\d+)\](?:\.(.+))?$", field)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def apply_corrections(scan_result: dict, corrections: list[dict]) -> dict:
    """Apply a list of corrections to a scan result, returning a new dict.

    Corrections are dicts with ``field``, ``original_value``, ``corrected_value``.

    Field paths:
    - Top-level: ``"supplier"``, ``"total"``, etc. -- set directly.
    - Item field: ``"items[0].unit_price"`` -- update item at index.
    - Row deletion: ``"items[1]"`` with ``corrected_value == "deleted_row"`` -- remove item.

    Does NOT mutate the input ``scan_result``.
    """
    result = copy.deepcopy(scan_result)

    # Separate deletions from other corrections so we can process deletions last
    # (highest index first to avoid shifting).
    deletions: list[int] = []
    field_updates: list[dict] = []

    for correction in corrections:
        field = correction["field"]
        corrected = correction["corrected_value"]

        parsed = _parse_item_field(field)
        if parsed is not None:
            idx, subfield = parsed
            if subfield is None and corrected == "deleted_row":
                deletions.append(idx)
            else:
                field_updates.append(correction)
        else:
            field_updates.append(correction)

    # Apply field updates (header and item subfields)
    items = result.get("items", [])
    for correction in field_updates:
        field = correction["field"]
        corrected = correction["corrected_value"]

        parsed = _parse_item_field(field)
        if parsed is not None:
            idx, subfield = parsed
            if 0 <= idx < len(items) and subfield:
                items[idx][subfield] = corrected
        else:
            # Top-level header field
            result[field] = corrected

    # Apply deletions highest-index-first so indices stay valid
    for idx in sorted(deletions, reverse=True):
        if 0 <= idx < len(items):
            del items[idx]

    return result
