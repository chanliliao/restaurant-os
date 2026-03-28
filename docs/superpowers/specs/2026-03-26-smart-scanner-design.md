# SmartScanner Design Spec

## Overview

SmartScanner is a web application with a React frontend and Python (Django REST) backend that uses Claude AI to extract structured data from restaurant receipt and invoice images. It is a specialty invoice scanning agent featuring:

- Intelligent image preprocessing with auto-detect quality correction
- Region-of-interest segmentation with supplier-aware layout mapping
- Three-pass scanning pipeline with tiebreaker logic
- Three scan modes (Light/Normal/Heavy) for cost vs accuracy control
- Three-tier memory system (supplier-specific → general industry → AI reasoning)
- Confidence scoring (0-100) per field
- User feedback loop — corrections immediately improve memory
- Accuracy and API usage tracking per scan and per mode
- Auto-categorization of errors (misread, missing, hallucinated)

## Architecture

Two-tier architecture: React frontend for the UI, Django REST Framework backend for the scanning agent logic. The frontend communicates with the backend via REST API. All AI/image processing happens server-side in Python.

**Tech Stack:**

**Backend (Python):**
- Python 3.11+
- Django 5.x + Django REST Framework
- django-cors-headers (for React dev server)
- Anthropic Python SDK (Claude Opus + Sonnet for scanning)
- Pillow + OpenCV for image preprocessing
- Tesseract OCR (pytesseract) for complementary text extraction
- JSON files for storage (prototype), SQLite for production

**Frontend (React + TypeScript):**
- React 18+ with Vite + TypeScript
- React Router (if needed for future pages)
- Axios for API calls
- TypeScript strict mode for type safety
- CSS Modules or plain CSS for styling

## 1. Image Preprocessing Pipeline

### Step 1: Orientation & Skew Correction
Before any quality-based preprocessing, fix geometric issues:
- **Auto-rotation** — detect and correct 90/180/270 degree rotations using EXIF data and orientation detection
- **Deskewing** — detect tilt angle using Hough line transform and rotate to align text horizontally
- **Perspective correction** — detect trapezoidal distortion (photo taken at angle) and apply perspective warp to produce a flat, rectangular image

This step is critical — a tilted or rotated image is one of the biggest sources of misreads.

### Step 2: Quality Assessment
Analyze the corrected image using Pillow/OpenCV to measure:
- Brightness (mean pixel intensity)
- Contrast (standard deviation of pixel values)
- Blur level (Laplacian variance)
- Noise level (high-frequency component analysis)
- Resolution (pixel dimensions)

### Step 3: Selective Processing
Only apply needed transformations based on quality assessment:
- Low contrast → histogram equalization
- Blurry → sharpening filter
- Noisy → Gaussian/bilateral denoising
- Low resolution → Lanczos upscaling
- Color issues → grayscale conversion

### Step 4: Multi-Variant Image Preparation
Produce two image variants for each scan pass:
- **Original** (after orientation/skew correction only)
- **Preprocessed** (after all selective processing)

Both variants are sent to Claude in the same message so the model can cross-reference both. This handles cases where preprocessing helps some areas but hurts others (e.g., over-sharpening artifacts obscuring small text).

The original uploaded image is always preserved separately.

### Debug Mode
Optional toggle in the UI. When enabled, saves each preprocessing stage to a temp folder (original, orientation-corrected, preprocessed, ROI crops) viewable in the UI for debugging why a scan went wrong.

## 2. Region-of-Interest Segmentation

Before scanning, detect and crop the image into focused regions:
- **Header region** — supplier name, address, date, invoice number
- **Line items region** — the table of items with names, quantities, prices
- **Totals region** — subtotal, tax, total, payment info

Each region is scanned separately with focused prompts tuned to that region's content. Smaller, targeted areas yield higher per-field accuracy than scanning the whole image at once.

If region detection fails (e.g., unusual layout), fall back to full-image scanning.

### Supplier-Aware Layout Mapping
On the first scan of a new supplier, the system maps the layout:
- Where the supplier name appears (e.g., top-left)
- Where the date and invoice number appear (e.g., top-right)
- Where the items table starts and ends
- Where totals are positioned (e.g., bottom-right)

This layout map is saved to the supplier profile. On subsequent scans from the same supplier, ROI segmentation uses the saved layout for faster, more accurate region detection.

## 3. OCR Pre-Pass

Run Tesseract OCR on the preprocessed image before sending to Claude. The OCR text is passed alongside the image in the Claude prompt as supplementary data. This gives the model two sources of information to cross-reference — especially helpful for small, faded, or low-contrast text that vision alone might miss.

## 4. Three-Pass Scanning Pipeline

### Scan Modes

Three modes control which AI model is used for each pass:

| Mode | Scan 1 | Scan 2 | Scan 3 (Tiebreaker) | Best For |
|------|--------|--------|---------------------|----------|
| Light | Sonnet | Sonnet | Sonnet | Clean images, budget-conscious |
| Normal | Sonnet | Sonnet | Opus | General use, good balance |
| Heavy | Opus | Opus | Opus | Fuzzy/blurry/damaged, max accuracy |

**Prototype:** User selects mode via dropdown before each scan.
**Future:** Auto-select mode based on image quality assessment and accuracy/cost data.

All three modes do up to 3 passes. Even Opus benefits from confirmation — the triple-check catches mistakes any single call can make.

### Scan 1 (Primary)
For each region (or full image if no regions detected), send both image variants (original + preprocessed) plus the Tesseract OCR text to the selected model with a structured prompt requesting flat JSON extraction with per-field confidence scores (0-100).

### Scan 2 (Confirmation)
Send the same inputs with a differently worded prompt (to avoid echo bias). Compare results field-by-field against Scan 1.

