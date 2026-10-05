from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.audit import AuditEntry, AuditLogModel

router = APIRouter(prefix="/audit", tags=["Audit Log"])

@router.get("", response_model=List[AuditEntry])
async def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    before_id: Optional[int] = Query(None, description="Return entries older than this id (pagination)"),
    username: Optional[str] = None,
    action: Optional[str] = Query(None, description="Prefix match, e.g. 'login' or 'POST'"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLogModel).order_by(AuditLogModel.id.desc()).limit(limit)
    if before_id:
        stmt = stmt.where(AuditLogModel.id < before_id)
    if username:
        stmt = stmt.where(AuditLogModel.username == username)
    if action:
        stmt = stmt.where(AuditLogModel.action.startswith(action))
    return (await db.execute(stmt)).scalars().all()
