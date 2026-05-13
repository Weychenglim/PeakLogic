# LightGBM Quantile MD Forecast Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a notebook-only two-stage MD forecasting benchmark using a LightGBM direct-horizon quantile value model plus a separate MD-risk head.

**Architecture:** Keep the production Streamlit app unchanged. Add a new notebook candidate beside the existing `enhanced`, `enhanced_late_peak_uplift`, `direct_hgb`, and `enhanced_peak_priority` rows. The new candidate forecasts expected demand and MD-risk demand separately: p50 for normal value forecasting, p80/p90 for MD-risk planning, and a separate classifier score for peak-risk ranking.

**Tech Stack:** Python 3.11+, pandas, numpy, scikit-learn, LightGBM, unittest, notebook rolling-origin metrics.

---

## Decision

Start with **LightGBM direct-horizon quantile regression**, not another Ridge correction and not another mean HGB.

Reasons:

- The rejected `direct_hgb` was a pooled mean model. It improved WAPE but worsened MD abs error, E, and Mi2.
- The diagnosed failure is upper-tail peak underprediction, especially late-horizon actual peaks.
- Mean models naturally smooth peaks. MD planning needs an upper quantile, not only expected demand.
- LightGBM supports quantile objectives directly and is a better fit than scikit-learn HGB for this benchmark.

The current model still helps as:

- the baseline to beat: `enhanced`
- the current value candidate to beat: `enhanced_late_peak_uplift`
- the peak-alert companion: `enhanced_peak_priority/current_20pct`
- the reusable forecast-safe feature source: `add_enhanced_features(...)`
- the diagnostic and metric framework

Do not use current model predictions as training features in the first LightGBM quantile version. That would require out-of-fold baseline predictions to avoid leakage and should be a second experiment only if plain quantile LightGBM is promising.

## Acceptance Gate

Keep the candidate only if fresh rolling-origin metrics satisfy all hard gates:

- Mean MD abs error beats `enhanced_late_peak_uplift` at `97.57` kW, or improves materially while fixing E/Mi2 late-peak diagnostics.
- RMSE does not worsen by more than 3% versus `enhanced` (`141.06` kW baseline).
- WAPE does not worsen by more than 2% versus `enhanced` (`26.88%` baseline).
- E non-solar night late actual-peak mean error improves from about `-256.89` kW.
- Mi2 late-horizon actual-peak underprediction does not regress versus `enhanced_late_peak_uplift`.
- Peak-risk recall remains at least comparable to `enhanced_peak_priority/current_20pct` when the MD-risk head is evaluated as an alert score.

If these gates fail, reject the candidate and document it. Do not tune small knobs repeatedly.

## File Map

- Modify: `pyproject.toml`
  - Add `lightgbm` as a project dependency after user approval to install.
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
  - Add LightGBM availability/import guard.
  - Add direct-horizon quantile dataset helpers using existing enhanced features.
  - Add `DirectHorizonQuantileModel` dataclass.
  - Add fit/predict helpers for p50, p80, and p90.
  - Add a separate MD-risk classifier head using LightGBM binary classification or scikit-learn fallback if needed.
  - Add quantile-aware evaluation helpers.
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
  - Import new helpers.
  - Fit the candidate inside the rolling-origin loop using the same pooled training frames.
  - Add model rows such as `direct_lgbm_quantile_p50`, `direct_lgbm_quantile_p80`, `direct_lgbm_quantile_p90`, and `direct_lgbm_md_risk`.
  - Save quantile forecast columns into `rolling_predictions`.
  - Include the new columns in candidate diagnostics.
- Modify: `tests/test_forecast_model_upgrade_support.py`
  - Add TDD coverage for row building, quantile model output shape, monotonic quantile repair, no target leakage, and MD-risk labels.
- Modify: `tests/test_forecast_model_upgrade_notebook.py`
  - Assert the notebook imports and evaluates the LightGBM quantile candidate.
- Update after benchmark: `docs/forecast_model_upgrade_source_of_truth.md`, `docs/status.md`, `docs/architecture.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_AND_CODING_DESIGN.md`.

---

### Task 1: Add Dependency Plan And Guard

**Files:**
- Modify: `pyproject.toml`
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Install LightGBM after approval**

Run:

```powershell
python -m pip install lightgbm
```

Expected: `Successfully installed lightgbm...`

- [ ] **Step 2: Add dependency**

Add to `pyproject.toml` dependencies:

```toml
  "lightgbm",
```

- [ ] **Step 3: Write import guard test**

Add a test that imports the new availability helper:

