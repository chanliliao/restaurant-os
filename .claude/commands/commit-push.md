# Commit and Push — SmartScanner

You are committing and pushing changes for the SmartScanner project. Follow this workflow exactly:

1. **Run tests first** — `cd backend && python -m pytest`. Zero failures required before any commit.
2. **Review changes** — `git status` and `git diff` to understand what changed.
3. **Stage selectively** — never `git add -A`. Stage specific files only. Never include `backend/data/`, `backend/venv/`, `.env`, or `*.pyc`.
4. **Write a focused commit message** — use conventional commit prefix (`feat`, `fix`, `chore`, `docs`, `test`, `security`). Describe what changed and why.
5. **Push to feature branch** — never push directly to `master`. Use `git push -u origin <branch>` if no upstream exists.
6. **Open a PR** — use `gh pr create` if one doesn't exist yet. Return the PR URL to the user.

@.claude/skills/commit-push/commit-push.md
