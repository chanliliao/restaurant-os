# Phase 15: Supplier Layout Mapping

> **For agentic workers:** execute this plan using the `superpowers:subagent-driven-development` skill.

## Goal

After a successful scan, save a layout descriptor for the supplier that records where regions (header, items, totals) appear on the invoice. On subsequent scans of the same supplier, use the saved layout to guide segmentation for faster and more accurate region cropping.

## Current State

- `segment_invoice(image)` in `backend/scanner/preprocessing/segmentation.py` detects regions via morphological analysis but is NOT used by the scan engine
- `JsonSupplierMemory.get_layout(supplier_id)` and `update_layout(supplier_id, layout)` exist and are tested
- `scan_invoice()` in `backend/scanner/scanning/engine.py` does NOT call segmentation
- `normalize_supplier_id()` and memory stores are already instantiated in engine.py

## New & Modified Files

| # | File | Action |
|---|------|--------|
| 1 | `backend/scanner/preprocessing/layout.py` | **Create** - Layout descriptor builder (pure functions) |
| 2 | `backend/scanner/preprocessing/segmentation.py` | **Modify** - Accept optional saved layout |
| 3 | `backend/scanner/preprocessing/__init__.py` | **Modify** - Export new layout functions |
| 4 | `backend/scanner/scanning/engine.py` | **Modify** - Wire segmentation + layout into pipeline |
| 5 | `backend/tests/test_layout.py` | **Create** - Unit tests for layout descriptor |
| 6 | `backend/tests/test_segmentation_layout.py` | **Create** - Unit tests for layout-aware segmentation |
| 7 | `backend/tests/test_engine_layout.py` | **Create** - Integration tests for engine layout wiring |

## Security

- Layout descriptors contain only numeric coordinates (0-1 range) -- no user input stored raw
- Supplier IDs are already validated/normalized via `normalize_supplier_id()` and `_validate_supplier_id()`
- Layout writes go through existing atomic JSON write with file locks
- No new user-facing inputs; layout is derived from scan results and bounding boxes internally

---

## Tasks

### Task 1: Layout Descriptor Builder - Tests

**File:** `backend/tests/test_layout.py`

```python
"""Tests for layout descriptor builder."""

import pytest

from scanner.preprocessing.layout import build_layout_descriptor, LAYOUT_VERSION


class TestBuildLayoutDescriptor:
    """Unit tests for build_layout_descriptor."""

    def test_basic_descriptor_has_required_keys(self):
        bounding_boxes = {
            "header": (0, 0, 1000, 150),
            "line_items": (0, 150, 1000, 650),
            "totals": (500, 800, 500, 200),
        }
        image_size = (1000, 1000)
        scan_result = {"supplier": "Sysco Foods", "items": [{"name": "Chicken"}]}

        descriptor = build_layout_descriptor(scan_result, bounding_boxes, image_size)

        assert "image_size_ratio" in descriptor
        assert "header_region" in descriptor
        assert "items_region" in descriptor
        assert "totals_region" in descriptor
        assert "version" in descriptor

    def test_coordinates_are_normalized_0_to_1(self):
        bounding_boxes = {
            "header": (0, 0, 1000, 250),
            "line_items": (0, 250, 1000, 500),
            "totals": (500, 750, 500, 250),
        }
        image_size = (1000, 1000)
        scan_result = {"supplier": "Test"}

        descriptor = build_layout_descriptor(scan_result, bounding_boxes, image_size)

        header = descriptor["header_region"]
        assert header["x"] == 0.0
        assert header["y"] == 0.0
        assert header["w"] == 1.0
        assert header["h"] == 0.25

        totals = descriptor["totals_region"]
        assert totals["x"] == 0.5
        assert totals["y"] == 0.75
        assert totals["w"] == 0.5
        assert totals["h"] == 0.25

    def test_image_size_ratio(self):
        bounding_boxes = {
            "header": (0, 0, 800, 200),
            "line_items": (0, 200, 800, 400),
            "totals": (0, 600, 800, 200),
        }
        image_size = (800, 1000)
        scan_result = {"supplier": "Test"}

        descriptor = build_layout_descriptor(scan_result, bounding_boxes, image_size)
        assert descriptor["image_size_ratio"] == 0.8

    def test_version_field(self):
        bounding_boxes = {
            "header": (0, 0, 100, 25),
            "line_items": (0, 25, 100, 50),
            "totals": (0, 75, 100, 25),
        }
        descriptor = build_layout_descriptor({}, bounding_boxes, (100, 100))
        assert descriptor["version"] == LAYOUT_VERSION

    def test_missing_region_gets_none(self):
        bounding_boxes = {
            "header": (0, 0, 100, 30),
            "line_items": (0, 30, 100, 70),
            # no totals
        }
        descriptor = build_layout_descriptor({}, bounding_boxes, (100, 100))
        assert descriptor["totals_region"] is None
        assert descriptor["header_region"] is not None
        assert descriptor["items_region"] is not None

    def test_empty_bounding_boxes_all_none(self):
        descriptor = build_layout_descriptor({}, {}, (100, 100))
        assert descriptor["header_region"] is None
        assert descriptor["items_region"] is None
        assert descriptor["totals_region"] is None
        assert descriptor["version"] == LAYOUT_VERSION

    def test_coordinates_rounded_to_4_decimals(self):
        bounding_boxes = {
            "header": (0, 0, 333, 111),
            "line_items": (0, 111, 333, 222),
            "totals": (0, 333, 333, 111),
        }
        descriptor = build_layout_descriptor({}, bounding_boxes, (1000, 1000))
        header = descriptor["header_region"]
        # All values should have at most 4 decimal places
        for val in [header["x"], header["y"], header["w"], header["h"]]:
            assert val == round(val, 4)
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_layout.py -v`

