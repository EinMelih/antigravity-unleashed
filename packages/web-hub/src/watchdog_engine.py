import time
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from src.config import config
from src.telegram import send_telegram
from src.watchdog_db import UptimeDB

# Escalation trigger thresholds
ESCALATION_LOG_ONLY = 1
ESCALATION_WARNING = 3
ESCALATION_CRITICAL = 5
ESCALATION_RESTART_HINT = 10

# High latency alert limit (ms)
HIGH_LATENCY_THRESHOLD_MS = 5000


class ServiceState:
    """Represents the in-memory state of a monitored service."""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url
        self.status = "unknown"  # up, down, degraded, unknown
        self.response_time_ms: Optional[float] = None
        self.last_check: Optional[str] = None
        self.last_error: Optional[str] = None
        self.consecutive_failures = 0
        self.last_up: Optional[str] = None
        self.last_down: Optional[str] = None
        self.last_alert_time = 0.0  # monotonic timestamp for cooldowns

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "response_time_ms": self.response_time_ms,
            "last_check": self.last_check,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "last_up": self.last_up,
            "last_down": self.last_down,
        }


class TelegramAlerter:
    """Wrapper that routes alerts to the centralized Telegram notifier and logs to UptimeDB."""

    def __init__(self, db: UptimeDB) -> None:
        self.db = db

    async def send(self, message: str, level: str = "INFO", service: str = "watchdog") -> bool:
        """Sends warning message to Telegram and commits alert entry to DB."""
        self.db.log_alert(service, level, message)
        # HTML formatting is passed from the escalation engine
        return await send_telegram(message, parse_mode="HTML")


