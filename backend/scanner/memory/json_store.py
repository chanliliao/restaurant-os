"""JSON file implementations for SmartScanner memory interfaces."""

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from django.conf import settings

from .interface import GeneralMemory, SupplierMemory

# Module-level lock for thread-safe file operations within a single process.
# NOTE: This does not protect against multi-process concurrency (e.g., Gunicorn
# workers). For production, switch to SQLite or use OS-level file locks.
_file_lock = threading.Lock()


def normalize_supplier_id(name: str) -> str:
    """Normalize a supplier name into a safe directory-friendly ID.

    - Lowercase
    - Spaces become hyphens
    - Strip all characters except alphanumeric and hyphens
    - Reject path traversal attempts
    """
    if not name or not name.strip():
        raise ValueError("Supplier name cannot be empty")

    # Reject any path traversal characters before normalization
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid supplier name: {name!r}")

    normalized = name.lower().strip()
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9\-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")

    # After stripping, must still have content
    if not normalized:
        raise ValueError(f"Supplier name normalizes to empty string: {name!r}")

    return normalized


def _validate_supplier_id(supplier_id: str) -> None:
    """Validate that a supplier_id is safe for use as a directory name."""
    if not supplier_id:
        raise ValueError("Supplier ID cannot be empty")
    if ".." in supplier_id or "/" in supplier_id or "\\" in supplier_id:
        raise ValueError(f"Invalid supplier ID: {supplier_id!r}")
    if not re.match(r"^[a-z0-9\-]+$", supplier_id):
        raise ValueError(f"Invalid supplier ID format: {supplier_id!r}")


def _read_json(path: Path) -> dict:
    """Read a JSON file, returning empty dict on missing or corrupt files."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomically write JSON data to a file using temp-file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".json_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # On Windows, os.replace is atomic within the same volume
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _get_data_dir() -> Path:
    """Get the DATA_DIR from Django settings."""
    return Path(settings.DATA_DIR)


class JsonSupplierMemory(SupplierMemory):
    """JSON file-based supplier memory storage.

    Stores per-supplier data in data/suppliers/{supplier_id}/.
    """

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _get_data_dir()
        self._suppliers_dir = self._data_dir / "suppliers"

    def _supplier_dir(self, supplier_id: str) -> Path:
        _validate_supplier_id(supplier_id)
        return self._suppliers_dir / supplier_id

    def _profile_path(self, supplier_id: str) -> Path:
        return self._supplier_dir(supplier_id) / "profile.json"

    def _layout_path(self, supplier_id: str) -> Path:
        return self._supplier_dir(supplier_id) / "layout.json"

    def _index_path(self) -> Path:
        return self._suppliers_dir / "index.json"

    def _default_profile(self, supplier_id: str, name: str = "") -> dict:
        return {
            "supplier_id": supplier_id,
            "name": name or supplier_id,
            "scan_count": 0,
            "latest_values": {},
            "item_history": {},
            "corrections": [],
        }

    def get_profile(self, supplier_id: str) -> dict:
        """Load a supplier's profile. Returns default profile if not found."""
        _validate_supplier_id(supplier_id)
        with _file_lock:
            profile = _read_json(self._profile_path(supplier_id))
        if not profile:
            return self._default_profile(supplier_id)
        return profile

    def save_scan(self, supplier_id: str, scan_data: dict) -> None:
        """Append scan data to supplier history and update running stats."""
        _validate_supplier_id(supplier_id)

        with _file_lock:
            profile = _read_json(self._profile_path(supplier_id))
            if not profile:
                name = scan_data.get("supplier", supplier_id)
                profile = self._default_profile(supplier_id, name)

            # Increment scan count
            profile["scan_count"] = profile.get("scan_count", 0) + 1

            # Update latest_values with top-level scan fields
            latest_values = profile.get("latest_values", {})
            for field in ("supplier", "tax_rate", "invoice_number", "date"):
                if field in scan_data and scan_data[field] is not None:
                    latest_values[field] = scan_data[field]
            profile["latest_values"] = latest_values

            # Update item_history with running averages
            item_history = profile.get("item_history", {})
            for item in scan_data.get("items", []):
                item_name = item.get("name") or item.get("description")
                if not item_name:
                    continue

                existing = item_history.get(item_name, {})
                seen_count = existing.get("seen_count", 0) + 1
                old_avg = existing.get("avg_price", 0)
                new_price = item.get("unit_price")

                if new_price is not None:
                    # Running average
                    if seen_count == 1:
                        avg_price = new_price
                    else:
                        avg_price = old_avg + (new_price - old_avg) / seen_count
                else:
                    avg_price = old_avg

                item_history[item_name] = {
                    "avg_price": round(avg_price, 4),
                    "common_unit": item.get("unit") or existing.get("common_unit", ""),
                    "seen_count": seen_count,
                }
            profile["item_history"] = item_history

            # Store corrections if present
            if "corrections" in scan_data:
                corrections = profile.get("corrections", [])
                corrections.extend(scan_data["corrections"])
                profile["corrections"] = corrections

            _write_json(self._profile_path(supplier_id), profile)

            # Update supplier index
            self._update_index(supplier_id, profile.get("name", supplier_id))

    def _update_index(self, supplier_id: str, name: str) -> None:
        """Update the supplier index file. Must be called within _file_lock."""
        index = _read_json(self._index_path())
        suppliers = index.get("suppliers", {})
        suppliers[supplier_id] = {"name": name, "supplier_id": supplier_id}
        index["suppliers"] = suppliers
        _write_json(self._index_path(), index)

    def infer_missing(self, supplier_id: str, field: str) -> Any:
        """Look up field from supplier's historical data.

        Returns the most common value for top-level fields,
        or None if no historical data exists.
        """
        _validate_supplier_id(supplier_id)

        with _file_lock:
            profile = _read_json(self._profile_path(supplier_id))

        if not profile:
            return None

        # Check latest_values first
        latest_values = profile.get("latest_values", {})
        if field in latest_values:
            return latest_values[field]

        return None

    def get_layout(self, supplier_id: str) -> dict | None:
        """Read the supplier's known invoice layout."""
        _validate_supplier_id(supplier_id)
        with _file_lock:
            layout = _read_json(self._layout_path(supplier_id))
        return layout if layout else None

    def update_layout(self, supplier_id: str, layout: dict) -> None:
        """Write/update the supplier's invoice layout."""
        _validate_supplier_id(supplier_id)
        with _file_lock:
            _write_json(self._layout_path(supplier_id), layout)