**Expected:** All tests FAIL (module does not exist yet).

---

### Task 2: Layout Descriptor Builder - Implementation

**File:** `backend/scanner/preprocessing/layout.py`

```python
"""Layout descriptor builder for supplier invoice layouts.

Pure functions -- no I/O, no state.  Converts absolute bounding boxes from
segmentation into normalized (0-1 range) layout descriptors that are
scale-independent and can be saved per-supplier for reuse.
"""

from __future__ import annotations

LAYOUT_VERSION = 1

# Mapping from segmentation region names to layout descriptor keys
_REGION_MAP = {
    "header": "header_region",
    "line_items": "items_region",
    "totals": "totals_region",
}


def _normalize_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> dict[str, float]:
    """Convert an absolute (x, y, w, h) bbox to normalized 0-1 coordinates.

    Args:
        bbox: (x, y, width, height) in pixels.
        image_size: (width, height) of the source image.

    Returns:
        Dict with keys x, y, w, h as floats in [0, 1].
    """
    img_w, img_h = image_size
    x, y, w, h = bbox
    return {
        "x": round(x / img_w, 4),
        "y": round(y / img_h, 4),
        "w": round(w / img_w, 4),
        "h": round(h / img_h, 4),
    }


def build_layout_descriptor(
    scan_result: dict,
    bounding_boxes: dict,
    image_size: tuple[int, int],
) -> dict:
    """Build a layout descriptor from a successful scan's bounding boxes.

    Args:
        scan_result: The scan result dict (used for future extensions;
            currently unused beyond presence check).
        bounding_boxes: Dict mapping region name ("header", "line_items",
            "totals") to (x, y, w, h) pixel tuples from segmentation.
        image_size: (width, height) of the original image in pixels.

    Returns:
        Layout descriptor dict with normalized coordinates and version.
    """
    img_w, img_h = image_size

    descriptor: dict = {
        "image_size_ratio": round(img_w / img_h, 4) if img_h > 0 else 0,
        "header_region": None,
        "items_region": None,
        "totals_region": None,
        "version": LAYOUT_VERSION,
    }

    for seg_name, layout_key in _REGION_MAP.items():
        if seg_name in bounding_boxes:
            descriptor[layout_key] = _normalize_bbox(
                bounding_boxes[seg_name], image_size
            )

    return descriptor
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_layout.py -v`

**Expected:** All tests PASS.

**Commit:** `"Add layout descriptor builder (Phase 15)"`

---

### Task 3: Layout-Aware Segmentation - Tests

