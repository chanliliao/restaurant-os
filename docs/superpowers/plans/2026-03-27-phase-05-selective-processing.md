# Phase 05: Selective Image Processing

**Date:** 2026-03-27
**Status:** In progress

## Goal
Apply only needed fixes based on quality assessment. Produce two image variants (original after orientation, preprocessed after selective enhancement) for Claude to cross-reference.

## Design Decisions

### Input/Output Types
- All functions accept both PIL Image and numpy ndarray (BGR or grayscale)
- All individual enhancement functions return PIL Image for consistency
- `prepare_variants` returns `{"original": PIL.Image, "preprocessed": PIL.Image, "quality_report": dict}`

### Enhancement Functions
1. **enhance_contrast(image)** — CLAHE histogram equalization; triggered when `quality_report["contrast"]["issue"]` is True
2. **sharpen(image)** — Unsharp mask kernel; triggered when `quality_report["blur"]["issue"]` is True
3. **denoise(image)** — cv2.fastNlMeansDenoisingColored (or bilateral fallback for grayscale); triggered when `quality_report["noise"]["issue"]` is True
4. **upscale(image, target_min=1000)** — Lanczos resampling; triggered when `quality_report["resolution"]["issue"]` is True
5. **to_grayscale(image)** — Always applied as final step for OCR readability

### Processing Order in selective_process
1. Upscale (if needed) — do first so subsequent filters work on higher-res data
2. Denoise (if needed) — remove noise before sharpening to avoid amplifying it
3. Enhance contrast (if needed) — equalize histogram
4. Sharpen (if needed) — apply last among conditional steps
5. Grayscale — always applied as final conversion

### Security
- No file I/O, no shell commands
- All processing is in-memory using PIL/OpenCV/numpy
- No external network calls

## Files Changed
- NEW: `backend/scanner/preprocessing/processor.py`
- EDIT: `backend/scanner/preprocessing/__init__.py` (add exports)
- APPEND: `backend/tests/test_preprocessing.py` (Phase 05 tests)

## Test Plan
- Test each enhancement function individually (returns PIL Image, measurably changes image)
- Test selective_process only applies needed transforms (blurry image gets sharpened, sharp one doesn't)
- Test clean image passes through selective_process mostly unchanged (only grayscale applied)
- Test prepare_variants returns correct dict structure with all three keys
- Test prepare_variants accepts both PIL and numpy inputs
- Run all Phase 03 + 04 + 05 tests together
