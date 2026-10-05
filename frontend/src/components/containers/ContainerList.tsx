import React, { useEffect, useState } from 'react';
import { Table, Tag, Button, Space, message, Popconfirm, Tooltip } from 'antd';
import {
  ReloadOutlined,
  CaretRightOutlined,
  PauseOutlined,
  RedoOutlined,
  DeleteOutlined,
  FileTextOutlined,
  ContainerOutlined,
} from '@ant-design/icons';
import { PodmanContainer } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';
import { FileText, Play, RotateCw, Square, Trash2 } from 'lucide-react';
import { useIsMobile } from '../../hooks/useIsMobile';
import { ActionSheet, ResourceList, ResourceRow, SheetAction, Tone } from '../common/MobileList';
import { LogModal } from '../common/LogModal';

const containerName = (c: PodmanContainer) => (c.names && c.names.length > 0 ? c.names[0] : c.id);

// Shown when systemd (Quadlet) owns the container; start/stop/restart then go through its unit
const serviceBadge = (c: PodmanContainer) =>
  c.systemd_unit ? (
    <Tag color="gold" className="m-0">
      Service
    </Tag>
  ) : null;

const containerTone = (c: PodmanContainer): Tone =>
  c.state === 'running' ? 'success' : c.state === 'exited' || c.state === 'created' ? 'neutral' : 'warning';

// systemd-managed (Quadlet) containers first, then by name
const byServiceThenName = (a: PodmanContainer, b: PodmanContainer) =>
  Number(!!b.systemd_unit) - Number(!!a.systemd_unit) || containerName(a).localeCompare(containerName(b));

