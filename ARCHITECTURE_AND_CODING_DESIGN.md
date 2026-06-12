# Project Architecture and Coding Design

## Purpose
This file is the canonical source of truth for how PeakLogic should be structured and how the code should be written. It should be updated whenever module boundaries, data schema, interfaces, modeling strategy, or coding conventions materially change.

## System Overview
The app is migrating from a Streamlit-based decision-support tool to a local React/Vite dashboard backed by a FastAPI API over the existing Python analysis modules. It has these major parts:
- upload and validation layer
- data normalization pipeline
- feature engineering and preprocessing layer
- forecasting engine
- optimization engine
- billing and savings engine
- React dashboard, API, and export layer

The system is designed for heterogeneous site-level Excel uploads. It must normalize historical meter data, forecast future demand, simulate optimization strategies, and present results in a way that is explainable to judges and easy to resume for future threads.

## Primary User Flow
1. User uploads one or more Excel workbooks.
2. App validates structure, timestamps, and site metadata.
3. App normalizes the data into one canonical schema.
4. App computes site profile features and baseline metrics.
5. App generates demand forecasts and peak-risk indicators.
6. App runs optimization scenarios for flexible loads, battery sizing, and solar sizing.
7. App calculates baseline and optimized bills.
8. App presents results through interactive dashboard views and exports.

## Data Flow
`React upload -> FastAPI -> validation -> normalization -> feature engineering -> forecasting -> optimization -> savings simulation -> React dashboard`

Each stage must pass structured outputs to the next stage without hidden coupling.

## Canonical Data Model
The normalized interval-level dataset must support at least these columns:
- `site_id`
- `interval_start`
- `interval_end`
- `kw_import`
- `kw_export`
- `kvar_import`
- `kvar_export`
- `has_solar`
- `existing_pv_kwp`
- `source_file`
- `source_sheet`
- `is_imputed`

Recommended derived columns for preprocessing and modeling:
- `interval_minutes`
- `date`
- `hour`
- `minute`
- `day_of_week`
- `is_weekend`
- `month`
- `billing_period`
- `is_peak_tariff_period`
- lag features such as previous interval demand
- rolling statistics such as rolling mean and rolling max

## Module Design
The implementation should be split into focused modules with clear responsibilities.

