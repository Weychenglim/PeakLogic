# Forecast Peak Alert Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the notebook forecasting path by reducing peak-alert false alarms, improving peak timing, and reducing MD magnitude error while keeping `enhanced_peak_priority` separate from forecast-value generation.

**Architecture:** Keep the notebook experiment path as the proving ground, centered on `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py` and `forecast_model_upgrade_inspection.ipynb`. This plan stops after fresh notebook metrics and source-of-truth documentation; Streamlit app promotion is deferred until the user reviews and accepts the metric score.

**Tech Stack:** Python 3.11+, pandas, numpy, scikit-learn, unittest, Streamlit.

---

## Execution Status

Executed on 2026-05-04 through notebook metric review. App promotion remains deferred pending user approval after reviewing the score.

Outcome:

- `current_20pct` remains the leading peak-alert policy for review.
- `enhanced_md_calibrated` is not accepted because RMSE and WAPE regressed.
- Refreshed CSV outputs were written to `notebooks/model_upgrade_inspection/_latest_rerun_metrics/`.
- Full regression command `python -m unittest -v` passed with 46 tests.

## Baseline To Preserve

The current verified rolling-origin benchmark is:

| Model | RMSE kW | WAPE % | MD abs error kW | Peak precision | Peak recall | Peak F1 | Missed peaks | False positives | MD peak rank | Timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.40 | 26.91 | 114.17 | 0.485 | 0.477 | 0.480 | 2.750 | 2.325 | 14.85 | 9.83 |
| enhanced_peak_priority | 141.40 | 26.91 | 114.17 | 0.395 | 0.782 | 0.524 | 1.225 | 4.225 | 12.30 | 9.83 |

Acceptance guardrails for this plan:

- `enhanced_peak_priority` must not modify `forecast_kw_import`.
- `select_blend_weight(...)` must continue using forecast-value metrics only.
- Rolling-origin peak recall should stay at or above `0.75`.
- Rolling-origin peak precision should improve toward `0.45` without raising missed peaks above `1.50`.
- Rolling-origin MD abs error should improve from `114.17 kW` by at least `15%` before calling the value model improved.
- App promotion is out of scope for the active execution path and must wait for explicit user approval after metric review.

## File Map

- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
  - Add peak alert policy objects.
  - Add alert smoothing and threshold application helpers.
  - Add per-site-type threshold comparison helpers.
  - Add ramp and approaching-peak forecast-safe features.
  - Add value-safe MD calibration helpers.
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
  - Wire policy constants into LOSO, rolling-origin, and 48-hour comparison cells.
  - Add threshold/policy comparison output tables.
- Modify: `tests/test_forecast_model_upgrade_support.py`
  - Unit tests for policy selection, smoothing, threshold comparison, feature safety, and value-safe calibration.
- Modify: `tests/test_forecast_model_upgrade_notebook.py`
  - Notebook structure tests for new constants and output columns.
- Deferred only: `trex_energy/forecasting.py`
  - Do not modify during this plan. Promotion requires explicit approval after notebook metric review.
- Deferred only: `app.py`
  - Do not modify during this plan. Display changes require explicit approval after notebook metric review.
- Modify: `docs/forecast_model_upgrade_source_of_truth.md`
  - Record every accepted benchmark rerun.
- Modify: `docs/status.md` and `PROJECT_STATUS.md`
  - Keep project memory current.

---

### Task 1: Make Peak Alert Policy Explicit And Testable

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Add failing tests for site-type alert policy selection**

Append this test method to `ForecastModelUpgradeSupportTests` in `tests/test_forecast_model_upgrade_support.py`:

```python
    def test_peak_alert_policy_supports_site_type_thresholds(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            peak_alert_policy_for_site,
        )

        solar_policy = peak_alert_policy_for_site(has_solar=True)
        nonsolar_policy = peak_alert_policy_for_site(has_solar=False)

        self.assertIsInstance(solar_policy, PeakAlertPolicy)
        self.assertIsInstance(nonsolar_policy, PeakAlertPolicy)
        self.assertGreaterEqual(solar_policy.alert_quantile, 0.70)
        self.assertLessEqual(solar_policy.alert_quantile, 0.90)
        self.assertGreaterEqual(nonsolar_policy.alert_quantile, 0.70)
        self.assertLessEqual(nonsolar_policy.alert_quantile, 0.90)
        self.assertEqual(solar_policy.match_window_intervals, 2)
        self.assertEqual(nonsolar_policy.match_window_intervals, 2)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_peak_alert_policy_supports_site_type_thresholds -v
```

