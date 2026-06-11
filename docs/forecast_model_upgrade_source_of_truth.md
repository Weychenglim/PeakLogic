# Forecast Model Upgrade Source of Truth

Last updated: 2026-05-05 (LightGBM quantile tiny proof)

## Purpose

This document is the durable reference for the forecasting-model upgrade work in the notebook experiment area. It records:

- what changed
- what is active today versus only scaffolded
- the latest verified results
- what future sessions should use as the starting point

This is the source of truth for the notebook workflow under `notebooks/model_upgrade_inspection/`.

## Canonical Files

- Notebook: `notebooks/model_upgrade_inspection/forecast_model_upgrade_inspection.ipynb`
- Shared helper module: `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`
- Notebook regression tests: `tests/test_forecast_model_upgrade_notebook.py`
- Support-layer regression tests: `tests/test_forecast_model_upgrade_support.py`

## Current Model Shape

The current notebook uses a single Ridge-based forecasting family with recursive multi-step forecasting. It is not a direct multi-horizon redesign.

Active ingredients:

- 30-minute regularization with conservative interpolation and imputation
- single global pooled Ridge training by default, with site-local normalization
- enhanced lag, rolling, and regime features
- hybrid recursive forecast using model output plus a seasonal anchor
- regime-aware calibration
- bias-aware blend-weight selection that now penalizes bias and drift, not only RMSE and MD error
- solar-specific daytime guardrails, with a softened rolling variant for solar sites
- non-solar weekly-anchor disagreement safeguard
- LOSO evaluation
- rolling-origin evaluation using pooled training frames plus site-local history for the evaluated site
- baseline comparison against `ridge_only` and `seasonal`
- experimental peak-priority overlay candidate named `enhanced_peak_priority`

Not active by default:

- segmented solar vs non-solar pooled training exists in the helper module, but the notebook does not enable it by default
- regime-specific blend-weight search is still available in the notebook code path, but it is no longer used in the rolling-origin loop
- horizon-bucket residual correction remains available in the helper module, but it was rolled back from the active notebook path after a regression rerun
- late-horizon peak-envelope uplift exists as a notebook rolling-origin candidate named `enhanced_late_peak_uplift`, but it is not promoted into the default `enhanced` value forecast or the production app
- direct-horizon scikit-learn `HistGradientBoostingRegressor` exists as a notebook rolling-origin candidate named `direct_hgb`, but it is rejected for now after a metric regression on E and Mi2
- direct-horizon LightGBM quantile helpers and notebook smoke wiring exist, but they are not accepted as a value model after the first capped E-only proof; the notebook caps this candidate to recent local rows and a small estimator count to avoid interactive runtime blowups
- no DirRec or direct multi-horizon redesign has been adopted

## Implemented Modifications

### 1. Code Structure and Reproducibility

- Forecast helpers were moved out of the notebook into `forecast_model_upgrade_support.py`.
- The notebook import cell was made reload-safe so stale module state does not silently survive notebook reruns.
- Regression tests were added for notebook structure and support-layer behavior.

Why it matters:

- future sessions can patch one helper module instead of editing large notebook cells
- reruns are more reproducible
- import regressions like missing helper functions are easier to catch

### 2. Feature Engineering Upgrades

Added weekly memory:

- `lag_336`
- `lag_672`

Added regime features:

- `is_monday`
- `is_post_weekend`
- `weekday_daylight`
- `same_slot_prev_week_delta`
- `same_slot_day_vs_week_gap`
- rolling delta mean and std features

Why it matters:

- SoL needed weekly context to avoid Monday collapse
- E and other non-solar sites need clearer day-versus-week memory than short lags alone

### 3. Seasonal Anchor Upgrade

The previous-day-only anchor was replaced by a weekday-aware daily plus weekly anchor.

Current behavior:

- Monday: more weight on previous week
- weekday daylight: balanced daily plus weekly anchor
- weekend and non-daylight: more previous-day influence

This fixed the original SoL Monday failure mode, but later revealed a different non-solar failure mode for `E`.

### 4. Solar Daytime Guardrails

Added or tightened solar-only safeguards for recursive forecasts:

- daytime floor behavior
- Monday daylight step-up allowance
- solar-specific upward and downward movement controls
- optional floor enablement in `site_evaluation_settings`

Why it matters:

- these changes were introduced to stop SoL from collapsing during weekday solar daylight ramps

### 5. Non-Solar Weekly-Anchor Disagreement Safeguard

