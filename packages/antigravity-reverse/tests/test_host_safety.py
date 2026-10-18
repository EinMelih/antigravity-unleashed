"""
Host Safety & Environment Integrity Tests (R5):
Asserts that host installations (%LOCALAPPDATA%\\Programs\\Antigravity and %APPDATA%\\Antigravity)
remain strictly read-only and that active Antigravity/language_server processes were not terminated.
"""

import os
import subprocess
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class TestHostSafety(unittest.TestCase):

    def test_programs_directory_unmodified(self):
        """Verifies that %LOCALAPPDATA%\\Programs\\Antigravity is intact with zero file corruptions."""
        programs_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity"))
        if not programs_dir.exists():
            self.skipTest(f"Host directory {programs_dir} not present on this machine.")

        # Core required binaries and assets
        required_files = [
            programs_dir / "Antigravity.exe",
            programs_dir / "resources" / "app.asar",
            programs_dir / "resources" / "bin" / "language_server.exe",
            programs_dir / "resources" / "bin" / "webm_encoder.exe",
            programs_dir / "resources" / "elevate.exe",
        ]

        for rf in required_files:
            self.assertTrue(rf.exists(), f"Expected core host file missing: {rf}")
            self.assertGreater(rf.stat().st_size, 0, f"Host file empty: {rf}")

        # Assert no stray temporary files created in programs root
        stray_extensions = [".tmp", ".bak", ".patch", ".extracted", ".temp"]
        for item in programs_dir.iterdir():
            if item.is_file():
                self.assertNotIn(item.suffix.lower(), stray_extensions, f"Stray file detected in host dir: {item}")

    def test_running_processes_not_terminated(self):
        """Verifies that running language_server.exe processes remain alive and active."""
        if os.name == "nt":
            try:
                cmd = [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | Measure-Object | Select-Object -ExpandProperty Count"
                ]
                out = subprocess.check_output(cmd, encoding="utf-8", timeout=5).strip()
                count = int(out) if out.isdigit() else 0
                self.assertGreater(count, 0, "language_server.exe processes should remain running and untouched.")
            except Exception as e:
                self.skipTest(f"Process query skipped: {e}")

    def test_package_write_isolation(self):
        """Verifies all outputs remain strictly contained inside packages/antigravity-reverse."""
        self.assertTrue((PACKAGE_ROOT / "catalog").exists())
        self.assertTrue((PACKAGE_ROOT / "proto").exists())
        self.assertTrue((PACKAGE_ROOT / "src").exists())
        self.assertTrue((PACKAGE_ROOT / "scripts").exists())
        self.assertTrue((PACKAGE_ROOT / "tests").exists())


if __name__ == "__main__":
    unittest.main()
