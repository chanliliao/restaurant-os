"""
OCR Pre-Pass module.

Extracts text from preprocessed invoice images using Tesseract OCR.
The extracted text serves as supplementary data for Claude, giving the
model two sources of information (image + text) to cross-reference.

Handles graceful degradation when Tesseract is not installed.
"""

import logging

import numpy as np
import pytesseract
from pytesseract import TesseractNotFoundError
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_pil(image) -> Image.Image:
    """Convert numpy array to PIL Image if needed."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return Image.fromarray(image, mode="L")
        return Image.fromarray(image)
    if isinstance(image, Image.Image):
        return image
    raise TypeError(f"Unsupported image type: {type(image)}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text(image) -> str:
    """
    Run Tesseract OCR on a single image and return the raw text.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Extracted text as a string. Empty string if Tesseract fails or
        is not installed.
    """
    try:
        pil_image = _to_pil(image)
        return pytesseract.image_to_string(pil_image)
    except TesseractNotFoundError:
        logger.warning(
            "Tesseract is not installed or not in PATH. "
            "OCR pre-pass will be skipped."
        )
        return ""
    except Exception:
        logger.warning("OCR extraction failed.", exc_info=True)
        return ""


def extract_text_from_regions(regions_dict: dict) -> dict:
    """
    Run OCR on each region from a segment_invoice() result.

    Args:
        regions_dict: Dict with keys like "header", "line_items", "totals",
            "full". Values are PIL Images or None.

    Returns:
        Dict mapping region_name -> extracted text string.
        Regions with None values get an empty string.
    """
    results = {}
    for region_name, image in regions_dict.items():
        if image is None:
            results[region_name] = ""
        else:
            results[region_name] = extract_text(image)
    return results


def ocr_prepass(image) -> str:
    """
    Orchestrator: run OCR on a preprocessed image and return the text.

    This is the main entry point for the OCR pre-pass step. It wraps
    extract_text with an additional safety net to guarantee a string
    return value.

    Args:
        image: PIL Image or numpy ndarray.

    Returns:
        Extracted text as a string. Empty string on any failure.
    """
    try:
        return extract_text(image)
    except Exception:
        logger.warning("ocr_prepass failed unexpectedly.", exc_info=True)
        return ""
