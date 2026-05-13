import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, RadioTower } from 'lucide-react';
import { cn } from '../lib/utils';

export type LoadingStepId = 'upload' | 'normalize' | 'forecast' | 'optimize';

const STEPS: Array<{ id: LoadingStepId; label: string }> = [
  { id: 'upload', label: 'Upload' },
  { id: 'normalize', label: 'Normalize' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'optimize', label: 'Optimize' },
];

export function LoadingProgress({ activeStep }: { activeStep: LoadingStepId }) {
  const activeIndex = Math.max(0, STEPS.findIndex(step => step.id === activeStep));

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-3">
        <Loader2 size={18} className="animate-spin text-primary" />
        <div>
          <p className="text-sm font-black text-on-surface">Analysis running</p>
          <p className="text-xs font-medium text-on-surface-variant">Processing workbook through the local FastAPI pipeline.</p>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2">
        {STEPS.map((step, index) => {
          const done = index < activeIndex;
          const current = index === activeIndex;
          return (
            <div
              key={step.id}
              className={cn(
                'rounded-lg border px-3 py-3 text-center text-[10px] font-black uppercase tracking-widest',
                done && 'border-secondary bg-secondary-container/40 text-secondary',
                current && 'border-primary bg-primary-fixed text-primary',
                !done && !current && 'border-outline-variant/20 bg-surface-container-low text-on-surface-variant'
              )}
            >
              {done ? <CheckCircle2 size={14} className="mx-auto mb-1" /> : <div className="mx-auto mb-1 h-3.5" />}
              {step.label}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function EmptyAnalysis({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-xl border border-dashed border-outline-variant/40 bg-surface-container-low p-8 text-sm text-on-surface-variant">
      <FileSpreadsheet size={24} className="mb-4 text-primary" />
      <p className="font-black text-on-surface">{title}</p>
      <p className="mt-1 max-w-xl leading-relaxed">{description}</p>
    </div>
  );
}

export function ErrorCard({ title, message }: { title: string; message: string }) {
  return (
    <div className="rounded-xl border border-error/20 bg-error-container p-5 text-error shadow-sm">
      <div className="flex gap-3">
        <AlertTriangle size={20} className="mt-0.5 shrink-0" />
        <div>
          <p className="font-black">{title}</p>
          <p className="mt-1 text-sm font-semibold leading-relaxed">{message}</p>
        </div>
      </div>
    </div>
  );
}

export function ApiUnavailableBanner({ message }: { message: string }) {
  return (
    <div className="mx-8 mt-4 rounded-xl border border-error/20 bg-error-container px-5 py-3 text-error shadow-sm">
      <div className="flex items-center gap-3 text-sm font-bold">
        <RadioTower size={18} />
        API unavailable: {message}
      </div>
    </div>
  );
}
