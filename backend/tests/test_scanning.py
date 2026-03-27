"""
Tests for scanner.scanning.ocr module.

All tests mock pytesseract so they work without Tesseract installed.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from scanner.scanning.ocr import extract_text, extract_text_from_regions, ocr_prepass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_image(width=200, height=100):
    """Create a simple white PIL Image for testing."""
    return Image.new("RGB", (width, height), "white")


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    """Tests for the extract_text function."""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_returns_extracted_text(self, mock_tess):
        mock_tess.image_to_string.return_value = "TOTAL: $12.50\n"
        img = _make_test_image()
        result = extract_text(img)
        assert result == "TOTAL: $12.50\n"
        mock_tess.image_to_string.assert_called_once_with(img)

    @patch("scanner.scanning.ocr.pytesseract")
    def test_returns_string_type(self, mock_tess):
        mock_tess.image_to_string.return_value = "some text"
        result = extract_text(_make_test_image())
        assert isinstance(result, str)

    @patch("scanner.scanning.ocr.pytesseract")
    def test_accepts_numpy_array(self, mock_tess):
        mock_tess.image_to_string.return_value = "text"
        arr = np.zeros((100, 200, 3), dtype=np.uint8)
        result = extract_text(arr)
        assert isinstance(result, str)
        # Should have converted to PIL before calling pytesseract
        mock_tess.image_to_string.assert_called_once()

    @patch("scanner.scanning.ocr.pytesseract")
    def test_handles_tesseract_not_found(self, mock_tess):
        from pytesseract import TesseractNotFoundError
        mock_tess.image_to_string.side_effect = TesseractNotFoundError()
        result = extract_text(_make_test_image())
        assert result == ""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_handles_generic_exception(self, mock_tess):
        mock_tess.image_to_string.side_effect = RuntimeError("unexpected")
        result = extract_text(_make_test_image())
        assert result == ""


# ---------------------------------------------------------------------------
# extract_text_from_regions
# ---------------------------------------------------------------------------

class TestExtractTextFromRegions:
    """Tests for the extract_text_from_regions function."""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_processes_all_non_none_regions(self, mock_tess):
        mock_tess.image_to_string.side_effect = [
            "RESTAURANT NAME",
            "1x Burger  $8.00",
            "Total $8.00",
            "Full text here",
        ]
        regions = {
            "header": _make_test_image(),
            "line_items": _make_test_image(),
            "totals": _make_test_image(),
            "full": _make_test_image(),
        }
        result = extract_text_from_regions(regions)
        assert result["header"] == "RESTAURANT NAME"
        assert result["line_items"] == "1x Burger  $8.00"
        assert result["totals"] == "Total $8.00"
        assert result["full"] == "Full text here"
        assert mock_tess.image_to_string.call_count == 4

    @patch("scanner.scanning.ocr.pytesseract")
    def test_skips_none_regions(self, mock_tess):
        mock_tess.image_to_string.return_value = "some text"
        regions = {
            "header": None,
            "line_items": _make_test_image(),
            "totals": None,
            "full": _make_test_image(),
        }
        result = extract_text_from_regions(regions)
        assert result["header"] == ""
        assert result["line_items"] == "some text"
        assert result["totals"] == ""
        assert result["full"] == "some text"
        assert mock_tess.image_to_string.call_count == 2

    @patch("scanner.scanning.ocr.pytesseract")
    def test_returns_dict_of_strings(self, mock_tess):
        mock_tess.image_to_string.return_value = "text"
        regions = {"header": _make_test_image(), "full": _make_test_image()}
        result = extract_text_from_regions(regions)
        assert isinstance(result, dict)
        for key, value in result.items():
            assert isinstance(value, str)

    @patch("scanner.scanning.ocr.pytesseract")
    def test_handles_tesseract_not_found(self, mock_tess):
        from pytesseract import TesseractNotFoundError
        mock_tess.image_to_string.side_effect = TesseractNotFoundError()
        regions = {"header": _make_test_image(), "full": _make_test_image()}
        result = extract_text_from_regions(regions)
        assert all(v == "" for v in result.values())

    @patch("scanner.scanning.ocr.pytesseract")
    def test_empty_dict_input(self, mock_tess):
        result = extract_text_from_regions({})
        assert result == {}
        mock_tess.image_to_string.assert_not_called()


# ---------------------------------------------------------------------------
# ocr_prepass
# ---------------------------------------------------------------------------

class TestOcrPrepass:
    """Tests for the ocr_prepass orchestrator."""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_returns_extracted_text(self, mock_tess):
        mock_tess.image_to_string.return_value = "Invoice #123\nTotal: $50.00"
        result = ocr_prepass(_make_test_image())
        assert result == "Invoice #123\nTotal: $50.00"
        assert isinstance(result, str)

    @patch("scanner.scanning.ocr.pytesseract")
    def test_handles_tesseract_not_found(self, mock_tess):
        from pytesseract import TesseractNotFoundError
        mock_tess.image_to_string.side_effect = TesseractNotFoundError()
        result = ocr_prepass(_make_test_image())
        assert result == ""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_handles_generic_exception(self, mock_tess):
        mock_tess.image_to_string.side_effect = Exception("anything")
        result = ocr_prepass(_make_test_image())
        assert result == ""

    @patch("scanner.scanning.ocr.pytesseract")
    def test_returns_string_always(self, mock_tess):
        mock_tess.image_to_string.return_value = ""
        result = ocr_prepass(_make_test_image())
        assert isinstance(result, str)
