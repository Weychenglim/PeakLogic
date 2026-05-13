# Full ML Planning Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only full ML long-horizon planning candidate that predicts p50, p90, and p95 for 1-3 month planning and compare it against the existing planner candidates.

**Architecture:** Keep the production API on the current statistical planner. Add a new `forecast_full_ml_planning_profile` candidate in `trex_energy.forecasting` that trains LightGBM quantile residual models using historical rolling monthly folds, planner outputs, long-horizon calendar features, and recent site-regime features. The candidate changes p50 as well as p90/p95, but bounds corrections so the experiment is measurable without destabilizing the app path.

**Tech Stack:** Python, pandas, numpy, LightGBM, unittest.

---

### Task 1: Contract Tests

**Files:**
- Modify: `tests/test_forecasting.py`

- [x] Add a failing test that imports `forecast_full_ml_planning_profile`, trains on synthetic target/reference frames, and verifies the monthly planning contract: row count, p50/p90/p95 columns, `planning_method == "full_ml_planning_gradient_boosting"`, nonnegative forecasts, and `p90 >= p50`, `p95 >= p90`.
- [x] Add a failing test that proves the candidate actually changes p50 versus `forecast_monthly_planning_profile`, so it is not just the existing statistical planner or the MD-risk-only candidate.
- [x] Add a failing short-history test that raises `ValueError("Not enough history...")` instead of silently falling back.
- [x] Run the three targeted tests and confirm they fail because the function is missing.

### Task 2: Backend Candidate

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `trex_energy/__init__.py`

- [x] Add feature builder helpers that combine `_correction_feature_row` planner-aware features with recent peak-regime features from `_md_risk_model_features`.
- [x] Add rolling monthly training-row builder with targets for p50, p90, and p95 residuals.
- [x] Fit LightGBM quantile residual models for p50, p90, and p95.
- [x] Add `forecast_full_ml_planning_profile(...)` with explicit 1-3 month validation, no silent fallback, bounded p50 correction, p90/p95 ordering, existing growth/EV assumptions, and existing peak-risk overlay.
- [x] Export the candidate from `trex_energy/__init__.py`.
- [x] Run targeted tests until green.

### Task 3: Documentation

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] Document that the new candidate is backend-only, model-development only, and not exposed in the UI.
- [x] Record the no-silent-fallback rule for this candidate.
- [x] After metric inspection, record whether the candidate beats the current statistical planner or remains rejected/deferred.

### Task 4: Verification And Metrics

**Files:**
- Read/execute only.

- [x] Run `python -m unittest tests.test_forecasting` after implementation.
- [x] Run the API smoke test that ensures production still uses the existing user-facing payload.
- [x] Run a bundled-workbook holdout inspection for statistical planner, hybrid ML-risk candidate, and full ML planning candidate.
- [x] Report RMSE, WAPE, p50 MD absolute error, p90 MD absolute error, p95 MD absolute error, p90/p95 coverage, and concise acceptance decision.
