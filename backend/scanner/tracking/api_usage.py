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
