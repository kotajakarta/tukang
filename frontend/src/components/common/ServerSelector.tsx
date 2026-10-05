import React, { useState } from 'react';
import { Select, Button, Modal, Form, Input, InputNumber, Radio, Tag, Space, message, Popconfirm, Switch, Drawer } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { Check, ChevronDown, Pencil, Plus, Search } from 'lucide-react';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';
import { api } from '../../services/api';
import { ServerNode } from '../../types/server';
import { StatusDot } from './NodeStatus';

/** Online by inventory status, or the active node while its metrics stream is live */
const isOnline = (s: ServerNode, active: boolean, live: boolean) => s.status === 'online' || (active && live);

interface ServerSelectorProps {
  /** desktop: inline select + Add node button; mobile: a pill that opens a bottom sheet */
  variant?: 'desktop' | 'mobile';
  /** Metrics stream state, so the active node shows as online while it streams */
  live?: boolean;
}

export const ServerSelector: React.FC<ServerSelectorProps> = ({ variant = 'desktop', live = false }) => {
  const { servers, activeServer, setActiveServerId, addServer, updateServer, removeServer } = useServer();
  const can = useCan();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<ServerNode | null>(null);
  const [testing, setTesting] = useState(false);
  const [form] = Form.useForm();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [query, setQuery] = useState('');

  const handleOpenAdd = () => {
    setEditingServer(null);
    form.resetFields();
    form.setFieldsValue({ port: 22, username: 'root', auth_type: 'key' });
    setModalOpen(true);
  };

  const handleOpenEdit = (server: ServerNode, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingServer(server);
    form.resetFields();
    form.setFieldsValue({
      name: server.name,
      host: server.host,
      port: server.port,
      username: server.username,
      auth_type: server.auth_type,
      key_path: server.key_path,
      use_sudo: server.use_sudo,
    });
    setModalOpen(true);
  };

  const handleTestConnection = async () => {
    try {
      const values = await form.validateFields();
      setTesting(true);
      message.loading({ content: 'Testing SSH connectivity...', key: 'test_ssh' });

      // Create a temporary server to test SSH credentials
      const res = await api.createServer({
        name: values.name || 'Temp Test',
        host: values.host,
        port: values.port || 22,
        username: values.username || 'root',
        auth_type: values.auth_type || 'key',
        key_path: values.key_path,
        private_key: values.private_key,
        password: values.password,
        use_sudo: values.use_sudo,
        sudo_password: values.sudo_password,
      });

      try {
        const testRes = await api.testServer(res.id);
        if (testRes.success) {
          message.success({
            content: `Connected! ${testRes.os_info || ''} (${testRes.latency_ms}ms)`,
            key: 'test_ssh',
            duration: 4,
          });
        } else {
          message.error({
            content: `Failed: ${testRes.message}`,
            key: 'test_ssh',
            duration: 5,
          });
        }
      } finally {
        // Always clean up temp server
        await api.deleteServer(res.id);
      }
    } catch (err: any) {
      message.error({ content: err.message || 'Validation failed', key: 'test_ssh' });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      let ok = false;
      if (editingServer) {
        ok = await updateServer(editingServer.id, values);
      } else {
        ok = await addServer(values);
      }
      if (ok) {
        form.resetFields();
        setModalOpen(false);
        setEditingServer(null);
      }
    } catch (err) {}
  };

  const trigger =
    variant === 'mobile' ? (
      <MobileNodeSheet
        servers={servers}
        activeServer={activeServer}
        live={live}
        open={sheetOpen}
        setOpen={setSheetOpen}
        query={query}
        setQuery={setQuery}
        canAdmin={can('admin')}
        onSelect={(id) => {
          setActiveServerId(id);
          setSheetOpen(false);
        }}
        onAdd={() => {
          setSheetOpen(false);
          handleOpenAdd();
        }}
        onEdit={(server, e) => {
          setSheetOpen(false);
          handleOpenEdit(server, e);
        }}
      />
    ) : (
      <>
        <Select
          value={activeServer?.id}
          onChange={setActiveServerId}
          className="w-44 lg:w-56"
          popupMatchSelectWidth={false}
          aria-label="Managed node"
          options={servers.map((s) => ({
            value: s.id,
            label: (
              <div className="flex items-center justify-between gap-3 w-72 py-1">
                <span className="flex items-center gap-2 min-w-0">
                  <StatusDot online={isOnline(s, s.id === activeServer?.id, live)} />
                  <span className="font-medium text-fg truncate">{s.name}</span>
                </span>
                <Space direction="horizontal" size="small">
                  <span className="text-xs text-fg-subtle font-mono">{s.is_local ? 'Local' : s.host}</span>
                  {!s.is_local && can('admin') && (
                    <>
                      <EditOutlined
                        className="text-fg-subtle hover:text-accent ml-1 text-xs cursor-pointer"
                        aria-label={`Edit ${s.name}`}
                        onClick={(e) => handleOpenEdit(s, e)}
                      />
                      <Popconfirm
                        title="Remove node?"
                        description="The node is removed from the inventory. Nothing on the node itself changes."
                        okText="Remove"
                        okButtonProps={{ danger: true }}
                        onConfirm={(e) => {
                          e?.stopPropagation();
                          removeServer(s.id);
                        }}
                        onPopupClick={(e) => e.stopPropagation()}
                      >
                        <DeleteOutlined
                          className="text-fg-subtle hover:text-danger ml-1 text-xs cursor-pointer"
                          aria-label={`Remove ${s.name}`}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>
                    </>
                  )}
                </Space>
              </div>
            ),
          }))}
        />

        {can('admin') && (
          <Button icon={<PlusOutlined />} onClick={handleOpenAdd}>
            Add node
          </Button>
        )}
      </>
    );

  return (
    <div className={variant === 'mobile' ? 'min-w-0 flex-1 flex' : 'flex items-center gap-2'}>
      {trigger}

      <Modal
        title={editingServer ? `Edit node: ${editingServer.name}` : 'Add node'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setEditingServer(null);
        }}
        footer={[
          <Button key="test" icon={<ThunderboltOutlined />} loading={testing} onClick={handleTestConnection}>
            Test connection
          </Button>,
          <Button key="cancel" onClick={() => {
            setModalOpen(false);
            setEditingServer(null);
          }}>
            Cancel
          </Button>,
          <Button key="submit" type="primary" onClick={handleSave}>
            {editingServer ? 'Save changes' : 'Add node'}
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" initialValues={{ port: 22, username: 'root', auth_type: 'key' }}>
          <Form.Item name="name" label="Display Name" rules={[{ required: true, message: 'Please enter node name' }]}>
            <Input placeholder="e.g. Database-Prod-01" />
          </Form.Item>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2">
              <Form.Item name="host" label="Host / IP Address" rules={[{ required: true, message: 'Enter hostname or IP' }]}>
                <Input placeholder="192.168.1.100 or srv.domain.com" />
              </Form.Item>
            </div>
            <div>
              <Form.Item name="port" label="SSH Port" rules={[{ required: true }]}>
                <InputNumber min={1} max={65535} className="w-full" />
              </Form.Item>
            </div>
          </div>
          <Form.Item name="username" label="SSH Username" rules={[{ required: true }]}>
            <Input placeholder="root" />
          </Form.Item>
          <Form.Item
            name="use_sudo"
            label="Elevate with sudo"
            valuePropName="checked"
            extra="Recommended: log in as a dedicated non-root user with sudo. Every command then appears in the node's sudo log."
          >
            <Switch />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.use_sudo !== curr.use_sudo}>
            {({ getFieldValue }) =>
              getFieldValue('use_sudo') && (
                <Form.Item
                  name="sudo_password"
                  label={
                    editingServer?.has_sudo_password
                      ? 'Sudo Password (stored — leave blank to keep)'
                      : 'Sudo Password (optional)'
                  }
                  extra="Leave empty if this user has passwordless sudo (NOPASSWD). Stored encrypted; turning sudo off forgets it."
                  rules={[{ pattern: /^[^\r\n]*$/, message: 'Must be a single line' }]}
                >
                  <Input.Password placeholder="Password for sudo" autoComplete="new-password" />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item name="auth_type" label="Authentication Type">
            <Radio.Group>
              <Radio.Button value="key">Private Key</Radio.Button>
              <Radio.Button value="password">Password</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, curr) => prev.auth_type !== curr.auth_type}
          >
            {({ getFieldValue }) =>
              getFieldValue('auth_type') === 'key' ? (
                <>
                  <Form.Item name="key_path" label="Key Path on Master Node (Optional)">
                    <Input placeholder="/root/.ssh/id_rsa or /home/user/.ssh/id_ed25519" />
                  </Form.Item>
                  <Form.Item
                    name="private_key"
                    label={
                      editingServer?.has_private_key
                        ? 'Private Key (stored — paste a new one to replace, leave blank to keep)'
                        : 'Or Paste Private Key (PEM format)'
                    }
                  >
                    <Input.TextArea rows={4} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..." />
                  </Form.Item>
                </>
              ) : (
                <Form.Item
                  name="password"
                  label={editingServer ? "SSH Password (leave blank to keep unchanged)" : "SSH Password"}
                  rules={editingServer ? [] : [{ required: true, message: 'Please enter password' }]}
                >
                  <Input.Password placeholder="Enter SSH user password" />
                </Form.Item>
              )
            }
          </Form.Item>

          {editingServer && (
            <div className="flex items-center justify-between gap-2 text-xs text-fg-muted border-t border-line pt-3">
              <div className="min-w-0">
                <div className="font-semibold text-fg">SSH host key</div>
                <div className="font-mono truncate">
                  {editingServer.host_key_fingerprint || 'Not pinned yet (pinned on next connection)'}
                </div>
              </div>
              {editingServer.host_key_fingerprint && (
                <Popconfirm
                  title="Forget pinned host key?"
                  description="Only do this if the server was reinstalled. The next key seen will be trusted."
                  okText="Reset"
                  okButtonProps={{ danger: true }}
                  onConfirm={async () => {
                    const updated = await api.resetHostKey(editingServer.id);
                    setEditingServer(updated);
                    message.success('Host key reset');
                  }}
                >
                  <Button size="small" danger>
                    Reset
                  </Button>
                </Popconfirm>
              )}
            </div>
          )}
        </Form>
      </Modal>
    </div>
  );
};

