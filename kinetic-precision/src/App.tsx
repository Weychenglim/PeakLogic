/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { Sidebar } from './components/Sidebar';
import { TopAppBar } from './components/TopAppBar';
import { DataUpload } from './components/DataUpload';
import { SiteProfile } from './components/SiteProfile';
import { ForecastRisk } from './components/ForecastRisk';
import { Optimization } from './components/Optimization';
import { ExecutiveSummary } from './components/ExecutiveSummary';
import { AuthPage } from './components/AuthPage';
import { ApiUnavailableBanner, type LoadingStepId } from './components/AnalysisState';
import { NAV_ITEMS } from './constants';
import {
  DEFAULT_ASSUMPTIONS,
  analyzeBundled,
  fetchBundledSites,
  uploadAnalysis,
  type AnalysisResult,
  type BundledSite,
  type PlanningAssumptions,
} from './lib/api';
import { isSupabaseConfigured, supabase } from './lib/supabaseClient';

export default function App() {
  const [activeTab, setActiveTab] = useState('upload');
  const [sites, setSites] = useState<BundledSite[]>([]);
  const [selectedSourceFile, setSelectedSourceFile] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [assumptions, setAssumptions] = useState<PlanningAssumptions>(DEFAULT_ASSUMPTIONS);
  const [sitesLoaded, setSitesLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState<LoadingStepId>('upload');
  const [error, setError] = useState<string | null>(null);
  const [waitingForProfileRedirect, setWaitingForProfileRedirect] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (!analysis && (activeTab === 'profile' || activeTab === 'forecast' || activeTab === 'optimization' || activeTab === 'summary')) {
      setActiveTab('upload');
    }
  }, [analysis, activeTab]);

  useEffect(() => {
    setAssumptions(current => ({
      ...current,
      existing_pv_kwp: analysis?.metadata.existing_pv_kwp ?? null,
    }));
  }, [analysis?.metadata.existing_pv_kwp]);

  const activeTitle = useMemo(() => {
    return NAV_ITEMS.find(item => item.id === activeTab)?.label || 'Dashboard';
  }, [activeTab]);

  const userName = session?.user?.user_metadata?.full_name
    ?? session?.user?.user_metadata?.name
    ?? session?.user?.email
    ?? 'Account';
  const userEmail = session?.user?.email ?? 'Signed in';
  const userRole = session?.user?.role ?? 'authenticated';
  const userAvatarUrl = session?.user?.user_metadata?.avatar_url
    ?? session?.user?.user_metadata?.picture
    ?? null;
  const sessionUserId = session?.user?.id ?? null;
  const preloadUserRef = useRef<string | null>(null);

  const buildAssumptionsKey = (nextAssumptions: PlanningAssumptions) => {
    const orderedKeys = Object.keys(nextAssumptions).sort() as (keyof PlanningAssumptions)[];
    const normalized = orderedKeys.reduce<Record<string, unknown>>((acc, key) => {
      acc[key] = nextAssumptions[key];
      return acc;
    }, {});
    return JSON.stringify(normalized);
  };

  const buildCacheKey = (signature: string, nextAssumptions: PlanningAssumptions) => {
    return `${signature}|${buildAssumptionsKey(nextAssumptions)}`;
  };

  const fetchCachedAnalysis = async (cacheKey: string) => {
    if (!isSupabaseConfigured || !session) return null;
    const { data, error: fetchError } = await supabase
      .from('analysis_cache')
      .select('analysis')
      .eq('cache_key', cacheKey)
      .maybeSingle();
    if (fetchError) {
      console.warn('Supabase cache fetch failed:', fetchError.message);
      return null;
    }
    if (!data?.analysis) return null;
    return data.analysis as AnalysisResult;
  };

  const storeCachedAnalysis = async (
    cacheKey: string,
    analysisResult: AnalysisResult,
    datasetSignature: string,
    nextAssumptions: PlanningAssumptions,
  ) => {
    if (!isSupabaseConfigured || !session) return;
    const { error: upsertError } = await supabase
      .from('analysis_cache')
      .upsert(
        {
          cache_key: cacheKey,
          user_id: session.user.id,
          source_file: analysisResult.metadata.source_file,
          dataset_signature: datasetSignature,
          assumptions: nextAssumptions,
          analysis: analysisResult,
          updated_at: new Date().toISOString(),
        },
        { onConflict: 'cache_key' }
      );
    if (upsertError) {
      console.warn('Supabase cache upsert failed:', upsertError.message);
    }
  };

  const runBundledAnalysis = async (
    sourceFile: string,
    nextAssumptions = assumptions,
    options: { force?: boolean } = {},
  ) => {
    if (!sitesLoaded && !options.force) {
      return;
    }
    setLoading(true);
    setLoadingStep('upload');
    setError(null);
    try {
      const matchedSite = sites.find(site => site.source_file === sourceFile);
      const resolvedAssumptions = matchedSite?.existing_pv_kwp != null
        ? { ...nextAssumptions, existing_pv_kwp: matchedSite.existing_pv_kwp }
        : nextAssumptions;
      const signature = `bundled:${sourceFile}`;
      const cacheKey = buildCacheKey(signature, resolvedAssumptions);
      const cached = await fetchCachedAnalysis(cacheKey);
      if (cached) {
        setSelectedSourceFile(sourceFile);
        setUploadedFile(null);
        setAnalysis(cached);
      } else {
        const result = await analyzeBundled(sourceFile, resolvedAssumptions);
        setSelectedSourceFile(sourceFile);
        setUploadedFile(null);
        setAnalysis(result);
        await storeCachedAnalysis(cacheKey, result, signature, resolvedAssumptions);
      }
      if (matchedSite?.existing_pv_kwp != null) {
        setAssumptions(current => ({
          ...current,
          existing_pv_kwp: matchedSite.existing_pv_kwp,
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to analyze bundled workbook');
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (file: File) => {
    setLoading(true);
    setLoadingStep('upload');
    setError(null);
    try {
      const signature = `upload:${file.name}:${file.size}:${file.lastModified}`;
      const cacheKey = buildCacheKey(signature, assumptions);
      const cached = await fetchCachedAnalysis(cacheKey);
      if (cached) {
        setUploadedFile(null);
        setSelectedSourceFile(cached.metadata.source_file);
        setAnalysis(cached);
      } else {
        const result = await uploadAnalysis(file, assumptions);
        setUploadedFile(file);
        setSelectedSourceFile(result.metadata.source_file);
        setAnalysis(result);
        await storeCachedAnalysis(cacheKey, result, signature, assumptions);
      }
      setActiveTab('profile');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to analyze upload');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    if (!isSupabaseConfigured) {
      setAuthLoading(false);
      return undefined;
    }
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session ?? null);
      setAuthLoading(false);
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!mounted) return;
      setSession(nextSession);
    });
    return () => {
      mounted = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    setSession(null);
  };

  useEffect(() => {
    if (!loading) {
      setLoadingStep('upload');
      return;
    }
    const steps: LoadingStepId[] = ['upload', 'normalize', 'forecast', 'optimize'];
    let index = 0;
    const timer = window.setInterval(() => {
      index = Math.min(index + 1, steps.length - 1);
      setLoadingStep(steps[index]);
    }, 850);
    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    let mounted = true;
    if (isSupabaseConfigured && !session) {
      return () => {
        mounted = false;
      };
    }
    if (preloadUserRef.current === sessionUserId) {
      return () => {
        mounted = false;
      };
    }
    preloadUserRef.current = sessionUserId;
    async function loadSites() {
      setSitesLoaded(false);
      if (!analysis && sites.length === 0) {
        setLoading(true);
        setLoadingStep('upload');
      }
      setError(null);
      try {
        const loadedSites = await fetchBundledSites();
        if (!mounted) return;
        setSites(loadedSites);
        setSitesLoaded(true);
        if (!analysis && loadedSites.length > 0) {
          const first = loadedSites[0].source_file;
          setSelectedSourceFile(first);
          await runBundledAnalysis(first, assumptions, { force: true });
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Unable to reach TREX API');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    loadSites();
    return () => {
      mounted = false;
    };
  }, [sessionUserId, analysis, sites.length]);

  const applyAssumptionsFromOptimization = async () => {
    if (uploadedFile) {
      setLoading(true);
      setLoadingStep('upload');
      setError(null);
      try {
        const result = await uploadAnalysis(uploadedFile, assumptions);
        setSelectedSourceFile(result.metadata.source_file);
        setAnalysis(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to reanalyze upload');
      } finally {
        setLoading(false);
      }
      return;
    }

    if (selectedSourceFile) {
      await runBundledAnalysis(selectedSourceFile, assumptions);
    }
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'upload':
        return (
          <DataUpload
            sites={sites}
            analysis={analysis}
            assumptions={assumptions}
            loading={loading}
            loadingStep={loadingStep}
            error={error}
            onAssumptionsChange={setAssumptions}
            onAnalyzeBundled={sourceFile => runBundledAnalysis(sourceFile)}
            onReanalyze={async () => {
              if (!selectedSourceFile) return;
              setWaitingForProfileRedirect(true);
              try {
                await runBundledAnalysis(selectedSourceFile);
              } finally {
                setWaitingForProfileRedirect(false);
                setActiveTab('profile');
              }
            }}
            onUpload={handleUpload}
          />
        );
      case 'profile':
        return <SiteProfile analysis={analysis} loading={loading} loadingStep={loadingStep} error={error} />;
      case 'forecast':
        return <ForecastRisk analysis={analysis} loading={loading} loadingStep={loadingStep} error={error} />;
      case 'optimization':
        return (
          <Optimization
            analysis={analysis}
            loading={loading}
            loadingStep={loadingStep}
            error={error}
            assumptions={assumptions}
            onAssumptionsChange={setAssumptions}
            onApplyAssumptions={applyAssumptionsFromOptimization}
            canApplyAssumptions={Boolean(uploadedFile || selectedSourceFile)}
          />
        );
      case 'summary':
        return <ExecutiveSummary analysis={analysis} loading={loading} loadingStep={loadingStep} error={error} />;
      default:
        return (
          <DataUpload
            sites={sites}
            analysis={analysis}
            assumptions={assumptions}
            loading={loading}
            loadingStep={loadingStep}
            error={error}
            onAssumptionsChange={setAssumptions}
            onAnalyzeBundled={sourceFile => runBundledAnalysis(sourceFile)}
            onReanalyze={async () => {
              if (!selectedSourceFile) return;
              setWaitingForProfileRedirect(true);
              try {
                await runBundledAnalysis(selectedSourceFile);
              } finally {
                setWaitingForProfileRedirect(false);
                setActiveTab('profile');
              }
            }}
            onUpload={handleUpload}
          />
        );
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="rounded-full bg-surface-container-low px-6 py-3 text-xs font-black uppercase tracking-widest text-on-surface-variant">
          Loading workspace...
        </div>
      </div>
    );
  }

  if (!session && isSupabaseConfigured) {
    return <AuthPage />;
  }

  return (
    <div className="min-h-screen bg-surface flex">
      {/* Side Navigation */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        disabledTabs={analysis ? [] : ['profile', 'forecast', 'optimization', 'summary']}
      />
      
      {/* Main Content Area */}
      <main className="flex-1 ml-64 min-h-screen relative overflow-x-hidden">
        {/* Top App Bar */}
        <TopAppBar 
          title={activeTitle} 
          sites={sites}
          selectedSourceFile={selectedSourceFile}
          loading={loading}
          onSiteChange={runBundledAnalysis}
          userName={userName}
          userEmail={userEmail}
          userRole={userRole}
          userAvatarUrl={userAvatarUrl}
          onSignOut={handleSignOut}
        />
        {error && !analysis && sites.length === 0 && <ApiUnavailableBanner message={error} />}
        
        {/* Page Content */}
        <div className="p-8 pb-16 max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>

      {/* Global CSS for animations */}
      {waitingForProfileRedirect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-outline-variant/20 bg-surface-container-lowest p-6 shadow-2xl">
            <p className="text-xs font-black uppercase tracking-widest text-on-surface-variant">Applying assumptions</p>
            <p className="mt-2 text-base font-bold text-on-surface">Recalculating the plan. You will be sent to Site Profile when it finishes.</p>
            <div className="mt-5 text-sm font-semibold text-on-surface-variant">
              <span className="loading-dots">Loading</span>
            </div>
          </div>
        </div>
      )}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes loadingDots {
          0% { content: ''; }
          25% { content: '.'; }
          50% { content: '..'; }
          75% { content: '...'; }
          100% { content: ''; }
        }
        .loading-dots::after {
          content: '';
          display: inline-block;
          margin-left: 4px;
          animation: loadingDots 1.2s steps(1, end) infinite;
        }
        .animate-in {
          animation: fadeIn 0.4s ease-out forwards;
        }
      `}</style>
    </div>
  );
}
