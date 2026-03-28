"""Tests for accuracy tracking, API usage tracking, stats endpoint, and confirm wiring."""

import json
import os
import tempfile
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from scanner.tracking.accuracy import record_scan_accuracy, get_accuracy_stats
from scanner.tracking.api_usage import record_api_usage, get_usage_stats


# ── Accuracy Tracker Tests ──────────────────────────────────────────


class AccuracyTrackerTest(TestCase):
    """Tests for record_scan_accuracy and get_accuracy_stats."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.stats_path = os.path.join(self.tmp_dir, "accuracy.json")

    def tearDown(self):
        if os.path.exists(self.stats_path):
            os.remove(self.stats_path)
        os.rmdir(self.tmp_dir)

    @mock.patch("scanner.tracking.accuracy._get_accuracy_path")
    def test_record_first_scan(self, mock_path):
        mock_path.return_value = self.stats_path
        record_scan_accuracy(
            scan_id="scan-001",
            mode="normal",
            supplier_id="sysco",
            total_fields=10,
            corrections_count=2,
        )
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["scans"]), 1)
        self.assertEqual(data["scans"][0]["scan_id"], "scan-001")
        self.assertEqual(data["scans"][0]["accuracy"], 0.8)

    @mock.patch("scanner.tracking.accuracy._get_accuracy_path")
    def test_record_multiple_scans_accumulates(self, mock_path):
        mock_path.return_value = self.stats_path
        record_scan_accuracy("s1", "light", "sysco", 10, 0)
        record_scan_accuracy("s2", "normal", "sysco", 10, 5)
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["scans"]), 2)

    @mock.patch("scanner.tracking.accuracy._get_accuracy_path")
    def test_get_accuracy_stats_empty(self, mock_path):
        mock_path.return_value = self.stats_path
        stats = get_accuracy_stats()
        self.assertEqual(stats["total_scans"], 0)
        self.assertEqual(stats["average_accuracy"], 0)

    @mock.patch("scanner.tracking.accuracy._get_accuracy_path")
    def test_get_accuracy_stats_with_data(self, mock_path):
        mock_path.return_value = self.stats_path
        record_scan_accuracy("s1", "normal", "sysco", 10, 0)
        record_scan_accuracy("s2", "normal", "birite", 10, 4)
        stats = get_accuracy_stats()
        self.assertEqual(stats["total_scans"], 2)
        self.assertAlmostEqual(stats["average_accuracy"], 0.8)
        self.assertEqual(stats["by_mode"]["normal"]["count"], 2)

    @mock.patch("scanner.tracking.accuracy._get_accuracy_path")
    def test_zero_fields_records_zero_accuracy(self, mock_path):
        mock_path.return_value = self.stats_path
        record_scan_accuracy("s1", "normal", "sysco", 0, 0)
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertEqual(data["scans"][0]["accuracy"], 0)


# ── API Usage Tracker Tests ─────────────────────────────────────────


class ApiUsageTrackerTest(TestCase):
    """Tests for record_api_usage and get_usage_stats."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.stats_path = os.path.join(self.tmp_dir, "api_usage.json")

    def tearDown(self):
        if os.path.exists(self.stats_path):
            os.remove(self.stats_path)
        os.rmdir(self.tmp_dir)

    @mock.patch("scanner.tracking.api_usage._get_usage_path")
    def test_record_first_usage(self, mock_path):
        mock_path.return_value = self.stats_path
        record_api_usage("scan-001", "normal", {"claude_calls": 3, "total_tokens": 1500})
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["api_calls"]["claude_calls"], 3)

    @mock.patch("scanner.tracking.api_usage._get_usage_path")
    def test_get_usage_stats_empty(self, mock_path):
        mock_path.return_value = self.stats_path
        stats = get_usage_stats()
        self.assertEqual(stats["total_scans"], 0)

    @mock.patch("scanner.tracking.api_usage._get_usage_path")
    def test_get_usage_stats_aggregates(self, mock_path):
        mock_path.return_value = self.stats_path
        record_api_usage("s1", "normal", {"claude_calls": 3, "total_tokens": 1000})
        record_api_usage("s2", "heavy", {"claude_calls": 5, "total_tokens": 2000})
        stats = get_usage_stats()
        self.assertEqual(stats["total_scans"], 2)
        self.assertEqual(stats["totals"]["claude_calls"], 8)
        self.assertEqual(stats["totals"]["total_tokens"], 3000)
        self.assertEqual(stats["by_mode"]["normal"]["count"], 1)
        self.assertEqual(stats["by_mode"]["heavy"]["count"], 1)


