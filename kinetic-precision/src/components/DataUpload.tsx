import { useRef } from 'react';
import { CheckCircle, Database, FileSpreadsheet, RefreshCw, SlidersHorizontal, UploadCloud } from 'lucide-react';
import { motion } from 'motion/react';
import { ErrorCard, LoadingProgress, type LoadingStepId } from './AnalysisState';
import type { AnalysisResult, BundledSite, PlanningAssumptions } from '../lib/api';
import { cn } from '../lib/utils';

interface DataUploadProps {
  sites: BundledSite[];
  analysis: AnalysisResult | null;
  assumptions: PlanningAssumptions;
  loading: boolean;
  loadingStep: LoadingStepId;
  error: string | null;
  onAssumptionsChange: (assumptions: PlanningAssumptions) => void;
  onAnalyzeBundled: (sourceFile: string) => void;
  onReanalyze: () => void;
  onUpload: (file: File) => void;
}

const previewColumns = ['interval_end', 'kw_import', 'kw_export', 'has_solar', 'source_sheet'];

function AssumptionField({
  label,
  value,
  step,
  placeholder,
  onChange,
}: {
  label: string;
  value: number | null;
  step?: number;
  placeholder?: string;
  onChange: (value: number | null) => void;
}) {
  const displayValue = Number.isFinite(value) ? value : '';
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{label}</span>
      <input
        type="number"
        min="0"
        step={step ?? 1}
        value={displayValue}
        placeholder={placeholder}
        onChange={event => {
          const raw = event.target.value;
          onChange(raw === '' ? null : Number(raw));
        }}
        className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-3 py-2 text-sm font-bold outline-none focus:border-primary focus:ring-2 focus:ring-primary/10"
      />
    </label>
  );
}