### Scan 3 (Tiebreaker)
Only triggered when Scans 1 and 2 disagree on any field. Sends the image with a focused prompt targeting ONLY the disagreed fields, plus context from both previous results. The tiebreaker result is final.

### Mathematical Cross-Validation
After all scan passes complete, run arithmetic checks on the final result:
- `qty × price = line total` for each item
- `sum of line totals = subtotal`
- `subtotal + tax = total`
- `tax / subtotal ≈ expected tax rate` (within tolerance)

If any math doesn't check out, send the specific contradiction back to Claude with the image and ask it to re-examine those fields. This catches errors that even three agreeing scans might get wrong.

### Field Comparison Logic
- String fields: fuzzy matching (handle minor formatting differences)
- Numeric fields: exact match required
- Array fields (items): match by item name, compare qty/price individually

## 5. Three-Tier Inference System

When fields are missing, fuzzy, or low-confidence, apply inference in priority order:

### Tier 1: Supplier-Specific Memory (highest priority)
Check the supplier profile for known values:
- Common item names and typical prices
- Tax rate patterns
- Invoice format/layout conventions
- Typical quantities and order frequency
- Example: "ABC Foods always charges $3.99/lb for chicken breast"

### Tier 2: General Industry Memory (learned over time)
Aggregated patterns across ALL scans from ALL suppliers:
- Common restaurant supply item names and typical price ranges
- Regional tax rate patterns
- Common invoice formats across the restaurant supply industry
- Example: "Chicken breast typically ranges $2.50-$5.00/lb across suppliers"

This knowledge base grows with every scan processed by the system.

### Tier 3: AI Contextual Reasoning (fallback)
When no historical data exists at any level, make a Claude call with:
- The partially extracted data
- Invoice domain knowledge (e.g., "subtotal = sum of line items", "tax is typically a percentage of subtotal", "invoice numbers are sequential")
- Ask Claude to identify keywords and contextual clues on the image to fill gaps and validate existing extractions

All inferred fields are flagged in the `confidence` object with their source.

## 6. Supplier Memory System

### Storage Structure (JSON Prototype)
```
data/
├── general/
│   ├── industry_profile.json   # cross-supplier learned patterns
│   └── item_catalog.json       # known items, typical price ranges
├── suppliers/
│   ├── index.json              # maps supplier names to IDs
│   └── {supplier_id}/
│       ├── profile.json        # learned patterns, common values, tax rates
│       ├── layout.json         # supplier-specific invoice layout mapping
│       └── scans/
│           ├── 2026-03-25_001.json
│           └── 2026-03-25_002.json
└── stats/
    ├── accuracy.json           # per-scan, per-supplier, per-mode accuracy
    └── api_usage.json          # API call counts by model and mode
```

### Learning Mechanism
After each successful scan (user confirms), update:
- **Supplier profile** — item names, prices, tax rates, format notes
- **Supplier layout** — invoice format/template mapping for ROI
- **General industry profile** — aggregate patterns across all suppliers
- **Item catalog** — growing database of known items and price ranges

### Memory Update Policy
Immediate trust — when a user corrects a value and confirms, the correction updates the supplier profile and general knowledge immediately. No waiting for multiple confirmations.

### Storage Interface
`SupplierMemory` class with methods: `get_profile()`, `save_scan()`, `infer_missing()`, `get_layout()`, `update_layout()`. `GeneralMemory` class with methods: `get_industry_profile()`, `get_item_catalog()`, `update_from_scan()`. When migrating to SQLite, swap the implementations behind these interfaces.

## 7. Confidence Scoring

Each field returned by Claude includes a confidence score from 0-100:
- **90-100:** High confidence — clear text, consistent across scans
- **60-89:** Medium confidence — somewhat readable, minor uncertainty
- **0-59:** Low confidence — blurry, guessed, or inferred

Confidence scores are used for:
- UI highlighting — fields below threshold are visually flagged
- Inference triggering — low-confidence fields are candidates for memory-based inference
- Future auto-mode selection — low average confidence → suggest Heavy mode
- Accuracy correlation — track if low-confidence scores predict user corrections

## 8. Error Categorization

When a user corrects a field, the system auto-categorizes the error type by comparing the original image region, the scanned value, and the correction:

- **Misread** — scanner saw something wrong (e.g., "Chckn" → "Chicken"). The text was visible but misinterpreted. Indicates preprocessing or vision issues.
- **Missing** — field wasn't visible on the image, had to be guessed. Indicates the image quality is too poor for that area or the field genuinely isn't present.
- **Hallucinated** — scanner invented a value that wasn't on the image at all. Indicates prompt issues that need tightening.

Error types are tracked per scan, per supplier, and per mode. This data reveals:
- Lots of misreads → preprocessing pipeline needs improvement
- Lots of missing → memory/inference system needs improvement
- Lots of hallucinations → prompt engineering needs tightening

## 9. Output Format

Flat JSON structure:
```json
{
  "supplier": "ABC Foods",
  "date": "2026-03-25",
  "invoice_number": "INV-1234",
  "items": [
    {"name": "Chicken Breast", "qty": 10, "unit": "lb", "price": 3.99}
  ],
  "subtotal": 39.90,
  "tax": 3.19,
  "total": 43.09,
  "confidence": {
    "supplier": 98,
    "date": 95,
    "invoice_number": 92,
    "items.0.name": 88,
    "items.0.qty": 95,
    "items.0.price": 72,
    "subtotal": 90,
    "tax": 45,
    "total": 90
  },
  "inference_sources": {
    "tax": "inferred_from_history"
  },
  "scan_metadata": {
    "mode": "normal",
    "scan_passes": 2,
    "tiebreaker_triggered": false,
    "math_validation_triggered": true,
    "api_calls": {
      "sonnet": 2,
      "opus": 0
    }
  }
}
```

