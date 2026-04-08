# Commit and Push Skill — SmartScanner

This skill guides a safe, standards-compliant commit and push for the SmartScanner project.

## Trigger

Invoked by the `/commit-push` command or when the user asks to commit and push changes.

## Workflow

### Step 1: Verify Tests Pass

Run the full test suite before touching git. Zero failures required.

```bash
cd backend && python -m pytest
```

If any test fails, **stop here**. Fix the failures before proceeding.

### Step 2: Update the Changelog

Invoke the `changelog-updater` agent to write an accurate entry to `docs/CHANGELOG.md` before staging anything:

```
Use the Agent tool with subagent_type="changelog-updater"
```

The agent will read recent git history, classify the changes, and insert a properly formatted entry. Do not skip this step — the changelog must be updated before the commit so the entry is included in the same commit.

### Step 3: Review What Changed

```bash
git status
git diff
```

Identify every modified, added, or deleted file. Understand the scope before staging.

### Step 4: Stage Selectively

Never use `git add -A` or `git add .`. Stage only intentional changes:

```bash
git add <specific files>
```

**Never stage:**
- `backend/data/` — runtime JSON data
- `backend/venv/` — virtualenv
- `backend/.env` — secrets
- `*.pyc` / `__pycache__/` — compiled bytecode

### Step 5: Write the Commit Message

Follow conventional commit format:

```
feat(phase-NN): <what changed and why>
fix(<component>): <what was broken and what the fix does>
chore: <maintenance task>
docs: <documentation update>
test: <test additions or fixes>
security: <security fix>
```

Rules:
- Describe **what changed and why**, not just which file was touched
- One logical change per commit — do not mix feature work, fixes, and refactors

Commit using a heredoc to preserve formatting:

```bash
git commit -m "$(cat <<'EOF'
feat(phase-NN): <description>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### Step 6: Push

Push to the current feature branch — **never directly to `master`**:

```bash
git push origin <current-branch>
```

If the branch has no upstream yet:

```bash
git push -u origin <current-branch>
```

### Step 7: Open a PR (if not already open)

```bash
gh pr create --title "<conventional commit title>" --body "$(cat <<'EOF'
## Summary
- <bullet: what changed>
- <bullet: why it changed>

## Testing
- [ ] `pytest` passes with zero failures
- [ ] No secrets, data files, or venv committed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL to the user.

## Hard Rules

- **Never force-push to `master`.**
- **Never skip `--no-verify`** unless the user explicitly requests it.
- **Never commit `.env`, `backend/data/`, or `backend/venv/`.**
- **Tests must pass before any commit.**
