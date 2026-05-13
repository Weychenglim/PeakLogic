# Architecture And Coding Design

The canonical architecture and coding design live in `docs/architecture.md`.

Current forecasting design:

- Production app forecasting remains separate from notebook experiments.
- A backend-only `forecast_long_horizon_model_profile` candidate exists for direct 1-3 month LightGBM quantile forecasting. It is not the production API default because the first holdout metric pass did not beat the current planner.
- A backend-only `forecast_corrected_long_horizon_profile` candidate exists for planner-residual correction. It learns p50 residuals over the current planner while preserving the existing p90/p95 risk envelopes during model development.
- A backend-only `forecast_ml_md_risk_profile` candidate exists for ML-trained MD-risk modeling. It preserves `forecast_kw_import` and `p50_forecast_kw`, then uses LightGBM ratio models, undercoverage classifiers, site-regime peak features, tuned uplift policy caps, and peak-timing localization to adjust p90/p95 monthly MD-risk envelopes only.
- A backend-only `forecast_full_ml_planning_profile` candidate exists for full ML planning development. It trains LightGBM quantile residual models for p50, p90, and p95 using the current planner as an input feature, changes the p50 path, and raises on short history instead of silently falling back.
- The main FastAPI forecast path now calls `forecast_gated_ml_planning_profile` for enough-history analyses. It starts from the strongest ML MD-risk candidate, applies tightly gated p50 corrections, and falls back to the statistical monthly planner only when the gated candidate cannot train on short history.
- The UI layer is being replaced: React/Vite owns the dashboard experience, while FastAPI exposes the existing `trex_energy` package functions to the frontend.
- The previous `app.py` Streamlit entry point has been removed; local React plus FastAPI should be used before adding Supabase persistence.
- Production app MD planning now uses a recent-pattern simulator for 1-3 month horizons instead of recursively extending the short-horizon Ridge forecast.
- Monthly planning now outputs p50 expected load, p90 MD-risk envelope, and p95 stress envelope; a rolling monthly backtest reports MD error and coverage.
- Conservative MD envelopes are calibrated with a recent observed MD floor. The default optimizer MD-risk input now follows the calibrated p95 stress envelope.
- When enough historical folds exist, the production app applies a lightweight trained monthly MD-risk calibrator over the statistical p95 envelope; short-history uploads fall back to the untrained statistical envelope.
- Forecasting exposes backend 7-day and 14-day rolling stress-window MD validation scores for denser model evidence from the existing limited workbooks; these are diagnostic stress scores, not replacements for the official 30-day monthly MD backtest.
- Forecasting now exposes adaptive p90 calibration candidate search over recent-history windows and p90 MD-floor multipliers, scored by stress-window coverage, MD absolute error, and overprediction bias.
- Optimization now accepts an explicit MD-risk basis so downstream reporting can compare balanced p90 planning against conservative p95 planning without adding UI coupling to the model layer.
- The canonical ingestion contract is that `kw_import` and `kw_export` are power columns. Active-energy uploads can be auto-detected from `kWh` headers or forced through the upload unit selector.
- Optimization can use the monthly planning forecast or the conservative `md_risk_envelope_kw` column, and tariff MD charges are evaluated per 30-day planning month.
- Notebook experiments use the shared helper module under `notebooks/model_upgrade_inspection/forecast_model_upgrade_support.py`.
- Peak-alert overlays must use forecast-safe engineered features only and must not rely on same-time measured `kw_import`, solar generation, gross load, or reactive-power leakage columns.
- Experimental peak-risk overlays should not change `forecast_kw_import` until rolling-origin benchmarks justify promotion.
- Production monthly planning now annotates a separate `peak_risk_overlay_score` and `is_peak_risk_overlay` marker for recall-oriented MD-risk windows while keeping `forecast_kw_import` equal to p50 expected demand.
- Model benchmark metrics are backend validation artifacts only; the React UI should continue to show result-oriented forecast, optimization, savings, and payback outputs rather than model comparison tables.
- Non-solar late-night MD-risk support is gated to recent local night peak shapes and only raises p90/p95 risk envelopes, not the p50 forecast path.
- FastAPI analysis requests accept visible tariff, CAPEX, and planning-month assumptions that React passes from the dashboard controls into optimization.
- `App.tsx` owns the active assumptions, selected bundled workbook, retained upload file, and analysis rerun callbacks; the Optimization tab receives editable assumption props and can rerun the active analysis without leaving the tab.
- Optimization UI language should translate technical MD-risk basis labels into judge-facing peak-demand planning wording.
- `trex_energy.optimization.evaluate_assumption_sensitivity` computes active-analysis sensitivity rows by reusing the deterministic optimizer with +/-10% tariff and CAPEX variants.
- `trex_energy.reporting.build_optimization_explanation` owns judge-facing Optimization explanation text, planning-basis labels, and confidence flags derived from best-scenario, assumptions, validation, and sensitivity context.
- FastAPI packages backend explanation and sensitivity under `optimization.explanation` and `optimization.sensitivity` for React to render.
- Bundled workbook discovery ignores Excel `~$` temporary lock files before ingestion.
- `SiteProfile.tsx` derives its Peak Risk Timeline from `forecast.preview` and derives Solar Impact Comparison from `optimization.schedule_preview` plus active energy-rate assumptions.