class HealthCheckEngine:
    """Periodically health-polls configured services using ClientSession request pool."""

    def __init__(self, db: UptimeDB, alerter: TelegramAlerter) -> None:
        self.db = db
        self.alerter = alerter
        self.states: Dict[str, ServiceState] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._start_mono = time.monotonic()

        # Initialize monitored services
        wd_cfg = config.watchdog
        for svc in wd_cfg.get("services", []):
            name = svc["name"]
            self.states[name] = ServiceState(name, svc["url"])

    async def start(self) -> None:
        """Launches check polling thread in the background."""
        self._running = True
        wd_cfg = config.watchdog
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=wd_cfg.get("timeout_ms", 3000) / 1000.0
            )
        )
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[ENGINE] Gestartet: {len(self.states)} Services, Intervall={wd_cfg.get('check_interval_seconds')}s", flush=True)

    async def stop(self) -> None:
        """Terminates background loops gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                print(f"[ENGINE] Fehler beim Stoppen: {e}", flush=True)
            self._task = None

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        print("[ENGINE] Gestoppt.", flush=True)

    async def _poll_loop(self) -> None:
        """Polling loop running checks at set intervals."""
        cleanup_counter = 0
        wd_cfg = config.watchdog
        interval = wd_cfg.get("check_interval_seconds", 10)

        while self._running:
            try:
                tasks = [
                    self._check_service(state)
                    for state in self.states.values()
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

                # Prune detailed history periodically. Retention is explicit so
                # installations can trade diagnostic depth for disk usage.
                cleanup_counter += 1
                if cleanup_counter >= 360:
                    cleanup_counter = 0
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        self.db.cleanup_old,
                        wd_cfg.get("retention_days", 30),
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ENGINE] Fehler in Poll-Schleife: {e}", flush=True)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _check_service(self, state: ServiceState) -> None:
        """Polls a single service HTTP GET health endpoint."""
        now_iso = datetime.now(timezone.utc).isoformat()
        state.last_check = now_iso
        start = time.monotonic()
        wd_cfg = config.watchdog

        try:
            if not self._session:
                raise RuntimeError("Client session not active")

            async with self._session.get(state.url) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                state.response_time_ms = round(elapsed_ms, 1)

                if resp.status < 400:
                    new_status = "up"
                    if elapsed_ms > HIGH_LATENCY_THRESHOLD_MS:
                        new_status = "degraded"
                    state.last_error = None
                else:
                    new_status = "down"
                    state.last_error = f"HTTP {resp.status}"

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            state.response_time_ms = round(elapsed_ms, 1)
            new_status = "down"
            state.last_error = f"Timeout nach {wd_cfg.get('timeout_ms', 3000)}ms"

        except aiohttp.ClientConnectorError as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            state.response_time_ms = round(elapsed_ms, 1)
            new_status = "down"
            state.last_error = f"Verbindung fehlgeschlagen: {e}"

        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            state.response_time_ms = round(elapsed_ms, 1)
            new_status = "down"
            state.last_error = f"{type(e).__name__}: {e}"

        previous_status = state.status
        state.status = new_status

        if new_status == "up":
            was_down = state.consecutive_failures > 0
            if was_down:
                down_duration = self._calc_downtime(state)
                await self._send_recovery_alert(state, down_duration)
            state.consecutive_failures = 0
            state.last_up = now_iso

        elif new_status == "degraded":
            state.last_up = now_iso
            state.consecutive_failures = 0
            await self._handle_high_latency(state)

        else:  # down
            state.consecutive_failures += 1
            if state.consecutive_failures == 1:
                state.last_down = now_iso
            await self._handle_escalation(state)

        # Log check entry
        self.db.log_check(state.name, new_status, state.response_time_ms, state.last_error)

    def _calc_downtime(self, state: ServiceState) -> str:
        """Calculates total downtime elapsed."""
        if not state.last_down:
            return "unbekannt"
        try:
            down_dt = datetime.fromisoformat(state.last_down)
            now_dt = datetime.now(timezone.utc)
            delta = now_dt - down_dt
            secs = int(delta.total_seconds())
            if secs < 60:
                return f"{secs}s"
            elif secs < 3600:
                return f"{secs // 60}m {secs % 60}s"
            else:
                h = secs // 3600
                m = (secs % 3600) // 60
                return f"{h}h {m}m"
        except Exception:
            return "unbekannt"

    async def _handle_escalation(self, state: ServiceState) -> None:
        """Escalation handler logging and alerting failures according to intervals."""
        fails = state.consecutive_failures
        wd_cfg = config.watchdog
        alert_cooldown = wd_cfg.get("alert_cooldown_seconds", 300)

        if fails < ESCALATION_LOG_ONLY:
            return

        if fails == ESCALATION_LOG_ONLY:
            print(f"[CHECK] {state.name}: Fehler #{fails} — {state.last_error}", flush=True)
            return

        now = time.monotonic()
        if (now - state.last_alert_time) < alert_cooldown:
            return

        if fails >= ESCALATION_RESTART_HINT:
            level = "CRITICAL"
            emoji = "🔴"
            msg = (
                f"{emoji} <b>NEUSTART EMPFOHLEN</b>\n\n"
                f"Service: <b>{state.name}</b>\n"
                f"Status: DOWN ({fails}x fehlgeschlagen)\n"
                f"Fehler: {state.last_error}\n"
                f"Ausfall seit: {self._calc_downtime(state)}\n\n"
                f"💡 Empfehlung: Service manuell neustarten\n"
                f"<code>python {state.name}.py</code>"
            )
        elif fails >= ESCALATION_CRITICAL:
            level = "CRITICAL"
            emoji = "🔴"
            msg = (
                f"{emoji} <b>KRITISCH — Service nicht erreichbar</b>\n\n"
                f"Service: <b>{state.name}</b>\n"
                f"Status: DOWN ({fails}x fehlgeschlagen)\n"
                f"Fehler: {state.last_error}\n"
                f"Ausfall seit: {self._calc_downtime(state)}"
            )
        elif fails >= ESCALATION_WARNING:
            level = "WARNING"
            emoji = "🟡"
            msg = (
                f"{emoji} <b>WARNUNG — Service reagiert nicht</b>\n\n"
                f"Service: <b>{state.name}</b>\n"
                f"Status: DOWN ({fails}x fehlgeschlagen)\n"
                f"Fehler: {state.last_error}"
            )
        else:
            return

        state.last_alert_time = now
        await self.alerter.send(msg, level=level, service=state.name)

    async def _send_recovery_alert(self, state: ServiceState, down_duration: str) -> None:
        """Triggers recovery announcement."""
        msg = (
            f"🟢 <b>Service wiederhergestellt</b>\n\n"
            f"Service: <b>{state.name}</b>\n"
            f"Status: UP\n"
            f"Ausfallzeit: {down_duration}\n"
            f"Antwortzeit: {state.response_time_ms}ms"
        )
        state.last_alert_time = time.monotonic()
        await self.alerter.send(msg, level="RECOVERY", service=state.name)

    async def _handle_high_latency(self, state: ServiceState) -> None:
        """Sends warning message if connection latency spikes."""
        now = time.monotonic()
        wd_cfg = config.watchdog
        alert_cooldown = wd_cfg.get("alert_cooldown_seconds", 300)

        if (now - state.last_alert_time) < alert_cooldown:
            return
        msg = (
            f"🟠 <b>Hohe Latenz erkannt</b>\n\n"
            f"Service: <b>{state.name}</b>\n"
            f"Antwortzeit: {state.response_time_ms}ms\n"
            f"Schwelle: {HIGH_LATENCY_THRESHOLD_MS}ms"
        )
        state.last_alert_time = now
        await self.alerter.send(msg, level="WARNING", service=state.name)
