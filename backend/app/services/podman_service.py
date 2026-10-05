import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple, Optional
from app.models.podman import (
    PodmanContainer, ContainerActionResponse,
    QuadletUnit, QuadletSaveResponse
)
import shlex
from app.core import validation
from app.services.executor import run_on_server

logger = logging.getLogger("podman_service")

QUADLET_EXTENSIONS = {
    ".container": "container",
    ".network": "network",
    ".volume": "volume",
    ".image": "image",
    ".kube": "kube"
}

# Stop/restart wait out the container's StopTimeout (10s by default, often more for databases) before SIGKILL
ACTION_TIMEOUT = 90.0

PODMAN_SUBCOMMANDS = {
    "start": "start",
    "stop": "stop",
    "restart": "restart",
    "pause": "pause",
    "unpause": "unpause",
    "remove": "rm -f",
}
# Lifecycle actions that go through the owning systemd unit (Quadlet): podman stop/restart race the unit's
# Restart= policy, which brings the container straight back or recreates it under a new ID
SYSTEMD_ACTIONS = {"start", "stop", "restart"}

# Lists one scope's containers: argv[1] is "user" (the login user's rootless podman) or "system" (root's).
# Prints {"uid": ..., "containers": [...]}; each container gets _systemd_unit when systemd really runs it.
DISCOVERY_SCRIPT = r"""# podman-discovery
import json, os, subprocess, sys

user = sys.argv[1] == 'user'
uid = os.getuid()
containers = []
if not (user and uid == 0):  # a root login has no separate rootless scope
    try:
        proc = subprocess.run(['podman', 'ps', '-a', '--format', 'json'], capture_output=True, text=True, timeout=8)
        if proc.returncode == 0 and proc.stdout.strip():
            items = json.loads(proc.stdout)
            if isinstance(items, list):
                containers = [it for it in items if isinstance(it, dict)]
    except Exception:
        pass

# Which containers systemd really runs (Quadlet). The PODMAN_SYSTEMD_UNIT label alone is not proof:
# podman-compose stamps podman-compose@<project>.service on every container, unit or not.
UNIT_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_.:-')
ACTIVE = ('active', 'activating', 'reloading', 'deactivating')
COMPOSE_LABELS = ('io.podman.compose.project', 'com.docker.compose.project')

def unit_states(units):
    # One systemctl call; the property blocks come back in argument order
    units = sorted(units)
    if not units:
        return {}
    cmd = ['systemctl'] + (['--user'] if user else []) + ['show', '--property=LoadState,ActiveState'] + units
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    blocks = proc.stdout.strip().split(chr(10) * 2)
    if proc.returncode != 0 or len(blocks) != len(units):
        return None
    return {unit: dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            for unit, block in zip(units, blocks)}

def unit_label(it):
    labels = it.get('Labels') or {}
    unit = labels.get('PODMAN_SYSTEMD_UNIT') if isinstance(labels, dict) else None
    if isinstance(unit, str) and unit.endswith('.service') and not unit.startswith('-') and set(unit) <= UNIT_CHARS:
        return unit
    return None

scoped = [it for it in containers if unit_label(it)]
states = unit_states({unit_label(it) for it in scoped})
for it in scoped:
    unit = unit_label(it)
    if states is None:
        # systemd unreachable (no user bus): trust the label unless the container came from compose
        labels = it.get('Labels') or {}
        managed = not any(k in labels for k in COMPOSE_LABELS)
    else:
        st = states.get(unit, {})
        managed = st.get('LoadState') == 'loaded' and (it.get('State') != 'running' or st.get('ActiveState') in ACTIVE)
    if managed:
        it['_systemd_unit'] = unit

def quadlet_file(path):
    # ContainerName= and Image= from the [Container] section; Quadlet names the container systemd-<unit> by default
    found, section = {}, ''
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('['):
                    section = line
                elif section == '[Container]' and '=' in line and not line.startswith(('#', ';')):
                    key, value = line.split('=', 1)
                    found[key.strip()] = value.strip()
    except Exception:
        pass
    return found

def stopped_quadlets():
    # Quadlet runs containers with --rm, so a stopped service has no container left to list. Report those units
    # anyway, or there is nothing to press Start on.
    base = ['systemctl'] + (['--user'] if user else [])
    try:
        proc = subprocess.run(base + ['list-unit-files', '--type=service', '--state=generated', '--no-legend', '--plain'],
                              capture_output=True, text=True, timeout=5)
        units = [line.split()[0] for line in proc.stdout.splitlines() if line.strip()]
        if proc.returncode != 0 or not units:
            return []
        proc = subprocess.run(base + ['show', '--property=Id,SourcePath,LoadState,ActiveState'] + units,
                              capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    have = {unit_label(it) for it in containers}
    result = []
    for block in proc.stdout.strip().split(chr(10) * 2):
        st = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        unit, source = st.get('Id', ''), st.get('SourcePath', '')
        if not source.endswith('.container') or unit in have or set(unit) - UNIT_CHARS or st.get('LoadState') != 'loaded':
            continue
        spec = quadlet_file(source)
        result.append({
            'Id': '', 'Names': [spec.get('ContainerName') or 'systemd-' + unit[:-len('.service')]],
            'Image': spec.get('Image', ''), 'State': st.get('ActiveState', 'inactive'),
            'Status': 'Service ' + st.get('ActiveState', 'inactive'), '_systemd_unit': unit,
        })
    return result

if not (user and uid == 0):
    containers += stopped_quadlets()

print(json.dumps({'uid': uid, 'containers': containers}))
"""


