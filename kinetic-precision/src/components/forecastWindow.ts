import type { AnalysisResult, ForecastPoint } from '../lib/api';

export type ForecastChartPoint = {
  rawTime: string;
  time: string;
  forecast: number;
  overlayScore: number;
  overlayPoint: number | null;
};

export type SiteLoadChartPoint = {
  rawTime: string;
  time: string;
  load: number;
};

export type PeakTimelineItem = {
  key: string;
  time: string;
  label: string;
  level: 'critical' | 'risk' | 'normal';
  peakLoad: number;
  alertCount: number;
};

export function forecastWindowPoints(analysis: AnalysisResult | null): ForecastPoint[] {
  const points = analysis?.forecast.points ?? [];
  return points.length > 0 ? points : analysis?.forecast.preview ?? [];
}

export function forecastLoad(point: ForecastPoint): number {
  return Number(point.calibrated_p95_stress_kw ?? point.md_risk_envelope_kw ?? point.forecast_kw_import);
}

export function downsampleForecastPoints(points: ForecastPoint[], maxPoints: number): ForecastPoint[] {
  if (points.length <= maxPoints) return points;
  const stride = Math.ceil(points.length / maxPoints);
  return points.filter((_, index) => index % stride === 0 || index === points.length - 1);
}

export function forecastWindowLabel(analysis: AnalysisResult): string {
  const months = analysis.assumptions.planning_months;
  return `${months}-month planning window`;
}

export function countPeakRiskAlerts(analysis: AnalysisResult): number {
  return forecastWindowPoints(analysis).filter(point => point.is_peak_risk_overlay).length;
}

export function selectForecastPeakPoint(analysis: AnalysisResult): ForecastPoint | null {
  return forecastWindowPoints(analysis).reduce<ForecastPoint | null>((peak, point) => {
    if (!peak) return point;
    return forecastLoad(point) > forecastLoad(peak) ? point : peak;
  }, null);
}

export function buildForecastChartPoints(analysis: AnalysisResult | null, maxPoints = 288): ForecastChartPoint[] {
  return downsampleForecastPoints(forecastWindowPoints(analysis), maxPoints).map(point => ({
    rawTime: point.interval_end,
    time: new Date(point.interval_end).toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }),
    forecast: forecastLoad(point),
    overlayScore: Number(point.peak_risk_overlay_score ?? 0),
    overlayPoint: point.is_peak_risk_overlay ? forecastLoad(point) : null,
  }));
}

export function buildSiteLoadChartPoints(analysis: AnalysisResult | null, maxPoints = 240): SiteLoadChartPoint[] {
  return downsampleForecastPoints(forecastWindowPoints(analysis), maxPoints).map(point => ({
    rawTime: point.interval_end,
    time: new Date(point.interval_end).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
    load: forecastLoad(point),
  }));
}

function timelineKey(point: ForecastPoint): string {
  return new Date(point.interval_end).toLocaleDateString([], { month: 'short', day: '2-digit' });
}

export function buildPeakTimelineItems(analysis: AnalysisResult): PeakTimelineItem[] {
  const buckets = new Map<string, PeakTimelineItem>();

  for (const point of forecastWindowPoints(analysis)) {
    const key = timelineKey(point);
    const existing = buckets.get(key);
    const hour = new Date(point.interval_end).getHours();
    const isCritical = Boolean(point.is_peak_risk_overlay);
    const isRisk = Number(point.peak_risk_overlay_score ?? point.peak_risk_score ?? 0) > 0.65;
    const level: PeakTimelineItem['level'] = isCritical ? 'critical' : isRisk ? 'risk' : 'normal';
    const currentLoad = forecastLoad(point);
    const label = hour < 10 ? 'Morning ramp' : hour < 17 ? 'Operational peak' : 'Evening MD risk';

    if (!existing) {
      buckets.set(key, {
        key,
        time: key,
        label,
        level,
        peakLoad: currentLoad,
        alertCount: isCritical ? 1 : 0,
      });
      continue;
    }

    if (currentLoad > existing.peakLoad) {
      existing.peakLoad = currentLoad;
      existing.label = label;
    }
    if (isCritical) existing.alertCount += 1;
    if (level === 'critical' || (level === 'risk' && existing.level === 'normal')) {
      existing.level = level;
    }
  }

  return Array.from(buckets.values());
}