Latest design note:

- 2026-05-10: Added a local FastAPI boundary and React/Vite frontend wiring as the replacement path for Streamlit; database persistence remains out of scope until after local integration.
- 2026-05-09: Added production monthly MD planning simulation, kWh-per-interval to kW normalization, 30-day MD billing periods, and a clear-sky sine PV profile.
- 2026-05-10: Added probabilistic p50/p90/p95 monthly planning outputs and monthly MD backtest metrics.
- 2026-05-10: Added recent observed MD floor calibration for p90/p95 peak envelopes and routed MD-risk optimization through calibrated p95.
- 2026-05-10: Added a trained monthly MD-risk calibration layer that learns conservative p95 uplift/intercept from rolling monthly folds and annotates calibrated forecast outputs.
- 2026-05-10: Added backend-only stress-window scoring and explicit p90/p95 optimization basis support for later UI/reporting.
- 2026-05-10: Added adaptive p90 candidate search and fit helpers so the balanced envelope can be calibrated against 7/14-day stress evidence.
- 2026-05-11: Added React-visible planning assumptions, staged loading/error UX, peak-risk overlay chart markers, and a gated non-solar late-night MD-risk envelope floor.
- 2026-05-11: Added editable Optimization-tab assumptions and same-analysis rerun wiring while keeping site/model comparison out of the Optimization decision view.
- 2026-05-11: Added backend Optimization explanation and active-analysis sensitivity payloads, then routed them into the React Optimization tab.
- 2026-05-11: Hardened workspace workbook discovery against temporary Excel lock files.
- 2026-05-11: Added Site Profile dashboard cards for peak-risk timeline and solar impact comparison without adding site/model comparison.
- 2026-05-11: Added a backend-only direct long-horizon LightGBM quantile model candidate and kept the production API on the stable planner after the first metric pass underperformed.
- 2026-05-12: Added a backend-only baseline-correction model candidate. Its first score improves average p50 MD absolute error, but interval RMSE/WAPE still regress, so it remains model-development only.
- 2026-05-12: Added a backend-only MD-risk-only LightGBM candidate and enhanced it with gated undercoverage classifiers plus peak-timing localization. Its current score keeps RMSE/WAPE unchanged while improving p90/p95 MD-risk error and average actual-peak ranking, making it the strongest model-development candidate so far.
- 2026-05-12: Added site-regime peak features to the backend-only MD-risk model. The bundled holdout score is unchanged, so these features are retained as model inputs for future folds/data rather than counted as a measured score gain.
- 2026-05-12: Tuned default MD-risk uplift policy caps and the active timing quantile. The tuned policy keeps MD-risk error and coverage unchanged while improving average actual-peak rank.
- 2026-05-13: Added a backend-only full ML planning candidate that predicts p50/p90/p95 residuals over planner-aware features. First bundled holdout inspection improves p90 MD error but slightly worsens RMSE/WAPE and p50 MD error, so it is not promoted.
- 2026-05-13: Added and integrated the gated ML planning candidate into FastAPI. Bundled 30-day holdout improves RMSE/WAPE from `209.45` kW / `36.10%` to `209.40` kW / `36.08%` while preserving the hybrid p90/p95 MD-risk scores.
- 2026-05-03: Added an exploratory scikit-learn `enhanced_peak_priority` overlay that changes peak scoring and flags while leaving forecast values unchanged.
- 2026-05-04: Added notebook-only peak-alert policy comparison, alert-score smoothing, ramp/approaching-peak features, and a bounded MD calibration candidate. Production app promotion remains deferred pending user metric review.
- 2026-05-04: Added notebook-only rolling diagnostic and confirmed-alert episode helpers. The confirmed-alert candidate is rejected; diagnostics point to late-horizon actual-peak underprediction as the next model target.
- 2026-05-04: Added notebook-only `enhanced_late_peak_uplift`, a capped same-site peak-envelope value candidate for high-risk late-horizon intervals. It remains separate from the default `enhanced` forecast pending metric review.
- 2026-05-04: Added candidate-level uplift diagnostics and kept the broader non-solar night site-peak floor fallback disabled after it regressed overall rolling MD error.
- 2026-05-04: Added notebook-only `direct_hgb`, a direct-horizon scikit-learn HGB candidate. It is rejected for now because E and Mi2 MD errors regressed despite lower average WAPE.
- 2026-05-05: Added LightGBM as an exploratory dependency and notebook-only direct-horizon quantile smoke helpers. The candidate is capped for interactive use and is not promoted because the first E-only proof showed unstable p50/p90 behavior.
