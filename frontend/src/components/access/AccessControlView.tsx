import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from 'antd';
import { KeyOutlined, PlusOutlined, ReloadOutlined, SafetyOutlined, TeamOutlined, DeleteOutlined } from '@ant-design/icons';
import { api, AppAccount, Role } from '../../services/api';
import { useAuth } from '../../context/AuthContext';

const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: 'viewer', label: 'Viewer — read-only dashboards' },
  { value: 'operator', label: 'Operator — start/stop services & containers, read logs' },
  { value: 'admin', label: 'Admin — everything, incl. terminal & accounts' },
];
const ROLE_COLOR: Record<Role, string> = { viewer: 'default', operator: 'blue', admin: 'gold' };

const errorText = (e: any, fallback: string) => e.response?.data?.detail || fallback;

export const AccessControlView: React.FC = () => {
  const { user: me } = useAuth();
  const [accounts, setAccounts] = useState<AppAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [resetFor, setResetFor] = useState<AppAccount | null>(null);
  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAccounts(await api.getAccounts());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      message.success(ok);
      await load();
    } catch (e: any) {
      message.error(errorText(e, 'Action failed'));
    }
  };

  return (
    <Card
      title={
        <span>
          <TeamOutlined className="mr-2" />
          Access Control
        </span>
      }
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            Add account
          </Button>
        </Space>
      }
    >
      <Table<AppAccount>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={accounts}
        pagination={false}
        scroll={{ x: 760 }}
        columns={[
          {
            title: 'Username',
            dataIndex: 'username',
            render: (u: string, row) => (
              <span className="font-semibold">
                {u} {row.id === me?.id && <Tag className="ml-1">you</Tag>}
              </span>
            ),
          },
          {
            title: 'Role',
            dataIndex: 'role',
            width: 150,
            render: (role: Role, row) => (
              <Select<Role>
                size="small"
                value={role}
                disabled={row.id === me?.id}
                style={{ width: 120 }}
                options={ROLE_OPTIONS.map((o) => ({ value: o.value, label: <Tag color={ROLE_COLOR[o.value]}>{o.value}</Tag> }))}
                onChange={(r) => run(() => api.updateAccount(row.id, { role: r }), `Role set to ${r}`)}
              />
            ),
          },
          {
            title: 'MFA',
            dataIndex: 'mfa_enabled',
            width: 80,
            render: (on: boolean) => <Tag color={on ? 'green' : 'red'}>{on ? 'On' : 'Off'}</Tag>,
          },
          {
            title: 'Active',
            dataIndex: 'disabled',
            width: 80,
            render: (disabled: boolean, row) => (
              <Switch
                size="small"
                checked={!disabled}
                disabled={row.id === me?.id}
                onChange={(on) => run(() => api.updateAccount(row.id, { disabled: !on }), on ? 'Account enabled' : 'Account disabled')}
              />
            ),
          },
          {
            title: 'Last login',
            dataIndex: 'last_login_at',
            width: 170,
            render: (t?: string) => (t ? new Date(t).toLocaleString() : <span className="text-fg-subtle">never</span>),
          },
          {
            title: '',
            key: 'actions',
            width: 130,
            render: (_, row) => (
              <Space size={4}>
                <Button size="small" icon={<KeyOutlined />} title="Reset password" onClick={() => setResetFor(row)} />
                <Popconfirm
                  title={`Reset MFA for ${row.username}?`}
                  description="They will have to enroll again at next login."
                  disabled={!row.mfa_enabled}
                  onConfirm={() => run(() => api.resetAccountMfa(row.id), 'MFA reset')}
                >
                  <Button size="small" icon={<SafetyOutlined />} title="Reset MFA" disabled={!row.mfa_enabled} />
                </Popconfirm>
                <Popconfirm
                  title={`Delete ${row.username}?`}
                  okButtonProps={{ danger: true }}
                  disabled={row.id === me?.id}
                  onConfirm={() => run(() => api.deleteAccount(row.id), 'Account deleted')}
                >
                  <Button size="small" danger icon={<DeleteOutlined />} title="Delete" disabled={row.id === me?.id} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="Add account"
        open={createOpen}
        okText="Create"
        destroyOnClose
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const v = await createForm.validateFields();
          try {
            await api.createAccount(v.username.trim(), v.password, v.role);
            message.success('Account created');
            setCreateOpen(false);
            createForm.resetFields();
            await load();
          } catch (e: any) {
            message.error(errorText(e, 'Failed to create account'));
          }
        }}
      >
        <Form form={createForm} layout="vertical" requiredMark={false} initialValues={{ role: 'viewer' }}>
          <Form.Item name="username" label="Username" rules={[{ required: true }, { pattern: /^[A-Za-z0-9_.@-]+$/, message: 'Letters, digits, _ . @ - only' }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="Initial password" rules={[{ required: true }, { min: 12, message: 'At least 12 characters' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="Role">
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Reset password — ${resetFor?.username}`}
        open={!!resetFor}
        okText="Reset password"
        destroyOnClose
        onCancel={() => setResetFor(null)}
        onOk={async () => {
          const v = await resetForm.validateFields();
          if (!resetFor) return;
          try {
            await api.resetAccountPassword(resetFor.id, v.new_password);
            message.success('Password reset; their sessions were signed out');
            setResetFor(null);
            resetForm.resetFields();
          } catch (e: any) {
            message.error(errorText(e, 'Failed to reset password'));
          }
        }}
      >
        <Form form={resetForm} layout="vertical" requiredMark={false}>
          <Form.Item name="new_password" label="New password" rules={[{ required: true }, { min: 12, message: 'At least 12 characters' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
};
