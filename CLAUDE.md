# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `backend/` with the virtualenv activated (`venv/Scripts/activate` on Windows).

```bash
# Run the dev server
python manage.py runserver

# Run all tests
pytest

# Run a single test file
pytest tests/test_scanning.py

# Run a single test function
pytest tests/test_scanning.py::TestClassName::test_function_name

# Run tests matching a keyword
pytest -k "test_ocr_fast_path"
```

`pytest.ini` sets `DJANGO_SETTINGS_MODULE = smartscanner.settings` so no env var is needed.

## Environment

Copy `.env` variables into `backend/.env`. Required keys:
- `GLM_OCR_API_KEY` — ZhipuAI key for GLM-OCR and GLM-4.6V-Flash
- `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`

---

## Architecture Overview

SmartScanner is an AI invoice scanner for restaurant supply invoices. The backend is a Django REST API; there is no active frontend (removed after phase 22). All image processing, OCR, and LLM calls happen server-side.

See `docs/ARCHITECTURE.md` for the full system overview, data flow, and component breakdown.

### Scan Pipeline (`scanner/scanning/engine.py`)

The core function is `scan_invoice(image_bytes)`. The pipeline:

1. **Auto-orient** — EXIF + heuristic rotation correction (`preprocessing/orientation.py`)
2. **GLM-OCR** — sends raw image to `glm-ocr` endpoint; returns structured markdown/text
3. **OCR Parse** — regex-based extraction with per-field confidence scores (`scanning/ocr_parser.py`)
4. **Fast path** — if all scalar fields ≥60% confidence and supplier ≥80%, skip LLM entirely
5. **Segment** — CV2 region detection for header/items/totals (`preprocessing/segmentation.py`)
6. **Targeted LLM call** — GLM-4.6V-Flash with only the crops needed for missing/low-confidence fields; full-page always used for supplier identification
7. **Math validation** — cross-check `subtotal + tax = total`, auto-correct within tolerance (`scanning/validator.py`)
8. **Inference** — fill remaining gaps from memory: tier 1 supplier history (conf 80) → tier 2 industry profile (conf 60) (`memory/inference.py`)
9. **Layout save** — persist supplier region ratios to `data/suppliers/<id>/layout.json`

### Memory System (`scanner/memory/`)

Abstract interfaces in `interface.py` (`SupplierMemory`, `GeneralMemory`) with JSON file implementations in `json_store.py`.

Data lives in `backend/data/`:
```
data/
├── general/              # industry-wide profile + item catalog
└── suppliers/
    ├── index.json        # supplier name → ID mapping
    └── <supplier-id>/
        ├── profile.json  # scan history, common field values, tax rates
        └── layout.json   # normalized region bounding boxes [0,1]
```

Supplier IDs are slugified names: `"Wismettac Asian Foods Inc"` → `"wismettac-asian-foods-inc"`. File writes are atomic (temp-file + rename); thread-safe within a single process via module-level lock. Multi-process (Gunicorn) requires OS-level locking or a DB-backed store.

After every confirmed scan (`POST /api/confirm/`), corrections update both supplier memory and the general industry profile immediately — no batching.

### API (`scanner/views.py` + `scanner/urls.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/scan/` | Upload image (`multipart/form-data`, field `image`); returns structured invoice JSON |
| POST | `/api/confirm/` | Submit corrections `{scan_result, corrections, confirmed_at}`; updates memory + tracking |
| GET | `/api/stats/` | Accuracy and API usage statistics |

Add `?debug=1` to `/api/scan/` for verbose pipeline metadata.

### Preprocessing (`scanner/preprocessing/`)

- `orientation.py` — EXIF-aware rotation + skew correction (applied before all else)
- `analyzer.py` — image quality assessment (blur, contrast, noise levels)
- `processor.py` — selective enhancement (only applies transforms the quality report flags)
- `segmentation.py` — CV2 region detection returning `{header, line_items, totals}` PIL crops; falls back to full image if detection fails
- `layout.py` — converts pixel crops to normalized `[0,1]` ratios for layout JSON storage

### Tracking (`scanner/tracking/`)

- `accuracy.py` — records per-scan correction rate; rolling-window aggregate stats
- `api_usage.py` — logs model calls and scan counts per mode

### Tests (`tests/`)

All tests mock external HTTP (GLM-OCR and GLM Vision). Integration tests in `test_integration.py` exercise the full `scan_invoice()` pipeline end-to-end with mocked responses. `integration_helpers.py` provides shared fixture builders and mock patches.

No DB migrations needed — SQLite is used only for Django's built-in auth/session tables; all scanner data is JSON files.

---

## Design Style Guide

### Tech Stack

