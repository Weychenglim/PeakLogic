# Backend Optimization Explanation Design

## Goal

Make the backend return the decision explanation and single-analysis sensitivity data that the Optimization tab needs, so the UI is not responsible for inventing the recommendation story.

## Scope

- Keep the enhancement focused on the active workbook or active upload.
- Do not add site-by-site comparison or model-comparison output to the Optimization view.
- Add backend-generated optimization explanation fields:
  - `what_changed`
  - `why_this_scenario`
  - `savings_sensitivity`
  - `confidence_flags`
  - `planning_basis_label`
  - `planning_basis_description`
- Add lightweight sensitivity rows for the active forecast by varying:
  - MD rate -10% and +10%
  - battery CAPEX -10% and +10%
  - solar CAPEX -10% and +10%
- Treat growth rate, EV load, and planning months as full-analysis assumptions that already rerun through the Apply action.

## Architecture

`trex_energy.optimization` owns the numeric sensitivity calculation because it can reuse the existing deterministic scenario evaluator with adjusted tariff/CAPEX values. It returns a dataframe of active-analysis sensitivity rows.

`trex_energy.reporting` owns judge-facing explanation text and confidence flags because those are presentation contracts derived from scenario, validation, and assumption context.

`api.py` packages the new structures under `optimization.explanation` and `optimization.sensitivity` in both bundled and upload analysis responses.

`kinetic-precision/src/lib/api.ts` extends TypeScript contracts for those fields, and `Optimization.tsx` renders the backend payload when available.

## Testing

- Add optimizer unit coverage for sensitivity rows and expected labels.
- Add reporting unit coverage for explanation fields and confidence flags.
- Add API coverage that bundled analysis returns `optimization.explanation` and `optimization.sensitivity`.
- Add frontend TypeScript contract coverage for the new payload shape.

