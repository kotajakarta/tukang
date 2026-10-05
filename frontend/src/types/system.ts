export interface SystemdUnit {
  unit: string;
  load: string;
  active: string;
  sub: string;
  description: string;
  unit_type: string;
}

export interface PodmanContainer {
  id: string;
  names: string[];
  image: string;
  state: string;
  status: string;
  created: string;
  ports?: any[];
  is_rootless?: boolean;
  systemd_unit?: string | null;
}

export interface QuadletUnit {
  name: string;
  path: string;
  unit_type: 'container' | 'network' | 'volume' | 'image' | 'kube' | 'pod' | 'build' | 'unknown';
  content?: string;
  is_user: boolean;
}

export interface BlockDevice {
  name: string;
  size: string;
  type: string;
  mountpoint?: string | null;
  mountpoints?: (string | null)[];
  fstype?: string;
  model?: string;
  children?: BlockDevice[];
}

export interface FilesystemMount {
  filesystem: string;
  type: string;
  size_kb: number;
  used_kb: number;
  avail_kb: number;
  percent: string;
  mounted_on: string;
}

export interface StorageOverview {
  server_id: string;
  block_devices: BlockDevice[];
  filesystems: FilesystemMount[];
}

export interface NetworkInterface {
  ifindex: number;
  ifname: string;
  flags: string[];
  mtu: number;
  operstate: string;
  address?: string;
  addr_info?: {
    family: string;
    local: string;
    prefixlen: number;
  }[];
}

export interface FirewallAllowedPort {
  port: number;
  end_port: number;
  /** tcp | udp | any */
  protocol: string;
  /** Only from this address/network; null = anywhere */
  source: string | null;
  /** firewalld service or ufw app profile */
  name: string | null;
}

export interface NetworkOverview {
  server_id: string;
  interfaces: NetworkInterface[];
  listening_sockets: {
    proto: string;
    state: string;
    local_address: string;
  }[];
  firewall: {
    type: string;
    active: boolean;
    rules: string[];
    /** Why rules are missing (engine stopped, or reading them needs root) */
    note?: string | null;
    /** Rules (and changes) need a sudo password on this node */
    needs_sudo?: boolean;
    /** Ports the firewall lets in; null = unknown (rules unread, or nftables) */
    allowed_ports?: FirewallAllowedPort[] | null;
    /** Default policy accepts every incoming port */
    allow_all?: boolean;
  };
}

export interface SystemUser {
  username: string;
  uid: number;
  gid: number;
  gecos?: string;
  home: string;
  shell: string;
  is_sudo: boolean;
  is_system: boolean;
}
