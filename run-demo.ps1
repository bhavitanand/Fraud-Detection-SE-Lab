# Windows PowerShell: build the frontend (once) and start the whole app on http://127.0.0.1:8000
# Prerequisites: Python 3.11+, Node 20+. Set $env:FRAUD_AUTH_REQUIRED="false" first for a no-login local demo.
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path frontend\dist\index.html)) { Push-Location frontend; npm install; npm run build; Pop-Location }
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
