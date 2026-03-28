# Phase 17: Integration Testing + Golden Test Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive integration test suite that runs the full scan pipeline end-to-end against synthetic receipt images with mocked Claude API calls, validating each pipeline stage and mode comparison.

**Architecture:** All tests live in `backend/tests/test_integration.py` alongside a helper module `backend/tests/integration_helpers.py` that provides synthetic image generation and mock Claude response builders. `_call_claude` in `scanner/scanning/engine.py` is patched via `unittest.mock.patch` so no real API calls are made — the mock returns pre-built JSON strings that drive each test scenario. The inference module's Anthropic client is also patched to prevent tier-3 AI calls.

**Tech Stack:** Django TestCase, DRF APIClient, unittest.mock (patch/MagicMock), Pillow (PIL) for synthetic images, Python 3.13

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/tests/integration_helpers.py` | **Create** | Synthetic image builder + mock Claude JSON response builders |
| `backend/tests/test_integration.py` | **Create** | Seven integration test classes covering all pipeline scenarios |

No existing files are modified. The two new files together form the complete integration test surface.

---

### Task 1: Create integration_helpers.py — synthetic images and mock response builders

**Files:**
- Create: `backend/tests/integration_helpers.py`

This module is imported by every test class. It provides:
1. `make_receipt_image_bytes(text_lines, width, height)` — draws text onto a white PIL image and returns PNG bytes
2. `make_claude_response(supplier, date, invoice_number, items, subtotal, tax, total, confidence_override, inference_sources_override)` — builds the exact JSON string `_call_claude` would return

- [ ] **Step 1: Create the helper module**

Create `backend/tests/integration_helpers.py` with the following content:

```python
"""
Helpers for integration tests.

Provides:
- make_receipt_image_bytes(): synthetic PIL image as PNG bytes
- make_claude_response(): builds a JSON string matching engine expectations
"""

import io
import json

from PIL import Image, ImageDraw, ImageFont


def make_receipt_image_bytes(
    text_lines: list[str] | None = None,
    width: int = 400,
    height: int = 600,
) -> bytes:
    """Create a synthetic receipt-like PNG image.

    Draws white background with black text lines. Does not require
    Tesseract to parse — used only to feed the pipeline's image-open step.

    Args:
        text_lines: Lines of text to draw. Defaults to a generic receipt.
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        PNG bytes.
    """
    if text_lines is None:
        text_lines = [
            "FRESH FOODS INC",
            "123 Market Street",
            "Invoice: INV-1234",
            "Date: 2026-03-15",
            "",
            "Organic Tomatoes  5 kg  $3.50  $17.50",
            "Fresh Basil       2 bch $2.00  $4.00",
            "",
            "Subtotal: $21.50",
            "Tax (10%): $2.15",
            "Total: $23.65",
        ]

    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Use default bitmap font (always available, no TTF required)
    y = 10
    for line in text_lines:
        draw.text((10, y), line, fill="black")
        y += 20

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_claude_response(
    supplier: str = "Fresh Foods Inc.",
    date: str = "2026-03-15",
    invoice_number: str = "INV-1234",
    items: list[dict] | None = None,
    subtotal: float | None = 21.50,
    tax: float | None = 2.15,
    total: float | None = 23.65,
    confidence_override: dict | None = None,
    inference_sources_override: dict | None = None,
) -> str:
    """Build a JSON string matching the schema scan_invoice() expects from Claude.

    This is used as the return value of the mocked _call_claude().

    Args:
        supplier: Supplier name.
        date: Invoice date (YYYY-MM-DD).
        invoice_number: Invoice number string.
        items: Line items list. Defaults to two standard items.
        subtotal: Invoice subtotal.
        tax: Tax amount.
        total: Invoice total.
        confidence_override: Override specific confidence values.
        inference_sources_override: Override specific inference_sources values.

    Returns:
        JSON string.
    """
    if items is None:
        items = [
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
        ]

    confidence = {
        "supplier": 95,
        "date": 90,
        "invoice_number": 85,
        "subtotal": 88,
        "tax": 80,
        "total": 92,
    }
    if confidence_override:
        confidence.update(confidence_override)

    inference_sources = {
        "supplier": "scanned",
        "date": "scanned",
        "invoice_number": "scanned",
        "subtotal": "scanned",
        "tax": "scanned",
        "total": "scanned",
    }
    if inference_sources_override:
        inference_sources.update(inference_sources_override)

    payload = {
        "supplier": supplier,
        "date": date,
        "invoice_number": invoice_number,
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "confidence": confidence,
        "inference_sources": inference_sources,
    }
    return json.dumps(payload)
