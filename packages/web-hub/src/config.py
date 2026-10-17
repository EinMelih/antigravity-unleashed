import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Base directory setup
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
CONFIG_ENV_VAR = "ANTIGRAVITY_HUB_CONFIG"
API_HOST_ENV_VAR = "ANTIGRAVITY_API_HOST"
DEFAULT_CONFIG_PATH = (
    Path.home() / ".gemini" / "config" / "antigravity-hub" / "config.json"
)
DEFAULT_PROJECTS_BASE_DIR = str(Path.home() / "Projects")


def resolve_config_path() -> Path:
    """Return the external runtime configuration path.

    Secrets must not live inside the Git worktree. Deployments and tests can
    provide an explicit path through ``ANTIGRAVITY_HUB_CONFIG``.
    """
    configured_path = os.environ.get(CONFIG_ENV_VAR)
    path = Path(configured_path) if configured_path else DEFAULT_CONFIG_PATH
    return path.expanduser().resolve()


CONFIG_PATH = resolve_config_path()

# Global default config values
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8001,
    "auth_token": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    "api_keys": {},
    "debug_mode": False,
    "max_message_length": 100000,
    "rate_limit": {
        "enabled": False,
        "max_requests_per_minute": 10,
        "whitelist_ips": ["127.0.0.1", "::1"]
    },
    "watchdog": {
        "host": "127.0.0.1",
        "port": 8010,
        "check_interval_seconds": 10,
        "retention_days": 30,
        "timeout_ms": 3000,
        "alert_cooldown_seconds": 300,
        "services": [
            {"name": "api_bridge", "url": "http://127.0.0.1:8001/health"},
            {"name": "proxy", "url": "http://127.0.0.1:8000/"},
            {"name": "session_manager", "url": "http://127.0.0.1:8002/health"},
            {"name": "auto_healer", "url": "http://127.0.0.1:8007/health"}
        ]
    },
    "session_manager": {
        "port": 8002,
        "sessions": [
            {"name": "main", "url": "http://127.0.0.1:8001"}
        ],
        "health_check_interval_seconds": 30,
        "session_timeout_seconds": 120
    },
    "auto_healer": {
        "port": 8007,
        "check_interval_seconds": 15,
        "max_healing_cycles": 3,
        "api_bridge_url": "http://127.0.0.1:8001"
    },
    "github_token": "",
    "github_owner": "",
    "github_webhook_secret": "",
    "projects_base_dir": DEFAULT_PROJECTS_BASE_DIR,
    "default_repo_visibility": "private"
}


def validate_positive_int(value: Any, name: str, default: int) -> int:
    """Checks if a value is a positive integer, otherwise returns the default."""
    try:
        val = int(value)
        if val <= 0:
            print(f"[CONFIG] [WARN] {name}: Value {val} is not positive - using default {default}", flush=True)
            return default
        return val
    except (TypeError, ValueError):
        print(f"[CONFIG] [WARN] {name}: Invalid value '{value}' - using default {default}", flush=True)
        return default


def validate_url(url: Any, name: str) -> bool:
    """Validates if a URL is non-empty and starts with http:// or https://."""
    if not url or not isinstance(url, str):
        print(f"[CONFIG] [WARN] {name}: URL is empty or invalid", flush=True)
        return False
    if not url.startswith(('http://', 'https://')):
        print(f"[CONFIG] [WARN] {name}: Invalid URL '{url}' - must start with http:// or https://", flush=True)
        return False
    return True


