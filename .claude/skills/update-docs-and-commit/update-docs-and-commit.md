# Update Docs and Commit Skill — SmartScanner

This skill guides a complete docs-first commit workflow for SmartScanner: tests → docs → commit. No push.

## Trigger

Invoked by the `/update-docs-and-commit` command or when the user finishes a feature, phase, bug fix, or any meaningful chunk of work and is ready to commit.

## Workflow

### Step 1: Verify Tests Pass

Run the full test suite. Zero failures required before touching docs or git.

```bash
cd backend && python -m pytest
```

If any test fails, **stop here**. Fix the failures before proceeding.

---

### Step 2: Update CHANGELOG.md

Dispatch the `changelog-updater` agent to write an accurate entry before staging anything:

```
Use the Agent tool with subagent_type="changelog-updater"
```

The agent reads recent git history, classifies the changes, and inserts a properly formatted entry at the top of `docs/CHANGELOG.md`. Do not skip — the changelog entry must be in the same commit as the code change.

---

### Step 3: Update PROJECT_STATUS.md

Update `docs/PROJECT_STATUS.md` inline — you have the full conversation context about what just changed.

Check and update:
- **Completed Phases / Completed Tooling** — mark anything that just finished; add a row if needed
- **Active Work** — remove or update items that are now done
- **Next / Potential Work** — add any newly identified follow-up items
- **Last updated** date at the top

Use the Edit tool to make targeted changes. Do not rewrite the whole file.

---

### Step 4: Check ARCHITECTURE.md

Open `docs/ARCHITECTURE.md` and judge whether it needs updating based on what changed.

**Update it if any of these changed:**
- New or removed API endpoints
- New modules or packages added to `backend/scanner/`
- Data flow changed (new pipeline stage, stage removed, stage reordered)
- New external dependency or service

**Skip it if:**
- Only bug fixes, config tweaks, or test changes
- Only docs/tooling changes

If an update is needed, edit only the relevant section. Do not rewrite sections that are still accurate.

---

### Step 5: Review What Changed

```bash
git status
git diff
```

Identify every modified, added, or deleted file. Confirm the three docs are in the diff alongside the code changes.

---

### Step 6: Stage Selectively

Never use `git add -A` or `git add .`. Stage specific files only:

```bash
git add <specific files>
```

**Never stage:**
- `backend/data/` — runtime JSON data
- `backend/venv/` — virtualenv
- `backend/.env` — secrets
- `*.pyc` / `__pycache__/` — compiled bytecode

---

### Step 7: Commit

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

Commit using a heredoc:

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <description>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Hard Rules

- **No push.** This skill commits only. Push and PR are separate decisions.
- **Never force-push to `master`.**
- **Never commit `.env`, `backend/data/`, or `backend/venv/`.**
- **Tests must pass before any commit.**
- **All three docs (CHANGELOG, PROJECT_STATUS, ARCHITECTURE if applicable) must be updated before staging.**
