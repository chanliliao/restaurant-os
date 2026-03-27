"""
Tests for scanner.scanning module (OCR + prompts + engine).

All tests mock external dependencies (pytesseract, Anthropic API)
so they work without Tesseract installed and without real API calls.
"""

import io
import json

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from scanner.scanning.ocr import extract_text, extract_text_from_regions, ocr_prepass
from scanner.scanning.prompts import build_scan_prompt
from scanner.scanning.engine import (
    scan_invoice,
    _call_claude,
    _parse_json_response,
    _encode_image_base64,
    _error_result,
    MODEL_MAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_image(width=200, height=100):
    """Create a simple white PIL Image for testing."""
    return Image.new("RGB", (width, height), "white")


def _make_test_image_bytes(width=200, height=100, fmt="PNG"):
    """Create test image bytes."""
    img = _make_test_image(width, height)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


MOCK_CLAUDE_JSON = {
    "supplier": "Fresh Foods Inc.",
    "date": "2026-03-15",
    "invoice_number": "INV-1234",
    "items": [
        {
            "name": "Organic Tomatoes",
            "quantity": 5,
            "unit": "kg",
            "unit_price": 3.50,
            "total": 17.50,
            "confidence": 92,
        },
        {
            "name": "Fresh Basil",
            "quantity": 2,
            "unit": "bunch",
            "unit_price": 2.00,
            "total": 4.00,
            "confidence": 88,
        },
    ],
    "subtotal": 21.50,
    "tax": 2.15,
    "total": 23.65,
    "confidence": {
        "supplier": 95,
        "date": 90,
        "invoice_number": 85,
        "subtotal": 88,
        "tax": 80,
        "total": 92,
    },
    "inference_sources": {
        "supplier": "scanned",
        "date": "scanned",
        "invoice_number": "scanned",
        "subtotal": "inferred",
        "tax": "scanned",
        "total": "scanned",
    },
}


# ===========================================================================
# OCR Tests (Phase 07 — kept intact)
# ===========================================================================

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


# ===========================================================================
# Phase 08 — Prompt Tests
# ===========================================================================

class TestBuildScanPrompt:
    """Tests for the build_scan_prompt function."""

    def test_returns_string(self):
        result = build_scan_prompt()
        assert isinstance(result, str)

    def test_contains_json_schema_keywords(self):
        result = build_scan_prompt()
        assert "supplier" in result
        assert "invoice_number" in result
        assert "confidence" in result
        assert "inference_sources" in result
        assert "items" in result
        assert "subtotal" in result

    def test_instructs_json_output(self):
        result = build_scan_prompt()
        assert "JSON" in result

    def test_mentions_two_image_variants(self):
        result = build_scan_prompt()
        assert "original" in result.lower()
        assert "preprocessed" in result.lower()

    def test_includes_ocr_text_when_provided(self):
        result = build_scan_prompt("Invoice #999\nTotal: $42.00")
        assert "Invoice #999" in result
        assert "Total: $42.00" in result
        assert "OCR" in result

    def test_omits_ocr_section_when_empty(self):
        result = build_scan_prompt("")
        assert "Supplementary OCR Text" not in result

    def test_omits_ocr_section_when_whitespace_only(self):
        result = build_scan_prompt("   \n  ")
        assert "Supplementary OCR Text" not in result

    def test_mentions_confidence_scores(self):
        result = build_scan_prompt()
        assert "confidence" in result.lower()
        assert "0 to 100" in result or "0-100" in result

    def test_mentions_inference_source_values(self):
        result = build_scan_prompt()
        assert "scanned" in result
        assert "inferred" in result
        assert "missing" in result


# ===========================================================================
# Phase 08 — Engine Helper Tests
# ===========================================================================

class TestParseJsonResponse:
    """Tests for _parse_json_response."""

    def test_parses_plain_json(self):
        text = '{"supplier": "Test", "total": 10.00}'
        result = _parse_json_response(text)
        assert result["supplier"] == "Test"
        assert result["total"] == 10.00

    def test_strips_markdown_fences(self):
        text = '```json\n{"supplier": "Test"}\n```'
        result = _parse_json_response(text)
        assert result["supplier"] == "Test"

    def test_strips_plain_fences(self):
        text = '```\n{"supplier": "Test"}\n```'
        result = _parse_json_response(text)
        assert result["supplier"] == "Test"

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json at all")

    def test_handles_whitespace(self):
        text = '  \n  {"key": "value"}  \n  '
        result = _parse_json_response(text)
        assert result["key"] == "value"


class TestEncodeImageBase64:
    """Tests for _encode_image_base64."""

    def test_returns_string(self):
        img = _make_test_image()
        result = _encode_image_base64(img)
        assert isinstance(result, str)

    def test_valid_base64(self):
        import base64
        img = _make_test_image()
        result = _encode_image_base64(img)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0


class TestModelMap:
    """Tests for model selection per scan mode."""

    def test_light_uses_sonnet(self):
        assert MODEL_MAP["light"] == "claude-sonnet-4-20250514"

    def test_normal_uses_sonnet(self):
        assert MODEL_MAP["normal"] == "claude-sonnet-4-20250514"

    def test_heavy_uses_opus(self):
        assert MODEL_MAP["heavy"] == "claude-opus-4-0-20250514"


class TestErrorResult:
    """Tests for _error_result helper."""

    def test_returns_complete_structure(self):
        result = _error_result("normal", "something broke")
        assert result["supplier"] == ""
        assert result["items"] == []
        assert result["total"] is None
        assert result["confidence"]["supplier"] == 0
        assert result["inference_sources"]["supplier"] == "missing"
        assert result["scan_metadata"]["mode"] == "normal"
        assert result["scan_metadata"]["error"] == "something broke"
        assert result["scan_metadata"]["scan_passes"] == 0


# ===========================================================================
# Phase 08 — _call_claude Tests
# ===========================================================================

class TestCallClaude:
    """Tests for _call_claude with mocked Anthropic client."""

    @patch("scanner.scanning.engine.anthropic.Anthropic")
    def test_sends_correct_structure(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"supplier": "Test"}')]
        mock_client.messages.create.return_value = mock_response

        images = [
            {"base64": "abc123", "media_type": "image/png"},
            {"base64": "def456", "media_type": "image/png"},
        ]

        result = _call_claude("test prompt", images, "claude-sonnet-4-20250514")

        assert result == '{"supplier": "Test"}'
        mock_client.messages.create.assert_called_once()

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["max_tokens"] == 4096

        content = call_kwargs["messages"][0]["content"]
        assert len(content) == 3  # 2 images + 1 text
        assert content[0]["type"] == "image"
        assert content[1]["type"] == "image"
        assert content[2]["type"] == "text"
        assert content[2]["text"] == "test prompt"

    @patch("scanner.scanning.engine.anthropic.Anthropic")
    def test_image_content_block_format(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="{}")]
        mock_client.messages.create.return_value = mock_response

        images = [{"base64": "data123", "media_type": "image/jpeg"}]
        _call_claude("prompt", images, "model-id")

        content = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        img_block = content[0]
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/jpeg"
        assert img_block["source"]["data"] == "data123"


