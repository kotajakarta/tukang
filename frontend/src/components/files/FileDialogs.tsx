import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Checkbox, Form, Input, Modal, Select, Spin, Typography } from 'antd';
import { api, FileEntry } from '../../services/api';
import { Access, accessOf, buildMode } from './fileUtils';

const errorText = (e: any, fallback: string) => e?.response?.data?.detail || fallback;

const validName = (_: unknown, value: string) => {
  if (!value || !value.trim()) return Promise.reject(new Error('Name is required'));
  if (value.includes('/')) return Promise.reject(new Error('Name cannot contain "/"'));
  if (value === '.' || value === '..') return Promise.reject(new Error('Invalid name'));
  return Promise.resolve();
};

/** Create directory / create file / rename. */
export const NameDialog: React.FC<{
  open: boolean;
  title: string;
  okText: string;
  initial?: string;
  existing: Set<string>;
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
}> = ({ open, title, okText, initial = '', existing, onSubmit, onClose }) => {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({ name: initial });
      setError(null);
    }
  }, [open, initial, form]);

  const submit = async () => {
    const { name } = await form.validateFields();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(name);
      onClose();
    } catch (e) {
      setError(errorText(e, 'Operation failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={title} open={open} okText={okText} onOk={submit} confirmLoading={busy} onCancel={onClose} destroyOnClose>
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      <Form form={form} layout="vertical" requiredMark={false} onFinish={submit}>
        <Form.Item
          name="name"
          label="Name"
          rules={[
            { validator: validName },
            {
              validator: (_, v) =>
                v && v !== initial && existing.has(v) ? Promise.reject(new Error('An item with this name already exists')) : Promise.resolve(),
            },
          ]}
        >
          <Input
            autoFocus
            onFocus={(e) => {
              // Select the base name without extension, like a desktop file manager
              const dot = initial.lastIndexOf('.');
              if (initial && dot > 0) e.target.setSelectionRange(0, dot);
            }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export const LinkDialog: React.FC<{
  open: boolean;
  initialTarget: string;
  existing: Set<string>;
  onSubmit: (target: string, name: string) => Promise<void>;
  onClose: () => void;
}> = ({ open, initialTarget, existing, onSubmit, onClose }) => {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      const base = initialTarget.split('/').pop() || '';
      form.setFieldsValue({ target: initialTarget, name: base ? `${base}-link` : '' });
      setError(null);
    }
  }, [open, initialTarget, form]);

  const submit = async () => {
    const { target, name } = await form.validateFields();
    setBusy(true);
    try {
      await onSubmit(target, name);
      onClose();
    } catch (e) {
      setError(errorText(e, 'Failed to create link'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Create link" open={open} okText="Create link" onOk={submit} confirmLoading={busy} onCancel={onClose} destroyOnClose>
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="target" label="Original" rules={[{ required: true, message: 'Target is required' }]} extra="Absolute path, or relative to this directory">
          <Input className="font-mono" />
        </Form.Item>
        <Form.Item
          name="name"
          label="New link name"
          rules={[
            { validator: validName },
            { validator: (_, v) => (v && existing.has(v) ? Promise.reject(new Error('An item with this name already exists')) : Promise.resolve()) },
          ]}
        >
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export const DeleteDialog: React.FC<{
  open: boolean;
  items: FileEntry[];
  onConfirm: () => Promise<void>;
  onClose: () => void;
}> = ({ open, items, onConfirm, onClose }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setError(null), [open]);
  const single = items.length === 1 ? items[0] : null;

  return (
    <Modal
      title={single ? `Delete ${single.type === 'directory' ? 'directory' : 'file'} ${single.name}?` : `Delete ${items.length} items?`}
      open={open}
      okText="Delete"
      okButtonProps={{ danger: true }}
      confirmLoading={busy}
      onCancel={onClose}
      onOk={async () => {
        setBusy(true);
        try {
          await onConfirm();
          onClose();
        } catch (e) {
          setError(errorText(e, 'Delete failed'));
        } finally {
          setBusy(false);
        }
      }}
    >
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      <p className="text-fg mt-0">
        {items.some((i) => i.type === 'directory')
          ? 'Directories are deleted with all of their contents. '
          : ''}
        This cannot be undone.
      </p>
      {!single && (
        <ul className="max-h-48 overflow-y-auto font-mono text-xs text-fg-muted pl-4 m-0">
          {items.map((i) => (
            <li key={i.path}>{i.name}</li>
          ))}
        </ul>
      )}
    </Modal>
  );
};

const ACCESS_OPTIONS = [
  { value: 'rw', label: 'Read and write' },
  { value: 'r', label: 'Read-only' },
  { value: 'none', label: 'No access' },
];

export const PermissionsDialog: React.FC<{
  open: boolean;
  serverId: string;
  items: FileEntry[];
  onDone: () => void;
  onClose: () => void;
}> = ({ open, serverId, items, onDone, onClose }) => {
  const [form] = Form.useForm();
  const [principals, setPrincipals] = useState<{ users: string[]; groups: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = items[0];
  const hasDir = items.some((i) => i.type === 'directory');
  const allDirs = items.every((i) => i.type === 'directory');

  useEffect(() => {
    if (!open || !first) return;
    setError(null);
    form.setFieldsValue({
      owner: first.owner,
      group: first.group,
      ownerAccess: accessOf(first.mode, 6),
      groupAccess: accessOf(first.mode, 3),
      otherAccess: accessOf(first.mode, 0),
      executable: (first.mode & 0o111) !== 0,
      recursive: false,
    });
    api.filesPrincipals(serverId).then(setPrincipals).catch(() => setPrincipals({ users: [], groups: [] }));
  }, [open, first, serverId, form]);

  const preview = Form.useWatch([], form);
  const octal = useMemo(() => {
    if (!preview || !first) return '';
    const m = buildMode(first.mode, preview.ownerAccess, preview.groupAccess, preview.otherAccess, allDirs, preview.executable);
    return m.toString(8).padStart(4, '0');
  }, [preview, first, allDirs]);

  const submit = async () => {
    const v = await form.validateFields();
    setBusy(true);
    setError(null);
    try {
      // Group items by kind so directories keep +x while files follow the executable checkbox
      const dirs = items.filter((i) => i.type === 'directory').map((i) => i.path);
      const files = items.filter((i) => i.type !== 'directory').map((i) => i.path);
      const common = { owner: v.owner, group: v.group, recursive: v.recursive };
      if (dirs.length)
        await api.filesAction(serverId, {
          op: 'chmod', paths: dirs, ...common,
          mode: buildMode(first.mode, v.ownerAccess as Access, v.groupAccess, v.otherAccess, true, v.executable),
        });
      if (files.length)
        await api.filesAction(serverId, {
          op: 'chmod', paths: files, ...common,
          mode: buildMode(first.mode, v.ownerAccess as Access, v.groupAccess, v.otherAccess, false, v.executable),
        });
      onDone();
      onClose();
    } catch (e) {
      setError(errorText(e, 'Failed to change permissions'));
    } finally {
      setBusy(false);
    }
  };

  if (!first) return null;
  const toOptions = (xs: string[]) => xs.map((x) => ({ value: x, label: x }));

  return (
    <Modal
      title={items.length === 1 ? `“${first.name}” permissions` : `Permissions for ${items.length} items`}
      open={open}
      okText="Change"
      onOk={submit}
      confirmLoading={busy}
      onCancel={onClose}
      destroyOnClose
    >
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      <Form form={form} layout="horizontal" labelCol={{ span: 8 }} wrapperCol={{ span: 16 }} requiredMark={false}>
        <Form.Item name="owner" label="Owner">
          <Select showSearch options={toOptions(principals?.users || [first.owner])} loading={!principals} />
        </Form.Item>
        <Form.Item name="group" label="Group">
          <Select showSearch options={toOptions(principals?.groups || [first.group])} loading={!principals} />
        </Form.Item>
        <Form.Item name="ownerAccess" label="Owner access">
          <Select options={ACCESS_OPTIONS} />
        </Form.Item>
        <Form.Item name="groupAccess" label="Group access">
          <Select options={ACCESS_OPTIONS} />
        </Form.Item>
        <Form.Item name="otherAccess" label="Others access">
          <Select options={ACCESS_OPTIONS} />
        </Form.Item>
        {!allDirs && (
          <Form.Item name="executable" valuePropName="checked" wrapperCol={{ offset: 8, span: 16 }}>
            <Checkbox>Set executable</Checkbox>
          </Form.Item>
        )}
        {hasDir && (
          <Form.Item name="recursive" valuePropName="checked" wrapperCol={{ offset: 8, span: 16 }}>
            <Checkbox>Apply to all contents of {items.length === 1 ? 'this directory' : 'the directories'}</Checkbox>
          </Form.Item>
        )}
        <Form.Item label="Mode" className="mb-0">
          <Typography.Text code>{octal}</Typography.Text>
        </Form.Item>
      </Form>
    </Modal>
  );
};

/** Plain-text editor (UTF-8, ≤ 2 MB) with conflict detection via mtime. */
export const EditorDialog: React.FC<{
  open: boolean;
  serverId: string;
  path: string | null;
  onSaved: () => void;
  onClose: () => void;
}> = ({ open, serverId, path, onSaved, onClose }) => {
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [mtime, setMtime] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textRef = useRef<any>(null);
  const dirty = content !== original;

  useEffect(() => {
    if (!open || !path) return;
    setLoading(true);
    setError(null);
    api
      .filesRead(serverId, path)
      .then((r) => {
        setContent(r.content);
        setOriginal(r.content);
        setMtime(r.mtime);
      })
      .catch((e) => setError(errorText(e, 'Failed to open file')))
      .finally(() => setLoading(false));
  }, [open, path, serverId]);

  const save = async () => {
    if (!path) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.filesAction<FileEntry>(serverId, { op: 'write', path, content, expected_mtime: mtime });
      setOriginal(content);
      setMtime(res.mtime);
      onSaved();
    } catch (e) {
      setError(errorText(e, 'Failed to save'));
    } finally {
      setSaving(false);
    }
  };

  const close = () => {
    if (!dirty) return onClose();
    Modal.confirm({
      title: 'Discard unsaved changes?',
      okText: 'Discard',
      okButtonProps: { danger: true },
      onOk: onClose,
    });
  };

  return (
    <Modal
      title={<span className="font-mono text-sm">{path}{dirty ? ' •' : ''}</span>}
      open={open}
      width={980}
      okText="Save"
      okButtonProps={{ disabled: !dirty || loading || !!(error && !original && !content) }}
      confirmLoading={saving}
      onOk={save}
      onCancel={close}
      maskClosable={false}
      destroyOnClose
    >
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      {loading ? (
        <div className="py-16 text-center">
          <Spin />
        </div>
      ) : (
        <Input.TextArea
          ref={textRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
              e.preventDefault();
              if (dirty) save();
            }
            if (e.key === 'Tab') {
              // Insert a tab instead of moving focus
              e.preventDefault();
              const el = e.currentTarget;
              const { selectionStart: s, selectionEnd: t } = el;
              const next = content.slice(0, s) + '\t' + content.slice(t);
              setContent(next);
              requestAnimationFrame(() => el.setSelectionRange(s + 1, s + 1));
            }
          }}
          spellCheck={false}
          autoSize={{ minRows: 18, maxRows: 32 }}
          className="font-mono text-xs leading-5"
          style={{ tabSize: 4 }}
        />
      )}
      <div className="text-xs text-fg-subtle mt-2">Ctrl+S to save · {content.split('\n').length} lines</div>
    </Modal>
  );
};
