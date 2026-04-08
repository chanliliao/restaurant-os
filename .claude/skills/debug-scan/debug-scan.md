# Debug Scan Skill — SmartScanner

Systematic debugging for bad scan results using the scientific method.

## Trigger

Invoked by the `/debug` command or when a scan produces wrong, missing, or malformed output.

## Inputs

Ask the user for:
1. What went wrong (describe the bad output)
2. The input image or test fixture if available
3. Any error messages or tracebacks

## Pipeline Map

```
Image file
    ↓
_preprocess_image()          # scanner/scanning/engine.py
    ↓
_call_glm_ocr()              # scanner/scanning/engine.py → ZhipuAI glm-ocr
    ↓
_call_glm_vision()           # scanner/scanning/engine.py → ZhipuAI glm-4.6v-flash
    ↓
validate_invoice()           # scanner/scanning/validator.py
    ↓
normalize_supplier_id()      # scanner/memory/json_store.py
    ↓
update_supplier_memory()     # scanner/memory/json_store.py
```

## Workflow

### Step 1: Capture
Document the exact bad output. What field is wrong? What was extracted vs. what was expected?

### Step 2: Trace Stage by Stage
Check each stage in order. Stop at the first stage that produces bad output.

**Stage 1 — Preprocessing:**
```python
from scanner.scanning.engine import _preprocess_image
img = _preprocess_image("path/to/invoice.jpg")
print(img.size, img.mode)  # Should be reasonable dimensions, RGB or L
```

**Stage 2 — GLM-OCR:**
Check the raw OCR response. In tests, inspect the mock return value. In dev, add temporary logging:
```python
import logging
logging.getLogger('scanner.scanning.engine').setLevel(logging.DEBUG)
```

**Stage 3 — GLM Vision:**
Check the vision LLM response for the parsed invoice structure. Common failures: wrong supplier name, missing line items, garbled numbers.

**Stage 4 — Validator:**
Run `validator.py` in isolation:
```python
from scanner.scanning.validator import validate_invoice
errors = validate_invoice(extracted_data)
print(errors)
```

**Stage 5 — Memory / Supplier Match:**
```python
from scanner.memory.json_store import normalize_supplier_id, _validate_supplier_id
sid = normalize_supplier_id("Supplier Name From Invoice")
print(sid)  # Should match a directory in backend/data/
```

### Step 3: Hypothesize
State a specific, testable hypothesis:
> "The failure is in Stage X because Y. I expect fixing Z will resolve it."

### Step 4: Test
Write a focused unit test that reproduces the failure:
```python
def test_specific_failure():
    # Arrange: mock GLM response with the bad data
    with patch('scanner.scanning.engine._call_glm_ocr') as mock_ocr:
        mock_ocr.return_value = {"text": "...bad data..."}
        result = scan_invoice("test.jpg")
    # Assert: confirm the failure mode
    assert result['supplier'] == 'expected_supplier'
```

Run: `cd backend && python -m pytest tests/test_scanning.py::test_specific_failure -v`
Expected: FAIL (confirms the hypothesis).

### Step 5: Fix and Verify
Implement the fix. Re-run the focused test (should now PASS), then run the full suite:
```bash
cd backend && python -m pytest -v
```
Zero failures required before committing.
