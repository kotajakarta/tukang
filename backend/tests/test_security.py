import asyncio
import uuid
import asyncssh
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete
from app.main import app
from app.core.database import init_db, AsyncSessionLocal
from app.core import validation
from app.models.server import ServerModel
from app.services.ssh_manager import ssh_manager, ServerConnectionInfo

def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

# ---------------------------------------------------------------- command injection

@pytest.mark.parametrize("bad", ["x; id", "x$(id)", "`id`", "a b", "-h", "x|cat", "x\nid", ""])
def test_unit_name_rejects_shell_metachars(bad):
    with pytest.raises(Exception):
        validation.unit_name(bad)

@pytest.mark.parametrize("good", ["sshd.service", "getty@tty1.service", "dev-sda1.device", "sys-devices-x\\x2d1.mount"])
def test_unit_name_accepts_real_units(good):
    assert validation.unit_name(good) == good

@pytest.mark.parametrize("bad", [
    "/etc/shadow",
    "/etc/containers/systemd/../../shadow.container",
    "/etc/containers/systemd/x.container; rm -rf /",
    "relative/x.container",
    "/etc/containers/systemd/x.conf",
])
def test_quadlet_path_confined(bad):
    with pytest.raises(Exception):
        validation.quadlet_path(bad)

def test_quadlet_path_allows_known_dirs():
    for p in ["/etc/containers/systemd/web.container", "/home/u/.config/containers/systemd/sub/db.volume",
              "/run/user/1000/containers/systemd/a.network", "/root/.config/containers/systemd/a.pod"]:
        assert validation.quadlet_path(p) == p

@pytest.mark.parametrize("bad", ["../x.container", "a/b.container", "x.sh", "$(id).container"])
def test_quadlet_filename(bad):
    with pytest.raises(Exception):
        validation.quadlet_filename(bad)

def test_ssh_key_validation():
    validation.ssh_public_key("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl user@host")
    for bad in ['command="id" ssh-ed25519 AAAA', "ssh-ed25519 AAAA\nssh-rsa BBBB", "not a key"]:
        with pytest.raises(Exception):
            validation.ssh_public_key(bad)

@pytest.mark.asyncio
async def test_injection_rejected_at_api():
    await init_db()
    async with client() as c:
        r = await c.get("/api/v1/services/local/x;echo%20PWNED/logs")
        assert r.status_code == 400
        r = await c.get("/api/v1/containers/local/quadlets/content", params={"path": "/etc/hostname; echo PWNED"})
        assert r.status_code == 400
        r = await c.get("/api/v1/services/local/units", params={"unit_type": "service; id"})
        assert r.status_code == 400
        r = await c.post("/api/v1/users/local", json={"username": "x; id", "shell": "/bin/bash"})
        assert r.status_code == 400
        r = await c.get("/api/v1/storage/local/smart/sda;id")
        assert r.status_code == 400

@pytest.mark.asyncio
async def test_cannot_delete_system_users():
    async with client() as c:
        r = await c.delete("/api/v1/users/local/root")
        assert r.status_code == 400
        assert "Refusing" in r.json()["detail"]

# ---------------------------------------------------------------- secrets never returned

@pytest.mark.asyncio
async def test_private_key_and_password_are_write_only():
    await init_db()
    sid = f"srv-{uuid.uuid4().hex[:6]}"
    async with client() as c:
        r = await c.post("/api/v1/servers", json={
            "id": sid, "name": "n", "host": "10.0.0.9", "private_key": "PRIVATE-KEY-MATERIAL", "password": "PW-MATERIAL"})
        assert r.status_code == 201
        for resp in (r, await c.get(f"/api/v1/servers/{sid}"), await c.get("/api/v1/servers")):
            assert "PRIVATE-KEY-MATERIAL" not in resp.text and "PW-MATERIAL" not in resp.text
        body = (await c.get(f"/api/v1/servers/{sid}")).json()
        assert body["has_private_key"] is True and body["has_password"] is True

        # Blank secrets on update keep the stored values
        await c.put(f"/api/v1/servers/{sid}", json={"name": "renamed", "password": "", "private_key": ""})
        async with AsyncSessionLocal() as s:
            srv = (await s.execute(select(ServerModel).where(ServerModel.id == sid))).scalar_one()
            assert srv.password == "PW-MATERIAL" and srv.private_key == "PRIVATE-KEY-MATERIAL"
        await c.delete(f"/api/v1/servers/{sid}")

# ---------------------------------------------------------------- CORS / CSRF / CSWSH / headers

