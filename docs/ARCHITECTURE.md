# SmartScanner Architecture

SmartScanner is an AI-powered invoice scanner for restaurant supply invoices. It extracts structured data from invoice images using a hybrid OCR + vision LLM pipeline, learns from corrections, and improves accuracy over time through a supplier memory system.

---

## System Overview

```
Client (HTTP)
     │
     ▼
Django REST API  (backend/)
     │
     ├── POST /api/scan/     ──▶  Scan Pipeline
     │                                │
     │                                ├── 1. Auto-orient (Pillow/CV2)
     │                                ├── 2. GLM-OCR (ZhipuAI API)
     │                                ├── 3. OCR Parse + confidence scoring
     │                                ├── 4. Fast path decision
     │                                ├── 5. Segmentation (CV2)
     │                                ├── 6. GLM Vision LLM (ZhipuAI API)
     │                                ├── 7. Math validation + auto-correct
     │                                ├── 8. Inference from memory
     │                                └── 9. Layout save to disk
     │
     ├── POST /api/confirm/  ──▶  Memory Update
     │                                │
     │                                ├── Apply corrections
     │                                ├── Categorize errors
     │                                ├── Update supplier memory
     │                                ├── Update general industry memory
     │                                └── Record tracking data
     │
     └── GET  /api/stats/    ──▶  Tracking Stats
                                      │
                                      ├── Accuracy stats (correction rate)
                                      └── API usage stats (call counts)
```

**No frontend is currently active.** The React + TypeScript frontend was removed after phase 22. The API can be consumed directly or via a future frontend.

---

## Data Flow

### Scan Request Flow

```
Image bytes (multipart upload)
    │
    ▼
auto_orient()                    # Fix EXIF rotation + skew
    │
    ▼
_optimize_for_glm()              # Resize/re-encode to JPEG for upload
    │
    ▼
_call_glm_ocr()                  # ZhipuAI layout_parsing endpoint
    │  returns: markdown/structured text
    ▼
parse_ocr_text()                 # Regex extraction → OCRParseResult
    │  returns: {supplier, date, invoice_number, subtotal, tax, total, items}
    │  each field has: value + confidence (0-100)
    ▼
Completeness check
    ├── All scalar fields ≥60% AND supplier ≥80%?
    │       └── YES → OCR Fast Path (no LLM)
    │
    └── Missing/low-confidence fields?
            │
            ▼
        segment_invoice()        # CV2 region detection
            │  returns: {header, line_items, totals} PIL crops
            ▼
        Build targeted crop list
            │  - Supplier: always full page
            │  - Totals: totals crop if segmentation found it
            │  - Items: items crop if segmentation found it
            ▼
        _call_glm_vision()       # GLM-4.6V-Flash with targeted images + prompt
            │  returns: JSON with extracted fields
            ▼
        Merge OCR + LLM results
    │
    ▼
validate_math() + auto_correct() # Arithmetic cross-check
    │
    ▼
run_inference()                  # Fill gaps from memory
    │  Tier 1: supplier history (confidence 80)
    │  Tier 2: industry profile (confidence 60)
    ▼
build_layout_descriptor()        # Compute normalized region ratios
    │
    ▼
supplier_memory.update_layout()  # Persist layout to disk
    │
    ▼
Return structured invoice JSON
```

### Confirm + Learn Flow

```
POST /api/confirm/
{scan_result, corrections, confirmed_at}
    │
    ▼
apply_corrections()              # Merge edits into canonical result
    │
    ▼
categorize_corrections()         # Tag each correction: misread / missing / hallucinated
    │
    ▼
general_memory.update_from_scan()    # Update industry-wide profile
    │
    ▼
supplier_memory.save_scan()          # Update supplier history + common values
    │
    ▼
record_scan_accuracy()               # Log correction count vs total fields
record_api_usage()                   # Log model calls and scan mode
```

---

## Component Architecture

### `scanner/scanning/`