interface MobileNodeSheetProps {
  servers: ServerNode[];
  activeServer: ServerNode | null;
  live: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
  query: string;
  setQuery: (q: string) => void;
  canAdmin: boolean;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onEdit: (server: ServerNode, e: React.MouseEvent) => void;
}

/** Mobile: the active node as a pill; tapping it opens a bottom sheet to switch nodes */
const MobileNodeSheet: React.FC<MobileNodeSheetProps> = ({
  servers,
  activeServer,
  live,
  open,
  setOpen,
  query,
  setQuery,
  canAdmin,
  onSelect,
  onAdd,
  onEdit,
}) => {
  const q = query.trim().toLowerCase();
  const shown = q ? servers.filter((s) => `${s.name} ${s.host}`.toLowerCase().includes(q)) : servers;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={activeServer ? `Managed node: ${activeServer.name}. Switch node` : 'Choose a node'}
        className="focus-ring flex items-center gap-2 min-w-0 max-w-full h-9 pl-3 pr-2 rounded-full bg-surface-2 border border-line text-fg cursor-pointer font-[inherit]"
      >
        {activeServer && <StatusDot online={isOnline(activeServer, true, live)} />}
        <span className="truncate text-sm font-medium">{activeServer?.name || 'Choose node'}</span>
        <ChevronDown size={16} strokeWidth={1.75} className="text-fg-subtle flex-shrink-0" />
      </button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        placement="bottom"
        height="auto"
        rootClassName="bottom-sheet"
        closable={false}
        title={null}
        styles={{ content: { maxHeight: '85vh' } }}
      >
        <div className="flex justify-center pt-2 pb-1" aria-hidden>
          <span className="h-1 w-9 rounded-full bg-line" />
        </div>
        <div className="flex items-center justify-between px-4 pt-1 pb-3">
          <h2 className="m-0 text-base font-semibold text-fg">Switch node</h2>
          {canAdmin && (
            <Button size="small" icon={<Plus size={14} />} onClick={onAdd}>
              Add node
            </Button>
          )}
        </div>
        {servers.length > 6 && (
          <div className="px-4 pb-2">
            <Input
              allowClear
              prefix={<Search size={15} className="text-fg-subtle" />}
              placeholder="Search nodes"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        )}
        <ul className="list-none m-0 p-0 pb-3" role="listbox" aria-label="Nodes">
          {shown.map((s) => {
            const active = s.id === activeServer?.id;
            return (
              <li key={s.id} role="option" aria-selected={active} className="flex items-center">
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  className={`focus-ring flex-1 min-w-0 flex items-center gap-3 min-h-[56px] px-4 text-left cursor-pointer font-[inherit] ${
                    active ? 'bg-accent/10' : 'bg-transparent active:bg-surface-2'
                  }`}
                >
                  <StatusDot online={isOnline(s, active, live)} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] text-fg">{s.name}</span>
                    <span className="block truncate text-xs text-fg-subtle">{s.is_local ? 'Local host' : `${s.host}:${s.port}`}</span>
                  </span>
                  {active && <Check size={18} className="text-accent flex-shrink-0" aria-hidden />}
                </button>
                {canAdmin && !s.is_local && (
                  <button
                    type="button"
                    onClick={(e) => onEdit(s, e)}
                    aria-label={`Edit ${s.name}`}
                    className="focus-ring h-12 w-12 mr-1 inline-flex items-center justify-center rounded-md bg-transparent text-fg-subtle cursor-pointer active:bg-surface-2"
                  >
                    <Pencil size={16} strokeWidth={1.75} />
                  </button>
                )}
              </li>
            );
          })}
          {shown.length === 0 && <li className="px-4 py-6 text-sm text-fg-muted">No node matches “{query}”.</li>}
        </ul>
      </Drawer>
    </>
  );
};