class ConfigurationManager:
    """Unified configuration manager loading settings from config.json."""

    def __init__(self) -> None:
        self.config_dict: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> None:
        if not CONFIG_PATH.exists():
            print(f"[CONFIG] {CONFIG_PATH} not found - using defaults", flush=True)
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                self._merge_configs(self.config_dict, loaded)
        except json.JSONDecodeError as e:
            print(f"[CONFIG] [ERROR] JSON error in {CONFIG_PATH}: {e} - using defaults", flush=True)
        except Exception as e:
            print(f"[CONFIG] [ERROR] Error loading configuration: {e} - using defaults", flush=True)

    def _merge_configs(self, target: dict, source: dict) -> None:
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                self._merge_configs(target[k], v)
            else:
                target[k] = v

    @property
    def api_bridge_host(self) -> str:
        host = str(
            os.environ.get(
                API_HOST_ENV_VAR,
                self.config_dict.get("host", DEFAULT_CONFIG["host"]),
            )
        ).strip()
        return host or str(DEFAULT_CONFIG["host"])

    @property
    def api_bridge_port(self) -> int:
        return validate_positive_int(self.config_dict.get("port"), "port", 8001)

    @property
    def auth_token(self) -> str:
        return str(self.config_dict.get("auth_token", DEFAULT_CONFIG["auth_token"]))

    @property
    def telegram_token(self) -> Optional[str]:
        val = self.config_dict.get("telegram_token")
        return str(val) if val else None

    @property
    def telegram_chat_id(self) -> Optional[str]:
        val = self.config_dict.get("telegram_chat_id")
        return str(val) if val else None

    @property
    def api_keys(self) -> Dict[str, str]:
        keys = self.config_dict.get("api_keys")
        return dict(keys) if isinstance(keys, dict) else {}

    @property
    def debug_mode(self) -> bool:
        return bool(self.config_dict.get("debug_mode", False))

    @property
    def max_message_length(self) -> int:
        return validate_positive_int(self.config_dict.get("max_message_length"), "max_message_length", 100000)

    @property
    def rate_limit(self) -> Dict[str, Any]:
        rl = self.config_dict.get("rate_limit", {})
        return {
            "enabled": bool(rl.get("enabled", False)),
            "max_requests_per_minute": validate_positive_int(rl.get("max_requests_per_minute"), "rate_limit.max_requests_per_minute", 10),
            "whitelist_ips": list(rl.get("whitelist_ips", ["127.0.0.1", "::1"]))
        }

    @property
    def watchdog(self) -> Dict[str, Any]:
        wd = self.config_dict.get("watchdog", {})
        services = []
        for s in wd.get("services", []):
            name = s.get("name", "")
            url = s.get("url", "")
            if name and validate_url(url, f"watchdog service '{name}'"):
                services.append({"name": name, "url": url})
        return {
            "host": str(wd.get("host", DEFAULT_CONFIG["watchdog"]["host"])).strip()
            or DEFAULT_CONFIG["watchdog"]["host"],
            "port": validate_positive_int(wd.get("port"), "watchdog.port", 8010),
            "check_interval_seconds": validate_positive_int(wd.get("check_interval_seconds"), "watchdog.check_interval_seconds", 10),
            "retention_days": validate_positive_int(wd.get("retention_days"), "watchdog.retention_days", 30),
            "timeout_ms": validate_positive_int(wd.get("timeout_ms"), "watchdog.timeout_ms", 3000),
            "alert_cooldown_seconds": validate_positive_int(wd.get("alert_cooldown_seconds"), "watchdog.alert_cooldown_seconds", 300),
            "services": services or DEFAULT_CONFIG["watchdog"]["services"]
        }

    @property
    def session_manager(self) -> Dict[str, Any]:
        sm = self.config_dict.get("session_manager", {})
        sessions = []
        for s in sm.get("sessions", []):
            name = s.get("name", "")
            url = s.get("url", "")
            if name and validate_url(url, f"session '{name}'"):
                sessions.append({"name": name, "url": url})
        return {
            "port": validate_positive_int(sm.get("port"), "session_manager.port", 8002),
            "sessions": sessions,
            "health_check_interval_seconds": validate_positive_int(sm.get("health_check_interval_seconds"), "session_manager.health_check_interval_seconds", 30),
            "session_timeout_seconds": validate_positive_int(sm.get("session_timeout_seconds"), "session_manager.session_timeout_seconds", 120)
        }

    @property
    def auto_healer(self) -> Dict[str, Any]:
        ah = self.config_dict.get("auto_healer", {})
        api_bridge_url = ah.get("api_bridge_url", "http://127.0.0.1:8001")
        if not validate_url(api_bridge_url, "auto_healer.api_bridge_url"):
            api_bridge_url = "http://127.0.0.1:8001"
        return {
            "port": validate_positive_int(ah.get("port"), "auto_healer.port", 8007),
            "check_interval_seconds": validate_positive_int(ah.get("check_interval_seconds"), "auto_healer.check_interval_seconds", 15),
            "max_healing_cycles": validate_positive_int(ah.get("max_healing_cycles"), "auto_healer.max_healing_cycles", 3),
            "api_bridge_url": api_bridge_url
        }

    # --- GitHub Integration Properties ---

    @property
    def github_token(self) -> Optional[str]:
        val = self.config_dict.get("github_token")
        return str(val) if val else None

    @property
    def github_owner(self) -> str:
        return str(self.config_dict.get("github_owner", ""))

    @property
    def github_webhook_secret(self) -> Optional[str]:
        val = self.config_dict.get("github_webhook_secret")
        return str(val) if val else None

    @property
    def projects_base_dir(self) -> str:
        configured = str(self.config_dict.get("projects_base_dir") or "").strip()
        return configured or DEFAULT_PROJECTS_BASE_DIR

    @property
    def default_repo_visibility(self) -> str:
        val = self.config_dict.get("default_repo_visibility", "private")
        return val if val in ("private", "public") else "private"

    @property
    def github_configured(self) -> bool:
        return bool(self.github_token and self.github_owner)


# Singleton config instance
config = ConfigurationManager()
