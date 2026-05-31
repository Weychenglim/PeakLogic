import { useState, type FormEvent } from 'react';
import { Lock, Mail, ShieldCheck } from 'lucide-react';
import { supabase } from '../lib/supabaseClient';

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
    <div className="min-h-screen bg-surface flex items-center justify-center px-6">
      <div className="w-full max-w-md rounded-3xl border border-outline-variant/20 bg-surface-container-lowest p-8 shadow-2xl">
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
  );
}
