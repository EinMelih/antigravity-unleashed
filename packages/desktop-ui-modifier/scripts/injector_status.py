"""Read-only version preflight and user-visible injector status/notifications."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


STATUS_NAME = "repack_status.json"
NOTIFICATION_NAME = "repack_notification.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_archive_version(archive_path: Path) -> str:
    """Read bundled package.json directly, using the ASAR pickle offsets."""
    try:
        with Path(archive_path).open("rb") as handle:
            prefix = handle.read(8)
            if len(prefix) != 8:
                raise ValueError("truncated prefix")
            payload_size, header_size = struct.unpack("<II", prefix)
            if payload_size != 4 or not 8 <= header_size <= 16 * 1024 * 1024:
                raise ValueError("invalid header size")
            header_buffer = handle.read(header_size)
            if len(header_buffer) != header_size:
                raise ValueError("truncated header")
            string_size = struct.unpack_from("<I", header_buffer, 4)[0]
            if string_size > header_size - 8:
                raise ValueError("invalid header string size")
            header = json.loads(header_buffer[8:8 + string_size])
            package = header["files"]["package.json"]
            size = package["size"]
            offset = int(package["offset"])
            if package.get("unpacked") or package.get("link") or not isinstance(size, int) or not 0 < size <= 1024 * 1024 or offset < 0:
                raise ValueError("invalid bundled package.json entry")
            handle.seek(8 + header_size + offset)
            content = handle.read(size)
            if len(content) != size:
                raise ValueError("truncated package.json")
            version = str(json.loads(content)["version"]).strip().lstrip("v")
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
                raise ValueError("invalid package version")
            return version
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        raise RuntimeError(f"ASAR-Version konnte nicht gelesen werden: {error}") from error


def version_info(archive_path: Path, skill_root: Path) -> dict[str, str]:
    supported = (Path(skill_root) / "SUPPORTED_UPSTREAM_VERSION").read_text(encoding="utf-8").strip().lstrip("v")
    manifest = json.loads((Path(skill_root) / "UPSTREAM_COMPATIBILITY.json").read_text(encoding="utf-8"))
    if not supported or manifest.get("version") != supported:
        raise RuntimeError("Injector-Versionsdatei und Kompatibilitaetsmanifest stimmen nicht ueberein.")
    return {"installed_version": read_archive_version(archive_path), "supported_version": supported}


def unsupported_message(versions: dict[str, str]) -> str:
    return (
        f"Anti-Gravity {versions['installed_version']} wird von diesem Injector noch nicht unterstuetzt "
        f"(freigegeben: {versions['supported_version']}). Die App bleibt unveraendert. "
        "Der Injector muss an die neue Version angepasst und geprueft werden."
    )


def atomic_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".injector-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_status(scratch_dir: Path) -> dict:
    try:
        data = json.loads((Path(scratch_dir) / STATUS_NAME).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("status is not an object")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as error:
        return {"state": "error", "phase": "status", "kind": "status_read_error", "message": f"Injector-Status ist nicht lesbar: {error}"}


def write_status(scratch_dir: Path, state: str, phase: str, **details) -> dict:
    previous = read_status(scratch_dir)
    versions = {key: previous[key] for key in ("installed_version", "supported_version") if key in previous} if previous.get("state") == "running" and phase != "preflight" else {}
    status = {**versions, "state": state, "phase": phase, "updated_at": time.time(), **details}
    atomic_json(Path(scratch_dir) / STATUS_NAME, status)
    try:
        # Drives the self-healing progress window; a no-op unless a run is active.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import selfheal

        selfheal.mirror_repack_status(state, phase, str(details.get("message", "")), Path(scratch_dir))
    except Exception:
        pass
    return status


def clear_notification(scratch_dir: Path) -> None:
    (Path(scratch_dir) / NOTIFICATION_NAME).unlink(missing_ok=True)


def launch_popup(scratch_dir: Path, status: dict) -> None:
    scratch = Path(scratch_dir)
    payload_key = hashlib.sha256(json.dumps(status, sort_keys=True).encode("utf-8")).hexdigest()
    payload_path = scratch / f"repack_popup_{payload_key}.json"
    atomic_json(payload_path, status)
    windowless = Path(sys.executable).with_name("pythonw.exe")
    interpreter = str(windowless if windowless.is_file() else Path(sys.executable))
    try:
        subprocess.Popen(
            [interpreter, str(Path(__file__).with_name("notification_popup.py")), str(payload_path)],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception:
        payload_path.unlink(missing_ok=True)
        raise


def notify_completion(scratch_dir: Path, started_at: float = 0) -> None:
    status = read_status(scratch_dir)
    if status.get("state") != "success" or status.get("updated_at", 0) < started_at:
        raise RuntimeError("Ein erfolgreicher Injector-Lauf wurde nicht bestaetigt.")
    launch_popup(scratch_dir, status)


def notify_failure(scratch_dir: Path) -> bool:
    """Launch a separate popup process once per failure; never wait for its UI."""
    scratch = Path(scratch_dir)
    status = read_status(scratch)
    if status.get("state") not in {"error", "blocked"}:
        return False
    key = hashlib.sha256(json.dumps({name: status.get(name) for name in ("kind", "message", "installed_version", "supported_version")}, sort_keys=True).encode("utf-8")).hexdigest()
    marker = scratch / NOTIFICATION_NAME
    try:
        if json.loads(marker.read_text(encoding="utf-8")).get("key") == key:
            return False
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    atomic_json(marker, {"key": key, "requested_at": time.time()})
    try:
        launch_popup(scratch, status)
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--launcher-error")
    action.add_argument("--completion", action="store_true")
    parser.add_argument("--started-at", type=float, default=0)
    args = parser.parse_args()
    scratch = Path.home() / ".gemini/antigravity/scratch"
    if args.completion:
        notify_completion(scratch, args.started_at)
        return 0
    status = read_status(scratch)
    if not (args.started_at > 0 and status.get("state") in {"error", "blocked"} and status.get("updated_at", 0) >= args.started_at):
        write_status(scratch, "error", "launcher", kind="launcher_error", message=args.launcher_error)
    notify_failure(scratch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
