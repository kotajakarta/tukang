import React, { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons';
import { Logo } from '../common/Logo';
import { MfaRequiredError, useAuth } from '../../context/AuthContext';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Credentials are kept in memory only between the password step and the code step
  const [pending, setPending] = useState<{ username: string; password: string } | null>(null);

  const attempt = async (username: string, password: string, otp?: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password, otp);
    } catch (e: any) {
      if (e instanceof MfaRequiredError) {
        setPending({ username, password });
      } else {
        setError(e.response?.data?.detail || 'Unable to reach the server');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <Logo size={64} className="mb-3" />
          <h1 className="text-xl font-bold text-fg m-0">tuKang</h1>
          <p className="text-sm text-fg-muted mt-1 mb-0">
            {pending ? 'Enter the code from your authenticator app' : 'Sign in to manage your servers'}
          </p>
        </div>

        <div className="bg-surface border border-line rounded-xl p-5 shadow-xl">
          {error && <Alert type="error" message={error} showIcon className="mb-4" />}

          {!pending ? (
            <Form
              layout="vertical"
              requiredMark={false}
              disabled={submitting}
              onFinish={(v: { username: string; password: string }) => attempt(v.username.trim(), v.password)}
            >
              <Form.Item name="username" label="Username" rules={[{ required: true, message: 'Enter your username' }]}>
                <Input prefix={<UserOutlined className="text-fg-subtle" />} autoComplete="username" autoFocus size="large" />
              </Form.Item>
              <Form.Item name="password" label="Password" rules={[{ required: true, message: 'Enter your password' }]}>
                <Input.Password prefix={<LockOutlined className="text-fg-subtle" />} autoComplete="current-password" size="large" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block size="large" loading={submitting}>
                Sign in
              </Button>
            </Form>
          ) : (
            <Form
              layout="vertical"
              requiredMark={false}
              disabled={submitting}
              onFinish={(v: { otp: string }) => attempt(pending.username, pending.password, v.otp.trim())}
            >
              <Form.Item
                name="otp"
                label="Authentication code"
                extra="6-digit code, or one of your recovery codes"
                rules={[{ required: true, message: 'Enter the code' }]}
              >
                <Input
                  prefix={<SafetyOutlined className="text-fg-subtle" />}
                  autoComplete="one-time-code"
                  inputMode="text"
                  autoFocus
                  size="large"
                  maxLength={32}
                />
              </Form.Item>
              <Button type="primary" htmlType="submit" block size="large" loading={submitting}>
                Verify
              </Button>
              <Button
                type="link"
                block
                className="mt-2"
                onClick={() => {
                  setPending(null);
                  setError(null);
                }}
              >
                Back
              </Button>
            </Form>
          )}
        </div>
      </div>
    </div>
  );
};
