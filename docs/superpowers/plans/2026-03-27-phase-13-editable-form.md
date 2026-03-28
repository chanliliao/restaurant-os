# Phase 13: Editable Result Form UI

## Goal
Replace raw JSON display with editable form components. Highlight guessed fields.

## Changes

### Frontend
1. **`frontend/src/types/scan.ts`** — Add `FieldCorrection`, `ConfirmRequest`, `ConfirmResponse` types
2. **`frontend/src/components/InvoiceForm.tsx`** — Editable header form with confidence/inference badges and change tracking
3. **`frontend/src/components/ItemsTable.tsx`** — Editable line items table with add/remove rows and cell-level change tracking
4. **`frontend/src/services/api.ts`** — Add `confirmScan()` API call
5. **`frontend/src/styles/app.css`** — Add field-state CSS classes (low-confidence, inferred, changed, normal)
6. **`frontend/src/App.tsx`** — Wire form + table into scan result display, handle confirm flow

### Backend
7. **`backend/scanner/serializers.py`** — Add `ConfirmRequestSerializer`
8. **`backend/scanner/views.py`** — Add `confirm_scan_view` endpoint
9. **`backend/scanner/urls.py`** — Add `/api/confirm/` route
10. **`backend/tests/test_api.py`** — Add tests for confirm endpoint

## Security
- All form inputs rendered via React (no dangerouslySetInnerHTML) — XSS safe
- Django REST framework handles CSRF via session auth; API uses JSON content type
- Backend validates confirm payload shape via serializer

## Verification
- `cd frontend && npm run build` — TypeScript compiles
- `cd backend && python -m pytest tests/ -v` — Backend tests pass
