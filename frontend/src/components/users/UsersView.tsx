import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input,
  Switch, message, Popconfirm, List, Typography
} from 'antd';
import {
  TeamOutlined, PlusOutlined, DeleteOutlined, KeyOutlined,
  ReloadOutlined, UserOutlined, SafetyOutlined
} from '@ant-design/icons';
import { SystemUser } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';

const { Text } = Typography;

export const UsersView: React.FC = () => {
  const { activeServer } = useServer();
  const can = useCan();
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [showSystem, setShowSystem] = useState<boolean>(false);

  // Add User Modal
  const [addUserOpen, setAddUserOpen] = useState<boolean>(false);
  const [addForm] = Form.useForm();

  // SSH Key Modal
  const [keysModalOpen, setKeysModalOpen] = useState<boolean>(false);
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [keys, setKeys] = useState<string[]>([]);
  const [newKey, setNewKey] = useState<string>('');
  const [loadingKeys, setLoadingKeys] = useState<boolean>(false);

  const fetchUsers = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getUsers(activeServer.id);
      setUsers(data);
    } catch (e: any) {
      message.error('Failed to load user accounts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [activeServer?.id]);

  const handleCreateUser = async () => {
    if (!activeServer) return;
    try {
      const values = await addForm.validateFields();
      message.loading({ content: 'Creating system user...', key: 'create_usr' });
      const res = await api.createUser(activeServer.id, values.username, values.shell, values.is_sudo);
      message.success({ content: res.message, key: 'create_usr' });
      setAddUserOpen(false);
      addForm.resetFields();
      await fetchUsers();
    } catch (e: any) {
      message.error({ content: e.response?.data?.detail || 'Failed to create user', key: 'create_usr' });
    }
  };

  const handleDeleteUser = async (username: string) => {
    if (!activeServer) return;
    try {
      message.loading({ content: `Deleting user ${username}...`, key: 'del_usr' });
      const res = await api.deleteUser(activeServer.id, username, true);
      message.success({ content: res.message, key: 'del_usr' });
      await fetchUsers();
    } catch (e: any) {
      message.error({ content: e.response?.data?.detail || 'Failed to delete user', key: 'del_usr' });
    }
  };

  const handleOpenKeys = async (username: string) => {
    if (!activeServer) return;
    setSelectedUser(username);
    setKeysModalOpen(true);
    try {
      setLoadingKeys(true);
      const res = await api.getUserKeys(activeServer.id, username);
      setKeys(res.keys || []);
    } catch (e) {
      setKeys([]);
    } finally {
      setLoadingKeys(false);
    }
  };

  const handleAddKey = async () => {
    if (!activeServer || !selectedUser || !newKey.trim()) return;
    try {
      const res = await api.addUserKey(activeServer.id, selectedUser, newKey.trim());
      message.success(res.message);
      setNewKey('');
      const updated = await api.getUserKeys(activeServer.id, selectedUser);
      setKeys(updated.keys || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to add SSH key');
    }
  };

  const filteredUsers = users.filter((u) => (showSystem ? true : !u.is_system));

  const columns = [
    {
      title: 'Username',
      dataIndex: 'username',
      key: 'username',
      render: (u: string, r: SystemUser) => (
        <div className="flex items-center gap-2">
          <UserOutlined className="text-accent" />
          <span className="font-bold text-fg">{u}</span>
          {r.uid === 0 && <Tag color="gold">Root</Tag>}
          {r.is_sudo && r.uid !== 0 && <Tag color="purple"><SafetyOutlined /> Sudo</Tag>}
        </div>
      ),
    },
    {
      title: 'UID / GID',
      key: 'uid',
      render: (_: any, r: SystemUser) => (
        <span className="font-mono text-xs text-fg-muted">{r.uid}:{r.gid}</span>
      ),
    },
    {
      title: 'Home Directory',
      dataIndex: 'home',
      key: 'home',
      render: (h: string) => <span className="font-mono text-xs text-fg">{h}</span>,
    },
    {
      title: 'Shell',
      dataIndex: 'shell',
      key: 'shell',
      render: (s: string) => <Tag className="font-mono text-xs">{s}</Tag>,
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: any, r: SystemUser) => (
        <Space direction="horizontal" size="small">
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => handleOpenKeys(r.username)}
          >
            SSH Keys
          </Button>

          {can('admin') && r.uid >= 1000 && (
            <Popconfirm
              title={`Delete user '${r.username}'?`}
              description="This will remove the user and their home directory."
              onConfirm={() => handleDeleteUser(r.username)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <div className="flex items-center gap-2">
          <TeamOutlined className="text-accent" />
          <span>Linux User Accounts & Privileges</span>
        </div>
      }
      extra={
        <Space wrap size="small">
          <div className="flex items-center gap-1.5 text-xs text-fg-muted mr-1 sm:mr-3">
            <span className="hidden sm:inline">Show System Users</span>
            <span className="sm:hidden">System</span>
            <Switch size="small" checked={showSystem} onChange={setShowSystem} />
          </div>
          {can('admin') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setAddUserOpen(true)}
              size="small"
            >
              Add
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={fetchUsers} loading={loading} size="small">
            Refresh
          </Button>
        </Space>
      }
      className="shadow-sm"
    >
      <Table
        dataSource={filteredUsers}
        columns={columns}
        rowKey="username"
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="middle"
        scroll={{ x: 650 }}
      />

      {/* Add User Modal */}
      <Modal
        title="Create New System User"
        open={addUserOpen}
        onCancel={() => setAddUserOpen(false)}
        onOk={handleCreateUser}
        okText="Create User"
      >
        <Form form={addForm} layout="vertical" initialValues={{ shell: '/bin/bash', is_sudo: false }}>
          <Form.Item name="username" label="Username" rules={[{ required: true, message: 'Enter username' }]}>
            <Input placeholder="e.g. deployer" />
          </Form.Item>
          <Form.Item name="shell" label="Default Login Shell" rules={[{ required: true }]}>
            <Input placeholder="/bin/bash" />
          </Form.Item>
          <Form.Item name="is_sudo" label="Grant Sudo Privileges (wheel)" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* SSH Keys Modal */}
      <Modal
        title={`Authorized SSH Keys: ${selectedUser}`}
        open={keysModalOpen}
        onCancel={() => setKeysModalOpen(false)}
        width={750}
        footer={[
          <Button key="close" onClick={() => setKeysModalOpen(false)}>
            Close
          </Button>,
        ]}
      >
        <div className="space-y-4">
          <div>
            <div className="text-xs text-fg-muted font-semibold mb-2">Existing Public Keys:</div>
            <div className="bg-canvas p-3 rounded-lg border border-line max-h-48 overflow-y-auto font-mono text-xs text-fg">
              {loadingKeys ? (
                'Loading keys...'
              ) : keys.length === 0 ? (
                <div className="text-fg-subtle italic">No authorized keys found in ~/.ssh/authorized_keys</div>
              ) : (
                keys.map((k, i) => (
                  <div key={i} className="truncate hover:text-fg py-0.5">
                    {k}
                  </div>
                ))
              )}
            </div>
          </div>

          {can('admin') && <div>
            <div className="text-xs text-fg-muted font-semibold mb-2">Add New Authorized Key:</div>
            <Input.TextArea
              rows={3}
              placeholder="Paste ssh-rsa, ssh-ed25519, or ecdsa public key here..."
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              className="font-mono text-xs"
            />
            <Button
              type="primary"
              className="mt-2"
              icon={<PlusOutlined />}
              onClick={handleAddKey}
              disabled={!newKey.trim()}
            >
              Add SSH Key
            </Button>
          </div>}
        </div>
      </Modal>
    </Card>
  );
};
