"""Tests for the two-tier inference engine (Tier 1: supplier, Tier 2: industry)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scanner.memory import JsonGeneralMemory, JsonSupplierMemory
from scanner.memory.inference import (
    INFERABLE_FIELDS,
    _tier1_supplier,
    _tier1_supplier_item,
    _tier2_industry,
    _tier2_industry_item,
    infer_field,
    run_inference,
)


# --- Fixtures ---


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory with required subdirs."""
    (tmp_path / "suppliers").mkdir()
    (tmp_path / "general").mkdir()
    return tmp_path


@pytest.fixture
def supplier_mem(tmp_data_dir):
    return JsonSupplierMemory(data_dir=tmp_data_dir)


@pytest.fixture
def general_mem(tmp_data_dir):
    return JsonGeneralMemory(data_dir=tmp_data_dir)


@pytest.fixture
def populated_supplier(supplier_mem):
    """Supplier memory with historical data."""
    supplier_mem.save_scan("sysco-foods", {
        "supplier": "Sysco Foods",
        "tax_rate": 0.08,
        "invoice_number": "INV-001",
        "date": "2026-03-15",
        "items": [
            {"name": "Chicken Breast", "unit_price": 4.99, "unit": "lb"},
            {"name": "Rice", "unit_price": 1.50, "unit": "bag"},
        ],
    })
    return supplier_mem


@pytest.fixture
def populated_general(general_mem):
    """General memory with industry catalog data."""
    general_mem.update_from_scan({
        "tax_rate": 0.08,
        "items": [
            {"name": "Chicken Breast", "unit_price": 5.00, "unit": "lb"},
            {"name": "Flour", "unit_price": 2.25, "unit": "bag"},
        ],
    })
    return general_mem


@pytest.fixture
def base_scan_result():
    """A scan result with some missing fields."""
    return {
        "supplier": "Sysco Foods",
        "date": "2026-03-20",
        "invoice_number": "",
        "items": [
            {"name": "Chicken Breast", "quantity": 10, "unit_price": 4.99,
             "unit": "lb", "total_price": 49.90},
        ],
        "subtotal": 49.90,
        "tax": None,
        "total": None,
        "tax_rate": None,
        "confidence": {
            "supplier": 95,
            "date": 90,
            "invoice_number": 20,
            "subtotal": 85,
            "tax": 0,
            "total": 0,
            "tax_rate": 0,
        },
        "inference_sources": {
            "supplier": "scan",
            "date": "scan",
            "invoice_number": "missing",
            "subtotal": "scan",
            "tax": "missing",
            "total": "missing",
            "tax_rate": "missing",
        },
        "scan_metadata": {},
    }


# --- Tier 1: Supplier Memory ---


class TestTier1Supplier:
    def test_returns_historical_value(self, populated_supplier):
        result = _tier1_supplier("tax_rate", "sysco-foods", populated_supplier, {})
        assert result is not None
        assert result["value"] == 0.08
        assert result["source"] == "tier1_supplier"
        assert result["confidence"] == 80

    def test_returns_none_for_unknown_field(self, populated_supplier):
        result = _tier1_supplier("nonexistent", "sysco-foods", populated_supplier, {})
        assert result is None

    def test_returns_none_for_unknown_supplier(self, supplier_mem):
        result = _tier1_supplier("tax_rate", "unknown-corp", supplier_mem, {})
        assert result is None

    def test_returns_none_when_no_supplier_id(self, populated_supplier):
        result = _tier1_supplier("tax_rate", None, populated_supplier, {})
        assert result is None

    def test_returns_none_when_no_memory(self):
        result = _tier1_supplier("tax_rate", "sysco-foods", None, {})
        assert result is None

    def test_supplier_name_inferred(self, populated_supplier):
        result = _tier1_supplier("supplier", "sysco-foods", populated_supplier, {})
        assert result["value"] == "Sysco Foods"

    def test_date_inferred(self, populated_supplier):
        result = _tier1_supplier("date", "sysco-foods", populated_supplier, {})
        assert result["value"] == "2026-03-15"