Expected: fail with an import error for `PeakAlertPolicy` or `peak_alert_policy_for_site`.

- [ ] **Step 3: Implement the explicit policy object**

Add this near the existing dataclasses in `forecast_model_upgrade_support.py`:

```python
@dataclass(frozen=True)
class PeakAlertPolicy:
    alert_quantile: float
    match_window_intervals: int = 2
    score_smoothing_window: int = 1
    overlay_weight: float = 0.60


DEFAULT_SOLAR_PEAK_ALERT_POLICY = PeakAlertPolicy(alert_quantile=0.80)
DEFAULT_NONSOLAR_PEAK_ALERT_POLICY = PeakAlertPolicy(alert_quantile=0.80)


def peak_alert_policy_for_site(has_solar: bool) -> PeakAlertPolicy:
    return DEFAULT_SOLAR_PEAK_ALERT_POLICY if bool(has_solar) else DEFAULT_NONSOLAR_PEAK_ALERT_POLICY
```

- [ ] **Step 4: Run the policy test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_peak_alert_policy_supports_site_type_thresholds -v
```

Expected: pass.

- [ ] **Step 5: Commit this checkpoint**

Run:

```powershell
git status --short
git add notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py tests/test_forecast_model_upgrade_support.py
git commit -m "test: expose peak alert policy defaults"
```

If git reports this folder is not a repository or reports dubious ownership, do not change global git config from this task. Continue and record the blocker in the final implementation notes.

---

### Task 2: Add Alert Smoothing Without Touching Forecast Values

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Add failing tests for smoothing and forecast-value safety**

Append these test methods:

```python
    def test_smooth_peak_scores_reduces_isolated_spikes(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import smooth_peak_scores

        scores = np.array([0.10, 0.10, 0.95, 0.10, 0.10, 0.80, 0.82, 0.81])
        smoothed = smooth_peak_scores(scores, window=3)

        self.assertLess(smoothed[2], scores[2])
        self.assertGreater(smoothed[6], 0.75)
        self.assertEqual(len(smoothed), len(scores))

    def test_apply_peak_risk_overlay_policy_does_not_change_forecast_values(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            add_enhanced_features,
            apply_peak_risk_overlay,
            fit_peak_risk_overlay,
        )

        frame = synthetic_site_frame("overlay_policy", has_solar=False, periods=950)
        train_frame = frame.iloc[:-48].copy()
        prepared, feature_columns = add_enhanced_features(train_frame)
        overlay = fit_peak_risk_overlay(prepared, feature_columns)
        forecast = pd.DataFrame(
            {
                "site_id": ["overlay_policy"] * 6,
                "interval_end": pd.date_range(
                    train_frame["interval_end"].iloc[-1] + pd.Timedelta(minutes=30),
                    periods=6,
                    freq="30min",
                ),
                "forecast_kw_import": [100.0, 120.0, 140.0, 160.0, 180.0, 200.0],
                "peak_risk_score": [0.10, 0.20, 0.90, 0.30, 0.85, 0.40],
            }
        )

        enriched = apply_peak_risk_overlay(
            forecast,
            overlay,
            train_frame,
            policy=PeakAlertPolicy(alert_quantile=0.80, score_smoothing_window=3),
        )

        self.assertTrue(np.allclose(enriched["forecast_kw_import"], forecast["forecast_kw_import"]))
        self.assertIn("peak_risk_overlay_score", enriched.columns)
        self.assertIn("peak_risk_smoothed_score", enriched.columns)
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_smooth_peak_scores_reduces_isolated_spikes tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_apply_peak_risk_overlay_policy_does_not_change_forecast_values -v
```

Expected: fail because `smooth_peak_scores` and the `policy` argument are missing.

- [ ] **Step 3: Implement smoothing and policy-aware overlay application**

Add this helper before `apply_peak_risk_overlay(...)`:

```python
def smooth_peak_scores(scores: np.ndarray | pd.Series, window: int = 1) -> np.ndarray:
    score_array = np.asarray(scores, dtype=float)
    smoothing_window = max(int(window), 1)
    if smoothing_window == 1 or len(score_array) == 0:
        return score_array.copy()

    return (
        pd.Series(score_array)
        .rolling(window=smoothing_window, min_periods=1, center=True)
        .mean()
        .to_numpy(dtype=float)
    )
```

Change the `apply_peak_risk_overlay(...)` signature to:

```python
def apply_peak_risk_overlay(
    forecast: pd.DataFrame,
    overlay: PeakRiskOverlay,
    target_frame: pd.DataFrame,
    policy: PeakAlertPolicy | None = None,
) -> pd.DataFrame:
```

Inside the function, after `has_solar = ...`, add:

```python
    alert_policy = policy or peak_alert_policy_for_site(has_solar)
```

Replace the score blend and threshold block with:

```python
    overlay_weight = float(np.clip(alert_policy.overlay_weight, 0.0, 1.0))
    if "peak_risk_score" in enriched.columns:
        value_score = enriched["peak_risk_score"].astype(float).to_numpy()
        combined_score = (1.0 - overlay_weight) * value_score + overlay_weight * overlay_scores
    else:
        combined_score = overlay_scores

    smoothed_score = smooth_peak_scores(combined_score, window=alert_policy.score_smoothing_window)
    enriched["peak_risk_score"] = combined_score
    enriched["peak_risk_smoothed_score"] = smoothed_score

    threshold = float(np.quantile(smoothed_score, alert_policy.alert_quantile))
    enriched["is_predicted_peak"] = smoothed_score >= threshold
```

- [ ] **Step 4: Run smoothing tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_smooth_peak_scores_reduces_isolated_spikes tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_apply_peak_risk_overlay_policy_does_not_change_forecast_values -v
```

Expected: pass.

- [ ] **Step 5: Run existing overlay tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_peak_overlay_rejects_leakage_columns_and_uses_forecast_safe_features tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_component_evaluation_uses_overlay_alert_quantile_for_peak_priority_row -v
```

Expected: pass.

- [ ] **Step 6: Commit this checkpoint**

Run:

```powershell
git add notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py tests/test_forecast_model_upgrade_support.py
git commit -m "feat: add value-safe peak alert smoothing"
```

If git is unavailable, continue and record it.

---

### Task 3: Add Policy Comparison Metrics For Threshold Tuning

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
- Test: `tests/test_forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_notebook.py`

- [ ] **Step 1: Add failing support test for policy comparison**

Append this test method:

```python
    def test_compare_peak_alert_policies_scores_recall_precision_tradeoff(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            compare_peak_alert_policies,
        )

        actual = np.array([100.0, 500.0, 120.0, 480.0, 130.0, 460.0, 140.0, 150.0, 160.0, 170.0])
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 300.0, 120.0, 470.0, 130.0, 350.0, 140.0, 150.0, 160.0, 170.0],
                "peak_risk_overlay_score": [0.01, 0.99, 0.02, 0.98, 0.03, 0.70, 0.04, 0.69, 0.06, 0.07],
            }
        )
        policies = {
            "strict": PeakAlertPolicy(alert_quantile=0.90),
            "catch_more": PeakAlertPolicy(alert_quantile=0.60),
        }

        table = compare_peak_alert_policies(actual, forecast, policies, actual_peak_quantile=0.70)

        self.assertEqual(set(table["policy"]), {"strict", "catch_more"})
        strict_recall = float(table.loc[table["policy"] == "strict", "peak_recall"].iloc[0])
        catch_more_recall = float(table.loc[table["policy"] == "catch_more", "peak_recall"].iloc[0])
        self.assertGreater(catch_more_recall, strict_recall)
        self.assertIn("alert_quantile", table.columns)
        self.assertIn("peak_false_positive_count", table.columns)
