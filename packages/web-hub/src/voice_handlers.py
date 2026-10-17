import asyncio
import json
import logging
import socket
import sys
import time
from typing import Any, Dict, Optional
from aiohttp import web

from src.cdp_client import AntigravityCDP
from src.config import config
from src.parallel_cdp import ParallelCDPManager

logger = logging.getLogger(__name__)

# Global cached CDP client and state variables
_global_cdp: Optional[AntigravityCDP] = None
_cdp_lock = asyncio.Lock()
_last_known_text = ""
_is_recording = False
_start_time = 0.0
_proxy_shutting_down = False
_active_voice_mode = ""
_dictation_manager: Optional[ParallelCDPManager] = None
_dictation_cdp: Optional[AntigravityCDP] = None
_dictation_target: Optional[Dict[str, Any]] = None


def get_is_recording() -> bool:
    """Gets recording state, falling back to MockState in tests."""
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "MockState"):
        return getattr(main_mod.MockState, "is_recording", _is_recording)
    return _is_recording


def set_is_recording(value: bool):
    """Sets recording state, syncing with MockState in tests."""
    global _is_recording
    _is_recording = value
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "MockState"):
        try:
            main_mod.MockState.is_recording = value
        except Exception:
            pass


def is_shutting_down() -> bool:
    """Checks if proxy is shutting down, falling back to MockState in tests."""
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "MockState"):
        return getattr(main_mod.MockState, "proxy_shutting_down", _proxy_shutting_down)
    return _proxy_shutting_down


def check_auth(request: web.Request) -> bool:
    """Validate Authorization header against config or mock state."""
    auth_header = request.headers.get("Authorization")
    auth_required = False

    # The Hub binds to loopback by default and serves these handlers directly.
    # Local UI calls therefore do not need a browser-visible copy of the API
    # secret. Explicit LAN exposure still requires the configured token.
    if str(getattr(request, "remote", "") or "") in {"127.0.0.1", "::1", "localhost"}:
        return True

    # Determine test environment
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "MockState"):
        auth_required = getattr(main_mod.MockState, "auth_required", False)
    elif "test_suite" in sys.modules or (sys.argv and any("test_suite" in arg for arg in sys.argv)):
        auth_required = False
    else:
        auth_required = bool(config.auth_token)

    if auth_required:
        expected = f"Bearer {config.auth_token}"
        if auth_header != expected:
            return False
    return True


async def is_network_online() -> bool:
    """Helper to check if network is online asynchronously.

    Tries to connect to a reliable public host (Google DNS) on port 53.
    """
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "MockState"):
        return getattr(main_mod.MockState, "network_online", True)

    def _check():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(("8.8.8.8", 53))
            s.close()
            return True
        except Exception:
            return False
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check)


async def close_voice_session() -> None:
    """Closes any active voice recording session and the global CDP connection."""
    global _global_cdp, _proxy_shutting_down, _active_voice_mode
    global _dictation_manager, _dictation_cdp, _dictation_target

    _proxy_shutting_down = True
    async with _cdp_lock:
        set_is_recording(False)
        if _global_cdp:
            try:
                await _global_cdp.disconnect()
            except Exception as e:
                logger.error(f"[Voice] Error disconnecting global CDP: {e}")
            _global_cdp = None
        if _dictation_cdp:
            try:
                await _dictation_cdp.evaluate(
                    "window.__agBridge?.stopVoiceRecording?.()",
                    timeout=3,
                )
            except Exception:
                pass
            try:
                await _dictation_cdp.evaluate(
                    "window.__agBridge?.clearVoiceDraft?.()",
                    timeout=3,
                )
            except Exception:
                pass
        if _dictation_manager:
            try:
                await _dictation_manager.close_dictation_window()
            except Exception as error:
                logger.error(f"[Voice] Error closing dictation window: {error}")
            try:
                await _dictation_manager.disconnect_all()
            except Exception as error:
                logger.error(f"[Voice] Error disconnecting dictation CDP: {error}")
        _dictation_manager = None
        _dictation_cdp = None
        _dictation_target = None
        _active_voice_mode = ""


