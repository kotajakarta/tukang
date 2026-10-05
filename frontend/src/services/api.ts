import axios from 'axios';
import { ServerNode, ServerCreateInput, ServerTestResult } from '../types/server';
import { SystemMetricsPayload } from '../types/metrics';
import {
  SystemdUnit, PodmanContainer, QuadletUnit,
  StorageOverview, NetworkOverview, SystemUser
} from '../types/system';

const client = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

export type Role = 'viewer' | 'operator' | 'admin';
export const ROLE_RANK: Record<Role, number> = { viewer: 1, operator: 2, admin: 3 };
export const hasRole = (user: { role: Role } | null, needed: Role) => !!user && ROLE_RANK[user.role] >= ROLE_RANK[needed];

export interface AuthUser {
  id: number;
  username: string;
  role: Role;
  mfa_enabled: boolean;
  mfa_setup_required: boolean;
}

export interface AppAccount {
  id: number;
  username: string;
  role: Role;
  disabled: boolean;
  mfa_enabled: boolean;
  created_at?: string;
  last_login_at?: string;
}

export interface AuditEntry {
  id: number;
  ts: number;
  username?: string;
  ip?: string;
  action: string;
  server_id?: string;
  target?: string;
  success: boolean;
  detail?: string;
}

export type FileType = 'directory' | 'file' | 'link' | 'device' | 'fifo' | 'socket' | 'other';

export interface FileEntry {
  name: string;
  path: string;
  type: FileType;
  size: number;
  mtime: number;
  mode: number;
  perms: string;
  owner: string;
  group: string;
  target?: string;
  target_type?: FileType | 'broken';
}

export interface FileActionBody {
  op: 'write' | 'mkdir' | 'symlink' | 'rename' | 'paste' | 'delete' | 'chmod';
  path?: string;
  paths?: string[];
  new_path?: string;
  dest_dir?: string;
  mode?: number | 'copy' | 'move';
  content?: string;
  create?: boolean;
  expected_mtime?: number;
  target?: string;
  owner?: string;
  group?: string;
  recursive?: boolean;
}

/** A folder on one server paired with a folder on another (like the VS Code SFTP extension's sftp.json) */
export interface FileRemote {
  id: number;
  name: string;
  local_server_id: string;
  local_path: string;
  remote_server_id: string;
  remote_path: string;
  ignore: string[];
  updated_at?: string;
}

export type FileRemoteInput = Omit<FileRemote, 'id' | 'updated_at'>;
export type TransferDirection = 'upload' | 'download';

export interface TransferScan {
  files: number;
  dirs: number;
  links: number;
  bytes: number;
  ignored: number;
  unsupported: number;
  /** Selected paths that the ignore rules exclude (never sent) */
  skipped: string[];
  tar_bytes: number;
  source_server_id: string;
  source_root: string;
  dest_server_id: string;
  dest_root: string;
  rels: string[];
}

export interface TransferJob {
  id: string;
  remote_id: number;
  remote_name: string;
  direction: TransferDirection;
  state: 'running' | 'done' | 'error' | 'cancelled';
  source_server_id: string;
  source_root: string;
  dest_server_id: string;
  dest_root: string;
  rels: string[];
  sent_bytes: number;
  total_bytes: number;
  total_files: number;
  result: { files: number; dirs: number; links: number; bytes: number } | null;
  error: string | null;
}

// Called whenever the backend reports the session is missing/expired (HTTP 401 or WS close 4401)
let unauthorizedHandler: (() => void) | null = null;
export const setUnauthorizedHandler = (handler: (() => void) | null) => {
  unauthorizedHandler = handler;
};
export const notifyUnauthorized = () => unauthorizedHandler?.();

// Called when the backend says this account must enroll MFA first (HTTP 403 mfa_setup_required)
let mfaRequiredHandler: (() => void) | null = null;
export const setMfaRequiredHandler = (handler: (() => void) | null) => {
  mfaRequiredHandler = handler;
};

/** WebSocket close code the backend uses when the session cookie is invalid. */
export const WS_UNAUTHORIZED = 4401;

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error.config?.url || '';
    if (error.response?.status === 401 && !url.startsWith('/auth/')) {
      notifyUnauthorized();
    }
    if (error.response?.status === 403 && error.response?.data?.detail === 'mfa_setup_required') {
      mfaRequiredHandler?.();
    }
    return Promise.reject(error);
  }
);

