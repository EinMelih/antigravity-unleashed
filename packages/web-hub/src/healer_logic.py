import time
import asyncio
import aiohttp
import platform
import subprocess
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.config import config
from src.telegram import send_telegram

# Paths
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
CONFIG_PATH = BASE_DIR / "config.json"

# State and history logs
state = {
    "status": "online",
    "healthy": True,
    "total_checks": 0,
    "consecutive_failures": 0,
    "total_recoveries": 0,
    "last_check": None,
    "last_success": None,
    "last_error": None,
    "api_bridge_healthy": None,
    "cdp_connected": None,
    "bridge_injected": None,
    "process_running": None,
    "healing_in_progress": False,
    "last_action": None,
    "start_time": time.time(),
}

healing_history: List[Dict[str, Any]] = []

# HTTP Client session for the healer (lazy initialized)
_http_session: Optional[aiohttp.ClientSession] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def uptime_str() -> str:
    elapsed = time.time() - state["start_time"]
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    mins, s = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{int(days)}d")
    if hours:
        parts.append(f"{int(hours)}h")
    if mins:
        parts.append(f"{int(mins)}m")
    parts.append(f"{int(s)}s")
    return " ".join(parts)


def record_event(level: int, action: str, success: bool, error_message: Optional[str] = None) -> Dict[str, Any]:
    """Records a healing event to local history and prints it to stdout."""
    event = {
        "timestamp": now_iso(),
        "level": level,
        "action": action,
        "success": success,
        "error_message": error_message,
    }
    healing_history.append(event)
    status_icon = "✅" if success else "❌"
    print(f"[HEALER] {status_icon} Level {level}: {action}" + (f" — {error_message}" if error_message else ""), flush=True)
    return event


async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        _http_session = aiohttp.ClientSession(timeout=timeout)
    return _http_session


async def close_http_session() -> None:
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None


def _api_bridge_auth_headers() -> Dict[str, str]:
    """Build internal Bridge authentication without exposing credentials."""
    token = str(config.auth_token or "").strip()
    if not token:
        token = next(
            (str(value).strip() for value in config.api_keys if str(value).strip()),
            "",
        )
    return {"Authorization": f"Bearer {token}"} if token else {}


async def check_api_bridge() -> Dict[str, Any]:
    """Hits the API Bridge health endpoint to verify connectivity and CDP state."""
    api_bridge_url = config.auto_healer.get("api_bridge_url", "http://127.0.0.1:8001")
    url = f"{api_bridge_url}/health"
    start = time.monotonic()
    try:
        session = await get_http_session()
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                cdp_info = data.get("cdp", {})
                cdp_connected = (
                    isinstance(cdp_info, dict)
                    and cdp_info.get("status") == "connected"
                )
                bridge_injected = False
                diagnostics_status = None
                diagnostics_error = None
                if cdp_connected:
                    async with session.get(
                        f"{api_bridge_url}/health/cdp",
                        headers=_api_bridge_auth_headers(),
                        timeout=5,
                    ) as diagnostics_resp:
                        diagnostics_status = diagnostics_resp.status
                        if diagnostics_resp.status == 200:
                            diagnostics_payload = await diagnostics_resp.json()
                            diagnostics = diagnostics_payload.get("diagnostics")
                            bridge_injected = bool(
                                isinstance(diagnostics, dict)
                                and diagnostics.get("inputFound")
                            )
                        else:
                            diagnostics_error = (
                                "CDP diagnostics returned HTTP "
                                f"{diagnostics_resp.status}"
                            )
                return {
                    "reachable": True,
                    "cdp_connected": cdp_connected,
                    "bridge_injected": bridge_injected,
                    "response_time_ms": (time.monotonic() - start) * 1000,
                    "status_code": resp.status,
                    "diagnostics_status_code": diagnostics_status,
                    **(
                        {"diagnostics_error": diagnostics_error}
                        if diagnostics_error
                        else {}
                    ),
                }
            elapsed = (time.monotonic() - start) * 1000
            return {
                "reachable": True,
                "cdp_connected": False,
                "bridge_injected": False,
                "response_time_ms": elapsed,
                "status_code": resp.status,
            }
    except Exception as e:
        return {
            "reachable": False,
            "cdp_connected": False,
            "bridge_injected": False,
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error": str(e),
        }