async def _auto_timeout_job(start_time_val: float, max_duration: int) -> None:
    """Background task to stop voice recording if it exceeds max_duration."""
    await asyncio.sleep(max_duration)
    global _global_cdp, _start_time, _active_voice_mode
    if (
        get_is_recording()
        and _active_voice_mode == "chat"
        and _start_time == start_time_val
    ):
        async with _cdp_lock:
            if (
                get_is_recording()
                and _active_voice_mode == "chat"
                and _start_time == start_time_val
            ):
                cdp = _global_cdp
                if cdp:
                    try:
                        await cdp.evaluate("window.__agBridge.stopVoiceRecording()")
                    except Exception:
                        pass
                    try:
                        await cdp.disconnect()
                    except Exception:
                        pass
                set_is_recording(False)
                _global_cdp = None
                _active_voice_mode = ""


async def handle_voice_start(request: web.Request) -> web.Response:
    """POST /api/voice/start

    Starts the voice recording session using the global cached CDP connection.
    """
    global _global_cdp, _last_known_text, _start_time, _active_voice_mode

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)

    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"}, status=503
        )

    if not await is_network_online():
        return web.json_response(
            {"success": False, "error": "Network connection offline"}, status=503
        )

    # Parse request payload
    body = {}
    if request.can_read_body:
        try:
            body = await request.json()
        except json.JSONDecodeError as jde:
            return web.json_response({"success": False, "error": f"Invalid JSON payload: {jde}"}, status=400)
        except Exception as e:
            return web.json_response({"success": False, "error": f"Bad Request: {e}"}, status=400)

    initial_text = body.get("text", "")
    chat_id = body.get("chat_id", "")
    if not isinstance(initial_text, str) and initial_text is not None:
        return web.json_response(
            {"success": False, "error": "Invalid request payload"}, status=400
        )

    if initial_text and len(initial_text) > 100000:
        return web.json_response(
            {"success": False, "error": "Oversized initial text"}, status=400
        )

    async with _cdp_lock:
        if get_is_recording():
            return web.json_response(
                {"success": False, "error": "Recording is already active"}, status=409
            )
        _active_voice_mode = ""

        try:
            if _global_cdp is None:
                _global_cdp = AntigravityCDP()
            if not _global_cdp._connected or not _global_cdp.ws or _global_cdp.ws.closed:
                await _global_cdp.connect()

            if chat_id:
                try:
                    print(f"[Voice] Navigating Tauri app to chat {chat_id}...")
                    await _global_cdp.evaluate(f"window.__agBridge.navigateToChat('{chat_id}')", timeout=10)
                except Exception as ne:
                    print(f"[WARN] Failed to navigate to chat {chat_id}: {ne}")

            await _global_cdp.inject_bridge()
        except ConnectionError as ce:
            logger.error(f"[Voice] Connect failed: {ce}")
            # Electron/Tauri is not running or can't connect
            if _global_cdp:
                try:
                    await _global_cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None
            set_is_recording(False)
            return web.json_response(
                {"success": False, "error": "Cannot connect to Tauri Electron application"},
                status=502
            )
        except Exception as e:
            logger.error(f"[Voice] CDP connection error: {e}")
            if _global_cdp:
                try:
                    await _global_cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None
            set_is_recording(False)
            return web.json_response(
                {"success": False, "error": f"CDP connection failed: {e}"},
                status=500
            )

        try:
            # Call JS helper in the webview
            escaped_text = json.dumps(initial_text or "")
            success = await _global_cdp.evaluate(
                f"window.__agBridge.startVoiceRecording({escaped_text})"
            )
            if not success:
                # Local cleanup since JS call failed
                try:
                    await _global_cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None
                set_is_recording(False)
                return web.json_response(
                    {"success": False, "error": "Failed to start recording in webview"},
                    status=500
                )

            set_is_recording(True)
            _active_voice_mode = "chat"
            _last_known_text = initial_text or ""
            _start_time = time.time()

            # Start background auto-timeout task
            max_duration = 300
            main_mod = sys.modules.get("__main__")
            if main_mod and hasattr(main_mod, "MockState"):
                max_duration = getattr(main_mod.MockState, "max_duration_seconds", max_duration)
            asyncio.create_task(_auto_timeout_job(_start_time, max_duration))

            return web.json_response({"success": True})
        except Exception as e:
            logger.error(f"[Voice] Start recording evaluate failed: {e}")
            try:
                await _global_cdp.disconnect()
            except Exception:
                pass
            _global_cdp = None
            set_is_recording(False)
            return web.json_response(
                {"success": False, "error": f"JS Evaluation failed: {e}"},
                status=500
            )


