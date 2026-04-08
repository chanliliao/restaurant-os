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

## Architecture

### Scan Pipeline (`scanner/scanning/engine.py`)

The core function is `scan_invoice(image_bytes)`. The pipeline:

1. **Auto-orient** — EXIF + heuristic rotation correction (`preprocessing/orientation.py`)
2. **GLM-OCR** — sends raw image to `glm-ocr` endpoint; returns markdown/text
3. **OCR Parse** — regex-based structured extraction with per-field confidence (`scanning/ocr_parser.py`)
4. **Fast path** — if all scalar fields ≥60% confidence and supplier ≥80%, skip LLM entirely
5. **Segment** — detect header/items/totals regions via CV2 (`preprocessing/segmentation.py`)
6. **Targeted LLM call** — GLM-4.6V-Flash with only the crops needed for missing/low-confidence fields; full-page used for supplier identification
7. **Math validation** — cross-check subtotal + tax = total, auto-correct within tolerance (`scanning/validator.py`)
8. **Inference** — fill remaining gaps from memory (tier 1: supplier history, tier 2: industry profile) (`memory/inference.py`)
9. **Layout save** — persist supplier region ratios to `data/suppliers/<id>/layout.json`

### Memory System (`scanner/memory/`)

- `interface.py` — abstract base classes `SupplierMemory` and `GeneralMemory`
- `json_store.py` — file-based implementations; data lives in `backend/data/`
  - `data/suppliers/<supplier-id>/profile.json` — scan history, common field values
  - `data/suppliers/<supplier-id>/layout.json` — normalized region bounding boxes
  - `data/suppliers/index.json` — supplier name → ID mapping
  - `data/general/` — industry-wide profile and item catalog
- `inference.py` — two-tier gap-filling: supplier memory (conf 80) → industry memory (conf 60)
- Supplier IDs are slugified names: `"Wismettac Asian Foods Inc"` → `"wismettac-asian-foods-inc"`
- File writes are atomic (temp-file + rename); thread-safe via module-level lock (not multi-process safe)

### API (`scanner/views.py` + `scanner/urls.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/scan/` | Upload image, returns structured invoice JSON |
| POST | `/api/confirm/` | Submit corrections, updates memory + tracking |
| GET | `/api/stats/` | Accuracy and API usage statistics |

`POST /api/scan/` accepts `multipart/form-data` with an `image` field. Add `?debug=1` for verbose metadata. `POST /api/confirm/` accepts JSON: `{scan_result, corrections, confirmed_at}`.

### Preprocessing (`scanner/preprocessing/`)

- `orientation.py` — EXIF-aware rotation + skew correction
- `analyzer.py` — image quality assessment (blur, contrast, noise)
- `processor.py` — selective enhancement pipeline (only applies transforms the quality report flags)
- `segmentation.py` — CV2-based region detection returning `{header, line_items, totals}` PIL crops
- `layout.py` — converts pixel crops to normalized `[0,1]` ratios for layout JSON

### Tracking (`scanner/tracking/`)

- `accuracy.py` — records per-scan correction rate; aggregates stats over a rolling window
- `api_usage.py` — logs model calls, token counts, scan counts per mode

### Tests (`tests/`)

All tests mock external API calls (GLM-OCR and GLM Vision). Integration tests in `test_integration.py` exercise the full `scan_invoice()` pipeline end-to-end with mocked HTTP. The `integration_helpers.py` module provides fixture builders and mock patches shared across test files.

No database migrations are needed — the app uses SQLite (auto-created) only for Django's auth/session infrastructure; all scanner data is JSON files.
