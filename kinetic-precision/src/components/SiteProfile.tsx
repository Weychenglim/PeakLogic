import { Activity, AlertTriangle, BarChart3, Factory, Gauge, Sun, Zap } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult } from '../lib/api';
import {
  buildSiteLoadChartPoints,
} from './forecastWindow';

export { buildPeakTimelineItems, buildSiteLoadChartPoints, selectForecastWindowPoints } from './forecastWindow';

interface SiteProfileProps {
  analysis: AnalysisResult | null;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
}

export function SiteProfile({ analysis, loading, loadingStep, error }: SiteProfileProps) {
  const profile = analysis?.profile;
  const metadata = analysis?.metadata;
  const points = buildSiteLoadChartPoints(analysis);
  const maxPoint = points.reduce((peak, point) => (point.load > peak.load ? point : peak), points[0] ?? { time: '', load: 0 });

  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Site profile unavailable" message={error} />;
    return <EmptyAnalysis title="No site profile yet" description="Analyze a bundled workbook or upload an .xlsx file to view load shape, observed MD, solar metadata, and data-quality flags." />;
  }

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

      <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
        {[
          { label: 'Weekday Avg', value: `${profile?.weekday_avg_kw_import.toFixed(1)} kW`, icon: Factory },
          { label: 'Weekend Avg', value: `${profile?.weekend_avg_kw_import.toFixed(1)} kW`, icon: Activity },
          { label: 'Average Import', value: `${profile?.avg_kw_import.toFixed(1)} kW`, icon: Gauge },
          { label: 'Intervals', value: profile?.rows.toLocaleString() ?? '0', icon: BarChart3 },
          { label: 'Solar Capacity', value: metadata?.has_solar ? `${metadata.existing_pv_kwp?.toFixed(0) ?? 'Known'} kWp` : 'No solar', icon: Sun },
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
