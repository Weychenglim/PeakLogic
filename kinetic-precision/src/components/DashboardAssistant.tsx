import { useMemo, useState } from 'react';
import { ArrowRight, Bot, CheckCircle2, Database, Loader2, MessageSquareText, Send, Sparkles, X } from 'lucide-react';
import { askAssistant, type AnalysisResult, type AssistantContext, type AssistantSuggestedAction } from '../lib/api';
import { cn } from '../lib/utils';
import { buildScenarioDecisionEvidence } from './Optimization';
import { buildTopRiskWindowItems } from './forecastWindow';

type AssistantMessage = {
  role: 'assistant' | 'user';
  content: string;
  sources?: string[];
  mode?: string;
  actions?: AssistantSuggestedAction[];
};

export const ASSISTANT_SUGGESTED_QUESTIONS = [
  'What is happening in this site?',
  'Why did the optimizer choose this option?',
  'Why not the cheaper option?',
  'What should we verify before approving?',
];

export const ALLOWED_ASSISTANT_ACTION_TABS = ['profile', 'forecast', 'optimization', 'summary', 'settings'] as const;
type AssistantActionTab = typeof ALLOWED_ASSISTANT_ACTION_TABS[number];

function isAssistantActionTab(value: string): value is AssistantActionTab {
  return (ALLOWED_ASSISTANT_ACTION_TABS as readonly string[]).includes(value);
}

export function formatAssistantContent(content: string) {
  return content
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map(line => line
      .trim()
      .replace(/^#{1,6}\s+/, '')
      .replace(/^[-*]\s+/, '')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\s+/g, ' ')
      .trim()
    )
    .filter(Boolean);
}

export function modeLabel(mode?: string) {
  return mode === 'provider' || mode === 'openai' ? 'API mode' : 'Dashboard data mode';
}

export function buildAssistantContext(analysis: AnalysisResult): AssistantContext {
  return {
    site_id: analysis.metadata.site_id,
    source_file: analysis.metadata.source_file,
    has_solar: analysis.metadata.has_solar,
    existing_pv_kwp: analysis.metadata.existing_pv_kwp,
    profile: {
      peak_kw_import: analysis.profile.peak_kw_import,
      avg_kw_import: analysis.profile.avg_kw_import,
      weekday_avg_kw_import: analysis.profile.weekday_avg_kw_import,
      weekend_avg_kw_import: analysis.profile.weekend_avg_kw_import,
    },
    validation: {
      gap_count: analysis.validation.gap_count,
      missing_value_count: analysis.validation.missing_value_count,
      duplicate_count: analysis.validation.duplicate_count,
      row_count: analysis.validation.row_count,
    },
    assumptions: analysis.assumptions,
    forecast: {
      metrics: analysis.forecast.metrics,
      top_risk_windows: buildTopRiskWindowItems(analysis, 5).map(item => ({
        rank: item.rank,
        day: item.day,
        time_window: item.timeWindow,
        label: item.label,
        level: item.level,
        peak_kw: item.peakLoad,
        score: item.score,
        action: item.action,
      })),
    },
    optimization: {
      best_scenario: analysis.optimization.best_scenario,
      scenario_evidence: buildScenarioDecisionEvidence(analysis),
    },
  };
}

