---
name: start-lesson
description: Use when the user runs /start-lesson <N> to begin a Restaurant OS→Restaurant OS migration lesson. Reads the lesson plan for lesson N and fully executes all migration work: deletions, directory creation, and complete working implementations of all new files.
---

# Start Lesson — Restaurant OS Migration

Executes one lesson from `docs/analysis/lesson-plan.md` end-to-end: reads the plan, deletes deprecated files, creates new directories, and **writes complete, working code** for every new file — not stubs, not skeletons, not TODOs.

## Trigger

Invoked by `/start-lesson <N>` where `<N>` is a lesson number (1–14).

## Workflow

### Step 1: Read the Lesson Plan

Read the full lesson section for lesson N from `docs/analysis/lesson-plan.md`.

Extract before touching any file:
1. **What to build** — every file and its purpose ("What you'll build" paragraph)
2. **Migration table** — each row: source path, action (`[PORT]`, `[DEPRECATED]`, `[NEW]`, `[NEW - REPLACE]`), target path
3. **Key concepts** — "What you'll learn" bullets (inform the implementation choices)
4. **Checkpoint** — the validation task (confirms what the finished code must be able to do)

Also read `docs/analysis/project-dir-scaffold.md` Section 2 for the target directory tree.

For `[PORT]` actions, read the Restaurant OS source file being ported before writing the target. Understand what it does so the port preserves the logic.

### Step 2: Orient to Current State

```bash
find backend/src/restaurant_os -type f -name "*.py" | sort
git status --short
```

Cross-reference against the migration table. Skip actions whose source is already gone or target already exists.

### Step 3: Delete Deprecated Files

For every `[DEPRECATED]` or `[NEW - REPLACE]` source that still exists:

```bash
rm backend/<path>
```

Only delete files listed in this lesson's migration table.

### Step 4: Create New Directories

For every new file whose parent directory does not yet exist:

```bash
mkdir -p backend/src/restaurant_os/<module>/
touch backend/src/restaurant_os/<module>/__init__.py
```

### Step 5: Write Complete Implementations

For every `[NEW]`, `[NEW - REPLACE]`, and `[PORT]` target file — **write real, working code**.

**What "complete" means:**
- Every function and class has a full implementation, not `pass`
- All imports resolve correctly
- The file does what the lesson says it does
- For `[PORT]` files: the Restaurant OS logic is preserved and adapted to the new stack (async, Pydantic v2, etc.)
- For `[NEW]` files: implements the feature as described in "What you'll build"
- The checkpoint at the end of the lesson can be satisfied by running against this code

**What to keep in mind while implementing:**
- Use the tech stack for this lesson (e.g., lesson 2 = Pydantic v2, lesson 6 = SQLAlchemy async)
- Follow `coding-standards.md` — no print(), logging over print, typed signatures, PEP 8
- Follow `requirements.txt` — only use packages already listed
- Security rules apply: supplier ID validation, no inline secrets, no shell injection

**File header docstring** — every file starts with:
```python
"""
One-line description of what this module does.

Replaces: backend/scanner/<source>.py  (or "none" if entirely new)
Learn: <the key concept this file demonstrates from the lesson's "What you'll learn">
"""
```

This is the pedagogical header — it situates the file in the migration narrative. Do not omit it.

### Step 6: Wire Up Imports

Read any prior-lesson file that needs to connect to this lesson's new modules. Replace placeholder comments with real imports and real calls now that the targets exist.

Example: once `core/config.py` exists, update `api/app.py` to import and use `settings.cors_allowed_origins` instead of `os.getenv(...)`.

### Step 7: Verify the Module Tree is Importable

```bash
cd backend && python -c "import src.restaurant_os; print('ok')"
```

Fix any import error before finishing.

### Step 8: Announce Completion

Report:
- Files deleted (with migration table reason)
- Files created or updated (one-line purpose each)
- Imports wired (what was connected and where)
- The checkpoint from the lesson — so the user can validate the implementation themselves

---

## Hard Rules

- **Read the lesson plan first, every time.** Do not rely on memory.
- **Write real code, not stubs.** Every function must have a body. If upstream dependencies (DB, Redis, agent) are not built yet, implement what is possible and make the missing pieces explicit via a raised `NotImplementedError` with a message pointing to the section that will fill it in — never silently `pass`.
- **For `[PORT]` files: read the source first.** Port the logic faithfully; don't rewrite from scratch.
- **Only delete files in this lesson's migration table.** Never delete speculatively.
- **Every created file must be importable.** Fix syntax and import errors before reporting done.
- **Do not skip the "Replaces / Learn" header.** It is how the user understands what changed and why.
- **One lesson at a time.** Do not pre-build files for future lessons.
