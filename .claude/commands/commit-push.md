# Commit and Push — SmartScanner

You are committing and pushing changes for the SmartScanner project. Follow this workflow exactly:

1. **Run tests first** — `cd backend && python -m pytest`. Zero failures required before any commit.
2. **Update the changelog** — invoke the `changelog-updater` agent to write an entry to `docs/CHANGELOG.md` before staging.
3. **Review changes** — `git status` and `git diff` to understand what changed.
4. **Stage selectively** — never `git add -A`. Stage specific files only. Never include `backend/data/`, `backend/venv/`, `.env`, or `*.pyc`.
5. **Write a focused commit message** — use conventional commit prefix (`feat`, `fix`, `chore`, `docs`, `test`, `security`). Describe what changed and why.
6. **Push to feature branch** — never push directly to `master`. Use `git push -u origin <branch>` if no upstream exists.
7. **Open a PR** — use `gh pr create` if one doesn't exist yet. Return the PR URL to the user.

@.claude/skills/commit-push/commit-push.md
