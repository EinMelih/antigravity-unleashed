"""
End-to-End integration tests for Antigravity Headless Client:
Executes REAL, live read-only calls against the active local Language Server:
- GetStatus
- GetUserStatus
- GetAvailableModels
- RetrieveUserQuotaSummary
- GetCascadeTrajectory
- SQLite conversation_summaries.db inspection
- CSRF 401 unauthenticated rejection
"""

import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from client import AntigravityClient, AuthenticationError, LanguageServerError


class TestHeadlessClientLive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = AntigravityClient()
        if not cls.client.port or not cls.client.csrf_token:
            raise unittest.SkipTest(
                "Active Antigravity Language Server not detected on host. Skipping live network tests."
            )

    def test_live_get_status(self):
        """Tests live GetStatus RPC method over native Connect-Web HTTPS."""
        data = self.client.get_status()
        self.assertIsInstance(data, dict, "GetStatus must return a dictionary")

    def test_live_get_user_status(self):
        """Tests live GetUserStatus RPC method returning authenticated account info."""
        data = self.client.get_user_status()
        self.assertIsInstance(data, dict)
        self.assertIn("userStatus", data, "GetUserStatus response must contain 'userStatus'")
        user_status = data["userStatus"]
        self.assertIn("planStatus", user_status, "userStatus must contain 'planStatus'")
        self.assertIn("email", user_status, "userStatus must contain 'email'")

    def test_live_get_available_models(self):
        """Tests live GetAvailableModels RPC method returning active model catalog."""
        data = self.client.get_available_models()
        self.assertIsInstance(data, dict)
        self.assertIn("response", data, "GetAvailableModels must contain 'response'")
        models = data["response"].get("models", {})
        self.assertGreater(len(models), 0, "Expected at least 1 available model")

    def test_live_retrieve_user_quota_summary(self):
        """Tests live RetrieveUserQuotaSummary RPC method returning 5h and weekly token limits."""
        data = self.client.get_user_quota_summary()
        self.assertIsInstance(data, dict)
        self.assertIn("response", data, "RetrieveUserQuotaSummary must contain 'response'")
        groups = data["response"].get("groups", [])
        self.assertGreater(len(groups), 0, "Expected at least 1 quota group")

        group_names = [g.get("displayName", "") for g in groups]
        self.assertTrue(
            any("Gemini" in gn for gn in group_names),
            f"Expected Gemini quota group in {group_names}"
        )

    def test_live_csrf_rejection(self):
        """Tests that requests with an invalid CSRF token are strictly rejected with HTTP 401."""
        bad_token_client = AntigravityClient(
            port=self.client.port,
            csrf_token="invalid-csrf-token-000000000000",
            host=self.client.host
        )
        with self.assertRaises(AuthenticationError) as ctx:
            bad_token_client.get_status()
        self.assertIn("401", str(ctx.exception))
        self.assertIn("invalid CSRF token", str(ctx.exception))

    def test_list_conversations_sqlite(self):
        """Tests querying local conversation summaries from SQLite storage."""
        convs = self.client.list_conversations(limit=10)
        self.assertIsInstance(convs, list)
        if convs:
            first = convs[0]
            self.assertIn("conversation_id", first)
            self.assertIn("title", first)
            self.assertIn("last_modified_time", first)

    def test_live_cascade_trajectory_lookup(self):
        """Tests querying cascade trajectory for a known conversation session."""
        convs = self.client.list_conversations(limit=1)
        if not convs:
            self.skipTest("No conversations in local storage to query trajectory.")

        cid = convs[0]["conversation_id"]
        try:
            data = self.client.get_cascade_trajectory(cid)
            self.assertIsInstance(data, dict)
            self.assertTrue(
                "trajectory" in data or "numTotalSteps" in data or "status" in data,
                f"Trajectory lookup response keys: {list(data.keys())}"
            )
        except LanguageServerError as e:
            # If trajectory was cleared from active memory, server returns known error with ID
            self.assertIn("trajectory not found", str(e).lower())


if __name__ == "__main__":
    unittest.main()