### Current Code Layout
The current repository layout is:
- `api.py`: FastAPI entry point for local React frontend integration, workbook upload analysis, bundled-site analysis, and JSON/CSV payloads
- `render.yaml`: Render web service blueprint for deploying the FastAPI backend
- `kinetic-precision/`: Vite React frontend replacing the Streamlit dashboard for the local demo path
- `kinetic-precision/src/components/DashboardAssistant.tsx`: floating read-only assistant panel and compact analysis-context builder for active dashboard questions
- `kinetic-precision/src/components/SettingsPage.tsx`: lightweight settings/deployment status page for API, frontend, Supabase, and demo-readiness checks
- `kinetic-precision/vercel.json`: Vercel project configuration for deploying the Vite frontend from the subdirectory
- `trex_energy/ingestion.py`: workbook parsing and canonical normalization
- `trex_energy/validation.py`: interval-quality checks and validation summaries
- `trex_energy/profile.py`: workspace dataset loading and site summary helpers
- `trex_energy/forecasting.py`: pooled baseline forecasting, peak-risk scoring, and backtest helpers
- `trex_energy/forecasting.py`: also includes monthly MD planning simulation using recent weekday/weekend half-hour patterns, p50/p90/p95 envelopes, recent-MD floor calibration, and monthly MD backtesting
- `trex_energy/forecasting.py`: also includes a backend-only direct long-horizon LightGBM quantile candidate for 1-3 month forecasting; the production API does not use it by default until internal validation beats the current planner
- `trex_energy/forecasting.py`: also includes a backend-only baseline-correction LightGBM candidate that learns p50 residuals over the current planner while leaving p90/p95 risk envelopes stable during model development
- `trex_energy/forecasting.py`: also includes a backend-only MD-risk-only LightGBM candidate that preserves p50 forecast values and adjusts only p90/p95 risk envelopes using site-regime peak features, gated undercoverage probabilities, tuned uplift policy caps, and peak-timing localization
- `trex_energy/forecasting.py`: also includes a backend-only full ML planning LightGBM candidate that predicts p50, p90, and p95 residuals over planner-aware features; it is model-development only and raises on short history instead of silently falling back
- `trex_energy/forecasting.py`: also includes `forecast_gated_ml_planning_profile` as a backend-only experiment; it keeps the ML MD-risk p90/p95 behavior and applies bounded p50 correction only to high-confidence intervals
- `trex_energy/forecasting.py`: also includes `forecast_monthly_md_corrected_profile` as a backend-only experiment; it predicts next-window monthly MD ratios and localizes p50/p90/p95 corrections to forecast peak-risk windows instead of changing the whole interval path
- `trex_energy/forecasting.py`: also includes `forecast_md_ensemble_profile` as the promoted separated-head app model; it takes p50 from the monthly MD correction candidate and p90/p95 from the ML MD-risk candidate, then reconciles ordering
- `trex_energy/tariff.py`: bill-component calculations for MD and energy charges
- `trex_energy/optimization.py`: deterministic scenario evaluation for flexible shifting, battery, and clear-sky sine solar
- `trex_energy/optimization.py`: also normalizes Optimization finance outputs into planning-period savings, average monthly savings, annualized savings, CAPEX, and monthly payback
- `trex_energy/assistant.py`: deterministic grounded assistant responses for active dashboard analysis questions and safe suggested prompts
- `trex_energy/reporting.py`: CSV export helpers, executive summary text, deterministic recommendation explainability, and cross-site comparison summaries
- `tests/test_ingestion.py`: workbook-driven ingestion and validation tests against the four provided files
- `tests/test_forecasting.py`: forecasting and backtest tests
- `tests/test_optimization.py`: tariff and optimization tests
- `tests/test_reporting.py`: reporting and export tests
- `pyproject.toml`: project metadata and baseline dependencies

### Parser / Ingestion
Responsibilities:
- read `.xlsx` files
- ignore Excel `~$` temporary lock files during bundled workspace discovery
- detect workbook shape
- locate header rows and sheets
- extract raw meter intervals
- infer initial site metadata from workbook name or workbook content when possible
- detect active power versus interval-energy headers for import/export columns and normalize canonical active columns to kW

### Validation
Responsibilities:
- detect duplicate timestamps
- detect missing intervals and non-30-minute gaps
- detect missing or malformed numeric fields
- flag suspicious values for review
- produce user-facing validation warnings

### Preprocessing
Responsibilities:
- convert raw uploads into the canonical schema
- sort and deduplicate intervals
- apply light imputation rules where appropriate
- derive time-based features
- prepare baseline site metrics

### Forecasting
Responsibilities:
- train or run pooled multi-site models
- apply site-local calibration for unseen sites
- output interval-level demand forecasts
- output peak-risk indicators and predicted daily peak windows
- for 1-3 month planning, output `forecast_kw_import`, `md_risk_envelope_kw`, `p50_forecast_kw`, `p90_md_risk_kw`, `p95_stress_kw`, `calibrated_p90_md_risk_kw`, `calibrated_p95_stress_kw`, and `planning_month` from recent pattern simulation rather than recursive ML predictions
- backtest monthly planning by comparing simulated 30-day MD against actual 30-day MD and reporting envelope coverage
- keep full ML planning candidates separate from the production planner until they improve MD planning metrics without materially worsening normal interval forecast error
- keep monthly MD correction candidates separate from the production planner until p50 MD gains are large enough to justify any interval-error tradeoff
- route FastAPI analysis through the promoted separated-head MD ensemble when enough history/model support is available
- fall back to the stable recent-pattern monthly planner when the promoted ensemble cannot train or score safely for an upload