The `inference_sources` object flags fields that were:
- `inferred_from_supplier` — filled from supplier-specific memory
- `inferred_from_industry` — filled from general industry memory
- `inferred_from_context` — filled by AI contextual reasoning
- `tiebreaker_resolved` — disagreed between scan 1 and 2, resolved by scan 3
- `math_corrected` — corrected by mathematical cross-validation

## 10. React Frontend

### Single Page Layout
- **Top:** Drag-and-drop zone component for multiple images (react-dropzone or HTML5 drag/drop). Each dropped image becomes its own invoice.
- **Controls:** Scan mode dropdown (Light/Normal/Heavy) + Debug mode toggle
- **Middle:** Tabbed results view — one tab per scanned invoice + a summary tab
- **Each invoice tab:** Editable form component with scan results (see below)
- **Summary tab:** Batch totals, overall accuracy, total API calls

### Editable Result Form Component
Each scan result displays as a form, not raw JSON:
- **Header fields:** Supplier, date, invoice number — each as a labeled input pre-filled with scanned value
- **Items table:** Editable table with columns for name, qty, unit, price. Users can add/remove rows if the scanner missed or hallucinated items.
- **Totals fields:** Subtotal, tax, total — each as a labeled input
- **Highlighting:** Fields that were guessed/inferred or have low confidence are highlighted with a distinct color/badge showing the inference source
- **No modal interruption:** User reviews the form, edits any wrong values inline, then clicks "Confirm All"
- **Tracking:** System tracks which fields the user changed before confirming. Fewer changes = higher accuracy.

### Scan Stats Component
At the bottom of each invoice tab:
- Mode used (Light/Normal/Heavy)
- API calls made (X Sonnet, Y Opus)
- Whether tiebreaker was triggered
- Whether math validation was triggered
- Scan accuracy (after user confirms)

### Mode Comparison Dashboard Component
Accessible from the summary tab:
- Per-mode accuracy averages: "Light: 78% | Normal: 89% | Heavy: 95%"
- Per-mode API usage averages
- Per-supplier accuracy over time
- Running totals across all scans

### API Endpoints (Django REST)
- `POST /api/scan/` — accepts image file + mode parameter, returns final JSON result
- `POST /api/confirm/` — accepts original scan + user corrections, updates memory
- `GET /api/stats/` — returns accuracy and API usage stats

## 11. Accuracy Tracking

### Measurement
Accuracy is measured by user corrections:
- `accuracy = (total_fields - user_corrections) / total_fields × 100%`
- A "field" includes each top-level value and each item row cell (name, qty, unit, price)
- Adding or removing item rows counts as corrections

### Tracking Levels
- **Per-scan:** accuracy %, fields corrected, error types
- **Per-supplier:** running accuracy over all scans for that supplier (should improve over time as memory builds)
- **Per-mode:** running accuracy averages for Light, Normal, Heavy
- **Overall:** global running accuracy across all scans

### Storage
Accuracy data stored in `data/stats/accuracy.json`. API usage stored in `data/stats/api_usage.json`.

## 12. Project Structure

```
SmartScanner/
├── backend/                    # Python Django REST API
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env                    # ANTHROPIC_API_KEY
│   ├── smartscanner/           # Django project settings
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── scanner/                # Main Django app
│   │   ├── views.py            # REST API endpoints
│   │   ├── urls.py
│   │   ├── serializers.py      # DRF serializers
│   │   ├── preprocessing/
│   │   │   ├── orientation.py  # Rotation, deskew, perspective correction
│   │   │   ├── analyzer.py     # Quality assessment
│   │   │   ├── processor.py    # Selective image processing
│   │   │   └── segmentation.py # ROI detection + supplier-aware layout
│   │   ├── scanning/
│   │   │   ├── ocr.py          # Tesseract OCR pre-pass
│   │   │   ├── engine.py       # Three-pass scan orchestration + mode selection
│   │   │   ├── prompts.py      # Claude prompt templates
│   │   │   ├── comparator.py   # Field-by-field comparison + error categorization
│   │   │   └── validator.py    # Mathematical cross-validation
│   │   ├── memory/
│   │   │   ├── interface.py    # SupplierMemory + GeneralMemory abstract interfaces
│   │   │   ├── json_store.py   # JSON file implementation
│   │   │   └── inference.py    # Three-tier inference logic
│   │   └── tracking/
│   │       ├── accuracy.py     # Accuracy measurement and tracking
│   │       └── api_usage.py    # API call counting per model/mode
│   ├── data/                   # All persistent data (gitignored)
│   │   ├── general/
│   │   ├── suppliers/
│   │   └── stats/
│   └── tests/
│       ├── fixtures/           # Test images (clear, blurry, rotated, etc.)
│       ├── expected/           # Golden JSON outputs
│       ├── test_preprocessing.py
│       ├── test_scanning.py
│       ├── test_memory.py
│       ├── test_inference.py
│       ├── test_validator.py
│       ├── test_accuracy.py
│       └── test_integration.py
├── frontend/                   # React + TypeScript (Vite)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── types/
│   │   │   └── scan.ts         # TypeScript interfaces for scan data
│   │   ├── components/
│   │   │   ├── DropZone.tsx     # Drag-and-drop file upload
│   │   │   ├── ScanControls.tsx # Mode dropdown + debug toggle
│   │   │   ├── ResultTabs.tsx   # Tabbed invoice results
│   │   │   ├── InvoiceForm.tsx  # Editable scan result form
│   │   │   ├── ItemsTable.tsx   # Editable items table with add/remove
│   │   │   ├── ScanStats.tsx    # Per-scan stats display
│   │   │   └── Dashboard.tsx    # Mode comparison + accuracy dashboard
│   │   ├── services/
│   │   │   └── api.ts          # Axios API client
│   │   └── styles/
│       │   └── app.css
│   └── public/
└── docs/
```

