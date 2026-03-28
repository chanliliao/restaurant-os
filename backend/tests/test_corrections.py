"""Tests for applying corrections to scan data."""

import copy

import pytest

from scanner.memory.corrections import apply_corrections


class TestApplyCorrectionsHeader:
    """Test applying corrections to top-level scan fields."""

    def test_correct_header_field(self):
        scan = {"supplier": "Sysco Fods", "date": "2026-01-01", "items": []}
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["supplier"] == "Sysco Foods"

    def test_correct_multiple_header_fields(self):
        scan = {"supplier": "Bad", "date": "wrong", "total": 0, "items": []}
        corrections = [
            {"field": "supplier", "original_value": "Bad", "corrected_value": "Good"},
            {"field": "date", "original_value": "wrong", "corrected_value": "2026-01-01"},
            {"field": "total", "original_value": 0, "corrected_value": 110.0},
        ]
        result = apply_corrections(scan, corrections)
        assert result["supplier"] == "Good"
        assert result["date"] == "2026-01-01"
        assert result["total"] == 110.0

    def test_no_corrections_returns_copy(self):
        scan = {"supplier": "Sysco", "items": []}
        result = apply_corrections(scan, [])
        assert result == scan
        assert result is not scan

    def test_does_not_mutate_original(self):
        scan = {"supplier": "Old", "items": []}
        original = copy.deepcopy(scan)
        corrections = [
            {"field": "supplier", "original_value": "Old", "corrected_value": "New"},
        ]
        apply_corrections(scan, corrections)
        assert scan == original


class TestApplyCorrectionsItems:
    """Test applying corrections to line items."""

    def test_correct_item_field(self):
        scan = {
            "supplier": "Sysco",
            "items": [
                {"name": "Chicken", "unit_price": 4.00, "unit": "lb"},
            ],
        }
        corrections = [
            {"field": "items[0].unit_price", "original_value": 4.00, "corrected_value": 4.99},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][0]["unit_price"] == 4.99

    def test_correct_item_name(self):
        scan = {
            "items": [
                {"name": "Chiken Brest", "unit_price": 4.99},
            ],
        }
        corrections = [
            {"field": "items[0].name", "original_value": "Chiken Brest", "corrected_value": "Chicken Breast"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][0]["name"] == "Chicken Breast"

    def test_correct_second_item(self):
        scan = {
            "items": [
                {"name": "Chicken", "unit_price": 4.99},
                {"name": "Rice", "unit_price": 1.00},
            ],
        }
        corrections = [
            {"field": "items[1].unit_price", "original_value": 1.00, "corrected_value": 1.50},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][1]["unit_price"] == 1.50
        assert result["items"][0]["unit_price"] == 4.99


class TestApplyCorrectionsDeleteRow:
    """Test deleting hallucinated rows."""

    def test_delete_row(self):
        scan = {
            "items": [
                {"name": "Real Item", "unit_price": 5.00},
                {"name": "Ghost Item", "unit_price": 99.00},
            ],
        }
        corrections = [
            {"field": "items[1]", "original_value": {"name": "Ghost Item"}, "corrected_value": "deleted_row"},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Real Item"

    def test_delete_multiple_rows_highest_index_first(self):
        scan = {
            "items": [
                {"name": "Keep"},
                {"name": "Delete1"},
                {"name": "Also Keep"},
                {"name": "Delete2"},
            ],
        }
        corrections = [
            {"field": "items[1]", "original_value": {"name": "Delete1"}, "corrected_value": "deleted_row"},
            {"field": "items[3]", "original_value": {"name": "Delete2"}, "corrected_value": "deleted_row"},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "Keep"
        assert result["items"][1]["name"] == "Also Keep"


class TestApplyCorrectionsEdgeCases:
    """Edge cases."""

    def test_out_of_range_index_is_skipped(self):
        scan = {"items": [{"name": "Only"}]}
        corrections = [
            {"field": "items[5].unit_price", "original_value": 0, "corrected_value": 10},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 1

    def test_unknown_header_field_added(self):
        scan = {"supplier": "Sysco", "items": []}
        corrections = [
            {"field": "notes", "original_value": None, "corrected_value": "Rush order"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["notes"] == "Rush order"
