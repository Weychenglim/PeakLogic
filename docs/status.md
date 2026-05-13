# Project Status

## Purpose
This file is the current operational snapshot for the TREX competition app. Future threads should read this file first to understand where work stands, what is locked, and what to do next.

## Read Order
Future threads should use this order:
1. `docs/status.md`
2. `docs/requirements.md`
3. `docs/architecture.md`
4. `docs/forecast_model_upgrade_source_of_truth.md` when working on the notebook forecasting experiment area

## Current Phase
Implementation

## Snapshot
The project now has an end-to-end baseline workflow from data ingestion through forecast, savings simulation, and downloadable outputs. The repo contains a Python package, workbook-driven tests, and a local FastAPI plus React/Vite app path replacing the previous Streamlit entry point. The new API can analyze bundled or uploaded workbooks, normalize them, validate interval quality, generate monthly MD planning forecasts with peak-risk flags, run deterministic optimization scenarios for flexible load shifting, battery, and solar, and return JSON/CSV payloads for the React dashboard. Stronger modeling and presentation polish are still pending.

## Completed
- Confirmed the workspace currently contains four Excel workbooks and no existing app code.
- Profiled the workbook formats and verified they are heterogeneous but compatible with a common normalization pipeline.
- Decided to treat the four workbooks as four separate site case studies.
- Chosen product direction: judge-facing decision-support demo rather than production EMS control.
- Chosen dashboard stack: React/Vite frontend plus FastAPI backend over the existing Python package. The previous Streamlit entry point has been removed.
- Chosen future-data assumption: unseen sites or unseen site-period combinations must be supported.
- Chosen load-control abstraction: flexible load blocks instead of named measured assets.
- Chosen billing scope: MD plus energy charges.
- Created the documentation memory set: `docs/requirements.md`, `docs/architecture.md`, `docs/status.md`.
- Created the initial Python project scaffold with `pyproject.toml` and `trex_energy/`; the active local app entry is now `api.py` plus `kinetic-precision/`.
- Implemented workbook ingestion and normalization for the four current Excel dataset shapes.
- Implemented interval validation with gap, duplicate, and missing-value reporting.
- Added `tests/test_ingestion.py` and verified the ingestion pipeline against the provided workbooks.
- Implemented the first Streamlit UI slice for bundled dataset overview, upload preview, and site profile charts; this has been superseded by the React/FastAPI path.
- Implemented a pooled baseline forecasting module with recursive next-48-interval prediction.
- Implemented forecast backtesting metrics and peak-risk flags.
- Added `tests/test_forecasting.py` and verified the first forecasting slice locally.
- Implemented tariff calculations for MD and energy charges.
- Implemented deterministic optimization scenario search covering flexible load shifting, battery dispatch, and solar offset.
- Added `tests/test_optimization.py` and verified tariff and optimization behavior locally.
- Extended the earlier Streamlit app with editable optimization assumptions and savings views; this has been superseded by the React/FastAPI path.
- Implemented reporting helpers for CSV exports, executive summary text, and bundled site comparison summaries.
- Added `tests/test_reporting.py` and verified reporting/export behavior locally.
- Extended the earlier Streamlit app with bundled site comparison and download buttons for key outputs; this has been superseded by the React/FastAPI path.
- Added interval-energy unit handling so active `kWh` per interval uploads are converted to canonical kW.
- Added 1-3 month MD planning simulation using recent weekday/weekend half-hour load patterns.
- Added MD-risk envelope output and optional envelope-based optimization.
- Added p50 expected, p90 MD-risk, and p95 stress planning outputs.
- Added monthly planning backtest metrics for p50/p90/p95 MD error and p90/p95 coverage.
- Added calibrated p90/p95 MD peak envelopes using a recent observed MD floor.
- Added a lightweight trained monthly MD-risk calibrator that learns conservative p95 uplift/intercept from rolling historical folds and applies it in the app when enough site history exists.
- Added backend-only 7/14-day rolling stress-window validation scores and p90/p95 optimization risk-basis tradeoff helpers.
- Added backend adaptive p90 calibration candidate search using 7/14-day stress coverage, MD error, and bias to select `recent_days` and `p90_floor_multiplier`.
- Added a local FastAPI API layer and wired the generated `kinetic-precision` React/Vite frontend to real backend analysis data as the Streamlit replacement path.
- Added editable React/FastAPI planning assumptions for MD rate, peak/off-peak energy rates, battery CAPEX, solar CAPEX, and planning months.
- Added staged analysis loading UX, API/workbook error cards, and per-page empty/loading/error states.
- Added a separate production `peak_risk_overlay_score` and high MD-risk chart marker while keeping `forecast_kw_import` unchanged.
- Added a gated non-solar late-night MD-risk envelope floor that only raises p90/p95 risk envelopes for recent local night-peak shapes.
- Simplified the executive summary into judge-facing problem, action, result, investment, and payback beats, leaving detailed planning-risk wording in the forecast and optimization tabs.
- Expanded local FastAPI CORS handling for localhost, alternate Vite ports, and private LAN dev URLs after the browser reported `Failed to fetch` even while FastAPI logged `200 OK`.
- Fixed React visual regressions by defining missing on-color Tailwind tokens and preventing site/forecast grid cards from stretching into oversized empty panels.
- Replaced the fragile hover-only top-bar site menu with a controlled native site selector so switching bundled sites works reliably.
- Replaced the visually clunky native site selector with a styled controlled click menu that keeps reliable site switching without browser-default dropdown chrome.
- Simplified Site Profile and Forecast & Risk UI to show one operational forecast/risk result, hiding p90/p95 model wording from the user-facing dashboard views.
- Updated the Optimization tab into a judge-facing decision screen with What Changed, Why This Scenario, and Savings Sensitivity copy, friendlier conservative peak-demand wording, editable assumptions, and an Apply action for the active bundled workbook or retained upload.
- Added backend-generated Optimization explanation, confidence flags, planning-basis labels, and active-analysis +/-10% sensitivity rows for MD rate, battery CAPEX, and solar CAPEX; React now renders those backend fields in the Optimization view.
- Hardened bundled workbook discovery so temporary Excel `~$` lock files are ignored before ingestion.
- Added Site Profile Peak Risk Timeline and Solar Impact Comparison cards based on active forecast and optimized schedule payloads.
- Changed tariff simulation to charge MD once per 30-day planning month.
- Replaced the solar sizing shape with a clear-sky sine profile.
- Added backend-only `forecast_full_ml_planning_profile`, a LightGBM full planning candidate that changes p50 and predicts p90/p95 risk paths while keeping all model details out of the UI.
- Added `forecast_gated_ml_planning_profile` and routed FastAPI bundled/upload analysis through it when enough history exists.

