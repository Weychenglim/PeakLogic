export interface BundledSite {
  site_id: string;
  source_file: string;
  has_solar: boolean;
  existing_pv_kwp: number | null;
  row_count: number;
  gap_count: number;
  peak_kw_import: number;
}

export interface SiteMetadata {
  site_id: string;
  has_solar: boolean;
  existing_pv_kwp: number | null;
  source_file: string;
}

export interface ValidationSummary {
  site_id: string;
  row_count: number;
  gap_count: number;
  duplicate_count: number;
  missing_value_count: number;
  expected_interval_minutes: number;
}

export interface SiteProfileSummary {
  rows: number;
  start: string;
  end: string;
  peak_kw_import: number;
  avg_kw_import: number;
  weekday_avg_kw_import: number;
  weekend_avg_kw_import: number;
}

export interface LoadHistoryPoint {
  interval_start?: string;
  interval_end: string;
  kw_import: number;
  kw_export?: number;
}

export interface ForecastPoint {
  interval_start: string;
  interval_end: string;
  forecast_kw_import: number;
  forecast_gross_load_kw?: number;
  estimated_existing_solar_kw?: number;
  forecast_basis?: string;
  p50_forecast_kw?: number;
  calibrated_p90_md_risk_kw?: number;
  calibrated_p95_stress_kw?: number;
  md_risk_envelope_kw?: number;
  peak_risk_score?: number;
  peak_risk_overlay_score?: number;
  is_predicted_peak?: boolean;
  is_peak_risk_overlay?: boolean;
  late_night_peak_floor_applied?: boolean;
  late_night_peak_shape_score?: number;
}

export interface OptimizationScenario {
  scenario_id: string;
  risk_basis: string;
  battery_kw: number;
  battery_kwh: number;
  solar_kwp: number;
  bill_before_rm: number;
  bill_after_rm: number;
  savings_rm: number;
  monthly_savings_rm: number;
  annual_savings_rm: number;
  capex_rm: number;
  savings_period_months: number;
  md_before: number;
  md_after: number;
  peak_reduction_pct: number;
  payback_months: number | null;
  has_storage: boolean;
  has_new_solar: boolean;
}

export interface OptimizationSensitivity {
  sensitivity_id: string;
  label: string;
  scope: string;
  changed_assumption: string;
  change_pct: number;
  savings_rm: number;
  monthly_savings_rm: number;
  annual_savings_rm: number;
  capex_rm: number;
  savings_period_months: number;
  payback_months: number | null;
  bill_before_rm: number;
  bill_after_rm: number;
  md_before: number;
  md_after: number;
  battery_kw: number;
  battery_kwh: number;
  solar_kwp: number;
}

export interface OptimizationConfidenceFlag {
  level: string;
  label: string;
  message: string;
}

export interface OptimizationExplanation {
  planning_basis_label: string;
  planning_basis_description: string;
  what_changed: string;
  why_this_scenario: string;
  savings_sensitivity: string;
  confidence_flags: OptimizationConfidenceFlag[];
}

export interface ExplainabilityDriver {
  label: string;
  value: string;
  detail: string;
  tone: 'risk' | 'asset' | 'finance' | 'confidence' | string;
}

export interface DecisionExplainability {
  headline: string;
  summary: string;
  drivers: ExplainabilityDriver[];
  model_factors: string[];
  sensitivity_notes: string[];
}

export interface SchedulePoint {
  interval_end: string;
  baseline_kw_import: number;
  optimized_kw_import: number;
  solar_offset_kw: number;
  battery_discharge_kw: number;
}

export interface AnalysisResult {
  metadata: SiteMetadata;
  assumptions: PlanningAssumptions;
  validation: ValidationSummary;
  profile: SiteProfileSummary;
  load_history: LoadHistoryPoint[];
  normalized_preview: Record<string, unknown>[];
  forecast: {
    metrics: {
      short_horizon: Record<string, number | string>;
      monthly_planning: Record<string, number | string>;
    };
    points: ForecastPoint[];
    preview: ForecastPoint[];
  };
  optimization: {
    best_scenario: OptimizationScenario;
    scenarios: OptimizationScenario[];
    schedule_preview: SchedulePoint[];
    sensitivity: OptimizationSensitivity[];
    explanation: OptimizationExplanation;
    explainability?: DecisionExplainability;
  };
  executive_summary: string;
  exports: {
    normalized_csv: string;
    forecast_csv: string;
    scenario_summary_csv: string;
  };
}

