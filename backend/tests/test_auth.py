import time
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, select, update
from app.main import app
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.core.security import hash_password, login_limiter
from app.models.audit import AuditLogModel
from app.models.user import AppSessionModel, AppUserModel

PASSWORD = "correct-horse-battery-1"

def client(**kw):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)

@pytest_asyncio.fixture
async def test_account():
    await init_db()
    username = f"tester-{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as session:
        session.add(AppUserModel(username=username, password_hash=hash_password(PASSWORD)))
        await session.commit()
    login_limiter._failures.clear()
    yield username
    login_limiter._failures.clear()
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(AppUserModel).where(AppUserModel.username == username))).scalar_one()
        await session.execute(delete(AppSessionModel).where(AppSessionModel.user_id == user.id))
        await session.delete(user)
        await session.commit()

async def _login(c, username, password=PASSWORD, **kw):
    return await c.post("/api/v1/auth/login", json={"username": username, "password": password}, **kw)

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_protected_routes_require_login():
    async with client() as c:
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/api/v1/servers")).status_code == 401
        assert (await c.get("/api/v1/audit")).status_code == 401
        assert (await c.get("/api/v1/auth/me")).status_code == 401

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_login_cookie_flags_and_opaque_token(test_account):
    async with client() as c:
        assert (await _login(c, test_account, "wrong")).status_code == 401
        ok = await _login(c, test_account)
        assert ok.status_code == 200 and ok.json()["username"] == test_account
        cookie = ok.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        token = c.cookies.get(settings.SESSION_COOKIE_NAME)
        # Only the hash is stored server-side
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(select(AppSessionModel.token_hash))).scalars().all()
        assert token not in rows
        assert (await c.get("/api/v1/servers")).status_code == 200

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_logout_revokes_token_server_side(test_account):
    async with client() as c:
        await _login(c, test_account)
        token = c.cookies.get(settings.SESSION_COOKIE_NAME)
        await c.post("/api/v1/auth/logout")
    # Replaying the stolen cookie after logout must fail
    async with client(cookies={settings.SESSION_COOKIE_NAME: token}) as replay:
        assert (await replay.get("/api/v1/auth/me")).status_code == 401

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_idle_timeout(test_account):
    async with client() as c:
        await _login(c, test_account)
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        async with AsyncSessionLocal() as s:
            await s.execute(update(AppSessionModel).values(
                last_seen_at=time.time() - settings.SESSION_IDLE_MINUTES * 60 - 1))
            await s.commit()
        assert (await c.get("/api/v1/auth/me")).status_code == 401

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_password_change_revokes_other_sessions(test_account):
    async with client() as laptop, client() as phone:
        await _login(laptop, test_account)
        await _login(phone, test_account)
        r = await laptop.post("/api/v1/auth/change-password",
                              json={"current_password": PASSWORD, "new_password": "brand-new-passphrase-2"})
        assert r.status_code == 204
        assert (await laptop.get("/api/v1/auth/me")).status_code == 200
        assert (await phone.get("/api/v1/auth/me")).status_code == 401

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_ip_rate_limit_behind_trusted_proxy(test_account, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    async with client() as c:
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            assert (await _login(c, test_account, "nope", headers=headers)).status_code == 401
        assert (await _login(c, test_account, headers=headers)).status_code == 429
        # A different visitor IP is not affected
        assert (await _login(c, test_account, headers={"CF-Connecting-IP": "198.51.100.7"})).status_code == 200

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_proxy_header_ignored_when_untrusted(test_account):
    async with client() as c:
        for i in range(settings.LOGIN_MAX_ATTEMPTS):
            # Rotating spoofed IPs must not bypass the per-IP limit
            await _login(c, test_account, "nope", headers={"CF-Connecting-IP": f"10.0.0.{i}"})
        assert (await _login(c, test_account, headers={"CF-Connecting-IP": "10.9.9.9"})).status_code == 429

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_proxy_header_only_honored_from_trusted_proxy(test_account, monkeypatch):
    # Another container on the proxy's network must not pick its own client IP (rate limit, audit)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["10.88.0.5"], raising=False)
    async with client() as c:  # peer 127.0.0.1: not the proxy
        for i in range(settings.LOGIN_MAX_ATTEMPTS):
            await _login(c, test_account, "nope", headers={"CF-Connecting-IP": f"10.0.0.{i}"})
        assert (await _login(c, test_account, headers={"CF-Connecting-IP": "10.9.9.9"})).status_code == 429

@pytest.mark.parametrize("trusted", [["127.0.0.1"], ["127.0.0.0/8"], ["localhost"]])
def test_client_ip_from_trusted_proxy_by_ip_cidr_or_hostname(monkeypatch, trusted):
    from starlette.requests import Request
    from app.core.security import client_ip
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", trusted, raising=False)
    req = Request({"type": "http", "client": ("127.0.0.1", 5000),
                   "headers": [(b"cf-connecting-ip", b"203.0.113.7")]})
    assert client_ip(req) == "203.0.113.7"

def test_client_ip_uses_the_forwarded_for_entry_added_by_the_proxy(monkeypatch):
    # The client controls everything left of what the proxy appended
    from starlette.requests import Request
    from app.core.security import client_ip
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    req = Request({"type": "http", "client": ("127.0.0.1", 5000),
                   "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.7")]})
    assert client_ip(req) == "203.0.113.7"

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_account_lockout_across_ips(test_account, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    async with client() as c:
        for i in range(settings.LOGIN_ACCOUNT_MAX_ATTEMPTS):
            await _login(c, test_account, "nope", headers={"CF-Connecting-IP": f"192.0.2.{i}"})
        r = await _login(c, test_account, headers={"CF-Connecting-IP": "192.0.2.250"})
        assert r.status_code == 429

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_account_lockout_cannot_lock_owner_out_of_known_ip(test_account, monkeypatch):
    # Anyone who knows the username can trip the per-account limit; the owner, from an address they
    # already signed in from, must still get in (that address keeps its own per-IP limit)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    home = {"CF-Connecting-IP": "198.51.100.20"}
    async with client() as c:
        assert (await _login(c, test_account, headers=home)).status_code == 200
        for i in range(settings.LOGIN_ACCOUNT_MAX_ATTEMPTS):
            await _login(c, test_account, "nope", headers={"CF-Connecting-IP": f"192.0.2.{i}"})
        assert (await _login(c, test_account, headers={"CF-Connecting-IP": "192.0.2.250"})).status_code == 429
        assert (await _login(c, test_account, headers=home)).status_code == 200

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_known_ip_still_has_per_ip_limit(test_account, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    home = {"CF-Connecting-IP": "198.51.100.21"}
    async with client() as c:
        assert (await _login(c, test_account, headers=home)).status_code == 200
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            await _login(c, test_account, "nope", headers=home)
        assert (await _login(c, test_account, headers=home)).status_code == 429

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_audit_trail(test_account):
    async with client() as c:
        await _login(c, test_account, "nope")
        await _login(c, test_account)
        await c.post("/api/v1/services/local/tukang-test-nonexistent.service/action", json={"action": "start"},
                     headers={"Origin": "http://test"})  # nonexistent unit: no side effects, we only check it is audited
        entries = (await c.get("/api/v1/audit", params={"username": test_account})).json()
    actions = [e["action"] for e in entries]
    assert "login.failure" in actions and "login.success" in actions
    svc = next(e for e in entries if e["action"] == "POST /api/v1/services/{server_id}/{unit}/action")
    assert svc["server_id"] == "local" and "unit=tukang-test-nonexistent.service" in svc["target"]

@pytest.mark.parametrize("raw", ["cloudflared, 10.88.0.0/16", '["cloudflared", "10.88.0.0/16"]'])
def test_trusted_proxies_env_accepts_comma_list_or_json(monkeypatch, raw):
    # systemd's Environment= strips double quotes, so a plain comma list must work in a Quadlet
    from app.core.config import Settings
    monkeypatch.setenv("TRUSTED_PROXIES", raw)
    assert Settings().TRUSTED_PROXIES == ["cloudflared", "10.88.0.0/16"]