```python
def test_lightgbm_quantile_dependency_is_available(self) -> None:
    from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import require_lightgbm

    module = require_lightgbm()

    self.assertTrue(hasattr(module, "LGBMRegressor"))
    self.assertTrue(hasattr(module, "LGBMClassifier"))
```

- [ ] **Step 4: Run failing/passing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_lightgbm_quantile_dependency_is_available -v
```

Expected after install and helper implementation: PASS.

### Task 2: Build Direct-Horizon Quantile Training Rows

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write row-builder test**

Add:

```python
def test_build_direct_horizon_quantile_rows_has_future_targets_and_no_leakage(self) -> None:
    from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
        build_direct_horizon_quantile_rows,
    )

    frame = synthetic_site_frame("quantile_rows", has_solar=True, periods=900)
    rows, feature_columns = build_direct_horizon_quantile_rows([frame], horizon=8)

    self.assertFalse(rows.empty)
    self.assertIn("target_kw_import", rows.columns)
    self.assertIn("is_md_risk_interval", rows.columns)
    self.assertIn("horizon_step", feature_columns)
    self.assertIn("target_is_daylight", feature_columns)
    self.assertNotIn("kw_import", feature_columns)
    self.assertNotIn("target_kw_import", feature_columns)
    self.assertEqual(int(rows["horizon_step"].min()), 1)
    self.assertEqual(int(rows["horizon_step"].max()), 8)
```

- [ ] **Step 2: Implement minimal row builder**

Create `build_direct_horizon_quantile_rows(frames, horizon=48, peak_quantile=0.90)` by adapting the existing direct-horizon row builder:

```python
def build_direct_horizon_quantile_rows(
    frames: Sequence[pd.DataFrame],
    horizon: int = 48,
    peak_quantile: float = 0.90,
) -> tuple[pd.DataFrame, list[str]]:
    rows, feature_columns = build_direct_horizon_training_rows(frames, horizon=horizon)
    if rows.empty:
        return rows, feature_columns

    threshold_by_site = rows.groupby("site_id")["target_kw_import"].transform(
        lambda values: float(np.quantile(values.astype(float), peak_quantile))
    )
    rows = rows.copy()
    rows["is_md_risk_interval"] = (rows["target_kw_import"].astype(float) >= threshold_by_site).astype(int)
    return rows, feature_columns
```

- [ ] **Step 3: Verify targeted test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_build_direct_horizon_quantile_rows_has_future_targets_and_no_leakage -v
```

Expected: PASS.

### Task 3: Fit LightGBM Quantile Models

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write forecast shape and monotonicity test**

Add:

```python
def test_direct_lightgbm_quantile_forecast_returns_monotonic_quantiles(self) -> None:
    from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
        fit_direct_horizon_lightgbm_quantile_model,
        forecast_with_direct_horizon_lightgbm_quantile_model,
    )

    frame = synthetic_site_frame("quantile_lgbm", has_solar=True, periods=950)
    train_frame = frame.iloc[:-48].copy()
    model = fit_direct_horizon_lightgbm_quantile_model([train_frame], horizon=12, n_estimators=30)
    forecast = forecast_with_direct_horizon_lightgbm_quantile_model(model, train_frame, horizon=12)

    self.assertEqual(len(forecast), 12)
    self.assertIn("forecast_p50_kw_import", forecast.columns)
    self.assertIn("forecast_p80_kw_import", forecast.columns)
    self.assertIn("forecast_p90_kw_import", forecast.columns)
    self.assertTrue((forecast["forecast_p80_kw_import"] >= forecast["forecast_p50_kw_import"]).all())
    self.assertTrue((forecast["forecast_p90_kw_import"] >= forecast["forecast_p80_kw_import"]).all())
```

- [ ] **Step 2: Implement dataclass and fit helper**

Add:

```python
@dataclass
class DirectHorizonQuantileModel:
    quantile_models: dict[float, object]
    feature_columns: list[str]
    horizon: int
    md_risk_model: object | None = None
    normalize_targets: bool = True
```

Implement `fit_direct_horizon_lightgbm_quantile_model(...)`:

