import React from 'react';
import { Layout } from 'antd';
import { ServerSelector } from './ServerSelector';
import { UserMenu } from '../auth/UserMenu';
import { Logo } from './Logo';
import { ThemeToggle } from './ThemeToggle';
import { StatusDot } from './NodeStatus';

const { Header } = Layout;

export const AppHeader: React.FC<{ wsConnected: boolean }> = ({ wsConnected }) => (
  <Header className="sticky top-0 z-50 flex items-center gap-2 md:gap-4 h-14 px-3 md:px-4 bg-surface border-b border-line leading-none">
    <div className="flex items-center gap-2.5 flex-shrink-0">
      <Logo size={30} />
      <span className="hidden sm:inline font-semibold text-[15px] text-fg">tuKang</span>
    </div>

    {/* Mobile: the node pill takes the free space */}
    <div className="md:hidden flex-1 min-w-0 flex justify-center">
      <ServerSelector variant="mobile" live={wsConnected} />
    </div>

    <div className="hidden md:flex items-center gap-3 ml-auto">
      <ServerSelector variant="desktop" live={wsConnected} />
      <span className="flex items-center gap-1.5 pl-3 border-l border-line h-6 text-xs text-fg-muted" role="status">
        <StatusDot online={wsConnected} />
        {wsConnected ? 'Live' : 'Reconnecting'}
      </span>
    </div>

    <div className="flex items-center gap-0.5 md:pl-2 md:border-l md:border-line flex-shrink-0">
      <ThemeToggle />
      <UserMenu />
    </div>
  </Header>
);