Added a narrow safeguard for non-solar forecasts when `lag_48` and `lag_336` strongly disagree.

Current rule:

- if `has_solar is False` and the weekly-versus-daily gap ratio is greater than `0.20`
- clip the previous-week anchor toward the previous-day level
- cap weekly anchor weight at `0.15`

Why it was added:

- `2. Load Profile (No Solar) E` had a bad 48-hour window where the previous week was far above the current regime
- the weekly anchor was pulling the forecast too high, and recursion then amplified the error

### 6. Evaluation Settings and Shared Defaults

The helper module now centralizes site-level evaluation defaults through `site_evaluation_settings(...)`.

Current split:

- solar sites use solar-specific blend and guardrail settings
- non-solar sites use a simpler setting set with no solar guardrails

Also active:

- site-local target scaling for pooled training and inversion
- daily-spaced rolling-origin cutoffs to improve weekday coverage

### 7. Training Strategy Simplification for Small Site Counts

The hard solar vs non-solar base-model split was removed from the default path.

Current behavior:

- `fit_global_enhanced_ridge(...)` now defaults to one global base model
- `has_solar` remains an input feature instead of a hard training partition
- segmented solar/non-solar base training is only allowed when explicitly enabled and when both segments meet a minimum site-count threshold

Why it matters:

- with only a few sites, hard partitioning was too sample-hungry and brittle
- the dominant observed failure mode was regime bias and shape mismatch, not obviously the wrong global model family
- this keeps the code ready for future competition datasets without forcing fragmentation today

### 8. Controlled Solar Guardrail Softening

The forecast path now exposes the two most bias-sensitive solar daytime controls as explicit parameters:

- `solar_daytime_floor_enabled`
- `solar_monday_step_up_bonus`

The daytime floor and Monday step-up logic were not removed. They were made controllable so the notebook can test a softened solar path without forking the forecasting implementation.

Why it matters:

- this reduces the risk of solar daytime positive bias
- it keeps the original anti-collapse guardrails available
- it makes future tuning safer and easier to explain

### 9. Evaluation and Reporting Cleanup

The notebook now reports more than raw enhanced-only RMSE:

- `MAE`
- `RMSE`
- `mean_error_kw`
- `WAPE`
- `sMAPE`
- `MAPE`
- `NRMSE / median`
- `NRMSE / peak`
- `peak_precision`
- `peak_recall`
- `peak_time_error_intervals`
- `MD abs error`

The notebook also now compares:

- `enhanced`
- `ridge_only`
- `seasonal`

for:

- LOSO
- rolling-origin
- 48-hour comparison windows

### 10. Lightweight Experiment Variants

The notebook now defines a small variant layer through `EXPERIMENT_VARIANTS` and `variant_bundle(...)`.

Current variants:

- `A`: `global_regime_current`
- `B`: `global_regime_softened`
- `C`: `seasonal_anchor_baseline`

Current intended use:

- LOSO remains on the existing comparison path while keeping the variant wiring available
- rolling-origin uses Variant `B` for solar sites and Variant `A` for non-solar sites
- the appended latest-fold comparison cell is for lightweight comparison only and is not yet the official scoreboard

### 11. Plotting and Demo Views

The notebook keeps the 48-hour comparison view for the other three sites, not SoL:

- `E`
- `SuN`
- `Mi2`

The comparison dataframe now also stores:

- `actual_kw_import`
- `enhanced_kw_import`
- `ridge_only_kw_import`
- `seasonal_kw_import`

This makes future demo or diagnostic plots easier to extend.

### 12. Notebook Evaluation Alignment Fixes

The later session also corrected two notebook-level evaluation mismatches that were affecting trust in the experiment workflow.

Current behavior:

- the LOSO loop now chooses its variant from `target_has_solar`, so it does not depend on a stale `site_has_solar` variable from a previously executed cell
- the rolling-origin loop now fits the pooled Ridge model on the current site's available training history plus the other sites, instead of training on `[train_frame]` alone
- the lightweight latest-fold variant comparison now uses the same pooled-training idea as rolling-origin

Why it matters:

- the LOSO section is now rerunnable from a fresh notebook state without hidden variable leakage
- rolling-origin is now better aligned with the documented pooled-training strategy instead of accidentally evaluating a different one-site regime
- future comparisons between LOSO, rolling-origin, and the lightweight variant cell are easier to interpret because they now share the same high-level training story

### 13. Bias-Aware Blend Selection and Horizon Residual Correction

The later session also added two low-risk model enhancements aimed at the remaining rolling-origin weakness.

