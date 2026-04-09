"""
Vector DB and relational DB query tools for the scanner agent.

Section 6 (Lesson 6): lookup_supplier is now wired to db/repositories.py.
Section 7 (Lesson 7): vector_search will be wired to db/vector.py.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel, Field

from ..db.repositories import SupplierRepository, _validate_supplier_slug
from ..db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic input schemas
# ---------------------------------------------------------------------------


class SupplierLookupInput(BaseModel):
    """Input schema for the relational supplier lookup tool.

    The LLM calls this when it needs structured supplier data (category,
    known items, contact info) for a supplier it has already identified.
    """

    supplier_id: str = Field(
        description=(
            "Immutable supplier slug (e.g. 'abc-foods'). "
            "Must not contain '..', '/', or '\\\\' (path traversal rejected)."
        )
    )
    restaurant_id: str = Field(
        description="Tenant restaurant ID used to scope the DB query."
    )


class VectorSearchInput(BaseModel):
    """Input schema for the pgvector semantic similarity search tool.

    The LLM calls this when it needs to find suppliers or invoice line items
    that are semantically similar to a query (e.g. 'fresh Atlantic salmon').
    """

    query: str = Field(
        description=(
            "Natural-language query to embed and search against the vector store, "
            "e.g. 'organic chicken breast' or 'seafood supplier Pacific Northwest'."
        )
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of nearest-neighbor results to return (1–20).",
    )
    restaurant_id: str = Field(
        description="Tenant restaurant ID used to scope the vector search."
    )


# ---------------------------------------------------------------------------
# Tool functions (stubs — implemented in Section 6)
# ---------------------------------------------------------------------------


async def lookup_supplier(inp: SupplierLookupInput) -> dict:
    """
    Fetch a supplier's structured profile from PostgreSQL.

    Returns supplier name, category, known items, and recent invoice summary
    for the given restaurant tenant. Used by the scanner agent to inject
    supplier context before calling GLM-OCR.

    Args:
        inp: Validated SupplierLookupInput from the LLM tool call.

    Returns:
        Dict with supplier profile fields. "found": False if the supplier
        does not exist in the database for this restaurant.

    Raises:
        ValueError: If supplier_id fails slug validation (path traversal attempt).
    """
    _validate_supplier_slug(inp.supplier_id)
    restaurant_uuid = UUID(inp.restaurant_id)

    async with AsyncSessionLocal() as session:
        repo = SupplierRepository(session)
        supplier = await repo.get_supplier(inp.supplier_id, restaurant_uuid)

    if supplier is None:
        logger.info("lookup_supplier: no profile found for slug=%s", inp.supplier_id)
        return {"found": False, "supplier_id": inp.supplier_id}

    return {
        "found": True,
        "supplier_id": supplier.supplier_slug,
        "name": supplier.name,
        "category": supplier.category,
        "scan_count": supplier.scan_count,
        "latest_values": supplier.latest_values,
        "item_history": supplier.item_history,
    }


def vector_search(inp: VectorSearchInput) -> dict:
    """
    Embed the query and retrieve the top-k semantically similar records from pgvector.

    Used by the scanner agent and agents/memory.py to find suppliers, line items,
    or historical invoices that match an ingredient or supplier description.
    Results are injected into LLM context as grounded retrieval (RAG).

    Args:
        inp: Validated VectorSearchInput from the LLM tool call.

    Returns:
        Dict with top-k results (text, similarity score, record type, id).

    Raises:
        NotImplementedError: Until Section 7 (db/vector.py) is implemented.
    """
    raise NotImplementedError(
        "vector_search requires db/vector.py (pgvector HNSW similarity search). "
        "This is implemented in Section 7 — Lesson 7: pgvector."
    )
