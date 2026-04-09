"""
DuckDuckGo supplier search tool wrapped as a LangGraph-compatible agent tool.
"""

from __future__ import annotations
import logging
from duckduckgo_search import DDGS
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """A single grounded search result returned to the LLM.

    Grounding: the LLM receives structured facts (title, url, snippet) rather
    than raw text, so it can cite sources instead of hallucinating.
    """

    title: str = Field(description="Page title of the search result.")
    url: str = Field(description="Source URL for citation.")
    snippet: str = Field(description="Short excerpt describing the result.")


# ---------------------------------------------------------------------------
# Pydantic input schema (LangGraph-compatible tool interface)
# ---------------------------------------------------------------------------


class SupplierSearchInput(BaseModel):
    """Input schema for the DuckDuckGo supplier search agent tool.

    The LLM populates this model when it needs live information about an unknown
    supplier or ingredient source. Call `.model_json_schema()` to compare the
    schema structure to the tool spec sent to GLM in Section 4.
    """

    query: str = Field(
        description=(
            "Natural-language search query, e.g. 'organic salmon supplier Seattle' "
            "or 'who is ABC Foods restaurant supply'. Be specific — include location "
            "and product type when known."
        )
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of results to return (1–20). Defaults to 5.",
    )


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def search_suppliers(query: str, max_results: int = 5) -> list[ToolResult]:
    """
    Search DuckDuckGo for supplier information and return grounded ToolResult objects.

    This is the convenience entry point for direct Python calls (e.g. the checkpoint).
    For agent tool calls, use the full tool function below.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.

    Returns:
        List of ToolResult objects with title, url, and snippet.
    """
    inp = SupplierSearchInput(query=query, max_results=max_results)
    return _execute_search(inp)


def search_suppliers_tool(inp: SupplierSearchInput) -> dict:
    """
    Execute a DuckDuckGo supplier search as an agent tool.

    The LLM calls this when it needs live information about suppliers —
    e.g. "Who supplies organic salmon in Seattle?" — and the result is
    injected back into message history as a tool response.

    Args:
        inp: Validated SupplierSearchInput from the LLM tool call.

    Returns:
        Dict with:
            - results: list of ToolResult dicts
            - query: the original query (for traceability)
            - result_count: number of results returned
    """
    results = _execute_search(inp)
    logger.info(
        "search_suppliers_tool — query=%r max_results=%d returned=%d",
        inp.query,
        inp.max_results,
        len(results),
    )
    return {
        "query": inp.query,
        "result_count": len(results),
        "results": [r.model_dump() for r in results],
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _execute_search(inp: SupplierSearchInput) -> list[ToolResult]:
    """Run the DuckDuckGo search and map raw results to ToolResult objects.

    Post-processing (grounding):
    - Strip None titles/snippets — the LLM must not receive empty fields it
      might hallucinate into facts.
    - Truncate snippets to 300 chars to keep tool responses within context budget.
    """
    results: list[ToolResult] = []

    try:
        with DDGS() as ddgs:
            raw = ddgs.text(inp.query, max_results=inp.max_results)
            for item in raw or []:
                title = (item.get("title") or "").strip()
                url = (item.get("href") or item.get("url") or "").strip()
                snippet = (item.get("body") or "").strip()

                # Skip results missing essential grounding fields
                if not title or not url:
                    continue

                results.append(
                    ToolResult(
                        title=title,
                        url=url,
                        snippet=snippet[:300],
                    )
                )
    except Exception:
        logger.exception("DuckDuckGo search failed for query=%r", inp.query)
        # Return empty list so the agent can handle the failure gracefully
        return []

    return results
