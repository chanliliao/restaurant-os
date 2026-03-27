"""
Orientation & Skew Correction module.

Provides functions to auto-fix rotated, tilted, and perspective-distorted
images as the first step in the preprocessing pipeline.
"""

import numpy as np
from PIL import Image, ExifTags
import cv2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_pil(image) -> Image.Image:
    """Convert numpy array to PIL Image if needed."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return Image.fromarray(image, mode="L")
        # BGR (OpenCV) -> RGB (PIL)
        return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if isinstance(image, Image.Image):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


def _to_cv(image) -> np.ndarray:
    """Convert PIL Image to BGR numpy array if needed."""
    if isinstance(image, Image.Image):
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if isinstance(image, np.ndarray):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


# ---------------------------------------------------------------------------
# 1. EXIF-based orientation fix
# ---------------------------------------------------------------------------

# Map EXIF orientation tag values to PIL transpose operations
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
    """
    Detect and correct 90/180/270-degree rotations using EXIF data.

    If the image has an EXIF orientation tag, apply the corresponding
    transpose to produce a correctly-oriented image. If no EXIF data
    is present, the image is returned unchanged.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Corrected PIL Image.
    """
    pil_img = _to_pil(image)

    try:
        exif = pil_img.getexif()
    except Exception:
        return pil_img

    if not exif:
        return pil_img

    # Find the orientation tag key
    orientation_key = None
    for tag_id, tag_name in ExifTags.TAGS.items():
        if tag_name == "Orientation":
            orientation_key = tag_id
            break

    if orientation_key is None or orientation_key not in exif:
        return pil_img

    orientation_value = exif[orientation_key]
    transpose_op = _EXIF_TRANSPOSE_MAP.get(orientation_value)

    if transpose_op is not None:
        pil_img = pil_img.transpose(transpose_op)

    return pil_img


# ---------------------------------------------------------------------------
# 2. Deskew via Hough line transform
# ---------------------------------------------------------------------------

def deskew(image) -> Image.Image:
    """
    Detect tilt angle using Hough line transform and rotate to align text
    horizontally.

    The function finds dominant near-horizontal lines in the image and
    computes the median tilt angle, then rotates to correct it.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Deskewed PIL Image.
    """
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)

    # Convert to grayscale
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # Edge detection
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Hough line detection
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=gray.shape[1] // 8,
        maxLineGap=20,
    )

    if lines is None or len(lines) == 0:
        return pil_img

    # Compute angles of detected lines
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        # Only consider near-horizontal lines (within 45 degrees of horizontal)
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return pil_img

    # Use median angle to be robust to outliers
    median_angle = float(np.median(angles))

    # Skip if angle is negligibly small
    if abs(median_angle) < 0.1:
        return pil_img

    # Rotate the image to correct the tilt
    (h, w) = cv_img.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)

    # Compute new bounding dimensions
    cos_a = abs(rotation_matrix[0, 0])
    sin_a = abs(rotation_matrix[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    rotation_matrix[0, 2] += (new_w - w) / 2
    rotation_matrix[1, 2] += (new_h - h) / 2

    rotated = cv2.warpAffine(
        cv_img, rotation_matrix, (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    return _to_pil(rotated)


# ---------------------------------------------------------------------------
# 3. Perspective correction
# ---------------------------------------------------------------------------

def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order four points as: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left has smallest sum
    rect[2] = pts[np.argmax(s)]   # bottom-right has largest sum
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]   # top-right has smallest difference
    rect[3] = pts[np.argmax(d)]   # bottom-left has largest difference
    return rect


def correct_perspective(image) -> Image.Image:
    """
    Detect trapezoidal distortion and apply perspective warp to produce a
    flat, rectangular image.

    Looks for the largest quadrilateral contour in the image. If found,
    applies a perspective transform to straighten it. If no suitable
    contour is found, the image is returned unchanged.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Perspective-corrected PIL Image.
    """
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)

    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold to create a binary image highlighting the document
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2,
    )

    # Morphological close to connect edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    # Find contours
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )

    if not contours:
        return pil_img

    # Sort by area descending and look for a quadrilateral
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    image_area = gray.shape[0] * gray.shape[1]

    target_quad = None
    for contour in contours[:5]:  # check top-5 largest
        area = cv2.contourArea(contour)
        # Contour should be at least 25% of image area to be the document
        if area < image_area * 0.25:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            target_quad = approx
            break

    if target_quad is None:
        return pil_img

    # Order the points and compute destination rectangle
    src_pts = _order_points(target_quad.reshape(4, 2).astype("float32"))

    # Compute width and height of the destination rectangle
    width_top = np.linalg.norm(src_pts[1] - src_pts[0])
    width_bottom = np.linalg.norm(src_pts[2] - src_pts[3])
    max_width = int(max(width_top, width_bottom))

    height_left = np.linalg.norm(src_pts[3] - src_pts[0])
    height_right = np.linalg.norm(src_pts[2] - src_pts[1])
    max_height = int(max(height_left, height_right))

    if max_width < 10 or max_height < 10:
        return pil_img

    dst_pts = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1],
    ], dtype="float32")

    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(cv_img, matrix, (max_width, max_height))

    return _to_pil(warped)


# ---------------------------------------------------------------------------
# 4. Orchestrator
# ---------------------------------------------------------------------------

def auto_orient(image) -> Image.Image:
    """
    Run the full orientation correction pipeline:
    1. Fix EXIF-based rotation
    2. Deskew (Hough line tilt correction)
    3. Perspective correction

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Fully corrected PIL Image.
    """
    result = fix_orientation(image)
    result = deskew(result)
    result = correct_perspective(result)
    return result
