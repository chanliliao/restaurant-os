# Phase 16: Batch Upload, Tabs, Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** Multi-image upload with tabbed results, per-scan stats, accuracy dashboard

**Architecture:** Backend tracking stores per-scan stats in JSON files using the existing `_file_lock` pattern from `json_store.py`. Stats endpoint aggregates accuracy + API usage. Frontend manages an array of scan results, renders tabs for each, fetches dashboard data on demand.

**Tech Stack:** React 19, TypeScript, Django REST Framework, JSON file storage

**Python path:** `/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe`

---

## Task 1: Tests for accuracy tracker

**File:** `backend/scanner/tracking/test_accuracy.py`

**Test commands:**
```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/Restaurant OS/backend
/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test scanner.tracking.test_accuracy -v2
```

**Code:**
```python
"""Tests for accuracy tracking."""

import json
import os
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from scanner.tracking.accuracy import record_scan_accuracy, get_accuracy_stats


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
```

---

## Task 2: Implement accuracy tracker

**File:** `backend/scanner/tracking/accuracy.py`

**Code:**
```python
"""Accuracy tracking for scan results."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

_lock = threading.Lock()


def _get_accuracy_path() -> str:
    """Return path to accuracy stats JSON file."""
    stats_dir = Path(settings.BASE_DIR).parent / "data" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    return str(stats_dir / "accuracy.json")


def _read_accuracy_data(path: str) -> dict:
    """Read accuracy data from file, return empty structure if missing."""
    if not os.path.exists(path):
        return {"scans": []}
    with open(path, "r") as f:
        return json.load(f)


def _write_accuracy_data(path: str, data: dict) -> None:
    """Atomic write of accuracy data."""
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def record_scan_accuracy(
    scan_id: str,
    mode: str,
    supplier_id: str,
    total_fields: int,
    corrections_count: int,
) -> None:
    """Record accuracy for a single confirmed scan."""
    accuracy = (
        (total_fields - corrections_count) / total_fields
        if total_fields > 0
        else 0
    )
    entry = {
        "scan_id": scan_id,
        "mode": mode,
        "supplier_id": supplier_id,
        "total_fields": total_fields,
        "corrections_count": corrections_count,
        "accuracy": round(accuracy, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = _get_accuracy_path()
    with _lock:
        data = _read_accuracy_data(path)
        data["scans"].append(entry)
        _write_accuracy_data(path, data)


def get_accuracy_stats() -> dict:
    """Aggregate accuracy statistics."""
    path = _get_accuracy_path()
    with _lock:
        data = _read_accuracy_data(path)

    scans = data.get("scans", [])
    if not scans:
        return {
            "total_scans": 0,
            "average_accuracy": 0,
            "total_corrections": 0,
            "by_mode": {},
            "by_supplier": {},
        }

    total = len(scans)
    avg = sum(s["accuracy"] for s in scans) / total
    total_corrections = sum(s["corrections_count"] for s in scans)

    by_mode: dict = {}
    for s in scans:
        m = s["mode"]
        if m not in by_mode:
            by_mode[m] = {"count": 0, "total_accuracy": 0}
        by_mode[m]["count"] += 1
        by_mode[m]["total_accuracy"] += s["accuracy"]
    for m in by_mode:
        by_mode[m]["average_accuracy"] = round(
            by_mode[m]["total_accuracy"] / by_mode[m]["count"], 4
        )
        del by_mode[m]["total_accuracy"]

    by_supplier: dict = {}
    for s in scans:
        sup = s["supplier_id"]
        if sup not in by_supplier:
            by_supplier[sup] = {"count": 0, "total_accuracy": 0}
        by_supplier[sup]["count"] += 1
        by_supplier[sup]["total_accuracy"] += s["accuracy"]
    for sup in by_supplier:
        by_supplier[sup]["average_accuracy"] = round(
            by_supplier[sup]["total_accuracy"] / by_supplier[sup]["count"], 4
        )
        del by_supplier[sup]["total_accuracy"]

    return {
        "total_scans": total,
        "average_accuracy": round(avg, 4),
        "total_corrections": total_corrections,
        "by_mode": by_mode,
        "by_supplier": by_supplier,
    }
```

Also update `backend/scanner/tracking/__init__.py`:
```python
from .accuracy import record_scan_accuracy, get_accuracy_stats
from .api_usage import record_api_usage, get_usage_stats
```

