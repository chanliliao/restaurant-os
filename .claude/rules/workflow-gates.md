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
