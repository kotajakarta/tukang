import React, { useEffect, useState } from 'react';
import { Card, Table, Progress, Tag, Button, Space, Modal, message } from 'antd';
import { HddOutlined, ReloadOutlined, MedicineBoxOutlined, FolderOutlined } from '@ant-design/icons';
import { StorageOverview, BlockDevice, FilesystemMount } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useTheme } from '../../context/ThemeContext';

export const StorageView: React.FC = () => {
  const { palette } = useTheme();
  const { activeServer } = useServer();
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // SMART Modal
  const [smartOpen, setSmartOpen] = useState<boolean>(false);
  const [smartData, setSmartData] = useState<any>(null);
  const [loadingSmart, setLoadingSmart] = useState<boolean>(false);
  const [selectedDevice, setSelectedDevice] = useState<string>('');

  const fetchStorage = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getStorage(activeServer.id);
      setStorage(data);
    } catch (e: any) {
      message.error('Failed to load storage data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStorage();
  }, [activeServer?.id]);

  const handleOpenSmart = async (device: string) => {
    if (!activeServer) return;
    setSelectedDevice(device);
    setSmartOpen(true);
    try {
      setLoadingSmart(true);
      const res = await api.getSmart(activeServer.id, device);
      setSmartData(res);
    } catch (e) {
      setSmartData({ raw_output: 'Failed to query SMART data' });
    } finally {
      setLoadingSmart(false);
    }
  };

  const fsColumns = [
    {
      title: 'Mounted On',
      dataIndex: 'mounted_on',
      key: 'mounted_on',
      render: (m: string) => (
        <span className="font-semibold text-accent font-mono">
          <FolderOutlined className="mr-1 text-fg-muted" />
          {m}
        </span>
      ),
    },
    {
      title: 'Device',
      dataIndex: 'filesystem',
      key: 'filesystem',
      render: (f: string) => <span className="text-xs text-fg-muted font-mono">{f}</span>,
    },
    {
      title: 'Type',
      dataIndex: 'type',
      key: 'type',
      render: (t: string) => <Tag color="geekblue" className="text-xs font-mono">{t}</Tag>,
    },
    {
      title: 'Size',
      key: 'size',
      render: (_: any, r: FilesystemMount) => (
        <span className="text-xs font-mono">
          {Math.round((r.used_kb / 1024 / 1024) * 10) / 10} GB / {Math.round((r.size_kb / 1024 / 1024) * 10) / 10} GB
        </span>
      ),
    },
    {
      title: 'Usage',
      dataIndex: 'percent',
      key: 'percent',
      render: (p: string) => {
        const val = parseInt(p.replace('%', ''), 10) || 0;
        return (
          <div className="w-48">
            <Progress
              percent={val}
              size="small"
              strokeColor={val > 90 ? palette.danger : val > 75 ? palette.warning : palette.accent}
            />
          </div>
        );
      },
    },
  ];

  const devColumns = [
    {
      title: 'Disk / Partition',
      dataIndex: 'name',
      key: 'name',
      render: (n: string) => <span className="font-mono font-bold text-fg">/dev/{n}</span>,
    },
    {
      title: 'Size',
      dataIndex: 'size',
      key: 'size',
      render: (s: string) => <span className="text-xs font-mono text-fg">{s}</span>,
    },
    {
      title: 'Type',
      dataIndex: 'type',
      key: 'type',
      render: (t: string) => <Tag color="cyan" className="uppercase text-xs">{t}</Tag>,
    },
    {
      title: 'Mount Point',
      key: 'mount',
      render: (_: any, r: BlockDevice) => {
        const mp = r.mountpoint || (r.mountpoints && r.mountpoints.filter(Boolean).join(', '));
        return mp ? <Tag color="blue">{mp}</Tag> : <span className="text-xs text-fg-subtle">—</span>;
      },
    },
    {
      title: 'SMART Health',
      key: 'smart',
      render: (_: any, r: BlockDevice) => {
        if (r.type === 'disk') {
          return (
            <Button
              size="small"
              icon={<MedicineBoxOutlined />}
              onClick={() => handleOpenSmart(r.name)}
            >
              SMART Info
            </Button>
          );
        }
        return null;
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Filesystem Mounts Card */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <FolderOutlined className="text-accent" />
            <span>Filesystems & Mount Points</span>
          </div>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={fetchStorage} loading={loading}>
            Refresh
          </Button>
        }
      >
        <Table
          dataSource={storage?.filesystems || []}
          columns={fsColumns}
          rowKey="mounted_on"
          loading={loading}
          pagination={false}
          size="middle"
          scroll={{ x: 650 }}
        />
      </Card>

      {/* Block Devices Card */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <HddOutlined className="text-purple" />
            <span>Block Storage & Partitions</span>
          </div>
        }
      >
        <Table
          dataSource={storage?.block_devices || []}
          columns={devColumns}
          rowKey="name"
          loading={loading}
          pagination={false}
          size="middle"
          scroll={{ x: 650 }}
        />
      </Card>

      {/* SMART Modal */}
      <Modal
        title={`SMART Health Diagnostics: /dev/${selectedDevice}`}
        open={smartOpen}
        onCancel={() => setSmartOpen(false)}
        width={700}
        footer={[
          <Button key="close" onClick={() => setSmartOpen(false)}>
            Close
          </Button>,
        ]}
      >
        <div className="bg-canvas p-4 rounded-lg font-mono text-xs text-fg h-80 overflow-y-auto whitespace-pre-wrap border border-line">
          {loadingSmart ? (
            'Running SMART diagnostics probe...'
          ) : (
            JSON.stringify(smartData, null, 2)
          )}
        </div>
      </Modal>
    </div>
  );
};