# ===========================================================================
# Phase 08 — scan_invoice Integration Tests (mocked)
# ===========================================================================

class TestScanInvoice:
    """Tests for the scan_invoice orchestrator with all dependencies mocked."""

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_full_pipeline_returns_result(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image(200, 100).convert("L"),
            "quality_report": {"resolution": {"issue": False}},
        }
        mock_ocr.return_value = "Invoice text"
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="normal")

        assert result["supplier"] == "Fresh Foods Inc."
        assert result["total"] == 23.65
        assert len(result["items"]) == 2
        assert result["scan_metadata"]["mode"] == "normal"
        assert result["scan_metadata"]["scan_passes"] == 1
        assert result["scan_metadata"]["api_calls"]["sonnet"] == 1
        assert result["scan_metadata"]["api_calls"]["opus"] == 0

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_heavy_mode_uses_opus(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = ""
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="heavy")

        mock_claude.assert_called_once()
        call_args = mock_claude.call_args
        assert call_args[0][2] == "claude-opus-4-0-20250514"
        assert result["scan_metadata"]["api_calls"]["opus"] == 1
        assert result["scan_metadata"]["api_calls"]["sonnet"] == 0

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_light_mode_uses_sonnet(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = ""
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        scan_invoice(_make_test_image_bytes(), mode="light")

        call_args = mock_claude.call_args
        assert call_args[0][2] == "claude-sonnet-4-20250514"

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_debug_mode_includes_extra_metadata(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {"test": True},
        }
        mock_ocr.return_value = "debug ocr text"
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="normal", debug=True)

        debug_info = result["scan_metadata"]["debug"]
        assert "elapsed_seconds" in debug_info
        assert debug_info["model"] == "claude-sonnet-4-20250514"
        assert debug_info["ocr_text"] == "debug ocr text"
        assert debug_info["quality_report"] == {"test": True}

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_api_error_returns_error_result(self, mock_prep, mock_ocr, mock_claude):
        import anthropic

        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = ""
        mock_claude.side_effect = anthropic.APIError(
            message="rate limited",
            request=MagicMock(),
            body=None,
        )

        result = scan_invoice(_make_test_image_bytes())

        assert result["supplier"] == ""
        assert result["scan_metadata"]["error"]
        assert "API error" in result["scan_metadata"]["error"]
        assert result["scan_metadata"]["scan_passes"] == 0

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_invalid_json_returns_error_result(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = ""
        mock_claude.return_value = "This is not JSON at all"

        result = scan_invoice(_make_test_image_bytes())

        assert result["supplier"] == ""
        assert "error" in result["scan_metadata"]
        assert "JSON" in result["scan_metadata"]["error"]

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_passes_ocr_text_to_prompt(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = "SUPPLIER: Test Co"
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        scan_invoice(_make_test_image_bytes())

        # The prompt (first arg to _call_claude) should contain the OCR text
        prompt_arg = mock_claude.call_args[0][0]
        assert "SUPPLIER: Test Co" in prompt_arg

    @patch("scanner.scanning.engine._call_claude")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_sends_two_images(self, mock_prep, mock_ocr, mock_claude):
        mock_prep.return_value = {
            "original": _make_test_image(),
            "preprocessed": _make_test_image().convert("L"),
            "quality_report": {},
        }
        mock_ocr.return_value = ""
        mock_claude.return_value = json.dumps(MOCK_CLAUDE_JSON)

        scan_invoice(_make_test_image_bytes())

        images_arg = mock_claude.call_args[0][1]
        assert len(images_arg) == 2
        assert images_arg[0]["media_type"] == "image/png"
        assert images_arg[1]["media_type"] == "image/png"


# ===========================================================================
# Phase 08 — View Endpoint Tests (Django test client + mocked engine)
# ===========================================================================

from django.test import TestCase
from rest_framework.test import APIClient


class TestScanEndpoint(TestCase):
    """Tests for POST /api/scan/ with mocked scan_invoice engine."""

    def setUp(self):
        self.client = APIClient()

    def _create_test_image(self):
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "test_receipt.png"
        return buf

    @patch("scanner.views.scan_invoice")
    def test_scan_endpoint_returns_200(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 1, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 1, "opus": 0}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        self.assertEqual(response.status_code, 200)

    @patch("scanner.views.scan_invoice")
    def test_scan_endpoint_returns_expected_json_structure(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 1, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 1, "opus": 0}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        data = response.json()
        self.assertIn("supplier", data)
        self.assertIn("date", data)
        self.assertIn("invoice_number", data)
        self.assertIn("items", data)
        self.assertIn("subtotal", data)
        self.assertIn("tax", data)
        self.assertIn("total", data)
        self.assertIn("confidence", data)
        self.assertIn("inference_sources", data)
        self.assertIn("scan_metadata", data)

    @patch("scanner.views.scan_invoice")
    def test_scan_metadata_contains_mode(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "heavy", "scan_passes": 1, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 0, "opus": 1}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "heavy"}, format="multipart")
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "heavy")

    def test_scan_endpoint_rejects_no_image(self):
        response = self.client.post("/api/scan/", {"mode": "normal"}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_scan_endpoint_rejects_invalid_mode(self):
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "turbo"}, format="multipart")
        self.assertEqual(response.status_code, 400)

    @patch("scanner.views.scan_invoice")
    def test_scan_endpoint_defaults_mode_to_normal(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 1, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 1, "opus": 0}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "normal")

    @patch("scanner.views.scan_invoice")
    def test_scan_passes_mode_to_engine(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "light", "scan_passes": 1, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 1, "opus": 0}}}
        image = self._create_test_image()
        self.client.post("/api/scan/", {"image": image, "mode": "light"}, format="multipart")
        mock_scan.assert_called_once()
        call_kwargs = mock_scan.call_args[1]
        self.assertEqual(call_kwargs["mode"], "light")

    @patch("scanner.views.scan_invoice")
    def test_scan_engine_error_returns_error_in_metadata(self, mock_scan):
        mock_scan.return_value = _error_result("normal", "API failed")
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        # Still 200 — error is in scan_metadata
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("error", data["scan_metadata"])

    @patch("scanner.views.scan_invoice")
    def test_unexpected_exception_returns_500(self, mock_scan):
        mock_scan.side_effect = RuntimeError("kaboom")
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        self.assertEqual(response.status_code, 500)
