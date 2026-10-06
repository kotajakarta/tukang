from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.passwords import enforce_password_policy
from app.core.security import client_ip, hash_password, require_user, revoke_user_sessions
from app.models.user import (
    AppUserCreate, AppUserModel, AppUserOut, AppUserUpdate, CurrentUser, PasswordResetRequest,
)
from app.services import audit_service

# tuKang login accounts (not Linux users). Admin-only via app.core.policy.
router = APIRouter(prefix="/app-users", tags=["Access Control"])

async def _get(db: AsyncSession, user_id: int) -> AppUserModel:
    user = (await db.execute(select(AppUserModel).where(AppUserModel.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return user

async def _active_admins(db: AsyncSession) -> int:
    return (await db.execute(
        select(func.count()).select_from(AppUserModel).where(AppUserModel.role == "admin", AppUserModel.disabled.is_(False))
    )).scalar_one()

@router.get("", response_model=List[AppUserOut])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(AppUserModel).order_by(AppUserModel.username))).scalars().all()

@router.post("", response_model=AppUserOut, status_code=status.HTTP_201_CREATED)
async def create_account(body: AppUserCreate, request: Request, db: AsyncSession = Depends(get_db),
                         me: CurrentUser = Depends(require_user)):
    if (await db.execute(select(AppUserModel).where(AppUserModel.username == body.username))).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")
    enforce_password_policy(body.password, body.username)
    user = AppUserModel(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit_service.record("account.create", username=me.username, ip=client_ip(request),
                               target=f"{body.username} role={body.role}")
    return user

@router.put("/{user_id}", response_model=AppUserOut)
async def update_account(user_id: int, body: AppUserUpdate, request: Request, db: AsyncSession = Depends(get_db),
                         me: CurrentUser = Depends(require_user)):
    user = await _get(db, user_id)
    losing_admin = user.role == "admin" and not user.disabled and (
        (body.role is not None and body.role != "admin") or body.disabled is True
    )
    if user.id == me.id and losing_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot demote or disable yourself")
    if losing_admin and await _active_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin is required")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    if body.disabled:
        await revoke_user_sessions(user.id)
    await audit_service.record("account.update", username=me.username, ip=client_ip(request),
                               target=f"{user.username} " + " ".join(f"{k}={v}" for k, v in changes.items()))
    return user

@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(user_id: int, body: PasswordResetRequest, request: Request,
                         db: AsyncSession = Depends(get_db), me: CurrentUser = Depends(require_user)):
    user = await _get(db, user_id)
    enforce_password_policy(body.new_password, user.username)
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    await revoke_user_sessions(user.id)
    await audit_service.record("account.reset_password", username=me.username, ip=client_ip(request), target=user.username)
    return None

@router.post("/{user_id}/reset-mfa", status_code=status.HTTP_204_NO_CONTENT)
async def reset_mfa(user_id: int, request: Request, db: AsyncSession = Depends(get_db),
                    me: CurrentUser = Depends(require_user)):
    """For a user who lost their authenticator and recovery codes."""
    user = await _get(db, user_id)
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_last_step = None
    user.recovery_codes = None
    await db.commit()
    await revoke_user_sessions(user.id)
    await audit_service.record("account.reset_mfa", username=me.username, ip=client_ip(request), target=user.username)
    return None

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(user_id: int, request: Request, db: AsyncSession = Depends(get_db),
                         me: CurrentUser = Depends(require_user)):
    user = await _get(db, user_id)
    if user.id == me.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")
    if user.role == "admin" and not user.disabled and await _active_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin is required")
    await revoke_user_sessions(user.id)  # SQLite doesn't enforce the FK cascade
    await db.delete(user)
    await db.commit()
    await audit_service.record("account.delete", username=me.username, ip=client_ip(request), target=user.username)
    return None
