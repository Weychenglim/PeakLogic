import { Download, Leaf, ShieldCheck, TrendingUp, Zap } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult } from '../lib/api';
import { downloadCsv } from '../lib/api';

interface ExecutiveSummaryProps {
  analysis: AnalysisResult | null;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
}

function chartData(analysis: AnalysisResult | null) {
  return (analysis?.optimization.schedule_preview ?? []).filter((_, index) => index % 8 === 0).map(point => ({
    time: new Date(point.interval_end).toLocaleString([], { hour: '2-digit', minute: '2-digit' }),
    baseline: Number(point.baseline_kw_import),
    optimized: Number(point.optimized_kw_import),
  }));
}

export function ExecutiveSummary({ analysis, loading, loadingStep, error }: ExecutiveSummaryProps) {
  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Executive summary unavailable" message={error} />;
    return <EmptyAnalysis title="No executive summary yet" description="Analyze a workbook to generate the judge-facing savings, MD reduction, payback, and recommendation story." />;
  }

  const best = analysis.optimization.best_scenario;
  const paybackYears = best.payback_months ? best.payback_months / 12 : null;
  const data = chartData(analysis);
  const mdReductionKw = best.md_before - best.md_after;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex justify-between items-end gap-6">
        <div className="space-y-1">
          <h1 className="text-4xl font-extrabold text-on-surface tracking-tight font-headline">Executive Summary</h1>
          <p className="text-on-surface-variant max-w-2xl">
            This site has costly maximum-demand spikes. The selected scenario uses battery discharge and load shifting to reduce the monthly peak, with solar offset where it improves savings.
          </p>
        </div>
        <button
          onClick={() => downloadCsv(`${analysis.metadata.site_id}-scenario-summary.csv`, analysis.exports.scenario_summary_csv)}
          className="bg-primary text-on-primary px-6 py-3 rounded-full font-bold flex items-center gap-2 hover:opacity-90 active:scale-95 shadow-xl shadow-primary/20 transition-all"
        >
          <Download size={20} />
          Download CSV
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border border-outline-variant/10">
          <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Estimated Savings</p>
          <span className="text-3xl font-black text-primary tracking-tight font-headline">RM {best.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
          <div className="mt-4 flex items-center gap-2 text-secondary font-bold text-[10px] bg-secondary-container/30 px-3 py-1 rounded-full w-fit">
            <TrendingUp size={12} />
            Selected scenario
          </div>
        </div>

        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border border-outline-variant/10">
          <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Peak Reduction</p>
          <span className="text-3xl font-black text-on-surface tracking-tight font-headline">{best.peak_reduction_pct.toFixed(1)}%</span>
          <p className="mt-4 text-[10px] font-bold text-on-surface-variant">MD {best.md_before.toFixed(0)} to {best.md_after.toFixed(0)} kW</p>
        </div>

        <div className="bg-primary text-on-primary p-6 rounded-xl shadow-xl shadow-primary/20">
          <p className="text-[10px] font-bold text-primary-fixed uppercase tracking-widest mb-2 opacity-80">Recommended System</p>
          <h3 className="text-xl font-extrabold mb-1 font-headline">{best.battery_kw.toFixed(0)} kW / {best.battery_kwh.toFixed(0)} kWh</h3>
          <p className="text-[10px] text-primary-fixed opacity-90 leading-tight">Battery with {best.solar_kwp.toFixed(0)} kWp incremental PV</p>
        </div>

        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border-2 border-primary-fixed/50">
          <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Payback Period</p>
          <span className="text-3xl font-black text-on-surface tracking-tight font-headline">{paybackYears ? paybackYears.toFixed(1) : 'N/A'}</span>
          <span className="ml-1 text-xl font-bold text-on-surface-variant">Years</span>
          <p className="mt-4 text-[10px] font-bold text-tertiary uppercase tracking-widest leading-none">Estimated payback</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-5 pt-4">
        {[
          { label: 'Problem', icon: Zap, text: `Costly maximum-demand spikes, with observed MD reaching ${analysis.profile.peak_kw_import.toFixed(0)} kW.` },
          { label: 'Action', icon: ShieldCheck, text: 'Use battery discharge and load shifting to reduce the monthly peak.' },
          { label: 'Result', icon: TrendingUp, text: `Reduce MD by ${mdReductionKw.toFixed(1)} kW and save about RM ${best.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}.` },
          { label: 'Investment', icon: Leaf, text: `${best.battery_kw.toFixed(0)} kW / ${best.battery_kwh.toFixed(0)} kWh battery plus ${best.solar_kwp.toFixed(0)} kWp solar.` },
          { label: 'Payback', icon: ShieldCheck, text: paybackYears ? `Estimated payback is ${paybackYears.toFixed(1)} years.` : 'No payback period because the selected scenario has no CAPEX.' },
        ].map(item => (
          <div key={item.label} className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full flex items-center justify-center bg-primary-fixed text-primary">
                <item.icon size={20} />
              </div>
              <h4 className="text-xl font-bold font-headline">{item.label}</h4>
            </div>
            <div className="bg-surface-container-low p-6 rounded-xl shadow-sm h-full">
              <p className="text-sm text-on-surface leading-relaxed opacity-90">{item.text}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-surface-container-lowest p-8 rounded-xl shadow-sm border border-outline-variant/10 space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h4 className="font-bold text-lg font-headline">Schedule Impact Preview</h4>
            <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{analysis.metadata.site_id}</p>
          </div>
        </div>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <Area type="monotone" dataKey="baseline" stroke="#c2c6d4" strokeWidth={2} strokeDasharray="5 5" fill="none" />
              <Area type="monotone" dataKey="optimized" stroke="#1b6d24" strokeWidth={3} fill="#1b6d24" fillOpacity={0.1} />
              <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#727783' }} />
              <YAxis hide />
              <Tooltip />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