| File | Responsibility |
|------|---------------|
| `engine.py` | Top-level `scan_invoice()` orchestrator; all GLM API calls; fast-path decision logic |
| `ocr_parser.py` | Regex-based structured extraction from raw OCR text; produces `OCRParseResult` with per-field `ParsedField` confidence |
| `prompts.py` | All LLM prompt builders: `build_smart_pass_prompt()`, `build_verification_prompt()`, `ACCOUNTANT_SYSTEM_INSTRUCTION` |
| `validator.py` | Math cross-validation (`validate_math()`); tolerance-based auto-correction (`auto_correct()`) |

**Key data structures in `ocr_parser.py`:**
```python
@dataclass
class ParsedField:
    value: str | float | None
    confidence: int        # 0-100
    source: str            # "ocr" or "missing"

@dataclass
class OCRParseResult:
    supplier: ParsedField
    invoice_number: ParsedField
    date: ParsedField
    subtotal: ParsedField
    tax: ParsedField
    total: ParsedField
    items: list[ParsedItem]
    raw_text: str
```

### `scanner/preprocessing/`

| File | Responsibility |
|------|---------------|
| `orientation.py` | EXIF rotation correction + Hough-line skew detection and correction |
| `analyzer.py` | Image quality metrics: blur (Laplacian variance), contrast (pixel std dev), brightness, noise, resolution |
| `processor.py` | Selective enhancement: only applies transforms flagged by analyzer (equalization, sharpening, denoising, upscaling) |
| `segmentation.py` | CV2-based detection of invoice regions; returns `{header, line_items, totals}` as PIL crops; falls back to full image |
| `layout.py` | Converts pixel bounding boxes to normalized `[0,1]` ratios for `layout.json` storage |

### `scanner/memory/`

| File | Responsibility |
|------|---------------|
| `interface.py` | Abstract base classes `SupplierMemory` and `GeneralMemory` |
| `json_store.py` | Concrete JSON file implementations; atomic writes; supplier ID normalization and validation |
| `inference.py` | Two-tier gap-filling: supplier memory → industry memory |
| `categorizer.py` | Classifies user corrections as `misread`, `missing`, or `hallucinated` |
| `corrections.py` | `apply_corrections()`: merges user edits into scan result dict |

