# .claude Folder Structure — SmartScanner

**Date:** 2026-04-08
**Status:** Approved

## Context

SmartScanner's `.claude/` project folder currently contains only a `settings.local.json` with a few bash permissions. All rules, constraints, and workflow guidance live inline in `CLAUDE.md`, making it hard to maintain as the project grows. This design organizes the `.claude/` folder into a structured system: rules extracted into dedicated files, custom slash commands for common workflows, project-specific skills that auto-invoke repeatable workflows, and an agents folder (empty for now, populated on demand).

## Goal

- Extract CLAUDE.md rules into `.claude/rules/` files, keeping CLAUDE.md as a thin index
- Add custom slash commands for skill-triggering and utility operations
- Add project-specific skills for the three core SmartScanner workflows
- Create an empty `agents/` folder ready for future population

---

## Folder Structure

```
.claude/
├── settings.local.json          # existing bash permissions (keep, expand)
├── commands/
│   ├── phase.md                 # /phase — triggers new-phase skill
│   ├── scan.md                  # /scan — triggers scan-test skill
│   ├── debug.md                 # /debug — triggers debug-scan skill
│   ├── activate-venv.md         # /activate-venv — activates backend venv
│   ├── run-tests.md             # /run-tests — runs pytest from backend/
│   └── check-logs.md            # /check-logs — tails Django log output
├── rules/
│   ├── coding-standards.md      # tech stack, code quality, constraints, security
│   └── workflow-gates.md        # phase gates, test requirements, commit/PR rules
├── skills/
│   ├── new-phase/
│   │   └── new-phase.md         # full phase lifecycle: research → plan → implement → test → commit
│   ├── scan-test/
│   │   └── scan-test.md         # end-to-end scan: OCR → JSON validate → memory check
│   └── debug-scan/
│       └── debug-scan.md        # pipeline trace: stage isolation → hypothesis → fix → verify
└── agents/                      # empty — populate on demand
```

---

## CLAUDE.md Changes

`CLAUDE.md` retains: Commands, Environment setup, Architecture summary, links to docs.

`CLAUDE.md` removes (moves to rules/): Design Style Guide, Constraints & Policies, Security, Repo Etiquette.

Replacement in CLAUDE.md:
```markdown
## Rules
@.claude/rules/coding-standards.md
@.claude/rules/workflow-gates.md
```

---

## Rules Files

### `coding-standards.md`
Sourced from CLAUDE.md sections: Design Style Guide, Constraints and Policies, Security.
- Tech stack (Python 3.11+, Django 5.x, GLM models only — no Tesseract, no Anthropic/Gemini)
- PEP 8, no `print()`, use `logging.getLogger(__name__)`
- No ORM models for scanner data — JSON files under `backend/data/` only
- Confidence scores are integers 0–100 (no floats)
- Supplier IDs are immutable slugs — always normalize via `normalize_supplier_id()` in `memory/json_store.py`
- Image size limits: 10 MB upload cap, >1 MB auto-downsized, >500 KB re-encoded as JPEG
- Math validation uses small absolute tolerance — do not raise it
- Security: no shell execution from user input, `_validate_supplier_id()` blocks path traversal, CORS from env only, `DEBUG=False` in production

### `workflow-gates.md`
Sourced from CLAUDE.md section: Repo Etiquette.
- Never implement without a plan in `docs/superpowers/plans/`
- Run `pytest` from `backend/` — zero failures before any push
- All GLM calls in tests must be mocked: patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`
- Conventional commit prefixes: `feat(phase-NN):`, `fix(component):`, `chore:`, `docs:`, `test:`, `security:`
- PR required for all changes to `master` — no direct pushes, no force-push
- PR description must include: what changed, why, testing notes
- Branch naming: `feat/phase-NN-<short-name>`, `fix/<component>-<issue>`
- Update `docs/ARCHITECTURE.md` + `docs/CHANGELOG.md` after major milestones

---

## Commands

### Skill-Triggering
| Command | Invokes | Purpose |
|---------|---------|---------|
| `/phase` | new-phase skill | Start a new feature phase end-to-end |
| `/scan` | scan-test skill | Run an end-to-end scan test |
| `/debug` | debug-scan skill | Debug a bad scan result |

### Utility
| Command | Action |
|---------|--------|
| `/activate-venv` | Activate `backend/venv/Scripts/activate`, confirm Python path |
| `/run-tests` | `cd backend && pytest` with clean output |
| `/check-logs` | Tail Django dev server log / print recent tracebacks |

---

## Skills

### `new-phase` (triggered by `/phase`)
Auto-invokes for any new SmartScanner feature phase:
1. Read `docs/ARCHITECTURE.md` + last phase plan for context
2. Research the feature area (relevant files, existing patterns)
3. Invoke brainstorming → writing-plans for spec + plan
4. Implement with TDD (mock all GLM calls)
5. Run `pytest` — zero failures gate
6. Update `ARCHITECTURE.md` + `CHANGELOG.md`
7. Commit + push with `feat(phase-NN):` prefix

### `scan-test` (triggered by `/scan`)
End-to-end scan validation:
1. Accept image path or test fixture
2. Run through `scan_invoice()` pipeline
3. Check OCR intermediate output (raw text, confidence scores)
4. Validate extracted JSON (required fields, math, supplier match)
5. Verify memory updated correctly in `data/` JSON files
6. Report pass/fail with field-level detail

### `debug-scan` (triggered by `/debug`)
Structured scan debugging:
1. Capture bad output + error description
2. Trace pipeline stages: image preprocessing → GLM-OCR → GLM vision → validator → memory
3. Isolate which stage introduced the error
4. Form hypothesis → test → fix → verify

---

## Agents

`agents/` folder created empty. Populate on demand. Planned candidates (deferred):
- `scan-tester` — pipeline investigator
- `phase-planner` — architecture-aware phase designer
- `invoice-validator` — JSON business rules checker
- `memory-inspector` — supplier memory debugger

---

## Verification

1. `.claude/rules/` files load correctly — confirm Claude reads rules by checking it enforces `normalize_supplier_id()` in a new session
2. `/phase`, `/scan`, `/debug` commands invoke the right skills when typed
3. `/activate-venv`, `/run-tests`, `/check-logs` execute correct bash operations
4. `CLAUDE.md` `@` imports resolve — Claude should see rule content without it being inline
5. `pytest` still passes after CLAUDE.md refactor (no code changes, just doc restructure)
