# Phase 14: Memory Learning from User Corrections

> **For agentic workers:** execute this plan using the `superpowers:subagent-driven-development` skill.

## Goal

Wire the learning loop so that confirmed corrections update memory. When a user confirms a scan with corrections, the system (1) builds corrected scan data, (2) categorizes each error, and (3) saves the corrected data + error categories to both supplier and general memory stores.

## Current State

- `POST /api/confirm/` accepts corrections but only logs them (no memory update)
- `JsonSupplierMemory.save_scan()` already stores corrections and updates profiles
- `JsonGeneralMemory.update_from_scan()` already updates item catalog and industry stats
- No error categorization exists yet
- No logic to apply corrections to scan data exists yet

## New & Modified Files

| # | File | Action |
|---|------|--------|
| 1 | `backend/scanner/memory/categorizer.py` | **Create** - Error categorization (pure functions) |
| 2 | `backend/scanner/memory/corrections.py` | **Create** - Apply corrections to scan data (pure functions) |
| 3 | `backend/scanner/memory/__init__.py` | **Modify** - Export new modules |
| 4 | `backend/scanner/views.py` | **Modify** - Wire confirm endpoint to memory |
| 5 | `backend/tests/test_categorizer.py` | **Create** - Unit tests for categorizer |
| 6 | `backend/tests/test_corrections.py` | **Create** - Unit tests for correction application |
| 7 | `backend/tests/test_api.py` | **Modify** - Add confirm+memory integration tests |

## Security

- No new user inputs beyond what `ConfirmRequestSerializer` already validates
- Supplier name from `scan_result` is normalized via `normalize_supplier_id()` which rejects path traversal
- Empty/unknown supplier names are handled gracefully (skip supplier memory, still update general)
- All memory writes go through existing atomic JSON write functions with file locks

---

## Tasks

### Task 1: Error Categorizer - Tests

**File:** `backend/tests/test_categorizer.py`

```python
"""Tests for error categorization."""

import pytest

from scanner.memory.categorizer import categorize_error, categorize_corrections


class TestCategorizeError:
    """Unit tests for single-error categorization."""

    def test_misread_both_non_empty(self):
        assert categorize_error("supplier", "Sysco Fods", "Sysco Foods") == "misread"

    def test_misread_numeric(self):
        assert categorize_error("total", 100.0, 110.0) == "misread"

    def test_missing_original_none(self):
        assert categorize_error("date", None, "2026-01-01") == "missing"

    def test_missing_original_empty_string(self):
        assert categorize_error("supplier", "", "Sysco Foods") == "missing"

    def test_missing_original_zero(self):
        assert categorize_error("total", 0, 110.0) == "missing"

    def test_hallucinated_corrected_none(self):
        assert categorize_error("tax", 5.00, None) == "hallucinated"

    def test_hallucinated_corrected_empty(self):
        assert categorize_error("supplier", "Ghost Corp", "") == "hallucinated"

    def test_hallucinated_deleted_row(self):
        assert categorize_error("items[2]", {"name": "Phantom"}, "deleted_row") == "hallucinated"

    def test_missing_original_empty_list(self):
        assert categorize_error("items", [], [{"name": "Real Item"}]) == "missing"

    def test_misread_both_zero_is_misread(self):
        # Edge: 0 -> 0 is technically misread (both "present" as zero)
        # but this shouldn't happen in practice. Categorize as misread.
        assert categorize_error("qty", 0, 0) == "misread"


class TestCategorizeCorrections:
    """Tests for batch categorization."""

    def test_adds_error_type_to_each(self):
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
            {"field": "date", "original_value": None, "corrected_value": "2026-01-01"},
            {"field": "items[2]", "original_value": {"name": "Ghost"}, "corrected_value": "deleted_row"},
        ]
        result = categorize_corrections(corrections)
        assert len(result) == 3
        assert result[0]["error_type"] == "misread"
        assert result[1]["error_type"] == "missing"
        assert result[2]["error_type"] == "hallucinated"

    def test_empty_corrections_returns_empty(self):
        assert categorize_corrections([]) == []

    def test_does_not_mutate_input(self):
        corrections = [
            {"field": "supplier", "original_value": "A", "corrected_value": "B"},
        ]
        result = categorize_corrections(corrections)
        assert "error_type" not in corrections[0]
        assert "error_type" in result[0]
```

