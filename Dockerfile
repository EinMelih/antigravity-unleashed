# ============================================================
#  Anti-Gravity Unleashed — Headless Linux API + API-Logs UI
#  Pure Python 3.12-slim + Direct ConnectRPC (No Electron/Xvfb)
# ============================================================
FROM python:3.12-slim

ARG APP_VERSION=2.1.0-headless
ARG VCS_REF=headless-linux

LABEL org.opencontainers.image.title="Anti-Gravity Headless API & Logs" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANTIGRAVITY_DOCKER=1 \
    ANTIGRAVITY_HEADLESS_UI=1 \
    ANTIGRAVITY_API_MODE=rpc \
    ANTIGRAVITY_STANDALONE_RPC=1 \
    ANTIGRAVITY_API_HOST=0.0.0.0 \
    ANTIGRAVITY_HUB_HOST=0.0.0.0 \
    ANTIGRAVITY_API_HOME=/data/antigravity-api/home \
    ANTIGRAVITY_HUB_DB=/data/antigravity-api/dashboard.db \
    ANTIGRAVITY_AUDIT_LOG_DIR=/data/antigravity-api/audit_logs \
    ANTIGRAVITY_LANGUAGE_SERVER_BIN=/data/antigravity-api/bin/language_server_linux_x64

RUN apt-get update \
    && apt-get install -y --no-install-recommends procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/web-hub/requirements.txt packages/web-hub/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY packages/web-hub/api_bridge.py packages/web-hub/proxy_server.py ./
COPY packages/web-hub/config.example.json ./config.example.json
COPY packages/web-hub/src/ ./src/
COPY packages/web-hub/dashboard/ ./dashboard/
COPY packages/web-hub/docs/ ./docs/
COPY packages/web-hub/scripts/ ./scripts/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data/antigravity-api

VOLUME ["/data/antigravity-api"]

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; [urllib.request.urlopen(u, timeout=2).read() for u in ('http://127.0.0.1:8000/health', 'http://127.0.0.1:8001/health')]"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
