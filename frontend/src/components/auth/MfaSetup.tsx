import React, { useEffect, useState } from 'react';
import { Alert, Button, Input, QRCode, Space, Typography, message } from 'antd';
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons';
import { api } from '../../services/api';
import { Logo } from '../common/Logo';

/** TOTP enrollment: scan QR -> confirm a code -> show recovery codes once. */
export const MfaSetup: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  useEffect(() => {
    api.mfaSetup().then(setSetup).catch((e) => setError(e.response?.data?.detail || 'Failed to start setup'));
  }, []);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.mfaEnable(code.trim());
      setRecoveryCodes(res.recovery_codes);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Verification failed');
    } finally {
      setBusy(false);
    }
  };

  if (recoveryCodes) {
    const text = recoveryCodes.join('\n');
    return (
      <div className="space-y-3">
        <Alert
          type="warning"
          showIcon
          message="Save these recovery codes now"
          description="Each code signs you in once if you lose your authenticator. They will not be shown again."
        />
        <pre className="bg-canvas border border-line rounded-lg p-3 font-mono text-sm text-fg grid grid-cols-2 gap-x-4 m-0">
          {recoveryCodes.map((c) => (
            <span key={c}>{c}</span>
          ))}
        </pre>
        <Space wrap>
          <Button icon={<CopyOutlined />} onClick={() => navigator.clipboard.writeText(text).then(() => message.success('Copied'))}>
            Copy
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => {
              const a = document.createElement('a');
              a.href = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }));
              a.download = 'tukang-recovery-codes.txt';
              a.click();
              URL.revokeObjectURL(a.href);
            }}
          >
            Download
          </Button>
          <Button type="primary" onClick={onDone}>
            I have saved them
          </Button>
        </Space>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Alert type="error" showIcon message={error} />}
      <ol className="text-sm text-fg pl-5 space-y-1 m-0">
        <li>Open an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy…).</li>
        <li>Scan this QR code, or enter the key manually.</li>
        <li>Type the 6-digit code it shows.</li>
      </ol>
      {setup && (
        <div className="flex flex-col items-center gap-2">
          <div className="bg-white p-2 rounded-lg">
            <QRCode value={setup.otpauth_uri} size={176} bordered={false} color="#000000" bgColor="#ffffff" />
          </div>
          <Typography.Text copyable={{ text: setup.secret }} className="font-mono text-xs break-all text-center">
            {setup.secret.match(/.{1,4}/g)?.join(' ')}
          </Typography.Text>
        </div>
      )}
      <Space.Compact className="w-full">
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onPressEnter={confirm}
          placeholder="123456"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          size="large"
        />
        <Button type="primary" size="large" loading={busy} disabled={code.trim().length !== 6 || !setup} onClick={confirm}>
          Enable
        </Button>
      </Space.Compact>
    </div>
  );
};

/** Full-screen gate shown when the server requires MFA and this account hasn't enrolled yet. */
export const MfaEnrollmentPage: React.FC<{ onDone: () => void; onLogout: () => void }> = ({ onDone, onLogout }) => (
  <div className="min-h-screen w-full flex items-center justify-center bg-canvas px-4 py-8">
    <div className="w-full max-w-md bg-surface border border-line rounded-xl p-5 shadow-xl">
      <Logo size={48} className="mb-3" />
      <h1 className="text-lg font-bold text-fg mt-0 mb-1">Set up two-factor authentication</h1>
      <p className="text-sm text-fg-muted mt-0 mb-4">This server requires a second factor for every account.</p>
      <MfaSetup onDone={onDone} />
      <Button type="link" className="mt-3 px-0" onClick={onLogout}>
        Sign out
      </Button>
    </div>
  </div>
);