### Optimization
Responsibilities:
- simulate flexible-load-block shifting under configurable rules
- simulate battery dispatch under power and energy constraints
- exclude physically invalid battery scenarios where battery power is present without storage energy, or storage energy is present without battery power
- simulate solar sizing scenarios using a standard PV generation profile
- use a clear-sky sine solar factor between 06:00 and 18:00 when no measured PV generation profile is available
- return interval-level optimized schedules and scenario summaries
- evaluate active-analysis sensitivity by rerunning the deterministic scenario evaluator with +/-10% MD-rate, battery-CAPEX, and solar-CAPEX variants
- keep `savings_rm` as modeled planning-period savings while exposing `monthly_savings_rm`, `annual_savings_rm`, `capex_rm`, and `savings_period_months` for UI/reporting clarity
- compute simple payback from average monthly savings, not total multi-month planning-period savings

### Tariff Calculator
Responsibilities:
- compute baseline and optimized electricity bills
- separate MD and energy components
- sum MD charges by 30-day planning period while reporting the maximum MD interval for display
- support editable tariff assumptions
- produce scenario comparison metrics

### Visualization
Responsibilities:
- render upload validation summaries
- render site load profiles and heatmaps
- render forecast and peak-risk views
- keep Site Profile scoped to historical load and site-health metrics rather than future risk/action content
- make the sidebar New Analysis action jump back to Data Upload while preserving the current analysis until the user runs a new one
- expose a simple Settings page for public deployment diagnostics rather than deep user preferences
- derive Site Profile observed peak-event, load-pattern, and compact site-fact summaries from `load_history`, `profile`, `metadata`, and `validation`, without requiring a new backend endpoint
- render future risk/action content only in Forecast & Risk
- render Forecast & Risk risk periods as ranked Top Risk Windows from the shared forecast helper rather than as a block timeline
- derive Forecast & Risk right-rail response items from the selected forecast window plus the active optimization target, while leaving financial scenario comparison in Optimization
- use an independent left-content/right-rail Forecast & Risk layout so the demand chart and risk list stack naturally without being blocked by the action cards' height
- format Forecast & Risk peak-window labels with deterministic date and time context, and expose a standby mitigation state when no immediate kW reduction is needed
- rank Forecast & Risk critical windows by forecast kW intensity before risk-score tie-breaks, avoiding contradictions between the Window Peak card and Top Risk Windows list
- select Forecast & Risk chart sub-windows from the start of `forecast.points` so shorter views preview the beginning of the future planning horizon consistently with the month view
- build Forecast & Risk month-scale window options from `analysis.assumptions.planning_months`, so 2-month and 3-month analyses expose 60-day and 90-day forecast scopes
- render optimization comparisons and executive-summary outputs
- render a compact Optimization options-considered comparison for recommended, fastest-payback, maximum-peak-cut, and lowest-investment profitable alternatives when those alternatives are distinct
- render a concise Optimization decision checklist covering data readiness, locked assumptions, and presentation evidence instead of exposing the full sensitivity table in the main page flow
- render an Optimization Explainable AI panel under Options Considered, deriving it from `optimization.scenarios`, `optimization.schedule_preview`, and `optimization.sensitivity` so the scenario table is followed by comparison evidence instead of repeated KPI-card values
- derive Optimization PV feasibility display values from organizer product sheets: Trina Vertex N 590-620W module at 620 W, 2.382 m by 1.134 m, 33 kg, and Sigen Hybrid Inverter Gen 2 planning at up to 24 kWp PV input per 12 kW three-phase inverter
- keep the sidebar application shell free of hardcoded user-profile placeholders until real authenticated profile data is available
- keep Optimization focused on the active analysis, with judge-facing decision copy and editable assumptions instead of site/model comparison views
- render a floating Dashboard Assistant only when an active analysis exists, with suggested questions limited to site explanation, optimizer reasoning, option tradeoffs, and approval checks
- display assistant response provenance in the chat UI: API mode when a provider responds, dashboard data mode when deterministic fallback is used
- normalize assistant text before rendering so provider markdown headings, bold markers, and bullet markers do not appear as raw characters in the chat panel
- render structured suggested-action buttons under assistant answers; each action must target only the fixed dashboard allow-list (`profile`, `forecast`, `optimization`, `summary`, `settings`)
- build a compact assistant context in React from selected metadata, profile, validation, assumptions, Forecast & Risk top-window evidence, best scenario, and scenario evidence; do not send CSV exports or full raw history to the assistant endpoint

