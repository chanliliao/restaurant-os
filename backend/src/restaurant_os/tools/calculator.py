"""
Math validation and confidence scoring wrapped as a LangGraph-compatible agent tool.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (preserved from validator.py)
# ---------------------------------------------------------------------------

TOLERANCE = 0.01
BOTTLE_DEPOSIT_PRICE = 0.05
_PACK_FORMAT_RE = re.compile(r"\((\d+)/(\d+)/\d+\s*ml\)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Pydantic input schema (LangGraph-compatible tool interface)
# ---------------------------------------------------------------------------


class CalculatorInput(BaseModel):
    """Input schema for the invoice math validation agent tool.

    The LLM populates this model when it decides to verify extracted invoice
    totals. Call `.model_json_schema()` to get the tool schema to send to GLM.
    """

    scan_result: dict = Field(
        description=(
            "Extracted invoice dict with keys: items (list of dicts with quantity, "
            "unit_price, total, name/description), subtotal, tax, total."
        )
    )
    auto_correct: bool = Field(
        default=True,
        description=(
            "If True, return an auto-corrected copy of scan_result alongside the "
            "validation errors. Corrections fix line totals, subtotal, and total "
            "via arithmetic; they do not modify source data."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers (preserved from validator.py)
# ---------------------------------------------------------------------------


def _approx_eq(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core validation logic (ported from validator.py)
# ---------------------------------------------------------------------------


def _validate_math(scan_result: dict) -> dict:
    """Validate the arithmetic consistency of a scan result.

    Checks:
        1. Each item: qty × unit_price ≈ line total
        2. Sum of item totals ≈ subtotal
        3. subtotal + tax ≈ total
        4. Bottle deposit quantities derived from pack format

    Returns:
        {"valid": bool, "errors": list[dict]}
    """
    errors: list[dict] = []
    items = scan_result.get("items") or []

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
            desc = item.get("description", item.get("name", f"item {i}"))
            errors.append({
                "field": f"item[{i}].total",
                "expected": expected,
                "actual": line_total,
                "description": (
                    f"Line total for '{desc}': "
                    f"{qty} × {unit_price} = {expected}, got {line_total}"
                ),
            })

    subtotal = _safe_float(scan_result.get("subtotal"))
    if subtotal is not None and all_item_totals_available and len(items) > 0:
        expected_subtotal = round(computed_item_sum, 2)
        if not _approx_eq(expected_subtotal, subtotal):
            errors.append({
                "field": "subtotal",
                "expected": expected_subtotal,
                "actual": subtotal,
                "description": (
                    f"Subtotal: sum of items = {expected_subtotal}, got {subtotal}"
                ),
            })

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
                    f"Total: {subtotal} + {tax} = {expected_total}, got {total}"
                ),
            })

    # Bottle deposit validation
    for i, item in enumerate(items):
        name = str(item.get("name", "")).lower()
        if "bottle deposit" not in name:
            continue

        beverage_item = None
        bottles_per_case = 0
        for j in range(i - 1, -1, -1):
            m = _PACK_FORMAT_RE.search(str(items[j].get("name", "")))
            if m:
                beverage_item = items[j]
                bottles_per_case = int(m.group(1)) * int(m.group(2))
                break

        if beverage_item is None:
            continue

        case_qty = _safe_float(beverage_item.get("quantity"))
        if case_qty is None:
            continue

        expected_bottles = int(case_qty) * bottles_per_case
        expected_deposit_total = round(expected_bottles * BOTTLE_DEPOSIT_PRICE, 2)
        deposit_qty = _safe_float(item.get("quantity"))
        deposit_total = _safe_float(item.get("total"))

        correction = {
            "index": i,
            "quantity": expected_bottles,
            "unit_price": BOTTLE_DEPOSIT_PRICE,
            "total": expected_deposit_total,
        }

        if deposit_qty is not None and not _approx_eq(deposit_qty, expected_bottles):
            errors.append({
                "field": f"item[{i}].quantity",
                "expected": expected_bottles,
                "actual": deposit_qty,
                "description": (
                    f"Bottle deposit qty: {int(case_qty)} cases × "
                    f"{bottles_per_case} bottles/case = {expected_bottles}, "
                    f"got {deposit_qty}"
                ),
                "_deposit_correction": correction,
            })
        elif deposit_total is not None and not _approx_eq(deposit_total, expected_deposit_total):
            errors.append({
                "field": f"item[{i}].total",
                "expected": expected_deposit_total,
                "actual": deposit_total,
                "description": (
                    f"Bottle deposit total: {expected_bottles} × "
                    f"${BOTTLE_DEPOSIT_PRICE} = ${expected_deposit_total}, "
                    f"got ${deposit_total}"
                ),
                "_deposit_correction": correction,
            })

    return {"valid": len(errors) == 0, "errors": errors}


def _auto_correct(scan_result: dict, errors: list[dict]) -> dict:
    """Apply arithmetic corrections to a deep copy of scan_result.

    Correction order: bottle deposits → line totals → subtotal → total.
    Does NOT mutate the original.
    """
    corrected = copy.deepcopy(scan_result)

    # Fill missing totals from items even when there are no errors
    items_for_fill = corrected.get("items") or []
    all_item_totals = [_safe_float(it.get("total")) for it in items_for_fill]
    if all(t is not None for t in all_item_totals) and all_item_totals:
        if _safe_float(corrected.get("subtotal")) is None:
            corrected["subtotal"] = round(sum(all_item_totals), 2)  # type: ignore[arg-type]
        if _safe_float(corrected.get("total")) is None:
            sub_val = _safe_float(corrected.get("subtotal"))
            tax_val = _safe_float(corrected.get("tax")) or 0.0
            if sub_val is not None:
                corrected["total"] = round(sub_val + tax_val, 2)

    if not errors:
        return corrected

    # Pass 0: bottle deposit corrections
    for error in errors:
        correction = error.get("_deposit_correction")
        if correction is None:
            continue
        idx = correction["index"]
        if idx < len(corrected.get("items", [])):
            corrected["items"][idx]["quantity"] = correction["quantity"]
            corrected["items"][idx]["unit_price"] = correction["unit_price"]
            corrected["items"][idx]["total"] = correction["total"]
            corrected["items"][idx]["unit"] = "bottle"

    # Pass 1: line total corrections
    for error in errors:
        if "_deposit_correction" in error:
            continue
        field = error["field"]
        if field.startswith("item[") and field.endswith("].total"):
            idx = int(field[5:field.index("]")])
            if idx < len(corrected.get("items", [])):
                corrected["items"][idx]["total"] = error["expected"]

    # Pass 2: recalculate subtotal from corrected items
    items = corrected.get("items") or []
    all_totals = [_safe_float(it.get("total")) for it in items]
    if all(t is not None for t in all_totals) and items:
        corrected["subtotal"] = round(sum(all_totals), 2)  # type: ignore[arg-type]

    # Pass 3: recalculate total from subtotal + tax
    sub = _safe_float(corrected.get("subtotal"))
    tax = _safe_float(corrected.get("tax"))
    if sub is not None and tax is not None:
        corrected["total"] = round(sub + tax, 2)

    return corrected


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def validate_invoice_math(inp: CalculatorInput) -> dict:
    """
    Validate and optionally correct invoice arithmetic as an agent tool.

    The LLM calls this tool after extracting invoice data to catch OCR errors
    in line totals, subtotals, and tax sums.

    Args:
        inp: Validated CalculatorInput from the LLM tool call.

    Returns:
        Dict with:
            - valid: bool — True when all arithmetic checks pass
            - errors: list of error dicts (field, expected, actual, description)
            - corrected_result: auto-corrected scan_result (only if inp.auto_correct)
    """
    validation = _validate_math(inp.scan_result)

    result: dict = {
        "valid": validation["valid"],
        "errors": validation["errors"],
    }

    if inp.auto_correct:
        result["corrected_result"] = _auto_correct(inp.scan_result, validation["errors"])

    logger.info(
        "validate_invoice_math — valid=%s errors=%d",
        validation["valid"],
        len(validation["errors"]),
    )
    return result