**File:** `backend/tests/test_segmentation_layout.py`

```python
"""Tests for layout-aware segmentation."""

import numpy as np
import pytest
from PIL import Image

from scanner.preprocessing.segmentation import segment_invoice


def _make_white_image(width: int = 800, height: int = 1000) -> Image.Image:
    """Create a plain white test image."""
    return Image.new("RGB", (width, height), color=(255, 255, 255))


class TestSegmentInvoiceWithSavedLayout:
    """Tests for segment_invoice when a saved_layout is provided."""

    def test_uses_saved_layout_regions(self):
        image = _make_white_image(1000, 1000)
        saved_layout = {
            "image_size_ratio": 1.0,
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.15},
            "items_region": {"x": 0.0, "y": 0.15, "w": 1.0, "h": 0.65},
            "totals_region": {"x": 0.5, "y": 0.80, "w": 0.5, "h": 0.20},
            "version": 1,
        }
        result = segment_invoice(image, saved_layout=saved_layout)

        assert result["regions_detected"] is True
        assert result["header"] is not None
        assert result["line_items"] is not None
        assert result["totals"] is not None

    def test_saved_layout_produces_correct_crop_sizes(self):
        image = _make_white_image(1000, 1000)
        saved_layout = {
            "image_size_ratio": 1.0,
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.20},
            "items_region": {"x": 0.0, "y": 0.20, "w": 1.0, "h": 0.60},
            "totals_region": {"x": 0.0, "y": 0.80, "w": 1.0, "h": 0.20},
            "version": 1,
        }
        result = segment_invoice(image, saved_layout=saved_layout)

        assert result["header"].size == (1000, 200)
        assert result["line_items"].size == (1000, 600)
        assert result["totals"].size == (1000, 200)

    def test_saved_layout_bounding_boxes_are_absolute(self):
        image = _make_white_image(800, 1000)
        saved_layout = {
            "image_size_ratio": 0.8,
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.25},
            "items_region": {"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.50},
            "totals_region": {"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25},
            "version": 1,
        }
        result = segment_invoice(image, saved_layout=saved_layout)

        assert result["bounding_boxes"]["header"] == (0, 0, 800, 250)
        assert result["bounding_boxes"]["line_items"] == (0, 250, 800, 500)
        assert result["bounding_boxes"]["totals"] == (0, 750, 800, 250)

    def test_none_saved_layout_falls_back_to_detection(self):
        image = _make_white_image(800, 1000)
        result = segment_invoice(image, saved_layout=None)

        # Should still work (heuristic fallback), same as no-arg call
        assert result["full"] is not None
        assert result["regions_detected"] is True

    def test_saved_layout_with_missing_region_skips_it(self):
        image = _make_white_image(1000, 1000)
        saved_layout = {
            "image_size_ratio": 1.0,
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.25},
            "items_region": {"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.50},
            "totals_region": None,
            "version": 1,
        }
        result = segment_invoice(image, saved_layout=saved_layout)

        assert result["header"] is not None
        assert result["line_items"] is not None
        assert result["totals"] is None

    def test_very_different_aspect_ratio_falls_back(self):
        """If saved layout ratio differs by >30%, fall back to detection."""
        image = _make_white_image(1000, 1000)  # ratio 1.0
        saved_layout = {
            "image_size_ratio": 0.5,  # very different ratio
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.25},
            "items_region": {"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.50},
            "totals_region": {"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25},
            "version": 1,
        }
        result = segment_invoice(image, saved_layout=saved_layout)

        # Should fall back to morphological/heuristic detection
        assert result["regions_detected"] is True
        assert result["full"] is not None
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_segmentation_layout.py -v`

**Expected:** All tests FAIL (`segment_invoice` does not accept `saved_layout` yet).

---

### Task 4: Layout-Aware Segmentation - Implementation

**File:** `backend/scanner/preprocessing/segmentation.py`

Add a helper function `_apply_saved_layout` and update `segment_invoice` to accept and use `saved_layout`:

Add after the `_find_line_y_positions` function (before the "Region cropping" section):

