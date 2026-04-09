# .claude Folder Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the project `.claude/` folder with organized rules, commands, skills, and agents; extract CLAUDE.md rule sections into dedicated files.

**Architecture:** Create `.claude/rules/`, `.claude/commands/`, `.claude/skills/`, and `.claude/agents/` folders. Extract "Design Style Guide", "Constraints and Policies", "Security", and "Repo Etiquette" from CLAUDE.md into two rule files. Replace those sections in CLAUDE.md with `@` imports. Create 6 command files and 3 skill files.

**Tech Stack:** Markdown files, Claude Code `.claude/` conventions, `@file` import syntax in CLAUDE.md.

---

## File Map

**Create:**
- `.claude/rules/coding-standards.md` — tech stack, code quality, constraints, security
- `.claude/rules/workflow-gates.md` — commit rules, test gates, PR rules, phase gates
- `.claude/commands/phase.md` — /phase slash command
- `.claude/commands/scan.md` — /scan slash command
- `.claude/commands/debug.md` — /debug slash command
- `.claude/commands/activate-venv.md` — /activate-venv slash command
- `.claude/commands/run-tests.md` — /run-tests slash command
- `.claude/commands/check-logs.md` — /check-logs slash command
- `.claude/skills/new-phase/new-phase.md` — new phase lifecycle skill
- `.claude/skills/scan-test/scan-test.md` — end-to-end scan test skill
- `.claude/skills/debug-scan/debug-scan.md` — scan debugging skill
- `.claude/agents/.gitkeep` — keeps agents folder in git

**Modify:**
- `CLAUDE.md` — remove 4 sections (lines 44–119), add `@` imports in their place

---

## Task 1: Create Folder Structure

**Files:**
- Create: `.claude/rules/`
- Create: `.claude/commands/`
- Create: `.claude/skills/new-phase/`
- Create: `.claude/skills/scan-test/`
- Create: `.claude/skills/debug-scan/`
- Create: `.claude/agents/`

- [ ] **Step 1: Create all directories**

```bash
mkdir -p ".claude/rules" ".claude/commands" ".claude/skills/new-phase" ".claude/skills/scan-test" ".claude/skills/debug-scan" ".claude/agents"
```

Expected: No output, directories created.

- [ ] **Step 2: Verify directories exist**

```bash
ls .claude/
```

Expected output includes: `agents/  commands/  rules/  settings.local.json  skills/`

---

## Task 2: Create coding-standards.md

**Files:**
- Create: `.claude/rules/coding-standards.md`

- [ ] **Step 1: Create the file with this exact content**

