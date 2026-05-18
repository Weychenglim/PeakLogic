import { useState } from 'react';
import { AlertCircle, BatteryCharging, Clock, Gauge, ShieldCheck, Zap } from 'lucide-react';
import { Area, CartesianGrid, ComposedChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult } from '../lib/api';
import {
  buildForecastChartPoints,
  buildPeakTimelineItems,
  countPeakRiskAlerts,
  forecastGrossLoad,
  forecastLoad,
  forecastWindowLabel,
  selectForecastWindowPoints,
  selectForecastPeakPoint,
  type ForecastChartBasis,
} from './forecastWindow';

export {
  buildForecastChartPoints,
  buildPeakTimelineItems as buildForecastPeakTimelineItems,
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

function formatTimeWindow(startIso: string, hours = 2) {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + hours * 60 * 60 * 1000);
  return `${start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

export function ForecastRisk({ analysis, loading, loadingStep, error }: ForecastRiskProps) {
  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Forecast unavailable" message={error} />;
    return <EmptyAnalysis title="No forecast yet" description="Run an analysis to inspect predicted demand, peak-risk windows, and recommended mitigation actions." />;
  }

  const windowOptions = [
    { id: '12h', label: '12h', intervals: 24 },
    { id: '24h', label: '24h', intervals: 48 },
    { id: '48h', label: '48h', intervals: 96 },
    { id: '7d', label: '7 days', intervals: 7 * 48 },
    { id: '1m', label: '1 month', intervals: 30 * 48 },
  ];
  const [windowSize, setWindowSize] = useState('24h');
  const [chartBasis, setChartBasis] = useState<ForecastChartBasis>('grid_import');
  const selectedWindow = windowOptions.find(option => option.id === windowSize) ?? windowOptions[1];
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
  const timelineItems = buildPeakTimelineItems(analysis);
  const windowLabel = forecastWindowLabel(analysis);
  const best = analysis.optimization.best_scenario;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h3 className="text-3xl font-extrabold tracking-tight text-on-surface">Future Load Forecast</h3>
          <p className="text-on-surface-variant mt-1">{selectedWindow.label} predicted peak-risk view for {analysis.metadata.site_id}</p>
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
          <div className="px-4 py-2 bg-surface-container-low rounded-xl flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-secondary" />
            <span className="text-sm font-medium">Site live</span>
          </div>
          <div className="px-4 py-2 bg-tertiary-fixed rounded-xl flex items-center gap-2">
            <AlertCircle size={16} className="text-on-tertiary-fixed" />
            <span className="text-sm font-bold text-on-tertiary-fixed">{overlayEvents} peak events detected</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 items-start gap-6">
        <div className="col-span-12 lg:col-span-8 bg-surface-container-lowest rounded-xl p-6 border border-outline-variant/10 shadow-sm">
          <div className="flex justify-between items-center mb-8">
            <div>
              <h4 className="text-lg font-bold">Predicted Demand</h4>
              <p className="text-xs text-on-surface-variant font-medium">Future forecast points with peak-risk markers.</p>
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
        </div>

        <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
          <div className="rounded-xl border-l-4 border-tertiary bg-tertiary-fixed p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h4 className="font-bold">Window Peak</h4>
              <span className="rounded-full bg-error px-2 py-1 text-[10px] font-black uppercase tracking-widest text-white">High risk</span>
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Estimated window</p>
            <p className="mt-1 text-3xl font-black text-on-surface">{formatTimeWindow(peakTime)}</p>
            <div className="mt-5 flex items-center justify-between border-t border-tertiary/15 pt-4 text-sm">
              <span className="font-bold text-on-surface-variant">Intensity</span>
              <span className="font-black text-tertiary">{peakLoad.toFixed(0)} kW</span>
            </div>
          </div>

          <div className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
            <h4 className="mb-4 font-bold">Recommended Response</h4>
            <div className="grid gap-3 text-sm font-bold">
              <div className="flex items-center gap-3 rounded-lg bg-surface-container-low p-3">
                <BatteryCharging size={16} className="text-primary" />
                Battery discharge
              </div>
              <div className="flex items-center gap-3 rounded-lg bg-surface-container-low p-3">
                <Clock size={16} className="text-primary" />
                Shift flexible load
              </div>
              <div className="flex items-center gap-3 rounded-lg bg-surface-container-low p-3">
                <Gauge size={16} className="text-primary" />
                Monitor MD threshold
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm lg:col-span-2">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h4 className="font-bold">Peak Risk Timeline</h4>
              <p className="text-xs font-medium text-on-surface-variant">{windowLabel}</p>
            </div>
            <span className="rounded-full bg-primary-fixed px-3 py-1 text-[10px] font-black uppercase tracking-widest text-primary">{overlayEvents} alerts</span>
          </div>
          <div className="grid grid-cols-6 gap-1">
            {timelineItems.slice(0, 36).map(item => (
              <div
                key={item.key}
                className={`h-8 rounded-md ${item.level === 'critical' ? 'bg-tertiary-fixed border border-tertiary/20' : item.level === 'risk' ? 'bg-primary-fixed' : 'bg-surface-container-low'}`}
                title={`${item.time}: ${item.label}, ${item.peakLoad.toFixed(0)} kW`}
              />
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-xs font-bold">
            <span className="rounded-full bg-surface-container-low px-3 py-2">Morning ramp</span>
            <span className="rounded-full bg-tertiary-fixed px-3 py-2 text-tertiary">Operational peak</span>
            <span className="rounded-full bg-primary-fixed px-3 py-2 text-primary">Evening MD risk</span>
          </div>
        </section>

        <section className="rounded-xl bg-primary p-6 text-on-primary shadow-xl shadow-primary/20">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-fixed text-primary">
              <ShieldCheck size={18} />
            </div>
            <h4 className="font-bold">Peak Reduction Plan</h4>
          </div>
          <div className="space-y-4 text-sm">
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">MD reduction</p>
              <p className="text-3xl font-black">{(best.md_before - best.md_after).toFixed(0)} kW</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-white/10 p-3">
                <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">Savings</p>
                <p className="mt-1 font-black">RM {best.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
              </div>
              <div className="rounded-lg bg-white/10 p-3">
                <p className="text-[10px] font-black uppercase tracking-widest text-primary-fixed">Battery</p>
                <p className="mt-1 font-black">{best.battery_kw.toFixed(0)} kW</p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