```

- [ ] **Step 2: Run the failing support test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_compare_peak_alert_policies_scores_recall_precision_tradeoff -v
```

Expected: fail because `compare_peak_alert_policies` is missing.

- [ ] **Step 3: Implement policy comparison**

Add this function after `evaluate_forecast_components(...)`:

```python
def compare_peak_alert_policies(
    actual: np.ndarray | pd.Series,
    forecast: pd.DataFrame,
    policies: dict[str, PeakAlertPolicy],
    actual_peak_quantile: float = 0.90,
) -> pd.DataFrame:
    if "forecast_kw_import" not in forecast.columns:
        raise ValueError("forecast must include forecast_kw_import")
    if "peak_risk_overlay_score" not in forecast.columns:
        raise ValueError("forecast must include peak_risk_overlay_score")

    rows: list[dict[str, float | str]] = []
    for policy_name, policy in policies.items():
        score = smooth_peak_scores(
            forecast["peak_risk_overlay_score"].to_numpy(dtype=float),
            window=policy.score_smoothing_window,
        )
        metrics = evaluate_forecast(
            actual,
            forecast["forecast_kw_import"].to_numpy(dtype=float),
            peak_quantile=actual_peak_quantile,
            peak_score=score,
            predicted_peak_quantile=policy.alert_quantile,
            peak_match_window=policy.match_window_intervals,
        )
        rows.append(
            {
                "policy": policy_name,
                "alert_quantile": float(policy.alert_quantile),
                "match_window_intervals": float(policy.match_window_intervals),
                "score_smoothing_window": float(policy.score_smoothing_window),
                **metrics,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["peak_recall", "peak_precision", "peak_f1"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
```