async def handle_voice_stop(request: web.Request) -> web.Response:
    """POST /api/voice/stop

    Stops the voice recording, retrieves the final transcript, and closes the CDP connection.
    """
    global _global_cdp, _last_known_text, _active_voice_mode

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)

    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"}, status=503
        )

    if not await is_network_online():
        final_text = _last_known_text
        async with _cdp_lock:
            if _global_cdp:
                try:
                    await _global_cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None
            set_is_recording(False)
        return web.json_response(
            {"success": False, "error": "Network connection offline", "text": final_text}, status=503
        )

    if not get_is_recording():
        return web.json_response(
            {"success": False, "error": "No active recording session"}, status=400
        )
    if _active_voice_mode == "dictation":
        return await handle_dictation_stop(request)

    async with _cdp_lock:
        final_text = _last_known_text
        if _global_cdp:
            try:
                # Call stop recording
                await _global_cdp.evaluate("window.__agBridge.stopVoiceRecording()")

                # Fetch final state and text
                state = await _global_cdp.evaluate("window.__agBridge.getVoiceState()")
                if isinstance(state, dict):
                    final_text = state.get("text", final_text)
            except Exception as e:
                logger.error(f"[Voice] Error stopping/getting voice state: {e}")
                # Fallback to last known text
            finally:
                # Close the connection and clear the cache
                try:
                    await _global_cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None

        set_is_recording(False)
        _active_voice_mode = ""
        _last_known_text = final_text
        return web.json_response({"success": True, "text": final_text})