```markdown
# Coding Standards

## Tech Stack

**Backend (current):**
- Python 3.11+
- Django 5.x + Django REST Framework
- django-cors-headers
- Pillow + OpenCV (headless) for image processing
- ZhipuAI GLM-OCR (`glm-ocr`) for structured text extraction
- ZhipuAI GLM-4.6V-Flash (`glm-4.6v-flash`) for vision LLM calls
- JSON files for all scanner data storage; SQLite for Django internals only

**Frontend (removed — for reference if reintroduced):**
- React 18 + TypeScript (strict mode)
- Vite as build tool
- Axios for API calls
- Plain CSS / CSS Modules for styling

## Code Quality

- **Python:** Follow PEP 8. Keep functions focused and short. Prefer explicit over implicit — no magic globals or module-level side effects.
- **TypeScript (if frontend returns):** Strict mode required (`"strict": true` in `tsconfig.json`). No `any` types. Run `npm run lint` and `npm run build` before pushing to catch type errors.
- **No inline secrets.** API keys and secrets go in `.env` only, never hardcoded.
- **Logging over print.** Use `logging.getLogger(__name__)` throughout; never use `print()` in production code paths.

## Constraints and Policies

- **No ORM models for scanner data.** All invoice, supplier, and tracking data lives as JSON files under `backend/data/`. Do not introduce Django models for these.
- **No multi-process file safety.** The JSON store uses a single threading lock — safe for dev/single-worker deploys only. Do not deploy with multiple Gunicorn workers without replacing the storage layer.
- **Image size limits.** `settings.py` caps uploads at 10 MB. GLM-OCR auto-downsizes images >1 MB; images >500 KB are re-encoded as JPEG before upload.
- **GLM models only.** Tesseract and Anthropic/Gemini are removed. All OCR goes through `glm-ocr`; all vision LLM calls go through `glm-4.6v-flash`. Do not reintroduce other providers without updating `engine.py` and `api_usage.py`.
- **Supplier IDs are immutable slugs.** Once a supplier's profile directory is created, renaming the supplier in code breaks the memory lookup. Normalize via `normalize_supplier_id()` in `memory/json_store.py`.
- **Confidence scores are integers 0–100.** OCR parse results carry confidence; inferred fields use fixed tiers (80 = supplier memory, 60 = industry memory). Do not use floats.
- **Math validation tolerance.** `validator.py` uses a small absolute tolerance for float comparison. Do not raise this to paper over extraction errors.

## Security

- **Never commit `.env`.** It is gitignored; keep it that way. Rotate any key that is accidentally committed.
- **Supplier ID validation.** `_validate_supplier_id()` in `json_store.py` rejects path traversal (`..`, `/`, `\`). Always call it before constructing file paths from user input.
- **File upload validation.** Only image content types are accepted at the API layer. The 10 MB cap prevents memory exhaustion from oversized uploads.
- **No shell execution from user input.** Image processing uses Pillow/OpenCV — no `subprocess` calls with user-supplied data.
- **CORS.** `CORS_ALLOWED_ORIGINS` in `settings.py` is set from `.env`. Do not set `CORS_ALLOW_ALL_ORIGINS = True` in any environment.
- **`DEBUG=False` in production.** Django debug mode exposes stack traces and settings to the browser.
```

- [ ] **Step 2: Verify file exists and is non-empty**

```bash
wc -l .claude/rules/coding-standards.md
```

Expected: line count > 40

---

## Task 3: Create workflow-gates.md

**Files:**
- Create: `.claude/rules/workflow-gates.md`

- [ ] **Step 1: Create the file with this exact content**

```markdown
# Workflow Gates

## Phase Gates

- **Never implement without a written plan.** Phase plans live in `docs/superpowers/plans/`. Create a plan using the `writing-plans` skill before touching code.
- Phase plans use naming: `YYYY-MM-DD-phase-NN-<name>.md`.

## Before Pushing

- Run `pytest` from `backend/` — zero failures required before any push.
- If a frontend exists: run `npm run lint` and `npm run build` from `frontend/` before pushing.
- All external API calls in tests must be mocked. Never let tests hit real GLM-OCR or GLM Vision endpoints. Patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.

## Commits

- Write clear commit messages that describe **what changed and why**, not just what file was touched.
- Keep commits focused on a single logical change. Do not mix feature work, bug fixes, and refactors in one commit.
- Use conventional commit prefixes: `feat(phase-NN):`, `fix(component):`, `chore:`, `docs:`, `test:`, `security:`.
- **No committing** `backend/venv/`, `backend/data/` (runtime data), `*.pyc`, or `.env`. These are gitignored.

## Pull Requests

- Create a PR for all changes going to `master`. Do not push feature or fix work directly to `master`.
- Never force-push to `master`.
- PR descriptions must include: **what** changed, **why** the change was made, and any **testing notes**.
- Branch naming: `feat/phase-NN-<short-name>`, `fix/<component>-<issue>`.

## Documentation

- Update `docs/ARCHITECTURE.md` and `docs/CHANGELOG.md` after major milestones, new phases, or significant additions/removals.
- Keep `CLAUDE.md` current — update it when the tech stack, pipeline, or policies change.
```

- [ ] **Step 2: Verify file exists and is non-empty**

```bash
wc -l .claude/rules/workflow-gates.md
```

Expected: line count > 30

---

## Task 4: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (remove lines 44–119, replace with `@` imports)

- [ ] **Step 1: Replace CLAUDE.md content**

Replace the entire file with:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `backend/` with the virtualenv activated (`venv/Scripts/activate` on Windows).

```bash
# Run the dev server
python manage.py runserver

# Run all tests
pytest

# Run a single test file
pytest tests/test_scanning.py

# Run a single test function
pytest tests/test_scanning.py::TestClassName::test_function_name

# Run tests matching a keyword
pytest -k "test_ocr_fast_path"
```

