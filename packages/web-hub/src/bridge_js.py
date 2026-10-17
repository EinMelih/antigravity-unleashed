# JavaScript Bridge injected into the Antigravity Webview
# The JS payload is stored in bridge.js and loaded at import time.
from pathlib import Path

_JS_PATH = Path(__file__).resolve().parent / 'bridge.js'
BRIDGE_JS = _JS_PATH.read_text(encoding='utf-8')
