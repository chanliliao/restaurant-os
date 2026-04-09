# New Phase — Restaurant OS

You are starting a new Restaurant OS feature phase. Follow this workflow exactly:

1. **Read context first** — read `docs/ARCHITECTURE.md` and the most recent plan in `docs/superpowers/plans/` to understand where the project is.
2. **Ask for the phase name and goal** — if not provided in the user's message, ask: "What is the phase number and what does it build?"
3. **Research** — explore the relevant files in `backend/scanner/` that the new phase will touch. Identify existing patterns to follow.
4. **Invoke brainstorming** — use the `superpowers:brainstorming` skill to design the feature. Do not skip this step.
5. **Invoke writing-plans** — use the `superpowers:writing-plans` skill to produce a step-by-step implementation plan saved to `docs/superpowers/plans/YYYY-MM-DD-phase-NN-<name>.md`.
6. **Implement with TDD** — use `superpowers:test-driven-development`. Mock all GLM calls: patch `scanner.scanning.engine._call_glm_ocr` and `scanner.scanning.engine._call_glm_vision`.
7. **Run tests** — `cd backend && python -m pytest`. Zero failures required before proceeding.
8. **Update docs** — update `docs/ARCHITECTURE.md` and `docs/CHANGELOG.md`.
9. **Commit and push** — use `feat(phase-NN):` prefix. Create a PR.

@.claude/skills/new-phase/new-phase.md
