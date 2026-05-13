# Forecast Error Diagnosis And Alert Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the notebook forecast experiment by diagnosing rolling-origin failure modes, then testing constrained alert confirmation and alert episodes without changing production app behavior.

**Architecture:** Keep all work inside the notebook experiment path. Add small, testable helper functions to `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`, wire them into `forecast_model_upgrade_inspection.ipynb`, and accept a candidate only after fresh rolling-origin metrics beat the current `current_20pct` policy or improve forecast value without RMSE/WAPE regression.

**Tech Stack:** Python 3.11+, pandas, numpy, scikit-learn, unittest.

---

## Execution Status

Executed on 2026-05-04 through notebook metric review.

Outcome:

- `enhanced_peak_confirmed` is rejected.
- `current_20pct` remains the accepted notebook alert policy for review.
- Rolling diagnostics identify late-horizon actual-peak underprediction on `E` and `Mi2` as the strongest next modeling target.
- Refreshed CSV outputs were written to `notebooks/model_upgrade_inspection/_latest_rerun_metrics/`.
- App promotion remains deferred.

## Current Baseline

Fresh 2026-05-04 rolling-origin metric review:

| Model | RMSE kW | WAPE % | MD abs error kW | Peak precision | Peak recall | Peak F1 | Missed peaks | False positives |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.06 | 26.88 | 114.04 | 0.480 | 0.472 | 0.475 | 2.775 | 2.325 |
| enhanced_peak_priority | 141.06 | 26.88 | 114.04 | 0.393 | 0.776 | 0.521 | 1.250 | 4.350 |
| enhanced_md_calibrated | 151.73 | 28.10 | 111.95 | 0.515 | 0.507 | 0.510 | 2.600 | 2.300 |

Accepted baseline:

- Forecast value model: `enhanced`
- Peak-alert policy: `enhanced_peak_priority` with `current_20pct`
- App promotion: deferred

Acceptance targets for this plan:

- Keep rolling peak recall `>= 0.75`.
- Improve rolling peak precision above `0.393`.
- Keep average missed peaks `<= 1.50`.
- Do not worsen `enhanced` RMSE or WAPE for any accepted forecast-value candidate.
- Do not promote anything into `trex_energy/forecasting.py` or `app.py`.

## File Map

- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
  - Add diagnostic summary helpers.
  - Add confirmed-alert policy helpers.
  - Add alert episode grouping/ranking helpers.
  - Add gated horizon-bias correction helpers only if diagnostics justify it.
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
  - Wire diagnostic tables, confirmed-alert comparison rows, and episode comparison rows.
- Modify: `tests/test_forecast_model_upgrade_support.py`
  - Add focused unit tests for every new helper.
- Modify: `tests/test_forecast_model_upgrade_notebook.py`
  - Assert notebook wiring for diagnostics and candidate rows.
- Modify: `docs/forecast_model_upgrade_source_of_truth.md`
  - Record accepted/rejected candidates and refreshed metrics.
- Modify: `docs/status.md` and `PROJECT_STATUS.md`
  - Record plan execution status and next decision.

---

### Task 1: Rolling-Origin Failure Diagnostics

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write the failing test**

Add this test to `ForecastModelUpgradeSupportTests`:

```python
    def test_summarize_rolling_error_diagnostics_groups_horizon_and_peak_regimes(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import summarize_rolling_error_diagnostics

        predictions = pd.DataFrame(
            {
                "site_id": ["A"] * 6,
                "fold": [1] * 6,
                "step": [1, 2, 10, 11, 30, 31],
                "actual_kw_import": [100.0, 120.0, 300.0, 320.0, 150.0, 140.0],
                "enhanced_kw_import": [110.0, 130.0, 260.0, 270.0, 170.0, 160.0],
                "has_solar": [False] * 6,
                "is_daylight": [False, False, True, True, True, False],
            }
        )

        summary = summarize_rolling_error_diagnostics(predictions)

        self.assertIn("horizon_bucket", summary.columns)
        self.assertIn("actual_peak_regime", summary.columns)
        self.assertIn("mean_abs_error_kw", summary.columns)
        self.assertTrue({"early", "middle", "late"}.intersection(set(summary["horizon_bucket"])))
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_summarize_rolling_error_diagnostics_groups_horizon_and_peak_regimes -v
```

Expected: fail because `summarize_rolling_error_diagnostics` does not exist.

