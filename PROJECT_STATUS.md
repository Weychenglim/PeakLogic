# Project Status

The canonical status file lives in `docs/status.md`.

Current phase: implementation.

Latest model status:

- 2026-05-10: Replaced the Streamlit app path with a local FastAPI API and generated React/Vite frontend wired to backend analysis results. Supabase remains deferred until the local app is stable.
- 2026-05-09: Implemented monthly MD planning in the app: 1-3 month recent-pattern simulation, canonical kW unit handling for interval-energy uploads, 30-day MD billing periods, MD-risk-envelope optimization, and sine clear-sky solar shape.
- 2026-05-10: Enhanced monthly planning with p50/p90/p95 envelopes and a monthly MD backtest harness that reports MD error and p90/p95 coverage.
- 2026-05-10: Set the default monthly backtest to 21 training days plus a 30-day test horizon so the bundled two-month workbooks produce visible app scores.
- 2026-05-10: Added calibrated MD peak envelopes using a recent observed MD floor and routed the app optimizer through the calibrated p95 MD envelope.
- 2026-05-10: Added a hybrid trained monthly MD-risk calibrator over the statistical planner; the app applies it when enough history exists and otherwise keeps the statistical fallback.
- 2026-05-10: Added backend-only 7/14-day rolling stress validation and p90/p95 optimization risk-basis tradeoff helpers. UI surfacing is deferred.
- 2026-05-10: Added backend adaptive p90 calibration candidate search over recent-history windows and p90 floor multipliers; UI surfacing remains deferred.
- 2026-05-11: Added FastAPI/React support for editable tariff, CAPEX, and planning-month assumptions; staged analysis loading states; clearer API/workbook error cards; separate peak-risk overlay markers; and a gated non-solar late-night MD-risk envelope floor.
- 2026-05-11: React production build passes, with a remaining Vite warning that the chart-heavy JavaScript bundle is larger than 500 kB before route-level code splitting.
- 2026-05-11: Simplified the executive summary to a judge-facing problem, action, result, investment, and payback story, keeping technical risk/planning details in the forecast and optimization tabs.
- 2026-05-11: Expanded local FastAPI CORS handling for localhost, alternate Vite ports, and private LAN dev URLs so the browser does not report `Failed to fetch` when the API logs `200 OK`.
- 2026-05-11: Fixed React visual regressions by defining missing on-color Tailwind tokens and stopping site/forecast grid cards from stretching into oversized empty panels.
- 2026-05-11: Replaced the fragile hover-only top-bar site menu with a controlled native site selector so switching bundled sites works reliably.
- 2026-05-11: Replaced the visually clunky native site selector with a styled controlled click menu that keeps reliable site switching without browser-default dropdown chrome.
- 2026-05-11: Simplified Site Profile and Forecast & Risk UI to show one operational forecast/risk result, hiding p90/p95 model wording from the user-facing dashboard views.
- 2026-05-11: Updated the Optimization tab into a more judge-facing decision view with What Changed, Why This Scenario, and Savings Sensitivity copy; replaced Locked Assumptions with editable assumptions and an Apply action that reruns the active bundled workbook or retained upload.
- 2026-05-11: Added backend-generated Optimization explanation, confidence flags, and active-analysis +/-10% tariff/CAPEX sensitivity rows, and surfaced those backend fields in the React Optimization tab.
- 2026-05-11: Hardened bundled workbook discovery so Excel `~$` lock files are ignored instead of being parsed as site workbooks.
- 2026-05-11: Added Peak Risk Timeline and Solar Impact Comparison cards to the Site Profile dashboard, using active forecast and optimized-schedule data.
- 2026-05-11: Added a backend-only direct long-horizon LightGBM quantile model candidate for 1-3 month forecasts and inspected its first 30-day holdout score. The candidate is not accepted as production default because it slightly worsened average RMSE/WAPE and materially worsened MD-risk magnitude error versus the current planner.
- 2026-05-12: Added a backend-only baseline-correction LightGBM candidate over the current monthly planner. The best inspected setting improved average p50 monthly MD absolute error from `259.12` kW to `240.75` kW and preserved p90/p95 error, but worsened average RMSE from `209.45` kW to `215.38` kW and WAPE from `36.10%` to `37.29%`, so it remains a development candidate.
- 2026-05-12: Added a backend-only MD-risk-only LightGBM candidate that preserves the p50 forecast path, then enhanced it with undercoverage classifiers for gated uplift. Current 30-day holdout score keeps RMSE/WAPE unchanged at `209.45` kW / `36.10%`, improves p90 MD abs error from `88.28` kW to `58.93` kW, improves p95 MD abs error from `57.21` kW to `52.58` kW, and improves p90/p95 coverage from `0%/25%` to `50%/50%`.
- 2026-05-12: Reduced model-development test runtime by shrinking synthetic LightGBM fixtures and training-row caps while keeping real model training coverage. `tests.test_forecasting` now completes in about `97` seconds instead of the previous roughly `336` seconds.
- 2026-05-12: Added peak-timing localization to the backend-only ML MD-risk model. The localized model preserves RMSE/WAPE and p90/p95 MD-risk gains, while improving average actual-peak rank from `393.75/395.50` under the statistical planner to `356.00/341.75` for p90/p95 risk scores.
- 2026-05-12: Added site-regime peak features to the backend-only ML MD-risk model, including recent peak hour, daylight/weekend flags, peak-slot concentration, 7-day versus 28-day max ratio, non-solar night peak indicator, and solar daylight peak interaction. Current bundled holdout score is unchanged, so the features are retained as low-risk model inputs rather than accepted as a measured score improvement yet.
- 2026-05-12: Tuned the backend-only ML MD-risk uplift policy. The selected default uses tighter p90/p95 ratio caps and a higher peak-timing active quantile; p90/p95 MD errors remain `58.93`/`52.58` kW, coverage remains `50%`/`50%`, and average actual-peak rank improves from `356.00`/`341.75` to `350.50`/`337.00`.
- 2026-05-13: Added a backend-only full ML planning candidate, `forecast_full_ml_planning_profile`, that trains LightGBM quantile residual models for p50/p90/p95 over planner-aware features and raises on short history instead of silently falling back. First bundled 30-day holdout score: RMSE `210.82` kW, WAPE `36.43%`, p50 MD abs error `277.43` kW, p90 MD abs error `49.69` kW, p95 MD abs error `56.34` kW, p90/p95 coverage `0%/50%`; it is not promoted because the hybrid ML MD-risk candidate still has better RMSE/WAPE, p50 MD error, p95 error, coverage balance, and peak ranking.
- 2026-05-13: Added and integrated `forecast_gated_ml_planning_profile` as the main FastAPI forecast path for enough-history analyses. Bundled 30-day holdout score: RMSE `209.40` kW, WAPE `36.08%`, p50 MD abs error `259.12` kW, p90 MD abs error `58.93` kW, p95 MD abs error `52.58` kW, p90/p95 coverage `50%/50%`. This is the current best backend model score, but the API smoke test now takes about `274` seconds because model training, optimization sensitivity, and short-horizon backtesting run synchronously.
- 2026-05-13: Added a root `.gitignore` for GitHub handoff so virtual environments, caches, logs, secrets, node modules, and frontend build outputs are excluded. A local TREX `.git` was initialized, but Git operations still require resolving Windows safe-directory ownership before commit/push.
- 2026-05-07: Added `docs/mentoring_session_prep.md` for the upcoming mentoring session. It includes source-of-truth-based questions, an architecture diagram, and decision prompts.
- 2026-05-03: Implemented and benchmarked the notebook-first `enhanced_peak_priority` overlay.
- Tuned the overlay to top-20% alerts and plus/minus one-hour peak matching.
- LOSO peak recall improved from `0.40` to `0.90`.
- Rolling-origin peak recall improved from `0.477` to `0.782`.
- 48-hour MD peak rank improved from `9.5` to `5.0`.
- RMSE, WAPE, and MD abs error stayed unchanged because the overlay only changes peak ranking and flags.
- Decision: treat the overlay as the leading notebook peak-alert candidate; app promotion should be planned separately.
- 2026-05-04: Fixed the temporary regression caused by using peak-priority scoring inside blend-weight selection. Blend selection is now forecast-value safe again.
- 2026-05-04: Executed the notebook refinement plan through metric review. `current_20pct` remains the leading peak-alert policy; bounded MD calibration is not accepted because RMSE/WAPE regress; app promotion remains deferred until user review of the metric score.
- 2026-05-04: Executed the diagnosis and confirmed-alert notebook plan. `enhanced_peak_confirmed` is rejected; diagnostics identify late-horizon actual-peak underprediction on `E` and `Mi2` as the next modeling target. App promotion remains deferred.
- 2026-05-04: Added and benchmarked notebook-only `enhanced_late_peak_uplift`. Overall rolling MD abs error improved from `114.04` to `97.57` kW with slight overall RMSE/WAPE improvement, but the default value model remains `enhanced` pending review because `E` only improves marginally.
- 2026-05-04: Added candidate-level uplift diagnostics. The worst `E` late-night actual-peak regime is unchanged by the uplift; a broader non-solar night site-peak fallback was tested and rejected because MD abs error regressed to `110.24` kW.
- 2026-05-04: Added and benchmarked notebook-only `direct_hgb`, a direct-horizon scikit-learn HGB candidate. It is rejected for now because rolling MD abs error worsened to `160.07` kW and E/Mi2 MD errors regressed.
- 2026-05-05: Planned the larger modeling redesign as a notebook-only LightGBM direct-horizon quantile benchmark plus separate MD-risk head. Plan file: `docs/superpowers/plans/2026-05-05-lightgbm-quantile-md-redesign.md`.
- 2026-05-05: Installed LightGBM and added capped notebook-only quantile smoke helpers. Tiny E-only proof is fast with capped local rows, but the candidate is not accepted because p50/p90 results are unstable.
