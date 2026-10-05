from fastapi import APIRouter
from app.models.network import FirewallPortRequest, FirewallPortResponse, FirewallRulesRequest
from app.services.network_service import network_service

router = APIRouter(prefix="/network", tags=["Network Configuration"])

@router.get("/{server_id}")
async def get_network_overview(server_id: str):
    return await network_service.get_network_overview(server_id)

@router.post("/{server_id}/firewall/ports", response_model=FirewallPortResponse)
async def allow_firewall_port(server_id: str, body: FirewallPortRequest):
    return await network_service.allow_port(server_id, body.port, body.end_port, body.protocol, body.sudo_password)

# POST so the password travels in the body (query strings land in the audit log)
@router.post("/{server_id}/firewall/rules")
async def read_firewall_rules(server_id: str, body: FirewallRulesRequest):
    return await network_service.read_firewall(server_id, body.sudo_password)
