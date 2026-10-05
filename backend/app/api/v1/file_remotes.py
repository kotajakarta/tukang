from typing import List, Literal, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.files import _abs_path, agent
from app.core.database import get_db
from app.core.security import client_ip, require_user
from app.models.file_remote import FileRemoteIn, FileRemoteModel, FileRemoteResponse
from app.models.server import ServerModel
from app.models.user import CurrentUser
from app.services import audit_service, transfer_service
from app.services.files_agent import PROTECTED

# Remote folder mappings for the file manager: upload/download a project folder between two servers,
# like the VS Code SFTP extension. Admin-only via app.core.policy (acts as root on both nodes).
router = APIRouter(prefix="/files", tags=["Files"])

class TransferIn(BaseModel):
    direction: Literal["upload", "download"]
    # Absolute paths on the mapping's LOCAL server, inside its local folder
    paths: List[str] = Field(..., min_length=1, max_length=10000)

def _overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")

async def _validated(db: AsyncSession, body: FileRemoteIn) -> Tuple[str, str]:
    for server_id in {body.local_server_id, body.remote_server_id}:
        if not (await db.execute(select(ServerModel.id).where(ServerModel.id == server_id))).scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Server {server_id} not found")
    local_path, remote_path = _abs_path(body.local_path), _abs_path(body.remote_path)
    for p in (local_path, remote_path):
        if p in PROTECTED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Choose a project folder, not the system directory {p}")
    if body.local_server_id == body.remote_server_id and _overlaps(local_path, remote_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="On the same server the two folders must not contain each other")
    return local_path, remote_path

async def _remote(db: AsyncSession, remote_id: int) -> FileRemoteModel:
    remote = (await db.execute(select(FileRemoteModel).where(FileRemoteModel.id == remote_id))).scalar_one_or_none()
    if not remote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remote not found")
    return remote

async def _audit(request: Request, user: CurrentUser, action: str, remote: FileRemoteModel, ok: bool = True, detail=None):
    await audit_service.record(action, username=user.username, ip=client_ip(request), server_id=remote.local_server_id,
                               target=f"{remote.name}: {remote.local_path} -> {remote.remote_server_id}:{remote.remote_path}",
                               success=ok, detail=detail)

def _plan(remote: FileRemoteModel, body: TransferIn):
    """(source server, source root, dest server, dest root, relative paths) for a transfer request."""
    root = remote.local_path.rstrip("/")
    rels = []
    for raw in body.paths:
        p = _abs_path(raw)
        if p == remote.local_path:
            rels.append(".")
        elif p.startswith(root + "/"):
            rels.append(p[len(root) + 1:])
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{p} is outside the remote's local folder {remote.local_path}")
    if body.direction == "upload":
        return remote.local_server_id, remote.local_path, remote.remote_server_id, remote.remote_path, rels
    return remote.remote_server_id, remote.remote_path, remote.local_server_id, remote.local_path, rels

# ---------------------------------------------------------------- mappings

@router.get("/remotes", response_model=List[FileRemoteResponse])
async def list_remotes(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(FileRemoteModel).order_by(FileRemoteModel.name))).scalars().all()

@router.post("/remotes", response_model=FileRemoteResponse, status_code=status.HTTP_201_CREATED)
async def create_remote(body: FileRemoteIn, request: Request, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_user)):
    local_path, remote_path = await _validated(db, body)
    remote = FileRemoteModel(name=body.name, local_server_id=body.local_server_id, local_path=local_path,
                             remote_server_id=body.remote_server_id, remote_path=remote_path)
    remote.ignore = body.ignore
    db.add(remote)
    await db.commit()
    await _audit(request, user, "files.remote.create", remote)
    return remote

@router.put("/remotes/{remote_id}", response_model=FileRemoteResponse)
async def update_remote(remote_id: int, body: FileRemoteIn, request: Request, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_user)):
    remote = await _remote(db, remote_id)
    local_path, remote_path = await _validated(db, body)
    remote.name, remote.local_server_id, remote.local_path = body.name, body.local_server_id, local_path
    remote.remote_server_id, remote.remote_path, remote.ignore = body.remote_server_id, remote_path, body.ignore
    await db.commit()
    await _audit(request, user, "files.remote.update", remote)
    return remote

@router.delete("/remotes/{remote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_remote(remote_id: int, request: Request, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_user)):
    remote = await _remote(db, remote_id)
    await db.delete(remote)
    await db.commit()
    await _audit(request, user, "files.remote.delete", remote)

# ---------------------------------------------------------------- transfers

@router.post("/remotes/{remote_id}/scan")
async def scan_transfer(remote_id: int, body: TransferIn, db: AsyncSession = Depends(get_db)):
    """Preview: what a transfer would send (counts, size, ignored), without changing anything."""
    remote = await _remote(db, remote_id)
    src_id, src_root, dst_id, dst_root, rels = _plan(remote, body)
    counts = await agent(src_id, "scan", root=src_root, rels=rels, ignore=remote.ignore)
    return {**counts, "source_server_id": src_id, "source_root": src_root, "dest_server_id": dst_id, "dest_root": dst_root, "rels": rels}

@router.post("/remotes/{remote_id}/transfer")
async def start_transfer(remote_id: int, body: TransferIn, request: Request, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_user)):
    remote = await _remote(db, remote_id)
    if transfer_service.running_for(remote.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A transfer for {remote.name} is already running")
    src_id, src_root, dst_id, dst_root, rels = _plan(remote, body)
    counts = await agent(src_id, "scan", root=src_root, rels=rels, ignore=remote.ignore)
    if not (counts["files"] or counts["dirs"] or counts["links"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to transfer: everything selected is ignored")

    ip = client_ip(request)
    job = transfer_service.TransferJob(
        remote_id=remote.id, remote_name=remote.name, direction=body.direction,
        source_server_id=src_id, source_root=src_root, dest_server_id=dst_id, dest_root=dst_root,
        rels=[r for r in rels if r not in counts["skipped"]], ignore=remote.ignore, username=user.username,
        total_bytes=counts["tar_bytes"], total_files=counts["files"],
    )

    async def audit_finished(j: transfer_service.TransferJob):
        r = j.result or {}
        detail = (f"from {j.source_server_id}:{j.source_root}; {r.get('files', 0)} files, {r.get('bytes', 0)} bytes"
                  if j.state == "done" else f"from {j.source_server_id}:{j.source_root}; {j.error}")
        await audit_service.record(f"files.sync.{j.direction}", username=j.username, ip=ip, server_id=j.dest_server_id,
                                   target=f"{j.dest_root} [{', '.join(j.rels)}]"[:500], success=j.state == "done", detail=detail)

    return transfer_service.start(job, audit_finished).public()

@router.get("/transfers/{job_id}")
async def transfer_status(job_id: str):
    job = transfer_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    return job.public()

@router.post("/transfers/{job_id}/cancel")
async def cancel_transfer(job_id: str):
    job = transfer_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    transfer_service.cancel(job)
    return job.public()