Current behavior:

- `select_blend_weight(...)` now scores candidate blend weights using not just RMSE and MD abs error, but also absolute mean error, cumulative error, and drift slope
- `fit_horizon_residual_adjustment(...)` remains available in the helper module for future experiments
- the active notebook path does not currently fit or apply residual correction after the rollback

Why it matters:

- the main documented remaining issue was rolling bias for `E` and `Mi2`, so blend selection needed to optimize for operational bias and drift instead of raw fit alone
- the residual layer gives the current recursive Ridge family a small horizon-aware correction without forcing a direct multi-horizon redesign
- this keeps the current notebook architecture intact while testing a more targeted fix for error accumulation over the 48-step horizon

Important later finding:

- activating residual correction in the notebook path materially regressed overall metrics
- the helper remains available in code today, but it is not part of the active notebook workflow
- future sessions should treat residual correction as exploratory until a safer gated version is demonstrated

### 14. Peak-Priority Overlay Experiment

The 2026-05-03 session added a dependency-free peak-risk overlay in the notebook experiment path.

Current behavior:

- `evaluate_forecast(...)` now reports `peak_f1`, false positive and false negative counts, `peak_capture_rate_at_k`, and `md_peak_rank`
- `select_blend_weight(...)` remains forecast-value safe and uses RMSE, MD error, bias, cumulative error, and drift
- `fit_peak_risk_overlay(...)` trains a scikit-learn `LogisticRegression` peak-risk model on forecast-safe engineered features
- `apply_peak_risk_overlay(...)` adds `peak_risk_overlay_score` and updates peak-risk flags without changing `forecast_kw_import`
- `evaluate_forecast_components(...)` reports a fourth comparison row, `enhanced_peak_priority`, when overlay scores are present
- the accepted operational benchmark uses top-20% overlay alerts via `PEAK_ALERT_QUANTILE = 0.80`
- the accepted operational benchmark gives credit for alerts within `PEAK_MATCH_WINDOW = 2` intervals, or plus/minus one hour
- `ESUM_T_Rex_Model_Building.ipynb` is reference only; it is not the active source of truth because it predicts `Gross Load` and uses features that are not available for future `kw_import` forecasting

Decision:

- keep `enhanced_peak_priority` as the leading notebook peak-alert candidate
- do not change forecast values; use the overlay only for peak-risk ranking and alert flags
- peak-priority scoring is for candidate assessment only; it must not drive `select_blend_weight(...)`
- promotion into the production app should still be a separate implementation step
- forecast-value metrics are unchanged by design because the overlay changes peak ranking and flags only

## Latest Verified Results

Important note:

- the results below now reflect a fresh rerun of the active notebook evaluation path after adding the peak-priority overlay
- the no-residual pooled recursive model remains the active baseline
- `enhanced_peak_priority` is benchmarked as the current leading peak-alert candidate, but not yet integrated into the app
- regression tests still pass, so the current state is both runnable and benchmarked

### A. LOSO 48-Step Results, Enhanced Versus Tuned Peak-Priority Overlay

Verified on 2026-05-03 from a fresh rerun after threshold/window tuning:

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 97.13 | 21.29 | 60.70 | 0.40 | 0.40 | 0.40 | 3.0 | 3.0 | 16.50 | 18.5 |
| enhanced_peak_priority | 97.13 | 21.29 | 60.70 | 0.45 | 0.90 | 0.60 | 0.5 | 3.5 | 10.75 | 18.5 |

Interpretation:

- LOSO peak recall improves from `0.40` to `0.90`
- average missed peaks drops from `3.0` to `0.5`
- mean MD peak rank improves from `16.50` to `10.75`
- RMSE, WAPE, and MD abs error are unchanged because the overlay does not alter forecast values
- false positives rise modestly from `3.0` to `3.5`, which is acceptable under the catch-peaks-first policy

### B. Rolling-Origin Enhanced Versus Tuned Peak-Priority Overlay

Verified on 2026-05-03 from a fresh rerun after threshold/window tuning:

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.40 | 26.91 | 114.17 | 0.485 | 0.477 | 0.480 | 2.750 | 2.325 | 14.85 | 9.83 |
| enhanced_peak_priority | 141.40 | 26.91 | 114.17 | 0.395 | 0.782 | 0.524 | 1.225 | 4.225 | 12.30 | 9.83 |

Interpretation:

