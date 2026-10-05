from datetime import datetime, timezone
from typing import Annotated, Optional, Literal
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from pydantic import BaseModel, Field, ConfigDict
from app.core.database import Base
from app.core.crypto import EncryptedText

def utc_now():
    return datetime.now(timezone.utc)

class ServerModel(Base):
    __tablename__ = "servers"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=22)
    username = Column(String(64), default="root")
    is_local = Column(Boolean, default=False)
    auth_type = Column(String(32), default="key")  # 'key', 'password', 'agent'
    key_path = Column(String(512), nullable=True)
    private_key = Column(EncryptedText, nullable=True)
    password = Column(EncryptedText, nullable=True)
    # Pinned SSH host public key (OpenSSH format), recorded on first successful connect (TOFU)
    host_key = Column(Text, nullable=True)
    # Log in as a regular account and elevate with `sudo -n` (host-side sudo log = second audit trail)
    use_sudo = Column(Boolean, default=False, nullable=False)
    # Password for sudo when the account has no NOPASSWD rule; None = passwordless sudo
    sudo_password = Column(EncryptedText, nullable=True)
    status = Column(String(32), default="unknown")  # 'online', 'offline', 'unknown', 'error'
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

# Pydantic Schemas
class ServerBase(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "Web-Server-01"})
    host: str = Field(..., json_schema_extra={"example": "192.168.1.100"})
    port: int = Field(22, ge=1, le=65535)
    username: str = Field("root", json_schema_extra={"example": "root"})
    is_local: bool = False
    auth_type: Literal["key", "password", "agent"] = "key"
    key_path: Optional[str] = None
    use_sudo: bool = False

# Sent to sudo as one stdin line, so it cannot contain line breaks
SudoPassword = Optional[Annotated[str, Field(max_length=256, pattern=r"^[^\r\n\x00]*$")]]

class ServerCreate(ServerBase):
    id: Optional[str] = None
    # Write-only secrets: accepted on input, never returned by the API
    private_key: Optional[str] = None
    password: Optional[str] = None
    sudo_password: SudoPassword = None

class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    auth_type: Optional[Literal["key", "password", "agent"]] = None
    key_path: Optional[str] = None
    private_key: Optional[str] = None
    password: Optional[str] = None
    use_sudo: Optional[bool] = None
    sudo_password: SudoPassword = None

class ServerResponse(ServerBase):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime
    has_password: Optional[bool] = None
    has_private_key: Optional[bool] = None
    has_sudo_password: Optional[bool] = None
    host_key_fingerprint: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ServerTestResult(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[float] = None
    os_info: Optional[str] = None
