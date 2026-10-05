from typing import Optional
from sqlalchemy import Column, Float, Integer, String, Text, Boolean
from pydantic import BaseModel, ConfigDict
from app.core.database import Base

class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(Float, nullable=False, index=True)  # epoch seconds
    username = Column(String(64), nullable=True, index=True)
    ip = Column(String(64), nullable=True)
    action = Column(String(128), nullable=False, index=True)
    server_id = Column(String(64), nullable=True)
    target = Column(String(512), nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    detail = Column(Text, nullable=True)

class AuditEntry(BaseModel):
    id: int
    ts: float
    username: Optional[str] = None
    ip: Optional[str] = None
    action: str
    server_id: Optional[str] = None
    target: Optional[str] = None
    success: bool
    detail: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
