"""Keep the dedicated API desktop window out of sight (and out of the taskbar) on demand.

The window is NOT minimized or SW_HIDE-n: Chromium throttles hidden/minimized renderers,
which would stall the API. Instead the window becomes a tool window (no taskbar button)
and is parked far outside the visible desktop. The preference is persisted in a small JSON
file shared with the main Anti-Gravity app (its quick menu toggles it).
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

STATE_PATH = Path.home() / ".gemini" / "antigravity" / "scratch" / "api_window_visibility.json"
POLL_SECONDS = 1.0
PARK_X = PARK_Y = -32000

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

_thread_lock = threading.Lock()
_thread: threading.Thread | None = None


def read_visible(path: Path = STATE_PATH) -> bool:
    """Default is hidden: the API should run headless-like unless the user asks otherwise."""
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("visible", False))
    except (OSError, ValueError, AttributeError):
        return False


def write_visible(visible: bool, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"visible": bool(visible), "updated_at": time.time()}), encoding="utf-8")
    os.replace(temporary, path)


def _user32():
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.GetWindow.restype = wintypes.HWND
    return user32


def _top_level_windows(user32, pids: set[int]) -> list[int]:
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value not in pids or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value == "Chrome_WidgetWin_1":
            found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def apply_visibility(pids: set[int], visible: bool) -> int:
    """Apply the preference to all main windows of the given processes; returns changed count."""
    if os.name != "nt" or not pids:
        return 0
    user32 = _user32()
    changed = 0
    for hwnd in _top_level_windows(user32, pids):
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        parked = bool(style & WS_EX_TOOLWINDOW) and not (style & WS_EX_APPWINDOW)
        if visible:
            if not parked:
                continue
            new_style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
            user32.SetWindowPos(hwnd, 0, 120, 80, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        else:
            if parked and not user32.IsIconic(hwnd) and rect.left < -20000:
                continue
            new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
            user32.SetWindowPos(hwnd, 0, PARK_X, PARK_Y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        changed += 1
    return changed


def listening_pids(port: int) -> set[int]:
    """Process (and children) that own the API DevTools port: the API desktop instance."""
    import psutil

    roots = {
        conn.pid for conn in psutil.net_connections(kind="tcp")
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port and conn.pid
    }
    pids = set(roots)
    for pid in roots:
        try:
            pids.update(child.pid for child in psutil.Process(pid).children(recursive=True))
        except psutil.Error:
            pass
    return pids


def _loop(devtools_port: int) -> None:
    while True:
        try:
            apply_visibility(listening_pids(devtools_port), read_visible())
        except Exception:
            pass  # enforcing a cosmetic preference must never break the API
        time.sleep(POLL_SECONDS)


def start_enforcer(devtools_port: int) -> None:
    """Start the background enforcer once per process."""
    global _thread
    if os.name != "nt":
        return
    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, args=(devtools_port,), name="api-window-enforcer", daemon=True)
            _thread.start()
