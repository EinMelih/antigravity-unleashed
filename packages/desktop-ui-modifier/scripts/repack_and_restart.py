import os
import sys
import subprocess
import time
import traceback
import json
import urllib.request
import urllib.parse
import shutil
import asyncio
import msvcrt
import re
import hashlib
from pathlib import Path
from injector_status import clear_notification, notify_failure, read_status, sha256_file, unsupported_message, version_info, write_status
from auto_repack_guard import source_signature


WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
DETACHED_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
CHAT_ID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)
SCRATCH_DIR = Path.home() / ".gemini" / "antigravity" / "scratch"
VERIFIED_INSTALLATION_FILE = SCRATCH_DIR / "verified_repack_installation.json"


def supported_upstream_version():
    """Return the upstream version this modifier is released for (display only)."""
    version_file = Path(__file__).resolve().parent.parent / "SUPPORTED_UPSTREAM_VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "unbekannt"
    except OSError:
        return "unbekannt"


def _configured_path(value):
    return Path(os.path.expandvars(value)).expanduser().resolve()


def resolve_install_paths():
    """Resolve this user's Antigravity installation without embedding a profile path."""
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


def resolve_user_data_dir():
    override = os.environ.get("ANTIGRAVITY_USER_DATA_DIR", "").strip()
    if override:
        return _configured_path(override)
    roaming_app_data = os.environ.get("APPDATA", "").strip()
    if roaming_app_data:
        return (_configured_path(roaming_app_data) / "Antigravity").resolve()
    return (Path.home() / "AppData" / "Roaming" / "Antigravity").resolve()


def application_launch_environment():
    environment = os.environ.copy()
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    return environment


def claim_trigger_chat_id(log_file):
    """Atomically claim and validate the optional chat that requested this repack."""
    trigger_file = SCRATCH_DIR / "repack_trigger_chat.txt"
    claimed_file = trigger_file.with_name(f"{trigger_file.name}.{os.getpid()}.claimed")
    try:
        os.replace(trigger_file, claimed_file)
    except FileNotFoundError:
        return None
    except OSError as error:
        log_file.write(f"Trigger-Chat-Datei konnte nicht uebernommen werden: {error}\n")
        log_file.flush()
        return None

    try:
        chat_id = claimed_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        log_file.write(f"Trigger-Chat-Datei konnte nicht gelesen werden: {error}\n")
        log_file.flush()
        return None
    finally:
        try:
            claimed_file.unlink(missing_ok=True)
        except OSError:
            pass

    if not CHAT_ID_PATTERN.fullmatch(chat_id):
        log_file.write("Ungueltige Trigger-Chat-ID wurde verworfen.\n")
        log_file.flush()
        return None
    log_file.write(f"Trigger-Chat-ID sicher uebernommen: {chat_id}\n")
    log_file.flush()
    return chat_id


def list_install_process_ids(app_path):
    """Return only Antigravity processes whose executable is this exact install."""
    if os.name != "nt":
        return []
    query_environment = os.environ.copy()
    query_environment["AMS_REPACK_TARGET_EXE"] = str(Path(app_path).resolve())
    command = (
        "$target = [IO.Path]::GetFullPath($env:AMS_REPACK_TARGET_EXE); "
        "Get-CimInstance Win32_Process -Filter \"Name = 'Antigravity.exe'\" | "
        "Where-Object { $_.ExecutablePath -and "
        "[string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $target, "
        "[StringComparison]::OrdinalIgnoreCase) } | "
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


def list_install_listener_ports(app_path):
    """Return loopback listener ports owned by this exact Antigravity install."""
    if os.name != "nt":
        return []
    process_ids = list_install_process_ids(app_path)
    if not process_ids:
        return []
    query_environment = os.environ.copy()
    query_environment["AMS_REPACK_TARGET_PIDS"] = ",".join(str(value) for value in process_ids)
    command = (
        "$targetPids = @($env:AMS_REPACK_TARGET_PIDS -split ',' | "
        "Where-Object { $_ -match '^\\d+$' } | ForEach-Object { [int]$_ }); "
        "Get-NetTCPConnection -State Listen -ErrorAction Stop | "
        "Where-Object { $targetPids -contains $_.OwningProcess -and "
        "$_.LocalAddress -in @('127.0.0.1', '::1') } | "
        "ForEach-Object { $_.LocalPort }"
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
            "Exact Antigravity listener lookup failed: "
            + (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        )
    return sorted(
        {
            int(line.strip())
            for line in (result.stdout or "").splitlines()
            if line.strip().isdigit() and 0 < int(line.strip()) <= 65535
        }
    )


def is_devtools_port(port):
    """Return whether a loopback port exposes the Chrome DevTools version API."""
    try:
        numeric_port = int(port)
        if numeric_port <= 0 or numeric_port > 65535:
            return False
        request = urllib.request.Request(f"http://127.0.0.1:{numeric_port}/json/version")
        with urllib.request.urlopen(request, timeout=0.5) as response:
            raw = response.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            return False
        payload = json.loads(raw.decode("utf-8"))
        browser = payload.get("Browser")
        debugger_url = payload.get("webSocketDebuggerUrl")
        return (
            isinstance(browser, str)
            and browser.startswith(("Chrome/", "HeadlessChrome/"))
            and isinstance(debugger_url, str)
            and debugger_url.startswith(("ws://127.0.0.1:", "ws://localhost:"))
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def find_devtools_port(port_file_path, app_path, log_file):
    """Find DevTools via its port file or exact-install listener ownership."""
    port_file = Path(port_file_path)
    if port_file.is_file():
        try:
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0].strip())
            if is_devtools_port(port):
                log_file.write(f"DevTools-Portdatei bestaetigt: {port}\n")
                log_file.flush()
                return port
        except (OSError, ValueError, IndexError):
            pass

    try:
        candidate_ports = list_install_listener_ports(app_path)
    except Exception as error:
        log_file.write(f"DevTools-Listener konnten nicht ermittelt werden: {error}\n")
        log_file.flush()
        return None
    for port in candidate_ports:
        if is_devtools_port(port):
            log_file.write(f"DevTools-Port ueber exakte Prozesszuordnung gefunden: {port}\n")
            log_file.flush()
            return port
    return None


def stop_install_process_tree(app_path, log_file, max_rounds=5):
    """Stop only process trees rooted in the selected Antigravity installation.

    The Hub's API profile (APIProfileRuntime.ensure_started) relaunches its own
    Antigravity instance from the same executable as soon as none is running.
    A single kill pass can therefore be followed by a respawn, so the stop is
    repeated in rounds until the installation is verifiably clear.
    """
    remaining = []
    for round_number in range(1, max_rounds + 1):
        process_ids = list_install_process_ids(app_path)
        if not process_ids:
            if round_number == 1:
                log_file.write("Keine Prozesse der ausgewaehlten Antigravity-Installation aktiv.\n")
            else:
                log_file.write(f"Installation nach Runde {round_number - 1} frei von Prozessen.\n")
            log_file.flush()
            return

        log_file.write(
            f"Beende exakte Antigravity-Prozessbaeume (Runde {round_number}/{max_rounds}): {process_ids}\n"
        )
        log_file.flush()
        for process_id in process_ids:
            if process_id not in list_install_process_ids(app_path):
                continue
            result = subprocess.run(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=WINDOW_FLAGS,
            )
            log_file.write(
                f"taskkill PID {process_id}: exit={result.returncode}; "
                f"stdout={(result.stdout or '').strip()}; stderr={(result.stderr or '').strip()}\n"
            )
            log_file.flush()

        deadline = time.monotonic() + 4
        remaining = list_install_process_ids(app_path)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.25)
            remaining = list_install_process_ids(app_path)
        if not remaining:
            # Give a watcher a moment to respawn, then re-verify before returning.
            time.sleep(1.5)
            remaining = list_install_process_ids(app_path)
            if not remaining:
                log_file.write("Alle Antigravity-Prozesse beendet und stabil.\n")
                log_file.flush()
                return
        log_file.write(
            f"Prozesse nach Runde {round_number} noch/wieder aktiv (Respawn?): {remaining}\n"
        )
        log_file.flush()

    raise RuntimeError(f"Antigravity processes did not exit: {remaining}")


def acquire_repack_lock():
    """Acquire the process-scoped Windows lock guarding the shared staging tree."""
    lock_path = SCRATCH_DIR / "repack.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode("ascii"))
    handle.flush()
    handle.seek(0)
    return handle