### React State Ownership
Responsibilities:
- keep `App.tsx` as the owner of selected bundled source, retained upload file, active assumptions, loading state, and current analysis payload
- pass editable assumptions and apply callbacks into the Optimization tab
- rerun bundled analysis through the bundled endpoint and rerun uploads through the retained `File` object when assumptions are reapplied
- pass the current analysis into `DashboardAssistant`; the assistant must stay read-only and must not mutate assumptions, rerun analyses, or approve recommendations

### Assistant API
Responsibilities:
- expose `POST /api/assistant` for question answering against compact active-analysis context
- load an optional root `.env` during local FastAPI startup, preserving already-set environment variables from the shell or hosting platform
- keep provider API keys server-side only; OpenAI-compatible chat completion providers use `AI_ASSISTANT_API_KEY`, `AI_ASSISTANT_BASE_URL`, and `AI_ASSISTANT_MODEL`, with `ZAI_API_KEY`, `ZAI_BASE_URL`, and `ZAI_MODEL` accepted as aliases
- keep legacy OpenAI Responses API support available through `AI_ASSISTANT_PROVIDER=openai`, `OPENAI_API_KEY`, and optional `OPENAI_ASSISTANT_MODEL`
- fall back to deterministic grounded answers from `trex_energy.assistant` when no provider is configured or provider calls fail
- avoid judge-facing presentation-script generation in default suggested prompts and scope
- generate suggested actions from app-owned deterministic logic rather than free-form provider text, so API mode cannot invent invalid navigation targets
- route high-risk event/window questions to Forecast & Risk top-window evidence before generic approval, tariff, or CAPEX risk checks
- route broad next-step questions to a grounded action-plan answer that combines forecast risk, option comparison, assumption checks, and data-quality review

### Export / Reporting
Responsibilities:
- export normalized datasets
- export forecast and scenario tables
- support presentation-friendly summaries
- generate Optimization explanation text, planning-basis labels, confidence flags, and sensitivity summaries for the active analysis
- include annualized savings and planning-period context in Optimization explanation text so judges can read financial impact without misinterpreting the modeled horizon
- keep Optimization recommendation explainability in a pure React helper so contract tests can verify scenario-comparison wording without requiring a browser render

## Coding Design Conventions
- Use Python as the primary implementation language.
- Use React/Vite for the dashboard layer and FastAPI for the local backend boundary.
- Defer Supabase until saved analyses, authentication, or shared project history are required.
- For public demos, deploy FastAPI to Render and the Vite frontend to Vercel; set `FRONTEND_ORIGINS` on Render and `VITE_API_BASE_URL` on Vercel.
- Keep logic site-agnostic and avoid hard-coded branching for named sites.
- Prefer small, focused modules over large mixed-responsibility files.
- Keep assumptions configuration-driven so tariff, flexibility, and finance values can be edited without rewriting logic.
- Use explicit function inputs and outputs.
- Add concise docstrings where they reduce ambiguity.
- Prefer pure functions for data transformation and billing calculations when practical.
- Keep business rules visible in code and mirrored in documentation.
- Avoid hidden notebook-only logic; core logic should live in importable modules even if notebooks are later used for exploration.

