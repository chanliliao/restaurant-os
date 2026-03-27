"""
Single scan engine for invoice processing with Claude.

Orchestrates the full pipeline: preprocessing, OCR pre-pass, Claude API call,
and JSON parsing to produce structured invoice data.
"""

import base64
import io
import json
import logging
import time

import anthropic
from PIL import Image

from scanner.preprocessing import prepare_variants
from scanner.scanning.ocr import ocr_prepass
from scanner.scanning.prompts import build_scan_prompt

logger = logging.getLogger(__name__)

# Model selection per scan mode
MODEL_MAP = {
    "light": "claude-sonnet-4-20250514",
    "normal": "claude-sonnet-4-20250514",
    "heavy": "claude-opus-4-0-20250514",
}


def _encode_image_base64(pil_image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image to a base64 string."""
    buf = io.BytesIO()
    pil_image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")



def _call_claude(prompt: str, images: list[dict], model: str) -> str:
    """
    Call the Anthropic API with a prompt and image content blocks.

    Args:
        prompt: The text prompt for Claude.
        images: List of dicts with keys "base64" and "media_type".
        model: The model identifier string.

    Returns:
        The text content from Claude's response.

    Raises:
        anthropic.APIError: If the API call fails.
    """
    client = anthropic.Anthropic()

    # Build content blocks: images first, then the text prompt
    content = []
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["base64"],
            },
        })
    content.append({
        "type": "text",
        "text": prompt,
    })

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "user", "content": content},
        ],
    )

    # Extract text from response
    return response.content[0].text


def _parse_json_response(text: str) -> dict:
    """
    Parse JSON from Claude's response text.

    Handles cases where Claude wraps JSON in markdown code fences.

    Args:
        text: Raw text response from Claude.

    Returns:
        Parsed dict.

    Raises:
        json.JSONDecodeError: If the response is not valid JSON.
    """
    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
            # Remove closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

    return json.loads(cleaned)


def scan_invoice(image_bytes: bytes, mode: str = "normal", debug: bool = False) -> dict:
    """
    Full single-scan pipeline for an invoice image.

    1. Opens image from bytes
    2. Runs prepare_variants() for preprocessing
    3. Runs ocr_prepass() for supplementary text
    4. Encodes both image variants as base64
    5. Calls Claude API with prompt + images + OCR text
    6. Parses JSON response
    7. Returns structured result with scan_metadata

    Args:
        image_bytes: Raw image file bytes.
        mode: Scan mode — "light", "normal", or "heavy".
        debug: If True, includes extra metadata in the response.

    Returns:
        Dict with invoice data, confidence scores, inference_sources,
        and scan_metadata.
    """
    start_time = time.time()
    model = MODEL_MAP.get(mode, MODEL_MAP["normal"])

    try:
        # Step 1: Open image
        image = Image.open(io.BytesIO(image_bytes))
        image.load()  # Force load to catch corrupt images early

        # Step 2: Preprocess
        variants = prepare_variants(image)
        original = variants["original"]
        preprocessed = variants["preprocessed"]

        # Step 3: OCR pre-pass on preprocessed image
        ocr_text = ocr_prepass(preprocessed)

        # Step 4: Encode images as base64
        images = [
            {
                "base64": _encode_image_base64(original),
                "media_type": "image/png",
            },
            {
                "base64": _encode_image_base64(preprocessed),
                "media_type": "image/png",
            },
        ]

        # Step 5: Build prompt and call Claude
        prompt = build_scan_prompt(ocr_text)
        response_text = _call_claude(prompt, images, model)

        # Step 6: Parse JSON
        result = _parse_json_response(response_text)

        # Step 7: Attach scan metadata
        elapsed = time.time() - start_time
        is_opus = model == MODEL_MAP["heavy"]
        result["scan_metadata"] = {
            "mode": mode,
            "scan_passes": 1,
            "tiebreaker_triggered": False,
            "math_validation_triggered": False,
            "api_calls": {
                "sonnet": 0 if is_opus else 1,
                "opus": 1 if is_opus else 0,
            },
        }

        if debug:
            result["scan_metadata"]["debug"] = {
                "elapsed_seconds": round(elapsed, 2),
                "model": model,
                "ocr_text": ocr_text,
                "quality_report": variants["quality_report"],
            }

        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", e)
        return _error_result(mode, f"Invalid JSON in Claude response: {e}")
    except anthropic.APIError as e:
        logger.error("Anthropic API error: %s", e)
        return _error_result(mode, f"Claude API error: {e}")
    except Exception as e:
        logger.error("Scan failed unexpectedly: %s", e, exc_info=True)
        return _error_result(mode, f"Scan failed: {e}")


def _error_result(mode: str, error_message: str) -> dict:
    """Build a standardised error result dict."""
    return {
        "supplier": "",
        "date": "",
        "invoice_number": "",
        "items": [],
        "subtotal": None,
        "tax": None,
        "total": None,
        "confidence": {
            "supplier": 0,
            "date": 0,
            "invoice_number": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
        },
        "inference_sources": {
            "supplier": "missing",
            "date": "missing",
            "invoice_number": "missing",
            "subtotal": "missing",
            "tax": "missing",
            "total": "missing",
        },
        "scan_metadata": {
            "mode": mode,
            "scan_passes": 0,
            "tiebreaker_triggered": False,
            "math_validation_triggered": False,
            "api_calls": {"sonnet": 0, "opus": 0},
            "error": error_message,
        },
    }
