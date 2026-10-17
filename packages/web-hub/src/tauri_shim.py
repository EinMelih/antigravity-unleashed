from pathlib import Path

SHIM_JS_PATH = Path(__file__).resolve().parent / "tauri_shim.js"
AMS_BRIDGE_PATH = Path(__file__).resolve().parent / "desktop_ams_bridge.js"


def get_tauri_shim(code_server_port: int, home_dir: str) -> bytes:
    """Reads tauri_shim.js and interpolates the code server port and user home directory."""
    try:
        with open(SHIM_JS_PATH, "rb") as f:
            content = f.read()

        # Replace code server port placeholder
        content = content.replace(b"{CODE_SERVER_PORT}", str(code_server_port).encode())

        # Replace home directory placeholder
        escaped_home = home_dir.replace('\\', '\\\\')
        content = content.replace(b"{HOME_DIR}", escaped_home.encode())
        bridge = AMS_BRIDGE_PATH.read_bytes()
        return b'<script>window.__AMS_WEB_MIRROR_PENDING = true;</script>\n' + content + b'\n<script>\n' + bridge + b'\n</script>\n'
    except Exception as e:
        print(f"[SHIM] ❌ Error loading tauri_shim.js: {e}", flush=True)
        return b""


def inject_shim(html_bytes: bytes, code_server_port: int, home_dir: str) -> bytes:
    """Injects the Tauri shim into the HTML bytes payload."""
    shim = get_tauri_shim(code_server_port, home_dir)
    if not shim:
        return html_bytes

    pos = html_bytes.find(b"</head>")
    if pos != -1:
        return html_bytes[:pos] + shim + html_bytes[pos:]

    pos = html_bytes.find(b"<script")
    if pos != -1:
        return html_bytes[:pos] + shim + html_bytes[pos:]

    return html_bytes