## 13. Verification Strategy

### Unit Tests Per Module
- **Orientation:** Test images rotated 90/180/270, tilted 5-15 degrees, perspective-warped. Verify text lines near 0 degrees after correction.
- **Quality Assessment:** Known-quality images (dark, washed out, blurry, noisy, low-res, clean). Assert correct detection of each issue.
- **Selective Processing:** Compare pixel metrics before/after (contrast increase, blur variance increase, etc.).
- **ROI Segmentation:** Draw bounding boxes on output for visual verification. Test fallback with non-receipt images.
- **OCR Pre-Pass:** Compare Tesseract output against known receipt text.
- **Scan Engine:** Known receipt with all fields clear — all scans agree. Degraded version — verify tiebreaker triggers.
- **Math Validator:** Feed intentionally wrong math, verify it catches contradictions.
- **Inference:** Same supplier scanned twice, second with obscured field — verify Tier 1 fills it. New supplier with missing tax — verify Tier 2/3 infer it.
- **Memory:** Scan 3 invoices from same supplier, verify profile accumulates patterns.
- **Accuracy Tracking:** Simulate user corrections, verify accuracy calculation is correct.
- **Error Categorization:** Simulate misread, missing, hallucinated corrections — verify auto-classification.

### Integration Tests
- **Golden test set:** 5-10 real receipts with manually created expected JSON output
- **Full pipeline test:** Drop each image through the entire pipeline, compare output JSON against expected, score field-by-field accuracy
- **Mode comparison test:** Run same images through Light, Normal, Heavy — compare accuracy and API call counts

### Debug Mode Verification
- Enable debug mode, run a scan, verify all intermediate outputs are saved and viewable

## 14. Phased Implementation Breakdown

Each phase is a small, independent feature. Build it, test it, verify it works, then move on. Each phase starts in a **fresh context window** so the agent has clean context and reads the latest state of the codebase and this plan.

### GitHub Repository
**Repo:** https://github.com/chanliliao/SmartScanner
**Remote:** origin (master branch)

### Workflow Per Phase
1. Open fresh context window
2. Read this spec + the implementation tracker (below)
3. **Plan first** — invoke the writing-plans skill to create a detailed plan for this phase before writing any code
4. Build the phase's feature
5. Write tests and verify it works
6. **Security scan** — review all code written in this phase for security issues:
   - Input validation (file uploads, API params, user corrections)
   - Injection vulnerabilities (command injection via filenames, path traversal)
   - API key exposure (never in frontend, never in git)
   - CORS configuration (restrict origins in production)
   - File handling (validate image types, size limits, sanitize filenames)
   - Dependency vulnerabilities (`pip audit` for Python, `npm audit` for frontend)
   - Fix any issues found before committing
7. Commit with clear message describing what was built
8. **Push to GitHub** (`git push origin master`)
9. Update the implementation tracker (below) with: what was done, files created/modified, test results, security scan results, any deviations from plan
10. Commit and **push** the tracker update to GitHub
11. Close context window

**Every phase MUST:**
- Start with a plan (writing-plans skill)
- End with a security scan
- End with code pushed to GitHub
No exceptions.

### Implementation Tracker

This section is updated after each phase is completed. It serves as the handoff document between context windows.

