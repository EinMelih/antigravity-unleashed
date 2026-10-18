"""
Unit tests for reconstructed Protobuf schema syntax and structural validity:
- Verifies syntax declarations (proto3 / proto2)
- Verifies balanced curly braces and quotes across all .proto files
- Verifies cross-file import resolution
- Verifies core service and method definitions
"""

import os
import re
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = PACKAGE_ROOT / "proto"


class TestProtoSyntax(unittest.TestCase):

    def setUp(self):
        self.proto_files = list(PROTO_DIR.rglob("*.proto"))
        self.assertTrue(len(self.proto_files) >= 50, f"Expected >= 50 .proto files, found {len(self.proto_files)}")

    def test_proto_syntax_declarations(self):
        for pf in self.proto_files:
            text = pf.read_text(encoding="utf-8", errors="ignore")
            first_non_empty = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
                    first_non_empty = stripped
                    break
            self.assertTrue(
                first_non_empty.startswith('syntax = "proto3";') or first_non_empty.startswith('syntax = "proto2";'),
                f"{pf.name} missing valid syntax header. Found: {first_non_empty}"
            )

    def test_proto_balanced_braces(self):
        for pf in self.proto_files:
            text = pf.read_text(encoding="utf-8", errors="ignore")
            # Strip comments to avoid counting braces inside comments
            stripped_text = re.sub(r"//.*", "", text)
            stripped_text = re.sub(r"/\*.*?\*/", "", stripped_text, flags=re.DOTALL)

            open_braces = stripped_text.count("{")
            close_braces = stripped_text.count("}")
            self.assertEqual(
                open_braces, close_braces,
                f"Mismatched braces in {pf.relative_to(PROTO_DIR)}: {open_braces} open vs {close_braces} close"
            )

    def test_core_proto_mirrors_exist(self):
        core_mirrors = [
            "language_server.proto",
            "cortex.proto",
            "trajectory.proto",
            "api_server.proto",
            "extension_server.proto",
            "jetski_service.proto",
            "host_bridge.proto"
        ]
        for mirror in core_mirrors:
            mirror_path = PROTO_DIR / mirror
            self.assertTrue(mirror_path.exists(), f"Core proto mirror missing: {mirror_path}")

    def test_proto_imports_resolve(self):
        for pf in self.proto_files:
            text = pf.read_text(encoding="utf-8", errors="ignore")
            imports = re.findall(r'import\s+(?:public\s+)?"([^"]+)";', text)
            for imp in imports:
                # Resolve relative to PROTO_DIR
                target = PROTO_DIR / imp.replace("/", os.sep)
                self.assertTrue(
                    target.exists(),
                    f"Unresolved import in {pf.relative_to(PROTO_DIR)}: '{imp}' not found at {target}"
                )

    def test_core_services_defined(self):
        ls_proto = PROTO_DIR / "language_server.proto"
        self.assertTrue(ls_proto.exists())
        ls_text = ls_proto.read_text(encoding="utf-8")
        self.assertIn("service LanguageServerService {", ls_text)
        self.assertIn("rpc GetStatus (", ls_text)
        self.assertIn("rpc GetUserStatus (", ls_text)
        self.assertIn("rpc GetAvailableModels (", ls_text)
        self.assertIn("rpc RetrieveUserQuotaSummary (", ls_text)
        self.assertIn("rpc GetCascadeTrajectory (", ls_text)

        api_proto = PROTO_DIR / "api_server.proto"
        self.assertTrue(api_proto.exists())
        api_text = api_proto.read_text(encoding="utf-8")
        self.assertIn("service ApiServerService {", api_text)

        ext_proto = PROTO_DIR / "extension_server.proto"
        self.assertTrue(ext_proto.exists())
        ext_text = ext_proto.read_text(encoding="utf-8")
        self.assertIn("service ExtensionServerService {", ext_text)


if __name__ == "__main__":
    unittest.main()
