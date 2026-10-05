from datetime import datetime, timezone
from typing import List, Literal, Optional
from sqlalchemy import Boolean, Column, String, Integer, DateTime, Float, ForeignKey, Text
from pydantic import BaseModel, ConfigDict, Field
from app.core.database import Base
from app.core.crypto import EncryptedText

Role = Literal["viewer", "operator", "admin"]
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

def utc_now():
    return datetime.now(timezone.utc)

class AppUserModel(Base):
    """Cockpit-Py login account (separate from Linux system users)."""
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    # Legacy (JWT era); kept so existing databases stay compatible
    token_version = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(String(16), nullable=False, default="admin")
    disabled = Column(Boolean, nullable=False, default=False)
    # TOTP: secret is set during enrollment and only trusted once mfa_enabled is true
    mfa_secret = Column(EncryptedText, nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_last_step = Column(Integer, nullable=True)  # last accepted TOTP step (replay protection)
    recovery_codes = Column(Text, nullable=True)  # JSON list of bcrypt hashes of unused codes

class AppSessionModel(Base):
    """Server-side login session. The cookie holds a random token; only its SHA-256 is stored."""
    __tablename__ = "app_sessions"

    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(Float, nullable=False)  # epoch seconds
    last_seen_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False)  # absolute lifetime
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(256), nullable=True)

# Pydantic Schemas
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)
    otp: Optional[str] = Field(None, max_length=32, description="TOTP code or recovery code")

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)

class CurrentUser(BaseModel):
    id: int
    username: str
    role: Role = "admin"
    mfa_enabled: bool = False
    mfa_setup_required: bool = False

class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str

class MfaCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=32)

class MfaDisableRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)
    code: str = Field(..., min_length=6, max_length=32)

class RecoveryCodesResponse(BaseModel):
    recovery_codes: List[str]

class AppUserOut(BaseModel):
    id: int
    username: str
    role: Role
    disabled: bool
    mfa_enabled: bool
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class AppUserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(..., min_length=1, max_length=256)
    role: Role = "viewer"

class AppUserUpdate(BaseModel):
    role: Optional[Role] = None
    disabled: Optional[bool] = None

class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=1, max_length=256)