def release_repack_lock(handle):
    if handle is None:
        return
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()

def log_renderer_error(log_file, error_message):
    formatted = f"[Renderer Error] {error_message}"
    log_file.write(formatted + "\n")
    log_file.flush()

async def recv_next(ws, log_file):
    import aiohttp
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)

            # Check for error events
            method = data.get("method")
            if method == "Log.entryAdded":
                params = data.get("params") or {}
                entry = params.get("entry") or {}
                if entry.get("level") == "error":
                    url = entry.get("url", "unknown")
                    text = entry.get("text", "")
                    err_msg = f"Log.entryAdded: {text} (URL: {url})"
                    log_renderer_error(log_file, err_msg)

            elif method == "Runtime.exceptionThrown":
                params = data.get("params") or {}
                exception_details = params.get("exceptionDetails") or {}
                exception = exception_details.get("exception")
                description = exception.get("description") if exception else None
                text = exception_details.get("text", "Unhandled Exception")
                if description:
                    err_msg = description
                else:
                    url = exception_details.get("url", "unknown")
                    line = exception_details.get("lineNumber", 0)
                    column = exception_details.get("columnNumber", 0)
                    err_msg = f"{text} at {url}:{line}:{column}"

                log_renderer_error(log_file, err_msg)

            elif method == "Runtime.consoleAPICalled":
                params = data.get("params") or {}
                if params.get("type") == "error":
                    args = params.get("args") or []
                    arg_msgs = []
                    for arg in args:
                        if not arg:
                            arg_msgs.append("null")
                        elif arg.get("type") == "object" and arg.get("description"):
                            arg_msgs.append(arg.get("description"))
                        else:
                            arg_msgs.append(str(arg.get("value") if "value" in arg else arg.get("description", "")))
                    arg_str = " ".join(arg_msgs)

                    # Construct call frame stack trace if available
                    stack_trace = params.get("stackTrace") or {}
                    call_frames = stack_trace.get("callFrames") or []
                    trace_lines = []
                    for frame in call_frames:
                        if not frame:
                            continue
                        fn = frame.get("functionName", "<anonymous>")
                        url = frame.get("url", "unknown")
                        line = frame.get("lineNumber", 0)
                        col = frame.get("columnNumber", 0)
                        trace_lines.append(f"    at {fn} ({url}:{line}:{col})")

                    stack_str = "\n".join(trace_lines)
                    err_msg = arg_str
                    if stack_str:
                        err_msg += "\n" + stack_str

                    log_renderer_error(log_file, err_msg)

            return data
    raise RuntimeError("WebSocket closed unexpectedly")

