import assert from 'node:assert/strict';
import {
  buildPeakMitigationPlan,
  buildForecastChartPoints,
  buildForecastWindowOptions,
  buildRecommendedResponseItems,
  buildTopRiskWindowItems,
  countPeakRiskAlerts,
  formatPeakWindow,
  selectForecastPeakPoint,
} from './ForecastRisk';
import {
  buildPeakTimelineItems,
  buildSiteLoadChartPoints,
  selectForecastWindowPoints,
} from './SiteProfile';
import type { AnalysisResult, ForecastPoint } from '../lib/api';

function point(date: string, load: number, critical = false, score?: number): ForecastPoint {
  return {
    interval_start: `${date}T00:00:00`,
    interval_end: `${date}T00:30:00`,
    forecast_kw_import: load,
    calibrated_p95_stress_kw: load,
    peak_risk_overlay_score: score ?? (critical ? 0.96 : 0.2),
    is_peak_risk_overlay: critical,
  };
}

const analysis = {
  metadata: {
    site_id: 'Test site',
  },
  assumptions: {
    planning_months: 3,
  },
  load_history: [
    { interval_end: '2024-12-01T00:30:00', kw_import: 50 },
    { interval_end: '2024-12-01T01:00:00', kw_import: 60 },
  ],
  forecast: {
    preview: [point('2025-01-01', 100, false), point('2025-01-02', 120, false)],
    points: [
      point('2025-01-01', 100, false),
      point('2025-01-02', 120, false),
      point('2025-02-14', 900, true),
      point('2025-02-20', 950, true, 0.91),
      point('2025-03-11', 750, true),
    ],
  },
  optimization: {
    best_scenario: {
      scenario_id: 'balanced_storage',
      risk_basis: 'p95',
      battery_kw: 100,
      battery_kwh: 200,
      solar_kwp: 50,
      bill_before_rm: 150000,
      bill_after_rm: 112500,
      savings_rm: 37500,
      monthly_savings_rm: 12500,
      annual_savings_rm: 150000,
      capex_rm: 600000,
      savings_period_months: 3,
      md_before: 900,
      md_after: 760,
      peak_reduction_pct: 15.6,
      payback_months: 48,
      has_storage: true,
      has_new_solar: true,
    },
    scenarios: [],
    schedule_preview: [],
    sensitivity: [],
    explanation: {
      planning_basis_label: 'Conservative peak demand',
      planning_basis_description: 'Uses stress demand for MD protection.',
      what_changed: '',
      why_this_scenario: '',
      savings_sensitivity: '',
      confidence_flags: [],
    },
  },
} as AnalysisResult;

assert.equal(countPeakRiskAlerts(analysis), 3);
assert.equal(selectForecastPeakPoint(analysis)?.forecast_kw_import, 950);
assert.equal(buildForecastChartPoints(analysis).at(-1)?.forecast, 750);
assert.equal(buildForecastChartPoints({
  ...analysis,
  forecast: {
    ...analysis.forecast,
    points: [
      {
        ...point('2025-04-01', 100, false),
        forecast_gross_load_kw: 180,
        estimated_existing_solar_kw: 80,
        forecast_basis: 'gross_load_with_existing_solar',
      },
    ],
  },
}, 288, 'gross_load').at(0)?.forecast, 180);
assert.equal(buildSiteLoadChartPoints(analysis).at(-1)?.load, 60);
assert.equal(buildPeakTimelineItems(analysis).length, 5);
const topRiskWindows = buildTopRiskWindowItems(analysis);
assert.equal(topRiskWindows.length, 3);
assert.equal(topRiskWindows.at(0)?.peakLoad, 950);
assert.equal(topRiskWindows.at(0)?.level, 'critical');
assert.equal(topRiskWindows.at(0)?.action, 'Battery discharge');
const responseItems = buildRecommendedResponseItems(analysis, topRiskWindows.at(0) ?? null);
assert.equal(responseItems.length, 3);
assert.match(responseItems.at(0)?.title ?? '', /battery/i);
assert.match(responseItems.at(1)?.detail ?? '', /outside/i);
assert.match(responseItems.at(2)?.detail ?? '', /760 kW/);
const mitigationPlan = buildPeakMitigationPlan(analysis);
assert.equal(mitigationPlan.mdReductionKw, 140);
assert.equal(mitigationPlan.targetMdKw, 760);
assert.match(mitigationPlan.planBasis, /Conservative/);
assert.match(mitigationPlan.storageText, /100 kW/);
const calmMitigationPlan = buildPeakMitigationPlan(analysis, 676);
assert.equal(calmMitigationPlan.windowReductionNeededKw, 0);
assert.equal(calmMitigationPlan.requiresImmediateReduction, false);
assert.match(calmMitigationPlan.headline, /No immediate reduction/i);
assert.match(calmMitigationPlan.guidance, /below the MD target/i);
const calmResponseItems = buildRecommendedResponseItems(analysis, {
  ...topRiskWindows[0],
  peakLoad: 676,
  timeWindow: '12:00 AM - 02:00 AM',
});
assert.match(calmResponseItems.at(0)?.title ?? '', /stand by/i);
assert.match(formatPeakWindow('2025-02-14T15:30:00'), /Feb 14/);
assert.match(formatPeakWindow('2025-02-14T15:30:00'), /03:30 PM/);

const monthForecast = {
  ...analysis,
  forecast: {
    ...analysis.forecast,
    points: Array.from({ length: 30 * 48 }, (_, index) =>
      point(`2025-01-${String(Math.floor(index / 48) + 1).padStart(2, '0')}`, index),
    ),
  },
} as AnalysisResult;

const threeMonthOptions = buildForecastWindowOptions(monthForecast);
assert.equal(threeMonthOptions.at(-1)?.id, '3m');
assert.equal(threeMonthOptions.at(-1)?.label, '3 months');
assert.equal(threeMonthOptions.at(-1)?.intervals, 90 * 48);
const twoMonthOptions = buildForecastWindowOptions({
  ...monthForecast,
  assumptions: {
    planning_months: 2,
  },
} as AnalysisResult);
assert.equal(twoMonthOptions.at(-1)?.id, '2m');
assert.equal(twoMonthOptions.at(-1)?.label, '2 months');
assert.equal(twoMonthOptions.at(-1)?.intervals, 60 * 48);

const twelveHourPoints = selectForecastWindowPoints(monthForecast, 24);
assert.equal(twelveHourPoints.length, 24);
assert.equal(twelveHourPoints.at(0)?.forecast_kw_import, 0);
assert.equal(twelveHourPoints.at(-1)?.forecast_kw_import, 23);
