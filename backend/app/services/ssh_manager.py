import asyncio
import logging
import os
import shlex
import time
from typing import Dict, Optional, Tuple, Any
import asyncssh

logger = logging.getLogger("ssh_manager")

# sudo with a password: the password arrives as the first stdin line (never on a command line, so not in
# `ps` or shell history) and reaches sudo through a throwaway SUDO_ASKPASS helper. The elevated command
# gets the rest of stdin untouched, and -k makes sudo ask every time, so the line is always consumed by
# `read` here and never leaks into the command's input even if credentials are cached or NOPASSWD.
# The helper only holds `printenv`; the password itself lives in this shell's environment. It answers once:
# sudo re-asks after a wrong password, and three failures in a row can trip pam_faillock and lock the account.
_ASKPASS_SUDO = (
    'IFS= read -r TUKANG_SUDO_PW; export TUKANG_SUDO_PW; '
    'A=$(mktemp "${HOME:-/tmp}/.tukang-askpass.XXXXXX") || exit 1; '
    "trap 'rm -f \"$A\" \"$A.used\"' EXIT; "
    "printf '#!/bin/sh\\n[ -e \"$0.used\" ] && exit 1\\n: > \"$0.used\"\\nexec printenv TUKANG_SUDO_PW\\n' "
    '> "$A" && chmod 700 "$A" || exit 1; '
    # LC_MESSAGES=C: callers recognise sudo's refusals by text, and they are translated otherwise
    'LC_MESSAGES=C SUDO_ASKPASS="$A" sudo -k -A -p "" -- sh -c '
)

def askpass_sudo(command: str) -> str:
    """`command` run as root by sudo, whose password must be the first line on stdin."""
    return _ASKPASS_SUDO + shlex.quote(command)

def host_key_fingerprint(host_key: Optional[str]) -> Optional[str]:
    if not host_key:
        return None
    try:
        return asyncssh.import_public_key(host_key).get_fingerprint("sha256")
    except Exception:
        return None

async def _pin_host_key(server_id: str, host_key: str):
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.server import ServerModel

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(ServerModel).where(ServerModel.id == server_id))
        server = res.scalar_one_or_none()
        if server and not server.host_key:
            server.host_key = host_key
            await session.commit()
            logger.warning(
                f"Pinned SSH host key for {server_id} ({server.host}): {host_key_fingerprint(host_key)}"
            )

class ServerConnectionInfo:
    def __init__(
        self,
        server_id: str,
        host: str,
        port: int = 22,
        username: str = "root",
        auth_type: str = "key",
        key_path: Optional[str] = None,
        private_key: Optional[str] = None,
        password: Optional[str] = None,
        host_key: Optional[str] = None,
        use_sudo: bool = False,
        sudo_password: Optional[str] = None,
    ):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.username = username
        self.auth_type = auth_type
        self.key_path = key_path
        self.private_key = private_key
        self.password = password
        # Pinned host public key (OpenSSH format). None = not pinned yet (trust on first use).
        self.host_key = host_key
        self.use_sudo = use_sudo
        self.sudo_password = sudo_password

    @classmethod
    def from_server(cls, server: Any) -> "ServerConnectionInfo":
        return cls(
            server_id=server.id,
            host=server.host,
            port=server.port,
            username=server.username,
            auth_type=getattr(server, "auth_type", "key"),
            key_path=getattr(server, "key_path", None),
            private_key=getattr(server, "private_key", None),
            password=getattr(server, "password", None),
            host_key=getattr(server, "host_key", None),
            use_sudo=bool(getattr(server, "use_sudo", False)),
            sudo_password=getattr(server, "sudo_password", None),
        )

