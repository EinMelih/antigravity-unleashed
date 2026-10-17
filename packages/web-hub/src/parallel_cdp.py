import asyncio
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.antigravity_project_settings import enforce_hub_project_settings
from src.cdp_client import AntigravityCDP


_CHAT_TARGET_IDS: Dict[str, str] = {}
_DUPLICATE_TARGET_IDS: set[str] = set()
_WINDOW_STAMPS: Dict[str, str] = {}
_NEXT_WINDOW_STAMP = 1
_PRIMARY_TARGET_ID: Optional[str] = None
_DICTATION_TARGET_ID: Optional[str] = None
_WINDOW_LOCK: Optional[asyncio.Lock] = None
_CHAT_LOCKS: Dict[str, asyncio.Lock] = {}
_TARGET_LOCKS: Dict[str, asyncio.Lock] = {}
_WORKER_STATES: Dict[str, Dict[str, Any]] = {}
_WORKER_MONITORS: Dict[str, asyncio.Task] = {}
_POOL_WAITERS = 0
_BUSY_WORKER_STATES = {"preparing", "sending", "working", "waiting_human"}


def _active_user_input_gate(
    history_payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return the latest unsuperseded approval-gated tool step, if any."""
    history = [
        item
        for item in history_payload.get("history", [])
        if isinstance(item, dict)
    ]
    gated = [
        item
        for item in history
        if item.get("type") == "tool_call"
        and (
            item.get("status") == 9
            or item.get("requires_user_input") is True
        )
    ]
    if not gated:
        return None

    gate = max(gated, key=lambda item: int(item.get("idx") or 0))
    gate_idx = int(gate.get("idx") or 0)
    has_later_progress = any(
        int(item.get("idx") or 0) > gate_idx
        and item.get("type") in {
            "message",
            "tool_call",
            "tool_output",
            "status",
        }
        for item in history
    )
    return None if has_later_progress else gate


def _positive_int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_WORKERS = _positive_int_setting("ANTIGRAVITY_HUB_MAX_WORKERS", 4)
MIN_WARM_WORKERS = min(
    MAX_WORKERS,
    _positive_int_setting("ANTIGRAVITY_HUB_MIN_WARM_WORKERS", 1),
)
IDLE_WORKER_TTL_SECONDS = _positive_int_setting(
    "ANTIGRAVITY_HUB_WORKER_IDLE_TTL_SECONDS",
    180,
)
WORKER_WAIT_TIMEOUT_SECONDS = _positive_int_setting(
    "ANTIGRAVITY_HUB_WORKER_WAIT_TIMEOUT_SECONDS",
    300,
)
WORKER_ACTIVE_TIMEOUT_SECONDS = _positive_int_setting(
    "ANTIGRAVITY_HUB_WORKER_ACTIVE_TIMEOUT_SECONDS",
    1800,
)
PROJECT_CREATION_VISIBILITY_TIMEOUT_SECONDS = 60.0
PROJECT_VISIBILITY_POLL_SECONDS = 0.25
PROJECT_LINKED_VISIBILITY_TIMEOUT_SECONDS = 30.0
PROJECT_SIDEBAR_SCROLL_RENDER_SECONDS = 0.15
PROJECT_SIDEBAR_MAX_SCROLL_POSITIONS = 32
_SEMANTIC_ACTION_SELECTOR = 'button,a,[role=\"button\"],[role=\"menuitem\"]'


def _semantic_action_matches_js(escaped_text: str) -> str:
    """Build the shared visible action lookup used by wizard interactions."""
    selector = json.dumps(_SEMANTIC_ACTION_SELECTOR)
    return (
        "const isActionable = element => {"
        "const style = getComputedStyle(element);"
        "const rect = element.getBoundingClientRect();"
        "return !element.disabled "
        "&& element.getAttribute('aria-disabled') !== 'true' "
        "&& !element.closest('[aria-hidden=\"true\"],[inert],[data-state=\"closed\"]') "
        "&& style.display !== 'none' && style.visibility !== 'hidden' "
        "&& style.pointerEvents !== 'none' && Number(style.opacity || 1) > 0 "
        "&& (element.offsetParent !== null || style.position === 'fixed') "
        "&& rect.width > 0 && rect.height > 0 "
        "&& rect.bottom > 0 && rect.right > 0 "
        "&& rect.top < innerHeight && rect.left < innerWidth;"
        "};"
        f"const matches = Array.from(document.querySelectorAll({selector}))"
        ".filter(element => isActionable(element) && ("
        f"(element.innerText || '').trim() === {escaped_text} || "
        f"(element.getAttribute('aria-label') || '').trim() === {escaped_text}"
        "));"
    )


def _window_lock() -> asyncio.Lock:
    global _WINDOW_LOCK
    if _WINDOW_LOCK is None:
        _WINDOW_LOCK = asyncio.Lock()
    return _WINDOW_LOCK


def _chat_lock(chat_id: str) -> asyncio.Lock:
    if chat_id not in _CHAT_LOCKS:
        _CHAT_LOCKS[chat_id] = asyncio.Lock()
    return _CHAT_LOCKS[chat_id]


def _target_lock(target_id: str) -> asyncio.Lock:
    if target_id not in _TARGET_LOCKS:
        _TARGET_LOCKS[target_id] = asyncio.Lock()
    return _TARGET_LOCKS[target_id]


def _worker_state(target_id: str) -> Dict[str, Any]:
    state = _WORKER_STATES.get(target_id)
    if state is None:
        now = time.time()
        state = {
            "target_id": target_id,
            "window_id": _WINDOW_STAMPS.get(target_id),
            "chat_id": None,
            "state": "idle",
            "detail": "Bereit",
            "activity_known": False,
            "reserved": False,
            "purpose": "chat",
            "created_at": now,
            "updated_at": now,
            "last_used_at": now,
            "error": "",
        }
        _WORKER_STATES[target_id] = state
    return state


def _reconcile_worker_activity(
    state: Dict[str, Any],
    runtime: Dict[str, Any],
) -> tuple[str, str]:
    """Resolve Hub and native evidence without inventing an idle state."""
    hub_activity_known = bool(state.get("activity_known"))
    hub_state = str(state.get("state") or "unknown")
    native_activity = str(runtime.get("native_activity") or "unknown")
    activity_observed = bool(runtime.get("activity_observed"))
    if hub_activity_known and hub_state in _BUSY_WORKER_STATES | {"error"}:
        return hub_state, str(state.get("detail") or "")
    if activity_observed and native_activity == "working":
        return "working", "Native Oberfläche arbeitet"
    if hub_activity_known:
        return hub_state, str(state.get("detail") or "")
    if activity_observed and native_activity == "idle":
        return "idle", "Native Oberfläche bereit"
    return "unknown", "Status nicht ermittelt"


def _worker_is_safely_idle(
    target_id: str,
    state: Dict[str, Any],
    runtime: Dict[str, Any],
) -> bool:
    """Require positive reachable idle evidence before reuse or retirement."""
    return bool(
        _worker_has_positive_idle_evidence(state, runtime)
        and not _target_lock(target_id).locked()
    )


def _worker_has_positive_idle_evidence(
    state: Dict[str, Any],
    runtime: Dict[str, Any],
) -> bool:
    """Require positive idle evidence while the caller owns the target lock."""
    activity, _ = _reconcile_worker_activity(state, runtime)
    return bool(
        runtime.get("runtime_reachable") is True
        and activity == "idle"
        and not state.get("reserved")
        and not runtime.get("has_draft")
    )


class ParallelCDPManager:
    """Manage CDP clients and dedicated desktop windows for individual chats."""

    def __init__(self, *, profile=None) -> None:
        self.profile = profile
        if profile:
            from src.api_profile import APIProfileRuntime
            self.profile_runtime = APIProfileRuntime(profile)
        else:
            self.profile_runtime = None
        self.clients: Dict[str, AntigravityCDP] = {}

    async def get_devtools_port(self) -> int:
        """Find the active DevTools port from port_finder."""
        from src.port_finder import find_devtools

        loop = asyncio.get_running_loop()
        finder = self.profile_runtime.find_target if self.profile_runtime else find_devtools
        info = await loop.run_in_executor(None, finder)
        if not info:
            raise ConnectionError("Antigravity DevTools not found!")
        return info["devtools_port"]

    async def _fetch_targets(self, port: int) -> List[Dict[str, Any]]:
        url = f"http://127.0.0.1:{port}/json"
        loop = asyncio.get_running_loop()

        def fetch() -> List[Dict[str, Any]]:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                print(
                    f"[ParallelCDPManager] Error fetching targets from port {port}: {exc}",
                    flush=True,
                )
                return []

        return await loop.run_in_executor(None, fetch)

    async def get_all_page_targets(self, port: int) -> List[Dict[str, Any]]:
        """Enumerate active Antigravity page targets for a DevTools port."""
        if self.profile_runtime and port != self.profile_runtime.devtools_port:
            raise ConnectionError('API windows must belong to the dedicated API browser.')
        targets = await self._fetch_targets(port)
        page_targets = []
        for target in targets:
            if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
                continue
            page_url = target.get("url", "")
            if any(exclude in page_url for exclude in ["/docs", "/editor", "/ide"]):
                continue
            if not page_url.startswith(("http://", "https://")):
                continue
            page_targets.append(target)
        return page_targets

    async def get_client_for_target(self, ws_url: str) -> AntigravityCDP:
        """Return a connected CDP client for a target WebSocket URL."""
        if ws_url not in self.clients:
            client = AntigravityCDP(profile=self.profile) if self.profile else AntigravityCDP()
            await client.connect(ws_url=ws_url)
            self.clients[ws_url] = client
        return self.clients[ws_url]

    async def _get_target_by_id(self, port: int, target_id: str) -> Optional[Dict[str, Any]]:
        targets = await self.get_all_page_targets(port)
        return next((target for target in targets if target.get("id") == target_id), None)

    @staticmethod
    def get_window_stamp(target_id: str) -> str:
        """Return one short, stable human-readable ID for a duplicate target."""
        global _NEXT_WINDOW_STAMP
        if target_id not in _WINDOW_STAMPS:
            _WINDOW_STAMPS[target_id] = f"AG-{_NEXT_WINDOW_STAMP:02d}"
            _NEXT_WINDOW_STAMP += 1
        return _WINDOW_STAMPS[target_id]

    @staticmethod
    def get_readonly_window_stamp(target_id: str) -> str:
        """Return a deterministic label without changing process or renderer state."""
        existing = _WINDOW_STAMPS.get(target_id)
        if existing:
            return existing
        fingerprint = hashlib.sha256(target_id.encode("utf-8")).hexdigest()[:6]
        return f"AG-{fingerprint.upper()}"

    async def apply_window_stamp(
        self,
        target: Dict[str, Any],
        *,
        preferred_stamp: str = "",
        purpose: str = "chat",
    ) -> str:
        """Render the Hub window ID inside the actual Anti-Gravity duplicate."""
        target_id = str(target.get("id") or "")
        if not target_id:
            raise RuntimeError("The duplicate window has no stable target ID.")
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        script = """(() => {
              const sessionKey = 'antigravityHubWindowId';
              const counterKey = 'antigravityHubWindowCounter';
              const purposeKey = 'antigravityHubWindowPurpose';
              const preferredStamp = __PREFERRED_STAMP__;
              const purpose = __WINDOW_PURPOSE__;
              let stamp = preferredStamp || sessionStorage.getItem(sessionKey);
              if (!stamp) {
                const next = Math.max(
                  1,
                  Number.parseInt(localStorage.getItem(counterKey) || '0', 10) + 1
                );
                localStorage.setItem(counterKey, String(next));
                stamp = `AG-${String(next).padStart(2, '0')}`;
              }
              sessionStorage.setItem(sessionKey, stamp);
              sessionStorage.setItem(purposeKey, purpose);
              window.__antigravityHubWindowId = stamp;
              window.__antigravityHubWindowPurpose = purpose;
              let badge = document.getElementById('antigravity-hub-window-stamp');
              if (!badge) {
                badge = document.createElement('div');
                badge.id = 'antigravity-hub-window-stamp';
                Object.assign(badge.style, {
                  position: 'fixed', top: '38px', right: '12px', zIndex: '2147483647',
                  padding: '5px 9px', borderRadius: '7px', pointerEvents: 'none',
                  font: '700 11px/1.2 system-ui, sans-serif', letterSpacing: '0.08em',
                  boxShadow: '0 4px 18px rgba(0,0,0,0.35)'
                });
                document.documentElement.appendChild(badge);
              }
              const isDictation = purpose === 'dictation';
              badge.style.color = isDictation ? '#fecdd3' : '#d9f99d';
              badge.style.background = isDictation
                ? 'rgba(55, 18, 29, 0.94)'
                : 'rgba(20, 30, 18, 0.92)';
              badge.style.border = isDictation
                ? '1px solid rgba(251, 113, 133, 0.62)'
                : '1px solid rgba(163, 230, 53, 0.55)';
              badge.dataset.purpose = purpose;
              badge.textContent = stamp;
              badge.title = isDictation
                ? 'Reserviertes Anti-Gravity-Diktatfenster'
                : 'Anti-Gravity Hub window ' + stamp;
              return stamp;
            })()"""
        script = (
            script
            .replace("__PREFERRED_STAMP__", json.dumps(str(preferred_stamp or "")))
            .replace("__WINDOW_PURPOSE__", json.dumps(str(purpose or "chat")))
        )
        stamp = await client.evaluate(
            script,
            timeout=5,
        )
        if not stamp:
            stamp = self.get_window_stamp(target_id)
        _WINDOW_STAMPS[target_id] = str(stamp)
        state = _worker_state(target_id)
        state["window_id"] = str(stamp)
        state["purpose"] = str(purpose or "chat")
        return stamp

    @staticmethod
    def _set_worker_state(
        target_id: str,
        state_name: str,
        *,
        chat_id: Optional[str] = None,
        detail: str = "",
        reserved: Optional[bool] = None,
        purpose: Optional[str] = None,
        error: str = "",
    ) -> Dict[str, Any]:
        state = _worker_state(target_id)
        state["state"] = state_name
        state["activity_known"] = True
        if chat_id is not None:
            state["chat_id"] = chat_id
        if detail:
            state["detail"] = detail
        if reserved is not None:
            state["reserved"] = reserved
        if purpose is not None:
            state["purpose"] = purpose
        state["error"] = error
        state["updated_at"] = time.time()
        if state_name in {"idle", "working"}:
            state["last_used_at"] = state["updated_at"]
        return state

    @staticmethod
    def _unbind_target(target_id: str, *, keep_chat_id: Optional[str] = None) -> None:
        for mapped_chat_id, mapped_target_id in list(_CHAT_TARGET_IDS.items()):
            if mapped_target_id == target_id and mapped_chat_id != keep_chat_id:
                _CHAT_TARGET_IDS.pop(mapped_chat_id, None)

    async def _inspect_target_runtime(
        self,
        target: Dict[str, Any],
    ) -> Dict[str, Any]:
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        return await client.evaluate(
            """(async () => {
              const api = window.electronNative || {};
              let role = null;
              try {
                role = typeof api.getWindowRole === 'function'
                  ? await api.getWindowRole()
                  : null;
              } catch (_) {}
              const input = window.__agBridge?.findInput?.()
                || document.querySelector(
                  '[aria-label="Message input"],'
                  + '[contenteditable="true"][role="textbox"],'
                  + '[contenteditable="true"][role="combobox"]'
                );
              const inputText = String(
                input?.innerText || input?.textContent || input?.value || ''
              ).trim();
              const activeChat = (
                location.href.match(/\\/c\\/([a-f0-9-]{36})/) || []
              )[1] || null;
              let activeMeta = null;
              try {
                activeMeta = typeof window.__agBridge?.getActiveChatMeta === 'function'
                  ? await window.__agBridge.getActiveChatMeta()
                  : null;
              } catch (_) {}
              const activityObserved = Boolean(
                activeMeta
                && typeof activeMeta === 'object'
                && (
                  typeof activeMeta.is_running === 'boolean'
                  || typeof activeMeta.is_streaming === 'boolean'
                )
              );
              const nativeActivity = activityObserved
                ? (
                  activeMeta.is_running === true || activeMeta.is_streaming === true
                    ? 'working'
                    : 'idle'
                )
                : 'unknown';
              return {
                role,
                stamp: sessionStorage.getItem('antigravityHubWindowId'),
                purpose: sessionStorage.getItem('antigravityHubWindowPurpose') || 'chat',
                chat_id: activeChat || activeMeta?.chat_id || null,
                url: location.href,
                title: document.title || '',
                composer_visible: Boolean(input && input.offsetParent !== null),
                has_draft: Boolean(inputText),
                focused: document.hasFocus(),
                activity_observed: activityObserved,
                native_activity: nativeActivity
              };
            })()""",
            timeout=5,
        ) or {}

    async def _discover_window_pool(
        self,
        port: int,
        *,
        mutate_registry: bool = True,
    ) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        global _DICTATION_TARGET_ID

        targets = await self.get_all_page_targets(port)
        workers: List[Dict[str, Any]] = []
        primary: Optional[Dict[str, Any]] = None
        live_target_ids = {
            str(target.get("id"))
            for target in targets
            if target.get("id")
        }

        for target in targets:
            target_id = str(target.get("id") or "")
            if not target_id:
                continue
            try:
                runtime = await self._inspect_target_runtime(target)
                runtime["runtime_reachable"] = True
            except Exception as exc:
                runtime = {"error": str(exc), "runtime_reachable": False}
            role = runtime.get("role")
            stamp = runtime.get("stamp") or _WINDOW_STAMPS.get(target_id)
            is_worker = role != "primary" and (
                role == "duplicate"
                or bool(stamp)
                or target_id in _DUPLICATE_TARGET_IDS
            )
            item = {**target, "runtime": runtime}

            if not is_worker:
                if role == "primary" or primary is None:
                    primary = item
                continue

            if mutate_registry:
                _DUPLICATE_TARGET_IDS.add(target_id)
                if stamp:
                    _WINDOW_STAMPS[target_id] = str(stamp)
                state = _worker_state(target_id)
                state["window_id"] = str(stamp or state.get("window_id") or "")
                state["purpose"] = str(
                    runtime.get("purpose") or state.get("purpose") or "chat"
                )
                if state["purpose"] == "dictation":
                    _DICTATION_TARGET_ID = target_id
                item["worker_state"] = state
            workers.append(item)

        if mutate_registry:
            for target_id in list(_WORKER_STATES):
                if target_id not in live_target_ids:
                    _WORKER_STATES.pop(target_id, None)
                    _WINDOW_STAMPS.pop(target_id, None)
                    _DUPLICATE_TARGET_IDS.discard(target_id)
                    if _DICTATION_TARGET_ID == target_id:
                        _DICTATION_TARGET_ID = None
                    self._unbind_target(target_id)

        return workers, primary

    async def get_worker_pool_snapshot(self) -> Dict[str, Any]:
        """Return live main-window and Hub worker state for the dashboard."""
        global _POOL_WAITERS

        port = await self.get_devtools_port()
        workers, primary = await self._discover_window_pool(
            port,
            mutate_registry=False,
        )
        worker_rows = []
        for worker in workers:
            target_id = str(worker.get("id") or "")
            runtime = worker.get("runtime") or {}
            state = dict(_WORKER_STATES.get(target_id) or {})
            activity, detail = _reconcile_worker_activity(state, runtime)
            window_id = (
                runtime.get("stamp")
                or state.get("window_id")
                or self.get_readonly_window_stamp(target_id)
            )
            worker_rows.append({
                "target_id": target_id,
                "window_id": window_id,
                "state": activity,
                "detail": detail,
                "chat_id": state.get("chat_id"),
                "loaded_chat_id": runtime.get("chat_id"),
                "reserved": bool(state.get("reserved")),
                "purpose": runtime.get("purpose") or state.get("purpose") or "chat",
                "composer_visible": bool(runtime.get("composer_visible")),
                "has_draft": bool(runtime.get("has_draft")),
                "background": True,
                "updated_at": state.get("updated_at"),
                "last_used_at": state.get("last_used_at"),
                "error": state.get("error") or runtime.get("error") or "",
                "runtime_reachable": bool(runtime.get("runtime_reachable")),
            })
        worker_rows.sort(key=lambda item: str(item.get("window_id") or ""))
        chat_worker_rows = [
            item for item in worker_rows
            if item.get("purpose") != "dictation"
        ]
        busy_workers = sum(
            item.get("state") in _BUSY_WORKER_STATES
            for item in chat_worker_rows
        )
        idle_workers = sum(
            item.get("state") == "idle"
            for item in chat_worker_rows
        )

        primary_row = None
        if primary:
            runtime = primary.get("runtime") or {}
            primary_activity = str(runtime.get("native_activity") or "unknown")
            if not runtime.get("activity_observed"):
                primary_activity = "unknown"
            primary_detail = {
                "working": "Native Oberfläche arbeitet",
                "idle": "Dein Hauptfenster",
                "unknown": "Status nicht ermittelt",
            }.get(primary_activity, "Status nicht ermittelt")
            primary_row = {
                "target_id": primary.get("id"),
                "window_id": "MAIN",
                "state": "user" if primary_activity == "idle" else primary_activity,
                "detail": primary_detail,
                "chat_id": runtime.get("chat_id"),
                "focused": bool(runtime.get("focused")),
                "runtime_reachable": bool(runtime.get("runtime_reachable")),
            }

        return {
            "primary": primary_row,
            "workers": worker_rows,
            "capacity": {
                # Retain `active` for legacy clients, with its user-facing
                # meaning: executions currently doing or awaiting work.
                "active": busy_workers,
                "open": len(chat_worker_rows),
                "busy": busy_workers,
                "idle": idle_workers,
                "maximum": MAX_WORKERS,
                "minimum_warm": MIN_WARM_WORKERS,
                "queued": _POOL_WAITERS,
                "idle_ttl_seconds": IDLE_WORKER_TTL_SECONDS,
            },
        }

    async def close_worker_window(self, target_id: str) -> Dict[str, Any]:
        """Close one idle Hub worker, never the primary or a busy worker."""
        async with _window_lock():
            port = await self.get_devtools_port()
            workers, _ = await self._discover_window_pool(port)
            target = next(
                (
                    worker
                    for worker in workers
                    if str(worker.get("id") or "") == target_id
                ),
                None,
            )
            if target is None:
                return {"success": False, "found": False}
            state = _worker_state(target_id)
            runtime = target.get("runtime") or {}
            if runtime.get("has_draft"):
                return {
                    "success": False,
                    "found": True,
                    "has_draft": True,
                    "window_id": state.get("window_id"),
                    "state": state.get("state"),
                }
            activity, _ = _reconcile_worker_activity(state, runtime)
            if not _worker_is_safely_idle(target_id, state, runtime):
                return {
                    "success": False,
                    "found": True,
                    "busy": bool(
                        state.get("reserved")
                        or activity in _BUSY_WORKER_STATES
                        or _target_lock(target_id).locked()
                    ),
                    "not_idle": True,
                    "window_id": state.get("window_id"),
                    "state": activity,
                    "reason": (
                        "runtime_unreachable"
                        if runtime.get("runtime_reachable") is not True
                        else "activity_not_idle"
                    ),
                }
            window_id = state.get("window_id")
            await self.close_target_window(target)
            return {
                "success": True,
                "found": True,
                "target_id": target_id,
                "window_id": window_id,
            }

    async def _get_window_role(self, target: Dict[str, Any]) -> Optional[str]:
        """Read the native role exposed by repacked Antigravity builds."""
        try:
            client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
            role = await client.evaluate(
                "window.electronNative?.getWindowRole?.() ?? null",
                timeout=3,
            )
            return role if role in {"primary", "duplicate"} else None
        except Exception:
            # Older Antigravity builds do not expose a role yet. The managed-target
            # fallback below remains safe for every duplicate created in this run.
            return None

    async def prepare_target_for_automation(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """Wake a duplicate renderer before CDP navigation, without stealing focus."""
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        for _ in range(40):
            supported = await client.evaluate(
                "typeof window.electronNative?.prepareAutomation === 'function'",
                timeout=3,
            )
            if supported:
                result = await client.evaluate(
                    "window.electronNative.prepareAutomation()",
                    timeout=5,
                )
                if not result or not result.get("success"):
                    raise RuntimeError(
                        f"Antigravity could not wake the automation window: {result}"
                    )
                return result
            await asyncio.sleep(0.25)
        raise RuntimeError(
            "The installed Anti-Gravity build does not expose "
            "electronNative.prepareAutomation(). Repack/update Anti-Gravity "
            "before using minimized Hub workers."
        )

    async def _select_primary_source(
        self,
        targets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Select a primary desktop window, never a Hub-managed duplicate."""
        global _PRIMARY_TARGET_ID

        by_id = {target.get("id"): target for target in targets if target.get("id")}
        if _PRIMARY_TARGET_ID in by_id:
            return by_id[_PRIMARY_TARGET_ID]

        for target in targets:
            role = await self._get_window_role(target)
            target_id = target.get("id")
            if role == "duplicate" and target_id:
                _DUPLICATE_TARGET_IDS.add(target_id)
            elif role == "primary":
                _PRIMARY_TARGET_ID = target_id
                return target

        managed_ids = _DUPLICATE_TARGET_IDS | set(_CHAT_TARGET_IDS.values())
        candidates = [target for target in targets if target.get("id") not in managed_ids]
        if not candidates:
            raise ConnectionError(
                "No primary Antigravity desktop window is available for duplication."
            )

        # Chromium lists newer page targets first. On legacy app builds without the
        # native role API, the oldest unmanaged target is the safest primary fallback.
        source = candidates[-1]
        _PRIMARY_TARGET_ID = source.get("id")
        return source

    async def open_duplicate_window(self, port: Optional[int] = None) -> Dict[str, Any]:
        """Open a duplicate desktop window and return its new CDP page target."""
        port = port or await self.get_devtools_port()
        before = await self.get_all_page_targets(port)
        if not before:
            raise ConnectionError("No active Antigravity desktop window found.")

        before_ids = {target.get("id") for target in before}
        source = await self._select_primary_source(before)
        client = await self.get_client_for_target(source["webSocketDebuggerUrl"])
        supported = await client.evaluate(
            "typeof window.electronNative?.openDuplicateWindow === 'function'",
            timeout=5,
        )
        if not supported:
            raise RuntimeError(
                "The installed Antigravity app does not expose duplicate-window support."
            )

        result = await client.evaluate(
            "window.electronNative.openDuplicateWindow()",
            timeout=10,
        )
        if not result or not result.get("success"):
            raise RuntimeError(f"Antigravity did not create a duplicate window: {result}")

        for _ in range(48):
            await asyncio.sleep(0.25)
            targets = await self.get_all_page_targets(port)
            duplicate = next(
                (target for target in targets if target.get("id") not in before_ids),
                None,
            )
            if duplicate:
                target_id = duplicate.get("id")
                if target_id:
                    _DUPLICATE_TARGET_IDS.add(target_id)
                    duplicate["window_id"] = self.get_window_stamp(target_id)
                return duplicate

        raise TimeoutError("The duplicate Antigravity window did not expose a CDP target.")

    async def ensure_dictation_window(self) -> Dict[str, Any]:
        """Return the single Hub-owned window reserved for native dictation."""
        global _DICTATION_TARGET_ID

        async with _window_lock():
            port = await self.get_devtools_port()
            workers, _ = await self._discover_window_pool(port)
            target = next(
                (
                    worker
                    for worker in workers
                    if (
                        str(worker.get("id") or "") == str(_DICTATION_TARGET_ID or "")
                        or _worker_state(str(worker.get("id") or "")).get("purpose")
                        == "dictation"
                        or (worker.get("runtime") or {}).get("purpose") == "dictation"
                    )
                ),
                None,
            )
            created = target is None
            if target is None:
                target = await self.open_duplicate_window(port)
                target["runtime"] = {}

            target_id = str(target.get("id") or "")
            if not target_id:
                raise RuntimeError("The dictation window has no stable target ID.")
            _DICTATION_TARGET_ID = target_id
            _DUPLICATE_TARGET_IDS.add(target_id)
            window_id = await self.apply_window_stamp(
                target,
                preferred_stamp="AG-DIKTAT",
                purpose="dictation",
            )
            self._set_worker_state(
                target_id,
                "dictation_preparing",
                chat_id="",
                detail="Diktatfenster wird vorbereitet",
                reserved=True,
                purpose="dictation",
            )

        try:
            async with _target_lock(target_id):
                await self.prepare_target_for_automation(target)
                client = await self.get_client_for_target(
                    target["webSocketDebuggerUrl"]
                )
                await client.inject_bridge()
                runtime = await self._inspect_target_runtime(target)
                composer = await client.evaluate(
                    "window.__agBridge?.getComposerState?.() ?? "
                    "{ready: false, reason: 'bridge-unavailable'}",
                    timeout=5,
                )
                if runtime.get("chat_id") or not (
                    isinstance(composer, dict) and composer.get("ready")
                ):
                    if not await self._wait_for_button_text(
                        client,
                        "New Conversation",
                        attempts=120,
                    ):
                        raise TimeoutError(
                            "The global New Conversation action did not become ready "
                            "for dictation."
                        )
                    started = await client.evaluate(
                        "window.__agBridge.startNewConversation()",
                        timeout=15,
                    )
                    if started is False:
                        raise RuntimeError(
                            "Anti-Gravity did not open the neutral dictation composer."
                        )
                    await self._wait_for_message_composer(client)

                cleared = await client.evaluate(
                    "window.__agBridge.clearVoiceDraft()",
                    timeout=5,
                )
                if cleared is False:
                    raise RuntimeError(
                        "The dictation composer could not be cleared safely."
                    )
                self._set_worker_state(
                    target_id,
                    "dictation_ready",
                    chat_id="",
                    detail="Mikrofon bereit",
                    reserved=True,
                    purpose="dictation",
                )
                target["window_id"] = window_id
                target["purpose"] = "dictation"
                target["created"] = created
                return target
        except Exception as exc:
            self._set_worker_state(
                target_id,
                "error",
                chat_id="",
                detail="Diktatfenster fehlgeschlagen",
                reserved=False,
                purpose="dictation",
                error=str(exc),
            )
            raise

    def set_dictation_state(
        self,
        target_id: str,
        state_name: str,
        detail: str,
        *,
        reserved: bool,
        error: str = "",
    ) -> Dict[str, Any]:
        """Expose one typed state update for the voice controller."""
        return self._set_worker_state(
            target_id,
            state_name,
            chat_id="",
            detail=detail,
            reserved=reserved,
            purpose="dictation",
            error=error,
        )

    async def close_dictation_window(self) -> bool:
        """Close the reserved dictation window if it is still alive."""
        global _DICTATION_TARGET_ID

        async with _window_lock():
            port = await self.get_devtools_port()
            workers, _ = await self._discover_window_pool(port)
            target = next(
                (
                    worker
                    for worker in workers
                    if (
                        str(worker.get("id") or "") == str(_DICTATION_TARGET_ID or "")
                        or _worker_state(str(worker.get("id") or "")).get("purpose")
                        == "dictation"
                    )
                ),
                None,
            )
            if target is None:
                _DICTATION_TARGET_ID = None
                return False
            await self.close_target_window(target)
            _DICTATION_TARGET_ID = None
            return True

    @staticmethod
    async def _wait_for_button_text(
        client: AntigravityCDP,
        text: str,
        attempts: int = 48,
    ) -> bool:
        if text == "New Conversation":
            for _ in range(attempts):
                await client.inject_bridge()
                ready = await client.evaluate(
                    "window.__agBridge?.hasNewConversationAction?.() === true",
                    timeout=3,
                )
                if ready:
                    return True
                await asyncio.sleep(0.25)
            return False

        escaped_text = json.dumps(text)
        for _ in range(attempts):
            match_count = await client.evaluate(
                "(() => {"
                + _semantic_action_matches_js(escaped_text)
                + "return matches.length;"
                + "})()",
                timeout=3,
            )
            if match_count == 1:
                return True
            await asyncio.sleep(0.25)
        return False

    @staticmethod
    async def _wait_for_button_unavailable(
        client: AntigravityCDP,
        text: str,
        attempts: int = 40,
    ) -> bool:
        """Confirm that one wizard action left its actionable UI state."""
        escaped_text = json.dumps(text)
        for _ in range(attempts):
            match_count = await client.evaluate(
                "(() => {"
                + _semantic_action_matches_js(escaped_text)
                + "return matches.length;"
                + "})()",
                timeout=3,
            )
            if match_count == 0:
                return True
            await asyncio.sleep(0.25)
        return False

    @staticmethod
    async def _click_text(client: AntigravityCDP, text: str) -> bool:
        escaped_text = json.dumps(text)
        return bool(
            await client.evaluate(
                "(() => {"
                + _semantic_action_matches_js(escaped_text)
                + "if (matches.length !== 1) return false;"
                + "const item = matches[0];"
                + "item.click();"
                + "return true;"
                + "})()",
                timeout=5,
            )
        )

    @staticmethod
    def _choose_project_entry(
        details: List[Dict[str, Any]],
        workspace_path: str,
        project_name: str = "",
        allow_basename: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Resolve one sidebar row without conflating a label with a full path."""
        def normalize(value: Any) -> str:
            return (
                str(value or "")
                .strip()
                .replace("/", "\\")
                .rstrip("\\")
                .lower()
            )

        wanted_path = normalize(Path(workspace_path).resolve())
        wanted_name = normalize(Path(workspace_path).name)
        wanted_project_name = normalize(project_name)
        entries = [
            {**entry, "normalized": normalize(entry.get("text"))}
            for entry in details
        ]

        if wanted_project_name:
            name_matches = [
                entry for entry in entries
                if entry["normalized"] == wanted_project_name
            ]
            if len(name_matches) == 1:
                return name_matches[0]
            if name_matches:
                return None

        path_matches = [
            entry for entry in entries
            if entry["normalized"] == wanted_path
        ]
        if len(path_matches) == 1:
            return path_matches[0]
        if path_matches or not allow_basename:
            return None

        basename_matches = [
            entry for entry in entries
            if entry["normalized"] == wanted_name
            or entry["normalized"].endswith("\\" + wanted_name)
        ]
        return basename_matches[0] if len(basename_matches) == 1 else None

    @staticmethod
    async def _project_button(
        client: AntigravityCDP,
        workspace_path: str,
        click: bool = False,
        allow_basename: bool = False,
        project_name: str = "",
    ) -> Dict[str, Any]:
        details = await client.evaluate(
            """(() => {
          const controlSelector =
            'button[aria-label="New Conversation in Project"], '
            + 'a[aria-label="New Conversation in Project"]';
          const controls = Array.from(document.querySelectorAll(controlSelector));
          const orderedHeaders = Array.from(document.querySelectorAll(
            'button[data-project-card="true"]'
          ));
          const projectHeaderFor = control => {
            let container = control.parentElement;
            while (container) {
              const headers = Array.from(container.querySelectorAll(
                'button[data-project-card="true"]'
              ));
              if (headers.length === 1) return headers[0];
              if (headers.length > 1) break;
              container = container.parentElement;
            }
            return control.parentElement?.closest('[role="button"]') || null;
          };
          const projectControlFor = header => {
            let container = header.parentElement;
            while (container) {
              const headers = Array.from(container.querySelectorAll(
                'button[data-project-card="true"]'
              ));
              const candidates = Array.from(
                container.querySelectorAll(controlSelector)
              );
              if (headers.length === 1 && headers[0] === header
                  && candidates.length === 1) {
                return candidates[0];
              }
              if (headers.length > 1) break;
              container = container.parentElement;
            }
            return null;
          };
          if (orderedHeaders.length
              && orderedHeaders.every(header => (header.innerText || '').trim())) {
            return orderedHeaders.map((header, headerIndex) => {
              const control = projectControlFor(header);
              return {
                index: control ? controls.indexOf(control) : -1,
                header_index: headerIndex,
                text: (header.innerText || '').trim(),
                expanded: header.getAttribute('aria-expanded'),
                has_control: Boolean(control)
              };
            });
          }
          const entries = controls.map((control, index) => {
            const ancestorHeader = projectHeaderFor(control);
            const text = (ancestorHeader?.innerText || '').trim();
            return { index, text };
          });
          return entries;
        })()""",
            timeout=5,
        )
        details = details if isinstance(details, list) else []
        catalog_ready = bool(details) and all(
            isinstance(entry, dict) and str(entry.get("text") or "").strip()
            for entry in details
        )
        if not catalog_ready:
            return {
                "success": False,
                "catalog_ready": False,
                "details": details,
            }
        match = ParallelCDPManager._choose_project_entry(
            details,
            workspace_path,
            project_name=project_name,
            allow_basename=allow_basename,
        )
        if not match:
            return {"success": False, "details": details}

        if click:
            clicked = await client.evaluate(
                f"""(async () => {{
                  const controlSelector =
                    'button[aria-label="New Conversation in Project"], '
                    + 'a[aria-label="New Conversation in Project"]';
                  const controls = () => Array.from(
                    document.querySelectorAll(controlSelector)
                  );
                  const orderedHeaders = Array.from(document.querySelectorAll(
                    'button[data-project-card="true"]'
                  ));
                  const projectControlFor = header => {{
                    let container = header.parentElement;
                    while (container) {{
                      const headers = Array.from(container.querySelectorAll(
                        'button[data-project-card="true"]'
                      ));
                      const candidates = Array.from(
                        container.querySelectorAll(controlSelector)
                      );
                      if (headers.length === 1 && headers[0] === header
                          && candidates.length === 1) {{
                        return candidates[0];
                      }}
                      if (headers.length > 1) break;
                      container = container.parentElement;
                    }}
                    return null;
                  }};
                  const matchingHeaders = orderedHeaders.filter(
                    header => (header.innerText || '').trim()
                      === {json.dumps(match["text"])}
                  );
                  if (matchingHeaders.length === 1) {{
                    const header = matchingHeaders[0];
                    let control = projectControlFor(header);
                    if (!control && header.getAttribute('aria-expanded') === 'false') {{
                      header.click();
                    }}
                    const deadline = Date.now() + 2000;
                    while (!control && Date.now() < deadline) {{
                      await new Promise(resolve => setTimeout(resolve, 50));
                      control = projectControlFor(header);
                    }}
                    if (!control && orderedHeaders.length === controls().length) {{
                      control = controls()[orderedHeaders.indexOf(header)] || null;
                    }}
                    if (!control || control.disabled
                        || control.getAttribute('aria-disabled') === 'true') {{
                      return false;
                    }}
                    control.click();
                    return true;
                  }}

                  const control = controls()[{int(match["index"])}];
                  if (!control) return false;
                  let container = control.parentElement;
                  let legacyHeader = null;
                  while (container) {{
                    const headers = Array.from(container.querySelectorAll(
                      'button[data-project-card="true"]'
                    ));
                    if (headers.length === 1) {{
                      legacyHeader = headers[0];
                      break;
                    }}
                    if (headers.length > 1) break;
                    container = container.parentElement;
                  }}
                  legacyHeader = legacyHeader
                    || control.parentElement?.closest('[role="button"]')
                    || null;
                  if ((legacyHeader?.innerText || '').trim()
                      !== {json.dumps(match["text"])}) {{
                    return false;
                  }}
                  control.click();
                  return true;
                }})()""",
                timeout=5,
            )
            if clicked is False:
                return {
                    "success": False,
                    "details": details,
                    "error": "Project sidebar changed before it could be clicked.",
                }

        return {
            "success": True,
            "text": match["text"],
            "index": match["index"],
            "details": details,
        }

    @staticmethod
    async def _active_project_context(
        client: AntigravityCDP,
        workspace_path: str,
        *,
        allow_basename: bool = False,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Read the active empty-composer project before its sidebar row exists."""
        state = await client.evaluate(
            """(() => {
              const projectSelector = document.querySelector(
                'button[data-testid="project-selector-trigger"]'
              );
              const composer = window.__agBridge?.findInput?.()
                || document.querySelector(
                  '[role="combobox"][aria-label="Message input"], '
                  + '[role="combobox"][contenteditable="true"], '
                  + '[contenteditable="true"], textarea'
                );
              const visible = element => Boolean(
                element
                && element.offsetParent !== null
                && !element.closest(
                  '[aria-hidden="true"],[inert],[data-state="closed"]'
                )
              );
              return {
                text: (projectSelector?.innerText || '').trim(),
                selector_visible: visible(projectSelector),
                composer_visible: visible(composer),
                composer_text: String(
                  composer?.innerText || composer?.textContent || composer?.value || ''
                ).trim()
              };
            })()""",
            timeout=5,
        )
        state = state if isinstance(state, dict) else {}
        text = str(state.get("text") or "").strip()
        details = [{"index": 0, "text": text}] if text else []
        if not (
            state.get("selector_visible")
            and state.get("composer_visible")
            and text
        ):
            return {
                "success": False,
                "active_context": False,
                "details": details,
                "state": state,
            }
        match = ParallelCDPManager._choose_project_entry(
            details,
            workspace_path,
            project_name=project_name,
            allow_basename=allow_basename,
        )
        if not match:
            return {
                "success": False,
                "active_context": False,
                "details": details,
                "state": state,
            }
        return {
            "success": True,
            "active_context": True,
            "sidebar_materialized": False,
            "text": match["text"],
            "index": match["index"],
            "details": details,
            "state": state,
        }

    @staticmethod
    async def _project_sidebar_state(
        client: AntigravityCDP,
        scroll_top: Optional[float] = None,
    ) -> Dict[str, Any]:
        requested_scroll = (
            "null" if scroll_top is None else json.dumps(float(scroll_top))
        )
        result = await client.evaluate(
            f"""(() => {{
              const sidebar = document.querySelector(
                '[data-testid="conversation-list-sidebar"]'
              );
              if (!sidebar) return {{ available: false }};
              const requestedScroll = {requested_scroll};
              if (Number.isFinite(requestedScroll)) {{
                const maxScroll = Math.max(
                  0,
                  sidebar.scrollHeight - sidebar.clientHeight
                );
                sidebar.scrollTop = Math.max(
                  0,
                  Math.min(requestedScroll, maxScroll)
                );
                sidebar.dispatchEvent(new Event('scroll', {{ bubbles: true }}));
              }}
              return {{
                available: true,
                scroll_top: Number(sidebar.scrollTop || 0),
                scroll_height: Number(sidebar.scrollHeight || 0),
                client_height: Number(sidebar.clientHeight || 0)
              }};
            }})()""",
            timeout=5,
        )
        return result if isinstance(result, dict) else {"available": False}

    @staticmethod
    def _project_sidebar_scroll_positions(
        state: Dict[str, Any],
    ) -> List[float]:
        scroll_height = max(0.0, float(state.get("scroll_height") or 0.0))
        client_height = max(0.0, float(state.get("client_height") or 0.0))
        max_scroll = max(0.0, scroll_height - client_height)
        original = min(
            max(0.0, float(state.get("scroll_top") or 0.0)),
            max_scroll,
        )
        if max_scroll <= 1.0:
            return [original]

        step = max(120.0, client_height * 0.75)
        max_sweep_positions = max(
            2,
            PROJECT_SIDEBAR_MAX_SCROLL_POSITIONS - 1,
        )
        position_count = min(
            max_sweep_positions,
            max(2, int(max_scroll // step) + 2),
        )
        sweep = [
            max_scroll * index / (position_count - 1)
            for index in range(position_count)
        ]
        positions: List[float] = []
        seen: set[int] = set()
        for position in [original, *sweep]:
            rounded = int(round(position))
            if rounded in seen:
                continue
            seen.add(rounded)
            positions.append(float(rounded))
        return positions

    async def _find_linked_project_in_sidebar(
        self,
        client: AntigravityCDP,
        workspace_path: str,
        project_name: str,
        *,
        click: bool = False,
    ) -> Dict[str, Any]:
        """Find, and optionally click, one exact project across a virtual sidebar."""
        deadline = time.monotonic() + PROJECT_LINKED_VISIBILITY_TIMEOUT_SECONDS
        original_scroll: Optional[float] = None
        current_scroll: Optional[float] = None
        found = False
        last_project: Dict[str, Any] = {
            "success": False,
            "catalog_ready": False,
            "details": [],
        }
        observed: Dict[str, Dict[str, Any]] = {}

        def remember(project: Dict[str, Any]) -> None:
            for detail in project.get("details", []):
                if not isinstance(detail, dict):
                    continue
                text = str(detail.get("text") or "").strip()
                if text:
                    observed.setdefault(text.casefold(), dict(detail))

        try:
            while True:
                last_project = await self._project_button(
                    client,
                    workspace_path,
                    click=click,
                    project_name=project_name,
                )
                remember(last_project)
                if last_project.get("success"):
                    found = True
                    return last_project
                if time.monotonic() >= deadline:
                    break

                state = await self._project_sidebar_state(client)
                if state.get("available"):
                    current_scroll = float(state.get("scroll_top") or 0.0)
                    if original_scroll is None:
                        original_scroll = current_scroll
                    for position in self._project_sidebar_scroll_positions(state):
                        if time.monotonic() >= deadline:
                            break
                        if abs(position - current_scroll) < 1.0:
                            continue
                        moved = await self._project_sidebar_state(client, position)
                        if not moved.get("available"):
                            break
                        current_scroll = float(moved.get("scroll_top") or position)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        await asyncio.sleep(
                            min(PROJECT_SIDEBAR_SCROLL_RENDER_SECONDS, remaining)
                        )
                        last_project = await self._project_button(
                            client,
                            workspace_path,
                            click=click,
                            project_name=project_name,
                        )
                        remember(last_project)
                        if last_project.get("success"):
                            found = True
                            return last_project

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(PROJECT_VISIBILITY_POLL_SECONDS, remaining))

            if observed:
                last_project = {
                    **last_project,
                    "details": list(observed.values()),
                }
            last_project["virtual_scroll_searched"] = True
            return last_project
        finally:
            if not found and original_scroll is not None:
                try:
                    await self._project_sidebar_state(client, original_scroll)
                except Exception:
                    pass

    async def ensure_project_in_window(
        self,
        target: Dict[str, Any],
        workspace_path: str,
        project_name: str = "",
        *,
        stamp_window: bool = True,
    ) -> Dict[str, Any]:
        """Ensure the linked Anti-Gravity project is available in one duplicate window."""
        resolved_path = str(Path(workspace_path).resolve())
        if not Path(resolved_path).is_dir():
            raise FileNotFoundError(f"Workspace directory does not exist: {resolved_path}")

        await self.prepare_target_for_automation(target)
        if stamp_window:
            await self.apply_window_stamp(target)
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        if not await self._wait_for_button_text(client, "File"):
            raise TimeoutError("The duplicate Antigravity UI did not become ready.")

        existing: Dict[str, Any] = {"success": False, "details": []}
        if project_name:
            existing = await self._find_linked_project_in_sidebar(
                client,
                resolved_path,
                project_name,
            )
            if existing.get("success"):
                return {"imported": False, "project": existing}
            raise TimeoutError(
                f"Linked Anti-Gravity project {project_name!r} did not become "
                f"visible within {PROJECT_LINKED_VISIBILITY_TIMEOUT_SECONDS:g} "
                "seconds after searching the virtualized sidebar. "
                f"Visible projects: {existing.get('details', [])}"
            )

        for _ in range(40):
            existing = await self._project_button(client, resolved_path)
            if existing.get("success"):
                return {"imported": False, "project": existing}
            await asyncio.sleep(0.25)

        supported = await client.evaluate(
            "typeof window.electronNative?.prepareWorkspaceOpen === 'function'",
            timeout=5,
        )
        if not supported:
            raise RuntimeError(
                "The installed Antigravity app does not expose secure workspace selection."
            )

        prepared = await client.evaluate(
            f"window.electronNative.prepareWorkspaceOpen({json.dumps(resolved_path)})",
            timeout=10,
        )
        if not prepared or not prepared.get("success"):
            raise RuntimeError(f"Antigravity rejected the workspace path: {prepared}")

        if not await self._click_text(client, "File"):
            raise RuntimeError("The File menu could not be opened.")
        if not await self._wait_for_button_text(client, "Create Project"):
            raise TimeoutError("The File menu did not expose Create Project.")
        if not await self._click_text(client, "Create Project"):
            raise RuntimeError("The Create Project action was not available.")
        if not await self._wait_for_button_text(client, "Add Folder"):
            raise TimeoutError("The Create Project wizard did not become ready.")
        if not await self._click_text(client, "Add Folder"):
            raise RuntimeError("The prepared workspace folder could not be selected.")
        if not await self._wait_for_button_text(client, "Next"):
            raise TimeoutError("Antigravity did not accept the selected workspace folder.")
        if not await self._click_text(client, "Next"):
            raise RuntimeError("The Create Project wizard could not be completed.")
        if not await self._wait_for_button_unavailable(client, "Next"):
            raise TimeoutError(
                "The Create Project wizard did not advance after Next. No "
                "project import was confirmed; retrying is safe."
            )

        reused_existing = False
        visibility_deadline = (
            time.monotonic() + PROJECT_CREATION_VISIBILITY_TIMEOUT_SECONDS
        )
        project = existing
        while True:
            remaining = visibility_deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(PROJECT_VISIBILITY_POLL_SECONDS, remaining))
            if (
                not reused_existing
                and await self._click_text(client, "Use Existing")
            ):
                reused_existing = True
                transitioned = await self._wait_for_button_unavailable(
                    client,
                    "Use Existing",
                )
                if not transitioned:
                    project = await self._project_button(
                        client,
                        resolved_path,
                        allow_basename=True,
                        project_name=project_name,
                    )
                    if project.get("success"):
                        return {
                            "imported": False,
                            "reused_existing": True,
                            "project": project,
                        }
                    raise TimeoutError(
                        "Anti-Gravity did not advance after Use Existing. No "
                        "existing project reuse was confirmed; retrying is safe."
                    )
                await asyncio.sleep(0.5)
            project = await self._project_button(
                client,
                resolved_path,
                allow_basename=True,
                project_name=project_name,
            )
            if project.get("success"):
                return {
                    "imported": not reused_existing,
                    "reused_existing": reused_existing,
                    "project": project,
                }
            active_project = await self._active_project_context(
                client,
                resolved_path,
                allow_basename=True,
                project_name=project_name,
            )
            if active_project.get("success"):
                return {
                    "imported": not reused_existing,
                    "reused_existing": reused_existing,
                    "project": active_project,
                }

        # One final read is intentionally separate from the polling deadline. A
        # sidebar render that lands on the boundary must not turn a successful,
        # idempotent import into a 503 response.
        project = await self._project_button(
            client,
            resolved_path,
            allow_basename=True,
            project_name=project_name,
        )
        if project.get("success"):
            return {
                "imported": not reused_existing,
                "reused_existing": reused_existing,
                "project": project,
            }
        active_project = await self._active_project_context(
            client,
            resolved_path,
            allow_basename=True,
            project_name=project_name,
        )
        if active_project.get("success"):
            return {
                "imported": not reused_existing,
                "reused_existing": reused_existing,
                "project": active_project,
            }

        expected_project = project_name or resolved_path
        raise TimeoutError(
            f"Workspace {resolved_path} was selected, but Anti-Gravity did not "
            f"show project {expected_project!r} within "
            f"{PROJECT_CREATION_VISIBILITY_TIMEOUT_SECONDS:g} seconds. The "
            "import may still be finishing; retrying this request is safe and "
            "will reuse the project if it appears. Last visible projects: "
            f"{project.get('details', [])}"
        )

    async def ensure_project_in_primary(
        self,
        workspace_path: str,
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Create or locate a project in the primary Anti-Gravity window."""
        port = await self.get_devtools_port()
        targets = await self.get_all_page_targets(port)
        if not targets:
            raise ConnectionError("No active Anti-Gravity desktop window found.")
        target = await self._select_primary_source(targets)
        target_id = str(target.get("id") or "")
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        await client.evaluate(
            """(() => {
              sessionStorage.removeItem('antigravityHubWindowId');
              sessionStorage.removeItem('antigravityHubWindowPurpose');
              delete window.__antigravityHubWindowId;
              delete window.__antigravityHubWindowPurpose;
              document.getElementById('antigravity-hub-window-stamp')?.remove();
              return true;
            })()""",
            timeout=5,
        )
        if target_id:
            _WINDOW_STAMPS.pop(target_id, None)
            _DUPLICATE_TARGET_IDS.discard(target_id)
            _WORKER_STATES.pop(target_id, None)
        result = await self.ensure_project_in_window(
            target,
            workspace_path,
            project_name=project_name,
            stamp_window=False,
        )
        result["target_id"] = target.get("id")
        return result

    async def read_native_models_from_primary(self) -> Dict[str, Any]:
        """Read the live model combobox from the primary Anti-Gravity window."""
        async with _window_lock():
            port = await self.get_devtools_port()
            targets = await self.get_all_page_targets(port)
            if not targets:
                raise ConnectionError("No active Anti-Gravity desktop window found.")
            target = await self._select_primary_source(targets)
            await self.prepare_target_for_automation(target)
            client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
            await client.inject_bridge()
            result = await client.evaluate(
                "window.__agBridge.getAvailableModels()",
                timeout=10,
            )
            if not result or not result.get("success"):
                raise RuntimeError(
                    f"Anti-Gravity model combobox could not be read: {result}"
                )
            return {
                "current": str(result.get("current") or ""),
                "models": list(result.get("models") or []),
                "target_id": target.get("id"),
            }

    async def disconnect_all(self) -> None:
        """Close every CDP connection owned by this manager."""
        for client in list(self.clients.values()):
            await client.disconnect()
        self.clients.clear()

    @staticmethod
    async def _wait_for_message_composer(
        client: AntigravityCDP,
        *,
        attempts: int = WORKER_WAIT_TIMEOUT_SECONDS * 4,
    ) -> Dict[str, Any]:
        await client.inject_bridge()
        last_state: Dict[str, Any] = {}
        for _ in range(attempts):
            await asyncio.sleep(0.25)
            result = await client.evaluate(
                "window.__agBridge?.getComposerState?.() ?? "
                "{ready: false, reason: 'bridge-unavailable'}",
                timeout=3,
            )
            if isinstance(result, dict):
                last_state = result
                ready = bool(result.get("ready"))
            else:
                ready = bool(result)
                last_state = {"ready": ready}
            if ready:
                return last_state
        raise TimeoutError(
            "The Anti-Gravity composer did not become stable and editable. "
            f"Last state: {last_state}"
        )

    async def _enter_message_with_retries(
        self,
        client: AntigravityCDP,
        *,
        target_id: str,
        chat_id: str,
        message: str,
        attempts: int = 3,
    ) -> int:
        last_diagnostics: Dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            await self._wait_for_message_composer(
                client,
                attempts=WORKER_WAIT_TIMEOUT_SECONDS * 4,
            )
            active_id = await client.get_active_conversation_id()
            if active_id != chat_id:
                raise RuntimeError(
                    f"Worker {_window_stamp(target_id)} changed to chat "
                    f"{active_id!r}, expected {chat_id!r}."
                )
            await client.inject_bridge()
            if await client.set_input_text_native(message):
                active_after_input = await client.get_active_conversation_id()
                if active_after_input != chat_id:
                    raise RuntimeError(
                        f"Worker {_window_stamp(target_id)} changed to chat "
                        f"{active_after_input!r} while entering the message; "
                        f"expected {chat_id!r}."
                    )
                return attempt

            last_diagnostics = await client.evaluate(
                "window.__agBridge?.diagnose?.() ?? {}",
                timeout=5,
            )
            if attempt < attempts:
                self._set_worker_state(
                    target_id,
                    "sending",
                    chat_id=chat_id,
                    detail=f"Composer wird synchronisiert · Versuch {attempt + 1}/{attempts}",
                    reserved=True,
                )
                await asyncio.sleep(0.5 * attempt)

        raise RuntimeError(
            "Antigravity did not accept text in the composer after "
            f"{attempts} synchronized attempts. "
            f"Worker diagnostics: {last_diagnostics}"
        )

    @staticmethod
    async def _submit_first_message(
        client: AntigravityCDP,
        message: str,
        attachment_paths: Optional[List[str]] = None,
    ) -> tuple[str, Any]:
        from src.integrity_sync import get_integrity_chat_history

        attachment_paths = list(attachment_paths or [])
        if not message.strip() and not attachment_paths:
            raise ValueError(
                "The first chat message must contain text or an attachment."
            )

        await client.inject_bridge()
        if message:
            last_diagnostics: Dict[str, Any] = {}
            for attempt in range(1, 4):
                await ParallelCDPManager._wait_for_message_composer(client)
                if await client.set_input_text_native(message):
                    break
                last_diagnostics = await client.evaluate(
                    "window.__agBridge?.diagnose?.() ?? {}",
                    timeout=5,
                )
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)
            else:
                raise RuntimeError(
                    "Antigravity did not accept the first message text after "
                    "3 synchronized attempts. "
                    f"Diagnostics: {last_diagnostics}"
                )
        if attachment_paths:
            await client.set_file_input_files(attachment_paths)
        submitted = await client.evaluate(
            "window.__agBridge.prepareAndSend('')",
            timeout=30,
        )
        if isinstance(submitted, dict) and submitted.get("error"):
            raise RuntimeError(
                f"Antigravity did not submit the first message: {submitted}"
            )

        convo_id = None
        for _ in range(80):
            await asyncio.sleep(0.25)
            convo_id = await client.get_active_conversation_id()
            if convo_id:
                break
        if not convo_id:
            raise TimeoutError(
                "Antigravity accepted the first message, but no conversation ID appeared."
            )

        async def delivery_persisted(attempts: int = 40) -> bool:
            for _ in range(attempts):
                history = await asyncio.to_thread(
                    get_integrity_chat_history,
                    convo_id,
                )
                if any(
                    item.get("role") == "user"
                    and str(item.get("content") or "").strip() == message.strip()
                    and (
                        not attachment_paths
                        or len(item.get("attachments") or [])
                        >= len(attachment_paths)
                    )
                    for item in history.get("history", [])
                ):
                    return True
                await asyncio.sleep(0.25)
            return False

        delivery_verified = await delivery_persisted()
        if not delivery_verified and submitted is None:
            # Clicking Send can replace the renderer before Runtime.evaluate
            # returns. Wait longer for native persistence, but never click Send
            # again because that could duplicate the first user message.
            delivery_verified = await delivery_persisted(attempts=80)

        if not delivery_verified:
            raise RuntimeError(
                "Antigravity created the chat, but the first message was not persisted."
            )
        return convo_id, submitted

    async def _finalize_created_chat_window(
        self,
        target: Dict[str, Any],
        convo_id: str,
        *,
        minimize: bool,
    ) -> Dict[str, Any]:
        target_id = str(target.get("id") or "")
        if not target_id:
            raise RuntimeError("The duplicate window has no stable target ID.")

        warnings: List[str] = []
        try:
            window_id = await self.apply_window_stamp(target)
        except Exception as exc:
            window_id = self.get_window_stamp(target_id)
            warnings.append(
                "The message was persisted, but the Anti-Gravity worker stamp "
                f"could not be refreshed: {exc}"
            )
        minimized = False
        if minimize:
            try:
                client = await self.get_client_for_target(
                    target["webSocketDebuggerUrl"]
                )
                minimized = bool(
                    await client.evaluate(
                        "(async () => { if (typeof window.electronNative?.minimize !== 'function') "
                        "return false; await window.electronNative.minimize(); return true; })()",
                        timeout=5,
                    )
                )
            except Exception as exc:
                warnings.append(
                    "The new chat and its first message were persisted, but the "
                    f"worker could not be minimized: {exc}"
                )
            if not minimized and not any("could not be minimized" in item for item in warnings):
                warnings.append(
                    "The new chat and its first message were persisted, but the "
                    "worker could not be minimized."
                )

        self.bind_chat_target(convo_id, target_id)
        self._start_worker_monitor(target_id, convo_id)
        return {
            "target_id": target_id,
            "window_id": window_id,
            "chat_id": convo_id,
            "ready": True,
            "minimized": minimized,
            "reused": False,
            "warning": " ".join(warnings),
            "warnings": warnings,
        }

    async def create_project_chat_with_message(
        self,
        target: Dict[str, Any],
        workspace_path: str,
        message: str,
        minimize: bool = True,
        project_name: str = "",
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a real project chat by sending its first message through the UI."""
        attachment_paths = list(attachment_paths or [])
        if not message.strip() and not attachment_paths:
            raise ValueError(
                "The first project-chat message must contain text or an attachment."
            )

        project_info = await self.ensure_project_in_window(
            target,
            workspace_path,
            project_name=project_name,
        )
        project_info["agent_settings"] = await asyncio.to_thread(
            enforce_hub_project_settings,
            workspace_path=workspace_path,
        )
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        confirmed_project = project_info.get("project")
        confirmed_project_name = (
            str(confirmed_project.get("text") or "").strip()
            if isinstance(confirmed_project, dict)
            else ""
        )
        if not confirmed_project_name:
            raise RuntimeError(
                "Anti-Gravity reported the workspace as ready without a stable "
                "project name, so no project conversation was opened."
            )
        if confirmed_project.get("active_context"):
            selected = await self._active_project_context(
                client,
                workspace_path,
                project_name=confirmed_project_name,
            )
        else:
            selected = await self._find_linked_project_in_sidebar(
                client,
                workspace_path,
                confirmed_project_name,
                click=True,
            )
        if not selected.get("success"):
            raise RuntimeError(
                f"The project-specific New Conversation button was not found: {selected}"
            )

        await self._wait_for_message_composer(client)
        convo_id, submitted = await self._submit_first_message(
            client,
            message,
            attachment_paths,
        )
        result = await self._finalize_created_chat_window(
            target,
            convo_id,
            minimize=minimize,
        )
        return {
            **result,
            "project": project_info,
            "submitted": submitted,
            "verified": True,
        }

    async def create_normal_chat_with_message(
        self,
        target: Dict[str, Any],
        message: str,
        minimize: bool = True,
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create one normal conversation outside every project."""
        attachment_paths = list(attachment_paths or [])
        if not message.strip() and not attachment_paths:
            raise ValueError(
                "The first normal-chat message must contain text or an attachment."
            )

        await self.prepare_target_for_automation(target)
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        if not await self._wait_for_button_text(
            client,
            "New Conversation",
            attempts=120,
        ):
            raise TimeoutError(
                "The global New Conversation button did not become ready."
            )
        await client.inject_bridge()
        started = await client.evaluate(
            "window.__agBridge.startNewConversation()",
            timeout=15,
        )
        # A successful click can replace the renderer before Runtime.evaluate
        # returns. Only an explicit false means the semantic button was absent;
        # composer readiness and persisted delivery remain the authoritative gates.
        if started is False:
            raise RuntimeError("The global New Conversation button was not found.")

        await self._wait_for_message_composer(client)
        convo_id, submitted = await self._submit_first_message(
            client,
            message,
            attachment_paths,
        )

        from src.integrity_sync import scan_integrity_convos

        verified_normal = False
        for _ in range(40):
            conversations = await asyncio.to_thread(scan_integrity_convos)
            metadata = next(
                (item for item in conversations if item.get("convo_id") == convo_id),
                None,
            )
            if metadata is not None and not metadata.get("workspace_path"):
                verified_normal = True
                break
            await asyncio.sleep(0.25)
        if not verified_normal:
            raise RuntimeError(
                "Antigravity created the chat, but it was not verified as a normal conversation."
            )

        result = await self._finalize_created_chat_window(
            target,
            convo_id,
            minimize=minimize,
        )
        return {
            **result,
            "project": None,
            "submitted": submitted,
            "verified": True,
        }

    async def navigate_target_to_chat(
        self,
        target: Dict[str, Any],
        chat_id: str,
        minimize: bool = True,
        section: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Navigate one worker to the exact chat without reloading an active route."""
        await self.prepare_target_for_automation(target)
        client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
        active_id = await client.get_active_conversation_id()
        route_reused = active_id == chat_id
        navigation: Dict[str, Any] = {
            "success": True,
            "chat_id": chat_id,
            "route_reused": route_reused,
        }
        if not route_reused:
            navigation = await client.navigate_to_chat(chat_id, section=section)
            if not navigation.get("success"):
                raise RuntimeError(
                    f"Failed to navigate the duplicate window to chat {chat_id}: {navigation}"
                )

        exact_chat_ready = False
        for _ in range(120):
            active_id = await client.get_active_conversation_id()
            if active_id == chat_id:
                exact_chat_ready = True
                break
            await asyncio.sleep(0.25)

        if not exact_chat_ready:
            raise TimeoutError(
                f"Chat {chat_id} did not become active in the selected worker."
            )

        input_ready = bool(
            await client.evaluate(
                "Boolean(window.__agBridge?.findInput?.() || "
                "document.querySelector('[aria-label=\"Message input\"], "
                "[contenteditable=\"true\"][role=\"textbox\"], "
                "[contenteditable=\"true\"][role=\"combobox\"]'))",
                timeout=5,
            )
        )
        window_id = await self.apply_window_stamp(target)

        if minimize:
            minimized = await client.evaluate(
                "(async () => { if (typeof window.electronNative?.minimize !== 'function') return false; await window.electronNative.minimize(); return true; })()",
                timeout=5,
            )
            if not minimized:
                raise RuntimeError("The duplicate chat window could not be minimized.")

        return {
            "target_id": target.get("id"),
            "window_id": window_id,
            "chat_id": chat_id,
            "ready": True,
            "composer_ready": input_ready,
            "minimized": minimize,
            "reused": route_reused,
            "navigation": navigation,
        }

    async def _request_target_window_close(self, target: Dict[str, Any]) -> bool:
        """Ask the native shell to close a target and preserve its confirmation."""
        try:
            client = await self.get_client_for_target(target["webSocketDebuggerUrl"])
            return bool(
                await client.evaluate(
                    "(async () => { if (typeof window.electronNative?.close !== 'function') return false; const closed = await window.electronNative.close(); return closed !== false; })()",
                    timeout=5,
                )
            )
        except Exception as exc:
            print(
                "[ParallelCDPManager] Could not close duplicate window: "
                f"{exc}",
                flush=True,
            )
            return False

    def _forget_target(
        self,
        target_id: str,
        *,
        keep_target_lock: bool = False,
    ) -> None:
        """Remove one confirmed-gone target from Hub-owned process state."""
        global _DICTATION_TARGET_ID

        if _DICTATION_TARGET_ID == target_id:
            _DICTATION_TARGET_ID = None
        _DUPLICATE_TARGET_IDS.discard(target_id)
        _WORKER_STATES.pop(target_id, None)
        _WINDOW_STAMPS.pop(target_id, None)
        if not keep_target_lock:
            _TARGET_LOCKS.pop(target_id, None)
        monitor = _WORKER_MONITORS.pop(target_id, None)
        if monitor and monitor is not asyncio.current_task():
            monitor.cancel()
        self._unbind_target(target_id)

    @staticmethod
    async def _forget_target_lock_when_unused(
        target_id: str,
        target_lock: asyncio.Lock,
    ) -> None:
        """Retire the exact lock after all previously queued users have left."""
        while _TARGET_LOCKS.get(target_id) is target_lock:
            waiters = getattr(target_lock, "_waiters", None)
            if not target_lock.locked() and not waiters:
                _TARGET_LOCKS.pop(target_id, None)
                return
            async with target_lock:
                pass
            await asyncio.sleep(0)

    async def close_target_window(self, target: Dict[str, Any]) -> bool:
        """Close only the desktop window represented by this CDP target."""
        target_id = str(target.get("id") or "")
        confirmed = False
        try:
            confirmed = await self._request_target_window_close(target)
        finally:
            if target_id:
                # Keep the established best-effort cleanup contract for ordinary
                # worker retirement. Deletion uses the stricter atomic seam below.
                self._forget_target(target_id)
        return confirmed

    async def _confirm_target_window_closed(
        self,
        port: int,
        target_id: str,
        *,
        attempts: int = 6,
    ) -> bool:
        """Confirm that CDP no longer exposes a window after native close."""
        for attempt in range(attempts):
            try:
                if await self._get_target_by_id(port, target_id) is None:
                    return True
            except Exception:
                return False
            if attempt + 1 < attempts:
                await asyncio.sleep(0.1)
        return False

    async def _trim_excess_idle_workers(
        self,
        workers: List[Dict[str, Any]],
        *,
        keep_target_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        chat_workers = [
            worker for worker in workers
            if _worker_state(str(worker.get("id") or "")).get("purpose")
            != "dictation"
        ]
        excess = max(0, len(chat_workers) - MAX_WORKERS)
        if not excess:
            return workers

        candidates = []
        for worker in chat_workers:
            target_id = str(worker.get("id") or "")
            state = _worker_state(target_id)
            runtime = worker.get("runtime") or {}
            if (
                target_id
                and target_id != keep_target_id
                and _worker_is_safely_idle(target_id, state, runtime)
            ):
                candidates.append(worker)

        candidates.sort(
            key=lambda worker: float(
                _worker_state(str(worker.get("id") or "")).get("last_used_at") or 0
            )
        )
        closed_ids = set()
        for worker in candidates[:excess]:
            target_id = str(worker.get("id") or "")
            await self.close_target_window(worker)
            closed_ids.add(target_id)
        return [
            worker
            for worker in workers
            if str(worker.get("id") or "") not in closed_ids
        ]

    async def _allocate_worker_target(
        self,
        chat_id: str,
    ) -> Dict[str, Any]:
        """Reserve one bounded worker, reusing an idle window before scaling out."""
        global _POOL_WAITERS

        deadline = time.monotonic() + WORKER_WAIT_TIMEOUT_SECONDS
        counted_waiter = False
        try:
            while True:
                async with _window_lock():
                    port = await self.get_devtools_port()
                    workers, _ = await self._discover_window_pool(port)
                    workers = [
                        worker for worker in workers
                        if _worker_state(str(worker.get("id") or "")).get("purpose")
                        != "dictation"
                    ]
                    mapped_target_id = _CHAT_TARGET_IDS.get(chat_id)
                    workers = await self._trim_excess_idle_workers(
                        workers,
                        keep_target_id=mapped_target_id,
                    )
                    by_id = {
                        str(worker.get("id") or ""): worker
                        for worker in workers
                    }

                    target = by_id.get(str(mapped_target_id or ""))
                    if target is not None:
                        target_id = str(target.get("id") or "")
                        state = _worker_state(target_id)
                        runtime = target.get("runtime") or {}
                        if not _worker_is_safely_idle(target_id, state, runtime):
                            target = None
                    reused = target is not None

                    if target is None:
                        available = []
                        for worker in workers:
                            target_id = str(worker.get("id") or "")
                            state = _worker_state(target_id)
                            runtime = worker.get("runtime") or {}
                            if (
                                target_id
                                and state.get("purpose") != "dictation"
                                and _worker_is_safely_idle(
                                    target_id,
                                    state,
                                    runtime,
                                )
                            ):
                                available.append(worker)

                        available.sort(
                            key=lambda worker: (
                                (worker.get("runtime") or {}).get("chat_id") != chat_id,
                                float(
                                    _worker_state(str(worker.get("id") or "")).get(
                                        "last_used_at"
                                    ) or 0
                                ),
                            )
                        )
                        if available:
                            target = available[0]
                            reused = True
                        elif len(workers) < MAX_WORKERS:
                            target = await self.open_duplicate_window(port)
                            target["runtime"] = {}
                            reused = False

                    if target is not None:
                        target_id = str(target.get("id") or "")
                        if not target_id:
                            raise RuntimeError(
                                "The allocated Anti-Gravity worker has no target ID."
                            )
                        self._unbind_target(target_id, keep_chat_id=chat_id)
                        self.bind_chat_target(chat_id, target_id)
                        self._set_worker_state(
                            target_id,
                            "preparing",
                            chat_id=chat_id,
                            detail="Chat wird vorbereitet",
                            reserved=True,
                        )
                        target["pool_reused"] = reused
                        return target

                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "All Anti-Gravity workers are busy and the queue timed out."
                    )
                if not counted_waiter:
                    _POOL_WAITERS += 1
                    counted_waiter = True
                await asyncio.sleep(0.25)
        finally:
            if counted_waiter:
                _POOL_WAITERS = max(0, _POOL_WAITERS - 1)

    @staticmethod
    async def _monitor_worker_until_idle(
        target_id: str,
        chat_id: str,
        generation: float,
    ) -> None:
        """Keep a worker leased while its chat is running, then retire it when idle."""
        from src.integrity_sync import (
            get_integrity_chat_history,
            scan_antigravity_conversation_catalog,
        )

        saw_running = False
        waiting_for_user = False
        gate_started_at: Optional[float] = None
        active_deadline = time.monotonic() + WORKER_ACTIVE_TIMEOUT_SECONDS
        timed_out = False
        successful_observation_started_at: Optional[float] = None
        completed_samples = 0
        catalog_failures = 0
        try:
            while True:
                current = _WORKER_STATES.get(target_id)
                if (
                    not current
                    or current.get("chat_id") != chat_id
                    or float(current.get("updated_at") or 0) != generation
                ):
                    return
                try:
                    conversations = await asyncio.to_thread(
                        scan_antigravity_conversation_catalog
                    )
                    history = await asyncio.to_thread(
                        get_integrity_chat_history,
                        chat_id,
                        strict=True,
                    )
                    catalog_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    catalog_failures += 1
                    # An unavailable catalog is not evidence that the chat is
                    # idle. Restart any idle grace window and require a fresh
                    # sequence of completed observations after recovery.
                    successful_observation_started_at = None
                    completed_samples = 0
                    if catalog_failures == 1 or catalog_failures % 10 == 0:
                        print(
                            "[ParallelCDPManager] Worker "
                            f"{target_id} catalog observation failed "
                            f"(attempt {catalog_failures}); retaining lease: {exc}",
                            flush=True,
                        )
                    if time.monotonic() >= active_deadline:
                        timed_out = True
                        break
                    await asyncio.sleep(min(5.0, float(catalog_failures)))
                    continue

                observed_at = time.monotonic()
                if successful_observation_started_at is None:
                    successful_observation_started_at = observed_at
                metadata = next(
                    (
                        item
                        for item in conversations
                        if item.get("convo_id") == chat_id
                    ),
                    None,
                )
                is_running = bool(
                    metadata
                    and not metadata.get("archived")
                    and metadata.get("status") == "running"
                )
                gate = _active_user_input_gate(history)
                if gate is not None:
                    saw_running = True
                    completed_samples = 0
                    if not waiting_for_user:
                        current = ParallelCDPManager._set_worker_state(
                            target_id,
                            "waiting_human",
                            chat_id=chat_id,
                            detail="Freigabe erforderlich",
                            reserved=True,
                        )
                        generation = float(current.get("updated_at") or 0)
                        waiting_for_user = True
                        gate_started_at = observed_at
                    await asyncio.sleep(1)
                    continue
                if waiting_for_user:
                    current = ParallelCDPManager._set_worker_state(
                        target_id,
                        "working",
                        chat_id=chat_id,
                        detail="Agent arbeitet",
                        reserved=True,
                    )
                    generation = float(current.get("updated_at") or 0)
                    waiting_for_user = False
                    if gate_started_at is not None:
                        active_deadline += observed_at - gate_started_at
                        gate_started_at = None
                if observed_at >= active_deadline:
                    timed_out = True
                    break
                if is_running:
                    saw_running = True
                    completed_samples = 0
                elif saw_running:
                    completed_samples += 1
                    if completed_samples >= 3:
                        break
                elif observed_at - successful_observation_started_at >= 30:
                    break
                await asyncio.sleep(1)

            if timed_out:
                current = _WORKER_STATES.get(target_id)
                if (
                    current
                    and current.get("chat_id") == chat_id
                    and float(current.get("updated_at") or 0) == generation
                ):
                    current = ParallelCDPManager._set_worker_state(
                        target_id,
                        "error",
                        chat_id=chat_id,
                        detail="Zeitlimit erreicht · Worker wird geschlossen",
                        reserved=True,
                        error="worker_active_timeout",
                    )
                    generation = float(current.get("updated_at") or 0)
                manager = ParallelCDPManager()
                try:
                    async with _window_lock():
                        port = await manager.get_devtools_port()
                        workers, _ = await manager._discover_window_pool(port)
                        target = next(
                            (
                                worker
                                for worker in workers
                                if str(worker.get("id") or "") == target_id
                            ),
                            None,
                        )
                        if target:
                            await manager.close_target_window(target)
                finally:
                    await manager.close_all()
                return

            current = _WORKER_STATES.get(target_id)
            if (
                not current
                or current.get("chat_id") != chat_id
                or float(current.get("updated_at") or 0) != generation
            ):
                return
            current = ParallelCDPManager._set_worker_state(
                target_id,
                "idle",
                chat_id=chat_id,
                detail="Warm und bereit",
                reserved=False,
            )
            idle_generation = float(current.get("updated_at") or 0)
            await asyncio.sleep(IDLE_WORKER_TTL_SECONDS)

            current = _WORKER_STATES.get(target_id)
            if (
                not current
                or current.get("state") != "idle"
                or current.get("reserved")
                or float(current.get("updated_at") or 0) != idle_generation
            ):
                return

            manager = ParallelCDPManager()
            try:
                async with _window_lock():
                    port = await manager.get_devtools_port()
                    workers, _ = await manager._discover_window_pool(port)
                    workers = [
                        worker for worker in workers
                        if _worker_state(str(worker.get("id") or "")).get("purpose")
                        != "dictation"
                    ]
                    if len(workers) <= MIN_WARM_WORKERS:
                        return
                    target = next(
                        (
                            worker
                            for worker in workers
                            if str(worker.get("id") or "") == target_id
                        ),
                        None,
                    )
                    if target:
                        current = _WORKER_STATES.get(target_id) or {}
                        runtime = target.get("runtime") or {}
                    if (
                        target
                        and float(current.get("updated_at") or 0) == idle_generation
                        and _worker_is_safely_idle(target_id, current, runtime)
                    ):
                        await manager.close_target_window(target)
            finally:
                await manager.close_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                f"[ParallelCDPManager] Worker {target_id} monitor failed: {exc}",
                flush=True,
            )
        finally:
            current_task = asyncio.current_task()
            if _WORKER_MONITORS.get(target_id) is current_task:
                _WORKER_MONITORS.pop(target_id, None)

    @classmethod
    def _start_worker_monitor(cls, target_id: str, chat_id: str) -> None:
        previous = _WORKER_MONITORS.pop(target_id, None)
        if previous and not previous.done():
            previous.cancel()
        state = cls._set_worker_state(
            target_id,
            "working",
            chat_id=chat_id,
            detail="Agent arbeitet",
            reserved=True,
        )
        generation = float(state.get("updated_at") or 0)
        _WORKER_MONITORS[target_id] = asyncio.create_task(
            cls._monitor_worker_until_idle(target_id, chat_id, generation)
        )

    async def create_new_project_chat_window(
        self,
        workspace_path: str,
        message: str,
        minimize: bool = True,
        project_name: str = "",
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Lease one bounded worker, then initialize the project chat independently."""
        pending_id = f"pending-project:{id(asyncio.current_task())}:{time.monotonic_ns()}"
        target = await self._allocate_worker_target(pending_id)
        try:
            async with _target_lock(str(target.get("id") or "")):
                kwargs: Dict[str, Any] = {
                    "minimize": minimize,
                    "project_name": project_name,
                }
                if attachment_paths:
                    kwargs["attachment_paths"] = attachment_paths
                return await self.create_project_chat_with_message(
                    target,
                    workspace_path,
                    message,
                    **kwargs,
                )
        except Exception:
            await self.close_target_window(target)
            raise
        finally:
            _CHAT_TARGET_IDS.pop(pending_id, None)

    async def create_new_normal_chat_window(
        self,
        message: str,
        minimize: bool = True,
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Lease one bounded worker and create a normal conversation."""
        pending_id = f"pending-normal:{id(asyncio.current_task())}:{time.monotonic_ns()}"
        target = await self._allocate_worker_target(pending_id)
        try:
            async with _target_lock(str(target.get("id") or "")):
                kwargs: Dict[str, Any] = {"minimize": minimize}
                if attachment_paths:
                    kwargs["attachment_paths"] = attachment_paths
                return await self.create_normal_chat_with_message(
                    target,
                    message,
                    **kwargs,
                )
        except Exception:
            await self.close_target_window(target)
            raise
        finally:
            _CHAT_TARGET_IDS.pop(pending_id, None)

    async def ensure_chat_window(
        self,
        chat_id: str,
        minimize: bool = True,
        section: Optional[str] = None,
        reserve: bool = False,
    ) -> Dict[str, Any]:
        """Prepare a bounded worker for a chat and optionally keep its lease."""
        async with _chat_lock(chat_id):
            target = await self._allocate_worker_target(chat_id)
            target_id = str(target.get("id") or "")
            try:
                async with _target_lock(target_id):
                    result = await self.navigate_target_to_chat(
                        target,
                        chat_id,
                        minimize,
                        section=section,
                    )
                result["reused"] = bool(
                    target.get("pool_reused") or result.get("reused")
                )
                self._set_worker_state(
                    target_id,
                    "preparing" if reserve else "idle",
                    chat_id=chat_id,
                    detail="Für Versand reserviert" if reserve else "Warm und bereit",
                    reserved=reserve,
                )
                return result
            except Exception as exc:
                _CHAT_TARGET_IDS.pop(chat_id, None)
                self._set_worker_state(
                    target_id,
                    "error",
                    chat_id=chat_id,
                    detail="Fensterfehler",
                    reserved=False,
                    error=str(exc),
                )
                await self.close_target_window(target)
                raise

    async def set_chat_archived(
        self,
        chat_id: str,
        archived: bool,
        *,
        section: Optional[str] = None,
        minimize: bool = True,
    ) -> Dict[str, Any]:
        """Change archive state in a bounded worker and verify persisted metadata."""
        async with _chat_lock(chat_id):
            target = await self._allocate_worker_target(chat_id)
            target_id = str(target.get("id") or "")
            try:
                async with _target_lock(target_id):
                    window_info = await self.navigate_target_to_chat(
                        target,
                        chat_id,
                        minimize=False,
                        section=section,
                    )
                    self._set_worker_state(
                        target_id,
                        "preparing",
                        chat_id=chat_id,
                        detail=(
                            "Chat wird archiviert"
                            if archived
                            else "Chat wird wiederhergestellt"
                        ),
                        reserved=True,
                    )
                    client = await self.get_client_for_target(
                        target["webSocketDebuggerUrl"]
                    )
                    action = (
                        await client.archive_chat(chat_id)
                        if archived
                        else await client.restore_chat(chat_id)
                    )

                    from src.integrity_sync import (
                        scan_antigravity_conversation_catalog,
                    )

                    verified = False
                    for _ in range(48):
                        conversations = await asyncio.to_thread(
                            scan_antigravity_conversation_catalog
                        )
                        metadata = next(
                            (
                                item
                                for item in conversations
                                if item.get("convo_id") == chat_id
                            ),
                            None,
                        )
                        if (
                            metadata is not None
                            and bool(metadata.get("archived")) is archived
                        ):
                            verified = True
                            break
                        await asyncio.sleep(0.25)
                    if not verified:
                        raise RuntimeError(
                            "Antigravity changed the UI, but the persisted "
                            "archive state was not confirmed."
                        )

                    minimized = False
                    if minimize:
                        minimized = bool(
                            await client.evaluate(
                                "(async () => { "
                                "if (typeof window.electronNative?.minimize !== "
                                "'function') return false; "
                                "await window.electronNative.minimize(); "
                                "return true; })()",
                                timeout=5,
                            )
                        )
                    self._set_worker_state(
                        target_id,
                        "idle",
                        chat_id=chat_id,
                        detail="Warm und bereit",
                        reserved=False,
                    )
                    return {
                        **window_info,
                        "minimized": minimized,
                        "archived": archived,
                        "verified": True,
                        "action": action,
                    }
            except Exception as exc:
                self._set_worker_state(
                    target_id,
                    "error",
                    chat_id=chat_id,
                    detail="Archivstatus fehlgeschlagen",
                    reserved=False,
                    error=str(exc),
                )
                raise

    async def select_model_for_chat(
        self,
        chat_id: str,
        model_name: str,
        *,
        section: Optional[str] = None,
        minimize: bool = True,
    ) -> Dict[str, Any]:
        """Select and verify a model inside the worker assigned to one chat."""
        requested_model = str(model_name or "").strip()
        if not requested_model:
            raise ValueError("A model name is required.")

        window_info = await self.ensure_chat_window(
            chat_id,
            minimize=False,
            section=section,
            reserve=True,
        )
        target_id = str(window_info.get("target_id") or "")
        port = await self.get_devtools_port()
        target = await self._get_target_by_id(port, target_id)
        if not target:
            raise RuntimeError(
                "The dedicated chat target disappeared before the model switch."
            )

        try:
            async with _target_lock(target_id):
                self._set_worker_state(
                    target_id,
                    "preparing",
                    chat_id=chat_id,
                    detail=f"Modellwechsel: {requested_model}",
                    reserved=True,
                )
                await self.prepare_target_for_automation(target)
                client = await self.get_client_for_target(
                    target["webSocketDebuggerUrl"]
                )
                active_id = await client.get_active_conversation_id()
                if active_id != chat_id:
                    raise RuntimeError(
                        f"Worker {window_info.get('window_id')} is on chat "
                        f"{active_id!r}, expected {chat_id!r}."
                    )

                await client.inject_bridge()
                selected = await client.evaluate(
                    "window.__agBridge.selectModel("
                    f"{json.dumps(requested_model)}"
                    ")",
                    timeout=30,
                )
                if not selected:
                    raise RuntimeError(
                        f"Anti-Gravity did not accept model {requested_model!r}."
                    )

                def normalize(value: Any) -> str:
                    tokens = (
                        str(value or "")
                        .replace("(", " ")
                        .replace(")", " ")
                        .strip()
                        .casefold()
                        .split()
                    )
                    return " ".join(token for token in tokens if token != "fast")

                confirmed_model = ""
                for _ in range(48):
                    current_model = await client.evaluate(
                        """(() => {
                          const button = document.querySelector(
                            '[data-testid="model-selector-trigger"], '
                            + '[aria-label^="Select model"]'
                          );
                          return (button?.getAttribute('aria-label') || '')
                            .replace(/^Select model,\\s*current:\\s*/i, '')
                            .trim();
                        })()""",
                        timeout=5,
                    )
                    if normalize(current_model) == normalize(requested_model):
                        confirmed_model = str(current_model).strip()
                        break
                    await asyncio.sleep(0.25)

                if not confirmed_model:
                    raise TimeoutError(
                        f"Anti-Gravity did not confirm model {requested_model!r} "
                        f"in worker {window_info.get('window_id')}."
                    )

                active_id = await client.get_active_conversation_id()
                if active_id != chat_id:
                    raise RuntimeError(
                        "The worker changed conversations during model selection."
                    )

                minimized = False
                if minimize:
                    for attempt in range(3):
                        try:
                            minimized = bool(
                                await client.evaluate(
                                    """(async () => {
                                      if (typeof window.electronNative?.minimize
                                          !== 'function') return false;
                                      await window.electronNative.minimize();
                                      return true;
                                    })()""",
                                    timeout=5,
                                )
                            )
                        except Exception:
                            minimized = False
                        if minimized:
                            break
                        if attempt < 2:
                            await asyncio.sleep(0.25)

                self._set_worker_state(
                    target_id,
                    "idle",
                    chat_id=chat_id,
                    detail=f"Modell aktiv: {confirmed_model}",
                    reserved=False,
                )
                return {
                    **window_info,
                    "ready": True,
                    "confirmed": True,
                    "model": requested_model,
                    "native_model": confirmed_model,
                    "minimized": minimized,
                }
        except Exception as exc:
            self._set_worker_state(
                target_id,
                "error",
                chat_id=chat_id,
                detail="Modellwechsel fehlgeschlagen",
                reserved=False,
                error=str(exc),
            )
            raise

    async def send_message_to_chat(
        self,
        chat_id: str,
        message: str,
        *,
        section: Optional[str] = None,
        minimize: bool = True,
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send through the real composer in the verified dedicated chat window."""
        attachment_paths = list(attachment_paths or [])
        if not message.strip() and not attachment_paths:
            raise ValueError(
                "The chat message must contain text or an attachment."
            )

        agent_settings = None
        if section:
            agent_settings = await asyncio.to_thread(
                enforce_hub_project_settings,
                project_uuid=section,
            )

        window_info = await self.ensure_chat_window(
            chat_id,
            minimize=False,
            section=section,
            reserve=True,
        )
        port = await self.get_devtools_port()
        target = await self._get_target_by_id(
            port,
            str(window_info.get("target_id") or ""),
        )
        if not target:
            raise RuntimeError("The dedicated chat target disappeared before sending.")

        target_id = str(window_info.get("target_id") or "")
        submitted = None
        send_error: Optional[Exception] = None
        minimized = False
        warnings: List[str] = []
        try:
            async with _target_lock(target_id):
                self._set_worker_state(
                    target_id,
                    "sending",
                    chat_id=chat_id,
                    detail="Nachricht wird eingegeben",
                    reserved=True,
                )
                await self.prepare_target_for_automation(target)
                client = await self.get_client_for_target(
                    target["webSocketDebuggerUrl"]
                )
                active_id = await client.get_active_conversation_id()
                if active_id != chat_id:
                    raise RuntimeError(
                        f"Worker {window_info.get('window_id')} is on chat "
                        f"{active_id!r}, expected {chat_id!r}."
                    )

                # When a previous answer is still running, Anti-Gravity removes or
                # disables the composer. Queue on this exact worker until it is
                # genuinely ready instead of navigating or creating another window.
                if message:
                    typing_attempt = await self._enter_message_with_retries(
                        client,
                        target_id=target_id,
                        chat_id=chat_id,
                        message=message,
                    )
                    self._set_worker_state(
                        target_id,
                        "sending",
                        chat_id=chat_id,
                        detail=(
                            "Nachricht eingegeben"
                            if typing_attempt == 1
                            else f"Composer synchronisiert · Versuch {typing_attempt}/3"
                        ),
                        reserved=True,
                    )
                else:
                    await self._wait_for_message_composer(
                        client,
                        attempts=WORKER_WAIT_TIMEOUT_SECONDS * 4,
                    )
                if attachment_paths:
                    await client.set_file_input_files(attachment_paths)
                active_id = await client.get_active_conversation_id()
                if active_id != chat_id:
                    raise RuntimeError(
                        f"Worker {window_info.get('window_id')} changed to chat "
                        f"{active_id!r} before submit; expected {chat_id!r}."
                    )
                submitted = await client.evaluate(
                    "window.__agBridge.prepareAndSend('')",
                    timeout=30,
                )
                if not submitted or submitted.get("error"):
                    raise RuntimeError(
                        f"Antigravity did not submit the message: {submitted}"
                    )
                self._start_worker_monitor(target_id, chat_id)
        except Exception as exc:
            send_error = exc
            self._set_worker_state(
                target_id,
                "error",
                chat_id=chat_id,
                detail="Versand fehlgeschlagen",
                reserved=False,
                error=str(exc),
            )
            raise
        finally:
            if minimize:
                try:
                    client = await self.get_client_for_target(
                        target["webSocketDebuggerUrl"]
                    )
                    minimized = bool(
                        await client.evaluate(
                            "(async () => { "
                            "if (typeof window.electronNative?.minimize !== 'function') "
                            "return false; "
                            "await window.electronNative.minimize(); "
                            "return true; "
                            "})()",
                            timeout=5,
                        )
                    )
                except Exception as exc:
                    minimized = False
                    if send_error is None:
                        warnings.append(
                            "The message was submitted, but the worker could not "
                            f"be minimized: {exc}"
                        )
                if not minimized and send_error is None:
                    if not warnings:
                        warnings.append(
                            "The message was submitted, but the dedicated chat "
                            "window could not be minimized."
                        )

        if not submitted:
            raise RuntimeError(
                f"Antigravity did not submit the message: {submitted}"
            )

        return {
            **window_info,
            "agent_settings": agent_settings,
            "ready": True,
            "composer_ready": True,
            "minimized": minimized,
            "submitted": submitted,
            "warning": " ".join(warnings),
            "warnings": warnings,
        }

    async def close_chat_window(self, chat_id: str) -> bool:
        """Close only the Hub-managed duplicate currently assigned to one chat."""
        async with _chat_lock(chat_id):
            target_id = _CHAT_TARGET_IDS.pop(chat_id, None)
            if not target_id:
                return False
            port = await self.get_devtools_port()
            target = await self._get_target_by_id(port, target_id)
            if not target:
                _DUPLICATE_TARGET_IDS.discard(target_id)
                _WINDOW_STAMPS.pop(target_id, None)
                return False
            await self.close_target_window(target)
            _WINDOW_STAMPS.pop(target_id, None)
            return True

    @staticmethod
    def _deletion_worker_status(
        target_id: str,
        state: Dict[str, Any],
        runtime: Dict[str, Any],
        *,
        role: str = "worker",
    ) -> Dict[str, Any]:
        """Build the stable, non-sensitive worker fragment for delete errors."""
        loaded_chat_id = str(runtime.get("chat_id") or "").strip().lower()
        assigned_chat_id = str(state.get("chat_id") or "").strip().lower()
        if role == "primary":
            binding_status = "confirmed" if loaded_chat_id else "none"
            activity = (
                str(runtime.get("native_activity") or "unknown")
                if runtime.get("activity_observed")
                else "unknown"
            )
        else:
            if not assigned_chat_id and not loaded_chat_id:
                binding_status = "none"
            elif assigned_chat_id == loaded_chat_id:
                binding_status = "confirmed"
            else:
                binding_status = "mismatch"
            activity, _ = _reconcile_worker_activity(state, runtime)
        if runtime.get("runtime_reachable") is not True:
            activity = "unknown"
            detail_code = "runtime_unreachable"
        elif binding_status == "mismatch":
            detail_code = "conversation_mismatch"
        else:
            detail_code = f"{role}_{activity}"
        return {
            "instance_id": (
                "MAIN"
                if role == "primary"
                else str(runtime.get("stamp") or state.get("window_id") or "")
            ),
            "activity": activity,
            "detail_code": detail_code,
            "has_draft": bool(runtime.get("has_draft")),
            "binding_status": binding_status,
        }

    @staticmethod
    def _deletion_blocked(
        chat_id: str,
        *,
        code: str,
        detail_code: str,
        worker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "allowed": False,
            "code": code,
            "conversation_id": chat_id,
            "retryable": True,
            "detail_code": detail_code,
        }
        if worker is not None:
            result["worker"] = worker
        return result

    async def _complete_prepared_chat_deletion(
        self,
        chat_id: str,
        *,
        window_closed: bool,
        delete_callback: Optional[Any],
    ) -> Dict[str, Any]:
        result = {
            "allowed": True,
            "conversation_id": chat_id,
            "window_closed": window_closed,
        }
        if delete_callback is not None:
            deletion_task = asyncio.create_task(
                asyncio.to_thread(delete_callback, chat_id)
            )
            try:
                result["deletion_result"] = await asyncio.shield(deletion_task)
            except asyncio.CancelledError:
                try:
                    await deletion_task
                except Exception:
                    pass
                raise
        return result

    async def prepare_chat_deletion(
        self,
        chat_id: str,
        *,
        delete_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Atomically verify and close a native chat window before file deletion."""
        normalized_chat_id = str(chat_id or "").strip().lower()
        async with _chat_lock(normalized_chat_id):
            mapped_target_id = str(
                _CHAT_TARGET_IDS.get(normalized_chat_id) or ""
            )
            try:
                port = await self.get_devtools_port()
                workers, primary = await self._discover_window_pool(
                    port,
                    mutate_registry=False,
                )
            except Exception:
                return self._deletion_blocked(
                    normalized_chat_id,
                    code="conversation_state_unavailable",
                    detail_code="desktop_state_unavailable",
                )
            if str(_CHAT_TARGET_IDS.get(normalized_chat_id) or "") != mapped_target_id:
                return self._deletion_blocked(
                    normalized_chat_id,
                    code="conversation_state_unavailable",
                    detail_code="conversation_binding_changed",
                )

            if primary is not None:
                primary_runtime = primary.get("runtime") or {}
                if primary_runtime.get("runtime_reachable") is not True:
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_state_unavailable",
                        detail_code="primary_runtime_unreachable",
                    )
                primary_chat_id = str(
                    primary_runtime.get("chat_id") or ""
                ).strip().lower()
                if primary_chat_id == normalized_chat_id:
                    worker_status = self._deletion_worker_status(
                        str(primary.get("id") or ""),
                        {},
                        primary_runtime,
                        role="primary",
                    )
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_busy",
                        detail_code=worker_status["detail_code"],
                        worker=worker_status,
                    )

            relevant_workers = []
            unreachable_worker_seen = False
            for worker in workers:
                target_id = str(worker.get("id") or "")
                runtime = worker.get("runtime") or {}
                state = _WORKER_STATES.get(target_id) or {}
                if runtime.get("runtime_reachable") is not True:
                    unreachable_worker_seen = True
                assigned_chat_id = str(
                    state.get("chat_id") or ""
                ).strip().lower()
                loaded_chat_id = str(
                    runtime.get("chat_id") or ""
                ).strip().lower()
                if (
                    target_id == mapped_target_id
                    or assigned_chat_id == normalized_chat_id
                    or loaded_chat_id == normalized_chat_id
                ):
                    relevant_workers.append(worker)

            if unreachable_worker_seen:
                return self._deletion_blocked(
                    normalized_chat_id,
                    code="conversation_state_unavailable",
                    detail_code="worker_runtime_unreachable",
                )

            if not mapped_target_id:
                if relevant_workers:
                    worker = relevant_workers[0]
                    target_id = str(worker.get("id") or "")
                    worker_status = self._deletion_worker_status(
                        target_id,
                        _WORKER_STATES.get(target_id) or {},
                        worker.get("runtime") or {},
                    )
                    # A live chat without the exact Hub binding is not safe to
                    # close on behalf of this request.
                    worker_status["binding_status"] = "mismatch"
                    worker_status["detail_code"] = "conversation_mismatch"
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_busy",
                        detail_code="conversation_mismatch",
                        worker=worker_status,
                    )
                return await self._complete_prepared_chat_deletion(
                    normalized_chat_id,
                    window_closed=False,
                    delete_callback=delete_callback,
                )

            mapped_workers = [
                worker
                for worker in relevant_workers
                if str(worker.get("id") or "") == mapped_target_id
            ]
            if len(mapped_workers) != 1 or len(relevant_workers) != 1:
                return self._deletion_blocked(
                    normalized_chat_id,
                    code="conversation_state_unavailable",
                    detail_code="conversation_binding_ambiguous",
                )

            target_lock = _target_lock(mapped_target_id)
            async with target_lock:
                try:
                    final_workers, final_primary = await self._discover_window_pool(
                        port,
                        mutate_registry=False,
                    )
                    if (
                        str(_CHAT_TARGET_IDS.get(normalized_chat_id) or "")
                        != mapped_target_id
                    ):
                        return self._deletion_blocked(
                            normalized_chat_id,
                            code="conversation_state_unavailable",
                            detail_code="conversation_binding_changed",
                        )
                    if final_primary is not None:
                        final_primary_runtime = final_primary.get("runtime") or {}
                        if final_primary_runtime.get("runtime_reachable") is not True:
                            return self._deletion_blocked(
                                normalized_chat_id,
                                code="conversation_state_unavailable",
                                detail_code="primary_runtime_unreachable",
                            )
                        final_primary_chat_id = str(
                            final_primary_runtime.get("chat_id") or ""
                        ).strip().lower()
                        if final_primary_chat_id == normalized_chat_id:
                            primary_status = self._deletion_worker_status(
                                str(final_primary.get("id") or ""),
                                {},
                                final_primary_runtime,
                                role="primary",
                            )
                            return self._deletion_blocked(
                                normalized_chat_id,
                                code="conversation_busy",
                                detail_code=primary_status["detail_code"],
                                worker=primary_status,
                            )
                    if any(
                        (worker.get("runtime") or {}).get("runtime_reachable")
                        is not True
                        for worker in final_workers
                    ):
                        return self._deletion_blocked(
                            normalized_chat_id,
                            code="conversation_state_unavailable",
                            detail_code="worker_runtime_unreachable",
                        )
                    final_relevant_workers = []
                    for worker in final_workers:
                        worker_target_id = str(worker.get("id") or "")
                        worker_runtime = worker.get("runtime") or {}
                        worker_state = _WORKER_STATES.get(worker_target_id) or {}
                        if (
                            worker_target_id == mapped_target_id
                            or str(worker_state.get("chat_id") or "").strip().lower()
                            == normalized_chat_id
                            or str(worker_runtime.get("chat_id") or "").strip().lower()
                            == normalized_chat_id
                        ):
                            final_relevant_workers.append(worker)
                    if (
                        len(final_relevant_workers) != 1
                        or str(final_relevant_workers[0].get("id") or "")
                        != mapped_target_id
                    ):
                        return self._deletion_blocked(
                            normalized_chat_id,
                            code="conversation_state_unavailable",
                            detail_code="conversation_binding_ambiguous",
                        )
                    target = await self._get_target_by_id(port, mapped_target_id)
                    if target is None:
                        return self._deletion_blocked(
                            normalized_chat_id,
                            code="conversation_state_unavailable",
                            detail_code="bound_window_missing",
                        )
                    runtime = await self._inspect_target_runtime(target)
                    runtime["runtime_reachable"] = True
                except Exception:
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_state_unavailable",
                        detail_code="worker_runtime_unreachable",
                    )

                state = _WORKER_STATES.get(mapped_target_id) or {}
                worker_status = self._deletion_worker_status(
                    mapped_target_id,
                    state,
                    runtime,
                )
                assigned_chat_id = str(
                    state.get("chat_id") or ""
                ).strip().lower()
                loaded_chat_id = str(
                    runtime.get("chat_id") or ""
                ).strip().lower()
                other_bindings = any(
                    mapped_chat_id != normalized_chat_id
                    and target_id == mapped_target_id
                    for mapped_chat_id, target_id in _CHAT_TARGET_IDS.items()
                )
                binding_is_exact = bool(
                    _CHAT_TARGET_IDS.get(normalized_chat_id) == mapped_target_id
                    and assigned_chat_id == normalized_chat_id
                    and loaded_chat_id == normalized_chat_id
                    and not other_bindings
                )
                if not binding_is_exact:
                    worker_status["binding_status"] = "mismatch"
                    worker_status["detail_code"] = "conversation_mismatch"
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_busy",
                        detail_code="conversation_mismatch",
                        worker=worker_status,
                    )
                if runtime.get("role") != "duplicate":
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_state_unavailable",
                        detail_code="worker_role_unverified",
                    )
                if not _worker_has_positive_idle_evidence(state, runtime):
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_busy",
                        detail_code=worker_status["detail_code"],
                        worker=worker_status,
                    )

                if not await self._request_target_window_close(target):
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_state_unavailable",
                        detail_code="window_close_unconfirmed",
                    )
                if not await self._confirm_target_window_closed(
                    port,
                    mapped_target_id,
                ):
                    return self._deletion_blocked(
                        normalized_chat_id,
                        code="conversation_state_unavailable",
                        detail_code="window_close_unconfirmed",
                    )
                self._forget_target(mapped_target_id, keep_target_lock=True)
            await self._forget_target_lock_when_unused(
                mapped_target_id,
                target_lock,
            )
            return await self._complete_prepared_chat_deletion(
                normalized_chat_id,
                window_closed=True,
                delete_callback=delete_callback,
            )

    @staticmethod
    def bind_chat_target(chat_id: str, target_id: str) -> None:
        """Bind a newly-created chat ID to the duplicate window that created it."""
        if chat_id and target_id:
            ParallelCDPManager._unbind_target(target_id, keep_chat_id=chat_id)
            _CHAT_TARGET_IDS[chat_id] = target_id
            _DUPLICATE_TARGET_IDS.add(target_id)

    async def close_all(self) -> None:
        """Disconnect all managed CDP clients without closing desktop windows."""
        for client in list(self.clients.values()):
            try:
                await client.disconnect()
            except Exception as exc:
                print(f"[ParallelCDPManager] Error disconnecting client: {exc}", flush=True)
        self.clients.clear()
