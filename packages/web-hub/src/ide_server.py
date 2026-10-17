"""Safe local code-server lifecycle and workspace resolution for the Hub."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web

from src.database import db


CODE_SERVER_HOST = "127.0.0.1"
CODE_SERVER_PORT = 8080
WSL_DISTRO = str(
    os.environ.get("ANTIGRAVITY_HUB_WSL_DISTRO") or "Ubuntu"
).strip()
_WSL_DESCRIPTOR_PREFIX = "wsl::"
_CONVERSATION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_code_server_process: Optional[subprocess.Popen] = None
_CODE_SERVER_STATUS_TTL_SECONDS = 20.0
_code_server_status_lock = threading.Lock()
_code_server_start_lock = threading.Lock()
_code_server_status_cache: Optional[Dict[str, Any]] = None
_code_server_status_cached_at = 0.0
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _no_window_creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _port_is_open(
    host: str = CODE_SERVER_HOST,
    port: int = CODE_SERVER_PORT,
) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((host, port)) == 0


def _code_server_is_ready() -> bool:
    if not _port_is_open():
        return False
    try:
        with urllib.request.urlopen(
            f"http://{CODE_SERVER_HOST}:{CODE_SERVER_PORT}/healthz",
            timeout=0.5,
        ) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def discover_code_server() -> Optional[str]:
    """Find a supported native or WSL code-server installation."""
    runtime_root = _PROJECT_ROOT / ".runtime"
    runtime_candidates = (
        sorted(
            runtime_root.glob(
                "code-server*/node_modules/code-server"
            ),
            reverse=True,
        )
        if runtime_root.is_dir()
        else []
    )
    candidates = (
        shutil.which("code-server"),
        shutil.which("code-server.cmd"),
        str(
            Path(os.environ.get("APPDATA", ""))
            / "npm"
            / "node_modules"
            / "code-server"
        ),
        *[str(path) for path in runtime_candidates],
        str(Path.home() / ".local" / "bin" / "code-server"),
        r"C:\Program Files\code-server\bin\code-server.cmd",
    )
    for raw_candidate in candidates:
        if not raw_candidate:
            continue
        candidate = Path(raw_candidate).expanduser()
        if candidate.is_dir():
            if (candidate / "out" / "node" / "entry.js").is_file():
                return str(candidate.resolve())
            continue
        if candidate.is_file():
            return str(candidate.resolve())
    return _discover_wsl_code_server()


def _discover_wsl_code_server() -> Optional[str]:
    if (
        sys.platform != "win32"
        or not shutil.which("wsl.exe")
        or not re.fullmatch(r"[A-Za-z0-9._-]+", WSL_DISTRO)
    ):
        return None
    command = (
        'if command -v code-server >/dev/null 2>&1; then '
        'command -v code-server; '
        'elif [ -x "$HOME/.local/bin/code-server" ]; then '
        'printf "%s\\n" "$HOME/.local/bin/code-server"; '
        "fi"
    )
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                ["wsl.exe", "-d", WSL_DISTRO, "--", "sh", "-lc", command],
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
                creationflags=_no_window_creation_flags(),
            )
            output.seek(0)
            stdout = output.read().decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    executable = stdout.strip().splitlines()
    if result.returncode != 0 or not executable:
        return None
    linux_path = executable[-1].strip()
    if not linux_path.startswith("/"):
        return None
    return f"{_WSL_DESCRIPTOR_PREFIX}{WSL_DISTRO}::{linux_path}"


def _parse_wsl_descriptor(executable: str) -> Optional[tuple[str, str]]:
    if not str(executable or "").startswith(_WSL_DESCRIPTOR_PREFIX):
        return None
    parts = str(executable).split("::", 2)
    if (
        len(parts) != 3
        or not re.fullmatch(r"[A-Za-z0-9._-]+", parts[1])
        or not parts[2].startswith("/")
    ):
        return None
    return parts[1], parts[2]


def _portable_node_executable() -> Optional[str]:
    runtime_root = _PROJECT_ROOT / ".runtime" / "node22"
    if not runtime_root.is_dir():
        return None
    candidates = sorted(runtime_root.glob("node-v22*-win-x64/node.exe"), reverse=True)
    return str(candidates[0].resolve()) if candidates else None


def _code_server_command(executable: str) -> list[str]:
    wsl_installation = _parse_wsl_descriptor(executable)
    if wsl_installation:
        distro, linux_path = wsl_installation
        command = ["wsl.exe", "-d", distro, "--exec", linux_path]
    else:
        candidate = Path(executable)
        entry = candidate / "out" / "node" / "entry.js"
        if candidate.is_dir() and entry.is_file():
            command = [_portable_node_executable() or "node", str(entry)]
        elif (
            sys.platform == "win32"
            and candidate.suffix.lower() in {".cmd", ".bat"}
        ):
            command = ["cmd.exe", "/d", "/s", "/c", str(candidate)]
        else:
            command = [str(candidate)]
    return [
        *command,
        "--bind-addr",
        f"{CODE_SERVER_HOST}:{CODE_SERVER_PORT}",
        "--auth",
        "none",
        "--disable-telemetry",
    ]


def _node_version() -> str:
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=_no_window_creation_flags(),
        )
        return str(result.stdout or result.stderr or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _read_code_server_status() -> Dict[str, Any]:
    executable = discover_code_server()
    running = _code_server_is_ready()
    process = _code_server_process
    wsl_installation = _parse_wsl_descriptor(executable or "")
    runtime = "wsl2" if wsl_installation else "windows"
    return {
        "installed": bool(executable),
        "running": running,
        "runtime": runtime if executable else "",
        "wsl_distribution": (
            wsl_installation[0] if wsl_installation else ""
        ),
        "host": CODE_SERVER_HOST,
        "port": CODE_SERVER_PORT,
        "url": f"http://{CODE_SERVER_HOST}:{CODE_SERVER_PORT}",
        "executable": executable or "",
        "managed_pid": (
            process.pid
            if process is not None and process.poll() is None
            else None
        ),
        "node_version": _node_version(),
        "required_node_major": None if wsl_installation else 22,
        "bundled_node": bool(wsl_installation),
        "security": "loopback-only",
        "install_hint": (
            "Install the official code-server standalone release in WSL2, "
            "then restart the Hub. The bundled runtime does not require the "
            "Windows Node.js or Visual Studio toolchain."
            if not executable
            else ""
        ),
    }


def invalidate_code_server_status_cache() -> None:
    """Invalidate the cached probe result before lifecycle operations."""
    global _code_server_status_cache, _code_server_status_cached_at

    with _code_server_status_lock:
        _code_server_status_cache = None
        _code_server_status_cached_at = 0.0


def code_server_status(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Return a short-lived, thread-safe snapshot of the local IDE state."""
    global _code_server_status_cache, _code_server_status_cached_at

    now = time.monotonic()
    with _code_server_status_lock:
        if (
            not force_refresh
            and _code_server_status_cache is not None
            and now - _code_server_status_cached_at
            < _CODE_SERVER_STATUS_TTL_SECONDS
        ):
            return dict(_code_server_status_cache)

        status = _read_code_server_status()
        _code_server_status_cache = dict(status)
        _code_server_status_cached_at = time.monotonic()
        return dict(status)