**Verification:** Run Task 1 tests, all 5 pass.

---

## Task 3: Tests for API usage tracker

**File:** `backend/scanner/tracking/test_api_usage.py`

**Code:**
```python
"""Tests for API usage tracking."""

import json
import os
import tempfile
from unittest import mock

from django.test import TestCase

from scanner.tracking.api_usage import record_api_usage, get_usage_stats


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
```

---

## Task 4: Implement API usage tracker

**File:** `backend/scanner/tracking/api_usage.py`

**Code:**
```python
"""API usage tracking for scan operations."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

_lock = threading.Lock()


def _get_usage_path() -> str:
    """Return path to API usage stats JSON file."""
    stats_dir = Path(settings.BASE_DIR).parent / "data" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    return str(stats_dir / "api_usage.json")


def _read_usage_data(path: str) -> dict:
    if not os.path.exists(path):
        return {"entries": []}
    with open(path, "r") as f:
        return json.load(f)


def _write_usage_data(path: str, data: dict) -> None:
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def record_api_usage(scan_id: str, mode: str, api_calls: dict) -> None:
    """Record API usage for a single scan."""
    entry = {
        "scan_id": scan_id,
        "mode": mode,
        "api_calls": api_calls,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = _get_usage_path()
    with _lock:
        data = _read_usage_data(path)
        data["entries"].append(entry)
        _write_usage_data(path, data)


def get_usage_stats() -> dict:
    """Aggregate API usage statistics."""
    path = _get_usage_path()
    with _lock:
        data = _read_usage_data(path)

    entries = data.get("entries", [])
    if not entries:
        return {"total_scans": 0, "totals": {}, "by_mode": {}}

    # Sum all numeric keys across api_calls dicts
    totals: dict = {}
    by_mode: dict = {}
    for e in entries:
        m = e["mode"]
        if m not in by_mode:
            by_mode[m] = {"count": 0, "totals": {}}
        by_mode[m]["count"] += 1
        for key, val in e["api_calls"].items():
            if isinstance(val, (int, float)):
                totals[key] = totals.get(key, 0) + val
                by_mode[m]["totals"][key] = by_mode[m]["totals"].get(key, 0) + val

    return {
        "total_scans": len(entries),
        "totals": totals,
        "by_mode": by_mode,
    }
```

**Verification:** Run Task 3 tests, all 3 pass.

---

## Task 5: Tests for stats endpoint + wiring into confirm

**File:** `backend/scanner/tracking/test_stats_endpoint.py`

**Code:**
```python
"""Tests for GET /api/stats/ endpoint and tracking wiring in confirm."""

import json
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient


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
```

---

## Task 6: Implement stats endpoint + wire tracking into confirm

### 6a. Add stats view to `backend/scanner/views.py`

Add imports at top:
```python
from scanner.tracking.accuracy import record_scan_accuracy, get_accuracy_stats
from scanner.tracking.api_usage import record_api_usage, get_usage_stats
```

Add new view at bottom of file:
```python
@api_view(["GET"])
def stats_view(request):
    """Return combined accuracy and API usage statistics."""
    return Response({
        "accuracy": get_accuracy_stats(),
        "api_usage": get_usage_stats(),
    })
```

### 6b. Wire tracking into `confirm_scan_view`

After the `return Response(...)` block in `confirm_scan_view`, move the return and add tracking before it. Insert before the final `return Response({...})`:

```python
    # --- Tracking ---
    scan_metadata = scan_result.get("scan_metadata", {})
    mode = scan_metadata.get("mode", "normal")
    supplier_id_for_tracking = ""
    if supplier_name and isinstance(supplier_name, str) and supplier_name.strip():
        try:
            supplier_id_for_tracking = normalize_supplier_id(supplier_name)
        except ValueError:
            supplier_id_for_tracking = "unknown"

    # Count total editable fields: header fields + item fields
    header_fields = ["supplier", "date", "invoice_number", "subtotal", "tax", "total"]
    items = scan_result.get("items", [])
    item_fields_per_row = ["name", "quantity", "unit", "unit_price", "total"]
    total_fields = len(header_fields) + len(items) * len(item_fields_per_row)

    import uuid
    scan_id = str(uuid.uuid4())[:8]

    try:
        record_scan_accuracy(
            scan_id=scan_id,
            mode=mode,
            supplier_id=supplier_id_for_tracking,
            total_fields=total_fields,
            corrections_count=corrections_count,
        )
        record_api_usage(
            scan_id=scan_id,
            mode=mode,
            api_calls={
                "api_calls": scan_metadata.get("api_calls", 0),
                "scans_performed": scan_metadata.get("scans_performed", 0),
                "models_used": scan_metadata.get("models_used", []),
            },
        )
    except Exception:
        logger.warning("Failed to record tracking data", exc_info=True)
```