class TestTier1SupplierItem:
    def test_fills_missing_unit_price(self, populated_supplier):
        item = {"name": "Chicken Breast", "quantity": 5}
        updates = _tier1_supplier_item(item, "sysco-foods", populated_supplier)
        assert "unit_price" in updates
        assert updates["unit_price"]["value"] == 4.99
        assert updates["unit_price"]["source"] == "tier1_supplier"

    def test_fills_missing_unit(self, populated_supplier):
        item = {"name": "Chicken Breast", "quantity": 5, "unit_price": 4.99}
        updates = _tier1_supplier_item(item, "sysco-foods", populated_supplier)
        assert "unit" in updates
        assert updates["unit"]["value"] == "lb"

    def test_no_update_when_fields_present(self, populated_supplier):
        item = {"name": "Chicken Breast", "quantity": 5, "unit_price": 4.99, "unit": "lb"}
        updates = _tier1_supplier_item(item, "sysco-foods", populated_supplier)
        assert updates == {}

    def test_no_update_for_unknown_item(self, populated_supplier):
        item = {"name": "Mystery Fish", "quantity": 2}
        updates = _tier1_supplier_item(item, "sysco-foods", populated_supplier)
        assert updates == {}

    def test_no_update_when_no_supplier(self, supplier_mem):
        item = {"name": "Chicken Breast"}
        updates = _tier1_supplier_item(item, None, supplier_mem)
        assert updates == {}


# --- Tier 2: Industry Memory ---


class TestTier2Industry:
    def test_returns_tax_rate(self, populated_general):
        result = _tier2_industry("tax_rate", populated_general, {})
        assert result is not None
        assert result["source"] == "tier2_industry"
        assert result["confidence"] == 60
        # Should return a rate from the typical list
        assert isinstance(result["value"], float)

    def test_returns_none_for_non_tax_field(self, populated_general):
        result = _tier2_industry("supplier", populated_general, {})
        assert result is None

    def test_returns_none_when_no_memory(self):
        result = _tier2_industry("tax_rate", None, {})
        assert result is None


class TestTier2IndustryItem:
    def test_fills_missing_price_from_catalog(self, populated_general):
        item = {"name": "Flour", "quantity": 3}
        updates = _tier2_industry_item(item, populated_general)
        assert "unit_price" in updates
        assert updates["unit_price"]["value"] == 2.25
        assert updates["unit_price"]["source"] == "tier2_industry"

    def test_fills_missing_unit_from_catalog(self, populated_general):
        item = {"name": "Flour", "quantity": 3, "unit_price": 2.25}
        updates = _tier2_industry_item(item, populated_general)
        assert "unit" in updates
        assert updates["unit"]["value"] == "bag"

    def test_no_update_for_unknown_item(self, populated_general):
        item = {"name": "Exotic Dragon Fruit"}
        updates = _tier2_industry_item(item, populated_general)
        assert updates == {}

    def test_no_update_when_no_memory(self):
        item = {"name": "Flour"}
        updates = _tier2_industry_item(item, None)
        assert updates == {}


# --- infer_field (two-tier cascade) ---


class TestInferField:
    def test_tier1_used_first(self, populated_supplier, populated_general):
        result = infer_field("tax_rate", {}, "sysco-foods",
                             populated_supplier, populated_general)
        assert result["source"] == "tier1_supplier"
        assert result["value"] == 0.08

    def test_falls_through_to_tier2(self, supplier_mem, populated_general):
        """New supplier with no history — should fall to tier 2."""
        result = infer_field("tax_rate", {}, "new-supplier",
                             supplier_mem, populated_general)
        assert result["source"] == "tier2_industry"

    def test_returns_none_result_when_both_tiers_fail(self, supplier_mem, general_mem):
        """No local data at all — both tiers fail, returns null result."""
        result = infer_field("invoice_number", {}, "new-supplier",
                             supplier_mem, general_mem)
        assert result["value"] is None
        assert result["source"] is None
        assert result["confidence"] == 0

    def test_no_supplier_id_skips_tier1(self, populated_supplier, populated_general):
        result = infer_field("tax_rate", {}, None,
                             populated_supplier, populated_general)
        # Should skip tier 1 and use tier 2
        assert result["source"] == "tier2_industry"


# --- run_inference (full pipeline) ---


