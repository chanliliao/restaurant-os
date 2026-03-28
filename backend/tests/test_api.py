import io
from django.test import TestCase
from rest_framework.test import APIClient
from PIL import Image


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
