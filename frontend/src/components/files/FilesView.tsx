import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Breadcrumb, Button, Card, Dropdown, Empty, Input, Modal, Progress, Segmented, Spin, Table, Tooltip, message } from 'antd';
import type { MenuProps } from 'antd';
import {
  ArrowLeftRight,
  ArrowUp,
  ClipboardPaste,
  CloudDownload,
  CloudUpload,
  Copy,
  Download,
  Eye,
  EyeOff,
  FilePlus,
  FolderPlus,
  Home,
  LayoutGrid,
  Link2,
  List,
  MoreVertical,
  Pencil,
  Play,
  RefreshCw,
  Scissors,
  Settings2,
  ShieldCheck,
  Star,
  StarOff,
  Trash2,
  Upload,
  FileEdit,
  HardDrive,
  SquareTerminal,
} from 'lucide-react';
import { useServer } from '../../context/ServerContext';
import { api, FileEntry, FileRemote, TransferDirection, TransferJob } from '../../services/api';
import { DeleteDialog, EditorDialog, LinkDialog, NameDialog, PermissionsDialog } from './FileDialogs';
import { FileThumb } from './FileThumb';
import { FileViewer } from './FileViewer';
import { RemoteDialog, TransferList, TransferSummary, isWithin, remotesFor } from './RemoteSync';
import {
  TYPE_LABEL,
  fileIcon,
  formatDate,
  formatSize,
  isDirLike,
  joinPath,
  linkDestination,
  parentOf,
  previewKind,
  thumbKind,
} from './fileUtils';

type ViewMode = 'list' | 'grid';
type Clipboard = { mode: 'copy' | 'move'; paths: string[]; serverId: string } | null;
type DialogState =
  | { kind: 'mkdir' }
  | { kind: 'newfile' }
  | { kind: 'rename'; item: FileEntry }
  | { kind: 'link'; target: string }
  | { kind: 'delete'; items: FileEntry[] }
  | { kind: 'perms'; items: FileEntry[] }
  | { kind: 'edit'; path: string }
  | { kind: 'view'; path: string }
  | { kind: 'remote'; remote: FileRemote | null; localPath: string }
  | null;

// Per-viewer conveniences only (never security state); storage may be unavailable
const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  },
};

const errorText = (e: any, fallback: string) => e?.response?.data?.detail || fallback;

const ico = (Icon: React.FC<any>) => <Icon size={15} strokeWidth={1.75} />;

interface FilesViewProps {
  /** Opens the Web Terminal in the given directory; omitted when the user may not use the terminal */
  onOpenTerminal?: (dir: string) => void;
}

