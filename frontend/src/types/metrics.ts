export interface CpuMetrics {
  usage_percent: number;
  cores: number;
  load_avg: number[];
}

export interface MemoryMetrics {
  total: number;
  used: number;
  free: number;
  percent: number;
}

export interface DiskIoMetrics {
  read_bytes_sec: number;
  write_bytes_sec: number;
}

export interface NetworkMetrics {
  rx_bytes_sec: number;
  tx_bytes_sec: number;
}

export interface HostInfo {
  hostname: string;
  os_name: string;
  kernel: string;
  uptime_seconds: number;
  cpu_model: string;
}

export interface SystemMetricsPayload {
  type: string;
  server_id: string;
  timestamp: number;
  cpu: CpuMetrics;
  memory: MemoryMetrics;
  disk_io: DiskIoMetrics;
  network: NetworkMetrics;
  host_info?: HostInfo;
}

export interface MetricDataPoint {
  time: string;
  cpu: number;
  memory: number;
  diskReadMB: number;
  diskWriteMB: number;
  netRxKB: number;
  netTxKB: number;
}