## In Progress
- Peak-priority notebook model enhancement was implemented and benchmarked in this thread; the 2026-05-04 refinement rerun keeps `current_20pct` as the leading alert policy for metric review.
- The 2026-05-04 diagnosis and confirmed-alert plan was executed through notebook metric review. App promotion remains deferred until the metric score is reviewed and explicitly accepted.
- The first late-horizon peak-envelope uplift value-model candidate was implemented and benchmarked in the notebook path. It improves overall rolling MD abs error, RMSE, and WAPE, but remains a review candidate because `E` only improves marginally and its RMSE/WAPE worsen slightly.
- Candidate-level diagnostics show `enhanced_late_peak_uplift` does not improve the worst `E / non-solar / night / late / actual_peak` regime; a broader non-solar night site-peak fallback was tested and rejected because overall MD abs error regressed.
- A notebook-only direct-horizon boosted candidate named `direct_hgb` was implemented and benchmarked with scikit-learn HGB. It is rejected for now because it worsens E and Mi2 MD errors despite improving average WAPE.
- A larger modeling redesign plan now exists at `docs/superpowers/plans/2026-05-05-lightgbm-quantile-md-redesign.md`. The planned next benchmark is LightGBM direct-horizon quantile forecasting plus a separate MD-risk head, not further Ridge/uplift/HGB tuning.
- LightGBM quantile helpers and notebook smoke wiring were added after installing `lightgbm`. A tiny E-only proof showed capped single-site training is fast, but p50/p90 behavior is unstable, so it is not accepted or promoted.
- Monthly MD planning has been promoted into the production decision horizon; short-horizon forecasting remains available as a backtest/reference path.
- Monthly planning now has a lightweight rolling MD backtest and trained envelope calibration, but the calibrated p90/p95 envelopes still need review on real competition examples before using them as final sizing guarantees.
- Optimizer MD-risk mode now plans against the calibrated p95 stress envelope because MD charges are governed by the highest interval, not average forecast accuracy.
- Backend model evidence can now compare 7-day and 14-day stress-window scores plus p90 versus p95 optimization tradeoffs; React UI surfacing is intentionally deferred.
- Backend adaptive p90 calibration can now choose balanced-envelope settings from stress-window candidate scores; React UI surfacing is intentionally deferred.
- The next major implementation slice remains model-quality refinement plus presentation polish.
- Supabase integration is intentionally deferred until the React/FastAPI local workflow is stable and the team needs saved analyses or user/project persistence.
- Full ML planning candidate validation is in progress as a backend-only experiment. The first bundled 30-day holdout improves p90 MD absolute error versus the statistical planner, but worsens RMSE/WAPE and p50 MD error versus both the statistical planner and the current hybrid ML MD-risk candidate.
- The gated ML planning candidate is the current best backend score and is now the main enough-history FastAPI forecast path. It keeps p50 MD error unchanged from the stable planner, preserves ML p90/p95 gains, and slightly improves RMSE/WAPE. API runtime needs optimization before broad handoff because synchronous bundled analysis currently takes several minutes.

