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
