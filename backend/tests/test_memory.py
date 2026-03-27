"""Tests for SmartScanner memory interfaces and JSON storage."""

import json
import tempfile
from pathlib import Path

import pytest

from scanner.memory import (
    JsonGeneralMemory,
    JsonSupplierMemory,
    normalize_supplier_id,
)


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory with required subdirs."""
    (tmp_path / "suppliers").mkdir()
    (tmp_path / "general").mkdir()
    (tmp_path / "stats").mkdir()
    return tmp_path


@pytest.fixture
def supplier_mem(tmp_data_dir):
    return JsonSupplierMemory(data_dir=tmp_data_dir)


@pytest.fixture
def general_mem(tmp_data_dir):
    return JsonGeneralMemory(data_dir=tmp_data_dir)


# --- Supplier ID Normalization ---


class TestNormalizeSupplierID:
    def test_basic_normalization(self):
        assert normalize_supplier_id("Sysco Foods") == "sysco-foods"

    def test_special_chars_stripped(self):
        assert normalize_supplier_id("US Foods, Inc.") == "us-foods-inc"

    def test_uppercase(self):
        assert normalize_supplier_id("ACME") == "acme"

    def test_multiple_spaces(self):
        assert normalize_supplier_id("Big  Apple  Produce") == "big-apple-produce"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            normalize_supplier_id("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            normalize_supplier_id("   ")

    def test_all_special_chars_raises(self):
        with pytest.raises(ValueError, match="normalizes to empty"):
            normalize_supplier_id("@#$%")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="Invalid supplier name"):
            normalize_supplier_id("../etc/passwd")

    def test_backslash_rejected(self):
        with pytest.raises(ValueError, match="Invalid supplier name"):
            normalize_supplier_id("foo\\bar")

    def test_forward_slash_rejected(self):
        with pytest.raises(ValueError, match="Invalid supplier name"):
            normalize_supplier_id("foo/bar")


# --- Supplier Memory CRUD ---


class TestJsonSupplierMemoryProfile:
    def test_get_profile_nonexistent_returns_default(self, supplier_mem):
        profile = supplier_mem.get_profile("sysco-foods")
        assert profile["supplier_id"] == "sysco-foods"
        assert profile["scan_count"] == 0
        assert profile["latest_values"] == {}
        assert profile["item_history"] == {}
        assert profile["corrections"] == []

    def test_save_scan_creates_profile(self, supplier_mem, tmp_data_dir):
        scan_data = {
            "supplier": "Sysco Foods",
            "tax_rate": 0.08,
            "items": [
                {"name": "Chicken Breast", "unit_price": 4.99, "unit": "lb"},
            ],
        }
        supplier_mem.save_scan("sysco-foods", scan_data)

        profile = supplier_mem.get_profile("sysco-foods")
        assert profile["scan_count"] == 1
        assert profile["latest_values"]["supplier"] == "Sysco Foods"
        assert profile["latest_values"]["tax_rate"] == 0.08
        assert "Chicken Breast" in profile["item_history"]
        assert profile["item_history"]["Chicken Breast"]["avg_price"] == 4.99
        assert profile["item_history"]["Chicken Breast"]["common_unit"] == "lb"
        assert profile["item_history"]["Chicken Breast"]["seen_count"] == 1

    def test_save_scan_updates_running_average(self, supplier_mem):
        scan1 = {
            "supplier": "Sysco",
            "items": [{"name": "Chicken", "unit_price": 4.00, "unit": "lb"}],
        }
        scan2 = {
            "supplier": "Sysco",
            "items": [{"name": "Chicken", "unit_price": 6.00, "unit": "lb"}],
        }
        supplier_mem.save_scan("sysco", scan1)
        supplier_mem.save_scan("sysco", scan2)

        profile = supplier_mem.get_profile("sysco")
        assert profile["scan_count"] == 2
        assert profile["item_history"]["Chicken"]["avg_price"] == 5.0
        assert profile["item_history"]["Chicken"]["seen_count"] == 2

    def test_save_scan_updates_index(self, supplier_mem, tmp_data_dir):
        supplier_mem.save_scan("sysco", {"supplier": "Sysco Foods", "items": []})

        index_path = tmp_data_dir / "suppliers" / "index.json"
        with open(index_path) as f:
            index = json.load(f)
        assert "sysco" in index["suppliers"]
        assert index["suppliers"]["sysco"]["name"] == "Sysco Foods"

    def test_save_scan_with_corrections(self, supplier_mem):
        scan_data = {
            "supplier": "Sysco",
            "items": [],
            "corrections": [{"field": "total", "old": 100, "new": 110}],
        }
        supplier_mem.save_scan("sysco", scan_data)

        profile = supplier_mem.get_profile("sysco")
        assert len(profile["corrections"]) == 1
        assert profile["corrections"][0]["field"] == "total"

    def test_save_scan_item_without_price(self, supplier_mem):
        scan_data = {
            "supplier": "Sysco",
            "items": [{"name": "Mystery Item", "unit": "ea"}],
        }
        supplier_mem.save_scan("sysco", scan_data)

        profile = supplier_mem.get_profile("sysco")
        assert profile["item_history"]["Mystery Item"]["avg_price"] == 0
        assert profile["item_history"]["Mystery Item"]["seen_count"] == 1


# --- Supplier Memory Inference ---


class TestJsonSupplierMemoryInfer:
    def test_infer_missing_returns_common_value(self, supplier_mem):
        supplier_mem.save_scan("sysco", {
            "supplier": "Sysco Foods",
            "tax_rate": 0.08,
            "items": [],
        })
        assert supplier_mem.infer_missing("sysco", "supplier") == "Sysco Foods"
        assert supplier_mem.infer_missing("sysco", "tax_rate") == 0.08

    def test_infer_missing_unknown_field_returns_none(self, supplier_mem):
        supplier_mem.save_scan("sysco", {"supplier": "Sysco", "items": []})
        assert supplier_mem.infer_missing("sysco", "nonexistent") is None

    def test_infer_missing_no_profile_returns_none(self, supplier_mem):
        assert supplier_mem.infer_missing("unknown", "supplier") is None


# --- Supplier Layout ---


class TestJsonSupplierMemoryLayout:
    def test_get_layout_nonexistent_returns_none(self, supplier_mem):
        assert supplier_mem.get_layout("sysco") is None

    def test_update_and_get_layout(self, supplier_mem):
        layout = {
            "header_region": {"x": 0, "y": 0, "w": 100, "h": 50},
            "items_region": {"x": 0, "y": 50, "w": 100, "h": 200},
        }
        supplier_mem.update_layout("sysco", layout)

        result = supplier_mem.get_layout("sysco")
        assert result == layout

    def test_update_layout_overwrites(self, supplier_mem):
        supplier_mem.update_layout("sysco", {"version": 1})
        supplier_mem.update_layout("sysco", {"version": 2})

        result = supplier_mem.get_layout("sysco")
        assert result["version"] == 2


# --- Supplier ID Validation ---


class TestSupplierIDValidation:
    def test_path_traversal_get_profile(self, supplier_mem):
        with pytest.raises(ValueError):
            supplier_mem.get_profile("../etc/passwd")

    def test_path_traversal_save_scan(self, supplier_mem):
        with pytest.raises(ValueError):
            supplier_mem.save_scan("../../evil", {"items": []})

    def test_path_traversal_layout(self, supplier_mem):
        with pytest.raises(ValueError):
            supplier_mem.get_layout("foo/../../bar")

    def test_empty_id_rejected(self, supplier_mem):
        with pytest.raises(ValueError):
            supplier_mem.get_profile("")

    def test_invalid_chars_rejected(self, supplier_mem):
        with pytest.raises(ValueError):
            supplier_mem.get_profile("foo bar")


# --- General Memory ---


class TestJsonGeneralMemory:
    def test_get_industry_profile_default(self, general_mem):
        profile = general_mem.get_industry_profile()
        assert "common_units" in profile
        assert "typical_tax_rates" in profile
        assert "ea" in profile["common_units"]

    def test_get_item_catalog_default(self, general_mem):
        catalog = general_mem.get_item_catalog()
        assert "items" in catalog
        assert catalog["items"] == {}

    def test_update_from_scan_adds_items(self, general_mem):
        scan_data = {
            "items": [
                {"name": "Chicken Breast", "unit_price": 4.99, "unit": "lb"},
                {"name": "Rice", "unit_price": 1.50, "unit": "bag"},
            ],
        }
        general_mem.update_from_scan(scan_data)

        catalog = general_mem.get_item_catalog()
        assert "Chicken Breast" in catalog["items"]
        assert catalog["items"]["Chicken Breast"]["avg_price"] == 4.99
        assert catalog["items"]["Rice"]["avg_price"] == 1.50

    def test_update_from_scan_running_average(self, general_mem):
        general_mem.update_from_scan({
            "items": [{"name": "Chicken", "unit_price": 4.00, "unit": "lb"}],
        })
        general_mem.update_from_scan({
            "items": [{"name": "Chicken", "unit_price": 6.00, "unit": "lb"}],
        })

        catalog = general_mem.get_item_catalog()
        assert catalog["items"]["Chicken"]["avg_price"] == 5.0
        assert catalog["items"]["Chicken"]["seen_count"] == 2

    def test_update_from_scan_adds_new_tax_rate(self, general_mem, tmp_data_dir):
        # Write initial profile
        profile_path = tmp_data_dir / "general" / "industry_profile.json"
        profile_path.write_text(json.dumps({
            "common_units": ["ea", "lb"],
            "typical_tax_rates": [0.08],
            "item_catalog": {},
        }))

        general_mem.update_from_scan({"tax_rate": 0.0625, "items": []})

        profile = general_mem.get_industry_profile()
        assert 0.0625 in profile["typical_tax_rates"]
        assert profile["typical_tax_rates"] == sorted(profile["typical_tax_rates"])

    def test_update_from_scan_adds_new_unit(self, general_mem, tmp_data_dir):
        profile_path = tmp_data_dir / "general" / "industry_profile.json"
        profile_path.write_text(json.dumps({
            "common_units": ["ea", "lb"],
            "typical_tax_rates": [],
        }))

        general_mem.update_from_scan({
            "items": [{"name": "Flour", "unit_price": 2.00, "unit": "bag"}],
        })

        profile = general_mem.get_industry_profile()
        assert "bag" in profile["common_units"]


# --- Corrupt / Missing Files ---


class TestCorruptFiles:
    def test_corrupt_profile_returns_default(self, supplier_mem, tmp_data_dir):
        # Write invalid JSON
        supplier_dir = tmp_data_dir / "suppliers" / "bad-supplier"
        supplier_dir.mkdir(parents=True)
        (supplier_dir / "profile.json").write_text("{invalid json!!!")

        profile = supplier_mem.get_profile("bad-supplier")
        assert profile["supplier_id"] == "bad-supplier"
        assert profile["scan_count"] == 0

    def test_corrupt_layout_returns_none(self, supplier_mem, tmp_data_dir):
        supplier_dir = tmp_data_dir / "suppliers" / "bad-supplier"
        supplier_dir.mkdir(parents=True)
        (supplier_dir / "layout.json").write_text("not json")

        assert supplier_mem.get_layout("bad-supplier") is None

    def test_corrupt_industry_profile_returns_default(self, general_mem, tmp_data_dir):
        (tmp_data_dir / "general" / "industry_profile.json").write_text("BROKEN")

        profile = general_mem.get_industry_profile()
        assert "common_units" in profile

    def test_corrupt_item_catalog_returns_default(self, general_mem, tmp_data_dir):
        (tmp_data_dir / "general" / "item_catalog.json").write_text("[1,2,3]")

        catalog = general_mem.get_item_catalog()
        assert catalog == {"items": {}}

    def test_save_scan_over_corrupt_profile(self, supplier_mem, tmp_data_dir):
        supplier_dir = tmp_data_dir / "suppliers" / "bad"
        supplier_dir.mkdir(parents=True)
        (supplier_dir / "profile.json").write_text("{broken}")

        supplier_mem.save_scan("bad", {"supplier": "Bad Corp", "items": []})
        profile = supplier_mem.get_profile("bad")
        assert profile["scan_count"] == 1
        assert profile["latest_values"]["supplier"] == "Bad Corp"