async def check_process_running(process_name: str = "antigravity.exe") -> Optional[bool]:
    """Check if process is active across OS environments."""
    try:
        if platform.system() == 'Windows':
            cmd = ['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/FO', 'CSV', '/NH']
            kwargs = {
                'stdout': asyncio.subprocess.PIPE,
                'stderr': asyncio.subprocess.PIPE,
                'creationflags': subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            }
        else:
            search_name = process_name.replace('.exe', '')
            cmd = ['pgrep', '-f', search_name]
            kwargs = {
                'stdout': asyncio.subprocess.PIPE,
                'stderr': asyncio.subprocess.PIPE,
            }

        proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)

        if platform.system() == 'Windows':
            return process_name.lower() in stdout.decode('utf-8', errors='replace').lower()
        else:
            return proc.returncode == 0
    except Exception as e:
        print(f"[HEALER] Prozessprüfung fehlgeschlagen: {e}", flush=True)
        return None


# --- Escalation Healing Level Functions ---

async def heal_level_1() -> bool:
    """Level 1: Bridge Re-Inject - trigger JS injection."""
    api_bridge_url = config.auto_healer.get("api_bridge_url", "http://127.0.0.1:8001")
    try:
        session = await get_http_session()
        async with session.get(
            f"{api_bridge_url}/health/cdp",
            headers=_api_bridge_auth_headers(),
        ) as resp:
            if resp.status == 200:
                record_event(1, "Bridge Re-Inject via GET /health/cdp", True)
                return True
            body = await resp.text()
            record_event(1, "Bridge Re-Inject", False, f"HTTP {resp.status}: {body[:200]}")
            return False
    except Exception as e:
        record_event(1, "Bridge Re-Inject", False, str(e))
        return False


