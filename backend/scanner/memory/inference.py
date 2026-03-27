"""Three-tier inference engine for filling missing/low-confidence invoice fields.

Tier 1: Supplier-specific memory (confidence 80)
Tier 2: General industry memory (confidence 60)
Tier 3: AI contextual reasoning via Claude (confidence 50)
"""

import json
import logging
from typing import Any

import anthropic

from .interface import GeneralMemory, SupplierMemory

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-20250514"

# Fields that can be inferred at the top level
INFERABLE_FIELDS = ("supplier", "date", "invoice_number", "subtotal", "tax", "total", "tax_rate")


def _tier1_supplier(field_name: str, supplier_id: str | None,
                    supplier_memory: SupplierMemory | None,
                    scan_result: dict) -> dict | None:
    """Tier 1: Look up field from supplier's historical data.

    Returns inference dict or None if no data found.
    """
    if not supplier_id or not supplier_memory:
        return None

    try:
        value = supplier_memory.infer_missing(supplier_id, field_name)
    except (ValueError, OSError):
        logger.debug("Tier 1 lookup failed for supplier=%s field=%s", supplier_id, field_name)
        return None

    if value is not None:
        return {
            "value": value,
            "source": "tier1_supplier",
            "confidence": 80,
        }

    return None


def _tier2_industry(field_name: str, general_memory: GeneralMemory | None,
                    scan_result: dict) -> dict | None:
    """Tier 2: Look up field from general industry data.

    Returns inference dict or None if no data found.
    """
    if not general_memory:
        return None

    try:
        if field_name == "tax_rate":
            profile = general_memory.get_industry_profile()
            typical_rates = profile.get("typical_tax_rates", [])
            if typical_rates:
                # Use the most common rate (middle of the sorted list)
                mid = len(typical_rates) // 2
                return {
                    "value": typical_rates[mid],
                    "source": "tier2_industry",
                    "confidence": 60,
                }
        # For other top-level fields, industry memory is unlikely to help
        # (supplier name, date, invoice number are supplier-specific)
    except (OSError, KeyError):
        logger.debug("Tier 2 lookup failed for field=%s", field_name)

    return None


def _tier2_industry_item(item: dict, general_memory: GeneralMemory | None) -> dict:
    """Tier 2: Fill missing item fields from industry catalog.

    Returns dict of field updates (may be empty).
    """
    updates = {}
    if not general_memory:
        return updates

    item_name = item.get("name") or item.get("description")
    if not item_name:
        return updates

    try:
        catalog = general_memory.get_item_catalog()
        catalog_items = catalog.get("items", {})
        catalog_entry = catalog_items.get(item_name)
        if not catalog_entry:
            return updates

        if not item.get("unit_price") and catalog_entry.get("avg_price"):
            updates["unit_price"] = {
                "value": catalog_entry["avg_price"],
                "source": "tier2_industry",
                "confidence": 60,
            }
        if not item.get("unit") and catalog_entry.get("common_unit"):
            updates["unit"] = {
                "value": catalog_entry["common_unit"],
                "source": "tier2_industry",
                "confidence": 60,
            }
    except (OSError, KeyError):
        logger.debug("Tier 2 item lookup failed for item=%s", item_name)

    return updates


def _tier1_supplier_item(item: dict, supplier_id: str | None,
                         supplier_memory: SupplierMemory | None) -> dict:
    """Tier 1: Fill missing item fields from supplier history.

    Returns dict of field updates (may be empty).
    """
    updates = {}
    if not supplier_id or not supplier_memory:
        return updates

    item_name = item.get("name") or item.get("description")
    if not item_name:
        return updates

    try:
        profile = supplier_memory.get_profile(supplier_id)
        item_history = profile.get("item_history", {})
        hist_entry = item_history.get(item_name)
        if not hist_entry:
            return updates

        if not item.get("unit_price") and hist_entry.get("avg_price"):
            updates["unit_price"] = {
                "value": hist_entry["avg_price"],
                "source": "tier1_supplier",
                "confidence": 80,
            }
        if not item.get("unit") and hist_entry.get("common_unit"):
            updates["unit"] = {
                "value": hist_entry["common_unit"],
                "source": "tier1_supplier",
                "confidence": 80,
            }
    except (ValueError, OSError):
        logger.debug("Tier 1 item lookup failed for supplier=%s item=%s",
                     supplier_id, item_name)

    return updates


def _build_tier3_prompt(field_name: str, scan_result: dict) -> str:
    """Build a focused prompt for Claude to reason about a missing field."""
    # Build a sanitised context (exclude raw images, metadata, etc.)
    context = {}
    for key in INFERABLE_FIELDS:
        if key in scan_result and scan_result[key] is not None:
            context[key] = scan_result[key]

    items_summary = []
    for item in scan_result.get("items", []):
        items_summary.append({
            k: v for k, v in item.items()
            if k in ("name", "description", "quantity", "unit", "unit_price", "total_price")
        })
    if items_summary:
        context["items"] = items_summary

    return (
        f"You are analyzing a restaurant supply invoice. The field '{field_name}' "
        f"is missing or low-confidence. Based on the other extracted fields, "
        f"what is the most likely value for '{field_name}'?\n\n"
        f"Extracted invoice data:\n{json.dumps(context, indent=2)}\n\n"
        f"Respond with ONLY a JSON object: "
        f'{{"value": <your best estimate>, "reasoning": "<brief explanation>"}}\n'
        f"If you cannot reasonably infer this field, respond with: "
        f'{{"value": null, "reasoning": "insufficient context"}}'
    )


