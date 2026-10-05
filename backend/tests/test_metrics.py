import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.local_collector import local_collector
from app.models.metrics import SystemMetricsPayload

@pytest.mark.asyncio
async def test_local_collector():
    metrics = local_collector.collect("local")
    assert isinstance(metrics, SystemMetricsPayload)
    assert metrics.server_id == "local"
    assert metrics.cpu.cores >= 1
    assert 0.0 <= metrics.cpu.usage_percent <= 100.0
    assert metrics.memory.total > 0
    assert 0.0 <= metrics.memory.percent <= 100.0
    assert metrics.host_info is not None
    assert metrics.host_info.hostname != ""

@pytest.mark.asyncio
async def test_metrics_snapshot_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/metrics/local")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == "local"
        assert "cpu" in data
        assert "memory" in data
        assert "disk_io" in data
        assert "network" in data
