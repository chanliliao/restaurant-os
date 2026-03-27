"""SmartScanner memory system for supplier and industry data."""

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
]
