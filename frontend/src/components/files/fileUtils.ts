import {
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderSymlink,
  Link2,
  Link2Off,
  Cpu,
  type LucideIcon,
} from 'lucide-react';
import { FileEntry } from '../../services/api';

export const joinPath = (dir: string, name: string) => (dir === '/' ? `/${name}` : `${dir}/${name}`);

export const parentOf = (path: string) => {
  if (path === '/') return '/';
  const parent = path.slice(0, path.lastIndexOf('/'));
  return parent || '/';
};

export const isDirLike = (e: FileEntry) => e.type === 'directory' || (e.type === 'link' && e.target_type === 'directory');

/** Resolves where a symlink to a directory should navigate to. */
export const linkDestination = (e: FileEntry) => {
  if (e.type !== 'link' || !e.target) return e.path;
  if (e.target.startsWith('/')) return e.target;
  const parts = [...parentOf(e.path).split('/'), ...e.target.split('/')];
  const out: string[] = [];
  for (const p of parts) {
    if (!p || p === '.') continue;
    if (p === '..') out.pop();
    else out.push(p);
  }
  return '/' + out.join('/');
};

export const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
};

export const formatDate = (epoch: number) =>
  new Date(epoch * 1000).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

const ARCHIVE = /\.(zip|tar|gz|tgz|bz2|xz|zst|7z|rar|rpm|deb|iso)$/i;
const IMAGE = /\.(png|jpe?g|gif|svg|webp|ico|bmp|avif)$/i;
// Must stay in sync with _VIEW_TYPES in backend/app/api/v1/files.py
const VIDEO = /\.(mp4|m4v|webm|ogv|mov)$/i;
const AUDIO = /\.(mp3|m4a|ogg|oga|opus|wav|flac)$/i;
const PDF = /\.pdf$/i;

export type PreviewKind = 'image' | 'video' | 'audio' | 'pdf';

/** What the media viewer can show for this entry, or null (then it opens in the text editor). */
export const previewKind = (e: FileEntry): PreviewKind | null => {
  if (!(e.type === 'file' || (e.type === 'link' && e.target_type === 'file'))) return null;
  if (IMAGE.test(e.name)) return 'image';
  if (VIDEO.test(e.name)) return 'video';
  if (AUDIO.test(e.name)) return 'audio';
  if (PDF.test(e.name)) return 'pdf';
  return null;
};
/** Files that get a thumbnail instead of their type icon. */
export const thumbKind = (e: FileEntry): 'image' | 'video' | null => {
  const kind = previewKind(e);
  return kind === 'image' || kind === 'video' ? kind : null;
};
const CODE = /\.(py|js|ts|tsx|jsx|sh|go|rs|c|h|cpp|java|php|rb|json|ya?ml|toml|ini|conf|cfg|xml|html|css|sql|container|network|volume|service|timer|socket)$/i;
const TEXT = /\.(txt|md|log|csv|env)$/i;

export const fileIcon = (e: FileEntry): { Icon: LucideIcon; color: string } => {
  if (e.type === 'directory') return { Icon: Folder, color: '#58a6ff' };
  if (e.type === 'link') {
    if (e.target_type === 'broken') return { Icon: Link2Off, color: '#f85149' };
    if (e.target_type === 'directory') return { Icon: FolderSymlink, color: '#58a6ff' };
    return { Icon: Link2, color: '#a371f7' };
  }
  if (e.type !== 'file') return { Icon: Cpu, color: '#8b949e' };
  if (ARCHIVE.test(e.name)) return { Icon: FileArchive, color: '#d29922' };
  if (IMAGE.test(e.name)) return { Icon: FileImage, color: '#3fb950' };
  if (VIDEO.test(e.name)) return { Icon: FileVideo, color: '#f0883e' };
  if (AUDIO.test(e.name)) return { Icon: FileAudio, color: '#39c5cf' };
  if (PDF.test(e.name)) return { Icon: FileText, color: '#f85149' };
  if (CODE.test(e.name)) return { Icon: FileCode, color: '#db61a2' };
  if (TEXT.test(e.name)) return { Icon: FileText, color: '#c9d1d9' };
  return { Icon: File, color: '#8b949e' };
};

export const TYPE_LABEL: Record<string, string> = {
  directory: 'Directory',
  file: 'File',
  link: 'Symbolic link',
  device: 'Device',
  fifo: 'Named pipe',
  socket: 'Socket',
  other: 'Special file',
};

export type Access = 'rw' | 'r' | 'none';

export const accessOf = (mode: number, shift: number): Access => {
  const bits = (mode >> shift) & 7;
  if (bits & 2) return 'rw';
  if (bits & 4) return 'r';
  return 'none';
};

/** Cockpit-style mode builder: directories get +x with read, files get +x only if "executable". */
export const buildMode = (
  current: number,
  owner: Access,
  group: Access,
  other: Access,
  isDir: boolean,
  executable: boolean
) => {
  const bits = (a: Access) => {
    let v = a === 'rw' ? 6 : a === 'r' ? 4 : 0;
    if (v && (isDir || executable)) v |= 1;
    return v;
  };
  const special = current & 0o7000;
  return special | (bits(owner) << 6) | (bits(group) << 3) | bits(other);
};