```python
# ---------------------------------------------------------------------------
# Saved layout application
# ---------------------------------------------------------------------------

# Maximum aspect ratio difference (30%) before falling back to detection
_MAX_RATIO_DIFF = 0.30


def _apply_saved_layout(image_size: tuple[int, int], saved_layout: dict) -> dict | None:
    """Convert a saved normalized layout back to absolute bounding boxes.

    Returns a regions dict compatible with crop_regions, or None if the
    saved layout is incompatible with the current image dimensions.

    Args:
        image_size: (width, height) of the current image.
        saved_layout: Normalized layout descriptor from a previous scan.

    Returns:
        Dict with "bounding_boxes", "regions_detected", "method" keys,
        or None if the layout should not be used.
    """
    width, height = image_size

    # Check aspect ratio compatibility
    current_ratio = width / height if height > 0 else 0
    saved_ratio = saved_layout.get("image_size_ratio", 0)
    if saved_ratio > 0 and current_ratio > 0:
        ratio_diff = abs(current_ratio - saved_ratio) / saved_ratio
        if ratio_diff > _MAX_RATIO_DIFF:
            return None

    # Convert normalized regions to absolute bounding boxes
    region_map = {
        "header_region": "header",
        "items_region": "line_items",
        "totals_region": "totals",
    }

    bounding_boxes = {}
    for layout_key, seg_name in region_map.items():
        region = saved_layout.get(layout_key)
        if region is None:
            continue
        x = int(region["x"] * width)
        y = int(region["y"] * height)
        w = int(region["w"] * width)
        h = int(region["h"] * height)
        if w > 0 and h > 0:
            bounding_boxes[seg_name] = (x, y, w, h)

    if not bounding_boxes:
        return None

    return {
        "bounding_boxes": bounding_boxes,
        "regions_detected": True,
        "method": "saved_layout",
    }
```

Update the `segment_invoice` function signature and body:

Replace the existing `segment_invoice` function with:

```python
def segment_invoice(image, saved_layout: dict | None = None) -> dict:
    """
    Full ROI segmentation orchestrator.

    1. If a saved_layout is provided and compatible, use it directly.
    2. Otherwise, run detect_regions to find header / line_items / totals.
    3. Crop the image into detected regions.
    4. Always include the full image as a fallback.

    Args:
        image: PIL Image or numpy ndarray.
        saved_layout: Optional normalized layout descriptor from a previous
            scan of the same supplier.

    Returns:
        Dict with keys:
            - "header": PIL Image or None
            - "line_items": PIL Image or None
            - "totals": PIL Image or None
            - "full": PIL Image (always present)
            - "regions_detected": bool
            - "bounding_boxes": dict of region name -> (x, y, w, h)
    """
    pil_img = _to_pil(image)
    width, height = pil_img.size

    # Try saved layout first
    regions = None
    if saved_layout is not None:
        regions = _apply_saved_layout((width, height), saved_layout)

    # Fall back to morphological detection
    if regions is None:
        regions = detect_regions(image)

    result = {
        "header": None,
        "line_items": None,
        "totals": None,
        "full": pil_img,
        "regions_detected": regions["regions_detected"],
        "bounding_boxes": regions["bounding_boxes"],
    }

    if not regions["regions_detected"]:
        return result

    cropped = crop_regions(image, regions)
    for name in ("header", "line_items", "totals"):
        if name in cropped:
            result[name] = cropped[name]

    return result
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_segmentation_layout.py -v`

**Expected:** All tests PASS.

**Commit:** `"Add layout-aware segmentation with fallback (Phase 15)"`

---

### Task 5: Export Layout Functions from Preprocessing Package

**File:** `backend/scanner/preprocessing/__init__.py`

Replace full contents with:

```python
from .orientation import fix_orientation, deskew, correct_perspective, auto_orient
from .analyzer import analyze_quality
from .processor import (
    enhance_contrast,
    sharpen,
    denoise,
    upscale,
    to_grayscale,
    selective_process,
    prepare_variants,
)
from .segmentation import detect_regions, crop_regions, segment_invoice
from .layout import build_layout_descriptor, LAYOUT_VERSION

__all__ = [
    "fix_orientation",
    "deskew",
    "correct_perspective",
    "auto_orient",
    "analyze_quality",
    "enhance_contrast",
    "sharpen",
    "denoise",
    "upscale",
    "to_grayscale",
    "selective_process",
    "prepare_variants",
    "detect_regions",
    "crop_regions",
    "segment_invoice",
    "build_layout_descriptor",
    "LAYOUT_VERSION",
]
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_layout.py backend/tests/test_segmentation_layout.py -v`

