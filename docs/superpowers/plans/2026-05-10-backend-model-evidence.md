# Backend Model Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-only model evidence helpers for 7/14-day rolling stress scores and p90 versus p95 optimization tradeoff.

**Architecture:** Keep the Streamlit UI unchanged. Extend the forecasting module with reusable stress-window backtests built on the existing monthly-planning backtest logic, and extend the optimization module with explicit MD-risk basis selection so downstream UI/reporting can compare balanced p90 and conservative p95 planning.

**Tech Stack:** Python, pandas, unittest.

---

### Task 1: 7/14-Day Stress Score Helper

**Files:**
- Modify: `tests/test_forecasting.py`
- Modify: `trex_energy/forecasting.py`

- [x] **Step 1: Write failing test**

Add a test for `backtest_md_stress_windows(frame, window_days=(7, 14))` asserting it returns one row per window with folds, p50/p90/p95 MD errors, p90/p95 coverage, and p90/p95 bias.

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting.ForecastingTests.test_md_stress_windows_report_7_and_14_day_scores
```

Expected: import error because the helper does not exist.

- [x] **Step 3: Implement helper**

Add `backtest_md_stress_windows(...)` to `trex_energy.forecasting`, reusing `backtest_monthly_planning_profile(...)` with shorter horizons.

### Task 2: p90 Versus p95 Optimization Basis

**Files:**
- Modify: `tests/test_optimization.py`
- Modify: `trex_energy/optimization.py`

- [x] **Step 1: Write failing tests**

Add tests for `OptimizationConfig(md_risk_basis="p90")`, `OptimizationConfig(md_risk_basis="p95")`, and `evaluate_risk_basis_tradeoff(...)`.

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_optimization.OptimizationTests.test_optimization_can_select_p90_or_p95_md_risk_basis
```

Expected: constructor/helper error because the basis API does not exist.

- [x] **Step 3: Implement basis selection**

Add `md_risk_basis` to `OptimizationConfig`, select the correct baseline column in `_base_profile`, and add `evaluate_risk_basis_tradeoff(...)` returning best scenario rows for each requested basis.

### Task 3: Docs And Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] **Step 1: Update docs**

Record the backend-only model evidence additions and clarify that UI surfacing is deferred.

- [x] **Step 2: Verify**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting tests.test_optimization
.\.venv312\Scripts\python.exe -m unittest discover
```