- [ ] **Step 3: Implement diagnostics helper**

Add this function near `summarize_prediction_errors(...)`:

```python
def summarize_rolling_error_diagnostics(predictions: pd.DataFrame) -> pd.DataFrame:
    required = {"site_id", "fold", "step", "actual_kw_import", "enhanced_kw_import", "has_solar", "is_daylight"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"Diagnostic predictions missing columns: {missing}")

    working = predictions.copy()
    working["error_kw"] = working["enhanced_kw_import"].astype(float) - working["actual_kw_import"].astype(float)
    working["abs_error_kw"] = working["error_kw"].abs()
    working["site_type"] = np.where(working["has_solar"].astype(bool), "solar", "non_solar")
    working["light_regime"] = np.where(working["is_daylight"].astype(bool), "daylight", "night")
    working["horizon_bucket"] = pd.cut(
        working["step"].astype(int),
        bins=[0, 16, 32, np.inf],
        labels=["early", "middle", "late"],
        include_lowest=True,
    ).astype(str)

    peak_threshold = working.groupby(["site_id", "fold"])["actual_kw_import"].transform(lambda s: s.quantile(0.90))
    working["actual_peak_regime"] = np.where(
        working["actual_kw_import"].astype(float) >= peak_threshold,
        "actual_peak",
        "non_peak",
    )

    return (
        working.groupby(["site_id", "site_type", "light_regime", "horizon_bucket", "actual_peak_regime"], as_index=False)
        .agg(
            rows=("error_kw", "size"),
            mean_error_kw=("error_kw", "mean"),
            mean_abs_error_kw=("abs_error_kw", "mean"),
            max_abs_error_kw=("abs_error_kw", "max"),
        )
        .sort_values(["mean_abs_error_kw"], ascending=False)
        .reset_index(drop=True)
    )
```

- [ ] **Step 4: Run the test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_summarize_rolling_error_diagnostics_groups_horizon_and_peak_regimes -v
```

Expected: pass.

---

### Task 2: Confirmed Peak Alert Policy

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write the failing test**

Add this test:

```python
    def test_confirm_peak_alerts_requires_risk_and_context_confirmation(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import confirm_peak_alerts

        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 180.0, 210.0, 120.0, 205.0],
                "peak_risk_overlay_score": [0.95, 0.92, 0.91, 0.20, 0.89],
                "ridge_component": [100.0, 180.0, 210.0, 120.0, 205.0],
                "seasonal_component": [100.0, 170.0, 205.0, 150.0, 190.0],
            }
        )

        confirmed = confirm_peak_alerts(forecast, alert_quantile=0.60, value_quantile=0.70)

        self.assertIn("confirmed_peak_score", confirmed.columns)
        self.assertIn("is_confirmed_peak_alert", confirmed.columns)
        self.assertLess(int(confirmed["is_confirmed_peak_alert"].sum()), 4)
        self.assertTrue(bool(confirmed.loc[2, "is_confirmed_peak_alert"]))
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_confirm_peak_alerts_requires_risk_and_context_confirmation -v
```

Expected: fail because `confirm_peak_alerts` does not exist.

- [ ] **Step 3: Implement confirmation helper**

Add this function after `compare_peak_alert_policies(...)`:

```python
def confirm_peak_alerts(
    forecast: pd.DataFrame,
    alert_quantile: float = 0.80,
    value_quantile: float = 0.75,
    score_column: str = "peak_risk_overlay_score",
) -> pd.DataFrame:
    required = {"forecast_kw_import", score_column}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError(f"Peak confirmation forecast missing columns: {missing}")

    confirmed = forecast.copy()
    score = confirmed[score_column].astype(float).to_numpy()
    forecast_values = confirmed["forecast_kw_import"].astype(float).to_numpy()
    risk_threshold = float(np.quantile(score, alert_quantile))
    value_threshold = float(np.quantile(forecast_values, value_quantile))

    near_value_peak = forecast_values >= value_threshold
    if "ridge_component" in confirmed.columns and "seasonal_component" in confirmed.columns:
        component_support = (
            confirmed["ridge_component"].astype(float).to_numpy()
            >= confirmed["seasonal_component"].astype(float).to_numpy()
        )
    else:
        component_support = np.ones(len(confirmed), dtype=bool)

    confirmed_mask = (score >= risk_threshold) & near_value_peak & component_support
    confirmed["confirmed_peak_score"] = np.where(confirmed_mask, score, 0.0)
    confirmed["is_confirmed_peak_alert"] = confirmed_mask
    return confirmed
