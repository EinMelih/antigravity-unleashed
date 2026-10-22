"""Invisible update guard for the injected Anti-Gravity desktop UI.

The guard never patches a closed app. It notices an Anti-Gravity update or changed
skill source, waits for the next normal app start, and then delegates to the
transactional repack script. The repacker owns backup, validation and rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from injector_status import clear_notification, notify_failure, read_status, sha256_file, unsupported_message, version_info, write_status


WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _configured_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().resolve()


def resolve_install_paths() -> tuple[Path, Path, Path]:
    install_override = os.environ.get("ANTIGRAVITY_INSTALL_DIR", "").strip()
    resources_override = os.environ.get("ANTIGRAVITY_RESOURCES_DIR", "").strip()
    if install_override:
        install_dir = _configured_path(install_override)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise RuntimeError(
                "LOCALAPPDATA is unavailable; set ANTIGRAVITY_INSTALL_DIR explicitly."
            )
        install_dir = _configured_path(local_app_data) / "Programs" / "Antigravity"
    resources_dir = (
        _configured_path(resources_override)
        if resources_override
        else install_dir / "resources"
    )
    return install_dir.resolve(), resources_dir.resolve(), (install_dir / "Antigravity.exe").resolve()


INSTALL_DIR, RESOURCES_DIR, APP_EXE = resolve_install_paths()
APP_ASAR = RESOURCES_DIR / "app.asar"
SKILL_ROOT = Path(__file__).resolve().parent.parent
REPACK_SCRIPT = Path(__file__).resolve().with_name("repack_and_restart.py")
SCRATCH_DIR = Path.home() / ".gemini" / "antigravity" / "scratch"
STATE_FILE = SCRATCH_DIR / "auto_repack_guard_state.json"
FAILURE_LATCH_FILE = SCRATCH_DIR / "auto_repack_guard_failure.json"
ERROR_FILE = SCRATCH_DIR / "repack_error.txt"
LOG_FILE = SCRATCH_DIR / "auto_repack_guard.log"
STAGING_DIR = APP_ASAR.parent / "repack-staging"


def log(message: str) -> None:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def request_failure_popup() -> None:
    try:
        notify_failure(SCRATCH_DIR)
    except Exception as notification_error:
        log(f"Error popup could not be launched: {notification_error}")


def stat_signature(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return None


def source_signature() -> str:
    digest = hashlib.sha256()
    supported_version_file = SKILL_ROOT / "SUPPORTED_UPSTREAM_VERSION"
    roots = [
        SKILL_ROOT / "src",
        SKILL_ROOT / "scripts" / "build_preload.py",
        SKILL_ROOT / "scripts" / "repack_and_restart.py",
        SKILL_ROOT / "scripts" / "injector_status.py",
        SKILL_ROOT / "scripts" / "notification_popup.py",
        supported_version_file,
        SKILL_ROOT / "UPSTREAM_COMPATIBILITY.json",
    ]
    # build_preload.py rewrites these generated files during every build. Their
    # changing mtimes must not be treated as source edits, otherwise one repack
    # can schedule the next one indefinitely.
    build_artifacts = {
        (SKILL_ROOT / "src" / "preload.js").resolve(),
        (SKILL_ROOT / "src" / "preload.js.build.tmp.js").resolve(),
    }
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())
    for path in sorted(files, key=lambda item: str(item).lower()):
        if (
            path.suffix.lower() not in {".js", ".json", ".txt", ".py"}
            and path.resolve() != supported_version_file.resolve()
        ):
            continue
        if path.resolve() in build_artifacts:
            continue
        stat = path.stat()
        digest.update(str(path.relative_to(SKILL_ROOT)).encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def current_state() -> dict[str, object]:
    return {
        "app_asar": stat_signature(APP_ASAR),
        "source": source_signature(),
    }


def read_state() -> dict[str, object]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def write_state(state: dict[str, object]) -> None:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({**state, "verified_at": time.time()}, indent=2), encoding="utf-8")
    os.replace(temp, STATE_FILE)


def mark_current_verified() -> None:
    versions = version_info(APP_ASAR, SKILL_ROOT)
    record = json.loads((SCRATCH_DIR / "verified_repack_installation.json").read_text(encoding="utf-8"))
    if versions["installed_version"] != versions["supported_version"] or record.get("upstream_version") != versions["supported_version"]:
        raise RuntimeError("Guard-Status abgewiesen: keine verifizierte, unterstuetzte Version.")
    if record.get("installed_asar_sha256") != sha256_file(APP_ASAR):
        raise RuntimeError("Guard-Status abgewiesen: der installierte Archivhash wurde nicht verifiziert.")
    if record.get("upstream_contract_sha256") != sha256_file(SKILL_ROOT / "UPSTREAM_COMPATIBILITY.json"):
        raise RuntimeError("Guard-Status abgewiesen: der Versionsvertrag wurde nicht verifiziert.")
    captured_source = record.get("source_signature")
    if not isinstance(captured_source, str) or not re.fullmatch(r"[a-f0-9]{64}", captured_source):
        raise RuntimeError("Guard-Status abgewiesen: Signatur der verifizierten Quellen fehlt.")
    write_state({"app_asar": stat_signature(APP_ASAR), "source": captured_source})
    clear_failure_latch()
    clear_notification(SCRATCH_DIR)
    clear_user_approval_and_notice()


def read_failure_latch() -> dict[str, object] | None:
    try:
        data = json.loads(FAILURE_LATCH_FILE.read_text(encoding="utf-8"))
        observed = data.get("observed")
        return observed if isinstance(observed, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def write_failure_latch(observed: dict[str, object]) -> None:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    temp = FAILURE_LATCH_FILE.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"observed": observed, "failed_at": time.time()}, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, FAILURE_LATCH_FILE)


def clear_failure_latch() -> None:
    try:
        FAILURE_LATCH_FILE.unlink()
    except FileNotFoundError:
        pass


def failure_latch_action(
    failed_observed: dict[str, object] | None,
    observed: dict[str, object],
    app_running: bool,
) -> str | None:
    if not failed_observed:
        return None
    if failed_observed != observed:
        return "signature_changed"
    if not app_running:
        return "app_exited"
    return "hold"


def antigravity_process_ids() -> list[int]:
    if os.name != "nt":
        return []
    query_environment = os.environ.copy()
    query_environment["AMS_GUARD_TARGET_EXE"] = str(APP_EXE)
    command = (
        "$target = [IO.Path]::GetFullPath($env:AMS_GUARD_TARGET_EXE); "
        "Get-CimInstance Win32_Process -Filter \"Name = 'Antigravity.exe'\" | "
        "Where-Object { $_.ExecutablePath -and "
        "[string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $target, "
        "[StringComparison]::OrdinalIgnoreCase) -and "
        "([string]$_.CommandLine -notmatch '--type=|dist/server\\.cjs|--import=') } | "
        "ForEach-Object { $_.ProcessId }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        env=query_environment,
        creationflags=WINDOW_FLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Exact Antigravity process lookup failed: "
            + (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        )
    return sorted(
        {int(line.strip()) for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
    )


def antigravity_is_running() -> bool:
    return bool(antigravity_process_ids())


def repack_is_running() -> bool:
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -like '*repack_and_restart.py*' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        creationflags=WINDOW_FLAGS,
    )
    return bool((result.stdout or "").strip())


def needs_repack(installed: dict[str, object], observed: dict[str, object]) -> bool:
    return bool(observed.get("app_asar")) and (
        installed.get("app_asar") != observed.get("app_asar")
        or installed.get("source") != observed.get("source")
    )


PAUSE_FILE = SCRATCH_DIR / "auto_repack_guard_pause.json"
PENDING_NOTICE_FILE = SCRATCH_DIR / "repack_pending_notice.json"
APPROVAL_FILE = SCRATCH_DIR / "repack_user_approved.json"
# Skill edits arrive in bursts (several files, rebuilds, tests). A source-only change
# must stay untouched this long before the guard repacks; app updates keep the short
# three-poll stability check.
SOURCE_QUIET_SECONDS = 90.0
MAX_PAUSE_MINUTES = 240.0


def _pause_file() -> Path:
    default_pause = Path.home() / ".gemini" / "antigravity" / "scratch" / "auto_repack_guard_pause.json"
    if PAUSE_FILE != default_pause:
        return PAUSE_FILE
    return SCRATCH_DIR / "auto_repack_guard_pause.json"


def _pending_notice_file() -> Path:
    return SCRATCH_DIR / "repack_pending_notice.json"


def _approval_file() -> Path:
    return SCRATCH_DIR / "repack_user_approved.json"


def pending_notice_awaiting_user() -> bool:
    try:
        data = json.loads(_pending_notice_file().read_text(encoding="utf-8"))
        return bool(isinstance(data, dict) and data.get("await_user_click") is True)
    except (OSError, ValueError, TypeError):
        return False


def user_approved_repack(observed: dict[str, object]) -> bool:
    try:
        data = json.loads(_approval_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("approved"):
            return False
        approved_at = float(data.get("approved_at") or data.get("timestamp") or 0)
        if time.time() - approved_at > 600:
            return False
        return True
    except (OSError, ValueError, TypeError):
        return False


def clear_user_approval_and_notice() -> None:
    for path in (_approval_file(), _pending_notice_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def read_pause_until(now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    try:
        until = float(json.loads(_pause_file().read_text(encoding="utf-8")).get("until", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return until if until > now else None


def write_pause(minutes: float) -> float:
    minutes = max(1.0, min(MAX_PAUSE_MINUTES, float(minutes)))
    until = time.time() + minutes * 60
    pause_path = _pause_file()
    pause_path.parent.mkdir(parents=True, exist_ok=True)
    temp = pause_path.with_suffix(".tmp")
    temp.write_text(json.dumps({"until": until, "requested_at": time.time()}, indent=2), encoding="utf-8")
    os.replace(temp, pause_path)
    return until


def clear_pause() -> None:
    try:
        _pause_file().unlink()
    except FileNotFoundError:
        pass


def agent_repair_active() -> bool:
    try:
        from selfheal import agent_repair_in_progress
        return agent_repair_in_progress(scratch=SCRATCH_DIR)
    except Exception:
        return False


def hold_reason(now: float | None = None) -> str | None:
    """Reasons to postpone an otherwise pending repack (never blocks forever)."""
    if read_pause_until(now):
        return "paused"
    if agent_repair_active():
        return "agent_repair"
    if pending_notice_awaiting_user():
        return "awaiting_user_click"
    return None


def source_only_change(installed: dict[str, object], observed: dict[str, object]) -> bool:
    return installed.get("app_asar") == observed.get("app_asar") and installed.get("source") != observed.get("source")


def ready_to_repack(
    installed: dict[str, object],
    observed: dict[str, object],
    stable_count: int,
    stable_since: float,
    now: float,
) -> bool:
    if stable_count < 3:
        return False
    if source_only_change(installed, observed):
        return now - stable_since >= SOURCE_QUIET_SECONDS
    return True


def run_guard(poll_seconds: float) -> int:
    log(f"Guard started (skill={SKILL_ROOT}).")
    stable_candidate: dict[str, object] | None = None
    stable_count = 0
    stable_since = time.time()
    last_hold_reason: str | None = None
    failed_observed = read_failure_latch()
    while True:
        try:
            # A manual --retry can clear the latch while this guard remains alive.
            failed_observed = read_failure_latch()
            installed = read_state()
            observed = current_state()
            if not needs_repack(installed, observed):
                if failed_observed:
                    clear_failure_latch()
                    failed_observed = None
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue

            app_running = antigravity_is_running()
            latch_action = failure_latch_action(failed_observed, observed, app_running)
            if latch_action == "hold":
                request_failure_popup()
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue
            if latch_action:
                clear_failure_latch()
                failed_observed = None
                stable_candidate = None
                stable_count = 0
                log(
                    "Previous failure latch cleared because "
                    + ("the app exited." if latch_action == "app_exited" else "the observed signature changed.")
                )
                if latch_action == "app_exited":
                    time.sleep(poll_seconds)
                    continue

            if observed == stable_candidate:
                stable_count += 1
            else:
                stable_candidate = observed
                stable_count = 1
                stable_since = time.time()

            # A running repack will store a new verified signature when it ends; the
            # stability window must restart afterwards instead of firing immediately
            # on the state read just before that signature was written.
            if repack_is_running():
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue

            # Avoid reading a partially replaced update and do not open a closed app.
            if stable_count < 3 or not app_running:
                time.sleep(poll_seconds)
                continue

            versions = version_info(APP_ASAR, SKILL_ROOT)
            if versions["installed_version"] != versions["supported_version"]:
                message = unsupported_message(versions)
                write_status(SCRATCH_DIR, "blocked", "preflight", kind="unsupported_version", message=message, **versions)
                ERROR_FILE.write_text(message, encoding="utf-8")
                failed_observed = observed
                write_failure_latch(observed)
                log(message)
                request_failure_popup()
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue

            if source_only_change(installed, observed) and not user_approved_repack(observed):
                notice_path = _pending_notice_file()
                if not notice_path.is_file():
                    notice_path.parent.mkdir(parents=True, exist_ok=True)
                    notice_path.write_text(
                        json.dumps(
                            {
                                "title": "Unleashed UI-Update bereit",
                                "details": "Neue Funktionen/Änderungen im Desktop-Modifier warten auf deinen Neustart-Klick.",
                                "await_user_click": True,
                                "updated_at": int(time.time()),
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    log("Source-only change detected; waiting for user click on in-app Repack button.")
                time.sleep(poll_seconds)
                continue

            reason = hold_reason()
            if reason != last_hold_reason:
                if reason:
                    log(f"Repack postponed ({reason}); sources may still be changing.")
                elif last_hold_reason:
                    log(f"Repack hold released ({last_hold_reason}).")
                last_hold_reason = reason
            if reason or not ready_to_repack(installed, observed, stable_count, stable_since, time.time()):
                time.sleep(poll_seconds)
                continue

            if not needs_repack(read_state(), current_state()):
                # Another repack stored the verified signature in the meantime.
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue

            log("Change detected after normal Anti-Gravity start; launching verified repack.")
            try:
                result = subprocess.run(
                    [sys.executable, str(REPACK_SCRIPT)],
                    cwd=str(SKILL_ROOT),
                    creationflags=WINDOW_FLAGS,
                )
            except Exception as repack_error:
                failed_observed = current_state()
                write_failure_latch(failed_observed)
                write_status(SCRATCH_DIR, "error", "launcher", kind="launch_error", message=f"Repack konnte nicht gestartet werden: {repack_error}", **versions)
                request_failure_popup()
                log(
                    f"Repack could not be launched ({repack_error}); "
                    "this signature is latched until app exit or signature change."
                )
                stable_candidate = None
                stable_count = 0
                time.sleep(poll_seconds)
                continue
            if result.returncode == 0 and not ERROR_FILE.exists():
                mark_current_verified()
                failed_observed = None
                log("Repack completed and new app/source signature was stored.")
            else:
                failed_observed = current_state()
                write_failure_latch(failed_observed)
                status = read_status(SCRATCH_DIR)
                if status.get("state") not in {"error", "blocked"}:
                    details = ERROR_FILE.read_text(encoding="utf-8") if ERROR_FILE.is_file() else f"Repack fehlgeschlagen (Exit {result.returncode})."
                    write_status(SCRATCH_DIR, "error", status.get("phase", "repack"), kind="repack_error", message=details, **versions)
                request_failure_popup()
                log(
                    f"Repack failed (exit={result.returncode}); this signature is latched "
                    "until app exit or signature change."
                )
            stable_candidate = None
            stable_count = 0
        except Exception as error:
            log(f"Guard loop error: {error}")
            write_status(SCRATCH_DIR, "error", "guard", kind="guard_error", message=str(error))
            request_failure_popup()
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-current", action="store_true", help="Trust and store the current verified installation signature.")
    parser.add_argument("--status-json", action="store_true", help="Print the current read-only guard status as JSON.")
    parser.add_argument("--retry", action="store_true", help="Retry a failed injection without trusting or changing the verified installation state.")
    parser.add_argument("--pause", type=float, metavar="MINUTES", help="Postpone automatic repacks (e.g. while editing skill sources); max 240 minutes.")
    parser.add_argument("--resume", action="store_true", help="Lift a pause requested with --pause.")
    parser.add_argument("--poll-seconds", type=float, default=4.0)
    args = parser.parse_args()
    if args.pause is not None:
        until = write_pause(args.pause)
        log(f"Automatic repacks paused until {time.strftime('%H:%M:%S', time.localtime(until))}.")
        print(f"Automatische Repacks pausiert bis {time.strftime('%H:%M:%S', time.localtime(until))}.")
        return 0
    if args.resume:
        clear_pause()
        log("Automatic repack pause lifted.")
        print("Pause aufgehoben. Der Guard prueft wieder normal.")
        return 0
    if args.retry:
        clear_failure_latch()
        clear_notification(SCRATCH_DIR)
        write_status(SCRATCH_DIR, "retry_requested", "waiting_for_app", message="Wiederholung angefordert; die verifizierte Installation bleibt unveraendert.")
        log("Manual retry requested without changing the verified installation state.")
        print("Wiederholung angefordert. Der Guard versucht es bei laufender App erneut.")
        return 0
    if args.status_json:
        installed = read_state()
        observed = current_state()
        failed_observed = read_failure_latch()
        app_running = antigravity_is_running()
        status = read_status(SCRATCH_DIR)
        try:
            versions = version_info(APP_ASAR, SKILL_ROOT)
            version_error = None
        except Exception as error:
            versions = {}
            version_error = str(error)
        print(
            json.dumps(
                {
                    "pending": needs_repack(installed, observed),
                    "source": observed.get("source", ""),
                    "verified_at": installed.get("verified_at"),
                    "app_running": app_running,
                    "status": status,
                    "versions": versions,
                    "version_error": version_error,
                    "error_log": str(ERROR_FILE),
                    "popup_requested": (SCRATCH_DIR / "repack_notification.json").is_file(),
                    "failure_latched": bool(failed_observed == observed),
                    "latch_action": failure_latch_action(
                        failed_observed,
                        observed,
                        app_running,
                    ),
                    "hold_reason": hold_reason(),
                    "paused_until": read_pause_until(),
                }
            )
        )
        return 0
    if args.mark_current:
        mark_current_verified()
        log("Current verified signature stored.")
        return 0
    return run_guard(max(2.0, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
