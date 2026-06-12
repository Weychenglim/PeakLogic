import assert from 'node:assert/strict';
import { ALLOWED_ASSISTANT_ACTION_TABS, ASSISTANT_SUGGESTED_QUESTIONS, buildAssistantContext, formatAssistantContent, modeLabel } from './DashboardAssistant';
import { DEFAULT_ASSUMPTIONS, type AnalysisResult } from '../lib/api';

const analysis: AnalysisResult = {
  metadata: {
    site_id: 'Test Site',
    has_solar: true,
    existing_pv_kwp: 945,
    source_file: 'test.xlsx',
  },
  assumptions: DEFAULT_ASSUMPTIONS,
  validation: {
    site_id: 'Test Site',
    row_count: 100,
    gap_count: 0,
    duplicate_count: 0,
    missing_value_count: 0,
    expected_interval_minutes: 30,
  },
  profile: {
    rows: 100,
    start: '2025-01-01T00:00:00',
    end: '2025-01-31T23:30:00',
    peak_kw_import: 973,
    avg_kw_import: 520,
    weekday_avg_kw_import: 540,
    weekend_avg_kw_import: 480,
  },
  load_history: [],
  normalized_preview: [],
  forecast: {
    metrics: {
      short_horizon: {},
      monthly_planning: {},
    },
    points: [
      {
        interval_start: '2025-11-05T10:00:00',
        interval_end: '2025-11-05T10:30:00',
        forecast_kw_import: 973,
        calibrated_p95_stress_kw: 973,
        peak_risk_overlay_score: 0.96,
        is_peak_risk_overlay: true,
      },
      {
        interval_start: '2025-11-06T14:00:00',
        interval_end: '2025-11-06T14:30:00',
        forecast_kw_import: 940,
        calibrated_p95_stress_kw: 940,
        peak_risk_overlay_score: 0.82,
        is_peak_risk_overlay: false,
      },
    ],
    preview: [],
  },
  optimization: {
    best_scenario: {
      scenario_id: 'selected',
      risk_basis: 'p95',
      battery_kw: 100,
      battery_kwh: 400,
      solar_kwp: 200,
      bill_before_rm: 1000000,
      bill_after_rm: 926463,
      savings_rm: 73537,
      monthly_savings_rm: 73537,
      annual_savings_rm: 882448,
      capex_rm: 1140000,
      savings_period_months: 1,
      md_before: 973,
      md_after: 832,
      peak_reduction_pct: 14.5,
      payback_months: 15.5,
      has_storage: true,
      has_new_solar: true,
    },
    scenarios: [
      {
        scenario_id: 'cheaper',
        risk_basis: 'p95',
        battery_kw: 50,
        battery_kwh: 200,
        solar_kwp: 100,
        bill_before_rm: 1000000,
        bill_after_rm: 941667,
        savings_rm: 58333,
        monthly_savings_rm: 58333,
        annual_savings_rm: 700000,
        capex_rm: 760000,
        savings_period_months: 1,
        md_before: 973,
        md_after: 855,
        peak_reduction_pct: 12.1,
        payback_months: 13,
        has_storage: true,
        has_new_solar: true,
      },
    ],
    schedule_preview: [
      {
        interval_end: '2025-11-05T10:30:00',
        baseline_kw_import: 973,
        optimized_kw_import: 832,
        solar_offset_kw: 120,
        battery_discharge_kw: 100,
      },
    ],
    sensitivity: [],
    explanation: {
      planning_basis_label: 'Conservative peak demand',
      planning_basis_description: '',
      what_changed: '',
      why_this_scenario: '',
      savings_sensitivity: '',
      confidence_flags: [],
    },
  },
  executive_summary: '',
  exports: {
    normalized_csv: '',
    forecast_csv: '',
    scenario_summary_csv: '',
  },
};

const context = buildAssistantContext(analysis);

assert.equal(context.site_id, 'Test Site');
assert.equal(context.source_file, 'test.xlsx');
assert.match(JSON.stringify(context.optimization), /Cheaper options/);
assert.match(JSON.stringify(context.forecast), /top_risk_windows/);
assert.match(JSON.stringify(context.forecast), /973/);
assert.ok(ASSISTANT_SUGGESTED_QUESTIONS.some(question => /cheaper option/i.test(question)));
assert.ok(
  ASSISTANT_SUGGESTED_QUESTIONS.every(question => !/judge|presentation|script/i.test(question)),
  'Assistant suggestions must not include judge-facing or presentation-script prompts'
);

const formatted = formatAssistantContent(
  '## Site Summary: Load Profile\n\n**Current Situation:**\n- **Existing solar:** 944.88 kWp already installed\n- **Peak demand:** 960 kW\n\n**Data Quality:** 14 timestamp gaps detected.'
);

assert.deepEqual(formatted, [
  'Site Summary: Load Profile',
  'Current Situation:',
  'Existing solar: 944.88 kWp already installed',
  'Peak demand: 960 kW',
  'Data Quality: 14 timestamp gaps detected.',
]);
assert.equal(modeLabel('provider'), 'API mode');
assert.equal(modeLabel('openai'), 'API mode');
assert.equal(modeLabel('grounded'), 'Dashboard data mode');
assert.deepEqual(ALLOWED_ASSISTANT_ACTION_TABS, ['profile', 'forecast', 'optimization', 'summary', 'settings']);