def ensure_code_server(timeout_seconds: float = 10.0) -> Dict[str, Any]:
    """Start code-server if installed and wait for its local port."""
    global _code_server_process

    with _code_server_start_lock:
        invalidate_code_server_status_cache()
        if _code_server_is_ready():
            return code_server_status(force_refresh=True)

        executable = discover_code_server()
        if not executable:
            return code_server_status(force_refresh=True)

        command = _code_server_command(executable)
        environment = os.environ.copy()
        environment["CS_DISABLE_GETTING_STARTED_OVERRIDE"] = "true"
        try:
            _code_server_process = subprocess.Popen(
                command,
                cwd=str(Path.home()),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_no_window_creation_flags(),
            )
            invalidate_code_server_status_cache()
        except OSError as error:
            status = code_server_status(force_refresh=True)
            status["error"] = f"code-server could not be started: {error}"
            return status

        deadline = time.monotonic() + max(0.5, timeout_seconds)
        while time.monotonic() < deadline:
            if _code_server_is_ready():
                return code_server_status(force_refresh=True)
            if _code_server_process.poll() is not None:
                break
            time.sleep(0.1)

        status = code_server_status(force_refresh=True)
        if not status["running"]:
            status["error"] = "code-server did not become ready in time."
        return status


def _verified_directory(raw_path: Any, label: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise ValueError(f"{label} has no local workspace path.")
    target = Path(value).expanduser().resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"{label} workspace does not exist: {target}")
    return target


