# Gated ML Planning Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only gated ML planning candidate that can safely change p50 while retaining the current strongest ML p90/p95 MD-risk behavior.

**Architecture:** Keep the production API and UI unchanged until validation is accepted. Add `forecast_gated_ml_planning_profile` in `trex_energy.forecasting`; it starts from `forecast_ml_md_risk_profile`, trains p50 residual confidence from rolling historical folds, and only applies bounded p50 corrections to high-confidence intervals. The model raises on short history and never silently falls back to the statistical planner.

**Tech Stack:** Python, pandas, numpy, LightGBM, unittest.

---

### Task 1: Contract Tests

**Files:**
- Modify: `tests/test_forecasting.py`

- [x] Add a failing test that imports `forecast_gated_ml_planning_profile`, returns the monthly planning contract, and uses `planning_method == "gated_ml_planning_gradient_boosting"`.
- [x] Add a failing test that verifies the model exposes `ml_p50_correction_confidence` and `ml_p50_correction_applied`, with corrections bounded to a small subset of intervals.
- [x] Add a failing test that confirms short history raises `ValueError("Not enough history...")`.
- [x] Run the targeted tests and verify they fail because the function does not exist.

### Task 2: Backend Model

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `trex_energy/__init__.py`

- [x] Add a small `GatedP50CorrectionPolicy` dataclass for confidence threshold, correction cap, and active interval quantile.
- [x] Reuse the existing full-ML training rows and p50 residual model.
- [x] Start from `forecast_ml_md_risk_profile` so the current strongest p90/p95 behavior is preserved.
- [x] Apply p50 correction only when residual magnitude and timing confidence pass the policy gate.
- [x] Keep p90 and p95 ordered above corrected p50.
- [x] Export the candidate from `trex_energy/__init__.py`.
- [x] Run targeted tests until green.

### Task 3: Metrics And Acceptance

**Files:**
- Read/execute only.

- [x] Compare statistical planner, hybrid ML MD-risk candidate, full ML candidate, and gated ML candidate on bundled 30-day holdout.
- [x] Accept only if gated ML improves p50 MD without materially worsening RMSE/WAPE and keeps the hybrid p90/p95 gains.
- [x] Keep UI untouched unless the candidate is explicitly accepted.

### Task 4: Documentation And Handoff

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] Document the candidate, metric result, and promotion decision.
- [ ] Run `python -m unittest tests.test_forecasting`.
- [x] Run the API smoke test to verify the app payload still works.
- [ ] Prepare final handoff notes for pushing to GitHub; actual push requires a safe Git repo state plus target remote URL.
