import asyncio
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.server import ServerModel
from app.services.local_collector import local_collector
from app.services.remote_collector import remote_collector
from app.services.ssh_manager import ServerConnectionInfo
from app.core.config import is_direct_local

logger = logging.getLogger("websocket_hub")

class WebSocketHub:
    def __init__(self):
        # ws -> current subscribed server_id
        self._client_subscriptions: Dict[WebSocket, str] = {}
        # server_id -> set of subscribed WebSockets
        self._server_subscribers: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._harvest_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        if self._harvest_task is None or self._harvest_task.done():
            self._harvest_task = asyncio.create_task(self._harvester_loop())
            logger.info("Metrics harvester loop started.")

    async def stop(self):
        self._running = False
        if self._harvest_task and not self._harvest_task.done():
            self._harvest_task.cancel()
            try:
                await self._harvest_task
            except asyncio.CancelledError:
                pass
        logger.info("Metrics harvester loop stopped.")

    async def connect_metrics(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            # Default subscribe to local
            self._client_subscriptions[ws] = "local"
            if "local" not in self._server_subscribers:
                self._server_subscribers["local"] = set()
            self._server_subscribers["local"].add(ws)
        
        # Send initial immediate snapshot
        if is_direct_local("local"):
            initial_payload = local_collector.collect("local")
            await ws.send_json(initial_payload.model_dump())

    async def subscribe(self, ws: WebSocket, server_id: str):
        async with self._lock:
            old_server = self._client_subscriptions.get(ws)
            if old_server and old_server in self._server_subscribers:
                self._server_subscribers[old_server].discard(ws)
                if not self._server_subscribers[old_server]:
                    del self._server_subscribers[old_server]

            self._client_subscriptions[ws] = server_id
            if server_id not in self._server_subscribers:
                self._server_subscribers[server_id] = set()
            self._server_subscribers[server_id].add(ws)

        # Trigger immediate snapshot if local
        if is_direct_local(server_id):
            try:
                payload = local_collector.collect("local")
                await ws.send_json(payload.model_dump())
            except Exception:
                pass

    async def disconnect_metrics(self, ws: WebSocket):
        async with self._lock:
            server_id = self._client_subscriptions.pop(ws, None)
            if server_id and server_id in self._server_subscribers:
                self._server_subscribers[server_id].discard(ws)
                if not self._server_subscribers[server_id]:
                    del self._server_subscribers[server_id]

    async def _harvester_loop(self):
        while self._running:
            try:
                active_servers = list(self._server_subscribers.keys())
                if active_servers:
                    tasks = [self._harvest_and_broadcast(sid) for sid in active_servers]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error in harvester loop: {e}")

            await asyncio.sleep(1.0)

    async def _harvest_and_broadcast(self, server_id: str):
        subscribers = list(self._server_subscribers.get(server_id, []))
        if not subscribers:
            return

        payload = None
        if is_direct_local(server_id):
            payload = local_collector.collect("local")
        else:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(ServerModel).where(ServerModel.id == server_id))
                server = res.scalar_one_or_none()
                if server:
                    info = ServerConnectionInfo.from_server(server)
                    payload = await remote_collector.collect(info)

        if payload:
            msg = payload.model_dump()
            dead_clients = []
            for ws in subscribers:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead_clients.append(ws)

            for ws in dead_clients:
                await self.disconnect_metrics(ws)

ws_hub = WebSocketHub()