- rolling peak recall improves from `0.477` to `0.782`, exceeding the planned `+0.10` acceptance bar
- missed peaks drop from `2.750` to `1.225`
- rolling MD peak rank improves from `14.85` to `12.30`
- precision drops from `0.485` to `0.395` because the overlay intentionally emits more alerts
- forecast-value metrics remain unchanged, so this is a peak-alert improvement, not a demand-value improvement

### C. 2026-05-04 Rolling-Origin Peak-Alert Refinement Rerun

Verified on 2026-05-04 after adding explicit peak-alert policies, alert-score smoothing, ramp/approaching-peak features, and a bounded MD peak calibration experiment.

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.06 | 26.88 | 114.04 | 0.480 | 0.472 | 0.475 | 2.775 | 2.325 | 14.95 | 9.25 |
| enhanced_peak_priority | 141.06 | 26.88 | 114.04 | 0.393 | 0.776 | 0.521 | 1.250 | 4.350 | 12.33 | 9.25 |
| enhanced_md_calibrated | 151.73 | 28.10 | 111.95 | 0.515 | 0.507 | 0.510 | 2.600 | 2.300 | 14.60 | 9.03 |

Peak policy comparison:

| Policy | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| catch_more_25pct | 0.352 | 0.836 | 0.495 | 0.950 | 5.200 | 12.33 |
| current_20pct | 0.392 | 0.776 | 0.521 | 1.250 | 4.350 | 12.33 |
| smoothed_20pct | 0.373 | 0.737 | 0.494 | 1.450 | 4.075 | 12.48 |
| strict_15pct | 0.444 | 0.704 | 0.544 | 1.625 | 3.350 | 12.33 |

Decision:

- accepted peak-alert policy: `current_20pct` retained for notebook metric review because it is the only tested policy that keeps rolling recall above `0.75` while avoiding the larger false-positive burden of `catch_more_25pct`
- no new precision-improving policy is accepted yet; `strict_15pct` improves precision but drops recall below the catch-peaks-first guardrail
- accepted value model: `enhanced` retained
- `enhanced_md_calibrated` is not accepted because MD abs error improves only slightly while RMSE and WAPE regress
- production app promotion status: deferred pending user metric review
- notebook rerun wrote refreshed CSVs under `notebooks/model_upgrade_inspection/_latest_rerun_metrics/`
- markdown printing failed only because optional package `tabulate` is not installed; CSV outputs were written successfully

### D. 2026-05-04 Diagnosis And Confirmed-Alert Rerun

Verified on 2026-05-04 after adding rolling-origin error diagnostics, confirmed-alert scoring, and alert episode summaries.

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.06 | 26.88 | 114.04 | 0.480 | 0.472 | 0.475 | 2.775 | 2.325 | 14.95 | 9.25 |
| enhanced_peak_priority | 141.06 | 26.88 | 114.04 | 0.393 | 0.776 | 0.521 | 1.250 | 4.350 | 12.33 | 9.25 |
| enhanced_peak_confirmed | 141.06 | 26.88 | 114.04 | 0.395 | 0.630 | 0.360 | 2.000 | 12.550 | 23.95 | 9.25 |
| enhanced_md_calibrated | 151.73 | 28.10 | 111.95 | 0.515 | 0.507 | 0.510 | 2.600 | 2.300 | 14.60 | 9.03 |

Top diagnostic failure regimes by mean absolute error:

| Site | Regime | Horizon | Peak regime | Mean error kW | Mean abs error kW |
| --- | --- | --- | --- | ---: | ---: |
| E | non-solar night | late | actual peak | -256.89 | 264.50 |
| Mi2 | solar daylight | late | actual peak | -257.72 | 257.72 |
| E | non-solar daylight | middle | actual peak | -117.08 | 218.55 |
| Mi2 | solar night | late | actual peak | -216.12 | 216.12 |
| Mi2 | solar night | early | actual peak | -203.40 | 203.40 |

Decision:

- accepted peak-alert policy: `current_20pct` retained
- `enhanced_peak_confirmed` is rejected because recall falls to `0.630`, false negatives rise to `2.000`, and MD peak rank worsens even though precision rises only slightly
- `enhanced_peak_priority` remains the leading notebook alert candidate
- diagnostic finding: the largest forecast-value errors are underpredicted actual peaks on `E` and `Mi2`, especially late-horizon peaks
- next modeling direction should target late-horizon actual-peak underprediction, not stricter alert confirmation
- production app promotion status: deferred pending user metric review

### E. 2026-05-04 Late-Horizon Peak Uplift Rerun

