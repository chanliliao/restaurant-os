"""
Database layer — SQLAlchemy 2.0 async models, repositories, and session factory.
"""

from .models import Base, Invoice, LineItem, Restaurant, Supplier, UserCorrection
from .repositories import (
    InvoiceRepository,
    SupplierRepository,
    UserCorrectionRepository,
    normalize_supplier_id,
)
from .session import AsyncSessionLocal, engine, get_session, init_db

__all__ = [
    # Models
    "Base",
    "Restaurant",
    "Supplier",
    "Invoice",
    "LineItem",
    "UserCorrection",
    # Repositories
    "SupplierRepository",
    "InvoiceRepository",
    "UserCorrectionRepository",
    "normalize_supplier_id",
    # Session
    "engine",
    "AsyncSessionLocal",
    "get_session",
    "init_db",
]
