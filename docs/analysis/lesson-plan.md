# Restaurant OS Learning Curriculum & Migration Guide

This document is two things at once: a **learning curriculum** that teaches you every technology in the Restaurant OS stack, and a **migration guide** that shows you exactly which SmartScanner files to port, replace, or retire as you build each layer. Work through sections in order — the concepts and the codebase evolve together.

---

## Current App Structure (SmartScanner)

What you have today. These are the files you'll migrate from.

```
backend/
├── scanner/
│   ├── memory/
│   │   ├── categorizer.py       # Supplier category classification via keyword matching
│   │   ├── corrections.py       # User correction history tracking + feedback loop
│   │   ├── inference.py         # Field value inference from supplier memory (lookup-based)
│   │   ├── interface.py         # Memory system public API (load/save/query operations)
│   │   └── json_store.py        # JSON file CRUD + supplier ID validation + path safety
│   │
│   ├── preprocessing/
│   │   ├── analyzer.py          # Image quality analysis (blur, contrast, brightness checks)
│   │   ├── layout.py            # Invoice layout detection (header, items, totals regions)
│   │   ├── orientation.py       # Image rotation correction for OCR readiness
│   │   ├── processor.py         # Main preprocessing orchestrator (calls all steps)
│   │   └── segmentation.py      # Invoice region segmentation and cropping
│   │
│   ├── scanning/
│   │   ├── engine.py            # GLM-OCR + GLM-4.6V-Flash pipeline orchestrator
│   │   ├── ocr_parser.py        # OCR result JSON parsing and field extraction
│   │   ├── prompts.py           # LLM prompt templates (system, extraction, validation)
│   │   └── validator.py         # Math validation (totals, tax, discounts) + confidence scoring
│   │
│   ├── tracking/
│   │   ├── accuracy.py          # Accuracy metrics tracking (TP/FP/FN per field)
│   │   └── api_usage.py         # GLM API token/cost tracking and quota monitoring
│   │
│   ├── views.py                 # Django REST Framework API views (POST /scan, GET /status)
│   ├── urls.py                  # URL routing (/api/v1/scan, /api/v1/status)
│   └── serializers.py           # DRF serializers for request/response validation
│
├── smartscanner/
│   ├── settings.py              # Django configuration (SECRET_KEY, CORS, API keys from .env)
│   ├── urls.py                  # Root URL config and app routing
│   ├── wsgi.py                  # WSGI entry point for production
│   └── asgi.py                  # ASGI entry point (not actively used)
│
├── tests/
│   ├── test_scanning.py
│   ├── test_memory.py
│   ├── test_preprocessing.py
│   ├── test_integration.py
│   ├── test_api.py
│   ├── test_tracking.py
│   ├── test_validator.py
│   ├── test_inference.py
│   ├── test_categorizer.py
│   ├── test_corrections.py
│   ├── test_layout.py
│   ├── test_engine_layout.py
│   ├── test_segmentation_layout.py
│   └── integration_helpers.py   # Shared test fixtures and mock utilities
│
├── manage.py
├── pytest.ini
└── requirements.txt
```

**Architecture today:** JSON files under `backend/data/` for all storage. Linear pipeline (image → preprocessing → GLM-OCR → parse → validate → memory). No auth, no agent loop, no chat, single-process threading lock on JSON writes.

---

## Target Structure (Restaurant OS)

What you're building toward. These are the files you'll create.

```
src/restaurant_os/
├── agents/
│   ├── supervisor.py            # LangGraph supervisor node (MVP: single ReAct graph)
│   ├── scanner_agent.py         # Restaurant context-aware invoice scanner agent
│   └── memory.py                # Hybrid memory (Redis short-term + pgvector long-term RAG)
│
├── llm/
│   ├── glm_client.py            # Async GLM-4-Flash + GLM-OCR wrapper (OpenAI-compatible)
│   └── prompts/
│       ├── scanner_prompt.yaml  # Invoice extraction system prompt
│       ├── validation_prompt.yaml
│       └── system_prompt.yaml   # Agent-level system instruction
│
├── tools/
│   ├── registry.py              # Dynamic tool registration and routing for LangGraph
│   ├── supplier_scanner.py      # DuckDuckGo search tool for unknown suppliers
│   ├── image_processor.py       # Image preprocessing and orientation (ported)
│   ├── calculator.py            # Math validation and confidence scoring (ported)
│   ├── db_tools.py              # Vector DB query + relational DB lookup tools
│   └── review_tools.py          # Google Places + Yelp integration (v1.0 future)
│
├── core/
│   ├── models.py                # Pydantic models (RestaurantContext, ScanResult, InvoiceLineItem)
│   ├── config.py                # Settings management (GLM key, DB URL, Clerk key from .env)
│   └── traces.py                # Learning trace instrumentation
│
├── db/
│   ├── models.py                # SQLAlchemy tables (restaurants, suppliers, invoices, embeddings)
│   ├── repositories.py          # CRUD layer (ported from json_store.py logic)
│   └── vector.py                # pgvector HNSW operations + RAG retriever
│
├── api/
│   └── v1/
│       ├── routes.py            # FastAPI routes (/chat, /scan, /status, /traces)
│       └── schemas.py           # Pydantic request/response schemas
│
├── auth/
│   └── clerk.py                 # Clerk JWT verification and user context extraction
│
├── observability/
│   └── reasoning_logger.py      # Full reasoning trace per agent run
│
├── tasks/
│   └── celery_app.py            # Background task queue for long-running scans
│
└── tests/
    ├── agent_evals/             # Agent accuracy evaluation suite
    ├── fixtures/
    │   ├── mock_suppliers.py
    │   └── mock_pos_data.py
    └── integration_helpers.py

docker-compose.yml               # Postgres 16 + pgvector, Redis 7, FastAPI app
.env.example                     # Template for required env vars
pyproject.toml                   # ruff, pyright, pytest, pre-commit config
```

