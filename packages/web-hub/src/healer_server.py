import time
import platform
import asyncio
from aiohttp import web

from src.config import config
from src.local_admin_security import local_cors_response
from src.telegram import send_telegram
from src.healer_logic import (
    state,
    healing_history,
    now_iso,
    uptime_str,
    record_event,
    run_healing_cycle,
    close_http_session
)
from src.healer_monitor import monitor_loop


# ============================================================
# Middleware
# ============================================================
@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    """Allow the local dashboard while rejecting cross-site admin requests."""
    return await local_cors_response(
        request,
        handler,
        methods="GET, POST, DELETE, OPTIONS",
    )


# ============================================================
# API Handlers
# ============================================================
async def status_handler(request: web.Request) -> web.Response:
    """GET /status — Returns current healing state and system health metrics."""
    try:
        recent = list(healing_history)[-5:] if healing_history else []

        uptime_secs = int(time.time() - state["start_time"])
        maintenance_hint = None
        if uptime_secs > 86400:  # > 24h
            maintenance_hint = "Empfehlung: Geplanter Neustart in einem Wartungsfenster (Betriebszeit > 24h)"
        elif uptime_secs > 43200:  # > 12h
            maintenance_hint = "Hinweis: Betriebszeit > 12h — Wartungsfenster in Betracht ziehen"

        ah_cfg = config.auto_healer
        return web.json_response({
            "status": "healthy" if state["healthy"] else "unhealthy",
            "uptime": uptime_str(),
            "uptime_seconds": uptime_secs,
            "monitoring": {
                "check_interval_seconds": ah_cfg.get("check_interval_seconds", 15),
                "total_checks": state["total_checks"],
                "total_heals": len(healing_history),
                "total_recoveries": state["total_recoveries"],
                "consecutive_failures": state["consecutive_failures"],
                "max_healing_cycles": ah_cfg.get("max_healing_cycles", 3),
            },
            "system": {
                "api_bridge_healthy": state["api_bridge_healthy"],
                "cdp_connected": state["cdp_connected"],
                "bridge_injected": state["bridge_injected"],
                "process_running": state["process_running"],
            },
            "last_check": state["last_check"],
            "last_action": state["last_action"],
            "last_error": state["last_error"],
            "last_success": state["last_success"],
            "healing_in_progress": state["healing_in_progress"],
            "recent_events": recent,
            "maintenance_hint": maintenance_hint,
        })
    except Exception as e:
        print(f"[ERROR] status_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def heal_handler(request: web.Request) -> web.Response:
    """POST /heal — Manually trigger a healing cycle."""
    try:
        print("[HEALER] Manueller Heilungszyklus angefordert", flush=True)
        result = await run_healing_cycle(source="manuell")
        return web.json_response({
            "triggered": True,
            "timestamp": now_iso(),
            "result": result,
            "state": {
                "healthy": state["healthy"],
                "consecutive_failures": state["consecutive_failures"],
            },
        })
    except Exception as e:
        print(f"[ERROR] heal_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def history_handler(request: web.Request) -> web.Response:
    """GET /history — Returns the event log history (up to last 200 items)."""
    try:
        try:
            limit = min(int(request.query.get("limit", "200")), 200)
        except (ValueError, TypeError):
            limit = 200
        events = list(healing_history)[-limit:]
        events.reverse()

        total = len(healing_history)
        successes = sum(1 for e in healing_history if e["success"])
        failures = total - successes
        by_level = {}
        for e in healing_history:
            lvl = e["level"]
            by_level.setdefault(lvl, {"total": 0, "success": 0, "failure": 0})
            by_level[lvl]["total"] += 1
            if e["success"]:
                by_level[lvl]["success"] += 1
            else:
                by_level[lvl]["failure"] += 1

        return web.json_response({
            "count": len(events),
            "total_events": total,
            "statistics": {
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / total * 100, 1) if total else 0,
                "by_level": by_level,
            },
            "events": events,
        })
    except Exception as e:
        print(f"[ERROR] history_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def restart_handler(request: web.Request) -> web.Response:
    """POST /restart/{service} — Trigger warning and notify user via Telegram."""
    try:
        service = request.match_info.get("service", "unknown")
        print(f"[HEALER] Neustart angefordert für: {service}", flush=True)

        record_event(0, f"Neustart angefordert: {service}", True)

        msg = (
            f"🔧 [Antigravity Auto-Healer] 🔄 Neustart angefordert: <b>{service}</b>\n"
            f"Zeitpunkt: {now_iso()}\n"
            f"Hinweis: Automatischer Neustart ist noch nicht implementiert."
        )
        await send_telegram(msg, parse_mode="HTML")

        return web.json_response({
            "service": service,
            "timestamp": now_iso(),
            "action": "logged_and_alerted",
            "note": "Automatischer Neustart ist derzeit nicht implementiert. Bitte starte den Service manuell neu.",
        })
    except Exception as e:
        print(f"[ERROR] restart_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — Auto-Healer health report."""
    try:
        uptime_secs = int(time.time() - state["start_time"])

        # Platform-agnostic memory check
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

        ah_cfg = config.auto_healer
        monitor_task = request.app.get('monitor_task')

        return web.json_response({
            "status": "ok",
            "service": "auto_healer",
            "version": "1.0.0",
            "uptime_seconds": uptime_secs,
            "uptime": uptime_str(),
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "memory_usage_mb": memory_mb,
            "port": ah_cfg.get("port", 8007),
            "monitoring_active": monitor_task is not None and not monitor_task.done(),
            "check_interval_seconds": ah_cfg.get("check_interval_seconds", 15),
            "api_bridge_url": ah_cfg.get("api_bridge_url", "http://127.0.0.1:8001"),
            "telegram_configured": bool(config.telegram_token and config.telegram_chat_id),
            "endpoints": {
                "status": "GET  /status",
                "heal": "POST /heal",
                "history": "GET  /history",
                "restart": "POST /restart/{service}",
                "health": "GET  /health",
            },
        })
    except Exception as e:
        print(f"[ERROR] health_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


async def root_handler(request: web.Request) -> web.Response:
    try:
        return web.json_response({
            "service": "Antigravity Auto-Healer v1.0",
            "info": "Selbstheilender Wächter für das Antigravity-Ökosystem.",
            "quickstart": {
                "1_status": "GET  /status",
                "2_heal": "POST /heal",
                "3_history": "GET  /history",
                "4_health": "GET  /health",
            },
            "healing_levels": {
                "1": "Bridge Re-Inject (JS Bridge)",
                "2": "CDP Reconnect (WebSocket)",
                "3": "New Conversation (Chat-UI)",
                "4": "Process Monitor (antigravity.exe)",
                "5": "Telegram Alert (Benachrichtigung)",
            },
        })
    except Exception as e:
        print(f"[ERROR] root_handler: {e}", flush=True)
        return web.json_response({"error": str(e), "type": "internal_error"}, status=500)


# ============================================================
# App Lifecycle Hooks
# ============================================================
async def on_startup(app: web.Application) -> None:
    app['monitor_task'] = asyncio.create_task(monitor_loop())
    print("[STARTUP] Überwachungs-Task gestartet", flush=True)

    # Initial Telegram notification
    ah_cfg = config.auto_healer
    msg = (
        f"🔧 [Antigravity Auto-Healer] 🚀 Auto-Healer gestartet\n"
        f"Port: {ah_cfg.get('port', 8007)}\n"
        f"Check-Intervall: {ah_cfg.get('check_interval_seconds', 15)}s\n"
        f"Max Zyklen vor Alert: {ah_cfg.get('max_healing_cycles', 3)}\n"
        f"API Bridge: {ah_cfg.get('api_bridge_url', 'http://127.0.0.1:8001')}"
    )
    await send_telegram(msg)


async def on_shutdown(app: web.Application) -> None:
    print("[SHUTDOWN] Fahre herunter...", flush=True)
    monitor_task = app.get('monitor_task')
    if monitor_task and not monitor_task.done():
        monitor_task.cancel()
        try:
            await asyncio.wait_for(monitor_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            print(f"[SHUTDOWN] Fehler beim Stoppen des Monitor-Tasks: {e}", flush=True)

    try:
        await send_telegram(f"🔧 [Antigravity Auto-Healer] ⛔ Auto-Healer heruntergefahren (Betriebszeit: {uptime_str()})")
    except Exception:
        pass

    await close_http_session()
    print(f"[SHUTDOWN] Auto-Healer sauber beendet (Betriebszeit: {uptime_str()})", flush=True)


# ============================================================
# Main Entry Point Function
# ============================================================
def main() -> None:
    config.load()
    app = web.Application(middlewares=[cors_middleware])

    # Routing
    app.router.add_get('/', root_handler)
    app.router.add_get('/status', status_handler)
    app.router.add_post('/heal', heal_handler)
    app.router.add_get('/history', history_handler)
    app.router.add_post('/restart/{service}', restart_handler)
    app.router.add_get('/health', health_handler)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    port = config.auto_healer.get("port", 8007)

    print(f"\n{'='*55}", flush=True)
    print("  Antigravity Auto-Healer v1.0 - Refactored", flush=True)
    print(f"  --> http://127.0.0.1:{port} <--", flush=True)
    print(f"  Check-Interval:  {config.auto_healer.get('check_interval_seconds', 15)}s", flush=True)
    print(f"  Max Alert Cycles: {config.auto_healer.get('max_healing_cycles', 3)} cycles", flush=True)
    print(f"  API Bridge Url:   {config.auto_healer.get('api_bridge_url')}", flush=True)
    print(f"{'='*55}\n", flush=True)

    web.run_app(app, host='127.0.0.1', port=port, print=None)
