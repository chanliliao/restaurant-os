"""
FastAPI v1 route handlers.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from restaurant_os.agents.scanner_agent import run_scan
from restaurant_os.agents.supervisor import AgentState, supervisor_graph
from restaurant_os.api.v1.schemas import ChatRequest, ScanResponse

router = APIRouter(prefix="/api/v1")

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.get("/health")
async def health_check():
    """
    Return a simple health status for load-balancer / uptime checks.

    Returns:
        dict with "status": "ok" and current UTC timestamp.
    """
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/scan")
async def scan_invoice(file: UploadFile = File(...)):
    """
    Accept an uploaded invoice image and run the scanner pipeline.

    Request body (multipart/form-data):
        file: UploadFile — the invoice image (JPEG/PNG, max 10 MB)

    Returns:
        ScanResponse Pydantic model (Section 2) with extracted fields,
        confidence scores, and supplier info.

    Steps:
        1. Validate file type and size.
        2. Read image bytes from the upload.
        3. Call the scanner agent (Section 3 → image_processor Section 5 → GLM Section 4).
        4. Return structured ScanResponse.
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{file.content_type}'. Must be image/jpeg or image/png.",
        )

    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds 10 MB limit ({len(contents)} bytes).",
        )

    # TODO (Section 6): load RestaurantContext from DB by restaurant_id (query param or header)
    result = await run_scan(contents, restaurant_context=None)

    return ScanResponse(
        scan_id=result.scan_id,
        supplier=result.supplier,
        line_items=result.line_items,
        subtotal=result.subtotal,
        total=result.total,
        tax=result.tax,
        overall_confidence=result.overall_confidence,
    )


@router.post("/chat")
async def chat_stream(request: ChatRequest):
    """
    Accept a chat message and stream the agent's reasoning back via SSE.

    This is the core Restaurant OS endpoint — no SmartScanner equivalent.

    Request body (JSON):
        message: str — the user's natural-language question or command.
        restaurant_id: str — scopes the agent to a specific restaurant's data.

    Returns:
        StreamingResponse with media_type "text/event-stream".
        Each SSE event is a JSON-encoded ChatStreamEvent (Section 2).

    Steps:
        1. Parse and validate request body.
        2. Look up RestaurantContext from DB (Section 6).
        3. Invoke the LangGraph supervisor (Section 3).
        4. Yield each reasoning chunk as an SSE event.
        5. Send a terminal "done" event when the graph finishes.

    Example SSE output:
        data: {"type": "reasoning", "content": "Looking up supplier..."}
        data: {"type": "tool_call", "tool": "search_supplier", "args": {...}}
        data: {"type": "tool_result", "content": "Found 3 suppliers."}
        data: {"type": "done", "content": "Here are your results."}
    """
    # TODO (Section 6): load RestaurantContext from DB by request.restaurant_id
    return StreamingResponse(
        _sse_event_generator(request.message),
        media_type="text/event-stream",
    )


async def _sse_event_generator(message: str):
    """
    Async generator that drives the supervisor graph and yields SSE-formatted strings.

    Each yielded string is one SSE event:
        "data: <json>\\n\\n"

    LangGraph's astream() yields one dict per completed node:
        {"node_name": {state_fields_updated_by_that_node}}

    Args:
        message: the user's input to the agent.

    Yields:
        SSE-formatted strings, one per graph node step.
    """
    initial_state: AgentState = {
        "messages": [{"role": "user", "content": message}],
        "tool_calls": [],
        "restaurant_context": None,  # TODO (Section 6): load from DB by restaurant_id
        "final_response": None,
    }

    async for step in supervisor_graph.astream(initial_state):
        for node_name, node_updates in step.items():
            if node_name == "respond" and node_updates.get("final_response"):
                event = {"type": "done", "content": node_updates["final_response"]}
            else:
                event = {"type": "reasoning", "content": f"[{node_name}] step complete"}
            yield f"data: {json.dumps(event)}\n\n"