## Next Actions
- Review the fresh notebook metric score before deciding whether and how to promote the `enhanced_peak_priority` peak-alert overlay into the production app forecast path.
- Review whether to accept `enhanced_late_peak_uplift` as the next value-model candidate; focus especially on whether the small `E` MD improvement is enough despite slight RMSE/WAPE regression.
- Continue improving late-horizon actual-peak underprediction on `E`; the first uplift candidate materially helps Mi2 and overall MD error, but the worst E late-night actual-peak regime is unchanged.
- Do not tune `direct_hgb` further in its current pooled HGB form unless the next experiment changes the training strategy, such as site-specific/regime-specific boosting or approved LightGBM dependency testing.
- If modeling resumes, do not run the unbounded LightGBM rolling benchmark interactively. First create an explicit capped benchmark mode, exclude rejected `direct_hgb` from the same loop, and enforce the acceptance gate before considering promotion.
- Continue improving precision and peak timing after the tuned overlay's recall improvement, but do not accept changes that collapse recall.
- Improve the forecasting model with site-local calibration and clearer uncertainty communication.
- Refine optimization scoring and payback assumptions using confirmed tariff/CAPEX inputs.
- Strengthen the bundled site comparison view with clearer ranking, annotations, and judge-facing storytelling.
- Add stronger presentation/report formatting for judge-facing executive summaries.
- Expand validation and forecasting coverage with additional edge-case tests.
- Do not promote `forecast_full_ml_planning_profile` unless the next iteration fixes p50/RMSE regression while retaining the p90 MD improvement.
- Before sharing the GitHub repo broadly, reduce synchronous analysis runtime by caching model/reference data, trimming repeated sensitivity runs, or moving heavier diagnostics out of the default endpoint.

## Current Decisions
- Primary audience: future agents and teammates, with judge readability as a secondary benefit.
- These three documents are living project memory, not presentation documents.
- `docs/architecture.md` includes both architecture and coding design, so no separate coding-design file is needed.
- Documentation must be updated after every meaningful change to requirements, assumptions, architecture, modeling approach, or implementation status.
- The app should be robust to unseen site uploads.
- The app should use pooled multi-site forecasting with site-local calibration.
- The app should use recent-pattern monthly simulation for 1-3 month MD planning and avoid recursive 1440-4320 interval Ridge forecasts.
- Monthly planning should present p50 expected demand, p90 MD-risk demand, and p95 stress demand so judges can see both expected and conservative planning cases.
- The production app should be described as hybrid monthly planning: explainable statistical recent-pattern simulation plus trained historical MD-risk calibration when sufficient history exists.
- 7-day and 14-day rolling stress-window scores are diagnostic evidence only; official MD billing evaluation remains based on 30-day planning periods.
- p90 optimization should be treated as balanced planning, while p95 optimization should be treated as conservative peak-protection planning.
- Adaptive p90 calibration should be used to select balanced-risk planner settings from existing data, not as proof of performance on unseen external datasets.
- Canonical active import/export columns are always kW; interval-energy uploads must be converted during ingestion.
- The optimizer should use deterministic scenario-based simulation.
- The app should remain configuration-driven and site-agnostic.
- The current import pipeline should treat workbook filenames as hints only, not as durable business identifiers.
- The current short-horizon forecasting baseline is a reference/backtest path, not the final competition-grade monthly planning model.
- The notebook now includes a scikit-learn peak-risk overlay candidate named `enhanced_peak_priority`; with top-20% alerts and plus/minus one-hour matching, it is the leading notebook peak-alert candidate.
- The 2026-05-04 policy comparison did not find a better accepted alert threshold: stricter alerts improve precision but lose too much recall, while looser alerts raise too many false positives.
- The bounded MD calibration experiment is not accepted as the value model because it slightly reduces MD abs error but worsens RMSE and WAPE.
- The confirmed-alert experiment is not accepted because recall drops to `0.630`, missed peaks rise to `2.000`, and MD peak rank worsens.
- The late-horizon peak-envelope uplift candidate is not promoted as the default value model yet. It improves rolling MD abs error from `114.04` to `97.57` kW and slightly improves RMSE/WAPE overall, but E remains the weak acceptance case.
- The broader non-solar night site-peak fallback is rejected for the active notebook path because it regressed the uplift candidate to `110.24` kW MD abs error and `142.29` kW RMSE.
- The direct-horizon HGB candidate is rejected because rolling MD abs error regresses to `160.07` kW, E MD abs error rises to `290.62` kW, and Mi2 MD abs error rises to `182.68` kW.
- The current optimization and payback logic is also a baseline and should remain transparent and editable.
- The current reporting layer exports CSVs but does not yet generate a polished presentation-ready report.
- The current React frontend is newly wired to the backend and should receive browser-based UX polish after the API workflow is verified locally.
- The Optimization tab should remain focused on one active analysis and avoid introducing site-by-site or model-comparison controls into the decision screen.
- Backend sensitivity is intentionally single-analysis and lightweight; growth rate, EV load, and planning months still update through a full Apply rerun rather than a local sensitivity shortcut.

