"""
API request and response schemas (Pydantic v2).

These are the boundary contracts for the FastAPI routes in routes.py.
They are deliberately separate from the domain models in core/models.py —
the API shape can evolve independently of the internal data structures.
"""

from __future__ import annotations
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field
from restaurant_os.core.models import InvoiceLineItem, SupplierInfo

# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """
    Request body for POST /api/v1/chat.

    """

    message: Annotated[str, Field(min_length=1, max_length=4096)]
    """The operator's natural-language question or command."""

    restaurant_id: str
    """Restaurant tenant identifier. Used to load RestaurantContext from DB."""


class ReasoningEvent(BaseModel):
    """SSE event carrying an intermediate reasoning step from the agent."""

    type: Literal["reasoning"] = "reasoning"
    content: str
    """One sentence of the agent's internal thought process."""


class ToolCallEvent(BaseModel):
    """SSE event emitted when the agent decides to invoke a tool."""

    type: Literal["tool_call"] = "tool_call"
    tool: str
    """Name of the tool being invoked."""

    args: dict[str, Any]
    """Tool arguments as a key-value dict."""


class ToolResultEvent(BaseModel):
    """SSE event emitted after a tool returns its result."""

    type: Literal["tool_result"] = "tool_result"
    content: str
    """Serialised tool result, truncated if very large."""


class DoneEvent(BaseModel):
    """Terminal SSE event. Signals the client that the stream is complete."""

    type: Literal["done"] = "done"
    content: str
    """Final answer text from the agent."""


# Discriminated union — FastAPI uses `type` as the discriminator field.
# The LLM's reasoning trace is a sequence of these event types.
ChatStreamEvent = Annotated[
    ReasoningEvent | ToolCallEvent | ToolResultEvent | DoneEvent,
    Field(discriminator="type"),
]
"""
Union of all possible SSE event types for the /chat stream.

"""


# ---------------------------------------------------------------------------
# Scan endpoint
# ---------------------------------------------------------------------------


class ScanResponse(BaseModel):
    """
    Response body for POST /api/v1/scan.

    """

    scan_id: str
    """Unique run identifier echoed back so the client can correlate async results."""

    supplier: SupplierInfo | None = None
    """Identified supplier profile. None when the agent cannot determine supplier."""

    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    """Extracted line items. Empty list when the invoice is unreadable."""

    subtotal: float | None = None
    total: float | None = None
    tax: float | None = None

    overall_confidence: Annotated[int, Field(ge=0, le=100)] = 0
    """Aggregate extraction confidence (0–100)."""

    warnings: list[str] = Field(default_factory=list)
    """
    Non-fatal issues detected during extraction (e.g. math mismatch, low confidence).
    """
