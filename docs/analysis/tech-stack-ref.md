# Restaurant OS Tech Stack Reference

This document provides a comprehensive reference for every technology in the Restaurant OS Technical Requirements Document (TRD), organized by functional category. Each entry includes official documentation URLs, the version phase where it was introduced (MVP v0.1, v1.0, or v2.0), a plain-English explanation of what the technology does, rationale for inclusion in Restaurant OS, and the key concepts needed to work with it effectively.

---

## Agent & Orchestration

These technologies power the core agent logic, reasoning loop, and state management for Restaurant OS's multi-step agentic workflows.

### LangGraph

**Official Docs**: https://langchain-ai.github.io/langgraph/

**Version Introduced**: MVP v0.1

**What it is**: A Python library for building stateful, graph-based agent systems. LangGraph models agents as directed graphs where nodes represent computation steps and edges represent transitions. It handles state persistence, branching logic, and tool-use orchestration in a structured way.

**Why it's in Restaurant OS**: LangGraph provides a reliable, visual way to implement the ReAct loop (reasoning + acting) that Restaurant OS agents use to iteratively fetch data, call tools, and refine insights. Its first-class support for state machines ensures deterministic, debuggable agent behavior.

**Key concepts to know**:
- **Graph**: The agent's state machine definition; nodes and edges define the flow.
- **Nodes**: Functions that process state (e.g., reasoning, tool selection, memory retrieval).
- **Edges**: Transitions between nodes; can be conditional (e.g., "if tool call needed, go to tool-call node").
- **State**: A Pydantic model that persists across the entire agent run; updated by each node.
- **ReAct loop**: Thought → Tool call → Observation → Reflection, repeated until done.

### Pydantic v2

**Official Docs**: https://docs.pydantic.dev/latest/

**Version Introduced**: MVP v0.1

**What it is**: A Python data validation and serialization library that enforces type hints at runtime. Pydantic automatically parses, validates, and serializes data using declarative schema definitions (BaseModel classes), with built-in support for custom validators and error reporting.

**Why it's in Restaurant OS**: Pydantic ensures that tool inputs, LLM-generated outputs, and database models are consistently validated. This is critical for a system that chains multiple LLM calls; garbage in one step is caught immediately, not allowed to propagate downstream.

**Key concepts to know**:
- **BaseModel**: Base class for all Pydantic schemas; define fields with type hints.
- **Field validators**: Custom validation logic (e.g., `@field_validator` decorators) to enforce business rules.
- **Serialization**: `.model_dump()` and `.model_dump_json()` convert models to dicts/JSON.
- **Parsing**: Pydantic automatically coerces types (e.g., `"123"` → `123` for int fields).
- **Error handling**: Validation errors raise `ValidationError` with rich error messages for easy debugging.

---

## API & Gateway

These technologies provide the HTTP layer, request handling, and database abstraction for Restaurant OS's backend services.

### FastAPI

**Official Docs**: https://fastapi.tiangolo.com/

**Version Introduced**: MVP v0.1

**What it is**: A modern, fast Python web framework for building REST APIs and WebSocket applications. FastAPI auto-generates interactive OpenAPI (Swagger) documentation, supports async/await, and includes built-in request validation via Pydantic.

**Why it's in Restaurant OS**: FastAPI's async nature and automatic Pydantic validation align perfectly with agent systems that need to handle long-running LLM calls without blocking. Server-Sent Events (SSE) support enables real-time agent reasoning streams to frontends.

**Key concepts to know**:
- **Path operations**: Functions decorated with `@app.get()`, `@app.post()`, etc. that define endpoints.
- **Dependency injection**: `Depends()` for shared logic (auth, database sessions, agent context).
- **Pydantic models**: Request/response bodies are validated automatically via type hints.
- **Server-Sent Events**: `StreamingResponse` with event-stream mimetype for long-running agent steps.
- **Background tasks**: `BackgroundTasks` for non-blocking work (e.g., triggering a Celery job).

### SQLAlchemy 2.0

**Official Docs**: https://docs.sqlalchemy.org/en/20/

**Version Introduced**: MVP v0.1

**What it is**: A mature Python ORM and SQL abstraction layer. SQLAlchemy 2.0 introduced modern patterns: async/await support, declarative table mapping, and a cleaner API that separates data models from database mechanics.

