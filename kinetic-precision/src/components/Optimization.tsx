import { useState } from 'react';
import { BrainCircuit, CheckCircle2, Gauge, RefreshCw, ShieldCheck, SlidersHorizontal, TrendingDown, WalletCards } from 'lucide-react';
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

const PV_MODULE_NAME = 'Trina Vertex N 590-620W';
const INVERTER_NAME = 'Sigen Hybrid Inverter Gen 2';
const PV_MODULE_WP = 620;
const PV_MODULE_AREA_SQM = 2.382 * 1.134;
const PV_MODULE_WEIGHT_KG = 33;
const MAX_PV_KWP_PER_INVERTER = 24;

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

function formatKw(value: number) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })} kW`;
}

function formatPayback(months: number | null) {
  return months != null ? `${months.toFixed(1)} months` : 'No CAPEX';
}

function annualSavings(scenario: AnalysisResult['optimization']['best_scenario']) {
  return Number(scenario.annual_savings_rm ?? scenario.savings_rm);
}

function scenarioCapex(scenario: AnalysisResult['optimization']['best_scenario']) {
  return Number(scenario.capex_rm ?? 0);
}

function scenarioSystem(scenario: AnalysisResult['optimization']['best_scenario']) {
  if (scenario.battery_kw <= 0 && scenario.battery_kwh <= 0 && scenario.solar_kwp <= 0) {
    return 'Operational load shifting only';
  }
  const parts = [
    `${scenario.battery_kw.toFixed(0)} kW battery`,
    `${scenario.battery_kwh.toFixed(0)} kWh storage`,
    `${scenario.solar_kwp.toFixed(0)} kWp ${PV_MODULE_NAME} PV`,
  ].filter(part => !part.startsWith('0 '));
  return parts.join(' / ');
}

function pvFeasibility(solarKwp: number) {
  if (solarKwp <= 0) return null;
  const modules = Math.ceil((solarKwp * 1000) / PV_MODULE_WP);
  const areaSqm = modules * PV_MODULE_AREA_SQM;
  const weightTonnes = (modules * PV_MODULE_WEIGHT_KG) / 1000;
  const inverters = Math.ceil(solarKwp / MAX_PV_KWP_PER_INVERTER);
  return { modules, areaSqm, weightTonnes, inverters };
}

function uniqueScenarioHighlights(analysis: AnalysisResult) {
  const scenarios = analysis.optimization.scenarios.length > 0
    ? analysis.optimization.scenarios
    : [analysis.optimization.best_scenario];
  const positivePayback = scenarios.filter(row => row.payback_months != null && annualSavings(row) > 0);
  const positiveSavings = scenarios.filter(row => annualSavings(row) > 0);
  const candidates = [
    {
      role: 'Recommended',
      scenario: analysis.optimization.best_scenario,
    },
    {
      role: 'Fastest payback',
      scenario: [...positivePayback].sort((a, b) => Number(a.payback_months) - Number(b.payback_months))[0],
    },
    {
      role: 'Maximum peak cut',
      scenario: [...scenarios].sort((a, b) => b.peak_reduction_pct - a.peak_reduction_pct)[0],
    },
    {
      role: 'Lowest investment',
      scenario: [...positiveSavings].sort((a, b) => scenarioCapex(a) - scenarioCapex(b) || annualSavings(b) - annualSavings(a))[0],
    },
  ];
  const seen = new Set<string>();
  return candidates.filter(candidate => {
    if (!candidate.scenario || seen.has(candidate.scenario.scenario_id)) return false;
    seen.add(candidate.scenario.scenario_id);
    return true;
  });
}

export function buildRecommendationEvidence(explainability?: AnalysisResult['optimization']['explainability']) {
  return explainability?.drivers ?? [];
}

type ScenarioDecisionEvidenceItem = {
  label: string;
  detail: string;
};

export function buildScenarioDecisionEvidence(analysis: AnalysisResult): {
  summary: string;
  items: ScenarioDecisionEvidenceItem[];
  sensitivity: string[];
} {
  const best = analysis.optimization.best_scenario;
  const scenarios = (analysis.optimization.scenarios.length > 0
    ? analysis.optimization.scenarios
    : [best]
  ).filter(scenario => scenario.scenario_id !== best.scenario_id);
  const testedCount = analysis.optimization.scenarios.length || 1;
  const bestSavings = annualSavings(best);
  const bestCapex = scenarioCapex(best);

  const cheaperOption = scenarios
    .filter(scenario => scenarioCapex(scenario) < bestCapex && annualSavings(scenario) > 0)
    .sort((a, b) => annualSavings(b) - annualSavings(a))[0];
  const largerOption = scenarios
    .filter(scenario => scenarioCapex(scenario) > bestCapex)
    .sort((a, b) => scenarioCapex(a) - scenarioCapex(b))[0];
  const highestDispatchPoint = [...analysis.optimization.schedule_preview]
    .sort((a, b) => Number(b.baseline_kw_import) - Number(a.baseline_kw_import))[0];

  const items: ScenarioDecisionEvidenceItem[] = [
    {
      label: 'Ranking logic',
      detail: `The model compared ${testedCount} tested combinations and picked the option where added annual value still justified the hardware cost under the active tariff and CAPEX assumptions.`,
    },
  ];

  if (cheaperOption) {
    const savingsGap = bestSavings - annualSavings(cheaperOption);
    const capexPremium = bestCapex - scenarioCapex(cheaperOption);
    const demandExposureGap = cheaperOption.md_after - best.md_after;
    const demandText = demandExposureGap > 0
      ? ` and left ${formatKw(demandExposureGap)} more peak-demand exposure`
      : '';
    items.push({
      label: 'Cheaper options',
      detail: savingsGap > 0
        ? `The strongest lower-investment option saved ${formatRm(savingsGap)}/yr less${demandText}. The selected option costs ${formatRm(capexPremium)} more because that extra spend still buys stronger recurring value.`
        : `A lower-investment option was available, but it did not improve the selected option's annual value under the current assumptions.`,
    });
  }

  if (largerOption) {
    const extraCapex = scenarioCapex(largerOption) - bestCapex;
    const extraSavings = annualSavings(largerOption) - bestSavings;
    const extraPeakProtection = best.md_after - largerOption.md_after;
    const peakText = extraPeakProtection > 0 ? ` and ${formatKw(extraPeakProtection)} more peak protection` : '';
    items.push({
      label: 'Larger options',
      detail: extraSavings > 0
        ? `The nearest larger option costs ${formatRm(extraCapex)} more but adds only ${formatRm(extraSavings)}/yr${peakText}. That weaker incremental return is why it loses on payback efficiency.`
        : `The nearest larger option costs ${formatRm(extraCapex)} more without improving annual savings, so the extra hardware is not justified by the model output.`,
    });
  }

  if (highestDispatchPoint) {
    const batteryDischarge = Number(highestDispatchPoint.battery_discharge_kw ?? 0);
    const solarOffset = Number(highestDispatchPoint.solar_offset_kw ?? 0);
    const dispatchParts = [
      batteryDischarge > 0 ? `${formatKw(batteryDischarge)} controllable battery discharge` : null,
      solarOffset > 0 ? `${formatKw(solarOffset)} PV offset` : null,
    ].filter(Boolean);
    if (dispatchParts.length > 0) {
      items.push({
        label: 'Dispatch proof',
        detail: `At the highest modeled dispatch sample, the optimizer uses ${dispatchParts.join(' plus ')}. This is the operational reason it combines dispatchable storage with PV instead of relying on PV timing alone.`,
      });
    }
  }

  const changedAssumptions = analysis.optimization.sensitivity
    .map(row => row.changed_assumption)
    .filter((assumption, index, rows) => assumption !== 'base' && rows.indexOf(assumption) === index)
    .map(assumption => ({
      md_rate_rm_per_kw: 'MD tariff',
      battery_capex: 'battery CAPEX',
      solar_capex_rm_per_kwp: 'solar CAPEX',
    }[assumption] ?? assumption.replaceAll('_', ' ')));
  const sensitivity = changedAssumptions.length > 0
    ? [`Re-check ${changedAssumptions.slice(0, 3).join(', ')} before procurement; these inputs can change which scenario ranks first.`]
    : ['Re-check MD tariff, battery CAPEX, solar CAPEX, and peak timing before procurement; these are the assumptions most likely to change the ranking.'];

  return {
    summary: `${testedCount} tested scenario${testedCount === 1 ? '' : 's'} were ranked by recurring savings, demand-charge exposure, investment, and payback efficiency.`,
    items,
    sensitivity,
  };
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

