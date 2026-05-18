import { Activity, AlertTriangle, BatteryCharging, CloudSun, Factory, Gauge, Sun, Zap } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult } from '../lib/api';
import { cn } from '../lib/utils';
import {
  buildPeakTimelineItems,
  buildSiteLoadChartPoints,
  countPeakRiskAlerts,
  forecastWindowLabel,
} from './forecastWindow';

export { buildPeakTimelineItems, buildSiteLoadChartPoints, selectForecastWindowPoints } from './forecastWindow';

interface SiteProfileProps {
  analysis: AnalysisResult | null;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
}

export function buildSolarImpactComparison(analysis: AnalysisResult) {
  const points = analysis.optimization.schedule_preview;
  const baselineKwh = points.reduce((total, point) => total + Math.max(Number(point.baseline_kw_import), 0) * 0.5, 0);
  const solarOffsetKwh = points.reduce((total, point) => total + Math.max(Number(point.solar_offset_kw), 0) * 0.5, 0);
  const cloudyOffsetKwh = points.reduce((total, point) => total + Math.max(Number(point.battery_discharge_kw), 0) * 0.5, 0);
  const solarOffsetPct = baselineKwh > 0 ? (solarOffsetKwh / baselineKwh) * 100 : 0;
  const cloudyOffsetPct = baselineKwh > 0 ? (cloudyOffsetKwh / baselineKwh) * 100 : 0;
  const dailySavingsRm = points.reduce((total, point) => {
    const hour = new Date(point.interval_end).getHours();
    const rate = hour >= 14 && hour < 22
      ? analysis.assumptions.peak_energy_rate_rm_per_kwh
      : analysis.assumptions.offpeak_energy_rate_rm_per_kwh;
    return total + Math.max(Number(point.solar_offset_kw), 0) * 0.5 * rate;
  }, 0);

  return {
    solarOffsetPct,
    cloudyOffsetPct,
    dailySavingsRm,
  };
}