- [ ] **Step 4: Run the policy comparison test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_compare_peak_alert_policies_scores_recall_precision_tradeoff -v
```

Expected: pass.

- [ ] **Step 5: Add notebook structure test for policy table wiring**

Add this method to `tests/test_forecast_model_upgrade_notebook.py`:

```python
    def test_notebook_wires_peak_alert_policy_comparison(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("PeakAlertPolicy = forecast_support.PeakAlertPolicy", all_source)
        self.assertIn("compare_peak_alert_policies = forecast_support.compare_peak_alert_policies", all_source)
        self.assertIn("PEAK_ALERT_POLICIES", all_source)
        self.assertIn("peak_policy_rows", all_source)
```

- [ ] **Step 6: Run the failing notebook test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook.ForecastModelUpgradeNotebookTests.test_notebook_wires_peak_alert_policy_comparison -v
```

Expected: fail until the notebook imports and rolling-origin cell are updated.

- [ ] **Step 7: Wire notebook constants and comparison output**

In the notebook import/setup cell, add bindings equivalent to:

```python
PeakAlertPolicy = forecast_support.PeakAlertPolicy
peak_alert_policy_for_site = forecast_support.peak_alert_policy_for_site
compare_peak_alert_policies = forecast_support.compare_peak_alert_policies

PEAK_ALERT_POLICIES = {
    "strict_15pct": PeakAlertPolicy(alert_quantile=0.85, match_window_intervals=2, score_smoothing_window=1),
    "current_20pct": PeakAlertPolicy(alert_quantile=0.80, match_window_intervals=2, score_smoothing_window=1),
    "catch_more_25pct": PeakAlertPolicy(alert_quantile=0.75, match_window_intervals=2, score_smoothing_window=1),
    "smoothed_20pct": PeakAlertPolicy(alert_quantile=0.80, match_window_intervals=2, score_smoothing_window=3),
}
```

In the rolling-origin cell, after producing a forecast with `peak_risk_overlay_score`, append rows equivalent to:

```python
policy_table = compare_peak_alert_policies(
    actual,
    forecast,
    PEAK_ALERT_POLICIES,
    actual_peak_quantile=PEAK_QUANTILE,
)
policy_table["site_id"] = site_id
policy_table["cutoff"] = cutoff
peak_policy_rows.extend(policy_table.to_dict("records"))
```

Initialize before the rolling loop:

```python
peak_policy_rows = []
```

Summarize after the rolling loop:

```python
peak_policy_summary = (
    pd.DataFrame(peak_policy_rows)
    .groupby("policy", as_index=False)[
        ["peak_precision", "peak_recall", "peak_f1", "peak_false_negative_count", "peak_false_positive_count", "md_peak_rank"]
    ]
    .mean()
    .sort_values(["peak_recall", "peak_precision"], ascending=[False, False])
)
display(peak_policy_summary)
```

- [ ] **Step 8: Run notebook structure tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_notebook -v
```

Expected: pass.

- [ ] **Step 9: Commit this checkpoint**

Run:

```powershell
git add notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb tests/test_forecast_model_upgrade_support.py tests/test_forecast_model_upgrade_notebook.py
git commit -m "feat: compare peak alert threshold policies"
```

If git is unavailable, continue and record it.

---

### Task 4: Add Forecast-Safe Ramp And Approaching-Peak Features

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Add failing test for new feature columns**

Append this test method:

```python
    def test_enhanced_features_include_ramp_and_peak_approach_signals(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import add_enhanced_features

        frame = synthetic_site_frame("ramp_features", has_solar=False, periods=950)
        prepared, feature_columns = add_enhanced_features(frame)

        expected = {
            "recent_slope_4",
            "recent_slope_8",
            "recent_acceleration_4",
            "gap_to_rolling_max_48",
            "rolling_max_ratio_48",
            "ramp_to_tariff_peak_interaction",
            "solar_ramp_to_daylight_interaction",
        }

        self.assertTrue(expected.issubset(set(feature_columns)))
        self.assertFalse(prepared[list(expected)].isna().any().any())
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_enhanced_features_include_ramp_and_peak_approach_signals -v
```

Expected: fail because the new columns do not exist.

- [ ] **Step 3: Implement the features in `add_enhanced_features(...)`**

After the existing rolling delta features, add:

```python
    ordered["recent_slope_4"] = (target.shift(1) - target.shift(5)) / 4.0
    ordered["recent_slope_8"] = (target.shift(1) - target.shift(9)) / 8.0
    ordered["recent_acceleration_4"] = ordered["recent_slope_4"] - ordered["recent_slope_4"].shift(4)
    ordered["gap_to_rolling_max_48"] = ordered["rolling_max_48"] - target.shift(1)
    ordered["rolling_max_ratio_48"] = target.shift(1) / ordered["rolling_max_48"].replace(0.0, np.nan)
    ordered["ramp_to_tariff_peak_interaction"] = ordered["recent_slope_4"] * ordered["tariff_peak"]
    ordered["solar_ramp_to_daylight_interaction"] = ordered["recent_slope_4"] * ordered["solar_daylight_interaction"]
```

Add these names to `feature_columns`:

```python
        "recent_slope_4",
        "recent_slope_8",
        "recent_acceleration_4",
        "gap_to_rolling_max_48",
        "rolling_max_ratio_48",
        "ramp_to_tariff_peak_interaction",
        "solar_ramp_to_daylight_interaction",
```

- [ ] **Step 4: Mirror the features in `enhanced_feature_row(...)`**

In `enhanced_feature_row(...)`, after existing rolling delta fields, add:

```python
    row["recent_slope_4"] = float((history[-1] - history[-5]) / 4.0) if len(history) >= 5 else 0.0
    row["recent_slope_8"] = float((history[-1] - history[-9]) / 8.0) if len(history) >= 9 else 0.0
    previous_slope_4 = float((history[-5] - history[-9]) / 4.0) if len(history) >= 9 else 0.0
    row["recent_acceleration_4"] = row["recent_slope_4"] - previous_slope_4
    rolling_max_48 = float(row["rolling_max_48"])
    last_value = float(history[-1]) if history else 0.0
    row["gap_to_rolling_max_48"] = rolling_max_48 - last_value
    row["rolling_max_ratio_48"] = last_value / rolling_max_48 if rolling_max_48 > 0 else 0.0
    row["ramp_to_tariff_peak_interaction"] = row["recent_slope_4"] * row["tariff_peak"]
    row["solar_ramp_to_daylight_interaction"] = row["recent_slope_4"] * row["solar_daylight_interaction"]
```

- [ ] **Step 5: Run the feature test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_enhanced_features_include_ramp_and_peak_approach_signals -v
```

Expected: pass.

- [ ] **Step 6: Run support regression tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support -v
```

Expected: pass. If the latest-fold SoL/Mi2 guardrail test fails, inspect feature ordering and recursive feature parity before changing thresholds.

- [ ] **Step 7: Commit this checkpoint**

Run:

```powershell
git add notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py tests/test_forecast_model_upgrade_support.py
git commit -m "feat: add ramp-aware forecast features"
```

If git is unavailable, continue and record it.

---

### Task 5: Add Value-Safe MD Calibration Experiment

**Files:**
- Modify: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Test: `tests/test_forecast_model_upgrade_support.py`

- [ ] **Step 1: Add failing test for MD calibration helper**

Append this test method:

```python
    def test_md_peak_calibration_adjusts_magnitude_without_changing_timing(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            apply_md_peak_calibration,
            fit_md_peak_calibration,
        )

        actual_peaks = np.array([400.0, 420.0, 410.0, 430.0])
        predicted_peaks = np.array([320.0, 335.0, 330.0, 340.0])
        correction = fit_md_peak_calibration(actual_peaks, predicted_peaks)
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 200.0, 340.0, 150.0],
                "peak_risk_score": [0.10, 0.20, 0.90, 0.30],
            }
        )

        corrected = apply_md_peak_calibration(forecast, correction)

        self.assertGreater(corrected["forecast_kw_import"].max(), forecast["forecast_kw_import"].max())
        self.assertEqual(int(corrected["forecast_kw_import"].idxmax()), int(forecast["forecast_kw_import"].idxmax()))
        self.assertIn("md_calibrated_kw_import", corrected.columns)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_md_peak_calibration_adjusts_magnitude_without_changing_timing -v
