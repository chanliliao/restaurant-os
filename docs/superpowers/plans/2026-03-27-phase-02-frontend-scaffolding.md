# Phase 02 + 02b: Frontend Scaffolding + Scan Controls UI

## Date: 2026-03-27

## Goals
- **Phase 02:** React app with Vite + TypeScript that can talk to the backend API
- **Phase 02b:** Mode dropdown (Light/Normal/Heavy) and debug toggle wired to API

## Prerequisites
- Phase 01 complete: Django REST backend with `POST /api/scan/` returning dummy JSON
- Backend accepts `image` (file) and `mode` (light/normal/heavy) parameters

## Implementation Plan

### Step 1: Scaffold Vite React-TS project
- Run `npm create vite@latest . -- --template react-ts` in `frontend/`
- Install dependencies: `npm install` + `npm install axios`
- Clean out default Vite boilerplate (App.css content, default counter code)

### Step 2: Create TypeScript interfaces (`src/types/scan.ts`)
- `ScanMode` type: "light" | "normal" | "heavy"
- `LineItem` interface: name, quantity, unit, unit_price, total, confidence
- `ScanResponse` interface: supplier, date, invoice_number, items, subtotal, tax, total, confidence, inference_sources, scan_metadata
- `ScanRequest` interface: image (File), mode (ScanMode), debug (boolean)

### Step 3: Create API service (`src/services/api.ts`)
- Axios instance with baseURL pointing to `/api` (proxied by Vite)
- `scanInvoice(file: File, mode: ScanMode, debug: boolean): Promise<ScanResponse>` function
- Uses FormData to send multipart file + mode parameter

### Step 4: Create DropZone component (`src/components/DropZone.tsx`)
- HTML5 drag-and-drop zone for image files
- Accept image/* file types
- Visual feedback on drag-over
- Calls parent callback with selected file
- Also supports click-to-browse

### Step 5: Create ScanControls component (`src/components/ScanControls.tsx`)
- Dropdown for scan mode: Light / Normal / Heavy (default Normal)
- Checkbox for debug mode (default off)
- Exposes state via props/callbacks

### Step 6: Create App.tsx
- State: scan mode, debug mode, scan result, loading, error
- Layout: ScanControls at top, DropZone in middle, JSON result display below
- On file drop: call API with file + mode + debug, display result as formatted JSON

### Step 7: Create styles (`src/styles/app.css`)
- Minimal clean styling for DropZone, controls, and result display
- Drop zone visual states (idle, hover, loading)

### Step 8: Configure Vite proxy (`vite.config.ts`)
- Proxy `/api/*` to `http://localhost:8000`

### Step 9: Verify
- `npm run build` succeeds with no TypeScript errors
- `npm audit` for security

### Step 10: Commit and push

## Files to Create/Modify
- `frontend/` (entire new directory)
  - `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`
  - `src/types/scan.ts`
  - `src/services/api.ts`
  - `src/components/DropZone.tsx`
  - `src/components/ScanControls.tsx`
  - `src/App.tsx`
  - `src/main.tsx`
  - `src/styles/app.css`

## Security Considerations
- File upload: validate image type on client side (defense in depth; backend validates too)
- No API keys in frontend code
- XSS: React auto-escapes; JSON display uses `<pre>` with `JSON.stringify`
- CORS: already configured in Django backend
- npm audit after install