**Test command:** `cd backend && python -m pytest tests/test_categorizer.py -v`

**Expected:** All tests FAIL (module does not exist yet).

---

### Task 2: Error Categorizer - Implementation

**File:** `backend/scanner/memory/categorizer.py`

```python
"""Error categorization for user corrections.

Pure functions -- no I/O, no state. Classifies each correction into one of:
  - "misread"      : OCR read it wrong (both original and corrected are non-empty)
  - "missing"      : OCR missed it (original is empty/null/zero, corrected is not)
  - "hallucinated" : OCR made it up (original is non-empty, corrected is empty/null/"deleted_row")
"""

from __future__ import annotations


def _is_empty(value) -> bool:
    """Return True if value is considered empty/absent."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _is_deletion(value) -> bool:
    """Return True if the corrected value signals a deletion."""
    if value is None:
        return True
    if isinstance(value, str) and (value.strip() == "" or value.strip() == "deleted_row"):
        return True
    return False


def categorize_error(field: str, original_value, corrected_value) -> str:
    """Classify a single field correction into an error type.

    Args:
        field: The field name/path that was corrected.
        original_value: The value the scanner produced.
        corrected_value: The value the user corrected it to.

    Returns:
        One of "misread", "missing", or "hallucinated".
    """
    original_empty = _is_empty(original_value)
    corrected_is_deletion = _is_deletion(corrected_value)

    if not original_empty and corrected_is_deletion:
        return "hallucinated"
    if original_empty and not corrected_is_deletion:
        return "missing"
    return "misread"


def categorize_corrections(corrections: list[dict]) -> list[dict]:
    """Add ``error_type`` to each correction dict. Returns new list (no mutation).

    Each input dict must have ``field``, ``original_value``, ``corrected_value``.
    """
    result = []
    for correction in corrections:
        enriched = {**correction}
        enriched["error_type"] = categorize_error(
            correction["field"],
            correction["original_value"],
            correction["corrected_value"],
        )
        result.append(enriched)
    return result
```

**Test command:** `cd backend && python -m pytest tests/test_categorizer.py -v`

**Expected:** All tests PASS.

**Commit:** `"Add error categorizer for user corrections (Phase 14)"`

---

### Task 3: Apply Corrections to Scan Data - Tests

**File:** `backend/tests/test_corrections.py`

