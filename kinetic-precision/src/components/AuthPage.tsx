import { useState, type FormEvent } from 'react';
import { Lock, Mail, ShieldCheck } from 'lucide-react';
import { supabase } from '../lib/supabaseClient';

const authBackdrop = encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" fill="none">
    <defs>
      <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#fbfdff"/>
        <stop offset="100%" stop-color="#eff6fb"/>
      </linearGradient>
      <linearGradient id="wave" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#b5d7ec" stop-opacity="0.2"/>
        <stop offset="50%" stop-color="#7fb8d8" stop-opacity="0.55"/>
        <stop offset="100%" stop-color="#b5d7ec" stop-opacity="0.18"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#wash)"/>
    <g opacity="0.58">
      <path d="M-120 510C70 360 210 680 420 520C610 375 670 150 890 250C1110 350 1120 670 1380 520C1510 444 1595 410 1710 450" stroke="url(#wave)" stroke-width="4"/>
      <path d="M-140 560C30 430 230 770 460 600C645 462 680 236 910 310C1140 384 1150 700 1420 570C1540 513 1615 490 1730 528" stroke="url(#wave)" stroke-width="2" opacity="0.8"/>
      <path d="M-110 620C90 500 250 780 470 670C660 576 720 330 920 380C1130 435 1185 765 1460 640C1565 594 1640 580 1760 618" stroke="url(#wave)" stroke-width="1.5" opacity="0.72"/>
      <path d="M-100 690C110 590 290 820 500 720C700 622 760 420 960 450C1170 482 1215 800 1490 700C1600 660 1690 646 1790 680" stroke="url(#wave)" stroke-width="1.25" opacity="0.64"/>
    </g>
    <g stroke="#9cbdd1" stroke-opacity="0.55" stroke-width="1.5" fill="none">
      <path d="M110 70H260L320 130V250"/>
      <path d="M300 140H420L500 60H660"/>
      <path d="M1020 80H1180L1240 140V260"/>
      <path d="M1260 160H1380L1460 80H1540"/>
      <path d="M220 390H360L430 320H560"/>
      <path d="M980 430H1120L1190 360H1350"/>
      <path d="M210 750H360L420 690H520"/>
      <path d="M1040 770H1180L1260 710H1410"/>
      <path d="M650 120V300"/>
      <path d="M790 180V360"/>
      <path d="M360 520V700"/>
      <path d="M1250 520V700"/>
    </g>
    <g fill="#a6d4ec" fill-opacity="0.35">
      <circle cx="470" cy="220" r="7"/>
      <circle cx="880" cy="330" r="7"/>
      <circle cx="1090" cy="470" r="10"/>
      <circle cx="1310" cy="270" r="8"/>
      <circle cx="560" cy="640" r="9"/>
      <circle cx="860" cy="650" r="8"/>
      <circle cx="1410" cy="610" r="7"/>
    </g>
    <g stroke="#c3d8e5" stroke-opacity="0.75" fill="none">
      <path d="M290 260h22v18h-22z"/>
      <path d="M291 257v-14h20v14"/>
      <path d="M294 267h16"/>
      <path d="M936 176h20v34h-20z"/>
      <path d="M940 168h12v8h-12z"/>
      <path d="M705 690h20v24h-20z"/>
      <path d="M709 683h12v7h-12z"/>
    </g>
  </svg>
`);

export function AuthPage() {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      if (mode === 'signup') {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setMessage('Check your email to confirm your account.');
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Unable to authenticate.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-surface px-6 py-10">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat opacity-95"
        style={{ backgroundImage: `url("data:image/svg+xml,${authBackdrop}")` }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-gradient-to-b from-surface/30 via-surface/45 to-surface/70" aria-hidden="true" />
      <div className="relative z-10 flex min-h-[calc(100vh-5rem)] items-center justify-center">
        <div className="w-full max-w-md rounded-3xl border border-outline-variant/20 bg-white/78 p-8 shadow-2xl shadow-primary/10 backdrop-blur-2xl">
        <div className="mb-6">
          <div className="flex items-center gap-3 text-primary">
            <ShieldCheck size={20} />
            <span className="text-[10px] font-black uppercase tracking-widest">Secure Access</span>
          </div>
          <h1 className="mt-3 text-2xl font-black text-on-surface font-headline">
            {mode === 'signup' ? 'Create your TREX workspace' : 'Welcome back to PeakLogic'}
          </h1>
          <p className="mt-2 text-sm text-on-surface-variant">
            {mode === 'signup'
              ? 'Sign up to save your analysis snapshots and return to them instantly.'
              : 'Sign in to continue with your stored forecasts and optimization runs.'}
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-1 block text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Email</span>
            <div className="relative">
              <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input
                type="email"
                required
                value={email}
                onChange={event => setEmail(event.target.value)}
                className="w-full rounded-xl border border-outline-variant/20 bg-surface-container-lowest pl-10 pr-3 py-2 text-sm font-bold text-on-surface outline-none focus:border-primary focus:ring-2 focus:ring-primary/10"
                placeholder="you@company.com"
              />
            </div>
          </label>

          <label className="block">
            <span className="mb-1 block text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Password</span>
            <div className="relative">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input
                type="password"
                required
                value={password}
                onChange={event => setPassword(event.target.value)}
                className="w-full rounded-xl border border-outline-variant/20 bg-surface-container-lowest pl-10 pr-3 py-2 text-sm font-bold text-on-surface outline-none focus:border-primary focus:ring-2 focus:ring-primary/10"
                placeholder="At least 8 characters"
              />
            </div>
          </label>

          {message && (
            <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low px-4 py-3 text-xs font-semibold text-on-surface">
              {message}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-primary px-6 py-3 text-xs font-black uppercase tracking-widest text-on-primary shadow-lg shadow-primary/20 transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {loading ? 'Working...' : mode === 'signup' ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <div className="mt-6 flex items-center justify-between text-xs font-bold text-on-surface-variant">
          <span>{mode === 'signup' ? 'Already have an account?' : 'New to PeakLogic?'}</span>
          <button
            type="button"
            onClick={() => {
              setMessage(null);
              setMode(mode === 'signup' ? 'login' : 'signup');
            }}
            className="text-primary hover:underline"
          >
            {mode === 'signup' ? 'Sign in' : 'Create one'}
          </button>
        </div>
      </div>
    </div>
    </div>
  );
}
