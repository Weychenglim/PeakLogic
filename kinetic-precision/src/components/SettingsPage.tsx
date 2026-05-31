import { Database, Globe2, Server, ShieldCheck } from 'lucide-react';
import { isSupabaseConfigured } from '../lib/supabaseClient';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

function SettingCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Server;
}) {
  return (
    <div className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">{label}</p>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-fixed text-primary">
          <Icon size={19} />
        </div>
      </div>
      <p className="break-all font-headline text-lg font-black text-on-surface">{value}</p>
      <p className="mt-2 text-sm font-semibold leading-relaxed text-on-surface-variant">{detail}</p>
    </div>
  );
}

export function SettingsPage() {
  const deploymentMode = API_BASE_URL.includes('localhost') || API_BASE_URL.includes('127.0.0.1')
    ? 'Local development'
    : 'Public deployment';

  return (
    <div className="animate-in fade-in space-y-6 duration-500">
      <section className="rounded-xl border border-outline-variant/10 bg-surface-container-lowest p-6 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-widest text-primary">Application settings</p>
            <h2 className="mt-2 font-headline text-3xl font-black tracking-tight text-on-surface">PeakLogic configuration</h2>
            <p className="mt-2 max-w-2xl text-sm font-semibold leading-relaxed text-on-surface-variant">
              Quick deployment and connection checks for the public demo.
            </p>
          </div>
          <div className="rounded-full bg-primary-fixed px-4 py-2 text-xs font-black uppercase tracking-widest text-primary">
            {deploymentMode}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SettingCard
          label="Backend API"
          value={API_BASE_URL}
          detail="Vercel should point this to the Render FastAPI service through VITE_API_BASE_URL."
          icon={Server}
        />
        <SettingCard
          label="Frontend host"
          value={window.location.origin}
          detail="Add this URL to Render FRONTEND_ORIGINS so browser requests pass CORS."
          icon={Globe2}
        />
        <SettingCard
          label="Supabase"
          value={isSupabaseConfigured ? 'Configured' : 'Disabled'}
          detail={isSupabaseConfigured ? 'Login and analysis cache can use the configured Supabase project.' : 'The app runs as a public demo without Supabase login/cache.'}
          icon={Database}
        />
        <SettingCard
          label="Demo readiness"
          value="Check API health before presenting"
          detail="Render free services may cold-start after inactivity, so open the API health URL before a live demo."
          icon={ShieldCheck}
        />
      </section>
    </div>
  );
}