```

Expected: fail because `fit_md_peak_calibration` and `apply_md_peak_calibration` are missing.

- [ ] **Step 3: Implement bounded MD calibration**

Add this dataclass near other dataclasses:

```python
@dataclass(frozen=True)
class MdPeakCalibration:
    multiplier: float
    intercept_kw: float = 0.0
```

Add these helpers near calibration functions:

```python
def fit_md_peak_calibration(
    actual_peaks: np.ndarray | pd.Series,
    predicted_peaks: np.ndarray | pd.Series,
    min_multiplier: float = 0.85,
    max_multiplier: float = 1.20,
) -> MdPeakCalibration:
    actual_array = np.asarray(actual_peaks, dtype=float)
    predicted_array = np.asarray(predicted_peaks, dtype=float)
    valid = np.isfinite(actual_array) & np.isfinite(predicted_array) & (predicted_array > 0)
    if not np.any(valid):
        return MdPeakCalibration(multiplier=1.0)

    ratios = actual_array[valid] / predicted_array[valid]
    multiplier = float(np.clip(np.median(ratios), min_multiplier, max_multiplier))
    return MdPeakCalibration(multiplier=multiplier)


def apply_md_peak_calibration(
    forecast: pd.DataFrame,
    calibration: MdPeakCalibration,
    score_column: str = "peak_risk_score",
    top_quantile: float = 0.80,
) -> pd.DataFrame:
    corrected = forecast.copy()
    if corrected.empty or "forecast_kw_import" not in corrected.columns:
        corrected["md_calibrated_kw_import"] = []
        return corrected

    values = corrected["forecast_kw_import"].astype(float).to_numpy()
    adjusted = values.copy()
    if score_column in corrected.columns:
        scores = corrected[score_column].astype(float).to_numpy()
    else:
        scores = values

    threshold = float(np.quantile(scores, top_quantile))
    mask = scores >= threshold
    adjusted[mask] = np.maximum(0.0, calibration.intercept_kw + calibration.multiplier * adjusted[mask])
    corrected["md_calibrated_kw_import"] = adjusted
    return corrected
