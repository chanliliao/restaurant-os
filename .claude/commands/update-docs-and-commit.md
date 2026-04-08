# Update Docs and Commit — SmartScanner

You are finishing a unit of work for SmartScanner and need to update docs and commit. Follow this workflow exactly:

1. **Run tests first** — `cd backend && python -m pytest`. Zero failures required before any commit.
2. **Update CHANGELOG.md** — invoke the `changelog-updater` agent to write an entry to `docs/CHANGELOG.md` before staging.
3. **Update PROJECT_STATUS.md** — inline: check off completed work, update active/next sections, update the "Last updated" date.
4. **Check ARCHITECTURE.md** — update only if endpoints, modules, data flow, or external dependencies changed. Skip for bug fixes and tooling changes.
5. **Review changes** — `git status` and `git diff` to confirm docs and code are all in the diff.
6. **Stage selectively** — never `git add -A`. Stage specific files only. Never include `backend/data/`, `backend/venv/`, `.env`, or `*.pyc`.
7. **Commit** — use conventional commit prefix (`feat`, `fix`, `chore`, `docs`, `test`, `security`). Describe what changed and why. No push.

@.claude/skills/update-docs-and-commit/update-docs-and-commit.md