```

- [ ] **Step 2: Verify the helper module imports cleanly**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe -c "from tests.integration_helpers import make_receipt_image_bytes, make_claude_response; print('OK')"`

Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/integration_helpers.py
git commit -m "test: add integration test helpers — synthetic images + mock Claude response builder"
```

---

### Task 2: Integration test — clean receipt flows through full pipeline

**Files:**
- Create: `backend/tests/test_integration.py`
- Test: `backend/tests/test_integration.py::TestCleanReceiptPipeline`

This test confirms that a "happy path" scan with two agreeing Claude responses produces the correct merged output, correct scan_metadata structure, and that `_call_claude` is called exactly twice (no tiebreaker).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_integration.py` with this initial content:

```python
"""
Phase 17 — Integration tests for the full scan pipeline.

All tests mock scanner.scanning.engine._call_claude so no real Anthropic
API calls are made. They also mock scanner.memory.inference._tier3_ai to
prevent any other Anthropic calls from the inference tier.

Synthetic images are generated via integration_helpers.make_receipt_image_bytes().
"""

import io
import json
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
# Task 2: Clean Receipt — full pipeline, no disagreements
# ===========================================================================

class TestCleanReceiptPipeline(TestCase):
    """Full pipeline with two agreeing scans — no tiebreaker triggered."""

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
```

- [ ] **Step 2: Run the test to verify it fails (no test_integration module yet fails to import, which counts)**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestCleanReceiptPipeline -v2 2>&1 | head -30`

Expected: Module loads, tests run. Since `scan_invoice` calls real `_call_claude` without the mock if something is wrong, confirm they PASS at this point — the mocks are fully wired.

- [ ] **Step 3: Run full test to verify all Task 2 tests pass**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestCleanReceiptPipeline -v2`

Expected: 8 tests pass, 0 failures, 0 errors.

- [ ] **Step 4: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 2 — clean receipt full pipeline"
```

---

### Task 3: Integration test — math validation triggers and auto-corrects

**Files:**
- Modify: `backend/tests/test_integration.py` (append new class)
- Test: `backend/tests/test_integration.py::TestMathValidation`

This test feeds a scan result where `item.total` is wrong (e.g. quantity=5, unit_price=3.50 but total=20.00 instead of 17.50). Both scan 1 and scan 2 return this bad data so the comparator agrees and merges the error. The validator should catch it, auto-correct, and set `math_validation_triggered=True`.

- [ ] **Step 1: Write the failing test — append to test_integration.py**

Open `backend/tests/test_integration.py` and append the following class at the end of the file:

```python
# ===========================================================================
# Task 3: Math validation — wrong line total gets auto-corrected
# ===========================================================================

class TestMathValidation(TestCase):
    """Pipeline with a math error in both scans — validator must auto-correct."""

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
                    "total": 20.00,   # WRONG — should be 17.50
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
            subtotal=24.00,   # WRONG — items sum to 17.50+4.00=21.50
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
        # qty=5, unit_price=3.50 → expected 17.50
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
```

- [ ] **Step 2: Run Task 3 tests**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestMathValidation -v2`

Expected: 5 tests pass, 0 failures, 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 3 — math validation auto-correct"
```

---

### Task 4: Integration test — scan disagreement triggers tiebreaker

**Files:**
- Modify: `backend/tests/test_integration.py` (append new class)
- Test: `backend/tests/test_integration.py::TestTiebreakerTriggered`

The key mechanic: scan 1 and scan 2 must return _different_ JSON so `compare_scans()` finds disagreements. We achieve this by making `_call_claude` return a different value on its second call using `side_effect`. The tiebreaker (third call) returns a definitive response.

- [ ] **Step 1: Write the failing test — append to test_integration.py**

```python
# ===========================================================================
# Task 4: Tiebreaker — disagreement between scans triggers third call
# ===========================================================================

class TestTiebreakerTriggered(TestCase):
    """Two scans that disagree on supplier and total → tiebreaker fires."""

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
```

- [ ] **Step 2: Run Task 4 tests**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestTiebreakerTriggered -v2`