```

- [ ] **Step 4: Run the test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_confirm_peak_alerts_requires_risk_and_context_confirmation -v
```

Expected: pass.

---

### Task 3: Alert Episode Grouping

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Write the failing test**

Add this test:

```python
    def test_rank_alert_episodes_groups_nearby_alerts(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import rank_alert_episodes

        forecast = pd.DataFrame(
            {
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=8, freq="30min"),
                "is_confirmed_peak_alert": [False, True, True, False, False, True, True, False],
                "confirmed_peak_score": [0.0, 0.7, 0.9, 0.0, 0.0, 0.6, 0.8, 0.0],
                "forecast_kw_import": [100.0, 180.0, 220.0, 120.0, 130.0, 190.0, 210.0, 140.0],
            }
        )

        episodes = rank_alert_episodes(forecast)

        self.assertEqual(len(episodes), 2)
        self.assertGreaterEqual(float(episodes.loc[0, "episode_score"]), float(episodes.loc[1, "episode_score"]))
        self.assertEqual(int(episodes.loc[0, "alert_count"]), 2)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_rank_alert_episodes_groups_nearby_alerts -v
```

Expected: fail because `rank_alert_episodes` does not exist.

- [ ] **Step 3: Implement episode helper**

Add this function after `confirm_peak_alerts(...)`:

```python
def rank_alert_episodes(
    forecast: pd.DataFrame,
    max_gap_intervals: int = 2,
) -> pd.DataFrame:
    required = {"interval_end", "is_confirmed_peak_alert", "confirmed_peak_score", "forecast_kw_import"}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError(f"Alert episode forecast missing columns: {missing}")

    working = forecast.sort_values("interval_end").reset_index(drop=True).copy()
    alert_indices = np.where(working["is_confirmed_peak_alert"].astype(bool).to_numpy())[0]
    if len(alert_indices) == 0:
        return pd.DataFrame(
            columns=["episode_id", "start_interval", "end_interval", "alert_count", "max_score", "max_forecast_kw", "episode_score"]
        )

    episodes: list[list[int]] = [[int(alert_indices[0])]]
    for idx in alert_indices[1:]:
        if int(idx) - episodes[-1][-1] <= max_gap_intervals:
            episodes[-1].append(int(idx))
        else:
            episodes.append([int(idx)])

    rows = []
    for episode_id, indices in enumerate(episodes, start=1):
        block = working.iloc[indices]
        max_score = float(block["confirmed_peak_score"].max())
        max_forecast = float(block["forecast_kw_import"].max())
        rows.append(
            {
                "episode_id": episode_id,
                "start_interval": block["interval_end"].iloc[0],
                "end_interval": block["interval_end"].iloc[-1],
                "alert_count": int(len(block)),
                "max_score": max_score,
                "max_forecast_kw": max_forecast,
                "episode_score": max_score * max_forecast,
            }
        )

    return pd.DataFrame(rows).sort_values(["episode_score"], ascending=False).reset_index(drop=True)
```