## Interface Contracts
### Normalization Input
- one or more Excel workbooks
- optional user overrides for `site_id`, `has_solar`, `existing_pv_kwp`, and tariff assumptions

### Normalization Output
- canonical interval-level table using the defined schema
- validation summary with warnings and inferred metadata

### Forecast Output
- interval-level forecast table with at least:
  `site_id`, `interval_start`, `forecast_kw_import`, `peak_risk_score`, `is_predicted_peak`
- monthly planning forecast tables additionally include:
  `md_risk_envelope_kw`, `p50_forecast_kw`, `p90_md_risk_kw`, `p95_stress_kw`, `planning_month`, `planning_method`, `growth_multiplier`, `ev_load_kw`

### Optimization Output
- interval-level optimized schedule table
- scenario summary table with at least:
  `scenario_id`, `battery_kw`, `battery_kwh`, `solar_kwp`, `md_before`, `md_after`, `bill_before_rm`, `bill_after_rm`, `savings_rm`, `payback_months`

### Recommendation Summary
- one selected best-fit scenario
- short explanation of the recommendation
- explicit assumptions used for the recommendation

## Modeling Approach
### Forecasting Strategy
- Use pooled multi-site forecasting as the default approach.
- Use recent weekday/weekend interval-shape simulation as the production monthly MD planning approach for 1-3 month horizons.
- Use the separated-head MD ensemble as the preferred FastAPI forecast path; it reuses the stable recent-pattern simulation as its baseline and fallback.
- Treat p50 as the expected planning profile, p90 as the conservative MD-risk profile, and p95 as the stress profile.
- Apply a recent observed MD floor to calibrated p90/p95 envelopes, with `md_risk_envelope_kw` pointing to the calibrated p95 stress profile for conservative optimization.
- When enough rolling monthly folds exist, fit a lightweight trained MD-risk calibrator over historical p95 monthly MD misses and apply its conservative uplift/intercept to `md_risk_envelope_kw`; if calibration cannot fit, keep the statistical recent-pattern envelope unchanged.
- Evaluate monthly planning quality with rolling 30-day MD backtests, including p50/p90/p95 MD error and p90/p95 coverage.
- Expose 7-day and 14-day rolling stress-window MD validation from the same planning logic to increase diagnostic fold counts on the limited four-workbook dataset; these scores are model evidence, not tariff billing periods.
- Expose adaptive p90 calibration helpers that search `recent_days` and `p90_floor_multiplier` candidates, rank by stress-window coverage shortfall first, then MD absolute error and positive bias.
- Let optimization select `expected`, `p90`, or `p95` MD-risk basis. The p90 basis uses `calibrated_p90_md_risk_kw` when present; the p95 basis uses `md_risk_envelope_kw`.
- Annotate monthly planning forecasts with `peak_risk_overlay_score` and `is_peak_risk_overlay` so the React chart can show high MD-risk windows without changing `forecast_kw_import`; the marker boolean is gated by both overlay-score percentile and upper-decile `md_risk_envelope_kw` materiality.
- For non-solar sites with recent local night peaks, apply a gated late-horizon night-shape floor to p90/p95 risk envelopes only. This avoids the rejected broad non-solar night fallback that regressed overall MD error in notebook experiments.
- Do not recursively forecast 1440-4320 intervals with the short-horizon Ridge model because long recursive horizons drift and are less defensible for planning.
- Include site-agnostic temporal and lag-based features.
- Add site-local calibration so unseen uploads can adapt to local scale and behavior.
- Treat peak/MD-risk ranking as a first-class evaluation target, not only a visual flag derived from forecast magnitude.
- Keep experimental peak-alert overlays separate from forecast-value generation until rolling-origin benchmarks justify promotion.
- Evaluate operational peak alerts with configurable alert quantiles and near-miss windows because battery/load-shifting action can still be useful when an alert is slightly early or late.
- Keep notebook-only peak-alert policy comparison, alert smoothing, ramp features, and MD calibration candidates separate from the production app until the metric score is reviewed and explicitly accepted.
- Use rolling-origin diagnostic tables to identify failure regimes before adding new correction layers; the current diagnosis points to late-horizon actual-peak underprediction on E and Mi2.
- Keep late-horizon value corrections as explicit candidate rows until accepted. The first `enhanced_late_peak_uplift` candidate uses same-site historical peak envelopes to lift only high-risk late-horizon forecast values with a hard cap, and remains separate from the default `enhanced` forecast.
- Candidate-level diagnostics should compare value-model candidates by regime before promotion. The broader non-solar night site-peak floor option remains disabled unless explicitly tested because the first rerun regressed overall MD error.
- Direct-horizon boosted candidates may be benchmarked in the notebook, but the first pooled scikit-learn HGB candidate is rejected and should not be promoted. Future boosted experiments should change the training strategy or dependency choice rather than tuning the same pooled HGB loop.
- LightGBM direct-horizon quantile candidates may be explored only through capped benchmark modes. The first tiny E-only proof showed fast app-like fitting when capped, but unstable p50/p90 behavior, so it is not a production forecast strategy.
- The production app must not run LOSO or rolling-origin benchmark retraining during upload. The promoted MD ensemble trains once per analysis with capped training rows and falls back to the stable planner if it cannot run.
- Prioritize explainability and stable performance over maximum model complexity.

