"""
Integration tests for layout descriptor round-trip: build → save → retrieve.

Tests the building blocks used by the scan engine for supplier layout mapping,
without requiring the Claude API (no mocking needed).
"""

import tempfile
from pathlib import Path

import pytest

from scanner.preprocessing.layout import build_layout_descriptor, LAYOUT_VERSION
from scanner.memory.json_store import JsonSupplierMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for memory storage."""
    return tmp_path


@pytest.fixture
def supplier_mem(tmp_data_dir):
    """JsonSupplierMemory backed by a temp directory."""
    return JsonSupplierMemory(data_dir=tmp_data_dir)


@pytest.fixture
def sample_bboxes():
    return {
        "header": (0, 0, 800, 300),
        "line_items": (0, 300, 800, 600),
        "totals": (0, 900, 800, 300),
    }


@pytest.fixture
def sample_scan_result():
    return {"supplier": "Test Co", "invoice_number": "INV-100"}


IMAGE_SIZE = (800, 1200)
SUPPLIER_ID = "test-co"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLayoutRoundTrip:
    def test_build_and_save_layout(self, supplier_mem, sample_scan_result, sample_bboxes):
        """Build a descriptor and save it via supplier memory."""
        descriptor = build_layout_descriptor(sample_scan_result, sample_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, descriptor)

        retrieved = supplier_mem.get_layout(SUPPLIER_ID)
        assert retrieved is not None
        assert retrieved["version"] == LAYOUT_VERSION

    def test_retrieved_layout_matches_saved(self, supplier_mem, sample_scan_result, sample_bboxes):
        """Saved and retrieved layout descriptors are identical."""
        descriptor = build_layout_descriptor(sample_scan_result, sample_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, descriptor)

        retrieved = supplier_mem.get_layout(SUPPLIER_ID)
        assert retrieved == descriptor

    def test_no_layout_returns_none(self, supplier_mem):
        """get_layout returns None when no layout has been saved."""
        assert supplier_mem.get_layout(SUPPLIER_ID) is None

    def test_layout_overwrite(self, supplier_mem, sample_scan_result, sample_bboxes):
        """Updating layout replaces the previous one."""
        desc1 = build_layout_descriptor(sample_scan_result, sample_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, desc1)

        # Build a different layout
        new_bboxes = {
            "header": (0, 0, 800, 200),
            "line_items": (0, 200, 800, 700),
            "totals": (0, 900, 800, 300),
        }
        desc2 = build_layout_descriptor(sample_scan_result, new_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, desc2)

        retrieved = supplier_mem.get_layout(SUPPLIER_ID)
        assert retrieved == desc2
        assert retrieved != desc1

    def test_layout_regions_are_normalized(self, supplier_mem, sample_scan_result, sample_bboxes):
        """All region coordinates in the round-tripped descriptor are in [0, 1]."""
        descriptor = build_layout_descriptor(sample_scan_result, sample_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, descriptor)
        retrieved = supplier_mem.get_layout(SUPPLIER_ID)

        for key in ("header_region", "items_region", "totals_region"):
            region = retrieved[key]
            if region is None:
                continue
            for coord in ("x", "y", "w", "h"):
                assert 0.0 <= region[coord] <= 1.0

    def test_layout_preserves_image_size_ratio(self, supplier_mem, sample_scan_result, sample_bboxes):
        """image_size_ratio survives the JSON round-trip."""
        descriptor = build_layout_descriptor(sample_scan_result, sample_bboxes, IMAGE_SIZE)
        supplier_mem.update_layout(SUPPLIER_ID, descriptor)
        retrieved = supplier_mem.get_layout(SUPPLIER_ID)
        assert retrieved["image_size_ratio"] == round(800 / 1200, 4)
