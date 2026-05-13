import { Battery, CheckCircle2, Info, RefreshCw, ShieldCheck, SlidersHorizontal, Sparkles, TrendingDown, Zap } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyAnalysis, ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult, PlanningAssumptions } from '../lib/api';
import { cn } from '../lib/utils';

interface OptimizationProps {
  analysis: AnalysisResult | null;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
  assumptions: PlanningAssumptions;
  onAssumptionsChange: (assumptions: PlanningAssumptions) => void;
  onApplyAssumptions: () => void;
  canApplyAssumptions: boolean;
}

function scheduleData(analysis: AnalysisResult | null) {
  return (analysis?.optimization.schedule_preview ?? []).filter((_, index) => index % 8 === 0).map(point => ({
    time: new Date(point.interval_end).toLocaleString([], { hour: '2-digit', minute: '2-digit' }),
    baseline: Number(point.baseline_kw_import),
    optimized: Number(point.optimized_kw_import),
  }));
}

function planningBasisLabel(riskBasis: string) {
  if (riskBasis === 'p95') return 'Conservative peak demand';
  if (riskBasis === 'p90') return 'Balanced peak demand';
  if (riskBasis === 'expected') return 'Expected demand';
  return riskBasis;
}

function AssumptionField({
  label,
  value,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{label}</span>
      <div className="relative">
        <input
          type="number"
          min="0"
          step={step ?? 1}
          value={value}
          onChange={event => onChange(Number(event.target.value))}
          className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-3 py-2 pr-10 text-sm font-bold outline-none focus:border-primary focus:ring-2 focus:ring-primary/10"
        />
        {suffix && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-black text-on-surface-variant">{suffix}</span>}
      </div>
    </label>
  );
}

export function Optimization({
  analysis,
  loading,
  loadingStep,
  error,
  assumptions,
  onAssumptionsChange,
  onApplyAssumptions,
  canApplyAssumptions,
}: OptimizationProps) {
  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Optimization unavailable" message={error} />;
    return <EmptyAnalysis title="No optimization results yet" description="Analyze a workbook to compare baseline cost, optimized MD, savings, payback, battery sizing, and solar sizing." />;
  }

  const best = analysis.optimization.best_scenario;
  const data = scheduleData(analysis);
  const analysisAssumptions = analysis.assumptions;
  const explanation = analysis.optimization.explanation;
  const sensitivityRows = analysis.optimization.sensitivity ?? [];
  const mdReductionKw = best.md_before - best.md_after;
  const updateAssumption = (key: keyof PlanningAssumptions, value: number) => {
    onAssumptionsChange({ ...assumptions, [key]: value });
  };

  return (
    <div className="animate-in fade-in duration-500 space-y-6">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm text-on-surface-variant flex items-center gap-2 italic">
          <Info size={14} className="text-primary" />
          {explanation.planning_basis_label}: {explanation.planning_basis_description}
        </p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-12 lg:col-span-4 space-y-6">
          <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border border-outline-variant/10">
            <div className="flex items-center gap-2 mb-6">
              <TrendingDown size={20} className="text-primary" />
              <h3 className="text-lg font-bold">Best Scenario</h3>
            </div>
            <div className="space-y-4 text-sm">
              <div className="flex justify-between"><span className="text-on-surface-variant">Battery power</span><strong>{best.battery_kw.toFixed(0)} kW</strong></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">Battery capacity</span><strong>{best.battery_kwh.toFixed(0)} kWh</strong></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">New solar</span><strong>{best.solar_kwp.toFixed(0)} kWp</strong></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">Planning basis</span><strong>{explanation.planning_basis_label || planningBasisLabel(best.risk_basis)}</strong></div>
            </div>
          </div>

          <div className="bg-primary text-on-primary p-6 rounded-xl relative overflow-hidden shadow-lg">
            <div className="relative z-10">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles size={18} className="text-primary-fixed" />
                <h3 className="font-bold text-lg">Recommendation</h3>
              </div>
              <p className="text-sm leading-relaxed opacity-90">{analysis.executive_summary}</p>
            </div>
          </div>
        </section>

        <section className="col-span-12 lg:col-span-8 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="rounded-xl bg-surface-container-lowest p-5 shadow-sm border border-outline-variant/10">
              <h4 className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">What Changed</h4>
              <p className="mt-3 text-sm leading-relaxed text-on-surface">
                {explanation.what_changed}
              </p>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-5 shadow-sm border border-outline-variant/10">
              <h4 className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Why This Scenario</h4>
              <p className="mt-3 text-sm leading-relaxed text-on-surface">
                {explanation.why_this_scenario}
              </p>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-5 shadow-sm border border-outline-variant/10">
              <h4 className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Savings Sensitivity</h4>
              <p className="mt-3 text-sm leading-relaxed text-on-surface">
                {explanation.savings_sensitivity}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-surface-container-low p-6 rounded-xl border-l-4 border-outline-variant shadow-sm">
              <h4 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Baseline</h4>
              <p className="text-2xl font-black text-on-surface">RM {best.bill_before_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
              <div className="grid grid-cols-2 gap-y-2 text-xs mt-4">
                <div className="text-on-surface-variant">MD before:</div>
                <div className="text-right font-bold tracking-tight">{best.md_before.toFixed(1)} kW</div>
              </div>
            </div>

            <div className="bg-secondary-container p-6 rounded-xl relative overflow-hidden shadow-lg border border-secondary/10">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h4 className="text-[10px] font-bold text-on-secondary-fixed uppercase tracking-widest opacity-70">Optimized</h4>
                  <p className="text-2xl font-black text-on-secondary-fixed">RM {best.bill_after_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
                <ShieldCheck size={24} className="text-secondary" />
              </div>
              <div className="grid grid-cols-2 gap-y-2 text-xs">
                <div className="text-on-secondary-fixed opacity-70">Savings:</div>
                <div className="text-right font-extrabold text-secondary">RM {best.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                <div className="text-on-secondary-fixed opacity-70">Payback:</div>
                <div className="text-right font-extrabold text-secondary">{best.payback_months ? `${best.payback_months.toFixed(1)} months` : 'No capex'}</div>
              </div>
            </div>
          </div>

          <div className="bg-surface-container-lowest p-8 rounded-xl shadow-sm border border-outline-variant/10 h-[420px]">
            <div className="flex justify-between items-center mb-8">
              <div>
                <h3 className="text-lg font-bold">Optimized Schedule Preview</h3>
                <p className="text-sm text-on-surface-variant">Comparing MD-risk baseline against optimized profile.</p>
              </div>
            </div>

            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#c2c6d4" strokeOpacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#424752' }} />
                  <YAxis hide />
                  <Tooltip cursor={{ fill: '#f3f3f7' }} contentStyle={{ borderRadius: '12px', border: 'none' }} />
                  <Bar dataKey="baseline" fill="#c2c6d4" opacity={0.35} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="optimized" fill="#00488d" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div className="bg-surface-container p-6 rounded-xl text-center">
              <Battery size={18} className="mx-auto mb-3 text-primary" />
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1 block">Peak Reduction</span>
              <span className="text-2xl font-black">{best.peak_reduction_pct.toFixed(1)}%</span>
            </div>
            <div className="bg-surface-container p-6 rounded-xl text-center">
              <Zap size={18} className="mx-auto mb-3 text-secondary" />
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1 block">MD After</span>
              <span className="text-2xl font-black">{best.md_after.toFixed(0)} kW</span>
            </div>
            <div className="bg-surface-container p-6 rounded-xl text-center">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1 block">Scenarios Tested</span>
              <span className="text-2xl font-black text-secondary">{analysis.optimization.scenarios.length}</span>
            </div>
          </div>

          {sensitivityRows.length > 0 && (
            <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border border-outline-variant/10">
              <div className="mb-4 flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold">Sensitivity Check</h3>
                  <p className="text-xs text-on-surface-variant">Active-analysis +/-10% checks for tariff and CAPEX assumptions.</p>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                {sensitivityRows.map(row => (
                  <div key={row.sensitivity_id} className="rounded-lg bg-surface-container-low p-4">
                    <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{row.label}</p>
                    <p className="mt-2 text-lg font-black text-on-surface">RM {row.savings_rm.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                    <p className="mt-1 text-[10px] font-bold text-on-surface-variant">
                      Payback {row.payback_months ? `${row.payback_months.toFixed(1)} months` : 'N/A'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {explanation.confidence_flags.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {explanation.confidence_flags.map(flag => (
                <div key={flag.label} className="rounded-xl bg-surface-container-low p-4 border border-outline-variant/10">
                  <div className="mb-2 flex items-center gap-2">
                    <CheckCircle2 size={15} className={flag.level === 'ok' ? 'text-secondary' : 'text-tertiary'} />
                    <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{flag.label}</p>
                  </div>
                  <p className="text-xs font-semibold leading-relaxed text-on-surface">{flag.message}</p>
                </div>
              ))}
            </div>
          )}

          <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border border-outline-variant/10">
            <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-tertiary-fixed text-tertiary">
                  <SlidersHorizontal size={19} />
                </div>
                <div>
                  <h3 className="text-lg font-bold">Optimization Assumptions</h3>
                  <p className="text-xs text-on-surface-variant">
                    Current results used {analysisAssumptions.planning_months} month{analysisAssumptions.planning_months === 1 ? '' : 's'}, RM {analysisAssumptions.md_rate_rm_per_kw.toFixed(2)}/kW MD, and RM {analysisAssumptions.solar_capex_rm_per_kwp.toFixed(0)}/kWp solar CAPEX.
                  </p>
                </div>
              </div>
              <button
                onClick={onApplyAssumptions}
                disabled={loading || !canApplyAssumptions}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-primary px-4 py-2 text-xs font-black uppercase tracking-widest text-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                {loading ? 'Applying' : 'Apply'}
              </button>
            </div>

            <div className="mb-5">
              <p className="mb-2 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Planning months</p>
              <div className="inline-grid grid-cols-3 rounded-lg bg-surface-container-low p-1">
                {[1, 2, 3].map(months => (
                  <button
                    key={months}
                    onClick={() => updateAssumption('planning_months', months)}
                    className={cn(
                      'rounded-md px-5 py-2 text-xs font-black transition-colors',
                      assumptions.planning_months === months ? 'bg-primary text-on-primary shadow-sm' : 'text-on-surface-variant hover:bg-surface-container-high'
                    )}
                  >
                    {months}M
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <AssumptionField label="MD rate" value={assumptions.md_rate_rm_per_kw} step={0.01} suffix="RM/kW" onChange={value => updateAssumption('md_rate_rm_per_kw', value)} />
              <AssumptionField label="Peak energy" value={assumptions.peak_energy_rate_rm_per_kwh} step={0.001} suffix="RM/kWh" onChange={value => updateAssumption('peak_energy_rate_rm_per_kwh', value)} />
              <AssumptionField label="Off-peak energy" value={assumptions.offpeak_energy_rate_rm_per_kwh} step={0.001} suffix="RM/kWh" onChange={value => updateAssumption('offpeak_energy_rate_rm_per_kwh', value)} />
              <AssumptionField label="Battery power" value={assumptions.battery_capex_rm_per_kw} step={50} suffix="RM/kW" onChange={value => updateAssumption('battery_capex_rm_per_kw', value)} />
              <AssumptionField label="Battery capacity" value={assumptions.battery_capex_rm_per_kwh} step={50} suffix="RM/kWh" onChange={value => updateAssumption('battery_capex_rm_per_kwh', value)} />
              <AssumptionField label="Solar CAPEX" value={assumptions.solar_capex_rm_per_kwp} step={50} suffix="RM/kWp" onChange={value => updateAssumption('solar_capex_rm_per_kwp', value)} />
              <AssumptionField label="Growth rate" value={assumptions.growth_rate_pct} step={0.1} suffix="%" onChange={value => updateAssumption('growth_rate_pct', value)} />
              <AssumptionField label="EV load" value={assumptions.ev_load_kw} step={1} suffix="kW" onChange={value => updateAssumption('ev_load_kw', value)} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
