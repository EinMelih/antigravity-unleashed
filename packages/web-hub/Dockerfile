# ============================================================
#  Antigravity Web - Dockerfile
#  Headless Linux Direct-ConnectRPC API (:8001) + API-Logs UI (:8000)
# ============================================================
FROM node:22-alpine AS frontend-build

WORKDIR /build

# Keep dependency installation cacheable and build the ignored React artifact
# from source instead of depending on a developer's local dashboard/react tree.
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN npm --prefix frontend run build

FROM python:3.12-slim

ARG APP_VERSION=0.1.0-dev
ARG VCS_REF=development

LABEL org.opencontainers.image.title="Anti-Gravity Hub" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"
LABEL description="Antigravity Web - Headless Linux AI API & API-Logs Server"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ANTIGRAVITY_HUB_VERSION=${APP_VERSION}
ENV ANTIGRAVITY_HUB_BUILD_SHA=${VCS_REF}

# Working directory
WORKDIR /app

# Install dependencies (includes psutil for Linux process discovery)
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Copy application files
COPY api_bridge.py proxy_server.py session_manager.py auto_healer.py watchdog_monitor.py ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY dashboard/ ./dashboard/
COPY --from=frontend-build /build/dashboard/react/ ./dashboard/react/
COPY docs/api.html docs/antigravity-control-plane.md ./docs/
COPY config.example.json ./config.json
COPY start.sh ./start.sh
RUN mkdir -p /app/deployment
COPY Dockerfile docker-compose.yml requirements.lock.txt ./deployment/
COPY frontend/package-lock.json ./deployment/package-lock.json
RUN chmod +x start.sh

# Isolated Headless Linux / Docker defaults
ENV ANTIGRAVITY_HUB_CONFIG=/app/config.json
ENV ANTIGRAVITY_DOCKER=1
ENV ANTIGRAVITY_HEADLESS_UI=1
ENV ANTIGRAVITY_API_MODE=rpc
ENV ANTIGRAVITY_STANDALONE_RPC=1
ENV ANTIGRAVITY_API_HOME=/data/antigravity-api/home
ENV ANTIGRAVITY_AUDIT_LOG_DIR=/data/antigravity-api/audit_logs
ENV ANTIGRAVITY_LANGUAGE_SERVER_BIN=/opt/antigravity/bin/language_server_linux_x64

# Create isolated API data directory, log directory, and non-root user
RUN useradd --create-home --shell /bin/bash antigravity \
    && mkdir -p /app/data /app/logs /home/antigravity/Projects /data/antigravity-api /opt/antigravity/bin \
    && chown -R antigravity:antigravity /app /home/antigravity/Projects /data/antigravity-api /opt/antigravity

USER antigravity

# Expose API-Logs Web UI (8000) and Headless OpenAI API Bridge (8001)
EXPOSE 8000 8001 8002 8007 8010

# Health check core API + Hub endpoints
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; [urllib.request.urlopen(url, timeout=2).read() for url in ('http://127.0.0.1:8000/health', 'http://127.0.0.1:8001/health')]"

# Start headless API + API-Logs UI in Docker
CMD ["./start.sh", "headless"]