**Backend (current):**
- Python 3.11+
- Django 5.x + Django REST Framework
- django-cors-headers
- Pillow + OpenCV (headless) for image processing
- ZhipuAI GLM-OCR (`glm-ocr`) for structured text extraction
- ZhipuAI GLM-4.6V-Flash (`glm-4.6v-flash`) for vision LLM calls
- JSON files for all scanner data storage; SQLite for Django internals only

**Frontend (removed — for reference if reintroduced):**
- React 18 + TypeScript (strict mode)
- Vite as build tool
- Axios for API calls
- Plain CSS / CSS Modules for styling

### Code Quality

- **Python:** Follow PEP 8. Keep functions focused and short. Prefer explicit over implicit — no magic globals or module-level side effects.
- **TypeScript (if frontend returns):** Strict mode required (`"strict": true` in `tsconfig.json`). No `any` types. Run `npm run lint` and `npm run build` before pushing to catch type errors.
- **No inline secrets.** API keys and secrets go in `.env` only, never hardcoded.
- **Logging over print.** Use `logging.getLogger(__name__)` throughout; never use `print()` in production code paths.

---

## Constraints and Policies

- **No ORM models for scanner data.** All invoice, supplier, and tracking data lives as JSON files under `backend/data/`. Do not introduce Django models for these.
- **No multi-process file safety.** The JSON store uses a single threading lock — safe for dev/single-worker deploys only. Do not deploy with multiple Gunicorn workers without replacing the storage layer.
- **Image size limits.** `settings.py` caps uploads at 10 MB. GLM-OCR auto-downsizes images >1 MB; images >500 KB are re-encoded as JPEG before upload.
- **GLM models only.** Tesseract and Anthropic/Gemini are removed. All OCR goes through `glm-ocr`; all vision LLM calls go through `glm-4.6v-flash`. Do not reintroduce other providers without updating `engine.py` and `api_usage.py`.
- **Supplier IDs are immutable slugs.** Once a supplier's profile directory is created, renaming the supplier in code breaks the memory lookup. Normalize via `normalize_supplier_id()` in `memory/json_store.py`.
- **Confidence scores are integers 0–100.** OCR parse results carry confidence; inferred fields use fixed tiers (80 = supplier memory, 60 = industry memory). Do not use floats.
- **Math validation tolerance.** `validator.py` uses a small absolute tolerance for float comparison. Do not raise this to paper over extraction errors.

### Security

- **Never commit `.env`.** It is gitignored; keep it that way. Rotate any key that is accidentally committed.
- **Supplier ID validation.** `_validate_supplier_id()` in `json_store.py` rejects path traversal (`..`, `/`, `\`). Always call it before constructing file paths from user input.
- **File upload validation.** Only image content types are accepted at the API layer. The 10 MB cap prevents memory exhaustion from oversized uploads.
- **No shell execution from user input.** Image processing uses Pillow/OpenCV — no `subprocess` calls with user-supplied data.
- **CORS.** `CORS_ALLOWED_ORIGINS` in `settings.py` is set from `.env`. Do not set `CORS_ALLOW_ALL_ORIGINS = True` in any environment.
- **`DEBUG=False` in production.** Django debug mode exposes stack traces and settings to the browser.

---

## Repo Etiquette

### Commits

- Write clear commit messages that describe **what changed and why**, not just what file was touched.
- Keep commits focused on a single logical change. Do not mix feature work, bug fixes, and refactors in one commit.
- Use conventional commit prefixes: `feat(phase-NN):`, `fix(component):`, `chore:`, `docs:`, `test:`, `security:`.
- **No committing** `backend/venv/`, `backend/data/` (runtime data), `*.pyc`, or `.env`. These are gitignored; keep them there.

### Before Pushing

- Run `pytest` from `backend/` — zero failures required before any push.
- If a frontend exists: run `npm run lint` and `npm run build` from `frontend/` to catch type errors and build failures before pushing.
- All external API calls in tests must be mocked. Never let tests hit real GLM-OCR or GLM Vision endpoints. Patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.

### Pull Requests

- Create a PR for all changes going to `master`. Do not push feature or fix work directly to `master`.
- Never force-push to `master`.
- PR descriptions must include: **what** changed, **why** the change was made, and any **testing notes** (what was run, edge cases checked).
- Branch naming: `feat/phase-NN-<short-name>`, `fix/<component>-<issue>`.

### Documentation

- Update `docs/ARCHITECTURE.md` and `docs/CHANGELOG.md` after major milestones, new phases, or significant additions/removals.
- Phase plans live in `docs/superpowers/plans/`. Naming: `YYYY-MM-DD-phase-NN-<name>.md`.
- Keep `CLAUDE.md` current — update it when the tech stack, pipeline, or policies change.
