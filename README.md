# PeakLogic

PeakLogic is a React + FastAPI decision-support application for commercial energy demand planning, forecasting, and optimization. It analyzes historical site load data, identifies maximum-demand risk, compares load shifting, battery, and solar options, and presents cost-saving recommendations through an interactive dashboard.

## Project Description

PeakLogic helps users turn site electricity load workbooks into practical planning decisions. The backend reads bundled or uploaded Excel files, normalizes interval data, validates data quality, forecasts future demand, identifies high-risk maximum-demand windows, and simulates optimization options such as operational load shifting, battery dispatch, and solar sizing.

The frontend presents those results as an interactive dashboard with site profiles, forecast and risk views, optimization recommendations, financial assumptions, and export-ready analysis outputs. The app is designed to help users compare current operating costs against optimized scenarios and understand which actions can reduce demand charges and overall electricity cost.

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

## Supabase Setup

Create a Supabase project and copy these values into the frontend environment file at `kinetic-precision/.env.local` (not committed):

```
VITE_SUPABASE_URL=your_project_url
VITE_SUPABASE_ANON_KEY=your_anon_key
```

Create the cache table in Supabase (SQL editor):

```sql
create table if not exists analysis_cache (
	id uuid primary key default gen_random_uuid(),
	user_id uuid not null,
	cache_key text not null unique,
	source_file text,
	dataset_signature text,
	assumptions jsonb,
	analysis jsonb,
	created_at timestamptz not null default now(),
	updated_at timestamptz not null default now()
);

alter table analysis_cache enable row level security;

create policy "analysis_cache_select" on analysis_cache
	for select using (auth.uid() = user_id);

create policy "analysis_cache_insert" on analysis_cache
	for insert with check (auth.uid() = user_id);

create policy "analysis_cache_update" on analysis_cache
	for update using (auth.uid() = user_id);
```

Supabase Auth should have Email/Password enabled for the login UI.

## Current Forecast Path

The main API uses the stable monthly planning forecast for the user-facing app. ML candidates remain in the backend for model development and validation, but model benchmark details are not shown in the UI.
