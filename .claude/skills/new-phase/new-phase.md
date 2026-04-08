# New Phase Skill — SmartScanner

This skill guides a complete SmartScanner feature phase from inception to merged PR.

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

**Gate: before proceeding to Step 6, confirm the plan file exists:**
```bash
ls docs/superpowers/plans/ | grep "phase-NN"
```
Do not begin implementation until the plan file is saved and visible on disk.

### Step 6: Implement with TDD
Invoke `superpowers:test-driven-development`.

Key rules for SmartScanner tests:
- Mock all external calls: `unittest.mock.patch('scanner.scanning.engine._call_glm_ocr')` and `unittest.mock.patch('scanner.scanning.engine._call_glm_vision')`
- Use `backend/tests/integration_helpers.py` for shared fixtures
- Run after each test: `cd backend && python -m pytest -v`

### Step 7: Gate Check

```bash
cd backend && python -m pytest
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
