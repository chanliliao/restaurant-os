# Debug Scan — SmartScanner

You are debugging a bad scan result. Follow this systematic workflow:

1. **Capture the failure** — ask the user to describe what went wrong and provide the input image or test case if possible.
2. **Trace the pipeline stages in order:**
   - Stage 1: Image preprocessing (`scanner/scanning/engine.py` — `_preprocess_image()`)
   - Stage 2: GLM-OCR call (`_call_glm_ocr()`) — did it return structured text?
   - Stage 3: GLM Vision call (`_call_glm_vision()`) — did it parse the invoice correctly?
   - Stage 4: Validator (`scanner/scanning/validator.py`) — did math validation pass?
   - Stage 5: Memory lookup (`scanner/memory/json_store.py`) — was the supplier matched?
3. **Isolate the failing stage** — identify which stage first produced bad output.
4. **Form a hypothesis** — state the specific cause (e.g., "GLM-OCR returned empty text because image was too dark").
5. **Test the hypothesis** — write a focused test or add logging to confirm.
6. **Fix and verify** — implement the fix, run `cd backend && pytest`, confirm zero failures.

@.claude/skills/debug-scan/debug-scan.md