export type AssistantContext = Record<string, unknown>;

export interface AssistantResponse {
  answer: string;
  sources: string[];
  mode: 'grounded' | 'openai' | string;
  suggested_questions: string[];
}

export interface PlanningAssumptions {
  planning_months: number;
  growth_rate_pct: number;
  ev_load_kw: number;
  existing_pv_kwp: number | null;
  md_rate_rm_per_kw: number;
  peak_energy_rate_rm_per_kwh: number;
  offpeak_energy_rate_rm_per_kwh: number;
  battery_capex_rm_per_kw: number;
  battery_capex_rm_per_kwh: number;
  solar_capex_rm_per_kwp: number;
}

export const DEFAULT_ASSUMPTIONS: PlanningAssumptions = {
  planning_months: 1,
  growth_rate_pct: 0,
  ev_load_kw: 0,
  existing_pv_kwp: null,
  md_rate_rm_per_kw: 97.06,
  peak_energy_rate_rm_per_kwh: 0.455,
  offpeak_energy_rate_rm_per_kwh: 0.365,
  battery_capex_rm_per_kw: 1400,
  battery_capex_rm_per_kwh: 900,
  solar_capex_rm_per_kwp: 3200,
};

const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = payload?.detail ?? `Request failed with ${response.status}`;
    throw new Error(Array.isArray(message) ? message.map(item => item.msg).join(', ') : String(message));
  }
  return response.json() as Promise<T>;
}

export async function fetchBundledSites(): Promise<BundledSite[]> {
  const response = await fetch(`${API_BASE_URL}/api/bundled-sites`);
  const payload = await parseJson<{ sites: BundledSite[] }>(response);
  return payload.sites;
}

export async function analyzeBundled(sourceFile: string, assumptions = DEFAULT_ASSUMPTIONS): Promise<AnalysisResult> {
  const payload: Record<string, unknown> = {
    source_file: sourceFile,
    months: assumptions.planning_months,
    growth_rate_pct: assumptions.growth_rate_pct,
    ev_load_kw: assumptions.ev_load_kw,
    md_rate_rm_per_kw: assumptions.md_rate_rm_per_kw,
    peak_energy_rate_rm_per_kwh: assumptions.peak_energy_rate_rm_per_kwh,
    offpeak_energy_rate_rm_per_kwh: assumptions.offpeak_energy_rate_rm_per_kwh,
    battery_capex_rm_per_kw: assumptions.battery_capex_rm_per_kw,
    battery_capex_rm_per_kwh: assumptions.battery_capex_rm_per_kwh,
    solar_capex_rm_per_kwp: assumptions.solar_capex_rm_per_kwp,
  };
  if (assumptions.existing_pv_kwp !== null) {
    payload.existing_pv_kwp = assumptions.existing_pv_kwp;
  }
  const response = await fetch(`${API_BASE_URL}/api/analyze/bundled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseJson<AnalysisResult>(response);
}

export async function uploadAnalysis(file: File, assumptions = DEFAULT_ASSUMPTIONS): Promise<AnalysisResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('months', String(assumptions.planning_months));
  form.append('active_power_unit', 'auto');
  form.append('growth_rate_pct', String(assumptions.growth_rate_pct));
  form.append('ev_load_kw', String(assumptions.ev_load_kw));
  if (assumptions.existing_pv_kwp !== null) {
    form.append('existing_pv_kwp', String(assumptions.existing_pv_kwp));
  }
  form.append('md_rate_rm_per_kw', String(assumptions.md_rate_rm_per_kw));
  form.append('peak_energy_rate_rm_per_kwh', String(assumptions.peak_energy_rate_rm_per_kwh));
  form.append('offpeak_energy_rate_rm_per_kwh', String(assumptions.offpeak_energy_rate_rm_per_kwh));
  form.append('battery_capex_rm_per_kw', String(assumptions.battery_capex_rm_per_kw));
  form.append('battery_capex_rm_per_kwh', String(assumptions.battery_capex_rm_per_kwh));
  form.append('solar_capex_rm_per_kwp', String(assumptions.solar_capex_rm_per_kwp));

  const response = await fetch(`${API_BASE_URL}/api/analyze/upload`, {
    method: 'POST',
    body: form,
  });
  return parseJson<AnalysisResult>(response);
}

export async function askAssistant(question: string, context: AssistantContext): Promise<AssistantResponse> {
  const response = await fetch(`${API_BASE_URL}/api/assistant`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, context }),
  });
  return parseJson<AssistantResponse>(response);
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