Verified on 2026-05-04 after adding a notebook-only `enhanced_late_peak_uplift` candidate that uses same-site historical peak envelopes to lift high-risk late-horizon forecast values with a hard uplift cap.

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.06 | 26.88 | 114.04 | 0.480 | 0.472 | 0.475 | 2.775 | 2.325 | 14.95 | 9.25 |
| enhanced_late_peak_uplift | 140.80 | 26.69 | 97.57 | 0.485 | 0.477 | 0.480 | 2.750 | 2.225 | 14.15 | 9.43 |
| enhanced_peak_priority | 141.06 | 26.88 | 114.04 | 0.393 | 0.776 | 0.521 | 1.250 | 4.350 | 12.33 | 9.25 |
| enhanced_md_calibrated | 151.73 | 28.10 | 111.95 | 0.515 | 0.507 | 0.510 | 2.600 | 2.300 | 14.60 | 9.03 |
| enhanced_peak_confirmed | 141.06 | 26.88 | 114.04 | 0.395 | 0.630 | 0.360 | 2.000 | 12.550 | 23.95 | 9.25 |

Site-level value impact for the uplift candidate:

| Site | Enhanced MD abs error kW | Uplift MD abs error kW | RMSE impact | WAPE impact |
| --- | ---: | ---: | ---: | ---: |
| SoL | 110.49 | 98.60 | improved | improved |
| E | 140.87 | 140.06 | slightly improved MD, but RMSE/WAPE worsened slightly |
| SuN | 72.17 | 37.56 | improved | improved |
| Mi2 | 132.61 | 114.04 | improved | improved |

Decision:

- accepted default value model: `enhanced` retained for now
- candidate status: keep `enhanced_late_peak_uplift` as a promising notebook value-model candidate for review
- reason: overall MD abs error improves from `114.04` to `97.57` kW while RMSE and WAPE improve slightly, but the original `E` target only improves marginally and its RMSE/WAPE worsen slightly
- accepted peak-alert policy: `enhanced_peak_priority/current_20pct` retained
- production app promotion status: deferred pending user metric review
- refreshed rolling CSVs were written under `notebooks/model_upgrade_inspection/_latest_rerun_metrics/`

Follow-up diagnostic:

- candidate-level diagnostics now compare `enhanced` and `enhanced_late_peak_uplift` by site, light regime, horizon bucket, and actual-peak regime
- for `E / non_solar / night / late / actual_peak`, the uplift candidate leaves the mean error unchanged at about `-256.89` kW and mean absolute error unchanged at about `264.50` kW
- root cause: the same-slot historical envelope is below the already-underpredicted forecast on several high-risk E late-night peaks, while other late-night underpredictions are not selected by the overlay score gate
- a broader non-solar night site-peak floor fallback was tested as an explicit helper option, but it is not enabled in the active notebook path because it regressed the rolling uplift candidate from `97.57` to `110.24` kW MD abs error and raised RMSE to `142.29` kW

### F. 2026-05-04 Direct-Horizon Boosted Candidate Rerun

Verified on 2026-05-04 after adding a notebook-only direct-horizon boosted candidate named `direct_hgb` using scikit-learn `HistGradientBoostingRegressor`.

Dependency note:

- `lightgbm` and `xgboost` were not installed in the current environment
- `direct_hgb` was chosen first because scikit-learn is already a project dependency
- the notebook sets thread-count environment guards before sklearn imports because HGB binning attempted to open a Windows threadpool that can fail under sandbox permissions

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 141.06 | 26.88 | 114.04 | 0.480 | 0.472 | 0.475 | 2.775 | 2.325 | 14.95 | 9.25 |
| enhanced_late_peak_uplift | 140.80 | 26.69 | 97.57 | 0.485 | 0.477 | 0.480 | 2.750 | 2.225 | 14.15 | 9.43 |
| direct_hgb | 150.18 | 21.08 | 160.07 | 0.414 | 0.466 | 0.432 | 2.750 | 2.850 | 12.80 | 10.45 |
| enhanced_peak_priority | 141.06 | 26.88 | 114.04 | 0.393 | 0.776 | 0.521 | 1.250 | 4.350 | 12.33 | 9.25 |

Site-level value impact for `direct_hgb`:

| Site | Direct HGB RMSE kW | Direct HGB WAPE % | Direct HGB MD abs error kW | Interpretation |
| --- | ---: | ---: | ---: | --- |
| SoL | 116.09 | 19.87 | 98.32 | improves RMSE/WAPE and roughly matches uplift MD error |
| E | 231.94 | 21.86 | 290.62 | fails badly versus both `enhanced` and uplift |
| SuN | 42.85 | 26.38 | 68.64 | improves RMSE/WAPE but not enough to offset E/Mi2 |
| Mi2 | 209.85 | 16.21 | 182.68 | fails versus both `enhanced` and uplift |

