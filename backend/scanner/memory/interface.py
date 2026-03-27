"""Abstract interfaces for SmartScanner memory system."""

from abc import ABC, abstractmethod
from typing import Any


class SupplierMemory(ABC):
    """Interface for supplier-specific memory storage."""

    @abstractmethod
    def get_profile(self, supplier_id: str) -> dict:
        """Load a supplier's profile (scan history, common values, corrections)."""
        ...

    @abstractmethod
    def save_scan(self, supplier_id: str, scan_data: dict) -> None:
        """Append scan data to supplier history and update running stats."""
        ...

    @abstractmethod
    def infer_missing(self, supplier_id: str, field: str) -> Any:
        """Look up field from supplier's historical data (most common value)."""
        ...

    @abstractmethod
    def get_layout(self, supplier_id: str) -> dict | None:
        """Read the supplier's known invoice layout, or None if unknown."""
        ...

    @abstractmethod
    def update_layout(self, supplier_id: str, layout: dict) -> None:
        """Write/update the supplier's invoice layout."""
        ...


class GeneralMemory(ABC):
    """Interface for general industry memory storage."""

    @abstractmethod
    def get_industry_profile(self) -> dict:
        """Read the industry profile (common field patterns across all suppliers)."""
        ...

    @abstractmethod
    def get_item_catalog(self) -> dict:
        """Read the item catalog (known items with typical prices)."""
        ...

    @abstractmethod
    def update_from_scan(self, scan_data: dict) -> None:
        """Update industry profile with new data points from a scan."""
        ...