`pytest.ini` sets `DJANGO_SETTINGS_MODULE = restaurant-os.settings` so no env var is needed.

## Environment

Copy `.env` variables into `backend/.env`. Required keys:
- `GLM_OCR_API_KEY` — ZhipuAI key for GLM-OCR and GLM-4.6V-Flash
- `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`

---

## Architecture Overview

Restaurant OS is an AI invoice scanner for restaurant supply invoices. The backend is a Django REST API; there is no active frontend (removed after phase 22). All image processing, OCR, and LLM calls happen server-side via a hybrid GLM-OCR + GLM-4.6V-Flash pipeline with a JSON-file memory system that improves accuracy over time.

See `docs/ARCHITECTURE.md` for the full system overview, data flow, component breakdown, and API reference.

---

## Rules

@.claude/rules/coding-standards.md
@.claude/rules/workflow-gates.md
```

- [ ] **Step 2: Verify CLAUDE.md is the right length**

```bash
wc -l CLAUDE.md
```

Expected: ~45 lines (down from 120).

- [ ] **Step 3: Confirm @ imports are present**

```bash
grep "@.claude/rules" CLAUDE.md
```

Expected output:
```
@.claude/rules/coding-standards.md
@.claude/rules/workflow-gates.md
```

- [ ] **Step 4: Commit rules extraction**

```bash
git add CLAUDE.md .claude/rules/coding-standards.md .claude/rules/workflow-gates.md
git commit -m "chore: extract CLAUDE.md rules into .claude/rules/ files"
```

---

## Task 5: Create Skill-Triggering Commands

**Files:**
- Create: `.claude/commands/phase.md`
- Create: `.claude/commands/scan.md`
- Create: `.claude/commands/debug.md`

- [ ] **Step 1: Create phase.md**

```markdown
# New Phase — Restaurant OS

You are starting a new Restaurant OS feature phase. Follow this workflow exactly:

1. **Read context first** — read `docs/ARCHITECTURE.md` and the most recent plan in `docs/superpowers/plans/` to understand where the project is.
2. **Ask for the phase name and goal** — if not provided in the user's message, ask: "What is the phase number and what does it build?"
3. **Research** — explore the relevant files in `backend/scanner/` that the new phase will touch. Identify existing patterns to follow.
4. **Invoke brainstorming** — use the `superpowers:brainstorming` skill to design the feature. Do not skip this step.
5. **Invoke writing-plans** — use the `superpowers:writing-plans` skill to produce a step-by-step implementation plan saved to `docs/superpowers/plans/YYYY-MM-DD-phase-NN-<name>.md`.
6. **Implement with TDD** — use `superpowers:test-driven-development`. Mock all GLM calls: patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.
7. **Run tests** — `cd backend && pytest`. Zero failures required before proceeding.
8. **Update docs** — update `docs/ARCHITECTURE.md` and `docs/CHANGELOG.md`.
9. **Commit and push** — use `feat(phase-NN):` prefix. Create a PR.

@.claude/skills/new-phase/new-phase.md
```

- [ ] **Step 2: Create scan.md**

```markdown
# Scan Test — Restaurant OS

You are running an end-to-end scan test. Follow this workflow:

1. **Get the input** — ask for an image path or test fixture name if not provided.
2. **Run the scan** — invoke `scan_invoice()` with the provided image. Use the test infrastructure in `backend/tests/integration_helpers.py` for fixtures.
3. **Check OCR output** — inspect the raw GLM-OCR response: did it extract text? What confidence scores were returned?
4. **Validate extracted JSON** — check all required fields are present: supplier, invoice_number, date, line_items, total. Verify line item math within tolerance. Check supplier ID matches a known slug.
5. **Check memory update** — verify `backend/data/<supplier_id>/` was updated correctly after the scan.
6. **Report results** — give a pass/fail summary with field-level detail for any failures. Include the exact extracted values and what was expected.

