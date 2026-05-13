# Monthly Probabilistic Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-backed monthly MD planning by producing calibrated p50/p90/p95 planning profiles and a monthly rolling backtest harness.

**Architecture:** Extend the existing recent-pattern monthly simulator in `trex_energy/forecasting.py` instead of promoting another recursive ML model. Keep `forecast_kw_import` as the expected/p50 profile for compatibility, use `md_risk_envelope_kw` as the p90 conservative planning envelope, add `p95_stress_kw` for stress testing, and add a backtest function that compares simulated 30-day MD against actual 30-day MD.

**Tech Stack:** Python, pandas, numpy, Streamlit, unittest.

---

### Task 1: Probabilistic Planning Columns

**Files:**
- Modify: `trex_energy/forecasting.py`
- Test: `tests/test_forecasting.py`

- [x] **Step 1: Write the failing test**

Add a test that builds a synthetic 35-day half-hour frame with repeated slot-level spikes and calls:

```python
forecast = forecast_monthly_planning_profile(frame, months=1)
```

Assert these columns exist:

```python
{
    "p50_forecast_kw",
    "p90_md_risk_kw",
    "p95_stress_kw",
    "forecast_kw_import",
    "md_risk_envelope_kw",
}
```

Assert:

```python
(forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all()
(forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all()
(forecast["forecast_kw_import"] == forecast["p50_forecast_kw"]).all()
(forecast["md_risk_envelope_kw"] == forecast["p90_md_risk_kw"]).all()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting.ForecastingTests.test_monthly_planning_forecast_returns_probabilistic_envelopes
```

Expected: fail because the p50/p90/p95 columns do not exist yet.

- [x] **Step 3: Implement minimal planner extension**

In `forecast_monthly_planning_profile`, compute grouped slot quantiles:

```python
p50_kw = values.quantile(0.50)
p90_kw = values.quantile(0.90)
p95_kw = values.quantile(0.95)
```

Apply the existing growth and EV adders to each quantile. Preserve compatibility by setting:

```python
forecast_kw_import = p50_forecast_kw
md_risk_envelope_kw = p90_md_risk_kw
```

- [x] **Step 4: Run test to verify it passes**

Run the same focused test and expect `OK`.

### Task 2: Monthly Backtest Harness

**Files:**
- Modify: `trex_energy/forecasting.py`
- Test: `tests/test_forecasting.py`

- [x] **Step 1: Write the failing test**

Add a test that creates 75 days of synthetic half-hour data with a known higher final-month peak, then calls:

```python
result = backtest_monthly_planning_profile(frame, train_days=45, horizon_days=30, step_days=15)
```

Assert:

```python
result.metrics["folds"] >= 1
"actual_md_kw" in result.predictions.columns
"p90_md_kw" in result.predictions.columns
"p95_coverage" in result.predictions.columns
```

Assert metric keys include:

```python
{
    "p50_md_abs_error_kw",
    "p90_md_abs_error_kw",
    "p95_md_abs_error_kw",
    "p90_coverage_pct",
    "p95_coverage_pct",
}
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting.ForecastingTests.test_monthly_planning_backtest_reports_md_errors_and_coverage
```

Expected: fail because `backtest_monthly_planning_profile` does not exist yet.

- [x] **Step 3: Implement minimal backtest harness**

Add:

```python
@dataclass(frozen=True)
class MonthlyPlanningBacktestResult:
    predictions: pd.DataFrame
    metrics: dict[str, float]
```

Add:

```python
def backtest_monthly_planning_profile(frame, train_days=21, horizon_days=30, step_days=15, max_folds=4):
```

For each cutoff, train on history up to cutoff, generate one-month forecast, align to the actual horizon length, and calculate actual MD versus p50/p90/p95 MD.

- [x] **Step 4: Run test to verify it passes**

Run the same focused test and expect `OK`.

### Task 3: App Surface And Docs

**Files:**
- Modify: `app.py`
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] **Step 1: Show p50/p90/p95 in the monthly forecast chart**

Use `p50_forecast_kw`, `p90_md_risk_kw`, and `p95_stress_kw` when present.

- [x] **Step 2: Add monthly backtest metrics to the forecast section**

Call `backtest_monthly_planning_profile(frame)` and display p50/p90/p95 MD error and p90/p95 coverage when there is enough history.

- [x] **Step 3: Update docs**

Record that monthly planning is now probabilistic and backtested against monthly MD.

### Task 4: Verification

**Files:**
- Test: `tests/test_forecasting.py`
- Test: full unittest discovery

- [x] **Step 1: Run focused forecasting tests**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest tests.test_forecasting
```

Expected: all forecasting tests pass.

- [x] **Step 2: Run full test discovery**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest discover
```

Expected: all tests pass.