# ── Stats Endpoint Tests ────────────────────────────────────────────


class StatsEndpointTest(TestCase):
    """Tests for the stats API endpoint."""

    def setUp(self):
        self.client = APIClient()

    @mock.patch("scanner.views.get_accuracy_stats")
    @mock.patch("scanner.views.get_usage_stats")
    def test_stats_endpoint_returns_combined(self, mock_usage, mock_accuracy):
        mock_accuracy.return_value = {
            "total_scans": 5,
            "average_accuracy": 0.9,
            "total_corrections": 3,
            "by_mode": {},
            "by_supplier": {},
        }
        mock_usage.return_value = {
            "total_scans": 5,
            "totals": {"claude_calls": 15},
            "by_mode": {},
        }
        response = self.client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("accuracy", data)
        self.assertIn("api_usage", data)
        self.assertEqual(data["accuracy"]["total_scans"], 5)

    @mock.patch("scanner.views.get_accuracy_stats")
    @mock.patch("scanner.views.get_usage_stats")
    def test_stats_endpoint_empty(self, mock_usage, mock_accuracy):
        mock_accuracy.return_value = {
            "total_scans": 0,
            "average_accuracy": 0,
            "total_corrections": 0,
            "by_mode": {},
            "by_supplier": {},
        }
        mock_usage.return_value = {"total_scans": 0, "totals": {}, "by_mode": {}}
        response = self.client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)


# ── Confirm Tracking Wiring Tests ───────────────────────────────────


class ConfirmTrackingWiringTest(TestCase):
    """Verify confirm endpoint calls tracking functions."""

    def setUp(self):
        self.client = APIClient()

    @mock.patch("scanner.views.record_api_usage")
    @mock.patch("scanner.views.record_scan_accuracy")
    @mock.patch("scanner.views._get_general_memory")
    @mock.patch("scanner.views._get_supplier_memory")
    def test_confirm_records_tracking(
        self, mock_sup_mem, mock_gen_mem, mock_accuracy, mock_usage
    ):
        mock_gen_mem.return_value = mock.MagicMock()
        mock_sup_mem.return_value = mock.MagicMock()

        payload = {
            "scan_result": {
                "supplier": "Sysco",
                "date": "2026-01-15",
                "invoice_number": "INV-001",
                "items": [
                    {
                        "name": "Tomatoes",
                        "quantity": 10,
                        "unit": "lb",
                        "unit_price": 2.5,
                        "total": 25.0,
                        "confidence": 0.95,
                    }
                ],
                "subtotal": 25.0,
                "tax": 2.0,
                "total": 27.0,
                "confidence": {"supplier": 0.95, "date": 0.9},
                "inference_sources": {},
                "scan_metadata": {
                    "mode": "normal",
                    "scans_performed": 1,
                    "tiebreaker_triggered": False,
                    "math_validation_triggered": False,
                    "api_calls": 3,
                    "models_used": ["claude-sonnet-4-20250514"],
                    "preprocessing": {},
                },
            },
            "corrections": [
                {
                    "field": "supplier",
                    "original_value": "Syco",
                    "corrected_value": "Sysco",
                }
            ],
            "confirmed_at": "2026-01-15T12:00:00Z",
        }
        response = self.client.post(
            "/api/confirm/", json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        mock_accuracy.assert_called_once()
        mock_usage.assert_called_once()
