# Phase 01: Backend Scaffolding (Django REST) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a runnable Django REST API backend with empty app structure, all subpackage directories, data directories, and a placeholder scan endpoint.

**Architecture:** Django 5.x project with Django REST Framework. The `scanner` app contains subpackages for `preprocessing`, `scanning`, `memory`, and `tracking`. CORS is configured for the React dev server (localhost:5173). A placeholder `POST /api/scan/` endpoint returns dummy JSON matching the spec's output format.

**Tech Stack:** Python 3.11+, Django 5.x, Django REST Framework, django-cors-headers, python-dotenv, anthropic, Pillow, opencv-python-headless, pytesseract

---

## File Structure

```
backend/
├── manage.py
├── requirements.txt
├── .env
├── restaurant-os/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── scanner/
│   ├── __init__.py
│   ├── apps.py
│   ├── urls.py
│   ├── views.py
│   ├── serializers.py
│   ├── preprocessing/
│   │   └── __init__.py
│   ├── scanning/
│   │   └── __init__.py
│   ├── memory/
│   │   └── __init__.py
│   └── tracking/
│       └── __init__.py
├── data/
│   ├── general/
│   │   ├── industry_profile.json
│   │   └── item_catalog.json
│   ├── suppliers/
│   │   └── index.json
│   └── stats/
│       ├── accuracy.json
│       └── api_usage.json
└── tests/
    ├── __init__.py
    ├── fixtures/
    ├── expected/
    └── test_api.py
```

---

### Task 1: Create backend directory and requirements.txt

**Files:**
- Create: `backend/requirements.txt`

- [ ] **Step 1: Create the backend directory**

```bash
mkdir -p backend
```

- [ ] **Step 2: Write requirements.txt**

```
django>=5.0,<6.0
djangorestframework>=3.15,<4.0
django-cors-headers>=4.3,<5.0
python-dotenv>=1.0,<2.0
anthropic>=0.39,<1.0
Pillow>=10.0,<11.0
opencv-python-headless>=4.9,<5.0
pytesseract>=0.3.10,<1.0
pytest>=8.0,<9.0
pytest-django>=4.8,<5.0
```

- [ ] **Step 3: Install dependencies**

Run: `cd backend && pip install -r requirements.txt`
Expected: All packages install successfully, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat(phase-01): add backend requirements.txt with all dependencies"
```

---

### Task 2: Create Django project and scanner app

**Files:**
- Create: `backend/manage.py`
- Create: `backend/restaurant-os/__init__.py`
- Create: `backend/restaurant-os/settings.py`
- Create: `backend/restaurant-os/urls.py`
- Create: `backend/restaurant-os/wsgi.py`
- Create: `backend/scanner/__init__.py`
- Create: `backend/scanner/apps.py`

- [ ] **Step 1: Create Django project**

Run from the `backend/` directory:
```bash
cd backend && django-admin startproject restaurant-os .
```
Expected: Creates `manage.py` and `restaurant-os/` directory with settings, urls, wsgi.

- [ ] **Step 2: Create scanner app**

```bash
cd backend && python manage.py startapp scanner
```
Expected: Creates `scanner/` directory with models.py, views.py, apps.py, etc.

- [ ] **Step 3: Verify Django starts**

Run: `cd backend && python manage.py runserver 0.0.0.0:8000`
Expected: "Starting development server at http://0.0.0.0:8000/" with no errors. Stop with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
git add backend/manage.py backend/restaurant-os/ backend/scanner/
git commit -m "feat(phase-01): create Django project and scanner app"
```

---

### Task 3: Create .env and configure settings.py

**Files:**
- Create: `backend/.env`
- Modify: `backend/restaurant-os/settings.py`

- [ ] **Step 1: Create .env file**

```
ANTHROPIC_API_KEY=your-api-key-here
DJANGO_SECRET_KEY=change-me-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173
```

- [ ] **Step 2: Update settings.py**

Replace the entire content of `backend/restaurant-os/settings.py` with:

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me")

DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "scanner",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "restaurant-os.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "restaurant-os.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
]

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Data directory for supplier memory and stats
DATA_DIR = BASE_DIR / "data"

# File upload limits (10MB max)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
```

- [ ] **Step 3: Verify Django starts with new settings**

Run: `cd backend && python manage.py runserver 0.0.0.0:8000`
Expected: Server starts without errors. Stop with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
git add backend/.env backend/restaurant-os/settings.py
git commit -m "feat(phase-01): configure settings with DRF, CORS, env loading"
```

---

### Task 4: Update .gitignore

**Files:**
- Modify: `.gitignore` (root level)

- [ ] **Step 1: Write .gitignore**

Create or update the root `.gitignore`:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
dist/
build/
*.egg
.eggs/

# Virtual environment
venv/
.venv/
env/

# Django
*.log
db.sqlite3
db.sqlite3-journal

# Environment
.env
.env.local
.env.production

# Data directory (persistent storage, not code)
backend/data/general/*.json
backend/data/suppliers/
backend/data/stats/*.json
!backend/data/general/.gitkeep
!backend/data/suppliers/.gitkeep
!backend/data/stats/.gitkeep

# Node
node_modules/
frontend/dist/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Debug/temp
*.tmp
temp/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "feat(phase-01): add comprehensive .gitignore"
```

---

### Task 5: Create subpackage directories

**Files:**
- Create: `backend/scanner/preprocessing/__init__.py`
- Create: `backend/scanner/scanning/__init__.py`
- Create: `backend/scanner/memory/__init__.py`
- Create: `backend/scanner/tracking/__init__.py`

- [ ] **Step 1: Create all subpackage directories with __init__.py**

```bash
mkdir -p backend/scanner/preprocessing
mkdir -p backend/scanner/scanning
mkdir -p backend/scanner/memory
mkdir -p backend/scanner/tracking
```

Create each `__init__.py` as an empty file:
- `backend/scanner/preprocessing/__init__.py`
- `backend/scanner/scanning/__init__.py`
- `backend/scanner/memory/__init__.py`
- `backend/scanner/tracking/__init__.py`

- [ ] **Step 2: Verify imports work**

Run: `cd backend && python -c "import scanner.preprocessing; import scanner.scanning; import scanner.memory; import scanner.tracking; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Commit**

```bash
git add backend/scanner/preprocessing/ backend/scanner/scanning/ backend/scanner/memory/ backend/scanner/tracking/
git commit -m "feat(phase-01): create scanner subpackages"
```

---

### Task 6: Create data directory structure

**Files:**
- Create: `backend/data/general/industry_profile.json`
- Create: `backend/data/general/item_catalog.json`
- Create: `backend/data/suppliers/index.json`
- Create: `backend/data/stats/accuracy.json`
- Create: `backend/data/stats/api_usage.json`
- Create: `backend/data/general/.gitkeep`
- Create: `backend/data/suppliers/.gitkeep`
- Create: `backend/data/stats/.gitkeep`

- [ ] **Step 1: Create directories**

```bash
mkdir -p backend/data/general
mkdir -p backend/data/suppliers
mkdir -p backend/data/stats
```

- [ ] **Step 2: Create initial JSON files**

`backend/data/general/industry_profile.json`:
```json
{
  "common_tax_rates": [],
  "common_items": [],
  "format_patterns": []
}
```

`backend/data/general/item_catalog.json`:
```json
{
  "items": {}
}
```

`backend/data/suppliers/index.json`:
```json
{
  "suppliers": {}
}
```

`backend/data/stats/accuracy.json`:
```json
{
  "scans": [],
  "by_supplier": {},
  "by_mode": {
    "light": {"total_fields": 0, "corrections": 0},
    "normal": {"total_fields": 0, "corrections": 0},
    "heavy": {"total_fields": 0, "corrections": 0}
  }
}
```

`backend/data/stats/api_usage.json`:
```json
{
  "total": {"sonnet": 0, "opus": 0},
  "by_mode": {
    "light": {"sonnet": 0, "opus": 0},
    "normal": {"sonnet": 0, "opus": 0},
    "heavy": {"sonnet": 0, "opus": 0}
  }
}
```

- [ ] **Step 3: Create .gitkeep files**

Create empty `.gitkeep` files in each data subdirectory so git tracks the directories even though JSON files are gitignored:
- `backend/data/general/.gitkeep`
- `backend/data/suppliers/.gitkeep`
- `backend/data/stats/.gitkeep`

- [ ] **Step 4: Commit**

```bash
git add backend/data/
git commit -m "feat(phase-01): create data directory structure with initial JSON"
```

---

### Task 7: Write the failing test for the scan API endpoint

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_api.py`
- Create: `backend/pytest.ini`

- [ ] **Step 1: Create pytest.ini**

`backend/pytest.ini`:
```ini
[pytest]
DJANGO_SETTINGS_MODULE = restaurant-os.settings
python_files = tests/test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 2: Create tests/__init__.py**

Empty file: `backend/tests/__init__.py`

- [ ] **Step 3: Write the failing test**

`backend/tests/test_api.py`:
```python
import io
from django.test import TestCase
from rest_framework.test import APIClient
from PIL import Image


class TestScanEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _create_test_image(self):
        """Create a minimal valid PNG image for testing."""
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "test_receipt.png"
        return buf

    def test_scan_endpoint_returns_200(self):
        image = self._create_test_image()
        response = self.client.post(
            "/api/scan/",
            {"image": image, "mode": "normal"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)

    def test_scan_endpoint_returns_expected_json_structure(self):
        image = self._create_test_image()
        response = self.client.post(
            "/api/scan/",
            {"image": image, "mode": "normal"},
            format="multipart",
        )
        data = response.json()
        self.assertIn("supplier", data)
        self.assertIn("date", data)
        self.assertIn("invoice_number", data)
        self.assertIn("items", data)
        self.assertIn("subtotal", data)
        self.assertIn("tax", data)
        self.assertIn("total", data)
        self.assertIn("confidence", data)
        self.assertIn("inference_sources", data)
        self.assertIn("scan_metadata", data)

    def test_scan_metadata_contains_mode(self):
        image = self._create_test_image()
        response = self.client.post(
            "/api/scan/",
            {"image": image, "mode": "heavy"},
            format="multipart",
        )
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "heavy")

    def test_scan_endpoint_rejects_no_image(self):
        response = self.client.post(
            "/api/scan/",
            {"mode": "normal"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_scan_endpoint_rejects_invalid_mode(self):
        image = self._create_test_image()
        response = self.client.post(
            "/api/scan/",
            {"image": image, "mode": "turbo"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_scan_endpoint_defaults_mode_to_normal(self):
        image = self._create_test_image()
        response = self.client.post(
            "/api/scan/",
            {"image": image},
            format="multipart",
        )
        data = response.json()
        self.assertEqual(data["scan_metadata"]["mode"], "normal")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: All 6 tests FAIL (URL not found / 404).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/ backend/pytest.ini
git commit -m "test(phase-01): add failing tests for scan API endpoint"
```

---

### Task 8: Implement scan API endpoint

**Files:**
- Create: `backend/scanner/urls.py`
- Create: `backend/scanner/serializers.py`
- Modify: `backend/scanner/views.py`
- Modify: `backend/restaurant-os/urls.py`

- [ ] **Step 1: Create scanner/serializers.py**

```python
from rest_framework import serializers

VALID_MODES = ("light", "normal", "heavy")


class ScanRequestSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)
    mode = serializers.ChoiceField(
        choices=VALID_MODES,
        default="normal",
        required=False,
    )
```

- [ ] **Step 2: Create scanner/views.py**

```python
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status

from scanner.serializers import ScanRequestSerializer


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def scan_invoice(request):
    serializer = ScanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mode = serializer.validated_data.get("mode", "normal")

    # Placeholder response matching spec output format
    placeholder_result = {
        "supplier": "Placeholder Supplier",
        "date": "2026-01-01",
        "invoice_number": "INV-0000",
        "items": [
            {
                "name": "Sample Item",
                "qty": 1,
                "unit": "ea",
                "price": 0.00,
            }
        ],
        "subtotal": 0.00,
        "tax": 0.00,
        "total": 0.00,
        "confidence": {
            "supplier": 0,
            "date": 0,
            "invoice_number": 0,
            "items.0.name": 0,
            "items.0.qty": 0,
            "items.0.price": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
        },
        "inference_sources": {},
        "scan_metadata": {
            "mode": mode,
            "scan_passes": 0,
            "tiebreaker_triggered": False,
            "math_validation_triggered": False,
            "api_calls": {
                "sonnet": 0,
                "opus": 0,
            },
        },
    }

    return Response(placeholder_result)
```

- [ ] **Step 3: Create scanner/urls.py**

```python
from django.urls import path
from scanner.views import scan_invoice

urlpatterns = [
    path("scan/", scan_invoice, name="scan-invoice"),
]
```

- [ ] **Step 4: Update restaurant-os/urls.py**

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("scanner.urls")),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 6: Verify server starts and endpoint works manually**

Run: `cd backend && python manage.py runserver 0.0.0.0:8000`
Then in another terminal:
```bash
curl -X POST http://localhost:8000/api/scan/ -F "image=@some_test_image.png" -F "mode=normal"
```
Expected: Returns JSON with placeholder data and `"mode": "normal"`.

- [ ] **Step 7: Commit**

```bash
git add backend/scanner/serializers.py backend/scanner/views.py backend/scanner/urls.py backend/restaurant-os/urls.py
git commit -m "feat(phase-01): implement placeholder scan API endpoint"
```

---

### Task 9: Security scan

- [ ] **Step 1: Review code for security issues**

Check each item:
- [x] `.env` is in `.gitignore` — API key won't be committed
- [x] `CORS_ALLOWED_ORIGINS` restricts to React dev server only
- [x] `DATA_UPLOAD_MAX_MEMORY_SIZE` limits file uploads to 10MB
- [x] `ScanRequestSerializer` validates image field (Django validates file type)
- [x] `mode` field uses `ChoiceField` — only accepts `light`/`normal`/`heavy`
- [x] No raw SQL or shell commands
- [x] CSRF middleware enabled
- [x] `DEBUG` loaded from env, defaults to `False`
- [x] `SECRET_KEY` loaded from env

- [ ] **Step 2: Run pip audit**

Run: `cd backend && pip install pip-audit && pip-audit`
Expected: No known vulnerabilities (or only informational). Fix any critical/high findings.

- [ ] **Step 3: Commit any security fixes**

If any fixes were needed:
```bash
git add -A
git commit -m "security(phase-01): fix issues found during security scan"
```

---

### Task 10: Final push and tracker update

- [ ] **Step 1: Push all commits to GitHub**

```bash
git push origin master
```

- [ ] **Step 2: Update the implementation tracker in the spec**

In `docs/superpowers/specs/2026-03-26-restaurant-os-design.md`, change:
```
Phase 01:  [ ] Not started — Backend scaffolding (Django REST)
```
to:
```
Phase 01:  [x] Complete — Backend scaffolding (Django REST)
  - Django 5.x + DRF + CORS configured
  - Scanner app with preprocessing/, scanning/, memory/, tracking/ subpackages
  - Placeholder POST /api/scan/ endpoint with validation
  - Data directory structure with initial JSON files
  - 6 passing tests for scan endpoint
  - Security scan: passed
```

- [ ] **Step 3: Commit and push tracker update**

```bash
git add docs/superpowers/specs/2026-03-26-restaurant-os-design.md
git commit -m "docs(phase-01): update implementation tracker — phase 01 complete"
git push origin master
```
