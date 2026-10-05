import json
import logging
import secrets
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core import totp
from app.core.passwords import enforce_password_policy
from app.core.security import (
    check_password_or_dummy, client_ip, create_session, hash_password, login_limiter,
    require_session, revoke_session, revoke_user_sessions, session_token, to_current_user, verify_password,
)
from app.models.audit import AuditLogModel
from app.models.user import (
    AppUserModel, ChangePasswordRequest, CurrentUser, LoginRequest, MfaCodeRequest, MfaDisableRequest,
    MfaSetupResponse, RecoveryCodesResponse, utc_now,
)
from app.services import audit_service

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["Auth"])

def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )

def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many failed attempts. Try again in {wait} seconds.",
        headers={"Retry-After": str(wait)},
    )

def _reauth_guard(user: CurrentUser) -> str:
    """Limiter key for re-entering the password / an MFA code inside a session. A stolen session must not
    be an unlimited oracle for them (a guessed TOTP mints recovery codes). 429 once the limit is hit."""
    key = f"reauth:{user.id}"
    wait = login_limiter.retry_after(key, settings.LOGIN_MAX_ATTEMPTS)
    if wait:
        raise _too_many(wait)
    return key

RECOVERY_CODE_COUNT = 10

def _new_recovery_codes() -> List[str]:
    # 10 chars from an unambiguous alphabet, shown as xxxxx-xxxxx
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes

def _check_second_factor(user: AppUserModel, code: str) -> Optional[str]:
    """Verifies a TOTP or single-use recovery code. Returns 'totp'/'recovery' or None. Mutates user."""
    step = totp.verify(user.mfa_secret, code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return "totp"
    normalized = code.strip().lower()
    hashes = json.loads(user.recovery_codes or "[]")
    for h in hashes:
        if verify_password(normalized, h):
            hashes.remove(h)  # single use
            user.recovery_codes = json.dumps(hashes)
            return "recovery"
    return None

async def _signed_in_from(db: AsyncSession, username: str, ip: str) -> bool:
    """True if `username` logged in successfully from `ip` within LOGIN_KNOWN_IP_DAYS (per the audit log)."""
    since = time.time() - settings.LOGIN_KNOWN_IP_DAYS * 86400
    return (await db.execute(
        select(AuditLogModel.id).where(
            AuditLogModel.action == "login.success", AuditLogModel.username == username,
            AuditLogModel.ip == ip, AuditLogModel.ts >= since,
        ).limit(1)
    )).first() is not None

@router.post("/login", response_model=CurrentUser)
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    ip_key, account_key = f"ip:{ip}", f"user:{body.username.lower()}"
    ip_wait = login_limiter.retry_after(ip_key, settings.LOGIN_MAX_ATTEMPTS)
    account_wait = login_limiter.retry_after(account_key, settings.LOGIN_ACCOUNT_MAX_ATTEMPTS)
    if account_wait and not ip_wait and await _signed_in_from(db, body.username, ip):
        account_wait = 0
    wait = max(ip_wait, account_wait)
    if wait:
        await audit_service.record("login.blocked", username=body.username, ip=ip, success=False)
        raise _too_many(wait)

    res = await db.execute(select(AppUserModel).where(AppUserModel.username == body.username))
    user = res.scalar_one_or_none()
    if not check_password_or_dummy(body.password, user) or user.disabled:
        login_limiter.record_failure(ip_key)
        login_limiter.record_failure(account_key)
        await audit_service.record("login.failure", username=body.username, ip=ip, success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if user.mfa_enabled:
        if not body.otp:
            # Password was right; the client must now ask for the second factor
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="mfa_required")
        method = _check_second_factor(user, body.otp)
        if not method:
            login_limiter.record_failure(ip_key)
            login_limiter.record_failure(account_key)
            await audit_service.record("login.mfa_failure", username=user.username, ip=ip, success=False)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code")
        if method == "recovery":
            await audit_service.record("mfa.recovery_code_used", username=user.username, ip=ip,
                                       detail=f"{len(json.loads(user.recovery_codes))} recovery codes left")

    login_limiter.reset(ip_key)
    login_limiter.reset(account_key)
    user.last_login_at = utc_now()
    await db.commit()

    token = await create_session(user.id, ip, request.headers.get("user-agent", ""))
    _set_session_cookie(response, token)
    await audit_service.record("login.success", username=user.username, ip=ip)
    return to_current_user(user)

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response):
    token = session_token(request)
    try:
        user = await require_session(request)
        await audit_service.record("logout", username=user.username, ip=client_ip(request))
    except HTTPException:
        pass
    await revoke_session(token)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return None

