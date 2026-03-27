"""
Image Quality Assessment module.

Measures brightness, contrast, blur, noise, and resolution to produce
a structured quality report.  Designed to run after orientation correction
and before any enhancement steps in the preprocessing pipeline.
"""

import numpy as np
from PIL import Image
import cv2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_gray(image) -> np.ndarray:
    """Convert PIL Image or numpy array to a single-channel grayscale array."""
    if isinstance(image, Image.Image):
        return np.array(image.convert("L"))
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return image
        # Assume BGR (OpenCV convention)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise TypeError(f"Unsupported image type: {type(image)}")


def _image_dimensions(image):
    """Return (width, height) regardless of input type."""
    if isinstance(image, Image.Image):
        return image.size  # (width, height)
    if isinstance(image, np.ndarray):
        h, w = image.shape[:2]
        return (w, h)
    raise TypeError(f"Unsupported image type: {type(image)}")


# ---------------------------------------------------------------------------
# Individual metric functions
# ---------------------------------------------------------------------------

def _measure_brightness(gray: np.ndarray) -> dict:
    """Mean pixel intensity.  Flag if < 80 (dark) or > 200 (washed out)."""
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
    """Standard deviation of pixel values.  Flag if < 30 (low contrast)."""
    value = float(np.std(gray))
    issue = value < 30

    if issue:
        detail = f"Low contrast (std dev {value:.1f})"
    else:
        detail = f"Contrast is acceptable (std dev {value:.1f})"

    return {"value": value, "issue": issue, "detail": detail}


def _measure_blur(gray: np.ndarray) -> dict:
    """Laplacian variance.  Flag if < 100 (blurry)."""
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    value = float(laplacian.var())
    issue = value < 100

    if issue:
        detail = f"Image is blurry (Laplacian variance {value:.1f})"
    else:
        detail = f"Sharpness is acceptable (Laplacian variance {value:.1f})"

    return {"value": value, "issue": issue, "detail": detail}


def _measure_noise(gray: np.ndarray) -> dict:
    """
    Estimate noise by measuring high-frequency energy.

    Estimate noise using the robust median estimator on the Laplacian.
    This approach (from Immerkaer 1996) is less sensitive to image content
    than simple high-pass subtraction.  A value above 12 indicates
    excessive noise.
    """
    # Robust noise estimation: sigma = median(|Laplacian|) * sqrt(pi/2) / 6
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    median_abs = float(np.median(np.abs(laplacian)))
    value = median_abs * np.sqrt(np.pi / 2) / 6.0
    issue = bool(value > 12)

    if issue:
        detail = f"Excessive noise detected (high-freq std dev {value:.1f})"
    else:
        detail = f"Noise level is acceptable (high-freq std dev {value:.1f})"

    return {"value": value, "issue": issue, "detail": detail}


def _measure_resolution(width: int, height: int) -> dict:
    """Flag if width or height < 500 pixels."""
    issue = width < 500 or height < 500

    if issue:
        detail = f"Resolution too low ({width}x{height}); minimum 500px on each side"
    else:
        detail = f"Resolution is acceptable ({width}x{height})"

    return {"width": width, "height": height, "issue": issue, "detail": detail}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_quality(image) -> dict:
    """
    Analyze image quality and return a structured report.

    Args:
        image: PIL Image or numpy ndarray (BGR or grayscale).

    Returns:
        Dict with keys: brightness, contrast, blur, noise, resolution,
        overall_quality ("good" | "fair" | "poor"), and issues (list of str).
    """
    gray = _to_gray(image)
    width, height = _image_dimensions(image)

    brightness = _measure_brightness(gray)
    contrast = _measure_contrast(gray)
    blur = _measure_blur(gray)
    noise = _measure_noise(gray)
    resolution = _measure_resolution(width, height)

    # Collect issue descriptions
    issues = []
    for metric in [brightness, contrast, blur, noise, resolution]:
        if metric["issue"]:
            issues.append(metric["detail"])

    # Classify overall quality
    issue_count = len(issues)
    if issue_count >= 2:
        overall_quality = "poor"
    elif issue_count == 1:
        overall_quality = "fair"
    else:
        overall_quality = "good"

    return {
        "brightness": brightness,
        "contrast": contrast,
        "blur": blur,
        "noise": noise,
        "resolution": resolution,
        "overall_quality": overall_quality,
        "issues": issues,
    }
