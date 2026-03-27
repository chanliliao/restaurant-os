"""Tests for mathematical cross-validation (Phase 10)."""

import copy
import pytest

from scanner.scanning.validator import validate_math, auto_correct


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(description="Widget", qty=2, unit_price=5.00, total=10.00):
    return {
        "description": description,
        "quantity": qty,
        "unit_price": unit_price,
        "total": total,
    }


def _make_result(items=None, subtotal=20.00, tax=1.60, total=21.60):
    if items is None:
        items = [
            _make_item("Widget A", 2, 5.00, 10.00),
            _make_item("Widget B", 1, 10.00, 10.00),
        ]
    return {
        "supplier": "Test Supplier",
        "date": "2026-01-15",
        "invoice_number": "INV-001",
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "confidence": {},
        "inference_sources": {},
    }


# ---------------------------------------------------------------------------
# validate_math tests
# ---------------------------------------------------------------------------

class TestValidateMath:
    """Tests for validate_math()."""

    def test_correct_math_returns_valid(self):
        result = _make_result()
        validation = validate_math(result)
        assert validation["valid"] is True
        assert validation["errors"] == []

    def test_wrong_line_total_detected(self):
        items = [
            _make_item("Widget A", 2, 5.00, 99.99),  # should be 10.00
            _make_item("Widget B", 1, 10.00, 10.00),
        ]
        result = _make_result(items=items, subtotal=109.99, total=111.59)
        validation = validate_math(result)
        assert validation["valid"] is False
        line_errors = [e for e in validation["errors"] if "item" in e["field"].lower()]
        assert len(line_errors) >= 1
        err = line_errors[0]
        assert err["expected"] == 10.00
        assert err["actual"] == 99.99

    def test_wrong_subtotal_detected(self):
        result = _make_result(subtotal=999.99)
        validation = validate_math(result)
        assert validation["valid"] is False
        sub_errors = [e for e in validation["errors"] if "subtotal" in e["field"]]
        assert len(sub_errors) == 1
        assert sub_errors[0]["expected"] == 20.00
        assert sub_errors[0]["actual"] == 999.99

    def test_wrong_total_detected(self):
        result = _make_result(total=999.99)
        validation = validate_math(result)
        assert validation["valid"] is False
        total_errors = [e for e in validation["errors"] if e["field"] == "total"]
        assert len(total_errors) == 1
        assert total_errors[0]["expected"] == 21.60
        assert total_errors[0]["actual"] == 999.99

    def test_missing_subtotal_skips_check(self):
        result = _make_result(subtotal=None)
        validation = validate_math(result)
        # Should not crash; subtotal check skipped, but total check also
        # skipped because subtotal is None
        assert isinstance(validation["valid"], bool)
        assert isinstance(validation["errors"], list)

    def test_missing_tax_skips_total_check(self):
        result = _make_result(tax=None)
        validation = validate_math(result)
        assert isinstance(validation["valid"], bool)

    def test_missing_total_skips_check(self):
        result = _make_result(total=None)
        validation = validate_math(result)
        assert isinstance(validation["valid"], bool)

    def test_item_missing_quantity_skips_line_check(self):
        items = [
            {"description": "Widget", "quantity": None, "unit_price": 5.00, "total": 10.00},
        ]
        result = _make_result(items=items, subtotal=10.00, tax=0.80, total=10.80)
        validation = validate_math(result)
        # Line check skipped, no error for that item
        line_errors = [e for e in validation["errors"] if "item" in e["field"].lower()]
        assert len(line_errors) == 0

    def test_item_missing_unit_price_skips_line_check(self):
        items = [
            {"description": "Widget", "quantity": 2, "unit_price": None, "total": 10.00},
        ]
        result = _make_result(items=items, subtotal=10.00, tax=0.80, total=10.80)
        validation = validate_math(result)
        line_errors = [e for e in validation["errors"] if "item" in e["field"].lower()]
        assert len(line_errors) == 0

    def test_item_missing_total_skips_line_check(self):
        items = [
            {"description": "Widget", "quantity": 2, "unit_price": 5.00, "total": None},
        ]
        result = _make_result(items=items, subtotal=None, tax=0.80, total=None)
        validation = validate_math(result)
        line_errors = [e for e in validation["errors"] if "item" in e["field"].lower()]
        assert len(line_errors) == 0

    def test_empty_items_list(self):
        result = _make_result(items=[], subtotal=0.0, tax=0.0, total=0.0)
        validation = validate_math(result)
        assert validation["valid"] is True

    def test_multiple_errors_all_detected(self):
        items = [
            _make_item("A", 2, 5.00, 99.00),  # wrong line total
            _make_item("B", 3, 4.00, 88.00),  # wrong line total
        ]
        result = _make_result(items=items, subtotal=50.00, tax=2.00, total=100.00)
        validation = validate_math(result)
        assert validation["valid"] is False
        assert len(validation["errors"]) >= 2  # at least the two line errors

    def test_tolerance_within_one_cent(self):
        """Values within 0.01 should pass."""
        items = [
            _make_item("Widget", 3, 3.33, 9.99),  # 3 * 3.33 = 9.99 exactly
        ]
        result = _make_result(items=items, subtotal=9.99, tax=0.80, total=10.79)
        validation = validate_math(result)
        assert validation["valid"] is True

    def test_tolerance_just_over(self):
        """Values off by more than 0.01 should fail."""
        items = [
            _make_item("Widget", 3, 3.33, 10.01),  # expected 9.99
        ]
        result = _make_result(items=items, subtotal=10.01, tax=0.80, total=10.81)
        validation = validate_math(result)
        line_errors = [e for e in validation["errors"] if "item" in e["field"].lower()]
        assert len(line_errors) == 1


