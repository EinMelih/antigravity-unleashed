import time
import uuid
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from src.config import config


class SessionStatus:
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    STUCK = "stuck"


class APIBridgeSession:
    """Represents a single downstream API Bridge instance."""

    def __init__(self, session_id: str, name: str, url: str) -> None:
        self.id = session_id
        self.name = name
        self.url = url.rstrip('/')
        self.status = SessionStatus.IDLE
        self.current_request: Optional[str] = None
        self.last_used: Optional[float] = None
        self.busy_since: Optional[float] = None
        self.total_requests = 0
        self.total_errors = 0
        self.total_response_ms = 0.0
        self.last_health_check: Optional[float] = None
        self.last_health_ok: bool = False
        self.acquired_by: Optional[str] = None  # client_id affinity

    @property
    def avg_response_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.total_response_ms / self.total_requests, 1)

    @property
    def is_available(self) -> bool:
        return self.status == SessionStatus.IDLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "current_request": self.current_request,
            "last_used": datetime.fromtimestamp(self.last_used, tz=timezone.utc).isoformat() if self.last_used else None,
            "busy_since": datetime.fromtimestamp(self.busy_since, tz=timezone.utc).isoformat() if self.busy_since else None,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "avg_response_ms": self.avg_response_ms,
            "last_health_ok": self.last_health_ok,
            "acquired_by": self.acquired_by,
        }

    def mark_busy(self, request_info: str = "", client_id: Optional[str] = None) -> None:
        self.status = SessionStatus.BUSY
        self.current_request = request_info
        self.busy_since = time.time()
        if client_id:
            self.acquired_by = client_id

    def mark_idle(self) -> None:
        self.status = SessionStatus.IDLE
        self.current_request = None
        self.busy_since = None

    def mark_error(self, reason: str = "") -> None:
        self.status = SessionStatus.ERROR
        self.current_request = reason
        self.busy_since = None
        self.total_errors += 1

    def record_response(self, duration_ms: float) -> None:
        self.total_requests += 1
        self.total_response_ms += duration_ms
        self.last_used = time.time()


