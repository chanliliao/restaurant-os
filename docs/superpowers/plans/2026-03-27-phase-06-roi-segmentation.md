# Phase 06: ROI Segmentation — Implementation Plan

**Date:** 2026-03-27
**Status:** In progress

## Goal
Detect and crop invoice images into focused regions (header, line items, totals) for more accurate downstream OCR scanning.

## Approach
1. Convert image to grayscale, apply adaptive threshold
2. Detect horizontal divider lines using morphological operations
3. If dividers found (2+), split into header/line_items/totals based on line positions
4. If fewer than 2 dividers, use heuristic split: top 25%, middle 50%, bottom 25%
5. If image too small or detection fails entirely, return {"full": image} fallback
6. Always include `full` image in output for fallback usage

## Files
- **New:** `backend/scanner/preprocessing/segmentation.py`
- **Edit:** `backend/scanner/preprocessing/__init__.py` (add exports)
- **Append:** `backend/tests/test_preprocessing.py` (new test class)

## Functions
- `detect_regions(image)` — returns bounding boxes dict
- `crop_regions(image, regions)` — crops image per bounding boxes, returns dict of PIL Images
- `segment_invoice(image)` — orchestrator combining detect + crop + fallback

## Return Format
```python
{
    "header": PIL.Image | None,
    "line_items": PIL.Image | None,
    "totals": PIL.Image | None,
    "full": PIL.Image,
    "regions_detected": bool,
    "bounding_boxes": {"header": (x,y,w,h), "line_items": (x,y,w,h), "totals": (x,y,w,h)}
}
```

## Test Cases
1. Receipt-like image with clear horizontal dividers -> regions detected
2. Image without dividers -> heuristic fallback (still regions_detected=True with heuristic)
3. Very small image (<50px) -> full-image fallback only
4. PIL Image input accepted
5. numpy array input accepted
6. Crop regions returns valid PIL Images with correct dimensions
7. Bounding boxes match cropped region sizes

## Security
- No file I/O, no shell commands, all in-memory processing
- Input validation for image type
- No user-supplied strings used in any execution context
