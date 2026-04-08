# Changelog

All notable changes to SmartScanner are documented here, organized by phase and date.

---

## [Tooling] — 2026-04-08 — commit-push Changelog Integration

### Changed
- `.claude/commands/commit-push.md` — added Step 2 "Update the changelog" that invokes the `changelog-updater` agent before staging; renumbered subsequent steps
- `.claude/skills/commit-push/commit-push.md` — added Step 2 "Update the Changelog" section with `changelog-updater` agent invocation; renumbered Steps 3–7 accordingly

---

## [Tooling] — 2026-04-08 — .claude Project Structure

### Added
- `.claude/rules/coding-standards.md` — tech stack, code quality, constraints, and security rules extracted from `CLAUDE.md`
- `.claude/rules/workflow-gates.md` — phase gates, commit conventions, test requirements, and PR rules extracted from `CLAUDE.md`
- `.claude/commands/` — 6 slash commands: `/phase` (new phase workflow), `/scan` (end-to-end scan test), `/debug` (pipeline debugger), `/activate-venv`, `/run-tests`, `/check-logs`
- `.claude/skills/new-phase/new-phase.md` — full phase lifecycle skill (research → brainstorm → plan → TDD → gate check → docs → PR)
- `.claude/skills/scan-test/scan-test.md` — end-to-end scan validation skill with field-level pass/fail reporting
- `.claude/skills/debug-scan/debug-scan.md` — systematic pipeline-stage debugging skill using hypothesis/test/fix loop
- `.claude/agents/changelog-updater.md` — subagent that reads git history and existing changelog format, classifies changes, and writes precise entries to `docs/CHANGELOG.md`

### Changed
- `CLAUDE.md` slimmed from 120 → 50 lines; inline rule sections replaced with `@.claude/rules/` imports

---

## [Phase 22] — 2026-04-02 to 2026-04-07 — Targeted OCR Pipeline

### Added
- GLM-OCR fast path: if all scalar fields score ≥60% confidence (supplier ≥80%), LLM call is skipped entirely
- Targeted crop strategy: GLM-4.6V-Flash receives only the crops needed for missing/low-confidence fields instead of the full image
- Full-page image always sent for supplier identification (segmented header crops proved unreliable)
- Supplier layout profiles for 6 real suppliers: J&J, JFC International, Kyodo Beverage, NY Mutual Trading, Wine of Japan, Wismettac Asian Foods

### Changed
- Supplier confidence bar raised to 80% for OCR fast-path trust (was implicitly 60%)
- Supplier OCR result cross-validated against known supplier names in memory before accepting fast path
- Tax/registration number lines no longer misclassified as supplier name in OCR parser

### Deleted
- React/TypeScript frontend (`frontend/`) — removed to focus on backend API
- Legacy Django app structure: `smartscanner/__init__.py`, `asgi.py`, `wsgi.py`, `urls.py`, `settings.py` (consolidated then restored)
- `scanner/admin.py`, `scanner/models.py` — no ORM models needed
- `scanner/scanning/comparator.py` — replaced by targeted crop logic in engine
- `scanner/scanning/ocr.py` — replaced by `ocr_parser.py`
- `backend/test_scan_3785.py` — ad-hoc test script removed

---

## [Phase 21] — 2026-04-01 — Memory-Driven Parser + GLM-4.6V-Flash

### Added
- Memory-driven OCR parser: supplier extraction profile loaded from supplier memory to guide field parsing
- GLM-4.6V-Flash replaces Gemini as the vision LLM for all scan calls

### Changed
- Gemini API dependency removed entirely from engine and tracking
- OCR parser updated to use supplier-specific column maps and label overrides when available

---

## [Phase 20] — 2026-04-01 — OCR Parser & Segmentation Improvements

### Added
- `ocr_parser.py` structured extraction module with per-field `ParsedField` confidence dataclass
- `OCRParseResult.to_dict()` method for pipeline handoff

### Changed
- Segmentation improved: more robust line-item region detection using content density heuristics
- OCR text cleaning: strips HTML artifacts and markdown fences from GLM-OCR output before parsing

---

## [Phase 19] — 2026-04-01 — GLM-OCR-First Pipeline

### Changed
- Upgraded light mode to GLM-OCR-first pipeline (OCR → parse → fallback to vision only if needed)
- GLM-OCR uploads switched from WebP to JPEG (WebP rejected by GLM-OCR API)
- Math validator updated to fill missing `subtotal`/`total` from line item totals when those fields are absent

### Fixed
- Test mocks updated from `_call_claude` to `_call_api` after API refactor

---

## [Phase 18] — 2026-03-31 — GLM-OCR Scan Mode

### Added
- GLM-OCR scan mode integrated into the engine as a scan option
- Enhanced light and normal pipeline variants using GLM-OCR as the first pass

---

## [Phase 17] — 2026-03-28 — Integration Testing

### Added
- Integration test suite: 35 tests across 6 pipeline scenarios in `tests/test_integration.py`
- `integration_helpers.py`: shared fixture builders, mock patches, and response templates

---

## [Phase 16] — 2026-03-28 — Accuracy & API Usage Tracking + Dashboard

### Added
- `scanner/tracking/accuracy.py`: per-scan correction rate recording and rolling-window stats
- `scanner/tracking/api_usage.py`: model call counts and scan counts per mode
- `GET /api/stats/` endpoint returning combined accuracy and API usage data
- Frontend: `ScanStats`, `ResultTabs`, `Dashboard` components
- Frontend: multi-file `DropZone` and multi-scan flow in `App.tsx`
- TypeScript types: `ScanTab`, `StatsResponse`; `getStats` API service method

---

## [Phase 15] — 2026-03-27 — Supplier Layout Mapping

