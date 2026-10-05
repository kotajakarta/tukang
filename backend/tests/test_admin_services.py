import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_storage_overview_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/storage/local")
        assert resp.status_code == 200
        data = resp.json()
        assert "block_devices" in data
        assert "filesystems" in data

@pytest.mark.asyncio
async def test_network_overview_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/network/local")
        assert resp.status_code == 200
        data = resp.json()
        assert "interfaces" in data
        assert "listening_sockets" in data
        assert "firewall" in data

@pytest.mark.asyncio
async def test_users_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/users/local")
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        assert any(u["username"] == "root" for u in users)
