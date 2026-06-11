# Project Requirements

## Purpose
This file is the canonical source of truth for what the TREX competition app must achieve. It should be updated whenever scope, goals, datasets, assumptions, or success criteria materially change.

## Project Overview
The project is a competition app for a Malaysia energy management case study focused on reducing commercial electricity costs under higher Maximum Demand (MD) charges. The app is intended to help judges and collaborators understand how predictive energy management, load shifting, peak shaving, battery sizing, and solar sizing can reduce site operating costs.

The target outcome is a judge-facing decision-support demo that:
- ingests historical site load data
- forecasts future demand
- identifies high-risk peak intervals
- simulates optimization actions
- quantifies cost savings and MD reduction
- explains recommendations through a dashboard

## Problem Statement
Commercial buildings and EV charging facilities in Malaysia are exposed to much higher electricity costs due to the increase in MD charges from about RM30.30/kW to RM97.06/kW effective July 2025. When large loads such as EV charging, HVAC, and machinery operate without coordination, short demand spikes can materially increase the monthly electricity bill.

Variable pricing alone does not guarantee savings. Sites need predictive and automated decision support that can:
- forecast demand before peaks happen
- identify intervals with high MD risk
- recommend load shifting and peak shaving actions
- evaluate whether solar and battery investments are financially worthwhile

## Target Users
- competition judges who need a clear, credible demo
- project teammates who need a shared source of truth
- future Codex threads that need to resume work without prior context

## Datasets in Scope
The current working dataset consists of four Excel workbooks that are treated as four site-level case studies.

### Current Datasets
- `1. Load Profile (With Solar Installed) SoL.xlsx`
  Period currently observed: September 2025 to October 2025
  Notes: multi-sheet workbook, solar metadata present, approximate existing PV size noted as `944.880 kWp`, some non-30-minute gaps
- `2. Load Profile (No Solar) E.xlsx`
  Period currently observed: April 2025 to May 2025
  Notes: uses `start_time` and `end_time` columns, no solar metadata, consistent 30-minute intervals
- `3. Load Profile (No Solar) SuN.xlsx`
  Period currently observed: January 2026 to February 2026
  Notes: extra header rows, lower-load site profile, some non-30-minute gaps
- `4. Load Profile (With Solar) Mi2.xlsx`
  Period currently observed: November 2025 to December 2025
  Notes: solar site, standard timestamp layout, mostly consistent 30-minute intervals

### Inferred Dataset Role
- Each workbook is assumed to represent a different site.
- The current four files form the development, validation, and demo dataset.
- Future datasets are assumed to include unseen sites or unseen site-period combinations and must be supported without hard-coded site logic.

## Functional Requirements
The app must:
- ingest one or more `.xlsx` site datasets
- support the current workbook variations and future unseen file variants
- normalize uploaded files into one canonical site time-series format
- validate timestamps, intervals, gaps, duplicates, and missing values
- infer or accept site metadata such as solar presence and existing PV size
- engineer time-series features for forecasting
- forecast short-horizon future load demand from historical data
- support 1, 2, and 3 month MD planning windows equal to 1440, 2880, and 4320 half-hour intervals
- use recent weekday/weekend interval-shape simulation for monthly planning instead of recursively extending the short-horizon model
- provide probabilistic monthly planning outputs with p50 expected demand, p90 MD-risk demand, and p95 stress demand
- backtest monthly planning outputs against actual monthly MD when enough history exists, including MD error and p90/p95 coverage
- calibrate conservative p90/p95 MD envelopes against recent observed MD so peak-shaving plans do not understate recent chargeable peaks
- apply a lightweight trained monthly MD-risk calibration layer when enough historical folds exist, so conservative p95 envelopes can learn from recent undercoverage without replacing the explainable statistical planner
- provide backend 7-day and 14-day rolling stress-window MD validation scores to extract more repeated peak-risk evidence from the limited available workbooks while keeping official monthly billing evaluation separate
- support backend p90 versus p95 MD-risk optimization comparison so balanced and conservative planning assumptions can be compared later in UI/reporting
- support backend adaptive p90 calibration by selecting recent-history windows and p90 safety floors using stress-window validation coverage, MD error, and bias
- keep new long-horizon and correction-model candidates backend-only until internal 30/60/90-day validation beats the current production planner
- allow backend-only ML MD-risk candidates to adjust p90/p95 risk envelopes while preserving the user-facing p50 forecast path
- allow backend-only full ML planning candidates to predict p50, p90, and p95 for model development, but require explicit validation and no silent fallback before any production promotion
- allow backend-only monthly MD correction candidates to directly predict next-window maximum-demand ratios and localize p50 corrections to peak-risk windows, but require material p50 MD improvement without unacceptable RMSE/WAPE regression before production promotion
- allow backend-only separated-head MD ensemble candidates to combine corrected p50 monthly MD forecasts with the strongest validated p90/p95 risk envelopes, but keep them internal until they improve the accepted score without unacceptable runtime or interval-error regression
- keep the main FastAPI forecast path on the stable monthly planner until an ML candidate shows material score improvement and acceptable local runtime
- expose a separate peak-risk overlay score and high MD-risk window marker in the app without changing `forecast_kw_import`, so the UI can tell a recall-oriented peak-alert story while keeping the value forecast stable
- guard late-night non-solar MD-risk corrections to recent local night-peak shapes and apply them only to p90/p95 risk envelopes, not the p50 forecast path
- keep canonical `kw_import` and `kw_export` as power in kW; if source active import/export values are interval energy in kWh, convert to kW using the interval duration
- expose configurable planning assumptions such as load growth and evening EV/load additions
- expose editable tariff, CAPEX, and planning-month assumptions in the React UI and pass those assumptions into FastAPI optimization requests
- expose editable planning, tariff, CAPEX, growth, and EV-load assumptions directly in the Optimization tab, with an Apply action that reruns the active workbook or retained upload
- explain Optimization results with judge-facing "what changed", "why this scenario", and "savings sensitivity" copy without adding site-by-site or model-comparison views
- return backend-generated Optimization explanation, planning-basis labels, confidence flags, and active-analysis +/-10% tariff/CAPEX sensitivity rows for the current workbook or upload
- show a Peak Risk Timeline and Solar Impact Comparison in Site Profile using the active analysis rather than site-by-site/model comparison
- identify likely peak demand periods and MD-risk intervals
- simulate flexible load shifting using an aggregate flexible-load-block model
- simulate battery dispatch for peak shaving and optional energy arbitrage
- simulate solar sizing, including incremental PV for sites with existing solar
- estimate baseline versus optimized electricity cost
- estimate MD reduction, peak reduction, and simple payback
- provide a dashboard with site profiling, forecasting, optimization, and executive-summary views
- provide the dashboard through a local React/Vite frontend backed by a FastAPI API over the existing Python analysis modules
- show staged analysis progress and clear API/workbook error cards during local React/FastAPI processing
- export normalized data and scenario outputs for analysis or presentation

