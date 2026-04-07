"""
Integration tests for the GLM-only scan pipeline.

All tests mock scanner.scanning.engine._call_glm_vision and
scanner.scanning.engine._call_glm_ocr so no real API calls are made.
segment_invoice is also mocked to avoid real image processing.

Synthetic images are generated via integration_helpers.make_receipt_image_bytes().
"""

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.test import APIClient

from scanner.scanning.engine import scan_invoice, GLM_VISION_MODEL
from scanner.memory import JsonSupplierMemory, JsonGeneralMemory
from tests.integration_helpers import (
    make_receipt_image_bytes,
    make_claude_response,
)


# ---------------------------------------------------------------------------
# Shared mock target paths
# ---------------------------------------------------------------------------

CALL_GLM_VISION = "scanner.scanning.engine._call_glm_vision"
CALL_GLM_OCR = "scanner.scanning.engine._call_glm_ocr"
SEGMENT_INVOICE = "scanner.scanning.engine.segment_invoice"

# Minimal OCR string — incomplete on purpose so the pipeline takes the LLM path
_MINIMAL_OCR = "Date: 2026-03-15\nInvoice: INV-1234"

# Full GLM vision response matching pipeline expectations
_GLM_VISION_JSON = (
    '{"supplier": "Fresh Foods Inc.", "date": "2026-03-15", '
    '"invoice_number": "INV-1234", '
    '"items": ['
    '{"name": "Organic Tomatoes", "quantity": 5, "unit": "kg", '
    '"unit_price": 3.50, "total": 17.50, "confidence": 92}, '
    '{"name": "Fresh Basil", "quantity": 2, "unit": "bunch", '
    '"unit_price": 2.00, "total": 4.00, "confidence": 88}'
    '], '
    '"subtotal": 21.50, "tax": 2.15, "total": 23.65, '
    '"confidence": {"supplier": 95, "date": 90, "invoice_number": 85, '
    '"subtotal": 88, "tax": 80, "total": 92}, '
    '"inference_sources": {"supplier": "scanned", "date": "scanned", '
    '"invoice_number": "scanned", "subtotal": "scanned", '
    '"tax": "scanned", "total": "scanned"}}'
)

_NO_SEGMENT = {
    "regions_detected": False,
    "header": None,
    "line_items": None,
    "totals": None,
    "bounding_boxes": {},
}


# ===========================================================================
# GLM Pipeline — core correctness tests
# ===========================================================================