**Why it's in Restaurant OS**: SQLAlchemy provides a robust, type-safe way to interact with PostgreSQL for structured data (user metadata, supplier profiles, scan history) while keeping the invoice JSON storage separate. Async support is essential for non-blocking database calls in async FastAPI handlers.

**Key concepts to know**:
- **Declarative mapping**: Classes inherit from `DeclarativeBase` and are auto-mapped to tables; no separate table definition needed.
- **mapped_column**: New SA 2.0 syntax; replaces `Column()` in type-hinted class definitions.
- **Relationships**: One-to-many, many-to-one defined with `relationship()` for eager/lazy loading.
- **Async sessions**: `AsyncSession` for non-blocking database calls; use `async with` context managers.
- **Query API**: `.select()` for modern imperative queries; chainable with `.where()`, `.join()`, `.order_by()`.

---

## Database & Storage

These technologies provide persistent storage for user data, vectors, and session state.

### PostgreSQL 16

**Official Docs**: https://www.postgresql.org/docs/16/

**Version Introduced**: MVP v0.1

**What it is**: An enterprise-grade open-source relational database. PostgreSQL 16 offers advanced features like JSONB columns for semi-structured data, GIN indexes for full-text and JSON search, and native support for vector data types (via extensions).

**Why it's in Restaurant OS**: PostgreSQL is chosen for structured data (users, suppliers, scan metadata) and as a foundation for vector embeddings (via pgvector). Its robustness, ACID compliance, and rich feature set make it suitable for a production system.

**Key concepts to know**:
- **JSONB columns**: Store semi-structured data (e.g., supplier metadata, extracted invoice fields) without pre-defining a schema; queryable via `@>`, `->`, `@` operators.
- **GIN indexes**: Generalized Inverted Indexes for fast searches on JSONB and array columns.
- **Transactions**: ACID guarantees; use explicit transactions for multi-step operations (e.g., create supplier + initialize memory).
- **Connection pooling**: Always use a connection pool (e.g., via SQLAlchemy) to avoid resource exhaustion.
- **Extensions**: Loaded with `CREATE EXTENSION`; `pgvector` and `uuid-ossp` are common in Restaurant OS.

### pgvector

**Official Docs**: https://github.com/pgvector/pgvector

**Version Introduced**: MVP v0.1

**What it is**: A PostgreSQL extension that adds native support for vector data types and similarity search. pgvector stores vectors as columns, provides indexing (HNSW), and supports cosine, euclidean, and inner-product distance metrics.

**Why it's in Restaurant OS**: pgvector enables semantic search over invoice embeddings and supplier profiles without a separate vector database. This reduces operational complexity and keeps all structured data in one place.

**Key concepts to know**:
- **Vector column type**: `vector(N)` where N is the embedding dimension (e.g., 1536 for ZhipuAI embeddings).
- **Distance operators**: `<->` (L2 distance), `<#>` (negative inner product), `<=>` (cosine distance); cosine is most common for semantic search.
- **HNSW index**: `CREATE INDEX ON table USING hnsw (vector_col vector_cosine_ops)` for sub-second nearest-neighbor queries at scale.
- **Similarity search**: Use `ORDER BY vector_col <=> query_vector LIMIT k` to find k nearest neighbors.
- **Embedding dimension**: Must match the dimension of vectors from your embedding model (ZhipuAI, OpenAI, etc.).

### Redis (redis-py)

**Official Docs**: https://redis.io/docs/latest/develop/clients/redis-py/

**Version Introduced**: MVP v0.1

**What it is**: An in-memory data structure store and message broker. Redis excels at caching, session storage, and pub/sub messaging. The `redis-py` client provides a Python interface with both sync and async APIs.

**Why it's in Restaurant OS**: Redis caches frequently accessed data (supplier profiles, user context) to reduce database load, and stores short-term agent memory (e.g., recent conversation state) for low-latency retrieval during multi-step agentic workflows.

**Key concepts to know**:
- **Key-value store**: Simple `SET key value` and `GET key` for caching; TTL support with `EX seconds`.
- **Data structures**: Strings, lists, sets, hashes, sorted sets, streams; choose the right structure for your use case.
- **Pub/Sub**: `PUBLISH channel message` and `SUBSCRIBE channel` for real-time notifications (e.g., scan complete).
- **Sessions**: Store user session tokens with expiration; use hash structures for multi-field session data.
- **async API**: `redis.asyncio.Redis` for non-blocking calls in async FastAPI handlers.

