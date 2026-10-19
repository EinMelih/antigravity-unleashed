#!/bin/bash
# ============================================================
#  Anti-Gravity Hub - Linux Startup Script
#  Equivalent to start.bat for Linux/Proxmox deployments
# ============================================================

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# -- Script directory (resolve symlinks) --
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.antigravity.pids"
LOG_DIR="${SCRIPT_DIR}/logs"
CONFIG_FILE="${ANTIGRAVITY_HUB_CONFIG:-${SCRIPT_DIR}/config.json}"
export ANTIGRAVITY_HUB_CONFIG="${CONFIG_FILE}"
HEALTH_TIMEOUT_SECONDS="${ANTIGRAVITY_HEALTH_TIMEOUT_SECONDS:-30}"
SERVICE_PIDS=()
SERVICE_NAMES=()
SERVICE_HEALTH_URLS=()

if [[ ! "${HEALTH_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ANTIGRAVITY_HEALTH_TIMEOUT_SECONDS must be a positive integer." >&2
    exit 1
fi

# -- Detect Python --
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo -e "${RED}[FEHLER] Weder python3 noch python gefunden!${NC}"
    echo "Bitte Python 3.10+ installieren."
    exit 1
fi

PYTHON_EXECUTABLE="$(readlink -f "$(command -v "${PYTHON}")")"

echo -e "${CYAN}Python: ${PYTHON} ($(${PYTHON} --version 2>&1))${NC}"

# -- Check aiohttp --
if ! ${PYTHON} -c "import aiohttp" 2>/dev/null; then
    echo -e "${RED}[FEHLER] aiohttp ist nicht installiert!${NC}"
    echo -e "${YELLOW}  Bitte installieren: ${PYTHON} -m pip install aiohttp>=3.9${NC}"
    exit 1
fi

# -- Ensure log directory --
mkdir -p "${LOG_DIR}"

# -- Ensure the selected external config exists --
if [ ! -f "${CONFIG_FILE}" ]; then
    echo -e "${YELLOW}[CONFIG] ${CONFIG_FILE} nicht gefunden. Erstelle sie aus config.example.json...${NC}"
    if [ -f "${SCRIPT_DIR}/config.example.json" ]; then
        mkdir -p "$(dirname "${CONFIG_FILE}")"
        cp "${SCRIPT_DIR}/config.example.json" "${CONFIG_FILE}"
    else
        echo -e "${RED}[FEHLER] config.example.json nicht gefunden!${NC}"
        exit 1
    fi
fi

# -- Banner --
print_banner() {
    echo ""
    echo -e "${BOLD}  ================================================${NC}"
    echo -e "${BOLD}   Anti-Gravity Hub - Linux Startup${NC}"
    echo -e "${BOLD}  ================================================${NC}"
    echo ""
}

# -- Managed process ownership --
script_for_name() {
    case "$1" in
        proxy) echo "proxy_server.py" ;;
        api-bridge) echo "api_bridge.py" ;;
        session-manager) echo "session_manager.py" ;;
        auto-healer) echo "auto_healer.py" ;;
        watchdog) echo "watchdog_monitor.py" ;;
        *) return 1 ;;
    esac
}

is_owned_process() {
    local pid="$1"
    local name="$2"
    local script
    script="$(script_for_name "${name}")" || return 1
    local expected_path="${SCRIPT_DIR}/${script}"

    if ! kill -0 "${pid}" 2>/dev/null ||
       [ ! -r "/proc/${pid}/cmdline" ] ||
       [ ! -e "/proc/${pid}/exe" ]; then
        return 1
    fi

    local actual_executable
    actual_executable="$(readlink -f "/proc/${pid}/exe" 2>/dev/null)" || return 1
    if [ "${actual_executable}" != "${PYTHON_EXECUTABLE}" ]; then
        return 1
    fi

    local argument
    while IFS= read -r -d '' argument; do
        if [ "${argument}" = "${expected_path}" ]; then
            return 0
        fi
    done < "/proc/${pid}/cmdline"
    return 1
}

health_check() {
    local url="$1"
    "${PYTHON}" -c '
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=2.0) as response:
        raise SystemExit(0 if 200 <= response.status < 400 else 1)
except Exception:
    raise SystemExit(1)
' "${url}" >/dev/null 2>&1
}

