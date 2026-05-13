# MD Risk Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight trained MD-risk calibration layer that improves monthly envelope reliability while preserving the current statistical monthly planner.

**Architecture:** Keep `forecast_monthly_planning_profile` as the production planning backbone. Train a simple, explainable calibration model from rolling historical monthly-planning folds, then apply the learned p95 uplift to the future monthly planning profile so `md_risk_envelope_kw` reflects both recent-pattern statistics and learned historical MD miss behavior.

**Tech Stack:** Python, pandas, numpy, scikit-learn linear regression, Streamlit, unittest.

---

### Task 1: Calibration API And Tests

**Files:**
- Modify: `tests/test_forecasting.py`
- Modify: `trex_energy/forecasting.py`

- [x] **Step 1: Write the failing tests**

Add tests that call a new `fit_monthly_md_risk_calibrator(frame)` helper and assert:

```python
calibrator.uplift_factor >= 1.0
calibrator.training_folds >= 1
calibrated_forecast["md_risk_envelope_kw"].max() >= raw_forecast["md_risk_envelope_kw"].max()
calibrated_forecast["md_risk_calibration_method"].iloc[0] == "trained_monthly_md_risk_calibrator"
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting.ForecastingTests.test_monthly_md_risk_calibrator_raises_undercovered_envelope
```

Expected: fail because the calibration helper does not exist yet.

- [x] **Step 3: Implement the minimal calibration API**

Add:

```python
@dataclass(frozen=True)
class MonthlyMDRiskCalibrator:
    uplift_factor: float
    intercept_kw: float
    training_folds: int
    coverage_before_pct: float
    coverage_after_pct: float
```

Add:

```python
def fit_monthly_md_risk_calibrator(frame, train_days=21, horizon_days=30, step_days=15, max_folds=4)
def apply_monthly_md_risk_calibration(forecast, calibrator)
```

- [x] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting
```

Expected: all forecasting tests pass.

### Task 2: App Wiring

**Files:**
- Modify: `app.py`
- Modify: `tests/test_forecasting.py`

- [x] **Step 1: Add optional app calibration**

In `_render_forecast_section`, fit the calibrator after creating the monthly forecast. If the frame has enough history, apply it and display a concise calibration caption. If there is not enough history, keep the uncalibrated statistical envelope.

- [x] **Step 2: Preserve fallback behavior**

No upload should fail because calibration cannot fit. The app should catch `ValueError` from insufficient data and continue with the statistical planner.

### Task 3: Documentation And Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] **Step 1: Update docs**

Record that the production app is now hybrid: statistical monthly pattern planning plus a trained historical MD-risk calibration layer.

- [x] **Step 2: Run verification**

Run:

```powershell
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting
.\.venv312\Scripts\python.exe -m unittest discover
```

Expected: all tests pass.