@.claude/skills/scan-test/scan-test.md
```

- [ ] **Step 3: Create debug.md**

```markdown
# Debug Scan — Restaurant OS

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
```

- [ ] **Step 4: Verify command files exist**

```bash
ls .claude/commands/
```

Expected: `debug.md  phase.md  scan.md`

---

## Task 6: Create Utility Commands

**Files:**
- Create: `.claude/commands/activate-venv.md`
- Create: `.claude/commands/run-tests.md`
- Create: `.claude/commands/check-logs.md`

- [ ] **Step 1: Create activate-venv.md**

```markdown
# Activate Virtual Environment

Run the following to activate the Restaurant OS backend virtual environment and confirm it is working:

```bash
source backend/venv/Scripts/activate && python --version && python -c "import django; print('Django', django.__version__)"
```

Expected output: Python version line followed by `Django 5.x.x`.

If activation fails, check that `backend/venv/` exists. If not, run:
```bash
cd backend && python -m venv venv && source venv/Scripts/activate && pip install -r requirements.txt
```
```

- [ ] **Step 2: Create run-tests.md**

```markdown
# Run Tests

Run the full Restaurant OS test suite:

```bash
cd backend && python -m pytest -v 2>&1
```

- Zero failures required before any commit or push.
- All GLM API calls are mocked — tests do not hit real endpoints.
- To run a single test file: `pytest tests/test_scanning.py -v`
- To run a single test: `pytest tests/test_scanning.py::TestClass::test_name -v`
- To filter by keyword: `pytest -k "test_ocr_fast_path" -v`

`pytest.ini` sets `DJANGO_SETTINGS_MODULE = restaurant-os.settings` — no env var needed.
```

- [ ] **Step 3: Create check-logs.md**

```markdown
# Check Logs

To see Django dev server output, run the server in the foreground:

```bash
cd backend && python manage.py runserver 2>&1
```

To check for recent Python tracebacks in the current session output, look for lines starting with `Traceback (most recent call last)`.

To check what GLM API calls were made during a scan, grep the running server output for:
```bash
grep -i "glm\|ocr\|vision\|scan" backend/logs/*.log 2>/dev/null || echo "No log files found — check server stdout"
```

If you need structured logging, `logging.getLogger(__name__)` is used throughout `backend/scanner/`. Log level is set in `backend/restaurant-os/settings.py`.
```

- [ ] **Step 4: Verify all 6 command files exist**

```bash
ls .claude/commands/
```

Expected: `activate-venv.md  check-logs.md  debug.md  phase.md  run-tests.md  scan.md`

- [ ] **Step 5: Commit commands**

```bash
git add .claude/commands/
git commit -m "chore: add .claude/commands/ with skill-triggering and utility slash commands"
```

---

## Task 7: Create new-phase Skill

**Files:**
- Create: `.claude/skills/new-phase/new-phase.md`

- [ ] **Step 1: Create the skill file**

```markdown
# New Phase Skill — Restaurant OS

This skill guides a complete Restaurant OS feature phase from inception to merged PR.

## Trigger

Invoked by the `/phase` command or when starting any new phase of work.

## Workflow

### Step 1: Orient
- Read `docs/ARCHITECTURE.md` to understand current system state
- Read the most recent file in `docs/superpowers/plans/` to understand what phase came before
- Read `docs/CHANGELOG.md` for the milestone history

### Step 2: Define the Phase
Ask the user for:
- Phase number (e.g., Phase 23)
- Phase goal (one sentence: what does it build?)
- Any constraints or known dependencies

### Step 3: Research
Explore the codebase area the phase will touch:
- Identify files that will be created or modified
- Note existing patterns (function signatures, error handling style, test patterns)
- Check `backend/tests/` for existing test patterns to follow

### Step 4: Brainstorm
Invoke `superpowers:brainstorming` to design the feature. Do NOT skip this step. The design must be approved before planning begins.

### Step 5: Write the Plan
Invoke `superpowers:writing-plans` to produce a step-by-step plan. Save to:
`docs/superpowers/plans/YYYY-MM-DD-phase-NN-<name>.md`

### Step 6: Implement with TDD
Invoke `superpowers:test-driven-development`.

Key rules for Restaurant OS tests:
- Mock all external calls: `unittest.mock.patch('scanner.scanning.engine._call_glm_ocr')` and `unittest.mock.patch('scanner.scanning.engine._call_glm_vision')`
- Use `backend/tests/integration_helpers.py` for shared fixtures
- Run after each test: `cd backend && pytest -v`

