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
from google import genai
from PIL import Image

from scanner.preprocessing import prepare_variants
from scanner.preprocessing.processor import remove_stripes, prepare_alternative_variant
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
    ACCOUNTANT_SYSTEM_INSTRUCTION,
    HEADER_RESPONSE_SCHEMA,
    ITEMS_RESPONSE_SCHEMA,
)
from scanner.scanning.ocr_parser import (
    parse_ocr_text,
    _extract_supplier,
    _extract_totals,
)
from scanner.memory import JsonGeneralMemory, JsonSupplierMemory, normalize_supplier_id
from scanner.memory.inference import run_inference
from scanner.scanning.comparator import compare_scans, merge_results
from scanner.scanning.validator import validate_math, auto_correct
from scanner.tracking.api_usage import record_gemini_call

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-20250514"
OPUS = "claude-opus-4-0-20250514"
GEMINI_FLASH = "gemini-2.5-flash"
GLM_OCR_MODEL = "glm-ocr"
GLM_OCR_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"


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
    """
    Return the correct model for a given mode and scan number.

    Uses Gemini Flash for all modes since Claude API credits are unavailable.

    Args:
        mode: "light", "normal", or "heavy".
        scan_number: 1 (primary), 2 (confirmation), or 3 (tiebreaker).

    Returns:
        Model identifier string.
    """
    # Use Gemini for all scans (Claude API credits unavailable)
    return GEMINI_FLASH


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