**Architecture target:** PostgreSQL + pgvector for all storage. LangGraph ReAct agent loop (reason → act → observe → repeat). FastAPI async gateway with SSE streaming. Redis session state. Celery background tasks. Clerk auth with restaurant context injection.

---

## Learning Path Overview

| # | Technology | Core Concept Unlocked | Migration Work |
|---|---|---|---|
| 1 | FastAPI | Async HTTP gateway | Replace Django views + routing |
| 2 | Pydantic v2 | Type-safe tool I/O | Replace DRF serializers + Django settings |
| 3 | LangGraph | ReAct loop, state graphs | New agent layer on top of ported pipeline |
| 4 | GLM-4-Flash tool calling | LLM tool calling, prompt engineering | Port engine + prompts + OCR parser |
| 5 | DuckDuckGo + image tools | Tool registration and execution | Port preprocessing + validator as agent tools |
| 6 | PostgreSQL + SQLAlchemy 2.0 | Relational context for agent memory | Port json_store + corrections to SQLAlchemy |
| 7 | pgvector | Vector RAG, embedding retrieval | Port inference + categorizer to RAG |
| 8 | Redis | Stateful agents, turn-by-turn context | New session layer |
| 9 | Celery | Async agent tasks, event-driven scanning | New background task layer |
| 10 | Clerk | Auth in agent APIs | New auth layer |
| 11 | LangSmith | Observability, reasoning traces | Port accuracy + api_usage tracking |
| 12 | DeepEval (v1.0) | LLM evaluation, faithfulness metrics | Port test suite to agent evals |
| 13 | LangGraph Supervisor (v1.0) | Multi-agent coordination | New multi-agent layer |
| 14 | Docker Compose | Containerized dev environment | New infra layer |

---

### 1. FastAPI

**What it is** — FastAPI is a Python web framework built on top of Starlette and Pydantic. It handles HTTP requests asynchronously using Python's `async`/`await` syntax, meaning a single worker can serve many concurrent requests without blocking. It auto-generates OpenAPI docs from your type annotations.

**Why it's in Restaurant OS** — Django's synchronous request cycle is a bottleneck when endpoints need to stream LLM tokens, wait on vector DB queries, and call external APIs concurrently. FastAPI's native async support and Server-Sent Events (SSE) capability make it the right gateway for an agent that streams its reasoning in real time.

**What you'll build** — `src/restaurant_os/api/v1/routes.py` (endpoints: `POST /api/v1/chat` with SSE streaming, `POST /api/v1/scan`, `GET /api/v1/health`) and `src/restaurant_os/api/app.py` (FastAPI app instance, middleware, lifespan events).

**What you'll learn** — Async HTTP gateway design. How `async def` endpoints differ from Django's `def` views. How SSE streaming works (yielding chunks from an async generator). How FastAPI's dependency injection replaces Django middleware for auth and DB sessions.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/views.py` | `[NEW - REPLACE]` | `api/v1/routes.py` — FastAPI async route handlers replace DRF class-based views |
| `backend/scanner/urls.py` | `[DEPRECATED]` | URL routing moves into FastAPI's `include_router()` declarations in `api/v1/routes.py` |
| `backend/smartscanner/urls.py` | `[DEPRECATED]` | Root routing replaced by FastAPI app factory in `api/app.py` |
| `backend/smartscanner/settings.py` | `[DEPRECATED]` | Django config replaced by Pydantic settings in `core/config.py` (Section 2) |
| `backend/smartscanner/wsgi.py` | `[DEPRECATED]` | WSGI replaced by uvicorn ASGI server |