```

- [ ] **Step 4: Run the MD calibration test**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support.ForecastModelUpgradeSupportTests.test_md_peak_calibration_adjusts_magnitude_without_changing_timing -v
```

Expected: pass.

- [ ] **Step 5: Add notebook experiment wiring**

In the notebook, add imports:

```python
MdPeakCalibration = forecast_support.MdPeakCalibration
fit_md_peak_calibration = forecast_support.fit_md_peak_calibration
apply_md_peak_calibration = forecast_support.apply_md_peak_calibration
```

In rolling-origin evaluation, create a candidate row named `enhanced_md_calibrated` only after computing a calibration from past folds or past inner validation peaks. Evaluate it separately from `enhanced` and `enhanced_peak_priority`.

Use this structure:

```python
md_calibrated_forecast = apply_md_peak_calibration(forecast, md_calibration)
md_calibrated_metrics = evaluate_forecast(
    actual,
    md_calibrated_forecast["md_calibrated_kw_import"].to_numpy(dtype=float),
    peak_quantile=PEAK_QUANTILE,
    peak_match_window=PEAK_MATCH_WINDOW,
)
```

- [ ] **Step 6: Run support tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support -v
```

Expected: pass.

- [ ] **Step 7: Commit this checkpoint**

Run:

```powershell
git add notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb tests/test_forecast_model_upgrade_support.py
git commit -m "feat: add bounded MD peak calibration experiment"
```

If git is unavailable, continue and record it.

---

### Task 6: Rerun Benchmarks And Update Source Of Truth

**Files:**
- Modify: `docs/forecast_model_upgrade_source_of_truth.md`
- Modify: `docs/status.md`
- Modify: `PROJECT_STATUS.md`

- [ ] **Step 1: Run fast regression tests**

Run:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support tests.test_forecast_model_upgrade_notebook -v
```

Expected: pass.

- [ ] **Step 2: Run full regression tests**

Run:

```powershell
python -m unittest -v
```

Expected: pass.

