import asyncio
import logging
import time
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.terminal_service import TerminalSession, normalize_cwd
from app.core.security import authenticate_websocket, client_ip, resolve_session, session_token
from app.services import audit_service
from app.core import policy

logger = logging.getLogger("terminal_ws")
router = APIRouter(tags=["Terminal"])

@router.websocket("/ws/terminal/{server_id}")
async def terminal_websocket_endpoint(
    websocket: WebSocket,
    server_id: str,
    cols: int = Query(80, ge=10, le=500),
    rows: int = Query(24, ge=5, le=200),
    cwd: Optional[str] = Query(None, max_length=4096),
):
    user = await authenticate_websocket(websocket, policy.WEBSOCKET_ROLES["/ws/terminal"])
    if not user:
        return
    await websocket.accept()
    ip = client_ip(websocket)
    token = session_token(websocket)
    logger.info(f"Terminal connection opened by '{user.username}' for server: {server_id} ({cols}x{rows})")
    cwd = normalize_cwd(cwd)
    await audit_service.record("terminal.open", username=user.username, ip=ip, server_id=server_id, target=cwd)
    session = TerminalSession(server_id=server_id, ws=websocket, cols=cols, rows=rows, cwd=cwd)

    async def watch_session():
        # A shell outlives the HTTP request that opened it: kill it when the login session ends.
        # Typing counts as activity; an untouched open terminal does not keep the session alive.
        while True:
            await asyncio.sleep(30)
            active = time.monotonic() - session.last_input_at < 60
            resolved = await resolve_session(token, touch=active)
            # Also end the shell if the account was demoted below admin meanwhile
            if not resolved or not policy.has_role(resolved[0].role, policy.WEBSOCKET_ROLES["/ws/terminal"]):
                logger.info(f"Closing terminal of '{user.username}' on {server_id}: session ended")
                await websocket.close(code=4401)
                return

    watcher = asyncio.create_task(watch_session())
    try:
        await session.run()
    except WebSocketDisconnect:
        logger.info(f"Terminal client disconnected for server: {server_id}")
    except Exception as e:
        logger.error(f"Terminal error for server {server_id}: {e}")
    finally:
        watcher.cancel()
        await audit_service.record("terminal.close", username=user.username, ip=ip, server_id=server_id)
