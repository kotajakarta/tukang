import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import init_db
from app.services.ssh_manager import ssh_manager, ServerConnectionInfo

def _info(**kw):
    return ServerConnectionInfo(server_id="s", host="h", **kw)

def test_elevation_modes():
    plain = _info()
    assert ssh_manager.elevated(plain, "id") == "id" and ssh_manager.sudo_stdin(plain) == ""

    nopasswd = _info(use_sudo=True)
    assert ssh_manager.elevated(nopasswd, "id").startswith("sudo -n -- sh -c")
    assert ssh_manager.sudo_stdin(nopasswd) == ""

    pw = _info(use_sudo=True, sudo_password="p@ss 'word")
    cmd = ssh_manager.elevated(pw, "id")
    assert "sudo -k -A" in cmd and "p@ss" not in cmd  # never on the command line
    assert ssh_manager.sudo_stdin(pw) == "p@ss 'word\n"

    # A stored password is ignored while sudo is off
    assert ssh_manager.elevated(_info(sudo_password="x"), "id") == "id"

@pytest.mark.asyncio
async def test_run_command_prefixes_password_to_stdin(monkeypatch):
    sent = {}

    class Conn:
        async def run(self, command, check=False, input=None):
            sent.update(command=command, input=input)
            class R: exit_status, stdout, stderr = 0, "", ""
            return R()

    async def get_conn(info):
        return Conn()

    monkeypatch.setattr(ssh_manager, "get_connection", get_conn)
    await ssh_manager.run_command(_info(use_sudo=True, sudo_password="pw"), "cat", stdin='{"a": 1}')
    assert sent["input"] == 'pw\n{"a": 1}'
    await ssh_manager.run_command(_info(use_sudo=True, sudo_password="pw"), "true")
    assert sent["input"] == "pw\n"

@pytest.mark.asyncio
async def test_sudo_password_api_write_only():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"id": "srv-sudo-1", "name": "Sudo node", "host": "10.0.0.9", "username": "ops",
                   "use_sudo": True, "sudo_password": "hunter2"}
        created = (await client.post("/api/v1/servers", json=payload)).json()
        try:
            assert created["use_sudo"] is True and created["has_sudo_password"] is True
            assert "hunter2" not in str(created)

            # Blank keeps it
            kept = (await client.put("/api/v1/servers/srv-sudo-1", json={"sudo_password": ""})).json()
            assert kept["has_sudo_password"] is True

            # Line breaks would split the stdin protocol
            bad = await client.put("/api/v1/servers/srv-sudo-1", json={"sudo_password": "a\nb"})
            assert bad.status_code == 422

            # Turning sudo off forgets it
            off = (await client.put("/api/v1/servers/srv-sudo-1", json={"use_sudo": False})).json()
            assert off["has_sudo_password"] is False
        finally:
            await client.delete("/api/v1/servers/srv-sudo-1")
