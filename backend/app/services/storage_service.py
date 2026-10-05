import json
import logging
from typing import List, Dict, Any, Tuple, Optional
import shlex
from app.core import validation
from app.services.executor import run_on_server

logger = logging.getLogger("storage_service")

class StorageService:
    async def _run_command(self, server_id: str, cmd: str, stdin: Optional[str] = None) -> Tuple[int, str, str]:
        return await run_on_server(server_id, cmd, timeout=15.0, stdin=stdin)

    async def get_storage_overview(self, server_id: str) -> Dict[str, Any]:
        # 1. Block devices via lsblk -J
        exit_code, stdout, _ = await self._run_command(server_id, "lsblk -J -b -o NAME,MAJ:MIN,RM,SIZE,RO,TYPE,MOUNTPOINT,FSTYPE,MODEL 2>/dev/null || lsblk -J")
        block_devices = []
        if exit_code == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
                block_devices = data.get("blockdevices", [])
            except Exception as e:
                logger.error(f"Error parsing lsblk: {e}")

        # 2. Filesystems via df
        df_script = r"""python3 -c "
import subprocess, json
try:
    res = subprocess.run(['df', '-P', '-T', '-k'], capture_output=True, text=True)
    lines = res.stdout.strip().splitlines()
    filesystems = []
    if len(lines) > 1:
        for line in lines[1:]:
            p = line.split()
            if len(p) >= 7:
                filesystems.append({
                    'filesystem': p[0],
                    'type': p[1],
                    'size_kb': int(p[2]),
                    'used_kb': int(p[3]),
                    'avail_kb': int(p[4]),
                    'percent': p[5],
                    'mounted_on': p[6]
                })
    print(json.dumps(filesystems))
except Exception as e:
    print('[]')
" 2>/dev/null
"""
        exit_code_df, stdout_df, _ = await self._run_command(server_id, df_script)
        filesystems = []
        if exit_code_df == 0 and stdout_df.strip():
            try:
                filesystems = json.loads(stdout_df.strip())
            except Exception:
                pass

        return {
            "server_id": server_id,
            "block_devices": block_devices,
            "filesystems": filesystems
        }

    async def get_smart_data(self, server_id: str, device: str) -> Dict[str, Any]:
        dev = shlex.quote("/dev/" + validation.block_device(device))
        cmd = f"smartctl -x -j {dev} 2>/dev/null || smartctl -H {dev} 2>/dev/null"
        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        if stdout.strip().startswith("{"):
            try:
                return json.loads(stdout)
            except Exception:
                pass
        return {
            "device": device,
            "smart_supported": False,
            "status": "passed" if exit_code == 0 else "unknown",
            "raw_output": stdout.strip() or stderr.strip() or "No SMART data available for virtual/emulated disk."
        }

storage_service = StorageService()
