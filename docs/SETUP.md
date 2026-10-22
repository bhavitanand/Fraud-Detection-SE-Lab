# Setup guide — run Fraud Desk locally

Takes about 5 minutes. Works on Windows, macOS and Linux. No Docker, no database server, no internet needed after install.

## 1. Prerequisites
| Tool | Version | Check |
|---|---|---|
| Python | 3.11 or newer | `python --version` (Windows: `py -3 --version`) |
| Node.js + npm | 20 or newer | `node --version` |

You do **not** need `creditcard.csv`. The trained model files ship in `ml/artifacts/`.

## 2. Get the code
Unzip the project and open a terminal in the project folder (the one containing `app/`, `frontend/`, `README.md`).

## 3. Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-ml.txt
cd frontend; npm install; npm run build; cd ..
python -m app.cli create-user --email you@example.com --name "Your Name" --role admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
If PowerShell blocks the activate script: `Set-ExecutionPolicy -Scope Process Bypass`, then retry.

## 3. macOS / Linux
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
(cd frontend && npm install && npm run build)
python -m app.cli create-user --email you@example.com --name "Your Name" --role admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`create-user` asks for a password (minimum 10 characters). The first server start creates `fraud_demo.sqlite` with 129 synthetic transactions, 14 Indian cardholders, 19 merchants, 18 alerts and the trained model.

## 4. Open the app
Go to **http://127.0.0.1:8000** and sign in with the e-mail and password from step 3.
- API docs (Swagger): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health → `"status":"ok"`

## 5. Optional
**Skip sign-in (solo demo only).** Set the variable before starting uvicorn:
- PowerShell: `$env:FRAUD_AUTH_REQUIRED="false"`
- bash: `export FRAUD_AUTH_REQUIRED=false`

**E-mail OTP on login.** `FRAUD_LOGIN_OTP=true`. The 6-digit code is printed in the server terminal (`FRAUD_OTP_DELIVERY=console`). For real e-mail use `FRAUD_OTP_DELIVERY=smtp` plus `FRAUD_SMTP_HOST`, `FRAUD_SMTP_PORT`, `FRAUD_SMTP_USER`, `FRAUD_SMTP_PASSWORD`, `FRAUD_SMTP_FROM` (for Gmail use an app password).

**Reset demo data.** Stop the server, delete `fraud_demo.sqlite`, create the user again, restart.

**Second analyst account.** `python -m app.cli create-user --email analyst@example.com --name "Analyst" --role analyst`

**Retrain the model.** Download `creditcard.csv` (Kaggle: ULB "Credit Card Fraud Detection") into `data/`, then `python -m ml.train --csv data/creditcard.csv --register`, and deploy the new candidate on the ML model page.

**Run the tests.**
```bash
pip install -r requirements-dev.txt
python -m pytest --cov=app
cd frontend && npm test
```

**Developer mode (hot reload).** Terminal 1: `uvicorn app.main:app --reload --port 8000`. Terminal 2: `cd frontend && npm run dev`, then open http://localhost:5173.

## 6. Troubleshooting
| Symptom | Fix |
|---|---|
| Page says "frontend has not been built" | `cd frontend && npm install && npm run build` |
| Cannot sign in / no account | Re-run the `create-user` command, or use `FRAUD_AUTH_REQUIRED=false` |
| `Address already in use` | Another process uses port 8000: use `--port 8001`, or stop the other process |
| ML page says scikit-learn is missing | `pip install -r requirements-ml.txt` (the app still works rules-only) |
| `database is locked` | Two servers share one SQLite file; stop the extra one |
| `python` not found on Windows | Use `py -3` instead of `python` |
| Account locked after wrong passwords | Wait a few minutes, or restart the server (lockout is in memory) |
