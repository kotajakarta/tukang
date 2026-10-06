import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
from app.core.security import AuthRequired
from app.core.middleware import AuditMiddleware, SecurityMiddleware
from app.api.v1.audit import router as audit_router
from app.api.v1.app_users import router as app_users_router
from app.api.v1.files import router as files_router
from app.api.v1.file_remotes import router as file_remotes_router
from app.services import audit_service
from app.api.v1.auth import router as auth_router
from app.api.v1.servers import router as servers_router
from app.api.v1.services import router as services_router
from app.api.v1.containers import router as containers_router
from app.api.v1.storage import router as storage_router
from app.api.v1.network import router as network_router
from app.api.v1.users import router as users_router
from app.websockets.metrics_ws import router as metrics_router
from app.websockets.terminal_ws import router as terminal_router
from app.websockets.hub import ws_hub
from app.services.ssh_manager import ssh_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tukang_backend")
# asyncssh logs every executed command line at INFO (incl. the whole file-agent source); keep only problems
logging.getLogger("asyncssh").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing tuKang Master Controller...")
    if settings.TRUST_PROXY_HEADERS and not settings.TRUSTED_PROXIES:
        logger.warning("TRUST_PROXY_HEADERS without TRUSTED_PROXIES: any peer that reaches this app directly can "
                       "choose its client IP (rate limits, audit). Set TRUSTED_PROXIES to the proxy's address/name.")
    await init_db()
    await audit_service.prune()
    await ws_hub.start()
    yield
    logger.info("Shutting down tuKang Master Controller...")
    await ws_hub.stop()
    await ssh_manager.close_all()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Agentless Multi-Server Linux Administration Platform",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
app.add_middleware(AuditMiddleware)
app.add_middleware(SecurityMiddleware)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "tukang-controller", "version": "1.0.0"}

# API Routers (everything except /auth and /api/health requires a session)
app.include_router(auth_router, prefix=settings.API_V1_STR)
# file_remotes before files: its fixed /files/remotes... paths must win over /files/{server_id}/...
for protected_router in (audit_router, app_users_router, file_remotes_router, files_router, servers_router, services_router, containers_router, storage_router, network_router, users_router):
    app.include_router(protected_router, prefix=settings.API_V1_STR, dependencies=[AuthRequired])
# WebSocket routes authenticate the handshake themselves (see authenticate_websocket)
app.include_router(metrics_router)
app.include_router(terminal_router)

# Serve the built React app (production / container). In dev, Vite serves it on :3000.
if settings.FRONTEND_DIST.is_dir():
    dist_dir = settings.FRONTEND_DIST.resolve()
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (dist_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist_dir):
            return FileResponse(candidate)
        # index.html must be revalidated so a redeploy's new hashed bundles are picked up immediately
        return FileResponse(dist_dir / "index.html", headers={"Cache-Control": "no-cache"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
