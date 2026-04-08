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

SmartScanner is an AI invoice scanner for restaurant supply invoices. The backend is a Django REST API; there is no active frontend (removed after phase 22). All image processing, OCR, and LLM calls happen server-side via a hybrid GLM-OCR + GLM-4.6V-Flash pipeline with a JSON-file memory system that improves accuracy over time.

See `docs/ARCHITECTURE.md` for the full system overview, data flow, component breakdown, and API reference.

---

## Rules

@.claude/rules/coding-standards.md
@.claude/rules/workflow-gates.md
