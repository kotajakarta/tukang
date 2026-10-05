import React, { useEffect, useState } from 'react';
import {
  Table, Tag, Button, Input, Select, Space, Card,
  Modal, message, Tooltip, Popconfirm
} from 'antd';
import {
  ReloadOutlined,
  SearchOutlined,
  CaretRightOutlined,
  PauseOutlined,
  RedoOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { SystemdUnit } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';
import { JournalViewerModal } from './JournalViewerModal';
import { FileText, Play, RotateCw, Search, Square } from 'lucide-react';
import { useIsMobile } from '../../hooks/useIsMobile';
import { ActionSheet, ResourceList, ResourceRow, SheetAction, Tone } from '../common/MobileList';

const isFailed = (u: SystemdUnit) => u.active === 'failed' || u.sub === 'failed';

const unitTone = (u: SystemdUnit): Tone =>
  isFailed(u) ? 'danger' : u.active === 'active' ? 'success' : u.active === 'inactive' ? 'neutral' : 'warning';

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'failed', label: 'Failed' },
  { value: 'inactive', label: 'Inactive' },
];

export const ServiceTable: React.FC = () => {
  const { activeServer } = useServer();
  const can = useCan();
  const [units, setUnits] = useState<SystemdUnit[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [search, setSearch] = useState<string>('');
  const [unitType, setUnitType] = useState<string>('service');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Logs modal state
  const [logModalOpen, setLogModalOpen] = useState<boolean>(false);
  const [selectedUnit, setSelectedUnit] = useState<string>('');
  const isMobile = useIsMobile();
  const [sheetUnit, setSheetUnit] = useState<SystemdUnit | null>(null);

  const fetchUnits = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getUnits(activeServer.id, unitType);
      setUnits(data);
    } catch (e: any) {
      message.error('Failed to load systemd units');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUnits();
  }, [activeServer?.id, unitType]);

  const handleAction = async (unit: string, action: string) => {
    if (!activeServer) return;
    try {
      message.loading({ content: `Executing systemctl ${action} ${unit}...`, key: 'sys_action' });
      const res = await api.unitAction(activeServer.id, unit, action);
      if (res.success) {
        message.success({ content: res.message || `${unit} ${action} succeeded`, key: 'sys_action' });
        await fetchUnits();
      } else {
        message.error({ content: res.message || `Failed to ${action} ${unit}`, key: 'sys_action' });
      }
    } catch (e: any) {
      message.error({ content: e.message || 'Action failed', key: 'sys_action' });
    }
  };

  const filteredUnits = units.filter((u) => {
    const matchesSearch =
      u.unit.toLowerCase().includes(search.toLowerCase()) ||
      u.description.toLowerCase().includes(search.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'active' && u.active === 'active') ||
      (statusFilter === 'inactive' && u.active === 'inactive') ||
      (statusFilter === 'failed' && (u.active === 'failed' || u.sub === 'failed'));
    return matchesSearch && matchesStatus;
  });

  const openLogs = (unit: string) => {
    setSelectedUnit(unit);
    setLogModalOpen(true);
  };

  const logsModal = (
    <JournalViewerModal
      open={logModalOpen}
      serverId={activeServer?.id || 'local'}
      unitName={selectedUnit}
      onClose={() => setLogModalOpen(false)}
    />
  );

  if (isMobile) {
    const q = search.toLowerCase();
    const matching = units.filter((u) => u.unit.toLowerCase().includes(q) || u.description.toLowerCase().includes(q));
    const counts: Record<string, number> = {
      all: matching.length,
      active: matching.filter((u) => u.active === 'active').length,
      failed: matching.filter(isFailed).length,
      inactive: matching.filter((u) => u.active === 'inactive').length,
    };
    // Failed units first: on a phone you are usually here because something broke
    const shown = [...filteredUnits].sort((a, b) => Number(isFailed(b)) - Number(isFailed(a)));

    const sheetActions: SheetAction[] =
      sheetUnit && can('operator')
        ? [
            sheetUnit.active === 'active'
              ? {
                  key: 'stop',
                  label: 'Stop',
                  icon: <Square size={18} />,
                  danger: true,
                  confirm: { title: `Stop ${sheetUnit.unit}?`, content: 'The service stays stopped until it is started again.' },
                  onClick: () => handleAction(sheetUnit.unit, 'stop'),
                }
              : { key: 'start', label: 'Start', icon: <Play size={18} />, onClick: () => handleAction(sheetUnit.unit, 'start') },
            {
              key: 'restart',
              label: 'Restart',
              icon: <RotateCw size={18} />,
              confirm: { title: `Restart ${sheetUnit.unit}?`, content: 'Open connections to this service may drop.' },
              onClick: () => handleAction(sheetUnit.unit, 'restart'),
            },
            { key: 'logs', label: 'View logs', icon: <FileText size={18} />, onClick: () => openLogs(sheetUnit.unit) },
          ]
        : [];

    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h1 className="m-0 text-lg font-semibold text-fg">Services</h1>
          <div className="flex items-center gap-2">
            <Select
              value={unitType}
              onChange={setUnitType}
              aria-label="Unit type"
              options={[
                { value: 'service', label: 'Services' },
                { value: 'timer', label: 'Timers' },
                { value: 'socket', label: 'Sockets' },
              ]}
              className="w-28"
            />
            <Button icon={<RotateCw size={16} />} onClick={fetchUnits} loading={loading} aria-label="Refresh" />
          </div>
        </div>
        <Input
          size="large"
          allowClear
          placeholder="Search units"
          prefix={<Search size={16} className="text-fg-subtle" />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="flex gap-2 overflow-x-auto -mx-3 px-3 pb-0.5" role="group" aria-label="Filter by state">
          {STATUS_FILTERS.map((f) => {
            const on = statusFilter === f.value;
            const alert = f.value === 'failed' && counts.failed > 0;
            return (
              <button
                key={f.value}
                type="button"
                aria-pressed={on}
                onClick={() => setStatusFilter(f.value)}
                className={`focus-ring flex-shrink-0 h-8 px-3 rounded-full border text-[13px] font-[inherit] cursor-pointer ${
                  on ? 'bg-accent/15 border-accent/50 text-accent font-medium' : alert ? 'bg-danger/10 border-danger/40 text-danger' : 'bg-surface border-line text-fg-muted'
                }`}
              >
                {f.label} <span className="tabular-nums">{counts[f.value]}</span>
              </button>
            );
          })}
        </div>

        <ResourceList
          items={shown}
          loading={loading}
          rowKey={(u) => u.unit}
          emptyText={search ? `No unit matches “${search}”` : 'No units'}
          renderRow={(u) => (
            <ResourceRow
              tone={unitTone(u)}
              title={u.unit}
              subtitle={u.description}
              state={`${u.active} · ${u.sub}`}
              onClick={() => setSheetUnit(u)}
            />
          )}
        />

        {sheetUnit && (
          <ActionSheet
            open={!!sheetUnit}
            onClose={() => setSheetUnit(null)}
            title={sheetUnit.unit}
            subtitle={sheetUnit.description}
            tone={unitTone(sheetUnit)}
            state={`${sheetUnit.active} · ${sheetUnit.sub}`}
            details={[{ label: 'Load', value: sheetUnit.load }]}
            actions={sheetActions}
          />
        )}
        {logsModal}
      </div>
    );
  }

  const columns = [
    {
      title: 'Unit Name',
      dataKey: 'unit',
      key: 'unit',
      render: (_: any, record: SystemdUnit) => (
        <div>
          <span className="font-semibold text-fg">{record.unit}</span>
          <div className="text-xs text-fg-muted truncate max-w-md">{record.description}</div>
        </div>
      ),
    },
    {
      title: 'Load',
      dataIndex: 'load',
      key: 'load',
      width: 100,
      render: (load: string) => (
        <span className="text-xs text-fg-muted font-mono">{load}</span>
      ),
    },
    {
      title: 'State',
      key: 'state',
      width: 140,
      render: (_: any, record: SystemdUnit) => {
        const isRunning = record.active === 'active' && record.sub === 'running';
        const isFailed = record.active === 'failed' || record.sub === 'failed';
        const color = isRunning ? 'success' : isFailed ? 'error' : 'default';

        return (
          <Space direction="vertical" size={2}>
            <Tag color={color} className="text-xs px-2 py-0">
              {record.active.toUpperCase()}
            </Tag>
            <span className="text-[11px] text-fg-muted font-mono">({record.sub})</span>
          </Space>
        );
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 260,
      render: (_: any, record: SystemdUnit) => {
        const isActive = record.active === 'active';
        return (
          <Space direction="horizontal" size="small">
            {isActive ? (
              <Popconfirm
                title={`Stop ${record.unit}?`}
                onConfirm={() => handleAction(record.unit, 'stop')}
              >
                <Button size="small" danger icon={<PauseOutlined />}>
                  Stop
                </Button>
              </Popconfirm>
            ) : (
              <Button
                size="small"
                type="primary"
                icon={<CaretRightOutlined />}
                onClick={() => handleAction(record.unit, 'start')}
              >
                Start
              </Button>
            )}

            <Button
              size="small"
              icon={<RedoOutlined />}
              onClick={() => handleAction(record.unit, 'restart')}
            >
              Restart
            </Button>

            <Tooltip title="View Journalctl Logs">
              <Button
                size="small"
                icon={<FileTextOutlined />}
                onClick={() => openLogs(record.unit)}
              />
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  return (
    <Card className="shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <Space wrap>
          <Input
            placeholder="Search units..."
            prefix={<SearchOutlined />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          <Select
            value={unitType}
            onChange={setUnitType}
            options={[
              { value: 'service', label: 'Services (.service)' },
              { value: 'timer', label: 'Timers (.timer)' },
              { value: 'socket', label: 'Sockets (.socket)' },
            ]}
            className="w-48"
          />
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'all', label: 'All Statuses' },
              { value: 'active', label: 'Active (Running)' },
              { value: 'inactive', label: 'Inactive' },
              { value: 'failed', label: 'Failed' },
            ]}
            className="w-36"
          />
        </Space>

        <Button icon={<ReloadOutlined />} onClick={fetchUnits} loading={loading}>
          Refresh Units
        </Button>
      </div>

      <Table
        dataSource={filteredUnits}
        // Start/stop/restart and log access need the operator role
        columns={can('operator') ? columns : columns.filter((c) => c.title !== 'Actions')}
        rowKey="unit"
        loading={loading}
        pagination={{ pageSize: 12, showSizeChanger: true }}
        size="middle"
        scroll={{ x: 750 }}
      />

      {logsModal}
    </Card>
  );
};
