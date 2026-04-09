# Project Directory Scaffold: SmartScanner → Restaurant OS

This document maps the current SmartScanner backend structure to the target Restaurant OS architecture, identifying which components port, which are new, and which are deferred to v1.0.

---

## Section 1: Current App Structure (SmartScanner)

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
│   ├── test_scanning.py         # Unit tests for OCR parsing and field extraction
│   ├── test_memory.py           # JSON store and memory inference tests
│   ├── test_preprocessing.py    # Image processing pipeline tests
│   ├── test_integration.py      # End-to-end scan workflow tests
│   ├── test_api.py              # API endpoint and serializer tests
│   ├── test_tracking.py         # Accuracy and usage metrics tests
│   ├── test_validator.py        # Math validation and confidence scoring tests
│   ├── test_inference.py        # Memory inference and field lookup tests
│   ├── test_categorizer.py      # Supplier categorization tests
│   ├── test_corrections.py      # User correction tracking tests
│   ├── test_layout.py           # Layout detection tests
│   ├── test_engine_layout.py    # Engine + layout integration tests
│   ├── test_segmentation_layout.py # Segmentation + layout integration tests
│   └── integration_helpers.py   # Shared test fixtures and mock utilities
│
├── manage.py                    # Django CLI management command entry
├── pytest.ini                   # Pytest configuration (DJANGO_SETTINGS_MODULE)
└── requirements.txt             # Python dependencies (Django, DRF, Pillow, opencv-python)
```

**Key Architecture Notes:**
- **Storage:** JSON files under `backend/data/` (supplier profiles, run history, metrics).
- **Pipeline:** Image → Preprocessing → GLM-OCR → LLM Extraction → Validation → Memory Update.
- **Memory:** Lookup-based inference from supplier profiles; no embeddings.
- **API:** Django REST Framework with single-process JSON file locking (not production-ready for multiple workers).

---

## Section 2: Target Structure (Restaurant OS)

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
│       ├── validation_prompt.yaml # Math validation prompt
│       └── system_prompt.yaml   # Agent-level system instruction
│
├── tools/
│   ├── registry.py              # Dynamic tool registration and routing for LangGraph
│   ├── supplier_scanner.py      # DuckDuckGo search tool for unknown suppliers
│   ├── image_processor.py       # Image preprocessing and orientation (ported from preprocessing/)
│   ├── calculator.py            # Math validation and confidence scoring (ported from validator.py)
│   ├── db_tools.py              # Vector DB query + relational DB lookup tools
│   └── review_tools.py          # Google Places + Yelp integration (v1.0 future)
│
├── core/
│   ├── models.py                # Pydantic models (RestaurantContext, ScanResult, InvoiceLineItem)
│   ├── config.py                # Settings management (GLM key, DB URL, Clerk key from .env)
│   └── traces.py                # Learning trace instrumentation (input, reasoning, output)
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
│   └── reasoning_logger.py      # Full reasoning trace per agent run (input, decisions, output)
│
├── tasks/
│   └── celery_app.py            # Background task queue for long-running scans
│
└── tests/
    ├── agent_evals/             # Agent accuracy evaluation suite (extraction + math)
    ├── fixtures/
    │   ├── mock_suppliers.py    # Mock restaurant supplier profiles
    │   └── mock_pos_data.py     # Mock POS transaction data
    └── integration_helpers.py   # Shared fixtures and utilities
│
docker-compose.yml               # Postgres 15 + pgvector, Redis 7, FastAPI app container
.env.example                     # Template for required env vars (GLM key, DB URL, Clerk key)
pyproject.toml                   # Python project config (ruff, pyright, pytest, pre-commit)
```

**Key Architecture Notes:**
- **LLM:** GLM-4-Flash (async wrapper) + GLM-OCR; no fallback to other providers.
- **Storage:** PostgreSQL + pgvector for embeddings and long-term memory; Redis for short-term cache.
- **Agent:** LangGraph ReAct single-node graph with tool calling for restaurant context injection.
- **Memory:** Vector RAG for semantic lookup + relational DB for structured queries.
- **Auth:** Clerk JWT verification for API authentication.
- **Observability:** Full reasoning trace per run (inputs, thoughts, tool calls, outputs).

---

## Section 3: Gap Analysis Table