wait_for_service_health() {
    local name="$1"
    local pid="$2"
    local url="$3"
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))

    while (( SECONDS < deadline )); do
        if ! is_owned_process "${pid}" "${name}"; then
            echo -e "  ${RED}✗ ${name} exited before becoming healthy.${NC}"
            return 1
        fi
        if health_check "${url}"; then
            return 0
        fi
        sleep 0.5
    done

    echo -e "  ${RED}✗ ${name} health check timed out: ${url}${NC}"
    return 1
}

wait_for_managed_set_health() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))

    while (( SECONDS < deadline )); do
        local all_healthy=1
        local index
        for index in "${!SERVICE_PIDS[@]}"; do
            if ! is_owned_process "${SERVICE_PIDS[$index]}" "${SERVICE_NAMES[$index]}"; then
                echo -e "  ${RED}✗ ${SERVICE_NAMES[$index]} exited during final health verification.${NC}"
                return 1
            fi
            if ! health_check "${SERVICE_HEALTH_URLS[$index]}"; then
                all_healthy=0
            fi
        done
        if [ "${all_healthy}" -eq 1 ]; then
            return 0
        fi
        sleep 0.5
    done

    echo -e "  ${RED}✗ Managed service set failed final health verification.${NC}"
    return 1
}

# -- Start a single service --
# Usage: start_service "name" "script.py" port health_path
start_service() {
    local name="$1"
    local script="$2"
    local port="$3"
    local health_path="$4"
    local log_file="${LOG_DIR}/${name}.log"
    local health_url="http://127.0.0.1:${port}${health_path}"

    if [ ! -f "${SCRIPT_DIR}/${script}" ]; then
        echo -e "  ${RED}✗ ${name}: ${script} nicht gefunden!${NC}"
        return 1
    fi

    "${PYTHON}" "${SCRIPT_DIR}/${script}" >> "${log_file}" 2>&1 &
    local pid=$!
    SERVICE_PIDS+=("${pid}")
    SERVICE_NAMES+=("${name}")
    SERVICE_HEALTH_URLS+=("${health_url}")
    echo "${pid}:${name}" >> "${PID_FILE}"

    sleep 0.2
    if ! is_owned_process "${pid}" "${name}"; then
        echo -e "  ${RED}✗ ${name} konnte nicht sicher gestartet werden!${NC}"
        echo -e "    Log: ${log_file}"
        return 1
    fi

    if ! wait_for_service_health "${name}" "${pid}" "${health_url}"; then
        echo -e "    Log: ${log_file}"
        return 1
    fi

    echo -e "  ${GREEN}✓ ${name} gesund${NC} (PID ${pid}, Port ${port})"
}