E late actual-peak diagnostics:

| Model | Light regime | Mean error kW | Mean abs error kW |
| --- | --- | ---: | ---: |
| enhanced | daylight | -88.65 | 90.93 |
| enhanced_late_peak_uplift | daylight | -88.65 | 90.93 |
| direct_hgb | daylight | -168.97 | 168.97 |
| enhanced | night | -256.89 | 264.50 |
| enhanced_late_peak_uplift | night | -256.89 | 264.50 |
| direct_hgb | night | -372.99 | 372.99 |

Decision:

- accepted default value model: `enhanced` retained for now
- leading value candidate for review: `enhanced_late_peak_uplift`
- rejected value candidate: `direct_hgb`
- reason: `direct_hgb` improves WAPE and helps SoL/SuN, but it materially worsens the operational target metrics: MD abs error rises to `160.07` kW, E MD abs error rises to `290.62` kW, Mi2 MD abs error rises to `182.68` kW, and E late actual-peak underprediction worsens
- accepted peak-alert policy: `enhanced_peak_priority/current_20pct` retained
- production app promotion status: deferred pending user metric review

### G. 2026-05-05 LightGBM Quantile Tiny Proof

Verified on 2026-05-05 after installing `lightgbm==4.6.0` and adding notebook-only direct-horizon quantile helpers.

Runtime finding:

- the unbounded rolling benchmark is not suitable for interactive use because it multiplies direct-horizon training rows across sites, folds, quantiles, and candidate models
- app usage should not run rolling-origin evaluation on upload
- capped app-like single-site training is fast enough for experimentation: on E with 1,200 recent rows, row building took about `1.24` to `1.33` seconds, LightGBM fitting took about `1.90` to `1.97` seconds, and forecasting took about `0.04` seconds

Tiny proof metrics:

| Site / fold | Candidate | RMSE kW | WAPE % | Mean error kW | MD abs error kW | Peak recall | False negatives | MD peak rank |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E fold 10 | p50 | 151.30 | 18.25 | 118.38 | 56.10 | 0.60 | 2.0 | 20.0 |
| E fold 10 | p90 | 440.95 | 60.60 | 429.72 | 218.79 | 1.00 | 0.0 | 14.0 |
| E fold 10 | MD-risk head over p50 | 151.30 | 18.25 | 118.38 | 56.10 | 1.00 | 0.0 | 14.0 |
| E fold 3 | p50 | 360.20 | 26.72 | -327.64 | 635.29 | 1.00 | 0.0 | 23.0 |
| E fold 3 | p90 | 144.29 | 9.83 | 30.55 | 233.19 | 0.20 | 4.0 | 1.0 |
| E fold 3 | MD-risk head over p50 | 360.20 | 26.72 | -327.64 | 635.29 | 0.60 | 2.0 | 10.0 |

Fold-specific comparison:

- E fold 3 `enhanced` had RMSE `231.54`, WAPE `16.45%`, mean error `-183.89`, and MD abs error `238.07`
- E fold 3 LightGBM p90 improved RMSE/WAPE and reduced the late-night actual-peak mean error from about `-315.45` kW on `enhanced` to about `-170.52` kW, but peak recall collapsed to `0.20` and p50 failed badly
- E fold 10 had no late-horizon actual-peak diagnostic case; p90 overpredicted badly while p50 was closer but still worse than the existing `enhanced` MD metric on that fold

Decision:

- keep the LightGBM quantile code as an exploratory smoke candidate only
- do not run the full unbounded LightGBM rolling benchmark interactively
- do not promote LightGBM quantile into the app or default notebook value model
- if revisited, first design a capped, explicit benchmark mode and evaluate multiple folds without the rejected `direct_hgb` candidate in the same loop
- current app usage remains unaffected; the production app should not perform LOSO or rolling-origin benchmark retraining during upload

### H. 48-Hour Comparison Result

Verified on 2026-05-03 from a fresh rerun:

