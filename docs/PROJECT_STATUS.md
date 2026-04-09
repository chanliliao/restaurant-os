# Restaurant OS — Project Status

_Last updated: 2026-04-09 (Restaurant OS rebrand)_

---

## Current State

**Backend:** Fully operational Django REST API with a hybrid GLM-OCR + GLM-4.6V-Flash pipeline, supplier memory system, and accuracy/API tracking.

**Frontend:** Removed after Phase 22. API is consumed directly (HTTP). No active frontend.

**Active branch:** `chore/claude-folder-structure` (`.claude/` tooling additions — pending PR merge to `master`)

---

## Completed Phases

| # | Phase | Date | Summary |
|---|-------|------|---------|
| 01 | Backend Scaffolding | 2026-03-27 | Django project, `scanner` app, `POST /api/scan/` stub, `data/` layout |
| 02 | React Frontend Scaffold | 2026-03-27 | React 18 + TypeScript + Vite; removed in Phase 22 |
| 03 | Orientation & Skew Correction | 2026-03-27 | EXIF rotation + Hough-line skew fix (`auto_orient()`) |
| 04 | Image Quality Assessment | 2026-03-27 | Blur, contrast, noise, brightness, resolution scoring (`analyzer.py`) |
| 05 | Selective Image Processing | 2026-03-27 | Conditional enhancement pipeline (`processor.py`) |
| 06 | ROI Segmentation | 2026-03-27 | CV2 header/line-items/totals crop detection (`segmentation.py`) |
| 07 | OCR Pre-Pass (Tesseract) | 2026-03-27 | Tesseract OCR pass to assist Claude prompts — later replaced |
| 08 | Single Scan with Claude API | 2026-03-27 | First working scan via Claude API — later replaced with GLM |
| 09 | Three-Pass Scanning Pipeline | 2026-03-27 | Primary → confirm → tiebreaker; Light/Normal/Heavy scan modes |
| 10 | Math Cross-Validation | 2026-03-27 | `validator.py`: subtotal+tax=total and qty×price=line total |
| 11 | Memory Interfaces + JSON Storage | 2026-03-27 | Abstract supplier/general memory; atomic JSON writes; slug normalization |
| 12 | Three-Tier Inference | 2026-03-27 | Gap-filling from supplier memory (80) and industry memory (60) |
| 13 | Editable Result Form | 2026-03-27 | `InvoiceForm` component + `POST /api/confirm/` endpoint |
| 14 | Memory Learning from Corrections | 2026-03-27 | Correction categorizer; memory update on confirm |
| 15 | Supplier Layout Mapping | 2026-03-27 | Normalized layout descriptors saved per supplier (`layout.json`) |
| 16 | Accuracy & API Tracking + Dashboard | 2026-03-28 | `GET /api/stats/`; accuracy + API usage tracking modules |
| 17 | Integration Testing | 2026-03-28 | 35 integration tests across 6 pipeline scenarios |
| 18 | GLM-OCR Scan Mode | 2026-03-31 | ZhipuAI GLM-OCR integrated as first scan pass |
| 19 | GLM-OCR-First Pipeline | 2026-04-01 | OCR → parse → LLM only on fallback; JPEG uploads |
| 20 | OCR Parser + Segmentation Improvements | 2026-04-01 | `ocr_parser.py` with `ParsedField` confidence dataclass |
| 21 | Memory-Driven Parser + GLM-4.6V-Flash | 2026-04-01 | Supplier memory drives OCR parsing; Gemini removed |
| 22 | Targeted OCR Pipeline | 2026-04-02–07 | GLM-OCR fast path; targeted crops; 6 real supplier profiles; frontend removed |

## Completed Tooling

| Item | Date | Summary |
|------|------|---------|
| `.claude/` Project Structure | 2026-04-08 | Rules, slash commands (`/phase`, `/scan`, `/debug`, etc.), skills, `changelog-updater` agent |
| `update-docs-and-commit` Skill | 2026-04-08 | Replaced `commit-push` — tests → changelog agent → PROJECT_STATUS → ARCHITECTURE check → commit (no push) |
| `retro-agent` + `/retro` command | 2026-04-08 | Retrospective agent — audits workflow, proposes CLAUDE.md changes and new skills, writes `docs/RETRO.md` |
| Claude Folder Structure Hardening | 2026-04-08 | Retro findings applied: rule file fixes, `/push-pr` command + skill, plan-file gate in `/phase`, `.gitignore` recursive data coverage, user-level `~/.claude/CLAUDE.md` |
| Restaurant OS Rebrand | 2026-04-09 | Renamed `backend/src/platemind/` → `backend/src/restaurant_os/`; updated all imports, docs, skills |

---

## Active Work

| Branch | Description | Status |
|--------|-------------|--------|
| `chore/claude-folder-structure` | `.claude/` tooling (rules, skills, commands, agents) | Code complete — awaiting PR merge |

---

## Next / Potential Work

These are ideas from the original design spec or natural next steps — not committed to any branch yet.

- **Phase 23+: New supplier onboarding flow** — guided first-scan profile creation for unknown suppliers
- **Multi-page invoice support** — pipeline currently handles single-image invoices only
- **Confidence dashboard improvements** — per-field confidence visualization in a future frontend
- **SQLite or Postgres migration** — replace JSON file store for multi-worker / production deployments
- **New frontend** — React + TypeScript replacement for the removed Phase 22 frontend, if needed
- **Rate limiting + auth** — API currently unprotected; any production deployment needs this

---

## Key File Locations

| What | Where |
|------|-------|
| Scan pipeline | `backend/scanner/scanning/engine.py` |
| OCR parser | `backend/scanner/scanning/ocr_parser.py` |
| Memory store | `backend/scanner/memory/json_store.py` |
| Math validator | `backend/scanner/scanning/validator.py` |
| Supplier profiles | `backend/data/suppliers/<id>/` |
| API endpoints | `backend/scanner/views.py` |
| Tests | `backend/tests/` |
| Phase plans | `docs/superpowers/plans/` |
| Architecture | `docs/ARCHITECTURE.md` |
| Changelog | `docs/CHANGELOG.md` |