**Checkpoint** — Write a minimal FastAPI endpoint that accepts `POST {"message": "hello"}` and returns an SSE stream yielding three chunks with 1-second delays. Run with `uvicorn`. Can you explain why Django would need Django Channels for this, while FastAPI handles it natively with a plain async generator?

---

### 2. Pydantic v2

**What it is** — Pydantic validates and serializes data against typed schemas you define as Python classes. v2 is a ground-up Rust-core rewrite, 5–20x faster than v1. You already use Python dicts in SmartScanner — Pydantic replaces them with validated, serializable models with a `.model_json_schema()` method that generates JSON schemas automatically.

**Why it's in Restaurant OS** — Every boundary in the agent system needs a contract: API request/response shapes, tool input/output schemas (passed to the LLM for tool calling), and internal state objects in LangGraph. FastAPI uses Pydantic natively for request parsing. The GLM tool-calling interface needs JSON schemas — Pydantic generates them from your model definitions automatically.

**What you'll build** — `src/restaurant_os/core/models.py` (domain models: `ChatMessage`, `ScanResult`, `SupplierInfo`, `InvoiceLineItem`, `RestaurantContext`) and `src/restaurant_os/api/v1/schemas.py` (API-layer schemas: `ChatRequest`, `ChatStreamEvent`, `ScanRequest`, `ScanResponse`). Also `src/restaurant_os/core/config.py` — a Pydantic `BaseSettings` class that replaces Django's `settings.py`.

**What you'll learn** — Type-safe tool I/O. How a Pydantic model doubles as a JSON schema for LLM tool calling. How `model_validator` and `field_validator` replace SmartScanner's manual validation logic. Discriminated unions for polymorphic SSE event types. `BaseSettings` for loading config from `.env` without Django's settings module.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/serializers.py` | `[NEW - REPLACE]` | `api/v1/schemas.py` — Pydantic schemas replace DRF serializers for request/response validation |
| `backend/smartscanner/settings.py` | `[DEPRECATED]` | `core/config.py` — Pydantic `BaseSettings` loads `GLM_OCR_API_KEY`, `DATABASE_URL`, `CLERK_SECRET_KEY` from `.env` |

**Checkpoint** — Define a Pydantic model `ToolCall` with a validator rejecting tool names containing `/`, `\`, or `..`. Call `.model_json_schema()`. Look at the output — can you identify which parts of the schema the LLM uses to decide how to fill in `arguments`?

---

### 3. LangGraph

**What it is** — LangGraph is a framework for building stateful, graph-based agent workflows. Nodes are functions ("call the LLM", "execute a tool", "check if done"); edges define transitions including conditional branching; a typed state object flows through and is updated by each node. It is not LangChain — LangGraph uses graph primitives instead of chains.

**Why it's in Restaurant OS** — The ReAct (Reason + Act) loop is a state machine: the LLM reasons about the request, selects a tool, executes it, observes the result, then loops or responds. LangGraph makes this state machine explicit and inspectable. The graph structure also makes it straightforward to extend from single-agent (MVP) to multi-agent (v1.0) by replacing or adding nodes.

**What you'll build** — `src/restaurant_os/agents/supervisor.py` — a ReAct loop with three nodes: `reason` (LLM call with tool schemas), `act` (tool execution), `respond` (final answer). Conditional edge from `reason`: if tool call requested → `act`, else → `respond`. `act` → `reason` to loop back with the tool result. `AgentState` typed dict carries `messages`, `tool_calls`, `restaurant_context`. Also `src/restaurant_os/agents/scanner_agent.py` — the restaurant context-aware scanner logic that evolves from SmartScanner's pipeline concept.

**What you'll learn** — The ReAct loop. How state graphs work (nodes mutate state, edges route based on state). Conditional edges. Checkpointing for resumable agent runs. Why a graph is better than a `while` loop: it's inspectable via LangSmith, traceable step-by-step, and composable into a supervisor later.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/scanning/engine.py` (pipeline concept) | `[NEW]` | `agents/scanner_agent.py` — the linear pipeline becomes a LangGraph node. The "call GLM, parse, validate, update memory" steps become discrete graph nodes. |
| — | `[NEW]` | `agents/supervisor.py` — the ReAct orchestrator has no SmartScanner equivalent; it's the agent brain |

**Checkpoint** — Sketch a LangGraph graph for "Find me a cheaper supplier for salmon": look up current supplier from DB, search the web, compare prices, respond. How many nodes? Where are the conditional edges? What fields does `AgentState` need to carry between nodes?

---

### 4. GLM-4-Flash Tool Calling

**What it is** — You already use GLM-4-Flash in SmartScanner. Tool calling is the structured mode where you send the model a list of tool definitions (JSON schemas) alongside the conversation, and instead of returning free text, it returns a structured `tool_calls` array specifying which tool to invoke with what arguments. This is the mechanism that lets the LLM "act" in the ReAct loop.

