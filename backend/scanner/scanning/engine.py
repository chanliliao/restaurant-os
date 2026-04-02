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

import os

import anthropic
import requests
from PIL import Image

from scanner.preprocessing.processor import remove_stripes, prepare_alternative_variant, auto_orient
from scanner.preprocessing.segmentation import segment_invoice, segment_invoice_zones
from scanner.preprocessing.layout import build_layout_descriptor
from scanner.scanning.ocr import ocr_prepass, extract_text_enhanced
from scanner.scanning.prompts import (
    build_scan_prompt,
    build_scan_prompt_v2,
    build_tiebreaker_prompt,
    build_smart_pass_prompt,
    build_verification_prompt,
    build_header_scan_prompt,
    build_items_scan_prompt,
    build_description_prompt,
    build_supplier_context_section,
    build_format_description_request,
    ACCOUNTANT_SYSTEM_INSTRUCTION,
    HEADER_RESPONSE_SCHEMA,
    ITEMS_RESPONSE_SCHEMA,
)
from scanner.scanning.ocr_parser import (
    parse_ocr_text,
    identify_supplier,
    parse_with_profile,
    _extract_supplier,
    _extract_totals,
)
from scanner.memory import JsonGeneralMemory, JsonSupplierMemory, normalize_supplier_id
from scanner.memory.inference import run_inference
from scanner.scanning.comparator import compare_scans, merge_results
from scanner.scanning.validator import validate_math, auto_correct

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-20250514"
OPUS = "claude-opus-4-0-20250514"
GLM_OCR_MODEL = "glm-ocr"
GLM_OCR_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
GLM_VISION_MODEL = "glm-4.6v-flash"
GLM_VISION_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _match_supplier_from_ocr(ocr_text: str, supplier_mem: JsonSupplierMemory) -> str | None:
    """Try to identify a known supplier from OCR text.

    Checks if any known supplier name appears in the OCR text (case-insensitive).
    Returns the supplier_id if found, None otherwise.
    """
    if not ocr_text:
        return None
    ocr_lower = ocr_text.lower()
    try:
        suppliers = supplier_mem.list_suppliers()
    except Exception:
        return None
    for sid, name in suppliers.items():
        if name.lower() in ocr_lower:
            return sid
    return None



def _get_model_for_scan(mode: str, scan_number: int) -> str:
    """Return the correct model for a given mode and scan number.

    Uses GLM vision for all modes.

    Args:
        mode: "light", "normal", or "heavy".
        scan_number: 1 (primary), 2 (confirmation), or 3 (tiebreaker).

    Returns:
        Model identifier string.
    """
    return GLM_VISION_MODEL


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


def _optimize_image_for_vision(pil_image: Image.Image, max_edge: int = 1600) -> tuple[str, str]:
    """
    Resize and JPEG-encode a PIL image for GLM Vision to keep payload small.

    Returns:
        (base64_string, media_type)
    """
    w, h = pil_image.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        pil_image = pil_image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def _call_glm_vision(
    prompt: str,
    images: list[dict],
    system_instruction: str | None = None,
    temperature: float = 0,
) -> str:
    """
    Call GLM-4.6V-Flash with images + prompt, return JSON text.
    Retries up to 3 times on 429 with exponential backoff.

    Args:
        prompt: The text prompt.
        images: List of dicts with keys "base64" and "media_type".
        system_instruction: Optional system message for role framing.
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        The JSON text content from the model's response.
    """
    api_key = os.getenv("GLM_OCR_API_KEY", "")

    # Build content: images first, then text prompt
    content = []
    for img in images:
        data_uri = f"data:{img['media_type']};base64,{img['base64']}"
        content.append({"type": "image_url", "image_url": {"url": data_uri}})
    content.append({"type": "text", "text": prompt})

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": content})

    payload = {
        "model": GLM_VISION_MODEL,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "max_tokens": 4096,
    }

    max_retries = 3
    for attempt in range(max_retries):
        response = requests.post(
            GLM_VISION_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=120,
        )
        if response.status_code == 429 and attempt < max_retries - 1:
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
            logger.warning("GLM Vision 429 rate limit — retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)
            continue
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    # Final attempt already raised above; this line is unreachable but satisfies linters
    response.raise_for_status()
    return ""


def _call_api(
    prompt: str,
    images: list[dict],
    model: str,
    **kwargs,
) -> str:
    """Dispatch to Claude or GLM-4.6V-Flash based on the model identifier."""
    if model == GLM_VISION_MODEL:
        return _call_glm_vision(prompt, images, **kwargs)
    return _call_claude(prompt, images, model)


def _optimize_for_glm(image_bytes: bytes) -> tuple[bytes, str]:
    """
    Optimize image bytes for GLM-OCR upload.

    GLM-OCR API accepts only JPG/PNG (not WebP). Large JPEGs (3-4MB) time out,
    so this function resizes and re-encodes as JPEG:
    - If > 1MB: resize longest edge to ≤2000px, encode as JPEG quality 82
    - If 500KB-1MB: encode as JPEG quality 85 (keeps resolution)
    - If < 500KB and already JPEG/PNG: return as-is

    Returns:
        (optimized_bytes, media_type)
    """
    size = len(image_bytes)
    if size < 500_000:
        if image_bytes[:3] == b'\xff\xd8\xff':
            return image_bytes, "image/jpeg"
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return image_bytes, "image/png"
        return image_bytes, "image/jpeg"

    img = Image.open(io.BytesIO(image_bytes))
    img.load()

    if size > 1_000_000:
        # Resize so longest edge is at most 2000px
        w, h = img.size
        max_edge = max(w, h)
        if max_edge > 2000:
            scale = 2000 / max_edge
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)

    quality = 82 if size > 1_000_000 else 85
    buf = io.BytesIO()
    # Convert to RGB before JPEG (handles RGBA/palette modes)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    optimized = buf.getvalue()
    logger.debug(
        "_optimize_for_glm: %d KB -> %d KB (JPEG q%d)",
        size // 1024, len(optimized) // 1024, quality,
    )
    return optimized, "image/jpeg"