# -- Stop all services --
stop_services() {
    echo ""
    echo -e "${YELLOW}Stoppe alle Anti-Gravity-Services...${NC}"

    if [ ! -f "${PID_FILE}" ]; then
        echo -e "${YELLOW}Keine PID-Datei gefunden (${PID_FILE})${NC}"
        return 0
    fi

    local count=0
    local ownership_error=0
    local owned_pids=()
    local owned_names=()
    while IFS=: read -r pid name; do
        if [ -z "${pid}" ]; then
            continue
        fi
        if ! [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || ! script_for_name "${name}" >/dev/null; then
            echo -e "  ${RED}Ungültiger PID-Datei-Eintrag: ${pid}:${name}${NC}"
            ownership_error=1
        elif is_owned_process "${pid}" "${name}"; then
            owned_pids+=("${pid}")
            owned_names+=("${name}")
            kill -TERM "${pid}" 2>/dev/null || true
            count=$((count + 1))
        elif kill -0 "${pid}" 2>/dev/null; then
            echo -e "  ${RED}PID ${pid} gehört nicht zu ${SCRIPT_DIR}; nicht beendet.${NC}"
            ownership_error=1
        else
            echo -e "  ${YELLOW}○ ${name} war bereits beendet${NC} (PID ${pid})"
        fi
    done < "${PID_FILE}"

    local deadline=$((SECONDS + 5))
    local process_alive=1
    while (( SECONDS < deadline )); do
        process_alive=0
        local index
        for index in "${!owned_pids[@]}"; do
            if is_owned_process "${owned_pids[$index]}" "${owned_names[$index]}"; then
                process_alive=1
                break
            fi
        done
        if [ "${process_alive}" -eq 0 ]; then
            break
        fi
        sleep 0.2
    done

    local index
    for index in "${!owned_pids[@]}"; do
        local owned_pid="${owned_pids[$index]}"
        local owned_name="${owned_names[$index]}"
        if is_owned_process "${owned_pid}" "${owned_name}"; then
            echo -e "  ${YELLOW}${owned_name} reagiert nicht auf SIGTERM; sende SIGKILL.${NC}"
            kill -KILL "${owned_pid}" 2>/dev/null || true
        fi
        wait "${owned_pid}" 2>/dev/null || true
        echo -e "  ${RED}■ ${owned_name} gestoppt${NC} (PID ${owned_pid})"
    done

    rm -f "${PID_FILE}"
    SERVICE_PIDS=()
    SERVICE_NAMES=()
    SERVICE_HEALTH_URLS=()
    echo ""
    echo -e "${GREEN}${count} Service(s) gestoppt.${NC}"
    return "${ownership_error}"
}

# -- Trap: cleanup on Ctrl+C or SIGTERM --
cleanup() {
    echo ""
    echo -e "${YELLOW}Signal empfangen, stoppe Services...${NC}"
    trap - SIGINT SIGTERM
    stop_services || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# -- Start modes --
start_all() {
    print_banner

    if [ -f "${PID_FILE}" ] && ! stop_services; then
        echo -e "${RED}Vorhandene PID-Datei enthält fremde Prozesse; Start abgebrochen.${NC}"
        return 1
    fi
    : > "${PID_FILE}"
    SERVICE_PIDS=()
    SERVICE_NAMES=()
    SERVICE_HEALTH_URLS=()

    echo -e "${BOLD}Starte alle Services...${NC}"
    echo ""

    if ! start_service "proxy" "proxy_server.py" 8000 "/health" ||
       ! start_service "api-bridge" "api_bridge.py" 8001 "/health" ||
       ! start_service "session-manager" "session_manager.py" 8002 "/health" ||
       ! start_service "auto-healer" "auto_healer.py" 8007 "/health" ||
       ! start_service "watchdog" "watchdog_monitor.py" 8010 "/health"; then
        echo -e "${RED}Mindestens ein Service wurde nicht gesund; räume gestartete Prozesse auf.${NC}"
        stop_services || true
        return 1
    fi
    if ! wait_for_managed_set_health; then
        stop_services || true
        return 1
    fi

    echo ""
    echo -e "${BOLD}  ================================================${NC}"
    echo -e "${GREEN}   Alle Services gestartet!${NC}"
    echo -e "${BOLD}  ================================================${NC}"
    echo ""
    echo -e "  Proxy:           http://127.0.0.1:8000"
    echo -e "  API Bridge:      http://127.0.0.1:8001"
    echo -e "  Session Manager: http://127.0.0.1:8002"
    echo -e "  Auto-Healer:     http://127.0.0.1:8007"
    echo -e "  Watchdog:        http://127.0.0.1:8010"
    echo ""
    echo -e "  ${CYAN}Health Checks:${NC}"
    echo -e "    curl http://127.0.0.1:8000/health"
    echo -e "    curl http://127.0.0.1:8001/health"
    echo -e "    curl http://127.0.0.1:8002/health"
    echo -e "    curl http://127.0.0.1:8007/health"
    echo -e "    curl http://127.0.0.1:8010/health"
    echo ""
    echo -e "  PID-Datei: ${PID_FILE}"
    echo -e "  Stoppen:   ${BOLD}$0 stop${NC}"
    echo ""
}

start_agents() {
    print_banner

    if [ -f "${PID_FILE}" ] && ! stop_services; then
        echo -e "${RED}Vorhandene PID-Datei enthält fremde Prozesse; Start abgebrochen.${NC}"
        return 1
    fi
    : > "${PID_FILE}"
    SERVICE_PIDS=()
    SERVICE_NAMES=()
    SERVICE_HEALTH_URLS=()

    echo -e "${BOLD}Starte nur Agent-Services (ohne Proxy/Bridge)...${NC}"
    echo ""

    if ! start_service "session-manager" "session_manager.py" 8002 "/health" ||
       ! start_service "auto-healer" "auto_healer.py" 8007 "/health" ||
       ! start_service "watchdog" "watchdog_monitor.py" 8010 "/health"; then
        echo -e "${RED}Mindestens ein Agent-Service wurde nicht gesund; räume gestartete Prozesse auf.${NC}"
        stop_services || true
        return 1
    fi
    if ! wait_for_managed_set_health; then
        stop_services || true
        return 1
    fi

    echo ""
    echo -e "${GREEN}Agent-Services gestartet!${NC}"
    echo -e "  Stoppen: ${BOLD}$0 stop${NC}"
    echo ""
}

start_headless() {
    print_banner

    if [ -f "${PID_FILE}" ] && ! stop_services; then
        echo -e "${RED}Vorhandene PID-Datei enthält fremde Prozesse; Start abgebrochen.${NC}"
        return 1
    fi
    : > "${PID_FILE}"
    SERVICE_PIDS=()
    SERVICE_NAMES=()
    SERVICE_HEALTH_URLS=()

    # Bootstrap isolated /data/antigravity-api directory, API Key & OAuth Token
    "${PYTHON}" - <<'PY'
import json
import os
import secrets
from pathlib import Path

data_root = Path(os.environ.get("ANTIGRAVITY_DATA_ROOT", "/data/antigravity-api"))
if os.environ.get("ANTIGRAVITY_DOCKER") == "1" or data_root.exists():
    try:
        home_dir = Path(os.environ.get("ANTIGRAVITY_API_HOME", str(data_root / "home")))
        for sub in (
            home_dir / ".gemini/config",
            home_dir / ".gemini/antigravity-api/conversations",
            home_dir / ".gemini/antigravity-api/scratch",
            home_dir / ".config/Antigravity-api/User/globalStorage",
            home_dir / "workspace",
            data_root / "audit_logs",
            data_root / "bin",
        ):
            sub.mkdir(parents=True, exist_ok=True)
        for idx in range(10):
            (home_dir / "workspaces" / f"ws-{idx:02d}" / "src").mkdir(parents=True, exist_ok=True)

        # Ensure persistent config.json with a strong API key (auth_token)
        runtime_cfg_path = data_root / "config.json"
        base_cfg_path = Path(os.environ.get("ANTIGRAVITY_HUB_CONFIG", "/app/config.json"))
        cfg = {}
        for candidate in (runtime_cfg_path, base_cfg_path):
            if candidate.is_file():
                try:
                    cfg = json.loads(candidate.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
        env_key = os.environ.get("ANTIGRAVITY_API_KEY", "").strip()
        api_key = env_key or str(cfg.get("auth_token") or "").strip()
        if not api_key:
            api_key = f"agk_{secrets.token_urlsafe(24)}"
        cfg["auth_token"] = api_key
        cfg["proxy_host"] = "0.0.0.0"
        cfg["api_bridge_host"] = "0.0.0.0"
        cfg.setdefault("api_engine", {})["mode"] = "rpc"
        runtime_cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (data_root / "api_key.txt").write_text(api_key + "\n", encoding="utf-8")

        # Seed OAuth token if provided via environment variable
        from src.api_profile import APIProfileRuntime
        rt = APIProfileRuntime()
        oauth_status = rt.get_oauth_status()
        print("================================================")
        print(f"  [API KEY]     {api_key}")
        print(f"  [KEY FILE]    {data_root / 'api_key.txt'}")
        print(f"  [GOOGLE AUTH] configured={oauth_status['configured']} auto_refresh={oauth_status['auto_refresh_enabled']}")
        print("================================================")
    except Exception as exc:
        print(f"[Headless Bootstrap Warning] {exc}")
PY

    if [ -f "/data/antigravity-api/config.json" ]; then
        export ANTIGRAVITY_HUB_CONFIG="/data/antigravity-api/config.json"
    fi

    echo -e "${BOLD}Starte Headless Linux Services (API-Logs UI :8000 + ConnectRPC API :8001)...${NC}"
    echo ""

    if ! start_service "proxy" "proxy_server.py" 8000 "/health" ||
       ! start_service "api-bridge" "api_bridge.py" 8001 "/health"; then
        echo -e "${RED}Mindestens ein Headless-Service wurde nicht gesund; räume gestartete Prozesse auf.${NC}"
        stop_services || true
        return 1
    fi
    if ! wait_for_managed_set_health; then
        stop_services || true
        return 1
    fi

    echo ""
    echo -e "${BOLD}  ================================================${NC}"
    echo -e "${GREEN}   Headless Linux API + API-Logs Server bereit!${NC}"
    echo -e "${BOLD}  ================================================${NC}"
    echo ""
    echo -e "  API-Logs UI:     http://0.0.0.0:8000/dashboard/react/index.html#/api-logs"
    echo -e "  OpenAI API:      http://0.0.0.0:8001/v1/chat/completions"
    echo -e "  Models API:      http://0.0.0.0:8001/v1/models"
    echo -e "  OAuth Token API: http://0.0.0.0:8001/v1/auth/token"
    echo ""
}

start_proxy() {
    print_banner
    echo -e "${BOLD}Starte nur Proxy Server...${NC}"
    echo ""
    exec "${PYTHON}" "${SCRIPT_DIR}/proxy_server.py"
}

start_api() {
    print_banner
    echo -e "${BOLD}Starte nur API Bridge...${NC}"
    echo ""
    exec "${PYTHON}" "${SCRIPT_DIR}/api_bridge.py"
}

# -- Supervise children and fail the container if one exits --
supervise_services() {
    if [ "${#SERVICE_PIDS[@]}" -eq 0 ]; then
        echo -e "${RED}Keine Services zum Überwachen vorhanden.${NC}"
        return 1
    fi

    echo -e "  ${CYAN}Supervisor aktiv; SIGINT/SIGTERM stoppt alle Services.${NC}"
    set +e
    wait -n "${SERVICE_PIDS[@]}"
    local child_status=$?
    set -e

    local exited_name="unknown"
    local index
    for index in "${!SERVICE_PIDS[@]}"; do
        if ! is_owned_process "${SERVICE_PIDS[$index]}" "${SERVICE_NAMES[$index]}"; then
            exited_name="${SERVICE_NAMES[$index]}"
            break
        fi
    done

    echo -e "${RED}Service ${exited_name} wurde unerwartet beendet (Status ${child_status}).${NC}"
    stop_services || true
    return 1
}

# -- Main --
MODE="${1:-all}"

case "${MODE}" in
    headless)
        start_headless
        supervise_services
        ;;
    all)
        start_all
        supervise_services
        ;;
    agents)
        start_agents
        supervise_services
        ;;
    proxy)
        start_proxy
        ;;
    api)
        start_api
        ;;
    stop)
        stop_services
        ;;
    status)
        echo ""
        echo -e "${BOLD}Anti-Gravity Service Status:${NC}"
        echo ""
        if [ ! -f "${PID_FILE}" ]; then
            echo -e "${YELLOW}Keine PID-Datei gefunden. Vermutlich laufen keine Services.${NC}"
            exit 0
        fi
        while IFS=: read -r pid name; do
            if [ -z "${pid}" ]; then continue; fi
            if is_owned_process "${pid}" "${name}"; then
                echo -e "  ${GREEN}● ${name}${NC} (PID ${pid}) — läuft"
            elif kill -0 "${pid}" 2>/dev/null; then
                echo -e "  ${RED}! ${name}${NC} (PID ${pid}) — fremder Prozess, nicht verwaltet"
            else
                echo -e "  ${RED}○ ${name}${NC} (PID ${pid}) — beendet"
            fi
        done < "${PID_FILE}"
        echo ""
        ;;
    *)
        echo ""
        echo -e "${BOLD}Anti-Gravity Hub - Startup Script${NC}"
        echo ""
        echo "Verwendung: $0 [MODUS]"
        echo ""
        echo "Modi:"
        echo "  headless - Headless Linux API (:8001) + API-Logs UI (:8000)"
        echo "  all      - Alle 5 Services starten (Standard)"
        echo "  agents   - Nur Agent-Services (Session, Healer, Watchdog)"
        echo "  proxy    - Nur Proxy Server (Vordergrund)"
        echo "  api      - Nur API Bridge (Vordergrund)"
        echo "  stop     - Alle Services stoppen"
        echo "  status   - Status aller Services anzeigen"
        echo ""
        exit 1
        ;;
esac

