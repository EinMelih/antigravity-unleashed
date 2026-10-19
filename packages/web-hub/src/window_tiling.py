import ctypes
import os
import asyncio
from src.parallel_cdp import ParallelCDPManager

if os.name == "nt":
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
else:
    wintypes = None
    user32 = None
    WNDENUMPROC = None

SPI_GETWORKAREA = 48
SW_RESTORE = 9

def get_antigravity_hwnds(allowed_process_ids=None) -> list:
    """Returns window handles (HWNDs) for visible Antigravity widget windows."""
    if os.name != "nt" or user32 is None or WNDENUMPROC is None:
        return []
    hwnds = []

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if allowed_process_ids is not None:
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value not in allowed_process_ids:
                return True

        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)

        title_len = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if title_len > 0:
            title_buf = ctypes.create_unicode_buffer(title_len + 1)
            user32.GetWindowTextW(hwnd, title_buf, title_len + 1)
            title = title_buf.value

        # Match class and title
        if class_buf.value == "Chrome_WidgetWin_1" and "antigravity" in title.lower():
            hwnds.append(hwnd)
        return True

    callback_func = WNDENUMPROC(callback)
    user32.EnumWindows(callback_func, 0)
    hwnds.sort()
    return hwnds

def tile_windows(hwnds: list, *, focus=True):
    """Tiles the given window handles based on count according to the layout contract."""
    if os.name != "nt" or user32 is None:
        return
    num_windows = len(hwnds)
    if num_windows == 0:
        return

    rect = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)

    screen_x = rect.left
    screen_y = rect.top
    screen_w = rect.right - rect.left
    screen_h = rect.bottom - rect.top

    if num_windows == 1:
        user32.ShowWindow(hwnds[0], SW_RESTORE if focus else 4)
        user32.MoveWindow(hwnds[0], screen_x, screen_y, screen_w, screen_h, True)
        if focus: user32.SetForegroundWindow(hwnds[0])
    elif num_windows == 2:
        w = screen_w // 2
        for i, hwnd in enumerate(hwnds):
            user32.ShowWindow(hwnd, SW_RESTORE if focus else 4)
            user32.MoveWindow(hwnd, screen_x + i * w, screen_y, w, screen_h, True)
            if focus: user32.SetForegroundWindow(hwnd)
    elif num_windows == 3:
        w = screen_w // 2
        h = screen_h // 2
        # Left main
        user32.ShowWindow(hwnds[0], SW_RESTORE if focus else 4)
        user32.MoveWindow(hwnds[0], screen_x, screen_y, w, screen_h, True)
        # Right Top
        user32.ShowWindow(hwnds[1], SW_RESTORE if focus else 4)
        user32.MoveWindow(hwnds[1], screen_x + w, screen_y, w, h, True)
        # Right Bottom
        user32.ShowWindow(hwnds[2], SW_RESTORE if focus else 4)
        user32.MoveWindow(hwnds[2], screen_x + w, screen_y + h, w, h, True)
        # Focus windows in reverse order to keep them correctly layered
        for hwnd in reversed(hwnds):
            if focus: user32.SetForegroundWindow(hwnd)
    else:
        # 2x2 Grid (max 4 windows)
        w = screen_w // 2
        h = screen_h // 2
        for i, hwnd in enumerate(hwnds[:4]):
            user32.ShowWindow(hwnd, SW_RESTORE if focus else 4)
            row, col = i // 2, i % 2
            user32.MoveWindow(hwnd, screen_x + col * w, screen_y + row * h, w, h, True)
            if focus: user32.SetForegroundWindow(hwnd)

async def duplicate_window_via_cdp(ws_url: str) -> bool:
    """Triggers window duplication by clicking .antigravity-duplicate-btn via CDP."""
    from src.cdp_client import AntigravityCDP
    client = AntigravityCDP()
    try:
        await client.connect(ws_url)
        await client.inject_bridge()
        success = await client.evaluate(
            "const btn = document.querySelector('.antigravity-duplicate-btn'); if (btn) { btn.click(); true; } else { false; }",
            timeout=5.0
        )
        print(f"[WindowTiling] Clicked duplicate button via CDP: {success}", flush=True)
        return bool(success)
    except Exception as e:
        print(f"[WindowTiling] Click duplicate error: {e}", flush=True)
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def ensure_and_tile_windows(target_count: int, *, manager=None) -> list:
    """Ensures at least target_count windows are open and tiles them."""
    manager = manager or ParallelCDPManager()
    owned_profile = getattr(manager, 'profile_runtime', None)
    def scoped_handles():
        return get_antigravity_hwnds(set(owned_profile.get_process_ids())) if owned_profile else get_antigravity_hwnds()
    devtools_port = await manager.get_devtools_port()
    page_targets = await manager.get_all_page_targets(devtools_port)

    current_count = len(page_targets)
    if current_count >= target_count:
        print(f"[WindowTiling] Enough windows open ({current_count} >= {target_count}). Tiling.", flush=True)
        hwnds = scoped_handles()
        tile_windows(hwnds, focus=not bool(owned_profile))
        return page_targets

    needed = target_count - current_count
    print(f"[WindowTiling] Need {target_count} windows, currently have {current_count}. Spawning {needed}...", flush=True)

    ws_url = page_targets[0]["webSocketDebuggerUrl"]
    for i in range(needed):
        print(f"[WindowTiling] Duplicating window {i+1}/{needed}...", flush=True)
        if owned_profile:
            await manager.open_duplicate_window(devtools_port)
            success = True
        else:
            success = await duplicate_window_via_cdp(ws_url)
        if not success:
            print("[WindowTiling] Duplication failed. Breaking out of spawn loop.", flush=True)
            break
        # Poll for new page target
        for attempt in range(30):
            await asyncio.sleep(0.5)
            updated_targets = await manager.get_all_page_targets(devtools_port)
            if len(updated_targets) > current_count:
                print(f"[WindowTiling] Spawn success. Total now: {len(updated_targets)}", flush=True)
                page_targets = updated_targets
                current_count = len(page_targets)
                break
        else:
            print("[WindowTiling] Warning: Timeout waiting for new target to register.", flush=True)

    await asyncio.sleep(1.5)  # Wait for OS window layout stability
    hwnds = scoped_handles()
    print(f"[WindowTiling] Tiling {len(hwnds)} windows.", flush=True)
    tile_windows(hwnds, focus=not bool(owned_profile))
    return page_targets
