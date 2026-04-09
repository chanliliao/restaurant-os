# Product Requirements Document (PRD): Restaurant AI Agent

## 1. Overview

**Product Name**: Restaurant AI Agent (codename: "Restaurant OS")  
**Version**: 1.0 (MVP) → 2.0 → 3.0  
**Mission**: Deliver an accurate, zero-to-low-cost AI agent suite that helps restaurant owners manage suppliers, operations, and customer experience while teaching foundational AI agent development through progressive difficulty levels.

**Key Differentiators**:

- Starts with a specialized, no-cost supplier scanner.
- Evolves into multi-agent operations intelligence.
- Culminates in end-to-end autonomous assistance for owners _and_ diners.

**Target Users**:

- Restaurant owners/managers (primary).
- Front-of-house staff and diners (secondary, Level 3 only).

## 2. Business Objectives

- Reduce supplier research time by 80%.
- Improve inventory accuracy and margin insights.
- Increase customer satisfaction via personalized recommendations.
- Serve as a learning platform: each version maps to increasing AI agent complexity.

## 3. Versions & Roadmap

| Version        | Difficulty   | MVP Status | Core Focus                            | Go-Live Criteria                                    |
| -------------- | ------------ | ---------- | ------------------------------------- | --------------------------------------------------- |
| **MVP (v0.1)** | Beginner     | Yes        | Single-agent supplier scanner + chat  | Accurate scanner on 50 suppliers; 90% query success |
| **v1.0**       | Intermediate | No         | Multi-agent + POS/reviews integration | POS mock works; review insights <5% hallucination   |
| **v2.0**       | Advanced     | No         | Full agentic + customer suggestions   | Autonomous daily insights; end-to-end accuracy >95% |

**Timeline (learning-focused)**: MVP in 1-2 weeks, v1.0 in 3-4 weeks, v2.0 in 4-6 weeks (iterative coding sprints).

## 4. Features by Version

### MVP – Level 1: Supplier Scanner Agent

- Supplier Scanner (web-based, zero-cost).
- Simple conversational chatbot for supplier queries & discovery.
- User-specific restaurant context.

**Learning Objectives**: Tool calling, basic RAG, ReAct reasoning.

### v1.0 – Level 2: Operations Intelligence Agent

- POS & inventory integration (mock → real APIs).
- Dedicated Reviews Analysis Agent (in-person + online).
- Multi-agent orchestration for manager queries.

**Learning Objectives**: API integrations, multi-agent collab, vector memory, analytics tools.

### v2.0 – Level 3: End-to-End Restaurant AI Agent

- Taste profile & conversational dish suggestions.
- Proactive insights & autonomous planning.
- Full cross-domain orchestration + guardrails.

**Learning Objectives**: Advanced planning loops, long-term memory, multi-modal reasoning, evaluation frameworks.

**Future Enhancements (post-v2.0)**:

- Predictive ordering.
- Menu engineering.
- Competitor intelligence.
- Voice interface.
- Sustainability filters.

## 5. Non-Functional Requirements

- **Performance**: <5s response for chat; scanner batch <2min.
- **Accuracy**: Ground all outputs in data; human-verifiable citations.
- **Cost**: MVP = $0; later versions use free tiers first.
- **Security**: API keys encrypted; no PII in logs.
- **Scalability**: Start single-restaurant; design for multi-tenant later.
- **Tech Stack Suggestion** (flexible for learning): LangGraph/CrewAI for orchestration, LlamaIndex/Chroma for RAG, Grok or open LLMs.

## 6. Success Metrics

- **Product**: User NPS >8/10; time saved reported.
- **Learning**: Each version ships with self-assessment (accuracy logs, reasoning traces).
- **Business**: Pilot with 5 restaurants showing measurable margin lift.

## 7. Assumptions & Dependencies

- Public data availability for suppliers/reviews.
- Mock APIs for POS during learning.
- LLM with strong tool-calling (Grok-4 or equivalent).

## 8. Risks & Mitigations

- Hallucinations → Strict grounding + citation requirements.
- API rate limits → Caching + fallback to local data.
- Data freshness → Scheduled re-scans.