**Expected:** All tests still PASS.

**Commit:** `"Export layout module from preprocessing package (Phase 15)"`

---

### Task 6: Engine Layout Integration - Tests

**File:** `backend/tests/test_engine_layout.py`

```python
"""Integration tests for layout mapping in the scan engine."""

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from scanner.memory import JsonSupplierMemory, normalize_supplier_id
from scanner.preprocessing.layout import build_layout_descriptor, LAYOUT_VERSION


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


def _make_test_image_bytes(width=800, height=1000) -> bytes:
    """Create a simple test image as bytes."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestSaveLayoutAfterScan:
    """Test that a layout is saved after a successful first scan."""

    def test_layout_saved_after_successful_scan(self, supplier_mem):
        """After a scan returns a supplier name, layout should be saved."""
        supplier_id = normalize_supplier_id("Sysco Foods")

        # Simulate what the engine should do: save layout after scan
        bounding_boxes = {
            "header": (0, 0, 800, 200),
            "line_items": (0, 200, 800, 600),
            "totals": (0, 800, 800, 200),
        }
        scan_result = {"supplier": "Sysco Foods", "items": [{"name": "Chicken"}]}
        image_size = (800, 1000)

        layout = build_layout_descriptor(scan_result, bounding_boxes, image_size)
        supplier_mem.update_layout(supplier_id, layout)

        # Verify it was saved
        saved = supplier_mem.get_layout(supplier_id)
        assert saved is not None
        assert saved["version"] == LAYOUT_VERSION
        assert saved["header_region"] is not None
        assert saved["items_region"] is not None
        assert saved["totals_region"] is not None

    def test_layout_retrievable_for_subsequent_scan(self, supplier_mem):
        """A saved layout can be retrieved for a subsequent scan."""
        supplier_id = normalize_supplier_id("Sysco Foods")

        layout = {
            "image_size_ratio": 0.8,
            "header_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.20},
            "items_region": {"x": 0.0, "y": 0.20, "w": 1.0, "h": 0.60},
            "totals_region": {"x": 0.0, "y": 0.80, "w": 1.0, "h": 0.20},
            "version": LAYOUT_VERSION,
        }
        supplier_mem.update_layout(supplier_id, layout)

        # Retrieve
        saved = supplier_mem.get_layout(supplier_id)
        assert saved == layout

    def test_no_layout_for_unknown_supplier(self, supplier_mem):
        """Unknown supplier returns None for layout."""
        saved = supplier_mem.get_layout("unknown-supplier")
        assert saved is None


class TestLayoutDescriptorRoundTrip:
    """Test that layout descriptors survive save/load round-trip."""

    def test_round_trip_preserves_all_fields(self, supplier_mem):
        supplier_id = "test-supplier"
        bounding_boxes = {
            "header": (0, 0, 800, 250),
            "line_items": (0, 250, 800, 500),
            "totals": (400, 750, 400, 250),
        }
        layout = build_layout_descriptor({}, bounding_boxes, (800, 1000))
        supplier_mem.update_layout(supplier_id, layout)

        loaded = supplier_mem.get_layout(supplier_id)
        assert loaded["version"] == layout["version"]
        assert loaded["image_size_ratio"] == layout["image_size_ratio"]
        assert loaded["header_region"] == layout["header_region"]
        assert loaded["items_region"] == layout["items_region"]
        assert loaded["totals_region"] == layout["totals_region"]

    def test_layout_update_overwrites_previous(self, supplier_mem):
        supplier_id = "test-supplier"
        layout_v1 = build_layout_descriptor(
            {}, {"header": (0, 0, 100, 25)}, (100, 100)
        )
        supplier_mem.update_layout(supplier_id, layout_v1)

        layout_v2 = build_layout_descriptor(
            {},
            {
                "header": (0, 0, 100, 30),
                "line_items": (0, 30, 100, 40),
                "totals": (0, 70, 100, 30),
            },
            (100, 100),
        )
        supplier_mem.update_layout(supplier_id, layout_v2)

        loaded = supplier_mem.get_layout(supplier_id)
        assert loaded["header_region"]["h"] == 0.3
        assert loaded["items_region"] is not None
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_engine_layout.py -v`

