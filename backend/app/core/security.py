import hashlib
import ipaddress
import secrets
import socket
import time
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
import bcrypt
from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy import delete, select
from app.core import policy
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import AppSessionModel, AppUserModel, CurrentUser

logger = logging.getLogger("security")

# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; truncate explicitly so bcrypt>=4.1 doesn't raise
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except ValueError:
        return False

# Constant-time dummy check for unknown usernames (avoids user enumeration via timing)
_DUMMY_HASH = hash_password("cockpit-py-dummy-password")

def check_password_or_dummy(password: str, user: Optional[AppUserModel]) -> bool:
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user.password_hash)

# ---------------------------------------------------------------- server-side sessions

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

async def create_session(user_id: int, ip: str, user_agent: str) -> str:
    """Creates a session row and returns the raw token for the cookie (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    async with AsyncSessionLocal() as db:
        # Opportunistic cleanup of dead sessions
        idle_cutoff = now - settings.SESSION_IDLE_MINUTES * 60
        await db.execute(
            delete(AppSessionModel).where(
                (AppSessionModel.expires_at < now) | (AppSessionModel.last_seen_at < idle_cutoff)
            )
        )
        db.add(AppSessionModel(
            token_hash=_hash_token(token),
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + settings.SESSION_HOURS * 3600,
            ip=ip[:64],
            user_agent=(user_agent or "")[:256],
        ))
        await db.commit()
    return token

async def revoke_session(token: Optional[str]):
    if not token:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSessionModel).where(AppSessionModel.token_hash == _hash_token(token)))
        await db.commit()

async def revoke_user_sessions(user_id: int, keep_token: Optional[str] = None):
    async with AsyncSessionLocal() as db:
        stmt = delete(AppSessionModel).where(AppSessionModel.user_id == user_id)
        if keep_token:
            stmt = stmt.where(AppSessionModel.token_hash != _hash_token(keep_token))
        await db.execute(stmt)
        await db.commit()

async def resolve_session(token: Optional[str], touch: bool = True) -> Optional[Tuple[CurrentUser, AppUserModel]]:
    """Returns the user for a valid, non-idle, non-expired session token; None otherwise."""
    if not token or len(token) > 128:
        return None
    now = time.time()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(AppSessionModel, AppUserModel)
            .join(AppUserModel, AppUserModel.id == AppSessionModel.user_id)
            .where(AppSessionModel.token_hash == _hash_token(token))
        )
        row = res.first()
        if not row:
            return None
        sess, user = row
        if user.disabled:
            return None
        if sess.expires_at < now or sess.last_seen_at < now - settings.SESSION_IDLE_MINUTES * 60:
            await db.delete(sess)
            await db.commit()
            return None
        # Sliding idle window; throttled to avoid a DB write on every request
        if touch and now - sess.last_seen_at > 30:
            sess.last_seen_at = now
            await db.commit()
        return to_current_user(user), user

def to_current_user(user: AppUserModel) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role or "viewer",
        mfa_enabled=bool(user.mfa_enabled),
        mfa_setup_required=settings.MFA_REQUIRED and not user.mfa_enabled,
    )

def session_token(conn) -> Optional[str]:
    return conn.cookies.get(settings.SESSION_COOKIE_NAME)

async def require_session(request: Request) -> CurrentUser:
    """Any logged-in user, even one who still has to enroll MFA. Only for /auth endpoints."""
    resolved = await resolve_session(session_token(request))
    if not resolved:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    request.state.user = resolved[0]
    return resolved[0]

def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return path[len(settings.API_V1_STR):] if path.startswith(settings.API_V1_STR) else path

async def require_user(request: Request) -> CurrentUser:
    """Logged in, MFA satisfied, and role allowed by app.core.policy for this route."""
    user = await require_session(request)
    if user.mfa_setup_required:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="mfa_setup_required")
    needed = policy.required_role(request.method, _route_template(request))
    if not policy.has_role(user.role, needed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role '{needed}'")
    return user

async def authenticate_websocket(websocket: WebSocket, needed_role: str = "viewer") -> Optional[CurrentUser]:
    """Validates session, MFA and role on a WebSocket handshake. Closes the socket if not allowed."""
    resolved = await resolve_session(session_token(websocket))
    user = resolved[0] if resolved else None
    if not user:
        code = 4401  # unauthenticated
    elif user.mfa_setup_required or not policy.has_role(user.role, needed_role):
        code = 4403  # forbidden
    else:
        return user
    # Accept then close so the browser sees our code instead of a bare 1006
    await websocket.accept()
    await websocket.close(code=code)
    return None

# ---------------------------------------------------------------- client identity & rate limiting

_proxy_hosts: Dict[str, Tuple[float, Set[str]]] = {}  # hostname -> (resolved at, addresses)

def _resolve_proxy_host(name: str) -> Set[str]:
    cached = _proxy_hosts.get(name)
    if cached and time.time() - cached[0] < 60:  # container IPs change when it is recreated
        return cached[1]
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(name, None)}
    except OSError:
        logger.warning(f"Cannot resolve trusted proxy '{name}'; its client-IP headers are ignored")
        addrs = set()
    _proxy_hosts[name] = (time.time(), addrs)
    return addrs

def is_trusted_proxy(peer: str) -> bool:
    if not settings.TRUSTED_PROXIES:
        return True
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in settings.TRUSTED_PROXIES:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:  # not an IP/CIDR: a hostname
            if peer in _resolve_proxy_host(entry):
                return True
    return False

def client_ip(conn) -> str:
    peer = conn.client.host if conn.client else "unknown"
    if settings.TRUST_PROXY_HEADERS and is_trusted_proxy(peer):
        # Cloudflare Tunnel sets CF-Connecting-IP to the real visitor address. In X-Forwarded-For only
        # the last entry (appended by the proxy itself) is trustworthy; the client wrote the rest.
        forwarded = conn.headers.get("cf-connecting-ip") or conn.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return peer

class LoginRateLimiter:
    """In-memory sliding-window failure counter (per IP and per account)."""
    def __init__(self):
        self._failures: Dict[str, List[float]] = defaultdict(list)

    def _prune(self, key: str) -> List[float]:
        cutoff = time.time() - settings.LOGIN_LOCKOUT_SECONDS
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, key: str, max_attempts: int) -> int:
        recent = self._prune(key)
        if len(recent) < max_attempts:
            return 0
        return max(1, int(recent[0] + settings.LOGIN_LOCKOUT_SECONDS - time.time()))

    def record_failure(self, key: str):
        self._failures[key].append(time.time())

    def reset(self, key: str):
        self._failures.pop(key, None)

login_limiter = LoginRateLimiter()

AuthRequired = Depends(require_user)
