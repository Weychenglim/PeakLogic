import { Battery, CheckCircle2, Gauge, RefreshCw, ShieldCheck, SlidersHorizontal, Sun, TrendingDown, WalletCards, Zap } from 'lucide-react';
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

function formatRm(value: number) {
  return `RM ${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPayback(months: number | null) {
  return months ? `${months.toFixed(1)} months` : 'No CAPEX';
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

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  highlight = false,
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof TrendingDown;
  highlight?: boolean;
}) {
  return (
    <div className={cn(
      'rounded-xl border p-5 shadow-sm',
      highlight ? 'border-primary-fixed/60 bg-primary text-on-primary shadow-primary/15' : 'border-outline-variant/10 bg-surface-container-lowest'
    )}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className={cn('text-[10px] font-black uppercase tracking-widest', highlight ? 'text-primary-fixed' : 'text-on-surface-variant')}>{label}</p>
        <Icon size={18} className={highlight ? 'text-primary-fixed' : 'text-primary'} />
      </div>
      <p className="font-headline text-3xl font-black leading-none tracking-tight">{value}</p>
      <p className={cn('mt-3 text-xs font-semibold leading-relaxed', highlight ? 'text-primary-fixed/90' : 'text-on-surface-variant')}>{detail}</p>
    </div>
  );
}

function SystemPill({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Battery }) {
  return (
    <div className="rounded-lg bg-surface-container-low px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-primary">
        <Icon size={15} />
        <span className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{label}</span>
      </div>
      <p className="text-lg font-black text-on-surface">{value}</p>
    </div>
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
    return <EmptyAnalysis title="No optimization results yet" description="Analyze a workbook to compare cost reduction, peak-demand reduction, payback, battery sizing, and solar sizing." />;
  }

  const best = analysis.optimization.best_scenario;
  const data = scheduleData(analysis);
  const analysisAssumptions = analysis.assumptions;
  const explanation = analysis.optimization.explanation;
  const sensitivityRows = analysis.optimization.sensitivity ?? [];
  const mdReductionKw = best.md_before - best.md_after;
  const planningLabel = explanation.planning_basis_label || planningBasisLabel(best.risk_basis);
  const updateAssumption = (key: keyof PlanningAssumptions, value: number) => {
    onAssumptionsChange({ ...assumptions, [key]: value });
  };

  return (
    <div className="animate-in fade-in space-y-8 duration-500">
      <section className="grid grid-cols-12 gap-6">
        <div className="col-span-12 rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm lg:col-span-5">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-primary">Recommended optimization plan</p>
              <h2 className="mt-2 font-headline text-3xl font-black tracking-tight text-on-surface">
                Reduce MD by {mdReductionKw.toFixed(0)} kW and save {formatRm(best.savings_rm)}
              </h2>
            </div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-fixed text-primary">
              <ShieldCheck size={24} />
            </div>
          </div>

          <p className="text-sm font-medium leading-relaxed text-on-surface-variant">{explanation.what_changed}</p>

          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <SystemPill label="Battery power" value={`${best.battery_kw.toFixed(0)} kW`} icon={Battery} />
            <SystemPill label="Storage size" value={`${best.battery_kwh.toFixed(0)} kWh`} icon={Zap} />
            <SystemPill label="New solar" value={`${best.solar_kwp.toFixed(0)} kWp`} icon={Sun} />
          </div>

          <div className="mt-6 rounded-lg bg-secondary-container/45 px-4 py-3">
            <p className="text-[10px] font-black uppercase tracking-widest text-on-secondary-fixed/70">Why this scenario</p>
            <p className="mt-2 text-sm font-semibold leading-relaxed text-on-secondary-fixed">{explanation.why_this_scenario}</p>
          </div>
        </div>

        <div className="col-span-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-7">
          <MetricCard
            highlight
            label="Annual savings"
            value={formatRm(best.savings_rm)}
            detail={`Optimized bill ${formatRm(best.bill_after_rm)} from ${formatRm(best.bill_before_rm)} baseline.`}
            icon={WalletCards}
          />
          <MetricCard
            label="Maximum demand"
            value={`${best.md_after.toFixed(0)} kW`}
            detail={`Down from ${best.md_before.toFixed(0)} kW, a ${best.peak_reduction_pct.toFixed(1)}% peak reduction.`}
            icon={Gauge}
          />
          <MetricCard
            label="Payback"
            value={formatPayback(best.payback_months)}
            detail="Estimated from battery, storage, and solar CAPEX assumptions."
            icon={TrendingDown}
          />
          <MetricCard
            label="Planning basis"
            value={planningLabel}
            detail={explanation.planning_basis_description}
            icon={ShieldCheck}
          />
        </div>
      </section>

      <section className="grid grid-cols-12 gap-6">
        <div className="col-span-12 rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm lg:col-span-8">
          <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="font-headline text-xl font-black text-on-surface">Load Shape After Optimization</h3>
              <p className="mt-1 text-sm font-medium text-on-surface-variant">Baseline demand compared with the selected optimized profile.</p>
            </div>
            <div className="flex items-center gap-4 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
              <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-outline-variant" /> Baseline</span>
              <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-primary" /> Optimized</span>
            </div>
          </div>

          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#c2c6d4" strokeOpacity={0.12} />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#424752', fontWeight: 600 }} />
                <YAxis hide />
                <Tooltip cursor={{ fill: '#f3f3f7' }} contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 16px 30px rgb(0 0 0 / 0.08)' }} />
                <Bar dataKey="baseline" fill="#c2c6d4" opacity={0.45} radius={[4, 4, 0, 0]} name="Baseline kW" />
                <Bar dataKey="optimized" fill="#00488d" radius={[4, 4, 0, 0]} name="Optimized kW" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="col-span-12 space-y-4 lg:col-span-4">
          <div className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-5 shadow-sm">
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Decision confidence</p>
            <div className="mt-4 space-y-3">
              {explanation.confidence_flags.length > 0 ? explanation.confidence_flags.map(flag => (
                <div key={flag.label} className="flex gap-3 rounded-lg bg-surface-container-low p-3">
                  <CheckCircle2 size={16} className={flag.level === 'ok' ? 'mt-0.5 shrink-0 text-secondary' : 'mt-0.5 shrink-0 text-tertiary'} />
                  <div>
                    <p className="text-xs font-black uppercase tracking-widest text-on-surface">{flag.label}</p>
                    <p className="mt-1 text-xs font-semibold leading-relaxed text-on-surface-variant">{flag.message}</p>
                  </div>
                </div>
              )) : (
                <p className="text-sm font-medium text-on-surface-variant">No confidence flags returned for this analysis.</p>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-5 shadow-sm">
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Savings sensitivity</p>
            <p className="mt-3 text-sm font-semibold leading-relaxed text-on-surface">{explanation.savings_sensitivity}</p>
          </div>
        </div>
      </section>

      {sensitivityRows.length > 0 && (
        <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="font-headline text-xl font-black text-on-surface">Sensitivity Check</h3>
              <p className="mt-1 text-sm font-medium text-on-surface-variant">Active-analysis +/-10% checks for tariff and CAPEX assumptions.</p>
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{analysis.optimization.scenarios.length} scenarios tested</p>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {sensitivityRows.map(row => (
              <div key={row.sensitivity_id} className="rounded-lg bg-surface-container-low p-4">
                <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{row.label}</p>
                <p className="mt-2 text-xl font-black text-on-surface">{formatRm(row.savings_rm)}</p>
                <p className="mt-1 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Payback {formatPayback(row.payback_months)}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-tertiary-fixed text-tertiary">
              <SlidersHorizontal size={19} />
            </div>
            <div>
              <h3 className="font-headline text-xl font-black text-on-surface">Decision Assumptions</h3>
              <p className="text-xs font-medium text-on-surface-variant">
                Current result uses {analysisAssumptions.planning_months} month{analysisAssumptions.planning_months === 1 ? '' : 's'}, RM {analysisAssumptions.md_rate_rm_per_kw.toFixed(2)}/kW MD, and RM {analysisAssumptions.solar_capex_rm_per_kwp.toFixed(0)}/kWp solar CAPEX.
              </p>
            </div>
          </div>
          <button
            onClick={onApplyAssumptions}
            disabled={loading || !canApplyAssumptions}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-primary px-4 py-2 text-xs font-black uppercase tracking-widest text-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {loading ? 'Applying' : 'Apply changes'}
          </button>
        </div>

        <div className="mb-5">
          <p className="mb-2 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Planning horizon</p>
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-4">
          <AssumptionField label="MD rate" value={assumptions.md_rate_rm_per_kw} step={0.01} suffix="RM/kW" onChange={value => updateAssumption('md_rate_rm_per_kw', value)} />
          <AssumptionField label="Peak energy" value={assumptions.peak_energy_rate_rm_per_kwh} step={0.001} suffix="RM/kWh" onChange={value => updateAssumption('peak_energy_rate_rm_per_kwh', value)} />
          <AssumptionField label="Off-peak energy" value={assumptions.offpeak_energy_rate_rm_per_kwh} step={0.001} suffix="RM/kWh" onChange={value => updateAssumption('offpeak_energy_rate_rm_per_kwh', value)} />
          <AssumptionField label="Battery power CAPEX" value={assumptions.battery_capex_rm_per_kw} step={50} suffix="RM/kW" onChange={value => updateAssumption('battery_capex_rm_per_kw', value)} />
          <AssumptionField label="Battery energy CAPEX" value={assumptions.battery_capex_rm_per_kwh} step={50} suffix="RM/kWh" onChange={value => updateAssumption('battery_capex_rm_per_kwh', value)} />
          <AssumptionField label="Solar CAPEX" value={assumptions.solar_capex_rm_per_kwp} step={50} suffix="RM/kWp" onChange={value => updateAssumption('solar_capex_rm_per_kwp', value)} />
          <AssumptionField label="Growth rate" value={assumptions.growth_rate_pct} step={0.1} suffix="%" onChange={value => updateAssumption('growth_rate_pct', value)} />
          <AssumptionField label="EV load" value={assumptions.ev_load_kw} step={1} suffix="kW" onChange={value => updateAssumption('ev_load_kw', value)} />
        </div>
      </section>
    </div>
  );
}
