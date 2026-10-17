import socket
import urllib.request
import urllib.parse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, Tuple, List

RECENT_PORTS = [59546, 51405, 64124, 63692, 58323, 9222, 9223, 9224]


def check_port(port: int) -> Optional[Dict[str, Any]]:
    """
    Check if a port is open and serves the Antigravity DevTools JSON endpoint.
    Returns metadata dict of the best matching active chat target if found, otherwise None.
    """
    # The general Hub discovery must never pick the public API's browser.
    from src.config import config
    if port == int(config.config_dict.get('api_profile', {}).get('devtools_port', 9229)):
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.05)
    result = s.connect_ex(('127.0.0.1', port))
    s.close()
    if result != 0:
        return None

    try:
        url = f"http://127.0.0.1:{port}/json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=0.3) as resp:
            if resp.status == 200:
                targets = json.loads(resp.read().decode('utf-8'))
                best_target = None
                best_score = -1

                for t in targets:
                    ws_url = t.get("webSocketDebuggerUrl")
                    page_url = t.get("url", "")
                    if not ws_url:
                        continue

                    # Only page targets, skip workers and background frames
                    if t.get("type") != "page":
                        continue

                    # Must connect to local resources
                    if "127.0.0.1:" not in page_url and "localhost:" not in page_url and "10.0.2.2:" not in page_url:
                        continue

                    # Exclude documentation or IDE views
                    if any(exclude in page_url for exclude in ["/docs", "/editor", "/ide"]):
                        continue

                    score = 10  # Base page score

                    # Secure protocol indicates Tauri backend WebView
                    if page_url.startswith("https://"):
                        score += 20

                    # Primary chat/conversation paths
                    if "/c/" in page_url or "/conversations/" in page_url or "/chat" in page_url:
                        score += 50

                    # Task/project context in target title
                    title = t.get("title", "")
                    if "working on project" in title.lower() or "issue:" in title.lower():
                        score += 40

                    if score > best_score:
                        best_score = score
                        try:
                            backend = urllib.parse.urlparse(page_url).port
                        except Exception:
                            backend = None
                        best_target = {
                            "devtools_port": port,
                            "ws_url": ws_url,
                            "backend_port": backend,
                            "page_url": page_url,
                            "title": title
                        }

                if best_target and best_score > 0:
                    return best_target
    except Exception:
        pass
    return None


def find_devtools(recent_ports: List[int] = RECENT_PORTS) -> Optional[Dict[str, Any]]:
    """
    Find Antigravity DevTools by checking recent ports first, then performing a full scan.
    """
    print("[CDP] Searching for Antigravity webview...", flush=True)

    # Try reading from DevToolsActivePort file first (guaranteed to be the active Tauri app port)
    import os
    from pathlib import Path
    appdata = os.environ.get("APPDATA")
    if appdata:
        port_file = Path(appdata) / "Antigravity" / "DevToolsActivePort"
        if port_file.exists():
            try:
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if lines:
                    port = int(lines[0].strip())
                    res = check_port(port)
                    if res:
                        print(f"[CDP] Found via DevToolsActivePort file! DevTools={res['devtools_port']} "
                              f"Backend={res['backend_port']} "
                              f"Title=\"{res['title']}\"", flush=True)
                        return res
            except Exception as e:
                print(f"[CDP] Error reading DevToolsActivePort file: {e}", flush=True)

    # 1. Check known ports first
    for port in recent_ports:
        res = check_port(port)
        if res:
            print(f"[CDP] Found! DevTools={res['devtools_port']} "
                  f"Backend={res['backend_port']} "
                  f"Title=\"{res['title']}\"", flush=True)
            return res

    # 2. Parallel full scan of private port range
    print("[CDP] Known ports not active, starting full scan (49152-65535)...", flush=True)
    with ThreadPoolExecutor(max_workers=200) as executor:
        futures = {}
        for p in range(49152, 65535):
            if p in recent_ports:
                continue
            futures[executor.submit(check_port, p)] = p

        for future in as_completed(futures):
            res = future.result()
            if res:
                # Cancel other pending futures to save resources
                executor.shutdown(wait=False, cancel_futures=True)
                print(f"[CDP] Found! DevTools={res['devtools_port']} "
                      f"Backend={res['backend_port']}", flush=True)
                return res

    return None


def find_active_ports() -> Tuple[Optional[int], Optional[int]]:
    """
    Find active DevTools and backend ports. Returns (devtools_port, backend_port).
    This function maintains backwards compatibility with proxy_server.py.
    """
    res = find_devtools()
    if res:
        return res["devtools_port"], res["backend_port"]
    return None, None
