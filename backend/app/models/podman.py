from typing import List, Optional, Any, Literal
from pydantic import BaseModel, ConfigDict

class PodmanContainer(BaseModel):
    id: str
    names: List[str]
    image: str
    state: str
    status: str
    created: str
    ports: Optional[List[Any]] = []
    is_rootless: bool = False
    # systemd unit that owns the container (Quadlet sets the PODMAN_SYSTEMD_UNIT label), if any
    systemd_unit: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ContainerActionRequest(BaseModel):
    action: Literal["start", "stop", "restart", "pause", "unpause", "remove"]

class ContainerActionResponse(BaseModel):
    success: bool
    container_id: str
    action: str
    message: str

class QuadletUnit(BaseModel):
    name: str
    path: str
    unit_type: Literal["container", "network", "volume", "image", "kube", "pod", "build", "unknown"]
    content: Optional[str] = None
    is_user: bool = False

class QuadletSaveRequest(BaseModel):
    filename: str
    content: str
    is_user: bool = False
    # Existing file being edited: written in place instead of to the default dir for `is_user`
    path: Optional[str] = None

class QuadletSaveResponse(BaseModel):
    success: bool
    path: str
    message: str
    # Saved, but something after it went wrong (e.g. daemon-reload)
    warning: Optional[str] = None