# Lists one scope's Quadlet files: argv[1] "user" = the login user's own dirs (~, /run/user/<uid>,
# /etc/containers/systemd/users/<uid>); "system" = root's dirs, where users/ holds user units for everyone.
QUADLET_LISTING_SCRIPT = r"""# quadlet-listing
import os, json, sys

exts = {'.container', '.network', '.volume', '.image', '.kube', '.pod', '.build'}
if sys.argv[1] == 'user':
    uid = os.getuid()
    dirs = [
        (os.path.expanduser('~/.config/containers/systemd'), True),
        (os.path.expanduser('~/.local/share/containers/systemd'), True),
        (f'/run/user/{uid}/containers/systemd', True),
        (f'/etc/containers/systemd/users/{uid}', True),
    ]
else:
    dirs = [
        ('/etc/containers/systemd/users', True),
        ('/etc/containers/systemd', False),
        ('/run/containers/systemd', False),
        ('/usr/share/containers/systemd', False),
        ('/usr/local/share/containers/systemd', False),
    ]

result = []
seen_paths = set()

for d, is_user in dirs:
    if os.path.isdir(d):
        try:
            for root, _, files in os.walk(d, followlinks=True):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in exts:
                        full_p = os.path.join(root, f)
                        try:
                            real_p = os.path.realpath(full_p)
                        except Exception:
                            real_p = full_p
                        if full_p not in seen_paths and real_p not in seen_paths:
                            seen_paths.add(full_p)
                            seen_paths.add(real_p)
                            result.append({
                                'name': f,
                                'path': full_p,
                                'unit_type': ext[1:],
                                'is_user': is_user
                            })
        except Exception:
            pass

print(json.dumps(result))
"""

# Writes one quadlet file. Constant: filename/content arrive as JSON on stdin, so nothing user-supplied
# is ever parsed by the shell or by Python source.
QUADLET_WRITER_SCRIPT = r"""import json, os, sys, tempfile
req = json.load(sys.stdin)
if req['path']:
    base, name = os.path.split(req['path'])
else:
    base = os.path.expanduser('~/.config/containers/systemd') if req['is_user'] else '/etc/containers/systemd'
    name = req['filename']
    os.makedirs(base, exist_ok=True)
target = os.path.join(base, name)
if os.path.dirname(os.path.abspath(target)) != os.path.abspath(base) or os.path.islink(target):
    sys.exit('refusing to write outside the quadlet directory')
# The directory may belong to another user (who could plant links): create the temp file exclusively
# under a random name and only touch it through its descriptor
fd, tmp = tempfile.mkstemp(dir=base, prefix='.' + name + '.', suffix='.cockpit-tmp')
try:
    with os.fdopen(fd, 'w') as f:
        f.write(req['content'])
        os.fchmod(f.fileno(), 0o644)
    os.replace(tmp, target)
except BaseException:
    os.unlink(tmp)
    raise
print(target)
"""