class JsonGeneralMemory(GeneralMemory):
    """JSON file-based general industry memory storage."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _get_data_dir()
        self._general_dir = self._data_dir / "general"

    def _industry_profile_path(self) -> Path:
        return self._general_dir / "industry_profile.json"

    def _item_catalog_path(self) -> Path:
        return self._general_dir / "item_catalog.json"

    def get_industry_profile(self) -> dict:
        """Read the industry profile."""
        with _file_lock:
            profile = _read_json(self._industry_profile_path())
        if not profile:
            return {
                "common_units": ["ea", "lb", "kg", "case", "oz", "gal"],
                "typical_tax_rates": [
                    0.0, 0.05, 0.06, 0.07, 0.075, 0.08, 0.0825, 0.10
                ],
                "item_catalog": {},
            }
        return profile

    def get_item_catalog(self) -> dict:
        """Read the item catalog."""
        with _file_lock:
            catalog = _read_json(self._item_catalog_path())
        if not catalog:
            return {"items": {}}
        return catalog

    def update_from_scan(self, scan_data: dict) -> None:
        """Update industry profile with new data points from a scan."""
        with _file_lock:
            # Update item catalog
            catalog = _read_json(self._item_catalog_path())
            items = catalog.get("items", {})

            for item in scan_data.get("items", []):
                item_name = item.get("name") or item.get("description")
                if not item_name:
                    continue

                existing = items.get(item_name, {})
                seen_count = existing.get("seen_count", 0) + 1
                old_avg = existing.get("avg_price", 0)
                new_price = item.get("unit_price")

                if new_price is not None:
                    if seen_count == 1:
                        avg_price = new_price
                    else:
                        avg_price = old_avg + (new_price - old_avg) / seen_count
                else:
                    avg_price = old_avg

                items[item_name] = {
                    "avg_price": round(avg_price, 4),
                    "common_unit": item.get("unit") or existing.get("common_unit", ""),
                    "seen_count": seen_count,
                }

            catalog["items"] = items
            _write_json(self._item_catalog_path(), catalog)

            # Update industry profile with tax rate if present
            profile = _read_json(self._industry_profile_path())
            tax_rate = scan_data.get("tax_rate")
            if tax_rate is not None:
                typical_rates = profile.get("typical_tax_rates", [])
                if tax_rate not in typical_rates:
                    typical_rates.append(tax_rate)
                    typical_rates.sort()
                    profile["typical_tax_rates"] = typical_rates

            # Update common units from items
            common_units = set(profile.get("common_units", []))
            for item in scan_data.get("items", []):
                unit = item.get("unit")
                if unit and unit not in common_units:
                    common_units.add(unit)
            profile["common_units"] = sorted(common_units)

            _write_json(self._industry_profile_path(), profile)
