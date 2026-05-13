# Adaptive P90 Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the current p90 planning model with backend adaptive calibration selected from 7-day and 14-day stress-window validation.

**Architecture:** Keep the current recent-pattern statistical planner. Add candidate search over `recent_days` and `p90_floor_multiplier`, score each candidate on stress-window MD coverage, MD absolute error, and overprediction bias, then expose the best configuration for future forecasting/UI use.

**Tech Stack:** Python, pandas, numpy, unittest.

---

### Task 1: Planner Parameter Plumbing

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `tests/test_forecasting.py`

- [x] **Step 1: Add failing test**

Add a test that calls `backtest_monthly_planning_profile(..., recent_days=21, p90_floor_multiplier=1.08)` and asserts the returned predictions include `recent_days`, `p90_floor_multiplier`, and p90 MD output at least as high as actual recent floor where applicable.

- [x] **Step 2: Verify RED**

Run the focused test and expect a keyword-argument error.

- [x] **Step 3: Implement parameter plumbing**

Pass `recent_days`, `p90_floor_multiplier`, and `md_floor_multiplier` through `backtest_monthly_planning_profile` and `backtest_md_stress_windows` into `forecast_monthly_planning_profile`.

### Task 2: Adaptive P90 Candidate Search

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `tests/test_forecasting.py`

- [x] **Step 1: Add failing test**

Add tests for:

```python
evaluate_p90_calibration_candidates(...)
fit_adaptive_p90_calibration(...)
```

Assert the candidate table includes coverage/error/bias/score columns and the fitted config has valid `recent_days`, `p90_floor_multiplier`, `stress_coverage_pct`, and `stress_md_abs_error_kw`.

- [x] **Step 2: Verify RED**

Run the focused tests and expect import errors.

- [x] **Step 3: Implement adaptive selector**

Use 7/14-day stress-window scores. Ranking should prefer candidates that meet target coverage, then lower MD absolute error, then lower positive bias.

### Task 3: Docs And Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] **Step 1: Update docs**

Record that p90 can now be adaptively selected from stress-window calibration candidates.

- [x] **Step 2: Verify**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting
.\.venv312\Scripts\python.exe -m unittest discover
```
