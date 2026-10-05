import React, { useEffect, useRef, useState } from 'react';
import { Layout, Tabs } from 'antd';
import { ServerProvider, useServer } from './context/ServerContext';
import { useMetricsStream } from './hooks/useMetricsStream';
import { AppHeader } from './components/common/AppHeader';
import { AppSidebar } from './components/common/AppSidebar';
import { HostInfoCard } from './components/dashboard/HostInfoCard';
import { MetricsOverview } from './components/dashboard/MetricsOverview';
import { RealtimeCharts } from './components/dashboard/RealtimeCharts';
import { ServiceTable } from './components/services/ServiceTable';
import { ContainerList } from './components/containers/ContainerList';
import { QuadletManager } from './components/containers/QuadletManager';
import { StorageView } from './components/storage/StorageView';
import { NetworkView } from './components/network/NetworkView';
import { WebTerminal } from './components/terminal/WebTerminal';
import { UsersView } from './components/users/UsersView';
import { BottomNav } from './components/common/BottomNav';
import { AuditView } from './components/audit/AuditView';
import { AccessControlView } from './components/access/AccessControlView';
import { FilesView } from './components/files/FilesView';
import { MfaEnrollmentPage } from './components/auth/MfaSetup';
import { hasRole } from './services/api';
import { tabRole } from './navigation';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { LoginPage } from './components/auth/LoginPage';
import { Spin } from 'antd';
import { ContainerOutlined, AppstoreAddOutlined } from '@ant-design/icons';

const { Content } = Layout;

const MainContent: React.FC = () => {
  const { activeServer } = useServer();
  const { currentMetrics, history, connected } = useMetricsStream();
  const { user } = useAuth();
  const [tab, setCurrentTab] = useState<string>('dashboard');
  // Start directory for the Web Terminal when it is opened from Files; plain navigation resets it
  const [terminalCwd, setTerminalCwd] = useState<string | undefined>();
  const selectTab = (next: string) => {
    setTerminalCwd(undefined);
    setCurrentTab(next);
  };
  const openTerminalAt = (dir: string) => {
    setTerminalCwd(dir);
    setCurrentTab('terminal');
  };
  // Never render a page the role can't use (e.g. after being demoted mid-session)
  const currentTab = hasRole(user, tabRole(tab)) ? tab : 'dashboard';

  // Each page starts at its top, not at the previous page's scroll position
  const contentRef = useRef<HTMLElement>(null);
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [currentTab]);

  return (
    <Layout className="h-[100dvh] w-screen overflow-hidden flex flex-col bg-canvas">
      <AppHeader wsConnected={connected} />

      <Layout hasSider className="flex-1 flex flex-row min-h-0 overflow-hidden relative">
        <AppSidebar currentTab={currentTab} onSelectTab={selectTab} wsConnected={connected} />

        <Content ref={contentRef} className="flex-1 min-w-0 px-3 pt-3 sm:px-4 sm:pt-4 md:px-6 md:pt-6 mobile-content-pad overflow-y-auto bg-canvas">
          {currentTab === 'dashboard' && (
            <div className="space-y-6 max-w-7xl mx-auto">
              <HostInfoCard
                server={activeServer}
                hostInfo={currentMetrics?.host_info}
                loadAvg={currentMetrics?.cpu.load_avg}
              />
              <MetricsOverview metrics={currentMetrics} />
              <RealtimeCharts history={history} />
            </div>
          )}

          {currentTab === 'services' && (
            <div className="max-w-7xl mx-auto">
              <ServiceTable />
            </div>
          )}

          {currentTab === 'containers' && (
            <div className="max-w-7xl mx-auto">
              <Tabs
                defaultActiveKey="containers"
                items={[
                  {
                    key: 'containers',
                    label: (
                      <span>
                        <ContainerOutlined /> Containers
                      </span>
                    ),
                    children: <ContainerList />,
                  },
                  {
                    key: 'quadlets',
                    label: (
                      <span>
                        <AppstoreAddOutlined /> Systemd Quadlets
                      </span>
                    ),
                    children: <QuadletManager />,
                  },
                ]}
              />
            </div>
          )}

          {currentTab === 'storage' && (
            <div className="max-w-7xl mx-auto">
              <StorageView />
            </div>
          )}

          {currentTab === 'network' && (
            <div className="max-w-7xl mx-auto">
              <NetworkView />
            </div>
          )}

          {currentTab === 'terminal' && (
            <div className="h-full">
              <WebTerminal cwd={terminalCwd} />
            </div>
          )}

          {currentTab === 'files' && (
            <div className="max-w-[1400px] mx-auto">
              <FilesView onOpenTerminal={hasRole(user, tabRole('terminal')) ? openTerminalAt : undefined} />
            </div>
          )}

          {currentTab === 'access' && (
            <div className="max-w-7xl mx-auto">
              <AccessControlView />
            </div>
          )}

          {currentTab === 'audit' && (
            <div className="max-w-7xl mx-auto">
              <AuditView />
            </div>
          )}

          {currentTab === 'users' && (
            <div className="max-w-7xl mx-auto">
              <UsersView />
            </div>
          )}
        </Content>
      </Layout>

      <BottomNav currentTab={currentTab} onSelectTab={selectTab} currentMetrics={currentMetrics} connected={connected} />
    </Layout>
  );
};

const AuthGate: React.FC = () => {
  const { user, checking, refresh, logout } = useAuth();

  if (checking) {
    return (
      <div className="h-[100dvh] w-screen flex items-center justify-center bg-canvas">
        <Spin size="large" />
      </div>
    );
  }

  if (!user) return <LoginPage />;

  if (user.mfa_setup_required) return <MfaEnrollmentPage onDone={refresh} onLogout={logout} />;

  return (
    <ServerProvider>
      <MainContent />
    </ServerProvider>
  );
};

export const App: React.FC = () => (
  <ThemeProvider>
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  </ThemeProvider>
);

export default App;
