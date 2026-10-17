"""
Antigravity Auto-Healer v1.0 — Refactored Entry Point
=========================================================
All logic is refactored into the `src/` package.
This file serves as a backwards-compatible launcher.
"""
import sys
from pathlib import Path

# Add project root to python path to ensure imports work correctly
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.healer_server import main

if __name__ == '__main__':
    main()
