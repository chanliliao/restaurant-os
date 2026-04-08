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

SmartScanner is an AI invoice scanner for restaurant supply invoices. The backend is a Django REST API; there is no frontend (removed after phase 22). All image processing, OCR, and LLM calls happen server-side.

**Tech stack:** Python 3.11+, Django 5.x + DRF, Pillow + OpenCV, ZhipuAI GLM-OCR + GLM-4.6V-Flash.

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

<!-- No frontend exists in this repo. Add UI/design standards here if a frontend is reintroduced. -->

---

## Constraints and Policies

- **No ORM models for scanner data.** All invoice, supplier, and tracking data lives as JSON files under `backend/data/`. Do not introduce Django models for these.
- **No multi-process file safety.** The JSON store uses a single threading lock — safe for dev/single-worker deploys only. Do not deploy with multiple Gunicorn workers without replacing the storage layer.
- **Image size limits.** `backend/.env` and `settings.py` cap uploads at 10 MB. GLM-OCR auto-downsizes images >1 MB; images >500 KB are re-encoded as JPEG before upload.
- **GLM-OCR only.** Tesseract and Anthropic/Gemini are removed. All OCR goes through `glm-ocr`; all vision LLM calls go through `glm-4.6v-flash`. Do not reintroduce other providers without updating `engine.py` and `api_usage.py`.
- **Supplier IDs are immutable slugs.** Once a supplier's profile directory is created, renaming the supplier in code breaks the memory lookup. Normalize via `normalize_supplier_id()` in `memory/json_store.py`.
- **Confidence scores are integers 0–100.** OCR parse results carry confidence; inferred fields use fixed tiers (80 = supplier memory, 60 = industry memory). Do not use floats.
- **Math validation tolerance.** `validator.py` uses a small absolute tolerance for float comparison. Do not raise this to paper over extraction errors.

---

## Repo Etiquette

- **Branch per phase.** Feature work goes on `feat/phase-NN-<short-name>` branches off `master`.
- **Commit per phase.** One meaningful commit when a phase is complete; push immediately. Do not batch multiple phases into one commit.
- **Conventional commit prefixes.** Use `feat(phase-NN):`, `fix(component):`, `chore:`, `docs:`, `test:`.
- **No committing `backend/venv/`, `backend/data/` (runtime data), `*.pyc`, or `.env`.**  These are in `.gitignore`; keep them there.
- **All tests must pass before pushing.** Run `pytest` from `backend/` — zero failures required.
- **Mocks for all external calls in tests.** Never let tests hit the real GLM-OCR or GLM Vision APIs. Patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.
- **Phase plans live in `docs/superpowers/plans/`.** Naming: `YYYY-MM-DD-phase-NN-<name>.md`.
