"""
Three-pass scan engine for invoice processing with Claude.

Orchestrates the full pipeline: preprocessing, OCR pre-pass, two independent
Claude API scans, field-by-field comparison, and optional tiebreaker scan
when disagreements are found.
"""

import base64
import io
import json
import logging
import time

import anthropic
from PIL import Image

from scanner.preprocessing import prepare_variants
from scanner.preprocessing.segmentation import segment_invoice
from scanner.preprocessing.layout import build_layout_descriptor
from scanner.scanning.ocr import ocr_prepass
from scanner.scanning.prompts import (
    build_scan_prompt,
    build_scan_prompt_v2,
    build_tiebreaker_prompt,
)
from scanner.memory import JsonGeneralMemory, JsonSupplierMemory, normalize_supplier_id
from scanner.memory.inference import run_inference
from scanner.scanning.comparator import compare_scans, merge_results
from scanner.scanning.validator import validate_math, auto_correct

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-20250514"
OPUS = "claude-opus-4-0-20250514"


def _get_model_for_scan(mode: str, scan_number: int) -> str:
    """
    Return the correct model for a given mode and scan number.

    Args:
        mode: "light", "normal", or "heavy".
        scan_number: 1 (primary), 2 (confirmation), or 3 (tiebreaker).

    Returns:
        Model identifier string.
    """
    if mode == "heavy":
        return OPUS
    elif mode == "normal":
        return SONNET if scan_number in (1, 2) else OPUS
    else:  # light
        return SONNET


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
    Three-pass scan pipeline for an invoice image.

    1. Opens image from bytes and preprocesses
    2. Scan 1: Primary extraction with build_scan_prompt
    3. Scan 2: Confirmation extraction with build_scan_prompt_v2
    4. Compare: Field-by-field comparison of both results
    5. If disagreements exist → Scan 3: Tiebreaker with both results
    6. Merge and return structured result with scan_metadata

    Args:
        image_bytes: Raw image file bytes.
        mode: Scan mode — "light", "normal", or "heavy".
        debug: If True, includes extra metadata in the response.

    Returns:
        Dict with invoice data, confidence scores, inference_sources,
        and scan_metadata.
    """
    start_time = time.time()
    models_used = []
    api_calls = 0

    try:
        # Step 1: Open image and preprocess
        image = Image.open(io.BytesIO(image_bytes))
        image.load()  # Force load to catch corrupt images early

        variants = prepare_variants(image)
        original = variants["original"]
        preprocessed = variants["preprocessed"]

        ocr_text = ocr_prepass(preprocessed)

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

        # Step 1b: ROI segmentation (layout-aware when supplier is known)
        segmentation_result = segment_invoice(original)

        # Step 2: Scan 1 — Primary extraction
        model1 = _get_model_for_scan(mode, 1)
        prompt1 = build_scan_prompt(ocr_text)
        response1 = _call_claude(prompt1, images, model1)
        scan1 = _parse_json_response(response1)
        models_used.append(model1)
        api_calls += 1

        # Step 3: Scan 2 — Confirmation extraction
        model2 = _get_model_for_scan(mode, 2)
        prompt2 = build_scan_prompt_v2(ocr_text)
        response2 = _call_claude(prompt2, images, model2)
        scan2 = _parse_json_response(response2)
        models_used.append(model2)
        api_calls += 1

        # Step 4: Compare results
        comparison = compare_scans(scan1, scan2)
        agreement_ratio = comparison["agreement_ratio"]
        tiebreaker_triggered = False
        tiebreaker_result = None

        # Step 5: Tiebreaker if disagreements exist
        has_disagreements = (
            len(comparison["disagreed"]) > 0
            or len(comparison["items_comparison"]["disagreed"]) > 0
        )

        if has_disagreements:
            tiebreaker_triggered = True
            model3 = _get_model_for_scan(mode, 3)
            prompt3 = build_tiebreaker_prompt(scan1, scan2, ocr_text)
            response3 = _call_claude(prompt3, images, model3)
            tiebreaker_result = _parse_json_response(response3)
            models_used.append(model3)
            api_calls += 1

        # Step 6: Merge results
        result = merge_results(scan1, scan2, tiebreaker_result, comparison=comparison)

        # Step 6b: Mathematical cross-validation
        validation = validate_math(result)
        math_validation_triggered = False
        if not validation["valid"]:
            result = auto_correct(result, validation["errors"])
            math_validation_triggered = True

        # Step 7: Three-tier inference for missing/low-confidence fields
        try:
            supplier_name = result.get("supplier", "")
            if supplier_name:
                sid = normalize_supplier_id(supplier_name)
            else:
                sid = None
            supplier_mem = JsonSupplierMemory()
            general_mem = JsonGeneralMemory()
            result = run_inference(result, sid, supplier_mem, general_mem)
        except Exception as e:
            logger.warning("Inference step failed (non-fatal): %s", e)

        # Step 7b: Save layout descriptor for supplier if not already saved
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
        except Exception as e:
            logger.warning("Layout saving failed (non-fatal): %s", e)

        # Step 8: Attach scan metadata
        elapsed = time.time() - start_time
        sonnet_count = sum(1 for m in models_used if m == SONNET)
        opus_count = sum(1 for m in models_used if m == OPUS)

        # Preserve any metadata added by inference before merging
        existing_metadata = result.get("scan_metadata", {})
        existing_metadata.update({
            "mode": mode,
            "scan_passes": api_calls,
            "scans_performed": api_calls,
            "tiebreaker_triggered": tiebreaker_triggered,
            "agreement_ratio": agreement_ratio,
            "math_validation_triggered": math_validation_triggered,
            "api_calls": {
                "sonnet": sonnet_count,
                "opus": opus_count,
            },
            "models_used": models_used,
        })
        result["scan_metadata"] = existing_metadata

        if debug:
            result["scan_metadata"]["debug"] = {
                "elapsed_seconds": round(elapsed, 2),
                "models_used": models_used,
                "ocr_text": ocr_text,
                "quality_report": variants["quality_report"],
                "agreement_ratio": agreement_ratio,
                "comparison_details": {
                    "agreed_fields": list(comparison["agreed"].keys()),
                    "disagreed_fields": list(comparison["disagreed"].keys()),
                    "agreed_items": len(comparison["items_comparison"]["agreed"]),
                    "disagreed_items": len(comparison["items_comparison"]["disagreed"]),
                },
                "math_validation": {
                    "valid": validation["valid"],
                    "errors": validation["errors"],
                    "corrections_applied": math_validation_triggered,
                },
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
            "scans_performed": 0,
            "tiebreaker_triggered": False,
            "agreement_ratio": 0.0,
            "math_validation_triggered": False,
            "api_calls": {"sonnet": 0, "opus": 0},
            "models_used": [],
            "error": error_message,
        },
    }
