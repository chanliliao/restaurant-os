"""
Async SQLAlchemy repository layer — CRUD operations for Restaurant OS entities.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Invoice, LineItem, Restaurant, Supplier, UserCorrection


# ---------------------------------------------------------------------------
# Supplier slug helpers — ported directly from json_store.py
# ---------------------------------------------------------------------------


def normalize_supplier_id(name: str) -> str:
    """Normalize a supplier name into a safe, slug-friendly ID.

    Rules:
    - Lowercase, strip whitespace
    - Spaces become hyphens
    - Strip all characters except alphanumeric and hyphens
    - Reject path traversal attempts before normalizing

    The result is used as supplier_slug in the database and as the lookup key
    for all supplier profile queries.
    """
    if not name or not name.strip():
        raise ValueError("Supplier name cannot be empty")

    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid supplier name: {name!r}")

    normalized = name.lower().strip()
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9\-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")

    if not normalized:
        raise ValueError(f"Supplier name normalizes to empty string: {name!r}")

    return normalized


def _validate_supplier_slug(supplier_slug: str) -> None:
    """Validate that a supplier_slug is safe for use as a DB lookup key.
    """
    if not supplier_slug:
        raise ValueError("Supplier slug cannot be empty")
    if ".." in supplier_slug or "/" in supplier_slug or "\\" in supplier_slug:
        raise ValueError(f"Invalid supplier slug: {supplier_slug!r}")
    if not re.match(r"^[a-z0-9\-]+$", supplier_slug):
        raise ValueError(f"Invalid supplier slug format: {supplier_slug!r}")


# ---------------------------------------------------------------------------
# SupplierRepository
# ---------------------------------------------------------------------------


class SupplierRepository:
    """Async CRUD for Supplier entities.

    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_supplier(
        self, supplier_slug: str, restaurant_id: UUID
    ) -> Supplier | None:
        """Load a supplier by slug and restaurant. Returns None if not found."""
        _validate_supplier_slug(supplier_slug)
        result = await self._session.execute(
            select(Supplier).where(
                Supplier.supplier_slug == supplier_slug,
                Supplier.restaurant_id == restaurant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_supplier(
        self, supplier_slug: str, restaurant_id: UUID, name: str
    ) -> Supplier:
        """Load an existing supplier or insert a new one.

        flush() after insert makes the new row visible within this transaction
        without committing — callers can still roll back.
        """
        supplier = await self.get_supplier(supplier_slug, restaurant_id)
        if supplier is None:
            supplier = Supplier(
                supplier_slug=supplier_slug,
                name=name,
                restaurant_id=restaurant_id,
                scan_count=0,
                latest_values={},
                item_history={},
            )
            self._session.add(supplier)
            await self._session.flush()
        return supplier

    async def save_scan(
        self,
        supplier_slug: str,
        restaurant_id: UUID,
        scan_data: dict,
    ) -> Supplier:
        """Update supplier profile statistics from a completed scan.

        Increments scan_count, updates latest_values (supplier name, tax_rate,
        invoice_number, date), and maintains per-item running averages in
        item_history.
        """
        _validate_supplier_slug(supplier_slug)
        name = scan_data.get("supplier") or supplier_slug
        supplier = await self.get_or_create_supplier(supplier_slug, restaurant_id, name)

        supplier.scan_count = (supplier.scan_count or 0) + 1

        # Update latest_values with top-level fields (same fields as json_store)
        latest_values = dict(supplier.latest_values or {})
        for field in ("supplier", "tax_rate", "invoice_number", "date"):
            if field in scan_data and scan_data[field] is not None:
                latest_values[field] = scan_data[field]
        supplier.latest_values = latest_values

        # Update item_history with running averages (same logic as json_store)
        item_history = dict(supplier.item_history or {})
        for item in scan_data.get("items", []):
            item_name = item.get("name") or item.get("description")
            if not item_name:
                continue

            existing = item_history.get(item_name, {})
            seen_count = existing.get("seen_count", 0) + 1
            old_avg = existing.get("avg_price", 0)
            new_price = item.get("unit_price")

            if new_price is not None:
                avg_price = (
                    new_price
                    if seen_count == 1
                    else old_avg + (new_price - old_avg) / seen_count
                )
            else:
                avg_price = old_avg

            item_history[item_name] = {
                "avg_price": round(avg_price, 4),
                "common_unit": item.get("unit") or existing.get("common_unit", ""),
                "seen_count": seen_count,
            }
        supplier.item_history = item_history

        return supplier

    async def list_suppliers(self, restaurant_id: UUID) -> list[Supplier]:
        """Return all suppliers for a restaurant, ordered by name.

        """
        result = await self._session.execute(
            select(Supplier)
            .where(Supplier.restaurant_id == restaurant_id)
            .order_by(Supplier.name)
        )
        return list(result.scalars().all())

    async def infer_missing(
        self, supplier_slug: str, restaurant_id: UUID, field: str
    ) -> Any:
        """Look up a field from the supplier's latest_values.
        This is a convenience method for inferring missing values during scanning
        """
        _validate_supplier_slug(supplier_slug)
        supplier = await self.get_supplier(supplier_slug, restaurant_id)
        if supplier is None:
            return None
        return (supplier.latest_values or {}).get(field)


# ---------------------------------------------------------------------------
# InvoiceRepository
# ---------------------------------------------------------------------------


class InvoiceRepository:
    """Async CRUD for Invoice and LineItem entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_invoice(
        self,
        supplier_id: UUID,
        restaurant_id: UUID,
        scan_data: dict,
        raw_ocr: dict | None = None,
    ) -> Invoice:
        """Create an Invoice with its LineItems from a scan result dict.

        Accepts the same dict structure that SmartScanner's scanning pipeline
        produced: top-level header fields + "items" list.
        """
        invoice_date: datetime | None = None
        raw_date = scan_data.get("date") or scan_data.get("invoice_date")
        if isinstance(raw_date, str) and raw_date:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
                try:
                    invoice_date = datetime.strptime(raw_date, fmt).replace(
                        tzinfo=timezone.utc
                    )
                    break
                except ValueError:
                    continue
        elif isinstance(raw_date, datetime):
            invoice_date = raw_date

        invoice = Invoice(
            invoice_number=scan_data.get("invoice_number"),
            invoice_date=invoice_date,
            supplier_id=supplier_id,
            restaurant_id=restaurant_id,
            subtotal=scan_data.get("subtotal"),
            tax=scan_data.get("tax"),
            total=scan_data.get("total"),
            tax_rate=scan_data.get("tax_rate"),
            raw_ocr=raw_ocr,
        )
        self._session.add(invoice)
        await self._session.flush()  # populate invoice.id before inserting line items

        for item in scan_data.get("items", []):
            description = item.get("name") or item.get("description") or ""
            if not description:
                continue
            self._session.add(
                LineItem(
                    invoice_id=invoice.id,
                    description=description,
                    quantity=item.get("quantity"),
                    unit=item.get("unit"),
                    unit_price=item.get("unit_price"),
                    total_price=item.get("total") or item.get("total_price"),
                )
            )

        return invoice

    async def get_invoice(self, invoice_id: UUID) -> Invoice | None:
        """Load an invoice by ID, eagerly loading its line items."""
        result = await self._session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == invoice_id)
        )
        return result.scalar_one_or_none()

    async def list_invoices(
        self,
        restaurant_id: UUID,
        supplier_id: UUID | None = None,
    ) -> list[Invoice]:
        """Return invoices for a restaurant, optionally filtered by supplier.

        Results are ordered newest-first.
        """
        stmt = (
            select(Invoice)
            .where(Invoice.restaurant_id == restaurant_id)
            .order_by(Invoice.created_at.desc())
        )
        if supplier_id is not None:
            stmt = stmt.where(Invoice.supplier_id == supplier_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_spend_by_supplier(
        self, restaurant_id: UUID, days: int = 7
    ) -> list[dict]:
        """Query total spend per supplier over the last N days.

        This is the checkpoint query from Lesson 6: uses SELECT with func.sum,
        a JOIN, a WHERE on created_at, and GROUP BY. Returns rows ordered by
        total_spend descending.

        Returns:
            List of dicts: [{"supplier_slug": str, "supplier_name": str, "total_spend": float}]
        """
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(
                Supplier.supplier_slug,
                Supplier.name.label("supplier_name"),
                func.sum(Invoice.total).label("total_spend"),
            )
            .join(Invoice, Invoice.supplier_id == Supplier.id)
            .where(
                Invoice.restaurant_id == restaurant_id,
                Invoice.created_at >= since,
            )
            .group_by(Supplier.supplier_slug, Supplier.name)
            .order_by(func.sum(Invoice.total).desc())
        )
        return [
            {
                "supplier_slug": row.supplier_slug,
                "supplier_name": row.supplier_name,
                "total_spend": float(row.total_spend) if row.total_spend is not None else 0.0,
            }
            for row in result
        ]


# ---------------------------------------------------------------------------
# UserCorrectionRepository
# ---------------------------------------------------------------------------


class UserCorrectionRepository:
    """Async CRUD for UserCorrection entities.
    
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_correction(
        self,
        restaurant_id: UUID,
        field_path: str,
        corrected_value: str,
        original_value: str | None = None,
        invoice_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> UserCorrection:
        """Record a single user correction and flush to the session."""
        correction = UserCorrection(
            restaurant_id=restaurant_id,
            field_path=field_path,
            original_value=original_value,
            corrected_value=corrected_value,
            invoice_id=invoice_id,
            supplier_id=supplier_id,
        )
        self._session.add(correction)
        await self._session.flush()
        return correction

    async def get_corrections_for_invoice(
        self, invoice_id: UUID
    ) -> list[UserCorrection]:
        """Load all corrections for a given invoice, ordered by creation time."""
        result = await self._session.execute(
            select(UserCorrection)
            .where(UserCorrection.invoice_id == invoice_id)
            .order_by(UserCorrection.created_at)
        )
        return list(result.scalars().all())

    async def get_corrections_for_supplier(
        self, supplier_id: UUID
    ) -> list[UserCorrection]:
        """Load all corrections associated with a supplier (all invoices)."""
        result = await self._session.execute(
            select(UserCorrection)
            .where(UserCorrection.supplier_id == supplier_id)
            .order_by(UserCorrection.created_at)
        )
        return list(result.scalars().all())
