import React from 'react';
import { Server } from 'lucide-react';
import { ServerNode } from '../../types/server';

const STATUS_LABEL: Record<string, string> = {
  online: 'Online',
  offline: 'Offline',
  error: 'Connection error',
  unknown: 'Status unknown',
};

/** The metrics stream is the live signal; fall back to the inventory status when it is down. */
export const nodeStatusLabel = (server: ServerNode | null, wsConnected: boolean) => ({
  online: wsConnected || server?.status === 'online',
  label: wsConnected ? 'Live' : STATUS_LABEL[server?.status || 'unknown'],
});

/** Status dot on its own (lists, pills) */
export const StatusDot: React.FC<{ online: boolean; className?: string }> = ({ online, className = '' }) => (
  <span aria-hidden className={`inline-block h-2 w-2 rounded-full flex-shrink-0 ${online ? 'bg-success' : 'bg-danger'} ${className}`} />
);

/** Server glyph with a status dot in its corner; ringClass matches the background it sits on */
export const NodeStatusIcon: React.FC<{ online: boolean; ringClass: string; size?: number }> = ({ online, ringClass, size = 16 }) => (
  <span className="relative flex-shrink-0 inline-flex">
    <Server size={size} strokeWidth={1.75} className="text-fg-muted" />
    <span
      aria-hidden
      className={`absolute -right-0.5 -bottom-0.5 h-2 w-2 rounded-full ring-2 ${ringClass} ${online ? 'bg-success' : 'bg-danger'}`}
    />
  </span>
);