**Why it's in Restaurant OS** — The agent's ability to take actions (search, query DB, scan an invoice) depends on the LLM producing structured tool calls. The async wrapper you build here handles retries, token tracking, streaming, and prompt versioning. Prompt versioning via YAML means you can iterate on prompts without code changes and track prompt history in git.

**What you'll build** — `src/restaurant_os/llm/glm_client.py` (async client class with `achat(messages, tools, stream)`, error handling, token counting) and `src/restaurant_os/llm/prompts/` (YAML files: `system_prompt.yaml`, `scanner_prompt.yaml`, `validation_prompt.yaml`).

**What you'll learn** — How the LLM receives tool schemas, decides which to call, and how tool results get appended back to message history for the next reasoning step. Async generator patterns for streaming. Why YAML prompt versioning matters when debugging why the agent made a bad decision in a specific run.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/scanning/engine.py` | `[PORT]` | `llm/glm_client.py` — extract the GLM-OCR + GLM-4.6V-Flash API call logic; rewrite as async; add tool-calling support |
| `backend/scanner/scanning/prompts.py` | `[PORT]` | `llm/prompts/*.yaml` — move hardcoded prompt strings to versioned YAML files |
| `backend/scanner/scanning/ocr_parser.py` | `[PORT]` | Integrated into `llm/glm_client.py` — OCR result parsing becomes part of the async GLM response handler |

**Checkpoint** — Using the ZhipuAI SDK directly (not your wrapper yet), send a chat request with a `search_supplier` tool schema and message "Find salmon suppliers in Seattle." Does the model return a `tool_calls` array? Send the same message without `tools` — how does the response differ?

---

### 5. DuckDuckGo Search Tool + Image Preprocessing Tools

**What it is** — The `duckduckgo-search` Python library provides zero-cost, no-API-key web search. In Restaurant OS it's wrapped as an agent tool — the LLM decides to invoke it during its reasoning loop. This section also covers how SmartScanner's preprocessing and validation code becomes agent tools (callable by the LLM the same way).

**Why it's in Restaurant OS** — The agent needs live answers ("Who supplies organic salmon in my area?"). DuckDuckGo is the first tool you register, which makes it the vehicle for learning the full tool-registration pattern — tool schema → LLM calls it → your code executes → result goes back into message history → LLM reasons over it. Preprocessing and validation become tools so the scanner agent can call them within its ReAct loop.

**What you'll build** — `src/restaurant_os/tools/supplier_scanner.py` (DuckDuckGo search, Pydantic input schema, result post-processing), `src/restaurant_os/tools/registry.py` (dynamic tool registration for LangGraph), `src/restaurant_os/tools/image_processor.py` (ported from preprocessing), `src/restaurant_os/tools/calculator.py` (ported from validator), and `src/restaurant_os/tools/db_tools.py` (vector + relational query tools).

**What you'll learn** — Tool registration and execution. The complete tool-calling loop. Grounding: shaping raw search results so the LLM cites them rather than hallucinating. How existing business logic (preprocessing, math validation) gets wrapped as tools without rewriting the core logic.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/preprocessing/processor.py` | `[PORT]` | `tools/image_processor.py` — preprocessing orchestrator becomes a callable agent tool with a Pydantic input schema |
| `backend/scanner/preprocessing/analyzer.py` | `[PORT]` | Integrated into `tools/image_processor.py` |
| `backend/scanner/preprocessing/orientation.py` | `[PORT]` | Integrated into `tools/image_processor.py` |
| `backend/scanner/preprocessing/layout.py` | `[PORT]` | Integrated into `tools/image_processor.py` |
| `backend/scanner/preprocessing/segmentation.py` | `[PORT]` | Integrated into `tools/image_processor.py` |
| `backend/scanner/scanning/validator.py` | `[PORT]` | `tools/calculator.py` — math validation + confidence scoring logic preserved; wrapped as an agent tool |
| — | `[NEW]` | `tools/supplier_scanner.py` — DuckDuckGo search tool (no SmartScanner equivalent) |
| — | `[NEW]` | `tools/registry.py` — dynamic tool registration (no SmartScanner equivalent) |

**Checkpoint** — Implement `search_suppliers("organic salmon Seattle", max_results=5)` returning `ToolResult` objects. Call `.model_json_schema()` on the Pydantic input model. Compare to the tool schema you sent to GLM in Section 4 — do they match structurally? If not, why does the mismatch matter?

---

### 6. PostgreSQL + SQLAlchemy 2.0

**What it is** — PostgreSQL is a relational database. SQLAlchemy 2.0's new API supports fully async access via `asyncpg`. SmartScanner's JSON files with a threading lock work for single-user dev but break under concurrent access, have no query capability, and cannot enforce relational integrity. PostgreSQL replaces JSON file storage with proper tables, indexes, and transactions.