- [ ] **Step 3: Rerun notebook cells for LOSO, rolling-origin, and 48-hour comparison**

Open `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb` and run cells top-to-bottom through the benchmark output cells. Save updated CSV outputs under:

```text
notebooks/model_upgrade_inspection/_latest_rerun_metrics/
```

Required outputs:

```text
rolling_model_summary.csv
rolling_summary.csv
loso_model_results.csv
comparison_48h_model_results.csv
```

- [ ] **Step 4: Accept or reject policy candidate**

Accept the new default policy only if the fresh rolling-origin summary meets all of:

```text
enhanced_peak_priority peak_recall >= 0.75
enhanced_peak_priority peak_precision > 0.395
enhanced_peak_priority peak_false_negative_count <= 1.50
enhanced_peak_priority rmse_kw == enhanced rmse_kw
enhanced_peak_priority md_abs_error_kw == enhanced md_abs_error_kw
```

Accept `enhanced_md_calibrated` as value-model candidate only if it meets:

```text
enhanced_md_calibrated md_abs_error_kw <= 97.04
enhanced_md_calibrated wape_pct <= enhanced wape_pct
enhanced_md_calibrated rmse_kw <= enhanced rmse_kw * 1.03
```

- [ ] **Step 5: Generate the benchmark markdown table**

After the notebook rerun, run this in a notebook cell or a short Python console with the fresh `rolling_model_summary` loaded:

```python
benchmark_columns = [
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
candidate_models = ["enhanced", "enhanced_peak_priority", "enhanced_md_calibrated"]
benchmark_table = rolling_model_summary.loc[
    rolling_model_summary["model"].isin(candidate_models),
    benchmark_columns,
].copy()
print(benchmark_table.to_markdown(index=False))
```

Expected: a markdown table with concrete numeric values for the accepted rerun models.

- [ ] **Step 6: Update source-of-truth docs**

In `docs/forecast_model_upgrade_source_of_truth.md`, add a new dated section under `Latest Verified Results`. The section must contain this heading, the verification sentence, the exact numeric markdown table printed in the previous step, and the decision bullets that match the acceptance outcome:

```markdown
### E. 2026-05-04 Peak Alert Refinement Rerun

Verified on 2026-05-04 after policy comparison, smoothing, ramp features, and MD calibration experiments.
```

Insert the exact numeric markdown table immediately after the verification sentence. Then add the decision block:

```markdown

Decision:

- If a new policy satisfies the acceptance guardrails, write: `Accepted peak-alert policy: smoothed_20pct.`
- If no new policy satisfies the acceptance guardrails, write: `Accepted peak-alert policy: current_20pct retained.`
- If MD calibration satisfies the value-model criteria, write: `Accepted value model: enhanced_md_calibrated.`
- If MD calibration does not satisfy the value-model criteria, write: `Accepted value model: enhanced.`
- Write: `App promotion status: deferred pending user metric review.`
```

- [ ] **Step 7: Update status docs**

In `docs/status.md`, update:

```markdown
## In Progress
- Model-quality refinement has a benchmarked candidate policy from the 2026-05-04 peak-alert refinement plan.

## Next Actions
- Review the fresh notebook metric score before deciding whether any Streamlit app promotion should happen.
```

In `PROJECT_STATUS.md`, add a matching short bullet:

```markdown
- 2026-05-04: Ran the peak-alert refinement plan and recorded the accepted notebook benchmark in `docs/forecast_model_upgrade_source_of_truth.md`; app promotion remains deferred pending metric review.
```

- [ ] **Step 8: Commit benchmark docs**

Run:

```powershell
git add docs/forecast_model_upgrade_source_of_truth.md docs/status.md PROJECT_STATUS.md notebooks/model_upgrade_inspection/_latest_rerun_metrics
git commit -m "docs: record peak alert refinement benchmark"
```

If git is unavailable, continue and record it.

---

### Deferred Appendix: Future App Promotion After Metric Review

Do not execute this section as part of the active plan. Use it only after the user reviews the fresh notebook metric score and explicitly approves app promotion.

**Files:**
- Modify: `trex_energy/forecasting.py`
- Modify: `app.py`
- Test: `tests/test_forecasting.py`

- [ ] **Future Step 1: Add failing production forecast test**

Add this test method to `tests/test_forecasting.py`:

```python
    def test_enhanced_forecast_exposes_separate_md_risk_alert_columns(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        forecast = forecast_next_intervals(frames=frames, target_frame=frames[0], horizon=48)

        self.assertIn("peak_risk_score", forecast.columns)
        self.assertIn("is_predicted_peak", forecast.columns)
        self.assertIn("md_risk_alert_score", forecast.columns)
        self.assertIn("is_md_risk_alert", forecast.columns)
        self.assertTrue(np.allclose(forecast["forecast_kw_import"], forecast["forecast_kw_import"]))
```

- [ ] **Future Step 2: Run the failing production test**

Run:

```powershell
python -m unittest tests.test_forecasting.ForecastingTests.test_enhanced_forecast_exposes_separate_md_risk_alert_columns -v
```

Expected: fail because `md_risk_alert_score` and `is_md_risk_alert` are missing.

- [ ] **Future Step 3: Implement production-safe alert columns**

In `trex_energy/forecasting.py`, add a small helper near `_add_peak_flags(...)`:

```python
def _add_md_risk_alerts(forecast: pd.DataFrame, alert_quantile: float = 0.80) -> pd.DataFrame:
    tagged = forecast.copy()
    if tagged.empty:
        tagged["md_risk_alert_score"] = []
        tagged["is_md_risk_alert"] = []
        return tagged

    score = tagged["peak_risk_score"].astype(float).to_numpy()
    threshold = float(np.quantile(score, alert_quantile))
    tagged["md_risk_alert_score"] = score
    tagged["is_md_risk_alert"] = score >= threshold
    return tagged
```

In `forecast_next_intervals(...)`, wrap successful enhanced forecasts with:

```python
        forecast = forecast_with_enhanced_model(
            model=enhanced.model,
            feature_columns=enhanced.feature_columns,
            target_frame=target_frame,
            horizon=horizon,
            blend_weight=blend_weight,
            calibration=calibration,
            normalize_targets=enhanced.normalize_targets,
            site_scale=inferred_scale,
        )
        return _add_md_risk_alerts(forecast)
```

Also wrap fallback returns:

```python
        return _add_md_risk_alerts(_forecast_with_baseline_model(baseline_model, target_frame, horizon))
```

- [ ] **Future Step 4: Run production forecast tests**

Run:

```powershell
python -m unittest tests.test_forecasting -v
```

Expected: pass.

- [ ] **Future Step 5: Update app labels**

In `app.py`, change peak marker selection from:

```python
    peak_markers = forecast.loc[forecast["is_predicted_peak"]]
```

to:

```python
    alert_column = "is_md_risk_alert" if "is_md_risk_alert" in forecast.columns else "is_predicted_peak"
    peak_markers = forecast.loc[forecast[alert_column]]
```

Change marker name from:

```python
            name="Predicted peak",
```

to:

```python
            name="MD risk alert",
```

- [ ] **Future Step 6: Run full regression tests**

Run:

```powershell
python -m unittest -v
```

Expected: pass.

- [ ] **Future Step 7: Update docs after app promotion**

In `docs/architecture.md`, add to the forecasting output section:

```markdown
- production forecasts expose `md_risk_alert_score` and `is_md_risk_alert` separately from `forecast_kw_import`
```

In `docs/status.md`, move app promotion from `Next Actions` to `Completed`.

In `PROJECT_STATUS.md`, add:

```markdown
- 2026-05-04: Promoted the accepted MD-risk alert output into the Streamlit forecast path with alert columns separate from forecast kW.
```

- [ ] **Future Step 8: Commit app promotion**

Run:

```powershell
git add trex_energy/forecasting.py app.py tests/test_forecasting.py docs/architecture.md docs/status.md PROJECT_STATUS.md
git commit -m "feat: expose MD risk alerts in app forecast"
```

If git is unavailable, continue and record it.

---

## Verification Checklist

Run these before claiming the active notebook refinement branch is complete:

```powershell
python -m unittest tests.test_forecast_model_upgrade_support -v
python -m unittest tests.test_forecast_model_upgrade_notebook -v
python -m unittest -v
```

Then verify the latest benchmark tables in:

```text
notebooks/model_upgrade_inspection/_latest_rerun_metrics/
docs/forecast_model_upgrade_source_of_truth.md
```

Completion means:

- peak-alert recall remains high,
- peak-alert precision improves or the current policy is explicitly retained,
- MD magnitude calibration is accepted only if value metrics improve,
- docs are updated with the accepted notebook decision,
- app promotion remains deferred until the user approves it after metric review.
