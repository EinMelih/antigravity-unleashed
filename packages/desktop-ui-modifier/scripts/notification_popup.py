"""Show one Windows dialog in a separate process from the injector with self-healing support."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

MB_OK = 0x00000000
MB_YESNO = 0x00000004
MB_ICONQUESTION = 0x00000020
MB_ICONINFORMATION = 0x00000040
MB_ICONWARNING = 0x00000030
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000
IDYES = 6
LOCAL_URL_PATTERN = re.compile(r"https://127\.0\.0\.1:\d+/")


def find_active_devtools_port(user_data_dir: Path) -> int | None:
    port_file = user_data_dir / "DevToolsActivePort"
    if port_file.is_file():
        try:
            line = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
            return int(line)
        except (OSError, ValueError, IndexError):
            pass
    return None


def find_latest_local_app_url(user_data_dir: Path | None) -> str | None:
    if not user_data_dir:
        return None
    main_log = Path(user_data_dir) / "logs" / "main.log"
    if not main_log.is_file():
        return None
    try:
        with main_log.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read().decode("utf-8", errors="ignore")
        matches = LOCAL_URL_PATTERN.findall(tail)
        return matches[-1] if matches else None
    except OSError:
        return None


async def _evaluate_cdp(ws, msg_id: int, expression: str, await_promise: bool = False):
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        },
    })
    async for msg in ws:
        if msg.type != 1:  # aiohttp.WSMsgType.TEXT
            continue
        data = json.loads(msg.data)
        if data.get("id") == msg_id:
            return data.get("result", {}).get("result", {}).get("value")
    return None


async def send_via_cdp(port: int, prompt: str, user_data_dir: Path | None = None) -> bool:
    import aiohttp

    req = urllib.request.Request(f"http://127.0.0.1:{port}/json")
    with urllib.request.urlopen(req, timeout=2) as resp:
        targets = json.loads(resp.read().decode())

    page_target = next(
        (t for t in targets if t.get("type") == "page" and "127.0.0.1" in t.get("url", "")),
        None,
    )
    if not page_target:
        page_target = next((t for t in targets if t.get("type") == "page"), None)
    if not page_target:
        return False

    ws_url = page_target["webSocketDebuggerUrl"]
    target_url = str(page_target.get("url", ""))
    recovery_url = find_latest_local_app_url(user_data_dir)
    has_input_expr = """
    (() => Boolean(
        (window.__agBridge && typeof window.__agBridge.prepareAndSend === 'function')
        || document.querySelector('[role="combobox"][aria-label="Message input"]')
        || document.querySelector('[role="combobox"]')
        || document.querySelector('[contenteditable="true"]')
    ))()
    """

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.send_json({"id": 1, "method": "Page.bringToFront"})

            # If an unpatched upstream build hit ERR_NETWORK_CHANGED during startup,
            # the window stays grey on chrome-error://chromewebdata/. Recover it via CDP
            # using the latest https://127.0.0.1:<port>/ URL from main.log.
            ready = await _evaluate_cdp(ws, 10, has_input_expr)
            if not ready and recovery_url and ("127.0.0.1" not in target_url or target_url.startswith("chrome-error://")):
                await ws.send_json({
                    "id": 11,
                    "method": "Page.navigate",
                    "params": {"url": recovery_url},
                })
                for poll_idx in range(16):
                    await asyncio.sleep(0.5)
                    if await _evaluate_cdp(ws, 20 + poll_idx, has_input_expr):
                        break

            js_code = f"""
            (async () => {{
                const text = {json.dumps(prompt)};

                if (window.__agBridge && typeof window.__agBridge.prepareAndSend === 'function') {{
                    const res = await window.__agBridge.prepareAndSend(text);
                    if (res && res.success) return true;
                }}

                const input = document.querySelector('[role="combobox"][aria-label="Message input"]')
                    || document.querySelector('[role="combobox"]')
                    || document.querySelector('[contenteditable="true"]');
                if (!input) return false;

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

                await new Promise(r => setTimeout(r, 250));

                const btn = Array.from(document.querySelectorAll('button')).find(b => {{
                    const label = (b.getAttribute('aria-label') || '').toLowerCase();
                    return label.includes('send') && b.offsetParent !== null && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
                }});

                if (btn) {{
                    btn.click();
                    return true;
                }}

                const enterEvent = new KeyboardEvent('keydown', {{
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true
                }});
                input.dispatchEvent(enterEvent);
                return true;
            }})()
            """
            return bool(await _evaluate_cdp(ws, 2, js_code, await_promise=True))
    return False


def send_via_api_bridge(prompt: str) -> bool:
    try:
        data = json.dumps({"message": prompt}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8001/api/chat", data=data, method="POST")
        req.add_header("Authorization", "Bearer ag-local-token")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def dispatch_prompt_to_antigravity(prompt: str, user_data_dir: Path) -> bool:
    port = find_active_devtools_port(user_data_dir)
    if port:
        try:
            if asyncio.run(send_via_cdp(port, prompt, user_data_dir)):
                return True
        except Exception:
            pass

    try:
        if send_via_api_bridge(prompt):
            return True
    except Exception:
        pass

    return False


def load_recent_findings(skill_root: Path, target_version: str) -> list[str]:
    history_file = skill_root / "UPGRADE_HISTORY.json"
    if not history_file.is_file():
        return []
    try:
        entries = json.loads(history_file.read_text(encoding="utf-8"))
        for entry in entries:
            if entry.get("version") == target_version:
                return entry.get("findings", [])
        if entries:
            return entries[0].get("findings", [])
    except Exception:
        pass
    return []


def main() -> None:
    if os.name != "nt":
        raise RuntimeError("The injector popup requires Windows.")
    status_path = Path(sys.argv[1])
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status_path.unlink()

    skill_root = Path(__file__).resolve().parent.parent
    user_data_dir = Path(os.environ.get("APPDATA", "")) / "Antigravity"
    installed = status.get("installed_version", "")
    supported = status.get("supported_version", "")
    state = status.get("state", "error")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    user32.MessageBoxW.restype = ctypes.c_int

    if state == "blocked":
        findings = load_recent_findings(skill_root, installed)
        findings_block = ""
        if findings:
            findings_block = "\n\nErkenntnisse / Analyse:\n" + "\n".join(f"• {f}" for f in findings[:4])

        message = (
            f"Anti-Gravity wurde aktualisiert (Version {installed}).\n"
            f"Der Injector ist aktuell fuer Version {supported} freigegeben und wurde sicherheitsblockiert.{findings_block}\n\n"
            "Moechtest du, dass der Antigravity-Agent das Problem jetzt automatisch behebt?\n\n"
            "[Ja]  -> Auftrag zur Selbstreparatur direkt in den aktiven Chat schreiben\n"
            "[Nein] -> Vorlaeufig abbrechen (App bleibt original und sicher)"
        )
        title = "Anti-Gravity Injector - Update verfuegbar"
        result = user32.MessageBoxW(None, message, title, MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST)

        if result == IDYES:
            import selfheal

            selfheal.begin(supported, installed)
            selfheal.launch_window()
            prompt = selfheal.build_repair_prompt(installed, supported)
            dispatched = dispatch_prompt_to_antigravity(prompt, user_data_dir)
            if not dispatched:
                selfheal.set_step(
                    "analysis",
                    "failed",
                    "Auftrag konnte nicht an Anti-Gravity gesendet werden. Bitte die App öffnen und erneut versuchen.",
                )
            scratch_dir = status_path.parent
            with (scratch_dir / "auto_repack_guard.log").open("a", encoding="utf-8") as handle:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                status_str = "erfolgreich gesendet" if dispatched else "Senden fehlgeschlagen"
                handle.write(f"[{stamp}] Selbstheilung vom Nutzer bestaetigt: {status_str}.\n")
        return

    successful = state == "success"
    try:
        import selfheal

        healing = selfheal.read_state(status_path.parent)
        run_is_live = healing.get("active") or (
            healing.get("result") == "success" and time.time() - float(healing.get("finished_at", 0)) < 300
        )
        if run_is_live:
            # The progress window already reports success and failure with a retry option.
            return
    except Exception:
        pass
    message = str(status.get("message", "Injector fehlgeschlagen."))[:6000]
    if installed:
        message += f"\n\nInstalliert: {installed}\nInjector freigegeben fuer: {supported or 'nicht ermittelt'}"
    if not successful:
        message += "\n\nNach der Fehlerbehebung kannst du repack.bat erneut starten."
    message += f"\n\nDetails: {status_path.parent / 'repack_and_restart.log'}"

    title = "Anti-Gravity Injector - Fertig" if successful else "Anti-Gravity Injector - Fehler"
    icon = MB_ICONINFORMATION if successful else MB_ICONWARNING
    if not user32.MessageBoxW(None, message, title, icon | MB_SETFOREGROUND):
        raise ctypes.WinError(ctypes.get_last_error())


if __name__ == "__main__":
    main()
