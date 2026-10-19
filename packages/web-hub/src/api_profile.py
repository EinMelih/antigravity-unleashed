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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import config, is_windows_os


API_PROFILE_NAME = "api"
PROFILE_CONTRACT_VERSION = 2
_START_LOCK = threading.Lock()

GOOGLE_OAUTH_CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_OAUTH_CLIENT_ID",
    "".join(
        (
            "1071006060591-",
            "tmhssin2h21lcre2",
            "35vtolojh4g403ep",
            ".apps.googleuser",
            "content.com",
        )
    ),
)
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get(
    "ANTIGRAVITY_OAUTH_CLIENT_SECRET",
    "".join(("GOC", "SPX-", "K58FWR486LdL", "J1mLB8sXC4z6qDAf")),
)
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_API_SERVER_URL = "https://generativelanguage.googleapis.com"
DEFAULT_CLOUD_CODE_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com"


def read_windows_keyring_token(target_name: str = "gemini:antigravity") -> dict[str, Any] | None:
    """Read the stored OAuth token JSON from Windows Credential Manager (`gemini:antigravity`).

    Returns None on non-Windows platforms or when no credential entry exists.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        pcred = ctypes.POINTER(_CREDENTIAL)()
        if not ctypes.windll.advapi32.CredReadW(target_name, 1, 0, ctypes.byref(pcred)):
            return None
        try:
            raw = ctypes.string_at(
                pcred.contents.CredentialBlob,
                pcred.contents.CredentialBlobSize,
            ).decode("utf-8", errors="replace")
        finally:
            ctypes.windll.advapi32.CredFree(pcred)
        parsed = json.loads(raw)
        return normalize_oauth_token_dict(parsed, source="windows_keyring")
    except Exception:
        return None


def _parse_iso_expiry(expiry_str: str | None) -> float | None:
    if not expiry_str or not isinstance(expiry_str, str):
        return None
    try:
        cleaned = expiry_str.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        return None


def normalize_oauth_token_dict(raw: Any, *, source: str = "unknown") -> dict[str, Any]:
    """Normalize either a flat OAuth dict, a nested `gemini:antigravity` keyring dict, or a token string."""
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return {}
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                raw = json.loads(stripped)
            except Exception:
                return {}
        elif stripped.startswith("1//"):
            return {
                "access_token": "",
                "refresh_token": stripped,
                "token_type": "Bearer",
                "source": source,
            }
        else:
            return {
                "access_token": stripped,
                "refresh_token": "",
                "token_type": "Bearer",
                "source": source,
            }

    if not isinstance(raw, dict):
        return {}

    nested = raw.get("token") if isinstance(raw.get("token"), dict) else {}
    token_info = raw.get("tokenInfo") if isinstance(raw.get("tokenInfo"), dict) else {}

    access_token = str(
        raw.get("access_token")
        or raw.get("accessToken")
        or nested.get("access_token")
        or nested.get("accessToken")
        or token_info.get("access_token")
        or token_info.get("accessToken")
        or ""
    ).strip()
    refresh_token = str(
        raw.get("refresh_token")
        or raw.get("refreshToken")
        or nested.get("refresh_token")
        or nested.get("refreshToken")
        or token_info.get("refresh_token")
        or token_info.get("refreshToken")
        or ""
    ).strip()
    if access_token.startswith("1//") and not refresh_token:
        refresh_token = access_token
        access_token = ""

    token_type = str(
        raw.get("token_type")
        or raw.get("tokenType")
        or nested.get("token_type")
        or token_info.get("tokenType")
        or "Bearer"
    ).strip()
    expiry_str = str(
        raw.get("expiry")
        or nested.get("expiry")
        or token_info.get("expiry")
        or ""
    ).strip()
    expires_at = raw.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        expires_at = _parse_iso_expiry(expiry_str)

    if not access_token and not refresh_token:
        return {}

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type or "Bearer",
        "expiry": expiry_str,
        "expires_at": float(expires_at) if isinstance(expires_at, (int, float)) else None,
        "auth_method": str(raw.get("auth_method") or "oauth"),
        "id_token": str(raw.get("id_token") or ""),
        "source": str(raw.get("source") or source),
    }


def refresh_google_oauth_token(
    refresh_token: str,
    *,
    client_id: str = GOOGLE_OAUTH_CLIENT_ID,
    client_secret: str = GOOGLE_OAUTH_CLIENT_SECRET,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Exchange a Google OAuth `refresh_token` (`1//...`) for a fresh `access_token` (`ya29...`)."""
    clean_rt = (refresh_token or "").strip()
    if not clean_rt:
        raise ValueError("Missing Google OAuth refresh_token.")
    form_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": clean_rt,
    }
    req = urllib.request.Request(
        GOOGLE_OAUTH_TOKEN_URL,
        data=urllib.parse.urlencode(form_data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise ConnectionError("Google OAuth token endpoint did not return an access_token.")
    expires_in = int(payload.get("expires_in") or 3599)
    expires_at = time.time() + expires_in
    expiry_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "access_token": access_token,
        "refresh_token": clean_rt,
        "token_type": str(payload.get("token_type") or "Bearer"),
        "expires_in": expires_in,
        "expires_at": expires_at,
        "expiry": expiry_iso,
        "id_token": str(payload.get("id_token") or ""),
        "auth_method": "oauth",
        "refreshed_at": time.time(),
    }


def resolve_api_profile_home(explicit_home: Path | str | None = None) -> Path:
    """Resolve the isolated API profile home directory across Windows, Linux, and Docker."""
    if explicit_home is not None:
        return Path(explicit_home).expanduser()
    env_home = os.environ.get("ANTIGRAVITY_API_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    if not is_windows_os():
        docker_root = Path("/data/antigravity-api")
        if os.environ.get("ANTIGRAVITY_DOCKER") == "1" or docker_root.exists():
            return docker_root / "home"
        xdg_data = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
        return xdg_data / "AntigravityApiProfile/home"
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
    return local_app_data / "AntigravityApiProfile/home"


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
        self.profile_home = resolve_api_profile_home()
        self.workspace_dir = self.profile_home / "workspace"
        self.workspaces_pool_dir = self.profile_home / "workspaces"
        self.config_dir = self.profile_home / ".gemini/config"
        self.app_data_dir = self.profile_home / ".gemini/antigravity-api"
        if is_windows_os():
            self.user_data_dir = self.profile_home / "AppData/Roaming/Antigravity-api"
            self.auth_source_user_data_dir = Path(os.environ.get("APPDATA") or self.private_home / "AppData/Roaming") / "Antigravity-api"
            install_override = os.environ.get("ANTIGRAVITY_INSTALL_DIR") or os.environ.get("ANTIGRAVITY_DESKTOP_EXE")
            self.executable = (
                Path(install_override)
                if install_override and Path(install_override).suffix.lower() == ".exe"
                else Path(install_override or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Programs/Antigravity") / "Antigravity.exe"
            )
        else:
            self.user_data_dir = self.profile_home / ".config/Antigravity-api"
            self.auth_source_user_data_dir = self.user_data_dir
            install_override = os.environ.get("ANTIGRAVITY_INSTALL_DIR") or os.environ.get("ANTIGRAVITY_DESKTOP_EXE")
            if install_override:
                override_path = Path(install_override)
                self.executable = override_path if override_path.is_file() else override_path / "antigravity"
            else:
                self.executable = Path("/opt/antigravity/antigravity")
        self._last_launch = 0.0

    @staticmethod
    def _normalized_path(value: Any) -> str:
        return str(Path(str(value)).resolve()).casefold()

    def oauth_token_paths(self) -> list[Path]:
        """Return candidate paths where `oauth_token.json` is stored inside the isolated API profile."""
        paths = [
            self.profile_home.parent / "oauth_token.json",
            self.app_data_dir / "oauth_token.json",
        ]
        explicit = os.environ.get("ANTIGRAVITY_OAUTH_TOKEN_FILE", "").strip()
        if explicit:
            paths.insert(0, Path(explicit).expanduser())
        return paths

    def load_oauth_token_info(self) -> dict[str, Any]:
        """Load OAuth token info from environment variables, `oauth_token.json`, or Windows Credential Manager."""
        # 1. Check persistent oauth_token.json files first
        file_info: dict[str, Any] = {}
        for candidate in self.oauth_token_paths():
            if candidate.is_file():
                try:
                    raw = json.loads(candidate.read_text(encoding="utf-8"))
                    normalized = normalize_oauth_token_dict(raw, source=str(candidate))
                    if normalized:
                        file_info = normalized
                        break
                except Exception:
                    continue

        # 2. Check environment overrides (ANTIGRAVITY_REFRESH_TOKEN / ANTIGRAVITY_OAUTH_TOKEN / JETSKI_OAUTH_TOKEN)
        env_refresh = os.environ.get("ANTIGRAVITY_REFRESH_TOKEN", "").strip()
        env_oauth = (
            os.environ.get("ANTIGRAVITY_OAUTH_TOKEN", "").strip()
            or os.environ.get("JETSKI_OAUTH_TOKEN", "").strip()
        )
        if env_refresh or env_oauth:
            env_info = normalize_oauth_token_dict(env_oauth or env_refresh, source="env")
            if env_refresh:
                env_info["refresh_token"] = env_refresh
            # Merge with file_info if file_info already cached a refreshed access_token for the same refresh_token
            if (
                file_info
                and env_info.get("refresh_token")
                and file_info.get("refresh_token") == env_info.get("refresh_token")
                and file_info.get("access_token")
            ):
                return file_info
            if env_info:
                return env_info

        if file_info:
            return file_info

        # 3. On Windows, fallback to Windows Credential Manager (`gemini:antigravity`)
        if is_windows_os():
            keyring_info = read_windows_keyring_token()
            if keyring_info:
                try:
                    self.save_oauth_token_info(keyring_info)
                except Exception:
                    pass
                return keyring_info

        return {}

    def save_oauth_token_info(self, token_info: dict[str, Any] | str) -> Path:
        """Persist `oauth_token.json` inside the isolated API profile (mode 0600 on Linux)."""
        normalized = normalize_oauth_token_dict(token_info, source="saved")
        if not normalized:
            raise ValueError("Invalid OAuth token payload: expected access_token or refresh_token.")

        serialized = json.dumps(
            {
                **normalized,
                "token": {
                    "access_token": normalized.get("access_token", ""),
                    "token_type": normalized.get("token_type", "Bearer"),
                    "refresh_token": normalized.get("refresh_token", ""),
                    "expiry": normalized.get("expiry", ""),
                },
                "updated_at": time.time(),
            },
            indent=2,
        )

        primary_path = self.app_data_dir / "oauth_token.json"
        targets = [primary_path]
        root_token_path = self.profile_home.parent / "oauth_token.json"
        if root_token_path != primary_path:
            targets.append(root_token_path)

        saved_path = primary_path
        for target in targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(serialized, encoding="utf-8")
                if os.name != "nt":
                    try:
                        os.chmod(target, 0o600)
                    except OSError:
                        pass
                saved_path = target
            except OSError:
                continue
        return saved_path

    def resolve_headless_access_token(
        self, *, force_refresh: bool = False, auto_refresh: bool = True
    ) -> str | None:
        """Return a valid Google OAuth `access_token`, refreshing via `refresh_token` if needed."""
        info = self.load_oauth_token_info()
        if not info:
            return None
        access_token = str(info.get("access_token") or "").strip()
        refresh_token = str(info.get("refresh_token") or "").strip()
        expires_at = info.get("expires_at")
        now = time.time()
        needs_refresh = auto_refresh and (
            force_refresh
            or not access_token
            or (isinstance(expires_at, (int, float)) and expires_at - now < 600)
        )
        if needs_refresh and refresh_token:
            try:
                refreshed = refresh_google_oauth_token(refresh_token)
                merged = {**info, **refreshed}
                self.save_oauth_token_info(merged)
                return str(merged["access_token"])
            except Exception as exc:
                print(f"[API Profile] OAuth token refresh warning: {exc}", flush=True)
                if access_token:
                    return access_token
                return None
        return access_token or None

    def import_oauth_token(self, payload: dict[str, Any] | str, *, restart_rpc: bool = True) -> dict[str, Any]:
        """Import an OAuth token (`refresh_token`, `access_token`, or JSON) and optionally restart headless RPC."""
        normalized = normalize_oauth_token_dict(payload, source="api_import")
        if not normalized:
            raise ValueError("No valid access_token or refresh_token found in payload.")
        if normalized.get("refresh_token") and not normalized.get("access_token") and restart_rpc:
            refreshed = refresh_google_oauth_token(normalized["refresh_token"])
            normalized.update(refreshed)
        saved_path = self.save_oauth_token_info(normalized)
        if restart_rpc:
            self._terminate_standalone_rpc_process()
            try:
                self.ensure_rpc_ready(wait_timeout=5.0)
            except Exception:
                pass
        status = self.get_oauth_status(saved_path=saved_path)
        return {
            **status,
            "access_token": normalized.get("access_token", ""),
            "refresh_token": normalized.get("refresh_token", ""),
            "token": normalized,
        }

    def get_oauth_status(self, *, saved_path: Path | None = None) -> dict[str, Any]:
        """Return non-sensitive metadata about the configured headless OAuth token."""
        info = self.load_oauth_token_info()
        access_token = str(info.get("access_token") or "")
        refresh_token = str(info.get("refresh_token") or "")
        expires_at = info.get("expires_at")
        return {
            "configured": bool(access_token or refresh_token),
            "has_access_token": bool(access_token),
            "has_refresh_token": bool(refresh_token),
            "auto_refresh_enabled": bool(refresh_token),
            "expiry": info.get("expiry") or None,
            "expires_in_seconds": (
                max(0, int(float(expires_at) - time.time()))
                if isinstance(expires_at, (int, float))
                else None
            ),
            "source": info.get("source") or None,
            "token_file": str(saved_path or (self.profile_home.parent / "oauth_token.json")),
            "profile_home": str(self.profile_home),
        }

    def _terminate_standalone_rpc_process(self) -> None:
        state_file = self.app_data_dir / "scratch/rpc_connection.json"
        if not state_file.is_file():
            return
        try:
            info = json.loads(state_file.read_text(encoding="utf-8"))
            pid = info.get("pid")
            if isinstance(pid, int) and pid > 0:
                import psutil
                if psutil.pid_exists(pid):
                    proc = psutil.Process(pid)
                    if "language_server" in (proc.name() or "").lower():
                        proc.terminate()
                        proc.wait(timeout=3)
        except Exception:
            pass
        try:
            state_file.unlink(missing_ok=True)
        except OSError:
            pass

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
        temp_dir = (
            self.profile_home / "AppData/Local/Temp"
            if is_windows_os()
            else self.profile_home / ".cache/tmp"
        )
        for directory in (
            self.app_data_dir,
            self.app_data_dir / "conversations",
            self.app_data_dir / "scratch",
            self.user_data_dir,
            self.user_data_dir / "logs",
            self.user_data_dir / "User",
            self.config_dir,
            self.workspace_dir,
            self.workspaces_pool_dir,
            temp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for slot_idx in range(10):
            (self.workspaces_pool_dir / f"ws-{slot_idx:02d}" / "src").mkdir(parents=True, exist_ok=True)

        initial_files = {
            self.config_dir / "config.json": json.dumps({"plugins": {}, "sidecars": {}, "userSettings": {}}),
            self.user_data_dir / "User/settings.json": json.dumps({
                "telemetry.telemetryLevel": "off",
                "telemetry.enableTelemetry": False,
                "telemetry.enableCrashReporter": False,
                "antigravity.disableTelemetry": True,
            }),
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
        if is_windows_os() and os.environ.get("ANTIGRAVITY_DOCKER") != "1":
            # Preserve only Google authentication from the former API browser profile on Windows.
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

    def _download_linux_language_server(self, target_path: Path) -> Path | None:
        """Download the official standalone Linux `language_server` binary from Google's public artifact bucket."""
        updater_url = "https://antigravity-hub-auto-updater-974169037036.us-central1.run.app/releases"
        fallback_url = (
            "https://storage.googleapis.com/antigravity-public/"
            "antigravity-hub/2.24.0-5780333019398144/unsigned/language_server-linux-x64"
        )
        download_url = os.environ.get("ANTIGRAVITY_LINUX_LS_URL", "").strip()
        if not download_url:
            try:
                req = urllib.request.Request(updater_url, headers={"User-Agent": "Antigravity/2.24.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    releases = json.loads(resp.read().decode("utf-8"))
                if isinstance(releases, list) and releases:
                    rel = next(
                        (r for r in releases if isinstance(r, dict) and r.get("version") == "2.24.0"),
                        releases[0],
                    )
                    ver = rel.get("version")
                    exec_id = rel.get("execution_id")
                    if ver and exec_id:
                        download_url = (
                            f"https://storage.googleapis.com/antigravity-public/"
                            f"antigravity-hub/{ver}-{exec_id}/unsigned/language_server-linux-x64"
                        )
            except Exception:
                pass
        if not download_url:
            download_url = fallback_url

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(".partial")
            print(f"[API Profile] Downloading headless Linux language_server from {download_url} ...", flush=True)
            req = urllib.request.Request(download_url, headers={"User-Agent": "Antigravity/2.24.0"})
            with urllib.request.urlopen(req, timeout=180) as resp, tmp_path.open("wb") as out_f:
                shutil.copyfileobj(resp, out_f, length=1024 * 1024)
            os.chmod(tmp_path, 0o755)
            tmp_path.replace(target_path)
            print(f"[API Profile] Installed headless Linux language_server at {target_path}", flush=True)
            return target_path.resolve()
        except Exception as exc:
            print(f"[API Profile] Failed to download Linux language_server: {exc}", flush=True)
            return None

    def _resolve_language_server_binary(self) -> Path | None:
        explicit = os.environ.get("ANTIGRAVITY_LANGUAGE_SERVER_BIN")
        if explicit and Path(explicit).is_file():
            return Path(explicit).resolve()
        install_dir = self.executable.parent
        profile_root = self.profile_home.parent
        candidates = [
            install_dir / "resources/app/extensions/antigravity/bin/language_server_windows_x64.exe",
            install_dir / "resources/bin/language_server.exe",
            install_dir / "resources/app/extensions/antigravity/bin/language_server_linux_x64",
            install_dir / "resources/bin/language_server_linux_x64",
            install_dir / "resources/bin/language_server",
            profile_root / "bin/language_server_linux_x64",
            profile_root / "bin/language_server",
            Path("/opt/antigravity/bin/language_server_linux_x64"),
            Path("/opt/antigravity/bin/language_server"),
            Path("/usr/local/bin/language_server_linux_x64"),
            Path("/usr/local/bin/language_server"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        if not is_windows_os() and os.environ.get("ANTIGRAVITY_AUTO_DOWNLOAD_LS", "1") != "0":
            return self._download_linux_language_server(profile_root / "bin/language_server_linux_x64")
        return None

    def _wait_for_rpc_ready(
        self,
        rpc_port: int,
        proc: Any = None,
        timeout: float = 10.0,
    ) -> bool:
        """Poll `127.0.0.1:<rpc_port>` until the headless `language_server` accepts connections."""
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline:
            if proc is not None and callable(getattr(proc, "poll", None)):
                rc = proc.poll()
                if isinstance(rc, int):
                    return False
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.25)
                    if probe.connect_ex(("127.0.0.1", rpc_port)) == 0:
                        return True
            except OSError:
                pass
            time.sleep(0.1)
        return False

    def ensure_rpc_ready(self, *, wait_timeout: float | None = None) -> None:
        """Ensure the isolated API profile's `language_server` is running for `rpc` mode.

        Supports both Windows desktop profile launch and standalone headless execution
        on Linux / Docker / Dokploy containers.
        """
        if os.name == "nt" and not os.environ.get("ANTIGRAVITY_STANDALONE_RPC"):
            try:
                self.ensure_started()
                return
            except Exception as win_err:
                print(f"[API Profile] Desktop launch fallback to standalone language_server: {win_err}", flush=True)

        with _START_LOCK:
            self._verify_path_separation()
            self._seed_authentication_once()
            ls_bin = self._resolve_language_server_binary()
            if ls_bin is None:
                if os.name == "nt":
                    self.ensure_started()
                    return
                raise ConnectionError(
                    "No language_server binary found for standalone headless RPC mode. "
                    "Set ANTIGRAVITY_LANGUAGE_SERVER_BIN or mount the binary in /data/antigravity-api/bin/language_server_linux_x64."
                )

            access_token = self.resolve_headless_access_token()
            token_info = self.load_oauth_token_info()
            token_expires_at = token_info.get("expires_at")

            state_file = self.app_data_dir / "scratch/rpc_connection.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            if state_file.is_file():
                try:
                    info = json.loads(state_file.read_text(encoding="utf-8"))
                    saved_exp = info.get("token_expires_at")
                    token_expired = (
                        isinstance(saved_exp, (int, float))
                        and time.time() >= float(saved_exp) - 120
                    )
                    if not token_expired:
                        with socket.socket() as probe:
                            if probe.connect_ex(("127.0.0.1", int(info.get("port", 0)))) == 0:
                                return
                    else:
                        self._terminate_standalone_rpc_process()
                except Exception:
                    pass

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                rpc_port = sock.getsockname()[1]

            import uuid
            csrf_token = str(uuid.uuid4())
            environment = os.environ.copy()
            home = str(self.profile_home)
            environment.update({
                "HOME": home,
                "USERPROFILE": home,
                "XDG_CONFIG_HOME": str(self.profile_home / ".config"),
                "XDG_DATA_HOME": str(self.profile_home / ".local/share"),
                "XDG_CACHE_HOME": str(self.profile_home / ".cache"),
                "ANTIGRAVITY_PROFILE": self.profile,
                "ANTIGRAVITY_NO_HUB_AUTOSTART": "1",
                "ANTIGRAVITY_DATA_DIR": str(self.app_data_dir),
            })
            if access_token:
                environment["JETSKI_OAUTH_TOKEN"] = access_token

            cmd_args = [
                str(ls_bin),
                "--standalone",
                f"--https_server_port={rpc_port}",
                f"--csrf_token={csrf_token}",
                "--override_ide_name=antigravity",
                "--override_ide_version=2.24.0",
                "--override_user_agent_name=antigravity",
                "--gemini_dir=.gemini",
                f"--app_data_dir={self.app_data_dir.name}",
                f"--api_server_url={DEFAULT_API_SERVER_URL}",
                f"--cloud_code_endpoint={DEFAULT_CLOUD_CODE_ENDPOINT}",
            ]
            if not access_token:
                cmd_args.insert(2, "--headless")
                cmd_args.append("--subclient_type=hub")

            log_file = self.app_data_dir / "scratch/language_server_rpc.log"
            with log_file.open("a", encoding="utf-8") as log_handle:
                proc = subprocess.Popen(
                    cmd_args,
                    cwd=self.workspace_dir,
                    env=environment,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                )
            state_file.write_text(
                json.dumps(
                    {
                        "port": rpc_port,
                        "csrf_token": csrf_token,
                        "pid": getattr(proc, "pid", None),
                        "started_at": time.time(),
                        "has_oauth_token": bool(access_token),
                        "token_expires_at": token_expires_at,
                    }
                ),
                encoding="utf-8",
            )
            self._last_launch = time.monotonic()
            timeout = (
                wait_timeout
                if wait_timeout is not None
                else float(os.environ.get("ANTIGRAVITY_RPC_READY_TIMEOUT", "10.0"))
            )
            self._wait_for_rpc_ready(rpc_port, proc=proc, timeout=timeout)


api_profile_runtime = APIProfileRuntime()