def _call_glm_ocr(image_base64: str, media_type: str = "image/png") -> str:
    """
    Send an image to GLM-OCR and return extracted text as a single string.

    Args:
        image_base64: Base64-encoded image bytes.
        media_type: MIME type of the image (e.g. "image/png", "image/jpeg").

    Returns:
        Extracted text/markdown content joined from all recognized blocks.

    Raises:
        requests.HTTPError: If the API returns an error status.
    """
    api_key = os.getenv("GLM_OCR_API_KEY", "")
    data_uri = f"data:{media_type};base64,{image_base64}"

    response = requests.post(
        GLM_OCR_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
        json={"model": GLM_OCR_MODEL, "file": data_uri},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    # Response structure: {"layout_details": [[{label, content, bbox_2d, ...}, ...], ...]}
    # Each inner list is one page; each block has label ("text", "table", "image") and content.
    text_parts = []
    for page_blocks in data.get("layout_details", []):
        for block in page_blocks:
            if not isinstance(block, dict):
                continue
            label = block.get("label", "")
            content = block.get("content", "")
            if content and label in ("text", "table"):
                text_parts.append(str(content))

    # Fallback: unexpected structure
    if not text_parts:
        logger.warning("GLM-OCR: unexpected response structure — using raw JSON as text")
        text_parts = [json.dumps(data, ensure_ascii=False)]

    return "\n".join(text_parts)


def _scan_glm(image_bytes: bytes, debug: bool = False) -> dict:
    """
    GLM-OCR targeted pipeline: fast benchmark-proven pipeline.

    Steps:
    1. Auto-orient image, GLM-OCR on raw image
    2. Parse OCR + assess completeness → fast path if all fields confident
    3. Segment + build targeted crop list for only missing/low-conf fields
    4. Single GLM Vision call with targeted crops
    5. Math validation → inference → layout saving
    """
    start_time = time.time()

    image = Image.open(io.BytesIO(image_bytes))
    image.load()

    # Step 1: Auto-orient only (no preprocessing), then GLM-OCR on raw image
    original = auto_orient(image)

    logger.info("GLM-OCR: optimizing image for upload")
    glm_bytes, raw_media_type = _optimize_for_glm(image_bytes)
    raw_b64 = base64.b64encode(glm_bytes).decode("utf-8")
    logger.info("GLM-OCR: sending %d KB as %s", len(glm_bytes) // 1024, raw_media_type)
    glm_text = _call_glm_ocr(raw_b64, media_type=raw_media_type)
    logger.info("GLM-OCR: extracted %d characters", len(glm_text))

    # Step 2: Parse OCR text + assess completeness
    ocr_parsed = parse_ocr_text(glm_text)
    ocr_data = ocr_parsed.to_dict()

    SCALAR_FIELDS = ("supplier", "invoice_number", "date", "subtotal", "tax", "total")
    missing_scalar = []
    for fname in SCALAR_FIELDS:
        pf = getattr(ocr_parsed, fname)
        if pf.value is None or pf.confidence < 60:
            missing_scalar.append(fname)

    items_incomplete = False
    if not ocr_parsed.items:
        items_incomplete = True
    else:
        for item in ocr_parsed.items:
            if item.quantity is None or item.total is None:
                items_incomplete = True
                break

    # Determine OCR quality for downstream prompts
    ocr_useful_fields = [k for k in ocr_data if k != "items"]
    ocr_has_items = bool(ocr_data.get("items"))
    ocr_field_count = len(ocr_useful_fields) + (1 if ocr_has_items else 0)
    ocr_quality = "good" if ocr_field_count >= 3 else "poor"
    logger.info("GLM-OCR parsed %d structured fields (quality=%s)", ocr_field_count, ocr_quality)

    # Supplier needs higher bar for fast-path trust (≥80%) + cross-validate against memory
    if "supplier" not in missing_scalar:
        supplier_pf = ocr_parsed.supplier
        if supplier_pf.confidence < 80:
            logger.info("OCR supplier conf %d%% < 80%% — sending to LLM", supplier_pf.confidence)
            missing_scalar.append("supplier")
        else:
            _smem = JsonSupplierMemory()
            _known_sid = _match_supplier_from_ocr(glm_text, _smem)
            if _known_sid:
                _known_name = _smem.list_suppliers().get(_known_sid, "")
                _parsed = str(supplier_pf.value or "")
                if _known_name.lower() not in _parsed.lower() and _parsed.lower() not in _known_name.lower():
                    logger.info(
                        "OCR supplier %r conflicts with known supplier %r — sending to LLM",
                        _parsed, _known_name,
                    )
                    missing_scalar.append("supplier")

    # OCR fast path: skip LLM entirely if all scalar fields ≥60% and items complete
    if not missing_scalar and not items_incomplete:
        logger.info("OCR fast path: all fields confident, skipping LLM")
        result = {}
        for fname in SCALAR_FIELDS:
            pf = getattr(ocr_parsed, fname)
            if pf.value is not None:
                result[fname] = pf.value
        result["items"] = []
        for item in ocr_parsed.items:
            result["items"].append({
                "name": item.name,
                "quantity": item.quantity,
                "unit": item.unit,
                "unit_price": item.unit_price,
                "total": item.total,
                "confidence": item.confidence,
            })
        result.setdefault("confidence", {})
        glm_calls = 0

        # Segmentation still needed for layout saving
        segmentation_result = segment_invoice(original)

        # Jump to Step 5
        verification_triggered = False
        uncertain_fields = []
        uncertain_items = []

    else:
        # Step 3: Segment + build targeted crop list
        segmentation_result = segment_invoice(original)

        need_header = bool(set(missing_scalar) & {"supplier", "invoice_number", "date"})
        need_totals = bool(set(missing_scalar) & {"subtotal", "tax", "total"})
        need_items = items_incomplete

        has_header_crop = segmentation_result.get("header") is not None
        crop_descriptions = []
        images = []

        if need_header:
            # Supplier identification needs full-page context; segmented header crops
            # are unreliable (may capture the items table instead of the company header).
            images.append({"base64": raw_b64, "media_type": raw_media_type})
            crop_descriptions.append("full page")
        elif not images:
            # Fall back to raw image if no useful crops available
            images.append({"base64": raw_b64, "media_type": raw_media_type})
            crop_descriptions.append("full page")

        if need_totals and segmentation_result.get("totals") is not None:
            totals_b64, totals_type = _optimize_image_for_vision(segmentation_result["totals"], max_edge=1600)
            images.append({"base64": totals_b64, "media_type": totals_type})
            crop_descriptions.append("totals crop")

        if need_items and segmentation_result.get("line_items") is not None:
            items_b64, items_type = _optimize_image_for_vision(segmentation_result["line_items"], max_edge=1600)
            images.append({"base64": items_b64, "media_type": items_type})
            crop_descriptions.append("line items crop")

        # If segmentation produced no useful crops at all, send raw image
        if not images:
            images = [{"base64": raw_b64, "media_type": raw_media_type}]
            crop_descriptions = ["full page"]

        # Step 4: Single GLM Vision call with targeted crops
        targeted_note = (
            "\n\n## Targeted Extraction\n"
            f"Images provided: {', '.join(crop_descriptions)}. "
            "OCR already extracted most fields. "
            f"Focus on: {', '.join(missing_scalar) if missing_scalar else 'line items'}."
        )
        prompt = build_smart_pass_prompt(
            ocr_data, glm_text,
            has_header_crop=has_header_crop,
            has_binary_image=False,
            ocr_quality=ocr_quality,
            ocr_source="glm",
        ) + targeted_note

        response = _call_glm_vision(
            prompt, images,
            system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
        )
        result = _flatten_result(_parse_json_response(response))
        glm_calls = 1

        # Step 4b: Verification pass for uncertain fields
        verification_triggered = False
        readable = result.pop("readable", {})
        uncertain_fields = [f for f, v in readable.items() if v is False]
        uncertain_items = []
        for i, item in enumerate(result.get("items", [])):
            if item.pop("readable", True) is False:
                uncertain_items.append(i)

        if uncertain_fields or uncertain_items:
            verification_triggered = True
            verify_prompt = build_verification_prompt(result, uncertain_fields, uncertain_items)
            verify_response = _call_glm_vision(
                verify_prompt, images,
                system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
            )
            verified = _flatten_result(_parse_json_response(verify_response))
            glm_calls += 1

            for field in uncertain_fields:
                if field in verified and verified[field] is not None:
                    result[field] = verified[field]
                if field in verified.get("confidence", {}):
                    result.setdefault("confidence", {})[field] = verified["confidence"][field]
                if field in verified.get("inference_sources", {}):
                    result.setdefault("inference_sources", {})[field] = verified["inference_sources"][field]

            verified_items = verified.get("items", [])
            for idx in uncertain_items:
                if idx < len(verified_items) and idx < len(result.get("items", [])):
                    result["items"][idx] = verified_items[idx]

    # Step 5: OCR cross-validation, math, inference, layout
    result = _cross_validate_invoice_number(result, ocr_parsed, glm_text)

    validation = validate_math(result)
    math_validation_triggered = False
    if not validation["valid"]:
        result = auto_correct(result, validation["errors"])
        math_validation_triggered = True

    supplier_mem = JsonSupplierMemory()
    sid = None
    try:
        supplier_name = result.get("supplier", "")
        if supplier_name:
            sid = normalize_supplier_id(supplier_name)
        general_mem = JsonGeneralMemory()
        result = run_inference(result, sid, supplier_mem, general_mem)
    except Exception as e:
        logger.warning("Inference step failed (non-fatal): %s", e)

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

    elapsed = time.time() - start_time
    existing_metadata = result.get("scan_metadata", {})
    existing_metadata.update({
        "mode": "glm",
        "pipeline": "glm-ocr-targeted",
        "preprocessing": False,
        "scan_passes": glm_calls,
        "scans_performed": glm_calls,
        "verification_triggered": verification_triggered,
        "uncertain_fields": uncertain_fields,
        "uncertain_items_count": len(uncertain_items),
        "tiebreaker_triggered": False,
        "agreement_ratio": 1.0,
        "math_validation_triggered": math_validation_triggered,
        "api_calls": {"sonnet": 0, "opus": 0, "glm_vision": glm_calls},
        "models_used": [GLM_VISION_MODEL] * glm_calls,
        "ocr_fields_extracted": list(ocr_data.keys()),
        "ocr_quality": ocr_quality,
        "glm_ocr_chars": len(glm_text),
    })
    result["scan_metadata"] = existing_metadata

    if debug:
        result["scan_metadata"]["debug"] = {
            "elapsed_seconds": round(elapsed, 2),
            "glm_ocr_text": glm_text,
            "ocr_parsed": ocr_data,
            "verification_triggered": verification_triggered,
            "uncertain_fields": uncertain_fields,
            "math_validation": {
                "valid": validation["valid"],
                "errors": validation["errors"],
                "corrections_applied": math_validation_triggered,
            },
        }

    return result


def _parse_json_response(text: str) -> dict:
    """
    Parse JSON from an LLM response text.

    Handles markdown code fences and common Gemini JSON quirks
    (trailing commas, single-line comments).

    Args:
        text: Raw text response from the LLM.

    Returns:
        Parsed dict.

    Raises:
        json.JSONDecodeError: If the response is not valid JSON.
    """
    import re

    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

    # Try parsing as-is first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fix common Gemini JSON issues: trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
    # Remove single-line comments
    fixed = re.sub(r"//[^\n]*", "", fixed)
    return json.loads(fixed)


_SCALAR_FIELDS = {"supplier", "invoice_number", "date", "subtotal", "tax", "total"}


def _flatten_result(result: dict) -> dict:
    """
    Flatten any scalar field that the LLM returned as a structured dict.

    The LLM occasionally returns e.g. {"supplier": {"value": "Foo", "confidence": 95}}
    instead of {"supplier": "Foo"}. This extracts the value and merges the
    confidence into result["confidence"] so downstream code always sees plain scalars.
    """
    confidence = result.setdefault("confidence", {})
    for field in _SCALAR_FIELDS:
        val = result.get(field)
        if isinstance(val, dict) and "value" in val:
            result[field] = val["value"]
            if "confidence" in val and field not in confidence:
                confidence[field] = val["confidence"]
    return result


def _cross_validate_invoice_number(result: dict, ocr_parsed, header_ocr_text: str) -> dict:
    """
    Cross-validate the LLM's invoice number against OCR findings.

    If OCR found a letter-prefixed invoice number but LLM returned all
    digits, lower confidence and try to reconcile.
    """
    import re

    llm_inv = str(result.get("invoice_number", ""))
    if not llm_inv:
        return result

    # Check if OCR found any alphanumeric codes that look like invoice numbers
    # Search in header OCR text for patterns with letter prefixes
    ocr_candidates = []
    for pattern in [
        re.compile(r"\b([A-Z]\d{5,})\b"),  # B1139777 style
        re.compile(r"\b([A-Z]{1,3}\d{4,})\b"),  # INV12345 style
    ]:
        for m in pattern.finditer(header_ocr_text):
            ocr_candidates.append(m.group(1))

    # Also check the parsed OCR result
    if ocr_parsed.invoice_number.value:
        ocr_candidates.append(str(ocr_parsed.invoice_number.value))

    if not ocr_candidates:
        return result

    # If LLM returned all digits but OCR found a letter-prefixed version,
    # check if the digit portions match
    if llm_inv.isdigit():
        for candidate in ocr_candidates:
            if not candidate[0].isalpha():
                continue
            # Extract digits from OCR candidate
            ocr_digits = re.sub(r"[^0-9]", "", candidate)
            # Check if the LLM digits are similar to OCR digits
            # (they might differ in some positions too)
            if len(ocr_digits) >= 4 and len(llm_inv) >= 4:
                # If last 4+ digits match, the OCR letter prefix is likely correct
                if llm_inv.endswith(ocr_digits[-4:]) or ocr_digits.endswith(llm_inv[-4:]):
                    logger.info(
                        "OCR cross-validation: LLM said '%s' but OCR found '%s' — "
                        "adopting OCR letter prefix",
                        llm_inv, candidate,
                    )
                    result["invoice_number"] = candidate
                    result.setdefault("confidence", {})["invoice_number"] = min(
                        result.get("confidence", {}).get("invoice_number", 70), 70
                    )
                    result.setdefault("inference_sources", {})["invoice_number"] = "inferred"
                    return result

        # Even if no OCR match, flag that all-digit invoice number might be wrong
        # if any OCR candidate had a letter
        if any(c[0].isalpha() for c in ocr_candidates):
            current_conf = result.get("confidence", {}).get("invoice_number", 95)
            if current_conf > 75:
                logger.info(
                    "OCR cross-validation: LLM returned all-digit '%s' but OCR "
                    "suggests letter prefix — lowering confidence %s -> 75",
                    llm_inv, current_conf,
                )
                result.setdefault("confidence", {})["invoice_number"] = 75

    return result


def _majority_vote_header(candidates: list[dict]) -> dict:
    """
    Pick the best header value per field using majority voting.

    For each of (supplier, date, invoice_number):
    - If 2+ candidates agree, use that value with the max confidence.
    - If all 3 differ, use the one with the highest confidence.
    """
    from collections import Counter

    best = {}
    for field in ("supplier", "date", "invoice_number"):
        values = [(c.get(field, ""), c.get("confidence", {}).get(field, 0)) for c in candidates]
        # Count occurrences of each value
        value_counts = Counter(v for v, _ in values)
        most_common_val, count = value_counts.most_common(1)[0]

        if count >= 2:
            # Majority — use that value with the max confidence among agreeing candidates
            max_conf = max(conf for val, conf in values if val == most_common_val)
            best[field] = most_common_val
            best.setdefault("confidence", {})[field] = max_conf
        else:
            # No majority — pick highest confidence
            best_val, best_conf = max(values, key=lambda x: x[1])
            best[field] = best_val
            best.setdefault("confidence", {})[field] = best_conf

    # Copy readable and inference_sources from the first candidate
    # (we'll update readable based on agreement)
    first = candidates[0] if candidates else {}
    best["readable"] = first.get("readable", {})
    best["inference_sources"] = first.get("inference_sources", {})

    # If all 3 disagree on a field, mark it as not readable
    for field in ("supplier", "date", "invoice_number"):
        values = [c.get(field, "") for c in candidates]
        if len(set(values)) == len(values):  # all different
            best.setdefault("readable", {})[field] = False

    logger.info(
        "Header majority vote: supplier=%s, inv#=%s, date=%s (from %d candidates)",
        best.get("supplier", "?"), best.get("invoice_number", "?"),
        best.get("date", "?"), len(candidates),
    )
    return best


def _build_extraction_profile(format_desc: dict) -> dict:
    """Convert LLM format_description into a stored extraction profile.

    Args:
        format_desc: Dict from LLM's format_description response key.

    Returns:
        Extraction profile dict ready to store in extraction_profile.json.
    """
    profile: dict = {}

    if "invoice_number_label" in format_desc:
        profile["invoice_number_label"] = format_desc["invoice_number_label"]

    if "date_label" in format_desc:
        profile["date_label"] = format_desc["date_label"]

    # Build column_map from column_mapping (header_text -> field_name)
    column_mapping = format_desc.get("column_mapping", {})
    if column_mapping:
        profile["column_map"] = column_mapping

    if "has_subtotal_row" in format_desc:
        profile["has_subtotal_row"] = bool(format_desc["has_subtotal_row"])

    if "has_tax_row" in format_desc:
        profile["has_tax_row"] = bool(format_desc["has_tax_row"])

    if "totals_label" in format_desc:
        profile["totals_label"] = format_desc["totals_label"]

    return profile


def _scan_light(image_bytes: bytes, debug: bool = False) -> dict:
    """
    GLM-OCR-first pipeline for light mode.

    Replaces the old Tesseract + 5-7 Gemini call approach with:
    1. Preprocess image (for Gemini image variants)
    2. GLM-OCR on optimized image bytes → rich HTML tables + text
    3. Segment + Tesseract header OCR (cheap cross-reference)
    4. Parse OCR text (HTML table-aware)
    5. Single Gemini validation pass
    6. Optional verification pass (if readable:false fields)
    7. Math validation → inference → layout saving

    Gemini calls: 1 minimum, 2 maximum (vs old 5-7).
    Falls back to Tesseract if GLM-OCR fails.
    """
    start_time = time.time()

    image = Image.open(io.BytesIO(image_bytes))
    image.load()

    from scanner.preprocessing.analyzer import analyze_quality
    quality_report = analyze_quality(image)
    needs_preprocessing = (
        quality_report["blur"]["issue"]
        or quality_report["brightness"]["issue"]
        or quality_report["noise"]["issue"]
    )

    if needs_preprocessing:
        variants = prepare_variants(image)
        logger.info(
            "Quality gate: preprocessing triggered (blur_issue=%s, brightness_issue=%s, noise_issue=%s)",
            quality_report["blur"]["issue"],
            quality_report["brightness"]["issue"],
            quality_report["noise"]["issue"],
        )
    else:
        variants = {"original": image, "preprocessed": image, "quality_report": quality_report}
        logger.info("Quality gate: preprocessing skipped (image is clean)")

    original = variants["original"]
    preprocessed = variants["preprocessed"]

    # Step 1: GLM-OCR on optimized image (resize+WebP to prevent timeouts)
    ocr_source = "glm"
    try:
        glm_bytes, glm_media_type = _optimize_for_glm(image_bytes)
        glm_b64 = base64.b64encode(glm_bytes).decode("utf-8")
        logger.info(
            "GLM-OCR (light): sending %d KB as %s",
            len(glm_bytes) // 1024, glm_media_type,
        )
        glm_text = _call_glm_ocr(glm_b64, media_type=glm_media_type)
        logger.info("GLM-OCR (light): extracted %d characters", len(glm_text))
    except Exception as glm_err:
        logger.warning("GLM-OCR failed, falling back to Tesseract: %s", glm_err)
        ocr_source = "tesseract"
        ocr_image = remove_stripes(preprocessed)
        glm_text = ocr_prepass(ocr_image)

    # Step 2: Segment + enhanced header OCR (Tesseract, cheap cross-reference)
    segmentation_result = segment_invoice(original)
    header_ocr_text = ""
    if segmentation_result.get("header") is not None:
        header_ocr_text = extract_text_enhanced(segmentation_result["header"])

    # Step 3: Parse combined text (HTML table-aware via updated ocr_parser)
    combined_text = glm_text
    if header_ocr_text.strip():
        combined_text += "\n\n--- HEADER REGION OCR ---\n" + header_ocr_text

    # Early supplier identification — check against known supplier index
    supplier_mem_early = JsonSupplierMemory()
    known_supplier_id = identify_supplier(glm_text, supplier_mem_early.list_suppliers())

    is_new_supplier = False
    if known_supplier_id:
        # Path A: Known supplier — use extraction profile
        extraction_profile = supplier_mem_early.get_extraction_profile(known_supplier_id)
        known_profile = supplier_mem_early.get_profile(known_supplier_id)
        known_name = known_profile.get("name", "")
        if extraction_profile and known_name:
            ocr_parsed = parse_with_profile(combined_text, extraction_profile, known_name)
            logger.info(
                "Path A: Known supplier '%s' — using extraction profile for parsing",
                known_name,
            )
        else:
            ocr_parsed = parse_ocr_text(combined_text)
            logger.info(
                "Path A: Known supplier '%s' — no extraction profile yet, using generic parse",
                known_name,
            )
    else:
        # Path B: New supplier — generic parsing, LLM will describe format
        is_new_supplier = True
        ocr_parsed = parse_ocr_text(combined_text)
        logger.info("Path B: Unknown supplier — using generic parse, will request format description")

    ocr_data = ocr_parsed.to_dict()

    # Step 3b: Zone-targeted Tesseract fallback for missing fields
    # Runs cheap Tesseract on small image crops — no API calls.
    _supplier_missing = (
        not ocr_data.get("supplier")
        or ocr_data["supplier"].get("confidence", 0) < 50
    )
    _total_missing = not ocr_data.get("total")
    if _supplier_missing or _total_missing:
        try:
            zones = segment_invoice_zones(original)
            if _supplier_missing and zones.get("header_left") is not None:
                supplier_text = extract_text_enhanced(zones["header_left"])
                supplier_field = _extract_supplier(supplier_text.split("\n"))
                if supplier_field.confidence > 0:
                    ocr_data["supplier"] = {
                        "value": supplier_field.value,
                        "confidence": supplier_field.confidence,
                    }
                    logger.info(
                        "Zone fallback: supplier='%s' (conf=%d)",
                        supplier_field.value, supplier_field.confidence,
                    )
            if _total_missing and zones.get("footer_right") is not None:
                totals_text = extract_text_enhanced(zones["footer_right"])
                _, _, total_field = _extract_totals(totals_text)
                if total_field.confidence > 0:
                    ocr_data["total"] = {
                        "value": total_field.value,
                        "confidence": total_field.confidence,
                    }
                    logger.info(
                        "Zone fallback: total=%s (conf=%d)",
                        total_field.value, total_field.confidence,
                    )
        except Exception as zone_err:
            logger.debug("Zone-targeted fallback failed (non-fatal): %s", zone_err)

    ocr_useful_fields = [k for k in ocr_data if k != "items"]
    ocr_has_items = bool(ocr_data.get("items"))
    ocr_field_count = len(ocr_useful_fields) + (1 if ocr_has_items else 0)
    if ocr_field_count >= 3:
        ocr_quality = "good"
    elif ocr_field_count >= 1:
        ocr_quality = "poor"
    else:
        # GLM text is still richer than Tesseract even when unparsed
        ocr_quality = "poor" if ocr_source == "glm" else "failed"
    logger.info(
        "OCR (light, source=%s): %d structured fields (quality=%s)",
        ocr_source, ocr_field_count, ocr_quality,
    )

    # Step 4: Build image set for Gemini
    preprocessed_b64 = _encode_image_base64(preprocessed)
    original_b64 = _encode_image_base64(original)
    has_header_crop = segmentation_result.get("header") is not None
    images = [
        {"base64": original_b64, "media_type": "image/png"},
        {"base64": preprocessed_b64, "media_type": "image/png"},
    ]
    if has_header_crop:
        images.append({
            "base64": _encode_image_base64(segmentation_result["header"]),
            "media_type": "image/png",
        })

    # Step 5: Single GLM vision smart pass
    glm_calls = 0
    uncertain_fields: list[str] = []
    uncertain_items: list[int] = []
    verification_triggered = False

    # Build optional supplier context for the LLM
    llm_supplier_context = None
    llm_format_request = None
    if known_supplier_id and not is_new_supplier:
        ep = supplier_mem_early.get_extraction_profile(known_supplier_id) or {}
        kp = supplier_mem_early.get_profile(known_supplier_id)
        llm_supplier_context = build_supplier_context_section(
            supplier_name=kp.get("name", known_supplier_id),
            scan_count=kp.get("scan_count", 0),
            invoice_number_label=ep.get("invoice_number_label"),
            date_label=ep.get("date_label"),
        )
    elif is_new_supplier:
        llm_format_request = build_format_description_request()

    prompt = build_smart_pass_prompt(
        ocr_data, combined_text,
        has_header_crop=has_header_crop,
        has_binary_image=False,
        ocr_quality=ocr_quality,
        ocr_source=ocr_source,
        supplier_context=llm_supplier_context,
        format_description_request=llm_format_request,
    )
    response = _call_glm_vision(
        prompt, images,
        system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
    )
    result = _parse_json_response(response)
    glm_calls += 1

    # Step 5b: Save format_description as extraction profile for new suppliers
    format_desc = result.pop("format_description", None)
    if is_new_supplier and format_desc and isinstance(format_desc, dict):
        try:
            supplier_name_from_result = result.get("supplier", "")
            if supplier_name_from_result:
                new_sid = normalize_supplier_id(supplier_name_from_result)
                ep = _build_extraction_profile(format_desc)
                supplier_mem_early.update_extraction_profile(new_sid, ep)
                logger.info(
                    "Path B: Saved extraction profile for new supplier '%s'",
                    supplier_name_from_result,
                )
        except Exception as ep_err:
            logger.warning("Failed to save extraction profile (non-fatal): %s", ep_err)

    # Step 5d: Optional verification pass
    readable = result.pop("readable", {})
    uncertain_fields = [f for f, v in readable.items() if v is False]
    for i, item in enumerate(result.get("items", [])):
        if item.pop("readable", True) is False:
            uncertain_items.append(i)

    if uncertain_fields or uncertain_items:
        verification_triggered = True
        logger.info(
            "Light scan flagged uncertain fields=%s, items=%s — verification pass",
            uncertain_fields, uncertain_items,
        )
        verify_prompt = build_verification_prompt(result, uncertain_fields, uncertain_items)
        verify_response = _call_glm_vision(
            verify_prompt, images,
            system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
        )
        verified = _parse_json_response(verify_response)
        glm_calls += 1

        for f in uncertain_fields:
            if f in verified and verified[f] is not None:
                result[f] = verified[f]
            if f in verified.get("confidence", {}):
                result.setdefault("confidence", {})[f] = verified["confidence"][f]
            if f in verified.get("inference_sources", {}):
                result.setdefault("inference_sources", {})[f] = verified["inference_sources"][f]

        verified_items = verified.get("items", [])
        for idx in uncertain_items:
            if idx < len(verified_items) and idx < len(result.get("items", [])):
                result["items"][idx] = verified_items[idx]

    # Step 6: OCR cross-validation, math, inference, layout saving
    result = _cross_validate_invoice_number(result, ocr_parsed, combined_text)

    validation = validate_math(result)
    math_validation_triggered = False
    if not validation["valid"]:
        result = auto_correct(result, validation["errors"])
        math_validation_triggered = True

    sid = None
    try:
        supplier_name = result.get("supplier", "")
        if supplier_name:
            sid = normalize_supplier_id(supplier_name)
        general_mem = JsonGeneralMemory()
        result = run_inference(result, sid, supplier_mem_early, general_mem)
    except Exception as e:
        logger.warning("Inference step failed (non-fatal): %s", e)

    try:
        if sid and segmentation_result.get("regions_detected"):
            existing_layout = supplier_mem_early.get_layout(sid)
            if existing_layout is None:
                layout_desc = build_layout_descriptor(
                    result,
                    segmentation_result["bounding_boxes"],
                    original.size,
                )
                supplier_mem_early.update_layout(sid, layout_desc)
    except Exception as e:
        logger.warning("Layout saving failed (non-fatal): %s", e)

    elapsed = time.time() - start_time
    existing_metadata = result.get("scan_metadata", {})
    existing_metadata.update({
        "mode": "light",
        "pipeline": "glm-ocr-light",
        "ocr_source": ocr_source,
        "scan_passes": glm_calls,
        "scans_performed": glm_calls,
        "verification_triggered": verification_triggered,
        "uncertain_fields": uncertain_fields,
        "uncertain_items_count": len(uncertain_items),
        "tiebreaker_triggered": False,
        "agreement_ratio": 1.0,
        "math_validation_triggered": math_validation_triggered,
        "api_calls": {"sonnet": 0, "opus": 0, "glm_vision": glm_calls},
        "models_used": [GLM_VISION_MODEL] * glm_calls,
        "ocr_fields_extracted": list(ocr_data.keys()),
        "ocr_quality": ocr_quality,
        "glm_ocr_chars": len(glm_text),
    })
    result["scan_metadata"] = existing_metadata

    if debug:
        result["scan_metadata"]["debug"] = {
            "elapsed_seconds": round(elapsed, 2),
            "ocr_source": ocr_source,
            "glm_ocr_text": glm_text,
            "ocr_parsed": ocr_data,
            "quality_report": variants["quality_report"],
            "verification_triggered": verification_triggered,
            "uncertain_fields": uncertain_fields,
            "math_validation": {
                "valid": validation["valid"],
                "errors": validation["errors"],
                "corrections_applied": math_validation_triggered,
            },
        }

    return result


def scan_invoice(image_bytes: bytes, mode: str = "normal", debug: bool = False) -> dict:
    """
    Main scan pipeline for an invoice image.

    Light mode uses OCR-first pipeline (1 API call).
    Normal/heavy modes use three-pass pipeline (2-3 API calls).

    Args:
        image_bytes: Raw image file bytes.
        mode: Scan mode — "light", "normal", or "heavy".
        debug: If True, includes extra metadata in the response.

    Returns:
        Dict with invoice data, confidence scores, inference_sources,
        and scan_metadata.
    """
    # GLM mode: GLM-OCR document parsing + single Gemini extraction call
    if mode == "glm":
        try:
            return _scan_glm(image_bytes, debug)
        except requests.HTTPError as e:
            logger.error("GLM-OCR API error: %s", e)
            return _error_result(mode, f"GLM-OCR API error: {e}")
        except json.JSONDecodeError as e:
            logger.error("Failed to parse GLM vision response as JSON: %s", e)
            return _error_result(mode, f"Invalid JSON in GLM vision response: {e}")
        except Exception as e:
            logger.error("GLM scan failed: %s", e, exc_info=True)
            return _error_result(mode, f"Scan failed: {e}")

    # Light mode: OCR-first pipeline
    if mode == "light":
        try:
            return _scan_light(image_bytes, debug)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse GLM vision response as JSON: %s", e)
            return _error_result(mode, f"Invalid JSON in GLM vision response: {e}")
        except Exception as e:
            logger.error("Light scan failed: %s", e, exc_info=True)
            return _error_result(mode, f"Scan failed: {e}")

    # Normal/heavy mode: three-pass pipeline
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

        ocr_image = remove_stripes(preprocessed)
        ocr_text = ocr_prepass(ocr_image)

        # Optimize images before sending to GLM Vision — raw PNGs are too large
        orig_b64, orig_media = _optimize_image_for_vision(original)
        pre_b64, pre_media = _optimize_image_for_vision(preprocessed)
        images = [
            {"base64": orig_b64, "media_type": orig_media},
            {"base64": pre_b64, "media_type": pre_media},
        ]

        # Step 1b: ROI segmentation (layout-aware when supplier is known)
        # Try to identify supplier from OCR text to load saved layout
        supplier_mem = JsonSupplierMemory()
        saved_layout = None
        early_sid = _match_supplier_from_ocr(ocr_text, supplier_mem)
        if early_sid:
            saved_layout = supplier_mem.get_layout(early_sid)
        segmentation_result = segment_invoice(original, saved_layout=saved_layout)

        # Step 2: Scan 1 — Primary extraction
        model1 = _get_model_for_scan(mode, 1)
        prompt1 = build_scan_prompt(ocr_text)
        response1 = _call_api(prompt1, images, model1)
        scan1 = _parse_json_response(response1)
        models_used.append(model1)
        api_calls += 1

        # Step 3: Scan 2 — Confirmation extraction
        model2 = _get_model_for_scan(mode, 2)
        prompt2 = build_scan_prompt_v2(ocr_text)
        response2 = _call_api(prompt2, images, model2)
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
            response3 = _call_api(prompt3, images, model3)
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
        sid = None
        try:
            supplier_name = result.get("supplier", "")
            if supplier_name:
                sid = normalize_supplier_id(supplier_name)
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
        glm_vision_count = sum(1 for m in models_used if m == GLM_VISION_MODEL)

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
                "glm_vision": glm_vision_count,
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
            "api_calls": {"sonnet": 0, "opus": 0, "gemini": 0},
            "models_used": [],
            "error": error_message,
        },
    }
