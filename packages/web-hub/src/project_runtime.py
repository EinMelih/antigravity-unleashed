"""Safe, persistent frontend/backend runtimes for registered Hub projects."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import CONFIG_PATH


SERVICE_NAMES = {"frontend", "backend"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
RESERVED_PORTS = {8000, 8001, 8002, 8007, 8010}
PROFILE_VERSION = 1


@dataclass
class RunningService:
    process: subprocess.Popen[Any]
    log_handle: Any
    config: Dict[str, Any]
    path: Path
    started_at: float


def _free_port(preferred: int) -> int:
    for port in range(preferred, min(preferred + 100, 65535)):
        if port in RESERVED_PORTS:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free localhost port is available for this project runtime.")


def _port_open(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"localhost", "::1"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.15):
            return True
    except OSError:
        return False


def _safe_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _package_json(project_path: Path) -> Dict[str, Any]:
    return _safe_json(project_path / "package.json")


def detect_project_runtime(project_path: Path, project_id: int) -> Dict[str, Any]:
    """Return conservative runtime recommendations from repository files."""
    resolved = project_path.resolve()
    package_candidates = []
    for candidate in [*(resolved / name for name in ("frontend", "client", "web", "ui")), resolved]:
        package = _package_json(candidate)
        if package:
            package_candidates.append((candidate, package))

    def package_parts(package: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        dependencies = {
            **(package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}),
            **(package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}),
        }
        return scripts, dependencies

    def looks_like_frontend(candidate: Path, package: Dict[str, Any]) -> bool:
        scripts, dependencies = package_parts(package)
        frontend_dependencies = {
            "vite", "next", "react", "react-dom", "vue", "nuxt", "svelte",
            "@angular/core", "astro", "react-scripts",
        }
        script_text = " ".join(str(value).lower() for value in scripts.values())
        return bool(
            frontend_dependencies.intersection(dependencies)
            or any(marker in script_text for marker in ("vite", "next ", "next dev", "react-scripts", "ng serve", "astro dev", "webpack serve"))
            or (candidate / "index.html").is_file()
        )

    def looks_like_backend(package: Dict[str, Any]) -> bool:
        scripts, dependencies = package_parts(package)
        backend_dependencies = {
            "fastify", "express", "@nestjs/core", "hono", "koa", "@hapi/hapi",
        }
        main = str(package.get("main") or "").lower()
        script_text = " ".join(str(value).lower() for value in scripts.values())
        return bool(
            backend_dependencies.intersection(dependencies)
            or any(name in scripts for name in ("server", "backend", "api"))
            or "server" in main
            or any(marker in script_text for marker in ("src/server", "server/index", "nest start"))
        )

    frontend_entry = next(
        ((candidate, package) for candidate, package in package_candidates if looks_like_frontend(candidate, package)),
        None,
    )
    frontend_root, frontend_package = frontend_entry or (resolved, {})
    frontend_cwd = str(frontend_root.relative_to(resolved)) or "."
    frontend_scripts, frontend_dependencies = package_parts(frontend_package)
    frontend_port = _free_port(5173)
    backend_port = _free_port(8080)
    frontend_command = ""
    backend_command = ""
    frontend_reason = "No frontend start script was detected."
    backend_reason = "No separate backend start command was detected."

    if "dev" in frontend_scripts:
        if "next" in frontend_dependencies:
            frontend_command = "npm run dev -- --hostname {host} --port {port}"
            frontend_port = _free_port(3000)
            frontend_reason = "Next.js dev script detected in package.json."
        else:
            frontend_command = "npm run dev -- --host {host} --port {port}"
            frontend_reason = f"Frontend dev script detected in {frontend_cwd}/package.json."
    elif "start" in frontend_scripts:
        frontend_command = "npm run start"
        frontend_reason = "Start script detected in package.json; confirm its host and port support."
    elif (frontend_root / "index.html").is_file():
        frontend_command = "python -m http.server {port} --bind {host}"
        frontend_reason = "Static index.html detected."

    root_package = _package_json(resolved)
    root_scripts, _ = package_parts(root_package)
    if root_package and looks_like_backend(root_package):
        for script_name in ("server", "backend", "api", "dev", "start"):
            if script_name in root_scripts:
                backend_command = f"npm run {script_name}"
                backend_reason = f"Node/Bun backend '{script_name}' script detected in root package.json."
                break

    if not frontend_command and root_package and not looks_like_backend(root_package):
        if "start" in root_scripts:
            frontend_command = "npm run start"
            frontend_reason = "Generic start script detected; confirm its host and port support."

    manage_py = resolved / "manage.py"
    if manage_py.is_file():
        backend_command = "python manage.py runserver {host}:{port}"
        backend_reason = "Django manage.py detected."
    else:
        for module_name in ("main.py", "app.py"):
            module_path = resolved / module_name
            if not module_path.is_file():
                continue
            try:
                source = module_path.read_text(encoding="utf-8", errors="ignore")[:200_000]
            except OSError:
                source = ""
            if "FastAPI(" in source:
                backend_command = (
                    f"python -m uvicorn {module_path.stem}:app "
                    "--host {host} --port {port}"
                )
                backend_reason = f"FastAPI application detected in {module_name}."
                break
            if "Flask(" in source:
                backend_command = f"python {module_name}"
                backend_reason = f"Flask application detected in {module_name}; set PORT/HOST through environment."
                break

    def service(
        name: str,
        command: str,
        port: int,
        reason: str,
        cwd: str = ".",
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "enabled": bool(command),
            "command": command,
            "cwd": cwd,
            "host": "127.0.0.1",
            "port": port,
            "health_path": "/",
            "detected": True,
            "reason": reason,
        }

    return {
        "version": PROFILE_VERSION,
        "project_id": int(project_id),
        "detected_at": int(time.time()),
        "services": {
            "frontend": service(
                "Frontend",
                frontend_command,
                frontend_port,
                frontend_reason,
                frontend_cwd,
            ),
            "backend": service("Backend", backend_command, backend_port, backend_reason),
        },
    }


class ProjectRuntimeManager:
    """Own project runtime profiles and only the processes started by this Hub."""

    def __init__(
        self,
        store_path: Optional[Path] = None,
        runtime_root: Optional[Path] = None,
    ) -> None:
        base = CONFIG_PATH.parent
        self.store_path = (store_path or base / "project-runtimes.json").resolve()
        self.runtime_root = (runtime_root or base / "runtime").resolve()
        self.logs_root = self.runtime_root / "logs"
        self.screenshots_root = self.runtime_root / "screenshots"
        self._running: Dict[str, RunningService] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._file_lock = threading.RLock()

    def _key(self, project_id: int, service_name: str) -> str:
        if service_name not in SERVICE_NAMES:
            raise ValueError("service must be frontend or backend.")
        return f"{int(project_id)}:{service_name}"

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _read_store(self) -> Dict[str, Any]:
        with self._file_lock:
            payload = _safe_json(self.store_path)
            payload.setdefault("version", PROFILE_VERSION)
            payload.setdefault("projects", {})
            return payload

    def _write_store(self, payload: Dict[str, Any]) -> None:
        with self._file_lock:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.store_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.store_path)

    def get_profile(self, project: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        project_id = int(project["id"])
        configured = self._read_store().get("projects", {}).get(str(project_id))
        if isinstance(configured, dict):
            return configured, True
        return detect_project_runtime(Path(project["path"]), project_id), False

    def validate_service(
        self,
        project_path: Path,
        service_name: str,
        raw: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._key(0, service_name)
        host = str(raw.get("host") or "127.0.0.1").strip().lower()
        if host not in LOOPBACK_HOSTS:
            raise ValueError("Only localhost/loopback hosts are allowed.")
        try:
            port = int(raw.get("port"))
        except (TypeError, ValueError) as error:
            raise ValueError("port must be an integer.") from error
        if not 1024 <= port <= 65535:
            raise ValueError("port must be between 1024 and 65535.")
        if port in RESERVED_PORTS:
            raise ValueError(f"port {port} is reserved by Anti-Gravity Hub services.")
        command = str(raw.get("command") or "").strip()
        if "\x00" in command or "\n" in command or "\r" in command or len(command) > 500:
            raise ValueError("command contains unsupported characters or is too long.")
        enabled = bool(raw.get("enabled", bool(command)))
        if enabled and not command:
            raise ValueError("An enabled runtime requires a command.")
        relative_cwd = str(raw.get("cwd") or ".").strip() or "."
        resolved_project = project_path.resolve()
        resolved_cwd = (resolved_project / relative_cwd).resolve()
        try:
            resolved_cwd.relative_to(resolved_project)
        except ValueError as error:
            raise ValueError("cwd must stay inside the registered project directory.") from error
        if not resolved_cwd.is_dir():
            raise ValueError(f"Runtime directory does not exist: {resolved_cwd}")
        health_path = str(raw.get("health_path") or "/").strip()
        if not health_path.startswith("/") or len(health_path) > 200:
            raise ValueError("health_path must start with '/'.")
        return {
            "name": "Frontend" if service_name == "frontend" else "Backend",
            "enabled": enabled,
            "command": command,
            "cwd": relative_cwd,
            "host": host,
            "port": port,
            "health_path": health_path,
            "detected": bool(raw.get("detected", False)),
            "reason": str(raw.get("reason") or "Manual project runtime configuration.")[:500],
        }

    def save_profile(self, project: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        project_path = Path(project["path"])
        services = payload.get("services")
        if not isinstance(services, dict):
            raise ValueError("services is required.")
        normalized = {
            name: self.validate_service(project_path, name, services.get(name) or {})
            for name in sorted(SERVICE_NAMES)
        }
        profile = {
            "version": PROFILE_VERSION,
            "project_id": int(project["id"]),
            "updated_at": int(time.time()),
            "services": normalized,
        }
        store = self._read_store()
        store["projects"][str(project["id"])] = profile
        self._write_store(store)
        return profile

    def _service_config(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        profile, _ = self.get_profile(project)
        config = profile.get("services", {}).get(service_name)
        if not isinstance(config, dict):
            raise ValueError(f"No {service_name} runtime is configured.")
        return self.validate_service(Path(project["path"]), service_name, config)

    def _url(self, config: Dict[str, Any]) -> str:
        host = "127.0.0.1" if config["host"] in {"localhost", "::1"} else config["host"]
        return f"http://{host}:{config['port']}{config['health_path']}"

    def _tail_log(self, project_id: int, service_name: str, maximum: int = 16_000) -> str:
        path = self.logs_root / f"{project_id}-{service_name}.log"
        if not path.is_file():
            return ""
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - maximum))
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def dependency_setup(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        """Describe a required JS dependency setup without executing it."""
        config = self._service_config(project, service_name)
        cwd = (Path(project["path"]).resolve() / config["cwd"]).resolve()
        package = _package_json(cwd)
        command = str(config.get("command") or "").strip().lower()
        uses_package_manager = command.startswith(("npm ", "npx ", "pnpm ", "yarn ", "bun "))
        if not package or not uses_package_manager or (cwd / "node_modules").is_dir():
            return {"required": False, "command": "", "reason": ""}
        if (cwd / "package-lock.json").is_file():
            setup_command = "npm ci"
        elif (cwd / "pnpm-lock.yaml").is_file():
            setup_command = "pnpm install --frozen-lockfile"
        elif (cwd / "yarn.lock").is_file():
            setup_command = "yarn install --frozen-lockfile"
        elif (cwd / "bun.lock").is_file() or (cwd / "bun.lockb").is_file():
            setup_command = "bun install --frozen-lockfile"
        else:
            setup_command = "npm install"
        dependency_location = "the project root" if config["cwd"] == "." else config["cwd"]
        return {
            "required": True,
            "command": setup_command,
            "reason": f"Dependencies are not installed in {dependency_location}.",
        }

    def service_status(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        project_id = int(project["id"])
        key = self._key(project_id, service_name)
        config = self._service_config(project, service_name)
        running = self._running.get(key)
        if running and running.process.poll() is not None:
            try:
                running.log_handle.close()
            except OSError:
                pass
            self._running.pop(key, None)
            running = None
        port_active = _port_open(config["host"], config["port"])
        managed = running is not None
        active = bool(port_active or managed)
        status = "running" if port_active else "starting" if managed else "stopped"
        if port_active and not managed:
            status = "external"
        return {
            "service": service_name,
            "active": active,
            "managed": managed,
            "status": status,
            "url": self._url(config),
            "pid": running.process.pid if running else None,
            "started_at": running.started_at if running else None,
            "config": config,
            "log": self._tail_log(project_id, service_name),
            "setup": self.dependency_setup(project, service_name),
        }

    def snapshot(self, project: Dict[str, Any]) -> Dict[str, Any]:
        profile, configured = self.get_profile(project)
        return {
            "project_id": int(project["id"]),
            "configured": configured,
            "profile": profile,
            "services": {
                name: self.service_status(project, name)
                for name in ("frontend", "backend")
            },
            "storage_path": str(self.store_path),
        }

    def _command_args(self, command: str, config: Dict[str, Any]) -> list[str]:
        expanded = command.replace("{host}", config["host"]).replace(
            "{port}", str(config["port"])
        )
        args = shlex.split(expanded, posix=os.name != "nt")
        if not args:
            raise ValueError("Runtime command is empty.")
        executable = shutil.which(args[0])
        if executable:
            args[0] = executable
        return args

    async def start(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        project_id = int(project["id"])
        key = self._key(project_id, service_name)
        async with self._lock(key):
            detected_profile, configured = self.get_profile(project)
            if not configured:
                self.save_profile(project, detected_profile)
            current = self.service_status(project, service_name)
            if current["active"]:
                current["unchanged"] = True
                return current
            config = current["config"]
            if not config["enabled"]:
                raise ValueError(f"The {service_name} runtime is disabled.")
            setup = current.get("setup") or {}
            if setup.get("required"):
                raise RuntimeError(
                    f"Dependencies are missing. Run '{setup['command']}' through the setup action first."
                )
            cwd = (Path(project["path"]).resolve() / config["cwd"]).resolve()
            args = self._command_args(config["command"], config)
            self.logs_root.mkdir(parents=True, exist_ok=True)
            log_path = self.logs_root / f"{project_id}-{service_name}.log"
            log_handle = log_path.open("ab", buffering=0)
            header = (
                f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting "
                f"{service_name}: {' '.join(args)}\n"
            )
            log_handle.write(header.encode("utf-8", errors="replace"))
            environment = os.environ.copy()
            environment.update({"HOST": config["host"], "PORT": str(config["port"])})
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                process = subprocess.Popen(
                    args,
                    cwd=str(cwd),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    creationflags=creation_flags,
                )
            except Exception:
                log_handle.close()
                raise
            self._running[key] = RunningService(
                process=process,
                log_handle=log_handle,
                config=config,
                path=cwd,
                started_at=time.time(),
            )
            await asyncio.sleep(0.45)
            status = self.service_status(project, service_name)
            if process.poll() is not None:
                raise RuntimeError(
                    f"{service_name} exited during startup. Check the runtime log."
                )
            return status

    async def setup_dependencies(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        """Install one runtime's declared dependencies after an explicit action."""
        project_id = int(project["id"])
        key = self._key(project_id, service_name)
        async with self._lock(key):
            current = self.service_status(project, service_name)
            if current["active"]:
                raise RuntimeError(f"Stop the {service_name} runtime before changing dependencies.")
            setup = current.get("setup") or {}
            if not setup.get("required"):
                return {**current, "unchanged": True}
            config = current["config"]
            cwd = (Path(project["path"]).resolve() / config["cwd"]).resolve()
            args = self._command_args(str(setup["command"]), config)
            self.logs_root.mkdir(parents=True, exist_ok=True)
            log_path = self.logs_root / f"{project_id}-{service_name}.log"
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            with log_path.open("ab", buffering=0) as log_handle:
                header = f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Setting up dependencies: {' '.join(args)}\n"
                log_handle.write(header.encode("utf-8", errors="replace"))
                try:
                    completed = await asyncio.to_thread(
                        subprocess.run,
                        args,
                        cwd=str(cwd),
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        shell=False,
                        creationflags=creation_flags,
                        timeout=900,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError("Dependency setup exceeded the 15 minute limit.") from error
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Dependency setup failed with exit code {completed.returncode}. Check the runtime log."
                )
            return self.service_status(project, service_name)

    async def stop(self, project: Dict[str, Any], service_name: str) -> Dict[str, Any]:
        project_id = int(project["id"])
        key = self._key(project_id, service_name)
        async with self._lock(key):
            running = self._running.pop(key, None)
            if running is None:
                status = self.service_status(project, service_name)
                status["unchanged"] = True
                if status["status"] == "external":
                    status["message"] = "The port belongs to an external process and was not stopped."
                return status
            try:
                running.process.terminate()
                await asyncio.to_thread(running.process.wait, 5)
            except Exception:
                running.process.kill()
                await asyncio.to_thread(running.process.wait, 3)
            finally:
                running.log_handle.close()
            return self.service_status(project, service_name)

    async def capture_screenshot(self, project: Dict[str, Any]) -> Dict[str, Any]:
        status = self.service_status(project, "frontend")
        if status["status"] not in {"running", "external"}:
            raise RuntimeError("The frontend must be running before a screenshot can be captured.")
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise RuntimeError("Playwright is not installed for runtime screenshots.") from error
        self.screenshots_root.mkdir(parents=True, exist_ok=True)
        target = self.screenshots_root / f"project-{int(project['id'])}.png"
        async with async_playwright() as playwright:
            browser = None
            last_error: Optional[Exception] = None
            for launch_options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
                try:
                    browser = await playwright.chromium.launch(headless=True, **launch_options)
                    break
                except Exception as error:
                    last_error = error
            if browser is None:
                raise RuntimeError(f"No Chromium browser is available: {last_error}")
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.goto(status["url"], wait_until="networkidle", timeout=30_000)
                await page.screenshot(path=str(target), full_page=True)
            finally:
                await browser.close()
        return {
            "success": True,
            "captured_at": int(time.time()),
            "path": str(target),
            "url": f"/api/projects/{int(project['id'])}/runtime/screenshot/image",
        }

    def screenshot_path(self, project_id: int) -> Path:
        return self.screenshots_root / f"project-{int(project_id)}.png"


project_runtime_manager = ProjectRuntimeManager()