Note: Move `import uuid` to the top-level imports instead.

### 6c. Add route to `backend/scanner/urls.py`

```python
from django.urls import path
from scanner.views import scan_invoice_view, confirm_scan_view, stats_view

urlpatterns = [
    path("scan/", scan_invoice_view, name="scan-invoice"),
    path("confirm/", confirm_scan_view, name="confirm-scan"),
    path("stats/", stats_view, name="stats"),
]
```

**Verification:** Run Task 5 tests, all 3 pass. Then run full backend suite:
```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/Restaurant OS/backend
/c/Users/cliao/AppData/Local/Programs/Python/Python313/python.exe manage.py test scanner -v2
```

---

## Task 7: Update types with StatsResponse and multi-scan types

**File:** `frontend/src/types/scan.ts`

Add at the end of the existing file:

```typescript
/** A single scan result paired with its source file name */
export interface ScanTab {
  id: string;
  fileName: string;
  status: "scanning" | "done" | "error";
  result: ScanResponse | null;
  error: string | null;
  confirmed: boolean;
}

/** Accuracy stats from backend */
export interface AccuracyStats {
  total_scans: number;
  average_accuracy: number;
  total_corrections: number;
  by_mode: Record<string, { count: number; average_accuracy: number }>;
  by_supplier: Record<string, { count: number; average_accuracy: number }>;
}

/** API usage stats from backend */
export interface ApiUsageStats {
  total_scans: number;
  totals: Record<string, number>;
  by_mode: Record<string, { count: number; totals: Record<string, number> }>;
}

/** Combined stats response from GET /api/stats/ */
export interface StatsResponse {
  accuracy: AccuracyStats;
  api_usage: ApiUsageStats;
}
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 8: Update api.ts with getStats()

**File:** `frontend/src/services/api.ts`

Add import of `StatsResponse` to the existing import line:
```typescript
import type { ScanMode, ScanResponse, ConfirmRequest, ConfirmResponse, StatsResponse } from "../types/scan.ts";
```

Add at the end of the file:
```typescript
/**
 * Fetch aggregated scan statistics from the backend.
 */
export async function getStats(): Promise<StatsResponse> {
  const response = await client.get<StatsResponse>("/stats/");
  return response.data;
}
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 9: Update DropZone.tsx for multiple files

**File:** `frontend/src/components/DropZone.tsx`

**Changes:**

1. Change the prop interface:
```typescript
interface DropZoneProps {
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
}
```

2. Update the component signature:
```typescript
export default function DropZone({ onFilesSelected, disabled = false }: DropZoneProps) {
```

3. Replace `validateAndSelect` to handle multiple files:
```typescript
  const validateAndSelect = useCallback(
    (fileList: FileList) => {
      setError(null);
      const valid: File[] = [];
      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i];
        if (!ACCEPTED_TYPES.includes(file.type)) {
          setError(
            `Skipped "${file.name}": invalid type. Accepts JPEG, PNG, WebP, TIFF, BMP.`
          );
          continue;
        }
        if (file.size > 20 * 1024 * 1024) {
          setError(`Skipped "${file.name}": exceeds 20 MB limit.`);
          continue;
        }
        valid.push(file);
      }
      if (valid.length > 0) {
        onFilesSelected(valid);
      }
    },
    [onFilesSelected]
  );
```

4. Update `handleDrop`:
```typescript
      if (files.length > 0) {
        validateAndSelect(files);
      }
```

5. Update `handleFileInput`:
```typescript
      if (files && files.length > 0) {
        validateAndSelect(files);
      }
```

6. Add `multiple` to the hidden input:
```html
<input
  ref={fileInputRef}
  type="file"
  accept={ACCEPTED_TYPES.join(",")}
  multiple
  onChange={handleFileInput}
  style={{ display: "none" }}
  aria-hidden="true"
/>
```

