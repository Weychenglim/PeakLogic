# Monthly MD Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the app from a next-day forecast demo to a 1-3 month MD planning simulator.

**Architecture:** Keep the existing Ridge forecast path for short-horizon backtesting, but add a separate planning forecast based on recent weekday/weekend interval shapes. Feed the monthly planning profile into the existing deterministic optimizer with optional MD-risk envelope input and 30-day MD billing periods.

**Tech Stack:** Python, pandas, scikit-learn, Streamlit, openpyxl, unittest.

---

### Task 1: Canonical Unit Handling

**Files:**
- Modify: `trex_energy/ingestion.py`
- Test: `tests/test_ingestion.py`

- [x] **Step 1: Write the failing test**

Add `test_interval_energy_columns_are_converted_to_canonical_kw`, creating a workbook with `kwh_export` and `kwh_import` interval-energy headers.

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest tests.test_ingestion.DatasetIngestionTests.test_interval_energy_columns_are_converted_to_canonical_kw
```

Expected before implementation: error or failure because interval-energy headers are not converted to kW.

- [x] **Step 3: Implement minimal parser support**

Detect `kWh` active import/export headers or accept `active_power_unit="kwh_per_interval"` and convert values to canonical kW with `kW = kWh / interval_hours`.

- [x] **Step 4: Verify green**

Run the same focused test and expect `OK`.

### Task 2: Monthly Planning Forecast

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `app.py`
- Test: `tests/test_forecasting.py`

- [x] **Step 1: Write the failing test**

Add `test_monthly_planning_forecast_returns_30_day_blocks_without_recursive_modeling`.

- [x] **Step 2: Run test to verify it fails**

Expected before implementation: `forecast_monthly_planning_profile` cannot be imported.

- [x] **Step 3: Implement pattern simulation**

Add `forecast_monthly_planning_profile(...)` that returns `months * 1440` rows for 1-3 months, using recent weekday/weekend and half-hour slot medians plus a high-quantile MD-risk envelope.

- [x] **Step 4: Wire Streamlit controls**

Add planning-window, growth, EV-load, and envelope-optimization controls to the forecast section.

### Task 3: Monthly MD Billing And Optimization

**Files:**
- Modify: `trex_energy/tariff.py`
- Modify: `trex_energy/optimization.py`
- Test: `tests/test_optimization.py`

- [x] **Step 1: Write failing tests**

Add tests for 30-day MD period charging, sine solar profile, and optional envelope-based optimization input.

- [x] **Step 2: Implement billing and optimizer changes**

Add `TariffConfig.md_period_intervals`, sum MD charges over each 30-day planning period, expose `clear_sky_sine_solar_factor`, and let `OptimizationConfig.use_md_risk_envelope` choose `md_risk_envelope_kw` as the baseline profile when available.

- [x] **Step 3: Verify focused tests**

Run the five new focused tests and expect `OK`.

### Task 4: Documentation And Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [x] **Step 1: Update docs**

Record the new monthly MD planning scope, unit semantics, planning forecast architecture, and current implementation status.

- [x] **Step 2: Run focused verification**

Run:

```bash
.\.venv312\Scripts\python.exe -m unittest tests.test_ingestion tests.test_forecasting tests.test_optimization tests.test_reporting
```

Expected: all core app tests pass.
