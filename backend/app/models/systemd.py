from typing import List, Literal
from pydantic import BaseModel, ConfigDict

class SystemdUnit(BaseModel):
    unit: str
    load: str
    active: str
    sub: str
    description: str
    unit_type: str = "service"

    model_config = ConfigDict(from_attributes=True)

class UnitActionRequest(BaseModel):
    action: Literal["start", "stop", "restart", "enable", "disable", "reload", "mask", "unmask"]

class UnitActionResponse(BaseModel):
    success: bool
    unit: str
    action: str
    message: str

class JournalLogsResponse(BaseModel):
    unit: str
    logs: List[str]
