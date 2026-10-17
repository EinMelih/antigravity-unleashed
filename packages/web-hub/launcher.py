import subprocess
import time
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

services = [
    ("proxy_server.py", "logs/proxy.log", "logs/proxy.err.log"),
    ("api_bridge.py", "logs/api_bridge.log", "logs/api_bridge.err.log"),
    ("session_manager.py", "logs/session_manager.log", "logs/session_manager.err.log"),
    ("auto_healer.py", "logs/auto_healer.log", "logs/auto_healer.err.log"),
    ("watchdog_monitor.py", "logs/watchdog.log", "logs/watchdog.err.log"),
]

print("Launching services via subprocess...")
for script, stdout_file, stderr_file in services:
    script_path = BASE_DIR / script
    stdout_p = open(BASE_DIR / stdout_file, "a", encoding="utf-8")
    stderr_p = open(BASE_DIR / stderr_file, "a", encoding="utf-8")
    
    p = subprocess.Popen(
        [sys.executable, "-u", str(script_path)],
        stdout=stdout_p,
        stderr=stderr_p,
        cwd=str(BASE_DIR),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    print(f"Started {script} with PID {p.pid}")
    time.sleep(1)

print("All processes launched.")
