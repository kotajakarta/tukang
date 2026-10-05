import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, AutoComplete, Button, Form, Input, Modal, Popconfirm, Progress, Select, Typography } from 'antd';
import { CloudDownload, CloudUpload, X } from 'lucide-react';
import { api, FileRemote, FileRemoteInput, TransferDirection, TransferJob, TransferScan } from '../../services/api';
import { ServerNode } from '../../types/server';
import { formatSize, parentOf } from './fileUtils';

const errorText = (e: any, fallback: string) => e?.response?.data?.detail || fallback;

export const DEFAULT_IGNORE = ['.git', '.vscode', '.idea'];

/** True when `path` is `root` or inside it */
export const isWithin = (path: string, root: string) => path === root || path.startsWith(root === '/' ? '/' : `${root}/`);

/** Remotes whose local folder (on this server) contains every one of `paths` */
export const remotesFor = (remotes: FileRemote[], serverId: string, paths: string[]) =>
  paths.length ? remotes.filter((r) => r.local_server_id === serverId && paths.every((p) => isWithin(p, r.local_path))) : [];

/** JSON with // and /* comments and trailing commas, as VS Code writes sftp.json */
export const parseJsonc = (text: string): any => {
  let out = '';
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      const start = i;
      for (i++; i < text.length && text[i] !== '"'; i++) if (text[i] === '\\') i++;
      out += text.slice(start, i + 1);
    } else if (c === '/' && text[i + 1] === '/') {
      while (i < text.length && text[i] !== '\n') i++;
      out += '\n';
    } else if (c === '/' && text[i + 1] === '*') {
      i = text.indexOf('*/', i + 2);
      if (i < 0) break;
      i++;
    } else out += c;
  }
  return JSON.parse(out.replace(/,(\s*[}\]])/g, '$1'));
};

interface SftpConfig {
  ignore: string[];
  remotePath?: string;
  host?: string;
}

/** The parts of a VS Code SFTP extension config we can use (first profile when it holds several) */
const readSftpConfig = (raw: any): SftpConfig | null => {
  const cfg = Array.isArray(raw) ? raw[0] : raw;
  if (!cfg || typeof cfg !== 'object') return null;
  return {
    ignore: Array.isArray(cfg.ignore) ? cfg.ignore.filter((p: unknown) => typeof p === 'string') : [],
    remotePath: typeof cfg.remotePath === 'string' ? cfg.remotePath : undefined,
    host: typeof cfg.host === 'string' ? cfg.host : undefined,
  };
};

const linesToList = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);
const mergeLists = (a: string[], b: string[]) => [...a, ...b.filter((x) => !a.includes(x))];

