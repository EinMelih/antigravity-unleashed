import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator, Mapping, Optional


ReadyCallback = Callable[[], Awaitable[None]]


class CDPUnavailableError(ConnectionError):
    """Raised when a lifecycle operation cannot make CDP ready."""


def cdp_is_connected(client: Any) -> bool:
    """Return whether the client currently owns an open CDP websocket."""
    websocket = getattr(client, "ws", None)
    return bool(
        getattr(client, "_connected", False)
        and websocket is not None
        and not getattr(websocket, "closed", True)
    )


def bridge_is_ready(client: Any) -> bool:
    """Return readiness only when both CDP and the injected bridge are live."""
    return cdp_is_connected(client) and bool(
        getattr(client, "_bridge_injected", False)
    )


class CDPStartupSupervisor:
    """Connect and inject in the background until the desktop renderer is ready."""

    def __init__(
        self,
        client: Any,
        *,
        retry_seconds: float,
        on_ready: Optional[ReadyCallback] = None,
    ) -> None:
        self.client = client
        self.retry_seconds = max(0.0, float(retry_seconds))
        self.on_ready = on_ready
        self.last_error: Optional[str] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._lifecycle_lock = asyncio.Lock()
        self._stopping = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(
            self._connect_and_inject(),
            name="antigravity-cdp-startup",
        )

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        async with self._lifecycle_lock:
            await self.client.disconnect()

    async def ensure_ready(self) -> None:
        """Connect and inject once, serialized with diagnostics and shutdown."""
        async with self._lifecycle_lock:
            if self._stopping:
                raise CDPUnavailableError("CDP lifecycle is shutting down.")
            await self._ensure_ready_locked()

    async def diagnose(self) -> Any:
        """Make CDP ready and diagnose it as one serialized lifecycle action."""
        async with self._lifecycle_lock:
            if self._stopping:
                raise CDPUnavailableError("CDP lifecycle is shutting down.")
            try:
                await self._ensure_ready_locked()
            except Exception as error:
                raise CDPUnavailableError(str(error)) from error
            return await self.client.diagnose()

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[Any]:
        """Keep one shared-CDP operation serialized with startup and shutdown."""
        async with self._lifecycle_lock:
            if self._stopping:
                raise CDPUnavailableError("CDP lifecycle is shutting down.")
            try:
                await self._ensure_ready_locked()
            except Exception as error:
                raise CDPUnavailableError(str(error)) from error
            yield self.client

    async def _ensure_ready_locked(self) -> None:
        if not cdp_is_connected(self.client):
            await self.client.connect()
        await self.client.inject_bridge()
        if not bridge_is_ready(self.client):
            raise RuntimeError(
                "CDP connected, but bridge injection was not confirmed."
            )

    async def _connect_and_inject(self) -> None:
        reported_error: Optional[str] = None
        ready_notified = False
        while not self._stopping:
            if not bridge_is_ready(self.client):
                try:
                    await self.ensure_ready()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.last_error = str(error)
                    if self.last_error != reported_error:
                        print(
                            "[WARN] CDP/Bridge noch nicht bereit: "
                            f"{self.last_error} (neuer Versuch in "
                            f"{self.retry_seconds:g}s)",
                            flush=True,
                        )
                        reported_error = self.last_error
                else:
                    self.last_error = None
                    reported_error = None
                    print("[STARTUP] CDP verbunden und Bridge injiziert", flush=True)
                    if self.on_ready is not None and not ready_notified:
                        try:
                            await self.on_ready()
                        except Exception as error:
                            print(
                                f"[WARN] Startup-Benachrichtigung fehlgeschlagen: {error}",
                                flush=True,
                            )
                    ready_notified = True
            await asyncio.sleep(self.retry_seconds)


@asynccontextmanager
async def cdp_operation(app: Mapping[str, Any]) -> AsyncIterator[Any]:
    """Use the app's lifecycle gate, retaining a fallback for isolated callers."""
    supervisor = app.get("cdp_startup_supervisor")
    if supervisor is None:
        yield app["cdp"]
        return
    async with supervisor.operation() as client:
        yield client