```python
"""Tests for applying corrections to scan data."""

import copy

import pytest

from scanner.memory.corrections import apply_corrections


class TestApplyCorrectionsHeader:
    """Test applying corrections to top-level scan fields."""

    def test_correct_header_field(self):
        scan = {"supplier": "Sysco Fods", "date": "2026-01-01", "items": []}
        corrections = [
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["supplier"] == "Sysco Foods"

    def test_correct_multiple_header_fields(self):
        scan = {"supplier": "Bad", "date": "wrong", "total": 0, "items": []}
        corrections = [
            {"field": "supplier", "original_value": "Bad", "corrected_value": "Good"},
            {"field": "date", "original_value": "wrong", "corrected_value": "2026-01-01"},
            {"field": "total", "original_value": 0, "corrected_value": 110.0},
        ]
        result = apply_corrections(scan, corrections)
        assert result["supplier"] == "Good"
        assert result["date"] == "2026-01-01"
        assert result["total"] == 110.0

    def test_no_corrections_returns_copy(self):
        scan = {"supplier": "Sysco", "items": []}
        result = apply_corrections(scan, [])
        assert result == scan
        assert result is not scan

    def test_does_not_mutate_original(self):
        scan = {"supplier": "Old", "items": []}
        original = copy.deepcopy(scan)
        corrections = [
            {"field": "supplier", "original_value": "Old", "corrected_value": "New"},
        ]
        apply_corrections(scan, corrections)
        assert scan == original


class TestApplyCorrectionsItems:
    """Test applying corrections to line items."""

    def test_correct_item_field(self):
        scan = {
            "supplier": "Sysco",
            "items": [
                {"name": "Chicken", "unit_price": 4.00, "unit": "lb"},
            ],
        }
        corrections = [
            {"field": "items[0].unit_price", "original_value": 4.00, "corrected_value": 4.99},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][0]["unit_price"] == 4.99

    def test_correct_item_name(self):
        scan = {
            "items": [
                {"name": "Chiken Brest", "unit_price": 4.99},
            ],
        }
        corrections = [
            {"field": "items[0].name", "original_value": "Chiken Brest", "corrected_value": "Chicken Breast"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][0]["name"] == "Chicken Breast"

    def test_correct_second_item(self):
        scan = {
            "items": [
                {"name": "Chicken", "unit_price": 4.99},
                {"name": "Rice", "unit_price": 1.00},
            ],
        }
        corrections = [
            {"field": "items[1].unit_price", "original_value": 1.00, "corrected_value": 1.50},
        ]
        result = apply_corrections(scan, corrections)
        assert result["items"][1]["unit_price"] == 1.50
        assert result["items"][0]["unit_price"] == 4.99  # unchanged


class TestApplyCorrectionsDeleteRow:
    """Test deleting hallucinated rows."""

    def test_delete_row(self):
        scan = {
            "items": [
                {"name": "Real Item", "unit_price": 5.00},
                {"name": "Ghost Item", "unit_price": 99.00},
            ],
        }
        corrections = [
            {"field": "items[1]", "original_value": {"name": "Ghost Item"}, "corrected_value": "deleted_row"},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Real Item"

    def test_delete_multiple_rows_highest_index_first(self):
        scan = {
            "items": [
                {"name": "Keep"},
                {"name": "Delete1"},
                {"name": "Also Keep"},
                {"name": "Delete2"},
            ],
        }
        corrections = [
            {"field": "items[1]", "original_value": {"name": "Delete1"}, "corrected_value": "deleted_row"},
            {"field": "items[3]", "original_value": {"name": "Delete2"}, "corrected_value": "deleted_row"},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "Keep"
        assert result["items"][1]["name"] == "Also Keep"


class TestApplyCorrectionsEdgeCases:
    """Edge cases."""

    def test_out_of_range_index_is_skipped(self):
        scan = {"items": [{"name": "Only"}]}
        corrections = [
            {"field": "items[5].unit_price", "original_value": 0, "corrected_value": 10},
        ]
        result = apply_corrections(scan, corrections)
        assert len(result["items"]) == 1

    def test_unknown_header_field_added(self):
        scan = {"supplier": "Sysco", "items": []}
        corrections = [
            {"field": "notes", "original_value": None, "corrected_value": "Rush order"},
        ]
        result = apply_corrections(scan, corrections)
        assert result["notes"] == "Rush order"
```

**Test command:** `cd backend && python -m pytest tests/test_corrections.py -v`

**Expected:** All tests FAIL (module does not exist yet).

---

### Task 4: Apply Corrections - Implementation

**File:** `backend/scanner/memory/corrections.py`

