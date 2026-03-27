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
- JSON files for storage (prototype), SQLite for production

## 1. Image Preprocessing Pipeline

### Quality Assessment
Analyze uploaded images using Pillow/OpenCV to measure:
- Brightness (mean pixel intensity)
- Contrast (standard deviation of pixel values)
- Blur level (Laplacian variance)
- Noise level (high-frequency component analysis)
- Resolution (pixel dimensions)

### Selective Processing
Only apply needed transformations based on quality assessment:
- Low contrast → histogram equalization
- Blurry → sharpening filter
- Noisy → Gaussian/bilateral denoising
- Low resolution → Lanczos upscaling
- Color issues → grayscale conversion

The original image is always preserved. Preprocessed version is used for scanning only.

## 2. Three-Pass Scanning Pipeline

### Scan 1 (Primary)
Send preprocessed image to Claude Opus with a structured prompt requesting flat JSON extraction of all invoice fields.

### Scan 2 (Confirmation)
Send the same image with a differently worded prompt (to avoid echo bias). Compare results field-by-field against Scan 1.

### Scan 3 (Tiebreaker)
Only triggered when Scans 1 and 2 disagree on any field. Sends the image with a focused prompt targeting ONLY the disagreed fields, plus context from both previous results. The tiebreaker result is final.

### Field Comparison Logic
- String fields: fuzzy matching (handle minor formatting differences)
- Numeric fields: exact match required
- Array fields (items): match by item name, compare qty/price individually

## 3. Two-Tier Inference System

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

## 4. Supplier Memory System

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

## 5. Output Format

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

## 6. Django UI

### Single Page
- Drag-and-drop zone (HTML5 drag/drop + file browse fallback)
- AJAX upload with loading spinner during processing
- JSON result displayed below in formatted, readable view
- Confidence flags visually indicated for inferred/disputed fields

### API Endpoint
`POST /api/scan/` — accepts image file, returns final JSON result.

### Frontend
Vanilla HTML/CSS/JS. No framework. Minimal and functional for prototype.

## 7. Project Structure

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
│   │   ├── analyzer.py         # Quality assessment
│   │   └── processor.py        # Selective image processing
│   ├── scanning/
│   │   ├── engine.py           # Three-pass scan orchestration
│   │   ├── prompts.py          # Claude prompt templates
│   │   └── comparator.py       # Field-by-field comparison
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