export function SiteProfile({ analysis, loading, loadingStep, error }: SiteProfileProps) {
  const profile = analysis?.profile;
  const metadata = analysis?.metadata;
  const points = buildSiteLoadChartPoints(analysis);
  const best = analysis?.optimization.best_scenario;
  const maxPoint = points.reduce((peak, point) => (point.load > peak.load ? point : peak), points[0] ?? { time: '', load: 0 });

  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Site profile unavailable" message={error} />;
    return <EmptyAnalysis title="No site profile yet" description="Analyze a bundled workbook or upload an .xlsx file to view load shape, observed MD, solar metadata, and data-quality flags." />;
  }

  const windowLabel = forecastWindowLabel(analysis);

  return (
    <div className="animate-in fade-in duration-500 space-y-8">
      <div className="flex items-center justify-between">
        <p className="text-xs text-on-surface-variant italic flex items-center gap-1.5 font-medium">
          <Activity size={14} className="text-primary" />
          Analysis generated from <span className="font-black text-on-surface not-italic">{metadata?.source_file}</span>
        </p>
        <span className="text-[10px] font-black text-on-surface-variant uppercase tracking-widest">
          {profile?.start} to {profile?.end}
        </span>
      </div>

      <div className="grid grid-cols-12 items-start gap-6">
        <section className="col-span-12 lg:col-span-8 bg-surface-container-lowest p-8 rounded-xl shadow-sm border border-outline-variant/10">
          <div className="flex justify-between items-end mb-8">
            <div>
              <h3 className="font-headline text-2xl font-black text-on-surface leading-tight">Operational Load Curve</h3>
              <p className="text-on-surface-variant text-sm font-medium mt-1">Historical grid-import load from the active dataset.</p>
            </div>
            <div className="rounded-lg bg-primary-fixed px-3 py-2 text-right">
              <p className="text-[10px] font-black uppercase tracking-widest text-primary">Peak load</p>
              <p className="text-sm font-black text-on-surface">{maxPoint.load.toFixed(0)} kW</p>
            </div>
          </div>

          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <CartesianGrid strokeDasharray="5 5" vertical={false} stroke="#c2c6d4" strokeOpacity={0.16} />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#727783', fontWeight: 600 }} />
                <YAxis hide />
                <Tooltip contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 20px 25px -5px rgb(0 0 0 / 0.1)' }} />
                <ReferenceLine x={maxPoint.time} stroke="#00488d" strokeDasharray="4 4" />
                <Area type="monotone" dataKey="load" stroke="#1b6d24" strokeWidth={3} fill="#1b6d24" fillOpacity={0.08} name="Historical import" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="col-span-12 lg:col-span-4 bg-primary text-on-primary p-8 rounded-xl shadow-2xl shadow-primary/20">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Zap size={16} className="text-primary-fixed" />
              <span className="text-[10px] font-black uppercase tracking-widest opacity-70">Observed Maximum Demand</span>
            </div>
            <h4 className="text-5xl font-black font-headline leading-none">{profile?.peak_kw_import.toFixed(0)} <span className="text-xl font-medium opacity-50">kW</span></h4>
            <p className="mt-4 text-sm opacity-90 leading-relaxed font-medium">
              Average import is {profile?.avg_kw_import.toFixed(1)} kW across {profile?.rows.toLocaleString()} normalized intervals.
            </p>
          </div>
        </section>
      </div>

      <div className="grid grid-cols-12 items-stretch gap-6">
        <section className="col-span-12 lg:col-span-8 rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
          <div className="mb-5 flex items-center justify-between gap-4">
            <div>
              <h3 className="font-headline text-lg font-black text-on-surface">Peak Risk Timeline</h3>
              <p className="text-xs font-medium text-on-surface-variant">{windowLabel} from the active analysis.</p>
            </div>
            <div className="flex items-center gap-3 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-primary-fixed-dim" /> MD risk</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-tertiary" /> Critical</span>
            </div>
          </div>

          <div className="grid grid-cols-12 gap-1">
            {buildPeakTimelineItems(analysis).map(item => (
              <div
                key={item.time}
                title={`${item.time} ${item.label}: ${item.peakLoad.toFixed(0)} kW`}
                className={cn(
                  'h-10 rounded-md border transition-transform hover:scale-[1.03]',
                  item.level === 'critical'
                    ? 'border-tertiary/30 bg-tertiary-fixed'
                    : item.level === 'risk'
                      ? 'border-primary-fixed-dim/50 bg-primary-fixed'
                      : 'border-outline-variant/10 bg-surface-container-low'
                )}
              />
            ))}
          </div>

          <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
            {['Morning ramp', 'Operational peak', 'Evening MD risk'].map((label, index) => (
              <div key={label} className="rounded-lg bg-surface-container-low p-3">
                <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
                  {index === 0 ? '06:30 - 10:00' : index === 1 ? '14:00 - 16:00' : '19:00 - 21:00'}
                </p>
                <p className="mt-1 text-xs font-black text-on-surface">{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-5 border-t border-outline-variant/10 pt-4">
            <p className="mb-3 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Action Required</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {['Battery discharge', 'Shift flexible load', 'Monitor MD threshold'].map(action => (
                <div key={action} className="rounded-lg bg-surface-container-low px-4 py-3 text-center text-xs font-black text-on-surface">
                  {action}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="col-span-12 lg:col-span-4 rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
          {(() => {
            const solar = buildSolarImpactComparison(analysis);
            return (
              <>
                <div className="mb-6">
                  <div className="mb-3 flex items-center gap-2">
                    <CloudSun size={18} className="text-primary" />
                    <h3 className="font-headline text-lg font-black text-on-surface">Solar Impact Comparison</h3>
                  </div>
                  <p className="text-xs font-medium text-on-surface-variant">Performance shift for the active scenario forecast.</p>
                </div>

                <div className="space-y-5">
                  <div>
                    <div className="mb-2 flex items-center justify-between text-xs font-black">
                      <span className="flex items-center gap-2 text-secondary"><Sun size={13} /> Solar active</span>
                      <span>{solar.solarOffsetPct.toFixed(0)}% offset</span>
                    </div>
                    <div className="h-8 overflow-hidden rounded-lg bg-primary-fixed">
                      <div className="h-full rounded-lg bg-secondary" style={{ width: `${Math.min(solar.solarOffsetPct, 100)}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 flex items-center justify-between text-xs font-black">
                      <span className="flex items-center gap-2 text-tertiary"><CloudSun size={13} /> Non-solar/cloudy</span>
                      <span>{solar.cloudyOffsetPct.toFixed(0)}% offset</span>
                    </div>
                    <div className="h-8 overflow-hidden rounded-lg bg-primary-fixed">
                      <div className="h-full rounded-lg bg-primary" style={{ width: `${Math.min(solar.cloudyOffsetPct, 100)}%` }} />
                    </div>
                  </div>
                </div>

                <div className="mt-8 border-t border-outline-variant/10 pt-5">
                  <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Preview energy savings</p>
                  <p className="mt-1 font-headline text-3xl font-black text-secondary">
                    RM {solar.dailySavingsRm.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </p>
                  <p className="mt-2 text-xs font-medium text-on-surface-variant">From solar offset in the optimized schedule preview.</p>
                </div>
              </>
            );
          })()}
        </section>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        {[
          { label: 'Weekday Avg', value: `${profile?.weekday_avg_kw_import.toFixed(1)} kW`, icon: Factory },
          { label: 'Weekend Avg', value: `${profile?.weekend_avg_kw_import.toFixed(1)} kW`, icon: Activity },
          { label: 'Solar Capacity', value: metadata?.has_solar ? `${metadata.existing_pv_kwp?.toFixed(0) ?? 'Known'} kWp` : 'No solar', icon: Sun },
          { label: 'Risk Alerts', value: `${countPeakRiskAlerts(analysis)} windows`, icon: AlertTriangle },
          { label: 'MD Reduction', value: best ? `${(best.md_before - best.md_after).toFixed(0)} kW` : 'N/A', icon: Gauge },
          { label: 'Battery Plan', value: best ? `${best.battery_kw.toFixed(0)} kW` : 'N/A', icon: BatteryCharging },
          { label: 'Savings', value: best ? `RM ${best.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : 'N/A', icon: Zap },
          { label: 'Data Quality', value: `${analysis.validation.gap_count} gaps`, icon: AlertTriangle },
        ].map(stat => (
          <div key={stat.label} className="p-6 rounded-xl shadow-sm border border-outline-variant/5 bg-surface-container-low">
            <stat.icon size={18} className="text-primary mb-4" />
            <p className="text-[10px] font-black text-on-surface-variant uppercase tracking-widest mb-2 opacity-60">{stat.label}</p>
            <p className="text-2xl font-black font-headline tracking-tight">{stat.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