async def verify_runtime_after_restart(port_file_path, app_path, log_file, target_chat_id=None, active_path=None):
    """Verify the restarted preload/UI through read-only CDP expressions."""
    log_file.write("Starte read-only Runtime-Verifikation...\n")
    log_file.flush()
    # 1. Wait for DevTools. Newer Electron builds can expose port 0 without
    # writing DevToolsActivePort, so fall back to listeners owned by this exact
    # Antigravity installation.
    port = None
    for i in range(60):
        port = find_devtools_port(port_file_path, app_path, log_file)
        if port is not None:
            log_file.write(f"DevTools erreichbar nach {i*0.5}s.\n")
            log_file.flush()
            break
        await asyncio.sleep(0.5)
    else:
        log_file.write("Kein DevTools-Endpunkt der ausgewaehlten Installation gefunden.\n")
        log_file.flush()
        raise FileNotFoundError("Kein DevTools-Endpunkt gefunden.")

    await asyncio.sleep(0.5)

    # 3. Targets abfragen - Warten bis ein Target eine https://127.0.0.1 URL hat
    url = f"http://127.0.0.1:{port}/json"
    ws_url = None
    backend_url = None
    for i in range(60):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1) as resp:
                targets = json.loads(resp.read().decode())
                # Erstes Ziel: nach passendem Chat-Target suchen
                for t in targets:
                    target_url = t.get("url", "")
                    if t.get("webSocketDebuggerUrl") and target_url.startswith("https://127.0.0.1:"):
                        if target_chat_id and target_chat_id in target_url:
                            ws_url = t["webSocketDebuggerUrl"]
                            backend_url = target_url
                            log_file.write(f"WS-URL fuer Ziel-Chat {target_chat_id} gefunden: {ws_url} (Target-URL: {backend_url})\n")
                            log_file.flush()
                            break
                if ws_url:
                    break

                # Nach 15 Sekunden (30 Versuche) als Fallback ein beliebiges aktives Fenster waehlen
                if i > 30:
                    for t in targets:
                        target_url = t.get("url", "")
                        if t.get("webSocketDebuggerUrl") and target_url.startswith("https://127.0.0.1:"):
                            ws_url = t["webSocketDebuggerUrl"]
                            backend_url = target_url
                            log_file.write(f"Fallback: Beliebiges Fenster gewaehlt: {ws_url} (Target-URL: {backend_url})\n")
                            log_file.flush()
                            break
                    if ws_url:
                        break
        except Exception as e:
            pass
        await asyncio.sleep(0.5)
    else:
        log_file.write("Kein passendes Debug-Target gefunden.\n")
        log_file.flush()
        raise RuntimeError("Kein passendes Debug-Target gefunden.")

    # 4. WebSocket-Verbindung aufbauen und Nachricht senden
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                # Enable Runtime and Log domains to listen to console errors/exceptions
                await ws.send_json({"id": 1, "method": "Runtime.enable"})
                await ws.send_json({"id": 2, "method": "Log.enable"})

                # 4a. Aktuelle URL abfragen
                await ws.send_json({
                    "id": 10,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "window.location.href",
                        "returnByValue": True
                    }
                })

                current_href = ""
                while True:
                    data = await recv_next(ws, log_file)
                    if data.get("id") == 10:
                        current_href = data.get("result", {}).get("result", {}).get("value", "")
                        break

                log_file.write(f"Aktuelle Href: {current_href}\n")
                log_file.flush()

                # 4ab. Check if preload.js API is loaded and injection succeeded (with retries to allow loading time)
                log_file.write("Pruefe ob preload.js geladen und AMS-Skript erfolgreich injiziert wurde...\n")
                log_file.flush()
                check_expr = """
                (() => {
                    if (typeof window.electronNative === 'undefined') return "Preload-Skript (window.electronNative) wurde nicht geladen.";
                    if (typeof window.electronNative.openDuplicateWindow !== 'function') return "Duplicate-Window-API fehlt.";
                    if (typeof window.electronNative.hubRequest !== 'function') return "Anti-Gravity-Hub-IPC fehlt.";
                    if (typeof window.electronNative.getProfileInfo !== 'function') return "Profil-Isolations-API fehlt.";
                    if (typeof window.electronUpdater?.getState !== 'function') return "Updater-State-API fehlt.";
                    const errPopup = document.getElementById('antigravity-injection-error-popup');
                    if (errPopup) {
                        const pre = errPopup.querySelector('pre');
                        return "AMS-Skript-Injektion fehlgeschlagen: " + (pre ? pre.textContent.trim() : "Unbekannter Fehler");
                    }
                    if (window.__antigravity_ams_loaded !== true) return "WAIT_AMS";
                    if (typeof window.getTaskPlan === 'undefined') return "WAIT_AMS";
                    if (typeof window.amsAntigravityHub?.getStatus !== 'function') return "WAIT_AMS_HUB";
                    const fileButton = Array.from(document.querySelectorAll('button')).find(
                        button => button.textContent?.trim() === 'File'
                    );
                    if (!fileButton) return "WAIT_UI";
                    return "OK";
                })()
                """

                check_res = "WAIT_AMS"
                for check_attempt in range(20):
                    await ws.send_json({
                        "id": 100 + check_attempt,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": check_expr,
                            "returnByValue": True
                        }
                    })

                    while True:
                        data = await recv_next(ws, log_file)
                        if data.get("id") == 100 + check_attempt:
                            check_res = data.get("result", {}).get("result", {}).get("value", "check_failed")
                            break

                    if check_res == "OK" or "AMS-Skript-Injektion" in check_res:
                        break

                    await asyncio.sleep(0.2)

                if check_res != "OK":
                    raise RuntimeError(f"UI-Injektion unvollstaendig oder fehlerhaft: {check_res}")

                log_file.write("Preload-Skript und AMS-Injektion erfolgreich verifiziert.\n")
                log_file.flush()

                # Restore chat navigation and auto-post status message to the last active conversation
                chat_to_restore = active_path
                if not chat_to_restore and target_chat_id:
                    chat_to_restore = f"/c/{target_chat_id}"

                if chat_to_restore:
                    log_file.write(f"Stelle letzten aktiven Chat wieder her: {chat_to_restore}...\n")
                    log_file.flush()
                    nav_expr = f"""
                    (() => {{
                        const targetPath = {json.dumps(chat_to_restore)};
                        const curPath = window.location.pathname + window.location.search;
                        if (curPath !== targetPath && !curPath.includes(targetPath)) {{
                            window.location.href = window.location.origin + targetPath;
                            return "NAVIGATING";
                        }}
                        return "ALREADY_THERE";
                    }})()
                    """
                    try:
                        await ws.send_json({
                            "id": 200,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": nav_expr,
                                "returnByValue": True
                            }
                        })
                        while True:
                            data = await recv_next(ws, log_file)
                            if data.get("id") == 200:
                                nav_status = data.get("result", {}).get("result", {}).get("value", "")
                                log_file.write(f"Navigation-Status: {nav_status}\n")
                                log_file.flush()
                                break

                        if nav_status == "NAVIGATING":
                            await asyncio.sleep(2.0)

                        # Wait for the chat input field to be available (up to 15 seconds)
                        log_file.write("Warte auf Chat-Eingabefeld zur Bestaetigungsnachricht...\n")
                        log_file.flush()
                        find_input_expr = """
                        (() => {
                            const input = document.querySelector('[role="combobox"][aria-label="Message input"]')
                                || document.querySelector('[role="combobox"]')
                                || document.querySelector('[contenteditable="true"]');
                            return Boolean(input);
                        })()
                        """
                        input_found = False
                        for attempt in range(30):
                            await ws.send_json({
                                "id": 210 + attempt,
                                "method": "Runtime.evaluate",
                                "params": {
                                    "expression": find_input_expr,
                                    "returnByValue": True
                                }
                            })
                            while True:
                                data = await recv_next(ws, log_file)
                                if data.get("id") == 210 + attempt:
                                    input_found = bool(data.get("result", {}).get("result", {}).get("value"))
                                    break
                            if input_found:
                                break
                            await asyncio.sleep(0.5)

                        if input_found:
                            log_file.write("Chat-Eingabefeld gefunden. Sende Bestaetigungsnachricht...\n")
                            log_file.flush()
                            post_msg = (
                                f"✨ Anti-Gravity wurde erfolgreich für Version {supported_upstream_version()} "
                                "gepatcht und neu gestartet. "
                                "Dieser Chat wurde automatisch wiederhergestellt."
                            )
                            post_script = f"""
                            (async () => {{
                                const text = {json.dumps(post_msg)};
                                if (window.__agBridge && typeof window.__agBridge.prepareAndSend === 'function') {{
                                    const res = await window.__agBridge.prepareAndSend(text);
                                    if (res && res.success) return "SENT_VIA_BRIDGE";
                                }}
                                const input = document.querySelector('[role="combobox"][aria-label="Message input"]')
                                    || document.querySelector('[role="combobox"]')
                                    || document.querySelector('[contenteditable="true"]');
                                if (!input) return "NO_INPUT";
                                input.focus();
                                const selection = window.getSelection();
                                const range = document.createRange();
                                range.selectNodeContents(input);
                                selection.removeAllRanges();
                                selection.addRange(range);
                                const deleteEvent = new InputEvent('beforeinput', {{
                                    inputType: 'deleteContentBackward',
                                    bubbles: true,
                                    cancelable: true,
                                    composed: true
                                }});
                                input.dispatchEvent(deleteEvent);
                                selection.collapseToStart();
                                try {{
                                    const dt = new DataTransfer();
                                    dt.setData('text/plain', text);
                                    const pasteEvent = new ClipboardEvent('paste', {{
                                        clipboardData: dt,
                                        bubbles: true,
                                        cancelable: true,
                                        composed: true
                                    }});
                                    input.dispatchEvent(pasteEvent);
                                }} catch (e) {{
                                    const insertEvent = new InputEvent('beforeinput', {{
                                        inputType: 'insertText',
                                        data: text,
                                        bubbles: true,
                                        cancelable: true,
                                        composed: true
                                    }});
                                    input.dispatchEvent(insertEvent);
                                }}
                                const findSendButton = () => Array.from(document.querySelectorAll('button')).find(b => {{
                                    const label = (b.getAttribute('aria-label') || '').toLowerCase();
                                    return label.includes('send') && b.offsetParent !== null && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
                                }});
                                let btn = null;
                                for (let i = 0; i < 40 && !btn; i++) {{
                                    await new Promise(r => setTimeout(r, 250));
                                    btn = findSendButton();
                                }}
                                if (btn) {{
                                    btn.click();
                                    return "SENT_VIA_BUTTON";
                                }}
                                input.focus();
                                return "NEEDS_ENTER";
                            }})()
                            """
                            await ws.send_json({
                                "id": 250,
                                "method": "Runtime.evaluate",
                                "params": {
                                    "expression": post_script,
                                    "awaitPromise": True,
                                    "returnByValue": True
                                }
                            })
                            while True:
                                data = await recv_next(ws, log_file)
                                if data.get("id") == 250:
                                    post_res = data.get("result", {}).get("result", {}).get("value", "")
                                    log_file.write(f"Bestaetigungsnachricht-Ergebnis: {post_res}\n")
                                    log_file.flush()
                                    break
                            if post_res == "NEEDS_ENTER":
                                for offset, event_type in enumerate(("rawKeyDown", "keyUp")):
                                    await ws.send_json({
                                        "id": 251 + offset,
                                        "method": "Input.dispatchKeyEvent",
                                        "params": {
                                            "type": event_type, "key": "Enter", "code": "Enter",
                                            "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                                            "text": "\r" if event_type == "rawKeyDown" else "",
                                        },
                                    })
                                    while True:
                                        data = await recv_next(ws, log_file)
                                        if data.get("id") == 251 + offset:
                                            break
                                log_file.write("Bestaetigungsnachricht-Ergebnis: SENT_VIA_CDP_ENTER\n")
                                log_file.flush()
                        else:
                            log_file.write("Warnung: Chat-Eingabefeld innerhalb des Zeitlimits nicht gefunden.\n")
                            log_file.flush()
                    except Exception as chat_restore_err:
                        log_file.write(f"Warnung bei Chat-Wiederherstellung: {chat_restore_err}\n")
                        log_file.flush()

                log_file.write("Runtime-Verifikation abgeschlossen.\n")
                log_file.flush()
                return {"injection_verified": True, "target_url": backend_url}

    except Exception as e:
        log_file.write(f"Fehler bei WebSocket/CDP-Verbindung: {e}\n")
        log_file.write(traceback.format_exc())
        log_file.flush()
        raise e

