import json
import posixpath
import shlex
import struct
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.security import client_ip, require_user
from app.models.user import CurrentUser
from app.services import audit_service, thumbnails
from app.services.executor import open_process, run_on_server, stream_output

# File manager (Cockpit "Files" equivalent). Admin-only via app.core.policy: it acts as root on the node.
router = APIRouter(prefix="/files", tags=["Files"])

_AGENT_SOURCE = (Path(__file__).resolve().parent.parent.parent / "services" / "files_agent.py").read_text()
_AGENT_CMD = f"python3 -c {shlex.quote(_AGENT_SOURCE)}"

def _abs_path(path: str) -> str:
    if not path or not path.startswith("/") or "\x00" in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path must be absolute")
    return posixpath.normpath(path) if path != "/" else "/"

def _file_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\x00" in name or len(name.encode()) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file name")
    return name

async def agent(server_id: str, op: str, **params) -> Any:
    payload = json.dumps({"op": op, **params})
    code, out, err = await run_on_server(server_id, _AGENT_CMD, timeout=120.0, stdin=payload)
    try:
        res = json.loads(out)
    except ValueError:
        detail = (err or out or "no output").strip()[:500]
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"File agent failed: {detail}")
    if not res.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.get("error", "Operation failed"))
    return res["result"]

async def _audit(request: Request, user: CurrentUser, action: str, server_id: str, target: str, ok: bool = True, detail=None):
    await audit_service.record(action, username=user.username, ip=client_ip(request), server_id=server_id,
                               target=target, success=ok, detail=detail)

# ---------------------------------------------------------------- reads

@router.get("/{server_id}/list")
async def list_dir(server_id: str, path: str = Query("/"), show_hidden: bool = False):
    return await agent(server_id, "list", path=_abs_path(path), show_hidden=show_hidden)

@router.get("/{server_id}/principals")
async def principals(server_id: str):
    """Users/groups for the ownership dialog, plus the agent user's home (default start dir)."""
    return await agent(server_id, "principals")

@router.get("/{server_id}/read")
async def read_file(server_id: str, request: Request, path: str = Query(...), user: CurrentUser = Depends(require_user)):
    path = _abs_path(path)
    result = await agent(server_id, "read", path=path)
    await _audit(request, user, "files.read", server_id, path)
    return result

async def _regular_file_size(server_id: str, path: str, verb: str) -> int:
    info = await agent(server_id, "stat", path=path)
    if info["type"] == "link":
        info = await agent(server_id, "stat", path=posixpath.join(posixpath.dirname(path), info["target"]))
    if info["type"] != "file":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Only regular files can be {verb}")
    return info["size"]

@router.get("/{server_id}/download")
async def download(server_id: str, request: Request, path: str = Query(...), user: CurrentUser = Depends(require_user)):
    path = _abs_path(path)
    size = await _regular_file_size(server_id, path, "downloaded")
    await _audit(request, user, "files.download", server_id, path, detail=f"{size} bytes")
    filename = posixpath.basename(path)
    return StreamingResponse(
        stream_output(server_id, f"cat -- {shlex.quote(path)}"),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(size),
        },
    )

# Media the viewer may render inline. Never HTML/XML documents: they'd run as this origin.
_VIEW_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "bmp": "image/bmp", "ico": "image/x-icon", "avif": "image/avif", "svg": "image/svg+xml",
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "ogv": "video/ogg", "mov": "video/quicktime",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg",
    "wav": "audio/wav", "flac": "audio/flac",
    "pdf": "application/pdf",
}
# Opened directly (not via <img>), an SVG could carry script: render it inert
_MEDIA_CSP = "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox"
# The browser's PDF viewer refuses to render under `sandbox`/`object-src 'none'`; the viewer iframes it
_PDF_CSP = "default-src 'none'; frame-ancestors 'self'"

