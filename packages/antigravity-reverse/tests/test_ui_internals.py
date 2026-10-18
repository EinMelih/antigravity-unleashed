import json
import unittest
from pathlib import Path

class TestUiInternalsCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_path = Path(__file__).resolve().parent.parent / "catalog" / "ui_internals.json"
        cls.assertTrue(catalog_path.exists(), f"Catalog file does not exist at {catalog_path}")
        with open(catalog_path, "r", encoding="utf-8") as f:
            cls.catalog = json.load(f)

    def test_json_structure(self):
        """Verify root keys and metadata exist."""
        self.assertIn("version", self.catalog)
        self.assertEqual(self.catalog["version"], "2.24.0")
        self.assertIn("summary", self.catalog)
        self.assertIn("ipc_channels", self.catalog)
        self.assertIn("actions", self.catalog)
        self.assertIn("feature_flags", self.catalog)
        self.assertIn("user_tiers", self.catalog)

    def test_ipc_channels_threshold(self):
        """Verify IPC channels count exceeds minimum threshold (>= 15)."""
        channels = self.catalog["ipc_channels"]
        self.assertGreaterEqual(len(channels), 15, f"Expected >= 15 IPC channels, found {len(channels)}")
        # Check required fields on each channel
        for ch in channels:
            self.assertIn("channel", ch)
            self.assertIn("direction", ch)
            self.assertIn("type", ch)
            self.assertIn("source_file", ch)
            self.assertIn("line_number", ch)
            self.assertIn("description", ch)
            self.assertIn(ch["direction"], ["renderer-to-main", "main-to-renderer"])

    def test_actions_threshold(self):
        """Verify actions count exceeds minimum threshold (>= 25)."""
        actions = self.catalog["actions"]
        self.assertGreaterEqual(len(actions), 25, f"Expected >= 25 actions, found {len(actions)}")
        # Check required fields on each action
        for act in actions:
            self.assertIn("id", act)
            self.assertIn("label", act)
            self.assertIn("category", act)
            self.assertIn("keybindings", act)
            self.assertIsInstance(act["keybindings"], list)

    def test_feature_flags_threshold(self):
        """Verify feature flags count exceeds minimum threshold (>= 20)."""
        flags = self.catalog["feature_flags"]
        self.assertGreaterEqual(len(flags), 20, f"Expected >= 20 feature flags, found {len(flags)}")
        # Check required fields on each flag
        for fl in flags:
            self.assertIn("key", fl)
            self.assertIn("type", fl)
            self.assertIn("description", fl)
            self.assertIn(fl["type"], ["mendel_experiment", "user_tier_entitlement", "settings_config"])

    def test_user_tiers(self):
        """Verify all 4 user tiers are cataloged."""
        tiers = self.catalog["user_tiers"]
        self.assertEqual(len(tiers), 4, f"Expected exactly 4 user tiers, found {len(tiers)}")
        tier_ids = {t["id"] for t in tiers}
        expected_ids = {"USER_TIER_UNSPECIFIED", "USER_TIER_FREE", "USER_TIER_PRO", "USER_TIER_ENTERPRISE"}
        self.assertEqual(tier_ids, expected_ids)

if __name__ == "__main__":
    unittest.main()