```python
def fit_direct_horizon_lightgbm_quantile_model(
    frames: Sequence[pd.DataFrame],
    horizon: int = 48,
    quantiles: Sequence[float] = (0.50, 0.80, 0.90),
    n_estimators: int = 120,
    learning_rate: float = 0.04,
    num_leaves: int = 31,
    random_state: int = 42,
) -> DirectHorizonQuantileModel:
    lgb = require_lightgbm()
    rows, feature_columns = build_direct_horizon_quantile_rows(frames, horizon=horizon)
    if rows.empty:
        raise ValueError("not enough rows to train direct-horizon quantile model")

    x_train = rows[feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_train = rows["target_kw_import"].astype(float)

    quantile_models = {}
    for quantile in quantiles:
        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=float(quantile),
            n_estimators=int(n_estimators),
            learning_rate=float(learning_rate),
            num_leaves=int(num_leaves),
            random_state=int(random_state),
            verbose=-1,
            n_jobs=1,
        )
        model.fit(x_train, y_train)
        quantile_models[float(quantile)] = model

    classifier = lgb.LGBMClassifier(
        n_estimators=max(40, int(n_estimators // 2)),
        learning_rate=float(learning_rate),
        num_leaves=int(num_leaves),
        random_state=int(random_state),
        verbose=-1,
        n_jobs=1,
    )
    classifier.fit(x_train, rows["is_md_risk_interval"].astype(int))

    return DirectHorizonQuantileModel(
        quantile_models=quantile_models,
        feature_columns=feature_columns,
        horizon=horizon,
        md_risk_model=classifier,
    )
```

- [ ] **Step 3: Implement forecast helper**

Implement `forecast_with_direct_horizon_lightgbm_quantile_model(...)` using `_direct_horizon_prediction_features(...)`, then repair quantile crossing:

```python
forecast["forecast_p80_kw_import"] = np.maximum(
    forecast["forecast_p80_kw_import"], forecast["forecast_p50_kw_import"]
)
forecast["forecast_p90_kw_import"] = np.maximum(
    forecast["forecast_p90_kw_import"], forecast["forecast_p80_kw_import"]
)
forecast["forecast_kw_import"] = forecast["forecast_p50_kw_import"]
forecast["md_risk_value_kw_import"] = forecast["forecast_p90_kw_import"]
```

If `md_risk_model` exists, add:

```python
forecast["md_risk_head_score"] = model.md_risk_model.predict_proba(x_future)[:, 1]
```

- [ ] **Step 4: Verify targeted test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_direct_lightgbm_quantile_forecast_returns_monotonic_quantiles -v
```

Expected: PASS.

### Task 4: Wire Notebook Candidate

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
- Test: `tests/test_forecast_model_upgrade_notebook.py`

- [ ] **Step 1: Write notebook wiring test**

Add:

```python
def test_notebook_wires_lightgbm_quantile_md_candidate(self) -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

    self.assertIn("fit_direct_horizon_lightgbm_quantile_model = forecast_support.fit_direct_horizon_lightgbm_quantile_model", all_source)
    self.assertIn("forecast_with_direct_horizon_lightgbm_quantile_model = forecast_support.forecast_with_direct_horizon_lightgbm_quantile_model", all_source)
    self.assertIn("direct_lgbm_quantile_p50", all_source)
    self.assertIn("direct_lgbm_quantile_p90", all_source)
    self.assertIn("direct_lgbm_md_risk", all_source)
```

- [ ] **Step 2: Add imports in notebook reload cell**

Add bindings:

```python
fit_direct_horizon_lightgbm_quantile_model = forecast_support.fit_direct_horizon_lightgbm_quantile_model
forecast_with_direct_horizon_lightgbm_quantile_model = forecast_support.forecast_with_direct_horizon_lightgbm_quantile_model
```

- [ ] **Step 3: Add rolling loop candidate**

Inside the rolling-origin loop, after existing model fits:

```python
direct_lgbm_quantile = fit_direct_horizon_lightgbm_quantile_model(
    pooled_train_frames,
    horizon=FORECAST_HORIZON,
    n_estimators=DIRECT_LGBM_N_ESTIMATORS,
)
direct_lgbm_forecast = forecast_with_direct_horizon_lightgbm_quantile_model(
    direct_lgbm_quantile,
    train_frame,
    horizon=FORECAST_HORIZON,
)
```

Evaluate p50 and p90:

```python
component_records.append({
    "model": "direct_lgbm_quantile_p50",
    **evaluate_forecast(actual, direct_lgbm_forecast["forecast_p50_kw_import"].to_numpy(dtype=float)),
})
component_records.append({
    "model": "direct_lgbm_quantile_p90",
    **evaluate_forecast(actual, direct_lgbm_forecast["forecast_p90_kw_import"].to_numpy(dtype=float)),
})
component_records.append({
    "model": "direct_lgbm_md_risk",
    **evaluate_forecast(
        actual,
        direct_lgbm_forecast["forecast_p50_kw_import"].to_numpy(dtype=float),
        peak_score=direct_lgbm_forecast["md_risk_head_score"].to_numpy(dtype=float),
        peak_match_window=PEAK_MATCH_WINDOW,
    ),
})
```

- [ ] **Step 4: Save predictions**

Add columns to each rolling prediction row:

```python
"direct_lgbm_p50_kw_import": direct_lgbm_forecast["forecast_p50_kw_import"].to_numpy(dtype=float),
"direct_lgbm_p80_kw_import": direct_lgbm_forecast["forecast_p80_kw_import"].to_numpy(dtype=float),
"direct_lgbm_p90_kw_import": direct_lgbm_forecast["forecast_p90_kw_import"].to_numpy(dtype=float),
"direct_lgbm_md_risk_score": direct_lgbm_forecast["md_risk_head_score"].to_numpy(dtype=float),
```

- [ ] **Step 5: Verify notebook test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook.ForecastModelUpgradeNotebookTests.test_notebook_wires_lightgbm_quantile_md_candidate -v
```