export const api = {
  // Auth
  login: (username: string, password: string, otp?: string) =>
    client.post<AuthUser>('/auth/login', { username, password, otp }).then(r => r.data),
  mfaSetup: () => client.post<{ secret: string; otpauth_uri: string }>('/auth/mfa/setup').then(r => r.data),
  mfaEnable: (code: string) => client.post<{ recovery_codes: string[] }>('/auth/mfa/enable', { code }).then(r => r.data),
  mfaDisable: (password: string, code: string) => client.post('/auth/mfa/disable', { password, code }).then(r => r.data),
  mfaRegenerateCodes: (code: string) =>
    client.post<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes', { code }).then(r => r.data),

  // Access control (admin)
  getAccounts: () => client.get<AppAccount[]>('/app-users').then(r => r.data),
  createAccount: (username: string, password: string, role: Role) =>
    client.post<AppAccount>('/app-users', { username, password, role }).then(r => r.data),
  updateAccount: (id: number, changes: { role?: Role; disabled?: boolean }) =>
    client.put<AppAccount>(`/app-users/${id}`, changes).then(r => r.data),
  resetAccountPassword: (id: number, newPassword: string) =>
    client.post(`/app-users/${id}/reset-password`, { new_password: newPassword }).then(r => r.data),
  resetAccountMfa: (id: number) => client.post(`/app-users/${id}/reset-mfa`).then(r => r.data),
  deleteAccount: (id: number) => client.delete(`/app-users/${id}`).then(r => r.data),
  logout: () => client.post('/auth/logout').then(r => r.data),
  logoutAll: () => client.post('/auth/logout-all').then(r => r.data),
  me: () => client.get<AuthUser>('/auth/me').then(r => r.data),
  changePassword: (currentPassword: string, newPassword: string) =>
    client.post('/auth/change-password', { current_password: currentPassword, new_password: newPassword }).then(r => r.data),

  // Files
  filesList: (serverId: string, path: string, showHidden: boolean) =>
    client
      .get<{ path: string; entries: FileEntry[]; self: FileEntry }>(`/files/${serverId}/list`, { params: { path, show_hidden: showHidden } })
      .then(r => r.data),
  filesRead: (serverId: string, path: string) =>
    client.get<{ path: string; content: string; mtime: number; size: number }>(`/files/${serverId}/read`, { params: { path } }).then(r => r.data),
  filesPrincipals: (serverId: string) =>
    client.get<{ users: string[]; groups: string[]; home: string }>(`/files/${serverId}/principals`).then(r => r.data),
  filesAction: <T = any>(serverId: string, body: FileActionBody) =>
    client.post<T>(`/files/${serverId}/action`, body).then(r => r.data),
  filesUpload: (serverId: string, dir: string, file: File, overwrite: boolean, onProgress?: (fraction: number) => void) =>
    client
      .post<FileEntry>(`/files/${serverId}/upload`, file, {
        params: { dir, name: file.name, overwrite },
        headers: { 'Content-Type': 'application/octet-stream' },
        timeout: 0,
        onUploadProgress: (e) => e.total && onProgress?.(e.loaded / e.total),
      })
      .then(r => r.data),
  filesDownloadUrl: (serverId: string, path: string) =>
    `/api/v1/files/${encodeURIComponent(serverId)}/download?path=${encodeURIComponent(path)}`,
  /** Inline image/video/audio/PDF (cookie-authenticated, so usable as <img>/<video> src) */
  filesViewUrl: (serverId: string, path: string) =>
    `/api/v1/files/${encodeURIComponent(serverId)}/view?path=${encodeURIComponent(path)}`,
  /** `version` (mtime/size) busts the browser and server caches when the file changes. */
  filesThumbUrl: (serverId: string, path: string, version: string) =>
    `/api/v1/files/${encodeURIComponent(serverId)}/thumb?path=${encodeURIComponent(path)}&v=${encodeURIComponent(version)}`,

  filesRemotes: () => client.get<FileRemote[]>('/files/remotes').then(r => r.data),
  createFileRemote: (input: FileRemoteInput) => client.post<FileRemote>('/files/remotes', input).then(r => r.data),
  updateFileRemote: (id: number, input: FileRemoteInput) => client.put<FileRemote>(`/files/remotes/${id}`, input).then(r => r.data),
  deleteFileRemote: (id: number) => client.delete(`/files/remotes/${id}`).then(r => r.data),
  scanTransfer: (id: number, direction: TransferDirection, paths: string[]) =>
    client.post<TransferScan>(`/files/remotes/${id}/scan`, { direction, paths }).then(r => r.data),
  startTransfer: (id: number, direction: TransferDirection, paths: string[]) =>
    client.post<TransferJob>(`/files/remotes/${id}/transfer`, { direction, paths }).then(r => r.data),
  getTransfer: (jobId: string) => client.get<TransferJob>(`/files/transfers/${jobId}`).then(r => r.data),
  cancelTransfer: (jobId: string) => client.post<TransferJob>(`/files/transfers/${jobId}/cancel`).then(r => r.data),

  // Audit
  getAudit: (params: { limit?: number; before_id?: number; username?: string; action?: string }) =>
    client.get<AuditEntry[]>('/audit', { params }).then(r => r.data),

  // Server Inventory
  getServers: () => client.get<ServerNode[]>('/servers').then(r => r.data),
  getServer: (id: string) => client.get<ServerNode>(`/servers/${id}`).then(r => r.data),
  createServer: (input: ServerCreateInput) => client.post<ServerNode>('/servers', input).then(r => r.data),
  updateServer: (id: string, input: Partial<ServerCreateInput>) => client.put<ServerNode>(`/servers/${id}`, input).then(r => r.data),
  deleteServer: (id: string) => client.delete(`/servers/${id}`).then(r => r.data),
  resetHostKey: (id: string) => client.post<ServerNode>(`/servers/${id}/reset-host-key`).then(r => r.data),
  testServer: (id: string) => client.post<ServerTestResult>(`/servers/${id}/test`).then(r => r.data),

  // Metrics Snapshot
  getMetricsSnapshot: (serverId: string) => client.get<SystemMetricsPayload>(`/metrics/${serverId}`).then(r => r.data),

  // Systemd
  getUnits: (serverId: string, unitType: string = 'service') =>
    client.get<SystemdUnit[]>(`/services/${serverId}/units`, { params: { unit_type: unitType } }).then(r => r.data),
  unitAction: (serverId: string, unit: string, action: string) =>
    client.post<{ success: boolean; message: string }>(`/services/${serverId}/${unit}/action`, { action }).then(r => r.data),
  getUnitLogs: (serverId: string, unit: string, lines: number = 100) =>
    client.get<{ unit: string; logs: string[] }>(`/services/${serverId}/${unit}/logs`, { params: { lines } }).then(r => r.data),

  // Podman & Quadlets
  getContainers: (serverId: string) => client.get<PodmanContainer[]>(`/containers/${serverId}`).then(r => r.data),
  containerAction: (serverId: string, containerId: string, action: string) =>
    client.post<{ success: boolean; message: string }>(`/containers/${serverId}/${containerId}/action`, { action }).then(r => r.data),
  getContainerLogs: (serverId: string, containerId: string, lines: number = 100) =>
    client.get<{ container_id: string; logs: string[] }>(`/containers/${serverId}/${containerId}/logs`, { params: { lines } }).then(r => r.data),
  getQuadlets: (serverId: string) => client.get<QuadletUnit[]>(`/containers/${serverId}/quadlets/list`).then(r => r.data),
  getQuadletContent: (serverId: string, path: string) =>
    client.get<{ path: string; content: string }>(`/containers/${serverId}/quadlets/content`, { params: { path } }).then(r => r.data),
  // `path`: the existing file being edited, written in place
  saveQuadlet: (serverId: string, filename: string, content: string, isUser: boolean = false, path?: string) =>
    client
      .post<{ success: boolean; path: string; message: string; warning?: string | null }>(`/containers/${serverId}/quadlets`, {
        filename,
        content,
        is_user: isUser,
        path: path ?? null,
      })
      .then(r => r.data),
  deleteQuadlet: (serverId: string, path: string, isUser: boolean = false) =>
    client.delete(`/containers/${serverId}/quadlets`, { params: { path, is_user: isUser } }).then(r => r.data),

  // Storage
  getStorage: (serverId: string) => client.get<StorageOverview>(`/storage/${serverId}`).then(r => r.data),
  getSmart: (serverId: string, device: string) => client.get<any>(`/storage/${serverId}/smart/${device}`).then(r => r.data),

  // Network
  getNetwork: (serverId: string) => client.get<NetworkOverview>(`/network/${serverId}`).then(r => r.data),
  // sudoPassword is used for that one request only; the server never stores it
  allowFirewallPort: (serverId: string, port: number, endPort: number | null, protocol: 'tcp' | 'udp', sudoPassword?: string) =>
    client
      .post<{ success: boolean; message: string; needs_sudo?: boolean; firewall?: NetworkOverview['firewall'] }>(
        `/network/${serverId}/firewall/ports`,
        { port, end_port: endPort, protocol, sudo_password: sudoPassword || null },
      )
      .then(r => r.data),
  readFirewallRules: (serverId: string, sudoPassword: string) =>
    client
      .post<NetworkOverview['firewall']>(`/network/${serverId}/firewall/rules`, { sudo_password: sudoPassword })
      .then(r => r.data),

  // Users
  getUsers: (serverId: string) => client.get<SystemUser[]>(`/users/${serverId}`).then(r => r.data),
  createUser: (serverId: string, username: string, shell: string = '/bin/bash', isSudo: boolean = false) =>
    client.post<{ success: boolean; message: string }>(`/users/${serverId}`, { username, shell, is_sudo: isSudo }).then(r => r.data),
  deleteUser: (serverId: string, username: string, removeHome: boolean = true) =>
    client.delete(`/users/${serverId}/${username}`, { params: { remove_home: removeHome } }).then(r => r.data),
  getUserKeys: (serverId: string, username: string) =>
    client.get<{ username: string; keys: string[] }>(`/users/${serverId}/${username}/keys`).then(r => r.data),
  addUserKey: (serverId: string, username: string, key: string) =>
    client.post<{ success: boolean; message: string }>(`/users/${serverId}/${username}/keys`, { key }).then(r => r.data),
};
