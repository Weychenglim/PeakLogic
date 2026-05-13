import {
  buildPeakTimelineItems,
  buildSolarImpactComparison,
} from './SiteProfile';
import type { AnalysisResult } from '../lib/api';

export const peakTimelineContract = buildPeakTimelineItems({
  forecast: {
    preview: [
      {
        interval_start: '2025-01-01T06:00:00',
        interval_end: '2025-01-01T06:30:00',
        forecast_kw_import: 100,
        is_peak_risk_overlay: false,
      },
      {
        interval_start: '2025-01-01T14:00:00',
        interval_end: '2025-01-01T14:30:00',
        forecast_kw_import: 250,
        is_peak_risk_overlay: true,
      },
    ],
  },
} as AnalysisResult);

export const solarImpactContract = buildSolarImpactComparison({
  assumptions: {
    planning_months: 1,
    growth_rate_pct: 0,
    ev_load_kw: 0,
    md_rate_rm_per_kw: 97.06,
    peak_energy_rate_rm_per_kwh: 0.455,
    offpeak_energy_rate_rm_per_kwh: 0.365,
    battery_capex_rm_per_kw: 1400,
    battery_capex_rm_per_kwh: 900,
    solar_capex_rm_per_kwp: 3200,
  },
  optimization: {
    schedule_preview: [
      {
        interval_end: '2025-01-01T12:30:00',
        baseline_kw_import: 100,
        optimized_kw_import: 75,
        solar_offset_kw: 25,
        battery_discharge_kw: 0,
      },
    ],
  },
} as AnalysisResult);