def get_last_active_session_id():
    # 1. Read the app-owned last path without mutating corrupt user data.
    try:
        storage_path = resolve_user_data_dir() / "app_storage.json"
        if storage_path.exists():
            content = storage_path.read_text(encoding="utf-8")
            try:
                storage_data = json.loads(content)
            except Exception:
                storage_data = {}
            last_path = storage_data.get("antigravity_last_chat_path", "")
            if last_path:
                match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", last_path, re.IGNORECASE)
                if match:
                    return match.group(1)
    except Exception:
        pass

    # 2. Fallback: Juengste modifizierte .db-Datei im conversations-Ordner ermitteln
    try:
        conv_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
        if conv_dir.exists():
            db_files = list(conv_dir.glob("*.db"))
            if db_files:
                # Sortiere nach modification time (juengste zuerst)
                db_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                for db_file in db_files:
                    name_without_ext = db_file.stem
                    # Pruefen ob es eine gueltige UUID ist (Chat-Datenbank)
                    match = re.match(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", name_without_ext, re.IGNORECASE)
                    if match:
                        return name_without_ext
    except Exception:
        pass
    return None

def get_current_active_path(port_file, log_file):
    try:
        if not port_file.exists():
            log_file.write("No active DevTools port file found before shutdown.\n")
            log_file.flush()
            return None

        lines = port_file.read_text(encoding="utf-8").splitlines()
        port = int(lines[0].strip())

        # Query DevTools targets
        url = f"http://127.0.0.1:{port}/json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            targets = json.loads(resp.read().decode())

        # Find active page target
        for t in targets:
            if t.get("type") == "page":
                target_url = t.get("url", "")
                if target_url.startswith("devtools://") or target_url.startswith("data:"):
                    continue
                if target_url.startswith("https://127.0.0.1:") or target_url.startswith("http://localhost:"):
                    parsed = urllib.parse.urlparse(target_url)
                    path = parsed.path
                    if parsed.query:
                        path += "?" + parsed.query
                    if path and path != "/" and path != "":
                        return path
    except Exception as e:
        log_file.write(f"Warning during get_current_active_path: {e}\n")
        log_file.flush()
    return None

def write_active_path_to_storage(path, log_file):
    try:
        if not path:
            return
        storage_path = resolve_user_data_dir() / "app_storage.json"
        storage_data = {}
        if storage_path.exists():
            try:
                storage_data = json.loads(storage_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        storage_data["antigravity_last_chat_path"] = path
        storage_path.write_text(json.dumps(storage_data, indent=2), encoding="utf-8")
        log_file.write(f"Successfully saved active path '{path}' to app_storage.json after shutdown.\n")
        log_file.flush()
    except Exception as e:
        log_file.write(f"Warning during write_active_path_to_storage: {e}\n")
        log_file.flush()

def validate_js_syntax(file_path, log_file):
    log_file.write(f"Pruefe Syntax von {file_path.name}...\n")
    log_file.flush()
    try:
        result = subprocess.run(
            ["node", "-c", str(file_path)],
            capture_output=True,
            text=True,
            creationflags=WINDOW_FLAGS,
        )
        if result.returncode != 0:
            log_file.write(f"SYNTAX-FEHLER in {file_path.name}:\n{result.stderr}\n")
            log_file.flush()
            return False
        log_file.write(f"{file_path.name} ist syntaktisch korrekt.\n")
        log_file.flush()
        return True
    except Exception as e:
        log_file.write(
            f"SYNTAX-PRUEFUNG NICHT AUSFUEHRBAR fuer {file_path.name}: {e}\n"
        )
        log_file.flush()
        return False


def install_staged_unpacked(staged_unpacked, app_unpacked_path, log_file):
    """Install unpacked directory with retries for Windows locks."""
    for attempt in range(1, 6):
        try:
            if app_unpacked_path.exists():
                shutil.rmtree(app_unpacked_path)
            shutil.copytree(staged_unpacked, app_unpacked_path)
            log_file.write(f"Unpacked-Verzeichnis erfolgreich installiert (Versuch {attempt}).\n")
            log_file.flush()
            return
        except Exception as pe:
            log_file.write(f"Unpacked-Installation Versuch {attempt} fehlgeschlagen: {pe}. Warte 1s...\n")
            log_file.flush()
            time.sleep(1.0)
            if attempt == 5:
                raise

def install_staged_asar(staged_asar, app_asar_path, log_file):
    """Install staged ASAR over app.asar with retries and copy2 fallback for WinError 5."""
    last_err = None
    for attempt in range(1, 6):
        try:
            os.replace(staged_asar, app_asar_path)
            log_file.write(f"ASAR via os.replace installiert (Versuch {attempt}).\n")
            log_file.flush()
            return
        except PermissionError as pe:
            last_err = pe
            log_file.write(f"os.replace Versuch {attempt} fehlgeschlagen ({pe}). Warte 1s...\n")
            log_file.flush()
            time.sleep(1.0)
        except Exception as e:
            last_err = e
            break

    log_file.write(f"os.replace fehlgeschlagen ({last_err}), wechsle zu shutil.copy2 Fallback...\n")
    log_file.flush()
    try:
        shutil.copy2(staged_asar, app_asar_path)
        try:
            staged_asar.unlink(missing_ok=True)
        except Exception:
            pass
        log_file.write("ASAR erfolgreich via shutil.copy2 Fallback installiert.\n")
        log_file.flush()
    except Exception as copy_err:
        log_file.write(f"shutil.copy2 Fallback ebenfalls fehlgeschlagen: {copy_err}\n")
        log_file.flush()
        raise last_err or copy_err

def remove_staging_tree(path, resources_dir):
    """Remove only the dedicated repack staging directory."""
    resolved_path = Path(path).resolve()
    resolved_resources = Path(resources_dir).resolve()
    if resolved_path.parent != resolved_resources or resolved_path.name != "repack-staging":
        raise RuntimeError(f"Refusing to remove unsafe staging path: {resolved_path}")
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def ensure_complete_unpacked_tree(app_unpacked_path, backup_unpacked_path, resources_dir, log_file):
    """Repair a partial external ASAR tree from its verified matching backup."""
    required_relative = Path(
        "node_modules/chrome-devtools-mcp/build/src/bin/check-latest-version.js"
    )

    def tree_state(root):
        root = Path(root)
        count = sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0
        return count, (root / required_relative).is_file()

    current_count, current_required = tree_state(app_unpacked_path)
    log_file.write(
        f"External ASAR tree: {current_count} files; required file: {current_required}.\n"
    )
    log_file.flush()
    if current_count >= 250 and current_required:
        return

    backup_count, backup_required = tree_state(backup_unpacked_path)
    log_file.write(
        f"External ASAR backup: {backup_count} files; required file: {backup_required}.\n"
    )
    log_file.flush()
    if backup_count < 250 or not backup_required:
        raise RuntimeError(
            "The external ASAR tree is incomplete and no complete matching backup exists."
        )

    resolved_resources = Path(resources_dir).resolve()
    if (
        Path(app_unpacked_path).resolve().parent != resolved_resources
        or Path(app_unpacked_path).name != "app.asar.unpacked"
        or Path(backup_unpacked_path).resolve().parent != resolved_resources
        or Path(backup_unpacked_path).name != "app.asar.unpacked.bak"
    ):
        raise RuntimeError("Refusing to repair unsafe external ASAR paths.")

    shutil.copytree(backup_unpacked_path, app_unpacked_path, dirs_exist_ok=True)
    repaired_count, repaired_required = tree_state(app_unpacked_path)
    if repaired_count < 250 or not repaired_required:
        raise RuntimeError("The external ASAR tree remained incomplete after repair.")
    log_file.write(
        f"External ASAR tree repaired from matching backup: {repaired_count} files.\n"
    )
    log_file.flush()

def validate_extracted_app(root_path, log_file, label):
    """Reject incomplete ASAR extractions before the running app is touched."""
    root = Path(root_path)
    required = [
        root / "package.json",
        root / "dist" / "main.js",
        root / "dist" / "preload.js",
        root / "node_modules" / "chrome-devtools-mcp" / "package.json",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    file_count = sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0
    log_file.write(
        f"{label}: {file_count} Dateien; fehlende Pflichtdateien: {missing or 'keine'}\n"
    )
    log_file.flush()
    if missing or file_count < 500:
        raise RuntimeError(
            f"{label} ist unvollstaendig ({file_count} Dateien, missing={missing})."
        )
    return file_count


def validate_upstream_contract(root_path, contract_path, supported_version, log_file):
    """Verify the exact pristine upstream files that the overlay replaces."""
    root = Path(root_path).resolve()
    manifest_path = Path(contract_path)
    if not manifest_path.is_file():
        raise RuntimeError(f"Upstream compatibility manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError(f"Upstream compatibility manifest is invalid: {error}") from error

    manifest_version = str(manifest.get("version", "")).strip().lstrip("v")
    expected_version = str(supported_version or "").strip().lstrip("v")
    package_data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    upstream_version = str(package_data.get("version", "")).strip().lstrip("v")
    if not expected_version or manifest_version != expected_version:
        raise RuntimeError(
            "Upstream compatibility manifest version does not match "
            f"SUPPORTED_UPSTREAM_VERSION ({manifest_version or 'unknown'} != "
            f"{expected_version or 'unknown'})."
        )
    if upstream_version != expected_version:
        raise RuntimeError(
            f"Unsupported upstream version ({upstream_version or 'unknown'} != {expected_version})."
        )

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("Upstream compatibility manifest contains no file hashes.")
    for relative_name, expected_hash in sorted(files.items()):
        if not isinstance(relative_name, str) or not isinstance(expected_hash, str):
            raise RuntimeError("Upstream compatibility manifest has an invalid file entry.")
        candidate = (root / relative_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"Upstream contract path escaped extraction root: {relative_name}") from error
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError(f"Upstream contract file is missing or unsafe: {relative_name}")
        digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if actual_hash.lower() != expected_hash.strip().lower():
            raise RuntimeError(f"Upstream hash mismatch: {relative_name}")

    log_file.write(
        f"Upstream-Vertrag bestaetigt: {upstream_version}; {len(files)} Basisdateien.\n"
    )
    log_file.flush()
    return upstream_version


UPSTREAM_BASELINE_DIRNAME = "upstream_baselines"
UPSTREAM_BASELINE_KEEP = 3


def _version_key(name):
    return tuple(int(part) if part.isdigit() else 0 for part in str(name).split("."))


def save_upstream_baseline(root_path, contract_path, supported_version, log_file, baseline_dir=None):
    """Snapshot the pristine upstream dist of a supported version (best effort, never fatal).

    Only a byte-exact upstream base is stored: the installed archive may already be the
    verified modifier build, whose dist contains overlay files and must not become a
    reference for future upstream diffs.
    """
    import io

    target_root = Path(baseline_dir) if baseline_dir else SCRATCH_DIR / UPSTREAM_BASELINE_DIRNAME
    try:
        version = validate_upstream_contract(root_path, contract_path, supported_version, io.StringIO())
    except Exception:
        log_file.write("Upstream-Baseline uebersprungen: Basis ist bereits modifiziert oder nicht freigegeben.\n")
        log_file.flush()
        return None
    try:
        if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
            raise RuntimeError(f"unexpected version format: {version!r}")
        destination = target_root / version
        if (destination / "baseline.json").is_file():
            return destination
        source_dist = Path(root_path) / "dist"
        temporary = target_root / f".{version}.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(
            source_dist,
            temporary / "dist",
            ignore=shutil.ignore_patterns("*.test.js", "__mocks__", "test"),
        )
        shutil.copy2(Path(root_path) / "package.json", temporary / "package.json")
        hashes = {
            path.relative_to(temporary).as_posix(): sha256_file(path)
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        }
        (temporary / "baseline.json").write_text(
            json.dumps({"version": version, "created_at": time.time(), "files": hashes}, indent=2),
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
        stored = sorted(
            (item for item in target_root.iterdir() if item.is_dir() and not item.name.startswith(".")),
            key=lambda item: _version_key(item.name),
            reverse=True,
        )
        for old in stored[UPSTREAM_BASELINE_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
        log_file.write(f"Upstream-Baseline {version} gespeichert: {destination}\n")
        log_file.flush()
        return destination
    except Exception as baseline_error:
        log_file.write(f"Upstream-Baseline konnte nicht gespeichert werden (nicht kritisch): {baseline_error}\n")
        log_file.flush()
        return None


def write_verified_installation_record(
    app_asar_path,
    contract_path,
    upstream_version,
    record_path=VERIFIED_INSTALLATION_FILE,
    source_signature=None,
):
    """Atomically bind a runtime-verified archive to its upstream contract."""
    record_file = Path(record_path)
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "upstream_version": str(upstream_version).strip().lstrip("v"),
        "upstream_contract_sha256": sha256_file(contract_path),
        "installed_asar_sha256": sha256_file(app_asar_path),
        "verified_at": time.time(),
        "profile_contract_version": 2,
    }
    if source_signature is not None:
        record["source_signature"] = source_signature
    temp_file = record_file.with_suffix(record_file.suffix + ".tmp")
    temp_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temp_file, record_file)
    return record


def validate_repack_base(
    extracted_root,
    app_asar_path,
    contract_path,
    supported_version,
    record_path,
    log_file,
):
    """Accept pristine upstream or the exact last runtime-verified modifier archive."""
    try:
        return validate_upstream_contract(
            extracted_root,
            contract_path,
            supported_version,
            log_file,
        )
    except Exception as pristine_error:
        expected_version = str(supported_version or "").strip().lstrip("v")
        package_data = json.loads(
            (Path(extracted_root) / "package.json").read_text(encoding="utf-8")
        )
        upstream_version = str(package_data.get("version", "")).strip().lstrip("v")
        if not expected_version or upstream_version != expected_version:
            raise RuntimeError(str(pristine_error)) from pristine_error
        try:
            record = json.loads(Path(record_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as record_error:
            raise RuntimeError(
                f"{pristine_error}; verified installation record is unavailable: {record_error}"
            ) from pristine_error
        if str(record.get("upstream_version", "")).strip().lstrip("v") != expected_version:
            raise RuntimeError("verified installation version mismatch") from pristine_error
        if str(record.get("upstream_contract_sha256", "")).lower() != sha256_file(
            contract_path
        ).lower():
            raise RuntimeError("verified installation contract mismatch") from pristine_error
        if str(record.get("installed_asar_sha256", "")).lower() != sha256_file(
            app_asar_path
        ).lower():
            raise RuntimeError("verified installation hash mismatch") from pristine_error
        log_file.write(
            f"Bereits verifizierte Modifier-Basis bestaetigt: {upstream_version}.\n"
        )
        log_file.flush()
        return upstream_version


def copy_overlay_sources(config_src_dir, dest_dist_dir, log_file):
    """Copy the complete JavaScript overlay or raise before packing anything."""
    source_root = Path(config_src_dir).resolve()
    destination_root = Path(dest_dist_dir).resolve()
    javascript_files = sorted(
        (
            path
            for path in source_root.rglob("*.js")
            if path.name != "preload.js.build.tmp.js"
        ),
        key=lambda path: str(path.relative_to(source_root)).lower(),
    )
    if not javascript_files:
        raise RuntimeError(f"No JavaScript overlay sources found under {source_root}.")

    copied = 0
    for source_file in javascript_files:
        if source_file.is_symlink() or not source_file.is_file():
            raise RuntimeError(f"Unsafe or missing overlay source: {source_file}")
        relative_path = source_file.relative_to(source_root)
        destination_file = destination_root / relative_path
        try:
            destination_file.resolve().relative_to(destination_root)
        except ValueError as error:
            raise RuntimeError(f"Overlay destination escaped dist: {relative_path}") from error
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied += 1
        log_file.write(f"Kopiert: {relative_path}\n")
    log_file.write(f"Overlay vollstaendig kopiert: {copied} JavaScript-Dateien.\n")
    log_file.flush()
    return copied


def run_asar(command_args, log_file, action):
    """Run the locally available ASAR CLI without shell interpolation, falling back to @electron/asar."""
    result = subprocess.run(
        ["npx.cmd", "--no-install", "asar", *command_args],
        capture_output=True,
        text=True,
        shell=False,
        creationflags=WINDOW_FLAGS,
    )
    if result.returncode != 0:
        log_file.write(f"{action}: lokales 'asar' nicht im npx-Cache, nutze '@electron/asar' Fallback...\n")
        log_file.flush()
        result = subprocess.run(
            ["npx.cmd", "--yes", "@electron/asar", *command_args],
            capture_output=True,
            text=True,
            shell=False,
            creationflags=WINDOW_FLAGS,
        )
    log_file.write(f"{action} returncode: {result.returncode}\n")
    if result.stdout.strip():
        log_file.write(f"{action} stdout: {result.stdout.strip()}\n")
    if result.stderr.strip():
        log_file.write(f"{action} stderr: {result.stderr.strip()}\n")
    log_file.flush()
    if result.returncode != 0:
        raise RuntimeError(f"{action} fehlgeschlagen (Exit {result.returncode}).")
    return result

def get_workspace_path(conversation_id, log_file):
    if not conversation_id:
        return None
    db_path = Path.home() / ".gemini" / "antigravity" / "conversations" / f"{conversation_id}.db"
    if not db_path.exists():
        return None
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT data FROM trajectory_metadata_blob WHERE id = 'main';").fetchone()
        if not row:
            return None
        d = row[0]
        idx = d.find(b'file:///')
        if idx == -1:
            return None
        end = idx
        while end < len(d) and 32 <= d[end] <= 126:
            end += 1
        uri = d[idx:end].decode('utf-8')
        if uri:
            import urllib.parse
            parsed_path = urllib.parse.unquote(uri.replace('file:///', ''))
            if parsed_path.startswith('/') and len(parsed_path) > 2 and parsed_path[2] == ':':
                parsed_path = parsed_path[1:]
            path_obj = Path(parsed_path)
            if path_obj.exists():
                log_file.write(f"Workspace-Pfad aus DB ermittelt: {path_obj}\n")
                log_file.flush()
                return path_obj
    except Exception as e:
        log_file.write(f"Fehler beim Ermitteln des Workspace-Pfads: {e}\n")
        log_file.flush()
    return None

def run_repack():
    log_path = SCRATCH_DIR / "repack_and_restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resources_dir = None
    staging_root = None
    restart_original_on_error = False

    # 0. Fehler-Datei loeschen, falls vorhanden
    err_file = SCRATCH_DIR / "repack_error.txt"
    if err_file.exists():
        try:
            err_file.unlink()
        except Exception:
            pass

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("--- LOG-START ---\n")
        log_file.write("repack_and_restart.py gestartet.\n")
        log_file.flush()
        write_status(SCRATCH_DIR, "running", "preflight")

        try:
            repack_trigger_id = claim_trigger_chat_id(log_file)

            # NodeJS-Pfad zur PATH-Variable hinzufuegen, damit node/npx verfuegbar sind
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            node_dir = str(Path(program_files) / "nodejs")
            if Path(node_dir).is_dir() and node_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = node_dir + os.path.pathsep + os.environ.get("PATH", "")

            # 1. Letzte aktive Session-ID und Workspace-Pfad ermitteln
            target_chat_id = get_last_active_session_id()

            # 2. Pfade definieren
            install_dir, resources_dir, app_path = resolve_install_paths()
            app_asar_path = resources_dir / "app.asar"
            if not app_path.is_file():
                raise RuntimeError(f"Antigravity executable not found: {app_path}")
            if not app_asar_path.is_file():
                raise RuntimeError(f"Antigravity app.asar not found: {app_asar_path}")
            log_file.write(f"Antigravity-Installation: {install_dir}\n")
            log_file.write(f"Resources: {resources_dir}\n")
            log_file.flush()
            app_unpacked_path = Path(str(app_asar_path) + ".unpacked")
            backup_unpacked_path = Path(str(app_unpacked_path) + ".bak")
            staging_root = resources_dir / "repack-staging"
            app_extracted = staging_root / "extracted"
            packed_dir = staging_root / "packed"
            validation_dir = staging_root / "validation"

            # Default to the src directory beside the script that is actually running.
            skill_root = Path(__file__).resolve().parent.parent
            config_src_dir = skill_root / "src"
            log_file.write(f"Nutze Skill-Quelle neben dem aktiven Skript: {config_src_dir}\n")
            log_file.flush()

            # Auto-build preload.js if modular build script exists
            versions = version_info(app_asar_path, config_src_dir.parent)
            if versions["installed_version"] != versions["supported_version"]:
                message = unsupported_message(versions)
                log_file.write(message + "\n")
                log_file.flush()
                err_file.write_text(message, encoding="utf-8")
                write_status(SCRATCH_DIR, "blocked", "preflight", kind="unsupported_version", message=message, **versions)
                return 1
            write_status(SCRATCH_DIR, "running", "build", **versions)
            captured_source_signature = source_signature()
            build_script = config_src_dir.parent / "scripts" / "build_preload.py"
            if build_script.exists():
                log_file.write(f"Führe Build-Skript fuer preload.js aus: {build_script}\n")
                log_file.flush()
                import subprocess
                res = subprocess.run(
                    [sys.executable, str(build_script)],
                    capture_output=True,
                    text=True,
                    creationflags=WINDOW_FLAGS,
                )
                if res.returncode != 0:
                    log_file.write(f"Fehler beim Kompilieren von preload.js:\n{res.stderr}\n{res.stdout}\n")
                    log_file.flush()
                    err_file.write_text("Build von preload.js fehlgeschlagen! Siehe repack_and_restart.log fuer Details.", encoding="utf-8")
                    return 1
                else:
                    log_file.write("preload.js erfolgreich kompiliert.\n")
                    log_file.flush()

            write_status(SCRATCH_DIR, "running", "validate")
            ensure_complete_unpacked_tree(
                app_unpacked_path,
                backup_unpacked_path,
                resources_dir,
                log_file,
            )

            # Always extract a complete fresh base. Never reuse resources/app-extracted.
            remove_staging_tree(staging_root, resources_dir)
            app_extracted.mkdir(parents=True, exist_ok=True)
            packed_dir.mkdir(parents=True, exist_ok=True)
            log_file.write(f"Extrahiere frische ASAR-Basis nach {app_extracted}...\n")
            log_file.flush()
            run_asar(
                ["extract", str(app_asar_path), str(app_extracted)],
                log_file,
                "ASAR-Basisextraktion",
            )
            validate_extracted_app(app_extracted, log_file, "ASAR-Basis")

            supported_version_path = config_src_dir.parent / "SUPPORTED_UPSTREAM_VERSION"
            if not supported_version_path.is_file():
                message = (
                    "Repack abgebrochen: SUPPORTED_UPSTREAM_VERSION fehlt. "
                    "Die laufende Installation wurde nicht veraendert."
                )
                log_file.write(message + "\n")
                log_file.flush()
                err_file.write_text(message, encoding="utf-8")
                return 1
            supported_version = supported_version_path.read_text(encoding="utf-8").strip().lstrip("v")
            compatibility_manifest_path = config_src_dir.parent / "UPSTREAM_COMPATIBILITY.json"
            try:
                upstream_version = validate_repack_base(
                    app_extracted,
                    app_asar_path,
                    compatibility_manifest_path,
                    supported_version,
                    VERIFIED_INSTALLATION_FILE,
                    log_file,
                )
            except Exception as compatibility_error:
                message = (
                    "Repack abgebrochen: Upstream-Kompatibilitaet ist nicht bestaetigt "
                    f"({compatibility_error}). "
                    "Die laufende Installation wurde nicht veraendert."
                )
                log_file.write(message + "\n")
                log_file.flush()
                err_file.write_text(message, encoding="utf-8")
                return 1
            log_file.write(f"Upstream-Kompatibilitaet bestaetigt: {upstream_version}.\n")
            log_file.flush()
            # Must run before the overlay is copied into the staging dist.
            save_upstream_baseline(app_extracted, compatibility_manifest_path, supported_version, log_file)

            dest_dist_dir = app_extracted / "dist"

            # 2. Praeventive Syntax-Pruefung der geaenderten Dateien
            log_file.write("Starte praeventive JS-Syntax-Pruefung...\n")
            log_file.flush()

            # Validate top-level and modular UI JavaScript recursively.
            js_files_to_check = list(config_src_dir.rglob("*.js"))
            if not js_files_to_check:
                js_files_to_check = [
                    config_src_dir / name
                    for name in ["preload.js", "ipcHandlers.js", "utils.js", "main.js"]
                ]

            syntax_ok = True
            for fpath in js_files_to_check:
                if fpath.exists():
                    if not validate_js_syntax(fpath, log_file):
                        syntax_ok = False
                else:
                    # If absent in the skill source, validate the extracted base copy.
                    fpath_dist = dest_dist_dir / fpath.name
                    if fpath_dist.exists() and not validate_js_syntax(fpath_dist, log_file):
                        syntax_ok = False

            if not syntax_ok:
                log_file.write("ABBRUCH: Syntax-Validierung fehlgeschlagen! Anwendung wird NICHT beendet.\n")
                log_file.flush()
                err_file.write_text("Syntax-Validierung in den JS-Dateien fehlgeschlagen! Siehe repack_and_restart.log fuer Details.", encoding="utf-8")
                return 1

            # Apply the overlay to staging before the running app is touched.
            try:
                log_file.write("Kopiere Modifier-Overlay in die frische ASAR-Staging-Basis...\n")
                log_file.flush()
                copy_overlay_sources(config_src_dir, dest_dist_dir, log_file)
            except Exception as overlay_error:
                message = (
                    "Overlay-Kopie fehlgeschlagen; App wurde nicht beendet und ASAR nicht gepackt: "
                    f"{overlay_error}"
                )
                log_file.write(message + "\n")
                log_file.write(traceback.format_exc())
                log_file.flush()
                err_file.write_text(message, encoding="utf-8")
                try:
                    remove_staging_tree(staging_root, resources_dir)
                except Exception as cleanup_error:
                    log_file.write(f"Staging-Cleanup nach Overlay-Fehler fehlgeschlagen: {cleanup_error}\n")
                    log_file.flush()
                return 1

            # 3. Warten, damit der Agent sich verabschieden kann
            write_status(SCRATCH_DIR, "running", "save_state")
            log_file.write("Warte 2 Sekunden...\n")
            log_file.flush()
            time.sleep(2)

            # DevToolsActivePort Pfad definieren
            user_data_dir = resolve_user_data_dir()
            port_file = user_data_dir / "DevToolsActivePort"

            # 3b. Draft aus app_storage.json in die Windows-Zwischenablage kopieren (Sicherheits-Backup)
            try:
                storage_path = user_data_dir / "app_storage.json"
                if storage_path.exists():
                    log_file.write("Versuche, aktuellen Draft aus app_storage.json in die Zwischenablage zu kopieren...\n")
                    log_file.flush()
                    storage_data = json.loads(storage_path.read_text(encoding="utf-8"))
                    draft_text = storage_data.get("antigravity_message_input_draft", "")
                    if draft_text and draft_text.strip():
                        clipboard_command = (
                            "[Console]::InputEncoding = [Text.UTF8Encoding]::new($false); "
                            "Set-Clipboard -Value ([Console]::In.ReadToEnd())"
                        )
                        clipboard_result = subprocess.run(
                            ["powershell", "-NoProfile", "-Command", clipboard_command],
                            input=draft_text.encode("utf-8"),
                            capture_output=True,
                            timeout=10,
                            creationflags=WINDOW_FLAGS,
                        )
                        if clipboard_result.returncode != 0:
                            details = clipboard_result.stderr.decode("utf-8", errors="replace").strip()
                            raise RuntimeError(
                                f"Set-Clipboard failed (exit={clipboard_result.returncode}): {details}"
                            )
                        log_file.write("Draft erfolgreich via PowerShell/Set-Clipboard in die Zwischenablage kopiert.\n")
                    else:
                        log_file.write("Kein aktiver Draft vorhanden oder leer.\n")
                    log_file.flush()
            except Exception as clipboard_err:
                log_file.write(f"Warnung beim Sichern des Drafts in das Clipboard: {clipboard_err}\n")
                log_file.flush()

            # 3c. Aktuellen Pfad (Chat/Einstellungen etc.) via DevTools ermitteln und sichern
            active_path = get_current_active_path(port_file, log_file)
            if not active_path and (repack_trigger_id or target_chat_id):
                active_path = f"/c/{repack_trigger_id or target_chat_id}"
                log_file.write(f"Aktiver Pfad auf Chat-ID zurueckgefallen: {active_path}\n")
                log_file.flush()

            # 4. Stop only the exact selected Antigravity installation tree.
            write_status(SCRATCH_DIR, "running", "stop")
            restart_original_on_error = True
            log_file.write("Beende Prozesse der ausgewaehlten Antigravity-Installation...\n")
            log_file.flush()
            stop_install_process_tree(app_path, log_file)
            time.sleep(1)

            # Aktuellen Pfad erst JETZT schreiben, da die App sonst beim Beenden die Datei ueberschreiben kann
            if active_path:
                write_active_path_to_storage(active_path, log_file)

            # DevToolsActivePort loeschen, falls vorhanden, damit wir nicht den alten Port auslesen
            if port_file.exists():
                log_file.write("Loesche alte DevToolsActivePort-Datei...\n")
                log_file.flush()
                try:
                    port_file.unlink()
                except Exception as e:
                    log_file.write(f"Konnte DevToolsActivePort nicht loeschen: {e}\n")
                    log_file.flush()

            write_status(SCRATCH_DIR, "running", "pack")
            # 6. Define archive and unpacked backups for atomic rollback.
            backup_asar_path = app_asar_path.with_suffix(".asar.bak")
            app_unpacked_path = Path(str(app_asar_path) + ".unpacked")
            backup_unpacked_path = Path(str(app_unpacked_path) + ".bak")

            # 7. Pack into staging, validate, then install.
            # The packing transaction below owns rollback from this point onward.
            restart_original_on_error = False
            log_file.write(f"Packe app.asar... PATH: {os.environ.get('PATH')}\n")
            log_file.flush()

            try:
                staged_asar = packed_dir / "app.asar"
                run_asar(
                    [
                        "pack",
                        "--unpack-dir",
                        "node_modules/chrome-devtools-mcp",
                        str(app_extracted),
                        str(staged_asar),
                    ],
                    log_file,
                    "ASAR-Staging-Pack",
                )
                staged_unpacked = Path(str(staged_asar) + ".unpacked")
                staged_unpacked_count = (
                    sum(1 for path in staged_unpacked.rglob("*") if path.is_file())
                    if staged_unpacked.exists()
                    else 0
                )
                log_file.write(
                    f"Staging-Archiv: {staged_asar.stat().st_size} Bytes; "
                    f"unpacked files: {staged_unpacked_count}\n"
                )
                log_file.flush()
                if staged_asar.stat().st_size < 1_000_000 or staged_unpacked_count < 250:
                    raise RuntimeError(
                        "Das gepackte Archiv hat nicht die erwartete vollstaendige Struktur."
                    )

                validation_dir.mkdir(parents=True, exist_ok=True)
                run_asar(
                    ["extract", str(staged_asar), str(validation_dir)],
                    log_file,
                    "ASAR-Staging-Validierung",
                )
                validate_extracted_app(validation_dir, log_file, "Gepackte ASAR")

                write_status(SCRATCH_DIR, "running", "install")
                shutil.copy2(app_asar_path, backup_asar_path)
                log_file.write("Backup von app.asar erstellt.\n")
                if backup_unpacked_path.exists():
                    if (
                        backup_unpacked_path.resolve().parent != resources_dir.resolve()
                        or backup_unpacked_path.name != "app.asar.unpacked.bak"
                    ):
                        raise RuntimeError(
                            f"Unsafe unpacked backup path: {backup_unpacked_path}"
                        )
                    shutil.rmtree(backup_unpacked_path)
                shutil.copytree(app_unpacked_path, backup_unpacked_path)
                log_file.write("Backup von app.asar.unpacked erstellt.\n")
                log_file.flush()

                if (
                    app_unpacked_path.resolve().parent != resources_dir.resolve()
                    or app_unpacked_path.name != "app.asar.unpacked"
                ):
                    raise RuntimeError(f"Unsafe unpacked install path: {app_unpacked_path}")
                install_staged_unpacked(staged_unpacked, app_unpacked_path, log_file)
                install_staged_asar(staged_asar, app_asar_path, log_file)
                log_file.write("Validiertes ASAR und unpacked-Baum installiert.\n")
                log_file.flush()
                remove_staging_tree(staging_root, resources_dir)
            except Exception as pack_error:
                log_file.write(f"Packen/Validieren fehlgeschlagen: {pack_error}\n")
                log_file.write(traceback.format_exc())
                log_file.flush()
                if backup_asar_path.exists():
                    try:
                        shutil.copy2(backup_asar_path, app_asar_path)
                        log_file.write("ASAR-Backup erfolgreich wiederhergestellt.\n")
                    except Exception as restore_err:
                        log_file.write(f"FEHLER beim Wiederherstellen des ASAR-Backups: {restore_err}\n")
                if backup_unpacked_path.exists():
                    try:
                        if app_unpacked_path.exists():
                            shutil.rmtree(app_unpacked_path)
                        shutil.copytree(backup_unpacked_path, app_unpacked_path)
                        log_file.write("Unpacked-Backup erfolgreich wiederhergestellt.\n")
                    except Exception as restore_err:
                        log_file.write(
                            f"FEHLER beim Wiederherstellen des unpacked-Backups: {restore_err}\n"
                        )
                log_file.flush()
                subprocess.Popen(
                    [str(app_path)],
                    env=application_launch_environment(),
                    close_fds=True,
                    creationflags=DETACHED_FLAGS,
                )
                err_file.write_text(
                    f"Packen/Validieren fehlgeschlagen: {pack_error}. Vorherige App wurde wiederhergestellt.",
                    encoding="utf-8",
                )
                return 1

            verification_chat_id = repack_trigger_id or target_chat_id
            log_file.write(f"Bevorzugter Chat fuer read-only Verifikation: {verification_chat_id}\n")
            log_file.flush()

            # 8. App neu starten
            write_status(SCRATCH_DIR, "running", "start")
            log_file.write(f"Starte App neu: {app_path}\n")
            log_file.flush()

            app_env = application_launch_environment()
            if repack_trigger_id and repack_trigger_id != target_chat_id:
                app_env["REPACK_TRIGGER_CHAT_ID"] = repack_trigger_id
                log_file.write(f"Setting env REPACK_TRIGGER_CHAT_ID={repack_trigger_id} to open a second window.\n")
            else:
                log_file.write("Trigger-Chat entspricht dem letzten User-Chat. Kein zweites Fenster noetig.\n")
            log_file.flush()

            subprocess.Popen(
                [str(app_path)],
                env=app_env,
                close_fds=True,
                creationflags=DETACHED_FLAGS,
            )
            log_file.write("Startbefehl abgesetzt. Starte Preload-Verifikation...\n")
            log_file.flush()
            write_status(SCRATCH_DIR, "running", "verify")

            try:
                asyncio.run(
                    verify_runtime_after_restart(
                        port_file,
                        app_path,
                        log_file,
                        verification_chat_id,
                        active_path=active_path,
                    )
                )
                log_file.write("App-Start und Preload-Pruefung erfolgreich abgeschlossen.\n")
                log_file.flush()

                write_verified_installation_record(
                    app_asar_path,
                    compatibility_manifest_path,
                    upstream_version,
                    source_signature=captured_source_signature,
                )
                log_file.write("Verifizierter Installationshash atomar gespeichert.\n")
                log_file.flush()

                # Erst nach erfolgreicher Verifikation das Backup loeschen
                if backup_asar_path.exists():
                    try:
                        backup_asar_path.unlink()
                        log_file.write("Backup-Datei app.asar.bak geloescht.\n")
                    except Exception as e:
                        log_file.write(f"Warnung beim Loeschen des Backups: {e}\n")
                    log_file.flush()
                if backup_unpacked_path.exists():
                    try:
                        if (
                            backup_unpacked_path.resolve().parent != resources_dir.resolve()
                            or backup_unpacked_path.name != "app.asar.unpacked.bak"
                        ):
                            raise RuntimeError(
                                f"Unsafe unpacked backup path: {backup_unpacked_path}"
                            )
                        shutil.rmtree(backup_unpacked_path)
                        log_file.write("Backup-Ordner app.asar.unpacked.bak geloescht.\n")
                    except Exception as e:
                        log_file.write(
                            f"Warnung beim Loeschen des unpacked-Backups: {e}\n"
                        )
                    log_file.flush()

                # Record the verified installation immediately. Otherwise the
                # background guard can schedule an unnecessary second repack.
                guard_script = skill_root / "scripts" / "auto_repack_guard.py"
                if guard_script.exists():
                    guard_mark = subprocess.run(
                        [sys.executable, str(guard_script), "--mark-current"],
                        cwd=str(skill_root),
                        capture_output=True,
                        text=True,
                        creationflags=WINDOW_FLAGS,
                    )
                    if guard_mark.returncode == 0:
                        log_file.write("Auto-Repack-Guard-Signatur aktualisiert.\n")
                    else:
                        log_file.write(
                            "Warnung: Auto-Repack-Guard-Signatur konnte nicht "
                            f"aktualisiert werden (Exit {guard_mark.returncode}).\n"
                        )
                    log_file.flush()

            except Exception as check_err:
                log_file.write(f"Preload-Pruefung FEHLGESCHLAGEN: {check_err}\n")
                log_file.write(traceback.format_exc())
                log_file.flush()

                # ROLLBACK TRIGGERN
                write_status(SCRATCH_DIR, "running", "rollback")
                log_file.write("Starte automatischen Rollback...\n")
                log_file.flush()

                # 1. Stop only this installation before restoring its backup.
                stop_install_process_tree(app_path, log_file)
                time.sleep(1)

                # 2. Backup wiederherstellen
                if backup_asar_path.exists():
                    try:
                        shutil.copy2(backup_asar_path, app_asar_path)
                        log_file.write("Backup erfolgreich wiederhergestellt.\n")
                        backup_asar_path.unlink()
                    except Exception as restore_err:
                        log_file.write(f"SCHWERER FEHLER beim Wiederherstellen des Backups: {restore_err}\n")
                    log_file.flush()
                else:
                    log_file.write("WARNUNG: Keine Backup-Datei app.asar.bak gefunden! Kann nicht wiederherstellen.\n")
                    log_file.flush()
                if backup_unpacked_path.exists():
                    try:
                        if app_unpacked_path.exists():
                            shutil.rmtree(app_unpacked_path)
                        shutil.copytree(backup_unpacked_path, app_unpacked_path)
                        shutil.rmtree(backup_unpacked_path)
                        log_file.write("Unpacked-Backup erfolgreich wiederhergestellt.\n")
                    except Exception as restore_err:
                        log_file.write(
                            f"SCHWERER FEHLER beim Wiederherstellen des unpacked-Backups: {restore_err}\n"
                        )
                    log_file.flush()

                # 3. App neu starten (mit dem funktionierenden Backup)
                log_file.write("Starte App mit wiederhergestelltem Backup neu...\n")
                log_file.flush()
                subprocess.Popen(
                    [str(app_path)],
                    env=application_launch_environment(),
                    close_fds=True,
                    creationflags=DETACHED_FLAGS,
                )

                # DevTools-Port loeschen und neu warten
                if port_file.exists():
                    try:
                        port_file.unlink()
                    except Exception:
                        pass

                # Verify the restored version without navigating or sending UI input.
                try:
                    time.sleep(1) # Kurz warten
                    asyncio.run(
                        verify_runtime_after_restart(
                            port_file,
                            app_path,
                            log_file,
                            verification_chat_id,
                        )
                    )
                    log_file.write("Rollback-Version read-only verifiziert.\n")
                except Exception as verification_error:
                    log_file.write(
                        f"Rollback-Version konnte nicht verifiziert werden: {verification_error}\n"
                    )
                log_file.flush()

                err_file.write_text(f"Repack-Pruefung fehlgeschlagen: {check_err}. Rollback durchgefuehrt.", encoding="utf-8")
                return 1

            write_status(SCRATCH_DIR, "running", "guard_state")
            guard_result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("auto_repack_guard.py")), "--mark-current"],
                capture_output=True,
                text=True,
                creationflags=WINDOW_FLAGS,
            )
            if guard_result.returncode != 0:
                raise RuntimeError(f"Verifizierter Guard-Status konnte nicht gespeichert werden: {guard_result.stderr.strip()}")
            log_file.write("Verifizierte App- und Quellsignatur an den Guard uebergeben.\n")
            log_file.write("Beende Skript.\n")
            log_file.flush()

        except Exception as e:
            log_file.write(f"SCHWERER FEHLER: {str(e)}\n")
            log_file.write(traceback.format_exc())
            log_file.flush()
            err_file.write_text(f"Repack fehlgeschlagen: {e}", encoding="utf-8")
            if restart_original_on_error:
                try:
                    subprocess.Popen(
                        [str(app_path)],
                        env=application_launch_environment(),
                        close_fds=True,
                        creationflags=DETACHED_FLAGS,
                    )
                    log_file.write("Start der unveraenderten App nach Pre-Pack-Fehler erneut angefordert.\n")
                except Exception as restart_error:
                    log_file.write(f"Unveraenderte App konnte nicht neu gestartet werden: {restart_error}\n")
                log_file.flush()
            return 1
        finally:
            if resources_dir is not None and staging_root is not None:
                try:
                    remove_staging_tree(staging_root, resources_dir)
                except Exception as cleanup_error:
                    log_file.write(
                        f"Staging-Cleanup beim Verlassen des Repack-Laufs fehlgeschlagen: "
                        f"{cleanup_error}\n"
                    )
                    log_file.flush()

    return 0


def main():
    lock_handle = acquire_repack_lock()
    if lock_handle is None:
        print("A verified Antigravity repack is already running.", file=sys.stderr)
        return 2
    try:
        result = run_repack()
        if result == 0:
            write_status(SCRATCH_DIR, "success", "complete", message="Injector erfolgreich installiert und verifiziert.")
            clear_notification(SCRATCH_DIR)
        else:
            status = read_status(SCRATCH_DIR)
            error_path = SCRATCH_DIR / "repack_error.txt"
            message = error_path.read_text(encoding="utf-8") if error_path.is_file() else "Repack fehlgeschlagen. Siehe repack_and_restart.log."
            if status.get("state") != "blocked":
                write_status(SCRATCH_DIR, "error", status.get("phase", "repack"), kind="repack_error", message=message)
            print(message, file=sys.stderr)
            try:
                notify_failure(SCRATCH_DIR)
            except Exception as notification_error:
                print(f"Fehler-Popup konnte nicht gestartet werden: {notification_error}", file=sys.stderr)
        return result
    finally:
        release_repack_lock(lock_handle)

def cli():
    import argparse
    parser = argparse.ArgumentParser(description="Validate, install and restart the Antigravity desktop modifier.")
    parser.parse_args()
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
