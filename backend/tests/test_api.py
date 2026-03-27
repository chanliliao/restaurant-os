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