# ---------------------------------------------------------------------------
# auto_correct tests
# ---------------------------------------------------------------------------

class TestAutoCorrect:
    """Tests for auto_correct()."""

    def test_corrects_wrong_line_total(self):
        items = [
            _make_item("Widget", 2, 5.00, 99.99),
        ]
        result = _make_result(items=items, subtotal=99.99, tax=1.60, total=101.59)
        validation = validate_math(result)
        corrected = auto_correct(result, validation["errors"])
        assert corrected["items"][0]["total"] == 10.00

    def test_corrects_wrong_subtotal(self):
        result = _make_result(subtotal=999.99)
        validation = validate_math(result)
        corrected = auto_correct(result, validation["errors"])
        assert corrected["subtotal"] == 20.00

    def test_corrects_wrong_total(self):
        result = _make_result(total=999.99)
        validation = validate_math(result)
        corrected = auto_correct(result, validation["errors"])
        assert corrected["total"] == 21.60

    def test_does_not_mutate_original(self):
        result = _make_result(subtotal=999.99)
        original = copy.deepcopy(result)
        validation = validate_math(result)
        auto_correct(result, validation["errors"])
        assert result == original

    def test_no_errors_returns_unchanged_copy(self):
        result = _make_result()
        validation = validate_math(result)
        corrected = auto_correct(result, validation["errors"])
        assert corrected["subtotal"] == result["subtotal"]
        assert corrected["total"] == result["total"]

    def test_cascading_correction(self):
        """Wrong line total should cascade to subtotal and total corrections."""
        items = [
            _make_item("A", 2, 5.00, 99.00),  # wrong: should be 10.00
            _make_item("B", 1, 10.00, 10.00),
        ]
        # subtotal and total are consistent with the wrong line total
        result = _make_result(items=items, subtotal=109.00, tax=1.60, total=110.60)
        validation = validate_math(result)
        corrected = auto_correct(result, validation["errors"])
        assert corrected["items"][0]["total"] == 10.00
        assert corrected["subtotal"] == 20.00
        assert corrected["total"] == 21.60