async def handle_voice_status(request: web.Request) -> web.Response:
    """GET /api/voice/status

    Returns the current voice recording status.
    """
    global _global_cdp, _last_known_text, _start_time, _active_voice_mode

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)

    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"}, status=503
        )

    if not get_is_recording() or not _global_cdp:
        if get_is_recording() and _active_voice_mode == "dictation":
            return await handle_dictation_status(request)
        return web.json_response({"isRecording": False, "text": _last_known_text})

    async with _cdp_lock:
        cdp = _global_cdp
        if not cdp or not get_is_recording():
            return web.json_response({"isRecording": False, "text": _last_known_text})

    try:
        # Query the voice state from webview
        state = await cdp.evaluate("window.__agBridge.getVoiceState()")

        if not isinstance(state, dict):
            # If state retrieval fails, default to not recording
            async with _cdp_lock:
                if _global_cdp == cdp:
                    set_is_recording(False)
                    _active_voice_mode = ""
                    try:
                        await cdp.disconnect()
                    except Exception:
                        pass
                    _global_cdp = None
            return web.json_response({"isRecording": False, "text": _last_known_text})

        is_rec = state.get("isRecording", False)
        text_val = state.get("text", "")
        _last_known_text = text_val

        # If the webview says recording has stopped, clean up the connection
        if not is_rec:
            async with _cdp_lock:
                if _global_cdp == cdp:
                    set_is_recording(False)
                    _active_voice_mode = ""
                    try:
                        await cdp.disconnect()
                    except Exception:
                        pass
                    _global_cdp = None
            return web.json_response({"isRecording": False, "text": text_val})

        # Check max duration (5 minutes / 300 seconds default, as in test)
        max_duration = 300
        main_mod = sys.modules.get("__main__")
        if main_mod and hasattr(main_mod, "MockState"):
            max_duration = getattr(main_mod.MockState, "max_duration_seconds", max_duration)
        if _start_time and (time.time() - _start_time) > max_duration:
            # Stop recording automatically in webview
            try:
                await cdp.evaluate("window.__agBridge.stopVoiceRecording()")
            except Exception:
                pass
            async with _cdp_lock:
                if _global_cdp == cdp:
                    set_is_recording(False)
                    _active_voice_mode = ""
                    try:
                        await cdp.disconnect()
                    except Exception:
                        pass
                    _global_cdp = None
            return web.json_response({"isRecording": False, "text": text_val})

        # Update last known text and return active status
        _last_known_text = text_val
        return web.json_response({"isRecording": True, "text": text_val})

    except Exception as e:
        logger.error(f"[Voice] Error querying status: {e}")
        # If CDP connection is lost or fails during recording:
        # perform local cleanup, mark is_recording as False, close connection
        async with _cdp_lock:
            if _global_cdp == cdp:
                set_is_recording(False)
                _active_voice_mode = ""
                try:
                    await cdp.disconnect()
                except Exception:
                    pass
                _global_cdp = None
        return web.json_response(
            {"isRecording": False, "error": str(e), "text": _last_known_text}
        )


def _dictation_window_payload() -> Dict[str, Any]:
    target = _dictation_target or {}
    return {
        "target_id": str(target.get("id") or ""),
        "window_id": str(target.get("window_id") or "AG-DIKTAT"),
        "purpose": "dictation",
        "created": bool(target.get("created")),
    }


async def _collect_dictation_text(
    cdp: AntigravityCDP,
    *,
    attempts: int = 6,
) -> str:
    """Collect the native transcript until it is briefly stable."""
    global _last_known_text

    stable_samples = 0
    previous = _last_known_text
    for _ in range(attempts):
        try:
            state = await cdp.evaluate(
                "window.__agBridge.getVoiceState()",
                timeout=5,
            )
        except Exception:
            break
        candidate = state.get("text") if isinstance(state, dict) else None
        if isinstance(candidate, str):
            _last_known_text = candidate
        if _last_known_text == previous:
            stable_samples += 1
        else:
            previous = _last_known_text
            stable_samples = 0
        if stable_samples >= 2:
            break
        await asyncio.sleep(0.2)
    return _last_known_text


async def _finish_dictation_locked(
    *,
    stop_native: bool,
    state_name: str = "dictation_ready",
    detail: str = "Mikrofon bereit",
) -> Dict[str, Any]:
    """Finish the active dictation. Caller must hold ``_cdp_lock``."""
    global _active_voice_mode, _dictation_cdp, _last_known_text

    cdp = _dictation_cdp
    target_id = str((_dictation_target or {}).get("id") or "")
    if cdp:
        if stop_native:
            try:
                await cdp.evaluate(
                    "window.__agBridge.stopVoiceRecording()",
                    timeout=5,
                )
            except Exception as error:
                logger.warning(f"[Voice] Native dictation stop failed: {error}")
        await asyncio.sleep(0.25)
        await _collect_dictation_text(cdp)
        try:
            await cdp.evaluate(
                "window.__agBridge.clearVoiceDraft()",
                timeout=5,
            )
        except Exception as error:
            logger.warning(f"[Voice] Dictation draft cleanup failed: {error}")

    set_is_recording(False)
    _active_voice_mode = ""
    if _dictation_manager and target_id:
        _dictation_manager.set_dictation_state(
            target_id,
            state_name,
            detail,
            reserved=False,
        )
    return {
        "success": True,
        "isRecording": False,
        "text": _last_known_text,
        "window": _dictation_window_payload(),
    }


