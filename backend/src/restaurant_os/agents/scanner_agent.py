"""
Restaurant context-aware invoice scanner agent.

"""

from __future__ import annotations

import base64
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from PIL import Image

from restaurant_os.core.models import InvoiceLineItem, RestaurantContext, ScanResult, SupplierInfo
from restaurant_os.llm.glm_client import glm_client
from restaurant_os.tools.calculator import CalculatorInput, validate_invoice_math
from restaurant_os.tools.image_processor import ImageProcessorInput, preprocess_image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ScannerState(TypedDict):
    """
    State flowing through the scanner agent graph.

    The pipeline is linear: each node reads earlier fields and adds its own.
    LangGraph merges the returned dict into the shared state, so upstream
    fields are always available to downstream nodes without explicit passing.

    Compare with SmartScanner's engine.py, which threaded these values through
    function return values and local variables — no explicit state object existed.
    """

    scan_id: str
    """Unique run identifier generated at graph entry. Echoed in ScanResult."""

    image_bytes: bytes
    """Raw image data received from the API upload (POST /api/v1/scan)."""

    preprocessed_bytes: bytes | None
    """Orientation-corrected, resized bytes for GLM-OCR. Set by `preprocess`."""

    raw_ocr_text: str | None
    """Raw text returned by GLM-OCR before structured extraction. Set by `ocr`."""

    scan_result: ScanResult | None
    """Assembled scan result. Populated by `extract`; confidence updated by `validate`."""

    restaurant_context: RestaurantContext | None
    """Restaurant-scoped context for supplier inference and memory lookup."""

    error: str | None
    """
    Non-None when a node fails gracefully. Causes `complete` to return a
    minimal ScanResult with overall_confidence=0 rather than propagating an exception.
    """


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def preprocess(state: ScannerState) -> dict[str, Any]:
    """
    Apply image preprocessing before submitting to GLM-OCR.

    Ported from SmartScanner's preprocessing/ module — orientation correction,
    JPEG re-encoding for images > 500 KB, and size validation — now wrapped as
    a discrete graph node so it can be observed and retried independently.

    Populates `preprocessed_bytes`.
    """
    image_b64 = base64.b64encode(state["image_bytes"]).decode("utf-8")
    try:
        result = preprocess_image(ImageProcessorInput(image_b64=image_b64))
        preprocessed_bytes = base64.b64decode(result["preprocessed_b64"])
        logger.info(
            "scanner_agent.preprocess: quality=%s regions_detected=%s",
            result["quality_report"]["overall_quality"],
            result["segmentation"]["regions_detected"],
        )
        return {"preprocessed_bytes": preprocessed_bytes}
    except Exception as exc:
        logger.warning(
            "scanner_agent.preprocess: preprocessing failed (%s), using raw image", exc
        )
        # Fall back to raw image — OCR can still proceed on the original
        return {"preprocessed_bytes": state["image_bytes"]}


async def ocr(state: ScannerState) -> dict[str, Any]:
    """
    Submit the preprocessed image to GLM-OCR and return raw extracted text.

    Ported from SmartScanner's engine._call_glm_ocr() — rewritten as an async
    LangGraph node that stores the raw OCR output in state for the `extract` node.

    Populates `raw_ocr_text`.
    """
    image_bytes = state.get("preprocessed_bytes") or state["image_bytes"]
    try:
        raw_text = await glm_client.aocr(image_bytes)
        return {"raw_ocr_text": raw_text}
    except Exception as exc:
        logger.error("scanner_agent.ocr: GLM-OCR call failed: %s", exc)
        return {"error": f"OCR failed: {exc}", "raw_ocr_text": None}