def resolve_project_workspace(project_id: int) -> Dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise LookupError("Project not found.")
    target = _verified_directory(
        project.get("integrity_workspace_path") or project.get("path"),
        "Project",
    )
    return {
        "scope": "project",
        "scope_id": project_id,
        "label": str(project.get("name") or target.name),
        "path": target,
    }


def _conversation_tool_workspace(conversation_id: str) -> Optional[Path]:
    """Return the latest existing absolute work directory recorded by tools."""
    from src.integrity_sync import get_integrity_chat_history

    history = get_integrity_chat_history(conversation_id).get("history") or []
    for entry in reversed(history):
        if not isinstance(entry, dict) or entry.get("type") != "tool_call":
            continue
        enriched = entry.get("enriched")
        if not isinstance(enriched, dict):
            continue
        raw_candidates = []
        file_path = str(enriched.get("file_path") or "").strip()
        if file_path:
            raw_candidates.append(str(Path(file_path).parent))
        cwd = str(enriched.get("cwd") or "").strip()
        if cwd:
            raw_candidates.append(cwd)
        for raw_candidate in raw_candidates:
            candidate = Path(raw_candidate).expanduser()
            if not candidate.is_absolute():
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_dir():
                return resolved
    return None


def resolve_conversation_workspace(conversation_id: str) -> Dict[str, Any]:
    if not _CONVERSATION_ID_RE.fullmatch(str(conversation_id or "")):
        raise ValueError("Invalid Anti-Gravity conversation ID.")

    from src.integrity_sync import scan_antigravity_conversation_catalog

    conversation = next(
        (
            item
            for item in scan_antigravity_conversation_catalog()
            if str(item.get("convo_id") or "").lower()
            == conversation_id.lower()
        ),
        None,
    )
    if conversation is None:
        raise LookupError("Conversation not found.")

    workspace_path = str(conversation.get("workspace_path") or "").strip()
    if workspace_path:
        target = _verified_directory(workspace_path, "Conversation")
        source = "project"
    else:
        target = _conversation_tool_workspace(conversation_id)
        if target is not None:
            source = "tool-workspace"
        else:
            brain_root = (
                Path.home() / ".gemini" / "antigravity" / "brain"
            ).resolve()
            target = (brain_root / conversation_id).resolve()
            if target.parent != brain_root:
                raise ValueError(
                    "Conversation workspace is outside the Brain root."
                )
            if not target.is_dir():
                raise FileNotFoundError(
                    "This conversation has no project, tool, or Brain workspace."
                )
            source = "brain"

    return {
        "scope": "conversation",
        "scope_id": conversation_id,
        "label": str(conversation.get("title") or target.name),
        "source": source,
        "path": target,
    }


def _windows_path_to_wsl(path: Path) -> str:
    raw_path = str(path)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw_path)
    if not match:
        raise ValueError(
            f"WSL code-server cannot map this Windows workspace: {raw_path}"
        )
    drive = match.group(1).lower()
    remainder = match.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{remainder}"


