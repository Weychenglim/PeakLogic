import {
  buildPeakTimelineItems,
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