Expected: PASS.

### Task 5: Add Candidate Diagnostics

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`

- [ ] **Step 1: Extend candidate diagnostic map**

Add:

```python
"direct_lgbm_quantile_p50": "direct_lgbm_p50_kw_import",
"direct_lgbm_quantile_p80": "direct_lgbm_p80_kw_import",
"direct_lgbm_quantile_p90": "direct_lgbm_p90_kw_import",
```

- [ ] **Step 2: Confirm CSV output includes new candidate rows**

After notebook rerun, inspect:

```powershell
Import-Csv notebooks\model_upgrade_inspection\_latest_rerun_metrics\rolling_candidate_error_diagnostics.csv | Where-Object { $_.model -like 'direct_lgbm*' } | Select-Object -First 5
```

Expected: rows exist for p50/p80/p90.

### Task 6: Run Verification And Benchmark

**Files:**
- Read generated CSVs under `notebooks/model_upgrade_inspection/_latest_rerun_metrics/`

- [ ] **Step 1: Run targeted tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support tests.test_forecast_model_upgrade_notebook -v
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```powershell
python -m unittest -v
```

Expected: PASS.

- [ ] **Step 3: Rerun notebook metric path**

Rerun `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb` from the import/helper cells through rolling-origin metric export.

Expected output files:

```text
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_model_summary.csv
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_model_results.csv
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_candidate_error_diagnostics.csv
notebooks/model_upgrade_inspection/_latest_rerun_metrics/rolling_predictions.csv
```

- [ ] **Step 4: Apply acceptance gate**

Compare:

- `enhanced`
- `enhanced_late_peak_uplift`
- `direct_hgb`
- `enhanced_peak_priority`
- `direct_lgbm_quantile_p50`
- `direct_lgbm_quantile_p90`
- `direct_lgbm_md_risk`

Accept only if the gate in this plan is met. Otherwise document rejection and stop modeling experiments.

### Task 7: Update Documentation

**Files:**
- Modify: `docs/forecast_model_upgrade_source_of_truth.md`
- Modify: `docs/status.md`
- Modify: `docs/architecture.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`

- [ ] **Step 1: Update source of truth**

Record:

- why LightGBM quantile was tested
- dependency addition
- exact rolling metrics
- site-level E/Mi2 diagnostics
- accept/reject decision
- whether production app promotion remains deferred

- [ ] **Step 2: Update status docs**

Add one concise status bullet with:

- candidate name
- benchmark result
- decision
- next action

- [ ] **Step 3: Update architecture docs**

Record the architectural decision:

- forecast expected demand and MD-risk demand separately
- keep notebook candidate separate from production app until accepted
- keep `enhanced_peak_priority` as alert comparison baseline

- [ ] **Step 4: Verify docs and tests**

Run:

```powershell
python -m unittest -v
```

Expected: PASS.

---

## Execution Notes

- Expect this to be slower than the current tests because three quantile regressors plus one classifier are trained per rolling fold.
- Start with conservative LightGBM settings (`n_estimators=120`, `learning_rate=0.04`, `num_leaves=31`, `n_jobs=1`) to avoid turning the first benchmark into a tuning sweep.
- If runtime is too high, reduce folds only for a smoke run, then restore the documented rolling-origin fold set for the acceptance run.
- Do not promote p90 as the normal forecast. Use p50 for expected demand, and use p80/p90 as MD-risk planning values.
- If the candidate only improves WAPE but worsens MD abs error, reject it like `direct_hgb`.
