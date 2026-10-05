from fastapi import APIRouter
from app.services.storage_service import storage_service

router = APIRouter(prefix="/storage", tags=["Storage Management"])

@router.get("/{server_id}")
async def get_storage_overview(server_id: str):
    return await storage_service.get_storage_overview(server_id)

@router.get("/{server_id}/smart/{device}")
async def get_smart_data(server_id: str, device: str):
    return await storage_service.get_smart_data(server_id, device)