class SessionPool:
    """Manages all active API Bridge session instances."""

    def __init__(self) -> None:
        self.sessions: Dict[str, APIBridgeSession] = {}
        self._round_robin_idx = 0
        self._lock = asyncio.Lock()
        self._http: Optional[aiohttp.ClientSession] = None
        self._health_task: Optional[asyncio.Task] = None
        self._started_at = time.time()

    async def start(self, http_session: aiohttp.ClientSession) -> None:
        self._http = http_session

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    def add_session(self, name: str, url: str) -> APIBridgeSession:
        session_id = f"ses_{uuid.uuid4().hex[:8]}"
        session = APIBridgeSession(session_id, name, url)
        self.sessions[session_id] = session
        print(f"[POOL] Session hinzugefügt: {name} -> {url} (id={session_id})", flush=True)
        return session

    def remove_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            s = self.sessions.pop(session_id)
            print(f"[POOL] Session entfernt: {s.name} (id={session_id})", flush=True)
            return True
        return False

    def get_session(self, session_id: str) -> Optional[APIBridgeSession]:
        return self.sessions.get(session_id)

    async def acquire_session(self, client_id: Optional[str] = None) -> Optional[APIBridgeSession]:
        """Acquires the best available session, favoring affinity and performance."""
        async with self._lock:
            # 1. Session Affinity
            if client_id:
                for s in self.sessions.values():
                    if s.acquired_by == client_id and s.is_available:
                        s.mark_busy("acquired", client_id)
                        print(f"[POOL] Affinity-Match: {s.name} für client={client_id}", flush=True)
                        return s

            # 2. Gather available sessions
            available = [s for s in self.sessions.values() if s.is_available]
            if not available:
                return None

            # 3. Sort by response time / performance
            available.sort(key=lambda s: (s.avg_response_ms, s.total_requests))
            chosen = available[0]
            chosen.mark_busy("acquired", client_id)
            print(f"[POOL] Session vergeben: {chosen.name} (avg={chosen.avg_response_ms}ms)", flush=True)
            return chosen

    def release_session(self, session_id: str) -> None:
        s = self.sessions.get(session_id)
        if s and s.status == SessionStatus.BUSY:
            s.mark_idle()
            print(f"[POOL] Session freigegeben: {s.name}", flush=True)

    async def select_for_proxy(self, client_id: Optional[str] = None) -> Optional[APIBridgeSession]:
        return await self.acquire_session(client_id)

    async def check_health(self, session: APIBridgeSession) -> None:
        """Sends a GET /health request to check a downstream session's status."""
        if not self._http:
            return
        try:
            url = f"{session.url}/health"
            async with self._http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                session.last_health_check = time.time()
                if resp.status == 200:
                    session.last_health_ok = True
                    if session.status == SessionStatus.ERROR:
                        session.mark_idle()
                        print(f"[HEALTH] Session erholt: {session.name}", flush=True)
                else:
                    session.last_health_ok = False
                    if session.status != SessionStatus.BUSY:
                        session.mark_error(f"Health-Check HTTP {resp.status}")
                        print(f"[HEALTH] Session fehlerhaft: {session.name} (HTTP {resp.status})", flush=True)
        except Exception as e:
            session.last_health_check = time.time()
            session.last_health_ok = False
            if session.status != SessionStatus.BUSY:
                session.mark_error(f"Health-Check Fehler: {str(e)[:80]}")
                print(f"[HEALTH] Session nicht erreichbar: {session.name} ({e})", flush=True)

    async def check_all_health(self) -> None:
        """Runs health checks across all idle sessions and marks stuck sessions."""
        now = time.time()
        tasks = []
        timeout_limit = config.session_manager.get("session_timeout_seconds", 120)

        for s in list(self.sessions.values()):
            if s.status == SessionStatus.BUSY and s.busy_since:
                busy_duration = now - s.busy_since
                if busy_duration > timeout_limit:
                    print(f"[HEALTH] Session blockiert: {s.name} (busy seit {round(busy_duration)}s)", flush=True)
                    s.status = SessionStatus.STUCK
                    s.current_request = f"Möglicherweise blockiert seit {round(busy_duration)}s"

            if s.status != SessionStatus.BUSY:
                tasks.append(self.check_health(s))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def health_check_loop(self) -> None:
        """Periodic background task that check sessions' health."""
        interval = config.session_manager.get("health_check_interval_seconds", 30)
        print(f"[HEALTH] Health-Check-Loop gestartet (Intervall: {interval}s)", flush=True)
        while True:
            try:
                await asyncio.sleep(interval)
                await self.check_all_health()
            except asyncio.CancelledError:
                print("[HEALTH] Health-Check-Loop beendet", flush=True)
                break
            except Exception as e:
                print(f"[HEALTH] Fehler im Health-Check: {e}", flush=True)

    def get_stats(self) -> Dict[str, Any]:
        total = len(self.sessions)
        idle = sum(1 for s in self.sessions.values() if s.status == SessionStatus.IDLE)
        busy = sum(1 for s in self.sessions.values() if s.status == SessionStatus.BUSY)
        error = sum(1 for s in self.sessions.values() if s.status == SessionStatus.ERROR)
        stuck = sum(1 for s in self.sessions.values() if s.status == SessionStatus.STUCK)

        total_requests = sum(s.total_requests for s in self.sessions.values())
        total_errors = sum(s.total_errors for s in self.sessions.values())
        avg_ms = 0.0
        if total_requests > 0:
            avg_ms = round(
                sum(s.total_response_ms for s in self.sessions.values()) / total_requests, 1
            )

        return {
            "pool": {
                "total_sessions": total,
                "idle": idle,
                "busy": busy,
                "error": error,
                "stuck": stuck,
            },
            "performance": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "avg_response_ms": avg_ms,
            },
            "uptime_seconds": round(time.time() - self._started_at),
        }