Current implementation note:
- The app now exports normalized data, forecast tables, scenario summaries, and bundled site comparison summaries as CSV files from the dashboard.
- The React/FastAPI path now accepts editable tariff, CAPEX, and planning-month assumptions, and the forecast payload includes a separate peak-risk overlay score for high MD-risk chart markers.
- The Optimization tab now treats assumptions as editable decision inputs rather than locked display values.
- The backend now owns the structured Optimization recommendation explanation and sensitivity payload consumed by the React UI.
- The Site Profile dashboard now includes peak-risk timeline and solar-impact cards based on existing forecast and optimized schedule payloads.

## Non-Functional Requirements
The app should be:
- explainable, with assumptions visible in the UI rather than hidden in code
- robust to heterogeneous Excel formats and future unseen sites
- site-agnostic and configuration-driven
- fast enough for a live competition demo
- reproducible, so future threads can retrace assumptions and results
- maintainable, with stable documentation and modular code boundaries

## Assumptions and Constraints
- Available data is site-level meter data, not device-level telemetry.
- Controllable demand is modeled as flexible load blocks rather than measured EV charger, HVAC, or machinery schedules.
- MD is approximated from the maximum observed or forecast `kw_import` within the modeled billing window.
- For multi-month planning, MD is charged on the highest 30-minute interval within each 30-day planning month.
- Default billing analysis includes both MD charges and energy charges, with user-editable rate assumptions.
- Default MD rate is RM97.06/kW effective July 2025 unless later evidence requires revision.
- Solar production for sizing analysis may use a built-in Malaysia daytime generation profile when direct solar generation inputs are unavailable.
- The built-in solar sizing profile may use a clear-sky sine curve between 06:00 and 18:00 when irradiance data is unavailable.
- Forecasting is designed to generalize to unseen sites, not only to memorize the four current sites.
- The app is optimized first as a judge-facing decision-support demo rather than as a production EMS controller.
- Phase 1 of the Streamlit replacement does not require a database. Uploaded files and results are processed locally per request; Supabase is reserved for a later saved-analysis workflow.

## Success Criteria
### Minimum Viable Product
- User can upload any of the current four workbooks without manual preprocessing.
- App produces a normalized load dataset and basic validation summary.
- App generates a demand forecast and flags likely peak intervals.
- App compares baseline versus optimized scenarios for at least flexible load shifting and battery dispatch.
- App renders a usable dashboard for one selected site.

Current implementation note:
- The current app now satisfies the ingestion, validation, forecasting, and basic scenario-comparison portions of the MVP, but the optimization logic is still a first deterministic baseline rather than the final competition-grade controller.

### Strong Competition-Ready Demo
- App supports all four current datasets and presents them as distinct case studies.
- App shows credible multi-site forecasting and optimization behavior.
- App prioritizes useful MD peak detection and peak ranking, because missing MD peaks directly weakens the peak-shaving recommendation.
- App quantifies MD reduction, bill savings, and simple payback for candidate battery and PV sizes.
- App clearly explains assumptions, risks, and why recommendations differ across sites.
- App is resilient enough to ingest future unseen datasets with limited manual adjustment.
- App gives judges downloadable outputs and a cross-site comparison view to support presentation storytelling.

## Open Questions / Pending Decisions
- Final energy-tariff assumptions beyond MD charges still need to be locked from competition materials or explicit team assumptions.
- CAPEX and payback assumptions for battery and solar sizing still need fixed values or ranges.
- The default planning horizon is now user-selectable at 1, 2, or 3 months; future work may add billing-cycle-date configuration if competition materials require calendar-month billing instead of 30-day planning blocks.
- The final export/report format for presentation use still needs to be chosen.
- The final optimization scoring logic may need refinement once competition judging priorities are clearer.
- Supabase schema, authentication, storage, and saved-project requirements are deferred until the local React/FastAPI workflow is accepted.

## Document Maintenance Rules
- Update this file when scope, goals, dataset understanding, assumptions, or success criteria change.
- If an assumption becomes invalid, revise the original section instead of only appending a correction elsewhere.
- Record locked decisions here and also mirror them in `docs/status.md`.
