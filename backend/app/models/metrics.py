from typing import List, Optional
from pydantic import BaseModel, Field

class CpuMetrics(BaseModel):
    usage_percent: float = Field(0.0, description="Overall CPU usage percentage")
    cores: int = Field(1, description="Number of logical CPU cores")
    load_avg: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], description="1, 5, 15 min load averages")

class MemoryMetrics(BaseModel):
    total: int = Field(0, description="Total physical memory in bytes")
    used: int = Field(0, description="Used physical memory in bytes")
    free: int = Field(0, description="Free physical memory in bytes")
    percent: float = Field(0.0, description="Memory utilization percentage")

class DiskIoMetrics(BaseModel):
    read_bytes_sec: float = Field(0.0, description="Disk read rate in bytes/sec")
    write_bytes_sec: float = Field(0.0, description="Disk write rate in bytes/sec")

class NetworkMetrics(BaseModel):
    rx_bytes_sec: float = Field(0.0, description="Network incoming bytes/sec")
    tx_bytes_sec: float = Field(0.0, description="Network outgoing bytes/sec")

class HostInfo(BaseModel):
    hostname: str = "unknown"
    os_name: str = "Linux"
    kernel: str = ""
    uptime_seconds: float = 0.0
    cpu_model: str = "Generic CPU"

class SystemMetricsPayload(BaseModel):
    type: str = "metrics_update"
    server_id: str
    timestamp: float
    cpu: CpuMetrics
    memory: MemoryMetrics
    disk_io: DiskIoMetrics
    network: NetworkMetrics
    host_info: Optional[HostInfo] = None