- [ ] **Step 4: Run the test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_rank_alert_episodes_groups_nearby_alerts -v
```

Expected: pass.

---

### Task 4: Notebook Candidate Wiring

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
- Test: `tests/test_forecast_model_upgrade_notebook.py`

- [ ] **Step 1: Write the failing notebook wiring test**

Add this test to `ForecastModelUpgradeNotebookTests`:

```python
    def test_notebook_wires_diagnostics_confirmation_and_episode_candidates(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("summarize_rolling_error_diagnostics = forecast_support.summarize_rolling_error_diagnostics", all_source)
        self.assertIn("confirm_peak_alerts = forecast_support.confirm_peak_alerts", all_source)
        self.assertIn("rank_alert_episodes = forecast_support.rank_alert_episodes", all_source)
        self.assertIn("enhanced_peak_confirmed", all_source)
        self.assertIn("rolling_error_diagnostics", all_source)
        self.assertIn("alert_episode_rows", all_source)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook.ForecastModelUpgradeNotebookTests.test_notebook_wires_diagnostics_confirmation_and_episode_candidates -v
```

Expected: fail until notebook imports and rolling-origin cell are updated.

- [ ] **Step 3: Wire imports**

In notebook support import cell, add:

```python
summarize_rolling_error_diagnostics = forecast_support.summarize_rolling_error_diagnostics
confirm_peak_alerts = forecast_support.confirm_peak_alerts
rank_alert_episodes = forecast_support.rank_alert_episodes
```

- [ ] **Step 4: Wire rolling-origin candidate rows**

Inside the rolling-origin loop after `enhanced_forecast = apply_peak_risk_overlay(...)`, add:

```python
confirmed_forecast = confirm_peak_alerts(enhanced_forecast, alert_quantile=PEAK_ALERT_QUANTILE)
confirmed_metrics = evaluate_forecast(
    actual,
    confirmed_forecast["forecast_kw_import"].to_numpy(dtype=float),
    peak_score=confirmed_forecast["confirmed_peak_score"].to_numpy(dtype=float),
    predicted_peak_quantile=PEAK_ALERT_QUANTILE,
    peak_match_window=PEAK_MATCH_WINDOW,
)
component_records.append({"model": "enhanced_peak_confirmed", **confirmed_metrics})

episode_table = rank_alert_episodes(confirmed_forecast)
episode_table["site_id"] = site_id
episode_table["fold"] = fold_number
alert_episode_rows.extend(episode_table.to_dict("records"))
```

Initialize before the rolling loop:

```python
alert_episode_rows = []
```

After `rolling_predictions` is built, add:

```python
rolling_error_diagnostics = summarize_rolling_error_diagnostics(rolling_predictions)
alert_episode_summary = pd.DataFrame(alert_episode_rows)
```

Display both tables after the existing rolling summaries.

- [ ] **Step 5: Run notebook wiring test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook.ForecastModelUpgradeNotebookTests.test_notebook_wires_diagnostics_confirmation_and_episode_candidates -v
```

Expected: pass.

---

### Task 5: Rerun Metrics And Accept/Reject Candidate

**Files:**
- Modify: `docs/forecast_model_upgrade_source_of_truth.md`
- Modify: `docs/status.md`
- Modify: `PROJECT_STATUS.md`

- [ ] **Step 1: Run fast tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support tests.test_forecast_model_upgrade_notebook -v
```

Expected: pass.

- [ ] **Step 2: Run full tests**

Run:

```powershell
python -m unittest -v
```

Expected: pass.

- [ ] **Step 3: Rerun notebook metric cells**

Use the existing runner pattern or Jupyter to rerun cells through rolling-origin summaries. Save updated CSV outputs under:

```text
notebooks/model_upgrade_inspection/_latest_rerun_metrics/
```

Required outputs:

```text
rolling_model_summary.csv
rolling_model_results.csv
rolling_summary.csv
rolling_error_diagnostics.csv
alert_episode_summary.csv
```

- [ ] **Step 4: Acceptance decision**

Accept `enhanced_peak_confirmed` only if:

```text
peak_recall >= 0.75
peak_precision > 0.393
peak_false_negative_count <= 1.50
rmse_kw == enhanced rmse_kw
wape_pct == enhanced wape_pct
md_abs_error_kw == enhanced md_abs_error_kw
```

If it fails any gate, retain `enhanced_peak_priority/current_20pct`.

- [ ] **Step 5: Update source-of-truth docs**

Add a dated section to `docs/forecast_model_upgrade_source_of_truth.md` with the rolling candidate table, diagnostic findings, and this exact decision format:

```markdown
Decision:

- accepted peak-alert policy: `enhanced_peak_confirmed` or `current_20pct retained`
- reason: one sentence based on recall, precision, and missed peaks
- app promotion status: deferred pending user metric review
```

- [ ] **Step 6: Update status docs**

In `docs/status.md`, add a `Recent Changes` bullet:

```markdown
- 2026-05-04: Ran the diagnosis/confirmed-alert notebook plan. Recorded whether `enhanced_peak_confirmed` beats the current top-20% peak-priority policy.
```

In `PROJECT_STATUS.md`, add:

```markdown
- 2026-05-04: Added/ran the diagnosis and confirmed-alert plan; app promotion remains deferred pending metric review.
```

---

## Completion Checklist

This plan is complete when:

- diagnostic tables identify the worst failure regimes,
- `enhanced_peak_confirmed` is either accepted or rejected with metrics,
- refreshed CSVs are written,
- docs record the decision,
- app promotion remains deferred.
