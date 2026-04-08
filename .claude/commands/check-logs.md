# Check Logs

To see Django dev server output, run the server in the foreground:

```bash
cd backend && python manage.py runserver 2>&1
```

To check for recent Python tracebacks in the current session output, look for lines starting with `Traceback (most recent call last)`.

To check what GLM API calls were made during a scan, grep the running server output for:
```bash
grep -i "glm\|ocr\|vision\|scan" backend/logs/*.log 2>/dev/null || echo "No log files found — check server stdout"
```

If you need structured logging, `logging.getLogger(__name__)` is used throughout `backend/scanner/`. Log level is set in `backend/smartscanner/settings.py`.
