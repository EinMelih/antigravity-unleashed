"""Safe project-level Anti-Gravity settings used by Hub-managed workers."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


HUB_AGENT_SETTINGS: Dict[str, Any] = {
    "fileAccessPolicy": "AGENT_SETTING_POLICY_ALLOW",
    "sandboxMode": False,
    "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER",
    "artifactReviewMode": "ARTIFACT_REVIEW_MODE_TURBO",
}

_CONFIG_WRITE_LOCK = threading.Lock()
_WINDOWS_DRIVE_PATH = re.compile(r"^/[a-zA-Z]:")


class AntigravityProjectSettingsError(RuntimeError):
    """Raised when one exact Anti-Gravity project cannot be configured safely."""


def default_project_config_root() -> Path:
    """Return Anti-Gravity's canonical project-config directory."""
    return Path.home() / ".gemini" / "config" / "projects"


def _canonical_path(value: str | Path) -> str:
    return os.path.normcase(
        os.path.normpath(os.path.abspath(os.fspath(value)))
    ).rstrip("\\/")


def _workspace_from_folder_uri(uri: Any) -> str:
    value = str(uri or "").strip()
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme and parsed.scheme.lower() != "file":
        return ""
    if parsed.scheme.lower() == "file":
        value = urllib.parse.unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            value = f"//{parsed.netloc}{value}"
        if _WINDOWS_DRIVE_PATH.match(value):
            value = value[1:]
    return value.replace("/", os.sep)


def _configured_workspaces(payload: Dict[str, Any]) -> Iterable[str]:
    resources = (
        payload.get("projectResources", {}).get("resources", [])
        if isinstance(payload.get("projectResources"), dict)
        else []
    )
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        git_folder = resource.get("gitFolder")
        if not isinstance(git_folder, dict):
            continue
        workspace = _workspace_from_folder_uri(git_folder.get("folderUri"))
        if workspace:
            yield workspace


