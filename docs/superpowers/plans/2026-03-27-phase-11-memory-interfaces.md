# Phase 11: Memory Interfaces + JSON Storage

## Goal
Build the storage layer for supplier-specific and general industry memory using abstract interfaces and JSON file implementations.

## Design

### 1. `backend/scanner/memory/interface.py` — Abstract base classes
- `SupplierMemory(ABC)` — get_profile, save_scan, infer_missing, get_layout, update_layout
- `GeneralMemory(ABC)` — get_industry_profile, get_item_catalog, update_from_scan

### 2. `backend/scanner/memory/json_store.py` — JSON implementations
- `JsonSupplierMemory(SupplierMemory)`:
  - Per-supplier dirs: `data/suppliers/{supplier_id}/profile.json`, `layout.json`
  - Normalize supplier IDs: lowercase, spaces to hyphens, strip special chars
  - Path traversal protection: validate supplier_id contains no `.` or `/`
  - Thread-safe writes via atomic temp-file + rename
  - `save_scan`: appends to history, updates running averages, updates index
  - `infer_missing`: returns most common historical value for a field
- `JsonGeneralMemory(GeneralMemory)`:
  - Reads/writes `data/general/industry_profile.json` and `item_catalog.json`
  - `update_from_scan`: merges new items into catalog with running price averages

### 3. `backend/scanner/memory/__init__.py` — Exports

### 4. `backend/tests/test_memory.py` — Tests
- All operations against a temp directory
- CRUD supplier profiles, scan saving, inference, layout, general memory
- Supplier ID normalization and path traversal rejection
- Corrupt/missing file handling

## Security
- Supplier ID normalization rejects path traversal characters (`..`, `/`, `\`)
- All file paths are resolved and checked to stay within DATA_DIR

## Checklist
- [ ] Write interface.py
- [ ] Write json_store.py
- [ ] Update __init__.py exports
- [ ] Write test_memory.py
- [ ] All tests pass
- [ ] Security review (path traversal)
- [ ] Commit and push
- [ ] Update tracker
