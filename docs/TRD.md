# Technical Requirements Document (TRD)

**Project:** Restaurant AI Agent (codename: **Restaurant OS**)  
**Version:** 1.2 (Updated per User Answers + Additional Tool Evaluation)  
**Date:** 2026-04-07  
**Author:** Grok – Senior Tech Lead AI Agent Engineer  
**Status:** Fully aligned to PRD + user answers + additional tools review (ready for AI-agent implementation)

## 1. Introduction

### 1.1 Purpose

This TRD translates the provided Product Requirements Document (PRD) into precise, executable technical specifications, architecture, and engineering standards. It is written for AI agents (or human developers) to implement Restaurant OS with zero ambiguity, while embedding the learning objectives (tool calling → multi-agent → advanced agentic loops) directly into the code structure and instrumentation.

### 1.2 Scope

- **In-scope (MVP v0.1)**: Single-agent Supplier Scanner + conversational chatbot with restaurant-specific context, basic RAG, ReAct reasoning.
- **Future-proof design**: Clear extension points for v1.0 (multi-agent + POS/reviews) and v2.0 (end-to-end autonomous + multi-modal).
- **Out-of-scope (MVP)**: Real POS integration, voice, predictive ordering, full multi-tenancy. Frontend (React/TypeScript) will be implemented **after** backend completion. No additional tools from the queried list are required for MVP.

### 1.3 References

- PRD: Restaurant AI Agent (full content incorporated)
- Architectural Decision Records (ADRs) – one per major choice (to be generated during implementation)

## 2. System Overview & PRD Alignment

**Mission (from PRD)**: Accurate, zero-to-low-cost AI agent suite for restaurant owners (suppliers, operations, customer experience) that also teaches foundational AI agent development through progressive difficulty.

**Target Users (MVP)**: Restaurant owners/managers.  
**Key Differentiators**: Starts with zero-cost supplier scanner → evolves into full multi-agent intelligence.

**Success Metrics (technical mapping)**:

- Scanner accuracy on 50 suppliers: ≥90% query success with citations.
- Chat response: <5s, grounded, human-verifiable.
- Learning: Every agent run logs full reasoning trace + self-assessment metrics (accuracy, token cost, tool calls) for post-mortem review.

**Assumptions (confirmed from PRD + answers)**:

- Public supplier/review data availability.
- Mock data/APIs for POS during learning phases.
- LLM with strong tool-calling (GLM-4-Flash + GLM-OCR support).

## 3. Versions & Implementation Roadmap (Learning-Aligned)

| Version      | Difficulty   | Core Components (this TRD)                           | Learning Objectives                               | Go-Live Criteria                        |
| ------------ | ------------ | ---------------------------------------------------- | ------------------------------------------------- | --------------------------------------- |
| **MVP v0.1** | Beginner     | Single-agent scanner + chat (ReAct + basic RAG)      | Tool calling, ReAct, restaurant-context RAG       | 50 suppliers, 90% success, <5s response |
| **v1.0**     | Intermediate | Multi-agent orchestration + POS mock + Reviews Agent | LangGraph collaboration, vector memory, analytics | POS mock works, <5% hallucination       |
| **v2.0**     | Advanced     | Full agentic loops + taste profiles + proactive      | Long-term memory, multi-modal, eval frameworks    | >95% end-to-end accuracy                |

**Implementation Sprints (1-2 weeks MVP)**:  
Sprint 0: Core + DB + LLM wrapper  
Sprint 1: Supplier Scanner Agent (MVP)  
Sprint 2: Chat interface + traces + Clerk auth  
Sprint 3+: v1.0 extensions (modular)

## 4. Architecture & System Design (Every Level)

### 4.1 High-Level Architecture (C4 Context – text representation)

[Restaurant Owner (Web/Chat)]
│
▼
[FastAPI Gateway + Auth (Clerk) + Rate Limiter]
│
▼
[LangGraph Supervisor (Single-Agent for MVP)]
│
┌──────┼──────┐
│ │
▼ ▼
[Supplier Scanner Agent] [Tool Executor]
│ │
▼ ▼
[GLM-4-Flash + GLM-OCR LLM Service] [Tools: DuckDuckGo Search, DB Query, Calculator, Google Places, Yelp]
│
▼
[PostgreSQL 16 + pgvector (restaurant context + embeddings) + Redis (session state)]
text
**Style**: Graph-based agent workflows (LangGraph) – single graph for MVP, easily extended to multi-node for v1.0+. Event-driven for background scans.