```python
"""Apply user corrections to scan data to produce the canonical "truth" result.

Pure functions -- no I/O, no state.
"""

from __future__ import annotations

import copy
import re


def _parse_item_field(field: str) -> tuple[int, str | None] | None:
    """Parse ``items[N]`` or ``items[N].subfield`` into (index, subfield|None).

    Returns None if the field does not match the items pattern.
    """
    m = re.match(r"^items\[(\d+)\](?:\.(.+))?$", field)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def apply_corrections(scan_result: dict, corrections: list[dict]) -> dict:
    """Apply a list of corrections to a scan result, returning a new dict.

    Corrections are dicts with ``field``, ``original_value``, ``corrected_value``.

    Field paths:
    - Top-level: ``"supplier"``, ``"total"``, etc. -- set directly.
    - Item field: ``"items[0].unit_price"`` -- update item at index.
    - Row deletion: ``"items[1]"`` with ``corrected_value == "deleted_row"`` -- remove item.

    Does NOT mutate the input ``scan_result``.
    """
    result = copy.deepcopy(scan_result)

    # Separate deletions from other corrections so we can process deletions last
    # (highest index first to avoid shifting).
    deletions: list[int] = []
    field_updates: list[dict] = []

    for correction in corrections:
        field = correction["field"]
        corrected = correction["corrected_value"]

        parsed = _parse_item_field(field)
        if parsed is not None:
            idx, subfield = parsed
            if subfield is None and corrected == "deleted_row":
                deletions.append(idx)
            else:
                field_updates.append(correction)
        else:
            field_updates.append(correction)

    # Apply field updates (header and item subfields)
    items = result.get("items", [])
    for correction in field_updates:
        field = correction["field"]
        corrected = correction["corrected_value"]

        parsed = _parse_item_field(field)
        if parsed is not None:
            idx, subfield = parsed
            if 0 <= idx < len(items) and subfield:
                items[idx][subfield] = corrected
        else:
            # Top-level header field
            result[field] = corrected

    # Apply deletions highest-index-first so indices stay valid
    for idx in sorted(deletions, reverse=True):
        if 0 <= idx < len(items):
            del items[idx]

    return result
```

**Test command:** `cd backend && python -m pytest tests/test_corrections.py -v`

**Expected:** All tests PASS.

**Commit:** `"Add correction application helpers (Phase 14)"`

---

### Task 5: Export New Modules from memory package

**File:** `backend/scanner/memory/__init__.py`

Add imports and exports for `categorize_error`, `categorize_corrections`, and `apply_corrections`:

```python
"""Restaurant OS memory system for supplier and industry data."""

from .categorizer import categorize_corrections, categorize_error
from .corrections import apply_corrections
from .inference import infer_field, run_inference
from .interface import GeneralMemory, SupplierMemory
from .json_store import (
    JsonGeneralMemory,
    JsonSupplierMemory,
    normalize_supplier_id,
)

__all__ = [
    "SupplierMemory",
    "GeneralMemory",
    "JsonSupplierMemory",
    "JsonGeneralMemory",
    "normalize_supplier_id",
    "infer_field",
    "run_inference",
    "categorize_error",
    "categorize_corrections",
    "apply_corrections",
]
```

**Test command:** `cd backend && python -m pytest tests/test_categorizer.py tests/test_corrections.py -v`

**Expected:** All tests still PASS.

**Commit:** `"Export categorizer and corrections from memory package (Phase 14)"`

---

### Task 6: Wire Confirm Endpoint to Memory - Tests

**File:** `backend/tests/test_api.py`

Add new test class at end of file:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch

from scanner.memory import JsonSupplierMemory, JsonGeneralMemory