**Why it's in Restaurant OS** — The agent needs structured, queryable, relational context: current suppliers, invoices, line items, menus, cost trends. JSONB columns give you flexibility for semi-structured data (raw OCR output) without abandoning relational structure. `tenant_id` columns on every table prepare the schema for multi-restaurant use.

**What you'll build** — `src/restaurant_os/db/models.py` (SQLAlchemy 2.0 declarative models: `Restaurant`, `Supplier`, `Invoice`, `LineItem`, `UserCorrection`), `src/restaurant_os/db/repositories.py` (CRUD layer), `src/restaurant_os/db/session.py` (async session factory and FastAPI dependency).

**What you'll learn** — Relational context as long-term agent memory. Async SQLAlchemy patterns (`async_session`, `select()`, `await session.execute()`). The repository pattern for keeping SQL out of agent code. JSONB columns for flexible storage alongside structured columns. How `tenant_id` enables multi-restaurant scoping.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/memory/json_store.py` | `[PORT]` | `db/repositories.py` — the JSON CRUD operations (load supplier, save supplier, list all) become async SQLAlchemy repository methods; supplier ID validation logic is preserved |
| `backend/scanner/memory/corrections.py` | `[PORT]` | `db/models.py` — correction tracking moves from JSON files to a `UserCorrection` SQLAlchemy table with proper foreign keys and timestamps |
| `backend/scanner/memory/interface.py` | `[DEPRECATED]` | The memory public API is replaced by repository classes with explicit async signatures |

**Checkpoint** — Write an async function that creates an `AsyncSession`, inserts a `Supplier` with two `Invoice` records (three `LineItem` rows each), then queries "total spend by supplier in the last 7 days" using `select` with `func.sum`. Does it return the expected sum? If you remove `await` from `session.execute()`, what error do you get and why?

---

### 7. pgvector

**What it is** — pgvector is a PostgreSQL extension adding a `vector` column type and similarity search operators. You store embedding vectors, create an HNSW index, and query for nearest neighbors via cosine similarity — turning PostgreSQL into a vector database without adding a separate service.

**Why it's in Restaurant OS** — SmartScanner's `inference.py` does lookup-based field inference: exact match on supplier name → return previously seen values. This breaks on variations ("ABC Foods" vs "ABC Food Co.") and can't find related records semantically. pgvector's embedding similarity replaces keyword matching with semantic retrieval, which is the "R" in RAG. Supplier categorization via `categorizer.py` also improves: instead of keyword rules, vector similarity clusters suppliers by domain automatically.

**What you'll build** — `src/restaurant_os/db/vector.py` (embed text, store in pgvector columns, HNSW similarity search) and the RAG portion of `src/restaurant_os/agents/memory.py` (retriever: embed the user's message, find top-k similar records, inject into LLM context).

**What you'll learn** — Vector RAG and embedding retrieval. How text becomes a fixed-length float vector. How cosine similarity measures semantic closeness. How HNSW makes nearest-neighbor search fast. The retrieval count tradeoff: too few misses context; too many dilutes signal or blows the context window.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/memory/inference.py` | `[PORT]` | `agents/memory.py` (RAG retriever portion) — lookup-based inference replaced by embedding similarity search via pgvector |
| `backend/scanner/memory/categorizer.py` | `[PORT]` | `agents/memory.py` — keyword-based categorization replaced by vector similarity clustering |
| — | `[NEW]` | `db/vector.py` — pgvector HNSW operations (no SmartScanner equivalent) |

**Checkpoint** — Store embeddings for "fresh Atlantic salmon fillet", "organic chicken breast", "wild-caught Pacific cod." Query nearest neighbor for "fish." Which comes back first? Does the ranking match your intuition? If not, what does that tell you about the embedding model's understanding of domain vocabulary?

---

### 8. Redis

**What it is** — Redis is an in-memory key-value store with microsecond reads/writes. In Restaurant OS it serves two roles: short-term agent memory (conversation state between HTTP requests) and message broker for Celery background tasks.

**Why it's in Restaurant OS** — HTTP is stateless. When a user sends message #5, the server needs the full conversation history (messages 1–4 plus all tool calls and results) to pass to the LLM. Storing this in PostgreSQL on every request is slow for the hot path. Redis stores active session state with sub-millisecond reads and automatic TTL-based expiration. SmartScanner had no concept of multi-turn conversation state at all.

**What you'll build** — The session management portion of `src/restaurant_os/agents/memory.py`: `save_turn(session_id, messages)`, `load_session(session_id)`, `expire_session(session_id)`. The memory module has two backends: Redis for session state (short-term), PostgreSQL+pgvector for knowledge retrieval (long-term).