### 4.2 Component Design (Level 2 – MVP + Extension Points)

| Component             | MVP Responsibility                         | Tech Choice (Best)                    | v1.0 / v2.0 Extension  |
| --------------------- | ------------------------------------------ | ------------------------------------- | ---------------------- |
| API Gateway           | Auth, streaming chat, OpenAPI              | FastAPI + Server-Sent Events          | Multi-tenant routes    |
| Agent Orchestrator    | ReAct loop, state machine                  | **LangGraph** (native GLM support)    | Multi-agent supervisor |
| Core Agent (Scanner)  | Supplier discovery + context RAG           | LangGraph node + ReAct                | Reviews + POS agents   |
| LLM Service           | Tool calling, streaming, prompt versioning | GLM-4-Flash wrapper (async) + GLM-OCR | Multi-modal (v2.0)     |
| Tool Executor         | Safe execution + citation                  | Pydantic-validated                    | POS mock, review APIs  |
| Memory & Vector Store | Restaurant menu/supplier embeddings        | **PostgreSQL + pgvector**             | Long-term memory       |
| Background Tasks      | Scheduled supplier re-scans                | Celery + Redis                        | Daily insights (v2.0)  |

### 4.3 Low-Level Design (Level 3 – Code Structure)

src/restaurant_os/
├── agents/
│ ├── supervisor.py # LangGraph graph (MVP: single ReAct node)
│ ├── scanner_agent.py # Core scanner with restaurant context
│ └── memory.py # Hybrid (Redis short + pgvector long)
├── llm/
│ ├── glm_client.py # Async GLM-4-Flash + GLM-OCR + tool calling + streaming
│ └── prompts/ # YAML: scanner_prompt.yaml, system_prompt.yaml
├── tools/
│ ├── registry.py # Dynamic registration (zero-cost DuckDuckGo)
│ ├── supplier_scanner.py # DuckDuckGo search tool
│ ├── review_tools.py # Google Places + Yelp (v1.0)
│ └── db_tools.py # Vector + relational queries
├── core/
│ ├── models.py # Pydantic: RestaurantContext, ScanResult
│ ├── config.py # Settings (GLM key, DB, zero-cost mode, Clerk)
│ └── traces.py # Learning instrumentation
├── db/
│ ├── models.py # SQLAlchemy: restaurants, suppliers, embeddings
│ ├── repositories.py
│ └── vector.py # pgvector HNSW ops + RAG retriever
├── api/
│ ├── v1/
│ │ ├── routes.py # /chat, /scan, /status
│ │ └── schemas.py
├── auth/
│ └── clerk.py # Clerk integration
├── observability/
│ └── reasoning_logger.py # Full trace for learning self-assessment
├── tasks/
│ └── celery_app.py # Background scans
└── tests/
├── agent_evals/ # Accuracy + citation checks
└── fixtures/ # Mock suppliers + POS data
text
**Data Flow (MVP Query → Response)**:

1. FastAPI → Clerk Auth + RestaurantContext injection.
2. LangGraph Supervisor → Scanner Agent (ReAct loop).
3. Tool call → Supplier Scanner Tool (DuckDuckGo zero-cost) + RAG (pgvector).
4. GLM-4-Flash generates grounded response with citations.
5. Stream back + persist full trace + state (Redis + Postgres).
6. Learning log: reasoning steps, token cost, accuracy score.

## 5. Technology Stack (Your Preferences + Best Completions)

**Fixed per your request + answers**:

- Language: **Python 3.12+**
- LLM: **GLM-4-Flash** (text) + **GLM-OCR** (multimodal support)
- Database: **PostgreSQL 16+ with pgvector** extension
- Supplier Scanner: **duckduckgo-search** Python library (zero-cost)
- Reviews (v1.0): **Google Places API** (free tier) + **Yelp Fusion API** (free tier)
- Auth: **Clerk** (full user login, free tier)
- Frontend: **React + TypeScript + Vite** (implemented **after** backend MVP)
- Deployment: **Docker-only** (for learning/MVP)

