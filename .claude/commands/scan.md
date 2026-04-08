# Scan Test — SmartScanner

You are running an end-to-end scan test. Follow this workflow:

1. **Get the input** — ask for an image path or test fixture name if not provided.
2. **Run the scan** — invoke `scan_invoice()` with the provided image. Use the test infrastructure in `backend/tests/integration_helpers.py` for fixtures.
3. **Check OCR output** — inspect the raw GLM-OCR response: did it extract text? What confidence scores were returned?
4. **Validate extracted JSON** — check all required fields are present: supplier, invoice_number, date, line_items, total. Verify line item math within tolerance. Check supplier ID matches a known slug.
5. **Check memory update** — verify `backend/data/<supplier_id>/` was updated correctly after the scan.
6. **Report results** — give a pass/fail summary with field-level detail for any failures. Include the exact extracted values and what was expected.

@.claude/skills/scan-test/scan-test.md
