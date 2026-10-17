"""Self-healing progress state shared by the popup, repacker, agent and progress window.

The state file is the single source of truth for the progress window. The repacker
mirrors its phases here automatically; the repairing agent reports its own steps
through the CLI of this module. When a run finishes, the result (findings, diffs,
step timings) is merged into UPGRADE_HISTORY.json so every version stays documented.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRATCH_DIR = Path.home() / ".gemini" / "antigravity" / "scratch"
STATE_NAME = "selfheal_state.json"
SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_SKILL_ROOT = Path.home() / ".gemini" / "config" / "skills" / "antigravity_desktop_ui_modifier"
HISTORY_NAME = "UPGRADE_HISTORY.json"
HISTORY_LIMIT = 50
STALE_AFTER_SECONDS = 2 * 60 * 60

# id, label, weight (share of the total progress bar)
STEPS = [
    ("detected", "Update erkannt", 5),
    ("analysis", "Agent analysiert die Änderungen", 20),
    ("adapt", "Agent passt den Injector an", 20),
    ("tests", "Tests & Kompatibilitätsprüfung", 15),
    ("repack", "Backup, Packen & Installieren", 20),
    ("restart", "Neustart & Live-Verifikation", 15),
    ("restore", "Chat wiederherstellen", 5),
]
STEP_IDS = [step[0] for step in STEPS]

# repack_and_restart.py phase -> (step id, fraction of that step already completed)
PHASE_MAP = {
    "preflight": ("tests", 0.1),
    "build": ("tests", 0.4),
    "validate": ("tests", 0.8),
    "save_state": ("repack", 0.1),
    "stop": ("repack", 0.25),
    "pack": ("repack", 0.5),
    "install": ("repack", 0.8),
    "start": ("restart", 0.3),
    "verify": ("restart", 0.7),
    "guard_state": ("restore", 0.5),
}


def _state_path(scratch: Path | None = None) -> Path:
    return Path(scratch or SCRATCH_DIR) / STATE_NAME


def _atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".selfheal-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_state(scratch: Path | None = None) -> dict:
    try:
        data = json.loads(_state_path(scratch).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def is_active(scratch: Path | None = None) -> bool:
    state = read_state(scratch)
    if not state.get("active"):
        return False
    return time.time() - float(state.get("updated_at", 0)) < STALE_AFTER_SECONDS


def compute_percent(state: dict) -> int:
    total = sum(weight for _, _, weight in STEPS)
    done = 0.0
    for step_id, _label, weight in STEPS:
        entry = state.get("steps", {}).get(step_id, {})
        status = entry.get("status", "pending")
        if status == "done":
            done += weight
        elif status in ("running", "failed"):
            done += weight * float(entry.get("fraction", 0.35))
    if state.get("result") == "success":
        return 100
    return max(0, min(99, int(round(done * 100 / total))))


def _write(state: dict, scratch: Path | None = None) -> dict:
    state["updated_at"] = time.time()
    state["percent"] = compute_percent(state)
    _atomic_json(_state_path(scratch), state)
    return state


def begin(from_version: str, to_version: str, scratch: Path | None = None, attempt: int = 1) -> dict:
    """Start a new self-healing run. The update itself is already detected."""
    now = time.time()
    steps = {step_id: {"status": "pending"} for step_id in STEP_IDS}
    steps["detected"] = {"status": "done", "started_at": now, "finished_at": now}
    state = {
        "active": True,
        "result": "running",
        "kind": "repair",
        "from_version": from_version,
        "to_version": to_version,
        "attempt": attempt,
        "started_at": now,
        "steps": steps,
        "findings": [],
        "diff_summary": {},
        "message": "Selbstheilung gestartet. Der Agent analysiert die neue Version.",
    }
    steps["analysis"] = {"status": "running", "started_at": now, "fraction": 0.1}
    return _write(state, scratch)


# The guard pauses automatic repacks while an agent edits the skill, but never longer
# than this without a progress report, so a stalled agent cannot block it for hours.
AGENT_EDIT_HOLD_SECONDS = 30 * 60


def agent_repair_in_progress(state: dict | None = None, now: float | None = None, scratch: Path | None = None) -> bool:
    """True while an agent repair is analysing/adapting/testing and has not started the repack.

    During that window skill sources change in several steps; an automatic repack
    would install a half-adapted, untested injector.
    """
    state = read_state(scratch) if state is None else state
    now = time.time() if now is None else now
    if not state.get("active") or state.get("result") != "running":
        return False
    steps = state.get("steps", {})
    if state.get("kind", "repair") != "repair":
        return False
    # Legacy plain-repack runs created before the "kind" field existed.
    if steps.get("analysis", {}).get("detail") == "nicht nötig (reiner Repack)":
        return False
    if steps.get("repack", {}).get("status", "pending") != "pending":
        return False
    return now - float(state.get("updated_at", 0)) < AGENT_EDIT_HOLD_SECONDS


def set_step(step_id: str, status: str, detail: str = "", fraction: float | None = None, scratch: Path | None = None) -> dict:
    state = read_state(scratch)
    if not state.get("active") or step_id not in STEP_IDS:
        return state
    now = time.time()
    entry = state.setdefault("steps", {}).setdefault(step_id, {"status": "pending"})
    if status == "running" and entry.get("status") != "running":
        entry["started_at"] = now
    if status in ("done", "failed"):
        entry["finished_at"] = now
        entry.setdefault("started_at", now)
    # Steps before the current one can no longer be pending or running, even if the
    # reporting agent forgot to mark them done.
    for earlier in STEP_IDS[: STEP_IDS.index(step_id)]:
        earlier_entry = state["steps"].setdefault(earlier, {"status": "pending"})
        if earlier_entry.get("status") in ("pending", "running"):
            earlier_entry["status"] = "done"
            earlier_entry.setdefault("started_at", now)
            earlier_entry["finished_at"] = now
    entry["status"] = status
    if fraction is not None:
        entry["fraction"] = max(0.0, min(1.0, fraction))
    if detail:
        entry["detail"] = detail
        state["message"] = detail
    if status == "failed":
        state["result"] = "failed"
        state["failed_step"] = step_id
    elif state.get("result") == "failed":
        state["result"] = "running"
        state.pop("failed_step", None)
    return _write(state, scratch)


def add_finding(text: str, scratch: Path | None = None) -> dict:
    state = read_state(scratch)
    if state.get("active") and text and text not in state.setdefault("findings", []):
        state["findings"].append(text)
        return _write(state, scratch)
    return state


def set_diff(file_name: str, detail: str, scratch: Path | None = None) -> dict:
    state = read_state(scratch)
    if state.get("active") and file_name:
        state.setdefault("diff_summary", {})[file_name] = detail
        return _write(state, scratch)
    return state


def _is_live_scratch(scratch: Path | None) -> bool:
    if scratch is None:
        return True
    try:
        return Path(scratch).resolve() == Path(SCRATCH_DIR).resolve()
    except OSError:
        return False


def mirror_repack_status(state_name: str, phase: str, message: str = "", scratch: Path | None = None) -> None:
    """Called from write_status(); mirrors repack phases into the progress window.

    A plain repack without a prior self-healing run starts its own run (and the
    window) so the user always sees that the app is being restarted.
    """
    try:
        if not is_active(scratch):
            if not _is_live_scratch(scratch) or state_name != "running" or phase not in PHASE_MAP:
                return
            begin("", "", scratch)
            current = read_state(scratch)
            current["kind"] = "repack"
            current["message"] = "Repack läuft: der Injector wird neu installiert."
            current["steps"]["detected"]["detail"] = "Repack gestartet"
            current["steps"]["analysis"] = {"status": "done", "detail": "nicht nötig (reiner Repack)"}
            current["steps"]["adapt"] = {"status": "done", "detail": "nicht nötig (reiner Repack)"}
            _write(current, scratch)
            launch_window()
        if state_name == "running" and phase in PHASE_MAP:
            step_id, fraction = PHASE_MAP[phase]
            set_step(step_id, "running", fraction=fraction, scratch=scratch)
        elif state_name == "running" and phase == "rollback":
            current = read_state(scratch)
            failing = next(
                (sid for sid in STEP_IDS if current.get("steps", {}).get(sid, {}).get("status") == "running"),
                "repack",
            )
            set_step(failing, "failed", "Fehler beim Repack: automatischer Rollback läuft.", scratch=scratch)
        elif state_name == "success" and phase == "complete":
            set_step("restore", "done", "Chat wiederhergestellt, alles verifiziert.", fraction=1.0, scratch=scratch)
            finish("success", scratch=scratch)
        elif state_name == "error" and phase not in ("preflight", "guard", "status"):
            current = read_state(scratch)
            failing = next(
                (sid for sid in STEP_IDS if current.get("steps", {}).get(sid, {}).get("status") == "running"),
                "repack",
            )
            set_step(failing, "failed", message or "Repack fehlgeschlagen.", scratch=scratch)
    except Exception:
        # Progress reporting must never break the repack itself.
        pass


def _history_paths() -> list[Path]:
    paths = [SKILL_ROOT / HISTORY_NAME]
    if CONFIG_SKILL_ROOT.is_dir() and (CONFIG_SKILL_ROOT / HISTORY_NAME) not in paths:
        paths.append(CONFIG_SKILL_ROOT / HISTORY_NAME)
    return paths


def _read_history(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def finish(result: str, scratch: Path | None = None) -> dict:
    """Close the run and merge it into the persistent per-version history."""
    state = read_state(scratch)
    if not state.get("active") and state.get("result") in ("success", "failed"):
        return state
    now = time.time()
    state["result"] = result
    state["finished_at"] = now
    if result == "success":
        for step_id in STEP_IDS:
            entry = state.setdefault("steps", {}).setdefault(step_id, {"status": "pending"})
            if entry.get("status") != "done":
                entry["status"] = "done"
                entry.setdefault("started_at", now)
                entry["finished_at"] = now
        state["active"] = False
        state["message"] = "Selbstheilung abgeschlossen. Alles verifiziert."
    else:
        state["message"] = state.get("message") or "Selbstheilung fehlgeschlagen."
    _write(state, scratch)
    record_history(state)
    return state


def _compact_steps(state: dict) -> list[dict]:
    compact = []
    for step_id, label, _weight in STEPS:
        entry = state.get("steps", {}).get(step_id, {})
        duration = None
        if entry.get("started_at") and entry.get("finished_at"):
            duration = round(entry["finished_at"] - entry["started_at"], 1)
        compact.append({"id": step_id, "label": label, "status": entry.get("status", "pending"), "duration_s": duration})
    return compact


def record_history(state: dict) -> None:
    """Merge the run into UPGRADE_HISTORY.json (newest first, bounded size)."""
    version = str(state.get("to_version") or "").strip()
    if not version:
        return
    entry_update = {
        "version": version,
        "from_version": state.get("from_version", ""),
        "date": time.strftime("%Y-%m-%d", time.localtime(state.get("started_at", time.time()))),
        "time": time.strftime("%H:%M", time.localtime(state.get("started_at", time.time()))),
        "result": state.get("result", ""),
        "attempts": state.get("attempt", 1),
        "duration_s": round(state.get("finished_at", time.time()) - state.get("started_at", time.time()), 1),
        "steps": _compact_steps(state),
    }
    for path in _history_paths():
        try:
            history = _read_history(path)
            existing = next((item for item in history if item.get("version") == version), None)
            if existing is None:
                existing = {"version": version, "upstream_status": "compatible", "diff_summary": {}, "findings": []}
                history.insert(0, existing)
            existing.update(entry_update)
            existing["upstream_status"] = "compatible" if state.get("result") == "success" else "failed"
            for finding in state.get("findings", []):
                if finding not in existing.setdefault("findings", []):
                    existing["findings"].append(finding)
            existing.setdefault("diff_summary", {}).update(state.get("diff_summary", {}))
            history.sort(key=lambda item: tuple(int(p) if p.isdigit() else 0 for p in str(item.get("version", "0")).split(".")), reverse=True)
            _atomic_json(path, history[:HISTORY_LIMIT])
        except OSError:
            continue


def build_repair_prompt(installed: str, supported: str, attempt: int = 1) -> str:
    script = Path(__file__).resolve()
    cli = f'python "{script}"'
    retry_note = ""
    if attempt > 1:
        retry_note = (
            f"Das ist Versuch {attempt}: Die vorherige Reparatur ist fehlgeschlagen und der Rollback wurde ausgeführt. "
            "Lies zuerst ~/.gemini/antigravity/scratch/repack_and_restart.log und die Historie, finde den Grund und behebe ihn.\n\n"
        )
    return (
        f"Anti-Gravity wurde auf Version {installed} aktualisiert (freigegeben war {supported}) und der Injector "
        "(antigravity_desktop_ui_modifier) wurde sicherheitsblockiert. Behebe das selbstständig.\n\n"
        + retry_note
        + "Aufgaben: 1) app.asar der neuen Version entpacken und die Core-Dateien (main.js, ipcHandlers.js, updater.js, utils.js, preload.js) "
        "gegen die bisherige Basis vergleichen. 2) Injector-Quellen, SUPPORTED_UPSTREAM_VERSION und UPSTREAM_COMPATIBILITY.json anpassen. "
        "3) Tests ausführen. 4) Repack starten (start_repack_task.ps1) und Live-Verifikation abwarten.\n\n"
        f"Unveränderte Upstream-Basis v{supported} (falls vorhanden): {SCRATCH_DIR / 'upstream_baselines' / supported / 'dist'} "
        "– damit alle dist-Dateien vergleichen, nicht nur die Core-Dateien. Der Guard pausiert automatische Repacks "
        "während dieser Reparatur selbst, solange du Fortschritt meldest.\n\n"
        "WICHTIG – melde deinen Fortschritt nach jedem Schritt, damit der Fortschrittsbalken des Nutzers stimmt:\n"
        f"- {cli} step analysis running|done \"Kurzinfo\"\n"
        f"- {cli} step adapt running|done \"Kurzinfo\"\n"
        f"- {cli} step tests running|done \"Kurzinfo\"\n"
        f"- {cli} finding \"Erkenntnis in einem Satz\"   (für jede wichtige Erkenntnis)\n"
        f"- {cli} diff \"dist/preload.js\" \"was sich geändert hat\"\n"
        f"- {cli} step <id> failed \"Grund\"   (nur bei einem Fehler)\n"
        "Repack und Neustart meldet das System selbst. Alle Erkenntnisse und Diffs werden dauerhaft im Update- & Patch-Log gespeichert."
    )


def launch_window() -> bool:
    """Start the always-on-top progress window unless one is already running."""
    window_script = Path(__file__).with_name("selfheal_window.py")
    if not window_script.is_file() or os.name != "nt":
        return False
    lock = SCRATCH_DIR / "selfheal_window.pid"
    try:
        pid = int(lock.read_text(encoding="utf-8").strip())
        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if str(pid) in (probe.stdout or ""):
            return True
    except (OSError, ValueError):
        pass
    windowless = Path(sys.executable).with_name("pythonw.exe")
    interpreter = str(windowless if windowless.is_file() else Path(sys.executable))
    subprocess.Popen(
        [interpreter, str(window_script)],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-healing progress reporter.")
    sub = parser.add_subparsers(dest="command", required=True)
    step = sub.add_parser("step")
    step.add_argument("step_id", choices=STEP_IDS)
    step.add_argument("status", choices=["running", "done", "failed"])
    step.add_argument("detail", nargs="?", default="")
    finding = sub.add_parser("finding")
    finding.add_argument("text")
    diff = sub.add_parser("diff")
    diff.add_argument("file")
    diff.add_argument("detail")
    begin_cmd = sub.add_parser("begin")
    begin_cmd.add_argument("from_version")
    begin_cmd.add_argument("to_version")
    sub.add_parser("show")
    sub.add_parser("window")
    args = parser.parse_args()

    if args.command == "step":
        set_step(args.step_id, args.status, args.detail)
    elif args.command == "finding":
        add_finding(args.text)
    elif args.command == "diff":
        set_diff(args.file, args.detail)
    elif args.command == "begin":
        begin(args.from_version, args.to_version)
        launch_window()
    elif args.command == "window":
        launch_window()
    elif args.command == "show":
        print(json.dumps(read_state(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
