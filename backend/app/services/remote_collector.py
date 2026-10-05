import json
import logging
import time
from typing import Dict, Optional
from app.models.metrics import (
    SystemMetricsPayload, CpuMetrics, MemoryMetrics,
    DiskIoMetrics, NetworkMetrics, HostInfo
)
from app.services.ssh_manager import ssh_manager, ServerConnectionInfo

logger = logging.getLogger("remote_collector")

REMOTE_PROBE_SCRIPT = r"""python3 -c "
import json, time, os, platform

def get_cpu():
    with open('/proc/stat') as f:
        fields = [float(column) for column in f.readline().strip().split()[1:]]
    idle, total = fields[3], sum(fields)
    return idle, total

def get_mem():
    mem = {}
    with open('/proc/meminfo') as f:
        for line in f:
            parts = line.split(':')
            if len(parts) == 2:
                mem[parts[0].strip()] = int(parts[1].strip().split()[0]) * 1024
    total = mem.get('MemTotal', 1)
    avail = mem.get('MemAvailable', mem.get('MemFree', 0))
    used = max(0, total - avail)
    return total, used, avail, round((used / total) * 100, 1)

def get_io():
    reads, writes = 0, 0
    try:
        with open('/proc/diskstats') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    # sectors read * 512, sectors written * 512
                    reads += int(parts[5]) * 512
                    writes += int(parts[9]) * 512
    except Exception:
        pass
    return reads, writes

def get_net():
    rx, tx = 0, 0
    try:
        with open('/proc/net/dev') as f:
            for line in f.readlines()[2:]:
                parts = line.split(':')
                if len(parts) == 2:
                    sub = parts[1].split()
                    rx += int(sub[0])
                    tx += int(sub[8])
    except Exception:
        pass
    return rx, tx

def get_os():
    pretty = 'Linux'
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    pretty = line.split('=', 1)[1].strip('\"\'\n')
                    break
    except Exception:
        pass
    return pretty

uname = platform.uname()
idle1, tot1 = get_cpu()
time.sleep(0.1)
idle2, tot2 = get_cpu()
diff_idle = idle2 - idle1
diff_tot = max(tot2 - tot1, 0.0001)
cpu_pct = round((1.0 - (diff_idle / diff_tot)) * 100.0, 1)

tot_mem, used_mem, free_mem, mem_pct = get_mem()
disk_r, disk_w = get_io()
net_rx, net_tx = get_net()

with open('/proc/loadavg') as f:
    loads = [float(x) for x in f.read().split()[:3]]

with open('/proc/uptime') as f:
    uptime = float(f.read().split()[0])

cores = os.cpu_count() or 1

print(json.dumps({
    'cpu_pct': cpu_pct,
    'cores': cores,
    'load_avg': loads,
    'mem_total': tot_mem,
    'mem_used': used_mem,
    'mem_free': free_mem,
    'mem_pct': mem_pct,
    'disk_r': disk_r,
    'disk_w': disk_w,
    'net_rx': net_rx,
    'net_tx': net_tx,
    'hostname': uname.node,
    'os_name': get_os(),
    'kernel': f'{uname.system} {uname.release}',
    'uptime': uptime,
    'cpu_model': uname.processor or 'Linux Remote CPU'
}))
" 2>/dev/null
"""

class RemoteCollector:
    def __init__(self):
        # Cache previous state per server to compute rates
        self._prev_state: Dict[str, dict] = {}

    async def collect(self, info: ServerConnectionInfo) -> Optional[SystemMetricsPayload]:
        now = time.time()
        exit_code, stdout, stderr = await ssh_manager.run_command(info, REMOTE_PROBE_SCRIPT, timeout=5.0, elevate=False)
        if exit_code != 0 or not stdout.strip():
            logger.warning(f"Failed to fetch remote metrics on {info.server_id}: {stderr}")
            return None

        try:
            data = json.loads(stdout.strip())
        except Exception as e:
            logger.error(f"Malformed JSON from remote metrics on {info.server_id}: {e}")
            return None

        prev = self._prev_state.get(info.server_id)
        if prev:
            dt = max(now - prev["timestamp"], 0.001)
            read_rate = max(0.0, (data["disk_r"] - prev["disk_r"]) / dt)
            write_rate = max(0.0, (data["disk_w"] - prev["disk_w"]) / dt)
            rx_rate = max(0.0, (data["net_rx"] - prev["net_rx"]) / dt)
            tx_rate = max(0.0, (data["net_tx"] - prev["net_tx"]) / dt)
        else:
            read_rate, write_rate, rx_rate, tx_rate = 0.0, 0.0, 0.0, 0.0

        self._prev_state[info.server_id] = {
            "timestamp": now,
            "disk_r": data["disk_r"],
            "disk_w": data["disk_w"],
            "net_rx": data["net_rx"],
            "net_tx": data["net_tx"]
        }

        return SystemMetricsPayload(
            server_id=info.server_id,
            timestamp=now,
            cpu=CpuMetrics(
                usage_percent=data["cpu_pct"],
                cores=data["cores"],
                load_avg=data["load_avg"]
            ),
            memory=MemoryMetrics(
                total=data["mem_total"],
                used=data["mem_used"],
                free=data["mem_free"],
                percent=data["mem_pct"]
            ),
            disk_io=DiskIoMetrics(
                read_bytes_sec=round(read_rate, 1),
                write_bytes_sec=round(write_rate, 1)
            ),
            network=NetworkMetrics(
                rx_bytes_sec=round(rx_rate, 1),
                tx_bytes_sec=round(tx_rate, 1)
            ),
            host_info=HostInfo(
                hostname=data["hostname"],
                os_name=data["os_name"],
                kernel=data["kernel"],
                uptime_seconds=data["uptime"],
                cpu_model=data["cpu_model"]
            )
        )

remote_collector = RemoteCollector()
