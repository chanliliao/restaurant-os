# Activate Virtual Environment

Run the following to activate the Restaurant OS backend virtual environment and confirm it is working:

```bash
source backend/venv/Scripts/activate && python --version && python -c "import django; print('Django', django.__version__)"
```

Expected output: Python version line followed by `Django 5.x.x`.

If activation fails, check that `backend/venv/` exists. If not, run:
```bash
cd backend && python -m venv venv && source venv/Scripts/activate && pip install -r requirements.txt
```
