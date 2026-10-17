"""Local, token-safe client for the official Codex app-server protocol.

The manager owns a dedicated ``codex app-server`` subprocess. It never reads
Codex authentication files and only exposes a deliberately small public API.
"""

from __future__ import annotations

import json
import hashlib
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence


DEFAULT_REQUEST_TIMEOUT = 20.0
DEFAULT_CHAT_TIMEOUT = 240.0
DEFAULT_START_TIMEOUT = 15.0
_MAX_MODEL_PAGES = 20
_MAX_NOTIFICATIONS = 4096
_MAX_AGENT_TURN_ITEMS = 512
_MAX_PUBLIC_DIFF_CHARS = 200_000
_MAX_PUBLIC_MESSAGE_CHARS = 200_000
_PROJECT_METADATA_CONVERSATION = "antigravity.conversation_id"
_PROJECT_METADATA_WORKSPACE = "antigravity.workspace_marker"
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_THREAD_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_EFFORT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_IMAGE_DATA_URL_PATTERN = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=\r\n]+$",
    re.IGNORECASE,
)


class CodexAppServerError(RuntimeError):
    """Base error with a browser-safe message and optional private detail."""

    code = "codex_app_server_error"

    def __init__(self, public_message: str, *, detail: Optional[str] = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.detail = detail


class CodexBinaryNotFound(CodexAppServerError):
    code = "codex_not_found"


class CodexUnavailable(CodexAppServerError):
    code = "codex_unavailable"


class CodexProtocolError(CodexAppServerError):
    code = "codex_protocol_error"


class CodexRequestTimeout(CodexAppServerError):
    code = "codex_timeout"


class CodexRpcError(CodexAppServerError):
    code = "codex_rpc_error"

    def __init__(self, method: str, rpc_code: Any, rpc_message: str):
        super().__init__(
            "Codex could not complete the request.",
            detail=f"{method}: [{rpc_code}] {rpc_message}",
        )
        self.method = method
        self.rpc_code = rpc_code


class CodexValidationError(CodexAppServerError):
    code = "codex_invalid_request"


def _is_windowsapps_path(path: Path) -> bool:
    return "windowsapps" in str(path).replace("/", "\\").lower().split("\\")


def _usable_binary(path: Path) -> Optional[Path]:
    """Return a resolved regular executable while rejecting Store aliases."""
    try:
        candidate = path.expanduser()
        if _is_windowsapps_path(candidate) or not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
        if _is_windowsapps_path(resolved):
            return None
        if os.name != "nt" and not os.access(resolved, os.X_OK):
            return None
        return resolved
    except (OSError, RuntimeError):
        return None


def resolve_codex_binary(
    env: Optional[Mapping[str, str]] = None,
    *,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> str:
    """Resolve the real Codex binary without selecting Windows Store aliases.

    Resolution order is explicit override, the Codex desktop installation,
    then PATH. An invalid explicit override is treated as a configuration
    error instead of silently selecting a different executable.
    """
    source = os.environ if env is None else env
    override = str(source.get("ANTIGRAVITY_CODEX_BIN") or "").strip().strip('"')
    if override:
        selected = _usable_binary(Path(override))
        if selected is None:
            raise CodexBinaryNotFound(
                "The configured Codex executable is unavailable."
            )
        return str(selected)

    local_app_data = str(source.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        install_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        candidates: List[Path] = []
        try:
            candidates.extend(install_root.glob("*/codex.exe"))
            candidates.extend(install_root.glob("codex.exe"))
        except OSError:
            candidates = []

        usable: List[tuple[float, Path]] = []
        for candidate in candidates:
            selected = _usable_binary(candidate)
            if selected is None:
                continue
            try:
                modified = selected.stat().st_mtime
            except OSError:
                modified = 0.0
            usable.append((modified, selected))
        if usable:
            usable.sort(key=lambda item: (item[0], str(item[1]).lower()), reverse=True)
            return str(usable[0][1])

    for command in ("codex.exe", "codex"):
        try:
            resolved = which(command)
        except (OSError, RuntimeError):
            resolved = None
        if not resolved:
            continue
        selected = _usable_binary(Path(resolved))
        if selected is not None:
            return str(selected)

    raise CodexBinaryNotFound(
        "Codex is not installed or its executable could not be found."
    )


class CodexAppServerManager:
    """Thread-safe lifecycle and JSONL RPC manager for one app-server."""

    def __init__(
        self,
        *,
        binary_resolver: Callable[[], str] = resolve_codex_binary,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        workspace_root: Optional[Path | str] = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        chat_timeout: float = DEFAULT_CHAT_TIMEOUT,
        start_timeout: float = DEFAULT_START_TIMEOUT,
        shutdown_timeout: float = 3.0,
    ) -> None:
        self._binary_resolver = binary_resolver
        self._popen_factory = popen_factory
        self._workspace_root = Path(
            workspace_root or Path(__file__).resolve().parents[1]
        ).resolve()
        self._request_timeout = max(0.1, float(request_timeout))
        self._chat_timeout = max(0.1, float(chat_timeout))
        self._start_timeout = max(0.1, float(start_timeout))
        self._shutdown_timeout = max(0.1, float(shutdown_timeout))

        self._lifecycle_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._notification_condition = threading.Condition()
        self._process: Optional[subprocess.Popen] = None
        self._initialized = False
        self._generation = 0
        self._next_request_id = 0
        self._pending: Dict[int, queue.Queue] = {}
        self._notification_seq = 0
        self._notifications: deque[tuple[int, Dict[str, Any]]] = deque(
            maxlen=_MAX_NOTIFICATIONS
        )
        self._stderr_tail: deque[str] = deque(maxlen=40)

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return bool(
                self._process is not None
                and self._process.poll() is None
                and self._initialized
            )

    def start(self) -> None:
        """Start and initialize the subprocess lazily."""
        with self._lifecycle_lock:
            if (
                self._process is not None
                and self._process.poll() is None
                and self._initialized
            ):
                return
            self._stop_locked()

            binary = self._binary_resolver()
            creationflags = 0
            if os.name == "nt":
                creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                process = self._popen_factory(
                    [binary, "app-server", "--listen", "stdio://"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(self._workspace_root),
                    creationflags=creationflags,
                )
            except (OSError, PermissionError, subprocess.SubprocessError) as error:
                raise CodexUnavailable(
                    "Codex could not be started.", detail=str(error)
                ) from error
            if process.stdin is None or process.stdout is None:
                try:
                    process.terminate()
                except OSError:
                    pass
                raise CodexUnavailable("Codex did not open its local protocol pipes.")

            self._generation += 1
            generation = self._generation
            self._process = process
            self._initialized = False
            with self._notification_condition:
                self._notifications.clear()

            threading.Thread(
                target=self._stdout_reader,
                args=(process, generation),
                name="antigravity-codex-stdout",
                daemon=True,
            ).start()
            if process.stderr is not None:
                threading.Thread(
                    target=self._stderr_reader,
                    args=(process, generation),
                    name="antigravity-codex-stderr",
                    daemon=True,
                ).start()

            # Keep startup serialized until the handshake finishes. The lock
            # is reentrant because _send_message validates the same lifecycle
            # state, while the reader can still deliver responses lock-free.
            try:
                self._request_once(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "antigravity-hub",
                            "title": "Anti-Gravity Hub",
                            "version": "1.0.0",
                        },
                        "capabilities": {
                            # `environments: []` is an experimental app-server
                            # field. Opting in lets the Hub explicitly disable
                            # environments instead of inheriting a default one.
                            "experimentalApi": True,
                            "requestAttestation": False,
                        },
                    },
                    timeout=self._start_timeout,
                )
                self._send_message({"method": "initialized"})
            except Exception:
                self._stop_locked()
                raise

            if self._process is not process or process.poll() is not None:
                self._stop_locked()
                raise CodexUnavailable("Codex exited during initialization.")
            self._initialized = True

    def stop(self) -> None:
        """Terminate the owned subprocess and unblock all waiting callers."""
        with self._lifecycle_lock:
            self._stop_locked()

    close = stop

    def restart(self) -> None:
        self.stop()
        self.start()

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._initialized = False
        self._generation += 1
        self._fail_pending(CodexUnavailable("The Codex process stopped."))
        with self._notification_condition:
            self._notification_condition.notify_all()
        if process is None:
            return

        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=self._shutdown_timeout)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass

    def request(
        self,
        method: str,
        params: Any = None,
        *,
        timeout: Optional[float] = None,
        retry_on_disconnect: bool = False,
    ) -> Any:
        """Send one RPC request, restarting only for explicitly safe reads."""
        attempts = 2 if retry_on_disconnect else 1
        for attempt in range(attempts):
            try:
                self.start()
                return self._request_once(
                    method,
                    params,
                    timeout=timeout or self._request_timeout,
                )
            except (CodexUnavailable, CodexRequestTimeout):
                self.stop()
                if attempt + 1 >= attempts:
                    raise
        raise CodexUnavailable("Codex is unavailable.")

    def _request_once(self, method: str, params: Any, *, timeout: float) -> Any:
        with self._pending_lock:
            self._next_request_id += 1
            request_id = self._next_request_id
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue

        message: Dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._send_message(message)
            try:
                response = response_queue.get(timeout=max(0.1, float(timeout)))
            except queue.Empty as error:
                raise CodexRequestTimeout(
                    "Codex took too long to respond.", detail=method
                ) from error
            if isinstance(response, Exception):
                raise response
            if not isinstance(response, dict):
                raise CodexProtocolError("Codex returned an invalid response.")
            if "error" in response:
                rpc_error = response.get("error") or {}
                raise CodexRpcError(
                    method,
                    rpc_error.get("code"),
                    str(rpc_error.get("message") or "Unknown RPC error"),
                )
            if "result" not in response:
                raise CodexProtocolError("Codex returned an incomplete response.")
            return response["result"]
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _send_message(self, message: Mapping[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lifecycle_lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise CodexUnavailable("Codex is not running.")
            stdin = process.stdin
            with self._write_lock:
                try:
                    stdin.write(payload)
                    stdin.flush()
                except (BrokenPipeError, OSError, ValueError) as error:
                    raise CodexUnavailable(
                        "The Codex connection closed unexpectedly.", detail=str(error)
                    ) from error

    def _stdout_reader(self, process: subprocess.Popen, generation: int) -> None:
        stdout = process.stdout
        if stdout is None:
            return
        try:
            for raw_line in iter(stdout.readline, ""):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._pending_lock:
                        target = self._pending.get(message.get("id"))
                    if target is not None:
                        try:
                            target.put_nowait(message)
                        except queue.Full:
                            pass
                    continue
                if "id" in message and "method" in message:
                    self._reject_server_request(message, process, generation)
                    continue
                if "method" in message:
                    self._record_notification(message)
        except (OSError, ValueError):
            pass
        finally:
            with self._lifecycle_lock:
                current = self._process is process and self._generation == generation
                if current:
                    self._initialized = False
            if current:
                self._fail_pending(
                    CodexUnavailable("The Codex connection closed unexpectedly.")
                )
                with self._notification_condition:
                    self._notification_condition.notify_all()

    def _stderr_reader(self, process: subprocess.Popen, generation: int) -> None:
        stderr = process.stderr
        if stderr is None:
            return
        try:
            for raw_line in iter(stderr.readline, ""):
                if self._generation != generation:
                    break
                line = raw_line.strip()
                if line:
                    self._stderr_tail.append(line[:1000])
        except (OSError, ValueError):
            pass

    def _reject_server_request(
        self,
        message: Mapping[str, Any],
        process: subprocess.Popen,
        generation: int,
    ) -> None:
        """Fail closed for approvals, tools, and token-refresh callbacks."""
        if self._process is not process or self._generation != generation:
            return
        try:
            self._send_message(
                {
                    "id": message.get("id"),
                    "error": {
                        "code": -32601,
                        "message": "Server-initiated requests are disabled by this client.",
                    },
                }
            )
        except CodexAppServerError:
            pass

    def _fail_pending(self, error: Exception) -> None:
        with self._pending_lock:
            targets = list(self._pending.values())
        for target in targets:
            try:
                target.put_nowait(error)
            except queue.Full:
                pass

    def _record_notification(self, message: Dict[str, Any]) -> None:
        with self._notification_condition:
            self._notification_seq += 1
            self._notifications.append((self._notification_seq, message))
            self._notification_condition.notify_all()

    def _notification_cursor(self) -> int:
        with self._notification_condition:
            return self._notification_seq

    def _wait_for_notification(
        self,
        after: int,
        predicate: Callable[[Mapping[str, Any]], bool],
        *,
        timeout: float,
    ) -> tuple[int, Dict[str, Any]]:
        deadline = time.monotonic() + max(0.1, float(timeout))
        cursor = after
        with self._notification_condition:
            while True:
                for sequence, message in self._notifications:
                    if sequence <= cursor:
                        continue
                    cursor = sequence
                    if predicate(message):
                        return sequence, message
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexRequestTimeout(
                        "Codex took too long to complete the response."
                    )
                # Do not acquire the lifecycle lock while holding the
                # notification condition: shutdown takes them in the opposite
                # order so it can wake this waiter. Object reads are atomic and
                # a concurrent stop is re-checked after every wakeup.
                process = self._process
                alive = process is not None and process.poll() is None
                if not alive:
                    raise CodexUnavailable("Codex stopped before completing the response.")
                self._notification_condition.wait(timeout=remaining)

    def account_read(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        result = self.request(
            "account/read",
            {"refreshToken": False},
            timeout=timeout,
            retry_on_disconnect=True,
        )
        if not isinstance(result, dict):
            raise CodexProtocolError("Codex returned an invalid account status.")
        return result

    def status(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Return token-safe availability and authentication state."""
        try:
            result = self.account_read(timeout=timeout)
        except CodexBinaryNotFound:
            return {
                "available": False,
                "running": False,
                "authenticated": False,
                "requires_openai_auth": True,
                "account_type": None,
                "plan_type": None,
            }

        account = result.get("account")
        if not isinstance(account, dict):
            account = None
        requires_auth = bool(result.get("requiresOpenaiAuth", account is None))
        return {
            "available": True,
            "running": self.running,
            # The app-server reports whether OpenAI auth is required as a
            # product policy even when a valid account is already present.
            # Presence of the redacted account object is the signed-in state.
            "authenticated": account is not None,
            "requires_openai_auth": requires_auth,
            "account_type": str(account.get("type")) if account else None,
            "plan_type": (
                str(account.get("planType"))
                if account and account.get("planType") is not None
                else None
            ),
        }

    def login_start(self, *, timeout: Optional[float] = None) -> Dict[str, str]:
        result = self.request(
            "account/login/start",
            {
                "type": "chatgpt",
                "codexStreamlinedLogin": True,
                "useHostedLoginSuccessPage": True,
            },
            timeout=timeout,
        )
        if not isinstance(result, dict) or result.get("type") != "chatgpt":
            raise CodexProtocolError("Codex did not start the ChatGPT sign-in flow.")
        login_id = str(result.get("loginId") or "").strip()
        auth_url = str(result.get("authUrl") or "").strip()
        if not login_id or not auth_url:
            raise CodexProtocolError("Codex returned an incomplete sign-in response.")
        return {"login_id": login_id, "auth_url": auth_url}

    def login_cancel(
        self, login_id: str, *, timeout: Optional[float] = None
    ) -> Dict[str, str]:
        selected = _validate_identifier(login_id, _THREAD_PATTERN, "login_id")
        result = self.request(
            "account/login/cancel",
            {"loginId": selected},
            timeout=timeout,
        )
        if not isinstance(result, dict):
            raise CodexProtocolError("Codex returned an invalid cancellation response.")
        return {"status": str(result.get("status") or "unknown")}

    def logout(self, *, timeout: Optional[float] = None) -> None:
        self.request("account/logout", None, timeout=timeout)

    def list_models(
        self,
        *,
        include_hidden: bool = False,
        timeout: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        models: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        seen_cursors = set()
        for _ in range(_MAX_MODEL_PAGES):
            params: Dict[str, Any] = {
                "limit": 100,
                "includeHidden": bool(include_hidden),
            }
            if cursor:
                params["cursor"] = cursor
            result = self.request(
                "model/list",
                params,
                timeout=timeout,
                retry_on_disconnect=True,
            )
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise CodexProtocolError("Codex returned an invalid model catalog.")
            models.extend(
                public_model(model)
                for model in result["data"]
                if isinstance(model, dict)
            )
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise CodexProtocolError("Codex returned a repeated model cursor.")
            seen_cursors.add(cursor)
        else:
            raise CodexProtocolError("The Codex model catalog exceeded its page limit.")
        return [model for model in models if model.get("id")]

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        thread_id: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        image_urls: Optional[Sequence[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        selected_model = _validate_identifier(model, _MODEL_PATTERN, "model")
        selected_prompt = str(prompt or "").strip()
        if not selected_prompt:
            raise CodexValidationError("A prompt is required.")
        if len(selected_prompt) > 200_000:
            raise CodexValidationError("The prompt is too large.")
        selected_images = []
        for value in image_urls or []:
            image = str(value or "")
            if len(selected_images) >= 5:
                raise CodexValidationError("At most five images are supported.")
            if len(image) > 12_000_000 or not _IMAGE_DATA_URL_PATTERN.fullmatch(image):
                raise CodexValidationError("An image attachment is invalid or too large.")
            selected_images.append(image)
        selected_effort = None
        if reasoning_effort is not None and str(reasoning_effort).strip():
            selected_effort = _validate_identifier(
                str(reasoning_effort).strip().lower(),
                _EFFORT_PATTERN,
                "reasoning_effort",
            )

        self.start()
        actual_model = selected_model
        if thread_id:
            selected_thread_id = _validate_identifier(
                thread_id, _THREAD_PATTERN, "thread_id"
            )
        else:
            thread_result = self._request_once(
                "thread/start",
                {
                    "model": selected_model,
                    "cwd": str(self._workspace_root),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "environments": [],
                    "dynamicTools": [],
                },
                timeout=timeout or self._request_timeout,
            )
            if not isinstance(thread_result, dict):
                raise CodexProtocolError("Codex did not create a chat thread.")
            thread = thread_result.get("thread")
            if not isinstance(thread, dict) or not thread.get("id"):
                raise CodexProtocolError("Codex returned an invalid chat thread.")
            selected_thread_id = str(thread["id"])
            if thread_result.get("model"):
                actual_model = str(thread_result["model"])

        cursor = self._notification_cursor()
        turn_input: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": selected_prompt,
                "text_elements": [],
            }
        ]
        turn_input.extend({"type": "image", "url": image} for image in selected_images)
        turn_params: Dict[str, Any] = {
            "threadId": selected_thread_id,
            "input": turn_input,
            "model": selected_model,
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            "cwd": str(self._workspace_root),
            "runtimeWorkspaceRoots": [str(self._workspace_root)],
            "environments": [],
        }
        if selected_effort:
            turn_params["effort"] = selected_effort
        try:
            turn_result = self._request_once(
                "turn/start",
                turn_params,
                timeout=timeout or self._request_timeout,
            )
            if not isinstance(turn_result, dict):
                raise CodexProtocolError("Codex did not start the chat response.")
            turn = turn_result.get("turn")
            if not isinstance(turn, dict) or not turn.get("id"):
                raise CodexProtocolError("Codex returned an invalid chat response.")
            turn_id = str(turn["id"])

            deadline = time.monotonic() + (timeout or self._chat_timeout)
            deltas: List[str] = []
            completed_turn: Optional[Dict[str, Any]] = None
            while completed_turn is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexRequestTimeout(
                        "Codex took too long to complete the response."
                    )
                cursor, notification = self._wait_for_notification(
                    cursor,
                    lambda item: _belongs_to_turn(
                        item, selected_thread_id, turn_id
                    ),
                    timeout=remaining,
                )
                method = notification.get("method")
                params = notification.get("params") or {}
                if method == "item/agentMessage/delta":
                    delta = params.get("delta")
                    if isinstance(delta, str):
                        deltas.append(delta)
                elif method == "turn/completed":
                    candidate = params.get("turn")
                    if isinstance(candidate, dict):
                        completed_turn = candidate

            status = str(completed_turn.get("status") or "unknown")
            if status != "completed":
                raise CodexRpcError(
                    "turn/completed",
                    status,
                    "The Codex turn did not complete successfully.",
                )
            final_content = _agent_text(completed_turn) or "".join(deltas)
            if not final_content:
                raise CodexProtocolError("Codex completed without an assistant message.")
            return {
                "thread_id": selected_thread_id,
                "turn_id": turn_id,
                "content": final_content,
                "status": status,
                "model": actual_model,
                "reasoning_effort": selected_effort,
            }
        except (CodexUnavailable, CodexRequestTimeout):
            self.stop()
            raise

    def agent_turn(
        self,
        model: str,
        prompt: str,
        *,
        workspace_path: Path | str,
        conversation_id: str,
        thread_id: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Run one write-capable turn inside one pre-authorized workspace.

        HTTP authorization is deliberately kept in ``codex_handlers``. This
        layer independently canonicalizes the workspace and never accepts
        caller-controlled sandbox, approval, network, or writable-root values.
        """
        selected_model = _validate_identifier(model, _MODEL_PATTERN, "model")
        selected_conversation_id = _validate_identifier(
            conversation_id, _THREAD_PATTERN, "conversation_id"
        )
        selected_prompt = str(prompt or "").strip()
        if not selected_prompt:
            raise CodexValidationError("A prompt is required.")
        if len(selected_prompt) > 200_000:
            raise CodexValidationError("The prompt is too large.")
        selected_effort = None
        if reasoning_effort is not None and str(reasoning_effort).strip():
            selected_effort = _validate_identifier(
                str(reasoning_effort).strip().lower(),
                _EFFORT_PATTERN,
                "reasoning_effort",
            )
        selected_workspace = _resolve_agent_workspace(workspace_path)
        workspace = str(selected_workspace)

        self.start()
        if thread_id:
            selected_thread_id = _validate_identifier(
                thread_id, _THREAD_PATTERN, "thread_id"
            )
            thread_result = self._request_once(
                "thread/resume",
                {
                    "threadId": selected_thread_id,
                    "model": selected_model,
                    "cwd": workspace,
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "runtimeWorkspaceRoots": [workspace],
                    "excludeTurns": True,
                },
                timeout=timeout or self._request_timeout,
            )
            thread = _agent_thread_from_result(
                thread_result, "Codex did not resume the project thread."
            )
            project_id = _verify_agent_thread_binding(
                thread,
                thread_id=selected_thread_id,
                workspace=selected_workspace,
            )
            project_result = self._request_once(
                "project/read",
                {"projectId": project_id},
                timeout=timeout or self._request_timeout,
            )
            project = _agent_project_from_result(
                project_result, "Codex did not return the project binding."
            )
            _verify_agent_project(
                project,
                project_id=project_id,
                conversation_id=selected_conversation_id,
                workspace=selected_workspace,
            )
        else:
            project_result = self._request_once(
                "project/create",
                _agent_project_create_params(
                    selected_conversation_id, selected_workspace
                ),
                timeout=timeout or self._request_timeout,
            )
            project = _agent_project_from_result(
                project_result, "Codex did not create the project binding."
            )
            project_id = str(project.get("id") or "")
            _verify_agent_project(
                project,
                project_id=project_id,
                conversation_id=selected_conversation_id,
                workspace=selected_workspace,
            )
            thread_result = self._request_once(
                "thread/start",
                {
                    "model": selected_model,
                    "cwd": workspace,
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "ephemeral": False,
                    "projectId": project_id,
                    "runtimeWorkspaceRoots": [workspace],
                    "dynamicTools": [],
                },
                timeout=timeout or self._request_timeout,
            )
            thread = _agent_thread_from_result(
                thread_result, "Codex did not create the project thread."
            )
            selected_thread_id = str(thread.get("id") or "")
            _verify_agent_thread_binding(
                thread,
                thread_id=selected_thread_id,
                workspace=selected_workspace,
                expected_project_id=project_id,
            )

        cursor = self._notification_cursor()
        turn_params: Dict[str, Any] = {
            "threadId": selected_thread_id,
            "input": [{
                "type": "text",
                "text": selected_prompt,
                "text_elements": [],
            }],
            "model": selected_model,
            "approvalPolicy": "never",
            "sandboxPolicy": {
                "type": "workspaceWrite",
                "writableRoots": [workspace],
                "networkAccess": False,
            },
            "cwd": workspace,
            "runtimeWorkspaceRoots": [workspace],
        }
        if selected_effort:
            turn_params["effort"] = selected_effort

        try:
            turn_result = self._request_once(
                "turn/start",
                turn_params,
                timeout=timeout or self._request_timeout,
            )
            if not isinstance(turn_result, dict):
                raise CodexProtocolError("Codex did not start the project turn.")
            turn = turn_result.get("turn")
            if not isinstance(turn, dict) or not turn.get("id"):
                raise CodexProtocolError("Codex returned an invalid project turn.")
            turn_id = str(turn["id"])

            deadline = time.monotonic() + (timeout or self._chat_timeout)
            completed_turn: Optional[Dict[str, Any]] = None
            completed_items: Dict[str, Mapping[str, Any]] = {}
            usage: Optional[Dict[str, Any]] = None
            while completed_turn is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexRequestTimeout(
                        "Codex took too long to complete the project turn."
                    )
                cursor, notification = self._wait_for_notification(
                    cursor,
                    lambda item: _belongs_to_agent_turn(
                        item, selected_thread_id, turn_id
                    ),
                    timeout=remaining,
                )
                params = notification.get("params") or {}
                method = notification.get("method")
                if method == "item/completed":
                    _collect_completed_agent_item(
                        completed_items, params.get("item")
                    )
                elif method == "thread/tokenUsage/updated":
                    usage = _public_token_usage(params.get("tokenUsage"))
                elif method == "turn/completed":
                    candidate = params.get("turn")
                    if isinstance(candidate, dict):
                        completed_turn = candidate

            status = str(completed_turn.get("status") or "unknown")
            if status != "completed":
                raise CodexRpcError(
                    "turn/completed",
                    status,
                    "The Codex project turn did not complete successfully.",
                )
            public_turn = _merge_completed_agent_items(
                completed_turn, completed_items
            )
            result = _public_agent_turn_result(
                public_turn,
                workspace=selected_workspace,
                thread_id=selected_thread_id,
                turn_id=turn_id,
            )
            if usage:
                result["usage"] = usage
            return result
        except (CodexUnavailable, CodexRequestTimeout):
            self.stop()
            raise


def _validate_identifier(value: Any, pattern: re.Pattern[str], field: str) -> str:
    selected = str(value or "").strip()
    if not selected or not pattern.fullmatch(selected):
        raise CodexValidationError(f"Invalid {field}.")
    return selected


def _belongs_to_turn(
    notification: Mapping[str, Any], thread_id: str, turn_id: str
) -> bool:
    if notification.get("method") not in {
        "item/agentMessage/delta",
        "turn/completed",
    }:
        return False
    params = notification.get("params")
    if not isinstance(params, dict) or params.get("threadId") != thread_id:
        return False
    if notification.get("method") == "turn/completed":
        turn = params.get("turn")
        return isinstance(turn, dict) and turn.get("id") == turn_id
    return params.get("turnId") == turn_id


def _belongs_to_agent_turn(
    notification: Mapping[str, Any], thread_id: str, turn_id: str
) -> bool:
    method = notification.get("method")
    if method not in {
        "item/completed",
        "thread/tokenUsage/updated",
        "turn/completed",
    }:
        return False
    params = notification.get("params")
    if not isinstance(params, dict) or params.get("threadId") != thread_id:
        return False
    if method in {"item/completed", "thread/tokenUsage/updated"}:
        return params.get("turnId") == turn_id
    turn = params.get("turn")
    return isinstance(turn, dict) and turn.get("id") == turn_id


def _agent_text(turn: Mapping[str, Any]) -> str:
    items = turn.get("items")
    if not isinstance(items, list):
        return ""
    messages = [
        str(item.get("text"))
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and item.get("text")
    ]
    return "\n\n".join(messages)


def _collect_completed_agent_item(
    target: Dict[str, Mapping[str, Any]], value: Any
) -> None:
    if not isinstance(value, dict):
        return
    item_id = str(value.get("id") or "").strip()
    if not item_id or not _THREAD_PATTERN.fullmatch(item_id):
        return
    if item_id not in target and len(target) >= _MAX_AGENT_TURN_ITEMS:
        return
    target[item_id] = value


def _merge_completed_agent_items(
    turn: Mapping[str, Any], collected: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    merged = dict(turn)
    items_by_id: Dict[str, Mapping[str, Any]] = dict(collected)
    order = list(items_by_id)
    final_order: List[str] = []
    final_without_id: List[Mapping[str, Any]] = []
    final_items = turn.get("items")
    if not isinstance(final_items, list):
        final_items = []
    for item in final_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id and _THREAD_PATTERN.fullmatch(item_id):
            if item_id not in items_by_id:
                order.append(item_id)
            if item_id not in final_order:
                final_order.append(item_id)
            # The completed turn is authoritative when it repeats an item.
            items_by_id[item_id] = item
        elif len(final_without_id) < _MAX_AGENT_TURN_ITEMS:
            final_without_id.append(item)
    authoritative_final = [items_by_id[item_id] for item_id in final_order]
    authoritative_final.extend(final_without_id)
    authoritative_final = authoritative_final[:_MAX_AGENT_TURN_ITEMS]
    final_ids = set(final_order)
    event_only = [
        items_by_id[item_id] for item_id in order if item_id not in final_ids
    ]
    event_slots = _MAX_AGENT_TURN_ITEMS - len(authoritative_final)
    merged["items"] = event_only[:event_slots] + authoritative_final
    return merged


def _resolve_agent_workspace(value: Any) -> Path:
    selected = str(value or "").strip()
    if not selected:
        raise CodexValidationError("A workspace is required.")
    path = Path(selected).expanduser()
    if not path.is_absolute():
        raise CodexValidationError("The workspace must be an absolute directory.")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise CodexValidationError("The workspace is unavailable.") from error
    if not resolved.is_dir():
        raise CodexValidationError("The workspace must be a directory.")
    return resolved


def _agent_thread_from_result(result: Any, public_message: str) -> Mapping[str, Any]:
    if not isinstance(result, dict):
        raise CodexProtocolError(public_message)
    thread = result.get("thread")
    if not isinstance(thread, dict) or not thread.get("id"):
        raise CodexProtocolError(public_message)
    return thread


def _workspace_marker(workspace: Path) -> str:
    canonical = os.path.normcase(str(workspace)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _agent_project_create_params(
    conversation_id: str, workspace: Path
) -> Dict[str, Any]:
    workspace_marker = _workspace_marker(workspace)
    idempotency_source = (
        f"antigravity-project-v1\0{conversation_id}\0"
        f"{os.path.normcase(str(workspace))}"
    ).encode("utf-8")
    idempotency_key = "antigravity-" + hashlib.sha256(
        idempotency_source
    ).hexdigest()
    safe_workspace_name = re.sub(
        r"[\x00-\x1f\x7f]+", " ", workspace.name or "Workspace"
    ).strip()
    project_name = f"Anti-Gravity · {safe_workspace_name}"[:120].strip()
    return {
        "idempotencyKey": idempotency_key,
        "name": project_name or "Anti-Gravity Workspace",
        "roots": [{"path": str(workspace)}],
        "metadata": {
            _PROJECT_METADATA_CONVERSATION: conversation_id,
            _PROJECT_METADATA_WORKSPACE: workspace_marker,
        },
    }


def _agent_project_from_result(result: Any, public_message: str) -> Mapping[str, Any]:
    if not isinstance(result, dict):
        raise CodexProtocolError(public_message)
    project = result.get("project")
    if not isinstance(project, dict) or not project.get("id"):
        raise CodexProtocolError(public_message)
    return project


def _verify_agent_project(
    project: Mapping[str, Any],
    *,
    project_id: str,
    conversation_id: str,
    workspace: Path,
) -> None:
    returned_project_id = str(project.get("id") or "").strip()
    if (
        not returned_project_id
        or not _THREAD_PATTERN.fullmatch(returned_project_id)
        or returned_project_id != project_id
    ):
        raise CodexProtocolError("Codex returned a different project binding.")
    metadata = project.get("metadata")
    if not isinstance(metadata, dict) or (
        metadata.get(_PROJECT_METADATA_CONVERSATION) != conversation_id
        or metadata.get(_PROJECT_METADATA_WORKSPACE) != _workspace_marker(workspace)
    ):
        raise CodexValidationError(
            "The Codex project does not belong to this conversation."
        )
    roots = project.get("roots")
    if not isinstance(roots, list) or len(roots) != 1:
        raise CodexValidationError(
            "The Codex project does not match the authorized workspace."
        )
    root = roots[0]
    if not isinstance(root, dict):
        raise CodexValidationError(
            "The Codex project does not match the authorized workspace."
        )
    try:
        project_workspace = _resolve_agent_workspace(root.get("path"))
    except CodexValidationError as error:
        raise CodexValidationError(
            "The Codex project does not match the authorized workspace."
        ) from error
    if os.path.normcase(str(project_workspace)) != os.path.normcase(str(workspace)):
        raise CodexValidationError(
            "The Codex project does not match the authorized workspace."
        )


def _verify_agent_thread_binding(
    thread: Mapping[str, Any],
    *,
    thread_id: str,
    workspace: Path,
    expected_project_id: Optional[str] = None,
) -> str:
    if str(thread.get("id") or "") != thread_id:
        raise CodexProtocolError("Codex returned a different project thread.")
    project_id = str(thread.get("projectId") or "").strip()
    if not project_id or not _THREAD_PATTERN.fullmatch(project_id):
        raise CodexProtocolError("Codex returned an invalid project binding.")
    if expected_project_id is not None and project_id != expected_project_id:
        raise CodexValidationError("The Codex thread belongs to another project.")
    try:
        returned_workspace = _resolve_agent_workspace(thread.get("cwd"))
    except CodexValidationError as error:
        raise CodexProtocolError(
            "Codex returned an invalid project workspace."
        ) from error
    if os.path.normcase(str(returned_workspace)) != os.path.normcase(str(workspace)):
        raise CodexProtocolError("Codex selected a different project workspace.")
    return project_id


def _workspace_relative_path(value: Any, workspace: Path) -> Optional[str]:
    selected = str(value or "").strip()
    if not selected:
        return None
    candidate = Path(selected)
    try:
        resolved = (
            candidate.resolve(strict=False)
            if candidate.is_absolute()
            else (workspace / candidate).resolve(strict=False)
        )
        relative = resolved.relative_to(workspace)
    except (OSError, RuntimeError, ValueError):
        return None
    public_path = relative.as_posix()
    return public_path if public_path and public_path != "." else None


def _public_text(value: Any, workspace: Path, *, limit: int) -> str:
    text = str(value or "")
    workspace_forms = {
        str(workspace),
        str(workspace).replace("\\", "/"),
        str(workspace).replace("/", "\\"),
    }
    for workspace_form in sorted(workspace_forms, key=len, reverse=True):
        if workspace_form:
            text = re.sub(re.escape(workspace_form), ".", text, flags=re.IGNORECASE)
    if len(text) > limit:
        marker = "\n...[truncated]"
        if limit <= len(marker):
            return marker[:limit]
        return text[: limit - len(marker)] + marker
    return text


def _public_agent_turn_result(
    turn: Mapping[str, Any],
    *,
    workspace: Path,
    thread_id: str,
    turn_id: str,
) -> Dict[str, Any]:
    activities: List[Dict[str, Any]] = []
    files_changed: List[str] = []
    seen_files = set()
    diff_sections: List[str] = []
    diff_chars = 0
    items = turn.get("items")
    if not isinstance(items, list):
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "commandExecution":
            command = _public_text(item.get("command"), workspace, limit=500).strip()
            title = command.splitlines()[0][:240] if command else "Command"
            detail_parts = []
            if item.get("exitCode") is not None:
                detail_parts.append(f"Exit code: {item['exitCode']}")
            if item.get("durationMs") is not None:
                detail_parts.append(f"Duration: {item['durationMs']} ms")
            activity: Dict[str, Any] = {
                "type": "command",
                "title": title,
                "status": str(item.get("status") or "unknown"),
            }
            if detail_parts:
                activity["detail"] = " · ".join(detail_parts)
            activities.append(activity)
        elif item_type == "fileChange":
            item_files: List[str] = []
            changes = item.get("changes")
            if not isinstance(changes, list):
                changes = []
            for change in changes:
                if not isinstance(change, dict):
                    continue
                public_path = _workspace_relative_path(change.get("path"), workspace)
                if not public_path:
                    continue
                item_files.append(public_path)
                if public_path not in seen_files:
                    seen_files.add(public_path)
                    files_changed.append(public_path)
                raw_diff = change.get("diff")
                if not isinstance(raw_diff, str) or not raw_diff or diff_chars >= _MAX_PUBLIC_DIFF_CHARS:
                    continue
                heading = f"### {public_path} ({change.get('kind') or 'change'})\n"
                remaining = _MAX_PUBLIC_DIFF_CHARS - diff_chars - len(heading)
                if remaining <= 0:
                    continue
                public_diff = _public_text(raw_diff, workspace, limit=remaining)
                section = heading + public_diff
                diff_sections.append(section)
                diff_chars += len(section)
            if item_files:
                activities.append({
                    "type": "file_change",
                    "title": (
                        f"Changed {item_files[0]}"
                        if len(item_files) == 1
                        else f"Changed {len(item_files)} files"
                    ),
                    "detail": ", ".join(item_files[:20]),
                    "status": str(item.get("status") or "unknown"),
                })

    message = _public_text(
        _agent_text(turn) or "Codex completed the project turn.",
        workspace,
        limit=_MAX_PUBLIC_MESSAGE_CHARS,
    )
    file_count = len(files_changed)
    changes_result: Dict[str, Any] = {
        "files_changed": files_changed,
        "summary": (
            "No files changed."
            if file_count == 0
            else f"{file_count} file{'s' if file_count != 1 else ''} changed."
        ),
    }
    if diff_sections:
        changes_result["diff"] = "\n\n".join(diff_sections)
    return {
        "success": True,
        "status": "completed",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "message": message,
        "activity": activities,
        "changes": changes_result,
    }


def _public_token_usage(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None

    key_map = {
        "inputTokens": "input_tokens",
        "cachedInputTokens": "cached_input_tokens",
        "cacheWriteInputTokens": "cache_write_input_tokens",
        "outputTokens": "output_tokens",
        "reasoningOutputTokens": "reasoning_output_tokens",
        "totalTokens": "total_tokens",
    }

    def breakdown(candidate: Any) -> Dict[str, int]:
        if not isinstance(candidate, dict):
            return {}
        return {
            public_key: int(candidate[source_key])
            for source_key, public_key in key_map.items()
            if isinstance(candidate.get(source_key), int)
            and not isinstance(candidate.get(source_key), bool)
        }

    result: Dict[str, Any] = {}
    last = breakdown(value.get("last"))
    total = breakdown(value.get("total"))
    if last:
        result["last"] = last
    if total:
        result["total"] = total
    context_window = value.get("modelContextWindow")
    if isinstance(context_window, int) and not isinstance(context_window, bool):
        result["model_context_window"] = context_window
    return result or None


def _string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, str)]


def public_model(model: Mapping[str, Any]) -> Dict[str, Any]:
    """Whitelist stable, non-secret model catalog fields for the browser."""
    efforts: List[Dict[str, str]] = []
    for effort in model.get("supportedReasoningEfforts") or []:
        if not isinstance(effort, dict) or not effort.get("reasoningEffort"):
            continue
        efforts.append(
            {
                "value": str(effort["reasoningEffort"]),
                "description": str(effort.get("description") or ""),
            }
        )
    tiers: List[Dict[str, str]] = []
    for tier in model.get("serviceTiers") or []:
        if not isinstance(tier, dict) or not tier.get("id"):
            continue
        tiers.append(
            {
                "id": str(tier["id"]),
                "name": str(tier.get("name") or tier["id"]),
                "description": str(tier.get("description") or ""),
            }
        )
    return {
        "id": str(model.get("id") or ""),
        "model": str(model.get("model") or model.get("id") or ""),
        "display_name": str(
            model.get("displayName") or model.get("model") or model.get("id") or ""
        ),
        "description": str(model.get("description") or ""),
        "hidden": bool(model.get("hidden", False)),
        "supported_reasoning_efforts": efforts,
        "default_reasoning_effort": (
            str(model.get("defaultReasoningEffort"))
            if model.get("defaultReasoningEffort") is not None
            else None
        ),
        "input_modalities": _string_list(model.get("inputModalities")),
        "service_tiers": tiers,
        "default_service_tier": (
            str(model.get("defaultServiceTier"))
            if model.get("defaultServiceTier") is not None
            else None
        ),
        "is_default": bool(model.get("isDefault", False)),
    }


_manager_lock = threading.Lock()
_manager: Optional[CodexAppServerManager] = None


def get_codex_manager() -> CodexAppServerManager:
    """Return the process-wide lazy Codex app-server manager."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = CodexAppServerManager()
        return _manager


def close_codex_manager() -> None:
    """Close and discard the process-wide manager during Hub shutdown."""
    global _manager
    with _manager_lock:
        manager = _manager
        _manager = None
    if manager is not None:
        manager.close()
