"""
Image preprocessing orchestrator wrapped as a LangGraph-compatible agent tool.
"""

from __future__ import annotations

import base64
import io
import logging

import cv2
import numpy as np
from PIL import Image, ExifTags
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic input schema (LangGraph-compatible tool interface)
# ---------------------------------------------------------------------------


class ImageProcessorInput(BaseModel):
    """Input schema for the image preprocessing agent tool.

    The LLM populates this model when it decides to invoke the tool.
    Call `.model_json_schema()` to get the tool schema to send to GLM.
    """

    image_b64: str = Field(
        description="Base64-encoded image bytes (JPEG or PNG)."
    )
    saved_layout: dict | None = Field(
        default=None,
        description=(
            "Optional normalized layout descriptor from supplier memory. "
            "When provided and aspect-ratio compatible, skips region detection."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers (shared by multiple sub-modules below)
# ---------------------------------------------------------------------------


def _to_pil(image) -> Image.Image:
    """Convert numpy array or PIL Image to PIL Image."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return Image.fromarray(image, mode="L")
        return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if isinstance(image, Image.Image):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


def _to_cv(image) -> np.ndarray:
    """Convert PIL Image or numpy array to BGR numpy array."""
    if isinstance(image, Image.Image):
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if isinstance(image, np.ndarray):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


def _to_gray(image) -> np.ndarray:
    """Convert any image input to a single-channel grayscale array."""
    if isinstance(image, Image.Image):
        return np.array(image.convert("L"))
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise TypeError(f"Unsupported image type: {type(image)}")


def _image_dimensions(image) -> tuple[int, int]:
    """Return (width, height) regardless of input type."""
    if isinstance(image, Image.Image):
        return image.size
    if isinstance(image, np.ndarray):
        h, w = image.shape[:2]
        return (w, h)
    raise TypeError(f"Unsupported image type: {type(image)}")


def _pil_to_b64(image: Image.Image, fmt: str = "JPEG") -> str:
    """Encode a PIL Image to a base64 string."""
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# Analyzer (from preprocessing/analyzer.py)
# ---------------------------------------------------------------------------


def _measure_brightness(gray: np.ndarray) -> dict:
    value = float(np.mean(gray))
    issue = value < 80 or value > 200
    if value < 80:
        detail = f"Image is too dark (mean brightness {value:.1f}/255)"
    elif value > 200:
        detail = f"Image is washed out (mean brightness {value:.1f}/255)"
    else:
        detail = f"Brightness is acceptable ({value:.1f}/255)"
    return {"value": value, "issue": issue, "detail": detail}


def _measure_contrast(gray: np.ndarray) -> dict:
    value = float(np.std(gray))
    issue = value < 30
    detail = (
        f"Low contrast (std dev {value:.1f})"
        if issue
        else f"Contrast is acceptable (std dev {value:.1f})"
    )
    return {"value": value, "issue": issue, "detail": detail}


def _measure_blur(gray: np.ndarray) -> dict:
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    value = float(laplacian.var())
    issue = value < 100
    detail = (
        f"Image is blurry (Laplacian variance {value:.1f})"
        if issue
        else f"Sharpness is acceptable (Laplacian variance {value:.1f})"
    )
    return {"value": value, "issue": issue, "detail": detail}


def _measure_noise(gray: np.ndarray) -> dict:
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    median_abs = float(np.median(np.abs(laplacian)))
    value = median_abs * np.sqrt(np.pi / 2) / 6.0
    issue = bool(value > 12)
    detail = (
        f"Excessive noise detected (high-freq std dev {value:.1f})"
        if issue
        else f"Noise level is acceptable (high-freq std dev {value:.1f})"
    )
    return {"value": value, "issue": issue, "detail": detail}


def _measure_resolution(width: int, height: int) -> dict:
    issue = width < 500 or height < 500
    detail = (
        f"Resolution too low ({width}x{height}); minimum 500px on each side"
        if issue
        else f"Resolution is acceptable ({width}x{height})"
    )
    return {"width": width, "height": height, "issue": issue, "detail": detail}


def analyze_quality(image) -> dict:
    """Analyze image quality; return structured report with brightness, contrast,
    blur, noise, resolution, overall_quality, and issues list."""
    gray = _to_gray(image)
    width, height = _image_dimensions(image)

    brightness = _measure_brightness(gray)
    contrast = _measure_contrast(gray)
    blur = _measure_blur(gray)
    noise = _measure_noise(gray)
    resolution = _measure_resolution(width, height)

    issues = [
        m["detail"]
        for m in [brightness, contrast, blur, noise, resolution]
        if m["issue"]
    ]
    issue_count = len(issues)
    overall_quality = "poor" if issue_count >= 2 else "fair" if issue_count == 1 else "good"

    return {
        "brightness": brightness,
        "contrast": contrast,
        "blur": blur,
        "noise": noise,
        "resolution": resolution,
        "overall_quality": overall_quality,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Orientation (from preprocessing/orientation.py)
# ---------------------------------------------------------------------------

_EXIF_TRANSPOSE_MAP = {
    2: Image.FLIP_LEFT_RIGHT,
    3: Image.ROTATE_180,
    4: Image.FLIP_TOP_BOTTOM,
    5: Image.TRANSPOSE,
    6: Image.ROTATE_270,
    7: Image.TRANSVERSE,
    8: Image.ROTATE_90,
}


def fix_orientation(image) -> Image.Image:
    """Correct 90/180/270-degree rotations using EXIF data."""
    pil_img = _to_pil(image)
    try:
        exif = pil_img.getexif()
    except Exception:
        return pil_img

    if not exif:
        return pil_img

    orientation_key = next(
        (tag_id for tag_id, name in ExifTags.TAGS.items() if name == "Orientation"),
        None,
    )
    if orientation_key is None or orientation_key not in exif:
        return pil_img

    transpose_op = _EXIF_TRANSPOSE_MAP.get(exif[orientation_key])
    if transpose_op is not None:
        pil_img = pil_img.transpose(transpose_op)
    return pil_img


def deskew(image) -> Image.Image:
    """Detect tilt angle via Hough lines and rotate to align text horizontally."""
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180, threshold=100,
        minLineLength=gray.shape[1] // 8, maxLineGap=20,
    )
    if lines is None or len(lines) == 0:
        return pil_img

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        if abs(dx) < 1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, dx))
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return pil_img

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.1:
        return pil_img

    (h, w) = cv_img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2
    rotated = cv2.warpAffine(
        cv_img, M, (new_w, new_h),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )
    return _to_pil(rotated)


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def correct_perspective(image) -> Image.Image:
    """Detect trapezoidal distortion and apply perspective warp to flatten the document."""
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return pil_img

    image_area = gray.shape[0] * gray.shape[1]
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    target_quad = None
    for contour in contours[:5]:
        if cv2.contourArea(contour) < image_area * 0.25:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            target_quad = approx
            break

    if target_quad is None:
        return pil_img

    src_pts = _order_points(target_quad.reshape(4, 2).astype("float32"))
    max_width = int(max(
        np.linalg.norm(src_pts[1] - src_pts[0]),
        np.linalg.norm(src_pts[2] - src_pts[3]),
    ))
    max_height = int(max(
        np.linalg.norm(src_pts[3] - src_pts[0]),
        np.linalg.norm(src_pts[2] - src_pts[1]),
    ))

    if max_width < 10 or max_height < 10:
        return pil_img

    dst_pts = np.array([
        [0, 0], [max_width - 1, 0],
        [max_width - 1, max_height - 1], [0, max_height - 1],
    ], dtype="float32")
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(cv_img, matrix, (max_width, max_height))
    return _to_pil(warped)


def auto_orient(image) -> Image.Image:
    """Run the full orientation pipeline: EXIF fix → deskew → perspective correction."""
    result = fix_orientation(image)
    result = deskew(result)
    result = correct_perspective(result)
    return result


# ---------------------------------------------------------------------------
# Segmentation (from preprocessing/segmentation.py)
# ---------------------------------------------------------------------------

_MIN_DIMENSION = 50
_ASPECT_RATIO_THRESHOLD = 0.30


def _find_line_y_positions(horizontal_mask: np.ndarray, img_height: int) -> list[int]:
    row_sums = np.sum(horizontal_mask, axis=1)
    threshold = horizontal_mask.shape[1] * 0.2
    line_rows = np.where(row_sums > threshold * 255)[0]
    if len(line_rows) == 0:
        return []

    merge_distance = max(int(img_height * 0.02), 3)
    groups: list[list[int]] = []
    current_group = [int(line_rows[0])]
    for i in range(1, len(line_rows)):
        if line_rows[i] - line_rows[i - 1] <= merge_distance:
            current_group.append(int(line_rows[i]))
        else:
            groups.append(current_group)
            current_group = [int(line_rows[i])]
    groups.append(current_group)

    line_positions = [int(np.median(g)) for g in groups]
    edge_margin = int(img_height * 0.05)
    return sorted(y for y in line_positions if edge_margin < y < img_height - edge_margin)


def detect_regions(image) -> dict:
    """Detect bounding boxes for header, line_items, and totals regions."""
    pil_img = _to_pil(image)
    width, height = pil_img.size

    if width < _MIN_DIMENSION or height < _MIN_DIMENSION:
        return {"bounding_boxes": {}, "regions_detected": False, "method": "none"}

    gray = _to_gray(image)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 10,
    )
    kernel_width = max(width // 3, 30)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    line_ys = _find_line_y_positions(horizontal_lines, height)

    if len(line_ys) >= 2:
        top_divider, bottom_divider = line_ys[0], line_ys[-1]
        min_region = int(height * 0.10)
        if (top_divider >= min_region
                and (bottom_divider - top_divider) >= min_region
                and (height - bottom_divider) >= min_region):
            return {
                "bounding_boxes": {
                    "header": (0, 0, width, top_divider),
                    "line_items": (0, top_divider, width, bottom_divider - top_divider),
                    "totals": (0, bottom_divider, width, height - bottom_divider),
                },
                "regions_detected": True,
                "method": "lines",
            }

    h25, h75 = int(height * 0.25), int(height * 0.75)
    return {
        "bounding_boxes": {
            "header": (0, 0, width, h25),
            "line_items": (0, h25, width, h75 - h25),
            "totals": (0, h75, width, height - h75),
        },
        "regions_detected": True,
        "method": "heuristic",
    }


def crop_regions(image, regions: dict) -> dict[str, Image.Image]:
    """Crop the PIL image into detected regions; return only non-zero-area crops."""
    pil_img = _to_pil(image)
    return {
        name: pil_img.crop((x, y, x + w, y + h))
        for name, (x, y, w, h) in regions.get("bounding_boxes", {}).items()
        if w > 0 and h > 0
    }


def _apply_saved_layout(
    saved_layout: dict | None,
    image_size: tuple[int, int],
) -> dict | None:
    if saved_layout is None:
        return None
    img_w, img_h = image_size
    if img_h == 0:
        return None
    current_ratio = img_w / img_h
    saved_ratio = saved_layout.get("image_size_ratio", 0)
    if saved_ratio <= 0:
        return None
    if abs(current_ratio - saved_ratio) / saved_ratio > _ASPECT_RATIO_THRESHOLD:
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
        bboxes[seg_name] = (
            int(region["x"] * img_w),
            int(region["y"] * img_h),
            int(region["w"] * img_w),
            int(region["h"] * img_h),
        )
    return bboxes or None


def segment_invoice(image, *, saved_layout: dict | None = None) -> dict:
    """Full ROI segmentation: saved layout → morphological detection → heuristic fallback."""
    pil_img = _to_pil(image)
    width, height = pil_img.size

    layout_bboxes = _apply_saved_layout(saved_layout, (width, height))
    if layout_bboxes is not None:
        regions = {
            "bounding_boxes": layout_bboxes,
            "regions_detected": True,
            "method": "saved_layout",
        }
    else:
        regions = detect_regions(image)

    result: dict = {
        "header": None,
        "line_items": None,
        "totals": None,
        "full": pil_img,
        "regions_detected": regions["regions_detected"],
        "bounding_boxes": regions["bounding_boxes"],
        "method": regions.get("method", "none"),
    }
    if regions["regions_detected"]:
        cropped = crop_regions(image, regions)
        for name in ("header", "line_items", "totals"):
            result[name] = cropped.get(name)

    return result


# ---------------------------------------------------------------------------
# Enhancement pipeline (from preprocessing/processor.py)
# ---------------------------------------------------------------------------


def enhance_contrast(image) -> Image.Image:
    """CLAHE contrast enhancement on the L channel (LAB) or grayscale."""
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    if cv_img.ndim == 2:
        return Image.fromarray(clahe.apply(cv_img), mode="L")

    lab = cv2.cvtColor(cv_img, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    lab = cv2.merge([clahe.apply(l_ch), a_ch, b_ch])
    return _to_pil(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR))


def sharpen(image) -> Image.Image:
    """Unsharp-mask sharpening (1.5× original, −0.5× blurred)."""
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)
    blurred = cv2.GaussianBlur(cv_img, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(cv_img, 1.5, blurred, -0.5, 0)
    if cv_img.ndim == 2:
        return Image.fromarray(sharpened, mode="L")
    return _to_pil(sharpened)


def denoise(image) -> Image.Image:
    """Non-local means denoising."""
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)
    if cv_img.ndim == 2:
        return Image.fromarray(
            cv2.fastNlMeansDenoising(cv_img, None, h=10, templateWindowSize=7, searchWindowSize=21),
            mode="L",
        )
    return _to_pil(cv2.fastNlMeansDenoisingColored(cv_img, None, 10, 10, 7, 21))


def upscale(image, target_min: int = 1000) -> Image.Image:
    """Upscale using Lanczos so the smallest dimension ≥ target_min pixels."""
    pil_img = _to_pil(image)
    width, height = pil_img.size
    min_dim = min(width, height)
    if min_dim >= target_min:
        return pil_img
    scale = target_min / min_dim
    return pil_img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)


def remove_stripes(image) -> Image.Image:
    """Adaptive threshold to eliminate horizontal striped form backgrounds."""
    pil_img = _to_pil(image)
    gray = np.array(pil_img.convert("L"))
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=31, C=15,
    )
    return Image.fromarray(binary, mode="L")


def selective_process(image, quality_report: dict) -> Image.Image:
    """Apply only the enhancements flagged as needed by the quality report."""
    result = _to_pil(image)

    if quality_report["resolution"]["issue"]:
        result = upscale(result)
    if quality_report["noise"]["issue"]:
        result = denoise(result)
    if quality_report["contrast"]["issue"]:
        result = enhance_contrast(result)
    if quality_report["blur"]["issue"]:
        blur_val = quality_report["blur"].get("value", 100)
        result = sharpen(result)
        if blur_val < 50:
            result = sharpen(result)  # Double sharpen for severe blur

    result = result.convert("L")
    return result


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def preprocess_image(inp: ImageProcessorInput) -> dict:
    """
    Execute the full preprocessing pipeline as an agent tool.

    Pipeline:
    1. Decode base64 image
    2. Auto-orient (EXIF fix → deskew → perspective correction)
    3. Analyze quality
    4. Selective enhancement → grayscale preprocessed variant
    5. Segment into regions (header, line_items, totals, full)
    6. Return base64-encoded variants + quality report + segmentation metadata

    Args:
        inp: Validated ImageProcessorInput from the LLM tool call.

    Returns:
        Dict with:
            - original_b64: orientation-corrected image (JPEG base64)
            - preprocessed_b64: fully processed grayscale image (JPEG base64)
            - quality_report: dict from analyze_quality()
            - segmentation: dict with region names, bounding_boxes, method
    """
    image_bytes = base64.b64decode(inp.image_b64)
    image = Image.open(io.BytesIO(image_bytes))

    oriented = auto_orient(image)
    quality_report = analyze_quality(oriented)
    preprocessed = selective_process(oriented, quality_report)

    seg_result = segment_invoice(oriented, saved_layout=inp.saved_layout)
    segmentation_meta = {
        "regions_detected": seg_result["regions_detected"],
        "method": seg_result["method"],
        "bounding_boxes": seg_result["bounding_boxes"],
    }

    logger.info(
        "preprocess_image complete — quality=%s regions_detected=%s method=%s",
        quality_report["overall_quality"],
        seg_result["regions_detected"],
        seg_result["method"],
    )

    return {
        "original_b64": _pil_to_b64(oriented),
        "preprocessed_b64": _pil_to_b64(preprocessed),
        "quality_report": quality_report,
        "segmentation": segmentation_meta,
    }