class SSHConnectionManager:
    """
    Manages persistent, keepalive SSH connection pools to managed Linux nodes using asyncssh.
    """
    def __init__(self):
        self._connections: Dict[str, asyncssh.SSHClientConnection] = {}
        self._lock = asyncio.Lock()

    async def get_connection(self, info: ServerConnectionInfo) -> asyncssh.SSHClientConnection:
        async with self._lock:
            conn = self._connections.get(info.server_id)
            if conn is not None:
                if not conn.is_closed():
                    return conn
                else:
                    logger.info(f"SSH connection to {info.server_id} was closed. Reconnecting...")
                    self._connections.pop(info.server_id, None)

            logger.info(f"Opening SSH connection to {info.username}@{info.host}:{info.port} [{info.server_id}]")
            
            client_keys = []
            if info.private_key:
                try:
                    imported_key = asyncssh.import_private_key(info.private_key)
                    client_keys.append(imported_key)
                except Exception as e:
                    logger.error(f"Failed to import private key for {info.server_id}: {e}")
                    raise ValueError(f"Invalid private key: {e}")
            elif info.key_path:
                client_keys.append(os.path.expanduser(info.key_path))
            elif info.auth_type == "key":
                for default_key in ["~/.ssh/id_ed25519", "~/.ssh/id_rsa"]:
                    expanded = os.path.expanduser(default_key)
                    if os.path.exists(expanded):
                        client_keys.append(expanded)

            connect_kwargs = {
                "host": info.host,
                "port": info.port,
                "username": info.username,
                # Verify against the pinned key; on first contact accept and pin it (TOFU)
                "known_hosts": ([asyncssh.import_public_key(info.host_key)], [], []) if info.host_key else None,
                "keepalive_interval": 30,
                "keepalive_count_max": 3,
            }

            if client_keys:
                connect_kwargs["client_keys"] = client_keys
            if info.password:
                connect_kwargs["password"] = info.password

            try:
                conn = await asyncio.wait_for(asyncssh.connect(**connect_kwargs), timeout=10.0)
            except asyncssh.HostKeyNotVerifiable:
                logger.error(f"SSH host key MISMATCH for {info.server_id} ({info.host})")
                raise ValueError(
                    f"SSH host key for {info.host} does not match the pinned key "
                    f"({host_key_fingerprint(info.host_key)}). This may be a man-in-the-middle attack. "
                    "If the server was reinstalled, reset its host key."
                ) from None
            except Exception as e:
                logger.error(f"Failed to connect to SSH node {info.server_id} ({info.host}): {e}")
                raise

            if not info.host_key:
                server_key = conn.get_server_host_key()
                if server_key is not None:
                    info.host_key = server_key.export_public_key("openssh").decode().strip()
                    await _pin_host_key(info.server_id, info.host_key)
            self._connections[info.server_id] = conn
            return conn

    @staticmethod
    def elevated(info: ServerConnectionInfo, command: str) -> str:
        """Wraps a command to run as root when the node is configured for sudo.
        Feed `sudo_stdin(info)` to the process before anything else."""
        if info.use_sudo and info.sudo_password:
            return askpass_sudo(command)
        if info.use_sudo:
            # -n fails fast instead of prompting for a password
            return f"sudo -n -- sh -c {shlex.quote(command)}"
        return command

    @staticmethod
    def sudo_stdin(info: ServerConnectionInfo) -> str:
        """Stdin prefix the elevated() wrapper consumes (the sudo password line), or ''."""
        return f"{info.sudo_password}\n" if info.use_sudo and info.sudo_password else ""

    async def run_command(
        self, info: ServerConnectionInfo, command: str, timeout: float = 15.0, stdin: Optional[str] = None,
        elevate: bool = True,
    ) -> Tuple[int, str, str]:
        """
        Executes a remote command over SSH and returns (exit_status, stdout, stderr).
        """
        if elevate:
            prefix = self.sudo_stdin(info)
            command = self.elevated(info, command)
            if prefix:
                stdin = prefix + (stdin or "")
        try:
            conn = await self.get_connection(info)
            result = await asyncio.wait_for(conn.run(command, check=False, input=stdin), timeout=timeout)
            return (result.exit_status, result.stdout, result.stderr)
        except asyncio.TimeoutError:
            logger.error(f"Command timed out ({timeout}s) on {info.server_id}: {command[:50]}")
            return (-1, "", f"Command timed out after {timeout} seconds")
        except Exception as e:
            logger.error(f"SSH command execution failed on {info.server_id}: {e}")
            return (-1, "", str(e))

    async def test_connection(self, info: ServerConnectionInfo, timeout: float = 5.0) -> Tuple[bool, str, Optional[float], Optional[str]]:
        """
        Tests SSH reachability and returns (success, message, latency_ms, os_info).
        """
        start_time = time.perf_counter()
        try:
            conn = await asyncio.wait_for(self.get_connection(info), timeout=timeout)
            res = await asyncio.wait_for(
                conn.run("cat /etc/os-release 2>/dev/null || uname -srm", check=False),
                timeout=timeout
            )
            if info.use_sudo:
                sudo_res = await asyncio.wait_for(
                    conn.run(self.elevated(info, "true"), check=False, input=self.sudo_stdin(info) or None),
                    timeout=timeout,
                )
                if sudo_res.exit_status != 0:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    problem = ("the sudo password was rejected" if info.sudo_password
                               else "passwordless sudo is not configured (set a sudo password)")
                    return (False, f"SSH OK but {problem} for {info.username}: "
                            f"{(sudo_res.stderr or '').strip()}", round(elapsed_ms, 2), None)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            os_name = "Linux"
            for line in res.stdout.splitlines():
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip('"\'')
                    break
                elif line.startswith("NAME="):
                    os_name = line.split("=", 1)[1].strip('"\'')

            return (True, "Connection successful", round(elapsed_ms, 2), os_name)
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return (False, f"Connection failed: {str(e)}", round(elapsed_ms, 2), None)

    async def close_connection(self, server_id: str):
        async with self._lock:
            conn = self._connections.pop(server_id, None)
            if conn and not conn.is_closed():
                conn.close()

    async def close_all(self):
        async with self._lock:
            for sid, conn in list(self._connections.items()):
                if not conn.is_closed():
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._connections.clear()

# Global Singleton
ssh_manager = SSHConnectionManager()
