"""
Tests for scanner.scanning module (prompts + engine helpers).

All tests mock external dependencies so they work without real API calls.
"""

import io
import json
import copy

import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from scanner.scanning.engine import (
    scan_invoice,
    _parse_json_response,
    _flatten_result,
    _error_result,
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


MOCK_GLM_JSON = {
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
# Engine Helper Tests
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


class TestFlattenResult:
    """Tests for _flatten_result helper."""

    def test_returns_dict(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert isinstance(result, dict)

    def test_preserves_supplier(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert result["supplier"] == "Fresh Foods Inc."

    def test_preserves_items(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert isinstance(result["items"], list)
        assert len(result["items"]) == 2

    def test_preserves_totals(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert result["subtotal"] == 21.50
        assert result["tax"] == 2.15
        assert result["total"] == 23.65

    def test_preserves_confidence(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert "confidence" in result
        assert result["confidence"]["supplier"] == 95

    def test_preserves_inference_sources(self):
        result = _flatten_result(MOCK_GLM_JSON)
        assert "inference_sources" in result


class TestErrorResult:
    """Tests for _error_result helper."""

    def test_returns_complete_structure(self):
        result = _error_result("something broke")
        assert result["supplier"] == ""
        assert result["items"] == []
        assert result["total"] is None
        assert result["confidence"]["supplier"] == 0
        assert result["inference_sources"]["supplier"] == "missing"
        assert result["scan_metadata"]["error"] == "something broke"
        assert result["scan_metadata"]["scan_passes"] == 0

    def test_error_result_has_metadata_keys(self):
        result = _error_result("test")
        meta = result["scan_metadata"]
        assert "models_used" in meta
        assert meta["models_used"] == []


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
        mock_scan.return_value = {**MOCK_GLM_JSON, "scan_metadata": {"scan_passes": 1, "models_used": [], "api_calls": {}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        self.assertEqual(response.status_code, 200)

    @patch("scanner.views.scan_invoice")
    def test_scan_endpoint_returns_expected_json_structure(self, mock_scan):
        mock_scan.return_value = {**MOCK_GLM_JSON, "scan_metadata": {"scan_passes": 1, "models_used": [], "api_calls": {}}}
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
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

    def test_scan_endpoint_rejects_no_image(self):
        response = self.client.post("/api/scan/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)

    @patch("scanner.views.scan_invoice")
    def test_scan_engine_error_returns_error_in_metadata(self, mock_scan):
        mock_scan.return_value = _error_result("API failed")
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        # Still 200 — error is in scan_metadata
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("error", data["scan_metadata"])

    @patch("scanner.views.scan_invoice")
    def test_unexpected_exception_returns_500(self, mock_scan):
        mock_scan.side_effect = RuntimeError("kaboom")
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        self.assertEqual(response.status_code, 500)


# ---------------------------------------------------------------------------
# OCR parser tests (Phase 20 improvements)
# ---------------------------------------------------------------------------

import unittest as _unittest


class TestExtractHeaderFromHtmlTables(_unittest.TestCase):
    """Tests for _extract_header_from_html_tables()."""

    def setUp(self):
        from scanner.scanning.ocr_parser import _extract_header_from_html_tables
        self.fn = _extract_header_from_html_tables

    def test_extracts_invoice_number_from_th_td(self):
        html = """<table>
        <tr><th>INVOICE NO.</th><td>80-3860822</td></tr>
        <tr><th>INVOICE DATE</th><td>02/26/2025</td></tr>
        </table>"""
        result = self.fn(html)
        self.assertIn("invoice_number", result)
        self.assertEqual(result["invoice_number"].value, "80-3860822")
        self.assertEqual(result["invoice_number"].confidence, 85)

    def test_extracts_date_from_invoice_date(self):
        html = """<table>
        <tr><th>INVOICE DATE</th><td>03/15/2025</td></tr>
        </table>"""
        result = self.fn(html)
        self.assertIn("date", result)
        self.assertEqual(result["date"].value, "03/15/2025")

    def test_returns_empty_dict_when_no_table(self):
        result = self.fn("Plain text, no tables here.")
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_no_matching_keys(self):
        html = """<table>
        <tr><th>DESCRIPTION</th><th>QTY</th><th>AMOUNT</th></tr>
        <tr><td>Widget</td><td>5</td><td>25.00</td></tr>
        </table>"""
        result = self.fn(html)
        self.assertEqual(result, {})

    def test_handles_inv_no_keyword(self):
        html = """<table>
        <tr><th>INV NO</th><td>INV-1234</td></tr>
        </table>"""
        result = self.fn(html)
        self.assertIn("invoice_number", result)
        self.assertEqual(result["invoice_number"].value, "INV-1234")


class TestExtractSupplierSkipList(_unittest.TestCase):
    """Tests for _extract_supplier() skip-list and heuristics (Phase 20)."""

    def setUp(self):
        from scanner.scanning.ocr_parser import _extract_supplier
        self.fn = _extract_supplier

    def test_skips_ship_to_line(self):
        lines = [
            "SHIP TO: Fresh Foods Inc.",
            "JFC International Inc.",
        ]
        result = self.fn(lines)
        self.assertEqual(result.value, "JFC International Inc.")

    def test_skips_bill_to_line(self):
        lines = [
            "BILL TO: Acme Distribution LLC",
            "Real Supplier Co.",
        ]
        result = self.fn(lines)
        self.assertEqual(result.value, "Real Supplier Co.")

    def test_skips_license_line(self):
        lines = [
            "LICENSE: PLENARY WHOLESALE LIC.",
            "NY Mutual Trading Inc.",
        ]
        result = self.fn(lines)
        self.assertIsNotNone(result.value)
        self.assertNotIn("PLENARY", result.value)

    def test_first_5_lines_get_higher_confidence(self):
        lines = ["Some Company Inc."]
        result = self.fn(lines)
        self.assertGreaterEqual(result.confidence, 85)

    def test_strips_markdown_header_prefix(self):
        lines = ["## JFC International Inc."]
        result = self.fn(lines)
        self.assertEqual(result.value, "JFC International Inc.")

    def test_returns_missing_when_all_lines_skipped(self):
        lines = [
            "SHIP TO: Acme Inc.",
            "BILL TO: Another Corp.",
        ]
        result = self.fn(lines)
        # Both are skipped — should return missing (None)
        self.assertIsNone(result.value)
        self.assertEqual(result.confidence, 0)


class TestColumnMappingLessKeyword(_unittest.TestCase):
    """Tests for _COL_MAP 'less' keyword and each_price priority (Phase 20)."""

    def setUp(self):
        from scanner.scanning.ocr_parser import _map_columns
        self.fn = _map_columns

    def test_less_column_maps_to_unit(self):
        header = ["DESCRIPTION", "QTY", "LESS", "UNIT PRICE", "AMOUNT"]
        mapping = self.fn(header)
        self.assertIn("unit", mapping)
        self.assertEqual(mapping["unit"], 2)

    def test_each_price_wins_over_unit_price(self):
        # Both columns are kept separately — unit_price maps to UNIT PRICE col,
        # each_price maps to EACH PRICE col; item extractor prefers unit_price.
        header = ["DESCRIPTION", "QTY", "UNIT PRICE", "EACH PRICE", "AMOUNT"]
        mapping = self.fn(header)
        self.assertIn("unit_price", mapping)
        self.assertEqual(mapping["unit_price"], 2)
        self.assertIn("each_price", mapping)
        self.assertEqual(mapping["each_price"], 3)

    def test_unit_price_alone_still_works(self):
        header = ["DESCRIPTION", "QTY", "UNIT PRICE", "AMOUNT"]
        mapping = self.fn(header)
        self.assertIn("unit_price", mapping)
        self.assertEqual(mapping["unit_price"], 2)


# ---------------------------------------------------------------------------
# Phase 21: identify_supplier and parse_with_profile
# ---------------------------------------------------------------------------

class TestIdentifySupplier(_unittest.TestCase):
    def test_identify_supplier_known(self):
        from scanner.scanning.ocr_parser import identify_supplier
        text = "## FRESH FOODS INC\n123 Market St\nINVOICE NO: 12345"
        index = {"fresh-foods-inc": "FRESH FOODS INC", "other-co": "Other Co"}
        assert identify_supplier(text, index) == "fresh-foods-inc"

    def test_identify_supplier_unknown(self):
        from scanner.scanning.ocr_parser import identify_supplier
        text = "## NEW VENDOR LLC\nINVOICE NO: 99999"
        index = {"fresh-foods-inc": "FRESH FOODS INC"}
        assert identify_supplier(text, index) is None

    def test_identify_supplier_empty(self):
        from scanner.scanning.ocr_parser import identify_supplier
        assert identify_supplier("", {}) is None


class TestParseWithProfile(_unittest.TestCase):
    def test_parse_with_profile_supplier_name(self):
        from scanner.scanning.ocr_parser import parse_with_profile
        text = "ORDER # 1234567-001\nSHIP DATE 03/15/2025"
        profile = {"invoice_number_label": "ORDER #", "date_label": "SHIP DATE"}
        result = parse_with_profile(text, profile, supplier_name="NY Mutual Trading Co.")
        assert result.supplier.value == "NY Mutual Trading Co."
        assert result.supplier.confidence == 95
        assert result.supplier.source == "memory"