7. Update hint text:
```html
<p className="dropzone__text">
  {disabled
    ? "Scanning..."
    : "Drag and drop invoice images here, or click to browse"}
</p>
<p className="dropzone__hint">
  Supports JPEG, PNG, WebP, TIFF, BMP (max 20 MB each) - multiple files OK
</p>
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 10: Create ScanStats.tsx

**File:** `frontend/src/components/ScanStats.tsx`

**Code:**
```tsx
import type { ScanResponse } from "../types/scan.ts";

interface ScanStatsProps {
  result: ScanResponse;
}

export default function ScanStats({ result }: ScanStatsProps) {
  const meta = result.scan_metadata;

  return (
    <div className="scan-stats">
      <h4 className="scan-stats__title">Scan Metadata</h4>
      <dl className="scan-stats__list">
        <div className="scan-stats__item">
          <dt>Mode</dt>
          <dd>{meta.mode}</dd>
        </div>
        <div className="scan-stats__item">
          <dt>API Calls</dt>
          <dd>{meta.api_calls}</dd>
        </div>
        <div className="scan-stats__item">
          <dt>Scans Performed</dt>
          <dd>{meta.scans_performed}</dd>
        </div>
        <div className="scan-stats__item">
          <dt>Models Used</dt>
          <dd>{meta.models_used.join(", ")}</dd>
        </div>
        {meta.tiebreaker_triggered && (
          <div className="scan-stats__item">
            <dt>Tiebreaker</dt>
            <dd>Triggered</dd>
          </div>
        )}
        {meta.math_validation_triggered && (
          <div className="scan-stats__item">
            <dt>Math Validation</dt>
            <dd>Triggered</dd>
          </div>
        )}
      </dl>
    </div>
  );
}
```

Add to `frontend/src/styles/app.css`:
```css
/* --- ScanStats --- */

.scan-stats {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary, #f8f9fa);
  border-radius: 6px;
  border: 1px solid var(--border, #e0e0e0);
}

.scan-stats__title {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #6c757d);
}

.scan-stats__list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
  margin: 0;
}

.scan-stats__item {
  display: flex;
  gap: 0.35rem;
}

.scan-stats__item dt {
  font-weight: 600;
  font-size: 0.85rem;
}

.scan-stats__item dd {
  margin: 0;
  font-size: 0.85rem;
}
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 11: Create ResultTabs.tsx

**File:** `frontend/src/components/ResultTabs.tsx`

**Code:**
```tsx
import type { ScanTab } from "../types/scan.ts";

interface ResultTabsProps {
  tabs: ScanTab[];
  activeTabId: string | null;
  onTabSelect: (id: string) => void;
}

export default function ResultTabs({ tabs, activeTabId, onTabSelect }: ResultTabsProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="result-tabs" role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        const statusClass =
          tab.status === "scanning"
            ? "result-tabs__tab--scanning"
            : tab.status === "error"
            ? "result-tabs__tab--error"
            : tab.confirmed
            ? "result-tabs__tab--confirmed"
            : "result-tabs__tab--done";

        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            className={`result-tabs__tab ${statusClass} ${
              isActive ? "result-tabs__tab--active" : ""
            }`}
            onClick={() => onTabSelect(tab.id)}
          >
            <span className="result-tabs__name">{tab.fileName}</span>
            {tab.status === "scanning" && (
              <span className="result-tabs__badge">...</span>
            )}
            {tab.confirmed && (
              <span className="result-tabs__badge result-tabs__badge--ok">OK</span>
            )}
            {tab.status === "error" && (
              <span className="result-tabs__badge result-tabs__badge--err">!</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
```

Add to `frontend/src/styles/app.css`:
```css
/* --- ResultTabs --- */

.result-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 2px solid var(--border, #e0e0e0);
  margin-bottom: 1rem;
  overflow-x: auto;
}

.result-tabs__tab {
  padding: 0.5rem 1rem;
  border: 1px solid var(--border, #e0e0e0);
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  background: var(--bg-secondary, #f8f9fa);
  cursor: pointer;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  white-space: nowrap;
}

.result-tabs__tab--active {
  background: white;
  border-bottom: 2px solid white;
  margin-bottom: -2px;
  font-weight: 600;
}

.result-tabs__tab--scanning {
  opacity: 0.6;
}

.result-tabs__tab--confirmed {
  border-color: var(--success, #28a745);
}

.result-tabs__tab--error {
  border-color: var(--danger, #dc3545);
}

.result-tabs__name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-tabs__badge {
  font-size: 0.7rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--bg-secondary, #e0e0e0);
}

.result-tabs__badge--ok {
  background: var(--success, #28a745);
  color: white;
}

.result-tabs__badge--err {
  background: var(--danger, #dc3545);
  color: white;
}
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 12: Create Dashboard.tsx

**File:** `frontend/src/components/Dashboard.tsx`

**Code:**
```tsx
import { useState, useEffect } from "react";
import { getStats } from "../services/api.ts";
import type { StatsResponse } from "../types/scan.ts";

