import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Button, Space, Row, Col, Badge, message, Input, Select, Popconfirm, Modal, Alert, Tooltip } from 'antd';
import { GlobalOutlined, ReloadOutlined, SafetyCertificateOutlined, ApiOutlined, LockOutlined } from '@ant-design/icons';
import { NetworkOverview, NetworkInterface } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';
import { allowedPortLabel, firewallVerdict } from './firewallMatch';

type ListeningSocket = NetworkOverview['listening_sockets'][number];

// "8080" or "8000-8010" -> [start, end|null]; null when invalid
const parsePortSpec = (spec: string): [number, number | null] | null => {
  const m = spec.trim().match(/^(\d{1,5})(?:\s*[-:]\s*(\d{1,5}))?$/);
  if (!m) return null;
  const start = Number(m[1]);
  const end = m[2] ? Number(m[2]) : null;
  const ok = (p: number) => p >= 1 && p <= 65535;
  if (!ok(start) || (end !== null && (!ok(end) || end < start))) return null;
  return [start, end === start ? null : end];
};

export const NetworkView: React.FC = () => {
  const { activeServer } = useServer();
  const [network, setNetwork] = useState<NetworkOverview | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const can = useCan();
  const [portSpec, setPortSpec] = useState('');
  const [protocol, setProtocol] = useState<'tcp' | 'udp'>('tcp');
  const [allowing, setAllowing] = useState(false);
  // Sudo password prompt: asked per action, kept only until the dialog closes
  const [sudoPrompt, setSudoPrompt] = useState<'rules' | 'allow' | null>(null);
  const [sudoPassword, setSudoPassword] = useState('');
  const [sudoError, setSudoError] = useState<string | null>(null);
  const [sudoBusy, setSudoBusy] = useState(false);
  // Once a node asked for a sudo password, keep asking until the server changes
  const [sudoRequired, setSudoRequired] = useState(false);

  const fetchNetwork = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getNetwork(activeServer.id);
      setNetwork(data);
    } catch (e: any) {
      message.error('Failed to load network details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSudoRequired(false);
    fetchNetwork();
  }, [activeServer?.id]);

  useEffect(() => {
    if (network?.firewall.needs_sudo) setSudoRequired(true);
  }, [network?.firewall.needs_sudo]);

  const parsedPort = parsePortSpec(portSpec);
  const portLabel = parsedPort ? `${parsedPort[0]}${parsedPort[1] ? `-${parsedPort[1]}` : ''}/${protocol}` : '';
  // Only firewalld and ufw have a standard "open a port" command; nftables rulesets are hand-written
  const canAllowPorts =
    can('admin') && !!network?.firewall.active && ['firewalld', 'ufw'].includes(network.firewall.type);

  const needsSudo = sudoRequired || !!network?.firewall.needs_sudo;

  const closeSudoPrompt = () => {
    setSudoPrompt(null);
    setSudoPassword('');
    setSudoError(null);
  };

  const setFirewall = (firewall: NetworkOverview['firewall']) =>
    setNetwork((prev) => (prev ? { ...prev, firewall } : prev));

  const handleAllowPort = async (password?: string) => {
    if (!activeServer || !parsedPort) return;
    try {
      setAllowing(true);
      const res = await api.allowFirewallPort(activeServer.id, parsedPort[0], parsedPort[1], protocol, password);
      if (res.success) {
        message.success(res.message);
        setPortSpec('');
        closeSudoPrompt();
        if (res.firewall) setFirewall(res.firewall);
        else await fetchNetwork();
      } else if (res.needs_sudo) {
        // Wrong or missing password: ask again in the dialog
        setSudoRequired(true);
        setSudoError(res.message);
        setSudoPassword('');
        setSudoPrompt('allow');
      } else {
        closeSudoPrompt();
        message.error(res.message);
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.[0]?.msg || e.message || 'Failed to allow port');
    } finally {
      setAllowing(false);
    }
  };

  const handleShowRules = async () => {
    if (!activeServer) return;
    try {
      setSudoBusy(true);
      const firewall = await api.readFirewallRules(activeServer.id, sudoPassword);
      // needs_sudo stays true after a password worked, so only a note means the read failed
      if (firewall.needs_sudo && firewall.note) {
        setSudoError(firewall.note);
        setSudoPassword('');
      } else {
        setFirewall(firewall);
        closeSudoPrompt();
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.[0]?.msg || e.message || 'Failed to read firewall rules');
    } finally {
      setSudoBusy(false);
    }
  };

  const submitSudo = () => {
    if (!sudoPassword) return;
    if (sudoPrompt === 'rules') handleShowRules();
    else handleAllowPort(sudoPassword);
  };

  const ifaceColumns = [
    {
      title: 'Interface',
      dataIndex: 'ifname',
      key: 'ifname',
      render: (name: string, r: NetworkInterface) => (
        <div>
          <span className="font-bold text-accent font-mono">{name}</span>
          <div className="text-xs text-fg-muted font-mono">MAC: {r.address || 'N/A'}</div>
        </div>
      ),
    },
    {
      title: 'Status',
      key: 'status',
      render: (_: any, r: NetworkInterface) => {
        const isUp = r.flags.includes('UP') || r.operstate === 'UP';
        return <Badge status={isUp ? 'success' : 'default'} text={isUp ? 'UP' : 'DOWN'} />;
      },
    },
    {
      title: 'MTU',
      dataIndex: 'mtu',
      key: 'mtu',
      render: (m: number) => <span className="font-mono text-xs">{m}</span>,
    },
    {
      title: 'IP Addresses',
      key: 'ips',
      render: (_: any, r: NetworkInterface) => {
        const addrs = r.addr_info || [];
        if (addrs.length === 0) return <span className="text-fg-subtle text-xs">No IP assigned</span>;
        return (
          <Space wrap>
            {addrs.map((a, i) => (
              <Tag key={i} color={a.family === 'inet' ? 'blue' : 'purple'} className="font-mono text-xs">
                {a.local}/{a.prefixlen}
              </Tag>
            ))}
          </Space>
        );
      },
    },
  ];

  // Engine runs but its rules (hence the allowed ports) could not be read without root
  const rulesUnread =
    !!network?.firewall.active && network.firewall.allowed_ports == null && network.firewall.type !== 'nftables';
  const allowedPorts = network?.firewall.active ? network.firewall.allowed_ports : null;

  const socketColumns = [
    {
      title: 'Protocol',
      dataIndex: 'proto',
      key: 'proto',
      render: (p: string) => <Tag color={p.toLowerCase().includes('tcp') ? 'blue' : 'orange'} className="uppercase text-xs">{p}</Tag>,
    },
    {
      title: 'Local Address : Port',
      dataIndex: 'local_address',
      key: 'local_address',
      render: (addr: string) => <span className="font-mono text-xs font-semibold text-fg">{addr}</span>,
    },
    {
      title: 'State',
      dataIndex: 'state',
      key: 'state',
      render: (s: string) => <Tag color="green" className="text-xs">{s}</Tag>,
    },
    {
      title: rulesUnread ? (
        <Tooltip title="Firewall rules need root to read: use “Show rules with sudo”.">
          <span>Firewall <LockOutlined className="text-fg-subtle" /></span>
        </Tooltip>
      ) : (
        'Firewall'
      ),
      key: 'firewall',
      render: (_: unknown, r: ListeningSocket) => {
        const v = firewallVerdict(r, network?.firewall);
        if (v.kind === 'allowed')
          return <Tag color="success" className="text-xs">✔ Allowed{v.detail ? ` (${v.detail})` : ''}</Tag>;
        if (v.kind === 'blocked') return <Tag color="error" className="text-xs">✖ Blocked</Tag>;
        if (v.kind === 'local') return <Tag className="text-xs">— Local only</Tag>;
        return <Tag className="text-xs text-fg-subtle">? Unknown</Tag>;
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Network Interfaces */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <GlobalOutlined className="text-accent" />
            <span>Network Interfaces</span>
          </div>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={fetchNetwork} loading={loading}>
            Refresh
          </Button>
        }
      >
        <Table
          dataSource={network?.interfaces || []}
          columns={ifaceColumns}
          rowKey="ifindex"
          loading={loading}
          pagination={false}
          size="middle"
          scroll={{ x: 650 }}
        />
      </Card>

      {/* Sockets and Firewall Row */}
      <Row gutter={[16, 16]}>
        {/* Listening Sockets */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <div className="flex items-center gap-2">
                <ApiOutlined className="text-success" />
                <span>Active Listening Ports & Sockets</span>
              </div>
            }
          >
            <Table
              dataSource={network?.listening_sockets || []}
              columns={socketColumns}
              rowKey={(r, i) => `${r.proto}-${r.local_address}-${i}`}
              loading={loading}
              pagination={{ pageSize: 8 }}
              size="small"
              scroll={{ x: 600 }}
            />
            {allowedPorts && (
              <div className="mt-4">
                <div className="text-sm font-semibold mb-2">
                  Allowed by {network?.firewall.type}
                  {network?.firewall.allow_all && (
                    <span className="font-normal text-fg-muted"> (default policy accepts every port)</span>
                  )}
                </div>
                {allowedPorts.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {allowedPorts.map((p, i) => (
                      <Tag key={i} className="font-mono text-xs">
                        {allowedPortLabel(p)}
                        {p.name && <span className="text-fg-muted"> ({p.name})</span>}
                        {p.source && <span className="text-fg-muted"> from {p.source}</span>}
                      </Tag>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-fg-subtle italic">No ports explicitly allowed.</div>
                )}
              </div>
            )}
          </Card>
        </Col>

        {/* Firewall */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <div className="flex items-center gap-2">
                <SafetyCertificateOutlined className="text-warning" />
                <span>Firewall Configuration</span>
              </div>
            }
          >
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-semibold">Firewall Engine:</span>
              {network?.firewall.type === 'none' ? (
                <Tag>Not detected</Tag>
              ) : (
                <Tag color={network?.firewall.active ? 'success' : 'default'} className="uppercase font-mono">
                  {network?.firewall.type} ({network?.firewall.active ? 'Active' : 'Inactive'})
                </Tag>
              )}
            </div>

            {canAllowPorts && (
              <div className="mb-4">
                <div className="flex flex-wrap gap-2">
                  <Input
                    value={portSpec}
                    onChange={(e) => setPortSpec(e.target.value)}
                    placeholder="Port, e.g. 8080 or 8000-8010"
                    status={portSpec && !parsedPort ? 'error' : undefined}
                    className="font-mono flex-1 min-w-[10rem]"
                    aria-label="Port or port range"
                  />
                  <Select
                    value={protocol}
                    onChange={setProtocol}
                    options={[
                      { value: 'tcp', label: 'TCP' },
                      { value: 'udp', label: 'UDP' },
                    ]}
                    className="w-24"
                    aria-label="Protocol"
                  />
                  {needsSudo ? (
                    // The sudo dialog doubles as the confirmation
                    <Button type="primary" disabled={!parsedPort} loading={allowing} onClick={() => setSudoPrompt('allow')}>
                      Allow port
                    </Button>
                  ) : (
                    <Popconfirm
                      title={`Allow ${portLabel}?`}
                      description={`Opens it in ${network?.firewall.type} on ${activeServer?.name ?? 'this server'}, now and after reboot.`}
                      onConfirm={() => handleAllowPort()}
                      okText="Allow"
                      disabled={!parsedPort}
                    >
                      <Button type="primary" disabled={!parsedPort} loading={allowing}>
                        Allow port
                      </Button>
                    </Popconfirm>
                  )}
                </div>
                {portSpec && !parsedPort && (
                  <div className="text-xs text-danger mt-1">Enter a port (1-65535) or a range like 8000-8010.</div>
                )}
              </div>
            )}

            <div className="bg-canvas p-3 rounded-lg font-mono text-xs text-fg h-64 overflow-y-auto border border-line leading-relaxed">
              {network?.firewall.rules && network.firewall.rules.length > 0 ? (
                network.firewall.rules.map((rule, idx) => <div key={idx}>{rule}</div>)
              ) : (
                <div className="text-fg-subtle italic">
                  {network?.firewall.note || 'No custom firewall rules configured.'}
                  {needsSudo && can('admin') && (
                    <div className="mt-3 not-italic">
                      <Button size="small" icon={<LockOutlined />} onClick={() => setSudoPrompt('rules')}>
                        Show rules with sudo
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </Card>

          <Modal
            open={sudoPrompt !== null}
            title={
              <span className="flex items-center gap-2">
                <LockOutlined />
                {sudoPrompt === 'allow' ? `Allow ${portLabel}` : 'Show firewall rules'}
              </span>
            }
            onCancel={closeSudoPrompt}
            onOk={submitSudo}
            okText={sudoPrompt === 'allow' ? 'Allow' : 'Show rules'}
            okButtonProps={{ disabled: !sudoPassword, loading: sudoBusy || allowing }}
            destroyOnClose
            centered
          >
            <p className="text-sm text-fg-muted mt-0">
              {sudoPrompt === 'allow'
                ? `Opens ${portLabel} in ${network?.firewall.type} on ${activeServer?.name ?? 'this server'}, now and after reboot. `
                : ''}
              Enter the sudo password for <span className="font-mono">{activeServer?.username}</span>. It is used for
              this action only and is not saved.
            </p>
            {sudoError && <Alert type="error" showIcon message={sudoError} className="mb-3" />}
            <Input.Password
              autoFocus
              value={sudoPassword}
              onChange={(e) => setSudoPassword(e.target.value)}
              onPressEnter={submitSudo}
              placeholder="Sudo password"
              autoComplete="new-password"
              aria-label="Sudo password"
            />
          </Modal>
        </Col>
      </Row>
    </div>
  );
};
