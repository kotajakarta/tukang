from typing import Optional
from urllib.parse import urlsplit
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# 'unsafe-inline' for styles is required by Ant Design's CSS-in-JS
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

def origin_allowed(headers: Headers) -> bool:
    """
    True if the request's Origin is this site (or explicitly trusted). Requests without an Origin
    header are allowed: browsers always send it on cross-origin and WebSocket requests, so a
    missing Origin means a same-origin navigation or a non-browser client.
    """
    origin: Optional[str] = headers.get("origin")
    if not origin:
        return True
    if origin in settings.TRUSTED_ORIGINS:
        return True
    origin_host = urlsplit(origin).netloc.lower()
    hosts = {headers.get("host", "").lower(), headers.get("x-forwarded-host", "").lower()}
    return bool(origin_host) and origin_host in hosts

class SecurityMiddleware:
    """
    - Rejects cross-origin state-changing HTTP requests and WebSocket handshakes (CSRF / CSWSH).
    - Adds security headers to every HTTP response.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        if scope["type"] == "websocket":
            if not origin_allowed(headers):
                # Reject the handshake before the app accepts it (browser sees a failed connection)
                await send({"type": "websocket.close", "code": 4403})
                return
            return await self.app(scope, receive, send)

        if scope["method"] not in SAFE_METHODS and not origin_allowed(headers):
            response = JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
            return await response(scope, receive, send)

        path: str = scope["path"]
        is_docs = path.startswith(("/docs", "/redoc"))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if not is_docs:  # Swagger UI loads its assets from a CDN
                    extra.append((b"content-security-policy", CONTENT_SECURITY_POLICY.encode()))
                if settings.COOKIE_SECURE:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if path.startswith("/api/"):
                    extra.append((b"cache-control", b"no-store"))
                message.setdefault("headers", [])
                # A route may set its own (e.g. the files viewer allows same-origin framing for PDFs)
                present = {k.lower() for k, _ in message["headers"]}
                message["headers"] = list(message["headers"]) + [(k, v) for k, v in extra if k not in present]
            await send(message)

        return await self.app(scope, receive, send_with_headers)

class AuditMiddleware:
    """Records every state-changing API call (who, what, which server, result) to the audit log."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or not scope["path"].startswith("/api/")
            # These endpoints write richer audit entries themselves
            or scope["path"].startswith(("/api/v1/auth/", "/api/v1/app-users", "/api/v1/files/"))
        ):
            return await self.app(scope, receive, send)

        status_holder = {"code": 500}

        async def capture(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            from app.core.security import client_ip
            from app.services import audit_service
            from starlette.requests import Request

            request = Request(scope)
            user = scope.get("state", {}).get("user")
            route = scope.get("route")
            params = dict(scope.get("path_params") or {})
            server_id = params.pop("server_id", None)
            code = status_holder["code"]
            template = getattr(route, "path", None) or scope["path"]
            if not template.startswith("/api/"):
                template = settings.API_V1_STR + template  # route path is relative to the router prefix
            if code != 401:  # unauthenticated noise is not an action
                await audit_service.record(
                    action=f"{scope['method']} {template}",
                    username=getattr(user, "username", None),
                    ip=client_ip(request),
                    server_id=server_id,
                    target=" ".join(f"{k}={v}" for k, v in params.items()) or scope.get("query_string", b"").decode()[:512] or None,
                    success=200 <= code < 400,
                    detail=f"HTTP {code}",
                )
