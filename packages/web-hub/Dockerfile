# ============================================================
#  Antigravity Web - Dockerfile
#  Multi-service container for all 5 Python services
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
LABEL description="Antigravity Web - AI Chat Bridge Platform"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ANTIGRAVITY_HUB_VERSION=${APP_VERSION}
ENV ANTIGRAVITY_HUB_BUILD_SHA=${VCS_REF}

# Working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Copy application files. The root scripts are thin launchers; the runtime
# implementation, browser UI, and two files served by HTTP live below them.
COPY api_bridge.py proxy_server.py session_manager.py auto_healer.py watchdog_monitor.py ./
COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY --from=frontend-build /build/dashboard/react/ ./dashboard/react/
COPY docs/api.html docs/antigravity-control-plane.md ./docs/
COPY config.example.json ./config.json
COPY start.sh ./start.sh
RUN mkdir -p /app/deployment
COPY Dockerfile docker-compose.yml requirements.lock.txt ./deployment/
COPY frontend/package-lock.json ./deployment/package-lock.json
RUN chmod +x start.sh

# The repository never contains a secret-bearing config.json. The example is a
# safe boot default and can be replaced by a read-only Compose bind mount.
ENV ANTIGRAVITY_HUB_CONFIG=/app/config.json

# Create log directory and non-root user
RUN useradd --create-home --shell /bin/bash antigravity \
    && mkdir -p /app/data /app/logs /home/antigravity/Projects \
    && chown -R antigravity:antigravity /app /home/antigravity/Projects

USER antigravity

# Expose all service ports
EXPOSE 8000 8001 8002 8007 8010

# Health check all five processes started by start.sh.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; [urllib.request.urlopen(url, timeout=2).read() for url in ('http://127.0.0.1:8000/health', 'http://127.0.0.1:8001/health', 'http://127.0.0.1:8002/health', 'http://127.0.0.1:8007/health', 'http://127.0.0.1:8010/health')]"

# Start all services
CMD ["./start.sh", "all"]
