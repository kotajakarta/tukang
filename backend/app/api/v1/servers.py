import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, or_, select
from app.core.config import is_direct_local
from app.services.ssh_manager import ssh_manager, host_key_fingerprint
from app.core.database import get_db
from app.models.file_remote import FileRemoteModel
from app.models.server import ServerModel, ServerCreate, ServerUpdate, ServerResponse, ServerTestResult

router = APIRouter(prefix="/servers", tags=["Servers"])

def _decorate(server: ServerModel) -> ServerModel:
    """Adds write-only-secret indicators; the secrets themselves are never serialized."""
    server.has_password = bool(server.password)
    server.has_private_key = bool(server.private_key)
    server.has_sudo_password = bool(server.sudo_password)
    server.host_key_fingerprint = host_key_fingerprint(server.host_key)
    return server

@router.get("", response_model=List[ServerResponse])
async def list_servers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ServerModel).order_by(ServerModel.is_local.desc(), ServerModel.name.asc()))
    servers = result.scalars().all()
    for s in servers:
        _decorate(s)
    return servers

@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(server_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
    _decorate(server)
    return server

@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(server_in: ServerCreate, db: AsyncSession = Depends(get_db)):
    server_id = server_in.id or f"srv-{uuid.uuid4().hex[:8]}"
    existing = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Server id {server_id} already exists")

    server = ServerModel(
        id=server_id,
        name=server_in.name,
        host=server_in.host,
        port=server_in.port,
        username=server_in.username,
        is_local=server_in.is_local,
        auth_type=server_in.auth_type,
        key_path=server_in.key_path,
        private_key=server_in.private_key,
        password=server_in.password,
        use_sudo=server_in.use_sudo,
        sudo_password=(server_in.sudo_password or None) if server_in.use_sudo else None,
        status="unknown"
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    _decorate(server)
    return server

@router.put("/{server_id}", response_model=ServerResponse)
async def update_server(server_id: str, server_in: ServerUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")

    update_data = server_in.model_dump(exclude_unset=True)
    # Blank secrets mean "keep the stored value" (the UI never receives them to round-trip)
    for secret_field in ("password", "private_key", "sudo_password"):
        if not update_data.get(secret_field):
            update_data.pop(secret_field, None)
    # Turning sudo off forgets its password (turn it back on without one for passwordless sudo)
    if update_data.get("use_sudo") is False:
        update_data["sudo_password"] = None
    # A different endpoint is a different machine: forget the pinned host key
    if ("host" in update_data and update_data["host"] != server.host) or (
        "port" in update_data and update_data["port"] != server.port
    ):
        server.host_key = None
        await ssh_manager.close_connection(server.id)
    for field, value in update_data.items():
        setattr(server, field, value)

    await db.commit()
    await db.refresh(server)
    _decorate(server)
    return server

@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: str, db: AsyncSession = Depends(get_db)):
    if server_id == "local":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete master/local controller server")
    result = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
    await db.delete(server)
    # Files remote mappings on either side of this server would point nowhere
    await db.execute(delete(FileRemoteModel).where(
        or_(FileRemoteModel.local_server_id == server_id, FileRemoteModel.remote_server_id == server_id)
    ))
    await db.commit()
    return None

@router.post("/{server_id}/test", response_model=ServerTestResult)
async def test_server_connection(server_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")

    if is_direct_local(server.id):
        import platform
        return ServerTestResult(
            success=True,
            message="Local controller node is operational",
            latency_ms=0.1,
            os_info=f"{platform.system()} {platform.release()}"
        )

    from app.services.ssh_manager import ServerConnectionInfo
    info = ServerConnectionInfo.from_server(server)
    success, msg, latency, os_info = await ssh_manager.test_connection(info)
    
    server.status = "online" if success else "error"
    await db.commit()

    return ServerTestResult(
        success=success,
        message=msg,
        latency_ms=latency,
        os_info=os_info
    )

@router.post("/{server_id}/reset-host-key", response_model=ServerResponse)
async def reset_host_key(server_id: str, db: AsyncSession = Depends(get_db)):
    """Forget the pinned SSH host key (use after the node was legitimately reinstalled)."""
    result = await db.execute(select(ServerModel).where(ServerModel.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
    server.host_key = None
    await db.commit()
    await db.refresh(server)
    await ssh_manager.close_connection(server_id)
    return _decorate(server)
