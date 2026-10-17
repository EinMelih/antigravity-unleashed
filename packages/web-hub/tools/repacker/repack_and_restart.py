import os
import subprocess
import time
import traceback
import json
import urllib.request
import urllib.parse
import shutil
import asyncio
import re
import uuid
from pathlib import Path

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
                    raise RuntimeError(f"Renderer error detected: {err_msg}")
                    
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
                raise RuntimeError(f"Unhandled exception detected: {err_msg}")
                
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
                    raise RuntimeError(f"Renderer console.error detected: {err_msg}")
            
            return data
    raise RuntimeError("WebSocket closed unexpectedly")

async def send_status_message(port_file_path, message, log_file, target_chat_id, user_chat_id=None):
    log_file.write("Starte send_status_message...\n")
    log_file.flush()
    # 1. Wait for DevToolsActivePort file
    for i in range(60):
        if port_file_path.exists():
            log_file.write(f"DevToolsActivePort-Datei gefunden nach {i*0.5}s.\n")
            log_file.flush()
            break
        await asyncio.sleep(0.5)
    else:
        log_file.write("DevToolsActivePort-Datei nicht gefunden.\n")
        log_file.flush()
        raise FileNotFoundError("DevToolsActivePort-Datei nicht gefunden.")

    await asyncio.sleep(0.5)

    # 2. Port lesen
    try:
        lines = port_file_path.read_text(encoding="utf-8").splitlines()
        port = int(lines[0].strip())
        log_file.write(f"Port ausgelesen: {port}\n")
        log_file.flush()
    except Exception as e:
        log_file.write(f"Fehler beim Lesen des Ports: {e}\n")
        log_file.flush()
        raise e

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
                    const errPopup = document.getElementById('antigravity-injection-error-popup');
                    if (errPopup) {
                        const pre = errPopup.querySelector('pre');
                        return "AMS-Skript-Injektion fehlgeschlagen: " + (pre ? pre.textContent.trim() : "Unbekannter Fehler");
                    }
                    if (typeof window.getTaskPlan === 'undefined') return "WAIT_AMS";
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

                # 4b. Falls nicht im richtigen Chat, dorthin navigieren
                # (target_chat_id is passed as an argument)
                if target_chat_id not in current_href:
                    parsed = urllib.parse.urlparse(backend_url)
                    target_chat_url = f"{parsed.scheme}://{parsed.netloc}/c/{target_chat_id}"
                    log_file.write(f"Navigiere zu Chat-URL: {target_chat_url}\n")
                    log_file.flush()
                    
                    await ws.send_json({
                        "id": 11,
                        "method": "Page.navigate",
                        "params": {
                            "url": target_chat_url
                        }
                    })
                    
                    while True:
                        data = await recv_next(ws, log_file)
                        if data.get("id") == 11:
                            break
                    # Warte auf das Laden der Seite
                    await asyncio.sleep(3)

                # 4c. Warte auf Eingabefeld im DOM
                js_wait = """
                (async function() {
                    for (let i = 0; i < 40; i++) {
                        const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                        if (input) return true;
                        await new Promise(r => setTimeout(r, 500));
                    }
                    return false;
                })()
                """
                log_file.write("Warte auf Eingabefeld im DOM...\n")
                log_file.flush()
                
                await ws.send_json({
                    "id": 12,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": js_wait,
                        "returnByValue": True,
                        "awaitPromise": True
                    }
                })
                
                input_found = False
                while True:
                    data = await recv_next(ws, log_file)
                    if data.get("id") == 12:
                        input_found = data.get("result", {}).get("result", {}).get("value")
                        break
                
                if not input_found:
                    log_file.write("Eingabefeld wurde nicht geladen oder nicht gefunden.\n")
                    log_file.flush()
                    raise RuntimeError("Eingabefeld wurde nicht geladen oder nicht gefunden.")

                # 4d. Nachricht eintragen und absenden
                escaped_text = json.dumps(message)
                js_send = f"""
                (async function() {{
                    const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                    if (!input) return 'no_input';
                    
                    input.focus();
                    
                    // Alles auswaehlen und loeschen
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    
                    // Text einfuegen
                    document.execCommand('insertText', false, {escaped_text});
                    
                    // 300ms warten, damit React den State aktualisiert und der Send-Button aktiv wird
                    await new Promise(r => setTimeout(r, 300));
                    
                    // Den Send-Button suchen und klicken
                    const sendBtn = document.querySelector('[data-testid="send-button"]');
                    if (sendBtn) {{
                        sendBtn.click();
                        return 'clicked_send_button';
                    }}
                    
                    return 'no_send_button_found';
                }})()
                """
                log_file.write("Sende Nachricht ueber CDP...\n")
                log_file.flush()
                
                await ws.send_json({
                    "id": 13,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": js_send,
                        "returnByValue": True,
                        "awaitPromise": True
                    }
                })
                
                send_res = None
                while True:
                    data = await recv_next(ws, log_file)
                    if data.get("id") == 13:
                        send_res = data.get("result", {}).get("result", {}).get("value")
                        break
                
                log_file.write(f"Nachricht gesendet. Ergebnis: {send_res}\n")
                log_file.flush()
                
                # 4e. Page in den Vordergrund bringen (nur wenn es das Hauptfenster ist, um Fokusklau zu vermeiden)
                if not user_chat_id or target_chat_id == user_chat_id:
                    log_file.write("Bringe Antigravity-Fenster in den Vordergrund (Page.bringToFront)...\n")
                    log_file.flush()
                    await ws.send_json({
                        "id": 14,
                        "method": "Page.bringToFront"
                    })
                    
                    while True:
                        data = await recv_next(ws, log_file)
                        if data.get("id") == 14:
                            log_file.write("Page.bringToFront erfolgreich abgeschlossen.\n")
                            log_file.flush()
                            break
                else:
                    log_file.write("Bypass Page.bringToFront, da es ein minimiertes Hintergrund-Fenster ist.\n")
                    log_file.flush()
                    
                    # 4f. Schliesse das minimierte Hintergrundfenster nach 3 Sekunden Wartezeit, um DB-Locks zu vermeiden
                    log_file.write("Warte 3 Sekunden vor dem Schliessen des Hintergrundfensters...\n")
                    log_file.flush()
                    await asyncio.sleep(3)
                    
                    log_file.write("Schliesse das Hintergrundfenster via window.close()...\n")
                    log_file.flush()
                    await ws.send_json({
                        "id": 15,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": "window.close()",
                            "returnByValue": True
                        }
                    })
                    
                    try:
                        while True:
                            data = await recv_next(ws, log_file)
                            if data.get("id") == 15:
                                log_file.write("window.close() erfolgreich aufgerufen.\n")
                                log_file.flush()
                                break
                    except RuntimeError as e:
                        if "WebSocket closed unexpectedly" in str(e):
                            log_file.write("WebSocket closed during window.close() as expected.\n")
                            log_file.flush()
                        else:
                            raise e
                            
    except Exception as e:
        log_file.write(f"Fehler bei WebSocket/CDP-Verbindung: {e}\n")
        log_file.write(traceback.format_exc())
        log_file.flush()
        raise e