**Completed Stack** (MVP-ready, learning-friendly): (unchanged – see previous comparison)

### 5.3 Additional Tools Evaluation (from your query)

For **every** tool you listed, I evaluated strictly against the PRD, current stack, zero-cost/Docker-only constraints, and learning progression.  
**Rule applied**: Only introduce if it _materially_ improves accuracy, scalability, or learning value _without_ adding complexity, cost, or scope creep in MVP. Most are **NOT needed**.

| Tool                                              | Needed?                             | Best Level to Introduce                                                  | What is Needed / Not Needed                                                                  | Why (for Restaurant OS)                                                                                                                                                                                 |
| ------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Pydantic AI** (Agent Framework)                 | No                                  | Never (or post-v2.0 if switching)                                        | Not needed. We already use **Pydantic v2** for all validation/tool schemas inside LangGraph. | Redundant – adds another framework layer. LangGraph + native Pydantic is sufficient and simpler for ReAct/tool-calling learning.                                                                    |
| **Arcade** (Agent Auth & Security)                | No                                  | Never                                                                    | Not needed. We use **Clerk** (your explicit choice).                                         | Clerk provides full user login, JWT, social auth, and free tier out-of-the-box. Arcade is an alternative agent-specific auth layer – overkill and not required.                                     |
| **Docling** (Data Extraction – Files)             | No (optional future)                | v2.0 only (if menu PDFs uploaded)                                        | Not needed for MVP/v1.0.                                                                     | No file uploads in PRD (suppliers = web search, POS = mock JSON). Adds PDF parsing complexity with zero current value.                                                                              |
| **Crawl4AI** (Data Extraction – Web)              | No                                  | Never (or v2.0 if heavy scraping needed)                                 | Not needed. We use **DuckDuckGo** (your choice) + Google Places/Yelp APIs.                   | Crawl4AI is for full-site crawling – unnecessary, higher legal/ethical risk for restaurant data, and violates zero-cost simplicity. DuckDuckGo suffices.                                            |
| **Mem0** (Long-term Memory)                       | No (nice-to-have)                   | v2.0 only (taste profiles + proactive insights)                          | Not needed. Current **Redis (short) + pgvector (long-term embeddings)** is sufficient.       | Mem0 is specialized agent memory but adds another service/dependency. Postgres pgvector already gives vector + relational long-term memory at zero extra cost.                                      |
| **Neo4j** (Graph Database)                        | No                                  | v2.0+ only (if competitor intelligence or complex supplier graphs added) | Not needed.                                                                                  | PRD has no graph queries (no relationships like “supplier A supplies to competitor B”). Overkill for MVP; would require new infra (not Docker-only friendly).                                       |
| **Graffiti** (Knowledge Graph Lib)                | No                                  | Never                                                                    | Not needed.                                                                                  | Niche lib for building knowledge graphs. LangGraph already handles agent state graphs. No value for this project.                                                                                   |
| **DeepEval (Ragas)** (RAG Evaluation)             | Optional / Recommended for learning | v1.0 (in tests/agent_evals folder)                                       | **Partially needed** for advanced learning only. Add as optional dev dependency.             | Excellent for automated RAG accuracy scoring (hallucination checks). Current custom traces are enough for MVP, but DeepEval fits “learning objectives” perfectly in v1.0 without affecting runtime. |
| **Brave Search API** (Web Search)                 | No                                  | Never                                                                    | Not needed. We use **DuckDuckGo** (your explicit choice).                                    | Brave requires API key and has usage limits/costs. DuckDuckGo is truly free, no-key, privacy-focused – better for zero-cost MVP scanner.                                                            |
| **Browserbase / Playwright** (Browser Automation) | No                                  | Never (or v2.0 if JS-heavy dynamic sites required)                       | Not needed.                                                                                  | Supplier scanner uses API/search libs. Playwright adds heavy browser overhead, anti-bot issues, and complexity – not required for public data.                                                      |
| **Auth0** (Authentication)                        | No                                  | Never                                                                    | Not needed. We use **Clerk** (your explicit choice).                                         | Auth0 is similar enterprise auth; Clerk is simpler, cheaper for startups, and matches “full user login” perfectly.                                                                                  |

