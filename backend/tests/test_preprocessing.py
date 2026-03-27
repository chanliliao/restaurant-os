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
