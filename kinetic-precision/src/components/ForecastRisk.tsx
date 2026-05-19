import { useEffect, useState } from 'react';
import { AlertCircle, BatteryCharging, Clock, Gauge, ShieldCheck, SunMedium } from 'lucide-react';
import { Area, CartesianGrid, ComposedChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult } from '../lib/api';
import {
  buildForecastChartPoints,
  buildTopRiskWindowItems,
  countPeakRiskAlerts,
  forecastGrossLoad,
  forecastLoad,
  selectForecastWindowPoints,
  selectForecastPeakPoint,
  type ForecastChartBasis,
} from './forecastWindow';

export {
  buildForecastChartPoints,
  buildTopRiskWindowItems,
  countPeakRiskAlerts,
  selectForecastWindowPoints,
  selectForecastPeakPoint,
} from './forecastWindow';

interface ForecastRiskProps {
  analysis: AnalysisResult | null;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
}

export type RecommendedResponseItem = {
  title: string;
  detail: string;
  meta: string;
  kind: 'battery' | 'shift' | 'threshold';
};

export type PeakMitigationPlan = {
  baselineMdKw: number;
  targetMdKw: number;
  mdReductionKw: number;
  windowReductionNeededKw: number;
  requiresImmediateReduction: boolean;
  headline: string;
  guidance: string;
  planBasis: string;
  storageText: string;
  solarText: string;
};

export type ForecastWindowOption = {
  id: string;
  label: string;
  intervals: number;
};

export function buildForecastWindowOptions(analysis: AnalysisResult): ForecastWindowOption[] {
  const planningMonths = Math.min(3, Math.max(1, Math.round(Number(analysis.assumptions?.planning_months ?? 1))));
  const baseOptions: ForecastWindowOption[] = [
    { id: '12h', label: '12h', intervals: 24 },
    { id: '24h', label: '24h', intervals: 48 },
    { id: '48h', label: '48h', intervals: 96 },
    { id: '7d', label: '7 days', intervals: 7 * 48 },
  ];
  const monthOptions = Array.from({ length: planningMonths }, (_, index) => {
    const months = index + 1;
    return {
      id: `${months}m`,
      label: `${months} month${months === 1 ? '' : 's'}`,
      intervals: months * 30 * 48,
    };
  });
  return [...baseOptions, ...monthOptions];
}

function compactForecastForBasis(
  points: AnalysisResult['forecast']['points'],
  stride: number,
  chartBasis: ForecastChartBasis,
) {
  return points.filter((_, index) => index % stride === 0).map(point => {
    const gridImport = forecastLoad(point);
    const grossLoad = forecastGrossLoad(point);
    const forecast = chartBasis === 'gross_load' ? grossLoad : gridImport;
    return {
      rawTime: point.interval_end,
      time: new Date(point.interval_end).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
      forecast,
      overlayScore: Number(point.peak_risk_overlay_score ?? 0),
      overlayPoint: point.is_peak_risk_overlay ? forecast : null,
    };
  });
}

export function formatPeakWindow(startIso: string, hours = 2) {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + hours * 60 * 60 * 1000);
  const formatDate = (date: Date) => date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const formatTime = (date: Date) => date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  const startDate = formatDate(start);
  const endDate = formatDate(end);

  if (startDate === endDate) {
    return `${startDate}, ${formatTime(start)} - ${formatTime(end)}`;
  }
  return `${startDate}, ${formatTime(start)} - ${endDate}, ${formatTime(end)}`;
}

function formatKw(value: number) {
  return `${Math.max(0, value).toFixed(0)} kW`;
}

function riskBasisFallback(riskBasis: string) {
  if (riskBasis === 'p95') return 'Conservative peak demand';
  if (riskBasis === 'p90') return 'Balanced peak demand';
  if (riskBasis === 'expected') return 'Expected demand';
  return riskBasis || 'Selected planning basis';
}