def get_last_active_session_id():
    # 1. Versuche aus app_storage.json zu lesen und repariere sie bei JSON-Fehlern
    try:
        storage_path = Path.home() / "AppData" / "Roaming" / "Antigravity" / "app_storage.json"
        if storage_path.exists():
            content = storage_path.read_text(encoding="utf-8")
            try:
                storage_data = json.loads(content)
            except Exception:
                # Datei ist korrupt! Reparieren mit leerem JSON
                storage_path.write_text("{}", encoding="utf-8")
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

    # 3. Fallback: MEMORY.pc.md auslesen
    try:
        config_dir = Path.home() / ".gemini" / "config"
        memory_path = config_dir / "MEMORY.pc.md"
        if memory_path.exists():
            content = memory_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if "Session" in line or "Session ID" in line or "Last Active Session" in line:
                    match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", line, re.IGNORECASE)
                    if match:
                        return match.group(1)
    except Exception as e:
        pass
    return "86b6e95e-3bd6-4a2d-bc4a-ca84f64e7188" # fallback auf diesen Chat

def update_last_active_session_id(new_id, log_file):
    try:
        config_dir = Path.home() / ".gemini" / "config"
        memory_path = config_dir / "MEMORY.pc.md"
        if memory_path.exists():
            content = memory_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            updated = False
            for i, line in enumerate(lines):
                if "Session" in line or "Session ID" in line or "Last Active Session" in line:
                    # Find and replace the UUID
                    lines[i] = re.sub(
                        r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                        new_id,
                        line,
                        flags=re.IGNORECASE
                    )
                    updated = True
                    break
            if updated:
                memory_path.write_text("\n".join(lines), encoding="utf-8")
                log_file.write(f"Updated Session ID in MEMORY.pc.md to {new_id}\n")
                log_file.flush()
                
                # Also compile memory.md using compile_memory.py
                compile_script = config_dir / "scripts" / "compile_memory.py"
                if compile_script.exists():
                    log_file.write("Running compile_memory.py...\n")
                    log_file.flush()
                    subprocess.run(["python", str(compile_script)], capture_output=True)
            else:
                log_file.write("Could not find Session line in MEMORY.pc.md\n")
                log_file.flush()
    except Exception as e:
        log_file.write(f"Failed to update Session ID in MEMORY.pc.md: {e}\n")
        log_file.flush()

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
        storage_path = Path.home() / "AppData" / "Roaming" / "Antigravity" / "app_storage.json"
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
        result = subprocess.run(["node", "-c", str(file_path)], capture_output=True, text=True)
        if result.returncode != 0:
            log_file.write(f"SYNTAX-FEHLER in {file_path.name}:\n{result.stderr}\n")
            log_file.flush()
            return False
        log_file.write(f"{file_path.name} ist syntaktisch korrekt.\n")
        log_file.flush()
        return True
    except Exception as e:
        log_file.write(f"Warnung: Konnte Syntaxpruefung fuer {file_path.name} nicht ausfuehren ({e}). Fuehre fort...\n")
        log_file.flush()
        return True

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