export function DashboardAssistant({
  analysis,
  onNavigate,
}: {
  analysis: AnalysisResult | null;
  onNavigate: (targetTab: AssistantActionTab) => void;
}) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      role: 'assistant',
      content: 'Ask for next steps, peak-risk events, optimizer reasoning, option tradeoffs, or approval checks.',
      sources: ['Current dashboard'],
      mode: 'grounded',
    },
  ]);
  const context = useMemo(() => (analysis ? buildAssistantContext(analysis) : null), [analysis]);

  if (!analysis || !context) return null;

  const submitQuestion = async (nextQuestion: string) => {
    const trimmed = nextQuestion.trim();
    if (!trimmed || loading) return;
    setQuestion('');
    setMessages(current => [...current, { role: 'user', content: trimmed }]);
    setLoading(true);
    try {
      const response = await askAssistant(trimmed, context);
      setMessages(current => [
        ...current,
        {
          role: 'assistant',
          content: response.answer,
          sources: response.sources,
          mode: response.mode,
          actions: response.suggested_actions.filter(action => isAssistantActionTab(action.target_tab)),
        },
      ]);
    } catch (error) {
      setMessages(current => [
        ...current,
        {
          role: 'assistant',
          content: error instanceof Error ? error.message : 'Assistant is unavailable right now.',
          sources: ['Assistant API'],
          mode: 'grounded',
          actions: [],
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed bottom-6 right-6 z-40">
      {open && (
        <section className="mb-4 flex h-[42rem] w-[36rem] max-h-[calc(100vh-7rem)] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-xl border border-outline-variant/20 bg-surface-container-lowest shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-outline-variant/10 px-5 py-4">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-fixed text-primary">
                <Bot size={18} />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest text-primary">AI Assistant</p>
                <p className="mt-1 text-sm font-black text-on-surface">Ask about this analysis</p>
                <p className="mt-1 text-xs font-semibold text-on-surface-variant">Answers use API mode when the provider responds, otherwise dashboard data mode.</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="flex h-8 w-8 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container-low"
              aria-label="Close assistant"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={cn(
                  'rounded-lg px-4 py-3 text-sm leading-relaxed',
                  message.role === 'user'
                    ? 'ml-16 bg-primary text-on-primary'
                    : 'mr-10 bg-surface-container-low text-on-surface'
                )}
              >
                {message.role === 'assistant' && (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className={cn(
                      'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-widest',
                      message.mode === 'provider' || message.mode === 'openai'
                        ? 'bg-primary-fixed text-primary'
                        : 'bg-surface-container-high text-on-surface-variant'
                    )}>
                      {message.mode === 'provider' || message.mode === 'openai' ? <Sparkles size={12} /> : <Database size={12} />}
                      {modeLabel(message.mode)}
                    </span>
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-container-lowest px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-on-surface-variant">
                      <CheckCircle2 size={12} />
                      Fallback ready
                    </span>
                  </div>
                )}
                <div className="space-y-2">
                  {formatAssistantContent(message.content).map((line, lineIndex) => (
                    <p key={`${index}-${lineIndex}`} className="font-semibold">{line}</p>
                  ))}
                </div>
                {message.sources && message.sources.length > 0 && (
                  <p className={cn(
                    'mt-2 text-[10px] font-black uppercase tracking-widest',
                    message.role === 'user' ? 'text-on-primary/70' : 'text-on-surface-variant'
                  )}>
                    Sources: {message.sources.join(', ')}
                  </p>
                )}
                {message.role === 'assistant' && message.actions && message.actions.length > 0 && (
                  <div className="mt-3 space-y-2">
                    <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Suggested actions</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {message.actions.map(action => (
                        <button
                          key={`${action.target_tab}-${action.label}`}
                          type="button"
                          onClick={() => {
                            if (isAssistantActionTab(action.target_tab)) {
                              onNavigate(action.target_tab);
                              setOpen(false);
                            }
                          }}
                          className="flex items-start justify-between gap-3 rounded-lg border border-primary/10 bg-surface-container-lowest px-3 py-2 text-left transition-colors hover:border-primary/30 hover:bg-primary-fixed/35"
                        >
                          <span>
                            <span className="block text-xs font-black text-on-surface">{action.label}</span>
                            <span className="mt-0.5 block text-[10px] font-semibold leading-snug text-on-surface-variant">{action.reason}</span>
                          </span>
                          <ArrowRight size={14} className="mt-0.5 shrink-0 text-primary" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="mr-8 flex items-center gap-2 rounded-lg bg-surface-container-low px-3 py-2 text-xs font-black uppercase tracking-widest text-on-surface-variant">
                <Loader2 size={14} className="animate-spin" />
                Reading dashboard
              </div>
            )}
          </div>

          <div className="border-t border-outline-variant/10 px-5 py-4">
            <div className="mb-3 flex flex-wrap gap-2">
              {ASSISTANT_SUGGESTED_QUESTIONS.map(item => (
                <button
                  key={item}
                  type="button"
                  onClick={() => submitQuestion(item)}
                  className="rounded-full bg-primary-fixed px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-primary transition-colors hover:bg-primary-fixed-dim"
                >
                  {item}
                </button>
              ))}
            </div>
            <form
              className="flex items-center gap-2"
              onSubmit={event => {
                event.preventDefault();
                submitQuestion(question);
              }}
            >
              <input
                value={question}
                onChange={event => setQuestion(event.target.value)}
                placeholder="Ask about the active analysis"
                className="min-w-0 flex-1 rounded-full border border-outline-variant/20 bg-surface-container-low px-4 py-2 text-sm font-semibold text-on-surface outline-none transition-colors placeholder:text-on-surface-variant focus:border-primary focus:bg-surface-container-lowest"
              />
              <button
                type="submit"
                disabled={loading || !question.trim()}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
                aria-label="Ask assistant"
              >
                <Send size={16} />
              </button>
            </form>
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen(current => !current)}
        className="flex items-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-black uppercase tracking-widest text-on-primary shadow-xl shadow-primary/25 transition-transform hover:-translate-y-0.5"
      >
        <MessageSquareText size={18} />
        Assistant
      </button>
    </div>
  );
}
