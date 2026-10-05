import json
import logging
import os
from typing import List, Dict, Any, Tuple, Optional
import shlex
from app.core import validation
from app.services.executor import run_on_server

logger = logging.getLogger("user_service")

class UserService:
    async def _run_command(self, server_id: str, cmd: str, stdin: Optional[str] = None) -> Tuple[int, str, str]:
        return await run_on_server(server_id, cmd, timeout=15.0, stdin=stdin)

    async def list_users(self, server_id: str) -> List[Dict[str, Any]]:
        script = r"""python3 -c "
import pwd, grp, json
users = []
try:
    sudo_members = set(grp.getgrnam('wheel').gr_mem)
except KeyError:
    try:
        sudo_members = set(grp.getgrnam('sudo').gr_mem)
    except KeyError:
        sudo_members = set()

for u in pwd.getpwall():
    # Show login users or system users with valid shells
    is_sudo = (u.pw_name in sudo_members) or (u.pw_uid == 0)
    users.append({
        'username': u.pw_name,
        'uid': u.pw_uid,
        'gid': u.pw_gid,
        'gecos': u.pw_gecos,
        'home': u.pw_dir,
        'shell': u.pw_shell,
        'is_sudo': is_sudo,
        'is_system': u.pw_uid < 1000 and u.pw_uid != 0
    })
print(json.dumps(users))
" 2>/dev/null
"""
        exit_code, stdout, _ = await self._run_command(server_id, script)
        if exit_code == 0 and stdout.strip():
            try:
                return json.loads(stdout.strip())
            except Exception:
                pass
        return []

    async def create_user(self, server_id: str, username: str, shell: str = "/bin/bash", is_sudo: bool = False) -> Tuple[bool, str]:
        q_user = shlex.quote(validation.username(username))
        q_shell = shlex.quote(validation.login_shell(shell))
        sudo_group = "wheel"  # RHEL/Rocky default
        cmd = f"useradd -m -s {q_shell} -- {q_user}"
        if is_sudo:
            cmd += f" && usermod -aG {sudo_group} -- {q_user}"

        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        if exit_code == 0:
            return True, f"User '{username}' created successfully."
        return False, stderr.strip() or "Failed to create user."

    async def delete_user(self, server_id: str, username: str, remove_home: bool = True) -> Tuple[bool, str]:
        q_user = shlex.quote(validation.username(username))
        # Refuse to delete root/system accounts (uid < 1000) — that would brick the node
        exit_code, stdout, _ = await self._run_command(server_id, f"id -u -- {q_user}")
        if exit_code != 0:
            return False, f"User '{username}' does not exist."
        if int(stdout.strip() or 0) < 1000:
            return False, "Refusing to delete root or system accounts (uid < 1000)."

        cmd = f"userdel {'-r ' if remove_home else ''}-- {q_user}"
        exit_code, stdout, stderr = await self._run_command(server_id, cmd)
        if exit_code == 0:
            return True, f"User '{username}' deleted successfully."
        return False, stderr.strip() or "Failed to delete user."

    async def get_authorized_keys(self, server_id: str, username: str) -> List[str]:
        reader = (
            "import os, pwd, sys\n"
            "u = pwd.getpwnam(sys.argv[1])\n"
            "keyfile = os.path.join(u.pw_dir, '.ssh', 'authorized_keys')\n"
            "if os.path.isfile(keyfile):\n"
            "    print(open(keyfile).read())\n"
        )
        q_user = shlex.quote(validation.username(username))
        exit_code, stdout, _ = await self._run_command(
            server_id, f"python3 -c {shlex.quote(reader)} {q_user} 2>/dev/null"
        )
        if exit_code == 0:
            return [line.strip() for line in stdout.splitlines() if line.strip() and not line.strip().startswith("#")]
        return []

    async def add_authorized_key(self, server_id: str, username: str, pubkey: str) -> Tuple[bool, str]:
        pubkey = validation.ssh_public_key(pubkey)
        writer = (
            "import os, pwd, sys\n"
            "u = pwd.getpwnam(sys.argv[1])\n"
            "key = sys.stdin.read().strip()\n"
            "ssh_dir = os.path.join(u.pw_dir, '.ssh')\n"
            "os.makedirs(ssh_dir, mode=0o700, exist_ok=True)\n"
            "keyfile = os.path.join(ssh_dir, 'authorized_keys')\n"
            "with open(keyfile, 'a') as f:\n"
            "    f.write(key + '\\n')\n"
            "os.chmod(keyfile, 0o600)\n"
            "os.chown(ssh_dir, u.pw_uid, u.pw_gid)\n"
            "os.chown(keyfile, u.pw_uid, u.pw_gid)\n"
            "print('OK')\n"
        )
        q_user = shlex.quote(validation.username(username))
        exit_code, stdout, stderr = await self._run_command(
            server_id, f"python3 -c {shlex.quote(writer)} {q_user}", stdin=pubkey
        )
        if exit_code == 0 and "OK" in stdout:
            return True, "SSH Key added successfully"
        return False, stderr.strip() or "Failed to add SSH key"

user_service = UserService()