/** Create or edit a remote mapping for a local folder. */
export const RemoteDialog: React.FC<{
  open: boolean;
  /** Mapping being edited; null creates one for `localPath` */
  remote: FileRemote | null;
  localServerId: string;
  localPath: string;
  servers: ServerNode[];
  onSaved: (remote: FileRemote) => void;
  onDeleted: (id: number) => void;
  onClose: () => void;
}> = ({ open, remote, localServerId, localPath, servers, onSaved, onDeleted, onClose }) => {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sftp, setSftp] = useState<SftpConfig | null>(null);
  const [dirOptions, setDirOptions] = useState<{ value: string }[]>([]);
  const lookup = useRef(0);
  const folder = remote ? remote.local_path : localPath;
  const remoteServerId: string | undefined = Form.useWatch('remote_server_id', form);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setSftp(null);
    setDirOptions([]);
    form.setFieldsValue(
      remote
        ? { name: remote.name, remote_server_id: remote.remote_server_id, remote_path: remote.remote_path, ignore: remote.ignore.join('\n') }
        : {
            name: folder.split('/').pop() || folder,
            remote_server_id: servers.find((s) => s.id !== localServerId)?.id,
            remote_path: '',
            ignore: DEFAULT_IGNORE.join('\n'),
          }
    );
    // A project already set up for the VS Code SFTP extension: offer its settings
    let cancelled = false;
    api
      .filesRead(localServerId, `${folder === '/' ? '' : folder}/.vscode/sftp.json`)
      .then((f) => !cancelled && setSftp(readSftpConfig(parseJsonc(f.content))))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, remote, folder, localServerId, servers, form]);

  const importSftp = () => {
    if (!sftp) return;
    const current = linesToList(form.getFieldValue('ignore') || '');
    const changes: Record<string, string> = { ignore: mergeLists(current, sftp.ignore).join('\n') };
    if (sftp.remotePath && !form.getFieldValue('remote_path')) changes.remote_path = sftp.remotePath;
    const match = sftp.host && servers.find((s) => s.host === sftp.host && s.id !== localServerId);
    if (match) changes.remote_server_id = match.id;
    form.setFieldsValue(changes);
  };

  // Suggest directories on the remote server as the path is typed
  const suggestDirs = async (value: string) => {
    if (!remoteServerId || !value.startsWith('/')) return setDirOptions([]);
    const dir = value.endsWith('/') ? value.replace(/\/+$/, '') || '/' : parentOf(value);
    const seq = ++lookup.current;
    try {
      const res = await api.filesList(remoteServerId, dir, true);
      if (seq !== lookup.current) return;
      setDirOptions(
        res.entries
          .filter((e) => e.type === 'directory' || (e.type === 'link' && e.target_type === 'directory'))
          .map((e) => ({ value: e.path }))
          .filter((o) => o.value.startsWith(value))
          .sort((a, b) => a.value.localeCompare(b.value))
          .slice(0, 50)
      );
    } catch {
      if (seq === lookup.current) setDirOptions([]);
    }
  };

  const submit = async () => {
    const v = await form.validateFields();
    const input: FileRemoteInput = {
      name: v.name.trim(),
      local_server_id: remote ? remote.local_server_id : localServerId,
      local_path: folder,
      remote_server_id: v.remote_server_id,
      remote_path: v.remote_path.trim().replace(/(.)\/+$/, '$1'),
      ignore: linesToList(v.ignore || ''),
    };
    setBusy(true);
    setError(null);
    try {
      onSaved(remote ? await api.updateFileRemote(remote.id, input) : await api.createFileRemote(input));
      onClose();
    } catch (e) {
      setError(errorText(e, 'Failed to save remote'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!remote) return;
    try {
      await api.deleteFileRemote(remote.id);
      onDeleted(remote.id);
      onClose();
    } catch (e) {
      setError(errorText(e, 'Failed to delete remote'));
    }
  };

  return (
    <Modal
      title={remote ? `Edit remote “${remote.name}”` : 'Set up remote'}
      open={open}
      onCancel={onClose}
      destroyOnClose
      width={560}
      footer={
        <div className="flex items-center gap-2">
          {remote && (
            <Popconfirm title="Delete this remote?" description="Files on both servers stay as they are." okText="Delete" okButtonProps={{ danger: true }} onConfirm={remove}>
              <Button danger>Delete</Button>
            </Popconfirm>
          )}
          <span className="flex-1" />
          <Button onClick={onClose}>Cancel</Button>
          <Button type="primary" loading={busy} onClick={submit}>
            {remote ? 'Save' : 'Create remote'}
          </Button>
        </div>
      }
    >
      {error && <Alert type="error" showIcon message={error} className="mb-3" />}
      {sftp && (
        <Alert
          type="info"
          showIcon
          className="mb-3"
          message="This folder has a .vscode/sftp.json"
          description={`${sftp.ignore.length} ignore pattern${sftp.ignore.length === 1 ? '' : 's'}${sftp.remotePath ? `, remote path ${sftp.remotePath}` : ''}`}
          action={
            <Button size="small" onClick={importSftp}>
              Use its settings
            </Button>
          }
        />
      )}
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="Local folder">
          <Typography.Text code className="break-all">
            {servers.find((s) => s.id === (remote?.local_server_id ?? localServerId))?.name ?? localServerId}: {folder}
          </Typography.Text>
        </Form.Item>
        <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Name is required' }, { max: 64 }]}>
          <Input placeholder="e.g. Production" />
        </Form.Item>
        <Form.Item name="remote_server_id" label="Remote server" rules={[{ required: true, message: 'Choose a server' }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={servers.map((s) => ({ value: s.id, label: `${s.name} (${s.host})` }))}
            onChange={() => setDirOptions([])}
          />
        </Form.Item>
        <Form.Item
          name="remote_path"
          label="Remote folder"
          extra="Created on the first upload if it does not exist yet"
          rules={[
            { required: true, message: 'Remote folder is required' },
            { pattern: /^\//, message: 'Enter an absolute path' },
          ]}
        >
          <AutoComplete options={dirOptions} onSearch={suggestDirs} onFocus={(e) => suggestDirs((e.target as HTMLInputElement).value || '/')}>
            <Input className="font-mono" placeholder="/var/www/project" />
          </AutoComplete>
        </Form.Item>
        <Form.Item
          name="ignore"
          label="Ignore"
          extra="One pattern per line, .gitignore style: node_modules matches at any depth, docs/*.* only at the top, *.log anywhere. Applies to uploads and downloads."
        >
          <Input.TextArea className="font-mono text-xs" autoSize={{ minRows: 4, maxRows: 12 }} spellCheck={false} />
        </Form.Item>
      </Form>
    </Modal>
  );
};

/** Body of the confirmation shown before a transfer starts. */
export const TransferSummary: React.FC<{ scan: TransferScan; direction: TransferDirection; serverName: (id: string) => string }> = ({
  scan,
  direction,
  serverName,
}) => {
  const items = scan.rels.filter((r) => !scan.skipped.includes(r));
  const sent = scan.files + scan.dirs + scan.links;
  return (
    <div className="space-y-2 text-sm">
      <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1">
        <span className="text-fg-subtle">From</span>
        <span className="font-mono text-xs break-all">
          {serverName(scan.source_server_id)}: {scan.source_root}
        </span>
        <span className="text-fg-subtle">To</span>
        <span className="font-mono text-xs break-all">
          {serverName(scan.dest_server_id)}: {scan.dest_root}
        </span>
        {!(items.length === 1 && items[0] === '.') && items.length > 0 && (
          <>
            <span className="text-fg-subtle">Items</span>
            <span className="font-mono text-xs break-all">
              {items.slice(0, 5).join(', ')}
              {items.length > 5 ? ` and ${items.length - 5} more` : ''}
            </span>
          </>
        )}
      </div>
      {sent > 0 ? (
        <div>
          <b>
            {scan.files} file{scan.files === 1 ? '' : 's'}
          </b>{' '}
          ({formatSize(scan.bytes)}){scan.dirs ? `, ${scan.dirs} folder${scan.dirs === 1 ? '' : 's'}` : ''}
          {scan.links ? `, ${scan.links} link${scan.links === 1 ? '' : 's'}` : ''}
          {scan.ignored ? <span className="text-fg-muted"> · {scan.ignored} ignored</span> : null}
        </div>
      ) : (
        <Alert type="warning" showIcon message="Nothing to transfer: everything selected matches the ignore rules." />
      )}
      {scan.skipped.length > 0 && sent > 0 && (
        <Alert type="warning" showIcon message={`Skipped by ignore rules: ${scan.skipped.join(', ')}`} />
      )}
      <div className="text-xs text-fg-muted">
        Existing files on {direction === 'upload' ? 'the remote' : 'this server'} are overwritten. Nothing is deleted.
      </div>
    </div>
  );
};

/** Progress rows for running and recently finished transfers. */
export const TransferList: React.FC<{
  jobs: TransferJob[];
  serverName: (id: string) => string;
  onCancel: (job: TransferJob) => void;
  onDismiss: (job: TransferJob) => void;
}> = ({ jobs, serverName, onCancel, onDismiss }) => {
  const rows = useMemo(() => [...jobs].reverse(), [jobs]);
  if (!rows.length) return null;
  return (
    <div className="px-3 py-2 border-t border-line space-y-1.5">
      {rows.map((j) => {
        const Icon = j.direction === 'upload' ? CloudUpload : CloudDownload;
        const percent = j.state === 'done' ? 100 : Math.min(99, Math.floor((j.sent_bytes / Math.max(j.total_bytes, 1)) * 100));
        return (
          <div key={j.id} className="flex items-center gap-3 text-xs">
            <Icon size={15} className="flex-shrink-0 text-fg-muted" />
            <span className="min-w-0 w-32 sm:w-56 truncate text-fg" title={`${j.source_root} → ${serverName(j.dest_server_id)}:${j.dest_root}`}>
              {j.direction === 'upload' ? 'Upload to' : 'Download from'} {j.remote_name}
            </span>
            {j.state === 'error' || j.state === 'cancelled' ? (
              <span className={`flex-1 min-w-0 truncate ${j.state === 'error' ? 'text-danger' : 'text-fg-muted'}`} title={j.error || ''}>
                {j.error}
              </span>
            ) : (
              <Progress
                percent={percent}
                size="small"
                className="flex-1 m-0"
                status={j.state === 'done' ? 'success' : 'active'}
                format={() => (j.state === 'done' ? `${j.result?.files ?? 0} files` : `${formatSize(j.sent_bytes)}`)}
              />
            )}
            {j.state === 'running' ? (
              <Button size="small" type="text" onClick={() => onCancel(j)}>
                Cancel
              </Button>
            ) : (
              <Button size="small" type="text" icon={<X size={14} />} aria-label="Dismiss" onClick={() => onDismiss(j)} />
            )}
          </div>
        );
      })}
    </div>
  );
};
