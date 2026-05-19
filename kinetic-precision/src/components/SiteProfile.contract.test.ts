import {
  buildLoadPatternSummary,
  buildObservedPeakEvents,
  buildPeakTimelineItems,
  buildSiteFactItems,
  buildSiteLoadChartPoints,
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

export const siteLoadContract = buildSiteLoadChartPoints({
  load_history: [
    {
      interval_end: '2025-01-01T12:30:00',
      kw_import: 100,
    },
  ],
} as AnalysisResult);

const historicalAnalysis = {
  profile: {
    peak_kw_import: 300,
    avg_kw_import: 100,
    weekday_avg_kw_import: 120,
    weekend_avg_kw_import: 70,
  },
  load_history: [
    { interval_end: '2025-01-01T01:00:00', kw_import: 90 },
    { interval_end: '2025-01-01T12:00:00', kw_import: 200 },
    { interval_end: '2025-01-02T14:00:00', kw_import: 300 },
    { interval_end: '2025-01-03T22:00:00', kw_import: 150 },
  ],
} as AnalysisResult;

export const observedPeakEventsContract = buildObservedPeakEvents(historicalAnalysis);
export const loadPatternSummaryContract = buildLoadPatternSummary(historicalAnalysis);
export const siteFactItemsContract = buildSiteFactItems({
  profile: {
    rows: 2787,
  },
  metadata: {
    has_solar: true,
    existing_pv_kwp: 944.88,
  },
  validation: {
    gap_count: 14,
  },
} as AnalysisResult);

if (observedPeakEventsContract.length !== 3) throw new Error('Expected top three observed peaks');
if (observedPeakEventsContract[0].load !== 300) throw new Error('Expected observed peaks sorted by load');
if (loadPatternSummaryContract.daytimeAvg !== 250) throw new Error('Expected daytime average from daylight history');
if (loadPatternSummaryContract.nightAvg !== 120) throw new Error('Expected night average from night history');
if (loadPatternSummaryContract.peakToAverageRatio !== 3) throw new Error('Expected peak-to-average ratio');
if (siteFactItemsContract.length !== 3) throw new Error('Expected three compact site facts');
if (siteFactItemsContract[0].value !== '2,787') throw new Error('Expected interval fact');
if (siteFactItemsContract[1].value !== '945 kWp') throw new Error('Expected solar capacity fact');
if (siteFactItemsContract[2].value !== '14 gaps') throw new Error('Expected data quality fact');
