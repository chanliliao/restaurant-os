"""
Tests for scanner.scanning module (OCR + prompts + engine + comparator).

All tests mock external dependencies (pytesseract, Anthropic API)
so they work without Tesseract installed and without real API calls.
"""

import io
import json
import copy

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from scanner.scanning.ocr import extract_text, extract_text_from_regions, ocr_prepass
from scanner.scanning.prompts import (
    build_scan_prompt,
    build_scan_prompt_v2,
    build_tiebreaker_prompt,
)
from scanner.scanning.comparator import (
    compare_scans,
    merge_results,
    _fuzzy_match,
    _numeric_match,
    _fuzzy_ratio,
)
from scanner.scanning.engine import (
    scan_invoice,
    _call_claude,
    _parse_json_response,
    _encode_image_base64,
    _error_result,
    SONNET,
    OPUS,
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

# A second scan result that agrees with the first
MOCK_CLAUDE_JSON_AGREE = copy.deepcopy(MOCK_CLAUDE_JSON)

# A second scan result that disagrees on some fields
MOCK_CLAUDE_JSON_DISAGREE = copy.deepcopy(MOCK_CLAUDE_JSON)
MOCK_CLAUDE_JSON_DISAGREE["supplier"] = "Fresh Food Inc"  # slightly different
MOCK_CLAUDE_JSON_DISAGREE["total"] = 24.00  # different number
MOCK_CLAUDE_JSON_DISAGREE["items"][0]["quantity"] = 6  # different quantity

# A tiebreaker result that resolves disagreements
MOCK_TIEBREAKER_JSON = copy.deepcopy(MOCK_CLAUDE_JSON)
MOCK_TIEBREAKER_JSON["supplier"] = "Fresh Foods Inc."
MOCK_TIEBREAKER_JSON["total"] = 23.65


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
# Phase 09 — Prompt V2 Tests
# ===========================================================================

class TestBuildScanPromptV2:
    """Tests for the build_scan_prompt_v2 function."""

    def test_returns_string(self):
        result = build_scan_prompt_v2()
        assert isinstance(result, str)

    def test_contains_json_schema_keywords(self):
        result = build_scan_prompt_v2()
        assert "supplier" in result
        assert "invoice_number" in result
        assert "confidence" in result
        assert "inference_sources" in result
        assert "items" in result

    def test_different_from_v1(self):
        v1 = build_scan_prompt()
        v2 = build_scan_prompt_v2()
        assert v1 != v2

    def test_mentions_bottom_up_strategy(self):
        result = build_scan_prompt_v2()
        assert "bottom-up" in result.lower() or "line items" in result.lower()

    def test_includes_ocr_text_when_provided(self):
        result = build_scan_prompt_v2("Invoice #999")
        assert "Invoice #999" in result

    def test_omits_ocr_section_when_empty(self):
        result = build_scan_prompt_v2("")
        assert "Reference OCR Text" not in result

    def test_instructs_json_output(self):
        result = build_scan_prompt_v2()
        assert "JSON" in result


class TestBuildTiebreakerPrompt:
    """Tests for the build_tiebreaker_prompt function."""

    def test_returns_string(self):
        result = build_tiebreaker_prompt(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE)
        assert isinstance(result, str)

    def test_contains_both_scan_results(self):
        result = build_tiebreaker_prompt(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE)
        assert "Scan 1" in result
        assert "Scan 2" in result
        assert "Fresh Foods Inc." in result
        assert "Fresh Food Inc" in result

    def test_instructs_resolution(self):
        result = build_tiebreaker_prompt(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE)
        assert "disagree" in result.lower() or "disagreement" in result.lower()

    def test_includes_ocr_when_provided(self):
        result = build_tiebreaker_prompt(
            MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE, "OCR text here"
        )
        assert "OCR text here" in result

    def test_omits_ocr_when_empty(self):
        result = build_tiebreaker_prompt(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE, "")
        assert "Supplementary OCR Text" not in result

    def test_strips_scan_metadata(self):
        scan_with_meta = copy.deepcopy(MOCK_CLAUDE_JSON)
        scan_with_meta["scan_metadata"] = {"mode": "normal"}
        result = build_tiebreaker_prompt(scan_with_meta, MOCK_CLAUDE_JSON_DISAGREE)
        assert "scan_metadata" not in result


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

    def test_error_result_has_phase09_metadata(self):
        result = _error_result("normal", "test")
        meta = result["scan_metadata"]
        assert "scans_performed" in meta
        assert "tiebreaker_triggered" in meta
        assert "agreement_ratio" in meta
        assert "models_used" in meta
        assert meta["models_used"] == []


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
# Phase 09 — Comparator Tests
# ===========================================================================

class TestFuzzyMatch:
    """Tests for fuzzy string matching helpers."""

    def test_exact_match(self):
        assert _fuzzy_match("Fresh Foods Inc.", "Fresh Foods Inc.") is True

    def test_close_match(self):
        assert _fuzzy_match("Fresh Foods Inc.", "Fresh Foods Inc") is True

    def test_different_case(self):
        assert _fuzzy_match("FRESH FOODS", "fresh foods") is True

    def test_clearly_different(self):
        assert _fuzzy_match("Fresh Foods Inc.", "Ocean Supplies Ltd.") is False

    def test_empty_strings(self):
        assert _fuzzy_match("", "") is True  # both empty
        assert _fuzzy_match("something", "") is False
        assert _fuzzy_match("", "something") is False

    def test_fuzzy_ratio_returns_float(self):
        ratio = _fuzzy_ratio("hello", "hello")
        assert ratio == 1.0
        ratio = _fuzzy_ratio("hello", "world")
        assert 0.0 <= ratio <= 1.0


class TestNumericMatch:
    """Tests for numeric matching."""

    def test_exact_match(self):
        assert _numeric_match(23.65, 23.65) is True

    def test_int_float_match(self):
        assert _numeric_match(5, 5.0) is True

    def test_different_values(self):
        assert _numeric_match(23.65, 24.00) is False

    def test_both_none(self):
        assert _numeric_match(None, None) is True

    def test_one_none(self):
        assert _numeric_match(23.65, None) is False
        assert _numeric_match(None, 23.65) is False


class TestCompareScans:
    """Tests for compare_scans."""

    def test_identical_scans_full_agreement(self):
        result = compare_scans(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_AGREE)
        assert result["agreement_ratio"] == 1.0
        assert len(result["disagreed"]) == 0
        assert len(result["items_comparison"]["disagreed"]) == 0

    def test_disagreeing_scans_detected(self):
        result = compare_scans(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE)
        assert result["agreement_ratio"] < 1.0
        # total should disagree (23.65 vs 24.00)
        assert "total" in result["disagreed"]
        # items should have disagreement (quantity 5 vs 6)
        assert len(result["items_comparison"]["disagreed"]) > 0

    def test_fuzzy_supplier_match(self):
        # "Fresh Foods Inc." vs "Fresh Food Inc" — close enough
        scan2 = copy.deepcopy(MOCK_CLAUDE_JSON)
        scan2["supplier"] = "Fresh Foods Inc"  # missing period
        result = compare_scans(MOCK_CLAUDE_JSON, scan2)
        assert "supplier" in result["agreed"]

    def test_supplier_clearly_different(self):
        scan2 = copy.deepcopy(MOCK_CLAUDE_JSON)
        scan2["supplier"] = "Ocean Supplies Ltd."
        result = compare_scans(MOCK_CLAUDE_JSON, scan2)
        assert "supplier" in result["disagreed"]

    def test_agreement_ratio_is_float(self):
        result = compare_scans(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_AGREE)
        assert isinstance(result["agreement_ratio"], float)

    def test_different_item_count(self):
        scan2 = copy.deepcopy(MOCK_CLAUDE_JSON)
        scan2["items"] = scan2["items"][:1]  # only one item
        result = compare_scans(MOCK_CLAUDE_JSON, scan2)
        assert len(result["items_comparison"]["disagreed"]) >= 1


class TestMergeResults:
    """Tests for merge_results."""

    def test_merge_agreeing_scans_no_tiebreaker(self):
        merged = merge_results(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_AGREE)
        assert merged["supplier"] == "Fresh Foods Inc."
        assert merged["total"] == 23.65
        assert "scan_metadata" not in merged

    def test_merge_with_tiebreaker(self):
        merged = merge_results(
            MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE, MOCK_TIEBREAKER_JSON
        )
        # Tiebreaker resolves: supplier stays, total from tiebreaker
        assert merged["total"] == 23.65
        assert merged["supplier"] == "Fresh Foods Inc."

    def test_merge_without_tiebreaker_uses_scan1(self):
        merged = merge_results(MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE)
        # Without tiebreaker, scan1 values used for disagreements
        assert merged["total"] == 23.65  # scan1's value
        assert merged["supplier"] == "Fresh Foods Inc."  # agreed

    def test_merge_strips_scan_metadata(self):
        scan_with_meta = copy.deepcopy(MOCK_CLAUDE_JSON)
        scan_with_meta["scan_metadata"] = {"mode": "test"}
        merged = merge_results(scan_with_meta, MOCK_CLAUDE_JSON_AGREE)
        assert "scan_metadata" not in merged

    def test_merge_with_tiebreaker_uses_tiebreaker_confidence(self):
        tiebreaker = copy.deepcopy(MOCK_TIEBREAKER_JSON)
        tiebreaker["confidence"]["supplier"] = 99
        merged = merge_results(
            MOCK_CLAUDE_JSON, MOCK_CLAUDE_JSON_DISAGREE, tiebreaker
        )
        assert merged["confidence"]["supplier"] == 99


# ===========================================================================
# Phase 09 — scan_invoice Three-Pass Integration Tests (mocked)
# ===========================================================================

def _mock_prep_return():
    return {
        "original": _make_test_image(),
        "preprocessed": _make_test_image(200, 100).convert("L"),
        "quality_report": {"resolution": {"issue": False}},
    }


class TestScanInvoiceThreePass:
    """Tests for the three-pass scan_invoice orchestrator."""

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_two_agreeing_scans_no_tiebreaker(self, mock_prep, mock_ocr, mock_api):
        """When both scans agree, only 2 API calls are made."""
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = "Invoice text"
        mock_api.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="normal")

        assert mock_api.call_count == 2
        assert result["supplier"] == "Fresh Foods Inc."
        assert result["total"] == 23.65
        meta = result["scan_metadata"]
        assert meta["scans_performed"] == 2
        assert meta["tiebreaker_triggered"] is False
        assert meta["agreement_ratio"] == 1.0

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_disagreeing_scans_trigger_tiebreaker(self, mock_prep, mock_ocr, mock_api):
        """When scans disagree, a 3rd tiebreaker call is made."""
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.side_effect = [
            json.dumps(MOCK_CLAUDE_JSON),
            json.dumps(MOCK_CLAUDE_JSON_DISAGREE),
            json.dumps(MOCK_TIEBREAKER_JSON),
        ]

        result = scan_invoice(_make_test_image_bytes(), mode="normal")

        assert mock_api.call_count == 3
        meta = result["scan_metadata"]
        assert meta["scans_performed"] == 3
        assert meta["tiebreaker_triggered"] is True
        assert meta["agreement_ratio"] < 1.0

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_normal_mode_three_scans_on_disagreement(self, mock_prep, mock_ocr, mock_api):
        """Normal mode triggers tiebreaker on disagreement."""
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.side_effect = [
            json.dumps(MOCK_CLAUDE_JSON),
            json.dumps(MOCK_CLAUDE_JSON_DISAGREE),
            json.dumps(MOCK_TIEBREAKER_JSON),
        ]

        result = scan_invoice(_make_test_image_bytes(), mode="normal")

        assert mock_api.call_count == 3
        meta = result["scan_metadata"]
        assert meta["scans_performed"] == 3
        assert meta["tiebreaker_triggered"] is True

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_heavy_mode_completes_scan(self, mock_prep, mock_ocr, mock_api):
        """Heavy mode completes a scan with mocked API."""
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="heavy")

        assert result["supplier"] == "Fresh Foods Inc."
        assert result["total"] == 23.65

    @patch("scanner.scanning.engine._call_gemini")
    @patch("scanner.scanning.engine._call_glm_ocr")
    @patch("scanner.scanning.engine.segment_invoice")
    @patch("scanner.scanning.engine.extract_text_enhanced")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_light_mode_uses_gemini_not_claude(
        self, mock_prep, mock_extract, mock_segment, mock_glm_ocr, mock_gemini
    ):
        """Light mode uses GLM-OCR + Gemini (not Claude)."""
        mock_prep.return_value = _mock_prep_return()
        mock_extract.return_value = ""
        mock_segment.return_value = {"header": None, "regions_detected": False}
        mock_glm_ocr.return_value = "Fresh Foods Inc Invoice INV-1234 Total: $23.65"
        mock_gemini.return_value = json.dumps(MOCK_CLAUDE_JSON)

        result = scan_invoice(_make_test_image_bytes(), mode="light")

        assert mock_gemini.called
        assert result["supplier"] == "Fresh Foods Inc."
        meta = result["scan_metadata"]
        assert meta["pipeline"] == "glm-ocr-light"

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_scan_metadata_reflects_actual_count(self, mock_prep, mock_ocr, mock_api):
        """scan_metadata correctly reports 2 or 3 scans."""
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""

        mock_api.return_value = json.dumps(MOCK_CLAUDE_JSON)
        result = scan_invoice(_make_test_image_bytes())
        assert result["scan_metadata"]["scans_performed"] == 2
        assert result["scan_metadata"]["scan_passes"] == 2

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_debug_mode_includes_comparison_details(self, mock_prep, mock_ocr, mock_api):
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = "debug ocr"
        mock_api.side_effect = [
            json.dumps(MOCK_CLAUDE_JSON),
            json.dumps(MOCK_CLAUDE_JSON_DISAGREE),
            json.dumps(MOCK_TIEBREAKER_JSON),
        ]

        result = scan_invoice(_make_test_image_bytes(), mode="normal", debug=True)

        debug_info = result["scan_metadata"]["debug"]
        assert "elapsed_seconds" in debug_info
        assert "comparison_details" in debug_info
        assert "agreed_fields" in debug_info["comparison_details"]
        assert "disagreed_fields" in debug_info["comparison_details"]

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_api_error_returns_error_result(self, mock_prep, mock_ocr, mock_api):
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.side_effect = Exception("API error: rate limited")

        result = scan_invoice(_make_test_image_bytes())

        assert result["supplier"] == ""
        assert result["scan_metadata"]["error"]
        assert result["scan_metadata"]["scan_passes"] == 0

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_invalid_json_returns_error_result(self, mock_prep, mock_ocr, mock_api):
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.return_value = "This is not JSON at all"

        result = scan_invoice(_make_test_image_bytes())

        assert result["supplier"] == ""
        assert "error" in result["scan_metadata"]
        assert "JSON" in result["scan_metadata"]["error"]

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_passes_ocr_text_to_prompts(self, mock_prep, mock_ocr, mock_api):
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = "SUPPLIER: Test Co"
        mock_api.return_value = json.dumps(MOCK_CLAUDE_JSON)

        scan_invoice(_make_test_image_bytes())

        prompt1 = mock_api.call_args_list[0][0][0]
        prompt2 = mock_api.call_args_list[1][0][0]
        assert "SUPPLIER: Test Co" in prompt1
        assert "SUPPLIER: Test Co" in prompt2

    @patch("scanner.scanning.engine._call_api")
    @patch("scanner.scanning.engine.ocr_prepass")
    @patch("scanner.scanning.engine.prepare_variants")
    def test_sends_two_images_to_each_scan(self, mock_prep, mock_ocr, mock_api):
        mock_prep.return_value = _mock_prep_return()
        mock_ocr.return_value = ""
        mock_api.return_value = json.dumps(MOCK_CLAUDE_JSON)

        scan_invoice(_make_test_image_bytes())

        for call in mock_api.call_args_list:
            images_arg = call[0][1]
            assert len(images_arg) == 2


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
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 2, "scans_performed": 2, "tiebreaker_triggered": False, "agreement_ratio": 1.0, "math_validation_triggered": False, "api_calls": {"sonnet": 2, "opus": 0}, "models_used": [SONNET, SONNET]}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        self.assertEqual(response.status_code, 200)

    @patch("scanner.views.scan_invoice")
    def test_scan_endpoint_returns_expected_json_structure(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 2, "scans_performed": 2, "tiebreaker_triggered": False, "agreement_ratio": 1.0, "math_validation_triggered": False, "api_calls": {"sonnet": 2, "opus": 0}, "models_used": [SONNET, SONNET]}}
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
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "heavy", "scan_passes": 2, "scans_performed": 2, "tiebreaker_triggered": False, "agreement_ratio": 1.0, "math_validation_triggered": False, "api_calls": {"sonnet": 0, "opus": 2}, "models_used": [OPUS, OPUS]}}
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
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "normal", "scan_passes": 2, "scans_performed": 2, "tiebreaker_triggered": False, "agreement_ratio": 1.0, "math_validation_triggered": False, "api_calls": {"sonnet": 2, "opus": 0}, "models_used": [SONNET, SONNET]}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "normal")

    @patch("scanner.views.scan_invoice")
    def test_scan_passes_mode_to_engine(self, mock_scan):
        mock_scan.return_value = {**MOCK_CLAUDE_JSON, "scan_metadata": {"mode": "light", "scan_passes": 2, "scans_performed": 2, "tiebreaker_triggered": False, "agreement_ratio": 1.0, "math_validation_triggered": False, "api_calls": {"sonnet": 2, "opus": 0}, "models_used": [SONNET, SONNET]}}
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