def workspace_url(path: Path, *, runtime: str = "windows") -> str:
    workspace_path = (
        _windows_path_to_wsl(path)
        if runtime == "wsl2"
        else str(path)
    )
    query = urllib.parse.urlencode(
        {"folder": workspace_path},
        quote_via=urllib.parse.quote,
    )
    return f"http://{CODE_SERVER_HOST}:{CODE_SERVER_PORT}/?{query}"


def resolve_control_task_workspace(task_id: str) -> Dict[str, Any]:
    """Resolve the isolated PR worktree, never an arbitrary request path."""
    from src.control_center import ControlCenterError, control_center

    try:
        task = control_center.get_task(str(task_id))
    except ControlCenterError as error:
        if error.status == 404:
            raise LookupError(str(error)) from error
        raise ValueError(str(error)) from error

    configured = str(task.get("worktree_path") or "").strip()
    source = "pr_worktree"
    configured_path = Path(configured).expanduser().resolve() if configured else None
    if (
        task.get("status") == "completed"
        and (configured_path is None or not configured_path.is_dir())
    ):
        project = db.get_project(int(task["project_id"]))
        configured = str(project.get("path") if project else "").strip()
        source = "merged_project"
    if not configured:
        raise FileNotFoundError(
            "Für diesen PR-Task wurde noch kein isoliertes Arbeitsverzeichnis angelegt."
        )

    path = Path(configured).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"PR-Arbeitsverzeichnis existiert nicht: {path}")
    return {
        "kind": "control_task",
        "task_id": str(task["id"]),
        "project_id": int(task["project_id"]),
        "branch_name": str(task.get("branch_name") or ""),
        "source": source,
        "path": path,
    }


async def handle_ide_status(_request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(code_server_status))


async def _workspace_response(workspace: Dict[str, Any]) -> web.Response:
    status = await asyncio.to_thread(ensure_code_server)
    if not status.get("installed"):
        return web.json_response(
            {
                **status,
                "error": "code-server is not installed.",
                "workspace": {
                    **workspace,
                    "path": str(workspace["path"]),
                },
            },
            status=503,
        )
    if not status.get("running"):
        return web.json_response(
            {
                **status,
                "error": status.get("error") or "code-server is not ready.",
            },
            status=503,
        )
    return web.json_response({
        "success": True,
        "ide": status,
        "workspace": {
            **workspace,
            "path": str(workspace["path"]),
        },
        "url": workspace_url(
            workspace["path"],
            runtime=str(status.get("runtime") or "windows"),
        ),
    })


async def handle_open_project_ide(request: web.Request) -> web.Response:
    try:
        project_id = int(request.match_info["id"])
        workspace = await asyncio.to_thread(
            resolve_project_workspace,
            project_id,
        )
        return await _workspace_response(workspace)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except LookupError as error:
        return web.json_response({"error": str(error)}, status=404)
    except FileNotFoundError as error:
        return web.json_response({"error": str(error)}, status=409)


async def handle_open_control_task_ide(request: web.Request) -> web.Response:
    try:
        workspace = await asyncio.to_thread(
            resolve_control_task_workspace,
            request.match_info["task_id"],
        )
        return await _workspace_response(workspace)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except LookupError as error:
        return web.json_response({"error": str(error)}, status=404)
    except FileNotFoundError as error:
        return web.json_response({"error": str(error)}, status=409)


async def handle_open_conversation_ide(request: web.Request) -> web.Response:
    try:
        conversation_id = request.match_info["convo_id"]
        workspace = await asyncio.to_thread(
            resolve_conversation_workspace,
            conversation_id,
        )
        return await _workspace_response(workspace)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except LookupError as error:
        return web.json_response({"error": str(error)}, status=404)
    except FileNotFoundError as error:
        return web.json_response({"error": str(error)}, status=409)