```
Phase 01:  [x] Complete — Backend scaffolding (Django REST)
  - Django 5.x + DRF + CORS configured
  - Scanner app with preprocessing/, scanning/, memory/, tracking/ subpackages
  - Placeholder POST /api/scan/ endpoint with validation
  - Data directory structure with initial JSON files
  - 6 passing tests for scan endpoint
  - Security scan: Pillow bumped for CVE-2026-25990, all else clean
Phase 02:  [x] Complete — Frontend scaffolding (React + TypeScript)
  - Vite 8 + React 19 + TypeScript 5.9 (strict mode)
  - TypeScript interfaces: ScanMode, LineItem, ScanResponse, ScanRequest
  - Axios API client (src/services/api.ts) with multipart/form-data POST
  - DropZone component: HTML5 drag-and-drop + click-to-browse with client-side
    type validation (image/*) and 20 MB size limit (defense in depth)
  - Vite proxy: /api/* -> http://localhost:8000
  - npm run build: 0 TypeScript errors, production build succeeds
  - npm audit: 0 vulnerabilities
  - Files: frontend/ (index.html, package.json, tsconfig.json, vite.config.ts,
    src/main.tsx, src/App.tsx, src/types/scan.ts, src/services/api.ts,
    src/components/DropZone.tsx, src/styles/app.css)
Phase 02b: [x] Complete — Scan controls UI (mode dropdown + debug toggle)
  - ScanControls component: Light/Normal/Heavy dropdown + Debug mode checkbox
  - Controls wired into App state -> DropZone -> API call sends mode parameter
  - Backend already accepts and echoes mode parameter (no backend changes needed)
  - Files: src/components/ScanControls.tsx
Phase 03:  [x] Complete — Orientation & skew correction
  - fix_orientation: EXIF-based auto-rotation (90/180/270 + flip/transpose)
  - deskew: Hough line transform detects tilt angle, rotates to straighten
  - correct_perspective: contour-based quadrilateral detection + perspective warp
  - auto_orient: orchestrator running all three in sequence
  - All functions accept both PIL Image and numpy array inputs
  - 22 passing tests with programmatically generated fixtures
  - Files: scanner/preprocessing/orientation.py, tests/test_preprocessing.py
Phase 04:  [x] Complete — Quality assessment
  - analyze_quality(): measures brightness, contrast, blur, noise, resolution
  - Robust noise estimation using Immerkaer median-Laplacian method
  - Returns structured report with per-metric values, issues, and overall_quality (good/fair/poor)
  - Accepts both PIL Image and numpy array inputs
  - 34 total passing tests (22 orientation + 12 analyzer)
  - Security: no file I/O, no shell commands, all in-memory processing
  - Files: scanner/preprocessing/analyzer.py, tests/test_preprocessing.py
Phase 05:  [x] Complete — Selective image processing
  - enhance_contrast (CLAHE), sharpen (unsharp mask), denoise (NLMeans), upscale (Lanczos), to_grayscale
  - selective_process applies only needed transforms based on quality report flags
  - prepare_variants orchestrates: auto_orient -> analyze_quality -> selective_process -> returns {original, preprocessed, quality_report}
  - Processing order: upscale -> denoise -> enhance_contrast -> sharpen -> grayscale
  - Accepts both PIL Image and numpy array inputs
  - 66 total passing tests (22 orientation + 12 analyzer + 32 processor)
  - Security: no file I/O, no shell commands, all in-memory processing
  - Files: scanner/preprocessing/processor.py, tests/test_preprocessing.py
Phase 06:  [x] Complete — ROI segmentation
  - detect_regions: morphological horizontal line detection to find invoice dividers
  - crop_regions: crops image into detected bounding boxes, returns dict of PIL Images
  - segment_invoice: orchestrator with three strategies — line detection, heuristic (25/50/25), full-image fallback
  - Returns header, line_items, totals regions plus full image, bounding boxes, and detection status
  - Heuristic fallback when no clear dividers found; full-image fallback for tiny images (<50px)
  - 87 total passing tests (22 orientation + 12 analyzer + 32 processor + 21 segmentation)
  - Security: no file I/O, no shell commands, all in-memory processing
  - Files: scanner/preprocessing/segmentation.py, tests/test_preprocessing.py
Phase 07:  [x] Complete — OCR pre-pass
  - scanner/scanning/ocr.py: extract_text, extract_text_from_regions, ocr_prepass
  - Graceful degradation: TesseractNotFoundError returns empty string with warning log
  - Supports PIL Image and numpy array input, auto-converts to PIL
  - extract_text_from_regions processes segment_invoice() output dict, skips None regions
  - 107 total passing tests (93 preprocessing + 14 scanning/OCR, all mocked)
  - Security: no file I/O, no shell commands, no user-controlled strings to subprocess
  - Files: scanner/scanning/ocr.py, scanner/scanning/__init__.py, tests/test_scanning.py
Phase 08:  [x] Complete — Single scan with Claude
  - prompts.py: build_scan_prompt() with OCR text, confidence scores, inference_sources
  - engine.py: scan_invoice() orchestrator with prepare_variants + ocr_prepass + Claude API
  - Model selection: light/normal -> claude-sonnet-4-20250514, heavy -> claude-opus-4-0-20250514
  - _call_claude() with vision content blocks (base64 images), _parse_json_response() with fence stripping
  - Error handling: API errors, JSON parse failures, unexpected exceptions all return structured error result
  - views.py: replaced dummy endpoint with real scan_invoice engine call
  - Debug mode: ?debug=true returns elapsed time, model, OCR text, quality report
  - 146 total passing tests (93 preprocessing + 53 scanning — all mocked, no real API calls)
  - Security: no API keys in source, input validation via serializer, safe JSON parsing, 10MB upload limit
  - Files: scanner/scanning/prompts.py, scanner/scanning/engine.py, scanner/views.py, tests/test_scanning.py
Phase 09:  [x] Complete — Three-pass scanning with tiebreaker
  - Three-pass pipeline: Scan 1 (primary) + Scan 2 (confirmation) + optional Scan 3 (tiebreaker)
  - Field-by-field comparator with fuzzy string matching (difflib, threshold 0.85) and exact numeric matching
  - Tiebreaker only triggered when disagreements exist (saves API calls when scans agree)
  - Mode-based model selection: light=all Sonnet, normal=Sonnet+Sonnet+Opus, heavy=all Opus
  - scan_metadata includes: scans_performed, tiebreaker_triggered, agreement_ratio, models_used, api_calls
  - 188 total passing tests (93 preprocessing + 95 scanning — all mocked, no real API calls)
  - Files: scanner/scanning/prompts.py, scanner/scanning/comparator.py, scanner/scanning/engine.py, scanner/scanning/__init__.py, tests/test_scanning.py
Phase 10:  [x] Complete — Mathematical cross-validation
  - validate_math() checks line totals (qty x price), subtotal (sum of items), grand total (subtotal + tax)
  - auto_correct() applies cascading fixes: line totals -> subtotal -> total
  - 0.01 tolerance for floating point, graceful None/null handling
  - Wired into scan_invoice() after merge_results; sets math_validation_triggered in metadata
  - Debug mode includes validation errors in scan_metadata
  - 208 total passing tests (188 existing + 20 new validator tests)
  - Files: scanner/scanning/validator.py, scanner/scanning/engine.py, scanner/scanning/__init__.py, tests/test_validator.py
Phase 11:  [x] Complete  — Memory interfaces + JSON storage
  - Abstract interfaces: SupplierMemory (get_profile, save_scan, infer_missing, get/update_layout), GeneralMemory (get_industry_profile, get_item_catalog, update_from_scan)
  - JSON implementations: JsonSupplierMemory (per-supplier dirs with profile.json/layout.json), JsonGeneralMemory (industry_profile.json/item_catalog.json)
  - Supplier ID normalization with path traversal protection (rejects .., /, \)
  - Thread-safe atomic writes via temp-file + os.replace, graceful corrupt/missing file handling
  - Running price averages for item history, supplier index auto-maintenance
  - 246 total passing tests (208 existing + 38 new memory tests)
  - Files: scanner/memory/interface.py, scanner/memory/json_store.py, scanner/memory/__init__.py, tests/test_memory.py
Phase 12:  [x] Complete — Three-tier inference system
  - infer_field() cascades through supplier memory (conf 80) -> industry memory (conf 60) -> AI reasoning via Claude Sonnet (conf 50)
  - run_inference() scans all fields below confidence threshold, fills missing values, tracks tier used in metadata
  - Item-level inference for unit_price and unit from supplier history and industry catalog
  - Wired into scan_invoice() after math validation step
  - 292 total passing tests (246 existing + 46 new inference tests)
  - Files: scanner/memory/inference.py, scanner/memory/__init__.py (updated exports), scanner/scanning/engine.py (wired in), tests/test_inference.py
Phase 13:  [x] Complete — Editable result form UI (React)
  - InvoiceForm component with editable header fields, confidence badges, inference source badges
  - ItemsTable component with editable cells, add/remove rows, per-cell change tracking
  - Field highlighting: yellow (low confidence <60), blue (inferred), green (user-edited)
  - POST /api/confirm/ endpoint with ConfirmRequestSerializer validation
  - FieldCorrection/ConfirmRequest/ConfirmResponse types in scan.ts, confirmScan() in api.ts
  - App.tsx wired: scan -> form display -> confirm flow with success message
  - 298 total passing tests (292 existing + 6 new confirm endpoint tests)
  - Files: InvoiceForm.tsx, ItemsTable.tsx, scan.ts (updated), api.ts (updated), views.py (updated), urls.py (updated), serializers.py (updated), app.css (updated), App.tsx (updated)
Phase 14:  [x] Complete — Memory learning from user corrections
  - Error categorizer: classifies corrections as misread/missing/hallucinated (pure functions)
  - Correction applicator: applies user corrections to scan data (header fields, item subfields, row deletions)
  - Confirm endpoint wired to memory: saves corrected data + error categories to supplier + general memory
  - Field name whitelist prevents arbitrary key injection into scan data
  - Graceful handling of empty/unknown supplier names (skips supplier memory, still updates general)
  - 332 total passing tests (330 + 2 new zero-as-deletion edge case tests)
  - Files: categorizer.py (new), corrections.py (new), memory/__init__.py (updated), views.py (updated), serializers.py (updated), test_categorizer.py (new), test_corrections.py (new), test_api.py (updated)
Phase 15:  [x] Complete — Supplier layout mapping
  - Layout descriptor builder: converts bounding boxes to normalized 0-1 coordinates
  - Layout-aware segmentation: uses saved layout when aspect ratio compatible, falls back to detection
  - OCR-based early supplier identification: matches known suppliers from OCR text to load layout before Claude scans
  - Layout saved to {supplier_id}/layout.json after first successful scan
  - 353 total passing tests (332 + 21 new layout/segmentation tests)
  - Files: layout.py (new), segmentation.py (updated), engine.py (updated), json_store.py (updated), preprocessing/__init__.py (updated), test_layout.py (new), test_segmentation_layout.py (new), test_engine_layout.py (new)
Phase 16:  [ ] Not started — Batch upload, tabs, dashboard, debug mode (React)
Phase 17:  [ ] Not started — Integration testing + golden test set
```

