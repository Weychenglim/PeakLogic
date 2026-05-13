# Direct-Horizon Boosted Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a notebook-only direct-horizon boosted forecasting candidate to test whether a nonlinear non-recursive model reduces late-horizon peak underprediction, especially on E and Mi2.

**Architecture:** Keep the production app unchanged. Add candidate helpers to `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`, wire them into `forecast_model_upgrade_inspection.ipynb`, and benchmark the candidate as `direct_hgb` beside `enhanced`, `enhanced_late_peak_uplift`, and `enhanced_peak_priority`. Start with scikit-learn `HistGradientBoostingRegressor` because LightGBM and XGBoost are not currently installed; keep the helper interface estimator-agnostic so LightGBM can be swapped in later.

**Tech Stack:** Python 3.11+, pandas, numpy, scikit-learn `HistGradientBoostingRegressor`, unittest.

---

## Decision

Start with **scikit-learn HistGradientBoostingRegressor direct-horizon**.

Reasons:

- `lightgbm` and `xgboost` are not installed in the current environment.
- `scikit-learn` is already a project dependency in `pyproject.toml`.
- HistGradientBoosting gives a nonlinear boosted-tree baseline without dependency friction.
- The important architecture change is direct-horizon prediction, not the exact boosted-tree library.

Do not start with LightGBM unless the user explicitly approves adding a dependency. Do not start with XGBoost unless it is installed or dependency approval is granted.

## How The Current Model Helps

Use the current Ridge-recursive model as:

- the benchmark to beat (`enhanced`)
- the alert/ranking companion (`enhanced_peak_priority/current_20pct`)
- the source of reusable forecast-safe feature engineering (`add_enhanced_features`, lag/rolling/regime features)
- the diagnostic framework (`summarize_model_metrics`, rolling candidate diagnostics)

Do **not** use current model predictions as training features in the first boosted candidate. That would require out-of-fold baseline forecasts to avoid leakage. Stacking can be a second experiment only after the plain direct-horizon boosted candidate is benchmarked.

## Acceptance Gate

Accept `direct_hgb` as the leading value-model candidate only if fresh rolling-origin metrics satisfy:

- `md_abs_error_kw < 97.57` kW, beating the current uplift candidate, or at minimum meaningfully below `114.04` kW while improving E/Mi2 late-horizon actual-peak diagnostics.
- `rmse_kw <= enhanced rmse_kw * 1.03`.
- `wape_pct <= enhanced wape_pct * 1.02`.
- E late-night late-horizon actual-peak mean error improves from about `-256.89` kW.
- Mi2 late-horizon actual-peak underprediction does not regress versus `enhanced_late_peak_uplift`.
- SoL/SuN site metrics do not collapse.
- `enhanced_peak_priority/current_20pct` remains separate for alert metrics.

If the candidate fails, keep it as an exploratory benchmark and do not promote it.

## File Map

- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
  - Add direct-horizon dataset builder.
  - Add `DirectHorizonBoostedModel` dataclass.
  - Add fit/predict helpers using `HistGradientBoostingRegressor`.
  - Add optional candidate diagnostics if needed.
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
  - Import the new helpers.
  - Fit `direct_hgb` inside rolling-origin loops using the same pooled training frames.
  - Add `direct_hgb` to rolling model comparison rows.
  - Save refreshed CSV outputs.
- Modify: `tests/test_forecast_model_upgrade_support.py`
  - Add TDD tests for training row shape, horizon-step feature, no target leakage, and forecast output shape.
- Modify: `tests/test_forecast_model_upgrade_notebook.py`
  - Assert notebook imports and evaluates `direct_hgb`.
- Modify after benchmark only: `docs/forecast_model_upgrade_source_of_truth.md`, `docs/status.md`, `docs/architecture.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_AND_CODING_DESIGN.md`.

---

### Task 1: Add Direct-Horizon Training Rows

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write the failing test**

Add to `ForecastModelUpgradeSupportTests`:

```python
def test_build_direct_horizon_training_rows_uses_future_steps_without_target_leakage(self) -> None:
    from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
        build_direct_horizon_training_rows,
    )

    frame = synthetic_site_frame("direct_rows", has_solar=False, periods=900)
    rows, feature_columns = build_direct_horizon_training_rows([frame], horizon=8)

    self.assertFalse(rows.empty)
    self.assertIn("target_kw_import", rows.columns)
    self.assertIn("horizon_step", rows.columns)
    self.assertIn("horizon_step", feature_columns)
    self.assertNotIn("kw_import", feature_columns)
    self.assertNotIn("target_kw_import", feature_columns)
    self.assertEqual(int(rows["horizon_step"].min()), 1)
    self.assertEqual(int(rows["horizon_step"].max()), 8)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_build_direct_horizon_training_rows_uses_future_steps_without_target_leakage -v
```

Expected: fail because `build_direct_horizon_training_rows` does not exist.

- [ ] **Step 3: Implement minimal row builder**

Add a helper that:

- calls `add_enhanced_features(frame)`
- uses each prepared row as the forecast origin
- creates one row per future step from `1..horizon`
- uses `target_kw_import` from `kw_import.shift(-step)`
- adds `horizon_step`
- adds target time features for the predicted timestamp, such as `target_hour_sin`, `target_hour_cos`, `target_day_of_week`, `target_is_weekend`, `target_is_daylight`
- drops rows where the future target is missing
- returns `(rows, feature_columns)`

