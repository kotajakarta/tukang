import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import init_db

@pytest.mark.asyncio
async def test_server_inventory_crud():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test health check
        health_resp = await client.get("/api/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"

        # Test listing servers - must contain default 'local'
        list_resp = await client.get("/api/v1/servers")
        assert list_resp.status_code == 200
        servers = list_resp.json()
        assert len(servers) >= 1
        assert any(s["id"] == "local" for s in servers)

        # Test creating new remote server with password
        new_server_payload = {
            "id": "srv-test-1",
            "name": "Production Node 1",
            "host": "192.168.1.50",
            "port": 22,
            "username": "admin",
            "auth_type": "password",
            "password": "secret_password_123"
        }
        create_resp = await client.post("/api/v1/servers", json=new_server_payload)
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["id"] == "srv-test-1"
        assert created["name"] == "Production Node 1"
        assert created["has_password"] is True

        # Test getting single server
        get_resp = await client.get("/api/v1/servers/srv-test-1")
        assert get_resp.status_code == 200
        assert get_resp.json()["host"] == "192.168.1.50"
        assert get_resp.json()["has_password"] is True

        # Verify from_server extracts password from DB
        from app.core.database import AsyncSessionLocal
        from app.models.server import ServerModel
        from app.services.ssh_manager import ServerConnectionInfo
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            s_db = (await session.execute(select(ServerModel).where(ServerModel.id == "srv-test-1"))).scalar_one()
            assert s_db.password == "secret_password_123"
            conn_info = ServerConnectionInfo.from_server(s_db)
            assert conn_info.password == "secret_password_123"
            assert conn_info.host == "192.168.1.50"

        # Test updating server
        update_resp = await client.put("/api/v1/servers/srv-test-1", json={"name": "Prod Node Renamed", "password": "new_secret_456"})
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Prod Node Renamed"
        assert update_resp.json()["has_password"] is True

        # Verify updated password in DB
        async with AsyncSessionLocal() as session:
            s_db = (await session.execute(select(ServerModel).where(ServerModel.id == "srv-test-1"))).scalar_one()
            assert s_db.password == "new_secret_456"

        # Test deleting server
        del_resp = await client.delete("/api/v1/servers/srv-test-1")
        assert del_resp.status_code == 204

        # Verify deleted
        get_deleted = await client.get("/api/v1/servers/srv-test-1")
        assert get_deleted.status_code == 404