---

## Background Tasks

These technologies handle asynchronous, long-running work outside the request-response cycle.

### Celery

**Official Docs**: https://docs.celeryq.dev/

**Version Introduced**: MVP v0.1

**What it is**: A distributed task queue library for Python. Celery workers pick up messages from a broker (e.g., Redis) and execute them asynchronously. It supports scheduled tasks (via Celery Beat), retries, and result storage.

**Why it's in Restaurant OS**: Invoice scans can take 10–30 seconds (LLM calls, multi-step reasoning); Celery offloads these to background workers so the API responds immediately. Scheduled re-scans of supplier profiles are triggered via Celery Beat.

**Key concepts to know**:
- **Tasks**: Functions decorated with `@app.task()` or `@celery.task()` that run asynchronously.
- **Broker**: Message queue (Redis in Restaurant OS) where tasks are enqueued; workers consume messages.
- **Result backend**: Storage for task results; can be Redis or database.
- **Celery Beat**: Scheduler for periodic tasks (e.g., re-scan suppliers every 24 hours).
- **Retries**: Built-in retry logic with exponential backoff; useful for flaky external APIs (LLM calls).

---

## Auth

These technologies manage user authentication and authorization.

### Clerk

**Official Docs**: https://clerk.com/docs

**Version Introduced**: MVP v0.1

**What it is**: A full-featured authentication and user management service. Clerk handles signup, login, password reset, multi-factor authentication (MFA), and social provider integrations (Google, GitHub, etc.) with zero infrastructure overhead.

**Why it's in Restaurant OS**: Clerk eliminates the need to build and maintain custom auth; its free tier supports dev/MVP without cost, and enterprise features (MFA, audit logs) are available as Restaurant OS scales.

**Key concepts to know**:
- **JWT tokens**: Clerk issues stateless JWTs included in request headers; validate them in FastAPI via Clerk's middleware.
- **User metadata**: Store restaurant info, preferences in Clerk's user object; retrieved during login.
- **Social providers**: Enable "Sign in with Google" with a few config lines.
- **Session tokens**: Clerk provides refresh tokens for long-lived sessions.
- **User IDs**: Unique `user_id` from Clerk; use as foreign key in PostgreSQL for user-related data.

---

## LLM & Search

These technologies provide language model capabilities and external knowledge retrieval.

### ZhipuAI / Z.AI API (GLM)

**Official Docs**: https://docs.z.ai/guides/llm/glm-4.7

**Version Introduced**: MVP v0.1

**What it is**: ZhipuAI's GLM model suite includes GLM-4-Flash (fast, cost-effective text/tool-calling) and GLM-4V-Flash (multimodal vision for invoice images). Both are accessible via REST API; GLM-4-Flash is optimized for structured reasoning and function calling.

**Why it's in Restaurant OS**: GLM-4-Flash is fast and cheap for agent reasoning loops; GLM-4V-Flash handles invoice image analysis without a separate OCR system. Both models are well-suited to Chinese restaurant suppliers (ZhipuAI is China-optimized).

**Key concepts to know**:
- **Tool calling**: GLM-4-Flash natively supports function calling via `tools` parameter in the API; the model outputs structured JSON indicating which tool to call and with what args.
- **Streaming**: Use `stream: true` in requests to receive reasoning tokens incrementally.
- **Multimodal input**: GLM-4V-Flash accepts image URLs or base64-encoded image data alongside text; use for invoice analysis.
- **Token limits**: GLM-4-Flash has 4K context; be mindful of token usage in long agent loops.
- **Cost tracking**: Track API calls via LangSmith or custom logging; integrate with `api_usage.py` patterns from SmartScanner.

### duckduckgo-search

**Official Docs**: https://pypi.org/project/duckduckgo-search/

**Version Introduced**: MVP v0.1

**What it is**: A Python library that wraps DuckDuckGo's search engine. It performs web searches (instant answers, news, images) without requiring an API key or rate-limit restrictions.

**Why it's in Restaurant OS**: duckduckgo-search provides agents with real-time web knowledge at zero cost. Agents can search for restaurant industry trends, supplier news, or product availability without API complexity.

