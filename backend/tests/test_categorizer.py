"""Tests for error categorization."""

import pytest

from scanner.memory.categorizer import categorize_error, categorize_corrections


class TestCategorizeError:
    """Unit tests for single-error categorization."""

    def test_misread_both_non_empty(self):
        assert categorize_error("supplier", "Sysco Fods", "Sysco Foods") == "misread"

    def test_misread_numeric(self):
        assert categorize_error("total", 100.0, 110.0) == "misread"

    def test_missing_original_none(self):
        assert categorize_error("date", None, "2026-01-01") == "missing"

    def test_missing_original_empty_string(self):
        assert categorize_error("supplier", "", "Sysco Foods") == "missing"

    def test_missing_original_zero(self):
        assert categorize_error("total", 0, 110.0) == "missing"

    def test_hallucinated_corrected_none(self):
        assert categorize_error("tax", 5.00, None) == "hallucinated"

    def test_hallucinated_corrected_empty(self):
        assert categorize_error("supplier", "Ghost Corp", "") == "hallucinated"

    def test_hallucinated_deleted_row(self):
        assert categorize_error("items[2]", {"name": "Phantom"}, "deleted_row") == "hallucinated"

    def test_missing_original_empty_list(self):
        assert categorize_error("items", [], [{"name": "Real Item"}]) == "missing"

    def test_both_zero_is_missing(self):
        # 0 -> 0: original is empty (zero=absent), corrected 0 is not a deletion
        assert categorize_error("qty", 0, 0) == "missing"

    def test_corrected_to_zero_is_misread_not_hallucinated(self):
        # Correcting $5 to $0 (complimentary item) should be "misread" not "hallucinated"
        assert categorize_error("unit_price", 5.00, 0) == "misread"

    def test_corrected_to_zero_int_is_misread(self):
        assert categorize_error("quantity", 3, 0) == "misread"


class TestCategorizeCorrections:
    """Tests for batch categorization."""

    def test_adds_error_type_to_each(self):
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
            {"field": "date", "original_value": None, "corrected_value": "2026-01-01"},
            {"field": "items[2]", "original_value": {"name": "Ghost"}, "corrected_value": "deleted_row"},
        ]
        result = categorize_corrections(corrections)
        assert len(result) == 3
        assert result[0]["error_type"] == "misread"
        assert result[1]["error_type"] == "missing"
        assert result[2]["error_type"] == "hallucinated"

    def test_empty_corrections_returns_empty(self):
        assert categorize_corrections([]) == []

    def test_does_not_mutate_input(self):
        corrections = [
            {"field": "supplier", "original_value": "A", "corrected_value": "B"},
        ]
        result = categorize_corrections(corrections)
        assert "error_type" not in corrections[0]
        assert "error_type" in result[0]