export const ContainerList: React.FC = () => {
  const { activeServer } = useServer();
  const can = useCan();
  const [containers, setContainers] = useState<PodmanContainer[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  // Action in flight per container id: stop/restart can take the container's whole StopTimeout (10s+)
  const [pending, setPending] = useState<Record<string, string>>({});

  // Logs modal state
  const [logsModalOpen, setLogsModalOpen] = useState<boolean>(false);
  const [selectedContainer, setSelectedContainer] = useState<PodmanContainer | null>(null);
  const [containerLogs, setContainerLogs] = useState<string[]>([]);
  const [loadingLogs, setLoadingLogs] = useState<boolean>(false);
  const isMobile = useIsMobile();
  const [sheet, setSheet] = useState<PodmanContainer | null>(null);

  const fetchContainers = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getContainers(activeServer.id);
      setContainers([...data].sort(byServiceThenName));
    } catch (e: any) {
      message.error('Failed to load Podman containers');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContainers();
  }, [activeServer?.id]);

  const handleAction = async (c: PodmanContainer, action: string) => {
    if (!activeServer || pending[c.id]) return;
    const key = `cnt_action_${c.id}`;
    setPending((p) => ({ ...p, [c.id]: action }));
    try {
      message.loading({ content: `${action[0].toUpperCase()}${action.slice(1)} ${containerName(c)}...`, key, duration: 0 });
      const res = await api.containerAction(activeServer.id, c.id, action);
      if (res.success) {
        message.success({ content: res.message, key });
        await fetchContainers();
      } else {
        message.error({ content: res.message, key });
      }
    } catch (e: any) {
      message.error({ content: e.message || 'Action failed', key });
    } finally {
      setPending((p) => {
        const { [c.id]: _, ...rest } = p;
        return rest;
      });
    }
  };

  const handleOpenLogs = async (record: PodmanContainer) => {
    setSelectedContainer(record);
    setLogsModalOpen(true);
    if (!activeServer) return;
    try {
      setLoadingLogs(true);
      const res = await api.getContainerLogs(activeServer.id, record.id, 200);
      setContainerLogs(res.logs || []);
    } catch (e) {
      setContainerLogs(['Failed to load container logs.']);
    } finally {
      setLoadingLogs(false);
    }
  };

  const logsModal = (
    <LogModal
      open={logsModalOpen}
      onClose={() => setLogsModalOpen(false)}
      title={
        <span className="flex items-center gap-2 min-w-0">
          <span className="text-fg-muted font-normal">Logs</span>
          <span className="font-mono text-sm truncate">{selectedContainer ? containerName(selectedContainer) : ''}</span>
        </span>
      }
      lines={containerLogs}
      loading={loadingLogs}
      emptyText="No logs for this container."
      desktopWidth={850}
      toolbar={
        selectedContainer && (
          <Button icon={<RotateCw size={14} />} onClick={() => handleOpenLogs(selectedContainer)} loading={loadingLogs}>
            Refresh
          </Button>
        )
      }
    />
  );

  if (isMobile) {
    // Services first (list is pre-sorted); within each group, unusual states (restarting, paused, dead) first,
    // since on a phone you are usually here because something broke
    const shown = [...containers].sort(
      (a, b) =>
        Number(!!b.systemd_unit) - Number(!!a.systemd_unit) ||
        Number(containerTone(b) === 'warning') - Number(containerTone(a) === 'warning'),
    );
    const running = containers.filter((c) => c.state === 'running').length;

    const sheetActions: SheetAction[] =
      sheet && can('operator')
        ? [
            sheet.state === 'running'
              ? {
                  key: 'stop',
                  label: 'Stop',
                  icon: <Square size={18} />,
                  danger: true,
                  confirm: { title: `Stop ${containerName(sheet)}?` },
                  onClick: () => handleAction(sheet, 'stop'),
                }
              : { key: 'start', label: 'Start', icon: <Play size={18} />, onClick: () => handleAction(sheet, 'start') },
            {
              key: 'restart',
              label: 'Restart',
              icon: <RotateCw size={18} />,
              confirm: { title: `Restart ${containerName(sheet)}?` },
              onClick: () => handleAction(sheet, 'restart'),
            },
            { key: 'logs', label: 'View logs', icon: <FileText size={18} />, onClick: () => handleOpenLogs(sheet) },
            // A Quadlet container is removed by stopping its service; the backend refuses a plain remove
            ...(sheet.systemd_unit ? [] : [{
              key: 'remove',
              label: 'Remove',
              icon: <Trash2 size={18} />,
              danger: true,
              confirm: { title: `Remove ${containerName(sheet)}?`, content: 'The container is force-removed. Its image and volumes are kept.' },
              onClick: () => handleAction(sheet, 'remove'),
            }]),
          ]
        : [];

    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="m-0 text-base font-semibold text-fg">Containers</h2>
            {!loading && (
              <p className="m-0 text-xs text-fg-muted">
                {running} of {containers.length} running
              </p>
            )}
          </div>
          <Button icon={<RotateCw size={16} />} onClick={fetchContainers} loading={loading} aria-label="Refresh" />
        </div>

        <ResourceList
          items={shown}
          loading={loading}
          rowKey={(c) => c.id}
          emptyText="No containers on this node"
          renderRow={(c) => (
            <ResourceRow
              tone={containerTone(c)}
              title={containerName(c)}
              badge={serviceBadge(c)}
              subtitle={c.image}
              state={c.status || c.state}
              onClick={() => setSheet(c)}
            />
          )}
        />

        {sheet && (
          <ActionSheet
            open={!!sheet}
            onClose={() => setSheet(null)}
            title={containerName(sheet)}
            badge={serviceBadge(sheet)}
            subtitle={sheet.image}
            tone={containerTone(sheet)}
            state={sheet.status || sheet.state}
            details={[
              { label: 'ID', value: <span className="font-mono">{sheet.id.slice(0, 12)}</span> },
              { label: 'Type', value: sheet.is_rootless ? 'Rootless' : 'System' },
              ...(sheet.systemd_unit
                ? [{ label: 'Service', value: <span className="font-mono">{sheet.systemd_unit}</span> }]
                : []),
            ]}
            actions={sheetActions}
          />
        )}
        {logsModal}
      </div>
    );
  }

  const columns = [
    {
      title: 'Container Name',
      key: 'name',
      render: (_: any, r: PodmanContainer) => (
        <div>
          <span className="font-semibold text-fg">
            {r.names && r.names.length > 0 ? r.names[0] : r.id}
          </span>
          <div className="text-xs text-fg-muted font-mono">ID: {r.id}</div>
        </div>
      ),
    },
    {
      title: 'Image',
      dataIndex: 'image',
      key: 'image',
      render: (img: string) => <Tag color="geekblue" className="font-mono text-xs">{img}</Tag>,
    },
    {
      title: 'State',
      key: 'state',
      render: (_: any, r: PodmanContainer) => {
        const isRunning = r.state === 'running';
        return (
          <Space direction="vertical" size={2}>
            <Tag color={isRunning ? 'success' : 'default'} className="px-2 py-0">
              {r.state.toUpperCase()}
            </Tag>
            <span className="text-[11px] text-fg-muted">{r.status}</span>
          </Space>
        );
      },
    },
    {
      title: 'Type',
      key: 'type',
      render: (_: any, r: PodmanContainer) => (
        <Space size={4} wrap>
          <Tag color={r.is_rootless ? 'cyan' : 'purple'}>
            {r.is_rootless ? 'Rootless' : 'System'}
          </Tag>
          {r.systemd_unit && (
            <Tooltip title={`${r.is_rootless ? 'systemctl --user' : 'systemctl'} status ${r.systemd_unit}`}>
              {serviceBadge(r)}
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: any, r: PodmanContainer) => {
        const isRunning = r.state === 'running';
        const busy = pending[r.id];
        return (
          <Space direction="horizontal" size="small">
            {isRunning ? (
              <Popconfirm title={`Stop ${containerName(r)}?`} okText="Stop" onConfirm={() => handleAction(r, 'stop')} disabled={!!busy}>
                <Button size="small" danger icon={<PauseOutlined />} loading={busy === 'stop'} disabled={!!busy && busy !== 'stop'}>
                  Stop
                </Button>
              </Popconfirm>
            ) : (
              <Button
                size="small"
                type="primary"
                icon={<CaretRightOutlined />}
                loading={busy === 'start'}
                disabled={!!busy && busy !== 'start'}
                onClick={() => handleAction(r, 'start')}
              >
                Start
              </Button>
            )}

            <Popconfirm title={`Restart ${containerName(r)}?`} okText="Restart" onConfirm={() => handleAction(r, 'restart')} disabled={!!busy}>
              <Button size="small" icon={<RedoOutlined />} loading={busy === 'restart'} disabled={!!busy && busy !== 'restart'}>
                Restart
              </Button>
            </Popconfirm>

            <Button
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => handleOpenLogs(r)}
            >
              Logs
            </Button>

            {r.systemd_unit ? (
              <Tooltip title={`Managed by ${r.systemd_unit}: stop the service, or delete its Quadlet file to remove it`}>
                <Button size="small" danger icon={<DeleteOutlined />} disabled />
              </Tooltip>
            ) : (
              <Popconfirm
                title="Remove Container?"
                description="This will forcefully remove this container."
                onConfirm={() => handleAction(r, 'remove')}
                disabled={!!busy}
              >
                <Button size="small" danger icon={<DeleteOutlined />} loading={busy === 'remove'} disabled={!!busy && busy !== 'remove'} />
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2 text-fg font-semibold">
          <ContainerOutlined className="text-accent" />
          <span>Active & Stopped Podman Containers</span>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchContainers} loading={loading}>
          Refresh Containers
        </Button>
      </div>

      <Table
        dataSource={containers}
        // Start/stop/restart and log access need the operator role
        columns={can('operator') ? columns : columns.filter((c) => c.title !== 'Actions')}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 8 }}
        size="middle"
        scroll={{ x: 700 }}
      />

      {logsModal}
    </div>
  );
};