### Step 7: Gate Check
```bash
cd backend && pytest
```
Zero failures required. Do not proceed to commit if any test fails.

### Step 8: Update Documentation
- Update `docs/ARCHITECTURE.md` — add new components, update data flow if changed
- Update `docs/CHANGELOG.md` — add an entry under the new phase number

### Step 9: Commit and PR
```bash
git add -p  # stage selectively — never include backend/data/, venv/, .env, *.pyc
git commit -m "feat(phase-NN): <what changed and why>"
git push origin feat/phase-NN-<short-name>
gh pr create --title "feat(phase-NN): <short description>"
```
```

- [ ] **Step 2: Verify file exists**

```bash
ls .claude/skills/new-phase/
```

Expected: `new-phase.md`

---

## Task 8: Create scan-test Skill

**Files:**
- Create: `.claude/skills/scan-test/scan-test.md`

- [ ] **Step 1: Create the skill file**

```markdown
# Scan Test Skill — Restaurant OS

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
cd backend && pytest tests/test_integration.py -v -k "your_test_name"
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
```

- [ ] **Step 2: Verify file exists**

```bash
ls .claude/skills/scan-test/
```

Expected: `scan-test.md`

---

## Task 9: Create debug-scan Skill

**Files:**
- Create: `.claude/skills/debug-scan/debug-scan.md`

- [ ] **Step 1: Create the skill file**

```markdown
# Debug Scan Skill — Restaurant OS

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

Run: `cd backend && pytest tests/test_scanning.py::test_specific_failure -v`
Expected: FAIL (confirms the hypothesis).

### Step 5: Fix and Verify
Implement the fix. Re-run the focused test (should now PASS), then run the full suite:
```bash
cd backend && pytest -v
```
Zero failures required before committing.
```

- [ ] **Step 2: Verify file exists**

```bash
ls .claude/skills/debug-scan/
```

Expected: `debug-scan.md`

- [ ] **Step 3: Commit skills**

```bash
git add .claude/skills/
git commit -m "chore: add .claude/skills/ with new-phase, scan-test, and debug-scan workflows"
```

---

## Task 10: Create agents Placeholder and Final Commit

**Files:**
- Create: `.claude/agents/.gitkeep`

- [ ] **Step 1: Create .gitkeep so agents/ is tracked by git**

```bash
touch .claude/agents/.gitkeep
```

- [ ] **Step 2: Verify full .claude/ structure**

```bash
find .claude/ -type f | sort
```

Expected output:
```
.claude/agents/.gitkeep
.claude/commands/activate-venv.md
.claude/commands/check-logs.md
.claude/commands/debug.md
.claude/commands/phase.md
.claude/commands/run-tests.md
.claude/commands/scan.md
.claude/rules/coding-standards.md
.claude/rules/workflow-gates.md
.claude/settings.local.json
.claude/skills/debug-scan/debug-scan.md
.claude/skills/new-phase/new-phase.md
.claude/skills/scan-test/scan-test.md
```

- [ ] **Step 3: Final commit**

```bash
git add .claude/agents/.gitkeep
git commit -m "chore: add .claude/agents/ placeholder for future agent definitions"
```

---

## Verification

- [ ] **1. Rules load:** Start a new Claude Code session in this project. Ask Claude "what are the confidence score rules?" — it should answer from `coding-standards.md` without being told to read it.
- [ ] **2. /phase command:** Type `/phase` — Claude should ask for a phase number/goal and start the new-phase workflow.
- [ ] **3. /scan command:** Type `/scan` — Claude should ask for an image path and start the scan-test workflow.
- [ ] **4. /debug command:** Type `/debug` — Claude should ask what went wrong and start the debug-scan workflow.
- [ ] **5. /run-tests command:** Type `/run-tests` — Claude should run `cd backend && python -m pytest -v`.
- [ ] **6. CLAUDE.md is slim:** Confirm `CLAUDE.md` is ~45 lines and contains `@.claude/rules/coding-standards.md`.
- [ ] **7. pytest still passes:** `cd backend && pytest` — zero failures (no code was changed, only docs/config).
