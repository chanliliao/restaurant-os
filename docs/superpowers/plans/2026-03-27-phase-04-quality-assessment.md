# Phase 04: Quality Assessment — Implementation Plan

**Date:** 2026-03-27
**Goal:** Analyze image quality and report issues before scanning.

## Summary

Add `backend/scanner/preprocessing/analyzer.py` that measures five quality metrics (brightness, contrast, blur, noise, resolution) and returns a structured quality report. This sits after orientation correction in the preprocessing pipeline.

## Tasks

### 1. Create `analyzer.py`
- Accept both PIL Image and numpy array inputs (reuse `_to_cv` / `_to_pil` helpers from orientation module)
- Implement five metric functions:
  - `_measure_brightness(gray)` — mean pixel intensity; flag if < 80 or > 200
  - `_measure_contrast(gray)` — std dev of pixel values; flag if < 30
  - `_measure_blur(gray)` — Laplacian variance; flag if < 100
  - `_measure_noise(gray)` — high-frequency energy via difference from Gaussian blur; flag if ratio is excessive
  - `_measure_resolution(image)` — check width/height; flag if either < 500
- `analyze_quality(image)` — orchestrator returning the full report dict
- Compute `overall_quality`: "poor" if 2+ issues, "fair" if 1 issue, "good" if 0

### 2. Export from `__init__.py`
- Add `analyze_quality` to the preprocessing package exports

### 3. Add tests to `test_preprocessing.py`
- Append new test class `TestAnalyzeQuality` after existing Phase 03 tests
- Programmatically create test images:
  - Dark image (all pixels ~40) — should flag brightness
  - Washed-out image (all pixels ~220) — should flag brightness
  - Low-contrast image (narrow pixel range) — should flag contrast
  - Blurry image (heavy Gaussian blur) — should flag blur
  - Low-res image (200x150) — should flag resolution
  - Clean image (800x600, good contrast, sharp) — should report no issues
- Test that `analyze_quality` accepts numpy arrays
- Test overall_quality classification

### 4. Security scan
- Review for path traversal, arbitrary file access, DoS via large images
- Ensure no file I/O — function operates only on in-memory image data

### 5. Commit, push, update tracker

## Dependencies
- Already installed: Pillow, opencv-python-headless, numpy
- No new dependencies needed

## Risk
- Noise threshold tuning — use conservative threshold, can adjust later
- All metrics are deterministic math on pixel arrays — low risk