@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(request: Request, response: Response, user: CurrentUser = Depends(require_session)):
    """Signs this account out everywhere, including the current browser."""
    await revoke_user_sessions(user.id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    await audit_service.record("logout.all", username=user.username, ip=client_ip(request))
    return None

@router.get("/me", response_model=CurrentUser)
async def me(user: CurrentUser = Depends(require_session)):
    return user

@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    guard = _reauth_guard(user)
    res = await db.execute(select(AppUserModel).where(AppUserModel.id == user.id))
    db_user = res.scalar_one()
    if not verify_password(body.current_password, db_user.password_hash):
        login_limiter.record_failure(guard)
        await audit_service.record("password.change", username=user.username, ip=client_ip(request), success=False)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    login_limiter.reset(guard)
    enforce_password_policy(body.new_password, db_user.username)

    db_user.password_hash = hash_password(body.new_password)
    await db.commit()
    # Sign out every other browser; keep this one
    await revoke_user_sessions(user.id, keep_token=session_token(request))
    await audit_service.record("password.change", username=user.username, ip=client_ip(request))
    return None

# ---------------------------------------------------------------- MFA (TOTP)

async def _load(db: AsyncSession, user_id: int) -> AppUserModel:
    return (await db.execute(select(AppUserModel).where(AppUserModel.id == user_id))).scalar_one()

@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(user: CurrentUser = Depends(require_session), db: AsyncSession = Depends(get_db)):
    """Starts enrollment: returns a new secret. MFA is not active until /mfa/enable confirms a code."""
    db_user = await _load(db, user.id)
    if db_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")
    db_user.mfa_secret = totp.generate_secret()
    db_user.mfa_last_step = None
    await db.commit()
    return MfaSetupResponse(secret=db_user.mfa_secret, otpauth_uri=totp.provisioning_uri(db_user.mfa_secret, db_user.username))

@router.post("/mfa/enable", response_model=RecoveryCodesResponse)
async def mfa_enable(
    body: MfaCodeRequest, request: Request,
    user: CurrentUser = Depends(require_session), db: AsyncSession = Depends(get_db),
):
    db_user = await _load(db, user.id)
    if db_user.mfa_enabled or not db_user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start MFA setup first")
    guard = _reauth_guard(user)
    step = totp.verify(db_user.mfa_secret, body.code, db_user.mfa_last_step)
    if step is None:
        login_limiter.record_failure(guard)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication code")
    login_limiter.reset(guard)
    codes = _new_recovery_codes()
    db_user.mfa_enabled = True
    db_user.mfa_last_step = step
    db_user.recovery_codes = json.dumps([hash_password(c) for c in codes])
    await db.commit()
    await revoke_user_sessions(user.id, keep_token=session_token(request))
    await audit_service.record("mfa.enable", username=user.username, ip=client_ip(request))
    return RecoveryCodesResponse(recovery_codes=codes)

@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_disable(
    body: MfaDisableRequest, request: Request,
    user: CurrentUser = Depends(require_session), db: AsyncSession = Depends(get_db),
):
    if settings.MFA_REQUIRED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is mandatory on this server")
    db_user = await _load(db, user.id)
    if not db_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    guard = _reauth_guard(user)
    if not verify_password(body.password, db_user.password_hash) or not _check_second_factor(db_user, body.code):
        login_limiter.record_failure(guard)
        await audit_service.record("mfa.disable", username=user.username, ip=client_ip(request), success=False)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password or authentication code")
    login_limiter.reset(guard)
    db_user.mfa_enabled = False
    db_user.mfa_secret = None
    db_user.mfa_last_step = None
    db_user.recovery_codes = None
    await db.commit()
    await audit_service.record("mfa.disable", username=user.username, ip=client_ip(request))
    return None

@router.post("/mfa/recovery-codes", response_model=RecoveryCodesResponse)
async def mfa_regenerate_recovery_codes(
    body: MfaCodeRequest, request: Request,
    user: CurrentUser = Depends(require_session), db: AsyncSession = Depends(get_db),
):
    db_user = await _load(db, user.id)
    if not db_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    guard = _reauth_guard(user)
    step = totp.verify(db_user.mfa_secret, body.code, db_user.mfa_last_step)
    if step is None:
        login_limiter.record_failure(guard)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication code")
    login_limiter.reset(guard)
    codes = _new_recovery_codes()
    db_user.mfa_last_step = step
    db_user.recovery_codes = json.dumps([hash_password(c) for c in codes])
    await db.commit()
    await audit_service.record("mfa.recovery_codes_regenerated", username=user.username, ip=client_ip(request))
    return RecoveryCodesResponse(recovery_codes=codes)
