import json
import logging
from typing import List, Tuple, Optional
from app.models.systemd import SystemdUnit, UnitActionResponse, JournalLogsResponse
import shlex
from app.core import validation
from app.services.executor import run_on_server

logger = logging.getLogger("systemd_service")

class SystemdService:
    async def _run_command(self, server_id: str, cmd: str, stdin: Optional[str] = None) -> Tuple[int, str, str]:
        return await run_on_server(server_id, cmd, timeout=15.0, stdin=stdin)

    async def list_units(self, server_id: str, unit_type: str = "service") -> List[SystemdUnit]:
        unit_type = shlex.quote(validation.unit_type(unit_type))
        units: List[SystemdUnit] = []
        seen_units = set()

        # Helper to parse systemctl JSON output
        def parse_json(out: str):
            try:
                data = json.loads(out)
                for item in data:
                    u_name = item.get("unit", "")
                    if not u_name or u_name in seen_units:
                        continue
                    seen_units.add(u_name)
                    u_type = unit_type
                    if "." in u_name:
                        u_type = u_name.rsplit(".", 1)[1]
                    units.append(SystemdUnit(
                        unit=u_name,
                        load=item.get("load", "unknown"),
                        active=item.get("active", "unknown"),
                        sub=item.get("sub", "unknown"),
                        description=item.get("description", ""),
                        unit_type=u_type
                    ))
            except Exception as e:
                logger.warning(f"Error parsing systemctl json: {e}")

        # 1. System units
        cmd = f"systemctl list-units --type={unit_type} --all --output=json"
        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        if exit_code == 0 and stdout.strip().startswith("["):
            parse_json(stdout)
        else:
            # Fallback tabular parser for system
            cmd_fallback = f"systemctl list-units --type={unit_type} --all --no-legend --no-pager"
            exit_code_fb, stdout_fb, _ = await self._run_command(server_id, cmd_fallback)
            for line in stdout_fb.splitlines():
                parts = line.strip().split(None, 4)
                if len(parts) >= 4:
                    u_name = parts[0]
                    if u_name in seen_units:
                        continue
                    seen_units.add(u_name)
                    u_type = unit_type
                    if "." in u_name:
                        u_type = u_name.rsplit(".", 1)[1]
                    units.append(SystemdUnit(
                        unit=u_name,
                        load=parts[1],
                        active=parts[2],
                        sub=parts[3],
                        description=parts[4] if len(parts) > 4 else "",
                        unit_type=u_type
                    ))

        # 2. User units (e.g. Quadlets or user services)
        cmd_user = f"systemctl --user list-units --type={unit_type} --all --output=json 2>/dev/null"
        exit_code_u, stdout_u, _ = await self._run_command(server_id, cmd_user)
        if exit_code_u == 0 and stdout_u.strip().startswith("["):
            parse_json(stdout_u)

        return units

    async def execute_action(self, server_id: str, unit: str, action: str) -> UnitActionResponse:
        valid_actions = ["start", "stop", "restart", "enable", "disable", "reload", "mask", "unmask"]
        if action not in valid_actions:
            return UnitActionResponse(success=False, unit=unit, action=action, message="Invalid action")

        q_unit = shlex.quote(validation.unit_name(unit))
        cmd = f"systemctl {action} -- {q_unit} 2>&1 || systemctl --user {action} -- {q_unit}"
        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        success = (exit_code == 0)
        msg = stdout.strip() or stderr.strip() or f"Successfully performed '{action}' on {unit}"
        return UnitActionResponse(
            success=success,
            unit=unit,
            action=action,
            message=msg
        )

    async def get_logs(self, server_id: str, unit: str, lines: int = 100) -> JournalLogsResponse:
        q_unit = shlex.quote(validation.unit_name(unit))
        lines = int(lines)
        cmd = f"journalctl -u {q_unit} -n {lines} --no-pager 2>/dev/null || journalctl --user -u {q_unit} -n {lines} --no-pager"
        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        logs = stdout.splitlines() if exit_code == 0 else [f"Failed to fetch logs: {stderr.strip()}"]
        return JournalLogsResponse(unit=unit, logs=logs)

systemd_service = SystemdService()
