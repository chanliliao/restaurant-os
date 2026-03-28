"""SmartScanner memory system for supplier and industry data."""

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
