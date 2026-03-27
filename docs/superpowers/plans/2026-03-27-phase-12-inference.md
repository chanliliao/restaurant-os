# Phase 12: Three-Tier Inference System

## Goal
Fill missing or low-confidence fields using a three-tier fallback: supplier memory -> industry memory -> AI reasoning.

## Files to create/modify
1. **Create** `backend/scanner/memory/inference.py` — Core inference engine
2. **Modify** `backend/scanner/memory/__init__.py` — Export new functions
3. **Modify** `backend/scanner/scanning/engine.py` — Wire inference after math validation
4. **Create** `backend/tests/test_inference.py` — Comprehensive tests

## Design

### `infer_field(field_name, scan_result, supplier_id, supplier_memory, general_memory)`
- Tier 1 (confidence=80): `supplier_memory.infer_missing(supplier_id, field)` for top-level fields; check `item_history` for item fields
- Tier 2 (confidence=60): `general_memory.get_industry_profile()` for tax_rate; `get_item_catalog()` for item prices/units
- Tier 3 (confidence=50): Call Claude Sonnet with partial invoice context, ask it to reason about the missing field
- Returns `{"value": Any, "source": str|None, "confidence": int}`

### `run_inference(scan_result, supplier_id, supplier_memory, general_memory, confidence_threshold=60)`
- Iterate top-level fields (supplier, date, invoice_number, subtotal, tax, total, tax_rate)
- Check confidence dict — if below threshold or inference_sources says "missing"/"inferred", attempt `infer_field`
- For items: check each item's fields against supplier item_history and industry catalog
- Only replace if inferred confidence > existing confidence
- Returns updated scan_result with inference_sources updated

### Engine integration
- After math validation in `scan_invoice()`, call `run_inference()` if supplier_id is available
- Add `inference_tier_used` to scan_metadata

## Test plan
- Tier 1: supplier has historical tax_rate -> uses it
- Tier 2: no supplier data, industry catalog has item price -> uses it
- Tier 3: mock Claude API, no local data -> calls AI, returns inferred value
- High-confidence fields NOT overridden
- New supplier with no history -> falls through to tier 2/3
- Missing supplier_id -> skip tier 1, try tier 2/3
- All external calls mocked (Claude API, memory stores)