class TestConfirmUpdatesMemory(TestCase):
    """Integration tests: confirm endpoint writes to memory stores."""

    def setUp(self):
        self.client = APIClient()
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp_dir)
        (self.tmp_path / "suppliers").mkdir()
        (self.tmp_path / "general").mkdir()
        (self.tmp_path / "stats").mkdir()

        self.supplier_mem = JsonSupplierMemory(data_dir=self.tmp_path)
        self.general_mem = JsonGeneralMemory(data_dir=self.tmp_path)

        # Patch the memory instances used by the confirm view
        patcher_supplier = patch(
            "scanner.views._get_supplier_memory", return_value=self.supplier_mem
        )
        patcher_general = patch(
            "scanner.views._get_general_memory", return_value=self.general_mem
        )
        self.mock_sup = patcher_supplier.start()
        self.mock_gen = patcher_general.start()
        self.addCleanup(patcher_supplier.stop)
        self.addCleanup(patcher_general.stop)

    def _make_payload(self, supplier="Sysco Foods", corrections=None):
        return {
            "scan_result": {
                "supplier": supplier,
                "date": "2026-01-01",
                "invoice_number": "INV-001",
                "items": [
                    {"name": "Chicken Breast", "unit_price": 4.00, "unit": "lb", "quantity": 10},
                ],
                "subtotal": 40.0,
                "tax": 3.20,
                "total": 43.20,
                "tax_rate": 0.08,
                "confidence": {},
                "inference_sources": {},
                "scan_metadata": {"mode": "normal"},
            },
            "corrections": corrections or [],
            "confirmed_at": "2026-03-27T12:00:00Z",
        }

    def test_confirm_saves_corrected_values_to_supplier_memory(self):
        payload = self._make_payload(corrections=[
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
            {"field": "items[0].unit_price", "original_value": 4.00, "corrected_value": 4.99},
        ])
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 200)

        profile = self.supplier_mem.get_profile("sysco-foods")
        self.assertEqual(profile["scan_count"], 1)
        self.assertEqual(profile["latest_values"]["supplier"], "Sysco Foods")
        # Item should have corrected price
        self.assertEqual(profile["item_history"]["Chicken Breast"]["avg_price"], 4.99)

    def test_confirm_saves_error_categories_in_corrections(self):
        payload = self._make_payload(corrections=[
            {"field": "supplier", "original_value": "Sysco Fods", "corrected_value": "Sysco Foods"},
            {"field": "date", "original_value": None, "corrected_value": "2026-01-01"},
        ])
        self.client.post("/api/confirm/", payload, format="json")

        profile = self.supplier_mem.get_profile("sysco-foods")
        stored_corrections = profile["corrections"]
        self.assertEqual(len(stored_corrections), 2)
        self.assertEqual(stored_corrections[0]["error_type"], "misread")
        self.assertEqual(stored_corrections[1]["error_type"], "missing")

    def test_confirm_updates_general_memory(self):
        payload = self._make_payload()
        self.client.post("/api/confirm/", payload, format="json")

        catalog = self.general_mem.get_item_catalog()
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_no_corrections_still_saves_to_memory(self):
        payload = self._make_payload(corrections=[])
        self.client.post("/api/confirm/", payload, format="json")

        profile = self.supplier_mem.get_profile("sysco-foods")
        self.assertEqual(profile["scan_count"], 1)

    def test_confirm_empty_supplier_skips_supplier_memory(self):
        payload = self._make_payload(supplier="", corrections=[])
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 200)
        # General memory should still be updated
        catalog = self.general_mem.get_item_catalog()
        self.assertIn("Chicken Breast", catalog["items"])

    def test_confirm_none_supplier_skips_supplier_memory(self):
        payload = self._make_payload(supplier=None, corrections=[])
        # supplier=None in scan_result
        payload["scan_result"]["supplier"] = None
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 200)

    def test_confirm_deleted_row_removes_item_before_saving(self):
        payload = self._make_payload(corrections=[
            {"field": "items[0]", "original_value": {"name": "Chicken Breast"}, "corrected_value": "deleted_row"},
        ])
        response = self.client.post("/api/confirm/", payload, format="json")
        self.assertEqual(response.status_code, 200)

        profile = self.supplier_mem.get_profile("sysco-foods")
        # Deleted item should not be in item_history
        self.assertEqual(profile["item_history"], {})

    def test_confirm_response_includes_memory_updated_flag(self):
        payload = self._make_payload()
        response = self.client.post("/api/confirm/", payload, format="json")
        data = response.json()
        self.assertTrue(data["memory_updated"])
```

**Test command:** `cd backend && python -m pytest tests/test_api.py::TestConfirmUpdatesMemory -v`

**Expected:** All tests FAIL (view not wired yet, `_get_supplier_memory` etc. don't exist).

---

### Task 7: Wire Confirm Endpoint to Memory - Implementation

**File:** `backend/scanner/views.py`

Replace the full file content with:

```python
import logging

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status

from scanner.serializers import ScanRequestSerializer, ConfirmRequestSerializer
from scanner.scanning.engine import scan_invoice
from scanner.memory import (
    JsonSupplierMemory,
    JsonGeneralMemory,
    normalize_supplier_id,
    categorize_corrections,
    apply_corrections,
)

