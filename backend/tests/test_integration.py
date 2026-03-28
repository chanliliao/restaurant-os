"""
Phase 17 -- Integration tests for the full scan pipeline.

All tests mock scanner.scanning.engine._call_claude so no real Anthropic
API calls are made. They also mock scanner.memory.inference._tier3_ai to
prevent any other Anthropic calls from the inference tier.

Synthetic images are generated via integration_helpers.make_receipt_image_bytes().
"""

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from django.test import TestCase
from rest_framework.test import APIClient

from scanner.scanning.engine import scan_invoice, SONNET, OPUS
from scanner.memory import JsonSupplierMemory, JsonGeneralMemory
from tests.integration_helpers import make_receipt_image_bytes, make_claude_response


# ---------------------------------------------------------------------------
# Shared mock target paths
# ---------------------------------------------------------------------------

CALL_CLAUDE = "scanner.scanning.engine._call_claude"
TIER3_AI = "scanner.memory.inference._tier3_ai"
OCR_PREPASS = "scanner.scanning.ocr.pytesseract"


# ===========================================================================
# Task 2: Clean Receipt -- full pipeline, no disagreements
# ===========================================================================

class TestCleanReceiptPipeline(TestCase):
    """Full pipeline with two agreeing scans -- no tiebreaker triggered."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()
        self.claude_response = make_claude_response()

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_returns_correct_supplier(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = "Fresh Foods Inc"
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(result["supplier"], "Fresh Foods Inc.")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_returns_correct_date(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(result["date"], "2026-03-15")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_returns_correct_totals(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertAlmostEqual(result["subtotal"], 21.50, places=2)
        self.assertAlmostEqual(result["tax"], 2.15, places=2)
        self.assertAlmostEqual(result["total"], 23.65, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_has_two_items(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["name"], "Organic Tomatoes")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_no_tiebreaker_triggered(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Two agreeing scans should call _call_claude exactly twice."""
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(mock_call.call_count, 2)
        self.assertFalse(result["scan_metadata"]["tiebreaker_triggered"])

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_scan_metadata_structure(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        meta = result["scan_metadata"]
        self.assertEqual(meta["mode"], "normal")
        self.assertEqual(meta["scan_passes"], 2)
        self.assertIn("api_calls", meta)
        self.assertIn("models_used", meta)
        self.assertIn("agreement_ratio", meta)
        self.assertAlmostEqual(meta["agreement_ratio"], 1.0, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_has_confidence_block(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        conf = result["confidence"]
        for field in ("supplier", "date", "invoice_number", "subtotal", "tax", "total"):
            self.assertIn(field, conf)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_clean_receipt_has_inference_sources_block(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        result = scan_invoice(self.image_bytes, mode="normal")
        sources = result["inference_sources"]
        for field in ("supplier", "date", "invoice_number", "subtotal", "tax", "total"):
            self.assertIn(field, sources)


# ===========================================================================
# Task 3: Math validation -- wrong line total gets auto-corrected
# ===========================================================================

class TestMathValidation(TestCase):
    """Pipeline with a math error in both scans -- validator must auto-correct."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()
        # item[0].total is wrong: 5 * 3.50 = 17.50 but we say 20.00
        # subtotal and total are also wrong as a consequence
        self.bad_response = make_claude_response(
            items=[
                {
                    "name": "Organic Tomatoes",
                    "quantity": 5,
                    "unit": "kg",
                    "unit_price": 3.50,
                    "total": 20.00,   # WRONG -- should be 17.50
                    "confidence": 90,
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
            subtotal=24.00,   # WRONG -- items sum to 17.50+4.00=21.50
            tax=2.40,
            total=26.40,      # WRONG
        )

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_math_validation_triggered_flag(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.bad_response
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertTrue(result["scan_metadata"]["math_validation_triggered"])

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_math_validation_corrects_item_line_total(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.bad_response
        result = scan_invoice(self.image_bytes, mode="normal")
        # qty=5, unit_price=3.50 -> expected 17.50
        self.assertAlmostEqual(result["items"][0]["total"], 17.50, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_math_validation_recalculates_subtotal(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.bad_response
        result = scan_invoice(self.image_bytes, mode="normal")
        # 17.50 + 4.00 = 21.50
        self.assertAlmostEqual(result["subtotal"], 21.50, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_math_validation_recalculates_total(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.bad_response
        result = scan_invoice(self.image_bytes, mode="normal")
        # subtotal=21.50 + tax=2.40 = 23.90
        self.assertAlmostEqual(result["total"], 23.90, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_correct_data_does_not_trigger_math_validation(
        self, mock_call, mock_tess, mock_tier3
    ):
        """When math is already correct, validation flag stays False."""
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = make_claude_response()  # correct data
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertFalse(result["scan_metadata"]["math_validation_triggered"])


# ===========================================================================
# Task 4: Tiebreaker -- disagreement between scans triggers third call
# ===========================================================================

class TestTiebreakerTriggered(TestCase):
    """Two scans that disagree on supplier and total -> tiebreaker fires."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()

        # Scan 1: supplier = "Fresh Foods Inc." total = 23.65
        self.scan1_response = make_claude_response(
            supplier="Fresh Foods Inc.",
            total=23.65,
        )

        # Scan 2: supplier = "Freshfoods" (different), total = 24.00 (different)
        self.scan2_response = make_claude_response(
            supplier="Freshfoods",
            total=24.00,
        )

        # Tiebreaker: authoritative answer
        self.tiebreaker_response = make_claude_response(
            supplier="Fresh Foods Inc.",
            total=23.65,
        )

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_tiebreaker_triggered_flag(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [
            self.scan1_response,
            self.scan2_response,
            self.tiebreaker_response,
        ]
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertTrue(result["scan_metadata"]["tiebreaker_triggered"])

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_tiebreaker_call_count_is_three(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [
            self.scan1_response,
            self.scan2_response,
            self.tiebreaker_response,
        ]
        scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(mock_call.call_count, 3)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_tiebreaker_result_used_for_disagreed_fields(
        self, mock_call, mock_tess, mock_tier3
    ):
        """After tiebreaker, supplier and total should match tiebreaker output."""
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [
            self.scan1_response,
            self.scan2_response,
            self.tiebreaker_response,
        ]
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(result["supplier"], "Fresh Foods Inc.")
        self.assertAlmostEqual(result["total"], 23.65, places=2)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_metadata_records_three_api_calls(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [
            self.scan1_response,
            self.scan2_response,
            self.tiebreaker_response,
        ]
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertEqual(result["scan_metadata"]["scan_passes"], 3)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_agreement_ratio_below_one_when_disagreements_exist(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [
            self.scan1_response,
            self.scan2_response,
            self.tiebreaker_response,
        ]
        result = scan_invoice(self.image_bytes, mode="normal")
        self.assertLess(result["scan_metadata"]["agreement_ratio"], 1.0)


# ===========================================================================
# Task 5: Inference -- missing tax field filled from supplier memory (tier 1)
# ===========================================================================

class TestInferenceFillsMissingFields(TestCase):
    """Scan with missing tax -> inference tier 1 fills from supplier history."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()

        # Claude returns tax=None with confidence=0 (missing field scenario)
        self.response_missing_tax = make_claude_response(
            supplier="Fresh Foods Inc.",
            tax=None,
            total=21.50,   # subtotal only, no tax rolled in
            confidence_override={"tax": 0},
            inference_sources_override={"tax": "missing"},
        )

        # Set up a temp supplier memory with historical tax data for this supplier
        self.supplier_dir = tempfile.mkdtemp()
        self.general_dir = tempfile.mkdtemp()
        self.supplier_memory = JsonSupplierMemory(data_dir=Path(self.supplier_dir))
        self.general_memory = JsonGeneralMemory(data_dir=Path(self.general_dir))

        # Pre-save a historical scan so infer_missing("fresh-foods-inc", "tax")
        # can return 2.15.  save_scan() stores latest_values for a fixed set of
        # fields that does NOT include "tax".  We work around this by writing
        # the profile JSON directly with "tax" in latest_values.
        past_scan = {
            "supplier": "Fresh Foods Inc.",
            "date": "2026-01-01",
            "invoice_number": "INV-0001",
            "items": [],
            "subtotal": 21.50,
            "tax": 2.15,
            "total": 23.65,
            "confidence": {"tax": 90},
            "inference_sources": {"tax": "scanned"},
        }
        # First save via save_scan to create the profile and index
        self.supplier_memory.save_scan("fresh-foods-inc", past_scan)

        # Then patch latest_values to include "tax" directly
        profile_path = Path(self.supplier_dir) / "suppliers" / "fresh-foods-inc" / "profile.json"
        with open(profile_path) as f:
            profile = json.load(f)
        profile["latest_values"]["tax"] = 2.15
        with open(profile_path, "w") as f:
            json.dump(profile, f)

    def tearDown(self):
        shutil.rmtree(self.supplier_dir, ignore_errors=True)
        shutil.rmtree(self.general_dir, ignore_errors=True)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_inference_fills_missing_tax_from_supplier_memory(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = "fresh foods inc"
        mock_call.return_value = self.response_missing_tax

        with patch(
            "scanner.scanning.engine.JsonSupplierMemory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.scanning.engine.JsonGeneralMemory",
            return_value=self.general_memory,
        ):
            result = scan_invoice(self.image_bytes, mode="normal")

        # tax should now be filled from tier 1
        self.assertIsNotNone(result.get("tax"))

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_inference_source_recorded_as_tier1(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = "fresh foods inc"
        mock_call.return_value = self.response_missing_tax

        with patch(
            "scanner.scanning.engine.JsonSupplierMemory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.scanning.engine.JsonGeneralMemory",
            return_value=self.general_memory,
        ):
            result = scan_invoice(self.image_bytes, mode="normal")

        self.assertEqual(result["inference_sources"].get("tax"), "tier1_supplier")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_high_confidence_field_not_overwritten_by_inference(
        self, mock_call, mock_tess, mock_tier3
    ):
        """A field with confidence >= 60 should not be replaced by inference."""
        high_confidence_response = make_claude_response(
            supplier="Fresh Foods Inc.",
            tax=9.99,  # unusual value
            confidence_override={"tax": 95},
            inference_sources_override={"tax": "scanned"},
        )
        mock_tess.image_to_string.return_value = "fresh foods inc"
        mock_call.return_value = high_confidence_response

        with patch(
            "scanner.scanning.engine.JsonSupplierMemory",
            return_value=self.supplier_memory,
        ), patch(
            "scanner.scanning.engine.JsonGeneralMemory",
            return_value=self.general_memory,
        ):
            result = scan_invoice(self.image_bytes, mode="normal")

        # Should NOT replace 9.99 because confidence=95 >= threshold=60
        self.assertAlmostEqual(result["tax"], 9.99, places=2)


# ===========================================================================
# Task 6: Mode comparison -- verify model selection per mode
# ===========================================================================

class TestModeComparison(TestCase):
    """Verify that Light/Normal/Heavy modes select the right Claude model."""

    def setUp(self):
        self.image_bytes = make_receipt_image_bytes()
        self.agree_response = make_claude_response()

        # Two disagreeing responses to force a tiebreaker in normal/heavy modes
        self.scan1 = make_claude_response(supplier="Fresh Foods Inc.", total=23.65)
        self.scan2 = make_claude_response(supplier="Freshfoods", total=24.00)
        self.tiebreaker = make_claude_response(supplier="Fresh Foods Inc.", total=23.65)

    def _get_models_used(self, mock_call):
        """Extract the 'model' argument from each _call_claude invocation."""
        return [c.args[2] for c in mock_call.call_args_list]

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_light_mode_uses_only_sonnet(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.agree_response
        scan_invoice(self.image_bytes, mode="light")
        models = self._get_models_used(mock_call)
        self.assertTrue(all(m == SONNET for m in models), f"Expected all SONNET, got {models}")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_heavy_mode_uses_only_opus(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Heavy mode: all scans use OPUS (including tiebreaker if triggered)."""
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [self.scan1, self.scan2, self.tiebreaker]
        scan_invoice(self.image_bytes, mode="heavy")
        models = self._get_models_used(mock_call)
        self.assertTrue(all(m == OPUS for m in models), f"Expected all OPUS, got {models}")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_normal_mode_scans_1_2_use_sonnet(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Normal mode without tiebreaker: both scans use SONNET."""
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.agree_response
        scan_invoice(self.image_bytes, mode="normal")
        models = self._get_models_used(mock_call)
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0], SONNET)
        self.assertEqual(models[1], SONNET)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_normal_mode_tiebreaker_uses_opus(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Normal mode with tiebreaker: scans 1+2 use SONNET, tiebreaker uses OPUS."""
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [self.scan1, self.scan2, self.tiebreaker]
        scan_invoice(self.image_bytes, mode="normal")
        models = self._get_models_used(mock_call)
        self.assertEqual(len(models), 3)
        self.assertEqual(models[0], SONNET)
        self.assertEqual(models[1], SONNET)
        self.assertEqual(models[2], OPUS)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_metadata_api_calls_counts_correct_for_light(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Light mode: api_calls.sonnet=2, api_calls.opus=0."""
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.agree_response
        result = scan_invoice(self.image_bytes, mode="light")
        api_calls = result["scan_metadata"]["api_calls"]
        self.assertEqual(api_calls["sonnet"], 2)
        self.assertEqual(api_calls["opus"], 0)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_metadata_api_calls_counts_correct_for_heavy_with_tiebreaker(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Heavy mode with tiebreaker: api_calls.sonnet=0, api_calls.opus=3."""
        mock_tess.image_to_string.return_value = ""
        mock_call.side_effect = [self.scan1, self.scan2, self.tiebreaker]
        result = scan_invoice(self.image_bytes, mode="heavy")
        api_calls = result["scan_metadata"]["api_calls"]
        self.assertEqual(api_calls["sonnet"], 0)
        self.assertEqual(api_calls["opus"], 3)


# ===========================================================================
# Task 7: Full API flow -- POST /api/scan/ -> POST /api/confirm/ -> GET /api/stats/
# ===========================================================================

class TestFullAPIFlow(TestCase):
    """End-to-end HTTP API test: scan -> confirm -> stats."""

    def setUp(self):
        self.api_client = APIClient()
        self.image_bytes = make_receipt_image_bytes()
        self.claude_response = make_claude_response()

        # Isolated memory stores
        self.supplier_dir = tempfile.mkdtemp()
        self.general_dir = tempfile.mkdtemp()
        self.supplier_memory = JsonSupplierMemory(data_dir=Path(self.supplier_dir))
        self.general_memory = JsonGeneralMemory(data_dir=Path(self.general_dir))

    def tearDown(self):
        shutil.rmtree(self.supplier_dir, ignore_errors=True)
        shutil.rmtree(self.general_dir, ignore_errors=True)

    def _post_scan(self, mode="normal"):
        """Helper: POST an image to /api/scan/ and return response."""
        buf = io.BytesIO(self.image_bytes)
        buf.name = "receipt.png"
        return self.api_client.post(
            "/api/scan/",
            {"image": buf, "mode": mode},
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

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_endpoint_returns_200(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        response = self._post_scan()
        self.assertEqual(response.status_code, 200)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_endpoint_returns_invoice_fields(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        response = self._post_scan()
        data = response.json()
        for field in ("supplier", "date", "invoice_number", "items",
                      "subtotal", "tax", "total", "confidence",
                      "inference_sources", "scan_metadata"):
            self.assertIn(field, data, f"Missing field: {field}")

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_confirm_endpoint_returns_200(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response

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

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_confirm_returns_expected_fields(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response

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

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_confirm_with_corrections_count_matches(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response

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

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_full_scan_confirm_stats_flow(
        self, mock_call, mock_tess, mock_tier3
    ):
        """Smoke test: all three endpoints chained together without error."""
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response

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
