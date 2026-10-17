"""Own the Windows desktop profile used exclusively by the public AI API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from src.config import config


API_PROFILE_NAME = "api"
PROFILE_CONTRACT_VERSION = 2
_START_LOCK = threading.Lock()


class APIProfileRuntime:
    def __init__(self, profile: str = API_PROFILE_NAME):
        if profile != API_PROFILE_NAME:
            raise ValueError("The public API requires its dedicated 'api' profile.")
        self.profile = profile
        options = config.config_dict.get("api_profile", {})
        self.devtools_port = int(options.get("devtools_port", 9229))
        if not 1024 <= self.devtools_port <= 65535:
            raise ValueError("Invalid API profile DevTools port.")
        from src import api_window
        api_window.start_enforcer(self.devtools_port)
        self.private_home = Path.home()
        local_app_data = Path(os.environ.get("LOCALAPPDATA") or self.private_home / "AppData/Local")
        self.profile_home = local_app_data / "AntigravityApiProfile/home"
        self.workspace_dir = self.profile_home / "workspace"
        self.config_dir = self.profile_home / ".gemini/config"
        self.user_data_dir = self.profile_home / "AppData/Roaming/Antigravity-api"
        self.app_data_dir = self.profile_home / ".gemini/antigravity-api"
        self.auth_source_user_data_dir = Path(os.environ.get("APPDATA") or self.private_home / "AppData/Roaming") / "Antigravity-api"
        install_override = os.environ.get("ANTIGRAVITY_INSTALL_DIR") or os.environ.get("ANTIGRAVITY_DESKTOP_EXE")
        self.executable = Path(install_override) if install_override and Path(install_override).suffix.lower() == ".exe" else Path(install_override or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Programs/Antigravity") / "Antigravity.exe"
        self._last_launch = 0.0

    @staticmethod
    def _normalized_path(value: Any) -> str:
        return str(Path(str(value)).resolve()).casefold()

    def verify_identity(self, info: dict) -> None:
        expected = {
            "user_data_dir": self.user_data_dir,
            "app_data_dir": self.app_data_dir,
            "settings_path": self.config_dir / "config.json",
            "home_dir": self.profile_home,
            "config_dir": self.config_dir,
            "process_cwd": self.workspace_dir,
        }
        if not isinstance(info, dict) or info.get("profile_contract_version") != PROFILE_CONTRACT_VERSION or info.get("profile") != self.profile:
            raise ConnectionError("API target is not the dedicated Anti-Gravity API profile.")
        for key, path in expected.items():
            if not info.get(key) or self._normalized_path(info[key]) != self._normalized_path(path):
                raise ConnectionError(f"API profile isolation failed: {key} does not belong to the API profile.")

    def validate_ws_url(self, url: str) -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != self.devtools_port:
            raise ConnectionError("API CDP targets must belong to the dedicated API browser port.")

    def _verify_installed_modifier(self) -> None:
        archive = self.executable.parent / "resources/app.asar"
        record_path = Path.home() / ".gemini/antigravity/scratch/verified_repack_installation.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            with archive.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
        except (OSError, ValueError) as error:
            raise ConnectionError("API profile launch requires a runtime-verified desktop modifier.") from error
        if record.get("profile_contract_version") != PROFILE_CONTRACT_VERSION or record.get("installed_asar_sha256") != digest:
            raise ConnectionError("Desktop profile isolation has not been verified for the installed archive. Run the updated injector.")

    def _seed_authentication_once(self) -> None:
        for directory in (self.app_data_dir, self.user_data_dir, self.user_data_dir / "logs", self.config_dir, self.workspace_dir, self.profile_home / "AppData/Local/Temp"):
            directory.mkdir(parents=True, exist_ok=True)
        initial_files = {
            self.config_dir / "config.json": json.dumps({"plugins": {}, "sidecars": {}, "userSettings": {}}),
            self.config_dir / "AGENTS.md": (
                "# API profile rules\n\n"
                "This environment has its own home, Gemini configuration, memory and workspace.\n"
                "Private profile rules, memory, plugins and sidecars are not part of this environment.\n"
                "Use the API workspace and profile directories for files created by API requests.\n"
                "Do not load or modify another profile's rules, memory or configuration.\n"
                "Do not start dashboard services or synchronize another profile's configuration.\n"
            ),
            self.config_dir / "USER.md": "# API profile preferences\n\nThis profile serves API requests with its own rules and files.\n",
            self.config_dir / "MEMORY.md": "# API profile memory\n\nNo private profile memory has been imported.\n",
        }
        for path, content in initial_files.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        marker = self.app_data_dir / "api_profile_seed.json"
        if marker.exists():
            return
        copied = []
        warnings = []
        # Preserve only Google authentication from the former API browser profile.
        # Never import its conversations, local storage, rules or personal settings.
        original_data = self.auth_source_user_data_dir
        local_state = original_data / "Local State"
        if local_state.is_file() and not (self.user_data_dir / "Local State").exists():
            state = json.loads(local_state.read_text(encoding="utf-8"))
            (self.user_data_dir / "Local State").write_text(json.dumps({"os_crypt": state.get("os_crypt", {})}), encoding="utf-8")
        cookies_source = original_data / "Network/Cookies"
        cookies_target = self.user_data_dir / "Network/Cookies"
        if cookies_source.is_file() and not cookies_target.exists():
            cookies_target.parent.mkdir(exist_ok=True)
            try:
                with sqlite3.connect(cookies_source.as_uri() + "?mode=ro", uri=True, timeout=2) as source:
                    with sqlite3.connect(cookies_target) as target:
                        source.backup(target)
                        target.execute("DELETE FROM cookies WHERE NOT (host_key = 'google.com' OR host_key LIKE '%.google.com' OR host_key = 'googleapis.com' OR host_key LIKE '%.googleapis.com' OR host_key = 'antigravity.google' OR host_key LIKE '%.antigravity.google')")
                        target.commit()
                        target.execute("VACUUM")
                copied.append("authentication_cookies")
            except (sqlite3.Error, OSError):
                warnings.append('authentication_cookie_copy_unavailable')
                print('[API Profile] Authentication cookies could not be copied; login may be required in the API window.', flush=True)
        marker.write_text(json.dumps({"profile": self.profile, "profile_contract_version": PROFILE_CONTRACT_VERSION, "seeded_at": time.time(), "copied": copied, "warnings": warnings}), encoding="utf-8")

    def get_process_ids(self) -> list[int]:
        if os.name != "nt":
            return []
        environment = os.environ.copy()
        environment["AMS_API_PROFILE_ARGUMENT"] = "--ams-profile=api"
        environment["AMS_API_PROFILE_EXE"] = str(self.executable.resolve())
        command = r"""