class TestGLMPipelineCorrectness(TestCase):
    """Full GLM pipeline with mocked GLM calls."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_returns_correct_supplier(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        self.assertEqual(result["supplier"], "Fresh Foods Inc.")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_returns_correct_date(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        self.assertEqual(result["date"], "2026-03-15")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_returns_correct_invoice_number(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        self.assertEqual(result["invoice_number"], "INV-1234")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_returns_correct_totals(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        self.assertAlmostEqual(result["subtotal"], 21.50, places=2)
        self.assertAlmostEqual(result["tax"], 2.15, places=2)
        self.assertAlmostEqual(result["total"], 23.65, places=2)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_returns_two_items(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["name"], "Organic Tomatoes")
        self.assertEqual(result["items"][1]["name"], "Fresh Basil")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_has_confidence_block(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        conf = result["confidence"]
        for field in ("supplier", "date", "invoice_number", "subtotal", "tax", "total"):
            self.assertIn(field, conf)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_has_inference_sources_block(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        sources = result["inference_sources"]
        for field in ("supplier", "date", "invoice_number", "subtotal", "tax", "total"):
            self.assertIn(field, sources)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_pipeline_has_scan_metadata(
        self, mock_vision, mock_ocr, mock_segment
    ):
        result = scan_invoice(self.image_bytes)
        meta = result["scan_metadata"]
        self.assertIn("scan_passes", meta)
        self.assertIn("models_used", meta)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_vision_was_called(
        self, mock_vision, mock_ocr, mock_segment
    ):
        scan_invoice(self.image_bytes)
        self.assertTrue(mock_vision.called)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_glm_ocr_was_called(
        self, mock_vision, mock_ocr, mock_segment
    ):
        scan_invoice(self.image_bytes)
        self.assertTrue(mock_ocr.called)


# ===========================================================================
# Full API flow — POST /api/scan/ -> POST /api/confirm/ -> GET /api/stats/
# ===========================================================================

class TestFullAPIFlow(TestCase):
    """End-to-end HTTP API test: scan -> confirm -> stats."""

    def setUp(self):
        self.api_client = APIClient()
        self.image_bytes = make_receipt_image_bytes()

        # Isolated memory stores
        self.supplier_dir = tempfile.mkdtemp()
        self.general_dir = tempfile.mkdtemp()
        self.supplier_memory = JsonSupplierMemory(data_dir=Path(self.supplier_dir))
        self.general_memory = JsonGeneralMemory(data_dir=Path(self.general_dir))

    def tearDown(self):
        shutil.rmtree(self.supplier_dir, ignore_errors=True)
        shutil.rmtree(self.general_dir, ignore_errors=True)

    def _post_scan(self):
        """Helper: POST an image to /api/scan/ and return response."""
        buf = io.BytesIO(self.image_bytes)
        buf.name = "receipt.png"
        return self.api_client.post(
            "/api/scan/",
            {"image": buf},
            format="multipart",
        )

    def _post_confirm(self, scan_result, corrections=None):
        """Helper: POST confirmation to /api/confirm/ and return response."""
        payload = {
            "scan_result": scan_result,
            "corrections": corrections or [],
            "confirmed_at": "2026-03-28T10:00:00Z",
        }
        return self.api_client.post("/api/confirm/", payload, format="json")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_scan_endpoint_returns_200(
        self, mock_vision, mock_ocr, mock_segment
    ):
        response = self._post_scan()
        self.assertEqual(response.status_code, 200)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_scan_endpoint_returns_invoice_fields(
        self, mock_vision, mock_ocr, mock_segment
    ):
        response = self._post_scan()
        data = response.json()
        for field in ("supplier", "date", "invoice_number", "items",
                      "subtotal", "tax", "total", "confidence",
                      "inference_sources", "scan_metadata"):
            self.assertIn(field, data, f"Missing field: {field}")

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_confirm_endpoint_returns_200(
        self, mock_vision, mock_ocr, mock_segment
    ):
        with patch(
            "scanner.views._get_supplier_memory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.views._get_general_memory",
            return_value=self.general_memory,
        ):
            scan_resp = self._post_scan()
            scan_result = scan_resp.json()
            confirm_resp = self._post_confirm(scan_result)

        self.assertEqual(confirm_resp.status_code, 200)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_confirm_returns_expected_fields(
        self, mock_vision, mock_ocr, mock_segment
    ):
        with patch(
            "scanner.views._get_supplier_memory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.views._get_general_memory",
            return_value=self.general_memory,
        ):
            scan_resp = self._post_scan()
            scan_result = scan_resp.json()
            confirm_resp = self._post_confirm(scan_result)

        data = confirm_resp.json()
        self.assertEqual(data["status"], "confirmed")
        self.assertIn("corrections_count", data)
        self.assertIn("confirmed_at", data)
        self.assertTrue(data["memory_updated"])

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_confirm_with_corrections_count_matches(
        self, mock_vision, mock_ocr, mock_segment
    ):
        corrections = [
            {
                "field": "supplier",
                "original_value": "Fresh Foods Inc.",
                "corrected_value": "Fresh Foods Incorporated",
            }
        ]

        with patch(
            "scanner.views._get_supplier_memory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.views._get_general_memory",
            return_value=self.general_memory,
        ):
            scan_resp = self._post_scan()
            scan_result = scan_resp.json()
            confirm_resp = self._post_confirm(scan_result, corrections=corrections)

        data = confirm_resp.json()
        self.assertEqual(data["corrections_count"], 1)

    def test_stats_endpoint_returns_200(self):
        response = self.api_client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)

    def test_stats_endpoint_returns_accuracy_and_api_usage(self):
        response = self.api_client.get("/api/stats/")
        data = response.json()
        self.assertIn("accuracy", data)
        self.assertIn("api_usage", data)

    @patch(SEGMENT_INVOICE, return_value=_NO_SEGMENT)
    @patch(CALL_GLM_OCR, return_value=_MINIMAL_OCR)
    @patch(CALL_GLM_VISION, return_value=_GLM_VISION_JSON)
    def test_full_scan_confirm_stats_flow(
        self, mock_vision, mock_ocr, mock_segment
    ):
        """Smoke test: all three endpoints chained together without error."""
        with patch(
            "scanner.views._get_supplier_memory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.views._get_general_memory",
            return_value=self.general_memory,
        ):
            scan_resp = self._post_scan()
            self.assertEqual(scan_resp.status_code, 200)

            scan_result = scan_resp.json()
            confirm_resp = self._post_confirm(scan_result)
            self.assertEqual(confirm_resp.status_code, 200)

        stats_resp = self.api_client.get("/api/stats/")
        self.assertEqual(stats_resp.status_code, 200)
