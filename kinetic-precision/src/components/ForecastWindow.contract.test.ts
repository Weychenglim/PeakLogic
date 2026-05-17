import assert from 'node:assert/strict';
import {
  buildForecastChartPoints,
  buildForecastPeakTimelineItems,
  countPeakRiskAlerts,
  selectForecastPeakPoint,
} from './ForecastRisk';
import {
  buildPeakTimelineItems,
  buildSiteLoadChartPoints,
} from './SiteProfile';
import type { AnalysisResult, ForecastPoint } from '../lib/api';

function point(date: string, load: number, critical = false): ForecastPoint {
  return {
    interval_start: `${date}T00:00:00`,
    interval_end: `${date}T00:30:00`,
    forecast_kw_import: load,
    calibrated_p95_stress_kw: load,
    peak_risk_overlay_score: critical ? 0.96 : 0.2,
    is_peak_risk_overlay: critical,
  };
}

const analysis = {
  assumptions: {
    planning_months: 3,
  },
  forecast: {
    preview: [point('2025-01-01', 100, false), point('2025-01-02', 120, false)],
    points: [
      point('2025-01-01', 100, false),
      point('2025-01-02', 120, false),
      point('2025-02-14', 900, true),
      point('2025-03-11', 750, true),
    ],
  },
} as AnalysisResult;

assert.equal(countPeakRiskAlerts(analysis), 2);
assert.equal(selectForecastPeakPoint(analysis)?.forecast_kw_import, 900);
assert.equal(buildForecastChartPoints(analysis).at(-1)?.forecast, 750);
assert.equal(buildSiteLoadChartPoints(analysis).at(-1)?.load, 750);
assert.equal(buildForecastPeakTimelineItems(analysis).length, 4);
assert.equal(buildPeakTimelineItems(analysis).length, 4);
