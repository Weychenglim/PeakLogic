import { Factory, TrendingUp, Zap, BarChart, Upload, Settings, Plus } from 'lucide-react';
import { NAV_ITEMS } from '../constants';
import { cn } from '../lib/utils';

interface SidebarProps {
  activeTab: string;
  onTabChange: (id: string) => void;
  onNewAnalysis?: () => void;
  onSettings?: () => void;
  disabledTabs?: string[];
}

const ICON_MAP: Record<string, any> = {
  Upload,
  Factory,
  TrendingUp,
  Zap,
  BarChart,
};

export function Sidebar({ activeTab, onTabChange, onNewAnalysis, onSettings, disabledTabs = [] }: SidebarProps) {
  return (
    <aside id="sidebar" className="h-screen w-64 fixed left-0 top-0 flex flex-col py-6 bg-slate-50 dark:bg-slate-900 z-20 border-r border-slate-200 dark:border-slate-800">
      <div className="px-6 mb-10">
        <h1 className="text-xl font-extrabold tracking-tight text-slate-900 dark:text-slate-100 font-headline">PeakLogic</h1>
        <p className="text-[10px] text-on-surface-variant font-bold uppercase tracking-widest mt-1">Energy Curator</p>
      </div>

      <nav className="flex-1 space-y-1 px-4">
        {NAV_ITEMS.map((item) => {
          const Icon = ICON_MAP[item.icon];
          const isActive = activeTab === item.id;
          const isDisabled = disabledTabs.includes(item.id);
          return (
            <span
              key={item.id}
              title={isDisabled ? 'Run an analysis to unlock this section.' : undefined}
              className={isDisabled ? 'block' : undefined}
            >
              <button
                onClick={() => {
                  if (!isDisabled) onTabChange(item.id);
                }}
                disabled={isDisabled}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 active:scale-[0.98]",
                  isActive 
                    ? "text-primary font-bold border-r-4 border-primary bg-primary/5 rounded-r-none" 
                    : "text-slate-500 dark:text-slate-400 hover:bg-slate-200/50 dark:hover:bg-slate-800/50",
                  isDisabled && "cursor-not-allowed opacity-50 hover:bg-transparent"
                )}
                aria-disabled={isDisabled}
              >
                <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
                <span className="text-sm font-medium">{item.label}</span>
              </button>
            </span>
          );
        })}
      </nav>

      <div className="mt-auto px-4 space-y-1">
        <button
          id="btn-new-analysis"
          onClick={onNewAnalysis}
          className="w-full bg-primary text-on-primary rounded-full py-2.5 px-4 mb-6 flex items-center justify-center font-bold text-sm shadow-lg shadow-primary/20 hover:opacity-90 transition-opacity"
        >
          <Plus size={16} className="mr-2" />
          New Analysis
        </button>

        <button
          onClick={onSettings}
          className={cn(
            "w-full flex items-center gap-3 px-4 py-2.5 rounded-xl transition-colors",
            activeTab === 'settings'
              ? "text-primary font-bold bg-primary/5"
              : "text-slate-500 dark:text-slate-400 hover:bg-slate-200/50"
          )}
        >
          <Settings size={20} />
          <span className="text-sm font-medium">Settings</span>
        </button>
      </div>
    </aside>
  );
}
