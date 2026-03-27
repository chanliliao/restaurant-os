# Phase 09: Three-Pass Scanning with Tiebreaker

## Goal
Replace single-scan pipeline with a triple-check system: two independent scans compared field-by-field, with an optional tiebreaker scan triggered only when disagreements exist.

## Implementation Steps

### Step 1: Add prompt templates (`prompts.py`)
- `build_scan_prompt_v2(ocr_text)` — independently-worded confirmation prompt with different emphasis (bottom-up extraction, item-first approach)
- `build_tiebreaker_prompt(scan1_result, scan2_result, ocr_text)` — presents both scan results and asks Claude to resolve field-by-field disagreements

### Step 2: Create comparator module (`comparator.py`)
- `compare_scans(scan1, scan2)` — field-by-field comparison:
  - Fuzzy string match for text fields (supplier, date, invoice_number, item names) using `difflib.SequenceMatcher` (stdlib, no new deps)
  - Exact match for numeric fields (quantities, prices, totals)
  - Item array matching by position then name similarity
  - Returns `{"agreed": {...}, "disagreed": {...}, "agreement_ratio": float}`
- `merge_results(scan1, scan2, tiebreaker=None)` — merge using agreed values + tiebreaker for disagreements

### Step 3: Update engine (`engine.py`)
- Add `_get_model_for_scan(mode, scan_number)` — returns correct model per mode/scan
- Modify `scan_invoice()` to run the three-pass pipeline:
  1. Scan 1 with `build_scan_prompt`
  2. Scan 2 with `build_scan_prompt_v2`
  3. Compare results
  4. If disagreement, Scan 3 with `build_tiebreaker_prompt`
  5. Merge and return
- Update scan_metadata: `scans_performed`, `tiebreaker_triggered`, `agreement_ratio`, `api_calls`, `models_used`

### Step 4: Update `__init__.py` exports

### Step 5: Tests
- Comparator unit tests (agree, disagree, fuzzy match, merge)
- Prompt template tests for v2 and tiebreaker
- Engine integration tests (2-scan agree, 3-scan disagree, mode/model selection)
- All mocked, no real API calls

## Model Selection per Mode
| Mode   | Scan 1 | Scan 2 | Tiebreaker |
|--------|--------|--------|------------|
| light  | Sonnet | Sonnet | Sonnet     |
| normal | Sonnet | Sonnet | Opus       |
| heavy  | Opus   | Opus   | Opus       |

## Fuzzy Match Threshold
- Text fields: ratio >= 0.85 = agreement
- Numbers: exact match (no tolerance for currency)