export function buildPeakMitigationPlan(analysis: AnalysisResult, windowPeakKw?: number): PeakMitigationPlan {
  const best = analysis.optimization.best_scenario;
  const peakKw = windowPeakKw ?? best.md_before;
  const mdReductionKw = Math.max(0, best.md_before - best.md_after);
  const windowReductionNeededKw = Math.max(0, peakKw - best.md_after);
  const requiresImmediateReduction = windowReductionNeededKw > 0.5;
  const planBasis = analysis.optimization.explanation?.planning_basis_label || riskBasisFallback(best.risk_basis);
  const storageText = best.battery_kw > 0
    ? `${formatKw(best.battery_kw)} battery discharge available for peak shaving`
    : 'No battery dispatch selected for this scenario';
  const solarText = best.has_new_solar && best.solar_kwp > 0
    ? `${best.solar_kwp.toFixed(0)} kWp new solar supports daytime import reduction`
    : analysis.metadata.has_solar
      ? 'Existing solar is already reflected in the grid-import forecast'
      : 'No solar contribution assumed for this response';

  return {
    baselineMdKw: best.md_before,
    targetMdKw: best.md_after,
    mdReductionKw,
    windowReductionNeededKw,
    requiresImmediateReduction,
    headline: requiresImmediateReduction ? formatKw(windowReductionNeededKw) : 'No immediate reduction needed',
    guidance: requiresImmediateReduction
      ? `Target grid import below ${formatKw(best.md_after)} during the highlighted peak window.`
      : 'This selected window is below the MD target. Keep monitoring and avoid adding discretionary load.',
    planBasis,
    storageText,
    solarText,
  };
}

export function buildRecommendedResponseItems(
  analysis: AnalysisResult,
  activeRiskWindow: ReturnType<typeof buildTopRiskWindowItems>[number] | null,
): RecommendedResponseItem[] {
  const best = analysis.optimization.best_scenario;
  const mitigation = buildPeakMitigationPlan(analysis, activeRiskWindow?.peakLoad);
  const timeWindow = activeRiskWindow?.timeWindow ?? 'the highlighted risk window';
  const batteryMeta = best.battery_kw > 0 ? `Up to ${formatKw(best.battery_kw)}` : 'No battery in selected scenario';
  const shiftKw = Math.max(0, mitigation.windowReductionNeededKw - Math.max(0, best.battery_kw));
  const calmWindow = !mitigation.requiresImmediateReduction;

  return [
    {
      title: calmWindow
        ? 'Stand by with battery'
        : best.battery_kw > 0 ? 'Discharge battery during peak window' : 'Prepare manual peak response',
      detail: calmWindow
        ? `This window is below the MD target; hold storage for a later spike and avoid adding load through ${timeWindow}.`
        : best.battery_kw > 0
          ? `Use storage through ${timeWindow} to shave the grid-import spike before it becomes the monthly MD.`
          : `No storage is selected, so use manual load control through ${timeWindow}.`,
      meta: batteryMeta,
      kind: 'battery',
    },
    {
      title: calmWindow ? 'Avoid starting flexible load' : 'Move flexible load outside the window',
      detail: calmWindow
        ? `Keep flexible activity outside ${timeWindow} so this window stays comfortably below target.`
        : shiftKw > 0
          ? `Shift about ${formatKw(shiftKw)} of discretionary load outside ${timeWindow} after battery support.`
          : `Keep discretionary activity outside ${timeWindow} so battery dispatch is not cancelled out by new load.`,
      meta: activeRiskWindow?.label ?? 'Peak operating window',
      kind: 'shift',
    },
    {
      title: 'Watch the MD target live',
      detail: `Keep grid import below ${formatKw(best.md_after)}; escalate if the live meter trends above this target.`,
      meta: `${mitigation.planBasis} target`,
      kind: 'threshold',
    },
  ];
}