export const FilesView: React.FC<FilesViewProps> = ({ onOpenTerminal }) => {
  const { activeServer, servers } = useServer();
  const serverId = activeServer?.id || 'local';

  const [path, setPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [current, setCurrent] = useState<FileEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [home, setHome] = useState('/root');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>(() => store.get('files.view', 'list'));
  const [showHidden, setShowHidden] = useState<boolean>(() => store.get('files.hidden', false));
  const [bookmarks, setBookmarks] = useState<string[]>(() => store.get(`files.bookmarks.${serverId}`, []));
  const [clipboard, setClipboard] = useState<Clipboard>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<{ name: string; progress: number; error?: string }[]>([]);
  const [remotes, setRemotes] = useState<FileRemote[]>([]);
  const [transfers, setTransfers] = useState<TransferJob[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => store.set('files.view', view), [view]);
  useEffect(() => store.set('files.hidden', showHidden), [showHidden]);
  useEffect(() => setBookmarks(store.get(`files.bookmarks.${serverId}`, [])), [serverId]);

  // Start in the last directory for this server, else the agent's home directory
  useEffect(() => {
    let cancelled = false;
    setPath(null);
    api
      .filesPrincipals(serverId)
      .then((p) => {
        if (cancelled) return;
        setHome(p.home);
        setPath(store.get(`files.last.${serverId}`, p.home));
      })
      .catch(() => !cancelled && setPath(store.get(`files.last.${serverId}`, '/')));
    return () => {
      cancelled = true;
    };
  }, [serverId]);

  const load = useCallback(
    async (target: string, keepSelection = false) => {
      setLoading(true);
      setLoadError(null);
      try {
        const res = await api.filesList(serverId, target, showHidden);
        setEntries(res.entries);
        setCurrent(res.self);
        if (!keepSelection) {
          setSelected(new Set());
          setAnchor(null);
        }
        store.set(`files.last.${serverId}`, res.path);
      } catch (e) {
        setLoadError(errorText(e, 'Failed to read directory'));
        setEntries([]);
      } finally {
        setLoading(false);
      }
    },
    [serverId, showHidden]
  );

  useEffect(() => {
    if (path) load(path);
  }, [path, load]);

  const refresh = useCallback(() => path && load(path, true), [path, load]);

  useEffect(() => {
    api.filesRemotes().then(setRemotes).catch(() => undefined);
  }, []);

  // Poll running transfers; refresh the listing when one finishes writing into the open directory
  const pathRef = useRef(path);
  pathRef.current = path;
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const serverIdRef = useRef(serverId);
  serverIdRef.current = serverId;
  const reported = useRef(new Set<string>());
  const anyRunning = transfers.some((t) => t.state === 'running');
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(async () => {
      const running = transfers.filter((t) => t.state === 'running');
      const updated = await Promise.all(running.map((t) => api.getTransfer(t.id).catch(() => t)));
      setTransfers((list) => list.map((t) => updated.find((u) => u.id === t.id) || t));
      for (const job of updated) {
        if (job.state === 'running' || reported.current.has(job.id)) continue;
        reported.current.add(job.id);
        if (job.state === 'done') {
          message.success(`${job.direction === 'upload' ? 'Uploaded to' : 'Downloaded from'} ${job.remote_name}: ${job.result?.files ?? 0} files`);
          setTimeout(() => setTransfers((list) => list.filter((t) => t.id !== job.id)), 6000);
        } else if (job.state === 'error') {
          message.error(`Transfer failed: ${job.error}`);
        }
        const here = pathRef.current;
        if (job.dest_server_id === serverIdRef.current && here && (isWithin(here, job.dest_root) || isWithin(job.dest_root, here))) {
          refreshRef.current();
        }
      }
    }, 800);
    return () => clearInterval(timer);
  }, [anyRunning, transfers]);

  const navigate = (target: string) => {
    setFilter('');
    setPath(target);
  };

  const sorted = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return entries
      .filter((e) => !q || e.name.toLowerCase().includes(q))
      .sort((a, b) => Number(isDirLike(b)) - Number(isDirLike(a)) || a.name.localeCompare(b.name, undefined, { numeric: true }));
  }, [entries, filter]);

  const existingNames = useMemo(() => new Set(entries.map((e) => e.name)), [entries]);
  const selectedItems = useMemo(() => sorted.filter((e) => selected.has(e.path)), [sorted, selected]);
  const detailItem = selectedItems.length === 1 ? selectedItems[0] : selectedItems.length === 0 ? current : null;
  // The viewer steps through the media files of this directory in display order
  const previewable = useMemo(() => sorted.filter((e) => previewKind(e)), [sorted]);
  const viewIndex = dialog?.kind === 'view' ? previewable.findIndex((e) => e.path === dialog.path) : -1;

  // ---------------------------------------------------------------- actions

  const open = (e: FileEntry) => {
    if (isDirLike(e)) return navigate(e.type === 'link' ? linkDestination(e) : e.path);
    if (previewKind(e)) setDialog({ kind: 'view', path: e.path });
    else if (e.type === 'file' || (e.type === 'link' && e.target_type === 'file')) setDialog({ kind: 'edit', path: e.path });
  };

  // Media opens in the viewer; SVG is also text, so it can be edited too
  const canEdit = (e: FileEntry) =>
    (e.type === 'file' || (e.type === 'link' && e.target_type === 'file')) && (!previewKind(e) || /\.svg$/i.test(e.name));

  const download = (e: FileEntry) => {
    const a = document.createElement('a');
    a.href = api.filesDownloadUrl(serverId, e.path);
    a.download = e.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) message.success(ok);
    } catch (e) {
      message.error(errorText(e, 'Operation failed'));
    } finally {
      refresh();
    }
  };

  const copyOrCut = (mode: 'copy' | 'move', items: FileEntry[]) => {
    if (!items.length) return;
    setClipboard({ mode, paths: items.map((i) => i.path), serverId });
    message.info(`${items.length} item${items.length > 1 ? 's' : ''} ${mode === 'copy' ? 'copied' : 'cut'}`);
  };

  const paste = (destDir: string) => {
    if (!clipboard || clipboard.serverId !== serverId) return;
    const { mode, paths } = clipboard;
    run(async () => {
      await api.filesAction(serverId, { op: 'paste', paths, dest_dir: destDir, mode });
      if (mode === 'move') setClipboard(null);
    }, mode === 'copy' ? 'Pasted' : 'Moved');
  };

  const serverName = (id: string) => servers.find((s) => s.id === id)?.name ?? id;

  const transfer = async (remote: FileRemote, direction: TransferDirection, paths: string[]) => {
    const hide = message.loading('Checking files…', 0);
    let scan;
    try {
      scan = await api.scanTransfer(remote.id, direction, paths);
    } catch (e) {
      message.error(errorText(e, 'Could not prepare the transfer'));
      return;
    } finally {
      hide();
    }
    const nothing = !(scan.files + scan.dirs + scan.links);
    Modal.confirm({
      title: direction === 'upload' ? `Upload to ${remote.name}?` : `Download from ${remote.name}?`,
      icon: direction === 'upload' ? <CloudUpload size={22} className="mr-3 text-accent flex-shrink-0" /> : <CloudDownload size={22} className="mr-3 text-accent flex-shrink-0" />,
      width: 520,
      content: <TransferSummary scan={scan} direction={direction} serverName={serverName} />,
      okText: direction === 'upload' ? 'Upload' : 'Download',
      okButtonProps: { disabled: nothing },
      onOk: async () => {
        try {
          const job = await api.startTransfer(remote.id, direction, paths);
          setTransfers((list) => [...list, job]);
        } catch (e) {
          message.error(errorText(e, 'Could not start the transfer'));
        }
      },
    });
  };

  // Upload/Download entries for the remotes covering `paths` (a submenu per remote when there are several)
  const remoteItems = (paths: string[], label: { up: string; down: string }): MenuProps['items'] => {
    const matching = remotesFor(remotes, serverId, paths);
    const entries = (r: FileRemote, suffix: string) => [
      { key: `up:${r.id}`, icon: ico(CloudUpload), label: `${label.up}${suffix}`, onClick: () => transfer(r, 'upload', paths) },
      { key: `down:${r.id}`, icon: ico(CloudDownload), label: `${label.down}${suffix}`, onClick: () => transfer(r, 'download', paths) },
    ];
    if (matching.length === 1) return entries(matching[0], ` ${matching[0].name}`);
    return matching.map((r) => ({ key: `remote:${r.id}`, icon: ico(ArrowLeftRight), label: r.name, children: entries(r, '') }));
  };

  const uploadFiles = async (files: File[]) => {
    if (!path || !files.length) return;
    const dir = path;
    setUploads(files.map((f) => ({ name: f.name, progress: 0 })));
    for (const [i, file] of files.entries()) {
      const setProgress = (p: number, error?: string) =>
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, progress: p, error } : x)));
      let overwrite = false;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        try {
          await api.filesUpload(serverId, dir, file, overwrite, setProgress);
          setProgress(1);
          break;
        } catch (e: any) {
          if (e?.response?.status === 409 && !overwrite) {
            const replace = await new Promise<boolean>((resolve) =>
              Modal.confirm({
                title: `Replace “${file.name}”?`,
                content: 'A file with the same name already exists in this directory.',
                okText: 'Replace',
                okButtonProps: { danger: true },
                cancelText: 'Skip',
                onOk: () => resolve(true),
                onCancel: () => resolve(false),
              })
            );
            if (replace) {
              overwrite = true;
              continue;
            }
            setProgress(0, 'Skipped');
          } else {
            setProgress(0, errorText(e, 'Upload failed'));
          }
          break;
        }
      }
    }
    refresh();
    setTimeout(() => setUploads((u) => (u.every((x) => x.progress === 1 || x.error) ? [] : u)), 4000);
  };

  const toggleBookmark = () => {
    if (!path) return;
    const next = bookmarks.includes(path) ? bookmarks.filter((b) => b !== path) : [...bookmarks, path];
    setBookmarks(next);
    store.set(`files.bookmarks.${serverId}`, next);
  };

  // ---------------------------------------------------------------- selection

  const onItemClick = (e: React.MouseEvent, item: FileEntry) => {
    const next = new Set(e.ctrlKey || e.metaKey ? selected : []);
    if (e.shiftKey && anchor) {
      const a = sorted.findIndex((x) => x.path === anchor);
      const b = sorted.findIndex((x) => x.path === item.path);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      sorted.slice(lo, hi + 1).forEach((x) => next.add(x.path));
    } else if ((e.ctrlKey || e.metaKey) && selected.has(item.path)) {
      next.delete(item.path);
    } else {
      next.add(item.path);
      setAnchor(item.path);
    }
    setSelected(next);
  };

  const onItemContext = (item: FileEntry) => {
    if (!selected.has(item.path)) {
      setSelected(new Set([item.path]));
      setAnchor(item.path);
    }
  };

  // ---------------------------------------------------------------- menus

  const itemMenu = (items: FileEntry[]): MenuProps['items'] => {
    const one = items.length === 1 ? items[0] : null;
    const isFile = one && (one.type === 'file' || (one.type === 'link' && one.target_type === 'file'));
    return [
      ...(one && isDirLike(one) ? [{ key: 'open', icon: ico(FolderPlus), label: 'Open', onClick: () => open(one) }] : []),
      ...(one && isDirLike(one) && onOpenTerminal
        ? [{ key: 'terminal', icon: ico(SquareTerminal), label: 'Open terminal here', onClick: () => onOpenTerminal(one.type === 'link' ? linkDestination(one) : one.path) }]
        : []),
      ...(one && isFile && previewKind(one) ? [{ key: 'view', icon: ico(Play), label: 'Open', extra: 'Enter', onClick: () => open(one) }] : []),
      ...(one && isFile && canEdit(one) ? [{ key: 'edit', icon: ico(FileEdit), label: 'Edit', onClick: () => setDialog({ kind: 'edit', path: one.path }) }] : []),
      ...(one && isFile ? [{ key: 'download', icon: ico(Download), label: 'Download', onClick: () => download(one) }] : []),
      ...(remotesFor(remotes, serverId, items.map((i) => i.path)).length
        ? [{ type: 'divider' as const }, ...remoteItems(items.map((i) => i.path), { up: 'Upload to', down: 'Download from' })!]
        : []),
      { type: 'divider' as const },
      { key: 'copy', icon: ico(Copy), label: 'Copy', extra: 'Ctrl+C', onClick: () => copyOrCut('copy', items) },
      { key: 'cut', icon: ico(Scissors), label: 'Cut', extra: 'Ctrl+X', onClick: () => copyOrCut('move', items) },
      ...(one && isDirLike(one) && clipboard
        ? [{ key: 'paste-into', icon: ico(ClipboardPaste), label: 'Paste into directory', onClick: () => paste(one.type === 'link' ? linkDestination(one) : one.path) }]
        : []),
      { type: 'divider' as const },
      ...(one ? [{ key: 'rename', icon: ico(Pencil), label: 'Rename', extra: 'F2', onClick: () => setDialog({ kind: 'rename', item: one }) }] : []),
      ...(one ? [{ key: 'link', icon: ico(Link2), label: 'Create link', onClick: () => setDialog({ kind: 'link', target: one.path }) }] : []),
      { key: 'perms', icon: ico(ShieldCheck), label: 'Edit permissions', onClick: () => setDialog({ kind: 'perms', items }) },
      { type: 'divider' as const },
      { key: 'delete', icon: ico(Trash2), label: 'Delete', extra: 'Del', danger: true, onClick: () => setDialog({ kind: 'delete', items }) },
    ];
  };

  const activeRemotes = path ? remotesFor(remotes, serverId, [path]) : [];

  const remoteSetupItems = (dir: string): NonNullable<MenuProps['items']> => [
    ...remotesFor(remotes, serverId, [dir]).map((r) => ({
      key: `edit:${r.id}`,
      icon: ico(Settings2),
      label: `Edit remote ${r.name}…`,
      onClick: () => setDialog({ kind: 'remote', remote: r, localPath: r.local_path }),
    })),
    {
      key: 'remote-new',
      icon: ico(ArrowLeftRight),
      label: activeRemotes.length ? 'Set up another remote for this folder…' : 'Set up remote for this folder…',
      onClick: () => setDialog({ kind: 'remote', remote: null, localPath: dir }),
    },
  ];

  const folderMenu: MenuProps['items'] = [
    { key: 'mkdir', icon: ico(FolderPlus), label: 'Create directory', onClick: () => setDialog({ kind: 'mkdir' }) },
    { key: 'newfile', icon: ico(FilePlus), label: 'Create file', onClick: () => setDialog({ kind: 'newfile' }) },
    { key: 'link', icon: ico(Link2), label: 'Create link', onClick: () => setDialog({ kind: 'link', target: '' }) },
    { key: 'upload', icon: ico(Upload), label: 'Upload files', onClick: () => fileInput.current?.click() },
    ...(onOpenTerminal && path
      ? [{ key: 'terminal', icon: ico(SquareTerminal), label: 'Open terminal in this folder', onClick: () => onOpenTerminal(path) }]
      : []),
    { type: 'divider' },
    ...(path ? remoteItems([path], { up: 'Upload this folder to', down: 'Download this folder from' })! : []),
    ...(path ? remoteSetupItems(path) : []),
    { type: 'divider' },
    { key: 'paste', icon: ico(ClipboardPaste), label: 'Paste', extra: 'Ctrl+V', disabled: !clipboard, onClick: () => path && paste(path) },
    { type: 'divider' },
    {
      key: 'hidden',
      icon: ico(showHidden ? EyeOff : Eye),
      label: showHidden ? 'Hide hidden items' : 'Show hidden items',
      extra: 'Ctrl+H',
      onClick: () => setShowHidden((v) => !v),
    },
    ...(current ? [{ key: 'perms', icon: ico(ShieldCheck), label: 'Edit permissions of this directory', onClick: () => setDialog({ kind: 'perms', items: [current] }) }] : []),
  ];

  const bookmarkMenu: MenuProps['items'] = [
    { key: 'home', icon: ico(Home), label: `Home (${home})`, onClick: () => navigate(home) },
    { key: 'root', label: 'Filesystem root (/)', onClick: () => navigate('/') },
    ...(bookmarks.length ? [{ type: 'divider' as const }] : []),
    ...bookmarks.map((b) => ({ key: `b:${b}`, label: <span className="font-mono text-xs">{b}</span>, onClick: () => navigate(b) })),
    { type: 'divider' as const },
    {
      key: 'toggle',
      icon: ico(path && bookmarks.includes(path) ? StarOff : Star),
      label: path && bookmarks.includes(path) ? 'Remove current directory' : 'Add bookmark',
      onClick: toggleBookmark,
    },
  ];

  // ---------------------------------------------------------------- keyboard

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).closest('input, textarea')) return;
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && key === 'a') {
      e.preventDefault();
      setSelected(new Set(sorted.map((x) => x.path)));
    } else if (mod && key === 'c') copyOrCut('copy', selectedItems);
    else if (mod && key === 'x') copyOrCut('move', selectedItems);
    else if (mod && key === 'v' && path) paste(path);
    else if (mod && key === 'h') {
      e.preventDefault();
      setShowHidden((v) => !v);
    } else if (e.key === 'Delete' && selectedItems.length) setDialog({ kind: 'delete', items: selectedItems });
    else if (e.key === 'F2' && selectedItems.length === 1) setDialog({ kind: 'rename', item: selectedItems[0] });
    else if (e.key === 'Enter' && selectedItems.length === 1) open(selectedItems[0]);
    else if ((e.key === 'Backspace' || (e.altKey && e.key === 'ArrowUp')) && path && path !== '/') navigate(parentOf(path));
    else if (e.key === 'Escape') setSelected(new Set());
  };

  // ---------------------------------------------------------------- render pieces

  const segments = useMemo(() => {
    if (!path) return [];
    const parts = path.split('/').filter(Boolean);
    return [{ name: '/', path: '/' }, ...parts.map((p, i) => ({ name: p, path: '/' + parts.slice(0, i + 1).join('/') }))];
  }, [path]);

  const nameCell = (e: FileEntry) => {
    const { Icon, color } = fileIcon(e);
    return (
      <span className="flex items-center gap-2 min-w-0">
        <FileThumb
          serverId={serverId}
          entry={e}
          className="w-[18px] h-6 rounded-sm"
          icon={<Icon size={18} color={color} strokeWidth={1.75} />}
        />
        <span className={`truncate ${isDirLike(e) ? 'font-medium text-fg' : 'text-fg'}`}>{e.name}</span>
        {e.type === 'link' && <span className="text-xs text-fg-subtle truncate font-mono">→ {e.target}</span>}
      </span>
    );
  };

  const rowMenuButton = (e: FileEntry) => (
    <Dropdown trigger={['click']} menu={{ items: itemMenu(selected.has(e.path) ? selectedItems : [e]) }}>
      <Button
        type="text"
        size="small"
        icon={<MoreVertical size={16} />}
        aria-label={`Actions for ${e.name}`}
        onClick={(ev) => {
          ev.stopPropagation();
          onItemContext(e);
        }}
      />
    </Dropdown>
  );

  const listView = (
    <Table<FileEntry>
      rowKey="path"
      size="small"
      dataSource={sorted}
      pagination={false}
      loading={loading}
      locale={{ emptyText: <Empty description={filter ? 'No matching items' : 'Empty directory'} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      rowClassName={(e) => `cursor-default select-none ${selected.has(e.path) ? 'files-row-selected' : ''}`}
      onRow={(e) => ({
        onClick: (ev) => onItemClick(ev, e),
        onDoubleClick: () => open(e),
        onContextMenu: () => onItemContext(e),
      })}
      columns={[
        {
          title: 'Name',
          key: 'name',
          sorter: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
          render: (_, e) => nameCell(e),
        },
        {
          title: 'Size',
          key: 'size',
          width: 100,
          align: 'right',
          sorter: (a, b) => a.size - b.size,
          render: (_, e) => <span className="text-fg-muted text-xs">{e.type === 'file' ? formatSize(e.size) : ''}</span>,
        },
        {
          title: 'Modified',
          key: 'mtime',
          width: 180,
          responsive: ['sm'],
          sorter: (a, b) => a.mtime - b.mtime,
          render: (_, e) => <span className="text-fg-muted text-xs">{formatDate(e.mtime)}</span>,
        },
        {
          title: 'Owner',
          key: 'owner',
          width: 140,
          responsive: ['md'],
          sorter: (a, b) => a.owner.localeCompare(b.owner),
          render: (_, e) => (
            <span className="text-fg-muted text-xs">
              {e.owner}
              {e.group !== e.owner ? `:${e.group}` : ''}
            </span>
          ),
        },
        {
          title: 'Permissions',
          key: 'perms',
          width: 120,
          responsive: ['lg'],
          render: (_, e) => <span className="font-mono text-xs text-fg-muted">{e.perms}</span>,
        },
        { title: '', key: 'menu', width: 44, render: (_, e) => rowMenuButton(e) },
      ]}
    />
  );

  const gridView = loading ? (
    <div className="py-16 text-center">
      <Spin />
    </div>
  ) : sorted.length === 0 ? (
    <Empty className="py-10" description={filter ? 'No matching items' : 'Empty directory'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  ) : (
    <div className="grid gap-2 p-1" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(112px, 1fr))' }}>
      {sorted.map((e) => {
        const { Icon, color } = fileIcon(e);
        const isSel = selected.has(e.path);
        return (
          <Dropdown key={e.path} trigger={['contextMenu']} menu={{ items: itemMenu(isSel ? selectedItems : [e]) }}>
            <button
              type="button"
              title={e.name}
              onClick={(ev) => onItemClick(ev, e)}
              onDoubleClick={() => open(e)}
              onContextMenu={() => onItemContext(e)}
              className={`flex flex-col items-center gap-1.5 p-2 rounded-lg border text-center transition-colors cursor-default ${
                isSel ? 'bg-accent/20 border-accent/60' : 'bg-transparent border-transparent hover:bg-fg/5'
              }`}
            >
              <FileThumb
                serverId={serverId}
                entry={e}
                badge
                className="w-full max-w-[96px] aspect-[3/4] rounded-md"
                icon={<Icon size={40} color={color} strokeWidth={1.25} />}
              />
              <span className="text-xs text-fg w-full break-words line-clamp-2">{e.name}</span>
            </button>
          </Dropdown>
        );
      })}
    </div>
  );

  const details = detailItem && (
    <div className="space-y-3">
      <div className="flex flex-col items-center text-center gap-2 pt-1">
        <FileThumb
          serverId={serverId}
          entry={detailItem}
          badge
          className={`rounded-md ${thumbKind(detailItem) ? 'w-36 aspect-[3/4] bg-fg/5' : 'w-full h-12'}`}
          icon={React.createElement(fileIcon(detailItem).Icon, { size: 44, color: fileIcon(detailItem).color, strokeWidth: 1.25 })}
        />
        <div className="font-semibold text-fg break-all">{detailItem.name}</div>
        <div className="text-xs text-fg-muted">
          {detailItem === current ? 'Current directory' : TYPE_LABEL[detailItem.type]}
          {detailItem.type === 'file' ? ` · ${formatSize(detailItem.size)}` : ''}
        </div>
      </div>
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-xs m-0">
        {detailItem.type === 'link' && (
          <>
            <dt className="text-fg-subtle">Target</dt>
            <dd className="m-0 font-mono break-all text-fg">{detailItem.target}</dd>
          </>
        )}
        <dt className="text-fg-subtle">Modified</dt>
        <dd className="m-0 text-fg">{formatDate(detailItem.mtime)}</dd>
        <dt className="text-fg-subtle">Owner</dt>
        <dd className="m-0 text-fg">{detailItem.owner}</dd>
        <dt className="text-fg-subtle">Group</dt>
        <dd className="m-0 text-fg">{detailItem.group}</dd>
        <dt className="text-fg-subtle">Permissions</dt>
        <dd className="m-0 font-mono text-fg">
          {detailItem.perms} ({detailItem.mode.toString(8).padStart(4, '0')})
        </dd>
      </dl>
      <div className="flex flex-wrap gap-1.5">
        {detailItem !== current && (detailItem.type === 'file' || detailItem.target_type === 'file') && (
          <>
            {previewKind(detailItem) && (
              <Button size="small" icon={ico(Play)} onClick={() => open(detailItem)}>
                Open
              </Button>
            )}
            {canEdit(detailItem) && (
              <Button size="small" icon={ico(FileEdit)} onClick={() => setDialog({ kind: 'edit', path: detailItem.path })}>
                Edit
              </Button>
            )}
            <Button size="small" icon={ico(Download)} onClick={() => download(detailItem)}>
              Download
            </Button>
          </>
        )}
        <Button size="small" icon={ico(ShieldCheck)} onClick={() => setDialog({ kind: 'perms', items: [detailItem] })}>
          Permissions
        </Button>
        {detailItem !== current && (
          <>
            <Button size="small" icon={ico(Pencil)} onClick={() => setDialog({ kind: 'rename', item: detailItem })}>
              Rename
            </Button>
            <Button size="small" danger icon={ico(Trash2)} onClick={() => setDialog({ kind: 'delete', items: [detailItem] })}>
              Delete
            </Button>
          </>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------- layout

  return (
    <Card className="shadow-sm" styles={{ body: { padding: 0 } }}>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2.5 border-b border-line">
        <Dropdown trigger={['click']} menu={{ items: bookmarkMenu }}>
          <Button icon={<Star size={16} className={path && bookmarks.includes(path) ? 'fill-warning text-warning' : ''} />} aria-label="Bookmarks" />
        </Dropdown>
        <Tooltip title="Parent directory (Backspace)">
          <Button icon={<ArrowUp size={16} />} disabled={!path || path === '/'} onClick={() => path && navigate(parentOf(path))} aria-label="Up" />
        </Tooltip>

        <div className="flex-1 min-w-[200px]">
          {editingPath !== null ? (
            <Input
              autoFocus
              size="middle"
              className="font-mono"
              value={editingPath}
              onChange={(e) => setEditingPath(e.target.value)}
              onBlur={() => setEditingPath(null)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditingPath(null);
                if (e.key === 'Enter') {
                  const v = editingPath.trim();
                  setEditingPath(null);
                  if (v.startsWith('/')) navigate(v.length > 1 ? v.replace(/\/+$/, '') : '/');
                  else message.error('Enter an absolute path');
                }
              }}
            />
          ) : (
            <div
              className="flex items-center gap-1 min-h-[32px] px-2 rounded-md border border-line bg-canvas overflow-x-auto"
              onDoubleClick={() => setEditingPath(path || '/')}
            >
              <Breadcrumb
                className="files-breadcrumb whitespace-nowrap"
                items={segments.map((s, i) => {
                  // Root is shown as a drive icon so the path doesn't read "/ / tmp"
                  const label = s.path === '/' ? <HardDrive size={14} className="align-[-2px]" aria-label="Filesystem root" /> : s.name;
                  return {
                    title:
                      i === segments.length - 1 ? (
                        <span className="text-fg font-medium">{label}</span>
                      ) : (
                        <a onClick={() => navigate(s.path)}>{label}</a>
                      ),
                  };
                })}
                separator={<span className="text-fg-subtle">/</span>}
              />
              <Button
                type="text"
                size="small"
                className="ml-auto flex-shrink-0"
                icon={<Pencil size={13} />}
                onClick={() => setEditingPath(path || '/')}
                aria-label="Edit path"
              />
            </div>
          )}
        </div>

        <Input.Search placeholder="Filter directory" allowClear value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 190 }} />
        <Segmented<ViewMode>
          value={view}
          onChange={setView}
          options={[
            { value: 'list', icon: <List size={15} className="align-[-2px]" />, title: 'List view' },
            { value: 'grid', icon: <LayoutGrid size={15} className="align-[-2px]" />, title: 'Grid view' },
          ]}
        />
        {path && activeRemotes.length > 0 && (
          <Dropdown
            trigger={['click']}
            menu={{ items: [...remoteItems([path], { up: 'Upload this folder to', down: 'Download this folder from' })!, { type: 'divider' as const }, ...remoteSetupItems(path)] }}
          >
            <Tooltip
              title={activeRemotes.map((r) => (
                <div key={r.id}>
                  {r.name} → {serverName(r.remote_server_id)}: <span className="font-mono">{r.remote_path}</span>
                </div>
              ))}
            >
              <Button icon={<ArrowLeftRight size={15} />}>
                <span className="hidden sm:inline max-w-[140px] truncate">
                  {activeRemotes.length === 1 ? activeRemotes[0].name : `${activeRemotes.length} remotes`}
                </span>
              </Button>
            </Tooltip>
          </Dropdown>
        )}
        <Button icon={<Upload size={15} />} onClick={() => fileInput.current?.click()}>
          <span className="hidden sm:inline">Upload</span>
        </Button>
        {onOpenTerminal && (
          <Tooltip title="Open terminal in this folder">
            <Button icon={<SquareTerminal size={15} />} disabled={!path} onClick={() => path && onOpenTerminal(path)}>
              <span className="hidden sm:inline">Terminal</span>
            </Button>
          </Tooltip>
        )}
        <Tooltip title="Refresh">
          <Button icon={<RefreshCw size={15} />} onClick={refresh} aria-label="Refresh" />
        </Tooltip>
        <Dropdown trigger={['click']} menu={{ items: folderMenu }}>
          <Button icon={<MoreVertical size={16} />} aria-label="Directory actions" />
        </Dropdown>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            uploadFiles(Array.from(e.target.files || []));
            e.target.value = '';
          }}
        />
      </div>

      {/* Body */}
      <div className="flex min-h-[420px]">
        <Dropdown trigger={['contextMenu']} menu={{ items: selectedItems.length ? itemMenu(selectedItems) : folderMenu }}>
          <div
            ref={container}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onClick={(e) => {
              if (e.target === e.currentTarget) setSelected(new Set());
            }}
            onContextMenu={(e) => {
              // Right-click on empty space targets the directory, not the old selection
              if (!(e.target as HTMLElement).closest('tr[data-row-key], button')) setSelected(new Set());
            }}
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes('Files')) {
                e.preventDefault();
                setDragOver(true);
              }
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              uploadFiles(Array.from(e.dataTransfer.files));
            }}
            className={`relative flex-1 min-w-0 p-2 outline-none ${dragOver ? 'ring-2 ring-inset ring-accent bg-accent/5' : ''}`}
          >
            {loadError ? (
              <Empty className="py-10" description={<span className="text-danger">{loadError}</span>}>
                <Button onClick={() => navigate(home)}>Go to home directory</Button>
              </Empty>
            ) : view === 'list' ? (
              listView
            ) : (
              gridView
            )}
            {dragOver && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-accent font-medium">
                Drop files to upload to {path}
              </div>
            )}
          </div>
        </Dropdown>

        <aside className="hidden lg:block w-72 flex-shrink-0 border-l border-line p-4">
          {selectedItems.length > 1 ? (
            <div className="space-y-3 text-center pt-4">
              <div className="text-fg font-semibold">{selectedItems.length} items selected</div>
              <div className="text-xs text-fg-muted">
                {formatSize(selectedItems.filter((i) => i.type === 'file').reduce((s, i) => s + i.size, 0))} in files
              </div>
              <div className="flex flex-wrap justify-center gap-1.5">
                <Button size="small" icon={ico(Copy)} onClick={() => copyOrCut('copy', selectedItems)}>
                  Copy
                </Button>
                <Button size="small" icon={ico(Scissors)} onClick={() => copyOrCut('move', selectedItems)}>
                  Cut
                </Button>
                <Button size="small" icon={ico(ShieldCheck)} onClick={() => setDialog({ kind: 'perms', items: selectedItems })}>
                  Permissions
                </Button>
                <Button size="small" danger icon={ico(Trash2)} onClick={() => setDialog({ kind: 'delete', items: selectedItems })}>
                  Delete
                </Button>
              </div>
            </div>
          ) : (
            details
          )}
        </aside>
      </div>

      {/* Status bar */}
      <div className="flex items-center justify-between gap-3 px-3 py-1.5 border-t border-line text-xs text-fg-subtle">
        <span>
          {sorted.length} item{sorted.length === 1 ? '' : 's'}
          {selected.size ? ` · ${selected.size} selected` : ''}
          {!showHidden && ' · hidden items not shown'}
        </span>
        {clipboard && (
          <span className="truncate">
            {clipboard.paths.length} item{clipboard.paths.length > 1 ? 's' : ''} {clipboard.mode === 'copy' ? 'copied' : 'cut'} —{' '}
            <a onClick={() => path && paste(path)}>paste here</a> · <a onClick={() => setClipboard(null)}>clear</a>
          </span>
        )}
      </div>

      {uploads.length > 0 && (
        <div className="px-3 py-2 border-t border-line space-y-1">
          {uploads.map((u) => (
            <div key={u.name} className="flex items-center gap-3 text-xs">
              <span className="w-48 truncate text-fg">{u.name}</span>
              {u.error ? (
                <span className="text-danger">{u.error}</span>
              ) : (
                <Progress percent={Math.round(u.progress * 100)} size="small" className="flex-1 m-0" />
              )}
            </div>
          ))}
        </div>
      )}

      <TransferList
        jobs={transfers}
        serverName={serverName}
        onCancel={(job) => api.cancelTransfer(job.id).catch((e) => message.error(errorText(e, 'Cancel failed')))}
        onDismiss={(job) => setTransfers((list) => list.filter((t) => t.id !== job.id))}
      />

      {/* Dialogs */}
      <NameDialog
        open={dialog?.kind === 'mkdir'}
        title="Create directory"
        okText="Create"
        existing={existingNames}
        onClose={() => setDialog(null)}
        onSubmit={async (name) => {
          await api.filesAction(serverId, { op: 'mkdir', path: joinPath(path!, name) });
          refresh();
        }}
      />
      <NameDialog
        open={dialog?.kind === 'newfile'}
        title="Create file"
        okText="Create and edit"
        existing={existingNames}
        onClose={() => setDialog(null)}
        onSubmit={async (name) => {
          const p = joinPath(path!, name);
          await api.filesAction(serverId, { op: 'write', path: p, content: '', create: true });
          refresh();
          setTimeout(() => setDialog({ kind: 'edit', path: p }), 0);
        }}
      />
      <NameDialog
        open={dialog?.kind === 'rename'}
        title="Rename"
        okText="Rename"
        initial={dialog?.kind === 'rename' ? dialog.item.name : ''}
        existing={existingNames}
        onClose={() => setDialog(null)}
        onSubmit={async (name) => {
          if (dialog?.kind !== 'rename' || name === dialog.item.name) return;
          await api.filesAction(serverId, { op: 'rename', path: dialog.item.path, new_path: joinPath(path!, name) });
          refresh();
        }}
      />
      <LinkDialog
        open={dialog?.kind === 'link'}
        initialTarget={dialog?.kind === 'link' ? dialog.target : ''}
        existing={existingNames}
        onClose={() => setDialog(null)}
        onSubmit={async (target, name) => {
          await api.filesAction(serverId, { op: 'symlink', path: joinPath(path!, name), target });
          refresh();
        }}
      />
      <DeleteDialog
        open={dialog?.kind === 'delete'}
        items={dialog?.kind === 'delete' ? dialog.items : []}
        onClose={() => setDialog(null)}
        onConfirm={async () => {
          if (dialog?.kind !== 'delete') return;
          await api.filesAction(serverId, { op: 'delete', paths: dialog.items.map((i) => i.path) });
          setSelected(new Set());
          refresh();
        }}
      />
      <PermissionsDialog
        open={dialog?.kind === 'perms'}
        serverId={serverId}
        items={dialog?.kind === 'perms' ? dialog.items : []}
        onClose={() => setDialog(null)}
        onDone={() => {
          message.success('Permissions changed');
          refresh();
        }}
      />
      <FileViewer
        serverId={serverId}
        items={previewable}
        index={viewIndex >= 0 ? viewIndex : null}
        onIndexChange={(i) => {
          const item = previewable[i];
          if (!item) return;
          setDialog({ kind: 'view', path: item.path });
          // Keep the list selection on the file being viewed, so closing lands on it
          setSelected(new Set([item.path]));
          setAnchor(item.path);
        }}
        onDownload={download}
        onClose={() => setDialog(null)}
      />
      <RemoteDialog
        open={dialog?.kind === 'remote'}
        remote={dialog?.kind === 'remote' ? dialog.remote : null}
        localServerId={serverId}
        localPath={dialog?.kind === 'remote' ? dialog.localPath : path || '/'}
        servers={servers}
        onClose={() => setDialog(null)}
        onSaved={(saved) => {
          setRemotes((list) => [...list.filter((r) => r.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
          message.success(`Remote ${saved.name} saved`);
        }}
        onDeleted={(id) => setRemotes((list) => list.filter((r) => r.id !== id))}
      />
      <EditorDialog
        open={dialog?.kind === 'edit'}
        serverId={serverId}
        path={dialog?.kind === 'edit' ? dialog.path : null}
        onClose={() => setDialog(null)}
        onSaved={() => {
          message.success('Saved');
          refresh();
        }}
      />
    </Card>
  );
};
