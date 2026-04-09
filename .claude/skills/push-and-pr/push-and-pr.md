# Push and PR Skill — Restaurant OS

This skill runs after `update-docs-and-commit` completes. It pushes the current branch and opens a PR following Restaurant OS conventions.

## Trigger

Invoked by the `/push-pr` command when the user is ready to push a committed branch and open a PR.

## Workflow

### Step 1: Pre-flight checks

```bash
git status
git log --oneline -5
```

Verify:
- Working tree is clean (no uncommitted changes)
- Current branch is NOT `master` — never push features directly to `master`
- Branch name matches `feat/phase-NN-<short-name>` or `fix/<component>-<issue>`

If the branch name does not match the convention, stop and ask the user whether to rename it before pushing.

### Step 2: Check for tracked backend/data/ files

```bash
git status --short | grep "backend/data/"
```

If any `backend/data/` files appear as staged or tracked, stop immediately. Run `git rm --cached <file>` to untrack them before proceeding.

### Step 3: Push

```bash
git push -u origin <current-branch>
```

If the push is rejected (non-fast-forward), investigate before using force. Never force-push to `master`.

### Step 4: Construct the PR body

Gather context for the PR description:

```bash
git log master..HEAD --oneline
git diff master..HEAD --stat
```

Build a PR body with three required sections:
- **What changed** — what was built or fixed
- **Why** — the motivation (which phase goal, which bug, which requirement)
- **Testing notes** — how to verify the change (test file names, how to run, what to look for)

### Step 5: Create the PR

```bash
gh pr create \
  --title "feat(phase-NN): <short description>" \
  --base master \
  --body "$(cat <<'EOF'
## What changed
<bullet points>

## Why
<motivation — which phase goal, bug, or requirement>

## Testing notes
- Run: `cd backend && python -m pytest -v`
- All GLM calls are mocked — tests do not hit real endpoints
- <any specific test to highlight>
EOF
)"
```

### Step 6: Confirm

Print the PR URL. Verify the PR targets `master` as the base branch.
