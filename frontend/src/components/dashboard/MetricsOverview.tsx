import React from 'react';
import { Card, Progress, Row, Col } from 'antd';
import { SystemMetricsPayload } from '../../types/metrics';
import { DashboardOutlined, DatabaseOutlined, HddOutlined, SwapOutlined } from '@ant-design/icons';
import { useTheme } from '../../context/ThemeContext';

interface MetricsOverviewProps {
  metrics: SystemMetricsPayload | null;
}

function formatBytes(bytes: number, decimals: number = 1): string {
  if (!bytes) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export const MetricsOverview: React.FC<MetricsOverviewProps> = ({ metrics }) => {
  const { palette } = useTheme();
  const cpuPct = metrics?.cpu.usage_percent || 0;
  const memPct = metrics?.memory.percent || 0;
  const memUsed = formatBytes(metrics?.memory.used || 0);
  const memTotal = formatBytes(metrics?.memory.total || 0);

  const diskRead = formatBytes(metrics?.disk_io.read_bytes_sec || 0) + '/s';
  const diskWrite = formatBytes(metrics?.disk_io.write_bytes_sec || 0) + '/s';

  const netRx = formatBytes(metrics?.network.rx_bytes_sec || 0) + '/s';
  const netTx = formatBytes(metrics?.network.tx_bytes_sec || 0) + '/s';

  return (
    <Row gutter={[16, 16]}>
      {/* CPU Card */}
      <Col xs={24} sm={12} lg={6}>
        <Card className="h-full bg-surface border-line hover:border-accent transition-colors">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-fg font-semibold">
              <DashboardOutlined className="text-accent" />
              <span>CPU Usage</span>
            </div>
            <span className="text-xs text-fg-muted">{metrics?.cpu.cores || 1} Cores</span>
          </div>
          <div className="flex items-end justify-between mb-2">
            <span className="text-3xl font-bold font-mono text-fg">{cpuPct}%</span>
            <span className="text-xs text-fg-muted">Total Load</span>
          </div>
          <Progress
            percent={cpuPct}
            showInfo={false}
            strokeColor={cpuPct > 85 ? palette.danger : cpuPct > 65 ? palette.warning : palette.accent}
            trailColor={palette["line-muted"]}
          />
        </Card>
      </Col>

      {/* Memory Card */}
      <Col xs={24} sm={12} lg={6}>
        <Card className="h-full bg-surface border-line hover:border-success transition-colors">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-fg font-semibold">
              <DatabaseOutlined className="text-success" />
              <span>Memory (RAM)</span>
            </div>
            <span className="text-xs text-fg-muted">{memUsed} / {memTotal}</span>
          </div>
          <div className="flex items-end justify-between mb-2">
            <span className="text-3xl font-bold font-mono text-fg">{memPct}%</span>
            <span className="text-xs text-fg-muted">Utilization</span>
          </div>
          <Progress
            percent={memPct}
            showInfo={false}
            strokeColor={memPct > 90 ? palette.danger : memPct > 75 ? palette.warning : palette.success}
            trailColor={palette["line-muted"]}
          />
        </Card>
      </Col>

      {/* Disk I/O Card */}
      <Col xs={24} sm={12} lg={6}>
        <Card className="h-full bg-surface border-line hover:border-purple transition-colors">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-fg font-semibold">
              <HddOutlined className="text-purple" />
              <span>Disk Activity</span>
            </div>
            <span className="text-xs text-fg-muted">Real-time IO</span>
          </div>
          <div className="space-y-2 mt-2">
            <div className="flex justify-between items-center text-xs">
              <span className="text-fg-muted">Read:</span>
              <span className="font-mono text-purple font-semibold">{diskRead}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-fg-muted">Write:</span>
              <span className="font-mono text-purple font-semibold">{diskWrite}</span>
            </div>
          </div>
        </Card>
      </Col>

      {/* Network Traffic Card */}
      <Col xs={24} sm={12} lg={6}>
        <Card className="h-full bg-surface border-line hover:border-cyan transition-colors">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-fg font-semibold">
              <SwapOutlined className="text-cyan" />
              <span>Network Traffic</span>
            </div>
            <span className="text-xs text-fg-muted">Transfer Rates</span>
          </div>
          <div className="space-y-2 mt-2">
            <div className="flex justify-between items-center text-xs">
              <span className="text-fg-muted">Inbound (RX):</span>
              <span className="font-mono text-cyan font-semibold">{netRx}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-fg-muted">Outbound (TX):</span>
              <span className="font-mono text-cyan font-semibold">{netTx}</span>
            </div>
          </div>
        </Card>
      </Col>
    </Row>
  );
};