# Quadlet dirs the login user owns; files anywhere else (/etc, /run/containers, /usr) are root's
OWN_QUADLET_DIR_RE = re.compile(
    r"^(/root|/home/[^/]+|/var/home/[^/]+)/(\.config|\.local/share)/containers/systemd/"
    r"|^/run/user/\d+/containers/systemd/"
)

# Prints one quadlet file (argv[1], a normalized absolute path). Run as root, it first takes on the identity
# of the first non-root owner along the path (e.g. the user of /home/<user>): a link that user planted in
# their quadlet dir then only reaches files they could read anyway, while their own links keep working.
QUADLET_READER_SCRIPT = r"""import os, sys
path = sys.argv[1]
if os.getuid() == 0:
    cur = '/'
    for part in path.strip('/').split('/'):
        cur = os.path.join(cur, part)
        st = os.lstat(cur)
        if st.st_uid != 0:
            os.setgroups([])
            os.setgid(st.st_gid)
            os.setuid(st.st_uid)
            break
with open(path) as f:
    sys.stdout.write(f.read())
"""

def quadlet_read_cmd(path: str) -> str:
    return f"python3 -c {shlex.quote(QUADLET_READER_SCRIPT)} {shlex.quote(path)}"

def as_root(cmd: str) -> str:
    """`cmd` run as root: as is when the session already is root (a root login, or the node's sudo setting
    elevated it), through passwordless sudo otherwise."""
    q = shlex.quote(cmd)
    return f'if [ "$(id -u)" -eq 0 ]; then sh -c {q}; else sudo -n -- sh -c {q}; fi'


