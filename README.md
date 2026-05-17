# Kinetic Precision / TREX Energy App

Local React + FastAPI decision-support demo for TREX maximum-demand planning, forecasting, and optimization.

## Start Locally

Activate the Python environment, then install dependencies once from the repository root:

```powershell
.\.venv312\Scripts\Activate.ps1
```

```powershell
pip install -e .
```

```powershell
cd kinetic-precision
npm install
```

Open two terminals from the repository root.

### Backend (FastAPI)

```powershell
.\.venv312\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health
```

Expected response:

```json
{"status":"ok"}
```

### Frontend (Vite)

```powershell
cd kinetic-precision
npm run dev
```

Open:

```text
http://localhost:3000
```

The frontend calls the API at:

```text
http://localhost:8000
```

## Current Forecast Path

The main API uses the stable monthly planning forecast for the user-facing app. ML candidates remain in the backend for model development and validation, but model benchmark details are not shown in the UI.
