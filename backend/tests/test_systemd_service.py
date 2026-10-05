import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.systemd_service import systemd_service

@pytest.mark.asyncio
async def test_systemd_service_list_local():
    units = await systemd_service.list_units("local", unit_type="service")
    assert isinstance(units, list)
    # On a live Linux system or WSL with systemd, units will have items
    if units:
        unit = units[0]
        assert hasattr(unit, "unit")
        assert hasattr(unit, "active")
        assert hasattr(unit, "sub")

@pytest.mark.asyncio
async def test_systemd_api_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/services/local/units?unit_type=service")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # Test log fetch (will either succeed or return systemd error msg gracefully)
        log_resp = await client.get("/api/v1/services/local/systemd-journald.service/logs?lines=5")
        assert log_resp.status_code == 200
        assert "logs" in log_resp.json()
