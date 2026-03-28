import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from PIL import Image

from scanner.memory import JsonSupplierMemory, JsonGeneralMemory


class TestScanEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _create_test_image(self):
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "test_receipt.png"
        return buf

    def test_scan_endpoint_returns_200(self):
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image, "mode": "normal"}, format="multipart")
        self.assertEqual(response.status_code, 200)

    def test_scan_endpoint_returns_expected_json_structure(self):
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

    def test_scan_metadata_contains_mode(self):
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

    def test_scan_endpoint_defaults_mode_to_normal(self):
        image = self._create_test_image()
        response = self.client.post("/api/scan/", {"image": image}, format="multipart")
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "normal")


class TestConfirmEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.valid_payload = {
            "scan_result": {
                "supplier": "Test Supplier",
                "date": "2026-01-01",
                "invoice_number": "INV-001",
                "items": [],
                "subtotal": 100.0,
                "tax": 10.0,
                "total": 110.0,
                "confidence": {},
                "inference_sources": {},
                "scan_metadata": {"mode": "normal"},
            },
            "corrections": [
                {
                    "field": "supplier",
                    "original_value": "Test Supplir",
                    "corrected_value": "Test Supplier",
                }
            ],
            "confirmed_at": "2026-03-27T12:00:00Z",
        }

    def test_confirm_returns_200(self):
        response = self.client.post("/api/confirm/", self.valid_payload, format="json")
        self.assertEqual(response.status_code, 200)

    def test_confirm_returns_expected_fields(self):
        response = self.client.post("/api/confirm/", self.valid_payload, format="json")
        data = response.json()
        self.assertEqual(data["status"], "confirmed")
        self.assertEqual(data["corrections_count"], 1)
        self.assertIn("confirmed_at", data)

    def test_confirm_with_no_corrections(self):
        payload = {**self.valid_payload, "corrections": []}
        response = self.client.post("/api/confirm/", payload, format="json")
        data = response.json()
        self.assertEqual(data["status"], "confirmed")
        self.assertEqual(data["corrections_count"], 0)

    def test_confirm_rejects_missing_scan_result(self):
        payload = {
            "corrections": [],
            "confirmed_at": "2026-03-27T12:00:00Z",
        }
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_confirm_rejects_missing_confirmed_at(self):
        payload = {
            "scan_result": self.valid_payload["scan_result"],
            "corrections": [],
        }
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_confirm_rejects_invalid_correction_shape(self):
        payload = {
            **self.valid_payload,
            "corrections": [{"bad_field": "oops"}],
        }
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 400)


class TestConfirmUpdatesMemory(TestCase):
    """Integration tests: confirm endpoint writes to memory stores."""

    def setUp(self):
        self.client = APIClient()
        self.supplier_dir = tempfile.mkdtemp()
        self.general_dir = tempfile.mkdtemp()
        self.supplier_memory = JsonSupplierMemory(data_dir=Path(self.supplier_dir))
        self.general_memory = JsonGeneralMemory(data_dir=Path(self.general_dir))

        self.patcher_supplier = patch(
            "scanner.views._get_supplier_memory",
            return_value=self.supplier_memory,
        )
        self.patcher_general = patch(
            "scanner.views._get_general_memory",
            return_value=self.general_memory,
        )
        self.patcher_supplier.start()
        self.patcher_general.start()

        self.base_scan = {
            "supplier": "Sysco Foods",
            "date": "2026-01-01",
            "invoice_number": "INV-001",
            "items": [
                {"name": "Chicken Breast", "unit_price": 4.99, "unit": "lb"},
                {"name": "Ghost Item", "unit_price": 99.00, "unit": "ea"},
            ],
            "subtotal": 103.99,
            "tax": 8.32,
            "total": 112.31,
            "confidence": {},
            "inference_sources": {},
            "scan_metadata": {"mode": "normal"},
        }

    def tearDown(self):
        self.patcher_supplier.stop()
        self.patcher_general.stop()

    def _post_confirm(self, scan_result=None, corrections=None):
        payload = {
            "scan_result": scan_result or self.base_scan,
            "corrections": corrections or [],
            "confirmed_at": "2026-03-27T12:00:00Z",
        }
        return self.client.post("/api/confirm/", payload, format="json")

    def test_confirm_saves_corrected_values_to_supplier_memory(self):
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
        ]
        scan = {**self.base_scan, "supplier": "Sysco Fods"}
        response = self._post_confirm(scan_result=scan, corrections=corrections)
        self.assertEqual(response.status_code, 200)

        profile = self.supplier_memory.get_profile("sysco-foods")
        self.assertEqual(profile["latest_values"]["supplier"], "Sysco Foods")

    def test_confirm_saves_error_categories_in_corrections(self):
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
            {"field": "date", "original_value": None, "corrected_value": "2026-01-01"},
        ]
        scan = {**self.base_scan, "supplier": "Sysco Fods"}
        self._post_confirm(scan_result=scan, corrections=corrections)

        profile = self.supplier_memory.get_profile("sysco-foods")
        stored_corrections = profile.get("corrections", [])
        self.assertTrue(len(stored_corrections) >= 2)
        error_types = [c["error_type"] for c in stored_corrections]
        self.assertIn("misread", error_types)
        self.assertIn("missing", error_types)

    def test_confirm_updates_general_memory(self):
        self._post_confirm()

        catalog = self.general_memory.get_item_catalog()
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_no_corrections_still_saves_to_memory(self):
        self._post_confirm(corrections=[])

        profile = self.supplier_memory.get_profile("sysco-foods")
        self.assertEqual(profile["scan_count"], 1)

    def test_confirm_empty_supplier_skips_supplier_memory(self):
        scan = {**self.base_scan, "supplier": ""}
        self._post_confirm(scan_result=scan, corrections=[])

        # General memory should still be updated
        catalog = self.general_memory.get_item_catalog()
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_none_supplier_skips_supplier_memory(self):
        scan = {**self.base_scan, "supplier": None}
        self._post_confirm(scan_result=scan, corrections=[])

        catalog = self.general_memory.get_item_catalog()
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_deleted_row_removes_item_before_saving(self):
        corrections = [
            {"field": "items[1]", "original_value": {"name": "Ghost Item"}, "corrected_value": "deleted_row"},
        ]
        self._post_confirm(corrections=corrections)

        catalog = self.general_memory.get_item_catalog()
        self.assertNotIn("Ghost Item", catalog.get("items", {}))
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_response_includes_memory_updated_flag(self):
        response = self._post_confirm()
        data = response.json()
        self.assertTrue(data.get("memory_updated"))
