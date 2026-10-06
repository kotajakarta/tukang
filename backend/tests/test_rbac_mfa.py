import json
from contextlib import asynccontextmanager
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, select
from app.main import app
from app.core import totp
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.core.security import hash_password, login_limiter
from app.models.user import AppSessionModel, AppUserModel

PASSWORD = "a-long-enough-passphrase-9"

def client(**kw):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)

@pytest_asyncio.fixture
async def make_user():
    await init_db()
    created = []

    async def _make(role: str, mfa_secret: str = None):
        name = f"{role}-{uuid.uuid4().hex[:6]}"
        async with AsyncSessionLocal() as s:
            u = AppUserModel(username=name, password_hash=hash_password(PASSWORD), role=role,
                             mfa_secret=mfa_secret, mfa_enabled=bool(mfa_secret))
            s.add(u)
            await s.commit()
            created.append(u.id)
        return name

    login_limiter._failures.clear()
    yield _make
    login_limiter._failures.clear()
    async with AsyncSessionLocal() as s:
        await s.execute(delete(AppSessionModel).where(AppSessionModel.user_id.in_(created)))
        await s.execute(delete(AppUserModel).where(AppUserModel.id.in_(created)))
        await s.commit()

@asynccontextmanager
async def logged_in(username, otp=None):
    async with client() as c:
        r = await c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD, "otp": otp})
        assert r.status_code == 200, r.text
        yield c

# ---------------------------------------------------------------- RBAC

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_viewer_can_read_but_not_act(make_user):
    async with logged_in(await make_user("viewer")) as c:
        assert (await c.get("/api/v1/servers")).status_code == 200
        assert (await c.get("/api/v1/network/local")).status_code == 200
        # Logs may hold secrets -> operator
        assert (await c.get("/api/v1/services/local/sshd.service/logs")).status_code == 403
        assert (await c.post("/api/v1/services/local/x.service/action", json={"action": "start"})).status_code == 403
        assert (await c.post("/api/v1/servers", json={"name": "n", "host": "h"})).status_code == 403
        assert (await c.get("/api/v1/audit")).status_code == 403
        assert (await c.get("/api/v1/app-users")).status_code == 403

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_operator_can_operate_but_not_administer(make_user):
    async with logged_in(await make_user("operator")) as c:
        r = await c.post("/api/v1/services/local/tukang-test-nonexistent.service/action", json={"action": "start"})
        assert r.status_code == 200  # authorized (the unit itself doesn't exist)
        assert (await c.get("/api/v1/services/local/tukang-test-nonexistent.service/logs")).status_code == 200
        assert (await c.post("/api/v1/users/local", json={"username": "x"})).status_code == 403
        assert (await c.post("/api/v1/containers/local/quadlets", json={"filename": "a.container", "content": ""})).status_code == 403
        assert (await c.delete("/api/v1/servers/local")).status_code == 403
        assert (await c.get("/api/v1/audit")).status_code == 403

@pytest.mark.real_auth
def test_terminal_websocket_requires_admin():
    import asyncio
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    async def setup():
        await init_db()
        name = f"op-{uuid.uuid4().hex[:6]}"
        async with AsyncSessionLocal() as s:
            s.add(AppUserModel(username=name, password_hash=hash_password(PASSWORD), role="operator"))
            await s.commit()
        return name
    name = asyncio.run(setup())
    try:
        with TestClient(app) as tc:
            assert tc.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
            with pytest.raises(WebSocketDisconnect) as exc:
                with tc.websocket_connect("/ws/terminal/local") as ws:
                    ws.receive_text()
            assert exc.value.code == 4403
    finally:
        async def cleanup():
            async with AsyncSessionLocal() as s:
                await s.execute(delete(AppUserModel).where(AppUserModel.username == name))
                await s.commit()
        asyncio.run(cleanup())

def test_policy_defaults_are_deny_leaning():
    from app.core import policy
    assert policy.required_role("POST", "/some/new/endpoint") == "admin"
    assert policy.required_role("DELETE", "/servers/{server_id}") == "admin"
    assert policy.required_role("GET", "/servers") == "viewer"

# ---------------------------------------------------------------- account management guards

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_admin_cannot_lock_themselves_out(make_user):
    admin = await make_user("admin")
    async with logged_in(admin) as c:
        me = (await c.get("/api/v1/auth/me")).json()
        assert (await c.put(f"/api/v1/app-users/{me['id']}", json={"role": "viewer"})).status_code == 400
        assert (await c.put(f"/api/v1/app-users/{me['id']}", json={"disabled": True})).status_code == 400
        assert (await c.delete(f"/api/v1/app-users/{me['id']}")).status_code == 400

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_password_policy_and_disable_revokes_sessions(make_user):
    admin = await make_user("admin")
    victim = await make_user("viewer")
    async with logged_in(admin) as a, logged_in(victim) as v:
        r = await a.post("/api/v1/app-users", json={"username": f"weak-{uuid.uuid4().hex[:4]}", "password": "short"})
        assert r.status_code == 400 and "Password policy" in r.json()["detail"]
        victim_id = next(u["id"] for u in (await a.get("/api/v1/app-users")).json() if u["username"] == victim)
        assert (await v.get("/api/v1/servers")).status_code == 200
        assert (await a.put(f"/api/v1/app-users/{victim_id}", json={"disabled": True})).status_code == 200
        assert (await v.get("/api/v1/servers")).status_code == 401
        async with client() as fresh:
            r = await fresh.post("/api/v1/auth/login", json={"username": victim, "password": PASSWORD})
        assert r.status_code == 401

