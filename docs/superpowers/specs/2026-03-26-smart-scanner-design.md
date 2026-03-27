# SmartScanner Design Spec

## Overview

SmartScanner is a Django-based web application that uses Claude Opus to extract structured data from restaurant receipt and invoice images. It features intelligent image preprocessing, a three-pass scanning pipeline with tiebreaker logic, and a supplier memory system that learns patterns over time to infer missing data.

## Architecture

Monolithic Django application. All processing happens in-process. Designed with clean internal module boundaries so components can be extracted into services later.

**Tech Stack:**
- Python 3.11+
- Django 5.x
- Anthropic Python SDK (Claude Opus for scanning)
- Pillow + OpenCV for image preprocessing
- Tesseract OCR (pytesseract) for complementary text extraction
- JSON files for storage (prototype), SQLite for production

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

## 2. Region-of-Interest Segmentation

Before scanning, detect and crop the image into focused regions:
- **Header region** — supplier name, address, date, invoice number
- **Line items region** — the table of items with names, quantities, prices
- **Totals region** — subtotal, tax, total, payment info

Each region is scanned separately with focused prompts tuned to that region's content. Smaller, targeted areas yield higher per-field accuracy than scanning the whole image at once.

If region detection fails (e.g., unusual layout), fall back to full-image scanning.

## 3. OCR Pre-Pass

Run Tesseract OCR on the preprocessed image before sending to Claude. The OCR text is passed alongside the image in the Claude prompt as supplementary data. This gives the model two sources of information to cross-reference — especially helpful for small, faded, or low-contrast text that vision alone might miss.

## 4. Three-Pass Scanning Pipeline

### Scan 1 (Primary)
For each region (or full image if no regions detected), send both image variants (original + preprocessed) plus the Tesseract OCR text to Claude Opus with a structured prompt requesting flat JSON extraction.

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

## 5. Two-Tier Inference System

### Tier 1: Historical Pattern Matching
Check the supplier profile for known values:
- Common item names and typical prices
- Tax rate patterns
- Invoice format/layout conventions
- Typical quantities and order frequency

### Tier 2: Contextual AI Inference
When no historical data exists, make another Claude call with:
- The partially extracted data
- Invoice domain knowledge (e.g., "subtotal = sum of line items", "tax is typically a percentage of subtotal", "invoice numbers are sequential")
- Ask Claude to identify keywords and contextual clues on the image to fill gaps and validate existing extractions

All inferred fields are flagged in a `confidence` object in the output.

## 6. Supplier Memory System

### Storage Structure (JSON Prototype)
```
data/suppliers/
  ├── index.json              # maps supplier names to IDs
  └── {supplier_id}/
      ├── profile.json        # learned patterns, common values, tax rates
      └── scans/
          ├── 2026-03-25_001.json
          └── 2026-03-25_002.json
```

### Learning Mechanism
After each successful scan, update the supplier profile with:
- Common item names and typical prices
- Tax rate patterns
- Invoice format/layout notes
- Order frequency and typical quantities

### Storage Interface
`SupplierMemory` class with methods: `get_profile()`, `save_scan()`, `infer_missing()`. When migrating to SQLite, swap the implementation behind this interface.

## 7. Output Format

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
    "tax": "inferred_from_history"
  }
}
```

The `confidence` object flags any fields that were:
- `inferred_from_history` — filled from supplier profile
- `inferred_from_context` — filled by AI contextual reasoning
- `tiebreaker_resolved` — disagreed between scan 1 and 2, resolved by scan 3
- `math_corrected` — corrected by mathematical cross-validation

## 8. Django UI

### Single Page
- Drag-and-drop zone (HTML5 drag/drop + file browse fallback)
- AJAX upload with loading spinner during processing
- JSON result displayed below in formatted, readable view
- Confidence flags visually indicated for inferred/disputed fields

### API Endpoint
`POST /api/scan/` — accepts image file, returns final JSON result.

### Frontend
Vanilla HTML/CSS/JS. No framework. Minimal and functional for prototype.

## 9. Project Structure

```
SmartScanner/
├── manage.py
├── requirements.txt
├── .env                        # ANTHROPIC_API_KEY
├── .gitignore
├── smartscanner/               # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── scanner/                    # Main Django app
│   ├── views.py
│   ├── urls.py
│   ├── preprocessing/
│   │   ├── orientation.py      # Rotation, deskew, perspective correction
│   │   ├── analyzer.py         # Quality assessment
│   │   ├── processor.py        # Selective image processing
│   │   └── segmentation.py     # Region-of-interest detection and cropping
│   ├── scanning/
│   │   ├── ocr.py              # Tesseract OCR pre-pass
│   │   ├── engine.py           # Three-pass scan orchestration
│   │   ├── prompts.py          # Claude prompt templates
│   │   ├── comparator.py       # Field-by-field comparison
│   │   └── validator.py        # Mathematical cross-validation
│   ├── memory/
│   │   ├── interface.py        # SupplierMemory abstract interface
│   │   ├── json_store.py       # JSON file implementation
│   │   └── inference.py        # Two-tier inference logic
│   ├── templates/
│   │   └── scanner/
│   │       └── index.html
│   └── static/
│       └── scanner/
│           ├── style.css
│           └── app.js
├── data/                       # Supplier memory (gitignored)
│   └── suppliers/
└── docs/
```

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Monolithic Django | Simplest for prototype, extractable later |
| Storage | JSON files (prototype), SQLite (production) | Clean interface allows swap |
| Preprocessing | Auto-detect and selectively apply | Best results without user overhead |
| Output format | Flat JSON with items array | Simple, future PDF/doc generation |
| UI scope | Single page, drop + result | Prototype — minimal viable |
| Scan disagreement | Third tiebreaker scan | Most accurate, fully automated |
| AI model | Claude Opus | Best vision capabilities for scanning |
| Frontend | Vanilla HTML/CSS/JS | No framework overhead for prototype |
| Orientation fix | Auto-detect rotation, skew, perspective | Tilted images are #1 misread source |
| ROI segmentation | Crop header/items/totals regions | Focused scanning = higher per-field accuracy |
| OCR pre-pass | Tesseract alongside Claude vision | Two data sources cross-reference |
| Multi-variant images | Send original + preprocessed together | Handles over-processing artifacts |
| Math validation | Post-scan arithmetic checks | Catches errors all 3 scans agree on |