def _read_config(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AntigravityProjectSettingsError(
            f"Anti-Gravity project config could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AntigravityProjectSettingsError(
            f"Anti-Gravity project config is not a JSON object: {path}"
        )
    return payload


def _matches_workspace(payload: Dict[str, Any], workspace_path: str) -> bool:
    expected = _canonical_path(workspace_path)
    return any(
        _canonical_path(candidate) == expected
        for candidate in _configured_workspaces(payload)
    )


def _is_dedicated_workspace_config(
    payload: Dict[str, Any],
    workspace_path: str,
) -> bool:
    """Return whether this config represents only the requested workspace.

    Anti-Gravity can temporarily retain a newly imported folder as an extra
    resource on the previously selected project while also creating the proper
    workspace-only project.  That overlap is not ambiguous: the config whose
    own name and sole resource both identify the workspace is canonical.
    """
    expected = _canonical_path(workspace_path)
    configured = [
        _canonical_path(candidate)
        for candidate in _configured_workspaces(payload)
    ]
    configured_name = str(
        payload.get("name") or payload.get("projectName") or ""
    ).strip()
    if not configured_name:
        return False
    return (
        _canonical_path(configured_name) == expected
        and configured == [expected]
    )


def _resolve_project_config(
    *,
    workspace_path: str = "",
    project_uuid: str = "",
    config_root: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    root = Path(config_root or default_project_config_root())
    expected_uuid = str(project_uuid or "").strip()
    expected_workspace = str(workspace_path or "").strip()
    if not expected_uuid and not expected_workspace:
        raise AntigravityProjectSettingsError(
            "A project UUID or workspace path is required."
        )

    if expected_uuid:
        path = root / f"{expected_uuid}.json"
        if not path.is_file():
            raise AntigravityProjectSettingsError(
                f"Anti-Gravity project config does not exist: {path}"
            )
        payload = _read_config(path)
        actual_uuid = str(payload.get("id") or "").strip()
        if actual_uuid.casefold() != expected_uuid.casefold():
            raise AntigravityProjectSettingsError(
                "Anti-Gravity project UUID does not match its config filename."
            )
        if expected_workspace and not _matches_workspace(
            payload,
            expected_workspace,
        ):
            raise AntigravityProjectSettingsError(
                "Anti-Gravity project config does not belong to the expected "
                f"workspace: {expected_workspace}"
            )
        return path, payload

    if not root.is_dir():
        raise AntigravityProjectSettingsError(
            f"Anti-Gravity project-config directory does not exist: {root}"
        )
    matches = []
    for path in root.glob("*.json"):
        try:
            payload = _read_config(path)
        except AntigravityProjectSettingsError:
            continue
        if _matches_workspace(payload, expected_workspace):
            matches.append((path, payload))
    if len(matches) == 1:
        return matches[0]

    dedicated_matches = [
        match
        for match in matches
        if _is_dedicated_workspace_config(match[1], expected_workspace)
    ]
    if len(dedicated_matches) == 1:
        return dedicated_matches[0]

    if len(matches) != 1:
        raise AntigravityProjectSettingsError(
            "Expected exactly one Anti-Gravity project config for workspace "
            f"{expected_workspace!r}, found {len(matches)}."
        )
    return matches[0]


def is_antigravity_project_configured(
    *,
    workspace_path: str,
    project_uuid: str,
    config_root: Optional[Path] = None,
) -> bool:
    """Return whether one native project config owns the exact workspace."""
    expected_uuid = str(project_uuid or "").strip()
    if not str(workspace_path or "").strip() or not expected_uuid:
        return False
    try:
        path, payload = _resolve_project_config(
            workspace_path=workspace_path,
            config_root=config_root,
        )
    except AntigravityProjectSettingsError:
        return False
    actual_uuid = str(payload.get("id") or "").strip()
    return (
        actual_uuid.casefold() == expected_uuid.casefold()
        and path.stem.casefold() == expected_uuid.casefold()
    )


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise AntigravityProjectSettingsError(
            f"Anti-Gravity project settings could not be written: {path}: {exc}"
        ) from exc


def enforce_hub_project_settings(
    *,
    workspace_path: str = "",
    project_uuid: str = "",
    config_root: Optional[Path] = None,
    wait_timeout: float = 10.0,
    poll_interval: float = 0.1,
) -> Dict[str, Any]:
    """Persist Turbo + Always Proceed for one exactly resolved project.

    Newly imported projects may appear on disk just after their sidebar row.
    Resolution therefore retries briefly, but ambiguity and path mismatches are
    always fatal so another project's policy can never be changed accidentally.
    """
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    last_error: Optional[AntigravityProjectSettingsError] = None
    while True:
        try:
            path, _ = _resolve_project_config(
                workspace_path=workspace_path,
                project_uuid=project_uuid,
                config_root=config_root,
            )
            break
        except AntigravityProjectSettingsError as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                raise last_error
            time.sleep(max(0.01, float(poll_interval)))

    with _CONFIG_WRITE_LOCK:
        path, payload = _resolve_project_config(
            workspace_path=workspace_path,
            project_uuid=project_uuid,
            config_root=config_root,
        )
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            settings = {}
            payload["settings"] = settings
        changed = any(
            settings.get(key) != value
            for key, value in HUB_AGENT_SETTINGS.items()
        )
        if changed:
            settings.update(HUB_AGENT_SETTINGS)
            payload["updatedAt"] = datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            _atomic_write_json(path, payload)

        verified = _read_config(path)
        verified_settings = verified.get("settings")
        if not isinstance(verified_settings, dict) or any(
            verified_settings.get(key) != value
            for key, value in HUB_AGENT_SETTINGS.items()
        ):
            raise AntigravityProjectSettingsError(
                f"Anti-Gravity did not persist the required project policy: {path}"
            )

    return {
        "project_uuid": str(verified.get("id") or ""),
        "config_path": str(path),
        "changed": changed,
        "security_preset": "turbo",
        "artifact_review_policy": "always_proceed",
    }