## Risks / Blockers
- Final tariff assumptions beyond the known MD rate are not yet locked.
- CAPEX assumptions for battery and solar sizing are not yet locked.
- The current datasets are site-level only, so controllable-load modeling remains assumption-driven.
- Some current files contain non-30-minute gaps, so preprocessing rules must be chosen carefully.
- Future dataset schema variations are still unknown.
- The current forecast model does not yet include explicit site-local calibration or uncertainty bands.
- Peak-alert precision and default forecast-value error remain modeling risks; the latest tuned overlay materially improves rolling-origin recall by accepting more false positives.
- The latest value-model candidate improves average forecast-value metrics but may overfit the current acceptance story if promoted before the E-site late-peak weakness is understood.
- The E-site root issue now appears to be peak shape/regime escalation rather than only a too-low same-slot floor; the same-slot envelope does not lift the worst E late-night actual peaks.
- The direct-horizon HGB benchmark is slow in the current environment and does not solve the target E/Mi2 peak-value failure mode.
- The LightGBM quantile proof shows app-like capped fitting can be fast, but full notebook benchmark expansion can still blow up runtime if folds, sites, and quantile heads are multiplied without caps.
- The latest metric rerun confirms app promotion should remain delayed until the team accepts the precision/recall tradeoff.
- Tariff and CAPEX assumptions are still placeholders for competition-grade financial outputs.
- Tariff and CAPEX assumptions are now visible/editable in the React UI, but final competition-grade values still need confirmation from official materials or explicit team decisions.
- Vite production build currently warns that the generated JavaScript bundle is larger than 500 kB; route-level code splitting is a future frontend performance task.

