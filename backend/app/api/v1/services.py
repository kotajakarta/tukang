from typing import List
from fastapi import APIRouter, Query, HTTPException, status
from app.models.systemd import SystemdUnit, UnitActionRequest, UnitActionResponse, JournalLogsResponse
from app.services.systemd_service import systemd_service

router = APIRouter(prefix="/services", tags=["Systemd Services"])

@router.get("/{server_id}/units", response_model=List[SystemdUnit])
async def list_units(
    server_id: str,
    unit_type: str = Query("service", description="service, timer, or socket")
):
    return await systemd_service.list_units(server_id, unit_type=unit_type)

@router.post("/{server_id}/{unit}/action", response_model=UnitActionResponse)
async def perform_unit_action(server_id: str, unit: str, body: UnitActionRequest):
    return await systemd_service.execute_action(server_id, unit, body.action)

@router.get("/{server_id}/{unit}/logs", response_model=JournalLogsResponse)
async def get_unit_logs(server_id: str, unit: str, lines: int = Query(100, ge=1, le=1000)):
    return await systemd_service.get_logs(server_id, unit, lines=lines)
