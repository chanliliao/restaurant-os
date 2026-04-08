# Scan Test Skill — SmartScanner

This skill validates a scan end-to-end through the full pipeline.

## Trigger

Invoked by the `/scan` command or when validating a scan result.

## Inputs

Ask the user for one of:
- An image file path (e.g., `z_test_files/invoice.jpg`)
- A test fixture name from `backend/tests/integration_helpers.py`

## Workflow

### Step 1: Run the Scan
Use the Django shell or test runner to invoke `scan_invoice()`:

```python
# In backend/ with venv activated:
from scanner.scanning.engine import scan_invoice
result = scan_invoice(image_path="path/to/invoice.jpg")
print(result)
```

Or use the existing test infrastructure:
```bash
cd backend && python -m pytest tests/test_integration.py -v -k "your_test_name"
```

### Step 2: Check OCR Output
Inspect the raw OCR response:
- Was text extracted? (non-empty `raw_text` field)
- What confidence scores were returned? (must be integers 0–100)
- Did GLM-OCR identify the correct line items?

### Step 3: Validate Extracted JSON
Check each required field:
| Field | Rule |
|-------|------|
| `supplier` | Must match a known supplier slug in `backend/data/` |
| `invoice_number` | Non-empty string |
| `date` | Valid date format |
| `line_items` | List with at least one item; each has `description`, `quantity`, `unit_price`, `total` |
| `total` | Matches sum of line_items[].total within tolerance |
| Confidence scores | All integers 0–100; inferred fields use 80 (supplier memory) or 60 (industry memory) |

### Step 4: Check Memory Update
After a successful scan, verify:
```bash
ls backend/data/<supplier_id>/
# Should contain updated JSON files
cat backend/data/<supplier_id>/profile.json
```
Confirm the supplier profile reflects the latest scan.

### Step 5: Report
Produce a structured report:
```
PASS/FAIL: Overall result
- OCR: PASS/FAIL (confidence: XX)
- Fields: PASS/FAIL (missing: field_name)
- Math: PASS/FAIL (expected: X.XX, got: X.XX)
- Memory: PASS/FAIL (supplier matched: yes/no)
```