async def extract(state: ScannerState) -> dict[str, Any]:
    """
    Extract structured invoice fields from raw OCR text using GLM-4-Flash.

    Calls the LLM with the system_prompt.yaml + scanner_prompt.yaml and the
    raw OCR text. Uses restaurant_context.known_suppliers as inference hints.

    Produces a partial ScanResult with line_items, supplier, totals, and
    per-field confidence scores. Math validation happens in the next node.
    """
    if state.get("error"):
        return {}

    raw_ocr_text = state.get("raw_ocr_text") or ""
    restaurant_context: RestaurantContext | None = state.get("restaurant_context")

    # Parse OCR text into structured fields for the prompt
    ocr_parsed = glm_client.parse_ocr_text(raw_ocr_text)
    ocr_data_json = json.dumps(ocr_parsed.to_dict(), indent=2)

    # Build supplier hints section if restaurant context is available
    supplier_hints_section = ""
    if restaurant_context and restaurant_context.known_suppliers:
        names = [s.name for s in restaurant_context.known_suppliers]
        supplier_hints_section = (
            "## Known Suppliers for This Restaurant\n"
            "The following suppliers have invoiced this restaurant before. "
            "If the invoice matches one of these, use the exact name shown:\n"
            + "\n".join(f"- {name}" for name in names)
        )

    # Load and render scanner_prompt.yaml
    scanner_template = glm_client.get_prompt_content("scanner_prompt")
    user_prompt = scanner_template.format(
        ocr_data_json=ocr_data_json,
        ocr_text=raw_ocr_text[:4000],  # cap to avoid token overflow
        supplier_hints_section=supplier_hints_section,
    )

    messages = [
        {"role": "system", "content": glm_client.get_prompt_content("system_prompt")},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await glm_client.achat(
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = response.get("content") or ""
        extracted = glm_client.parse_json_response(content)
    except Exception as exc:
        logger.error("scanner_agent.extract: LLM call failed: %s", exc)
        return {"error": f"Extraction failed: {exc}"}

    scan_result = _build_scan_result(
        state["scan_id"],
        extracted,
        raw_ocr_text=raw_ocr_text,
    )
    return {"scan_result": scan_result}


def _build_scan_result(
    scan_id: str,
    extracted: dict[str, Any],
    raw_ocr_text: str | None = None,
) -> ScanResult:
    """Convert the LLM JSON extraction dict into a ScanResult domain object."""
    supplier_name: str = extracted.get("supplier") or ""
    supplier: SupplierInfo | None = None
    if supplier_name:
        supplier = SupplierInfo(
            supplier_id=supplier_name.lower().replace(" ", "_")[:50],
            name=supplier_name,
        )

    invoice_date: datetime | None = None
    raw_date: str = extracted.get("date") or ""
    if raw_date:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
            try:
                invoice_date = datetime.strptime(raw_date, fmt)
                break
            except ValueError:
                continue

    line_items: list[InvoiceLineItem] = []
    for item in extracted.get("items") or []:
        if not isinstance(item, dict):
            continue
        description = item.get("name") or item.get("description") or ""
        if not description:
            continue
        line_items.append(
            InvoiceLineItem(
                description=description,
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                total_price=item.get("total"),
                unit=item.get("unit"),
                confidence=int(item.get("confidence") or 0),
            )
        )

    confidence_map: dict = extracted.get("confidence") or {}
    scores = [v for v in confidence_map.values() if isinstance(v, (int, float))]
    overall_confidence = int(sum(scores) / len(scores)) if scores else 0

    return ScanResult(
        scan_id=scan_id,
        supplier=supplier,
        invoice_date=invoice_date,
        line_items=line_items,
        subtotal=extracted.get("subtotal"),
        tax=extracted.get("tax"),
        total=extracted.get("total"),
        overall_confidence=overall_confidence,
        raw_ocr_text=raw_ocr_text,
    )


def validate(state: ScannerState) -> dict[str, Any]:
    """
    Run math validation on the extracted ScanResult.

    Ported from SmartScanner's scanner/scanning/validator.py — checks that
    subtotal + tax ≈ total within the tolerance defined in coding-standards.md.
    Auto-corrects line totals and recalculates subtotal/total when arithmetic
    errors are detected.
    """
    if state.get("error"):
        return {}

    scan_result: ScanResult | None = state.get("scan_result")
    if scan_result is None:
        return {}

    # Convert ScanResult to the dict format expected by the calculator
    scan_dict: dict[str, Any] = {
        "items": [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total": item.total_price,
            }
            for item in scan_result.line_items
        ],
        "subtotal": scan_result.subtotal,
        "tax": scan_result.tax,
        "total": scan_result.total,
    }

    validation = validate_invoice_math(CalculatorInput(scan_result=scan_dict, auto_correct=True))

    if not validation["valid"]:
        logger.warning(
            "scanner_agent.validate: %d math error(s) detected and corrected for scan %s",
            len(validation["errors"]),
            state["scan_id"],
        )

    corrected = validation.get("corrected_result", scan_dict)

    # Rebuild line items from corrected values
    corrected_items = corrected.get("items") or []
    updated_line_items = []
    for i, item in enumerate(scan_result.line_items):
        if i < len(corrected_items):
            updated_line_items.append(
                item.model_copy(update={"total_price": corrected_items[i].get("total", item.total_price)})
            )
        else:
            updated_line_items.append(item)

    updated_result = scan_result.model_copy(update={
        "line_items": updated_line_items,
        "subtotal": corrected.get("subtotal", scan_result.subtotal),
        "tax": corrected.get("tax", scan_result.tax),
        "total": corrected.get("total", scan_result.total),
    })

    return {"scan_result": updated_result}


def complete(state: ScannerState) -> dict[str, Any]:
    """
    Finalise the scan run and emit a log summary.

    If `error` is set (a node failed gracefully), returns a minimal ScanResult
    with overall_confidence=0 so the caller always receives a structured object.
    Otherwise, logs the final confidence and item count and returns unchanged.

    This node has no external dependencies and is fully implemented now.
    """
    if state.get("error"):
        logger.error(
            "scanner_agent: run %s failed: %s",
            state["scan_id"],
            state["error"],
        )
        return {
            "scan_result": ScanResult(
                scan_id=state["scan_id"],
                raw_ocr_text=state.get("raw_ocr_text"),
                overall_confidence=0,
            )
        }

    result = state.get("scan_result")
    if result is None:
        logger.warning(
            "scanner_agent: run %s completed but scan_result is None — returning empty result",
            state["scan_id"],
        )
        return {"scan_result": ScanResult(scan_id=state["scan_id"])}

    logger.info(
        "scanner_agent: run %s complete — confidence=%d, items=%d",
        state["scan_id"],
        result.overall_confidence,
        len(result.line_items),
    )
    return {}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_scanner_graph() -> StateGraph:
    """
    Construct and compile the scanner agent graph.

    Topology (linear — each step depends on the previous output):
        START → preprocess → ocr → extract → validate → complete → END

    Why LangGraph over a plain function call chain?
    - Each node is named and appears in LangSmith traces.
    - Checkpointing can resume from any node after a failure.
    - Adding a branching step (e.g. retry OCR on low confidence) is a single
      `add_conditional_edges` call — no refactor of the linear code required.

    Returns a compiled graph ready for .ainvoke() calls.
    """
    graph = StateGraph(ScannerState)

    graph.add_node("preprocess", preprocess)
    graph.add_node("ocr", ocr)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("complete", complete)

    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "ocr")
    graph.add_edge("ocr", "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "complete")
    graph.add_edge("complete", END)

    return graph.compile()


# Module-level compiled graph.
# Used by run_scan() below; can also be invoked directly:
#   from restaurant_os.agents.scanner_agent import scanner_graph
scanner_graph = build_scanner_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_scan(
    image_bytes: bytes,
    restaurant_context: RestaurantContext | None = None,
) -> ScanResult:
    """
    Run the full invoice scan pipeline for a given image.

    Called by POST /api/v1/scan in api/v1/routes.py.

    Args:
        image_bytes: raw image data from the multipart upload.
        restaurant_context: optional restaurant context for supplier inference.
            None until Section 6 wires up DB lookup.

    Returns:
        ScanResult with extracted fields, line items, and confidence scores.

    Raises:
        NotImplementedError: propagated from preprocess/ocr/extract/validate nodes
            until Sections 4 and 5 are implemented.
    """
    scan_id = str(uuid.uuid4())
    logger.info("scanner_agent: starting scan run %s", scan_id)

    initial_state: ScannerState = {
        "scan_id": scan_id,
        "image_bytes": image_bytes,
        "preprocessed_bytes": None,
        "raw_ocr_text": None,
        "scan_result": None,
        "restaurant_context": restaurant_context,
        "error": None,
    }

    final_state = await scanner_graph.ainvoke(initial_state)

    result: ScanResult | None = final_state.get("scan_result")
    if result is None:
        return ScanResult(scan_id=scan_id)
    return result
