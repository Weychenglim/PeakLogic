import { Factory, TrendingUp, Zap, BarChart, Upload, Settings, HelpCircle, Plus } from 'lucide-react';
import { NAV_ITEMS } from '../constants';
import { cn } from '../lib/utils';

interface SidebarProps {
  activeTab: string;
  onTabChange: (id: string) => void;
}

const ICON_MAP: Record<string, any> = {
  Upload,
  Factory,
  TrendingUp,
  Zap,
  BarChart,
};

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  return (
    <aside id="sidebar" className="h-screen w-64 fixed left-0 top-0 flex flex-col py-6 bg-slate-50 dark:bg-slate-900 z-20 border-r border-slate-200 dark:border-slate-800">
      <div className="px-6 mb-10">
        <h1 className="text-xl font-extrabold tracking-tight text-slate-900 dark:text-slate-100 font-headline">Kinetic Precision</h1>
        <p className="text-[10px] text-on-surface-variant font-bold uppercase tracking-widest mt-1">Energy Curator</p>
      </div>

      <nav className="flex-1 space-y-1 px-4">
        {NAV_ITEMS.map((item) => {
          const Icon = ICON_MAP[item.icon];
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={cn(
                "w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 active:scale-[0.98]",
                isActive 
                  ? "text-primary font-bold border-r-4 border-primary bg-primary/5 rounded-r-none" 
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-200/50 dark:hover:bg-slate-800/50"
              )}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mt-auto px-4 space-y-1">
        <button id="btn-new-analysis" className="w-full bg-primary text-on-primary rounded-full py-2.5 px-4 mb-6 flex items-center justify-center font-bold text-sm shadow-lg shadow-primary/20 hover:opacity-90 transition-opacity">
          <Plus size={16} className="mr-2" />
          New Analysis
        </button>

        <button className="w-full flex items-center gap-3 px-4 py-2.5 text-slate-500 dark:text-slate-400 hover:bg-slate-200/50 rounded-xl transition-colors">
          <Settings size={20} />
          <span className="text-sm font-medium">Settings</span>
        </button>
        <button className="w-full flex items-center gap-3 px-4 py-2.5 text-slate-500 dark:text-slate-400 hover:bg-slate-200/50 rounded-xl transition-colors">
          <HelpCircle size={20} />
          <span className="text-sm font-medium">Support</span>
        </button>

        <div className="flex items-center gap-3 px-4 py-4 mt-4 border-t border-slate-200 dark:border-slate-800">
          <div className="w-8 h-8 rounded-full bg-primary-fixed flex-shrink-0 overflow-hidden border border-outline-variant/30">
            <img 
              src="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?ixlib=rb-1.2.1&auto=format&fit=facearea&facepad=2&w=256&h=256&q=80" 
              alt="Alex Sterling" 
              className="w-full h-full object-cover"
            />
          </div>
          <div className="flex-1 overflow-hidden">
            <p className="text-xs font-bold text-slate-900 dark:text-white truncate">Alex Sterling</p>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 truncate">Admin Access</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
