# Backend Optimization Explanation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return backend-generated Optimization explanation, confidence flags, planning-basis labels, and single-analysis sensitivity rows for the active workbook/upload.

**Architecture:** Keep numeric sensitivity in `trex_energy.optimization`, presentation text in `trex_energy.reporting`, and API packaging in `api.py`. Extend React types and render the backend payload in `Optimization.tsx`.

**Tech Stack:** Python, pandas, unittest, FastAPI TestClient, React, TypeScript, Vite.

---

### Task 1: Backend Sensitivity Calculation

**Files:**
- Modify: `tests/test_optimization.py`
- Modify: `trex_energy/optimization.py`

- [ ] **Step 1: Write failing optimizer test**

Add a test that imports `evaluate_assumption_sensitivity`, evaluates a small forecast frame, and asserts labels include `md_rate_plus_10`, `battery_capex_plus_10`, and `solar_capex_minus_10`.

- [ ] **Step 2: Run test and confirm failure**

Run: `python -m unittest tests.test_optimization.OptimizationTests.test_assumption_sensitivity_returns_single_analysis_rows -v`

Expected: import error because the function does not exist.

- [ ] **Step 3: Implement sensitivity helper**

Add `evaluate_assumption_sensitivity(frame, config)` that returns a dataframe with:

```python
{
    "sensitivity_id": "md_rate_plus_10",
    "label": "MD rate +10%",
    "changed_assumption": "md_rate_rm_per_kw",
    "change_pct": 10.0,
    "savings_rm": ...,
    "payback_months": ...,
    "battery_kw": ...,
    "battery_kwh": ...,
    "solar_kwp": ...,
}
```

- [ ] **Step 4: Run optimizer test and confirm pass**

Run the same unittest command and expect success.

### Task 2: Reporting Explanation

**Files:**
- Modify: `tests/test_reporting.py`
- Modify: `trex_energy/reporting.py`

- [ ] **Step 1: Write failing reporting test**

Add a test for `build_optimization_explanation(...)` that asserts the returned dict contains `what_changed`, `why_this_scenario`, `savings_sensitivity`, `confidence_flags`, `planning_basis_label`, and `planning_basis_description`.

- [ ] **Step 2: Run test and confirm failure**

Run: `python -m unittest tests.test_reporting.ReportingTests.test_optimization_explanation_is_judge_facing -v`

Expected: import error because the function does not exist.

- [ ] **Step 3: Implement reporting helper**

Add `build_optimization_explanation(site_id, best_scenario, assumptions, validation, sensitivity)` with deterministic copy and confidence flags.

- [ ] **Step 4: Run reporting test and confirm pass**

Run the same unittest command and expect success.

### Task 3: API Payload and Frontend Contract

**Files:**
- Modify: `tests/test_api.py`
- Modify: `api.py`
- Modify: `kinetic-precision/src/lib/api.ts`
- Modify: `kinetic-precision/src/components/Optimization.contract.test.tsx`
- Modify: `kinetic-precision/src/components/Optimization.tsx`

- [ ] **Step 1: Write failing API and TypeScript contract checks**

Extend `test_bundled_analysis_returns_real_forecast_and_optimization_payload` to assert the response includes `optimization.explanation` and `optimization.sensitivity`.

Extend the TypeScript API contract so `AnalysisResult.optimization` requires the new fields.

- [ ] **Step 2: Run checks and confirm failure**

Run:

```powershell
python -m unittest tests.test_api.ApiTests.test_bundled_analysis_returns_real_forecast_and_optimization_payload -v
npm.cmd run lint
```

Expected: API test fails before packaging the fields.

- [ ] **Step 3: Package backend fields and render frontend fields**

In `api.py`, call the new sensitivity and explanation helpers and include them under the optimization payload.

In React, render backend explanation text and sensitivity rows when present, with fallback to existing copy.

- [ ] **Step 4: Run API and TypeScript checks**

Run the same commands and expect success.

### Task 4: Documentation and Final Verification

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/requirements.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [ ] **Step 1: Update docs**

Record backend explanation and active-analysis sensitivity.

- [ ] **Step 2: Run full verification**

Run:

```powershell
python -m unittest tests.test_optimization tests.test_reporting tests.test_api -v
npm.cmd run lint
npm.cmd run build
```

Expected: Python tests, TypeScript check, and Vite build exit with code 0. The known Vite large-bundle warning may remain.