**Key concepts to know**:
- **Instant answers**: Use `DDGS().answers()` for quick factual lookups (e.g., "What is the current price of flour?").
- **Web search**: Use `DDGS().text()` for ranked web results; returns title, link, snippet.
- **No API key**: Unlike Google Custom Search or Bing, DuckDuckGo has no API key requirement.
- **User-Agent required**: Some calls may need a realistic User-Agent header to avoid blocks.
- **Rate limiting**: Be respectful; add delays between searches to avoid IP blocks.

---

## Observability

These technologies provide tracing, monitoring, and debugging of agent behavior.

### LangSmith

**Official Docs**: https://docs.langchain.com/langsmith/observability

**Version Introduced**: MVP v0.1

**What it is**: A tracing and evaluation platform by LangChain. LangSmith logs every LLM call, tool invocation, and agent step into a web dashboard, enabling inspection of reasoning, token costs, and latency.

**Why it's in Restaurant OS**: In a complex multi-step agent system, visibility is critical. LangSmith allows operators to debug why an agent made a certain decision, track cumulative token costs, and identify bottlenecks or repeated failures.

**Key concepts to know**:
- **Traces**: Logs of a full agent run (e.g., one invoice scan); nested structure shows each step's input/output.
- **Feedback**: Annotate traces as success/failure to build datasets for evaluation and fine-tuning.
- **Token tracking**: Automatically sums tokens across all LLM calls in a trace; compare costs across different agent strategies.
- **API key**: Set `LANGSMITH_API_KEY` in environment; FastAPI and Celery hooks auto-log all LangChain calls.
- **Datasets and tests**: Create benchmark datasets from production traces; run regression tests before deploying new agent logic.

---

## Testing & Evaluation

These technologies provide automated quality assurance for LLM outputs and retrieval-augmented generation (RAG) pipelines.

### DeepEval

**Official Docs**: https://deepeval.com/docs/getting-started

**Version Introduced**: v1.0 (optional)

**What it is**: An evaluation framework for RAG and LLM systems. DeepEval provides pre-built metrics (hallucination detection, context relevance, faithfulness) and supports custom metrics to quantify the quality of LLM outputs.

**Why it's in Restaurant OS**: As Restaurant OS scales to handle thousands of supplier invoices, automated evaluation ensures that the agent's extractions and recommendations remain accurate. DeepEval detects when the agent hallucinates data or misinterprets supplier information.

**Key concepts to know**:
- **Metrics**: Pre-defined evaluators like `HallucinationMetric`, `ContextRelevancyMetric`, `FaithfulnessMetric`; each scores 0–1.
- **Test cases**: Represent (input, expected_output, actual_output) tuples; run metrics over a batch to get pass rates.
- **Custom metrics**: Inherit from `DeepEvalMetric` to define domain-specific quality checks (e.g., "is the extracted supplier ID valid?").
- **Integration with LangSmith**: Export traces from LangSmith and feed them into DeepEval for large-scale evaluation.
- **Assertion-based testing**: Use in pytest with `assert test.run()` to fail CI if quality drops below a threshold.

---

## Deployment

These technologies provide containerization and orchestration for local development and production environments.

### Docker Compose

**Official Docs**: https://docs.docker.com/compose/

**Version Introduced**: MVP v0.1

**What it is**: A tool for defining and running multi-container Docker applications. A `docker-compose.yml` file declaratively describes all services (database, cache, app, worker), their images, ports, volumes, and environment variables; `docker-compose up` starts everything.

**Why it's in Restaurant OS**: Docker Compose enables consistent dev/staging/production environments and eliminates "works on my machine" issues. It simplifies local development by spinning up PostgreSQL, Redis, and the FastAPI app with a single command.

**Key concepts to know**:
- **Services**: Each service (postgres, redis, api, worker) is a separate container definition.
- **Images**: Can be pre-built (postgres:16) or built from a Dockerfile (api: build: ./backend).
- **Volumes**: Persist database data and mount code for live reloading during development.
- **Environment variables**: Set per service via `environment` key; read from .env file with `env_file`.
- **Networks**: Compose creates an internal network; services communicate by hostname (e.g., postgres:5432).
- **Ports**: Expose ports for local access (e.g., 8000 for API, 6379 for Redis, 5432 for Postgres).