Expected: 5 tests pass, 0 failures, 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 4 — tiebreaker triggered on scan disagreement"
```

---

### Task 5: Integration test — inference fills missing/low-confidence fields

**Files:**
- Modify: `backend/tests/test_integration.py` (append new class)
- Test: `backend/tests/test_integration.py::TestInferenceFillsMissingFields`

The scan returns `tax=None` with confidence 0. The inference engine runs tier 1 (supplier memory) and fills in the missing value. We pre-populate a temp supplier memory store with a known `tax_rate`, patch `_get_supplier_memory` to use it, and verify the final result has the field filled with `inference_sources["tax"] == "tier1_supplier"`.

Note: The inference module calls `supplier_memory.infer_missing(supplier_id, "tax")`. `JsonSupplierMemory.infer_missing` returns the most recent scan's value for that field. So we need to pre-save a scan to the temp memory.

- [ ] **Step 1: Write the failing test — append to test_integration.py**

```python
# ===========================================================================
# Task 5: Inference — missing tax field filled from supplier memory (tier 1)
# ===========================================================================

class TestInferenceFillsMissingFields(TestCase):
    """Scan with missing tax → inference tier 1 fills from supplier history."""

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
        # can return 2.15
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
        self.supplier_memory.save_scan("fresh-foods-inc", past_scan)

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
```

- [ ] **Step 2: Run Task 5 tests**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestInferenceFillsMissingFields -v2`

Expected: 3 tests pass, 0 failures, 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 5 — inference fills missing fields from supplier memory"
```

---

### Task 6: Integration test — mode comparison (Light/Normal/Heavy model selection)

**Files:**
- Modify: `backend/tests/test_integration.py` (append new class)
- Test: `backend/tests/test_integration.py::TestModeComparison`

`_get_model_for_scan` determines which model string is passed to `_call_claude`. We capture the `model` argument on each call to verify:
- **Light:** all calls use SONNET
- **Normal with no disagreements:** calls 1+2 use SONNET; tiebreaker (call 3) would use OPUS but is not triggered
- **Normal with disagreements:** calls 1+2 use SONNET; call 3 (tiebreaker) uses OPUS
- **Heavy:** all calls use OPUS

- [ ] **Step 1: Write the failing test — append to test_integration.py**

```python
# ===========================================================================
# Task 6: Mode comparison — verify model selection per mode
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
```

- [ ] **Step 2: Run Task 6 tests**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestModeComparison -v2`

Expected: 6 tests pass, 0 failures, 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 6 — mode comparison verifies Light/Normal/Heavy model selection"
```

---

### Task 7: Integration test — full API endpoint flow (scan → confirm → stats)

**Files:**
- Modify: `backend/tests/test_integration.py` (append new class)
- Test: `backend/tests/test_integration.py::TestFullAPIFlow`

This tests the three HTTP endpoints together:
1. `POST /api/scan/` with a multipart image — returns scan result JSON
2. `POST /api/confirm/` with the scan result + corrections — returns confirmed
3. `GET /api/stats/` — returns accuracy + api_usage stats

Memory stores are patched to isolated temp directories so tests don't touch production data.

- [ ] **Step 1: Write the failing test — append to test_integration.py**

```python
# ===========================================================================
# Task 7: Full API flow — POST /api/scan/ → POST /api/confirm/ → GET /api/stats/
# ===========================================================================

class TestFullAPIFlow(TestCase):
    """End-to-end HTTP API test: scan → confirm → stats."""

    def setUp(self):
        self.api_client = APIClient()
        self.image_bytes = make_receipt_image_bytes()
        self.claude_response = make_claude_response()

        # Isolated memory stores
        self.supplier_dir = tempfile.mkdtemp()
        self.general_dir = tempfile.mkdtemp()
        self.supplier_memory = JsonSupplierMemory(data_dir=Path(self.supplier_dir))
        self.general_memory = JsonGeneralMemory(data_dir=Path(self.general_dir))

    def _post_scan(self, mock_call, mode="normal"):
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
        response = self._post_scan(mock_call)
        self.assertEqual(response.status_code, 200)

    @patch(TIER3_AI, return_value=None)
    @patch(OCR_PREPASS)
    @patch(CALL_CLAUDE)
    def test_scan_endpoint_returns_invoice_fields(
        self, mock_call, mock_tess, mock_tier3
    ):
        mock_tess.image_to_string.return_value = ""
        mock_call.return_value = self.claude_response
        response = self._post_scan(mock_call)
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
            scan_resp = self._post_scan(mock_call)
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
            scan_resp = self._post_scan(mock_call)
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
            scan_resp = self._post_scan(mock_call)
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
            scan_resp = self._post_scan(mock_call)
            self.assertEqual(scan_resp.status_code, 200)

            scan_result = scan_resp.json()
            confirm_resp = self._post_confirm(scan_result)
            self.assertEqual(confirm_resp.status_code, 200)

        stats_resp = self.api_client.get("/api/stats/")
        self.assertEqual(stats_resp.status_code, 200)