function ScenarioRow({
  role,
  scenario,
  selected,
}: {
  key?: string;
  role: string;
  scenario: AnalysisResult['optimization']['best_scenario'];
  selected: boolean;
}) {
  const description = {
    Recommended: 'Best balance from the optimizer.',
    'Fastest payback': 'Gets investment back soonest.',
    'Maximum peak cut': 'Most aggressive peak shaving.',
    'Lowest investment': scenarioCapex(scenario) === 0 ? 'No-hardware operational option.' : 'Cheapest option that still saves.',
  }[role] ?? 'Alternative tested by the optimizer.';

  return (
    <tr className={selected ? 'bg-primary-fixed/55' : 'bg-surface-container-low'}>
      <td className="rounded-l-lg px-4 py-3">
        <p className="text-xs font-black text-on-surface">{role}</p>
        <p className="mt-0.5 text-[10px] font-bold text-on-surface-variant">{description}</p>
        <p className="mt-1 text-[10px] font-bold text-on-surface-variant">{scenarioSystem(scenario)}</p>
      </td>
      <td className="px-4 py-3 text-right text-sm font-black text-on-surface">{formatRm(annualSavings(scenario))}<span className="text-[10px] text-on-surface-variant">/year</span></td>
      <td className="px-4 py-3 text-right text-sm font-black text-on-surface">{formatPayback(scenario.payback_months)}</td>
      <td className="px-4 py-3 text-right text-sm font-black text-on-surface">{scenario.md_after.toFixed(0)} kW</td>
      <td className="rounded-r-lg px-4 py-3 text-right text-sm font-black text-on-surface">{formatRm(scenarioCapex(scenario))}</td>
    </tr>
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
  const [showAssumptions, setShowAssumptions] = useState(false);

  if (!analysis) {
    if (loading) return <LoadingProgress activeStep={loadingStep} />;
    if (error) return <ErrorCard title="Optimization unavailable" message={error} />;
    return <EmptyAnalysis title="No optimization results yet" description="Analyze a workbook to compare cost reduction, peak-demand reduction, payback, battery sizing, and solar sizing." />;
  }

  const best = analysis.optimization.best_scenario;
  const data = scheduleData(analysis);
  const analysisAssumptions = analysis.assumptions;
  const explanation = analysis.optimization.explanation;
  const decisionEvidence = buildScenarioDecisionEvidence(analysis);
  const mdReductionKw = best.md_before - best.md_after;
  const planningLabel = explanation.planning_basis_label || planningBasisLabel(best.risk_basis);
  const periodMonths = Number(best.savings_period_months ?? analysisAssumptions.planning_months ?? 1);
  const scenarioHighlights = uniqueScenarioHighlights(analysis);
  const pvPlan = pvFeasibility(best.solar_kwp);
  const updateAssumption = (key: keyof PlanningAssumptions, value: number) => {
    onAssumptionsChange({ ...assumptions, [key]: value });
  };

  return (
    <div className="animate-in fade-in space-y-8 duration-500">
      <section className="grid grid-cols-12 gap-6">
        <div className="col-span-12 rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm lg:col-span-5">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-primary">Recommended plan</p>
              <h2 className="mt-2 font-headline text-3xl font-black tracking-tight text-on-surface">
                {scenarioSystem(best)}
              </h2>
            </div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-fixed text-primary">
              <ShieldCheck size={24} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-lg bg-surface-container-low p-3">
              <p className="text-[9px] font-black uppercase tracking-widest text-on-surface-variant">Save</p>
              <p className="mt-1 text-base font-black text-on-surface">{formatRm(annualSavings(best))}/yr</p>
            </div>
            <div className="rounded-lg bg-surface-container-low p-3">
              <p className="text-[9px] font-black uppercase tracking-widest text-on-surface-variant">Cut MD</p>
              <p className="mt-1 text-base font-black text-on-surface">{mdReductionKw.toFixed(0)} kW</p>
            </div>
            <div className="rounded-lg bg-surface-container-low p-3">
              <p className="text-[9px] font-black uppercase tracking-widest text-on-surface-variant">Payback</p>
              <p className="mt-1 text-base font-black text-on-surface">{formatPayback(best.payback_months)}</p>
            </div>
          </div>

          <div className="mt-5 flex flex-col gap-3 border-t border-outline-variant/10 pt-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Assumptions used</p>
              <p className="mt-1 text-xs font-semibold text-on-surface-variant">
                {analysisAssumptions.planning_months} month{analysisAssumptions.planning_months === 1 ? '' : 's'} / RM {analysisAssumptions.md_rate_rm_per_kw.toFixed(2)}/kW MD / RM {analysisAssumptions.solar_capex_rm_per_kwp.toFixed(0)}/kWp solar
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowAssumptions(current => !current)}
              aria-expanded={showAssumptions}
              className="inline-flex items-center justify-center gap-2 rounded-full border border-primary/15 bg-primary-fixed px-4 py-2 text-xs font-black uppercase tracking-widest text-primary transition-colors hover:bg-primary-fixed-dim"
            >
              <SlidersHorizontal size={14} />
              {showAssumptions ? 'Hide inputs' : 'Edit inputs'}
            </button>
          </div>
        </div>

        <div className="col-span-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-7">
          <MetricCard
            highlight
            label="Annualized savings"
            value={formatRm(annualSavings(best))}
            detail={`${formatRm(best.savings_rm)} over the active ${periodMonths}M plan.`}
            icon={WalletCards}
          />
          <MetricCard
            label="Maximum demand"
            value={`${best.md_after.toFixed(0)} kW`}
            detail={`${best.peak_reduction_pct.toFixed(1)}% below baseline.`}
            icon={Gauge}
          />
          <MetricCard
            label="Payback"
            value={formatPayback(best.payback_months)}
            detail={`${formatRm(scenarioCapex(best))} CAPEX, ${formatRm(best.monthly_savings_rm)}/month savings.`}
            icon={TrendingDown}
          />
          <MetricCard
            label="Planning basis"
            value={planningLabel}
            detail="Uses conservative demand for peak-charge protection."
            icon={ShieldCheck}
          />
        </div>
      </section>

      <div
        className={cn(
          'overflow-hidden transition-[max-height,opacity,transform,margin] duration-300 ease-out',
          showAssumptions ? 'max-h-[720px] opacity-100 translate-y-0' : 'max-h-0 -translate-y-2 opacity-0 -mt-8 pointer-events-none'
        )}
        aria-hidden={!showAssumptions}
      >
        <section className="rounded-xl border border-primary-fixed/60 bg-surface-container-lowest p-6 shadow-sm transition-shadow duration-300">
          <div className="transition-opacity delay-75 duration-200">
            <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-tertiary-fixed text-tertiary">
                  <SlidersHorizontal size={19} />
                </div>
                <div>
                  <h3 className="font-headline text-xl font-black text-on-surface">Decision Assumptions</h3>
                  <p className="text-xs font-medium text-on-surface-variant">
                    Adjust the planning inputs, then rerun this same analysis with the updated assumptions.
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
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
        <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="font-headline text-xl font-black text-on-surface">Options Considered</h3>
            <p className="mt-1 text-sm font-medium text-on-surface-variant">
              The optimizer tested combinations of battery power, storage size, and solar capacity, then kept the most useful choices.
            </p>
          </div>
          <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
            {analysis.optimization.scenarios.length} battery/storage/solar combinations tested
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-separate border-spacing-y-2">
            <thead>
              <tr className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
                <th className="px-4 pb-1 text-left">Option</th>
                <th className="px-4 pb-1 text-right">Saves</th>
                <th className="px-4 pb-1 text-right">Payback</th>
                <th className="px-4 pb-1 text-right">New peak</th>
                <th className="px-4 pb-1 text-right">Investment</th>
              </tr>
            </thead>
            <tbody>
              {scenarioHighlights.map(highlight => (
                <ScenarioRow
                  key={`${highlight.role}-${highlight.scenario.scenario_id}`}
                  role={highlight.role}
                  scenario={highlight.scenario}
                  selected={highlight.scenario.scenario_id === best.scenario_id}
                />
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-5 rounded-lg border border-primary/10 bg-primary-fixed/30 px-5 py-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-3 lg:max-w-sm">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-container-lowest text-primary">
                <BrainCircuit size={18} />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest text-primary">Explainable AI</p>
                <p className="mt-1 text-sm font-black leading-snug text-on-surface">Why the model chose this scenario</p>
                <p className="mt-1 text-xs font-semibold leading-relaxed text-on-surface-variant">{decisionEvidence.summary}</p>
              </div>
            </div>

            <div className="grid flex-1 grid-cols-1 gap-3 xl:grid-cols-3">
              {decisionEvidence.items.map(item => (
                <div key={item.label} className="rounded-lg bg-surface-container-lowest/80 px-4 py-3">
                  <p className="text-[10px] font-black uppercase tracking-widest text-primary">{item.label}</p>
                  <p className="mt-1 text-xs font-semibold leading-relaxed text-on-surface">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 rounded-lg border border-outline-variant/10 bg-surface-container-lowest/80 px-4 py-3">
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">What can change the answer</p>
            {decisionEvidence.sensitivity.map(item => (
              <p key={item} className="mt-1 text-xs font-semibold leading-relaxed text-on-surface-variant">{item}</p>
            ))}
          </div>
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
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Data checks</p>
            <div className="mt-4 space-y-2">
              {explanation.confidence_flags.length > 0 ? explanation.confidence_flags.map(flag => (
                <div key={flag.label} className="flex items-center justify-between gap-3 rounded-lg bg-surface-container-low px-3 py-2" title={flag.message}>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={16} className={flag.level === 'ok' ? 'shrink-0 text-secondary' : 'shrink-0 text-tertiary'} />
                    <p className="text-xs font-black uppercase tracking-widest text-on-surface">{flag.label}</p>
                  </div>
                  <span className={cn(
                    'rounded-full px-2 py-1 text-[9px] font-black uppercase tracking-widest',
                    flag.level === 'ok' ? 'bg-secondary-container text-secondary' : 'bg-tertiary-fixed text-tertiary'
                  )}>{flag.level === 'ok' ? 'OK' : 'Review'}</span>
                </div>
              )) : (
                <p className="text-sm font-medium text-on-surface-variant">No confidence flags returned for this analysis.</p>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-5 shadow-sm">
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Assumptions</p>
            <p className="mt-3 text-sm font-black text-on-surface">Editable inputs are above</p>
            <p className="mt-1 text-xs font-semibold leading-relaxed text-on-surface-variant">Change tariff, CAPEX, load growth, or EV load, then rerun the plan.</p>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
        <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="font-headline text-xl font-black text-on-surface">Decision Checklist</h3>
            <p className="mt-1 text-sm font-medium text-on-surface-variant">Use this before presenting or approving the recommendation.</p>
          </div>
          <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Before final sign-off</p>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="rounded-lg bg-surface-container-low p-5">
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary-fixed text-primary">
              <ShieldCheck size={19} />
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Data ready</p>
            <p className="mt-2 font-headline text-xl font-black text-on-surface">
              {analysis.validation.gap_count === 0 && analysis.validation.missing_value_count === 0 ? 'Clean enough' : 'Review first'}
            </p>
            <p className="mt-1 text-sm font-semibold text-on-surface-variant">
              Check interval gaps and missing values before using this as final evidence.
            </p>
          </div>
          <div className="rounded-lg bg-surface-container-low p-5">
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary-fixed text-primary">
              <SlidersHorizontal size={19} />
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Inputs locked</p>
            <p className="mt-2 font-headline text-xl font-black text-on-surface">{periodMonths}M planning basis</p>
            <p className="mt-1 text-sm font-semibold text-on-surface-variant">
              Confirm tariff, investment, growth, and EV assumptions with the editable inputs above.
            </p>
          </div>
          <div className="rounded-lg bg-surface-container-low p-5">
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary-fixed text-primary">
              <WalletCards size={19} />
            </div>
            <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">PV feasibility</p>
            <p className="mt-2 font-headline text-xl font-black text-on-surface">
              {pvPlan ? `${pvPlan.modules} modules / ${pvPlan.inverters} inverters` : 'No new PV selected'}
            </p>
            <p className="mt-1 text-sm font-semibold text-on-surface-variant">
              {pvPlan
                ? `Allow for about ${pvPlan.areaSqm.toFixed(0)} square meters of PV module area and ${pvPlan.weightTonnes.toFixed(1)} tonnes of module weight, based on ${PV_MODULE_NAME} and ${INVERTER_NAME} specifications.`
                : `No ${PV_MODULE_NAME} layout check is needed for this selected option.`}
            </p>
          </div>
        </div>
      </section>

    </div>
  );
}
