"""
LangGraph ReAct supervisor — three-node reason/act/respond graph.

"""

from __future__ import annotations
import logging
from typing import Annotated, Any, Literal, TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from restaurant_os.core.models import RestaurantContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """
    Shared state object that flows through every node in the supervisor graph.

    LangGraph passes this dict to each node function and merges the returned
    dict back into the graph's state. Fields annotated with `add_messages`
    are *appended* to on each update; all other fields are *replaced*.
    """

    messages: Annotated[list[dict[str, Any]], add_messages]
    """Full conversation history: system, user, assistant, and tool messages."""

    tool_calls: list[dict[str, Any]]
    """Pending tool calls emitted by the LLM's most recent reasoning step."""

    restaurant_context: RestaurantContext | None
    """Restaurant-scoped context injected at run start for tenant isolation."""

    final_response: str | None
    """Set by the `respond` node; non-None signals the graph is complete."""


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def reason(state: AgentState) -> dict[str, Any]:
    """
    Call the LLM with the current message history and available tool schemas.

    The LLM inspects the tool schemas and either:
    - Returns a `tool_calls` array → the conditional edge routes to `act`
    - Returns a plain-text response → the conditional edge routes to `respond`

    This node decides *what* to do next; it does NOT execute tools itself.
    That separation is what makes the ReAct loop inspectable: every decision
    lives in `reason`, every side effect lives in `act`.
    """
    # TODO (Section 4): import GLMClient from llm.glm_client
    # TODO (Section 4): call await GLMClient.achat(messages=state["messages"], tools=_TOOL_SCHEMAS)
    # TODO (Section 4): if response.tool_calls: return {"tool_calls": response.tool_calls, "messages": [...]}
    # TODO (Section 4): else: return {"tool_calls": [], "messages": [assistant_message]}
    raise NotImplementedError(
        "reason node requires GLMClient from llm/glm_client.py — implement in Section 4 (Lesson 4)."
    )


def act(state: AgentState) -> dict[str, Any]:
    """
    Execute the tool calls emitted by the `reason` node.

    For each tool call in `state["tool_calls"]`:
    1. Look up the tool function by name in the tool registry.
    2. Call it with the LLM-specified arguments.
    3. Append the result as a role='tool' message so `reason` can observe it.

    After `act` returns, the graph loops back to `reason`, which inspects
    the tool results and decides whether to call more tools or respond.
    """
    # TODO (Section 5): import TOOL_REGISTRY from tools.registry
    # TODO (Section 5): for each call in state["tool_calls"]: TOOL_REGISTRY[call["name"]](**call["arguments"])
    # TODO (Section 5): return {"messages": [tool_result_messages], "tool_calls": []}
    raise NotImplementedError(
        "act node requires tool registry from tools/registry.py — implement in Section 5 (Lesson 5)."
    )


def respond(state: AgentState) -> dict[str, Any]:
    """
    Emit the agent's final response.

    Reached when `reason` returns no tool calls — the LLM has enough
    information to answer. Extracts the last assistant message from
    state and sets `final_response` to terminate the graph.

    This node has no external dependencies and is fully implemented now.
    """
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                logger.info("supervisor: final response ready (%d chars)", len(content))
                return {"final_response": content}

    logger.warning("supervisor: no assistant message found in state — returning empty response")
    return {"final_response": ""}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------


def _route_from_reason(state: AgentState) -> Literal["act", "respond"]:
    """
    Choose the next node after `reason` runs.

    Conditional edges are the key LangGraph primitive for ReAct:
    - Tool calls present → `act` (execute and loop back)
    - No tool calls → `respond` (agent is done)

    This function reads *only* from state; it has no side effects.
    """
    if state.get("tool_calls"):
        return "act"
    return "respond"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_supervisor_graph() -> StateGraph:
    """
    Construct and compile the ReAct supervisor graph.

    Topology:
        START → reason
        reason → act         (when tool_calls present — conditional edge)
        reason → respond     (when no tool_calls — conditional edge)
        act    → reason      (loop: tool results feed back into the LLM)
        respond → END

    Returns a compiled graph ready for .invoke() or .stream() calls.
    The graph compiles without calling any nodes — node NotImplementedErrors
    surface only at runtime, not at import time.
    """
    graph = StateGraph(AgentState)

    # Register the three ReAct nodes
    graph.add_node("reason", reason)
    graph.add_node("act", act)
    graph.add_node("respond", respond)

    # Entry point
    graph.add_edge(START, "reason")

    # Conditional routing from reason — the heart of the ReAct loop
    graph.add_conditional_edges(
        "reason",
        _route_from_reason,
        {"act": "act", "respond": "respond"},
    )

    # Tool results loop back to the LLM for the next reasoning step
    graph.add_edge("act", "reason")

    # Respond is a terminal node
    graph.add_edge("respond", END)

    return graph.compile()


# Module-level compiled graph.
# Import and invoke from route handlers:
#   from restaurant_os.agents.supervisor import supervisor_graph
#   async for step in supervisor_graph.astream(initial_state): ...
supervisor_graph = build_supervisor_graph()