export default function Dashboard() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getStats()
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load stats");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p className="dashboard__loading">Loading stats...</p>;
  if (error) return <p className="dashboard__error">Error: {error}</p>;
  if (!stats) return null;

  const { accuracy, api_usage } = stats;

  return (
    <div className="dashboard">
      <h2 className="dashboard__title">Dashboard</h2>

      <div className="dashboard__grid">
        <div className="dashboard__card">
          <h3>Accuracy</h3>
          <p className="dashboard__big-number">
            {(accuracy.average_accuracy * 100).toFixed(1)}%
          </p>
          <p className="dashboard__detail">
            {accuracy.total_scans} scans, {accuracy.total_corrections} corrections
          </p>
        </div>

        <div className="dashboard__card">
          <h3>API Usage</h3>
          <p className="dashboard__big-number">
            {api_usage.totals.api_calls ?? 0}
          </p>
          <p className="dashboard__detail">total API calls</p>
        </div>
      </div>

      {Object.keys(accuracy.by_mode).length > 0 && (
        <div className="dashboard__section">
          <h3>Accuracy by Mode</h3>
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>Mode</th>
                <th>Scans</th>
                <th>Avg Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(accuracy.by_mode).map(([mode, data]) => (
                <tr key={mode}>
                  <td>{mode}</td>
                  <td>{data.count}</td>
                  <td>{(data.average_accuracy * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(accuracy.by_supplier).length > 0 && (
        <div className="dashboard__section">
          <h3>Accuracy by Supplier</h3>
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Scans</th>
                <th>Avg Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(accuracy.by_supplier).map(([sup, data]) => (
                <tr key={sup}>
                  <td>{sup}</td>
                  <td>{data.count}</td>
                  <td>{(data.average_accuracy * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

Add to `frontend/src/styles/app.css`:
```css
/* --- Dashboard --- */

.dashboard {
  max-width: 700px;
  margin: 0 auto;
}

.dashboard__title {
  margin-bottom: 1rem;
}

.dashboard__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.dashboard__card {
  padding: 1.25rem;
  border: 1px solid var(--border, #e0e0e0);
  border-radius: 8px;
  background: var(--bg-secondary, #f8f9fa);
  text-align: center;
}

.dashboard__card h3 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  text-transform: uppercase;
  color: var(--text-muted, #6c757d);
}

.dashboard__big-number {
  font-size: 2rem;
  font-weight: 700;
  margin: 0;
}

.dashboard__detail {
  font-size: 0.8rem;
  color: var(--text-muted, #6c757d);
  margin: 0.25rem 0 0;
}

.dashboard__section {
  margin-bottom: 1.5rem;
}

.dashboard__section h3 {
  margin-bottom: 0.5rem;
}

.dashboard__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.dashboard__table th,
.dashboard__table td {
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid var(--border, #e0e0e0);
  text-align: left;
}

.dashboard__table th {
  font-weight: 600;
  background: var(--bg-secondary, #f8f9fa);
}

.dashboard__loading,
.dashboard__error {
  text-align: center;
  padding: 2rem;
}

.dashboard__error {
  color: var(--danger, #dc3545);
}
```

**Verification:** `npx tsc --noEmit` passes.

---

## Task 13: Update App.tsx for multi-scan flow + dashboard

**File:** `frontend/src/App.tsx`

**Full replacement** -- this is the most complex change, replacing single-scan state with multi-scan tab state.

**Key changes:**
- Replace single `result`/`fileName`/`confirmed` state with `tabs: ScanTab[]` and `activeTabId: string`
- Add `showDashboard: boolean` state with toggle button in header
- `handleFilesSelected(files: File[])` creates a tab per file, scans each sequentially
- Render `ResultTabs` above the result area
- Render active tab's content (InvoiceForm + ItemsTable + ScanStats) or Dashboard
- Corrections refs become a `Map<string, { header: FieldCorrection[], items: FieldCorrection[] }>`

**Code:**
```tsx
import { useState, useCallback, useRef } from "react";
import DropZone from "./components/DropZone.tsx";
import ScanControls from "./components/ScanControls.tsx";
import InvoiceForm from "./components/InvoiceForm.tsx";
import ItemsTable from "./components/ItemsTable.tsx";
import ResultTabs from "./components/ResultTabs.tsx";
import ScanStats from "./components/ScanStats.tsx";
import Dashboard from "./components/Dashboard.tsx";
import { scanInvoice, confirmScan } from "./services/api.ts";
import type { ScanMode, ScanResponse, ScanTab, FieldCorrection } from "./types/scan.ts";
import "./styles/app.css";

let nextId = 1;
function makeTabId(): string {
  return `tab-${nextId++}`;
}

export default function App() {
  const [mode, setMode] = useState<ScanMode>("normal");
  const [debug, setDebug] = useState(false);
  const [tabs, setTabs] = useState<ScanTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);

  // Per-tab corrections: Map<tabId, { header, items }>
  const correctionsMap = useRef<
    Map<string, { header: FieldCorrection[]; items: FieldCorrection[] }>
  >(new Map());

  const handleFilesSelected = useCallback(
    async (files: File[]) => {
      setShowDashboard(false);

      // Create tab entries for each file
      const newTabs: ScanTab[] = files.map((file) => ({
        id: makeTabId(),
        fileName: file.name,
        status: "scanning" as const,
        result: null,
        error: null,
        confirmed: false,
      }));

      setTabs((prev) => [...prev, ...newTabs]);
      setActiveTabId(newTabs[0].id);
      setScanning(true);

      // Scan files sequentially to avoid API overload
      for (let i = 0; i < files.length; i++) {
        const tab = newTabs[i];
        correctionsMap.current.set(tab.id, { header: [], items: [] });

        try {
          const result = await scanInvoice(files[i], mode, debug);
          setTabs((prev) =>
            prev.map((t) =>
              t.id === tab.id ? { ...t, status: "done" as const, result } : t
            )
          );
        } catch (err: unknown) {
          const message =
            err instanceof Error ? err.message : "Unexpected error";
          setTabs((prev) =>
            prev.map((t) =>
              t.id === tab.id
                ? { ...t, status: "error" as const, error: message }
                : t
            )
          );
        }
      }

      setScanning(false);
    },
    [mode, debug]
  );

  const handleHeaderCorrections = useCallback(
    (corrections: FieldCorrection[]) => {
      if (!activeTabId) return;
      const entry = correctionsMap.current.get(activeTabId);
      if (entry) entry.header = corrections;
    },
    [activeTabId]
  );

  const handleItemCorrections = useCallback(
    (corrections: FieldCorrection[]) => {
      if (!activeTabId) return;
      const entry = correctionsMap.current.get(activeTabId);
      if (entry) entry.items = corrections;
    },
    [activeTabId]
  );

  const handleConfirm = useCallback(async () => {
    const tab = tabs.find((t) => t.id === activeTabId);
    if (!tab || !tab.result) return;

    const entry = correctionsMap.current.get(tab.id);
    const allCorrections = [
      ...(entry?.header ?? []),
      ...(entry?.items ?? []),
    ];

    // Optimistic UI: mark as confirming (reuse scanning status briefly)
    setTabs((prev) =>
      prev.map((t) => (t.id === tab.id ? { ...t, status: "scanning" as const } : t))
    );

    try {
      await confirmScan({
        scan_result: tab.result,
        corrections: allCorrections,
        confirmed_at: new Date().toISOString(),
      });
      setTabs((prev) =>
        prev.map((t) =>
          t.id === tab.id
            ? { ...t, status: "done" as const, confirmed: true }
            : t
        )
      );
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Unexpected error";
      setTabs((prev) =>
        prev.map((t) =>
          t.id === tab.id
            ? { ...t, status: "error" as const, error: message }
            : t
        )
      );
    }
  }, [tabs, activeTabId]);

  const activeTab = tabs.find((t) => t.id === activeTabId) ?? null;

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Restaurant OS</h1>
        <p className="app__subtitle">AI-powered restaurant invoice scanner</p>
        <button
          type="button"
          className="app__dashboard-toggle"
          onClick={() => setShowDashboard((v) => !v)}
        >
          {showDashboard ? "Back to Scanner" : "Dashboard"}
        </button>
      </header>

      <main className="app__main">
        {showDashboard ? (
          <Dashboard />
        ) : (
          <>
            <ScanControls
              mode={mode}
              onModeChange={setMode}
              debug={debug}
              onDebugChange={setDebug}
              disabled={scanning}
            />

            <DropZone onFilesSelected={handleFilesSelected} disabled={scanning} />

            <ResultTabs
              tabs={tabs}
              activeTabId={activeTabId}
              onTabSelect={setActiveTabId}
            />

            {activeTab?.status === "scanning" && (
              <div className="app__status">
                <p className="app__loading">Scanning {activeTab.fileName}...</p>
              </div>
            )}

            {activeTab?.status === "error" && (
              <div className="app__status">
                <p className="app__error">Error: {activeTab.error}</p>
              </div>
            )}

            {activeTab?.result && !activeTab.confirmed && (
              <div className="app__result">
                <h2 className="app__result-title">
                  Scan Result ({activeTab.fileName})
                </h2>

                <ScanStats result={activeTab.result} />

                <div className="app__result-body">
                  <div className="app__legend">
                    <span className="legend-item field--low-confidence">
                      Low confidence
                    </span>
                    <span className="legend-item field--inferred">Inferred</span>
                    <span className="legend-item field--changed">Edited</span>
                  </div>

                  <InvoiceForm
                    scanResult={activeTab.result}
                    onCorrectionsChange={handleHeaderCorrections}
                  />

                  <ItemsTable
                    items={activeTab.result.items}
                    onCorrectionsChange={handleItemCorrections}
                  />

                  <div className="app__actions">
                    <button
                      type="button"
                      className="app__confirm-btn"
                      onClick={handleConfirm}
                    >
                      Confirm All
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeTab?.confirmed && (
              <div className="app__status app__status--success">
                <p className="app__success">
                  {activeTab.fileName} confirmed successfully.
                </p>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
```

Add to `frontend/src/styles/app.css`:
```css
/* --- Dashboard Toggle --- */

.app__dashboard-toggle {
  position: absolute;
  top: 1rem;
  right: 1.5rem;
  padding: 0.4rem 1rem;
  border: 1px solid var(--border, #e0e0e0);
  border-radius: 6px;
  background: white;
  cursor: pointer;
  font-size: 0.85rem;
}

.app__dashboard-toggle:hover {
  background: var(--bg-secondary, #f8f9fa);
}
```

Also ensure `app__header` has `position: relative`:
```css
.app__header {
  position: relative;
  /* ... existing styles ... */
}
```

**Verification:**
```bash
cd /c/Users/cliao/Desktop/Coding/Claude\ Projects/Restaurant OS/frontend
npx tsc --noEmit
```

---

## Execution Order

```
Backend (TDD):
  Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6

Frontend (sequential, each builds on prior):
  Task 7 -> Task 8 -> Task 9 -> Task 10 -> Task 11 -> Task 12 -> Task 13
```

Tasks 1-6 and Tasks 7-8 are independent and could run in parallel via subagents. Tasks 9-13 are sequential.

## Files Changed Summary

| File | Action |
|------|--------|
| `backend/scanner/tracking/__init__.py` | Edit: add imports |
| `backend/scanner/tracking/accuracy.py` | Create |
| `backend/scanner/tracking/api_usage.py` | Create |
| `backend/scanner/tracking/test_accuracy.py` | Create |
| `backend/scanner/tracking/test_api_usage.py` | Create |
| `backend/scanner/tracking/test_stats_endpoint.py` | Create |
| `backend/scanner/views.py` | Edit: add imports, tracking wiring, stats view |
| `backend/scanner/urls.py` | Edit: add stats route |
| `frontend/src/types/scan.ts` | Edit: add ScanTab, StatsResponse types |
| `frontend/src/services/api.ts` | Edit: add getStats() |
| `frontend/src/components/DropZone.tsx` | Edit: multi-file support |
| `frontend/src/components/ScanStats.tsx` | Create |
| `frontend/src/components/ResultTabs.tsx` | Create |
| `frontend/src/components/Dashboard.tsx` | Create |
| `frontend/src/App.tsx` | Rewrite: multi-scan + tabs + dashboard |
| `frontend/src/styles/app.css` | Edit: add new component styles |
