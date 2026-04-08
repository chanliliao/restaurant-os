# Coding Standards

## Tech Stack

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

## Code Quality

- **Python:** Follow PEP 8. Keep functions focused and short. Prefer explicit over implicit — no magic globals or module-level side effects.
- **TypeScript (if frontend returns):** Strict mode required (`"strict": true` in `tsconfig.json`). No `any` types. Run `npm run lint` and `npm run build` before pushing to catch type errors.
- **No inline secrets.** API keys and secrets go in `.env` only, never hardcoded.
- **Logging over print.** Use `logging.getLogger(__name__)` throughout; never use `print()` in production code paths.

## Constraints and Policies

- **No ORM models for scanner data.** All invoice, supplier, and tracking data lives as JSON files under `backend/data/`. Do not introduce Django models for these.
- **No multi-process file safety.** The JSON store uses a single threading lock — safe for dev/single-worker deploys only. Do not deploy with multiple Gunicorn workers without replacing the storage layer.
- **Image size limits.** `settings.py` caps uploads at 10 MB. GLM-OCR auto-downsizes images >1 MB; images >500 KB are re-encoded as JPEG before upload.
- **GLM models only.** Tesseract and Anthropic/Gemini are removed. All OCR goes through `glm-ocr`; all vision LLM calls go through `glm-4.6v-flash`. Do not reintroduce other providers without updating `engine.py` and `api_usage.py`.
- **Supplier IDs are immutable slugs.** Once a supplier's profile directory is created, renaming the supplier in code breaks the memory lookup. Normalize via `normalize_supplier_id()` in `memory/json_store.py`.
- **Confidence scores are integers 0–100.** OCR parse results carry confidence; inferred fields use fixed tiers (80 = supplier memory, 60 = industry memory). Do not use floats.
- **Math validation tolerance.** `validator.py` uses a small absolute tolerance for float comparison. Do not raise this to paper over extraction errors.

## Security

- **Never commit `.env`.** It is gitignored; keep it that way. Rotate any key that is accidentally committed.
- **Supplier ID validation.** `_validate_supplier_id()` in `json_store.py` rejects path traversal (`..`, `/`, `\`). Always call it before constructing file paths from user input.
- **File upload validation.** Only image content types are accepted at the API layer. The 10 MB cap prevents memory exhaustion from oversized uploads.
- **No shell execution from user input.** Image processing uses Pillow/OpenCV — no `subprocess` calls with user-supplied data.
- **CORS.** `CORS_ALLOWED_ORIGINS` in `settings.py` is set from `.env`. Do not set `CORS_ALLOW_ALL_ORIGINS = True` in any environment.
- **`DEBUG=False` in production.** Django debug mode exposes stack traces and settings to the browser.