**What you'll learn** — Stateful agents and layered memory architecture. How to serialize Pydantic models to/from Redis (`.model_dump_json()` / `.model_validate_json()`). TTLs for memory hygiene. Why session store and knowledge store are separated — different access patterns, retention policies, and consistency requirements.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| — | `[NEW]` | `agents/memory.py` (session state portion) — SmartScanner had no conversation state; this is entirely new |

**Checkpoint** — Implement `save_turn` and `load_session` with `redis.asyncio`. Store a three-turn conversation with 60-second TTL. Load it back — all three turns intact? Wait 61 seconds and load again — what do you get? If the server crashes mid-turn, is session state consistent? What would you need to add to guarantee it?

---

### 9. Celery

**What it is** — Celery is a distributed task queue. Functions decorated with `@celery_app.task` get sent to a message broker (Redis) instead of executing inline. Worker processes pick them up asynchronously. Celery Beat schedules tasks on a recurring interval.

**Why it's in Restaurant OS** — Scanning a batch of invoices or running weekly cost reports is too slow for a synchronous request cycle. Celery lets the API return a task ID immediately and execute the work in the background. Celery Beat enables proactive agent behavior: re-scan supplier prices every Monday without user intervention. SmartScanner had no background task system.

**What you'll build** — `src/restaurant_os/tasks/celery_app.py` (Celery instance configured with Redis broker) and `src/restaurant_os/tasks/scanning.py` (`scan_invoice_batch`, `scheduled_supplier_rescan` tasks). Plus a `POST /api/v1/scan/batch` endpoint that enqueues a batch scan task and returns the task ID.

**What you'll learn** — Async tasks and event-driven scanning. How task queues decouple "request work" from "execute work." Task retries, dead-letter handling, and idempotency (a retried task must not create duplicate invoices).

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| — | `[NEW]` | `tasks/celery_app.py` — SmartScanner had no background task layer; this is entirely new |

**Checkpoint** — Define task `add(x, y)` with 5-second `time.sleep`. Call `.delay(2, 3)`. Check `result.ready()` immediately — False. Wait, then `result.get()` — 5. Make it fail on attempt #1 and succeed on retry with `max_retries=2, retry_backoff=True`. Verify it retries and succeeds. What happens with `max_retries=0`?

---

### 10. Clerk

**What it is** — Clerk is a third-party auth service handling sign-up, sign-in, session management, and JWT issuance. Your backend verifies JWTs against Clerk's public keys and extracts user identity — no password hashing, email verification, or session management to build yourself.

**Why it's in Restaurant OS** — Every query, tool call, and DB lookup is scoped to a specific restaurant. Clerk JWTs carry a `restaurant_id` claim (set via Clerk's metadata), so auth and restaurant-context injection happen in one step. Without this, the agent might retrieve restaurant B's data while serving restaurant A — both a bug and a security violation. SmartScanner had no auth at all.

**What you'll build** — `src/restaurant_os/auth/clerk.py` — a FastAPI dependency that extracts + verifies the JWT (using Clerk's cached JWKS endpoint), extracts `user_id` and `restaurant_id`, returns an `AuthContext` Pydantic model. Plus middleware to reject requests with missing/invalid tokens before they reach route handlers.

**What you'll learn** — JWT mechanics (header.payload.signature, public key verification, claims). FastAPI dependency composition (auth → DB session → route handler). Why restaurant-scoping is a security requirement, not just a UX feature.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| — | `[NEW]` | `auth/clerk.py` — SmartScanner had no auth; this is entirely new |

**Checkpoint** — Decode a sample Clerk JWT at jwt.io. Identify the `sub`, `exp`, and custom claims. Write the FastAPI dependency. What happens if the token is expired? If someone sends a valid JWT from a different Clerk application, does your verification reject it — and how?

---

### 11. LangSmith

**What it is** — LangSmith is an observability platform for LLM applications. It captures traces of every LLM call, tool execution, and agent step — showing exactly what the LLM saw, decided, and returned. Think APM but for agent reasoning.

**Why it's in Restaurant OS** — When the agent gives a wrong answer, you need to know why: bad retrieval? LLM ignored the tool result? Tool returned bad data? Without traces you're guessing. LangSmith replaces and extends SmartScanner's ad-hoc accuracy and API usage tracking with a structured, queryable trace system.

**What you'll build** — `src/restaurant_os/observability/reasoning_logger.py` — LangGraph has native LangSmith support via env vars (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`). The custom module adds structured metadata to traces: `restaurant_id`, `session_id`, `user_intent`, and a self-assessment score the agent generates for its own response quality. Also `src/restaurant_os/core/traces.py` for learning instrumentation (token cost, tool call count, accuracy score per run).

