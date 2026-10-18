"""
Privacy and Portability Compliance Unit Tests for packages/antigravity-reverse.

Verifies zero private user identifiers or hardcoded local user machine paths
remain in reverse engineering catalogs, documentation, scripts, or source files.
"""

import os
import re
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class TestReversePrivacyCleanliness(unittest.TestCase):
    """Verifies privacy sanitization and portable path hygiene across the package."""

    def setUp(self):
        self.package_root = PACKAGE_ROOT
        token_user = r"Users[/\\]+" + "EinMelih"
        token_gho = "gh" + "o_"
        token_pers = "user_" + "personality"
        token_win11 = "".join(["win11 ", "alt ", "backup"])
        token_klein = "Klein" + "anzeigen"
        token_luchs = "Luchs" + "Watch"
        token_snipe = "Snipe" + "Tower"
        token_gams = "Gams" + "Go"

        self.forbidden_patterns = [
            (token_user, re.compile(token_user, re.IGNORECASE)),
            (token_gho, re.compile(token_gho, re.IGNORECASE)),
            (token_pers, re.compile(token_pers, re.IGNORECASE)),
            (token_win11, re.compile(token_win11, re.IGNORECASE)),
            (token_klein, re.compile(token_klein, re.IGNORECASE)),
            (token_luchs, re.compile(token_luchs, re.IGNORECASE)),
            (token_snipe, re.compile(token_snipe, re.IGNORECASE)),
            (token_gams, re.compile(token_gams, re.IGNORECASE)),
        ]

    def test_zero_forbidden_patterns_across_package(self):
        """Scans all package files to ensure 0 forbidden privacy patterns occur."""
        violations = []
        scanned_count = 0

        # Scan catalogs, docs, scripts, src, tests, proto
        target_dirs = [
            self.package_root / "catalog",
            self.package_root / "docs",
            self.package_root / "scripts",
            self.package_root / "src",
            self.package_root / "tests",
            self.package_root / "proto",
        ]

        for target_dir in target_dirs:
            if not target_dir.exists():
                continue
            for p in target_dir.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() in [".pyc", ".pyo", ".png", ".jpg", ".svg"]:
                    continue

                scanned_count += 1
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            for name, pattern in self.forbidden_patterns:
                                match = pattern.search(line)
                                if match:
                                    violations.append({
                                        "file": str(p.relative_to(self.package_root)),
                                        "line": line_num,
                                        "pattern": name,
                                        "matched": match.group(0),
                                        "context": line.strip()[:100],
                                    })
                except Exception as e:
                    violations.append({
                        "file": str(p.relative_to(self.package_root)),
                        "line": 0,
                        "pattern": "READ_ERROR",
                        "matched": str(e),
                        "context": "",
                    })

        self.assertGreater(scanned_count, 15, "Expected to scan substantial package files")
        failure_msg = "\n".join(
            f"[{v['pattern']}] {v['file']}:{v['line']} -> {v['matched']}: {v['context']}"
            for v in violations
        )
        self.assertEqual(len(violations), 0, f"Found {len(violations)} privacy violations:\n{failure_msg}")

    def test_binary_analysis_uses_portable_placeholders(self):
        """Verifies binary_analysis.json uses portable environment variable placeholders."""
        import json
        catalog_path = self.package_root / "catalog" / "binary_analysis.json"
        self.assertTrue(catalog_path.exists())

        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Host paths in binaries must use %LOCALAPPDATA%
        for bin_key, bin_info in data.get("binaries", {}).items():
            if "host_path" in bin_info:
                host_path = bin_info["host_path"]
                self.assertTrue(
                    host_path.startswith("%LOCALAPPDATA%"),
                    f"Binary {bin_key} host_path '{host_path}' must start with %LOCALAPPDATA%"
                )
                self.assertNotIn("Users", host_path)

        # Storage paths must use environment variables
        storage = data.get("local_storage_schemas", {})
        self.assertIn("%USERPROFILE%", storage.get("base_directory", ""))
        self.assertIn("%USERPROFILE%", storage.get("config_directory", ""))
        self.assertIn("%APPDATA%", storage.get("appdata_directory", ""))


if __name__ == "__main__":
    unittest.main()