### Optimization Strategy
- Use deterministic scenario-based optimization rather than an opaque end-to-end RL controller.
- Model flexible load as a configurable share of aggregate demand with a shift window.
- Search across discrete battery power and duration combinations.
- Search across discrete solar sizing combinations.
- Score scenarios by MD reduction, bill savings, and simple payback.
- Allow conservative planning runs to optimize against `md_risk_envelope_kw` so scenario ranking targets monthly MD risk, not only the expected load shape.

## Error Handling and Resilience
The system must handle:
- missing intervals
- non-30-minute gaps
- duplicate timestamps
- malformed or shifted header rows
- unknown workbook sheet layouts
- missing solar metadata
- partial uploads with incomplete months
- future workbook variants not identical to the current four files

When recovery is possible, the app should continue with warnings. When recovery is not safe, the app should stop the affected flow with a clear error message.

## Testing Strategy
Testing should cover:
- parser support for the four known workbooks
- parser support for multi-sheet and `start_time` / `end_time` variants
- validation behavior for gaps, duplicates, and malformed rows
- preprocessing invariants such as sorted intervals and correct schema output
- forecasting backtests on each available site
- peak-detection quality against actual high-demand intervals
- peak-ranking metrics such as peak recall, peak F1, MD peak rank, and peak timing error
- threshold and window sensitivity for peak-alert policies
- optimization invariants such as energy conservation and battery state-of-charge bounds
- tariff calculation consistency
- React/FastAPI smoke tests for the main user flow

## Technical Debt / Future Extensions
- device-level controllable asset modeling
- richer tariff structures from utility-specific inputs
- more realistic PV generation from irradiance or weather data
- deeper financial modeling beyond simple payback
- forecast confidence calibration and scenario uncertainty communication
- automated report generation for submissions

## Operating Rules for Future Threads
Read these project files in this order before making major changes:
1. `docs/status.md`
2. `docs/requirements.md`
3. `docs/architecture.md`

If a future thread learns something that changes module structure, interfaces, or modeling strategy, update this file before making major implementation changes.

