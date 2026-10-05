import React, { useState } from 'react';
import { Alert, Button, Dropdown, Form, Input, Modal, Tag, message } from 'antd';
import { KeyOutlined, LogoutOutlined, SafetyOutlined } from '@ant-design/icons';
import { CircleUser } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { api } from '../../services/api';
import { MfaSetup } from './MfaSetup';

export const UserMenu: React.FC = () => {
  const { user, logout, logoutAll, changePassword, refresh } = useAuth();
  const [pwOpen, setPwOpen] = useState(false);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [form] = Form.useForm();
  const [mfaForm] = Form.useForm();

  if (!user) return null;

  const handleChangePassword = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await changePassword(values.current_password, values.new_password);
      message.success('Password updated. Other sessions have been signed out.');
      setPwOpen(false);
      form.resetFields();
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to change password');
    } finally {
      setSaving(false);
    }
  };

  const handleDisableMfa = async () => {
    const values = await mfaForm.validateFields();
    setSaving(true);
    try {
      await api.mfaDisable(values.password, values.code);
      message.success('Two-factor authentication disabled');
      setMfaOpen(false);
      mfaForm.resetFields();
      await refresh();
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to disable');
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    const values = await mfaForm.validateFields(['code']);
    setSaving(true);
    try {
      setNewCodes((await api.mfaRegenerateCodes(values.code)).recovery_codes);
      mfaForm.resetFields();
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to regenerate codes');
    } finally {
      setSaving(false);
    }
  };

  const closeMfa = () => {
    setMfaOpen(false);
    setNewCodes(null);
    mfaForm.resetFields();
  };

  return (
    <>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            {
              key: 'who',
              label: (
                <span className="text-fg-muted">
                  Signed in as <b className="text-fg">{user.username}</b>{' '}
                  <Tag className="ml-1 mr-0">{user.role}</Tag>
                </span>
              ),
              disabled: true,
            },
            { type: 'divider' },
            { key: 'password', icon: <KeyOutlined />, label: 'Change password', onClick: () => setPwOpen(true) },
            {
              key: 'mfa',
              icon: <SafetyOutlined />,
              label: (
                <span>
                  Two-factor authentication{' '}
                  <Tag color={user.mfa_enabled ? 'green' : 'default'} className="ml-1 mr-0">
                    {user.mfa_enabled ? 'On' : 'Off'}
                  </Tag>
                </span>
              ),
              onClick: () => setMfaOpen(true),
            },
            { key: 'logout', icon: <LogoutOutlined />, label: 'Sign out', onClick: () => logout() },
            {
              key: 'logout-all',
              icon: <LogoutOutlined />,
              label: 'Sign out everywhere',
              danger: true,
              onClick: () =>
                Modal.confirm({
                  title: 'Sign out of all devices?',
                  content: 'Every browser signed in to this account, including this one, will be signed out.',
                  okText: 'Sign out everywhere',
                  okButtonProps: { danger: true },
                  onOk: () => logoutAll(),
                }),
            },
          ],
        }}
      >
        <button
          type="button"
          aria-label="Account menu"
          className="focus-ring inline-flex items-center justify-center h-9 w-9 rounded-md bg-transparent text-fg-muted hover:bg-surface-2 hover:text-fg cursor-pointer"
        >
          <CircleUser size={19} strokeWidth={1.75} />
        </button>
      </Dropdown>

      <Modal
        title="Change password"
        open={pwOpen}
        onOk={handleChangePassword}
        okText="Update password"
        confirmLoading={saving}
        onCancel={() => {
          setPwOpen(false);
          form.resetFields();
        }}
        destroyOnClose
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="current_password" label="Current password" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="New password"
            rules={[{ required: true }, { min: 12, message: 'At least 12 characters' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="Confirm new password"
            dependencies={['new_password']}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator: (_, v) =>
                  !v || v === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('Passwords do not match')),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="Two-factor authentication" open={mfaOpen} onCancel={closeMfa} footer={null} destroyOnClose>
        {!user.mfa_enabled ? (
          <MfaSetup
            onDone={async () => {
              closeMfa();
              message.success('Two-factor authentication enabled. Other sessions were signed out.');
              await refresh();
            }}
          />
        ) : newCodes ? (
          <div className="space-y-3">
            <Alert type="warning" showIcon message="New recovery codes — the old ones no longer work. Save them now." />
            <pre className="bg-canvas border border-line rounded-lg p-3 font-mono text-sm grid grid-cols-2 gap-x-4 m-0">
              {newCodes.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </pre>
            <Button type="primary" onClick={closeMfa}>
              Done
            </Button>
          </div>
        ) : (
          <Form form={mfaForm} layout="vertical" requiredMark={false}>
            <Alert type="success" showIcon className="mb-4" message="Two-factor authentication is on for this account." />
            <Form.Item name="code" label="Authentication code" rules={[{ required: true }]}>
              <Input autoComplete="one-time-code" maxLength={32} />
            </Form.Item>
            <Form.Item name="password" label="Password (only needed to turn it off)">
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <div className="flex flex-wrap gap-2">
              <Button onClick={handleRegenerate} loading={saving}>
                New recovery codes
              </Button>
              <Button danger onClick={handleDisableMfa} loading={saving}>
                Turn off
              </Button>
            </div>
          </Form>
        )}
      </Modal>
    </>
  );
};
