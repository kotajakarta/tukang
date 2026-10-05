import React from 'react';
import { Card, Descriptions, Tag, Typography } from 'antd';
import { useIsMobile } from '../../hooks/useIsMobile';
import { HostInfo } from '../../types/metrics';
import { ServerNode } from '../../types/server';
import { ClockCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface HostInfoCardProps {
  server: ServerNode | null;
  hostInfo?: HostInfo;
  loadAvg?: number[];
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m ${Math.floor(seconds % 60)}s`;
}

export const HostInfoCard: React.FC<HostInfoCardProps> = ({ server, hostInfo, loadAvg }) => {
  const isMobile = useIsMobile();
  return (
    <Card
      title={
        <div className="flex items-center gap-2">
          <InfoCircleOutlined className="text-accent" />
          <span>System Information</span>
        </div>
      }
      extra={
        <div className="flex items-center gap-1.5 text-xs text-fg-muted">
          <ClockCircleOutlined />
          <span>Uptime: {hostInfo ? formatUptime(hostInfo.uptime_seconds) : 'Loading...'}</span>
        </div>
      }
      className="shadow-sm"
    >
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, md: 3 }}
        bordered
        // Phones: label above value, so long values (CPU model, kernel) wrap inside the card
        layout={isMobile ? 'vertical' : 'horizontal'}
      >
        <Descriptions.Item label="Hostname">
          <Text strong className="text-accent">{hostInfo?.hostname || server?.name || 'Loading...'}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="Operating System">
          <Tag color="blue">{hostInfo?.os_name || 'Linux'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Kernel Version">
          <span className="font-mono text-xs">{hostInfo?.kernel || 'Unknown'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="CPU Hardware">
          <span className="text-xs truncate max-w-xs">{hostInfo?.cpu_model || 'Standard CPU'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="Load Average (1/5/15m)">
          <div className="flex gap-1.5 font-mono text-xs">
            <span className="bg-surface-2 px-1.5 py-0.5 rounded text-warning">{loadAvg ? loadAvg[0] : 0}</span>
            <span className="bg-surface-2 px-1.5 py-0.5 rounded text-warning">{loadAvg ? loadAvg[1] : 0}</span>
            <span className="bg-surface-2 px-1.5 py-0.5 rounded text-warning">{loadAvg ? loadAvg[2] : 0}</span>
          </div>
        </Descriptions.Item>
        <Descriptions.Item label="Host Connection">
          <Tag color={server?.is_local ? 'cyan' : 'purple'}>
            {server?.is_local ? 'Local Master' : `SSH (${server?.username}@${server?.host}:${server?.port})`}
          </Tag>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
};