export function ForecastRisk({ analysis, loading, loadingStep, error }: ForecastRiskProps) {
  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Forecast unavailable" message={error} />;
    return <EmptyAnalysis title="No forecast yet" description="Run an analysis to inspect predicted demand, peak-risk windows, and recommended mitigation actions." />;
  }

  const planningMonths = Math.min(3, Math.max(1, Math.round(Number(analysis.assumptions?.planning_months ?? 1))));
  const planningDays = planningMonths * 30;
  const fullPlanningWindowId = `${planningMonths}m`;
  const windowOptions = buildForecastWindowOptions(analysis);
  const [windowSize, setWindowSize] = useState(fullPlanningWindowId);
  const [chartBasis, setChartBasis] = useState<ForecastChartBasis>('grid_import');
  useEffect(() => {
    setWindowSize(fullPlanningWindowId);
  }, [fullPlanningWindowId]);
  const selectedWindow = windowOptions.find(option => option.id === windowSize) ?? windowOptions.at(-1) ?? windowOptions[1];
  const windowPoints = selectForecastWindowPoints(analysis, selectedWindow.intervals);
  const stride = Math.max(1, Math.floor(windowPoints.length / 96));
  const data = compactForecastForBasis(windowPoints, stride, chartBasis);
  const overlayEvents = windowPoints.filter(point => point.is_peak_risk_overlay).length;
  const peakPoint = [...windowPoints].sort((a, b) => {
    const aLoad = Number(a.calibrated_p95_stress_kw ?? a.md_risk_envelope_kw ?? a.forecast_kw_import);
    const bLoad = Number(b.calibrated_p95_stress_kw ?? b.md_risk_envelope_kw ?? b.forecast_kw_import);
    return bLoad - aLoad;
  })[0];
  const peakLoad = peakPoint ? Number(peakPoint.calibrated_p95_stress_kw ?? peakPoint.md_risk_envelope_kw ?? peakPoint.forecast_kw_import) : 0;
  const peakTime = peakPoint?.interval_end ?? data[0]?.rawTime ?? new Date().toISOString();
  const chartPeak = data.reduce((peak, point) => (point.forecast > peak.forecast ? point : peak), data[0] ?? { time: '', forecast: 0 });
  const riskWindows = buildTopRiskWindowItems(analysis);
  const currentWindowRiskWindows = buildTopRiskWindowItems({
    ...analysis,
    forecast: {
      ...analysis.forecast,
      points: windowPoints,
    },
  });
  const activeRiskWindow = currentWindowRiskWindows[0] ?? null;
  const responseItems = buildRecommendedResponseItems(analysis, activeRiskWindow);
  const mitigation = buildPeakMitigationPlan(analysis, peakLoad);
  const peakBadgeLabel = overlayEvents > 0 ? 'High risk' : 'Forecast peak';
  const peakBadgeClass = overlayEvents > 0 ? 'bg-error text-white' : 'bg-primary-fixed text-primary';

  return (
    <div className="animate-in fade-in space-y-8 duration-500">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h3 className="text-3xl font-extrabold tracking-tight text-on-surface">Future Load Forecast</h3>
          <p className="mt-1 text-on-surface-variant">{selectedWindow.label} predicted peak-risk view for {analysis.metadata.site_id}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-2 rounded-full border border-outline-variant/10 bg-surface-container-low px-4 py-2 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
            Window
            <select
              value={windowSize}
              onChange={event => setWindowSize(event.target.value)}
              className="rounded-full border border-outline-variant/20 bg-surface-container-lowest px-3 py-1 text-[11px] font-black text-on-surface outline-none focus:border-primary focus:ring-2 focus:ring-primary/10"
            >
              {windowOptions.map(option => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
          <div className="flex rounded-full border border-outline-variant/10 bg-surface-container-low p-1 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
            {[
              { id: 'grid_import' as const, label: 'Grid import' },
              { id: 'gross_load' as const, label: 'Gross load' },
            ].map(option => (
              <button
                key={option.id}
                type="button"
                onClick={() => setChartBasis(option.id)}
                className={`rounded-full px-3 py-1 transition-colors ${
                  chartBasis === option.id
                    ? 'bg-primary text-on-primary shadow-sm'
                    : 'text-on-surface-variant hover:bg-surface-container-high'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 rounded-xl bg-surface-container-low px-4 py-2">
            <div className="h-2 w-2 rounded-full bg-secondary" />
            <span className="text-sm font-medium">Site live</span>
          </div>
          <div className="flex items-center gap-2 rounded-xl bg-tertiary-fixed px-4 py-2">
            <AlertCircle size={16} className="text-on-tertiary-fixed" />
            <span className="text-sm font-bold text-on-tertiary-fixed">{overlayEvents} peak events detected</span>
          </div>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_23rem]">
        <div className="space-y-6">
          <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
            <div className="mb-8 flex items-center justify-between">
              <div>
                <h4 className="text-lg font-bold">Predicted Demand</h4>
                <p className="text-xs font-medium text-on-surface-variant">Future forecast points with peak-risk markers.</p>
              </div>
            </div>

            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#c2c6d4" strokeOpacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#424752' }} />
                  <YAxis hide />
                  <Tooltip contentStyle={{ backgroundColor: '#ffffff', borderRadius: '12px', border: '1px solid #c2c6d4' }} />
                  <ReferenceLine x={chartPeak.time} stroke="#793300" strokeDasharray="4 4" />
                  <Area type="monotone" dataKey="forecast" stroke="#1b6d24" strokeWidth={3} fill="#1b6d24" fillOpacity={0.08} name="Predicted load" />
                  <Scatter dataKey="overlayPoint" fill="#793300" name="Peak risk" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h4 className="font-bold">Top Risk Windows - {planningDays}-Day Outlook</h4>
                <p className="text-xs font-medium text-on-surface-variant">
                  Ranked forecast intervals across the full {planningDays}-day planning period.
                </p>
              </div>
              <span className="rounded-full bg-primary-fixed px-3 py-1 text-[10px] font-black uppercase tracking-widest text-primary">{countPeakRiskAlerts(analysis)} alerts</span>
            </div>
            <div className="grid gap-3">
              {riskWindows.map(item => (
                <div
                  key={item.key}
                  className="grid gap-4 rounded-lg border border-outline-variant/10 bg-surface-container-low p-4 md:grid-cols-[auto_1fr_auto] md:items-center"
                >
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg text-xs font-black ${
                    item.level === 'critical' ? 'bg-tertiary-fixed text-tertiary' : 'bg-primary-fixed text-primary'
                  }`}>
                    {item.rank}
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-black text-on-surface">{item.day}, {item.timeWindow}</p>
                      <span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-widest ${
                        item.level === 'critical' ? 'bg-tertiary-fixed text-tertiary' : 'bg-primary-fixed text-primary'
                      }`}>
                        {item.level === 'critical' ? 'Critical' : 'MD risk'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs font-medium text-on-surface-variant">{item.label} - {item.action}</p>
                  </div>
                  <div className="md:text-right">
                    <p className="font-headline text-xl font-black text-on-surface">{item.peakLoad.toFixed(0)} kW</p>
                    <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
                      {(item.score * 100).toFixed(0)} risk
                    </p>
                  </div>
                </div>
              ))}
              {riskWindows.length === 0 && (
                <div className="rounded-lg border border-outline-variant/10 bg-surface-container-low p-5 text-sm font-bold text-on-surface-variant">
                  No high-risk forecast windows in the selected planning run.
                </div>
              )}
            </div>
          </section>
        </div>

        <aside className="flex flex-col gap-6">
          <section className="rounded-xl border-l-4 border-tertiary bg-tertiary-fixed p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h4 className="font-bold">Window Peak</h4>
              <span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-widest ${peakBadgeClass}`}>{peakBadgeLabel}</span>
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Peak in selected {selectedWindow.label} window</p>
            <p className="mt-1 text-2xl font-black text-on-surface">{formatPeakWindow(peakTime)}</p>
            <p className="mt-2 text-xs font-semibold leading-relaxed text-on-surface-variant">
              Highest predicted demand point inside the active chart window.
            </p>
            <div className="mt-5 flex items-center justify-between border-t border-tertiary/15 pt-4 text-sm">
              <span className="font-bold text-on-surface-variant">Intensity</span>
              <span className="font-black text-tertiary">{peakLoad.toFixed(0)} kW</span>
            </div>
          </section>

          <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
            <div className="mb-4">
              <h4 className="font-bold">Recommended Response</h4>
              <p className="text-xs font-medium text-on-surface-variant">Actions for the selected forecast window.</p>
            </div>
            <div className="grid gap-3">
              {responseItems.map((item, index) => {
                const Icon = item.kind === 'battery' ? BatteryCharging : item.kind === 'shift' ? Clock : Gauge;
                return (
                  <div key={item.title} className="grid gap-3 rounded-lg bg-surface-container-low p-3 text-sm md:grid-cols-[auto_1fr]">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-fixed text-primary">
                      <Icon size={15} />
                    </div>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[10px] font-black uppercase tracking-widest text-primary">Step {index + 1}</span>
                        <span className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{item.meta}</span>
                      </div>
                      <p className="mt-1 font-black text-on-surface">{item.title}</p>
                      <p className="mt-1 text-xs font-semibold leading-relaxed text-on-surface-variant">{item.detail}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-xl bg-primary p-6 text-on-primary shadow-xl shadow-primary/20">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-fixed text-primary">
                <ShieldCheck size={18} />
              </div>
              <div>
                <h4 className="font-bold">Immediate Mitigation</h4>
                <p className="text-xs font-semibold text-primary-fixed">Operational target for this forecast risk.</p>
              </div>
            </div>
            <div className="space-y-5 text-sm">
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">
                  {mitigation.requiresImmediateReduction ? 'Reduce this window by' : 'Current window status'}
                </p>
                <p className={mitigation.requiresImmediateReduction ? 'text-3xl font-black' : 'text-2xl font-black leading-tight'}>
                  {mitigation.headline}
                </p>
                <p className="mt-1 text-xs font-semibold leading-relaxed text-primary-fixed">
                  {mitigation.guidance}
                </p>
              </div>
              <div className="grid gap-3">
                <div className="rounded-lg bg-white/10 p-3">
                  <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">Planning basis</p>
                  <p className="mt-1 font-black">{mitigation.planBasis}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-white/10 p-3">
                    <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">Scenario MD cut</p>
                    <p className="mt-1 font-black">{formatKw(mitigation.mdReductionKw)}</p>
                  </div>
                  <div className="rounded-lg bg-white/10 p-3">
                    <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">MD target</p>
                    <p className="mt-1 font-black">{formatKw(mitigation.targetMdKw)}</p>
                  </div>
                </div>
                <div className="space-y-2 rounded-lg bg-white/10 p-3">
                  <div className="flex gap-2">
                    <BatteryCharging size={15} className="mt-0.5 shrink-0 text-primary-fixed" />
                    <p className="font-semibold leading-relaxed">{mitigation.storageText}</p>
                  </div>
                  <div className="flex gap-2">
                    <SunMedium size={15} className="mt-0.5 shrink-0 text-primary-fixed" />
                    <p className="font-semibold leading-relaxed">{mitigation.solarText}</p>
                  </div>
                </div>
                <p className="text-xs font-semibold leading-relaxed text-primary-fixed">
                  Full savings, CAPEX, payback, and scenario comparison remain in Optimization.
                </p>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