# ---------------------------------------------------------------- MFA

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_mfa_enrollment_and_login(make_user):
    name = await make_user("admin")
    async with logged_in(name) as c:
        setup = (await c.post("/api/v1/auth/mfa/setup")).json()
        assert setup["otpauth_uri"].startswith("otpauth://totp/")
        assert (await c.post("/api/v1/auth/mfa/enable", json={"code": "000000"})).status_code == 400
        code = totp._code_at(setup["secret"], totp.current_step())
        r = await c.post("/api/v1/auth/mfa/enable", json={"code": code})
        assert r.status_code == 200
        recovery = r.json()["recovery_codes"]
        assert len(recovery) == 10

    async with client() as c:
        r = await c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        assert r.status_code == 401 and r.json()["detail"] == "mfa_required"
        assert c.cookies.get(settings.SESSION_COOKIE_NAME) is None
        # The code used to enable MFA cannot be replayed
        r = await c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD, "otp": code})
        assert r.status_code == 401
        # A recovery code works exactly once
        r = await c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD, "otp": recovery[0]})
        assert r.status_code == 200
    async with client() as c:
        r = await c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD, "otp": recovery[0]})
        assert r.status_code == 401

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_mfa_required_blocks_until_enrolled(make_user, monkeypatch):
    monkeypatch.setattr(settings, "MFA_REQUIRED", True)
    async with logged_in(await make_user("admin")) as c:
        me = (await c.get("/api/v1/auth/me")).json()
        assert me["mfa_setup_required"] is True
        r = await c.get("/api/v1/servers")
        assert r.status_code == 403 and r.json()["detail"] == "mfa_setup_required"
        secret = (await c.post("/api/v1/auth/mfa/setup")).json()["secret"]
        await c.post("/api/v1/auth/mfa/enable", json={"code": totp._code_at(secret, totp.current_step())})
        assert (await c.get("/api/v1/servers")).status_code == 200

@pytest.mark.asyncio
async def test_mfa_secret_encrypted_at_rest(make_user):
    import sqlite3
    secret = totp.generate_secret()
    name = await make_user("viewer", mfa_secret=secret)
    raw = sqlite3.connect(settings.DATABASE_URL.split("///", 1)[1]).execute(
        "SELECT mfa_secret FROM app_users WHERE username = ?", (name,)).fetchone()[0]
    assert raw.startswith("enc:v1:") and secret not in raw

# ---------------------------------------------------------------- re-authentication brute force

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_change_password_current_password_is_rate_limited(make_user):
    # A stolen session must not become an unlimited password oracle
    async with logged_in(await make_user("viewer")) as c:
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            r = await c.post("/api/v1/auth/change-password",
                             json={"current_password": "wrong-guess", "new_password": "another-long-passphrase-3"})
            assert r.status_code == 400
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": PASSWORD, "new_password": "another-long-passphrase-3"})
        assert r.status_code == 429

@pytest.mark.real_auth
@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,body", [
    ("/api/v1/auth/mfa/recovery-codes", {"code": "000000"}),
    ("/api/v1/auth/mfa/disable", {"password": PASSWORD, "code": "000000"}),
])
async def test_mfa_code_checks_are_rate_limited(make_user, endpoint, body):
    # Guessing the TOTP here would mint fresh recovery codes (lasting access) or switch MFA off
    secret = totp.generate_secret()
    name = await make_user("viewer", mfa_secret=secret)
    async with logged_in(name, otp=totp._code_at(secret, totp.current_step())) as c:
        statuses = [(await c.post(endpoint, json=body)).status_code for _ in range(settings.LOGIN_MAX_ATTEMPTS + 1)]
    assert statuses[-1] == 429

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_mfa_enable_code_check_is_rate_limited(make_user):
    async with logged_in(await make_user("viewer")) as c:
        assert (await c.post("/api/v1/auth/mfa/setup")).status_code == 200
        statuses = [(await c.post("/api/v1/auth/mfa/enable", json={"code": "000000"})).status_code
                    for _ in range(settings.LOGIN_MAX_ATTEMPTS + 1)]
    assert statuses[-1] == 429

@pytest.mark.real_auth
def test_metrics_websocket_closed_when_session_ends(monkeypatch):
    # Like the terminal: a stream opened by a session must not outlive it (logout, disable, expiry)
    import asyncio
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.websockets import metrics_ws
    monkeypatch.setattr(metrics_ws, "SESSION_RECHECK_SECONDS", 0.2, raising=False)

    async def setup():
        await init_db()
        name = f"viewer-{uuid.uuid4().hex[:6]}"
        async with AsyncSessionLocal() as s:
            s.add(AppUserModel(username=name, password_hash=hash_password(PASSWORD), role="viewer"))
            await s.commit()
        return name
    name = asyncio.run(setup())
    try:
        with TestClient(app) as tc:
            assert tc.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
            with pytest.raises(WebSocketDisconnect) as exc:
                with tc.websocket_connect("/ws/metrics") as ws:
                    ws.receive_json()  # streaming while the session is valid
                    assert tc.post("/api/v1/auth/logout").status_code == 204
                    for _ in range(10):  # metrics arrive every second; the socket must close well before
                        ws.receive_json()
            assert exc.value.code == 4401
    finally:
        async def cleanup():
            async with AsyncSessionLocal() as s:
                user = (await s.execute(select(AppUserModel).where(AppUserModel.username == name))).scalar_one()
                await s.execute(delete(AppSessionModel).where(AppSessionModel.user_id == user.id))
                await s.delete(user)
                await s.commit()
        asyncio.run(cleanup())
