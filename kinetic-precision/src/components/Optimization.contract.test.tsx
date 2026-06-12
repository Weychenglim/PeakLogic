import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Optimization, buildRecommendationEvidence, buildScenarioDecisionEvidence } from './Optimization';
import { DEFAULT_ASSUMPTIONS, type AnalysisResult, type PlanningAssumptions } from '../lib/api';

const updateAssumptions = (_assumptions: PlanningAssumptions) => {};
const applyAssumptions = () => {};

export const optimizationContract = (
  <Optimization
    analysis={null}
    loading={false}
    loadingStep="upload"
    error={null}
    assumptions={DEFAULT_ASSUMPTIONS}
    onAssumptionsChange={updateAssumptions}
    onApplyAssumptions={applyAssumptions}
    canApplyAssumptions={false}
  />
);

const explanationContract: AnalysisResult['optimization']['explanation'] = {
  planning_basis_label: 'Conservative peak-demand planning',
  planning_basis_description: 'Sizes against high-demand periods.',
  what_changed: 'Bill and MD are reduced.',
  why_this_scenario: 'The selected mix gives the strongest savings result.',
  savings_sensitivity: 'Savings range across active sensitivity checks.',
  confidence_flags: [{ level: 'ok', label: 'History depth', message: 'Enough intervals.' }],
};

const explainabilityContract: NonNullable<AnalysisResult['optimization']['explainability']> = {
  headline: 'Battery plus solar is recommended because it lowers MD and annual cost.',
  summary: 'The recommendation is generated from forecast peaks, optimization results, and sensitivity checks.',
  drivers: [
    {
      label: 'Peak windows',
      value: '420 kW',
      detail: 'Highest material forecast risk occurs during the selected planning horizon.',
      tone: 'risk',
    },
    {
      label: 'Battery role',
      value: '100 kW',
      detail: 'Battery discharge reduces grid import during the high-risk windows.',
      tone: 'asset',
    },
  ],
  model_factors: ['Forecast peak-risk markers', 'MD reduction', 'Solar daytime offset'],
  sensitivity_notes: ['Savings stay positive across +/-10% assumption checks.'],
};

export const recommendationEvidenceContract = buildRecommendationEvidence(explainabilityContract);

const sensitivityContract: AnalysisResult['optimization']['sensitivity'][number] = {
  sensitivity_id: 'md_rate_plus_10',
  label: 'MD rate +10%',
  scope: 'active_analysis',
  changed_assumption: 'md_rate_rm_per_kw',
  change_pct: 10,
  savings_rm: 1000,
  monthly_savings_rm: 1000,
  annual_savings_rm: 12000,
  capex_rm: 280000,
  savings_period_months: 1,
  payback_months: 12,
  bill_before_rm: 5000,
  bill_after_rm: 4000,
  md_before: 500,
  md_after: 420,
  battery_kw: 100,
  battery_kwh: 200,
  solar_kwp: 50,
};

function scenarioContract(overrides: Partial<AnalysisResult['optimization']['best_scenario']>): AnalysisResult['optimization']['best_scenario'] {
  return {
    scenario_id: 'scenario_base',
    risk_basis: 'p95',
    battery_kw: 0,
    battery_kwh: 0,
    solar_kwp: 0,
    bill_before_rm: 1000000,
    bill_after_rm: 940000,
    savings_rm: 60000,
    monthly_savings_rm: 60000,
    annual_savings_rm: 720000,
    capex_rm: 0,
    savings_period_months: 1,
    md_before: 973,
    md_after: 870,
    peak_reduction_pct: 10.6,
    payback_months: null,
    has_storage: false,
    has_new_solar: false,
    ...overrides,
  };
}

const selectedScenario = scenarioContract({
  scenario_id: 'scenario_selected',
  battery_kw: 100,
  battery_kwh: 400,
  solar_kwp: 200,
  savings_rm: 73537,
  monthly_savings_rm: 73537,
  annual_savings_rm: 882448,
  capex_rm: 1140000,
  md_after: 832,
  peak_reduction_pct: 14.5,
  payback_months: 15.5,
  has_storage: true,
  has_new_solar: true,
});

const cheaperScenario = scenarioContract({
  scenario_id: 'scenario_cheaper',
  battery_kw: 50,
  battery_kwh: 200,
  solar_kwp: 100,
  annual_savings_rm: 700000,
  capex_rm: 760000,
  md_after: 855,
  payback_months: 13,
  has_storage: true,
  has_new_solar: true,
});

const largerScenario = scenarioContract({
  scenario_id: 'scenario_larger',
  battery_kw: 150,
  battery_kwh: 600,
  solar_kwp: 250,
  annual_savings_rm: 890000,
  capex_rm: 1400000,
  md_after: 828,
  payback_months: 18.9,
  has_storage: true,
  has_new_solar: true,
});

const decisionEvidenceAnalysis: AnalysisResult = {
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
    avg_kw_import: 450,
    weekday_avg_kw_import: 500,
    weekend_avg_kw_import: 350,
  },
  load_history: [],
  normalized_preview: [],
  forecast: {
    metrics: {
      short_horizon: {},
      monthly_planning: {},
    },
    points: [],
    preview: [],
  },
  optimization: {
    best_scenario: selectedScenario,
    scenarios: [cheaperScenario, selectedScenario, largerScenario],
    schedule_preview: [
      {
        interval_end: '2025-11-05T10:30:00',
        baseline_kw_import: 973,
        optimized_kw_import: 832,
        solar_offset_kw: 120,
        battery_discharge_kw: 100,
      },
    ],
    sensitivity: [sensitivityContract],
    explanation: explanationContract,
    explainability: explainabilityContract,
  },
  executive_summary: '',
  exports: {
    normalized_csv: '',
    forecast_csv: '',
    scenario_summary_csv: '',
  },
};

export const scenarioDecisionEvidenceContract = buildScenarioDecisionEvidence(decisionEvidenceAnalysis);

assert.match(scenarioDecisionEvidenceContract.summary, /3 tested/i);
assert.ok(
  scenarioDecisionEvidenceContract.items.some(item => item.label === 'Cheaper options' && /RM 182,448\/yr less/.test(item.detail)),
  'Expected selected plan to explain what it gained over cheaper options'
);
assert.ok(
  scenarioDecisionEvidenceContract.items.some(item => item.label === 'Larger options' && /RM 260,000 more/.test(item.detail) && /RM 7,552\/yr/.test(item.detail)),
  'Expected selected plan to explain diminishing returns against larger options'
);
assert.ok(
  scenarioDecisionEvidenceContract.sensitivity.some(item => /MD tariff/.test(item)),
  'Expected sensitivity to include decision variables that can change the recommendation'
);

const optimizationSource = readFileSync(new URL('./Optimization.tsx', import.meta.url), 'utf8');
const optionsConsideredIndex = optimizationSource.indexOf('Options Considered');
const explainableAiIndex = optimizationSource.indexOf('Explainable AI');
const loadShapeIndex = optimizationSource.indexOf('Load Shape After Optimization');

assert.ok(optionsConsideredIndex >= 0, 'Expected Optimization source to render Options Considered');
assert.ok(explainableAiIndex > optionsConsideredIndex, 'Expected Explainable AI to render under Options Considered');
assert.ok(loadShapeIndex > explainableAiIndex, 'Expected Explainable AI to render before Load Shape After Optimization');

export const backendOptimizationPayloadContract = {
  explanation: explanationContract,
  explainability: explainabilityContract,
  sensitivity: [sensitivityContract],
};