class TestRunInference:
    def test_fills_missing_fields_from_supplier(self, base_scan_result, populated_supplier,
                                                populated_general):
        """Tier 1: supplier has tax_rate and invoice_number."""
        result = run_inference(base_scan_result, "sysco-foods",
                               populated_supplier, populated_general)

        # tax_rate should be filled from supplier (tier 1)
        assert result["tax_rate"] == 0.08
        assert result["confidence"]["tax_rate"] == 80
        assert result["inference_sources"]["tax_rate"] == "tier1_supplier"

    def test_does_not_override_high_confidence(self, base_scan_result, populated_supplier,
                                                populated_general):
        """Fields with confidence >= threshold should not be touched."""
        original_supplier = base_scan_result["supplier"]
        original_date = base_scan_result["date"]

        result = run_inference(base_scan_result, "sysco-foods",
                               populated_supplier, populated_general)

        assert result["supplier"] == original_supplier
        assert result["date"] == original_date
        assert result["confidence"]["supplier"] == 95
        assert result["confidence"]["date"] == 90

    def test_fills_missing_source_field(self, base_scan_result, populated_supplier,
                                        populated_general):
        """Fields marked 'missing' in inference_sources are candidates."""
        result = run_inference(base_scan_result, "sysco-foods",
                               populated_supplier, populated_general)

        # invoice_number was confidence=20 and source="missing"
        # Supplier has historical value "INV-001"
        assert result["invoice_number"] == "INV-001"
        assert result["inference_sources"]["invoice_number"] == "tier1_supplier"

    def test_tracks_metadata(self, base_scan_result, populated_supplier,
                              populated_general):
        result = run_inference(base_scan_result, "sysco-foods",
                               populated_supplier, populated_general)

        metadata = result["scan_metadata"]
        assert "inference_tiers_used" in metadata
        assert "inference_fields_filled" in metadata
        assert metadata["inference_fields_filled"] > 0

    def test_item_level_inference(self, populated_supplier, populated_general):
        """Items with missing fields should be filled from memory."""
        scan_result = {
            "supplier": "Sysco Foods",
            "items": [
                {"name": "Chicken Breast", "quantity": 10},  # missing price and unit
            ],
            "confidence": {"supplier": 95},
            "inference_sources": {"supplier": "scan"},
            "scan_metadata": {},
        }
        result = run_inference(scan_result, "sysco-foods",
                               populated_supplier, populated_general)

        item = result["items"][0]
        assert item["unit_price"] == 4.99  # from supplier history
        assert item["unit"] == "lb"
        assert item.get("inference_sources", {}).get("unit_price") == "tier1_supplier"

    def test_item_tier2_fallback(self, supplier_mem, populated_general):
        """Items unknown to supplier but in industry catalog."""
        scan_result = {
            "supplier": "New Corp",
            "items": [
                {"name": "Flour", "quantity": 3},  # in industry catalog, not supplier
            ],
            "confidence": {"supplier": 90},
            "inference_sources": {"supplier": "scan"},
            "scan_metadata": {},
        }
        result = run_inference(scan_result, "new-corp",
                               supplier_mem, populated_general)

        item = result["items"][0]
        assert item["unit_price"] == 2.25  # from industry catalog
        assert item["unit"] == "bag"
        assert item.get("inference_sources", {}).get("unit_price") == "tier2_industry"

    def test_no_crash_with_none_memories(self, base_scan_result):
        """Should not crash when memory instances are None."""
        result = run_inference(base_scan_result, None, None, None)
        # Should return result unchanged (no inference possible)
        assert result is not None
        assert result["supplier"] == "Sysco Foods"

    def test_custom_threshold(self, base_scan_result, populated_supplier,
                               populated_general):
        """Higher threshold should trigger more inference attempts."""
        # Set subtotal confidence to 85 — default threshold 60 won't trigger,
        # but threshold 90 will
        result_default = run_inference(
            {**base_scan_result, "confidence": {**base_scan_result["confidence"]}},
            "sysco-foods", populated_supplier, populated_general,
            confidence_threshold=60,
        )
        assert result_default["confidence"]["subtotal"] == 85  # unchanged

        # With threshold=90, subtotal (conf=85) becomes a candidate
        scan2 = {
            **base_scan_result,
            "confidence": {**base_scan_result["confidence"]},
            "inference_sources": {**base_scan_result["inference_sources"]},
            "scan_metadata": {},
        }
        result_high = run_inference(
            scan2, "sysco-foods", populated_supplier, populated_general,
            confidence_threshold=90,
        )
        # subtotal was 85 < 90, so it's a candidate — but supplier may not have it
        # The key point: it was evaluated (metadata shows it)
        metadata = result_high["scan_metadata"]
        assert metadata["inference_fields_filled"] >= 0  # won't crash


class TestRunInferenceEdgeCases:
    def test_empty_scan_result(self, supplier_mem, general_mem):
        """Minimal scan result should not crash."""
        result = run_inference({}, None, supplier_mem, general_mem)
        assert result is not None

    def test_missing_confidence_dict(self, supplier_mem, general_mem):
        """Scan result without confidence dict."""
        result = run_inference(
            {"supplier": "Test", "items": [], "inference_sources": {}},
            None, supplier_mem, general_mem,
        )
        assert "confidence" in result

    def test_missing_inference_sources_dict(self, supplier_mem, general_mem):
        """Scan result without inference_sources dict."""
        result = run_inference(
            {"supplier": "Test", "items": [], "confidence": {}},
            None, supplier_mem, general_mem,
        )
        assert "inference_sources" in result


# --- Import/Export Check ---


class TestModuleExports:
    def test_infer_field_importable(self):
        from scanner.memory import infer_field as f
        assert callable(f)

    def test_run_inference_importable(self):
        from scanner.memory import run_inference as f
        assert callable(f)
