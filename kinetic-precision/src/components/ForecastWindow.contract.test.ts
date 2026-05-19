import assert from 'node:assert/strict';
import {
  buildForecastChartPoints,
  buildTopRiskWindowItems,
  countPeakRiskAlerts,
  selectForecastPeakPoint,
} from './ForecastRisk';
import {
  buildPeakTimelineItems,
  buildSiteLoadChartPoints,
  selectForecastWindowPoints,
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
      point('2025-03-11', 750, true),
    ],
  },
} as AnalysisResult;

assert.equal(countPeakRiskAlerts(analysis), 2);
assert.equal(selectForecastPeakPoint(analysis)?.forecast_kw_import, 900);
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
assert.equal(buildPeakTimelineItems(analysis).length, 4);
const topRiskWindows = buildTopRiskWindowItems(analysis);
assert.equal(topRiskWindows.length, 2);
assert.equal(topRiskWindows.at(0)?.peakLoad, 900);
assert.equal(topRiskWindows.at(0)?.level, 'critical');
assert.equal(topRiskWindows.at(0)?.action, 'Battery discharge');

const monthForecast = {
  ...analysis,
  forecast: {
    ...analysis.forecast,
    points: Array.from({ length: 30 * 48 }, (_, index) =>
      point(`2025-01-${String(Math.floor(index / 48) + 1).padStart(2, '0')}`, index),
    ),
  },
} as AnalysisResult;

const twelveHourPoints = selectForecastWindowPoints(monthForecast, 24);
assert.equal(twelveHourPoints.length, 24);
assert.equal(twelveHourPoints.at(0)?.forecast_kw_import, 0);
assert.equal(twelveHourPoints.at(-1)?.forecast_kw_import, 23);
