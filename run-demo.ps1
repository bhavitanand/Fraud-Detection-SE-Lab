# Windows PowerShell: set up and start the whole app on http://127.0.0.1:8000
# Prerequisites: Python 3.11+, Node 20+. See docs/SETUP.md for details.
# Optional no-login demo (only on a machine you alone use): $env:FRAUD_AUTH_REQUIRED="false"
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt
if (-not (Test-Path frontend\dist\index.html)) { Push-Location frontend; npm install; npm run build; Pop-Location }
if ((-not (Test-Path fraud_demo.sqlite)) -and ($env:FRAUD_AUTH_REQUIRED -ne "false")) {
  Write-Host "First run: create your administrator account (password min 10 characters)."
  $email = Read-Host "E-mail"; $name = Read-Host "Name"
  .\.venv\Scripts\python -m app.cli create-user --email $email --name $name --role admin
}
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