@pytest.mark.asyncio
async def test_no_cors_for_foreign_origin():
    async with client() as c:
        r = await c.get("/api/v1/servers", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers

@pytest.mark.asyncio
async def test_cross_origin_write_blocked_same_origin_allowed():
    async with client() as c:
        r = await c.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        r = await c.post("/api/v1/auth/logout", headers={"Origin": "http://test"})
        assert r.status_code == 204

def test_websocket_foreign_origin_rejected():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect("/ws/metrics", headers={"Origin": "https://evil.example"}) as ws:
                ws.receive_text()
        assert exc.value.code == 4403

@pytest.mark.asyncio
async def test_security_headers():
    async with client() as c:
        r = await c.get("/api/health")
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"

# ---------------------------------------------------------------- SSH host key pinning (TOFU)

async def _start_sshd(host_key):
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True
        def password_auth_supported(self):
            return True
        def validate_password(self, username, password):
            return password == "pw"
    return await asyncssh.create_server(
        Server, "127.0.0.1", 0, server_host_keys=[host_key],
        process_factory=lambda p: (p.stdout.write("ok\n"), p.exit(0)),
    )

@pytest.mark.asyncio
async def test_host_key_pinned_then_mismatch_detected():
    await init_db()
    key_a = asyncssh.generate_private_key("ssh-ed25519")
    key_b = asyncssh.generate_private_key("ssh-ed25519")
    sid = f"tofu-{uuid.uuid4().hex[:6]}"

    server = await _start_sshd(key_a)
    port = server.sockets[0].getsockname()[1]
    async with AsyncSessionLocal() as s:
        s.add(ServerModel(id=sid, name="t", host="127.0.0.1", port=port, username="u", auth_type="password", password="pw"))
        await s.commit()

    async def info():
        async with AsyncSessionLocal() as s:
            return ServerConnectionInfo.from_server(
                (await s.execute(select(ServerModel).where(ServerModel.id == sid))).scalar_one())

    try:
        code, out, _ = await ssh_manager.run_command(await info(), "x")
        assert (code, out.strip()) == (0, "ok")
        pinned = (await info()).host_key
        assert pinned and pinned.split()[1] == key_a.export_public_key("openssh").decode().split()[1]

        # Same port, different host key -> must refuse
        await ssh_manager.close_connection(sid)
        server.close(); await server.wait_closed()
        server = await asyncssh.create_server(
            asyncssh.SSHServer, "127.0.0.1", port, server_host_keys=[key_b])
        code, _, err = await ssh_manager.run_command(await info(), "x")
        assert code == -1 and "does not match the pinned key" in err
    finally:
        await ssh_manager.close_connection(sid)
        server.close()
        async with AsyncSessionLocal() as s:
            await s.execute(delete(ServerModel).where(ServerModel.id == sid))
            await s.commit()

# ---------------------------------------------------------------- encryption at rest

@pytest.mark.asyncio
async def test_credentials_encrypted_at_rest():
    import sqlite3
    from app.core.config import settings
    await init_db()
    sid = f"enc-{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as s:
        s.add(ServerModel(id=sid, name="e", host="h", password="PLAINTEXT-PW", private_key="PLAINTEXT-KEY"))
        await s.commit()
    raw = sqlite3.connect(settings.DATABASE_URL.split("///", 1)[1]).execute(
        "SELECT password, private_key FROM servers WHERE id = ?", (sid,)).fetchone()
    assert all(v.startswith("enc:v1:") and "PLAINTEXT" not in v for v in raw)
    async with AsyncSessionLocal() as s:
        srv = (await s.execute(select(ServerModel).where(ServerModel.id == sid))).scalar_one()
        assert (srv.password, srv.private_key) == ("PLAINTEXT-PW", "PLAINTEXT-KEY")
        await s.delete(srv)
        await s.commit()

@pytest.mark.asyncio
async def test_legacy_plaintext_migrated_on_startup():
    import sqlite3
    from app.core.config import settings
    await init_db()
    sid = f"leg-{uuid.uuid4().hex[:6]}"
    db = sqlite3.connect(settings.DATABASE_URL.split("///", 1)[1])
    db.execute("INSERT INTO servers (id, name, host, port, username, is_local, auth_type, password, status) "
               "VALUES (?, 'l', 'h', 22, 'root', 0, 'password', 'OLD-PLAIN', 'unknown')", (sid,))
    db.commit()
    await init_db()
    assert db.execute("SELECT password FROM servers WHERE id = ?", (sid,)).fetchone()[0].startswith("enc:v1:")
    db.execute("DELETE FROM servers WHERE id = ?", (sid,)); db.commit()
