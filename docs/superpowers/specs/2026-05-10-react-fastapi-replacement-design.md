# React FastAPI Replacement Design

## Goal

Replace the Streamlit UI with the generated `kinetic-precision` React frontend while preserving the existing `trex_energy` Python package as the source of truth for ingestion, forecasting, optimization, and reporting.

## Scope

Phase 1 is local-demo only. Uploaded workbooks are processed during the request and are not persisted. The frontend renders real backend results instead of static mock data. Supabase is deferred until the local React plus Python API workflow works end to end.

## Architecture

The app becomes:

`React/Vite frontend -> FastAPI backend -> trex_energy package -> JSON/CSV responses`

The existing Streamlit `app.py` is retired from the main user flow. Backend logic stays in importable modules so forecasting and optimization tests continue to protect the model behavior.

## Backend API

Create a FastAPI entry point that exposes:

- `GET /api/health` for dev-server checks.
- `GET /api/bundled-sites` for the four bundled workbook options.
- `POST /api/analyze/bundled` to analyze one bundled workbook.
- `POST /api/analyze/upload` to analyze an uploaded `.xlsx` workbook.

Each analysis response includes site metadata, validation summary, profile metrics, forecast preview, optimization summary, executive text, and CSV export payloads where practical.

## Frontend

Refactor `kinetic-precision` from a static mock dashboard into a stateful local app:

- `App.tsx` owns the current analysis state.
- `DataUpload` uploads a workbook or selects a bundled dataset.
- `SiteProfile`, `ForecastRisk`, `Optimization`, and `ExecutiveSummary` render the current analysis.
- Static fake names, fake live claims, fake timestamps, and fake monetary values are replaced by backend-derived values or honest empty states.

## Database Decision

No database is used in Phase 1. Supabase should be added only after the local app is stable and the team wants saved analyses, user accounts, shared projects, or persisted uploads/results.

## Testing

Add API-level tests for health, bundled-site listing, bundled analysis, and upload analysis. Keep existing package tests. Run frontend type/build checks after installing frontend dependencies.

## Documentation

Update `PROJECT_REQUIREMENTS.md`, `ARCHITECTURE_AND_CODING_DESIGN.md`, `PROJECT_STATUS.md`, and the canonical docs under `docs/` to record the UI replacement and Supabase deferral.
