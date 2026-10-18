"""
Unit tests for Antigravity machine-readable reverse engineering catalogs:
- catalog/ui_internals.json (IPC channels, shortcuts, feature flags, user tiers)
- catalog/rpc_schema.json (Connect/gRPC-Web services, methods, message types, enums)
- catalog/binary_analysis.json (Native binaries, CLI flags, env vars, CSRF auth, storage)
"""

import json
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = PACKAGE_ROOT / "catalog"


class TestCatalogs(unittest.TestCase):

    def test_ui_internals_catalog_validity_and_thresholds(self):
        catalog_path = CATALOG_DIR / "ui_internals.json"
        self.assertTrue(catalog_path.exists(), f"Missing catalog file: {catalog_path}")

        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertIn("ipc_channels", catalog)
        self.assertIn("actions", catalog)
        self.assertIn("feature_flags", catalog)
        self.assertIn("user_tiers", catalog)

        ipc = catalog["ipc_channels"]
        actions = catalog["actions"]
        flags = catalog["feature_flags"]
        tiers = catalog["user_tiers"]

        # Minimum threshold assertions (Scope & Requirements)
        self.assertGreaterEqual(len(ipc), 15, f"Expected >= 15 IPC channels, found {len(ipc)}")
        self.assertGreaterEqual(len(actions), 25, f"Expected >= 25 actions, found {len(actions)}")
        self.assertGreaterEqual(len(flags), 20, f"Expected >= 20 feature flags, found {len(flags)}")
        self.assertGreaterEqual(len(tiers), 4, f"Expected >= 4 user tiers, found {len(tiers)}")

        # Validate channel structure
        for ch in ipc:
            self.assertIn("channel", ch)
            self.assertIn("direction", ch)
            self.assertIn("type", ch)
            self.assertIn("source_file", ch)
            self.assertIn("return_type", ch)

        # Validate action structure
        for a in actions:
            self.assertIn("id", a)
            self.assertIn("label", a)
            self.assertIn("category", a)

        # Validate tier values
        tier_ids = {t["id"] for t in tiers}
        self.assertTrue({"USER_TIER_FREE", "USER_TIER_PRO", "USER_TIER_ENTERPRISE"}.issubset(tier_ids))

    def test_rpc_schema_catalog_validity_and_thresholds(self):
        catalog_path = CATALOG_DIR / "rpc_schema.json"
        self.assertTrue(catalog_path.exists(), f"Missing catalog file: {catalog_path}")

        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertIn("metadata", catalog)
        self.assertIn("services", catalog)
        self.assertIn("methods", catalog)
        self.assertIn("message_types", catalog)
        self.assertIn("enums", catalog)

        services = catalog["services"]
        methods = catalog["methods"]
        messages = catalog["message_types"]

        # Minimum threshold assertions
        self.assertGreaterEqual(len(services), 5, f"Expected >= 5 services, found {len(services)}")
        self.assertGreaterEqual(len(methods), 40, f"Expected >= 40 RPC methods, found {len(methods)}")
        self.assertGreaterEqual(len(messages), 40, f"Expected >= 40 message types, found {len(messages)}")

        service_names = {s["name"] for s in services}
        self.assertIn("LanguageServerService", service_names)
        self.assertIn("ApiServerService", service_names)
        self.assertIn("ExtensionServerService", service_names)

        method_names = {m["name"] for m in methods}
        self.assertIn("GetStatus", method_names)
        self.assertIn("GetUserStatus", method_names)
        self.assertIn("GetAvailableModels", method_names)
        self.assertIn("RetrieveUserQuotaSummary", method_names)
        self.assertIn("GetCascadeTrajectory", method_names)

        for m in methods:
            self.assertIn("path", m)
            self.assertIn("service", m)
            self.assertIn("request_type", m)
            self.assertIn("response_type", m)

    def test_binary_analysis_catalog_validity_and_thresholds(self):
        catalog_path = CATALOG_DIR / "binary_analysis.json"
        self.assertTrue(catalog_path.exists(), f"Missing catalog file: {catalog_path}")

        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        required_keys = [
            "binaries",
            "command_line_flags",
            "environment_variables",
            "http_connect_protocol",
            "csrf_authentication",
            "local_storage_schemas",
            "system_prompt_assembly",
            "upstream_google_cloud_apis",
            "verification"
        ]
        for key in required_keys:
            self.assertIn(key, catalog, f"Missing required top-level key: {key}")

        flags = catalog["command_line_flags"]["flags"]
        env_vars = catalog["environment_variables"]["variables"]
        ls_service = catalog["http_connect_protocol"]["services"]["exa.language_server_pb.LanguageServerService"]
        methods = ls_service["methods"]

        self.assertGreaterEqual(len(flags), 20, f"Expected >= 20 flags, found {len(flags)}")
        self.assertGreaterEqual(len(env_vars), 10, f"Expected >= 10 env vars, found {len(env_vars)}")
        self.assertGreaterEqual(len(methods), 40, f"Expected >= 40 LS methods, found {len(methods)}")
        self.assertEqual(len(methods), 342, f"Expected exactly 342 methods, found {len(methods)}")

        csrf = catalog["csrf_authentication"]
        self.assertEqual(csrf.get("header_name"), "x-codeium-csrf-token")
        self.assertEqual(csrf["rejection_behavior"]["missing_header"]["http_status"], 401)
        self.assertEqual(csrf["rejection_behavior"]["invalid_token"]["http_status"], 401)

        db_schemas = catalog["local_storage_schemas"]
        self.assertTrue("conversation_summaries_db" in db_schemas or "conversation_summaries.db" in db_schemas)


if __name__ == "__main__":
    unittest.main()
