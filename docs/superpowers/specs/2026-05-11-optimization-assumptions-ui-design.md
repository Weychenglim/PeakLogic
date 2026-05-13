# Optimization Assumptions UI Design

## Goal

Make the Optimization tab more judge-facing and let users edit the assumptions that drive savings, payback, and recommended system sizing without leaving the tab.

## Scope

- Keep the dashboard focused on the currently selected site or uploaded workbook.
- Avoid site-by-site comparison and model-comparison UI.
- Replace technical p90/p95 wording in the Optimization tab with business-facing peak-demand planning language.
- Replace the read-only "Locked Assumptions" panel with editable inputs for:
  - planning months
  - MD rate
  - peak energy rate
  - off-peak energy rate
  - battery RM/kW
  - battery RM/kWh
  - solar RM/kWp
  - growth rate
  - EV load
- Add an Apply Assumptions action that reruns analysis for the active bundled workbook or active upload using the edited values.
- Keep the existing Data Upload workflow and its assumptions panel.

## UI Design

The Optimization tab becomes the decision screen. The top technical note is rewritten as "Conservative peak-demand planning basis" and explains that TREX sizes the scenario against high-demand periods, not against a model-family comparison.

The result area includes three short judge-facing explanation blocks:

- What changed: baseline bill, optimized bill, peak reduction, and MD change.
- Why this scenario: battery, solar, savings, and payback rationale.
- Savings sensitivity: tariff, CAPEX, growth, EV load, and planning-window assumptions can be edited and reapplied.

The assumptions panel is editable, compact, and visually tied to the optimization output. Apply reruns the existing active analysis and leaves the user on the Optimization tab.

## Data Flow

`App.tsx` remains the owner of selected source, latest analysis, assumptions, loading, and errors. It passes assumptions, an assumption setter, and an apply callback into `Optimization.tsx`.

For bundled workbooks, apply calls the existing bundled analysis endpoint with the current `source_file` and edited assumptions. For uploaded workbooks, apply reuses the latest uploaded `File` object when available. If the upload file is no longer available, the Optimization tab disables Apply and tells the user to upload again.

## Testing

Use TypeScript contract coverage because the frontend currently has no runtime test runner. The contract test ensures the Optimization component accepts editable assumption props and an apply callback. Build verification uses `npm run build`.