| Model | Mean RMSE kW | Mean WAPE % | Mean MD abs error kW | Peak precision | Peak recall | Peak F1 | False negatives | False positives | MD peak rank | Peak timing error intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| enhanced | 101.62 | 14.99 | 75.33 | 0.825 | 0.825 | 0.825 | 1.75 | 1.5 | 9.5 | 3.5 |
| enhanced_peak_priority | 101.62 | 14.99 | 75.33 | 0.450 | 0.900 | 0.600 | 1.0 | 5.0 | 5.0 | 3.5 |

Interpretation:

- 48-hour peak recall improves from `0.825` to `0.900`
- it materially ranks the actual MD interval closer to the top, improving mean MD peak rank from `9.5` to `5.0`
- precision drops because the tuned overlay raises more peak alerts

### I. Lightweight Latest-Fold Variant Comparison

Verified on 2026-04-18 from a fresh rerun after rollback:

| Variant | Mean RMSE kW | Mean WAPE % | Mean NRMSE / peak % | Mean MD abs error kW |
| --- | ---: | ---: | ---: | ---: |
| global_regime_current | 92.65 | 21.64 | 18.54 | 48.67 |
| global_regime_softened | 91.89 | 21.64 | 18.50 | 47.83 |
| seasonal_anchor_baseline | 97.09 | 24.44 | 21.14 | 67.58 |

Interpretation:

- both enhanced competition-safe variants are again better overall than the seasonal baseline
- the softened solar variant is slightly better than the current solar variant on average in this lightweight comparison
- this supports the rollback decision and suggests the simpler no-residual path is the correct active default for now

### I. Current Regression Assessment

Verified on 2026-05-03 from a fresh rerun and regression tests:

- the default base-training path is now global, not hard-segmented by solar vs non-solar
- regime-aware calibration remains active
- the rolling-origin loop now uses one global `blend_weight` per fold instead of an additional regime-specific blend search
- the rolling-origin loop now uses Variant `B` for solar sites and Variant `A` for non-solar sites
- the rolling-origin loop now fits on pooled training frames rather than the evaluated site's partial history alone
- the lightweight latest-fold variant comparison now also fits on pooled training frames rather than the evaluated site's partial history alone
- the LOSO loop now uses `target_has_solar` directly, so it no longer depends on leaked notebook state from another cell
- `select_blend_weight(...)` now penalizes bias and drift terms in addition to RMSE and MD abs error
- `fit_horizon_residual_adjustment(...)` remains available in the helper module, but it is no longer applied in the active notebook workflow
- notebook import cells were made more robust against stale `fit_global_enhanced_ridge` bindings after helper edits
- peak-priority overlay helpers are available and `enhanced_peak_priority` is the leading notebook peak-alert candidate
- peak-alert policy comparison, alert-score smoothing, ramp/approaching-peak features, and bounded MD calibration helpers are available in the notebook path
- rolling-origin diagnostic helpers, confirmed-alert scoring, and alert episode summaries are available in the notebook path
- late-horizon peak-envelope uplift helpers are available and wired as a rolling-origin candidate named `enhanced_late_peak_uplift`
- direct-horizon boosted helpers are available and wired as a rolling-origin candidate named `direct_hgb`, but current metrics reject it
- direct-horizon LightGBM quantile helpers are available and wired as a capped smoke candidate, but the first E-only proof is not stable enough for acceptance

Observed practical effect from the fresh rerun after rollback:

- notebook wiring and pooled-evaluation alignment remain correct
- rollback removed the large regression introduced by the residual-correction experiment
- the active notebook path is again materially stronger than the failed residual-correction run
- the enhanced variants again beat the seasonal baseline in the lightweight latest-fold comparison
- the tuned overlay now materially improves operational peak recall and missed-peak counts
- the 2026-05-04 rerun retains `current_20pct` as the leading notebook alert policy, but does not solve the precision tradeoff
- the 2026-05-04 confirmed-alert rerun rejects stricter confirmation because recall and MD peak rank regress
- diagnostics show late-horizon actual-peak underprediction on `E` and `Mi2` is the main value-model failure mode
- the first late-horizon uplift candidate materially improves overall MD abs error and Mi2, but E remains weak enough that `enhanced` is still retained as the default value model pending review
- the first direct-horizon HGB candidate is not viable for the target problem because it worsens E and Mi2 MD errors despite improving average WAPE
- the first capped LightGBM quantile proof shows runtime can be app-feasible when training is capped, but p50/p90 behavior is unstable and not accepted
- the remaining problems are precision tradeoff, default forecast-value error, E-site late-peak weakness, and app integration

Runtime note:

- the removed rolling blend-tuning path was the main avoidable hotspot
- based on the current helper logic, the blend-tuning portion of rolling work should be roughly `6x` lighter than before
- this is an estimate from the number of inner recursive forecasts avoided, not a fresh wall-clock benchmark captured in the notebook output