def _tier3_ai(field_name: str, scan_result: dict) -> dict | None:
    """Tier 3: Use Claude to reason about the missing field.

    Returns inference dict or None if AI cannot infer.
    """
    prompt = _build_tier3_prompt(field_name, scan_result)

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=SONNET,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse response — handle markdown fences
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl + 1:]
            if text.endswith("```"):
                text = text[:-3].strip()

        result = json.loads(text)
        value = result.get("value")
        if value is not None:
            return {
                "value": value,
                "source": "tier3_ai",
                "confidence": 50,
            }
    except (anthropic.APIError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Tier 3 AI inference failed for field=%s: %s", field_name, exc)
    except Exception as exc:
        logger.warning("Tier 3 AI inference unexpected error for field=%s: %s",
                       field_name, exc)

    return None


def infer_field(field_name: str, scan_result: dict,
                supplier_id: str | None,
                supplier_memory: SupplierMemory | None,
                general_memory: GeneralMemory | None) -> dict:
    """Try to fill a missing or low-confidence field using three tiers.

    Tier 1: Supplier-specific memory (most trusted, confidence=80)
    Tier 2: General industry memory (cross-supplier, confidence=60)
    Tier 3: AI contextual reasoning (Claude Sonnet, confidence=50)

    Returns:
        {"value": Any, "source": "tier1_supplier"|"tier2_industry"|"tier3_ai"|None,
         "confidence": int}
    """
    # Tier 1
    result = _tier1_supplier(field_name, supplier_id, supplier_memory, scan_result)
    if result:
        return result

    # Tier 2
    result = _tier2_industry(field_name, general_memory, scan_result)
    if result:
        return result

    # Tier 3
    result = _tier3_ai(field_name, scan_result)
    if result:
        return result

    return {"value": None, "source": None, "confidence": 0}


def run_inference(scan_result: dict, supplier_id: str | None,
                  supplier_memory: SupplierMemory | None,
                  general_memory: GeneralMemory | None,
                  confidence_threshold: int = 60) -> dict:
    """Scan all fields and infer missing/low-confidence values.

    For any field with confidence below threshold or marked as
    "missing"/"inferred" in inference_sources, attempt three-tier inference.

    Only replaces a value if inferred confidence > existing confidence.

    Args:
        scan_result: The scan result dict (modified in place and returned).
        supplier_id: Normalized supplier ID, or None for unknown suppliers.
        supplier_memory: SupplierMemory instance, or None.
        general_memory: GeneralMemory instance, or None.
        confidence_threshold: Fields below this confidence are candidates.

    Returns:
        Updated scan_result with inferred values and updated inference_sources.
    """
    confidence = scan_result.get("confidence", {})
    inference_sources = scan_result.get("inference_sources", {})
    tiers_used = []

    # --- Top-level fields ---
    for field in INFERABLE_FIELDS:
        field_conf = confidence.get(field, 0)
        field_source = inference_sources.get(field, "")

        needs_inference = (
            field_conf < confidence_threshold
            or field_source in ("missing", "inferred")
            or (field in scan_result and scan_result[field] is None)
        )

        if not needs_inference:
            continue

        inferred = infer_field(field, scan_result, supplier_id,
                               supplier_memory, general_memory)

        if inferred["value"] is not None and inferred["confidence"] > field_conf:
            scan_result[field] = inferred["value"]
            confidence[field] = inferred["confidence"]
            inference_sources[field] = inferred["source"]
            tiers_used.append({"field": field, "tier": inferred["source"]})

    # --- Item-level fields ---
    items = scan_result.get("items", [])
    for item in items:
        item_updates = {}

        # Tier 1: supplier item history
        t1 = _tier1_supplier_item(item, supplier_id, supplier_memory)
        for fld, inf in t1.items():
            item_updates[fld] = inf

        # Tier 2: industry catalog (only for fields not already filled by tier 1)
        t2 = _tier2_industry_item(item, general_memory)
        for fld, inf in t2.items():
            if fld not in item_updates:
                item_updates[fld] = inf

        # Apply updates
        for fld, inf in item_updates.items():
            item[fld] = inf["value"]
            # Track source at item level
            if "inference_sources" not in item:
                item["inference_sources"] = {}
            item["inference_sources"][fld] = inf["source"]
            tiers_used.append({
                "field": f"item.{item.get('name', '?')}.{fld}",
                "tier": inf["source"],
            })

    # Update the result
    scan_result["confidence"] = confidence
    scan_result["inference_sources"] = inference_sources

    # Track in metadata
    metadata = scan_result.get("scan_metadata", {})
    metadata["inference_tiers_used"] = tiers_used
    metadata["inference_fields_filled"] = len(tiers_used)
    scan_result["scan_metadata"] = metadata

    return scan_result
