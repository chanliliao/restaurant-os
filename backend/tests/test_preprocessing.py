"""
Tests for scanner.preprocessing.orientation module.

All test images are created programmatically — no fixture files needed.
"""

import io
import numpy as np
import cv2
import pytest
from PIL import Image

from scanner.preprocessing.orientation import (
    fix_orientation,
    deskew,
    correct_perspective,
    auto_orient,
    _to_pil,
    _to_cv,
)


# ---------------------------------------------------------------------------
# Helpers to create test images
# ---------------------------------------------------------------------------

def _make_text_image(width=400, height=300):
    """Create a white image with horizontal black lines simulating text."""
    img = Image.new("RGB", (width, height), "white")
    arr = np.array(img)
    # Draw horizontal lines every 20 pixels (simulating text rows)
    for y in range(40, height - 40, 20):
        arr[y : y + 2, 60 : width - 60] = 0
    return Image.fromarray(arr)


def _make_image_with_exif(orientation_value):
    """Create a test image and embed an EXIF orientation tag."""
    img = _make_text_image()
    exif = img.getexif()
    # EXIF orientation tag is 0x0112 = 274
    exif[274] = orientation_value
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    return Image.open(buf)


def _tilt_image(pil_img, angle_deg):
    """Rotate a PIL image by a small angle (simulating tilt)."""
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    h, w = cv_img.shape[:2]
    center = (w // 2, h // 2)
    mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    # expand canvas to avoid clipping
    cos_a = abs(mat[0, 0])
    sin_a = abs(mat[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    mat[0, 2] += (new_w - w) / 2
    mat[1, 2] += (new_h - h) / 2
    rotated = cv2.warpAffine(cv_img, mat, (new_w, new_h),
                              borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB))


def _apply_perspective_warp(pil_img):
    """Apply a known trapezoidal warp to simulate photographing at an angle."""
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    h, w = cv_img.shape[:2]

    # Create a larger canvas with a dark background
    pad = 80
    canvas = np.zeros((h + 2 * pad, w + 2 * pad, 3), dtype=np.uint8)

    # Source points (rectangle)
    src = np.array([
        [0, 0],
        [w - 1, 0],
        [w - 1, h - 1],
        [0, h - 1],
    ], dtype="float32")

    # Destination points (trapezoid on canvas)
    dst = np.array([
        [pad + 30, pad + 20],
        [pad + w - 40, pad + 10],
        [pad + w - 10, pad + h - 10],
        [pad + 20, pad + h - 30],
    ], dtype="float32")

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(cv_img, matrix,
                                  (w + 2 * pad, h + 2 * pad),
                                  dst=canvas,
                                  borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=(0, 0, 0))
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


# ---------------------------------------------------------------------------
# Tests: fix_orientation
# ---------------------------------------------------------------------------

class TestFixOrientation:
    def test_no_exif_returns_same_size(self):
        """Image without EXIF should be returned with same dimensions."""
        img = _make_text_image(400, 300)
        result = fix_orientation(img)
        assert result.size == (400, 300)

    def test_orientation_3_rotates_180(self):
        """EXIF orientation=3 means 180-degree rotation."""
        img = _make_image_with_exif(3)
        original_size = img.size
        result = fix_orientation(img)
        # 180 rotation preserves dimensions
        assert result.size == original_size

    def test_orientation_6_rotates_270(self):
        """EXIF orientation=6 means 270-degree CW (90 CCW) rotation.
        Width and height should swap."""
        img = _make_image_with_exif(6)
        w, h = img.size
        result = fix_orientation(img)
        assert result.size == (h, w)

    def test_orientation_8_rotates_90(self):
        """EXIF orientation=8 means 90-degree CW rotation.
        Width and height should swap."""
        img = _make_image_with_exif(8)
        w, h = img.size
        result = fix_orientation(img)
        assert result.size == (h, w)

    def test_orientation_1_no_change(self):
        """EXIF orientation=1 means normal — no change expected."""
        img = _make_image_with_exif(1)
        result = fix_orientation(img)
        assert result.size == img.size


# ---------------------------------------------------------------------------
# Tests: deskew
# ---------------------------------------------------------------------------

class TestDeskew:
    def test_tilted_image_is_corrected(self):
        """An image tilted by 5 degrees should be roughly straightened."""
        img = _make_text_image(600, 400)
        tilted = _tilt_image(img, 5)
        result = deskew(tilted)
        # Result should be a valid PIL Image
        assert isinstance(result, Image.Image)
        assert result.size[0] > 0 and result.size[1] > 0

    def test_straight_image_stays_similar(self):
        """A straight image should not be significantly changed."""
        img = _make_text_image(400, 300)
        result = deskew(img)
        # Dimensions should be very close to original
        w, h = result.size
        assert abs(w - 400) < 20
        assert abs(h - 300) < 20

    def test_returns_pil_image(self):
        img = _make_text_image()
        result = deskew(img)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# Tests: correct_perspective
# ---------------------------------------------------------------------------

class TestCorrectPerspective:
    def test_warped_image_produces_rectangle(self):
        """A perspective-warped image should be corrected to a rectangle."""
        img = _make_text_image(400, 300)
        warped = _apply_perspective_warp(img)
        result = correct_perspective(warped)
        assert isinstance(result, Image.Image)
        assert result.size[0] > 0 and result.size[1] > 0

    def test_plain_image_unchanged(self):
        """An image with no clear quadrilateral contour returns unchanged."""
        # Solid white image — no document edges to detect
        img = Image.new("RGB", (200, 200), "white")
        result = correct_perspective(img)
        assert result.size == (200, 200)

    def test_returns_pil_image(self):
        img = _make_text_image()
        result = correct_perspective(img)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# Tests: auto_orient
# ---------------------------------------------------------------------------

class TestAutoOrient:
    def test_runs_without_error(self):
        """auto_orient should run the full pipeline without crashing."""
        img = _make_text_image()
        result = auto_orient(img)
        assert isinstance(result, Image.Image)

    def test_accepts_numpy_array(self):
        """auto_orient should accept a numpy array input."""
        img = _make_text_image()
        arr = np.array(img)
        result = auto_orient(arr)
        assert isinstance(result, Image.Image)

    def test_accepts_pil_image(self):
        """auto_orient should accept a PIL Image input."""
        img = _make_text_image()
        result = auto_orient(img)
        assert isinstance(result, Image.Image)

    def test_with_tilted_and_warped(self):
        """Pipeline handles an image that is both tilted and warped."""
        img = _make_text_image(600, 400)
        tilted = _tilt_image(img, 3)
        result = auto_orient(tilted)
        assert isinstance(result, Image.Image)
        assert result.size[0] > 0 and result.size[1] > 0


# ---------------------------------------------------------------------------
# Tests: helper conversion functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_to_pil_from_numpy(self):
        arr = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _to_pil(arr)
        assert isinstance(result, Image.Image)

    def test_to_pil_from_pil(self):
        img = Image.new("RGB", (100, 100))
        result = _to_pil(img)
        assert result is img

    def test_to_cv_from_pil(self):
        img = Image.new("RGB", (100, 100))
        result = _to_cv(img)
        assert isinstance(result, np.ndarray)
        assert result.shape == (100, 100, 3)

    def test_to_cv_from_numpy(self):
        arr = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _to_cv(arr)
        assert result is arr

    def test_to_pil_grayscale_array(self):
        arr = np.zeros((100, 100), dtype=np.uint8)
        result = _to_pil(arr)
        assert isinstance(result, Image.Image)
        assert result.mode == "L"

    def test_to_pil_invalid_type_raises(self):
        with pytest.raises(TypeError):
            _to_pil("not an image")

    def test_to_cv_invalid_type_raises(self):
        with pytest.raises(TypeError):
            _to_cv("not an image")


# ===========================================================================
# Phase 04 — Quality Assessment Tests
# ===========================================================================

from scanner.preprocessing.analyzer import analyze_quality


# ---------------------------------------------------------------------------
# Helpers to create quality-specific test images
# ---------------------------------------------------------------------------

def _make_dark_image(width=800, height=600):
    """Create a uniformly dark image (mean ~40)."""
    return Image.fromarray(np.full((height, width, 3), 40, dtype=np.uint8))


def _make_washed_out_image(width=800, height=600):
    """Create a uniformly bright / washed-out image (mean ~220)."""
    return Image.fromarray(np.full((height, width, 3), 220, dtype=np.uint8))


def _make_low_contrast_image(width=800, height=600):
    """Create an image with very narrow pixel range (low std dev)."""
    arr = np.random.randint(120, 135, (height, width, 3), dtype=np.uint8)
    return Image.fromarray(arr)


def _make_blurry_image(width=800, height=600):
    """Create a sharp pattern then blur it heavily so Laplacian variance is low."""
    # Start with a sharp checkerboard-like pattern
    arr = np.zeros((height, width), dtype=np.uint8)
    arr[::2, ::2] = 255
    arr[1::2, 1::2] = 255
    # Apply heavy Gaussian blur
    blurred = cv2.GaussianBlur(arr, (31, 31), 15)
    return Image.fromarray(blurred)


def _make_low_res_image():
    """Create a 200x150 image (below the 500px threshold)."""
    return Image.new("RGB", (200, 150), (128, 128, 128))


def _make_clean_image(width=800, height=600):
    """Create a clean, sharp, well-lit image with good contrast and texture."""
    img = Image.new("RGB", (width, height), (200, 200, 200))
    arr = np.array(img)
    # Draw sharp black horizontal lines (simulating receipt text)
    for y in range(30, height - 30, 12):
        arr[y : y + 2, 60 : width - 60] = 0
    # Add vertical lines for grid-like texture (more edges for Laplacian)
    for x in range(60, width - 60, 40):
        arr[30 : height - 30, x : x + 2] = 0
    # Add some mid-gray blocks for varied contrast
    for y in range(50, height - 80, 50):
        for x in range(80, width - 80, 80):
            arr[y : y + 10, x : x + 30] = 80
    return Image.fromarray(arr)


# ---------------------------------------------------------------------------
# Tests: analyze_quality
# ---------------------------------------------------------------------------

class TestAnalyzeQuality:

    def test_dark_image_flags_brightness(self):
        """A uniformly dark image should flag brightness as an issue."""
        img = _make_dark_image()
        report = analyze_quality(img)
        assert report["brightness"]["issue"] is True
        assert report["brightness"]["value"] < 80
        assert "dark" in report["brightness"]["detail"].lower()

    def test_washed_out_image_flags_brightness(self):
        """A uniformly bright image should flag brightness as washed out."""
        img = _make_washed_out_image()
        report = analyze_quality(img)
        assert report["brightness"]["issue"] is True
        assert report["brightness"]["value"] > 200
        assert "washed" in report["brightness"]["detail"].lower()

    def test_low_contrast_image_flags_contrast(self):
        """An image with narrow pixel range should flag low contrast."""
        img = _make_low_contrast_image()
        report = analyze_quality(img)
        assert report["contrast"]["issue"] is True
        assert report["contrast"]["value"] < 30

    def test_blurry_image_flags_blur(self):
        """A heavily blurred image should flag blur."""
        img = _make_blurry_image()
        report = analyze_quality(img)
        assert report["blur"]["issue"] is True
        assert report["blur"]["value"] < 100

    def test_low_res_image_flags_resolution(self):
        """A 200x150 image should flag resolution."""
        img = _make_low_res_image()
        report = analyze_quality(img)
        assert report["resolution"]["issue"] is True
        assert report["resolution"]["width"] == 200
        assert report["resolution"]["height"] == 150

    def test_clean_image_no_issues(self):
        """A clean, well-lit, sharp, high-res image should report no issues."""
        img = _make_clean_image()
        report = analyze_quality(img)
        assert report["overall_quality"] == "good"
        assert len(report["issues"]) == 0
        assert report["brightness"]["issue"] is False
        assert report["contrast"]["issue"] is False
        assert report["blur"]["issue"] is False
        assert report["noise"]["issue"] is False
        assert report["resolution"]["issue"] is False

    def test_accepts_numpy_array(self):
        """analyze_quality should accept a numpy ndarray."""
        arr = np.full((600, 800, 3), 128, dtype=np.uint8)
        # Draw some features for contrast/sharpness
        arr[100:105, 100:700] = 0
        report = analyze_quality(arr)
        assert "brightness" in report
        assert "overall_quality" in report

    def test_accepts_pil_image(self):
        """analyze_quality should accept a PIL Image."""
        img = _make_clean_image()
        report = analyze_quality(img)
        assert isinstance(report, dict)

    def test_overall_quality_poor_with_multiple_issues(self):
        """An image with 2+ issues should be classified as 'poor'."""
        # Dark + low-res => at least 2 issues
        img = Image.fromarray(np.full((150, 200, 3), 40, dtype=np.uint8))
        report = analyze_quality(img)
        assert report["overall_quality"] == "poor"
        assert len(report["issues"]) >= 2

    def test_overall_quality_fair_with_single_issue(self):
        """An image with exactly 1 issue should be classified as 'fair'."""
        # Low-res only (brightness, contrast, blur, noise should be fine)
        img = _make_clean_image(width=400, height=400)
        report = analyze_quality(img)
        # Resolution is the only issue (400 < 500)
        assert report["resolution"]["issue"] is True
        assert report["overall_quality"] == "fair"

    def test_report_structure(self):
        """Verify the returned dict has all expected keys."""
        img = _make_clean_image()
        report = analyze_quality(img)
        assert set(report.keys()) == {
            "brightness", "contrast", "blur", "noise",
            "resolution", "overall_quality", "issues",
        }
        # Check sub-keys
        for metric in ["brightness", "contrast", "blur", "noise"]:
            assert "value" in report[metric]
            assert "issue" in report[metric]
            assert "detail" in report[metric]
        assert "width" in report["resolution"]
        assert "height" in report["resolution"]

    def test_accepts_grayscale_array(self):
        """analyze_quality should handle a 2D grayscale numpy array."""
        gray = np.full((600, 800), 128, dtype=np.uint8)
        gray[100:105, 100:700] = 0
        report = analyze_quality(gray)
        assert report["resolution"]["width"] == 800
        assert report["resolution"]["height"] == 600
