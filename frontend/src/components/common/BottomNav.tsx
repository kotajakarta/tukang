import React, { useState } from 'react';
import { Button, Drawer, message } from 'antd';
import { ChevronRight, Ellipsis, Zap } from 'lucide-react';
import { useServer } from '../../context/ServerContext';
import { api, hasRole } from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { mobileBarItems, visibleSections } from '../../navigation';
import { NodeStatusIcon, nodeStatusLabel } from './NodeStatus';
import { ThemeSegmented } from './ThemeToggle';
import { SystemMetricsPayload } from '../../types/metrics';

interface BottomNavProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  /** From App's metrics stream (one socket for the whole page) */
  currentMetrics: SystemMetricsPayload | null;
  connected: boolean;
}

export const BottomNav: React.FC<BottomNavProps> = ({ currentTab, onSelectTab, currentMetrics, connected }) => {
  const { user } = useAuth();
  const { activeServer } = useServer();
  const [moreOpen, setMoreOpen] = useState(false);
  const [testing, setTesting] = useState(false);

  const sections = visibleSections(user);
  const primary = mobileBarItems(user);
  const inMore = !primary.some((i) => i.key === currentTab);
  const status = nodeStatusLabel(activeServer, connected);

  const go = (key: string) => {
    onSelectTab(key);
    setMoreOpen(false);
  };

  const testConnection = async () => {
    if (!activeServer) return;
    setTesting(true);
    try {
      const res = await api.testServer(activeServer.id);
      if (res.success) message.success(`${activeServer.name} is reachable (${res.latency_ms} ms)`);
      else message.error(`${activeServer.name} is not reachable: ${res.message}`);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e.message || 'Connection test failed');
    } finally {
      setTesting(false);
    }
  };

  const tabButton = (key: string, label: string, Icon: React.FC<any>, active: boolean, onClick: () => void, extra?: React.ReactNode) => (
    <button
      key={key}
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`focus-ring relative flex flex-col items-center justify-center gap-1 h-16 min-w-0 px-1 bg-transparent cursor-pointer font-[inherit] ${
        active ? 'text-accent' : 'text-fg-muted active:text-fg'
      }`}
    >
      {active && <span aria-hidden className="absolute top-0 left-1/2 -translate-x-1/2 h-[3px] w-8 rounded-b bg-accent" />}
      <span className="relative inline-flex">
        <Icon size={22} strokeWidth={active ? 2 : 1.75} />
        {extra}
      </span>
      <span className={`text-[11px] leading-none truncate max-w-full ${active ? 'font-semibold' : ''}`}>{label}</span>
    </button>
  );

  return (
    <>
      <nav
        aria-label="Main navigation"
        className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-surface/95 backdrop-blur border-t border-line safe-area-bottom select-none"
      >
        <div className="grid" style={{ gridTemplateColumns: `repeat(${primary.length + 1}, minmax(0, 1fr))` }}>
          {primary.map(({ key, label, Icon }) =>
            tabButton(
              key,
              label,
              Icon,
              currentTab === key,
              () => onSelectTab(key),
              key === 'dashboard' && connected ? (
                <span aria-hidden className="absolute -top-0.5 -right-1 h-2 w-2 rounded-full bg-success ring-2 ring-surface" />
              ) : null,
            ),
          )}
          {tabButton('more', 'More', Ellipsis, inMore || moreOpen, () => setMoreOpen(true))}
        </div>
      </nav>

      <Drawer
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        placement="bottom"
        height="auto"
        rootClassName="bottom-sheet md:hidden"
        closable={false}
        title={null}
        styles={{ content: { maxHeight: '88vh' } }}
      >
        <div className="flex justify-center pt-2 pb-2" aria-hidden>
          <span className="h-1 w-9 rounded-full bg-line" />
        </div>

        {/* The node every page acts on */}
        {activeServer && (
          <div className="mx-4 mb-4 rounded-lg border border-line bg-canvas p-3">
            <div className="flex items-center gap-3">
              <NodeStatusIcon online={status.online} ringClass="ring-canvas" size={18} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] font-medium text-fg">{activeServer.name}</div>
                <div className="truncate text-xs text-fg-subtle">
                  {activeServer.is_local ? 'Local host' : `${activeServer.host}:${activeServer.port}`} · {status.label}
                </div>
              </div>
              {hasRole(user, 'operator') && (
                <Button size="small" icon={<Zap size={14} />} loading={testing} onClick={testConnection}>
                  Test
                </Button>
              )}
            </div>
            <dl className="grid grid-cols-3 gap-2 mt-3 mb-0">
              {[
                ['CPU', currentMetrics ? `${currentMetrics.cpu.usage_percent}%` : '–'],
                ['Memory', currentMetrics ? `${currentMetrics.memory.percent}%` : '–'],
                ['Load', currentMetrics?.cpu.load_avg?.length ? currentMetrics.cpu.load_avg[0].toFixed(2) : '–'],
              ].map(([k, v]) => (
                <div key={k} className="rounded-md bg-surface border border-line-muted px-2 py-1.5">
                  <dt className="text-[11px] text-fg-subtle">{k}</dt>
                  <dd className="m-0 text-sm font-semibold tabular-nums text-fg">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {/* Every page, grouped like the desktop sidebar */}
        <nav aria-label="All pages">
          {sections.map((section, si) => (
            <div key={section.title || `s${si}`} className="mb-3">
              {section.title && <div className="px-4 pb-1 text-xs font-semibold text-fg-subtle">{section.title}</div>}
              <ul className="list-none m-0 p-0">
                {section.items.map(({ key, label, Icon }) => {
                  const active = currentTab === key;
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        onClick={() => go(key)}
                        aria-current={active ? 'page' : undefined}
                        className={`focus-ring flex w-full items-center gap-3 min-h-[48px] px-4 text-left cursor-pointer font-[inherit] text-[15px] ${
                          active ? 'bg-accent/10 text-accent font-medium' : 'bg-transparent text-fg active:bg-surface-2'
                        }`}
                      >
                        <Icon size={19} strokeWidth={1.75} className={active ? 'text-accent' : 'text-fg-muted'} />
                        <span className="flex-1 truncate">{label}</span>
                        <ChevronRight size={16} className="text-fg-subtle" aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-line mx-4 pt-3 pb-4">
          <div className="text-xs font-semibold text-fg-subtle mb-2">Appearance</div>
          <ThemeSegmented />
        </div>
      </Drawer>
    </>
  );
};
