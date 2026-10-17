import sys
import platform
from datetime import datetime, timezone
from aiohttp import web

from src.config import config
from src.local_admin_security import validate_loopback_host
from src.watchdog_db import UptimeDB, DB_PATH
from src.watchdog_engine import HealthCheckEngine, TelegramAlerter
from src.watchdog_handlers import (
    cors_middleware,
    handle_health,
    handle_status_all,
    handle_status_single,
    handle_uptime,
    handle_alert_test,
    handle_alerts,
)


async def on_startup(app: web.Application) -> None:
    """Startet die Health-Check-Engine beim Server-Start."""
    engine: HealthCheckEngine = app["engine"]
    await engine.start()


async def on_cleanup(app: web.Application) -> None:
    """Fährt die Engine sauber herunter und schließt DB-Verbindungen."""
    engine: HealthCheckEngine = app["engine"]
    await engine.stop()
    print("[WATCHDOG] Heruntergefahren.", flush=True)


def create_app() -> web.Application:
    """Erstellt und konfiguriert die aiohttp-Anwendung."""
    db = UptimeDB(DB_PATH)
    alerter = TelegramAlerter(db)
    engine = HealthCheckEngine(db, alerter)

    app = web.Application(middlewares=[cors_middleware])

    # Shared-State für Endpoints
    app["config"] = config
    app["db"] = db
    app["alerter"] = alerter
    app["engine"] = engine

    # Routen
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status_all)
    app.router.add_get("/status/{service}", handle_status_single)
    app.router.add_get("/uptime", handle_uptime)
    app.router.add_post("/alert/test", handle_alert_test)
    app.router.add_get("/alerts", handle_alerts)

    # Lifecycle-Hooks
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


def print_banner(port: int) -> None:
    try:
        print("", flush=True)
        print("  +----------------------------------------------+", flush=True)
        try:
            print("  |   [WD]  Anti-Gravity Watchdog Monitor v1.0   |", flush=True)
        except UnicodeEncodeError:
            print("  |   WD  Anti-Gravity Watchdog Monitor v1.0     |", flush=True)
        print("  +----------------------------------------------+", flush=True)
        print(f"  |   Port:     {port:<33}|", flush=True)
        print(f"  |   Status:   http://127.0.0.1:{port}/status    |", flush=True)
        print(f"  |   Uptime:   http://127.0.0.1:{port}/uptime    |", flush=True)
        print(f"  |   Health:   http://127.0.0.1:{port}/health    |", flush=True)
        print(f"  |   Alerts:   http://127.0.0.1:{port}/alerts    |", flush=True)
        print("  +----------------------------------------------+", flush=True)
        print("  |   Strg+C zum Beenden                        |", flush=True)
        print("  +----------------------------------------------+", flush=True)
        print("", flush=True)
    except Exception:
        print(f"[WATCHDOG] Starting on port {port}", flush=True)



def main() -> None:
    wd_cfg = config.watchdog
    host = validate_loopback_host(
        wd_cfg.get("host", "127.0.0.1"),
        service="Watchdog",
    )
    port = wd_cfg.get("port", 8010)
    print_banner(port)
    app = create_app()
    try:
        web.run_app(app, host=host, port=port,
                    print=lambda msg: print(f"  {msg}", flush=True))
    except KeyboardInterrupt:
        print("\n[WATCHDOG] Beendet.", flush=True)


if __name__ == "__main__":
    main()