## Active Versus Exploratory Decisions

### Active

- single-model Ridge family
- recursive forecasting
- weekly memory and regime features
- global base model by default
- pooled rolling-origin and latest-fold evaluation using current-site history plus other sites
- regime-aware calibration
- bias-aware global blend-weight selection
- solar-specific daytime guardrails
- softened solar rolling variant for solar sites
- non-solar weekly-anchor safeguard
- baseline comparison tables

### Present but Not Enabled by Default

- segmented solar vs non-solar pooled training
- regime-specific blend-weight search in rolling-origin
- horizon-bucket residual correction
- `enhanced_peak_priority` peak-risk overlay
- `enhanced_late_peak_uplift` late-horizon value uplift candidate
- `direct_hgb` direct-horizon boosted value-model candidate
- capped LightGBM direct-horizon quantile smoke candidate

These exist in code, but are not the default rolling evaluation path. Future sessions should treat them as exploratory until explicitly re-enabled and validated.

### Explicitly Deferred

- direct multi-horizon redesign
- DirRec redesign
- large architectural changes outside the notebook experiment area

## What Future Sessions Should Check First

When returning to this work:

1. Open `forecast_model_upgrade_inspection.ipynb`.
2. Rerun the import/helper cells so the notebook reloads `forecast_model_upgrade_support.py`.
3. Inspect these notebook objects first:
   - `loso_results`
   - `loso_model_results`
   - `comparison_48h_model_results`
   - `rolling_summary`
   - `rolling_model_summary`
4. Confirm the rolling loop is using:
   - Variant `B` for solar sites
   - Variant `A` for non-solar sites
   - pooled training frames, not `[train_frame]` alone
   - `select_blend_weight(...)`, not `select_regime_blend_weight(...)`
5. Confirm the LOSO loop uses `target_has_solar`, not a leaked `site_has_solar` variable.
6. Confirm `fit_horizon_residual_adjustment(...)` is not being applied in the active notebook path unless the session is explicitly testing that experiment again.
7. Compare `enhanced` against `ridge_only`, `seasonal`, and any candidate rows before changing model logic.
8. Recheck SoL, E, and Mi2 safeguard metrics before accepting any model change.

## Recommended Next Priorities

Priority order for the next session:

1. Reduce `SuN` LOSO weakness.
   - It remains the weakest held-out site across the current active notebook path.
   - Peak shape and timing should be inspected before changing the model family.

2. Reduce rolling-origin weakness for `E` and `Mi2`.
   - The first late-horizon uplift candidate improves Mi2 and the overall MD metric, but E still barely improves and its RMSE/WAPE regress slightly.
   - The direct-horizon HGB candidate should not be tuned further in its current pooled form because it worsens E and Mi2 MD errors.
   - The capped LightGBM quantile proof should not be expanded until a separate capped benchmark mode is designed; the first proof was too unstable for promotion.
   - Focus on E-specific late-night peak shape and timing before promoting the uplift candidate.

3. Keep the residual-correction helper exploratory.
   - If it is revisited, gate it behind explicit variant wiring and require it to beat both `enhanced` without residuals and `seasonal`.

4. Keep baseline comparison mandatory.
   - Enhanced should not be accepted just because raw RMSE improved on one site.

5. Avoid large redesigns until the restored no-residual path is fully benchmarked and stabilized.

## Validation Commands

Primary regression checks:

```bash
python -m unittest tests.test_forecast_model_upgrade_support tests.test_forecast_model_upgrade_notebook
```

Helpful targeted checks:

```bash
python -m unittest tests.test_forecast_model_upgrade_support
python -m unittest tests.test_forecast_model_upgrade_notebook
```

Notebook use:

- rerun the notebook from the import cell downward after helper changes
- expect the full evaluation section to remain heavier than the small regression tests
- if a notebook traceback mentions an unexpected keyword on a helper function, restart the kernel or rerun the reload/import cells before debugging the helper code itself

## Short Decision Summary

The current notebook path has been restored to the stronger no-residual configuration after the failed residual-correction experiment.

Best current characterization:

- notebook wiring and reproducibility: improved
- pooled-evaluation alignment: improved
- residual-correction experiment: rolled back after regression
- current active path: stronger than the failed residual run, but still not a universally strong four-site result
- remaining weak areas: `SuN` LOSO and rolling-origin quality for `E` and `Mi2`