**Supplier ID normalization** (`json_store.normalize_supplier_id()`):
- Lowercases, strips special chars, replaces spaces with hyphens
- Rejects path traversal (`..`, `/`, `\`) before normalization
- Example: `"Wismettac Asian Foods Inc."` → `"wismettac-asian-foods-inc"`

### `scanner/tracking/`

| File | Responsibility |
|------|---------------|
| `accuracy.py` | Records `corrections_count / total_fields` per scan; computes rolling-window aggregate accuracy |
| `api_usage.py` | Logs per-scan: model names used, call count, scan mode; aggregates totals |

### `scanner/views.py`

Three function-based views using DRF decorators. Memory store instances are created via `_get_supplier_memory()` / `_get_general_memory()` factory functions — these are patchable in tests without monkey-patching the class itself.

---

## API Layer

### `POST /api/scan/`

**Request:** `multipart/form-data`
```
image: <binary image file>   (JPEG, PNG; max 10 MB)
```
Optional query param: `?debug=1` adds pipeline metadata to response.

**Response (200):**
```json
{
  "supplier": "Wismettac Asian Foods Inc",
  "date": "2026-03-15",
  "invoice_number": "INV-00123",
  "subtotal": 1234.56,
  "tax": 111.11,
  "total": 1345.67,
  "items": [
    {
      "name": "Jasmine Rice 50lb",
      "quantity": 10,
      "unit": "bag",
      "unit_price": 45.00,
      "total": 450.00,
      "confidence": 90
    }
  ],
  "confidence": {
    "supplier": 95,
    "date": 80,
    "invoice_number": 70
  },
  "inferences": {
    "tax_rate": {"value": 0.09, "source": "tier1_supplier", "confidence": 80}
  },
  "scan_metadata": {
    "mode": "glm_ocr",
    "api_calls": 1,
    "scans_performed": 1,
    "models_used": ["glm-ocr"],
    "duration_ms": 3200
  }
}
```

### `POST /api/confirm/`

**Request:** `application/json`
```json
{
  "scan_result": { ...full scan result... },
  "corrections": [
    {"field": "supplier", "old_value": "Wismettac", "new_value": "Wismettac Asian Foods Inc"}
  ],
  "confirmed_at": "2026-04-07T10:30:00Z"
}
```

**Response (200):**
```json
{
  "status": "confirmed",
  "corrections_count": 1,
  "confirmed_at": "2026-04-07T10:30:00+00:00",
  "memory_updated": true
}
```

### `GET /api/stats/`

**Response (200):**
```json
{
  "accuracy": {
    "total_scans": 42,
    "avg_correction_rate": 0.08,
    "by_mode": { "glm_ocr": { "scans": 42, "avg_corrections": 0.08 } }
  },
  "api_usage": {
    "total_calls": 45,
    "by_model": { "glm-ocr": 42, "glm-4.6v-flash": 3 }
  }
}
```

---

## Library Modules

| Library | Version | Usage |
|---------|---------|-------|
| Django | >=5.0,<6.0 | Web framework, URL routing, settings, WSGI |
| djangorestframework | >=3.15,<4.0 | Serializers, `@api_view`, DRF parsers |
| django-cors-headers | >=4.3,<5.0 | CORS headers for cross-origin API access |
| python-dotenv | >=1.0,<2.0 | Loads `.env` into `os.environ` at startup |
| Pillow | >=12.1.1,<13.0 | Image open/save, EXIF reading, resize, format conversion |
| opencv-python-headless | >=4.9,<5.0 | Skew detection (Hough lines), region detection (CV2 contours), grayscale conversion |
| requests | (transitive) | HTTP calls to GLM-OCR and GLM Vision endpoints |
| pytest | >=8.0,<9.0 | Test runner |
| pytest-django | >=4.8,<5.0 | Django settings injection for pytest (`DJANGO_SETTINGS_MODULE`) |

### External APIs

| Service | Endpoint | Auth |
|---------|----------|------|
| GLM-OCR | `https://open.bigmodel.cn/api/paas/v4/layout_parsing` | `Authorization: <api_key>` (no Bearer prefix) |
| GLM-4.6V-Flash | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `Authorization: Bearer <api_key>` |

GLM Vision retries up to 3 times on HTTP 429 with exponential backoff (5s, 10s, 20s). GLM-OCR does not retry.

---

## File Storage Layout

```
backend/
├── data/
│   ├── general/
│   │   ├── industry_profile.json    # Aggregate patterns: tax rates, common items
│   │   └── item_catalog.json        # Known items with typical price ranges
│   └── suppliers/
│       ├── index.json               # {"wismettac-asian-foods-inc": "Wismettac Asian Foods Inc", ...}
│       └── <supplier-id>/
│           ├── profile.json         # {scan_history: [...], common_values: {...}}
│           └── layout.json          # {header_region: {x,y,w,h}, items_region: {...}, totals_region: {...}}
└── smartscanner/
    ├── settings.py                  # All config; reads from .env via python-dotenv
    └── urls.py                      # Root URL: /api/ → scanner.urls
```

`DATA_DIR` in `settings.py` defaults to `BASE_DIR / "data"` and is referenced by `json_store.py` via `django.conf.settings`.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| JSON files over database | Prototype speed; no migration overhead; data is human-readable for debugging |
| GLM-OCR first, LLM second | OCR is cheaper and faster; LLM called only for fields OCR can't confidently extract |
| Full-page for supplier ID | Segmented header crops frequently captured the wrong region; full page is more reliable |
| Atomic file writes | Prevents corrupt JSON if the process dies mid-write; `os.replace()` is atomic on the same volume |
| Abstract memory interfaces | Allows swapping JSON store for a database-backed store without changing the pipeline or tests |
| Confidence as integer 0–100 | Simpler to threshold and display than floats; consistent across OCR parser and inference tiers |