$rows = @(Get-CimInstance Win32_Process -Filter "Name = 'Antigravity.exe'")
$argument = [Regex]::Escape($env:AMS_API_PROFILE_ARGUMENT)
$roots = @($rows | Where-Object { $_.ExecutablePath -eq $env:AMS_API_PROFILE_EXE -and $_.CommandLine -match ('(?:^|\s)"?' + $argument + '(?:\s|"|$)') } | ForEach-Object { [int]$_.ProcessId })
$owned = [System.Collections.Generic.HashSet[int]]::new()
foreach ($root in $roots) { [void]$owned.Add($root) }
do {
    $added = $false
    foreach ($row in $rows) {
        if ($owned.Contains([int]$row.ParentProcessId) -and $owned.Add([int]$row.ProcessId)) { $added = $true }
    }
} while ($added)
$owned | ForEach-Object { $_ }
"""
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise ConnectionError("API desktop process ownership could not be checked.")
        return [int(line) for line in (result.stdout or "").splitlines() if line.strip().isdigit()]

    def ensure_started(self) -> None:
        if os.name != "nt":
            raise ConnectionError("The isolated native API profile currently requires Windows.")
        with _START_LOCK:
            from src import api_window
            api_window.start_enforcer(self.devtools_port)
            self._verify_path_separation()
            if self.get_process_ids():
                return
            self._verify_installed_modifier()
            if time.monotonic() - self._last_launch < 15:
                return
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", self.devtools_port)) == 0:
                    raise ConnectionError("The API debugging port is occupied by another process; no private-profile fallback is allowed.")
            self._seed_authentication_once()
            environment = os.environ.copy()
            environment.pop("ELECTRON_RUN_AS_NODE", None)
            for key in list(environment):
                if key.upper().startswith(("ANTIGRAVITY_", "GEMINI_")) or key == "REPACK_TRIGGER_CHAT_ID":
                    environment.pop(key)
            home = str(self.profile_home)
            environment.update({
                "HOME": home,
                "USERPROFILE": home,
                "HOMEDRIVE": self.profile_home.drive,
                "HOMEPATH": home[len(self.profile_home.drive):],
                "APPDATA": str(self.profile_home / "AppData/Roaming"),
                "LOCALAPPDATA": str(self.profile_home / "AppData/Local"),
                "TEMP": str(self.profile_home / "AppData/Local/Temp"),
                "TMP": str(self.profile_home / "AppData/Local/Temp"),
                "XDG_CONFIG_HOME": str(self.profile_home / ".config"),
                "XDG_DATA_HOME": str(self.profile_home / ".local/share"),
                "XDG_CACHE_HOME": str(self.profile_home / ".cache"),
                "CODEX_HOME": str(self.profile_home / ".codex"),
                "ANTIGRAVITY_PROFILE_HOME": home,
                "ANTIGRAVITY_API_WORKSPACE": str(self.workspace_dir),
            })
            environment["ANTIGRAVITY_PROFILE"] = self.profile
            environment["ANTIGRAVITY_NO_HUB_AUTOSTART"] = "1"
            environment["ANTIGRAVITY_DATA_DIR"] = str(self.app_data_dir)
            log_dir = self.app_data_dir / "scratch"
            log_dir.mkdir(exist_ok=True)
            with (log_dir / "desktop.log").open("a", encoding="utf-8") as log:
                subprocess.Popen([
                    str(self.executable),
                    "--ams-profile=api",
                    "--wsl-distro=",
                    f"--user-data-dir={self.user_data_dir}",
                    f"--remote-debugging-port={self.devtools_port}",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-features=CalculateNativeWinOcclusion",
                ], cwd=self.workspace_dir, env=environment, stdout=log, stderr=subprocess.STDOUT, close_fds=True, creationflags=subprocess.DETACHED_PROCESS)
            self._last_launch = time.monotonic()

    def find_target(self) -> dict:
        self.ensure_started()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.devtools_port}/json", timeout=2) as response:
                targets = json.load(response)
        except (OSError, ValueError) as error:
            raise ConnectionError("Dedicated API profile is starting or unavailable.") from error
        pages = [row for row in targets if row.get("type") == "page" and row.get("url", "").startswith("https://127.0.0.1:") and row.get("webSocketDebuggerUrl")]
        if not pages:
            raise ConnectionError("Dedicated API profile has no ready application window.")
        target = pages[0]
        self.validate_ws_url(target["webSocketDebuggerUrl"])
        from urllib.parse import urlsplit
        return {"ws_url": target["webSocketDebuggerUrl"], "devtools_port": self.devtools_port, "backend_port": urlsplit(target["url"]).port}

    def validate_conversation(self, conversation_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", conversation_id):
            raise ValueError("Invalid API conversation ID.")
        root = (self.app_data_dir / "conversations").resolve()
        candidates = [root / (conversation_id + suffix) for suffix in ('.pb', '.db')]
        if not any(path.is_file() and not path.is_symlink() and path.resolve().parent == root for path in candidates):
            raise ValueError("Conversation does not belong to the API profile.")

    def _verify_path_separation(self) -> None:
        home = self.profile_home.resolve()
        if self._normalized_path(home) == self._normalized_path(self.private_home):
            raise ConnectionError('API profile home must not alias the private home.')
        for directory in (self.app_data_dir, self.user_data_dir, self.config_dir, self.workspace_dir):
            if not directory.resolve().is_relative_to(home):
                raise ConnectionError('API profile directories must stay inside the API home.')
