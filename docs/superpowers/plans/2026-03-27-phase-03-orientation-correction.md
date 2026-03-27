# Phase 03: Orientation & Skew Correction — Implementation Plan

## Goal
Auto-fix rotated, tilted, and perspective-distorted invoice images before any quality assessment or OCR.

## Module
`backend/scanner/preprocessing/orientation.py`

## Functions

### 1. `fix_orientation(image)`
- Accept PIL Image or numpy array; normalize to PIL Image internally
- Read EXIF orientation tag (tag 0x0112)
- Apply corresponding rotation/transpose to correct orientation
- Return corrected PIL Image

### 2. `deskew(image)`
- Convert to grayscale numpy array
- Apply Canny edge detection
- Use Hough line transform to detect dominant line angles
- Compute median angle deviation from horizontal
- Rotate image by the negative of that angle to straighten
- Return corrected PIL Image

### 3. `correct_perspective(image)`
- Convert to grayscale numpy array
- Apply adaptive threshold + morphological close to find document contour
- Find largest quadrilateral contour (4-point approximation)
- If a valid quadrilateral is found, compute perspective warp to a rectangle
- If no quadrilateral found, return image unchanged
- Return corrected PIL Image

### 4. `auto_orient(image)`
- Run fix_orientation -> deskew -> correct_perspective in sequence
- Each step's output feeds the next
- Return final corrected PIL Image

## Helper
- `_to_pil(image)` — convert numpy array to PIL Image if needed
- `_to_cv(image)` — convert PIL Image to numpy array if needed

## Tests (`backend/tests/test_preprocessing.py`)

### Fixtures (created programmatically)
- Base test image: white rectangle with black text-like horizontal lines
- Rotated variants: 90, 180, 270 degrees
- Tilted variant: 5-degree clockwise tilt
- Perspective variant: apply known perspective warp

### Test cases
1. `test_fix_orientation_90` — rotate 90, fix, verify dimensions restored
2. `test_fix_orientation_180` — rotate 180, fix, verify pixel similarity
3. `test_fix_orientation_270` — rotate 270, fix, verify dimensions restored
4. `test_fix_orientation_no_exif` — image without EXIF returns unchanged
5. `test_deskew_tilted_image` — tilt 5 degrees, deskew, verify angle reduced
6. `test_deskew_already_straight` — straight image stays unchanged
7. `test_correct_perspective_warped` — apply known warp, correct, verify rectangular
8. `test_correct_perspective_no_contour` — plain image returns unchanged
9. `test_auto_orient_runs_all` — verify orchestrator runs without error
10. `test_accepts_numpy_array` — pass numpy array, verify it works
11. `test_accepts_pil_image` — pass PIL Image, verify it works

## Security review
- No file I/O (images passed as in-memory objects)
- No shell commands or user-controlled paths
- No pickle/eval/exec
- pip-audit on dependencies

## Sequence
1. Write plan (this file)
2. Implement orientation.py
3. Write tests
4. Run tests, iterate until green
5. Security scan
6. Commit + push
7. Update tracker
8. Commit + push tracker update
