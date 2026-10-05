import React, { useEffect, useState } from 'react';
import { Tooltip } from 'antd';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useServer } from '../../context/ServerContext';
import { visibleSections } from '../../navigation';
import { NodeStatusIcon, nodeStatusLabel } from './NodeStatus';

interface AppSidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  wsConnected: boolean;
}

const COLLAPSED_KEY = 'sidebar.collapsed';

// Per-viewer preference only; storage may be unavailable (private mode, blocked site data)
const readCollapsed = () => {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
};

export const AppSidebar: React.FC<AppSidebarProps> = ({ currentTab, onSelectTab, wsConnected }) => {
  const { user } = useAuth();
  const { activeServer } = useServer();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  const sections = visibleSections(user);
  const status = nodeStatusLabel(activeServer, wsConnected);

  const withTooltip = (title: React.ReactNode, node: React.ReactElement) =>
    collapsed ? (
      <Tooltip title={title} placement="right" mouseEnterDelay={0.15}>
        {node}
      </Tooltip>
    ) : (
      node
    );

  return (
    <aside
      className={`hidden md:flex flex-col flex-shrink-0 min-h-0 bg-surface border-r border-line select-none motion-safe:transition-[width] motion-safe:duration-200 ${
        collapsed ? 'w-[64px]' : 'w-[240px]'
      }`}
    >
      <nav aria-label="Main navigation" className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-2.5 py-3">
        {sections.map((section, si) => (
          <div key={section.title || `s${si}`} className={si > 0 ? 'mt-5' : ''}>
            {section.title &&
              (collapsed ? (
                <div className="mx-2 mb-2 border-t border-line" role="separator" />
              ) : (
                <div className="px-3 mb-1.5 text-[11px] font-semibold text-fg-subtle tracking-wide">{section.title}</div>
              ))}
            <ul className="list-none m-0 p-0 space-y-0.5">
              {section.items.map(({ key, label, Icon }) => {
                const active = currentTab === key;
                return (
                  <li key={key}>
                    {withTooltip(
                      label,
                      <button
                        type="button"
                        onClick={() => onSelectTab(key)}
                        aria-current={active ? 'page' : undefined}
                        aria-label={collapsed ? label : undefined}
                        className={`focus-ring relative flex w-full items-center gap-3 rounded-md h-9 cursor-pointer font-[inherit] text-[13.5px] ${
                          collapsed ? 'justify-center px-0' : 'px-3'
                        } ${active ? 'bg-accent/15 text-fg font-medium' : 'bg-transparent text-fg-muted hover:bg-surface-2 hover:text-fg'}`}
                      >
                        {active && <span aria-hidden className="absolute -left-2.5 top-1.5 bottom-1.5 w-[3px] rounded-r bg-accent" />}
                        <Icon size={17} strokeWidth={1.75} className={`flex-shrink-0 ${active ? 'text-accent' : ''}`} />
                        {!collapsed && <span className="truncate">{label}</span>}
                      </button>,
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Which node every page acts on, and whether we can see it */}
      <div className="border-t border-line p-2.5 space-y-1">
        {activeServer &&
          withTooltip(
            <div>
              <div className="font-medium">{activeServer.name}</div>
              <div className="text-xs opacity-80">
                {activeServer.host}:{activeServer.port} · {status.label}
              </div>
            </div>,
            <div
              className={`flex items-center gap-2.5 rounded-md py-2 ${collapsed ? 'justify-center' : 'px-3 bg-canvas border border-line'}`}
              aria-label={`Managing ${activeServer.name}, ${status.label}`}
            >
              <NodeStatusIcon online={status.online} ringClass={collapsed ? 'ring-surface' : 'ring-canvas'} />
              {!collapsed && (
                <div className="min-w-0 leading-tight">
                  <div className="truncate text-[13px] text-fg">{activeServer.name}</div>
                  <div className="truncate text-[11px] text-fg-subtle">
                    {activeServer.host} · {status.label}
                  </div>
                </div>
              )}
            </div>,
          )}
        {withTooltip(
          'Expand sidebar',
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className={`focus-ring flex w-full items-center gap-3 rounded-md h-8 bg-transparent cursor-pointer font-[inherit] text-[12.5px] text-fg-subtle hover:bg-surface-2 hover:text-fg ${
              collapsed ? 'justify-center' : 'px-3'
            }`}
          >
            {collapsed ? <PanelLeftOpen size={16} strokeWidth={1.75} /> : <PanelLeftClose size={16} strokeWidth={1.75} />}
            {!collapsed && <span>Collapse</span>}
          </button>,
        )}
      </div>
    </aside>
  );
};
