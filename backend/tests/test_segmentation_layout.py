"""
Tests for layout-aware segmentation in scanner.preprocessing.segmentation.

Tests the _apply_saved_layout helper and the updated segment_invoice function
that accepts a saved_layout parameter for supplier layout mapping.
"""

import numpy as np
import pytest
from PIL import Image

from scanner.preprocessing.segmentation import segment_invoice, _apply_saved_layout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_image(width=800, height=1200):
    """Create a simple test image with some content."""
    arr = np.ones((height, width, 3), dtype=np.uint8) * 255
    # Draw some horizontal lines to give structure
    for y in range(100, height - 100, 60):
        arr[y:y + 2, 50:width - 50] = 0
    return Image.fromarray(arr)


def _make_saved_layout(image_size_ratio=None, header=None, items=None, totals=None, version=1):
    """Build a saved layout descriptor for testing."""
    w, h = 800, 1200
    ratio = image_size_ratio if image_size_ratio is not None else round(w / h, 4)
    return {
        "image_size_ratio": ratio,
        "header_region": header or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.25},
        "items_region": items or {"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.50},
        "totals_region": totals or {"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25},
        "version": version,
    }


# ---------------------------------------------------------------------------
# Tests for _apply_saved_layout
# ---------------------------------------------------------------------------

class TestApplySavedLayout:
    def test_uses_saved_layout_regions(self):
        layout = _make_saved_layout()
        image_size = (800, 1200)
        result = _apply_saved_layout(layout, image_size)
        assert result is not None
        assert "header" in result
        assert "line_items" in result
        assert "totals" in result

    def test_saved_layout_produces_correct_crop_sizes(self):
        layout = _make_saved_layout(
            header={"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.25},
            items={"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.50},
            totals={"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25},
        )
        image_size = (800, 1200)
        result = _apply_saved_layout(layout, image_size)
        assert result is not None
        # header: (0, 0, 800, 300)
        assert result["header"] == (0, 0, 800, 300)
        # items: (0, 300, 800, 600)
        assert result["line_items"] == (0, 300, 800, 600)
        # totals: (0, 900, 800, 300)
        assert result["totals"] == (0, 900, 800, 300)

    def test_saved_layout_bounding_boxes_are_absolute(self):
        layout = _make_saved_layout(
            header={"x": 0.1, "y": 0.05, "w": 0.8, "h": 0.2},
        )
        image_size = (1000, 2000)
        result = _apply_saved_layout(layout, image_size)
        assert result is not None
        # x=0.1*1000=100, y=0.05*2000=100, w=0.8*1000=800, h=0.2*2000=400
        assert result["header"] == (100, 100, 800, 400)

    def test_none_saved_layout_falls_back_to_detection(self):
        result = _apply_saved_layout(None, (800, 1200))
        assert result is None

    def test_saved_layout_with_missing_region_skips_it(self):
        layout = _make_saved_layout()
        layout["totals_region"] = None
        image_size = (800, 1200)
        result = _apply_saved_layout(layout, image_size)
        assert result is not None
        assert "header" in result
        assert "line_items" in result
        assert "totals" not in result

    def test_very_different_aspect_ratio_falls_back(self):
        # Layout was built for portrait (0.6667), but image is landscape (1.5+)
        layout = _make_saved_layout(image_size_ratio=0.6667)
        # Very different aspect ratio image
        image_size = (1200, 400)  # ratio = 3.0
        result = _apply_saved_layout(layout, image_size)
        assert result is None  # Should fall back


# ---------------------------------------------------------------------------
# Integration: segment_invoice with saved_layout
# ---------------------------------------------------------------------------

class TestSegmentInvoiceWithLayout:
    def test_segment_invoice_uses_saved_layout(self):
        img = _make_test_image(800, 1200)
        layout = _make_saved_layout()
        result = segment_invoice(img, saved_layout=layout)
        assert result["regions_detected"] is True
        # The bounding boxes should come from the saved layout
        assert result["bounding_boxes"]["header"] == (0, 0, 800, 300)

    def test_segment_invoice_falls_back_without_layout(self):
        img = _make_test_image(800, 1200)
        result = segment_invoice(img)
        # Should still work via morphological detection / heuristic
        assert result["full"] is not None
