"""Export the authenticated Windows Anti-Gravity session into `./docker-data` for Headless Linux/Docker.

Copies only the isolated authentication state (`state.vscdb`, Google auth cookies,
and `Local State` encryption metadata) into the target Docker volume structure
(`/data/antigravity-api/home/...`) so the Linux container can immediately run
Direct ConnectRPC (`language_server_linux_x64`) without an interactive browser login.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _candidate_user_data_dirs(explicit_source: Optional[Path] = None) -> List[Path]:
    if explicit_source is not None:
        return [Path(explicit_source).expanduser().resolve()]
    candidates: List[Path] = []
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
    app_data = Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming"))
    api_profile_home = local_app_data / "AntigravityApiProfile/home"
    candidates.extend(
        [
            api_profile_home / "AppData/Roaming/Antigravity-api",
            api_profile_home / ".config/Antigravity-api",
            app_data / "Antigravity-api",
            app_data / "Antigravity",
            Path.home() / ".config/Antigravity-api",
            Path.home() / ".config/Antigravity",
        ]
    )
    return candidates


def _backup_sqlite_readonly(source_db: Path, target_db: Path, filter_sql: Optional[str] = None) -> bool:
    from contextlib import closing

    if not source_db.is_file():
        return False
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()
    try:
        uri = source_db.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as src_conn:
            with closing(sqlite3.connect(str(target_db))) as dst_conn:
                src_conn.backup(dst_conn)
                if filter_sql:
                    dst_conn.execute(filter_sql)
                    dst_conn.commit()
                    dst_conn.execute("VACUUM")
        return True
    except (sqlite3.Error, OSError):
        try:
            shutil.copy2(source_db, target_db)
            return True
        except OSError:
            return False


def export_linux_auth_seed(
    output_dir: Path | str = "./docker-data",
    *,
    source_user_data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """Populate `output_dir` (`/data/antigravity-api` mount) with auth seed & workspace skeleton."""
    out_root = Path(output_dir).expanduser().resolve()
    home_dir = out_root / "home"
    config_dir = home_dir / ".gemini/config"
    app_data_dir = home_dir / ".gemini/antigravity-api"
    linux_user_data_dir = home_dir / ".config/Antigravity-api"
    workspaces_dir = home_dir / "workspaces"
    workspace_single = home_dir / "workspace"
    audit_logs_dir = out_root / "audit_logs"
    bin_dir = out_root / "bin"

    for directory in (
        config_dir,
        app_data_dir / "scratch",
        app_data_dir / "conversations",
        linux_user_data_dir / "User/globalStorage",
        linux_user_data_dir / "logs",
        workspaces_dir,
        workspace_single,
        audit_logs_dir,
        bin_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for slot_idx in range(10):
        (workspaces_dir / f"ws-{slot_idx:02d}" / "src").mkdir(parents=True, exist_ok=True)

    initial_files = {
        config_dir / "config.json": json.dumps({"plugins": {}, "sidecars": {}, "userSettings": {}}),
        linux_user_data_dir / "User/settings.json": json.dumps(
            {
                "telemetry.telemetryLevel": "off",
                "telemetry.enableTelemetry": False,
                "telemetry.enableCrashReporter": False,
                "antigravity.disableTelemetry": True,
            }
        ),
        config_dir / "AGENTS.md": (
            "# API profile rules\n\n"
            "Isolated headless Linux API profile environment.\n"
        ),
        config_dir / "USER.md": "# API profile preferences\n",
        config_dir / "MEMORY.md": "# API profile memory\n",
    }
    for file_path, content in initial_files.items():
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")

    copied: List[str] = []
    warnings: List[str] = []
    selected_source: Optional[Path] = None

    explicit = Path(source_user_data_dir) if source_user_data_dir is not None else None
    for candidate in _candidate_user_data_dirs(explicit):
        if candidate.is_dir() and (
            (candidate / "User/globalStorage/state.vscdb").is_file()
            or (candidate / "Network/Cookies").is_file()
            or (candidate / "Local State").is_file()
        ):
            selected_source = candidate
            break

    if selected_source is not None:
        state_vscdb = selected_source / "User/globalStorage/state.vscdb"
        if state_vscdb.is_file():
            for dest in (
                linux_user_data_dir / "User/globalStorage/state.vscdb",
                app_data_dir / "User/globalStorage/state.vscdb",
            ):
                if _backup_sqlite_readonly(state_vscdb, dest):
                    if "state.vscdb" not in copied:
                        copied.append("state.vscdb")

        local_state = selected_source / "Local State"
        if local_state.is_file():
            try:
                raw_state = json.loads(local_state.read_text(encoding="utf-8"))
                (linux_user_data_dir / "Local State").write_text(
                    json.dumps({"os_crypt": raw_state.get("os_crypt", {})}),
                    encoding="utf-8",
                )
                copied.append("local_state")
            except (OSError, ValueError):
                warnings.append("local_state_unreadable")

        cookies_src = selected_source / "Network/Cookies"
        cookies_dst = linux_user_data_dir / "Network/Cookies"
        cookie_filter = (
            "DELETE FROM cookies WHERE NOT ("
            "host_key = 'google.com' OR host_key LIKE '%.google.com' "
            "OR host_key = 'googleapis.com' OR host_key LIKE '%.googleapis.com' "
            "OR host_key = 'antigravity.google' OR host_key LIKE '%.antigravity.google')"
        )
        if _backup_sqlite_readonly(cookies_src, cookies_dst, filter_sql=cookie_filter):
            copied.append("authentication_cookies")
    else:
        warnings.append("no_authenticated_source_profile_found")

    # Export headless Google OAuth token (refresh_token + access_token) from Windows Credential Manager
    has_oauth_token = False
    try:
        import sys
        hub_root = Path(__file__).resolve().parents[1]
        if str(hub_root) not in sys.path:
            sys.path.insert(0, str(hub_root))
        from src.api_profile import read_windows_keyring_token

        keyring_token = read_windows_keyring_token()
        if keyring_token and (keyring_token.get("refresh_token") or keyring_token.get("access_token")):
            token_payload = json.dumps(
                {
                    **keyring_token,
                    "token": {
                        "access_token": keyring_token.get("access_token", ""),
                        "token_type": keyring_token.get("token_type", "Bearer"),
                        "refresh_token": keyring_token.get("refresh_token", ""),
                        "expiry": keyring_token.get("expiry", ""),
                    },
                    "exported_at": time.time(),
                },
                indent=2,
            )
            for token_dest in (out_root / "oauth_token.json", app_data_dir / "oauth_token.json"):
                token_dest.write_text(token_payload, encoding="utf-8")
            copied.append("oauth_token_json")
            has_oauth_token = True
            if "no_authenticated_source_profile_found" in warnings:
                warnings.remove("no_authenticated_source_profile_found")
    except Exception as exc:
        warnings.append(f"keyring_token_export_skipped:{exc}")

    seed_manifest = {
        "profile": "api",
        "profile_contract_version": 2,
        "runtime_mode": "headless_linux",
        "exported_at": time.time(),
        "source_user_data_dir": str(selected_source) if selected_source else None,
        "output_dir": str(out_root),
        "oauth_token_file": str(out_root / "oauth_token.json") if has_oauth_token else None,
        "copied": copied,
        "warnings": warnings,
    }
    (app_data_dir / "api_profile_seed.json").write_text(
        json.dumps(seed_manifest, indent=2),
        encoding="utf-8",
    )
    return seed_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Windows Anti-Gravity authentication seed into ./docker-data for Linux/Docker."
    )
    parser.add_argument(
        "--output",
        default="./docker-data",
        help="Target directory mounted as /data/antigravity-api in Docker (default: ./docker-data)",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional explicit Windows User Data directory to export from",
    )
    args = parser.parse_args()
    manifest = export_linux_auth_seed(args.output, source_user_data_dir=args.source)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

