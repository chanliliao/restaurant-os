"""
Selective Image Processing module.

Applies only the enhancements that the quality report flags as needed,
then produces two image variants (orientation-corrected original and
fully preprocessed) for downstream consumption.
"""

import numpy as np
from PIL import Image, ImageFilter
import cv2

from .orientation import auto_orient
from .analyzer import analyze_quality


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
        if image.mode == "L":
            return np.array(image)
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if isinstance(image, np.ndarray):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


# ---------------------------------------------------------------------------
# Individual enhancement functions
# ---------------------------------------------------------------------------

def enhance_contrast(image) -> Image.Image:
    """
    Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    to improve contrast in low-contrast images.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Contrast-enhanced PIL Image.
    """
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)

    if cv_img.ndim == 2:
        # Grayscale
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(cv_img)
        return Image.fromarray(enhanced, mode="L")

    # Color image: apply CLAHE to the L channel in LAB color space
    lab = cv2.cvtColor(cv_img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)

    lab = cv2.merge([l_channel, a_channel, b_channel])
    result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    return _to_pil(result)


def sharpen(image) -> Image.Image:
    """
    Apply an unsharp mask sharpening filter to improve blurry images.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Sharpened PIL Image.
    """
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)

    # Unsharp mask: original + alpha * (original - blurred)
    if cv_img.ndim == 2:
        blurred = cv2.GaussianBlur(cv_img, (0, 0), sigmaX=3)
        sharpened = cv2.addWeighted(cv_img, 1.5, blurred, -0.5, 0)
        return Image.fromarray(sharpened, mode="L")

    blurred = cv2.GaussianBlur(cv_img, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(cv_img, 1.5, blurred, -0.5, 0)
    return _to_pil(sharpened)


def denoise(image) -> Image.Image:
    """
    Apply Non-Local Means Denoising to reduce noise while preserving edges.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Denoised PIL Image.
    """
    pil_img = _to_pil(image)
    cv_img = _to_cv(pil_img)

    if cv_img.ndim == 2:
        denoised = cv2.fastNlMeansDenoising(cv_img, None, h=10,
                                              templateWindowSize=7,
                                              searchWindowSize=21)
        return Image.fromarray(denoised, mode="L")

    denoised = cv2.fastNlMeansDenoisingColored(cv_img, None, 10, 10, 7, 21)
    return _to_pil(denoised)


def upscale(image, target_min: int = 1000) -> Image.Image:
    """
    Upscale an image using Lanczos resampling so that its smallest
    dimension is at least target_min pixels.

    If both dimensions already meet the target, the image is returned
    unchanged.

    Args:
        image: PIL Image or numpy ndarray.
        target_min: Minimum pixel count for the smallest dimension.

    Returns:
        Upscaled PIL Image.
    """
    pil_img = _to_pil(image)
    width, height = pil_img.size

    min_dim = min(width, height)
    if min_dim >= target_min:
        return pil_img

    scale = target_min / min_dim
    new_width = int(width * scale)
    new_height = int(height * scale)

    return pil_img.resize((new_width, new_height), Image.LANCZOS)


def remove_stripes(image) -> Image.Image:
    """
    Remove horizontal striped backgrounds (alternating row colors)
    common on pre-printed invoice forms.

    Uses adaptive thresholding to separate dark text from the
    lighter striped background, producing a clean binary image
    that OCR can read much more accurately.

    Args:
        image: PIL Image or numpy ndarray (should be grayscale).

    Returns:
        Cleaned PIL Image with stripes removed (grayscale).
    """
    pil_img = _to_pil(image)
    gray = np.array(pil_img.convert("L"))

    # Adaptive threshold separates text from background regardless
    # of local brightness variations (stripes, watermarks, etc.)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,  # Large block to smooth over stripe width
        C=15,          # Bias toward keeping text dark
    )

    return Image.fromarray(binary, mode="L")


def to_grayscale(image) -> Image.Image:
    """
    Convert image to grayscale.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Grayscale PIL Image (mode "L").
    """
    pil_img = _to_pil(image)
    return pil_img.convert("L")


# ---------------------------------------------------------------------------
# Selective processing pipeline
# ---------------------------------------------------------------------------

def selective_process(image, quality_report: dict) -> Image.Image:
    """
    Apply only the enhancements that the quality report flags as needed.

    Processing order:
    1. Upscale (if resolution issue)
    2. Denoise (if noise issue)
    3. Enhance contrast (if contrast issue)
    4. Sharpen (if blur issue — stronger for severe blur)
    5. Convert to grayscale (always)
    6. Remove stripes (always — handles form backgrounds, watermarks)

    Args:
        image: PIL Image or numpy ndarray.
        quality_report: Dict returned by analyze_quality().

    Returns:
        Processed PIL Image (grayscale, stripes removed).
    """
    result = _to_pil(image)

    if quality_report["resolution"]["issue"]:
        result = upscale(result)

    if quality_report["noise"]["issue"]:
        result = denoise(result)

    if quality_report["contrast"]["issue"]:
        result = enhance_contrast(result)

    if quality_report["blur"]["issue"]:
        blur_val = quality_report["blur"].get("value", 100)
        if blur_val < 50:
            # Severe blur: apply sharpening twice for stronger effect
            result = sharpen(result)
            result = sharpen(result)
        else:
            result = sharpen(result)

    result = to_grayscale(result)
    return result


def prepare_alternative_variant(image, quality_report: dict) -> Image.Image:
    """
    Produce a differently-processed image variant for retry scanning.

    Uses more aggressive parameters than the primary pipeline:
    - Higher CLAHE clip limit (4.0 vs 2.0) for stronger contrast
    - Stronger sharpening (2.0 weight vs 1.5)
    - Inverted grayscale (white text on black background)

    Args:
        image: PIL Image or numpy ndarray.
        quality_report: Dict returned by analyze_quality().

    Returns:
        Alternative processed PIL Image (inverted grayscale).
    """
    result = _to_pil(image)

    if quality_report["resolution"]["issue"]:
        result = upscale(result)

    if quality_report["noise"]["issue"]:
        result = denoise(result)

    # Aggressive contrast enhancement
    pil_img = result
    cv_img = _to_cv(pil_img)
    if cv_img.ndim == 2:
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(cv_img)
        result = Image.fromarray(enhanced, mode="L")
    else:
        lab = cv2.cvtColor(cv_img, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        l_channel = clahe.apply(l_channel)
        lab = cv2.merge([l_channel, a_channel, b_channel])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        result = _to_pil(enhanced)

    # Stronger sharpening
    cv_img = _to_cv(result)
    blurred = cv2.GaussianBlur(cv_img, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(cv_img, 2.0, blurred, -1.0, 0)
    result = _to_pil(sharpened)

    # Convert to grayscale and invert
    result = result.convert("L")
    result = Image.eval(result, lambda x: 255 - x)

    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def prepare_variants(image) -> dict:
    """
    Full preprocessing orchestrator.

    1. Run auto_orient (orientation/skew/perspective correction)
    2. Run analyze_quality on the oriented image
    3. Keep oriented image as "original" variant
    4. Run selective_process to produce "preprocessed" variant
    5. Return both variants plus the quality report

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Dict with keys:
            - "original": PIL Image (orientation-corrected only)
            - "preprocessed": PIL Image (fully processed, grayscale)
            - "quality_report": dict from analyze_quality()
    """
    oriented = auto_orient(image)
    quality_report = analyze_quality(oriented)
    preprocessed = selective_process(oriented, quality_report)

    return {
        "original": oriented,
        "preprocessed": preprocessed,
        "quality_report": quality_report,
    }