def _call_gemini(
    prompt: str,
    images: list[dict],
    model: str = GEMINI_FLASH,
    system_instruction: str | None = None,
    thinking_budget: int | None = 2048,
    response_schema: dict | None = None,
    temperature: float = 0,
    use_grounding: bool = False,
) -> str:
    """
    Call the Google Gemini API with a prompt and base64-encoded images.

    Args:
        prompt: The text prompt for Gemini.
        images: List of dicts with keys "base64" and "media_type".
        model: The Gemini model identifier string.
        system_instruction: Optional system instruction for role framing.
        thinking_budget: Token budget for Gemini's internal reasoning.
            Set to None to disable thinking mode.
        response_schema: Optional JSON schema dict to enforce output structure.
        temperature: Sampling temperature (0 = deterministic).
        use_grounding: If True, enable Google Search grounding.

    Returns:
        The text content from Gemini's response.
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

    # Build content parts: images first, then text
    parts = []
    for img in images:
        raw_bytes = base64.b64decode(img["base64"])
        parts.append(genai.types.Part.from_bytes(data=raw_bytes, mime_type=img["media_type"]))
    parts.append(genai.types.Part.from_text(text=prompt))

    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
    )
    if system_instruction:
        config.system_instruction = system_instruction
    if thinking_budget is not None:
        config.thinking_config = genai.types.ThinkingConfig(
            thinking_budget=thinking_budget,
        )
    if response_schema is not None:
        config.response_schema = response_schema
    if use_grounding:
        config.tools = [genai.types.Tool(google_search=genai.types.GoogleSearch())]

    response = client.models.generate_content(
        model=model, contents=parts, config=config,
    )
    record_gemini_call()
    return response.text


def _call_api(
    prompt: str,
    images: list[dict],
    model: str,
    **kwargs,
) -> str:
    """Dispatch to Claude or Gemini based on the model identifier."""
    if model == GEMINI_FLASH:
        return _call_gemini(prompt, images, model, **kwargs)
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
    GLM-OCR pipeline: uses GLM-OCR for high-quality document parsing,
    then a single Gemini call for structured extraction.

    Advantages over light mode:
    - GLM-OCR handles blurry/striped images much better than Tesseract
    - Only 1 Gemini call needed (richer OCR context reduces hallucination)

    Steps:
    1. Preprocess image
    2. Send to GLM-OCR → get structured markdown text
    3. Parse GLM-OCR text into structured fields (via parse_ocr_text)
    4. Single Gemini call: validate + fill gaps
    5. Math validation → inference → layout saving
    """
    start_time = time.time()

    image = Image.open(io.BytesIO(image_bytes))
    image.load()

    variants = prepare_variants(image)
    original = variants["original"]
    preprocessed = variants["preprocessed"]

    # Step 1: GLM-OCR — optimize image size first to avoid timeouts on large JPEGs
    logger.info("GLM-OCR: optimizing image for upload")
    glm_bytes, raw_media_type = _optimize_for_glm(image_bytes)
    raw_b64 = base64.b64encode(glm_bytes).decode("utf-8")
    logger.info("GLM-OCR: sending %d KB as %s", len(glm_bytes) // 1024, raw_media_type)
    glm_text = _call_glm_ocr(raw_b64, media_type=raw_media_type)
    logger.info("GLM-OCR: extracted %d characters", len(glm_text))

    # Step 2: Segment and run enhanced header OCR (Tesseract, for cross-reference)
    segmentation_result = segment_invoice(original)
    header_ocr_text = ""
    if segmentation_result.get("header") is not None:
        header_ocr_text = extract_text_enhanced(segmentation_result["header"])

    # Step 3: Parse GLM-OCR text into structured fields
    combined_text = glm_text
    if header_ocr_text.strip():
        combined_text += "\n\n--- HEADER REGION OCR ---\n" + header_ocr_text
    ocr_parsed = parse_ocr_text(combined_text)
    ocr_data = ocr_parsed.to_dict()

    # GLM-OCR output is high quality — assess accordingly
    ocr_useful_fields = [k for k in ocr_data if k != "items"]
    ocr_has_items = bool(ocr_data.get("items"))
    ocr_field_count = len(ocr_useful_fields) + (1 if ocr_has_items else 0)
    if ocr_field_count >= 3:
        ocr_quality = "good"
    elif ocr_field_count >= 1:
        ocr_quality = "poor"
    else:
        ocr_quality = "poor"  # GLM-OCR text is still richer than Tesseract even if unparsed
    logger.info("GLM-OCR parsed %d structured fields (quality=%s)", ocr_field_count, ocr_quality)

    # Step 4: Single Gemini call — OCR context is now much richer
    has_header_crop = segmentation_result.get("header") is not None
    preprocessed_b64 = _encode_image_base64(preprocessed)
    images = [
        {"base64": raw_b64, "media_type": raw_media_type},
        {"base64": preprocessed_b64, "media_type": "image/png"},
    ]
    if has_header_crop:
        images.append({
            "base64": _encode_image_base64(segmentation_result["header"]),
            "media_type": "image/png",
        })

    prompt = build_smart_pass_prompt(
        ocr_data, combined_text,
        has_header_crop=has_header_crop,
        has_binary_image=False,
        ocr_quality=ocr_quality,
        ocr_source="glm",
    )
    response = _call_gemini(
        prompt, images, GEMINI_FLASH,
        system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
    )
    result = _parse_json_response(response)
    gemini_calls = 1

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
        verify_response = _call_gemini(
            verify_prompt, images, GEMINI_FLASH,
            system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
        )
        verified = _parse_json_response(verify_response)
        gemini_calls += 1

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
    result = _cross_validate_invoice_number(result, ocr_parsed, combined_text)

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
        "pipeline": "glm-ocr-first",
        "scan_passes": gemini_calls,
        "scans_performed": gemini_calls,
        "verification_triggered": verification_triggered,
        "uncertain_fields": uncertain_fields,
        "uncertain_items_count": len(uncertain_items),
        "tiebreaker_triggered": False,
        "agreement_ratio": 1.0,
        "math_validation_triggered": math_validation_triggered,
        "api_calls": {"sonnet": 0, "opus": 0, "gemini": gemini_calls},
        "models_used": [GEMINI_FLASH] * gemini_calls,
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

    variants = prepare_variants(image)
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
    ocr_parsed = parse_ocr_text(combined_text)
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

    # Step 5: Single Gemini smart pass
    gemini_calls = 0
    uncertain_fields: list[str] = []
    uncertain_items: list[int] = []
    verification_triggered = False

    prompt = build_smart_pass_prompt(
        ocr_data, combined_text,
        has_header_crop=has_header_crop,
        has_binary_image=False,
        ocr_quality=ocr_quality,
        ocr_source=ocr_source,
    )
    response = _call_gemini(
        prompt, images, GEMINI_FLASH,
        system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
    )
    result = _parse_json_response(response)
    gemini_calls += 1

    # Step 5b: Optional verification pass
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
        verify_response = _call_gemini(
            verify_prompt, images, GEMINI_FLASH,
            system_instruction=ACCOUNTANT_SYSTEM_INSTRUCTION,
        )
        verified = _parse_json_response(verify_response)
        gemini_calls += 1

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
        "mode": "light",
        "pipeline": "glm-ocr-light",
        "ocr_source": ocr_source,
        "scan_passes": gemini_calls,
        "scans_performed": gemini_calls,
        "verification_triggered": verification_triggered,
        "uncertain_fields": uncertain_fields,
        "uncertain_items_count": len(uncertain_items),
        "tiebreaker_triggered": False,
        "agreement_ratio": 1.0,
        "math_validation_triggered": math_validation_triggered,
        "api_calls": {"sonnet": 0, "opus": 0, "gemini": gemini_calls},
        "models_used": [GEMINI_FLASH] * gemini_calls,
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
            logger.error("Failed to parse Gemini response as JSON: %s", e)
            return _error_result(mode, f"Invalid JSON in Gemini response: {e}")
        except genai.errors.ClientError as e:
            logger.error("Gemini API error: %s", e)
            return _error_result(mode, f"Gemini API error: {e}")
        except Exception as e:
            logger.error("GLM scan failed: %s", e, exc_info=True)
            return _error_result(mode, f"Scan failed: {e}")

    # Light mode: OCR-first pipeline
    if mode == "light":
        try:
            return _scan_light(image_bytes, debug)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini response as JSON: %s", e)
            return _error_result(mode, f"Invalid JSON in Gemini response: {e}")
        except genai.errors.ClientError as e:
            logger.error("Gemini API error: %s", e)
            return _error_result(mode, f"Gemini API error: {e}")
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
        gemini_count = sum(1 for m in models_used if m == GEMINI_FLASH)

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
                "gemini": gemini_count,
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
    except genai.errors.ClientError as e:
        logger.error("Gemini API error: %s", e)
        return _error_result(mode, f"Gemini API error: {e}")
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
