# Run Tests

Run the full Restaurant OS test suite:

```bash
cd backend && python -m pytest -v 2>&1
```

- Zero failures required before any commit or push.
- All GLM API calls are mocked — tests do not hit real endpoints.
- To run a single test file: `cd backend && python -m pytest tests/test_scanning.py -v`
- To run a single test: `cd backend && python -m pytest tests/test_scanning.py::TestClass::test_name -v`
- To filter by keyword: `cd backend && python -m pytest -k "test_ocr_fast_path" -v`

`pytest.ini` sets `DJANGO_SETTINGS_MODULE = restaurant-os.settings` — no env var needed.
