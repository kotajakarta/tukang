export interface ServerNode {
  id: string;
  name: string;
  host: string;
  port: number;
  username: string;
  is_local: boolean;
  auth_type: 'key' | 'password' | 'agent';
  key_path?: string;
  use_sudo?: boolean;
  status: 'online' | 'offline' | 'unknown' | 'error';
  has_password?: boolean;
  has_private_key?: boolean;
  has_sudo_password?: boolean;
  host_key_fingerprint?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ServerCreateInput {
  id?: string;
  name: string;
  host: string;
  port?: number;
  username?: string;
  auth_type?: 'key' | 'password' | 'agent';
  key_path?: string;
  private_key?: string;
  password?: string;
  use_sudo?: boolean;
  /** Only for accounts without NOPASSWD; blank on edit keeps the stored one */
  sudo_password?: string;
}

export interface ServerTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  os_info?: string;
}