async def heal_level_2() -> bool:
    """Level 2: CDP Reconnect - trigger WS reconnection."""
    api_bridge_url = config.auto_healer.get("api_bridge_url", "http://127.0.0.1:8001")
    try:
        session = await get_http_session()
        async with session.get(
            f"{api_bridge_url}/health/cdp",
            headers=_api_bridge_auth_headers(),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                status = data.get("status", "")
                if status == "ok":
                    record_event(2, "CDP Reconnect via GET /health/cdp", True)
                    return True
                record_event(2, "CDP Reconnect", False, f"Status: {status}")
                return False
            body = await resp.text()
            record_event(2, "CDP Reconnect", False, f"HTTP {resp.status}: {body[:200]}")
            return False
    except Exception as e:
        record_event(2, "CDP Reconnect", False, str(e))
        return False


async def heal_level_3() -> bool:
    """Level 3: Start New Conversation in webview."""
    api_bridge_url = config.auto_healer.get("api_bridge_url", "http://127.0.0.1:8001")
    try:
        session = await get_http_session()
        payload = {"message": "test", "new_chat": True}
        headers = {"Content-Type": "application/json"}
        headers.update(_api_bridge_auth_headers())

        async with session.post(
            f"{api_bridge_url}/api/chat",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                record_event(3, "Neuer Chat gestartet", True)
                return True
            body = await resp.text()
            record_event(3, "Neuer Chat starten", False, f"HTTP {resp.status}: {body[:200]}")
            return False
    except asyncio.TimeoutError:
        record_event(3, "Neuer Chat starten", False, "Timeout nach 30s")
        return False
    except Exception as e:
        record_event(3, "Neuer Chat starten", False, str(e))
        return False


async def heal_level_4() -> bool:
    """Level 4: Process check for active antigravity.exe process."""
    running = await check_process_running()
    if running is True:
        record_event(4, "Prozess-Check: antigravity.exe läuft", True)
        return True
    elif running is False:
        msg = "antigravity.exe ist NICHT aktiv! Manueller Neustart erforderlich."
        record_event(4, "Prozess-Check", False, msg)
        print(f"[HEALER] ⚠️ {msg}", flush=True)
        return False
    record_event(4, "Prozess-Check", False, "Konnte Prozessstatus nicht ermitteln")
    return False


async def heal_level_5(error_context: str = "") -> bool:
    """Level 5: Trigger Telegram warning notification."""
    healer_port = config.auto_healer.get("port", 8007)
    max_cycles = config.auto_healer.get("max_healing_cycles", 3)
    message = (
        f"🔧 [Antigravity Auto-Healer] <b>⚠️ KRITISCH — Alle Heilungsversuche fehlgeschlagen!</b>\n\n"
        f"<b>Zyklen:</b> {state['consecutive_failures']}/{max_cycles}\n"
        f"<b>Letzter Fehler:</b> {state.get('last_error', 'Unbekannt')}\n"
        f"<b>Kontext:</b> {error_context or 'Keine Details'}\n"
        f"<b>Betriebszeit:</b> {uptime_str()}\n"
        f"<b>Gesamtchecks:</b> {state['total_checks']}\n\n"
        f"Manuelles Eingreifen erforderlich!\n"
        f"→ POST http://127.0.0.1:{healer_port}/heal"
    )
    sent = await send_telegram(message, parse_mode="HTML")
    record_event(5, "Telegram-Alert gesendet", sent, None if sent else "Telegram nicht erreichbar")
    return sent


async def run_healing_cycle(source: str = "auto") -> Dict[str, Any]:
    """Runs a complete healing iteration sequentially through all levels."""
    if state["healing_in_progress"]:
        print("[HEALER] Heilung läuft bereits — Überspringe Zyklus", flush=True)
        return {"error": "Heilung aktiv"}

    state["healing_in_progress"] = True
    print(f"[HEALER] ⚡ Starte Heilungszyklus (Trigger: {source})...", flush=True)

    results = {}
    max_cycles = config.auto_healer.get("max_healing_cycles", 3)

    try:
        # Level 1: Bridge Re-Inject
        print("[HEALER] → Level 1: Bridge Re-Inject...", flush=True)
        if await heal_level_1():
            await asyncio.sleep(3)
            check = await check_api_bridge()
            if check["reachable"] and check["cdp_connected"]:
                results["healed_at_level"] = 1
                return results

        # Level 2: CDP Reconnect
        print("[HEALER] → Level 2: CDP Reconnect...", flush=True)
        if await heal_level_2():
            await asyncio.sleep(5)
            check = await check_api_bridge()
            if check["reachable"] and check["cdp_connected"]:
                results["healed_at_level"] = 2
                return results

        # Level 3: New Conversation
        print("[HEALER] → Level 3: Neuer Chat...", flush=True)
        await heal_level_3()
        await asyncio.sleep(3)

        # Level 4: Process Monitor
        print("[HEALER] → Level 4: Prozess-Check...", flush=True)
        process_ok = await heal_level_4()
        results["process_running"] = process_ok

        if not process_ok:
            results["healed_at_level"] = None
            results["error"] = "antigravity.exe nicht aktiv"

        # Level 5: Telegram Warning (if failures exceeded)
        if state["consecutive_failures"] >= max_cycles:
            print("[HEALER] → Level 5: Telegram-Alert...", flush=True)
            error_ctx = state.get("last_error", "Unbekannt")
            await heal_level_5(error_ctx)
            results["telegram_alert_sent"] = True

        results["healed_at_level"] = results.get("healed_at_level")
        return results

    finally:
        state["healing_in_progress"] = False
        state["last_action"] = now_iso()
        print(f"[HEALER] Heilungszyklus abgeschlossen: {results}", flush=True)