### Added
- `preprocessing/layout.py`: converts pixel crop bounding boxes to normalized `[0,1]` ratios
- `build_layout_descriptor()` function for creating layout JSON from segmentation results
- Supplier layout saving wired into scan engine: after each scan, layout is persisted to `data/suppliers/<id>/layout.json`
- Layout-aware segmentation: uses saved layout as a prior when detecting regions

---

## [Phase 14] — 2026-03-27 — Memory Learning from Corrections

### Added
- `scanner/memory/categorizer.py`: auto-categorizes user corrections into `misread`, `missing`, `hallucinated`
- `scanner/memory/corrections.py`: `apply_corrections()` helper to merge user edits into scan result
- `categorize_corrections()` and `apply_corrections()` exported from memory package
- `POST /api/confirm/` wired to update both supplier memory and general industry profile on confirmation

---

## [Phase 13] — 2026-03-27 — Editable Result Form

### Added
- Frontend `InvoiceForm` component: editable fields for all extracted invoice data
- `POST /api/confirm/` endpoint: accepts `{scan_result, corrections, confirmed_at}` and triggers memory update
- `ConfirmRequestSerializer` for confirm request validation

---

## [Phase 12] — 2026-03-27 — Three-Tier Inference System

### Added
- `scanner/memory/inference.py`: gap-filling engine with two active tiers
  - Tier 1: supplier-specific memory (confidence 80)
  - Tier 2: general industry memory (confidence 60)
- `run_inference()` function called at the end of every scan pipeline

---

## [Phase 11] — 2026-03-27 — Memory Interfaces and JSON Storage

### Added
- `scanner/memory/interface.py`: abstract base classes `SupplierMemory` and `GeneralMemory`
- `scanner/memory/json_store.py`: JSON file implementations; atomic writes via temp-file + rename
- `normalize_supplier_id()`: slugifies supplier names to safe directory-friendly IDs
- `data/suppliers/index.json`: supplier name → ID index
- Thread-safe file access via module-level lock

---

## [Phase 10] — 2026-03-27 — Mathematical Cross-Validation

### Added
- `scanner/scanning/validator.py`: validates `subtotal + tax = total` and `qty × price = line total`
- `auto_correct()`: fixes small rounding discrepancies within tolerance
- Math validation wired into end of scan pipeline

---

## [Phase 09] — 2026-03-27 — Three-Pass Scanning Pipeline

### Added
- Three-pass scan pipeline: primary scan → confirmation scan → tiebreaker on disagreement
- Tiebreaker focuses only on disagreed fields to avoid re-scanning the whole invoice
- Scan modes: Light (Sonnet × 3), Normal (Sonnet × 2 + Opus), Heavy (Opus × 3)
- Field comparison logic: fuzzy matching for strings, exact match for numerics

---

## [Phase 08] — 2026-03-27 — Single Scan with Claude API

### Added
- Claude API integration (`scanner/scanning/engine.py`): single-pass scan returning structured JSON with per-field confidence scores
- `ACCOUNTANT_SYSTEM_INSTRUCTION` system prompt for invoice extraction
- Pillow bumped to >=12.1.1 to fix CVE-2026-25990

---

## [Phase 07] — 2026-03-27 — OCR Pre-Pass (Tesseract)

### Added
- Tesseract OCR pre-pass: extracted text passed alongside image in Claude prompt for cross-referencing
- `scanner/scanning/ocr.py`: Tesseract integration with configurable `TESSERACT_CMD` env var

---

## [Phase 06] — 2026-03-27 — ROI Segmentation

### Added
- `scanner/preprocessing/segmentation.py`: CV2-based detection of header, line-items, and totals regions
- `segment_invoice()`: returns PIL crops for each region; falls back to full image on detection failure

---

## [Phase 05] — 2026-03-27 — Selective Image Processing

### Added
- `scanner/preprocessing/processor.py`: selective enhancement pipeline
- Only applies transforms flagged by the quality analyzer: histogram equalization, sharpening, denoising, Lanczos upscaling

---

## [Phase 04] — 2026-03-27 — Image Quality Assessment

### Added
- `scanner/preprocessing/analyzer.py`: measures blur (Laplacian variance), contrast (pixel std dev), noise, brightness, and resolution
- `analyze_quality()` returns a quality report dict used by the processor

---

## [Phase 03] — 2026-03-27 — Orientation & Skew Correction

### Added
- `scanner/preprocessing/orientation.py`: EXIF-based rotation + Hough-line skew detection and correction
- `auto_orient()` applied as the first step before any other preprocessing

---

## [Phase 02] — 2026-03-27 — React Frontend Scaffold

### Added
- React 18 + TypeScript frontend with Vite
- `DropZone`, `ScanControls`, `InvoiceForm`, `ItemsTable`, `QuotaBar` components
- `src/services/api.ts`: Axios-based API client
- `src/types/scan.ts`: TypeScript types for scan result and invoice fields

---

## [Phase 01] — 2026-03-27 — Backend Scaffolding

### Added
- Django 5 project: `smartscanner/` package with `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`
- `scanner` Django app with subpackages: `preprocessing/`, `scanning/`, `memory/`, `tracking/`
- `POST /api/scan/` placeholder endpoint with `ScanRequestSerializer`
- `data/` directory structure with `.gitkeep` placeholders
- `backend/requirements.txt`, `.gitignore`, `pytest.ini`
- `.env` template with all required environment variables

---

## [Design Spec] — 2026-03-26 — Project Foundation

### Added
- SmartScanner design specification: full feature set, architecture, API contract, memory system design, and 17-phase implementation plan
- Decision: React + TypeScript frontend, Django REST Framework backend
- Decision: JSON file storage for prototype; SQLite planned for production