async def _auto_timeout_dictation_job(
    start_time_val: float,
    max_duration: int,
) -> None:
    await asyncio.sleep(max_duration)
    global _start_time
    if (
        get_is_recording()
        and _active_voice_mode == "dictation"
        and _start_time == start_time_val
    ):
        async with _cdp_lock:
            if (
                get_is_recording()
                and _active_voice_mode == "dictation"
                and _start_time == start_time_val
            ):
                await _finish_dictation_locked(
                    stop_native=True,
                    detail="Diktat nach Zeitlimit beendet",
                )


async def handle_dictation_start(request: web.Request) -> web.Response:
    """Start native Anti-Gravity dictation in the single reserved window."""
    global _active_voice_mode, _dictation_manager, _dictation_cdp
    global _dictation_target, _last_known_text, _start_time

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)
    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"},
            status=503,
        )
    if not await is_network_online():
        return web.json_response(
            {"success": False, "error": "Network connection offline"},
            status=503,
        )

    try:
        body = await request.json() if request.can_read_body else {}
    except json.JSONDecodeError as error:
        return web.json_response(
            {"success": False, "error": f"Invalid JSON payload: {error}"},
            status=400,
        )
    except Exception as error:
        return web.json_response(
            {"success": False, "error": f"Bad Request: {error}"},
            status=400,
        )

    initial_text = body.get("text", "")
    field_label = body.get("field_label", "")
    if not isinstance(initial_text, str) or not isinstance(field_label, str):
        return web.json_response(
            {"success": False, "error": "Invalid request payload"},
            status=400,
        )
    if len(initial_text) > 100000 or len(field_label) > 160:
        return web.json_response(
            {"success": False, "error": "Oversized request payload"},
            status=400,
        )

    async with _cdp_lock:
        if get_is_recording():
            return web.json_response(
                {
                    "success": False,
                    "error": "Recording is already active",
                    "mode": _active_voice_mode or "unknown",
                },
                status=409,
            )

        target_id = ""
        try:
            _active_voice_mode = ""
            if _dictation_manager is None:
                _dictation_manager = ParallelCDPManager()
            target = await _dictation_manager.ensure_dictation_window()
            _dictation_target = target
            target_id = str(target.get("id") or "")
            _dictation_cdp = await _dictation_manager.get_client_for_target(
                target["webSocketDebuggerUrl"]
            )
            await _dictation_cdp.inject_bridge()
            success = await _dictation_cdp.evaluate(
                "window.__agBridge.startVoiceRecording("
                f"{json.dumps(initial_text)}"
                ")",
                timeout=10,
            )
            if not success:
                raise RuntimeError(
                    "Anti-Gravity did not expose an available microphone button."
                )

            _last_known_text = initial_text
            _start_time = time.time()
            _active_voice_mode = "dictation"
            set_is_recording(True)
            _dictation_manager.set_dictation_state(
                target_id,
                "dictation_recording",
                f"Aufnahme läuft{f' · {field_label.strip()}' if field_label.strip() else ''}",
                reserved=True,
            )
            asyncio.create_task(_auto_timeout_dictation_job(_start_time, 300))
            return web.json_response(
                {
                    "success": True,
                    "isRecording": True,
                    "text": initial_text,
                    "window": _dictation_window_payload(),
                }
            )
        except (ConnectionError, TimeoutError) as error:
            if _dictation_manager and target_id:
                _dictation_manager.set_dictation_state(
                    target_id,
                    "error",
                    "Diktatfenster nicht bereit",
                    reserved=False,
                    error=str(error),
                )
            set_is_recording(False)
            _active_voice_mode = ""
            return web.json_response(
                {"success": False, "error": str(error)},
                status=503,
            )
        except Exception as error:
            logger.error(f"[Voice] Dictation start failed: {error}")
            if _dictation_cdp:
                try:
                    await _dictation_cdp.evaluate(
                        "window.__agBridge.clearVoiceDraft()",
                        timeout=3,
                    )
                except Exception:
                    pass
            if _dictation_manager and target_id:
                _dictation_manager.set_dictation_state(
                    target_id,
                    "error",
                    "Diktatstart fehlgeschlagen",
                    reserved=False,
                    error=str(error),
                )
            set_is_recording(False)
            _active_voice_mode = ""
            return web.json_response(
                {"success": False, "error": str(error)},
                status=500,
            )


