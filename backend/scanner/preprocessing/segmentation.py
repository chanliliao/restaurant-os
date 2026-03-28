"""
ROI Segmentation module.

Detects and crops invoice images into focused regions (header, line items,
totals) for more accurate downstream OCR scanning.  Falls back to full-image
mode when region detection is not possible.
"""

import numpy as np
from PIL import Image
import cv2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_pil(image) -> Image.Image:
    """Convert numpy array to PIL Image if needed."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return Image.fromarray(image, mode="L")
        return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if isinstance(image, Image.Image):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


def _to_cv_gray(image) -> np.ndarray:
    """Convert any image input to a grayscale numpy array."""
    if isinstance(image, Image.Image):
        return np.array(image.convert("L"))
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise TypeError(f"Unsupported image type: {type(image)}")


# Minimum image dimension for attempting region detection.
_MIN_DIMENSION = 50


# ---------------------------------------------------------------------------
# Region detection
# ---------------------------------------------------------------------------

def detect_regions(image) -> dict:
    """
    Detect bounding boxes for header, line_items, and totals regions.

    Strategy:
    1. Convert to grayscale, apply adaptive threshold.
    2. Use morphological horizontal line detection to find major dividers.
    3. If 2+ dividers found, split into three regions at divider positions.
    4. Otherwise, use heuristic split: top 25%, middle 50%, bottom 25%.
    5. If image is too small, return empty bounding boxes.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Dict with keys:
            - "bounding_boxes": dict mapping region name to (x, y, w, h)
            - "regions_detected": True if segmentation produced regions
            - "method": "lines", "heuristic", or "none"
    """
    pil_img = _to_pil(image)
    width, height = pil_img.size

    # Too small to segment meaningfully
    if width < _MIN_DIMENSION or height < _MIN_DIMENSION:
        return {
            "bounding_boxes": {},
            "regions_detected": False,
            "method": "none",
        }

    gray = _to_cv_gray(image)

    # Adaptive threshold for better line detection on varying backgrounds
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 15, 10,
    )

    # Morphological horizontal line detection
    # Kernel width = ~40% of image width, height = 1
    kernel_width = max(width // 3, 30)
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (kernel_width, 1)
    )
    horizontal_lines = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=2
    )

    # Find y-coordinates of detected horizontal lines
    line_ys = _find_line_y_positions(horizontal_lines, height)

    if len(line_ys) >= 2:
        # Use the first and last strong dividers to split regions
        top_divider = line_ys[0]
        bottom_divider = line_ys[-1]

        # Ensure minimum region sizes (at least 10% of image height each)
        min_region = int(height * 0.10)
        if (top_divider < min_region
                or (bottom_divider - top_divider) < min_region
                or (height - bottom_divider) < min_region):
            # Dividers are too close together; fall through to heuristic
            pass
        else:
            return {
                "bounding_boxes": {
                    "header": (0, 0, width, top_divider),
                    "line_items": (0, top_divider, width, bottom_divider - top_divider),
                    "totals": (0, bottom_divider, width, height - bottom_divider),
                },
                "regions_detected": True,
                "method": "lines",
            }

    # Heuristic fallback: top 25%, middle 50%, bottom 25%
    h25 = int(height * 0.25)
    h75 = int(height * 0.75)

    return {
        "bounding_boxes": {
            "header": (0, 0, width, h25),
            "line_items": (0, h25, width, h75 - h25),
            "totals": (0, h75, width, height - h75),
        },
        "regions_detected": True,
        "method": "heuristic",
    }


def _find_line_y_positions(horizontal_mask: np.ndarray, img_height: int) -> list:
    """
    Find distinct y-positions of horizontal lines from a binary mask.

    Groups nearby rows (within 2% of image height) into single line positions.
    Filters out lines too close to the top/bottom edges (within 5%).

    Returns sorted list of y-coordinates.
    """
    # Sum along horizontal axis to find rows with significant line content
    row_sums = np.sum(horizontal_mask, axis=1)
    threshold = horizontal_mask.shape[1] * 0.2  # at least 20% of width

    line_rows = np.where(row_sums > threshold * 255)[0]

    if len(line_rows) == 0:
        return []

    # Group nearby rows into single line positions
    merge_distance = max(int(img_height * 0.02), 3)
    groups = []
    current_group = [line_rows[0]]

    for i in range(1, len(line_rows)):
        if line_rows[i] - line_rows[i - 1] <= merge_distance:
            current_group.append(line_rows[i])
        else:
            groups.append(current_group)
            current_group = [line_rows[i]]
    groups.append(current_group)

    # Take the median y of each group
    line_positions = [int(np.median(g)) for g in groups]

    # Filter out lines too close to edges (within 5% of top/bottom)
    edge_margin = int(img_height * 0.05)
    line_positions = [
        y for y in line_positions
        if edge_margin < y < (img_height - edge_margin)
    ]

    return sorted(line_positions)


# ---------------------------------------------------------------------------
# Region cropping
# ---------------------------------------------------------------------------

def crop_regions(image, regions: dict) -> dict:
    """
    Crop the image into the detected regions.

    Args:
        image: PIL Image or numpy ndarray.
        regions: Dict with "bounding_boxes" key mapping region names
                 to (x, y, w, h) tuples.

    Returns:
        Dict mapping region name to cropped PIL Image.
        Only includes regions with valid (non-zero area) bounding boxes.
    """
    pil_img = _to_pil(image)
    bboxes = regions.get("bounding_boxes", {})
    cropped = {}

    for name, (x, y, w, h) in bboxes.items():
        if w <= 0 or h <= 0:
            continue
        # PIL crop uses (left, upper, right, lower)
        box = (x, y, x + w, y + h)
        cropped[name] = pil_img.crop(box)

    return cropped


# ---------------------------------------------------------------------------
# Saved-layout application
# ---------------------------------------------------------------------------

# Maximum relative difference in aspect ratio before falling back to detection.
_ASPECT_RATIO_THRESHOLD = 0.30


def _apply_saved_layout(
    saved_layout: dict | None,
    image_size: tuple[int, int],
) -> dict | None:
    """Convert a normalized saved layout back to absolute bounding boxes.

    Returns a dict mapping region name to (x, y, w, h) in pixels, or None
    if the saved layout is absent or incompatible with the current image.

    Compatibility check: if the image's aspect ratio differs from the saved
    layout's by more than 30%, the layout is considered incompatible and
    None is returned so the caller can fall back to detection.
    """
    if saved_layout is None:
        return None

    img_w, img_h = image_size
    if img_h == 0:
        return None

    current_ratio = img_w / img_h
    saved_ratio = saved_layout.get("image_size_ratio", 0)
    if saved_ratio <= 0:
        return None

    # Check aspect-ratio compatibility
    ratio_diff = abs(current_ratio - saved_ratio) / saved_ratio
    if ratio_diff > _ASPECT_RATIO_THRESHOLD:
        return None

    _LAYOUT_TO_SEG = {
        "header_region": "header",
        "items_region": "line_items",
        "totals_region": "totals",
    }

    bboxes: dict[str, tuple[int, int, int, int]] = {}
    for layout_key, seg_name in _LAYOUT_TO_SEG.items():
        region = saved_layout.get(layout_key)
        if region is None:
            continue
        x = int(region["x"] * img_w)
        y = int(region["y"] * img_h)
        w = int(region["w"] * img_w)
        h = int(region["h"] * img_h)
        bboxes[seg_name] = (x, y, w, h)

    if not bboxes:
        return None

    return bboxes


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def segment_invoice(image, *, saved_layout: dict | None = None) -> dict:
    """
    Full ROI segmentation orchestrator.

    1. If a saved_layout is provided and aspect-ratio-compatible, use it.
    2. Otherwise, run detect_regions for morphological / heuristic detection.
    3. Crop the image into detected regions.
    4. Always include the full image as a fallback.

    Args:
        image: PIL Image or numpy ndarray.
        saved_layout: Optional normalized layout descriptor from supplier
            memory.  When provided and compatible, skips detection.

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
    layout_bboxes = _apply_saved_layout(saved_layout, (width, height))

    if layout_bboxes is not None:
        regions = {
            "bounding_boxes": layout_bboxes,
            "regions_detected": True,
            "method": "saved_layout",
        }
    else:
        regions = detect_regions(image)

    result = {
        "header": None,
        "line_items": None,
        "totals": None,
        "full": pil_img,
        "regions_detected": regions["regions_detected"],
        "bounding_boxes": regions["bounding_boxes"],
        "method": regions.get("method", "none"),
    }

    if not regions["regions_detected"]:
        return result

    cropped = crop_regions(image, regions)
    for name in ("header", "line_items", "totals"):
        if name in cropped:
            result[name] = cropped[name]

    return result