def main():
    log_path = Path.home() / ".gemini" / "antigravity" / "scratch" / "repack_and_restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 0. Fehler-Datei loeschen, falls vorhanden
    err_file = Path.home() / ".gemini" / "antigravity" / "scratch" / "repack_error.txt"
    if err_file.exists():
        try:
            err_file.unlink()
        except Exception:
            pass
            
    # Beende eventuell bereits laufende andere Instanzen von repack_and_restart.py und alte PowerShell-Fenster von Repacks
    my_pid = os.getpid()
    try:
        my_ppid = os.getppid()
    except Exception:
        my_ppid = 0
    ps_cmd = (
        f"Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' AND CommandLine LIKE '%repack_and_restart.py%'\" | Where-Object ProcessId -ne {my_pid} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}; "
        f"Get-CimInstance Win32_Process -Filter \"Name = 'powershell.exe' AND (CommandLine LIKE '%repack%' OR CommandLine LIKE '%AntigravityRepack%')\" | Where-Object ProcessId -ne {my_ppid} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("--- LOG-START ---\n")
        log_file.write("repack_and_restart.py gestartet.\n")
        log_file.flush()
        
        try:
            # NodeJS-Pfad zur PATH-Variable hinzufuegen, damit node/npx verfuegbar sind
            node_dir = r"C:\Program Files\nodejs"
            if node_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = node_dir + os.path.pathsep + os.environ.get("PATH", "")
                
            # 1. Letzte aktive Session-ID und Workspace-Pfad ermitteln
            target_chat_id = get_last_active_session_id()
            
            # 2. Pfade definieren
            local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            app_extracted = str(Path(local_app_data) / "Programs" / "Antigravity" / "resources" / "app-extracted")
            app_asar = str(Path(local_app_data) / "Programs" / "Antigravity" / "resources" / "app.asar")
            config_src_dir = Path.home() / ".gemini" / "config" / "skills" / "antigravity_desktop_ui_modifier" / "src"
            
            # Workspace-Pfad bevorzugen, falls vorhanden
            cwd_src = Path(os.getcwd()) / "skills" / "antigravity_desktop_ui_modifier" / "src"
            if cwd_src.exists():
                config_src_dir = cwd_src
                log_file.write(f"Nutze CWD-Workspace-Ordner als Quelle fuer Repack: {config_src_dir}\n")
                log_file.flush()
            else:
                workspace_dir = get_workspace_path(target_chat_id, log_file)
                if workspace_dir:
                    workspace_src = workspace_dir / "skills" / "antigravity_desktop_ui_modifier" / "src"
                    if workspace_src.exists():
                        config_src_dir = workspace_src
                        log_file.write(f"Nutze Workspace-Ordner aus DB als Quelle fuer Repack: {config_src_dir}\n")
                        log_file.flush()
            
            dest_dist_dir = Path(app_extracted) / "dist"
            
            # 2. Praeventive Syntax-Pruefung der geaenderten Dateien
            log_file.write("Starte praeventive JS-Syntax-Pruefung...\n")
            log_file.flush()
            
            # Alle .js-Dateien im Quellordner ermitteln
            js_files_to_check = [f.name for f in config_src_dir.glob("*.js")]
            if not js_files_to_check:
                js_files_to_check = ["preload.js", "ipcHandlers.js", "utils.js", "main.js"]
                
            syntax_ok = True
            for fname in js_files_to_check:
                fpath = config_src_dir / fname
                if fpath.exists():
                    if not validate_js_syntax(fpath, log_file):
                        syntax_ok = False
                else:
                    # Falls nicht im config, pruefe im dist-Ordner
                    fpath_dist = dest_dist_dir / fname
                    if fpath_dist.exists() and not validate_js_syntax(fpath_dist, log_file):
                        syntax_ok = False
                        
            if not syntax_ok:
                log_file.write("ABBRUCH: Syntax-Validierung fehlgeschlagen! Anwendung wird NICHT beendet.\n")
                log_file.flush()
                err_file.write_text("Syntax-Validierung in den JS-Dateien fehlgeschlagen! Siehe repack_and_restart.log fuer Details.", encoding="utf-8")
                return
                
            # 3. Warten, damit der Agent sich verabschieden kann
            log_file.write("Warte 2 Sekunden...\n")
            log_file.flush()
            time.sleep(2)
            
            # DevToolsActivePort Pfad definieren
            port_file = Path.home() / "AppData" / "Roaming" / "Antigravity" / "DevToolsActivePort"
            
            # 3b. Draft aus app_storage.json in die Windows-Zwischenablage kopieren (Sicherheits-Backup)
            try:
                storage_path = Path.home() / "AppData" / "Roaming" / "Antigravity" / "app_storage.json"
                if storage_path.exists():
                    log_file.write("Versuche, aktuellen Draft aus app_storage.json in die Zwischenablage zu kopieren...\n")
                    log_file.flush()
                    storage_data = json.loads(storage_path.read_text(encoding="utf-8"))
                    draft_text = storage_data.get("antigravity_message_input_draft", "")
                    if draft_text and draft_text.strip():
                        # Sicherer und robuster PowerShell-basierter Clipboard-Kopierer (unterstuetzt Unicode)
                        p = subprocess.Popen(
                            ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                            stdin=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        p.communicate(input=draft_text)
                        log_file.write("Draft erfolgreich via PowerShell/Set-Clipboard in die Zwischenablage kopiert.\n")
                    else:
                        log_file.write("Kein aktiver Draft vorhanden oder leer.\n")
                    log_file.flush()
            except Exception as clipboard_err:
                log_file.write(f"Warnung beim Sichern des Drafts in das Clipboard: {clipboard_err}\n")
                log_file.flush()
            
            # 3c. Aktuellen Pfad (Chat/Einstellungen etc.) via DevTools ermitteln und sichern
            active_path = get_current_active_path(port_file, log_file)
            
            # 4. Antigravity-Prozesse beenden
            log_file.write("Kille Antigravity-Prozesse...\n")
            log_file.flush()
            kill_res = subprocess.run(["taskkill", "/f", "/im", "Antigravity.exe"], capture_output=True, text=True)
            log_file.write(f"taskkill returncode: {kill_res.returncode}\n")
            log_file.write(f"taskkill stdout: {kill_res.stdout.strip()}\n")
            log_file.write(f"taskkill stderr: {kill_res.stderr.strip()}\n")
            
            # Kille auch Zombie-Daemons (language_server.exe), um offene Konsolenfenster zu schließen
            kill_ls = subprocess.run(["taskkill", "/f", "/im", "language_server.exe"], capture_output=True, text=True)
            log_file.write(f"taskkill language_server.exe returncode: {kill_ls.returncode}\n")
            log_file.write(f"taskkill language_server.exe stdout: {kill_ls.stdout.strip()}\n")
            log_file.flush()
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
            
            # 5. Kopiere die UI-Modifikationen aus dem Config-Repository in den App-Ordner
            log_file.write("Kopiere Modifikationen aus dem Git-Repository in den App-Ordner...\n")
            log_file.flush()
            
            try:
                for js_file in config_src_dir.glob("**/*.js"):
                    relative_path = js_file.relative_to(config_src_dir)
                    dest_file = dest_dist_dir / relative_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(js_file, dest_file)
                    log_file.write(f"Kopiert: {relative_path}\n")
                log_file.write("Dateien erfolgreich in App-Ordner kopiert.\n")
                log_file.flush()
            except Exception as copy_e:
                log_file.write(f"Warnung beim Kopieren der Quelldateien: {copy_e}\n")
                log_file.flush()
                
            # 6. Backup von app.asar erstellen
            app_asar_path = Path(app_asar)
            backup_asar_path = app_asar_path.with_suffix(".asar.bak")
            if app_asar_path.exists():
                try:
                    shutil.copy2(app_asar_path, backup_asar_path)
                    log_file.write("Backup von app.asar erstellt.\n")
                    log_file.flush()
                except Exception as backup_err:
                    log_file.write(f"Warnung: Backup von app.asar konnte nicht erstellt werden: {backup_err}\n")
                    log_file.flush()
            
            # 7. Packen
            log_file.write(f"Packe app.asar... PATH: {os.environ.get('PATH')}\n")
            log_file.flush()
            
            pack_success = False
            result = None
            # Versuche mit npx.cmd, ansonsten npx
            try:
                log_file.write("Versuche Packen mit npx.cmd...\n")
                log_file.flush()
                cmd_str = f'npx.cmd asar pack "{app_extracted}" "{app_asar}"'
                result = subprocess.run(cmd_str, capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    pack_success = True
            except Exception as inner_e:
                log_file.write(f"npx.cmd fehlgeschlagen: {str(inner_e)}. Versuche npx...\n")
                log_file.flush()
                
            if not pack_success:
                try:
                    cmd_str = f'npx asar pack "{app_extracted}" "{app_asar}"'
                    result = subprocess.run(cmd_str, capture_output=True, text=True, shell=True)
                    if result.returncode == 0:
                        pack_success = True
                except Exception as e2:
                    log_file.write(f"npx asar pack fehlgeschlagen: {str(e2)}\n")
                    log_file.flush()
                    
            log_file.write(f"Packen abgeschlossen. Erfolg: {pack_success}\n")
            if result:
                log_file.write(f"Packen returncode: {result.returncode}\n")
                log_file.write(f"Packen stdout: {result.stdout.strip()}\n")
                log_file.write(f"Packen stderr: {result.stderr.strip()}\n")
            log_file.flush()
            
            if not pack_success or (result and result.returncode != 0):
                log_file.write("Packen fehlgeschlagen! Stelle Backup wieder her...\n")
                log_file.flush()
                if backup_asar_path.exists():
                    try:
                        shutil.copy2(backup_asar_path, app_asar_path)
                        log_file.write("Backup erfolgreich wiederhergestellt.\n")
                    except Exception as restore_err:
                        log_file.write(f"FEHLER beim Wiederherstellen des Backups: {restore_err}\n")
                    log_file.flush()
                err_file.write_text("Packen der app.asar fehlgeschlagen! Backup wurde wiederhergestellt.", encoding="utf-8")
                return

            # Trigger-Chat-ID auslesen, falls vorhanden
            repack_trigger_file = Path.home() / ".gemini" / "antigravity" / "scratch" / "repack_trigger_chat.txt"
            repack_trigger_id = None
            if repack_trigger_file.exists():
                try:
                    repack_trigger_id = repack_trigger_file.read_text(encoding="utf-8").strip()
                    log_file.write(f"Trigger-Chat-ID aus Datei gelesen: {repack_trigger_id}\n")
                    repack_trigger_file.unlink() # Datei loeschen
                except Exception as e:
                    log_file.write(f"Failed to read/delete trigger file: {e}\n")
                log_file.flush()

            # Letzte aktive Session-ID auslesen (wo der User zuletzt war)
            target_chat_id = get_last_active_session_id()
            
            # Fallback falls kein Trigger-Chat uebergeben wurde
            if not repack_trigger_id:
                repack_trigger_id = target_chat_id
                
            log_file.write(f"Trigger-Chat-ID (Fokus fuer Erfolgsmeldung): {repack_trigger_id}\n")
            log_file.write(f"User-Chat-ID (Hauptfenster): {target_chat_id}\n")
            log_file.flush()
            
            # 8. App neu starten
            app_path = str(Path(local_app_data) / "Programs" / "Antigravity" / "Antigravity.exe")
            log_file.write(f"Starte App neu: {app_path}\n")
            log_file.flush()
            
            app_env = os.environ.copy()
            if repack_trigger_id and repack_trigger_id != target_chat_id:
                app_env["REPACK_TRIGGER_CHAT_ID"] = repack_trigger_id
                log_file.write(f"Setting env REPACK_TRIGGER_CHAT_ID={repack_trigger_id} to open a second window.\n")
            else:
                log_file.write("Trigger-Chat entspricht dem letzten User-Chat. Kein zweites Fenster noetig.\n")
            log_file.flush()
            
            subprocess.Popen([app_path], env=app_env, close_fds=True, creationflags=subprocess.DETACHED_PROCESS)
            log_file.write("Startbefehl abgesetzt. Starte Preload-Verifikation...\n")
            log_file.flush()
            
            # 6b. Nachricht ermitteln (entweder aus repack_message.txt oder Standardnachricht)
            msg_file = Path.home() / ".gemini" / "antigravity" / "scratch" / "repack_message.txt"
            if msg_file.exists():
                try:
                    msg_text = msg_file.read_text(encoding="utf-8").strip()
                    msg_file.unlink() # Nach dem Lesen loeschen
                    log_file.write(f"Nutze benutzerdefinierte Nachricht aus {msg_file}\n")
                except Exception as read_err:
                    log_file.write(f"Fehler beim Lesen der Nachrichtendatei: {read_err}\n")
                    msg_text = "Der Repack- und Neustart-Prozess wurde erfolgreich abgeschlossen!"
            else:
                msg_text = "Der Repack- und Neustart-Prozess wurde erfolgreich abgeschlossen und die Anwendung wurde neu gestartet."
            
            log_file.flush()
            
            try:
                # Versuche die Statusnachricht zu senden (prueft auch preload.js)
                asyncio.run(send_status_message(port_file, msg_text, log_file, repack_trigger_id, target_chat_id))
                log_file.write("App-Start und Preload-Pruefung erfolgreich abgeschlossen.\n")
                log_file.flush()
                
                # Erst nach erfolgreicher Verifikation das Backup loeschen
                if backup_asar_path.exists():
                    try:
                        backup_asar_path.unlink()
                        log_file.write("Backup-Datei app.asar.bak geloescht.\n")
                    except Exception as e:
                        log_file.write(f"Warnung beim Loeschen des Backups: {e}\n")
                    log_file.flush()
                    
            except Exception as check_err:
                log_file.write(f"Preload-Pruefung FEHLGESCHLAGEN: {check_err}\n")
                log_file.write(traceback.format_exc())
                log_file.flush()
                
                # ROLLBACK TRIGGERN
                log_file.write("Starte automatischen Rollback...\n")
                log_file.flush()
                
                # 1. Antigravity killen
                subprocess.run(["taskkill", "/f", "/im", "Antigravity.exe"], capture_output=True)
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
                
                # 3. App neu starten (mit dem funktionierenden Backup)
                log_file.write("Starte App mit wiederhergestelltem Backup neu...\n")
                log_file.flush()
                subprocess.Popen([app_path], close_fds=True, creationflags=subprocess.DETACHED_PROCESS)
                
                # 4. Warnnachricht an den User senden
                warn_msg = (
                     "⚠️ **Automatischer Rollback durchgefuehrt!**\n\n"
                     "Das letzte Repack der `app.asar` ist fehlgeschlagen (Fehler beim Starten oder Preload-Script nicht geladen).\n"
                     f"Fehlerdetails: `{check_err}`\n\n"
                     "Das vorherige funktionierende Backup wurde automatisch wiederhergestellt und die Anwendung neu gestartet."
                )
                
                # DevTools-Port loeschen und neu warten
                if port_file.exists():
                    try:
                        port_file.unlink()
                    except Exception:
                        pass
                
                # Nachricht ueber die funktionierende Version senden
                try:
                    time.sleep(1) # Kurz warten
                    asyncio.run(send_status_message(port_file, warn_msg, log_file, repack_trigger_id, target_chat_id))
                    log_file.write("Rollback-Warnmeldung erfolgreich gesendet.\n")
                except Exception as warn_err:
                    log_file.write(f"Konnte Rollback-Warnmeldung nicht senden: {warn_err}\n")
                log_file.flush()
                
                err_file.write_text(f"Repack-Pruefung fehlgeschlagen: {check_err}. Rollback durchgefuehrt.", encoding="utf-8")
                
            # Scheduled Task selbst loeschen, um PowerShell-Escaping-Fehler zu vermeiden
            try:
                log_file.write("Entregistriere Scheduled Task AntigravityRepack...\n")
                log_file.flush()
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Unregister-ScheduledTask -TaskName 'AntigravityRepack' -Confirm:$false -ErrorAction SilentlyContinue"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                log_file.write("Scheduled Task erfolgreich geloescht.\n")
            except Exception as unreg_err:
                log_file.write(f"Fehler beim Loeschen des Scheduled Tasks: {unreg_err}\n")
            log_file.flush()

            log_file.write("Beende Skript.\n")
            log_file.flush()
            
        except Exception as e:
            log_file.write(f"SCHWERER FEHLER: {str(e)}\n")
            log_file.write(traceback.format_exc())
            log_file.flush()

if __name__ == "__main__":
    main()
