import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, DateTime, Integer, String, Text
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.database import Base
from app.models.server import utc_now

DEFAULT_IGNORE = [".git", ".vscode", ".idea"]

class FileRemoteModel(Base):
    """A folder on one server paired with a folder on another (like a VS Code SFTP extension sftp.json)."""
    __tablename__ = "file_remotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    local_server_id = Column(String(64), nullable=False, index=True)
    local_path = Column(String(4096), nullable=False)
    remote_server_id = Column(String(64), nullable=False, index=True)
    remote_path = Column(String(4096), nullable=False)
    ignore_json = Column(Text, nullable=False, default="[]")  # gitignore-style patterns
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    @property
    def ignore(self) -> List[str]:
        return json.loads(self.ignore_json or "[]")

    @ignore.setter
    def ignore(self, patterns: List[str]):
        self.ignore_json = json.dumps(patterns)

class FileRemoteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    local_server_id: str = Field(..., max_length=64)
    local_path: str = Field(..., max_length=4096)
    remote_server_id: str = Field(..., max_length=64)
    remote_path: str = Field(..., max_length=4096)
    ignore: List[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE), max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("ignore")
    @classmethod
    def _ignore(cls, patterns: List[str]) -> List[str]:
        cleaned = []
        for p in patterns:
            if len(p) > 256 or any(ch in p for ch in "\r\n\x00"):
                raise ValueError("Each ignore pattern must be one line of at most 256 characters")
            if p.strip() and p.strip() not in cleaned:
                cleaned.append(p.strip())
        return cleaned

class FileRemoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    local_server_id: str
    local_path: str
    remote_server_id: str
    remote_path: str
    ignore: List[str]
    updated_at: Optional[datetime] = None
