import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status
from app.websockets.hub import ws_hub
from app.services.local_collector import local_collector
from app.models.metrics import SystemMetricsPayload
from app.core.config import is_direct_local
from app.core import policy
from app.core.security import AuthRequired, authenticate_websocket, resolve_session, session_token

logger = logging.getLogger("metrics_ws")
router = APIRouter(tags=["Metrics"])

# How often an open stream re-checks the login session that opened it
SESSION_RECHECK_SECONDS = 30

@router.get("/api/v1/metrics/{server_id}", response_model=SystemMetricsPayload, dependencies=[AuthRequired])
async def get_metrics_snapshot(server_id: str):
    if is_direct_local(server_id):
        return local_collector.collect("local")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Snapshot via REST for remote servers is stream-only via WebSocket."
    )

@router.websocket("/ws/metrics")
async def metrics_websocket_endpoint(websocket: WebSocket):
    role = policy.WEBSOCKET_ROLES["/ws/metrics"]
    if not await authenticate_websocket(websocket, role):
        return
    token = session_token(websocket)

    async def watch_session():
        # The stream must not outlive its session (logout, disabled account, demotion, expiry). Watching
        # graphs is not activity (touch=False), so an untouched dashboard still idles out.
        while True:
            await asyncio.sleep(SESSION_RECHECK_SECONDS)
            resolved = await resolve_session(token, touch=False)
            if not resolved or resolved[0].mfa_setup_required or not policy.has_role(resolved[0].role, role):
                await ws_hub.disconnect_metrics(websocket)
                await websocket.close(code=4401)
                return

    await ws_hub.connect_metrics(websocket)
    watcher = asyncio.create_task(watch_session())
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            server_id = data.get("server_id", "local")
            if action == "subscribe":
                await ws_hub.subscribe(websocket, server_id)
            elif action == "unsubscribe":
                await ws_hub.disconnect_metrics(websocket)
    except WebSocketDisconnect:
        await ws_hub.disconnect_metrics(websocket)
    except Exception as e:
        logger.warning(f"WebSocket client error: {e}")
        await ws_hub.disconnect_metrics(websocket)
    finally:
        watcher.cancel()
