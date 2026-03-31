"""
Mathematical cross-validation for scanned invoice data.

Catches arithmetic errors that all scan passes agree on — errors that
consensus-based merging cannot detect.
"""

import copy
import re
from typing import Any

TOLERANCE = 0.01

# Default bottle deposit price per bottle
BOTTLE_DEPOSIT_PRICE = 0.05

# Pattern to extract pack format from item names: "X/Y/Zml"
_PACK_FORMAT_RE = re.compile(r"\((\d+)/(\d+)/\d+\s*ml\)", re.IGNORECASE)


def _approx_eq(a: float, b: float) -> bool:
    """Return True if a and b are within TOLERANCE of each other."""
    return abs(a - b) <= TOLERANCE


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None if not possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_math(scan_result: dict) -> dict:
    """
    Validate the arithmetic consistency of a scan result.

    Checks:
        1. Each item: qty * unit_price ≈ line total
        2. Sum of item totals ≈ subtotal
        3. subtotal + tax ≈ total

    Skips any check where required values are None/missing.

    Args:
        scan_result: Dict with items, subtotal, tax, total fields.

    Returns:
        {"valid": bool, "errors": [{"field": str, "expected": float,
         "actual": float, "description": str}, ...]}
    """
    errors: list[dict] = []
    items = scan_result.get("items") or []

    # --- Check 1: Line totals ---
    computed_item_sum = 0.0
    all_item_totals_available = True

    for i, item in enumerate(items):
        qty = _safe_float(item.get("quantity"))
        unit_price = _safe_float(item.get("unit_price"))
        line_total = _safe_float(item.get("total"))

        if line_total is not None:
            computed_item_sum += line_total
        else:
            all_item_totals_available = False

        if qty is None or unit_price is None or line_total is None:
            continue

        expected = round(qty * unit_price, 2)
        if not _approx_eq(expected, line_total):
            desc = item.get("description", f"item {i}")
            errors.append({
                "field": f"item[{i}].total",
                "expected": expected,
                "actual": line_total,
                "description": (
                    f"Line total for '{desc}': "
                    f"{qty} x {unit_price} = {expected}, got {line_total}"
                ),
            })

    # --- Check 2: Subtotal ---
    subtotal = _safe_float(scan_result.get("subtotal"))

    if subtotal is not None and all_item_totals_available and len(items) > 0:
        expected_subtotal = round(computed_item_sum, 2)
        if not _approx_eq(expected_subtotal, subtotal):
            errors.append({
                "field": "subtotal",
                "expected": expected_subtotal,
                "actual": subtotal,
                "description": (
                    f"Subtotal: sum of items = {expected_subtotal}, "
                    f"got {subtotal}"
                ),
            })

    # --- Check 3: Total ---
    tax = _safe_float(scan_result.get("tax"))
    total = _safe_float(scan_result.get("total"))

    if subtotal is not None and tax is not None and total is not None:
        expected_total = round(subtotal + tax, 2)
        if not _approx_eq(expected_total, total):
            errors.append({
                "field": "total",
                "expected": expected_total,
                "actual": total,
                "description": (
                    f"Total: {subtotal} + {tax} = {expected_total}, "
                    f"got {total}"
                ),
            })

    # --- Check 4: Bottle deposit quantities ---
    # For beverage invoices, validate that bottle deposit qty matches
    # the number of bottles derived from the preceding case item.
    for i, item in enumerate(items):
        name = str(item.get("name", "")).lower()
        if "bottle deposit" not in name:
            continue

        # Look backwards for the nearest beverage case item
        beverage_item = None
        for j in range(i - 1, -1, -1):
            prev_name = str(items[j].get("name", ""))
            m = _PACK_FORMAT_RE.search(prev_name)
            if m:
                beverage_item = items[j]
                packs = int(m.group(1))
                units_per_pack = int(m.group(2))
                bottles_per_case = packs * units_per_pack
                break

        if beverage_item is None:
            continue

        case_qty = _safe_float(beverage_item.get("quantity"))
        deposit_qty = _safe_float(item.get("quantity"))
        deposit_price = _safe_float(item.get("unit_price"))
        deposit_total = _safe_float(item.get("total"))

        if case_qty is None:
            continue

        expected_bottles = int(case_qty) * bottles_per_case
        expected_total = round(expected_bottles * BOTTLE_DEPOSIT_PRICE, 2)

        if deposit_qty is not None and not _approx_eq(deposit_qty, expected_bottles):
            errors.append({
                "field": f"item[{i}].quantity",
                "expected": expected_bottles,
                "actual": deposit_qty,
                "description": (
                    f"Bottle deposit qty: {int(case_qty)} cases x "
                    f"{bottles_per_case} bottles/case = {expected_bottles}, "
                    f"got {deposit_qty}"
                ),
                "_deposit_correction": {
                    "index": i,
                    "quantity": expected_bottles,
                    "unit_price": BOTTLE_DEPOSIT_PRICE,
                    "total": expected_total,
                },
            })
        elif deposit_total is not None and not _approx_eq(deposit_total, expected_total):
            errors.append({
                "field": f"item[{i}].total",
                "expected": expected_total,
                "actual": deposit_total,
                "description": (
                    f"Bottle deposit total: {expected_bottles} x "
                    f"${BOTTLE_DEPOSIT_PRICE} = ${expected_total}, "
                    f"got ${deposit_total}"
                ),
                "_deposit_correction": {
                    "index": i,
                    "quantity": expected_bottles,
                    "unit_price": BOTTLE_DEPOSIT_PRICE,
                    "total": expected_total,
                },
            })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def auto_correct(scan_result: dict, errors: list[dict]) -> dict:
    """
    Apply straightforward arithmetic corrections to a scan result.

    Corrections are applied in order: line totals first, then subtotal,
    then total — so that cascading fixes work correctly.

    Does NOT mutate the original scan_result.

    Args:
        scan_result: The scan result dict to correct.
        errors: The list of errors from validate_math().

    Returns:
        A corrected deep copy of scan_result.
    """
    corrected = copy.deepcopy(scan_result)

    if not errors:
        return corrected

    # Pass 0: Fix bottle deposit items (qty, unit_price, total together)
    for error in errors:
        correction = error.get("_deposit_correction")
        if correction is None:
            continue
        idx = correction["index"]
        if idx < len(corrected["items"]):
            corrected["items"][idx]["quantity"] = correction["quantity"]
            corrected["items"][idx]["unit_price"] = correction["unit_price"]
            corrected["items"][idx]["total"] = correction["total"]
            corrected["items"][idx]["unit"] = "bottle"

    # Pass 1: Fix line totals
    for error in errors:
        field = error["field"]
        if "_deposit_correction" in error:
            continue  # Already handled in Pass 0
        if field.startswith("item[") and field.endswith("].total"):
            # Extract index
            idx_str = field[5:field.index("]")]
            idx = int(idx_str)
            if idx < len(corrected["items"]):
                corrected["items"][idx]["total"] = error["expected"]

    # Pass 2: Recalculate subtotal from (now-corrected) items
    items = corrected.get("items") or []
    all_totals = [_safe_float(it.get("total")) for it in items]
    if all(t is not None for t in all_totals) and len(items) > 0:
        corrected["subtotal"] = round(sum(all_totals), 2)

    # Pass 3: Recalculate total from subtotal + tax
    sub = _safe_float(corrected.get("subtotal"))
    tax = _safe_float(corrected.get("tax"))
    if sub is not None and tax is not None:
        corrected["total"] = round(sub + tax, 2)

    return corrected