## Current Implementation State
The initial implementation slice currently covers:
- multi-format Excel workbook ingestion for the four known dataset shapes
- canonical normalization into a shared schema
- interval validation with gap and duplicate reporting
- workspace dataset discovery for the bundled competition files
- a pooled baseline forecasting module with 48-interval forecasting and backtest metrics
- a monthly MD planning simulator with 1-3 month horizons and MD-risk envelope output
- a lightweight trained monthly MD-risk calibration layer that adjusts p95 envelopes from rolling historical fold undercoverage
- backend 7/14-day rolling stress-window validation scores and p90/p95 optimization tradeoff helpers for future UI/reporting
- backend adaptive p90 calibration candidate scoring for future balanced-risk forecast selection
- deterministic scenario evaluation for flexible load shifting, battery dispatch, and solar offset
- MD-plus-energy bill simulation with editable tariff assumptions and 30-day MD billing periods
- CSV export helpers for normalized data, forecast output, scenario summaries, and bundled site comparison summaries
- a local FastAPI API plus React/Vite frontend path that analyzes bundled and uploaded workbooks without database persistence
- React-visible tariff, energy-rate, CAPEX, and planning-month assumptions are passed through FastAPI into `OptimizationConfig` and `TariffConfig`
- The Optimization tab can edit tariff, CAPEX, growth, EV-load, and planning-month assumptions, then rerun the active analysis from the decision view.
- `api.py` allows local/private dev origins and Vercel app origins for CORS; exact production frontend origins can be added through the comma-separated `FRONTEND_ORIGINS` environment variable.
- FastAPI optimization responses include `explanation`, deterministic `explainability`, and `sensitivity` objects generated by backend reporting and optimization helpers.
- React loading/error UX includes upload, normalize, forecast, and optimize progress steps plus clearer API/workbook error cards
- Site Profile derives historical display summaries from the existing `load_history`, `profile`, `metadata`, and `validation` payloads; no new backend endpoint is required.
- Site Profile no longer duplicates forecast risk/action content; it now shows historical load, observed MD, observed peak events, and one unified Site Operating Pattern section with three pattern summaries plus compact site facts.
- Forecast & Risk now renders ranked Top Risk Windows from the shared `buildTopRiskWindowItems` helper, replacing the noisy block-grid timeline with time, level, intensity, and action rows.
- Forecast & Risk now derives a window-specific Recommended Response checklist and Immediate Mitigation card from forecast risk, selected window peak, and the optimized MD target, without duplicating Optimization savings/payback content.
- Forecast & Risk uses an independent two-column layout, date-aware Window Peak labels, and a no-immediate-reduction mitigation state for selected windows below the MD target.
- Forecast & Risk Top Risk Windows now ranks critical windows by peak kW before risk-score tie-breaks so MD-intensity ordering matches the Window Peak story.
- Forecast & Risk uses the shared `selectForecastWindowPoints` helper so 12h/24h/48h chart windows start at the first future forecast interval instead of tail-slicing the monthly planning horizon.
- Forecast & Risk now builds its full-horizon dropdown options and Top Risk Windows outlook label from active planning months rather than hardcoding a 30-day maximum.
- FastAPI now tries `forecast_md_ensemble_profile` for analysis forecasts before falling back to `forecast_monthly_planning_profile`; bundled runs pass the other bundled workbook frames as reference training data.
- `forecast_monthly_planning_profile` reconstructs `forecast_gross_load_kw` for solar sites using the shared clear-sky sine solar factor and resolved existing PV capacity, then derives `forecast_kw_import` and MD-risk fields on the utility-facing grid-import basis.
- `evaluate_site_scenarios` keeps baseline bills and MD on `baseline_kw_import`, while using `forecast_gross_load_kw` plus explicit existing/new solar offsets for optimization scheduling when gross-load fields are present.
- FastAPI analysis responses include `load_history` for historical charting. Site Profile consumes `load_history`, while Forecast & Risk consumes `forecast.points` so historical and future graph windows stay separate.

The following major areas are still planned but not yet implemented:
- Supabase persistence for saved analyses, if needed after the local app stabilizes
- polished export and reporting workflows beyond CSV downloads
- richer optimization logic, site-local calibration, and stronger finance modeling

## Document Maintenance Rules
- Update this file when architecture, schema, interface contracts, or coding design change.
- Keep this file curated and stable; avoid turning it into a dated changelog.
- Record implementation progress in `docs/status.md`, not here.