| Path | Status | Notes |
|------|--------|-------|
| `backend/scanner/scanning/engine.py` | `[PORT]` | GLM client logic and pipeline orchestration → `llm/glm_client.py` |
| `backend/scanner/scanning/prompts.py` | `[PORT]` | Prompt templates → `llm/prompts/*.yaml` (YAML-based system prompts) |
| `backend/scanner/scanning/ocr_parser.py` | `[PORT]` | OCR result JSON parsing → integrated into `llm/glm_client.py` |
| `backend/scanner/preprocessing/*` | `[PORT]` | Image analysis, orientation, segmentation → `tools/image_processor.py` |
| `backend/scanner/scanning/validator.py` | `[PORT]` | Math validation and confidence tiers → `tools/calculator.py` |
| `backend/scanner/memory/json_store.py` | `[PORT]` | JSON CRUD + supplier ID validation → `db/repositories.py` (SQLAlchemy) |
| `backend/scanner/memory/inference.py` | `[PORT]` | Field value inference from memory → `agents/memory.py` (RAG retriever) |
| `backend/scanner/memory/categorizer.py` | `[PORT]` | Supplier categorization → integrated into `agents/memory.py` (vector similarity) |
| `backend/scanner/memory/corrections.py` | `[PORT]` | User feedback tracking → `db/models.py` (correction log table) |
| `backend/scanner/tracking/accuracy.py` | `[PORT]` | Accuracy metrics → `observability/reasoning_logger.py` + `db/models.py` |
| `backend/scanner/tracking/api_usage.py` | `[PORT]` | API token/cost tracking → `observability/reasoning_logger.py` (trace metadata) |
| `backend/scanner/views.py` | `[NEW - REPLACE]` | Django views → `api/v1/routes.py` (FastAPI) |
| `backend/scanner/serializers.py` | `[NEW - REPLACE]` | DRF serializers → `api/v1/schemas.py` (Pydantic) |
| `backend/tests/*` | `[PORT]` | Test suite → `tests/agent_evals/` (agentic tests) + `tests/fixtures/` (mocks) |
| `src/restaurant_os/agents/supervisor.py` | `[NEW]` | LangGraph single-node ReAct orchestrator (not in SmartScanner) |
| `src/restaurant_os/agents/scanner_agent.py` | `[NEW]` | Restaurant context-aware agent logic (evolution of engine.py) |
| `src/restaurant_os/tools/registry.py` | `[NEW]` | Dynamic tool registration for LangGraph (not in SmartScanner) |
| `src/restaurant_os/tools/supplier_scanner.py` | `[NEW]` | DuckDuckGo supplier lookup tool (not in SmartScanner) |
| `src/restaurant_os/db/models.py` | `[NEW]` | SQLAlchemy ORM (not in SmartScanner; replaces JSON files) |
| `src/restaurant_os/db/repositories.py` | `[NEW]` | CRUD abstractions (refactored from json_store.py) |
| `src/restaurant_os/db/vector.py` | `[NEW]` | pgvector HNSW operations (not in SmartScanner; new RAG capability) |
| `src/restaurant_os/auth/clerk.py` | `[NEW]` | Clerk JWT verification (not in SmartScanner) |
| `src/restaurant_os/core/config.py` | `[NEW]` | Settings management via Pydantic (not in SmartScanner) |
| `src/restaurant_os/observability/reasoning_logger.py` | `[NEW]` | Structured trace logging for agentic runs (not in SmartScanner) |
| `src/restaurant_os/tasks/celery_app.py` | `[NEW]` | Background task queue (not in SmartScanner; added for scalability) |
| `docker-compose.yml` | `[NEW]` | Multi-container orchestration (not in SmartScanner) |
| `pyproject.toml` | `[NEW]` | Modern Python project config (replaces requirements.txt + setup.py) |
| `agents/supervisor.py` (multi-agent) | `[FUTURE v1.0]` | Multi-agent coordination (deferred; MVP uses single ReAct node) |
| `tools/review_tools.py` | `[FUTURE v1.0]` | Google Places + Yelp review integration (out of scope for MVP) |
| `backend/smartscanner/settings.py` | `[DEPRECATED]` | Django config → `core/config.py` (Pydantic) + FastAPI app factory |
| `backend/scanner/urls.py` | `[DEPRECATED]` | URL routing → `api/v1/routes.py` (FastAPI) |

---

## Migration Strategy Summary

**Phase 1 (MVP):**
1. Port core scanning logic: GLM client, OCR parser, prompts → `llm/`
2. Port preprocessing, validation, memory inference → `tools/` + `agents/`
3. Migrate JSON storage → SQLAlchemy + pgvector
4. Replace Django views/serializers with FastAPI routes/schemas
5. Add Clerk auth and observability instrumentation
6. Port test suite to agentic evaluation framework

**Phase 2 (v1.0):**
7. Implement multi-agent supervisor (if needed)
8. Add Google Places + Yelp review tool
9. Optimize vector indexing for large-scale RAG
10. Add Celery task queue for long-running scans

**Deferred:**
- Multi-agent patterns (reserved for future complexity)
- Third-party review APIs (Phase 2 feature)
- Advanced prompt engineering (iterate based on eval results)
