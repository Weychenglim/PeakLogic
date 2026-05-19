import { Activity, CalendarClock, Factory, Gauge, Moon, Sun, Zap } from 'lucide-react';
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

export type ObservedPeakEvent = {
  key: string;
  rank: number;
  time: string;
  day: string;
  load: number;
};

export type LoadPatternSummary = {
  weekdayAvg: number;
  weekendAvg: number;
  daytimeAvg: number;
  nightAvg: number;
  peakToAverageRatio: number;
};

export type SiteFactItem = {
  label: string;
  value: string;
};

export function buildObservedPeakEvents(analysis: AnalysisResult, limit = 3): ObservedPeakEvent[] {
  return [...(analysis.load_history ?? [])]
    .sort((a, b) => Number(b.kw_import) - Number(a.kw_import))
    .slice(0, limit)
    .map((point, index) => {
      const date = new Date(point.interval_end);
      return {
        key: point.interval_end,
        rank: index + 1,
        time: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        day: date.toLocaleDateString([], { month: 'short', day: 'numeric' }),
        load: Number(point.kw_import),
      };
    });
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

export function buildLoadPatternSummary(analysis: AnalysisResult): LoadPatternSummary {
  const history = analysis.load_history ?? [];
  const daytime: number[] = [];
  const night: number[] = [];

  for (const point of history) {
    const hour = new Date(point.interval_end).getHours();
    const load = Number(point.kw_import);
    if (hour >= 6 && hour < 18) {
      daytime.push(load);
    } else {
      night.push(load);
    }
  }

  const peak = Number(analysis.profile?.peak_kw_import ?? 0);
  const avgImport = Number(analysis.profile?.avg_kw_import ?? 0);
  return {
    weekdayAvg: Number(analysis.profile?.weekday_avg_kw_import ?? 0),
    weekendAvg: Number(analysis.profile?.weekend_avg_kw_import ?? 0),
    daytimeAvg: average(daytime),
    nightAvg: average(night),
    peakToAverageRatio: avgImport > 0 ? peak / avgImport : 0,
  };
}

export function buildSiteFactItems(analysis: AnalysisResult): SiteFactItem[] {
  return [
    {
      label: 'Intervals',
      value: analysis.profile?.rows.toLocaleString() ?? '0',
    },
    {
      label: 'Solar capacity',
      value: analysis.metadata?.has_solar
        ? `${analysis.metadata.existing_pv_kwp?.toFixed(0) ?? 'Known'} kWp`
        : 'No solar',
    },
    {
      label: 'Data quality',
      value: `${analysis.validation?.gap_count ?? 0} gaps`,
    },
  ];
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

  const observedPeaks = buildObservedPeakEvents(analysis);
  const loadPattern = buildLoadPatternSummary(analysis);
  const siteFacts = buildSiteFactItems(analysis);

  return (
    <div className="animate-in fade-in duration-500 space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-xs text-on-surface-variant italic flex items-center gap-1.5 font-medium">
          <Activity size={14} className="text-primary" />
          Analysis generated from <span className="font-black text-on-surface not-italic">{metadata?.source_file}</span>
        </p>
        <span className="text-[10px] font-black text-on-surface-variant uppercase tracking-widest">
          {profile?.start} to {profile?.end}
        </span>
      </div>

      <div className="grid grid-cols-12 items-start gap-5">
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

        <div className="col-span-12 grid gap-5 lg:col-span-4">
          <section className="bg-primary text-on-primary p-7 rounded-xl shadow-2xl shadow-primary/20">
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

          <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <CalendarClock size={16} className="text-primary" />
              <h3 className="font-headline text-base font-black text-on-surface">Observed Peak Events</h3>
            </div>
            <div className="grid gap-2">
              {observedPeaks.map(event => (
                <div key={event.key} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-lg bg-surface-container-low px-3 py-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-fixed text-xs font-black text-primary">{event.rank}</div>
                  <div>
                    <p className="text-sm font-black text-on-surface">{event.day}, {event.time}</p>
                    <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Historical peak</p>
                  </div>
                  <p className="text-sm font-black text-primary">{event.load.toFixed(0)} kW</p>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
        <div className="mb-5">
          <h3 className="font-headline text-lg font-black text-on-surface">Site Operating Pattern</h3>
          <p className="text-xs font-medium text-on-surface-variant">Historical shape and compact site facts from the active dataset.</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_auto]">
          <div className="rounded-lg bg-surface-container-low p-4">
            <div className="mb-3 flex items-center gap-2 text-primary">
              <Factory size={16} />
              <p className="text-[10px] font-black uppercase tracking-widest">Weekday vs weekend</p>
            </div>
            <p className="font-headline text-2xl font-black">{loadPattern.weekdayAvg.toFixed(1)} kW</p>
            <p className="text-xs font-bold text-on-surface-variant">Weekend avg {loadPattern.weekendAvg.toFixed(1)} kW</p>
          </div>
          <div className="rounded-lg bg-surface-container-low p-4">
            <div className="mb-3 flex items-center gap-2 text-primary">
              <Sun size={16} />
              <p className="text-[10px] font-black uppercase tracking-widest">Daytime vs night</p>
            </div>
            <p className="font-headline text-2xl font-black">{loadPattern.daytimeAvg.toFixed(1)} kW</p>
            <p className="text-xs font-bold text-on-surface-variant"><Moon size={12} className="mr-1 inline" /> Night avg {loadPattern.nightAvg.toFixed(1)} kW</p>
          </div>
          <div className="rounded-lg bg-surface-container-low p-4">
            <div className="mb-3 flex items-center gap-2 text-primary">
              <Gauge size={16} />
              <p className="text-[10px] font-black uppercase tracking-widest">Peak-to-average</p>
            </div>
            <p className="font-headline text-2xl font-black">{loadPattern.peakToAverageRatio.toFixed(1)}x</p>
            <p className="text-xs font-bold text-on-surface-variant">Observed MD compared with average import</p>
          </div>
          <div className="grid gap-2 rounded-lg bg-surface-container-low p-4 lg:min-w-44">
            {siteFacts.map(fact => (
              <div key={fact.label} className="border-b border-outline-variant/10 pb-2 last:border-b-0 last:pb-0">
                <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{fact.label}</p>
                <p className="mt-1 text-sm font-black text-on-surface">{fact.value}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
