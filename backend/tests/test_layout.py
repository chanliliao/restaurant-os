"""
Tests for scanner.preprocessing.layout module.

Tests the build_layout_descriptor function which converts absolute bounding
boxes from segmentation into normalized (0-1 range) layout descriptors.
"""

import pytest

from scanner.preprocessing.layout import build_layout_descriptor, LAYOUT_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_scan_result():
    """Minimal scan result dict."""
    return {
        "supplier": "Test Supplier",
        "invoice_number": "INV-001",
    }


@pytest.fixture
def sample_bounding_boxes():
    """Bounding boxes for a 1000x2000 image."""
    return {
        "header": (0, 0, 1000, 400),
        "line_items": (0, 400, 1000, 1200),
        "totals": (0, 1600, 1000, 400),
    }


IMAGE_SIZE = (1000, 2000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildLayoutDescriptor:
    def test_basic_descriptor_has_required_keys(self, sample_scan_result, sample_bounding_boxes):
        descriptor = build_layout_descriptor(sample_scan_result, sample_bounding_boxes, IMAGE_SIZE)
        assert "header_region" in descriptor
        assert "items_region" in descriptor
        assert "totals_region" in descriptor
        assert "image_size_ratio" in descriptor
        assert "version" in descriptor

    def test_coordinates_are_normalized_0_to_1(self, sample_scan_result, sample_bounding_boxes):
        descriptor = build_layout_descriptor(sample_scan_result, sample_bounding_boxes, IMAGE_SIZE)
        for region_key in ("header_region", "items_region", "totals_region"):
            region = descriptor[region_key]
            assert region is not None
            for coord_key in ("x", "y", "w", "h"):
                value = region[coord_key]
                assert 0.0 <= value <= 1.0, (
                    f"{region_key}.{coord_key} = {value} is not in [0, 1]"
                )

    def test_image_size_ratio(self, sample_scan_result, sample_bounding_boxes):
        descriptor = build_layout_descriptor(sample_scan_result, sample_bounding_boxes, IMAGE_SIZE)
        expected = round(1000 / 2000, 4)
        assert descriptor["image_size_ratio"] == expected

    def test_version_field(self, sample_scan_result, sample_bounding_boxes):
        descriptor = build_layout_descriptor(sample_scan_result, sample_bounding_boxes, IMAGE_SIZE)
        assert descriptor["version"] == LAYOUT_VERSION

    def test_missing_region_gets_none(self, sample_scan_result):
        # Only header provided, line_items and totals missing
        boxes = {"header": (0, 0, 800, 200)}
        descriptor = build_layout_descriptor(sample_scan_result, boxes, (800, 1000))
        assert descriptor["header_region"] is not None
        assert descriptor["items_region"] is None
        assert descriptor["totals_region"] is None

    def test_empty_bounding_boxes_all_none(self, sample_scan_result):
        descriptor = build_layout_descriptor(sample_scan_result, {}, IMAGE_SIZE)
        assert descriptor["header_region"] is None
        assert descriptor["items_region"] is None
        assert descriptor["totals_region"] is None

    def test_coordinates_rounded_to_4_decimals(self, sample_scan_result):
        # Use values that would produce long decimals
        boxes = {
            "header": (33, 77, 333, 111),
            "line_items": (33, 188, 333, 600),
            "totals": (33, 788, 333, 212),
        }
        descriptor = build_layout_descriptor(sample_scan_result, boxes, (1000, 1000))
        for region_key in ("header_region", "items_region", "totals_region"):
            region = descriptor[region_key]
            for coord_key in ("x", "y", "w", "h"):
                value = region[coord_key]
                # Check rounding to 4 decimals
                assert value == round(value, 4)
                parts = str(value).split(".")
                if len(parts) == 2:
                    assert len(parts[1]) <= 4