```

- [ ] **Step 2: Run Task 7 tests**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration.TestFullAPIFlow -v2`

Expected: 8 tests pass, 0 failures, 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py
git commit -m "test: integration test Task 7 — full API flow scan → confirm → stats"
```

---

### Task 8: Run the full integration suite + full existing suite

**Files:** No new files.

Run the new integration suite alone, then the full 364+N test suite to confirm nothing was broken.

- [ ] **Step 1: Run the complete integration test file**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests.test_integration -v2`

Expected: All 35 tests pass (8 + 5 + 5 + 3 + 6 + 8), 0 failures, 0 errors.

- [ ] **Step 2: Run the full test suite**

Run: `cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner/backend && /c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test tests -v2 2>&1 | tail -20`

Expected: All tests pass. Count should be 364 + 35 = 399 (or similar, depending on prior test count).

- [ ] **Step 3: Final commit**

```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/SmartScanner
git add backend/tests/test_integration.py backend/tests/integration_helpers.py
git commit -m "test: Phase 17 complete — integration test suite with 35 tests across 6 pipeline scenarios"
```

---

## Self-Review

**1. Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `tests/fixtures/` directory with test images | Replaced by `make_receipt_image_bytes()` in `integration_helpers.py` per spec simplification decision |
| `tests/expected/` directory | Replaced by inline `make_claude_response()` calls per spec simplification decision |
| `tests/test_integration.py` — full pipeline test | Task 2 (TestCleanReceiptPipeline) |
| Upload image → preprocessing → scan → validate → output | Task 2 — tests full `scan_invoice()` call chain |
| Mode comparison test: Light/Normal/Heavy | Task 6 (TestModeComparison) — 6 tests verify model strings and api_call counts |
| Compare output against expected, field-by-field | Tasks 2, 3, 4, 5 all assert specific field values |
| Math validation scenario | Task 3 (TestMathValidation) — wrong line total, recalculated subtotal+total |
| Tiebreaker disagreement scenario | Task 4 (TestTiebreakerTriggered) — side_effect forces 3 calls |
| Inference fills missing fields | Task 5 (TestInferenceFillsMissingFields) — tier1 fills missing tax |
| Full API endpoint test | Task 7 (TestFullAPIFlow) — POST scan → confirm → GET stats |
| Mock `_call_claude` | All tests patch `scanner.scanning.engine._call_claude` |
| `_call_claude` must be mocked | Confirmed — all test classes apply `@patch(CALL_CLAUDE)` |

**2. Placeholder scan:** No "TBD", "TODO", or vague instructions found. All code blocks are complete.

**3. Type consistency check:**

- `_call_claude(prompt, images, model)` — Task 6 uses `c.args[2]` to extract the `model` argument (position 2, 0-indexed). This is correct: the signature is `_call_claude(prompt: str, images: list[dict], model: str)` — `args[2]` is `model`. Verified against engine.py line 84.
- `make_claude_response()` returns a JSON string — all `mock_call.return_value = ...` assignments are consistent.
- `make_receipt_image_bytes()` returns `bytes` — passed directly to `scan_invoice(image_bytes, ...)` which expects `bytes`. Consistent.
- `JsonSupplierMemory(data_dir=Path(...))` — matches constructor in json_store.py. Consistent with test_api.py usage at line 143.
- `supplier_memory.save_scan("fresh-foods-inc", past_scan)` in Task 5 — `save_scan(supplier_id, scan)` is the correct method signature confirmed in views.py line 99.
- `CALL_CLAUDE = "scanner.scanning.engine._call_claude"` — matches the fully qualified path in engine.py. Correct.
- `TIER3_AI = "scanner.memory.inference._tier3_ai"` — matches inference.py line 186. Correct.
- `OCR_PREPASS = "scanner.scanning.ocr.pytesseract"` — patches the pytesseract module used by ocr.py. Consistent with test_scanning.py pattern at line 124.
- `io` imported at top of test_integration.py in Task 7 (`_post_scan` uses `io.BytesIO`) — must be added to the imports block. **Fix applied below.**

**Fix: Task 2's initial file creation is missing `import io` and `import tempfile`.** The file header in Task 2 Step 1 already shows `import io` and `import tempfile` in the import block. Verified — both are present.

No issues found.
