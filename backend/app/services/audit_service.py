import json
import logging
import time
from typing import Optional
from sqlalchemy import delete
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.audit import AuditLogModel

# Separate logger so operators can route audit lines (JSON) to a SIEM via journald
audit_logger = logging.getLogger("audit")

async def record(
    action: str,
    username: Optional[str] = None,
    ip: Optional[str] = None,
    server_id: Optional[str] = None,
    target: Optional[str] = None,
    success: bool = True,
    detail: Optional[str] = None,
):
    entry = dict(
        ts=time.time(), username=username, ip=ip, action=action,
        server_id=server_id, target=(target or None) and target[:512], success=success,
        detail=(detail or None) and detail[:2000],
    )
    audit_logger.info(json.dumps(entry))
    try:
        async with AsyncSessionLocal() as db:
            db.add(AuditLogModel(**entry))
            await db.commit()
    except Exception as e:  # never let auditing break the request, but make it loud
        audit_logger.error(f"Failed to persist audit entry: {e}")

async def prune():
    cutoff = time.time() - settings.AUDIT_RETENTION_DAYS * 86400
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLogModel).where(AuditLogModel.ts < cutoff))
        await db.commit()
