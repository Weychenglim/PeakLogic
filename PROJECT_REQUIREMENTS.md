# Project Requirements

The canonical requirements live in `docs/requirements.md`.

Current requirement emphasis:

- The app must support 1-3 month MD planning windows, not only next-day forecasting.
- Canonical `kw_import` must always mean power in kW. If source values are 30-minute interval energy, convert with `kW = kWh / 0.5`.
- Monthly planning should expose p50 expected demand, p90 MD-risk, and p95 stress envelopes, then backtest those envelopes against actual monthly MD where enough history exists.
- MD peak planning must use calibrated p90/p95 envelopes with a recent observed MD floor so conservative plans do not understate recent chargeable peaks.
- Monthly MD planning should use a lightweight trained historical calibration layer when enough site history exists, while keeping the statistical recent-pattern planner as the fallback for new or short-history uploads.
- Model evidence should include backend 7-day and 14-day rolling stress-window MD scores so the existing limited datasets can provide more repeated peak-validation cuts without treating them as official monthly billing scores.
- Optimization should support backend p90 versus p95 MD-risk basis comparison so later UI/reporting can show balanced versus conservative planning tradeoffs.
- The p90 balanced planning envelope should support adaptive backend calibration, selecting recent-history windows and p90 safety floors from 7/14-day stress validation instead of relying on a single fixed setting.
- Peak/MD-risk prediction is a core requirement because missed monthly MD peaks weaken battery dispatch, load shifting, MD reduction, and savings estimates.
- The app should expose a separate peak-risk overlay score for high MD-risk windows without changing the forecast kW path, and should label the overlay as a recall-oriented alert that accepts more false positives.
- Tariff, CAPEX, and planning-month assumptions must be visible/editable in the React UI and passed to the FastAPI analysis request.
- The Optimization tab must also expose editable planning, tariff, CAPEX, growth, and EV-load assumptions and rerun the active analysis from that tab.
- Optimization copy should be judge-facing and explain what changed, why the selected scenario was chosen, and which assumptions affect savings without introducing site-by-site or model comparison.
- Backend analysis responses must return structured Optimization explanation, confidence flags, and active-analysis tariff/CAPEX sensitivity rows so the UI does not invent the recommendation story.
- Site Profile must include an active-analysis Peak Risk Timeline and Solar Impact Comparison so the dashboard matches the operational peak and solar-impact story.
- Long-running analysis states should show upload, normalization, forecasting, and optimization progress, with clear API/workbook error messaging.
- The current notebook work remains experiment-first and should not be promoted to the production app until rolling-origin benchmarks justify it.
- New backend forecasting models must be accepted by internal 30/60/90-day validation before becoming the production default; model-development candidates must remain backend-only and must not surface model details in the user interface.
- The judge-facing dashboard now uses a local React/Vite frontend backed by a FastAPI API over the existing `trex_energy` package.
- Supabase/database persistence is deferred until the local React plus FastAPI workflow is stable; Phase 1 processes uploads locally without saved accounts, projects, or analysis history.

Latest requirement note:

- 2026-05-10: Replaced the Streamlit UI path with a local React/FastAPI app and explicitly deferred Supabase integration.
- 2026-05-09: Shifted production app emphasis to monthly MD planning simulation with 1, 2, and 3 month windows.
- 2026-05-10: Added probabilistic monthly planning requirements for p50/p90/p95 envelopes and monthly MD backtest coverage.
- 2026-05-10: Added an explicit MD peak reliability requirement: conservative envelopes should floor against recent observed MD.
- 2026-05-10: Added trained monthly MD-risk calibration on top of the statistical planner when enough history is available.
- 2026-05-10: Added backend-only 7/14-day stress validation and p90/p95 optimization tradeoff requirements.
- 2026-05-10: Added adaptive p90 calibration requirements based on stress-window candidate search.
- 2026-05-11: Added React UI requirements for editable tariff/CAPEX assumptions, staged analysis progress, API/workbook error cards, and a separate peak-risk overlay.
- 2026-05-11: Added Optimization-tab requirements for editable assumptions, same-analysis reruns, and simpler judge-facing peak-demand wording.
- 2026-05-11: Added backend requirements for Optimization explanation, confidence flags, and single-analysis +/-10% tariff/CAPEX sensitivity.
- 2026-05-11: Added Site Profile requirements for peak-risk timeline and solar impact comparison cards.
- 2026-05-11: Added the requirement that long-horizon model candidates stay backend-only until their metric score beats the current production planner.
- 2026-05-12: Added backend-only correction-model development scope: candidates may improve MD peak estimates internally, but the UI must continue to show only final results.
- 2026-05-12: Added backend-only MD-risk model scope: ML may adjust p90/p95 risk envelopes while preserving the p50 forecast path and all user-facing UI behavior.
- 2026-05-13: Added backend-only full-ML planning candidate scope: ML may predict p50, p90, and p95 internally, but must raise on short history instead of silently falling back and must stay out of the UI unless validation beats the current production planner.
- 2026-05-13: Added gated ML planning promotion scope: the main FastAPI forecast path may use the gated ML planning candidate for enough-history analyses, while keeping model details out of the React UI and retaining the statistical planner for short-history robustness.
- 2026-05-03: Added explicit competition-ready emphasis on useful MD peak detection and peak ranking.