## Recent Changes
- 2026-05-07: Added `docs/mentoring_session_prep.md` with mentoring questions, a current architecture diagram, and high-impact decision prompts based on the source-of-truth docs.
- 2026-05-09: Implemented monthly MD planning in the production app: user-selectable 1/2/3 month windows, recent weekday/weekend pattern simulation, MD-risk envelopes, interval-energy to kW normalization, 30-day MD billing periods, and a clear-sky sine solar profile.
- 2026-05-10: Added probabilistic monthly planning outputs and monthly MD backtesting. The app forecast view charts p50/calibrated-p90/calibrated-p95 profiles and reports p50/p90/p95 monthly MD error plus p90/p95 coverage when enough history exists.
- 2026-05-10: Set the default monthly backtest to 21 training days plus a 30-day test horizon so the bundled two-month workbooks produce visible app scores.
- 2026-05-10: Added recent-MD floor calibration so p95 MD planning covers recent observed peaks with a default 3% safety factor.
- 2026-05-10: Added trained monthly MD-risk calibration over the statistical planner. The app now fits a conservative p95 uplift/intercept from rolling monthly folds when possible and annotates calibrated forecast outputs.
- 2026-05-10: Added backend-only 7/14-day stress validation via `backtest_md_stress_windows` and p90/p95 tradeoff support via `md_risk_basis` and `evaluate_risk_basis_tradeoff`.
- 2026-05-10: Added adaptive p90 calibration helpers: `evaluate_p90_calibration_candidates` and `fit_adaptive_p90_calibration`.
- 2026-05-10: Added `forecast_adaptive_p90_planning_profile` so backend consumers can generate annotated adaptive p90 forecasts without manual parameter plumbing.
- 2026-05-10: Added `api.py` with FastAPI endpoints for health checks, bundled-site listing, bundled analysis, and upload analysis. Reworked the generated React frontend to call the API and render real analysis state instead of static mock values. Supabase remains deferred.
- 2026-05-11: Reworked the Optimization tab copy and assumptions panel so judges see the bill/MD change, selection rationale, and editable savings assumptions in the same view.
- 2026-05-11: Added backend Optimization explanation and sensitivity payloads and updated React types/rendering for those fields.
- 2026-05-11: Added a regression test and discovery filter for Excel `~$` lock files after a local open workbook caused bundled-site API tests to hit a permission error.
- 2026-05-11: Added the missing Site Profile Peak Risk Timeline and Solar Impact Comparison sections requested from the reference dashboard.
- 2026-05-11: Added a backend-only direct long-horizon LightGBM quantile model candidate and inspected its first 30-day holdout score. It is not accepted as production default because it did not beat the current planner on average RMSE/WAPE or MD-risk magnitude error.
- 2026-05-12: Added a backend-only baseline-correction LightGBM candidate over the current planner. The inspected score improves p50 monthly MD error but worsens interval RMSE/WAPE, so the candidate needs more model work before production promotion.
- 2026-05-12: Added a backend-only MD-risk-only LightGBM candidate that preserves p50 forecast values, then added undercoverage classifiers for gated uplift. The inspected score improves p90/p95 MD-risk error and coverage without changing interval RMSE/WAPE.
- 2026-05-12: Reduced model-development test runtime by shrinking synthetic LightGBM fixtures and row caps while retaining real model-training coverage.
- 2026-05-12: Added peak-timing localization to the backend-only ML MD-risk model. It keeps p50 forecast values unchanged, preserves p90/p95 MD-risk error gains, and improves average actual-peak ranking.
- 2026-05-12: Added site-regime peak features to the backend-only ML MD-risk model. The current bundled holdout score is unchanged, but the features are now available for future model iterations and data.
- 2026-05-12: Tuned the backend-only ML MD-risk uplift policy. The selected caps keep p90/p95 MD error and coverage unchanged while improving average actual-peak rank.
- 2026-04-16: Reviewed the four provided workbooks and inferred that they likely represent different sites.
- 2026-04-16: Chosen the initial product direction as a Streamlit-based, judge-facing decision-support demo; this UI stack was later replaced by React/FastAPI on 2026-05-10.
- 2026-04-16: Locked key working assumptions for unseen-site support, flexible-load-block control, and MD-plus-energy billing.
- 2026-04-16: Created the canonical documentation memory set under `docs/`.
- 2026-04-16: Verified the documentation set is internally consistent and ready for future-thread handoff.
- 2026-04-16: Implemented the initial ingestion, validation, and site-profile Streamlit slice; superseded by React/FastAPI.
- 2026-04-16: Added workbook-driven tests covering canonical normalization and gap detection across the four current datasets.
- 2026-04-16: Implemented the first pooled forecasting baseline, backtest metrics, and forecast preview wiring.
- 2026-04-16: Implemented baseline tariff calculations and deterministic optimization scenario evaluation.
- 2026-04-16: Extended the earlier Streamlit app with editable optimization assumptions and savings views; superseded by React/FastAPI.
- 2026-04-16: Added CSV export helpers, bundled site comparison summaries, and reporting downloads.
- 2026-04-18: Consolidated notebook forecast tuning defaults into shared support helpers so LOSO and rolling-origin use the same low-risk settings.
- 2026-04-18: Reduced blend-selection runtime by caching invariant per-cutoff calibration work inside the notebook support module.
- 2026-04-18: Added notebook-support regression tests covering shared evaluation settings, grouped-error summaries, SoL stability, and Mi2 safeguard behavior.
- 2026-04-18: Updated `docs/forecast_model_upgrade_source_of_truth.md` to reflect the current global-by-default base model, threshold-gated segmented training, softened solar rolling variant, simplified rolling blend selection, and the fact that fresh full notebook metrics still need rerunning after these code-path changes.
- 2026-04-18: Fixed the notebook LOSO cell so it no longer depends on leaked `site_has_solar` state, and aligned rolling/latest-fold notebook evaluation with pooled training by fitting on the current site's available history plus the other sites.
- 2026-04-18: Added bias-aware blend selection and horizon-bucket residual correction to the notebook forecast experiment path, and updated notebook regressions plus the source-of-truth doc to reflect that these enhancements are active in code but still need a fresh full notebook rerun for updated score tables.
- 2026-04-18: Rolled back residual correction from the active notebook workflow, reran LOSO, rolling-origin, and lightweight variant comparison, and updated `docs/forecast_model_upgrade_source_of_truth.md` to reflect the restored no-residual baseline plus the remaining weakness on `SuN`, `E`, and `Mi2`.
- 2026-05-03: Added peak-focused metrics and a scikit-learn `enhanced_peak_priority` overlay in the notebook experiment path. Initial exact-interval scoring improved LOSO recall and MD peak rank, but rolling recall was still too weak.
- 2026-05-03: Tuned the overlay to use top-20% peak alerts and plus/minus one-hour peak matching. Fresh corrected rerun showed rolling-origin peak recall improved from `0.477` to `0.782`, LOSO peak recall improved from `0.40` to `0.90`, and 48-hour MD peak rank improved from `9.5` to `5.0`; precision dropped as expected under the catch-peaks-first policy.
- 2026-05-04: Corrected an implementation mistake where peak-priority scoring had been allowed to affect blend-weight selection. `select_blend_weight(...)` is value-safe again, so forecast-value metrics return to the prior baseline while the overlay affects peak alert ranking only.
- 2026-05-04: Executed the notebook peak-alert refinement plan through metric review. Added explicit alert policies, alert smoothing, ramp/approaching-peak features, and bounded MD calibration; rerun metrics retain `current_20pct` and reject MD calibration for now.
- 2026-05-04: Executed the diagnosis and confirmed-alert plan through metric review. Added rolling-origin diagnostics and alert episode summaries; rejected `enhanced_peak_confirmed` and identified late-horizon actual-peak underprediction on `E` and `Mi2` as the strongest next modeling target.
- 2026-05-04: Added and benchmarked `enhanced_late_peak_uplift`, a notebook-only value-model candidate using same-site historical peak envelopes for high-risk late-horizon intervals. Overall rolling MD abs error improved from `114.04` to `97.57` kW, with slight overall RMSE/WAPE improvement; default value model remains `enhanced` pending review because `E` only improves marginally.
- 2026-05-04: Added candidate-level uplift diagnostics and tested a broader non-solar night site-peak fallback. The fallback was rejected after rerun metrics regressed; the active notebook path keeps the narrower uplift candidate.
- 2026-05-04: Added and benchmarked `direct_hgb`, a notebook-only direct-horizon scikit-learn HGB candidate. It is rejected for now: WAPE improves to `21.08%`, but RMSE rises to `150.18` kW and MD abs error worsens to `160.07` kW, with E and Mi2 both worse than `enhanced`.
- 2026-05-05: Installed LightGBM and added notebook-only direct-horizon quantile helpers plus smoke wiring. Tiny E-only proof runs in a few seconds with capped local rows, but p50/p90 behavior is unstable; candidate remains exploratory and is not promoted.

## Handoff Notes for Future Threads
- Start by reading this file, then `docs/requirements.md`, then `docs/architecture.md`.
- If the thread touches `notebooks/model_upgrade_inspection/`, read `docs/forecast_model_upgrade_source_of_truth.md` before changing notebook logic.
- Treat the four current workbooks as the baseline parser and modeling validation set.
- The current parser uses workbook names as hints for solar inference; if future metadata improves, replace that heuristic and update the docs.
- If a future thread discovers new facts about tariffs, solar metadata, or dataset semantics, update the relevant docs before large implementation changes.
- The next high-value implementation step is improving forecast/optimization quality and polishing the judge-facing presentation because the baseline end-to-end flow and CSV exports now exist.

## Maintenance Rules
- Update this file whenever work is completed, started, blocked, or reprioritized.
- Keep this file lightweight and current.
- Mirror final decisions here and also in `docs/requirements.md` or `docs/architecture.md` as appropriate.
