"""
Dynamic tool registration and routing for LangGraph.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .calculator import CalculatorInput, validate_invoice_math
from .db_tools import SupplierLookupInput, lookup_supplier
from .image_processor import ImageProcessorInput, preprocess_image
from .supplier_scanner import SupplierSearchInput, search_suppliers_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool descriptor
# ---------------------------------------------------------------------------


class ToolDescriptor:
    """Metadata + callable for a single registered tool.

    Holds:
        name        — unique tool name the LLM uses in its tool_calls JSON
        description — natural-language description sent in the tool list to the LLM
        input_model — Pydantic BaseModel subclass that validates the LLM's arguments
        fn          — callable that accepts a validated input_model instance
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        fn: Callable[[Any], Any],
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.fn = fn

    def json_schema(self) -> dict:
        """Return the JSON Schema for this tool's input model.

        This is the schema you send to GLM in the tools list. It must match
        the Pydantic model exactly so the LLM generates valid arguments.
        """
        return self.input_model.model_json_schema()

    def to_glm_tool_spec(self) -> dict:
        """Return a GLM-compatible tool specification dict.

        Format expected by the ZhipuAI / OpenAI-compatible tools API:
        {
            "type": "function",
            "function": {
                "name": "<name>",
                "description": "<description>",
                "parameters": <json_schema>
            }
        }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema(),
            },
        }

    def invoke(self, arguments: dict) -> Any:
        """Validate arguments with the Pydantic model and call the tool function.

        Args:
            arguments: Raw dict from the LLM tool_call.function.arguments.

        Returns:
            Whatever the underlying tool function returns. For async tool functions,
            returns a coroutine — callers must await it or use ainvoke().

        Raises:
            pydantic.ValidationError: If the LLM's arguments don't satisfy the schema.
        """
        validated_input = self.input_model.model_validate(arguments)
        return self.fn(validated_input)

    async def ainvoke(self, arguments: dict) -> Any:
        """Async version of invoke — awaits the result if fn is a coroutine function.

        Use this from async contexts (LangGraph nodes, FastAPI route handlers) to
        dispatch both sync and async tools uniformly.
        """
        validated_input = self.input_model.model_validate(arguments)
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(validated_input)
        return self.fn(validated_input)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Manages tool registration and LLM-driven dispatch.

    Usage:
        registry = ToolRegistry()
        registry.register(descriptor)
        spec_list = registry.to_glm_tool_specs()   # send to LLM
        result = registry.invoke("tool_name", args) # after LLM responds
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        """Add a tool to the registry. Raises ValueError on duplicate names."""
        if descriptor.name in self._tools:
            raise ValueError(
                f"Tool '{descriptor.name}' is already registered. "
                "Use deregister() first if you want to replace it."
            )
        self._tools[descriptor.name] = descriptor
        logger.debug("Registered tool: %s", descriptor.name)

    def deregister(self, name: str) -> None:
        """Remove a tool by name. Raises KeyError if not registered."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered.")
        del self._tools[name]
        logger.debug("Deregistered tool: %s", name)

    def get(self, name: str) -> ToolDescriptor:
        """Return a ToolDescriptor by name. Raises KeyError if not registered."""
        if name not in self._tools:
            raise KeyError(
                f"Tool '{name}' is not registered. "
                f"Available tools: {list(self._tools)}"
            )
        return self._tools[name]

    def names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools)

    def to_glm_tool_specs(self) -> list[dict]:
        """Return all registered tools as a GLM-compatible tool spec list.

        Pass this list directly to the ZhipuAI chat API's `tools` parameter.
        """
        return [descriptor.to_glm_tool_spec() for descriptor in self._tools.values()]

    def invoke(self, tool_name: str, arguments: dict) -> Any:
        """Dispatch an LLM tool call to the registered function.

        Args:
            tool_name: The name from the LLM's tool_call.function.name.
            arguments: Parsed dict from tool_call.function.arguments.

        Returns:
            The tool function's return value. For async tools, returns a coroutine;
            use ainvoke() from async contexts instead.
        """
        descriptor = self.get(tool_name)
        logger.info("Invoking tool: %s", tool_name)
        result = descriptor.invoke(arguments)
        logger.info("Tool %s completed successfully", tool_name)
        return result

    async def ainvoke(self, tool_name: str, arguments: dict) -> Any:
        """Async dispatch — handles both sync and async tool functions uniformly.

        Use this from LangGraph nodes and FastAPI handlers so that adding an
        async tool never requires changes to the caller.
        """
        descriptor = self.get(tool_name)
        logger.info("Invoking tool (async): %s", tool_name)
        result = await descriptor.ainvoke(arguments)
        logger.info("Tool %s completed successfully", tool_name)
        return result

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={self.names()})"


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def get_default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-loaded with all core Restaurant OS tools.

    Registered tools:
        - preprocess_image: Image orientation, quality analysis, and segmentation
        - validate_invoice_math: Arithmetic cross-validation for extracted invoices
        - search_suppliers: DuckDuckGo live supplier search with grounded results
        - lookup_supplier: PostgreSQL supplier profile lookup (async — use ainvoke)

    vector_search is registered in Section 7 once db/vector.py exists.
    """
    registry = ToolRegistry()

    registry.register(ToolDescriptor(
        name="preprocess_image",
        description=(
            "Preprocess a base64-encoded invoice image: correct orientation, "
            "analyze quality (blur, contrast, noise, resolution), apply selective "
            "enhancement, and segment into header/line-items/totals regions. "
            "Call this before OCR to improve extraction accuracy."
        ),
        input_model=ImageProcessorInput,
        fn=preprocess_image,
    ))

    registry.register(ToolDescriptor(
        name="validate_invoice_math",
        description=(
            "Validate the arithmetic consistency of extracted invoice data: "
            "line totals (qty × unit_price), subtotal (sum of line totals), "
            "and grand total (subtotal + tax). Returns errors and an "
            "auto-corrected result. Call this after extracting invoice fields."
        ),
        input_model=CalculatorInput,
        fn=validate_invoice_math,
    ))

    registry.register(ToolDescriptor(
        name="search_suppliers",
        description=(
            "Search DuckDuckGo for live information about restaurant suppliers. "
            "Use when the supplier name is unrecognized or the agent needs to "
            "verify supplier details (location, product range, contact). "
            "Returns grounded results with title, URL, and snippet."
        ),
        input_model=SupplierSearchInput,
        fn=search_suppliers_tool,
    ))

    registry.register(ToolDescriptor(
        name="lookup_supplier",
        description=(
            "Fetch a supplier's structured profile from PostgreSQL: name, category, "
            "known items with historical prices, and recent invoice stats. "
            "Call this when the agent needs supplier context before OCR extraction. "
            "Requires restaurant_id for tenant scoping. Async — use registry.ainvoke()."
        ),
        input_model=SupplierLookupInput,
        fn=lookup_supplier,
    ))

    return registry