**What you'll learn** — Trace structure (runs, child runs, inputs, outputs, metadata). Custom metadata for filtering and regression detection. Self-assessment: the agent evaluates its own response (1–5) and logs the score for aggregate quality monitoring. Privacy implications of traces containing user data.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/scanner/tracking/accuracy.py` | `[PORT]` | `observability/reasoning_logger.py` — TP/FP/FN accuracy metrics are preserved; they become fields in the structured trace rather than standalone JSON files |
| `backend/scanner/tracking/api_usage.py` | `[PORT]` | `observability/reasoning_logger.py` — token/cost tracking becomes trace metadata (cost_usd, token_count fields) in the `agent_runs` table |

**Checkpoint** — Run a full agent conversation with LangSmith tracing enabled. Find the LLM call node — what's the full prompt including system message and tool schemas? Find the tool execution node — input and output. Now find a trace where the agent gave a wrong answer. Can you identify from the trace alone where the reasoning went wrong?

---

### 12. DeepEval (v1.0)

**What it is** — DeepEval is a testing framework for LLM outputs with metrics like faithfulness (does the answer stick to retrieved context?), answer relevancy, and hallucination detection — all scored by an evaluator LLM (G-Eval) rather than string matching.

**Why it's in Restaurant OS** — Traditional unit tests can verify that your tool returns correct data, but they can't verify that the agent's natural language response is accurate and grounded. When you change a prompt, add a tool, or update retrieval, DeepEval metrics are your regression suite for end-to-end answer quality. SmartScanner's pytest suite tested the pipeline in isolation — DeepEval tests the agent's answers semantically.

**What you'll build** — `src/restaurant_os/tests/agent_evals/` — test cases specifying input (user message + restaurant context), expected retrieval context, and actual agent output scored by DeepEval metrics. Tests like `test_scanner_faithfulness` and `test_search_grounding` run in CI with quality thresholds (e.g., faithfulness > 0.8).

**What you'll learn** — G-Eval and the faithfulness metric. Why exact-match testing fails for LLM apps. How faithfulness is measured (every claim in the answer must be traceable to retrieved context). Setting quality thresholds as CI gates. The limitations of evaluator LLMs.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/tests/test_scanning.py` | `[PORT]` | `tests/agent_evals/test_scanner_faithfulness.py` — field extraction tests become DeepEval faithfulness test cases |
| `backend/tests/test_integration.py` | `[PORT]` | `tests/agent_evals/test_end_to_end.py` — end-to-end scan tests become agent eval test cases |
| `backend/tests/test_memory.py` | `[PORT]` | `tests/agent_evals/test_rag_retrieval.py` — memory tests become RAG retrieval accuracy tests |
| `backend/tests/test_validator.py` | `[PORT]` | `tests/agent_evals/test_math_validation.py` — math validation tests port directly (logic unchanged) |
| `backend/tests/test_preprocessing.py` | `[PORT]` | `tests/agent_evals/` — preprocessing pipeline tests |
| `backend/tests/test_api.py` | `[PORT]` | `tests/agent_evals/` — API contract tests rewritten for FastAPI |
| `backend/tests/test_tracking.py` | `[PORT]` | `tests/agent_evals/` — tracking tests become observability checks |
| `backend/tests/test_inference.py` | `[PORT]` | `tests/agent_evals/test_rag_retrieval.py` — inference tests become vector retrieval accuracy tests |
| `backend/tests/test_categorizer.py` | `[PORT]` | `tests/agent_evals/` — categorization tests become vector similarity tests |
| `backend/tests/test_corrections.py` | `[PORT]` | `tests/agent_evals/` — correction tracking tests port with updated DB backend |
| `backend/tests/test_layout.py` + `test_engine_layout.py` + `test_segmentation_layout.py` | `[PORT]` | `tests/agent_evals/` — image processing pipeline tests |
| `backend/tests/integration_helpers.py` | `[PORT]` | `tests/integration_helpers.py` — shared fixtures preserved; GLM mocks updated for new async wrapper |
| — | `[NEW]` | `tests/fixtures/mock_suppliers.py`, `tests/fixtures/mock_pos_data.py` — new mock data for agent eval scenarios |

**Checkpoint** — Set up a DeepEval test case where retrieved context says "Supplier ABC charges $12.50/lb for salmon, minimum order 50 lbs." The agent's response adds "they also offer free delivery on orders over $500." Run the faithfulness metric. Does it flag the free delivery claim? If not, what does that tell you about the metric's sensitivity?

---

### 13. LangGraph Supervisor (v1.0)

**What it is** — A LangGraph supervisor is a meta-agent that routes tasks to specialized sub-agents. Instead of one agent with all tools, you have focused agents (scanner, reviews, POS) and a supervisor that classifies the request and dispatches to the right one.

