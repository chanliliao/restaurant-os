# Phase 08: Single Scan with Claude

**Date:** 2026-03-27
**Status:** Complete

## Goal
Send image + OCR text to Claude and get structured JSON back with confidence scores. Wire into the real API endpoint.

## Files to create/modify

### New files
1. `backend/scanner/scanning/prompts.py` -- Prompt template for invoice scanning
2. `backend/scanner/scanning/engine.py` -- Scan orchestrator + Claude API call

### Modified files
3. `backend/scanner/scanning/__init__.py` -- Export new functions
4. `backend/scanner/views.py` -- Replace dummy endpoint with real scanning
5. `backend/tests/test_scanning.py` -- Append engine/prompt/view tests (all mocked)

## Implementation steps

### Step 1: prompts.py
- `build_scan_prompt(ocr_text: str) -> str` returns the system+user prompt
- Instructs Claude to return exact JSON schema with confidence scores and inference_sources
- Includes OCR text as supplementary context

### Step 2: engine.py
- `_call_claude(prompt, images, model) -> str` -- raw API call with vision content blocks
- `scan_invoice(image_bytes, mode="normal", debug=False) -> dict` -- full orchestrator:
  1. PIL.Image.open from bytes
  2. prepare_variants()
  3. ocr_prepass() on preprocessed variant
  4. Base64 encode both variants
  5. Build prompt with OCR text
  6. Call Claude with images
  7. Parse JSON from response
  8. Attach scan_metadata
- Model map: light/normal -> claude-sonnet-4-20250514, heavy -> claude-opus-4-0-20250514

### Step 3: Update views.py
- Read uploaded image bytes
- Call scan_invoice(image_bytes, mode, debug)
- Return result as JSON response
- Error handling: 500 with message on failure

### Step 4: Tests (all mocked, no real API calls)
- TestBuildScanPrompt: contains required keywords, includes OCR text
- TestCallClaude: correct API structure, model passed through
- TestScanInvoice: full orchestration with mocked dependencies
- TestModelSelection: light->sonnet, normal->sonnet, heavy->opus
- TestScanInvoiceErrors: API failure returns error dict
- TestScanEndpointIntegration: Django test client with mocked engine

## Security checklist
- [ ] No API key in source code (reads from env)
- [ ] Input validation via serializer (image required, mode validated)
- [ ] Safe JSON parsing with try/except
- [ ] Image size already limited by Django settings (10MB)
