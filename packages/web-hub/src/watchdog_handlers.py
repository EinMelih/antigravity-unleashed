import time
import platform
from datetime import datetime, timezone
from aiohttp import web
from typing import Any

from src.config import config
from src.local_admin_security import local_cors_response
from src.watchdog_db import UptimeDB
from src.watchdog_engine import HealthCheckEngine, TelegramAlerter


@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Allow the local dashboard while rejecting cross-site admin requests."""
    return await local_cors_response(
        request,
        handler,
        methods="GET, POST, OPTIONS",
    )


# ============================================================
# API-Endpoints
# ============================================================

async def handle_health(request: web.Request) -> web.Response:
    """GET /health — Watchdog self-health check."""
    try:
        engine: HealthCheckEngine = request.app["engine"]
        uptime_secs = int(time.monotonic() - engine._start_mono)

        # Platform-independent memory check
        memory_mb = 0.0
        try:
            if platform.system() != 'Windows':
                import resource
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if platform.system() == 'Darwin':
                    memory_mb = round(rss / (1024 * 1024), 1)
                else:
                    memory_mb = round(rss / 1024, 1)
            else:
                try:
                    import ctypes
                    import ctypes.wintypes
                    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                        _fields_ = [
                            ("cb", ctypes.wintypes.DWORD),
                            ("PageFaultCount", ctypes.wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t),
                        ]
                    psapi = ctypes.windll.psapi
                    pmc = PROCESS_MEMORY_COUNTERS()
                    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    handle = ctypes.windll.kernel32.GetCurrentProcess()
                    if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                        memory_mb = round(pmc.WorkingSetSize / (1024 * 1024), 1)
                except Exception:
                    pass
        except Exception:
            pass

        wd_cfg = config.watchdog
        telegram_enabled = bool(config.telegram_token and config.telegram_chat_id)

        return web.json_response({
            "status": "ok",
            "service": "watchdog_monitor",
            "version": "1.0",
            "uptime_seconds": uptime_secs,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "memory_usage_mb": memory_mb,
            "started_at": engine._started_at,
            "monitored_services": len(engine.states),
            "check_interval_seconds": wd_cfg.get("check_interval_seconds", 10),
            "telegram_enabled": telegram_enabled,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[ERROR] handle_health: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def handle_status_all(request: web.Request) -> web.Response:
    """GET /status — Aggregated health status of monitored services."""
    try:
        engine: HealthCheckEngine = request.app["engine"]
        services = {}
        overall = "ok"
        for name, state in engine.states.items():
            services[name] = state.to_dict()
            if state.status == "down":
                overall = "degraded"
            elif state.status == "degraded" and overall == "ok":
                overall = "warning"

        return web.json_response({
            "overall_status": overall,
            "services": services,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[ERROR] handle_status_all: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def handle_status_single(request: web.Request) -> web.Response:
    """GET /status/{service} — Health status of a single monitored service with history logs."""
    try:
        service_name = request.match_info["service"]
        engine: HealthCheckEngine = request.app["engine"]
        db: UptimeDB = request.app["db"]

        state = engine.states.get(service_name)
        if not state:
            return web.json_response(
                {"error": f"Service '{service_name}' nicht gefunden",
                 "available": list(engine.states.keys())},
                status=404,
            )

        history = db.get_checks_for_service(service_name, limit=50)
        return web.json_response({
            "service": state.to_dict(),
            "history": history,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[ERROR] handle_status_single: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def handle_uptime(request: web.Request) -> web.Response:
    """GET /uptime — Returns percent uptime for checked services (1h, 24h, 7d)."""
    try:
        engine: HealthCheckEngine = request.app["engine"]
        db: UptimeDB = request.app["db"]

        result = {}
        for name in engine.states:
            result[name] = {
                "1h": db.calc_uptime(name, 1),
                "24h": db.calc_uptime(name, 24),
                "7d": db.calc_uptime(name, 168),
            }

        return web.json_response({
            "uptime": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[ERROR] handle_uptime: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def handle_alert_test(request: web.Request) -> web.Response:
    """POST /alert/test — Triggers Telegram test alert warning."""
    try:
        alerter: TelegramAlerter = request.app["alerter"]
        msg = (
            "🧪 <b>Test-Alert vom Watchdog Monitor</b>\n\n"
            "Dies ist eine Testnachricht.\n"
            f"Zeitpunkt: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        success = await alerter.send(msg, level="TEST", service="watchdog")
        telegram_enabled = bool(config.telegram_token and config.telegram_chat_id)

        return web.json_response({
            "sent": success,
            "telegram_enabled": telegram_enabled,
            "message": "Testnachricht gesendet" if success else "Telegram nicht konfiguriert oder Sendefehler",
        })
    except Exception as e:
        print(f"[ERROR] handle_alert_test: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def handle_alerts(request: web.Request) -> web.Response:
    """GET /alerts — List alerts history (up to last 50)."""
    try:
        db: UptimeDB = request.app["db"]
        alerts = db.get_recent_alerts(limit=50)
        return web.json_response({
            "alerts": alerts,
            "count": len(alerts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"[ERROR] handle_alerts: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)
