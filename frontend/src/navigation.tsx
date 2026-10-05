import {
  Gauge,
  Layers,
  Package,
  FolderOpen,
  HardDrive,
  Network,
  Users,
  SquareTerminal,
  ShieldCheck,
  ScrollText,
  type LucideIcon,
} from 'lucide-react';
import { AuthUser, Role, hasRole } from './services/api';

/** Minimum role per page. Mirrors backend app/core/policy.py (the backend is what enforces it). */
export const TAB_ROLES: Record<string, Role> = {
  terminal: 'admin',
  files: 'admin',
  audit: 'admin',
  access: 'admin',
};

export const tabRole = (tab: string): Role => TAB_ROLES[tab] || 'viewer';

export interface NavItem {
  key: string;
  label: string;
  Icon: LucideIcon;
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

/** The one navigation model: desktop sidebar, mobile bottom bar and the "More" sheet all read it. */
export const NAV_SECTIONS: NavSection[] = [
  { items: [{ key: 'dashboard', label: 'Overview', Icon: Gauge}] },
  {
    title: 'Workloads',
    items: [
      { key: 'services', label: 'Services', Icon: Layers},
      { key: 'containers', label: 'Containers', Icon: Package},
    ],
  },
  {
    title: 'System',
    items: [
      { key: 'files', label: 'Files', Icon: FolderOpen },
      { key: 'storage', label: 'Storage', Icon: HardDrive },
      { key: 'network', label: 'Networking', Icon: Network },
      { key: 'users', label: 'Linux accounts', Icon: Users },
      { key: 'terminal', label: 'Terminal', Icon: SquareTerminal},
    ],
  },
  {
    title: 'Administration',
    items: [
      { key: 'access', label: 'Access control', Icon: ShieldCheck },
      { key: 'audit', label: 'Audit log', Icon: ScrollText },
    ],
  },
];

/** Sections with only the pages this user may open; empty sections dropped */
export const visibleSections = (user: AuthUser | null): NavSection[] =>
  NAV_SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => hasRole(user, tabRole(i.key))) })).filter((s) => s.items.length > 0);

/**
 * Mobile bottom bar, in display order; everything else lives in the "More" sheet.
 * Pages the user may not open are skipped and the next one moves up (a viewer gets Services
 * instead of Files and Terminal).
 */
const MOBILE_BAR = ['dashboard', 'files', 'containers', 'terminal', 'services'];
const MOBILE_BAR_SLOTS = 4;

export const mobileBarItems = (user: AuthUser | null): NavItem[] =>
  MOBILE_BAR.filter((key) => hasRole(user, tabRole(key)))
    .slice(0, MOBILE_BAR_SLOTS)
    .map((key) => navItem(key)!);

export const navItem = (key: string): NavItem | undefined =>
  NAV_SECTIONS.flatMap((s) => s.items).find((i) => i.key === key);
