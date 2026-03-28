"""Layout descriptor builder for supplier invoice layouts.

Pure functions -- no I/O, no state. Converts absolute bounding boxes from
segmentation into normalized (0-1 range) layout descriptors.
"""
from __future__ import annotations

LAYOUT_VERSION = 1

_REGION_MAP = {
    "header": "header_region",
    "line_items": "items_region",
    "totals": "totals_region",
}


def _normalize_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> dict[str, float]:
    """Normalize a bounding box (x, y, w, h) to 0-1 range."""
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
    """Build a normalized layout descriptor from segmentation bounding boxes.

    Args:
        scan_result: The scan result dict (currently unused but reserved for
            future enrichment, e.g. field positions).
        bounding_boxes: Dict mapping region name ("header", "line_items",
            "totals") to absolute (x, y, w, h) tuples.
        image_size: (width, height) of the source image in pixels.

    Returns:
        Layout descriptor dict with normalized region coordinates, image
        aspect ratio, and a version field.
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