def _parse_range(header: Optional[str], size: int) -> Optional[tuple]:
    """Single `bytes=a-b` / `bytes=a-` / `bytes=-n` range -> (start, end) inclusive; None = whole file."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if first:
            start, end = int(first), int(last) if last else size - 1
        else:
            start, end = max(size - int(last), 0), size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        raise HTTPException(status_code=416,  # constant name differs across Starlette versions
                            detail="Range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
    return start, min(end, size - 1)

async def _media_response(server_id: str, request: Request, path: str, media_type: str, audit_user: Optional[CurrentUser]):
    """Streams a media file inline, with Range support so players can seek."""
    size = await _regular_file_size(server_id, path, "previewed")
    byte_range = _parse_range(request.headers.get("range"), size)
    start, end = byte_range or (0, size - 1)
    if audit_user and start == 0:  # players issue many range requests while seeking; log the open, not each chunk
        await _audit(request, audit_user, "files.view", server_id, path, detail=f"{size} bytes")

    q_path = shlex.quote(path)
    cmd = f"cat -- {q_path}" if start == 0 and end == size - 1 else f"tail -c +{start + 1} -- {q_path} | head -c {end - start + 1}"
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(posixpath.basename(path))}",
        "Content-Length": str(max(end - start + 1, 0)),
        "Accept-Ranges": "bytes",
        "Content-Security-Policy": _PDF_CSP if media_type == "application/pdf" else _MEDIA_CSP,
        "X-Frame-Options": "SAMEORIGIN",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        stream_output(server_id, cmd),
        status_code=status.HTTP_206_PARTIAL_CONTENT if byte_range else status.HTTP_200_OK,
        media_type=media_type,
        headers=headers,
    )

@router.get("/{server_id}/view")
async def view(server_id: str, request: Request, path: str = Query(...), user: CurrentUser = Depends(require_user)):
    """Inline image/video/audio/PDF for the viewer, with Range support so media can seek."""
    path = _abs_path(path)
    media_type = _VIEW_TYPES.get(posixpath.splitext(path)[1].lstrip(".").lower())
    if not media_type:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="This file type cannot be previewed")
    return await _media_response(server_id, request, path, media_type, user)

@router.get("/{server_id}/thumb")
async def thumb(server_id: str, request: Request, path: str = Query(...), v: str = Query("", max_length=64)):
    """
    Thumbnail for the file list. Images are downscaled here (Pillow, cached); videos are streamed like
    /view so the browser grabs a frame itself, since nodes rarely have ffmpeg. `v` (mtime-size) busts
    the caches when the file changes. Not audited, like directory listings: a folder of photos would
    flood the log, and opening a file in the viewer still is.
    """
    path = _abs_path(path)
    ext = posixpath.splitext(path)[1].lstrip(".").lower()
    media_type = _VIEW_TYPES.get(ext, "")
    if media_type.startswith("video/"):
        return await _media_response(server_id, request, path, media_type, None)
    if not media_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="No thumbnail for this file type")
    data, thumb_type = await thumbnails.get(server_id, path, v, svg=ext == "svg")
    return Response(data, media_type=thumb_type, headers={
        "Cache-Control": "private, max-age=604800",
        "Content-Security-Policy": _MEDIA_CSP,
        "Cross-Origin-Resource-Policy": "same-origin",
    })

# ---------------------------------------------------------------- writes

class FileAction(BaseModel):
    op: Literal["write", "mkdir", "symlink", "rename", "paste", "delete", "chmod"]
    path: Optional[str] = None
    paths: Optional[List[str]] = Field(None, max_length=10000)
    new_path: Optional[str] = None
    dest_dir: Optional[str] = None
    mode: Optional[Any] = None  # paste: "copy"/"move"; chmod: int
    content: Optional[str] = Field(None, max_length=2 * 1024 * 1024)
    create: Optional[bool] = None
    expected_mtime: Optional[float] = None
    target: Optional[str] = Field(None, max_length=4096)
    owner: Optional[str] = Field(None, max_length=64)
    group: Optional[str] = Field(None, max_length=64)
    recursive: Optional[bool] = None

@router.post("/{server_id}/action")
async def file_action(server_id: str, body: FileAction, request: Request, user: CurrentUser = Depends(require_user)):
    params: Dict[str, Any] = body.model_dump(exclude_none=True, exclude={"op"})
    for key in ("path", "new_path", "dest_dir"):
        if key in params:
            params[key] = _abs_path(params[key])
    if "paths" in params:
        params["paths"] = [_abs_path(p) for p in params["paths"]]
        if not params["paths"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No paths given")
    if body.op == "chmod" and body.mode is not None:
        try:
            params["mode"] = int(body.mode)
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid mode")

    target = params.get("path") or " ".join(params.get("paths", []))[:480]
    detail = {
        "rename": f"-> {params.get('new_path')}",
        "paste": f"{params.get('mode', 'copy')} -> {params.get('dest_dir')}",
        "chmod": " ".join(f"{k}={params[k]}" for k in ("mode", "owner", "group", "recursive") if k in params),
        "symlink": f"-> {params.get('target')}",
    }.get(body.op)
    try:
        result = await agent(server_id, body.op, **params)
    except HTTPException as e:
        await _audit(request, user, f"files.{body.op}", server_id, target, ok=False, detail=str(e.detail)[:300])
        raise
    await _audit(request, user, f"files.{body.op}", server_id, target, detail=detail)
    return result

@router.post("/{server_id}/upload")
async def upload(
    server_id: str,
    request: Request,
    dir: str = Query(...),
    name: str = Query(...),
    overwrite: bool = False,
    user: CurrentUser = Depends(require_user),
):
    """Streams the raw request body into <dir>/<name> through the file agent (exclusive temp file + rename;
    owner follows the directory). The body goes as length-prefixed frames ended by an empty one, so an
    upload cut short (too large, client gone) is discarded instead of replacing the file."""
    directory = _abs_path(dir)
    name = _file_name(name)
    dest = posixpath.join(directory, name)
    limit = settings.FILES_MAX_UPLOAD_MB * 1024 * 1024
    received = 0
    agent_gone = False

    def send(data: bytes):
        nonlocal agent_gone
        if not agent_gone:
            try:
                proc.write(data)
            except Exception:
                agent_gone = True

    proc = await open_process(server_id, _AGENT_CMD)
    try:
        send(json.dumps({"op": "upload", "dir": directory, "name": name, "overwrite": overwrite}).encode() + b"\n")
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise HTTPException(status_code=413,  # constant name differs across Starlette versions
                                    detail=f"Upload exceeds {settings.FILES_MAX_UPLOAD_MB} MB")
            if chunk:
                send(struct.pack(">I", len(chunk)) + chunk)
                if not agent_gone:
                    try:
                        await proc.drain()
                    except Exception:  # the agent refused early (e.g. file exists); its reply says why
                        agent_gone = True
        send(struct.pack(">I", 0))
        if not agent_gone:
            proc.write_eof()
    except BaseException as e:
        await proc.close()  # EOF without the end frame: the agent removes its temp file
        if isinstance(e, HTTPException):
            await _audit(request, user, "files.upload", server_id, dest, ok=False, detail=str(e.detail)[:300])
        raise
    _, out, err = await proc.wait()
    try:
        res = json.loads(out)
    except ValueError:
        detail = (err or out or "no output").strip()[:500]
        await _audit(request, user, "files.upload", server_id, dest, ok=False, detail=detail[:300])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"File agent failed: {detail}")
    if not res.get("ok"):
        error = res.get("error", "Upload failed")
        await _audit(request, user, "files.upload", server_id, dest, ok=False, detail=error[:300])
        status_code = status.HTTP_409_CONFLICT if res.get("code") == "exists" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=error)
    await _audit(request, user, "files.upload", server_id, dest, detail=f"{received} bytes")
    return res["result"]