export function DataUpload({
  sites,
  analysis,
  assumptions,
  loading,
  loadingStep,
  error,
  onAssumptionsChange,
  onAnalyzeBundled,
  onReanalyze,
  onUpload,
}: DataUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const validation = analysis?.validation;
  const updateAssumption = (key: keyof PlanningAssumptions, value: number | null) => {
    onAssumptionsChange({ ...assumptions, [key]: value });
  };
  const existingSolarPlaceholder = analysis?.metadata.existing_pv_kwp != null
    ? `Detected: ${analysis.metadata.existing_pv_kwp.toFixed(0)} kWp`
    : 'Enter peak installed kWp';

  return (
    <div className="animate-in fade-in duration-500 space-y-8">
      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-12 lg:col-span-4 bg-surface-container-lowest rounded-xl p-6 shadow-sm border border-surface-container-high">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-primary-fixed flex items-center justify-center text-primary">
              <Database size={20} />
            </div>
            <div>
              <h3 className="text-lg font-black font-headline">Bundled Sites</h3>
              <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Competition workbooks</p>
            </div>
          </div>

          <div className="space-y-3">
            {sites.map(site => (
              <button
                key={site.source_file}
                onClick={() => onAnalyzeBundled(site.source_file)}
                disabled={loading}
                className={cn(
                  "w-full text-left rounded-lg border p-4 transition-all",
                  analysis?.metadata.source_file === site.source_file
                    ? "border-primary bg-primary/5"
                    : "border-outline-variant/20 bg-surface-container-low hover:border-primary/40"
                )}
              >
                <div className="flex justify-between gap-3">
                  <p className="text-sm font-black truncate">{site.site_id}</p>
                  <span className="text-[10px] font-bold text-primary">{site.has_solar ? 'Solar' : 'No solar'}</span>
                </div>
                <p className="text-[10px] text-on-surface-variant mt-1 truncate">{site.source_file}</p>
                <div className="grid grid-cols-2 gap-3 mt-3 text-[10px] font-bold text-on-surface-variant">
                  <span>{site.row_count.toLocaleString()} rows</span>
                  <span>{site.peak_kw_import.toFixed(0)} kW peak</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="col-span-12 lg:col-span-8 space-y-6">
          {loading && <LoadingProgress activeStep={loadingStep} />}

          <div className="bg-surface-container-lowest rounded-xl p-1 border-2 border-dashed border-outline-variant hover:border-primary transition-all">
            <div className="bg-surface-bright rounded-lg py-14 flex flex-col items-center justify-center text-center px-6">
              <motion.div
                whileHover={{ scale: 1.08, rotate: 4 }}
                className="w-16 h-16 bg-primary-fixed rounded-full flex items-center justify-center mb-4 text-primary"
              >
                <UploadCloud size={32} />
              </motion.div>
              <h3 className="text-xl font-black font-headline">Upload a site workbook</h3>
              <p className="text-sm text-on-surface-variant mt-1 mb-8 max-w-md mx-auto">
                Process a `.xlsx` load profile locally through the TREX ingestion, validation, forecasting, and optimization pipeline.
              </p>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={event => {
                  const file = event.target.files?.[0];
                  if (file) onUpload(file);
                }}
              />
              <button
                onClick={() => inputRef.current?.click()}
                disabled={loading}
                className="bg-on-surface text-surface px-10 py-3 rounded-full font-bold text-xs uppercase tracking-widest hover:bg-on-surface/90 transition-colors disabled:opacity-50"
              >
                {loading ? 'Analyzing...' : 'Select Workbook'}
              </button>
            </div>
          </div>

          {error && <ErrorCard title="Workbook analysis failed" message={error} />}

          <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
            <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-tertiary-fixed text-tertiary">
                  <SlidersHorizontal size={19} />
                </div>
                <div>
                  <h3 className="text-lg font-black font-headline">Planning Assumptions</h3>
                  <p className="text-xs font-medium text-on-surface-variant">Visible inputs for savings and payback credibility.</p>
                </div>
              </div>
              <button
                onClick={onReanalyze}
                disabled={loading || !analysis}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-primary px-4 py-2 text-xs font-black uppercase tracking-widest text-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <RefreshCw size={14} />
                Apply
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
              <AssumptionField label="MD rate RM/kW" value={assumptions.md_rate_rm_per_kw} step={0.01} onChange={value => updateAssumption('md_rate_rm_per_kw', value)} />
              <AssumptionField label="Peak energy RM/kWh" value={assumptions.peak_energy_rate_rm_per_kwh} step={0.001} onChange={value => updateAssumption('peak_energy_rate_rm_per_kwh', value)} />
              <AssumptionField label="Off-peak energy RM/kWh" value={assumptions.offpeak_energy_rate_rm_per_kwh} step={0.001} onChange={value => updateAssumption('offpeak_energy_rate_rm_per_kwh', value)} />
              <AssumptionField
                label="Existing solar kWp"
                value={assumptions.existing_pv_kwp}
                step={1}
                placeholder={existingSolarPlaceholder}
                onChange={value => updateAssumption('existing_pv_kwp', value)}
              />
              <AssumptionField label="Battery RM/kW" value={assumptions.battery_capex_rm_per_kw} step={50} onChange={value => updateAssumption('battery_capex_rm_per_kw', value)} />
              <AssumptionField label="Battery RM/kWh" value={assumptions.battery_capex_rm_per_kwh} step={50} onChange={value => updateAssumption('battery_capex_rm_per_kwh', value)} />
              <AssumptionField label="Solar RM/kWp" value={assumptions.solar_capex_rm_per_kwp} step={50} onChange={value => updateAssumption('solar_capex_rm_per_kwp', value)} />
            </div>
          </section>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {[
              ['Rows parsed', validation?.row_count ?? 0],
              ['Gaps', validation?.gap_count ?? 0],
              ['Duplicates', validation?.duplicate_count ?? 0],
              ['Missing values', validation?.missing_value_count ?? 0],
            ].map(([label, value]) => (
              <div key={label} className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/10">
                <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">{label}</p>
                <p className="text-2xl font-black font-headline">{Number(value).toLocaleString()}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="bg-surface-container-lowest rounded-xl shadow-lg border border-outline-variant/10 overflow-hidden">
        <div className="p-6 border-b border-outline-variant/10 flex justify-between items-center bg-surface-bright">
          <div>
            <h3 className="text-lg font-black font-headline">Normalized Preview</h3>
            <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">
              {analysis?.metadata.source_file ?? 'No workbook analyzed yet'}
            </p>
          </div>
          {analysis && (
            <div className="inline-flex items-center gap-2 text-secondary text-xs font-black">
              <CheckCircle size={16} />
              Canonical kW schema
            </div>
          )}
        </div>
        <div className="overflow-x-auto no-scrollbar">
          <table className="w-full text-left border-collapse">
            <thead className="bg-surface-container-low border-b border-outline-variant/10">
              <tr>
                {previewColumns.map(column => (
                  <th key={column} className="px-6 py-4 text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5">
              {(analysis?.normalized_preview ?? []).slice(0, 8).map((row, index) => (
                <tr key={index} className="hover:bg-surface-container-low/50">
                  {previewColumns.map(column => (
                    <td key={column} className="px-6 py-4 text-xs font-semibold">
                      {String(row[column] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
              {!analysis && (
                <tr>
                  <td colSpan={previewColumns.length} className="px-6 py-10 text-center text-sm text-on-surface-variant">
                    Choose a bundled workbook or upload an `.xlsx` file to start.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="p-4 bg-surface-container-low border-t border-outline-variant/10 flex items-center justify-center gap-2 text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">
          <FileSpreadsheet size={14} />
        </div>
      </section>
    </div>
  );
}
