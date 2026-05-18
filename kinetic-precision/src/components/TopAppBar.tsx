import { useEffect, useRef, useState } from 'react';
import { LogOut, Search, Bell, User, MapPin, ChevronDown, Check } from 'lucide-react';
import type { BundledSite } from '../lib/api';
import { cn } from '../lib/utils';

interface TopAppBarProps {
  title: string;
  sites: BundledSite[];
  selectedSourceFile: string;
  loading: boolean;
  onSiteChange: (sourceFile: string) => void;
  userName: string;
  userEmail: string;
  userRole: string;
  userAvatarUrl?: string | null;
  onSignOut: () => void;
}

export function TopAppBar({
  title,
  sites,
  selectedSourceFile,
  loading,
  onSiteChange,
  userName,
  userEmail,
  userRole,
  userAvatarUrl,
  onSignOut,
}: TopAppBarProps) {
  const [open, setOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);
  const currentSite = sites.find(s => s.source_file === selectedSourceFile) || sites[0];

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);

  return (
    <header className="flex justify-between items-center w-full px-8 h-16 sticky top-0 z-30 glass-panel border-b border-surface-container-high transition-all duration-300">
      <div className="flex items-center gap-4">
        <h2 className="text-xl font-bold font-headline text-on-surface">{title}</h2>
        <div className="h-4 w-[1px] bg-outline-variant/30 mx-2"></div>
        
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => {
              if (!loading && sites.length > 0) setOpen(value => !value);
            }}
            disabled={loading || sites.length === 0}
            className={cn(
              "group flex h-9 w-80 max-w-[42vw] items-center gap-2 rounded-lg border px-3 text-left text-sm font-bold shadow-sm transition-all",
              open
                ? "border-primary bg-surface-container-lowest ring-2 ring-primary/10"
                : "border-outline-variant/20 bg-surface-container-low hover:border-primary/30 hover:bg-surface-container-high",
              (loading || sites.length === 0) && "cursor-wait opacity-70"
            )}
            aria-haspopup="listbox"
            aria-expanded={open}
          >
            <MapPin size={14} className="shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate text-on-surface">{currentSite?.site_id || 'No site loaded'}</span>
            <ChevronDown
              size={15}
              className={cn("shrink-0 text-on-surface-variant transition-transform", open && "rotate-180")}
            />
          </button>

          {open && (
            <div
              role="listbox"
              className="absolute left-0 top-full z-50 mt-2 w-80 max-w-[42vw] overflow-hidden rounded-xl border border-outline-variant/20 bg-surface-container-lowest shadow-2xl"
            >
              <div className="border-b border-outline-variant/10 px-4 py-3">
                <p className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Bundled site</p>
              </div>
              <div className="max-h-72 overflow-y-auto p-1.5">
                {sites.map(site => {
                  const selected = site.source_file === selectedSourceFile;
                  return (
                    <button
                      key={site.source_file}
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        if (!selected) onSiteChange(site.source_file);
                      }}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left transition-colors",
                        selected ? "bg-primary/7 text-primary" : "text-on-surface hover:bg-surface-container-low"
                      )}
                      role="option"
                      aria-selected={selected}
                    >
                      <div
                        className={cn(
                          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                          selected ? "border-primary bg-primary text-on-primary" : "border-outline-variant/30 bg-surface-container-low"
                        )}
                      >
                        {selected ? <Check size={14} /> : <MapPin size={13} className="text-primary" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-black">{site.site_id}</p>
                        <p className="mt-0.5 truncate text-[10px] font-semibold text-on-surface-variant">{site.has_solar ? 'Solar site' : 'No solar'} · {site.peak_kw_import.toFixed(0)} kW peak</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {currentSite && (
          <div className="flex items-center gap-1.5 px-2.5 py-0.5 bg-secondary-container/50 text-on-secondary-container rounded-full animate-pulse">
            <div className="w-1.5 h-1.5 rounded-full bg-secondary" />
            <span className="text-[10px] font-bold uppercase tracking-tight">{loading ? 'Running' : 'Loaded'}</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-6">
        <div className="relative">
          <input 
            type="text" 
            placeholder="Search analytics..." 
            className="bg-surface-container-low border-none rounded-full py-1.5 pl-10 pr-4 text-sm w-48 focus:ring-2 focus:ring-primary/20 focus:w-64 transition-all outline-none"
          />
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
        </div>

        <div className="flex items-center gap-4 text-on-surface-variant">
          <button className="relative p-1 hover:opacity-80 transition-opacity">
            <Bell size={20} />
            <div className="absolute top-1 right-1 w-2 h-2 bg-error rounded-full border-2 border-surface" />
          </button>
          <div className="relative" ref={userMenuRef}>
            <button
              className="p-1 hover:opacity-80 transition-opacity"
              onClick={() => setUserMenuOpen(value => !value)}
              type="button"
              aria-haspopup="menu"
              aria-expanded={userMenuOpen}
            >
              {userAvatarUrl ? (
                <img
                  src={userAvatarUrl}
                  alt={userName}
                  className="h-8 w-8 rounded-full border border-outline-variant/30 object-cover"
                />
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full border border-outline-variant/30 bg-surface-container-low text-on-surface-variant">
                  <User size={16} />
                </div>
              )}
            </button>
            {userMenuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-full z-50 mt-3 w-64 overflow-hidden rounded-2xl border border-outline-variant/20 bg-surface-container-lowest shadow-2xl"
              >
                <div className="flex items-center gap-3 border-b border-outline-variant/10 px-4 py-4">
                  {userAvatarUrl ? (
                    <img
                      src={userAvatarUrl}
                      alt={userName}
                      className="h-10 w-10 rounded-full border border-outline-variant/30 object-cover"
                    />
                  ) : (
                    <div className="flex h-10 w-10 items-center justify-center rounded-full border border-outline-variant/30 bg-surface-container-low text-on-surface-variant">
                      <User size={18} />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-black text-on-surface">{userName}</p>
                    <p className="truncate text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{userRole}</p>
                    <p className="truncate text-[11px] font-semibold text-on-surface-variant">{userEmail}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={onSignOut}
                  className="flex w-full items-center gap-2 px-4 py-3 text-xs font-black uppercase tracking-widest text-on-surface-variant transition-colors hover:bg-surface-container-low"
                >
                  <LogOut size={14} />
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