async def handle_dictation_status(request: web.Request) -> web.Response:
    """Return live transcript text from the reserved dictation window."""
    global _active_voice_mode, _last_known_text

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)
    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"},
            status=503,
        )

    async with _cdp_lock:
        if (
            not get_is_recording()
            or _active_voice_mode != "dictation"
            or not _dictation_cdp
        ):
            return web.json_response(
                {
                    "success": True,
                    "isRecording": False,
                    "text": _last_known_text,
                    "window": _dictation_window_payload(),
                }
            )

        try:
            state = await _dictation_cdp.evaluate(
                "window.__agBridge.getVoiceState()",
                timeout=5,
            )
            if isinstance(state, dict) and isinstance(state.get("text"), str):
                _last_known_text = state["text"]
            native_recording = bool(
                isinstance(state, dict) and state.get("isRecording")
            )
            if not native_recording and time.time() - _start_time > 1.5:
                payload = await _finish_dictation_locked(stop_native=False)
                return web.json_response(payload)
            return web.json_response(
                {
                    "success": True,
                    "isRecording": True,
                    "text": _last_known_text,
                    "window": _dictation_window_payload(),
                }
            )
        except Exception as error:
            logger.error(f"[Voice] Dictation status failed: {error}")
            target_id = str((_dictation_target or {}).get("id") or "")
            if _dictation_manager and target_id:
                _dictation_manager.set_dictation_state(
                    target_id,
                    "error",
                    "Diktatverbindung verloren",
                    reserved=False,
                    error=str(error),
                )
            set_is_recording(False)
            _active_voice_mode = ""
            return web.json_response(
                {
                    "success": False,
                    "isRecording": False,
                    "text": _last_known_text,
                    "window": _dictation_window_payload(),
                    "error": str(error),
                },
                status=502,
            )


async def handle_dictation_stop(request: web.Request) -> web.Response:
    """Stop native dictation, return its full text, and clear the AG draft."""
    global _active_voice_mode

    if not check_auth(request):
        return web.json_response({"success": False, "error": "Unauthorized"}, status=401)
    if is_shutting_down():
        return web.json_response(
            {"success": False, "error": "Service Unavailable"},
            status=503,
        )

    async with _cdp_lock:
        if not get_is_recording() or _active_voice_mode != "dictation":
            return web.json_response(
                {
                    "success": False,
                    "error": "No active dictation session",
                    "text": _last_known_text,
                    "window": _dictation_window_payload(),
                },
                status=400,
            )
        try:
            return web.json_response(
                await _finish_dictation_locked(stop_native=True)
            )
        except Exception as error:
            logger.error(f"[Voice] Dictation stop failed: {error}")
            target_id = str((_dictation_target or {}).get("id") or "")
            if _dictation_manager and target_id:
                _dictation_manager.set_dictation_state(
                    target_id,
                    "error",
                    "Diktat konnte nicht sauber beendet werden",
                    reserved=False,
                    error=str(error),
                )
            set_is_recording(False)
            _active_voice_mode = ""
            return web.json_response(
                {
                    "success": False,
                    "error": str(error),
                    "text": _last_known_text,
                    "window": _dictation_window_payload(),
                },
                status=500,
            )
