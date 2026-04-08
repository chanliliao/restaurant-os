# Check Logs

To see Django dev server output, run the server in the foreground:

```bash
cd backend && python manage.py runserver 2>&1
```

To check for recent Python tracebacks in the current session output, look for lines starting with `Traceback (most recent call last)`.

To check what GLM API calls were made during a scan, grep server stdout directly — SmartScanner uses console logging only by default, so log files will not exist unless a `FileHandler` has been added to `LOGGING` in `backend/smartscanner/settings.py`:

```bash
# If you have enabled file-based logging:
grep -i "glm\|ocr\|vision\|scan" backend/logs/*.log 2>/dev/null || echo "No log files — logs go to server stdout by default"
```

`logging.getLogger(__name__)` is used throughout `backend/scanner/`. To enable file logging, add a `FileHandler` to the `LOGGING` dict in `settings.py` pointing to `backend/logs/smartscanner.log`.
