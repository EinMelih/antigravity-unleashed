import asyncio
import json
import os
import time
import aiohttp
from typing import Dict, Any, Optional, AsyncGenerator, Sequence

from src.port_finder import find_devtools
from src.bridge_js import BRIDGE_JS

# Reconnect and streaming constants
RECONNECT_MAX_ATTEMPTS = 3
RECONNECT_DELAYS = [0, 2, 5]
STREAM_POLL_INTERVAL = 0.15
STREAM_STABLE_TIMEOUT = 3.0


class UserInputRequiredError(RuntimeError):
    requires_user_input = True


class AntigravityCDP:
    """Connects to the Antigravity Webview via the Chrome DevTools Protocol (CDP)."""

    def __init__(self, *, profile: Optional[str] = None) -> None:
        self.profile = profile
        self.profile_info = None
        if profile:
            from src.api_profile import APIProfileRuntime
            self.profile_runtime = APIProfileRuntime(profile)
        else:
            self.profile_runtime = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self.msg_id = 0
        self.ws_url: Optional[str] = None
        # A client created for a duplicate window must never fall back to the
        # globally discovered primary target after a renderer/CDP disconnect.
        self._pinned_ws_url: Optional[str] = None
        self.devtools_port: Optional[int] = None
        self.backend_port: Optional[int] = None
        self.pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._bridge_injected = False
        self._lock = asyncio.Lock()  # Serialize chat requests to the webview
        self._connected = False

    async def connect(self, ws_url: Optional[str] = None) -> None:
        """Connect to the Antigravity webview via CDP WebSocket."""
        if self._session or self.ws:
            await self.disconnect()

        target_url = ws_url or self._pinned_ws_url
        if target_url and self.profile_runtime:
            self.profile_runtime.validate_ws_url(target_url)
        if target_url:
            self._pinned_ws_url = target_url
            self.ws_url = target_url
            try:
                import urllib.parse
                if "://" in target_url:
                    parsed = urllib.parse.urlsplit(target_url)
                    self.devtools_port = parsed.port
                else:
                    self.devtools_port = None
            except Exception:
                self.devtools_port = None
            self.backend_port = None
        else:
            loop = asyncio.get_running_loop()
            finder = self.profile_runtime.find_target if self.profile_runtime else find_devtools
            info = await loop.run_in_executor(None, finder)
            if not info:
                raise ConnectionError(
                    "Anti-Gravity DevTools nicht gefunden! Bitte starte die Anti-Gravity Desktop App."
                )

            self.ws_url = info["ws_url"]
            self.devtools_port = info["devtools_port"]
            self.backend_port = info["backend_port"]

        session = aiohttp.ClientSession()
        try:
            ws = await session.ws_connect(self.ws_url)
        except Exception:
            await session.close()
            raise

        self._session = session
        self.ws = ws
        self._reader_task = asyncio.create_task(self._read_loop())
        self._connected = True
        self._bridge_injected = False
        try:
            await self.call_cdp("Runtime.enable", {}, timeout=5)
            await self.call_cdp("Page.enable", {}, timeout=5)
            if self.profile_runtime:
                identity = await self.evaluate("window.electronNative?.getProfileInfo?.()", timeout=5)
                self.profile_runtime.verify_identity(identity)
                self.profile_info = identity
        except Exception:
            await self.disconnect()
            raise
        print(f"[CDP] Connected to WebSocket: {self.ws_url}", flush=True)

    async def disconnect(self) -> None:
        """Disconnect from CDP."""
        self._connected = False
        self._bridge_injected = False
        self.profile_info = None
        if self._reader_task:
            reader_task = self._reader_task
            reader_task.cancel()
            self._reader_task = None
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        for fut in list(self.pending.values()):
            if not fut.done():
                fut.cancel()
        self.pending.clear()
        if self.ws and not self.ws.closed:
            await self.ws.close()
            self.ws = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def reconnect(self, req_id: str = "") -> None:
        """Reconnect to CDP with exponential backoff (max 3 attempts)."""
        tag = f"[CDP] [{req_id}]" if req_id else "[CDP]"
        last_error = None
        pinned_ws_url = self._pinned_ws_url
        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            delay = RECONNECT_DELAYS[attempt] if attempt < len(RECONNECT_DELAYS) else RECONNECT_DELAYS[-1]
            if delay > 0:
                print(f"{tag} Reconnect Versuch {attempt + 1}/{RECONNECT_MAX_ATTEMPTS} - warte {delay}s...", flush=True)
                await asyncio.sleep(delay)
            else:
                print(f"{tag} Reconnect Versuch {attempt + 1}/{RECONNECT_MAX_ATTEMPTS} - sofort...", flush=True)
            try:
                await self.disconnect()
                self.ws_url = None
                self.devtools_port = None
                self.backend_port = None
                if self.profile_runtime:
                    # Rediscover only the dedicated browser after a desktop restart.
                    self._pinned_ws_url = None
                    await self.connect()
                elif pinned_ws_url:
                    await self.connect(ws_url=pinned_ws_url)
                else:
                    await self.connect()
                print(f"{tag} Reconnect erfolgreich (Versuch {attempt + 1})", flush=True)
                return
            except Exception as e:
                last_error = e
                print(f"{tag} Reconnect Versuch {attempt + 1} fehlgeschlagen: {e}", flush=True)
        raise ConnectionError(
            f"CDP Reconnect nach {RECONNECT_MAX_ATTEMPTS} Versuchen fehlgeschlagen: {last_error}"
        )

    async def _read_loop(self) -> None:
        """Background task to read CDP WebSocket messages."""
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    self.observe_protocol_event(data)
                    msg_id = data.get("id")
                    if msg_id and msg_id in self.pending:
                        self.pending[msg_id].set_result(data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    print("[CDP] WebSocket closed/error", flush=True)
                    self._connected = False
                    self._bridge_injected = False
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[CDP] Read loop error: {e}", flush=True)
            self._connected = False
            self._bridge_injected = False
        finally:
            for fut in list(self.pending.values()):
                if not fut.done():
                    fut.set_exception(ConnectionError("CDP WebSocket connection closed abruptly"))
            self.pending.clear()

    def observe_protocol_event(self, data: Dict[str, Any]) -> None:
        """Invalidate renderer-local bridge state after a context/navigation reset."""
        if data.get("method") in {
            "Runtime.executionContextsCleared",
            "Page.frameNavigated",
            "Inspector.detached",
            "Target.detachedFromTarget",
        }:
            self._bridge_injected = False

    async def evaluate(self, expression: str, timeout: float = 60.0) -> Any:
        """Execute JavaScript in the webview and return the result."""
        if not self._connected or not self.ws or self.ws.closed:
            await self.reconnect()

        self.msg_id += 1
        mid = self.msg_id

        future = asyncio.get_running_loop().create_future()
        self.pending[mid] = future

        await self.ws.send_json({
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "timeout": timeout * 1000
            }
        })

        try:
            result = await asyncio.wait_for(future, timeout=timeout + 5)
        except asyncio.TimeoutError:
            self.pending.pop(mid, None)
            raise TimeoutError(f"CDP evaluate timed out after {timeout}s")

        self.pending.pop(mid, None)

        r = result.get("result", {})
        if "exceptionDetails" in r:
            exc = r["exceptionDetails"]
            err_msg = exc.get("text", "Unknown error")
            if "exception" in exc:
                err_msg = exc["exception"].get("description", err_msg)
            raise RuntimeError(f"JS Error: {err_msg}")

        return r.get("result", {}).get("value")

    async def call_cdp(self, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Any:
        """Call a native CDP method and wait for the response from the browser."""
        if not self._connected or not self.ws or self.ws.closed:
            await self.reconnect()

        self.msg_id += 1
        mid = self.msg_id

        future = asyncio.get_running_loop().create_future()
        self.pending[mid] = future

        await self.ws.send_json({
            "id": mid,
            "method": method,
            "params": params
        })

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"CDP command {method} timed out after {timeout}s")
        finally:
            self.pending.pop(mid, None)

        error = result.get("error") if isinstance(result, dict) else None
        if error:
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            message = (
                error.get("message", str(error))
                if isinstance(error, dict)
                else str(error)
            )
            raise RuntimeError(
                f"CDP command {method} failed ({code}): {message}"
            )
        return result

    async def inject_bridge(self) -> None:
        """Inject the JavaScript bridge helper into the webview."""
        if self._bridge_injected:
            try:
                exists = await self.evaluate(
                    "typeof window.__agBridge !== 'undefined' && window.__agBridge._version === 45",
                    timeout=5
                )
                if exists:
                    return
            except Exception:
                pass

        result = await self.evaluate(BRIDGE_JS, timeout=10)
        if self.profile_runtime:
            ready = await self.evaluate("Boolean(window.__agBridge?.findInput?.() && window.__agBridge?._modelSelector?.())", timeout=5)
            if not ready:
                href = await self.evaluate("window.location?.href", timeout=3)
                if isinstance(href, str) and ("chrome-error:" in href or href == "about:blank"):
                    target_url = f"https://127.0.0.1:{self.backend_port}/" if self.backend_port else None
                    if target_url:
                        print(f"[CDP] Page on error URL ({href}). Auto-recovering to {target_url}...", flush=True)
                        try:
                            await self.call_cdp("Page.navigate", {"url": target_url})
                            await asyncio.sleep(2)
                            await self.evaluate(BRIDGE_JS, timeout=10)
                            ready = await self.evaluate("Boolean(window.__agBridge?.findInput?.() && window.__agBridge?._modelSelector?.())", timeout=10)
                        except Exception as e:
                            print(f"[CDP] Auto-recovery navigation failed: {e}", flush=True)
            if not ready:
                self._bridge_injected = False
                raise ConnectionError('API profile is waiting for login or its message composer.')
        self._bridge_injected = True
        print(f"[CDP] Bridge injected: {result}", flush=True)

    @staticmethod
    def _key_event_chunks(text: str) -> Sequence[str]:
        """Split fallback text into CDP-safe chunks of at most 4 UTF-16 units."""
        chunks = []
        current = ""
        current_units = 0
        for character in text:
            character_units = len(character.encode("utf-16-le")) // 2
            if current and current_units + character_units > 4:
                chunks.append(current)
                current = ""
                current_units = 0
            current += character
            current_units += character_units
        if current:
            chunks.append(current)
        return chunks

    async def set_input_text_native(self, text: str) -> bool:
        """Type through native key events so React/Lexical updates its composer state."""
        if not isinstance(text, str):
            raise TypeError("Composer text must be a string.")

        async def focus_composer() -> bool:
            return bool(await self.evaluate("""
              (function() {
                const input = window.__agBridge.findInput();
                if (!input) return false;
                if (input.offsetParent === null) return false;
                input.focus({ preventScroll: true });
                return document.activeElement === input;
              })()
            """))

        if not await focus_composer():
            return False

        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")

        async def clear_composer() -> None:
            if not await focus_composer():
                raise RuntimeError(
                    "The visible Anti-Gravity composer could not be focused."
                )
            events = [
                {
                    "type": "rawKeyDown",
                    "key": "a",
                    "code": "KeyA",
                    "windowsVirtualKeyCode": 65,
                    "nativeVirtualKeyCode": 65,
                    "modifiers": 2,
                },
                {
                    "type": "keyUp",
                    "key": "a",
                    "code": "KeyA",
                    "windowsVirtualKeyCode": 65,
                    "nativeVirtualKeyCode": 65,
                    "modifiers": 2,
                },
                {
                    "type": "rawKeyDown",
                    "key": "Backspace",
                    "code": "Backspace",
                    "windowsVirtualKeyCode": 8,
                    "nativeVirtualKeyCode": 8,
                },
                {
                    "type": "keyUp",
                    "key": "Backspace",
                    "code": "Backspace",
                    "windowsVirtualKeyCode": 8,
                    "nativeVirtualKeyCode": 8,
                },
            ]
            for event in events:
                await self.call_cdp(
                    "Input.dispatchKeyEvent",
                    event,
                    timeout=5.0,
                )
            for _ in range(20):
                cleared = await self.evaluate(r"""
                  (() => {
                    const input = window.__agBridge.findInput();
                    if (!input || input.offsetParent === null) return false;
                    const value = String(
                      input.innerText || input.textContent || input.value || ''
                    ).replace(/\r\n?/g, '\n');
                    return value.replace(/[\r\n\u200B\uFEFF]/g, '') === '';
                  })()
                """)
                if cleared:
                    if not await focus_composer():
                        raise RuntimeError(
                            "The Anti-Gravity composer lost focus after clearing."
                        )
                    return
                await asyncio.sleep(0.05)
            raise RuntimeError(
                "The Anti-Gravity composer could not be cleared exactly."
            )

        async def composer_state() -> Dict[str, Any]:
            expected_text = json.dumps(normalized_text)
            result = await self.evaluate(fr"""
                (() => {{
                  const input = window.__agBridge.findInput();
                  const sendButton = Array.from(document.querySelectorAll('button'))
                    .find(button => {{
                      const label = (button.getAttribute('aria-label') || '').toLowerCase();
                      return label.includes('send') && button.offsetParent !== null;
                  }});
                  const value = String(input
                    ? (input.innerText || input.textContent || input.value || '')
                    : '').replace(/\r\n?/g, '\n');
                  const textMatches = Boolean(
                    input && value === {expected_text}
                  );
                  const sendEnabled = Boolean(
                    sendButton &&
                    !sendButton.disabled &&
                    sendButton.getAttribute('aria-disabled') !== 'true'
                  );
                  return {{
                    inputFound: Boolean(input),
                    textMatches,
                    sendEnabled,
                    ready: textMatches && sendEnabled,
                  }};
                }})()
            """)
            return result if isinstance(result, dict) else {
                "ready": bool(result),
                "textMatches": bool(result),
                "sendEnabled": bool(result),
            }

        async def wait_for_ready(attempts: int) -> Dict[str, Any]:
            last_state: Dict[str, Any] = {}
            for _ in range(attempts):
                last_state = await composer_state()
                if last_state.get("ready"):
                    return last_state
                await asyncio.sleep(0.1)
            return last_state

        try:
            await clear_composer()
            state: Dict[str, Any] = {}
            try:
                if not await focus_composer():
                    raise RuntimeError(
                        "The Anti-Gravity composer lost focus before text insertion."
                    )
                await self.call_cdp(
                    "Input.insertText",
                    {"text": normalized_text},
                    timeout=10.0,
                )
            except Exception as insert_error:
                print(
                    "[WARN] atomic composer insert failed; "
                    f"using bounded key-event fallback: {insert_error}",
                    flush=True,
                )
            else:
                state = await wait_for_ready(20)
                if state.get("ready"):
                    return True
                if state.get("textMatches"):
                    # Lexical accepted the exact text. Give React more time to
                    # enable Send without clearing or duplicating the draft.
                    state = await wait_for_ready(40)
                    return bool(state.get("ready"))

            # Some older Chromium/Lexical combinations reject Input.insertText
            # while still accepting native character events. Clear the
            # unverified draft before this one bounded, chunked fallback.
            await clear_composer()
            if len(normalized_text) > 20000:
                raise ValueError(
                    "Composer text exceeds the 20,000 character native fallback limit."
                )

            async def dispatch_fallback_chunks() -> None:
                for chunk in self._key_event_chunks(normalized_text):
                    if not await focus_composer():
                        raise RuntimeError(
                            "The Anti-Gravity composer lost focus during fallback input."
                        )
                    await self.call_cdp(
                        "Input.dispatchKeyEvent",
                        {
                            "type": "char",
                            "text": chunk,
                            "unmodifiedText": chunk,
                        },
                        timeout=2.0,
                    )

            async with asyncio.timeout(15.0):
                await dispatch_fallback_chunks()
            state = await wait_for_ready(60)
            return bool(state.get("ready"))
        except Exception as e:
            print(f"[WARN] native composer typing failed: {e}", flush=True)
            return False

    async def set_file_input_files(
        self,
        file_paths: Sequence[str],
    ) -> Dict[str, Any]:
        """Load local files into Anti-Gravity's native attachment input."""
        normalized_paths = [
            os.path.abspath(os.fspath(path))
            for path in file_paths
        ]
        missing = [path for path in normalized_paths if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(
                f"Attachment file does not exist: {missing[0]}"
            )

        document = await self.call_cdp(
            "DOM.getDocument",
            {"depth": 1, "pierce": True},
            timeout=5.0,
        )
        document_payload = document.get("result", document)
        root_node_id = int(
            (document_payload.get("root") or {}).get("nodeId") or 0
        )
        if not root_node_id:
            raise RuntimeError("Anti-Gravity document root is unavailable.")

        query = await self.call_cdp(
            "DOM.querySelector",
            {
                "nodeId": root_node_id,
                "selector": 'input[type="file"]',
            },
            timeout=5.0,
        )
        query_payload = query.get("result", query)
        file_input_node_id = int(query_payload.get("nodeId") or 0)
        if not file_input_node_id:
            raise RuntimeError(
                "Anti-Gravity attachment input was not found."
            )

        media_before = int(
            await self.evaluate(
                """(() => Array.from(document.querySelectorAll('img')).filter(
                  image => {
                    const src = String(image.src || '');
                    return src.startsWith('blob:')
                      || src.startsWith('data:image/');
                  }
                ).length)()""",
                timeout=5,
            )
            or 0
        )
        await self.call_cdp(
            "DOM.setFileInputFiles",
            {
                "files": normalized_paths,
                "nodeId": file_input_node_id,
            },
            timeout=15.0,
        )

        expected_names = [os.path.basename(path) for path in normalized_paths]
        expected_count = len(normalized_paths)
        if expected_count == 0:
            return {"success": True, "files": []}
        expected_names_json = json.dumps(expected_names, ensure_ascii=False)
        for _ in range(60):
            state = await self.evaluate(
                f"""(() => {{
                  const input = document.querySelector('input[type="file"]');
                  const expectedNames = {expected_names_json};
                  const bodyText = document.body?.innerText || '';
                  const fileCount = Number(input?.files?.length || 0);
                  const matchedNames = expectedNames.filter(
                    name => bodyText.includes(name)
                  ).length;
                  const mediaCount = Array.from(
                    document.querySelectorAll('img')
                  ).filter(image => {{
                    const src = String(image.src || '');
                    return src.startsWith('blob:')
                      || src.startsWith('data:image/');
                  }}).length;
                  const sendButton = Array.from(
                    document.querySelectorAll('button')
                  ).find(button => {{
                    const label = (
                      button.getAttribute('aria-label') || ''
                    ).toLowerCase();
                    return label.includes('send')
                      && button.offsetParent !== null;
                  }});
                  return {{
                    fileCount,
                    matchedNames,
                    expectedCount: {expected_count},
                    mediaCount,
                    sendEnabled: Boolean(
                      sendButton
                      && !sendButton.disabled
                      && sendButton.getAttribute('aria-disabled') !== 'true'
                    )
                  }};
                }})()""",
                timeout=5,
            )
            attachment_visible = (
                int((state or {}).get("matchedNames") or 0) == expected_count
                or int((state or {}).get("mediaCount") or 0)
                >= media_before + expected_count
            )
            if attachment_visible and bool((state or {}).get("sendEnabled")):
                return {
                    "success": True,
                    "files": expected_names,
                    "mediaBefore": media_before,
                    "mediaElementsAdded": (
                        int((state or {}).get("mediaCount") or 0)
                        - media_before
                    ),
                    **(state or {}),
                }
            await asyncio.sleep(0.1)

        raise RuntimeError(
            "Anti-Gravity did not confirm the selected attachment files."
        )

    async def get_model_catalog(self):
        from src.api_model_catalog import model_rows
        await self.inject_bridge()
        native = await self.evaluate("window.__agBridge.getAvailableModels()", timeout=15)
        if not native or not native.get('success'):
            raise ConnectionError("Native model selector is not ready in the API profile.")
        self._current_native_model = str(native.get('current') or '')
        rows = model_rows(native.get('models') or [])
        if not rows:
            raise ConnectionError("Native API profile returned no available models.")
        return rows

    async def select_verified_model(self, model=None, reasoning_effort=None):
        from src.api_model_catalog import model_rows, resolve_model
        current = await self.evaluate("""(() => {
            const bridge = window.__agBridge;
            const selector = bridge._modelSelector();
            return {label:bridge._modelLabel(selector),ready:!!selector && !selector.disabled && selector.getAttribute('aria-disabled') !== 'true'};
        })()""", timeout=5)
        if isinstance(current, dict) and current.get('ready') and current.get('label'):
            try:
                selected = resolve_model(model_rows([{'label': current['label']}]), model, reasoning_effort, current['label'])
            except ValueError:
                pass  # A different selection still requires the full live catalog.
            else:
                self._current_native_model = current['label']
                self.last_model_selection = selected
                return selected
        rows = await self.get_model_catalog()
        selected = resolve_model(rows, model, reasoning_effort, self._current_native_model)
        accepted = await self.evaluate(f"window.__agBridge.selectModel({json.dumps(selected['native_name'])})", timeout=15)
        if accepted is not True:
            raise ValueError("Native model/reasoning selection was not confirmed; no message was sent.")
        actual = await self.evaluate("window.__agBridge._modelLabel(window.__agBridge._modelSelector())", timeout=5)
        normalize = lambda value: ''.join(character for character in str(value).casefold() if not character.isspace() and character not in '()')
        if normalize(actual) != normalize(selected['native_name']):
            raise ValueError("Native model/reasoning selection does not match the request; no message was sent.")
        self.last_model_selection = selected
        return selected

    async def _wait_for_chat_response(self, before_count, before_last_text, timeout, tag):
        started = time.monotonic()
        last_text = ''
        stable_since = None
        while time.monotonic() - started <= timeout:
            try:
                poll = await self.evaluate(f"window.__agBridge.pollResponse({before_count}, {before_last_text})", timeout=10)
            except Exception as error:
                print(f"{tag} Poll-Fehler: {error}", flush=True)
                await asyncio.sleep(0.15)
                continue
            if isinstance(poll, dict):
                if poll.get('requires_user_input'):
                    return {'error': 'User approval is required in the API profile.', 'requires_user_input': True}
                text = poll.get('text') or ''
                if poll.get('finished') and text:
                    return {'response': text, 'duration_ms': int((time.monotonic() - started) * 1000)}
                if text != last_text:
                    last_text = text
                    stable_since = time.monotonic() if text else None
                # Older renderers keep their conservative fallback. Observed
                # native work must finish before an unchanged partial is final.
                if not poll.get('native_observed') and stable_since is not None and time.monotonic() - stable_since >= 5:
                    return {'response': last_text, 'duration_ms': int((time.monotonic() - started) * 1000)}
            await asyncio.sleep(0.15)
        return {'error': f'Response timeout after {int(timeout)}s', 'partial': last_text}

    async def send_chat(self, message: str, timeout: float = 120.0, model: Optional[str] = None, new_chat: bool = False, project_name: Optional[str] = None, req_id: str = "", reasoning_effort: Optional[str] = None) -> Dict[str, Any]:
        """Send a chat message and wait for the complete AI response."""
        tag = f"[CHAT] [{req_id}]" if req_id else "[CHAT]"
        delivered = False
        self.last_model_selection = None

        async def _do_send() -> Dict[str, Any]:
            nonlocal delivered
            await self.inject_bridge()

            if new_chat:
                try:
                    success = False
                    if project_name:
                        escaped_project = json.dumps(project_name)
                        print(f"{tag} Versuche neuen Chat für Projekt {project_name} zu erstellen...", flush=True)
                        success = await self.evaluate(f"window.__agBridge.startNewConversationForProject({escaped_project})", timeout=15)

                    if not success:
                        print(f"{tag} Fallback zu standardmäßigem New Conversation...", flush=True)
                        await self.evaluate("window.__agBridge.startNewConversation()", timeout=10)
                except Exception as e:
                    print(f"[WARN] {tag} Neuer Chat fehlgeschlagen: {e}", flush=True)

            if self.profile_runtime:
                await self.select_verified_model(model, reasoning_effort)
            elif model:
                escaped_model = json.dumps(model)
                try:
                    await self.evaluate(
                        f"window.__agBridge.selectModel({escaped_model})",
                        timeout=15
                    )
                except Exception as e:
                    print(f"[WARN] {tag} Modellwechsel zu {model} fehlgeschlagen: {e}", flush=True)

            # Primary path: Use bridge's prepareAndSend (reliable, handles Unicode)
            escaped_message = json.dumps(message)
            prep_result = await self.evaluate(
                f"window.__agBridge.prepareAndSend({escaped_message})",
                timeout=30
            )
            if prep_result and prep_result.get("success"):
                delivered = True
                before_count = prep_result.get("beforeCount", 0)
                before_last_text = json.dumps(prep_result.get("beforeLastText", ""))
                print(f"{tag} prepareAndSend erfolgreich, warte auf Antwort...", flush=True)

                return await self._wait_for_chat_response(before_count, before_last_text, timeout, tag)

            # Fallback: Native CDP text input (may fail on special Unicode chars)
            print(f"{tag} prepareAndSend fehlgeschlagen, versuche nativen Input...", flush=True)
            set_ok = await self.set_input_text_native(message)
            if not set_ok:
                return {"error": "Konnte Text nicht im Eingabefeld setzen"}

            # Get snapshot before submitting
            snapshot = await self.evaluate(
                "(() => { const b = window.__agBridge; return { count: b.getMessageCount(), text: b.getLastMessageText() }; })()"
            )
            before_count = snapshot.get("count", 0) if snapshot else 0
            before_last_text = json.dumps(snapshot.get("text", "") if snapshot else "")

            # Submit the message (text already set natively)
            submit_result = await self.evaluate(
                "(() => { const b = window.__agBridge; const inp = b.findInput(); return inp ? b.submitMessage(inp) : {error:'no input'}; })()"
            )
            if not submit_result or submit_result.get("error"):
                return {"error": f"Submit failed: {submit_result}"}

            delivered = True
            return await self._wait_for_chat_response(before_count, before_last_text, timeout, tag)

        async with self._lock:
            # First attempt
            try:
                result = await _do_send()
            except ValueError as first_error:
                if self.profile_runtime:
                    raise
                result = {"error": str(first_error)}
            except Exception as first_error:
                print(f"{tag} Erster Versuch fehlgeschlagen: {first_error}", flush=True)
                result = {"error": str(first_error)}

            # Retry logic: Re-inject bridge and reconnect if needed
            if result and result.get("error") and not result.get('requires_user_input') and not (self.profile_runtime and delivered):
                print(f"{tag} Retry: Erneuter Versuch mit frischer Bridge-Injection...", flush=True)
                try:
                    if not self._connected or not self.ws or self.ws.closed:
                        print(f"{tag} Retry: CDP getrennt, reconnecte...", flush=True)
                        await self.reconnect(req_id=req_id)

                    self._bridge_injected = False
                    result = await _do_send()
                    if result and not result.get("error"):
                        print(f"{tag} Retry erfolgreich!", flush=True)
                    else:
                        print(f"{tag} Retry ebenfalls fehlgeschlagen", flush=True)
                except Exception as retry_error:
                    print(f"{tag} Retry-Fehler: {retry_error}", flush=True)
                    result = {"error": f"Retry fehlgeschlagen: {retry_error}"}

            return result

    async def send_chat_streaming(self, message: str, timeout: float = 120.0, model: Optional[str] = None, new_chat: bool = False, project_name: Optional[str] = None, req_id: str = "", run_id: Optional[int] = None, reasoning_effort: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Send a chat message and stream response deltas back to the caller."""
        tag = f"[STREAM] [{req_id}]" if req_id else "[STREAM]"
        self.last_model_selection = None

        async with self._lock:
            await self.inject_bridge()

            if new_chat:
                try:
                    success = False
                    if project_name:
                        escaped_project = json.dumps(project_name)
                        print(f"{tag} Versuche neuen Chat für Projekt {project_name} zu erstellen...", flush=True)
                        success = await self.evaluate(f"window.__agBridge.startNewConversationForProject({escaped_project})", timeout=15)

                    if not success:
                        print(f"{tag} Fallback zu standardmäßigem New Conversation...", flush=True)
                        await self.evaluate("window.__agBridge.startNewConversation()", timeout=10)
                except Exception as e:
                    print(f"[WARN] {tag} Neuer Chat fehlgeschlagen: {e}", flush=True)

            if self.profile_runtime:
                await self.select_verified_model(model, reasoning_effort)
            elif model:
                escaped_model = json.dumps(model)
                try:
                    await self.evaluate(
                        f"window.__agBridge.selectModel({escaped_model})",
                        timeout=15
                    )
                except Exception as e:
                    print(f"[WARN] {tag} Modellwechsel zu {model} fehlgeschlagen: {e}", flush=True)

            if self.profile_runtime:
                prep_result = await self.evaluate(
                    f"window.__agBridge.prepareAndSend({json.dumps(message)})",
                    timeout=30,
                )
            else:
                set_ok = await self.set_input_text_native(message)
                if not set_ok:
                    raise RuntimeError('Native input could not be prepared for streaming.')
                prep_result = await self.evaluate("window.__agBridge.prepareAndSend('')", timeout=30)

            if not prep_result or prep_result.get("error"):
                error_msg = prep_result.get("error", "prepareAndSend fehlgeschlagen") if prep_result else "Keine Antwort"
                print(f"{tag} Fehler beim Senden: {error_msg}", flush=True)
                raise RuntimeError(error_msg)

            before_count = prep_result["beforeCount"]
            before_last_text = json.dumps(prep_result.get("beforeLastText", ""))

            if run_id:
                try:
                    conv_id = await self.get_active_conversation_id()
                    if conv_id:
                        from src.database import db
                        db.update_agent_run_conversation_id(run_id, conv_id)
                        print(f"{tag} Linked run #{run_id} to conversation {conv_id}", flush=True)
                except Exception as e:
                    print(f"{tag} Failed to link conversation: {e}", flush=True)

            print(f"{tag} Nachricht gesendet, starte Streaming-Poll...", flush=True)

            last_known_text = ""
            stable_count = 0
            response_started = False
            start_time = time.monotonic()
            # 15 seconds fallback stability instead of 3.0s, because the finished flag is our primary signal
            stable_threshold = int(15.0 / STREAM_POLL_INTERVAL)
            total_chars_yielded = 0

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    print(f"{tag} Timeout nach {timeout}s", flush=True)
                    break

                try:
                    poll_result = await self.evaluate(
                        f"window.__agBridge.pollResponse({before_count}, {before_last_text})",
                        timeout=10
                    )
                except Exception as e:
                    print(f"{tag} Poll-Fehler: {e}", flush=True)
                    await asyncio.sleep(STREAM_POLL_INTERVAL)
                    continue

                if not poll_result:
                    await asyncio.sleep(STREAM_POLL_INTERVAL)
                    continue

                current_text = poll_result.get("text", "")
                if poll_result.get('requires_user_input'):
                    raise UserInputRequiredError('User approval is required in the API profile.')
                started = poll_result.get("started", False)
                finished = poll_result.get("finished", False)

                if not response_started:
                    if started:
                        response_started = True
                        print(f"{tag} Antwort begonnen nach {elapsed:.1f}s", flush=True)
                        if current_text and current_text != last_known_text:
                            delta = current_text
                            last_known_text = current_text
                            total_chars_yielded += len(delta)
                            yield delta
                    if finished:
                        break
                    await asyncio.sleep(STREAM_POLL_INTERVAL)
                    continue

                if current_text and len(current_text) > len(last_known_text):
                    delta = current_text[len(last_known_text):]
                    last_known_text = current_text
                    stable_count = 0
                    total_chars_yielded += len(delta)
                    yield delta
                else:
                    # If the text did not grow, we count it as stable
                    stable_count += 1
                    if finished:
                        print(f"{tag} Antwort abgeschlossen per UI-Signal nach {elapsed:.1f}s ({total_chars_yielded} Zeichen gestreamt)", flush=True)
                        break
                    if not poll_result.get('native_observed') and stable_count >= stable_threshold:
                        print(f"{tag} Antwort stabil nach {elapsed:.1f}s (Fallback-Timeout, {total_chars_yielded} Zeichen gestreamt)", flush=True)
                        break

                if finished and current_text == last_known_text:
                    print(f"{tag} Antwort abgeschlossen per UI-Signal (kein Delta) nach {elapsed:.1f}s", flush=True)
                    break

                await asyncio.sleep(STREAM_POLL_INTERVAL)

    async def diagnose(self) -> Dict[str, Any]:
        """Run diagnostics on the webview chat UI."""
        await self.inject_bridge()
        return await self.evaluate("window.__agBridge.diagnose()", timeout=10)

    async def get_active_conversation_id(self) -> Optional[str]:
        """Gets the active conversation ID from the webview URL."""
        try:
            url = await self.evaluate("window.location.href", timeout=5)
            # Match UUID in /c/UUID
            import re
            m = re.search(r'/c/([a-f0-9\-]{36})', url)
            if m:
                return m.group(1)
        except Exception as e:
            print(f"[CDP] Failed to get active conversation ID: {e}", flush=True)
        return None

    # ================================================================
    # Chat Reading Abstraction Layer (stable interface for future API)
    # ================================================================

    async def get_project_list(self) -> Dict[str, Any]:
        """Return only projects currently visible in the Anti-Gravity app."""
        await self.inject_bridge()
        try:
            result = await self.evaluate("window.__agBridge.getProjectList()", timeout=10)
            return result or {"projects": [], "count": 0}
        except Exception as error:
            print(f"[CDP] get_project_list error: {error}", flush=True)
            return {"projects": [], "count": 0, "error": str(error)}

    async def get_chat_list(self) -> Dict[str, Any]:
        """Returns a list of chats visible in the Antigravity sidebar.

        Abstraction layer: currently implemented via CDP DOM scraping.
        Replace this method body when a native Antigravity API becomes available.
        """
        await self.inject_bridge()
        try:
            result = await self.evaluate("window.__agBridge.getChatList()", timeout=15)
            return result or {"chats": [], "active_id": None, "count": 0}
        except Exception as e:
            print(f"[CDP] get_chat_list error: {e}", flush=True)
            return {"chats": [], "active_id": None, "count": 0, "error": str(e)}

    async def archive_chat(self, chat_id: str) -> Dict[str, Any]:
        """Archive one sidebar conversation through Antigravity's native UI."""
        await self.inject_bridge()
        result = await self.evaluate(
            f"window.__agBridge.archiveChat({json.dumps(chat_id)})",
            timeout=15,
        )
        if not isinstance(result, dict) or not result.get("success"):
            detail = (
                result.get("error")
                if isinstance(result, dict)
                else "Antigravity returned no archive result."
            )
            raise RuntimeError(str(detail))
        return result

    async def restore_chat(self, chat_id: str) -> Dict[str, Any]:
        """Restore the active archived conversation through Antigravity's UI."""
        await self.inject_bridge()
        result = await self.evaluate(
            f"window.__agBridge.restoreChat({json.dumps(chat_id)})",
            timeout=20,
        )
        if not isinstance(result, dict) or not result.get("success"):
            detail = (
                result.get("error")
                if isinstance(result, dict)
                else "Antigravity returned no restore result."
            )
            raise RuntimeError(str(detail))
        return result

    async def get_chat_history(self, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns the full message history of a chat with type detection.

        If chat_id is given and differs from the active chat, navigates first.
        Abstraction layer: currently implemented via CDP DOM scraping.
        """
        await self.inject_bridge()
        try:
            # Navigate to target chat if needed
            if chat_id:
                active_id = await self.get_active_conversation_id()
                if active_id != chat_id:
                    await self.navigate_to_chat(chat_id)
                    import asyncio as _asyncio
                    await _asyncio.sleep(1.0)  # Wait for page to settle

            result = await self.evaluate("window.__agBridge.getFullHistory()", timeout=15)
            return result or {"messages": [], "total": 0, "chat_id": chat_id}
        except Exception as e:
            print(f"[CDP] get_chat_history error: {e}", flush=True)
            return {"messages": [], "total": 0, "chat_id": chat_id, "error": str(e)}

    async def get_active_chat_meta(self) -> Dict[str, Any]:
        """Returns metadata about the currently active chat.

        Includes: chat_id, title, model, message_count, is_running, is_streaming.
        Abstraction layer: currently implemented via CDP DOM scraping.
        """
        await self.inject_bridge()
        try:
            result = await self.evaluate("window.__agBridge.getActiveChatMeta()", timeout=10)
            return result or {"chat_id": None, "is_running": False, "message_count": 0}
        except Exception as e:
            print(f"[CDP] get_active_chat_meta error: {e}", flush=True)
            return {"chat_id": None, "is_running": False, "message_count": 0, "error": str(e)}

    async def navigate_to_chat(
        self,
        chat_id: str,
        section: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Navigates the webview to a specific chat by its UUID.

        Abstraction layer: currently implemented via CDP DOM click / history.pushState.
        """
        await self.inject_bridge()
        chat_id_json = json.dumps(chat_id)
        section_json = json.dumps(section)
        try:
            result = await self.evaluate(
                f"window.__agBridge.navigateToChat({chat_id_json}, {section_json})",
                timeout=15
            )
            if result and result.get("reload_required") and result.get("target_url"):
                navigation = await self.call_cdp(
                    "Page.navigate",
                    {"url": result["target_url"]},
                    timeout=15,
                )
                if navigation.get("error"):
                    return {
                        "success": False,
                        "chat_id": chat_id,
                        "error": str(navigation["error"]),
                    }
                self._bridge_injected = False
                for _ in range(60):
                    await asyncio.sleep(0.25)
                    if await self.get_active_conversation_id() == chat_id:
                        return {
                            "success": True,
                            "chat_id": chat_id,
                            "url": result["target_url"],
                            "reloaded": True,
                        }
                return {
                    "success": False,
                    "chat_id": chat_id,
                    "error": "The full page navigation did not reach the target conversation.",
                }
            return result or {"success": False, "chat_id": chat_id}
        except Exception as e:
            print(f"[CDP] navigate_to_chat error: {e}", flush=True)
            return {"success": False, "chat_id": chat_id, "error": str(e)}

    async def stream_chat_tokens(
        self,
        chat_id: Optional[str] = None,
        timeout: float = 300.0,
        poll_interval: float = 0.4
    ) -> "AsyncGenerator[Dict[str, Any], None]":
        """Streams new tokens from the active (or specified) chat as they appear.

        Yields dicts with keys: delta, type, message_index, current_len,
        is_running, finished, timestamp.

        Abstraction layer: currently implemented by polling window.__agBridge.pollNewTokens().
        Replace with WebSocket subscription when native API is available.
        """
        import asyncio as _asyncio
        import time as _time

        await self.inject_bridge()

        # Navigate to target chat if needed
        if chat_id:
            active_id = await self.get_active_conversation_id()
            if active_id != chat_id:
                await self.navigate_to_chat(chat_id)
                await _asyncio.sleep(1.0)

        # Get initial state
        try:
            meta = await self.evaluate("window.__agBridge.getActiveChatMeta()", timeout=10)
        except Exception:
            meta = {}

        last_index = (meta.get("message_count") or 1) - 1
        if last_index < 0:
            last_index = 0
        last_len = 0

        start_time = _time.monotonic()
        consecutive_idle = 0
        MAX_IDLE_CYCLES = int(30 / poll_interval)  # 30s of no activity = stop

        while True:
            elapsed = _time.monotonic() - start_time
            if elapsed > timeout:
                yield {"type": "system", "delta": "", "finished": True,
                       "reason": "timeout", "duration_s": round(elapsed, 1)}
                break

            try:
                poll = await self.evaluate(
                    f"window.__agBridge.pollNewTokens({last_index}, {last_len})",
                    timeout=8
                )
            except Exception as e:
                print(f"[CDP] stream_chat_tokens poll error: {e}", flush=True)
                await _asyncio.sleep(poll_interval)
                continue

            if not poll:
                await _asyncio.sleep(poll_interval)
                continue

            import datetime as _dt
            now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

            if poll.get("has_new") and poll.get("delta"):
                consecutive_idle = 0
                last_index = poll["message_index"]
                last_len = poll["current_len"]
                yield {
                    "delta": poll["delta"],
                    "type": poll.get("type", "text"),
                    "message_index": last_index,
                    "current_len": last_len,
                    "is_running": poll.get("is_running", False),
                    "finished": poll.get("finished", False),
                    "timestamp": now_iso
                }
                if poll.get("finished"):
                    yield {"type": "system", "delta": "", "finished": True,
                           "reason": "completed", "duration_s": round(elapsed, 1)}
                    break
            else:
                consecutive_idle += 1
                # If not running and idle for a while, conclude stream
                if not poll.get("is_running") and consecutive_idle >= MAX_IDLE_CYCLES:
                    yield {"type": "system", "delta": "", "finished": True,
                           "reason": "idle", "duration_s": round(elapsed, 1)}
                    break

            await _asyncio.sleep(poll_interval)
