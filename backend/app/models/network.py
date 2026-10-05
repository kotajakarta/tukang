from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.server import SudoPassword

class FirewallPortRequest(BaseModel):
    port: int = Field(ge=1, le=65535)
    # Inclusive range end; omit for a single port
    end_port: Optional[int] = Field(default=None, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    # One-off password for sudo; used for this request only, never stored
    sudo_password: SudoPassword = None

    @model_validator(mode="after")
    def _range(self):
        if self.end_port is not None and self.end_port < self.port:
            raise ValueError("end_port must be >= port")
        return self

class FirewallPortResponse(BaseModel):
    success: bool
    message: str
    # sudo refused (missing/wrong password)
    needs_sudo: bool = False
    # Fresh firewall status after a successful change
    firewall: Optional[Dict[str, Any]] = None

class FirewallRulesRequest(BaseModel):
    sudo_password: SudoPassword = None
