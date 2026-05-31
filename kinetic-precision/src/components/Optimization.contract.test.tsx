import { Optimization } from './Optimization';
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

export const backendOptimizationPayloadContract = {
  explanation: explanationContract,
  sensitivity: [sensitivityContract],
};