---

### Phase 01: Backend Scaffolding (Django REST)
**Goal:** Runnable Django REST API with empty app structure.
**Build:**
- `backend/` directory with `django-admin startproject smartscanner .`
- `python manage.py startapp scanner`
- Install and configure Django REST Framework + django-cors-headers
- Create all subdirectory packages: `preprocessing/`, `scanning/`, `memory/`, `tracking/`
- Create `requirements.txt` with all dependencies
- Create `.env` with placeholder for `ANTHROPIC_API_KEY`
- Create `.gitignore` (Python, Django, .env, data/, node_modules/)
- Create `data/` directory structure: `general/`, `suppliers/`, `stats/`
- Configure `settings.py` for DRF, CORS (allow React dev server), env loading
- Create placeholder `POST /api/scan/` endpoint returning dummy JSON
- Create `scanner/serializers.py` for DRF
**Verify:** `python manage.py runserver` starts without errors. `curl POST /api/scan/` returns dummy JSON. All directories exist.
**Files:** backend/manage.py, backend/smartscanner/*, backend/scanner/*, all subpackages, requirements.txt, .env, .gitignore

---

### Phase 02: Frontend Scaffolding (React + TypeScript)
**Goal:** React app with Vite + TypeScript that can talk to the backend API.
**Build:**
- `frontend/` directory with `npm create vite@latest . -- --template react-ts`
- Create `src/types/scan.ts` — TypeScript interfaces for scan request/response data
- Create `src/services/api.ts` — Axios client configured to call backend
- Create `src/components/DropZone.tsx` — drag-and-drop file upload component
- Create `src/App.tsx` — main page with DropZone, displays placeholder JSON result
- Create `src/styles/app.css` — minimal styling
- Configure `vite.config.ts` with proxy to Django backend for dev
**Verify:** `npm run dev` starts. Drop an image → calls backend API → displays dummy JSON response. TypeScript compiles with no errors.
**Depends on:** Phase 01

---

### Phase 02b: Scan Controls UI
**Goal:** Mode dropdown and debug toggle wired to API.
**Build:**
- Create `src/components/ScanControls.tsx` — Light/Normal/Heavy dropdown + Debug mode checkbox
- Wire controls into DropZone → API call sends mode parameter
- Update backend `POST /api/scan/` to accept and echo back mode parameter
**Verify:** Mode dropdown sends correct value to backend. Debug toggle state persists. TypeScript types cover mode enum.
**Depends on:** Phase 02

---

### Phase 03: Orientation & Skew Correction
**Goal:** Auto-fix rotated, tilted, and perspective-distorted images.
**Build:**
- `scanner/preprocessing/orientation.py` — EXIF rotation, Hough deskew, perspective warp
**Verify:** Unit tests with rotated/tilted/warped test images. Tesseract OCR accuracy improves after correction.
**Files:** orientation.py, test_preprocessing.py (orientation section)

---

### Phase 04: Quality Assessment
**Goal:** Analyze image quality and report issues.
**Build:**
- `scanner/preprocessing/analyzer.py` — measure brightness, contrast, blur, noise, resolution. Return quality report dict.
**Verify:** Unit tests with known-quality images (dark, washed out, blurry, noisy, low-res, clean). Assert correct detection.
**Files:** analyzer.py, test_preprocessing.py (analyzer section)

---

### Phase 05: Selective Image Processing
**Goal:** Apply only needed fixes based on quality assessment.
**Build:**
- `scanner/preprocessing/processor.py` — histogram equalization, sharpening, denoising, upscaling, grayscale. Accept quality report, apply relevant transforms.
- Produce two variants: orientation-corrected-only + fully preprocessed.
**Verify:** Pixel metrics improve after processing. Clean image passes through unchanged.
**Files:** processor.py, test_preprocessing.py (processor section)

---

### Phase 06: ROI Segmentation
**Goal:** Detect and crop header, line items, and totals regions.
**Build:**
- `scanner/preprocessing/segmentation.py` — region detection using contour/line analysis. Return cropped regions or full image as fallback.
**Verify:** Visual bounding box test on sample receipts. Fallback works on non-standard layouts.
**Files:** segmentation.py, test_preprocessing.py (segmentation section)

---

### Phase 07: OCR Pre-Pass
**Goal:** Extract text from preprocessed image using Tesseract.
**Build:**
- `scanner/scanning/ocr.py` — run Tesseract on preprocessed image, return raw text.
**Verify:** Compare output against known receipt text. Doesn't need to be perfect — supplementary data.
**Files:** ocr.py, test_scanning.py (ocr section)

---

### Phase 08: Single Scan with Claude (No Multi-Pass Yet)
**Goal:** Send image + OCR text to Claude and get structured JSON back with confidence scores.
**Build:**
- `scanner/scanning/prompts.py` — prompt templates for scan 1 (structured extraction with 0-100 confidence per field)
- `scanner/scanning/engine.py` — single scan function: send both image variants + OCR text to Claude, parse JSON response
- Wire into `POST /api/scan/` REST endpoint — real scan instead of placeholder
**Verify:** Drop a clear receipt image via React UI, get back correct JSON with confidence scores. Manual spot-check.
**Files:** prompts.py, engine.py, views.py update

---

### Phase 09: Three-Pass Scanning with Tiebreaker
**Goal:** Full triple-check scan pipeline with mode selection.
**Build:**
- `scanner/scanning/prompts.py` — add scan 2 (differently worded) and scan 3 (tiebreaker focused) prompt templates
- `scanner/scanning/comparator.py` — field-by-field comparison: fuzzy match strings, exact match numbers, item array matching
- `scanner/scanning/engine.py` — orchestrate 3 passes, trigger tiebreaker only on disagreement, support Light/Normal/Heavy modes
- Add mode dropdown to UI
**Verify:** Clear receipt — scans 1 and 2 agree, no tiebreaker. Degraded receipt — tiebreaker triggers. Mode dropdown switches models.
**Files:** prompts.py update, comparator.py, engine.py update, index.html update, app.js update

---

### Phase 10: Mathematical Cross-Validation
**Goal:** Arithmetic checks catch errors all scans agree on.
**Build:**
- `scanner/scanning/validator.py` — check qty×price=line total, sum=subtotal, subtotal+tax=total. On failure, send contradiction back to Claude.
- Wire into engine after scan passes complete.
**Verify:** Feed intentionally wrong math in JSON — validator catches and corrects. Feed correct math — passes clean.
**Files:** validator.py, engine.py update, test_validator.py

---

### Phase 11: Memory Interfaces + JSON Storage
**Goal:** Storage layer for supplier-specific and general industry memory.
**Build:**
- `scanner/memory/interface.py` — abstract `SupplierMemory` (get_profile, save_scan, infer_missing, get_layout, update_layout) + `GeneralMemory` (get_industry_profile, get_item_catalog, update_from_scan)
- `scanner/memory/json_store.py` — JSON file implementations of both interfaces
- Create initial data structure: `data/suppliers/index.json`, `data/general/industry_profile.json`, `data/general/item_catalog.json`
**Verify:** Unit tests: save a scan, retrieve profile, verify data persists. Save layout, retrieve layout.
**Files:** interface.py, json_store.py, test_memory.py

---

### Phase 12: Three-Tier Inference System
**Goal:** Fill missing/low-confidence fields using supplier memory → industry memory → AI reasoning.
**Build:**
- `scanner/memory/inference.py` — three-tier inference: check supplier profile first, then general industry data, then make Claude call for contextual reasoning
- Wire into engine: after scan + validation, run inference on low-confidence fields
**Verify:** Same supplier scanned twice, second with obscured field — Tier 1 fills it. New supplier with missing field — Tier 2/3 fills it. All inferred fields flagged.
**Files:** inference.py, engine.py update, test_inference.py

---

### Phase 13: Editable Result Form UI (React)
**Goal:** Replace raw JSON display with editable React form components. Highlight guessed fields.
**Build:**
- Create `src/components/InvoiceForm.tsx` — editable form: header fields as inputs, totals as inputs, "Confirm All" button
- Create `src/components/ItemsTable.tsx` — editable items table with add/remove rows (name, qty, unit, price columns)
- Highlight low-confidence/inferred fields with distinct color + badge showing source
- Track which fields user changed (diff original vs final state)
- Update `src/types/scan.ts` — types for correction tracking
- Backend: `POST /api/confirm/` endpoint — receives original scan + user corrections
**Verify:** Scan an image, see editable form. Change a value, confirm. Verify correction is tracked. TypeScript compiles clean.
**Files:** InvoiceForm.tsx, ItemsTable.tsx, scan.ts update, api.ts update, views.py update

---

### Phase 14: Memory Learning from User Corrections
**Goal:** User corrections immediately update supplier + general memory.
**Build:**
- On confirm: compare original scan to user's final values
- Update supplier profile with corrected values (immediate trust)
- Update general industry profile with new data points
- Auto-categorize errors: misread, missing, hallucinated
- Save error categories alongside corrections
**Verify:** Correct a price, confirm. Scan same supplier again — corrected value appears in memory. Error type is correctly classified.
**Files:** views.py update, json_store.py update, comparator.py update (error categorization)

---

### Phase 15: Supplier Layout Mapping
**Goal:** Learn and reuse invoice layout per supplier for smarter ROI.
**Build:**
- After first successful scan of a supplier, map layout: where supplier name, date, items table, totals appear
- Save to `{supplier_id}/layout.json`
- Update `segmentation.py` to check for saved layout before generic detection
**Verify:** Scan supplier first time — layout saved. Scan same supplier again — segmentation uses saved layout. Verify faster/more accurate ROI.
**Files:** segmentation.py update, json_store.py update, engine.py update

---

### Phase 16: Batch Upload, Tabs, Accuracy Dashboard, Debug Mode (React)
**Goal:** Multi-image upload, tabbed results, stats, and debug toggle.
**Build:**
- Update `DropZone.tsx` to accept multiple images
- Create `src/components/ResultTabs.tsx` — tabbed view: one tab per invoice + summary tab
- Create `src/components/ScanStats.tsx` — per-scan stats (mode, API calls, tiebreaker/math flags)
- Create `src/components/Dashboard.tsx` — mode comparison dashboard (Light vs Normal vs Heavy accuracy + API usage), per-supplier accuracy over time
- Debug mode: when toggled, backend saves preprocessing intermediates, frontend displays them
- Backend: `scanner/tracking/accuracy.py` — accuracy calculation and storage
- Backend: `scanner/tracking/api_usage.py` — API call counting per model/mode
- Backend: `GET /api/stats/` — returns accuracy and API usage data
- `data/stats/accuracy.json` + `data/stats/api_usage.json`
**Verify:** Upload 3 images, see 3 tabs + summary. Confirm corrections, see accuracy stats. Toggle debug mode, verify intermediates saved. Mode comparison shows correct averages. All TypeScript types cover stats data.
**Files:** DropZone.tsx update, ResultTabs.tsx, ScanStats.tsx, Dashboard.tsx, scan.ts update, api.ts update, views.py update, accuracy.py, api_usage.py, test_accuracy.py

---

### Phase 17: Integration Testing + Golden Test Set
**Goal:** End-to-end verification with real receipts.
**Build:**
- `tests/fixtures/` — 5-10 test receipt images (clear, blurry, rotated, multi-format)
- `tests/expected/` — manually created expected JSON for each
- `tests/test_integration.py` — full pipeline test: upload image → preprocessing → scan → validate → output. Compare against expected JSON field-by-field.
- Mode comparison test: run same images through Light/Normal/Heavy
**Verify:** All integration tests pass. Accuracy report generated per mode.
**Files:** test fixtures, expected JSONs, test_integration.py

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Monolithic Django | Simplest for prototype, extractable later |
| Storage | JSON files (prototype), SQLite (production) | Clean interface allows swap |
| Preprocessing | Auto-detect and selectively apply | Best results without user overhead |
| Output format | Flat JSON with items array | Simple, future PDF/doc generation |
| UI scope | Single page with tabs | Batch upload, tabbed results per invoice |
| Scan disagreement | Third tiebreaker scan | Most accurate, fully automated |
| AI models | Opus + Sonnet via scan modes | Cost vs accuracy flexibility |
| Frontend | React + TypeScript (Vite) | Component-based, type-safe, modern stack |
| Backend API | Django REST Framework | Clean REST endpoints for React frontend |
| Orientation fix | Auto-detect rotation, skew, perspective | Tilted images are #1 misread source |
| ROI segmentation | Supplier-aware layout mapping | Gets smarter per supplier over time |
| OCR pre-pass | Tesseract alongside Claude vision | Two data sources cross-reference |
| Multi-variant images | Send original + preprocessed together | Handles over-processing artifacts |
| Math validation | Post-scan arithmetic checks | Catches errors all 3 scans agree on |
| Memory system | Three-tier: supplier → industry → AI | Maximizes inference accuracy at all stages |
| Confidence scoring | 0-100 per field from Claude | Drives highlighting, inference, future auto-mode |
| Error categorization | Auto-classify: misread, missing, hallucinated | Reveals which system component needs improvement |
| Result UI | Editable form with inline correction | No modal interruption, natural workflow |
| Memory updates | Immediate trust on correction | Fast learning, simplest for prototype |
| Duplicate detection | Not for prototype | Add later |
| Batch upload | Multiple images, each own invoice | Efficient bulk processing |
| Results display | Tabbed view per invoice + summary | Organized without overwhelming |
| Mode selection | Manual dropdown for prototype | Future: auto-select based on image quality |
| Debug mode | Optional toggle saves intermediates | On-demand debugging without overhead |
| Accuracy measurement | User corrections / total fields | Direct, honest measure of real-world accuracy |