- [ ] **Step 4: Run the test**

Run the same command. Expected: pass.

---

### Task 2: Fit And Forecast Direct-Horizon HGB

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write the failing test**

```python
def test_direct_horizon_boosted_forecast_returns_horizon_rows(self) -> None:
    from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
        fit_direct_horizon_boosted_model,
        forecast_with_direct_horizon_boosted_model,
    )

    frame = synthetic_site_frame("direct_hgb", has_solar=False, periods=950)
    train_frame = frame.iloc[:-48].copy()
    model = fit_direct_horizon_boosted_model([train_frame], horizon=12, max_iter=20)
    forecast = forecast_with_direct_horizon_boosted_model(model, train_frame, horizon=12)

    self.assertEqual(len(forecast), 12)
    self.assertIn("forecast_kw_import", forecast.columns)
    self.assertIn("horizon_step", forecast.columns)
    self.assertTrue(np.isfinite(forecast["forecast_kw_import"]).all())
    self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_direct_horizon_boosted_forecast_returns_horizon_rows -v
```

Expected: fail because helpers do not exist.

- [ ] **Step 3: Implement minimal model dataclass and helpers**

Add:

```python
@dataclass
class DirectHorizonBoostedModel:
    model: HistGradientBoostingRegressor
    feature_columns: list[str]
    horizon: int
```

Use `HistGradientBoostingRegressor` with conservative defaults:

```python
HistGradientBoostingRegressor(
    loss="squared_error",
    max_iter=120,
    learning_rate=0.06,
    max_leaf_nodes=31,
    l2_regularization=0.05,
    random_state=42,
)
```

For prediction, build one feature row for each horizon step from the last available prepared origin row and target timestamp features. Clip forecasts at `0.0`.

- [ ] **Step 4: Run the test**

Expected: pass.

---

### Task 3: Add Notebook Wiring

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
- Test: `tests/test_forecast_model_upgrade_notebook.py`

- [ ] **Step 1: Write failing notebook structure test**

Add:

```python
def test_notebook_wires_direct_horizon_boosted_candidate(self) -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

    self.assertIn("fit_direct_horizon_boosted_model = forecast_support.fit_direct_horizon_boosted_model", all_source)
    self.assertIn("forecast_with_direct_horizon_boosted_model = forecast_support.forecast_with_direct_horizon_boosted_model", all_source)
    self.assertIn("direct_hgb", all_source)
```

- [ ] **Step 2: Run failing test**

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook.ForecastModelUpgradeNotebookTests.test_notebook_wires_direct_horizon_boosted_candidate -v
```

- [ ] **Step 3: Wire notebook imports and rolling-origin candidate**

In the import cell:

```python
fit_direct_horizon_boosted_model = forecast_support.fit_direct_horizon_boosted_model
forecast_with_direct_horizon_boosted_model = forecast_support.forecast_with_direct_horizon_boosted_model
```

Inside the rolling-origin loop after `enhanced_forecast` is available:

```python
direct_hgb = fit_direct_horizon_boosted_model(
    pooled_train_frames,
    horizon=HORIZON,
)
direct_hgb_forecast = forecast_with_direct_horizon_boosted_model(
    direct_hgb,
    train_frame,
    horizon=HORIZON,
)
direct_hgb_metrics = evaluate_forecast(
    actual,
    direct_hgb_forecast["forecast_kw_import"].to_numpy(dtype=float),
    peak_match_window=PEAK_MATCH_WINDOW,
)
component_records.append({"model": "direct_hgb", **direct_hgb_metrics})
```

Also add `direct_hgb_kw_import` to `rolling_predictions`.

- [ ] **Step 4: Run notebook tests**

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook -v
```

Expected: pass.

---

### Task 4: Benchmark And Decide

**Files:**
- Modify after rerun: docs listed above

- [ ] **Step 1: Run targeted tests**

```powershell
python -m unittest tests.test_forecast_model_upgrade_support tests.test_forecast_model_upgrade_notebook -v
```

- [ ] **Step 2: Run rolling-origin benchmark cells**

Rerun notebook import/setup and rolling-origin cells. Save:

```text
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_model_results.csv
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_model_summary.csv
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_candidate_error_diagnostics.csv
```

- [ ] **Step 3: Compare candidates**

Compare at minimum:

- `enhanced`
- `enhanced_late_peak_uplift`
- `enhanced_peak_priority`
- `direct_hgb`

Use these columns:

```python
[
    "model",
    "rmse_kw",
    "wape_pct",
    "md_abs_error_kw",
    "peak_precision",
    "peak_recall",
    "peak_f1",
    "peak_false_negative_count",
    "peak_false_positive_count",
    "md_peak_rank",
    "peak_time_error_intervals",
]
```

- [ ] **Step 4: Apply acceptance gate**

If `direct_hgb` passes, record it as the leading notebook value-model candidate. If it fails, reject it clearly and decide whether LightGBM dependency approval is worth asking for.

- [ ] **Step 5: Run full tests**

```powershell
python -m unittest -v
```

- [ ] **Step 6: Update docs**

Record metrics and decision in:

- `docs/forecast_model_upgrade_source_of_truth.md`
- `docs/status.md`
- `docs/architecture.md`
- `PROJECT_STATUS.md`
- `ARCHITECTURE_AND_CODING_DESIGN.md`

Do not update production app behavior unless the user explicitly approves promotion.

