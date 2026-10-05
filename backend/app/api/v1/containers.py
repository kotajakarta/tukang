from typing import List
from fastapi import APIRouter, Query, HTTPException, status
from app.models.podman import (
    PodmanContainer, ContainerActionRequest, ContainerActionResponse,
    QuadletUnit, QuadletSaveRequest, QuadletSaveResponse
)
from app.services.podman_service import podman_service

router = APIRouter(prefix="/containers", tags=["Podman Containers & Quadlets"])

@router.get("/{server_id}", response_model=List[PodmanContainer])
async def list_containers(server_id: str):
    return await podman_service.list_containers(server_id)

@router.post("/{server_id}/{container_id}/action", response_model=ContainerActionResponse)
async def container_action(server_id: str, container_id: str, body: ContainerActionRequest):
    return await podman_service.container_action(server_id, container_id, body.action)

@router.get("/{server_id}/{container_id}/logs")
async def get_container_logs(server_id: str, container_id: str, lines: int = Query(100, ge=1, le=1000)):
    logs = await podman_service.get_container_logs(server_id, container_id, lines)
    return {"container_id": container_id, "logs": logs}

@router.get("/{server_id}/quadlets/list", response_model=List[QuadletUnit])
async def list_quadlets(server_id: str):
    return await podman_service.list_quadlets(server_id)

@router.get("/{server_id}/quadlets/content")
async def get_quadlet_content(server_id: str, path: str = Query(...)):
    content = await podman_service.get_quadlet_content(server_id, path)
    if content is None:
        raise HTTPException(status_code=404, detail="Quadlet file not found")
    return {"path": path, "content": content}

@router.post("/{server_id}/quadlets", response_model=QuadletSaveResponse)
async def save_quadlet(server_id: str, body: QuadletSaveRequest):
    return await podman_service.save_quadlet(server_id, body.filename, body.content, body.is_user, body.path)

@router.delete("/{server_id}/quadlets")
async def delete_quadlet(server_id: str, path: str = Query(...), is_user: bool = Query(False)):
    success = await podman_service.delete_quadlet(server_id, path, is_user)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete quadlet file")
    return {"success": True, "message": "Quadlet deleted"}
