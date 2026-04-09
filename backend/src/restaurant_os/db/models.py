"""
SQLAlchemy 2.0 declarative models for Restaurant OS relational storage.

"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Shared declarative base for all Restaurant OS ORM models."""


class Restaurant(Base):
    """A restaurant tenant.

    Every other table carries a restaurant_id foreign key so all queries can be
    scoped to a single tenant without cross-contamination between restaurants.
    """

    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    suppliers: Mapped[list[Supplier]] = relationship(
        "Supplier", back_populates="restaurant", cascade="all, delete-orphan"
    )
    invoices: Mapped[list[Invoice]] = relationship(
        "Invoice", back_populates="restaurant", cascade="all, delete-orphan"
    )
    corrections: Mapped[list[UserCorrection]] = relationship(
        "UserCorrection", back_populates="restaurant", cascade="all, delete-orphan"
    )


class Supplier(Base):
    """A food/supply vendor that invoices a restaurant.

    supplier_slug is an immutable, normalized identifier derived from the supplier
    name (e.g. "abc-foods"). Once created it must not change — it is the lookup
    key for invoice history and memory retrieval.

    Ported concept: Restaurant OS's per-supplier directory under data/suppliers/.
    """

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("supplier_slug", "restaurant_id", name="uq_supplier_slug_restaurant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_slug: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    scan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSONB columns mirror Restaurant OS's profile.json structure; flexible storage
    # allows new fields without schema migrations.
    latest_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    item_history: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    restaurant: Mapped[Restaurant] = relationship("Restaurant", back_populates="suppliers")
    invoices: Mapped[list[Invoice]] = relationship(
        "Invoice", back_populates="supplier"
    )
    corrections: Mapped[list[UserCorrection]] = relationship(
        "UserCorrection", back_populates="supplier"
    )


class Invoice(Base):
    """A single invoice scanned from an image.

    raw_ocr stores the full OCR extraction payload as JSONB so we have the
    original data for auditing and re-processing without needing to re-scan.
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    invoice_date: Mapped[Any] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    subtotal: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    raw_ocr: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="invoices")
    restaurant: Mapped[Restaurant] = relationship("Restaurant", back_populates="invoices")
    line_items: Mapped[list[LineItem]] = relationship(
        "LineItem", back_populates="invoice", cascade="all, delete-orphan"
    )
    corrections: Mapped[list[UserCorrection]] = relationship(
        "UserCorrection", back_populates="invoice"
    )


class LineItem(Base):
    """One line on an invoice (a single product/SKU entry).

    Cascade delete ensures line items are removed with their parent invoice.
    """

    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    total_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    invoice: Mapped[Invoice] = relationship("Invoice", back_populates="line_items")


class UserCorrection(Base):
    """A correction a user applied to an extracted invoice field.

    Ports Restaurant OS's inline corrections list (stored inside profile.json)
    to a first-class relational table with proper foreign keys and timestamps.

    field_path uses the same notation as corrections.py:
        "supplier"          — top-level header field
        "items[0].unit_price" — item subfield by index
    """

    __tablename__ = "user_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoice: Mapped[Invoice | None] = relationship(
        "Invoice", back_populates="corrections"
    )
    supplier: Mapped[Supplier | None] = relationship(
        "Supplier", back_populates="corrections"
    )
    restaurant: Mapped[Restaurant] = relationship(
        "Restaurant", back_populates="corrections"
    )