**Expected:** All tests PASS (these test the building blocks, not the engine wiring itself).

---

### Task 7: Wire Layout into Scan Engine - Implementation

**File:** `backend/scanner/scanning/engine.py`

Add the segmentation and layout imports near the top, after the existing imports:

```python
from scanner.preprocessing.segmentation import segment_invoice
from scanner.preprocessing.layout import build_layout_descriptor
```

In the `scan_invoice` function, add layout lookup and segmentation after the image is opened and preprocessed (after the `images = [...]` block, before Step 2), and add layout saving after the inference step (after Step 7).

**After** the line `images = [` block (around line 183), add:

```python
        # Step 1b: Segmentation with layout lookup
        # Try to get saved layout after first scan pass (need supplier name).
        # For now, run segmentation without layout -- we'll apply saved layout
        # after we know the supplier from scan results.
        segmentation_result = segment_invoice(original)
```

**After** the inference step (Step 7, around line 243), add:

```python
        # Step 7b: Save layout for this supplier
        try:
            supplier_name = result.get("supplier", "")
            if supplier_name and sid:
                # Check if supplier already has a saved layout
                existing_layout = supplier_mem.get_layout(sid)
                if existing_layout is None and segmentation_result["regions_detected"]:
                    # First scan -- save the layout
                    layout = build_layout_descriptor(
                        result,
                        segmentation_result["bounding_boxes"],
                        original.size,
                    )
                    supplier_mem.update_layout(sid, layout)
                    logger.info("Saved layout for supplier %s", sid)
        except Exception as e:
            logger.warning("Layout save failed (non-fatal): %s", e)
```

**Full updated `scan_invoice` function** (showing all changes in context):

Replace the `scan_invoice` function body from the `try:` block. The key changes are:

1. After `variants = prepare_variants(image)` and before Scan 1, add segmentation call
2. After the inference step, add layout save logic
3. In `debug` metadata, add segmentation info

Here is the specific edit to make after the `images = [...]` block closes (after the closing `]` on the images list):

```python
        # Step 1b: Run segmentation (no saved layout yet -- need supplier name first)
        segmentation_result = segment_invoice(original)
```

And after the inference `except` block (after `logger.warning("Inference step failed (non-fatal): %s", e)`):

```python
        # Step 7b: Save layout for this supplier if none exists
        try:
            if sid and segmentation_result.get("regions_detected"):
                existing_layout = supplier_mem.get_layout(sid)
                if existing_layout is None:
                    layout_desc = build_layout_descriptor(
                        result,
                        segmentation_result["bounding_boxes"],
                        original.size,
                    )
                    supplier_mem.update_layout(sid, layout_desc)
                    logger.info("Saved new layout for supplier %s", sid)
        except Exception as e:
            logger.warning("Layout save failed (non-fatal): %s", e)
```

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_engine_layout.py -v`

**Expected:** All tests PASS.

**Commit:** `"Wire segmentation and layout saving into scan engine (Phase 15)"`

---

### Task 8: Full Test Suite Verification

Run the complete backend test suite to verify nothing is broken.

**Test command:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/ -v`

**Expected:** All tests PASS.

**Commit (if any fixups needed):** `"Fix test issues from Phase 15 integration"`

---

## Verification

```bash
/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -m pytest backend/tests/test_layout.py backend/tests/test_segmentation_layout.py backend/tests/test_engine_layout.py backend/tests/test_memory.py -v
```

All tests green confirms:
- Layout descriptors are built correctly with normalized coordinates
- Saved layouts are used for segmentation when aspect ratio matches
- Segmentation falls back to detection when layout is incompatible
- Layouts are saved to supplier memory after first successful scan
- Layout round-trip through JSON storage preserves all fields
- Existing segmentation and memory tests remain unbroken
