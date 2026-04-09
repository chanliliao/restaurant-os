# Workflow Gates

## Phase Gates

- **Never implement without a written plan.** Phase plans live in `docs/superpowers/plans/`. Create a plan using the `superpowers:writing-plans` skill (a Claude Code superpowers skill) before touching code.
  - `superpowers:writing-plans`, `superpowers:brainstorming`, and `superpowers:test-driven-development` are built-in Claude Code Superpowers skills — invoke them by name in the `/phase` command flow.
- Phase plans use naming: `YYYY-MM-DD-phase-NN-<name>.md`.

## Before Pushing

- Run `pytest` from `backend/` — zero failures required before any push.
- If a frontend exists: run `npm run lint` and `npm run build` from `frontend/` to catch type errors and build failures before pushing.
- All external API calls in tests must be mocked. Never let tests hit real GLM-OCR or GLM Vision endpoints. Patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.

## Commits

- Use Restaurant OS-specific prefix format: `feat(phase-NN):`, `fix(component):` when referencing a phase or component.
- **No committing** `backend/venv/`, `backend/data/` (runtime data), `*.pyc`, or `.env`. These are gitignored; keep them there.
- **Before any `git add`:** Run `git status` and verify no files under `backend/data/` appear as modified or tracked. If a `backend/data/` file is tracked, remove it with `git rm --cached <file>` before staging anything else.

## Pull Requests

- Create a PR for all changes going to `master`. Do not push directly to `master`.
- Never force-push to `master`.
- PR descriptions must include: **what** changed, **why** the change was made, and any **testing notes**.
- Branch naming: `feat/phase-NN-<short-name>`, `fix/<component>-<issue>`.

## Documentation

- Update `docs/ARCHITECTURE.md` and `docs/CHANGELOG.md` after major milestones, new phases, or significant additions/removals.
- Keep `CLAUDE.md` current — update it when the tech stack, pipeline, or policies change.

## Rule File Maintenance

- **When editing rule files for brevity:** Preserve all substantive constraints. Shortening a sentence that contains an action (e.g., "do not deploy with multiple workers", "do not reintroduce other providers") requires an explicit decision to drop that action — not just implicit style trimming. When in doubt, keep the constraint.