**Why it's in Restaurant OS** — v1.0 adds a reviews agent and POS mock agent. A single agent with all their tools would have a bloated tool list, conflicting prompt instructions, and worse accuracy. The supervisor keeps each agent focused. It also handles multi-step tasks spanning agents — e.g., "Compare what reviewers say about our seafood with what we're paying for it" requires both the reviews and scanner agents with coordinated handoff.

**What you'll build** — An extended `src/restaurant_os/agents/supervisor.py` that becomes the routing layer with sub-graphs for `scanner_agent` and `reviews_agent`. Also `src/restaurant_os/tools/review_tools.py` (Google Places + Yelp integration).

**What you'll learn** — Multi-agent coordination. Specialization vs. generalization tradeoffs. Agent handoff in LangGraph (supervisor sets next node based on intent). Shared state across sub-graphs. Handling sub-agent failures without crashing the conversation.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `src/restaurant_os/agents/supervisor.py` (multi-agent) | `[FUTURE v1.0]` | Extend single-node MVP graph to supervisor pattern with multiple sub-agent sub-graphs |
| `src/restaurant_os/tools/review_tools.py` | `[FUTURE v1.0]` | Google Places + Yelp integration — deferred, no SmartScanner equivalent |

**Checkpoint** — Add a stub `reviews_agent` returning "Reviews analysis not yet implemented." Add a supervisor routing on keyword heuristic ("review"/"feedback" → reviews, else → scanner). Send "What are customers saying about our salmon, and how much are we paying for it?" Does the supervisor handle the handoff? What happens if the first sub-agent fails?

---

### 14. Docker Compose

**What it is** — Docker Compose defines and runs multi-container applications from a single `docker-compose.yml`. One command (`docker compose up`) starts every service with correct networking, volumes, environment variables, and health checks. `pyproject.toml` replaces `requirements.txt` with a modern Python project configuration that also configures ruff (linting), pyright (type checking), and pre-commit hooks.

**Why it's in Restaurant OS** — Restaurant OS depends on PostgreSQL+pgvector, Redis, a Celery worker, Celery Beat, and FastAPI. Setting these up manually on every developer machine is error-prone. Docker Compose standardizes the environment and documents the system's service topology. SmartScanner had no containerization.

**What you'll build** — `docker-compose.yml` at project root: `api` (FastAPI via uvicorn), `db` (PostgreSQL 16 with pgvector), `redis` (Redis 7), `worker` (Celery worker), `beat` (Celery Beat). With volumes, health checks, `.env` injection, and startup dependency ordering. A shared `Dockerfile` for `api`, `worker`, and `beat`. `pyproject.toml` replacing `requirements.txt`.

**What you'll learn** — Infrastructure-as-code. Docker image layering. Compose networking (services communicate by hostname: `db:5432`, `redis:6379`). Health checks preventing startup race conditions. Volume persistence. Environment variable injection. This translates almost directly to a Kubernetes manifest or cloud service definition.

**Migration**

| SmartScanner File | Action | Restaurant OS Target |
|---|---|---|
| `backend/requirements.txt` | `[DEPRECATED]` | `pyproject.toml` — modern Python project config with ruff, pyright, and dependency groups |
| `backend/pytest.ini` | `[DEPRECATED]` | Pytest config moves into `pyproject.toml` `[tool.pytest.ini_options]` section |
| — | `[NEW]` | `docker-compose.yml` — multi-container orchestration (SmartScanner had none) |
| — | `[NEW]` | `.env.example` — template for required env vars |
| — | `[NEW]` | `pyproject.toml` — replaces requirements.txt + pytest.ini |

**Checkpoint** — Write and run the full compose file. Verify: (1) API answers `GET /api/v1/health`, (2) pgvector extension installed (`SELECT * FROM pg_extension WHERE extname = 'vector'`), (3) Redis answers `PING`, (4) Celery worker logs show registered tasks. Stop `db` — does the health check correctly report the database as unhealthy?

---

## How to Use This Curriculum

Work through sections in order. Each section assumes you completed the previous. Checkpoints are not optional — they are the minimum proof of understanding before building on that section. The **Migration** table in each section tells you exactly which SmartScanner files to work with: `[PORT]` means carry the logic forward into a new file, `[NEW - REPLACE]` means this file is superseded, `[DEPRECATED]` means delete it, `[NEW]` means build from scratch, `[FUTURE v1.0]` means defer it.

**After sections 1–5:** Working FastAPI app, Pydantic contracts, LangGraph ReAct loop, async GLM client, DuckDuckGo tool, preprocessor tool, calculator tool. The scanner pipeline from SmartScanner is operational inside the agent framework.

**After sections 6–11:** Full persistent memory (PostgreSQL + pgvector + Redis), Clerk auth, Celery background tasks, LangSmith observability. Restaurant OS MVP is complete.

**Sections 12–14:** DeepEval regression suite, multi-agent supervisor (v1.0), reproducible Docker dev environment.