**Summary Recommendation**:

- **Nothing from this list is required for MVP or v1.0**.
- **Only DeepEval (Ragas)** is worth adding optionally in **v1.0** (as a test-only dependency) because it directly supports the learning objective of “self-assessment / accuracy logs” without runtime impact.
- All others would increase complexity, cost, or scope without benefit → **explicitly excluded** to keep the project lean, Docker-only, and zero-cost.
- No changes to the core stack or code structure are needed.

## 6. Engineering Requirements

- **Code Quality**: 100% type hints, ruff + pyright, pre-commit, conventional commits.
- **Testing**: pytest (≥85% coverage), Testcontainers (Postgres+Redis), LangGraph agent evals (accuracy + citation scoring). Optional: DeepEval for RAG tests in v1.0.
- **Documentation**: Inline + MkDocs + auto-generated OpenAPI.
- **Error Handling**: Centralized, user-friendly, with citation fallback on failure.
- **Performance Budget (MVP)**: Chat <5s, batch scan <2min, token tracking per run.
- **Educational Instrumentation**: Every run saves JSON trace (`reasoning_steps`, `tool_calls`, `citations`, `cost`) to `agent_runs` table for self-assessment.

## 7. Non-Functional Requirements (Direct from PRD)

- **Performance**: Chat <5s, scanner batch <2min.
- **Accuracy**: All outputs grounded + citations; ≤5% hallucination (v1.0 target).
- **Cost**: MVP = $0 (free GLM tier + zero-cost tools); track & alert.
- **Security**: API keys encrypted (Fernet or DB), no PII in logs/traces, OWASP compliance. Clerk handles auth.
- **Scalability**: Single-restaurant MVP; multi-tenant schema ready (tenant_id column everywhere).
- **Availability**: Local-first; design for 99.9% when cloud-deployed.

## 8. Data Model (PostgreSQL)

**Core Tables (SQLAlchemy)**:

- `restaurants` (id, name, cuisine_type, location, taste_profile_json)
- `suppliers` (id, name, products, contact, last_scanned)
- `embeddings` (pgvector column + metadata: restaurant_id, supplier_id, content_type)
- `agent_runs` (trace_id, agent_type, reasoning_jsonb, citations, cost_usd, accuracy_score)
- `scans` (restaurant_id, supplier_id, results_jsonb)
- `users` (Clerk integration fields)

**Indexes**: HNSW on vectors, GIN on JSONB, composite on restaurant_id.

## 9. API Design (OpenAPI v3.1)

- `POST /api/v1/chat` – conversational endpoint (stream optional)
- `POST /api/v1/scan` – trigger supplier scan (background optional)
- `GET /api/v1/traces/{run_id}` – learning trace retrieval
- WebSocket `/ws/chat/{restaurant_id}` – real-time (optional MVP)

## 10. Security & Compliance

- Clerk full user login (JWT, social providers, free tier).
- Prompt injection guards (via GLM built-in + output validation).
- Rate limiting (100 req/min per user).
- Data retention: Configurable (default 90 days for traces).

## 11. Deployment & Operations (MVP)

- **Local**: `docker compose up` (Postgres+pgvector, Redis, FastAPI). Streamlit prototype optional for testing only.
- **Monitoring**: Structured logs + LangSmith dashboard for traces.
- **CI/CD**: GitHub Actions (test + build).

## 12. Risks & Mitigations (PRD + Technical)

- Hallucinations → Mandatory citation + RAG grounding + eval gating.
- Data freshness → Background Celery task + user-triggered re-scan.
- GLM rate limits → Caching + fallback mock responses.
- Zero-cost enforcement → Hard-coded tool whitelist (DuckDuckGo only in MVP).

## Appendix A: Anything Else Needed

No critical gaps. The stack remains minimal and fully aligned. DeepEval is the only optional addition (v1.0 tests only) for enhanced learning value.

## Appendix B: POS Mock Companion

- Use free public GitHub datasets (e.g., “restaurant-inventory-sample” CSVs/JSONs).
- `pos_mock_schema.yaml` will be generated separately as a simple OpenAPI spec for mock inventory/orders.
