# Phase 10: Mathematical Cross-Validation

## Goal
Add arithmetic checks that catch errors all scans agree on — errors that consensus alone cannot detect.

## Design

### New file: `backend/scanner/scanning/validator.py`

Two public functions:

1. **`validate_math(scan_result) -> dict`**
   - Returns `{"valid": bool, "errors": [...]}`
   - Checks:
     - Each item: `qty * unit_price ≈ line_total` (tolerance 0.01)
     - Sum of item totals ≈ subtotal
     - subtotal + tax ≈ total
   - Skips checks when values are None/missing

2. **`auto_correct(scan_result, errors) -> dict`**
   - For each error, applies straightforward fixes:
     - Wrong line_total → recalculate from qty * unit_price
     - Wrong subtotal → recalculate from sum of item totals
     - Wrong total → recalculate from subtotal + tax
   - Returns corrected copy of scan_result (does not mutate original)

### Wire into engine.py

After `merge_results()` in `scan_invoice()`:
1. Call `validate_math(result)`
2. If errors found, call `auto_correct(result, errors)`
3. Set `scan_metadata.math_validation_triggered = True` when corrections applied
4. In debug mode, include validation errors in metadata

### Export from `__init__.py`
Add `validate_math` and `auto_correct` to scanning package exports.

## Testing: `backend/tests/test_validator.py`

| Test case | What it checks |
|-----------|---------------|
| Correct math | valid=True, no errors |
| Wrong line total | Detected in errors |
| Wrong subtotal | Detected and auto-corrected |
| Wrong grand total | Detected |
| Missing/null values | Handled gracefully, no crash |
| Multiple errors | All detected |
| Empty items list | No crash |
| auto_correct immutability | Original not mutated |

## Risks
- Floating point: use `abs(a - b) <= 0.01` tolerance everywhere
- None handling: every numeric field could be None; guard all arithmetic
