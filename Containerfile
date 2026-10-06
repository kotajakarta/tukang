# ---- Stage 1: build the React frontend ----
FROM docker.io/library/node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: FastAPI backend that also serves the built UI ----
FROM docker.io/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist \
    LOCAL_MODE=ssh \
    COOKIE_SECURE=true \
    TRUST_PROXY_HEADERS=true \
    MFA_REQUIRED=true \
    ENABLE_API_DOCS=false

WORKDIR /app
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock
COPY backend/app backend/app
COPY --from=frontend /src/frontend/dist frontend/dist
# The image is a distribution: it must carry tuKang's license and the third-party notices
COPY LICENSE THIRD_PARTY_NOTICES.md ./

RUN useradd --system --uid 1000 --create-home tukang \
    && mkdir -p /data && chown tukang:tukang /data
USER tukang

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# No --forwarded-allow-ips "*": uvicorn would then take the client address from X-Forwarded-For sent by
# anyone. The app reads the client IP itself, from TRUSTED_PROXIES only (see TRUST_PROXY_HEADERS).
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