class PodmanService:
    async def _run_command(self, server_id: str, cmd: str, stdin: Optional[str] = None) -> Tuple[int, str, str]:
        return await run_on_server(server_id, cmd, timeout=15.0, stdin=stdin)

    async def _run_scoped(
        self, server_id: str, cmd: str, rootless: bool, timeout: float = 15.0, stdin: Optional[str] = None
    ) -> Tuple[int, str, str]:
        if rootless:
            # The login user's own podman/systemd: never through the node's sudo setting, which would make it root's
            return await run_on_server(server_id, cmd, timeout=timeout, stdin=stdin, elevate=False)
        return await run_on_server(server_id, as_root(cmd), timeout=timeout, stdin=stdin)

    async def _discover(self, server_id: str, rootless: bool) -> List[dict]:
        cmd = f"python3 -c {shlex.quote(DISCOVERY_SCRIPT)} {'user' if rootless else 'system'} 2>/dev/null"
        exit_code, stdout, _ = await self._run_scoped(server_id, cmd, rootless)
        if exit_code != 0 or not stdout.strip():
            # e.g. no podman, or sudo needs a password the node was not given
            return []
        try:
            data = json.loads(stdout.strip())
        except ValueError as e:
            logger.error(f"Error parsing podman containers json: {e}")
            return []
        items = data.get("containers") if isinstance(data, dict) else None
        if not isinstance(items, list) or (rootless and data.get("uid") == 0):
            return []
        for item in items:
            item["_is_rootless"] = rootless
        return items

    async def list_containers(self, server_id: str) -> List[PodmanContainer]:
        user_items, system_items = await asyncio.gather(
            self._discover(server_id, rootless=True), self._discover(server_id, rootless=False)
        )
        containers: List[PodmanContainer] = []
        seen = set()
        for item in system_items + user_items:
            c_id = str(item.get("Id") or item.get("ID") or "")[:12]
            names = item.get("Names") or [c_id]
            if isinstance(names, str):
                names = [names]
            if not c_id and item.get("_systemd_unit"):
                c_id = str(names[0])  # stopped Quadlet service: no container yet, act on it by name
            if not c_id or c_id in seen:
                continue
            seen.add(c_id)
            try:
                containers.append(PodmanContainer(
                    id=c_id,
                    names=names,
                    image=str(item.get("Image") or item.get("ImageName") or "unknown"),
                    state=str(item.get("State", "unknown")),
                    status=str(item.get("Status", "")),
                    created=str(item.get("CreatedAt", item.get("Created", ""))),
                    ports=item.get("Ports") or [],
                    is_rootless=bool(item.get("_is_rootless", False)),
                    systemd_unit=item.get("_systemd_unit") or None
                ))
            except Exception as e:
                logger.error(f"Error parsing podman container {c_id}: {e}")
        return containers

    async def _find_container(self, server_id: str, ref: str) -> Optional[PodmanContainer]:
        # Scope and unit come from the node itself, never from the client
        for c in await self.list_containers(server_id):
            if c.id in (ref, ref[:12]) or ref in c.names:
                return c
        return None

    async def container_action(self, server_id: str, container_id: str, action: str) -> ContainerActionResponse:
        def response(success: bool, message: str) -> ContainerActionResponse:
            return ContainerActionResponse(success=success, container_id=container_id, action=action, message=message)

        sub = PODMAN_SUBCOMMANDS.get(action)
        if not sub:
            return response(False, "Invalid action")
        container = await self._find_container(server_id, validation.container_ref(container_id))
        if not container:
            return response(False, "Container not found (it may have been removed or recreated); refresh the list.")

        unit = container.systemd_unit
        if unit and action == "remove":
            return response(False, f"Managed by {unit}: stop the service instead, "
                                   f"or delete its Quadlet file to remove it for good.")
        if unit and action in SYSTEMD_ACTIONS:
            scope = "systemctl --user" if container.is_rootless else "systemctl"
            cmd = f"{scope} {action} -- {shlex.quote(validation.unit_name(unit))} 2>&1"
        else:
            cmd = f"podman {sub} -- {shlex.quote(container.id)} 2>&1"

        exit_code, stdout, stderr = await self._run_scoped(server_id, cmd, container.is_rootless, timeout=ACTION_TIMEOUT)
        success = (exit_code == 0)
        done = f"Action '{action}' completed" + (f" via {unit}." if unit and action in SYSTEMD_ACTIONS else ".")
        output = stdout.strip() or stderr.strip()
        if not success:
            return response(False, output or f"Action '{action}' failed.")
        if "resorting to SIGKILL" in output:
            done += " The container ignored SIGTERM and was killed after its stop timeout."
        return response(True, done)

    async def get_container_logs(self, server_id: str, container_id: str, lines: int = 100) -> List[str]:
        q_id = shlex.quote(validation.container_ref(container_id))
        lines = int(lines)
        # 2>&1: podman logs replays the container's stderr on stderr
        cmd = f"podman logs --tail {lines} -- {q_id} 2>&1"
        out = ""
        for rootless in (True, False):
            exit_code, stdout, stderr = await self._run_scoped(server_id, cmd, rootless)
            if exit_code == 0:
                return stdout.splitlines()
            out = out or stdout or stderr
        return out.splitlines()

    async def _run_quadlet_file_cmd(self, server_id: str, path: str, cmd: str) -> Tuple[int, str, str]:
        if OWN_QUADLET_DIR_RE.match(path):
            return await self._run_scoped(server_id, cmd, rootless=True)
        # Root's dirs (and /etc/containers/systemd/users/); a plain read still works where sudo does not
        return await run_on_server(server_id, f"{as_root(cmd)} || {cmd}")

    async def _daemon_reload(self, server_id: str, is_user: bool) -> Optional[str]:
        """Reloads the systemd manager that runs these quadlets; returns why it failed, if it did."""
        cmd = "systemctl --user daemon-reload 2>&1" if is_user else "systemctl daemon-reload 2>&1"
        exit_code, stdout, stderr = await self._run_scoped(server_id, cmd, rootless=is_user)
        if exit_code == 0:
            return None
        return (stdout.strip() or stderr.strip() or f"exit status {exit_code}")[:300]

    async def list_quadlets(self, server_id: str) -> List[QuadletUnit]:
        """
        Lists Quadlet files in all system and user search directories per Podman specification.
        User dirs are read as the login user (whose ~ and uid they hang off), system dirs as root.
        """
        def listing(rootless: bool) -> str:
            return f"python3 -c {shlex.quote(QUADLET_LISTING_SCRIPT)} {'user' if rootless else 'system'} 2>/dev/null"

        system_cmd = listing(False)
        (u_code, u_out, _), (s_code, s_out, _) = await asyncio.gather(
            self._run_scoped(server_id, listing(True), rootless=True),
            run_on_server(server_id, f"{as_root(system_cmd)} || {system_cmd}"),
        )
        quadlets: List[QuadletUnit] = []
        seen = set()
        for exit_code, stdout in ((s_code, s_out), (u_code, u_out)):
            if exit_code != 0 or not stdout.strip():
                continue
            try:
                data = json.loads(stdout.strip())
                for item in data:
                    if item["path"] in seen:
                        continue
                    seen.add(item["path"])
                    quadlets.append(QuadletUnit(
                        name=item["name"],
                        path=item["path"],
                        unit_type=item["unit_type"],
                        is_user=item["is_user"]
                    ))
            except Exception as e:
                logger.error(f"Error parsing quadlets output: {e}")
        return quadlets

    async def get_quadlet_content(self, server_id: str, file_path: str) -> Optional[str]:
        path = validation.quadlet_path(file_path)
        exit_code, stdout, stderr = await self._run_quadlet_file_cmd(server_id, path, quadlet_read_cmd(path))
        if exit_code == 0:
            return stdout
        return None

    async def save_quadlet(
        self, server_id: str, filename: str, content: str, is_user: bool = False, path: Optional[str] = None
    ) -> QuadletSaveResponse:
        filename = validation.quadlet_filename(filename)
        path = validation.quadlet_path(path) if path else None
        payload = json.dumps({"filename": filename, "content": content, "is_user": bool(is_user), "path": path})
        # A new user quadlet goes to the login user's ~ (through sudo, ~ would be root's), a new system one to /etc;
        # an edited file is written by whoever owns its directory
        rootless = bool(OWN_QUADLET_DIR_RE.match(path)) if path else bool(is_user)
        exit_code, stdout, stderr = await self._run_scoped(
            server_id, f"python3 -c {shlex.quote(QUADLET_WRITER_SCRIPT)}", rootless=rootless, stdin=payload
        )
        if exit_code != 0:
            return QuadletSaveResponse(success=False, path="", message=f"Failed to save file: {stderr.strip()}")

        saved_path = stdout.strip()
        reload_error = await self._daemon_reload(server_id, bool(is_user))
        if reload_error:
            warning = f"Quadlet saved, but systemd daemon-reload failed: {reload_error}"
            return QuadletSaveResponse(success=True, path=saved_path, message=warning, warning=warning)
        return QuadletSaveResponse(
            success=True,
            path=saved_path,
            message="Quadlet saved and systemd daemon reloaded successfully"
        )

    async def delete_quadlet(self, server_id: str, file_path: str, is_user: bool = False) -> bool:
        path = validation.quadlet_path(file_path)
        exit_code, _, _ = await self._run_quadlet_file_cmd(server_id, path, f"rm -f -- {shlex.quote(path)}")
        await self._daemon_reload(server_id, is_user)
        return (exit_code == 0)

podman_service = PodmanService()
