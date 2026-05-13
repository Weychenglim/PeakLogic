# React FastAPI Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit dashboard with the generated React frontend wired to a local FastAPI backend.

**Architecture:** Keep `trex_energy/` as the analytical core. Add a FastAPI API layer that calls the existing ingestion, validation, forecasting, optimization, and reporting functions. Refactor `kinetic-precision` so each page renders one shared analysis state returned by the API.

**Tech Stack:** Python, FastAPI, pandas, openpyxl, Vite, React, TypeScript, Recharts, Tailwind CSS.

---

## File Map

- Create `api.py`: FastAPI app, local CORS setup, upload handling, bundled-site analysis, response serialization.
- Create `tests/test_api.py`: API smoke tests using FastAPI `TestClient`.
- Modify `pyproject.toml`: add `fastapi`, `uvicorn`, and `python-multipart`.
- Modify `kinetic-precision/src/lib/api.ts`: typed frontend API client.
- Modify `kinetic-precision/src/App.tsx`: own active analysis state and pass it to pages.
- Modify `kinetic-precision/src/constants.ts`: use real bundled site ids instead of generic mock sites.
- Modify `kinetic-precision/src/components/*.tsx`: replace hardcoded mock content with props from the current analysis.
- Modify project docs: record React/FastAPI migration and defer Supabase.

## Tasks

### Task 1: API Smoke Contract

**Files:**
- Create: `tests/test_api.py`
- Create: `api.py`
- Modify: `pyproject.toml`

- [ ] Add tests for `GET /api/health`, `GET /api/bundled-sites`, `POST /api/analyze/bundled`, and `POST /api/analyze/upload`.
- [ ] Add FastAPI dependencies to `pyproject.toml`.
- [ ] Implement `api.py` using existing `trex_energy` functions.
- [ ] Run `python -m unittest tests.test_api`.

### Task 2: Frontend API Client And State

**Files:**
- Create: `kinetic-precision/src/lib/api.ts`
- Modify: `kinetic-precision/src/App.tsx`
- Modify: `kinetic-precision/src/constants.ts`
- Modify: `kinetic-precision/src/components/TopAppBar.tsx`

- [ ] Add TypeScript types matching the API response.
- [ ] Load bundled-site choices from the API.
- [ ] Store the current analysis in `App.tsx`.
- [ ] Wire site selection to `POST /api/analyze/bundled`.

### Task 3: Upload And Analysis Pages

**Files:**
- Modify: `kinetic-precision/src/components/DataUpload.tsx`
- Modify: `kinetic-precision/src/components/SiteProfile.tsx`
- Modify: `kinetic-precision/src/components/ForecastRisk.tsx`
- Modify: `kinetic-precision/src/components/Optimization.tsx`
- Modify: `kinetic-precision/src/components/ExecutiveSummary.tsx`

- [ ] Replace static upload preview with a real file input.
- [ ] Render validation warnings and normalized preview from API results.
- [ ] Render profile, forecast, optimization, and summary cards from the current analysis.
- [ ] Remove fake live/dynamic claims that are not backed by API data.

### Task 4: Docs And Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [ ] Record that the dashboard layer is migrating from Streamlit to React/FastAPI.
- [ ] Record that Supabase is deferred until after local wiring works.
- [ ] Run backend unit tests.
- [ ] Install frontend dependencies if needed and run `npm.cmd run lint` and `npm.cmd run build`.

## Self-Review

The plan covers the approved Phase 1 scope: local React UI, FastAPI API layer, no database, real backend data, and documentation updates. Supabase is explicitly out of scope for this implementation plan and remains a follow-up after the local demo is stable.