logger = logging.getLogger(__name__)


def _get_supplier_memory() -> JsonSupplierMemory:
    """Factory for supplier memory (patchable in tests)."""
    return JsonSupplierMemory()


def _get_general_memory() -> JsonGeneralMemory:
    """Factory for general memory (patchable in tests)."""
    return JsonGeneralMemory()


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def scan_invoice_view(request):
    serializer = ScanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mode = serializer.validated_data.get("mode", "normal")
    debug = request.query_params.get("debug", "").lower() in ("1", "true")
    image_file = serializer.validated_data["image"]

    try:
        image_bytes = image_file.read()
        result = scan_invoice(image_bytes, mode=mode, debug=debug)

        # If the engine returned an error, still return 200 with error in metadata
        # so the frontend can display partial results or error info
        return Response(result)

    except Exception as e:
        logger.error("Unexpected error in scan endpoint: %s", e, exc_info=True)
        return Response(
            {"error": "Internal server error during scan."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@parser_classes([JSONParser])
def confirm_scan_view(request):
    serializer = ConfirmRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated = serializer.validated_data
    scan_result = validated["scan_result"]
    corrections_raw = validated["corrections"]
    corrections_count = len(corrections_raw)
    confirmed_at = validated["confirmed_at"].isoformat()

    logger.info(
        "Scan confirmed with %d correction(s) at %s",
        corrections_count,
        confirmed_at,
    )

    # Convert OrderedDicts from serializer to plain dicts
    corrections = [dict(c) for c in corrections_raw]

    # 1. Apply corrections to get the canonical "truth" scan data
    corrected_scan = apply_corrections(scan_result, corrections)

    # 2. Categorize errors
    categorized = categorize_corrections(corrections)

    # 3. Attach categorized corrections to the scan data for memory storage
    corrected_scan["corrections"] = categorized

    # 4. Save to memory stores
    memory_updated = False
    supplier_name = corrected_scan.get("supplier")

    general_mem = _get_general_memory()
    supplier_mem = _get_supplier_memory()

    # Always update general memory
    try:
        general_mem.update_from_scan(corrected_scan)
        memory_updated = True
    except Exception as e:
        logger.error("Failed to update general memory: %s", e, exc_info=True)

    # Update supplier memory only if supplier is known
    if supplier_name and str(supplier_name).strip():
        try:
            supplier_id = normalize_supplier_id(str(supplier_name))
            supplier_mem.save_scan(supplier_id, corrected_scan)
            memory_updated = True
        except ValueError as e:
            logger.warning("Skipping supplier memory (invalid name): %s", e)
        except Exception as e:
            logger.error("Failed to update supplier memory: %s", e, exc_info=True)

    return Response({
        "status": "confirmed",
        "corrections_count": corrections_count,
        "confirmed_at": confirmed_at,
        "memory_updated": memory_updated,
    })
```

**Test command:** `cd backend && python -m pytest tests/test_api.py -v`

**Expected:** All tests PASS (old tests + new memory integration tests).

**Commit:** `"Wire confirm endpoint to memory with error categorization (Phase 14)"`

---

### Task 8: Full Test Suite Verification

Run the complete backend test suite to verify nothing is broken.

**Test command:** `cd backend && python -m pytest tests/ -v`

**Expected:** All tests PASS.

**Commit (if any fixups needed):** `"Fix test issues from Phase 14 integration"`

---

## Verification

```bash
cd backend && python -m pytest tests/test_categorizer.py tests/test_corrections.py tests/test_api.py tests/test_memory.py -v
```

All tests green confirms:
- Error categorizer correctly classifies misread/missing/hallucinated
- Corrections are correctly applied to scan data (header fields, item fields, row deletions)
- Confirm endpoint saves corrected data + error categories to supplier memory
- Confirm endpoint saves corrected data to general memory
- Empty/unknown supplier names are handled gracefully
- Existing API and memory tests remain unbroken
