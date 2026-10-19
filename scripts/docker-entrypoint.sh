#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${ANTIGRAVITY_DATA_ROOT:-/data/antigravity-api}"
export ANTIGRAVITY_DOCKER=1
export ANTIGRAVITY_HEADLESS_UI=1
export ANTIGRAVITY_API_MODE="${ANTIGRAVITY_API_MODE:-rpc}"
export ANTIGRAVITY_STANDALONE_RPC=1
export ANTIGRAVITY_API_HOST="${ANTIGRAVITY_API_HOST:-0.0.0.0}"
export ANTIGRAVITY_HUB_HOST="${ANTIGRAVITY_HUB_HOST:-0.0.0.0}"
export ANTIGRAVITY_API_HOME="${ANTIGRAVITY_API_HOME:-${DATA_ROOT}/home}"
export ANTIGRAVITY_HUB_DB="${ANTIGRAVITY_HUB_DB:-${DATA_ROOT}/dashboard.db}"
export ANTIGRAVITY_AUDIT_LOG_DIR="${ANTIGRAVITY_AUDIT_LOG_DIR:-${DATA_ROOT}/audit_logs}"
export ANTIGRAVITY_HUB_CONFIG="${ANTIGRAVITY_HUB_CONFIG:-${DATA_ROOT}/config.json}"

mkdir -p \
  "${ANTIGRAVITY_API_HOME}/workspaces" \
  "${ANTIGRAVITY_API_HOME}/workspace" \
  "${ANTIGRAVITY_API_HOME}/.gemini/config" \
  "${ANTIGRAVITY_API_HOME}/.gemini/antigravity-api/scratch" \
  "${ANTIGRAVITY_API_HOME}/.config/Antigravity-api" \
  "${ANTIGRAVITY_AUDIT_LOG_DIR}" \
  "${DATA_ROOT}/bin" \
  "${DATA_ROOT}/logs"

if [ ! -f "${ANTIGRAVITY_HUB_CONFIG}" ] && [ -f "/app/config.example.json" ]; then
  cp /app/config.example.json "${ANTIGRAVITY_HUB_CONFIG}"
fi

if [ -n "${ANTIGRAVITY_LANGUAGE_SERVER_BIN:-}" ] && [ -f "${ANTIGRAVITY_LANGUAGE_SERVER_BIN}" ]; then
  chmod +x "${ANTIGRAVITY_LANGUAGE_SERVER_BIN}" || true
fi

echo "============================================================"
echo "  Anti-Gravity Headless Linux Runtime (Direct ConnectRPC)"
echo "  API Bridge:   http://0.0.0.0:8001 (/v1/chat/completions)"
echo "  API-Logs UI:  http://0.0.0.0:8000/dashboard/react/index.html#/api-logs"
echo "  API Home:     ${ANTIGRAVITY_API_HOME}"
echo "============================================================"

python3 -u /app/api_bridge.py &
API_PID=$!

python3 -u /app/proxy_server.py &
UI_PID=$!

cleanup() {
  kill -TERM "${API_PID}" "${UI_PID}" 2>/dev/null || true
  wait "${API_PID}" "${UI_PID}" 2>/dev/null || true
}
trap cleanup SIGINT SIGTERM

wait -n "${API_PID}" "${UI_PID}"
EXIT_CODE=$?
cleanup
exit "${EXIT_CODE}"
