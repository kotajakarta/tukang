import os
import platform
import time
import psutil
from app.models.metrics import (
    SystemMetricsPayload, CpuMetrics, MemoryMetrics,
    DiskIoMetrics, NetworkMetrics, HostInfo
)

class LocalCollector:
    def __init__(self):
        self._last_time = time.time()
        
        # Disk IO baseline
        disk = psutil.disk_io_counters()
        self._last_disk_read = disk.read_bytes if disk else 0
        self._last_disk_write = disk.write_bytes if disk else 0
        
        # Network IO baseline
        net = psutil.net_io_counters()
        self._last_net_rx = net.bytes_recv if net else 0
        self._last_net_tx = net.bytes_sent if net else 0

        # Boot time
        self._boot_time = psutil.boot_time()

        # Cache Host Info
        self._host_info = self._collect_host_info()

    def _collect_host_info(self) -> HostInfo:
        uname = platform.uname()
        os_pretty = "Linux"
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            os_pretty = line.split("=", 1)[1].strip('"\'\n')
                            break
        except Exception:
            pass

        cpu_model = uname.processor or "x86_64"
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        cpu_model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

        return HostInfo(
            hostname=uname.node,
            os_name=os_pretty,
            kernel=f"{uname.system} {uname.release}",
            uptime_seconds=round(time.time() - self._boot_time, 1),
            cpu_model=cpu_model
        )

    def collect(self, server_id: str = "local") -> SystemMetricsPayload:
        now = time.time()
        elapsed = max(now - self._last_time, 0.001)
        self._last_time = now

        # CPU
        cpu_pct = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_count(logical=True) or 1
        try:
            load1, load5, load15 = os.getloadavg()
        except (AttributeError, OSError):
            load1, load5, load15 = 0.0, 0.0, 0.0

        # Memory
        mem = psutil.virtual_memory()

        # Disk I/O delta
        disk = psutil.disk_io_counters()
        current_disk_read = disk.read_bytes if disk else 0
        current_disk_write = disk.write_bytes if disk else 0
        read_rate = max(0.0, (current_disk_read - self._last_disk_read) / elapsed)
        write_rate = max(0.0, (current_disk_write - self._last_disk_write) / elapsed)
        self._last_disk_read = current_disk_read
        self._last_disk_write = current_disk_write

        # Network delta
        net = psutil.net_io_counters()
        current_net_rx = net.bytes_recv if net else 0
        current_net_tx = net.bytes_sent if net else 0
        rx_rate = max(0.0, (current_net_rx - self._last_net_rx) / elapsed)
        tx_rate = max(0.0, (current_net_tx - self._last_net_tx) / elapsed)
        self._last_net_rx = current_net_rx
        self._last_net_tx = current_net_tx

        # Update uptime
        self._host_info.uptime_seconds = round(now - self._boot_time, 1)

        return SystemMetricsPayload(
            server_id=server_id,
            timestamp=now,
            cpu=CpuMetrics(
                usage_percent=round(cpu_pct, 1),
                cores=cores,
                load_avg=[round(load1, 2), round(load5, 2), round(load15, 2)]
            ),
            memory=MemoryMetrics(
                total=mem.total,
                used=mem.used,
                free=mem.available,
                percent=round(mem.percent, 1)
            ),
            disk_io=DiskIoMetrics(
                read_bytes_sec=round(read_rate, 1),
                write_bytes_sec=round(write_rate, 1)
            ),
            network=NetworkMetrics(
                rx_bytes_sec=round(rx_rate, 1),
                tx_bytes_sec=round(tx_rate, 1)
            ),
            host_info=self._host_info
        )

local_collector = LocalCollector()
