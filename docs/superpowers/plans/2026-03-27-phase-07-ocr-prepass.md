# Phase 07: OCR Pre-Pass — Implementation Plan

**Date:** 2026-03-27
**Status:** In progress

## Goal
Extract text from preprocessed invoice images using Tesseract OCR as supplementary data for Claude. The OCR text is passed alongside the image in the Claude prompt, giving the model two sources of information to cross-reference.

## Approach
1. Use pytesseract to run Tesseract OCR on PIL Images
2. Handle `TesseractNotFoundError` gracefully — return empty string, log warning
3. Support both single-image OCR and region-dict OCR (from segment_invoice output)
4. All tests mock pytesseract so they work without Tesseract installed

## Files
- **New:** `backend/scanner/scanning/ocr.py`
- **New:** `backend/tests/test_scanning.py`
- **Edit:** `backend/scanner/scanning/__init__.py` (add exports)

## Functions
- `extract_text(image)` — run Tesseract on a single PIL Image, return raw text string
- `extract_text_from_regions(regions_dict)` — takes dict from segment_invoice() (keys: header, line_items, totals, full), runs OCR on each non-None region, returns dict of region_name -> text
- `ocr_prepass(image)` — orchestrator: runs extract_text, handles errors gracefully

## Error Handling
- `TesseractNotFoundError` -> log warning, return empty string (or empty dict)
- Any other pytesseract exception -> log warning, return empty string
- Never crash the pipeline due to OCR failure

## Testing Strategy
- All tests mock `pytesseract.image_to_string` — no Tesseract dependency
- Test successful text extraction
- Test graceful handling of TesseractNotFoundError
- Test extract_text_from_regions with mixed None/Image values
- Test that return types are always str (or dict of str)
