"""
Field-by-field comparison and merging of two invoice scan results.

Compares text fields with fuzzy matching and numeric fields with exact
matching, then merges results using agreed values and optional tiebreaker.
"""

import copy
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Fuzzy match threshold for text fields (0.0–1.0)
TEXT_MATCH_THRESHOLD = 0.85

# Top-level text fields to compare
TEXT_FIELDS = ("supplier", "date", "invoice_number")

# Top-level numeric fields to compare
NUMERIC_FIELDS = ("subtotal", "tax", "total")

# Item-level text fields
ITEM_TEXT_FIELDS = ("name", "unit")

# Item-level numeric fields
ITEM_NUMERIC_FIELDS = ("quantity", "unit_price", "total")


def _fuzzy_match(a: str, b: str) -> bool:
    """Return True if two strings are similar enough to be considered a match."""
    if a == b:
        return True
    if not a or not b:
        return False
    ratio = SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
    return ratio >= TEXT_MATCH_THRESHOLD


def _fuzzy_ratio(a: str, b: str) -> float:
    """Return the similarity ratio between two strings."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _numeric_match(a, b) -> bool:
    """Return True if two numeric values are exactly equal (or both None)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # Compare as floats with small epsilon for currency precision
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


def _best_match_items(items1: list, items2: list) -> list:
    """
    Match items between two scans by name similarity, falling back to position.

    Returns list of (item1, item2) tuples. Unmatched items paired with None.
    """
    if not items1 or not items2:
        paired = [(items1[i] if i < len(items1) else None,
                    items2[i] if i < len(items2) else None)
                   for i in range(max(len(items1), len(items2)))]
        return paired

    # Try name-based matching first
    used2 = set()
    pairs = []

    for item1 in items1:
        name1 = str(item1.get("name", ""))
        best_idx = -1
        best_ratio = 0.0

        for j, item2 in enumerate(items2):
            if j in used2:
                continue
            name2 = str(item2.get("name", ""))
            ratio = _fuzzy_ratio(name1, name2)
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = j

        if best_idx >= 0 and best_ratio >= TEXT_MATCH_THRESHOLD:
            pairs.append((item1, items2[best_idx]))
            used2.add(best_idx)
        else:
            pairs.append((item1, None))

    # Add unmatched items2
    for j, item2 in enumerate(items2):
        if j not in used2:
            pairs.append((None, item2))

    return pairs


def _compare_items(items1: list, items2: list) -> dict:
    """
    Compare two item arrays, matching by name similarity with position fallback.

    Returns:
        Dict with "agreed", "disagreed" item lists and per-item match info.
    """
    agreed_items = []
    disagreed_items = []

    pairs = _best_match_items(items1, items2)

    for i, (item1, item2) in enumerate(pairs):
        if item1 is None or item2 is None:
            disagreed_items.append({
                "index": i,
                "scan1": item1,
                "scan2": item2,
            })
            continue

        # Compare individual item fields
        item_agreed = {}
        item_disagreed = {}

        for field in ITEM_TEXT_FIELDS:
            val1 = str(item1.get(field, ""))
            val2 = str(item2.get(field, ""))
            if _fuzzy_match(val1, val2):
                item_agreed[field] = val1
            else:
                item_disagreed[field] = [val1, val2]

        for field in ITEM_NUMERIC_FIELDS:
            val1 = item1.get(field)
            val2 = item2.get(field)
            if _numeric_match(val1, val2):
                item_agreed[field] = val1
            else:
                item_disagreed[field] = [val1, val2]

        if item_disagreed:
            disagreed_items.append({
                "index": i,
                "agreed_fields": item_agreed,
                "disagreed_fields": item_disagreed,
                "scan1": item1,
                "scan2": item2,
            })
        else:
            agreed_items.append(item1)

    return {
        "agreed": agreed_items,
        "disagreed": disagreed_items,
    }


def compare_scans(scan1: dict, scan2: dict) -> dict:
    """
    Compare two scan results field by field.

    Args:
        scan1: Parsed JSON result from scan 1.
        scan2: Parsed JSON result from scan 2.

    Returns:
        Dict with keys:
        - "agreed": {field: value} for fields that match
        - "disagreed": {field: [val1, val2]} for fields that differ
        - "items_comparison": detailed item comparison
        - "agreement_ratio": float (0.0–1.0)
    """
    agreed = {}
    disagreed = {}

    # Compare top-level text fields
    for field in TEXT_FIELDS:
        val1 = str(scan1.get(field, ""))
        val2 = str(scan2.get(field, ""))
        if _fuzzy_match(val1, val2):
            agreed[field] = val1
        else:
            disagreed[field] = [val1, val2]

    # Compare top-level numeric fields
    for field in NUMERIC_FIELDS:
        val1 = scan1.get(field)
        val2 = scan2.get(field)
        if _numeric_match(val1, val2):
            agreed[field] = val1
        else:
            disagreed[field] = [val1, val2]

    # Compare items
    items1 = scan1.get("items", [])
    items2 = scan2.get("items", [])
    items_comparison = _compare_items(items1, items2)

    # Calculate agreement ratio
    total_fields = len(TEXT_FIELDS) + len(NUMERIC_FIELDS)
    agreed_count = len(agreed)

    # Count item agreement
    total_items = max(len(items1), len(items2))
    agreed_items = len(items_comparison["agreed"])
    if total_items > 0:
        total_fields += total_items
        agreed_count += agreed_items

    agreement_ratio = agreed_count / total_fields if total_fields > 0 else 1.0

    return {
        "agreed": agreed,
        "disagreed": disagreed,
        "items_comparison": items_comparison,
        "agreement_ratio": round(agreement_ratio, 4),
    }


def merge_results(
    scan1: dict, scan2: dict, tiebreaker: dict | None = None,
    comparison: dict | None = None,
) -> dict:
    """
    Merge two scan results, using agreed values and tiebreaker for disputes.

    When no tiebreaker is provided, scan1 values are used for disagreements.

    Args:
        scan1: Parsed JSON result from scan 1.
        scan2: Parsed JSON result from scan 2.
        tiebreaker: Optional parsed JSON from tiebreaker scan.
        comparison: Pre-computed comparison result. If None, computed internally.

    Returns:
        Merged invoice result dict.
    """
    if comparison is None:
        comparison = compare_scans(scan1, scan2)
    source = tiebreaker if tiebreaker is not None else scan1

    # Start with a copy of scan1 as the base
    merged = copy.deepcopy(scan1)

    # Apply agreed values
    for field, value in comparison["agreed"].items():
        merged[field] = value

    # Apply tiebreaker (or scan1 fallback) for disagreed fields
    for field in comparison["disagreed"]:
        merged[field] = source.get(field, scan1.get(field))

    # Handle items
    items_comp = comparison["items_comparison"]
    if items_comp["disagreed"]:
        # If there are item disagreements, use tiebreaker's items if available
        if tiebreaker is not None:
            merged["items"] = tiebreaker.get("items", scan1.get("items", []))
        # else keep scan1 items (already in merged)
    else:
        # All items agree — keep scan1's items (already in merged)
        pass

    # Use confidence and inference_sources from the most authoritative source
    if tiebreaker is not None:
        merged["confidence"] = tiebreaker.get(
            "confidence", scan1.get("confidence", {})
        )
        merged["inference_sources"] = tiebreaker.get(
            "inference_sources", scan1.get("inference_sources", {})
        )

    # Remove scan_metadata from merge result (engine adds its own)
    merged.pop("scan_metadata", None)

    return merged
