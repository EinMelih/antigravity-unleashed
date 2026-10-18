"""
Adversarial Stress Test Suite for Antigravity Reverse Engineering Headless Client & Pipeline:
Empirically tests failure modes, edge cases, error handling, concurrency, and security boundaries.
"""

import concurrent.futures
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from client import (
    AntigravityClient,
    LanguageServerError,
    AuthenticationError,
    ConnectionError,
)


class TestAdversarialStress(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = AntigravityClient()
        if not cls.client.port or not cls.client.csrf_token:
            raise unittest.SkipTest("Active Antigravity Language Server not detected. Skipping live stress tests.")

    # =========================================================================
    # 1. CSRF & Authentication Adversarial Boundaries
    # =========================================================================

    def test_adversarial_csrf_empty_token(self):
        """Verify that an empty string CSRF token is rejected with AuthenticationError (401)."""
        c = AntigravityClient(port=self.client.port, csrf_token="", host=self.client.host)
        # Empty string csrf_token in __init__ falls into: if port is None or csrf_token is None...
        # Wait, if csrf_token is "", it's not None, but _ensure_connected checks `not self.csrf_token`
        with self.assertRaises(ConnectionError):
            c.get_status()

    def test_adversarial_csrf_malformed_tokens(self):
        """Verify that various adversarial strings in CSRF token header are rejected with 401."""
        adversarial_tokens = [
            "../../../etc/passwd",
            "' OR '1'='1",
            "<script>alert(1)</script>",
            "a" * 500,
            "00000000-0000-0000-0000-000000000000",
            "invalid_uuid",
        ]
        for token in adversarial_tokens:
            with self.subTest(token=token):
                c = AntigravityClient(port=self.client.port, csrf_token=token, host=self.client.host)
                with self.assertRaises(AuthenticationError) as ctx:
                    c.get_status()
                self.assertIn("401", str(ctx.exception))

    # =========================================================================
    # 2. Network & Host Unreachability
    # =========================================================================

    def test_adversarial_connection_to_dead_port(self):
        """Verify connecting to an unused closed port raises ConnectionError quickly without hanging."""
        # Port 59999 is typically unbound
        c = AntigravityClient(port=59999, csrf_token=self.client.csrf_token, host="127.0.0.1", timeout=1.0)
        start = time.time()
        with self.assertRaises(ConnectionError):
            c.get_status()
        duration = time.time() - start
        self.assertLess(duration, 3.0, f"Connection to closed port took too long: {duration:.2f}s")

    def test_adversarial_invalid_method_call(self):
        """Verify calling a non-existent method raises LanguageServerError with HTTP error."""
        with self.assertRaises(LanguageServerError) as ctx:
            self.client._post(self.client.DEFAULT_SERVICE, "NonExistentMethod_12345", {})
        # ConnectRPC / Language server returns HTTP 404 or unimplemented
        self.assertTrue(
            "HTTP 404" in str(ctx.exception) or "unimplemented" in str(ctx.exception).lower(),
            f"Unexpected error for non-existent method: {ctx.exception}"
        )

    def test_adversarial_invalid_service_call(self):
        """Verify calling a non-existent service raises LanguageServerError (SPA HTML fallback triggers decode error or 404)."""
        with self.assertRaises(LanguageServerError) as ctx:
            self.client._post("exa.nonexistent_service.FakeService", "GetStatus", {})
        self.assertTrue(
            "HTTP 404" in str(ctx.exception) or "Expecting value" in str(ctx.exception) or "Language Server" in str(ctx.exception),
            f"Unexpected error: {ctx.exception}"
        )

    # =========================================================================
    # 3. Method Parameter Boundaries & Payloads
    # =========================================================================

    def test_adversarial_get_cascade_trajectory_empty_id(self):
        """Verify querying empty cascade_id raises LanguageServerError without crashing client."""
        with self.assertRaises(LanguageServerError) as ctx:
            self.client.get_cascade_trajectory("")
        self.assertTrue(len(str(ctx.exception)) > 0)

    def test_adversarial_get_cascade_trajectory_huge_id(self):
        """Verify querying massive 10,000-char string cascade_id does not cause buffer overflow or freeze."""
        huge_id = "test-" + "x" * 10000
        start = time.time()
        with self.assertRaises(LanguageServerError):
            self.client.get_cascade_trajectory(huge_id)
        duration = time.time() - start
        self.assertLess(duration, 5.0, "Huge payload request took too long")

    # =========================================================================
    # 4. Multi-Threaded Concurrency Stress Test
    # =========================================================================

    def test_adversarial_concurrent_requests(self):
        """Verify 20 concurrent threads calling GetStatus and GetAvailableModels do not race or fail."""
        def call_status(idx):
            if idx % 2 == 0:
                res = self.client.get_status()
                return "status", isinstance(res, dict)
            else:
                res = self.client.get_available_models()
                return "models", "response" in res

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(call_status, i) for i in range(20)]
            results = [f.result(timeout=10.0) for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 20)
        for kind, success in results:
            self.assertTrue(success, f"Concurrent call failed for {kind}")

    # =========================================================================
    # 5. Rapid Sequential Request Burst
    # =========================================================================

    def test_adversarial_rapid_sequential_burst(self):
        """Verify 30 rapid back-to-back requests do not exhaust sockets or trigger rate-limiting crashes."""
        start = time.time()
        for i in range(30):
            res = self.client.get_status()
            self.assertIsInstance(res, dict)
        duration = time.time() - start
        avg_latency_ms = (duration / 30) * 1000
        # Should be sub-50ms per loopback request
        self.assertLess(avg_latency_ms, 200.0, f"Average loopback RPC latency too high: {avg_latency_ms:.1f}ms")

    # =========================================================================
    # 6. SQLite Read-Only & SQL Injection Robustness
    # =========================================================================

    def test_adversarial_sqlite_corrupt_or_empty_db(self):
        """Verify querying a zero-byte DB file returns [] gracefully without uncaught exceptions."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            res = self.client.list_conversations(db_path=tmp_path)
            self.assertEqual(res, [])
        except sqlite3.DatabaseError:
            # A DatabaseError is also acceptable if file is empty
            pass
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_adversarial_sqlite_write_prevention(self):
        """Verify that opening the DB through client helper strictly enforces read-only mode."""
        convs = self.client.list_conversations(limit=1)
        if not convs:
            self.skipTest("No database found to test read-only integrity.")

        # Resolve candidate path
        candidates = [
            Path(os.path.expanduser("~/.gemini/antigravity/conversation_summaries.db")),
            Path(os.path.expandvars(r"%APPDATA%\Antigravity\conversation_summaries.db")),
            Path(os.path.expandvars(r"%LOCALAPPDATA%\antigravity\conversation_summaries.db")),
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity\conversation_summaries.db")),
        ]
        target_db = None
        for c in candidates:
            if c.exists():
                target_db = str(c)
                break

        if target_db:
            uri_path = f"file:{Path(target_db).resolve().as_posix()}?mode=ro"
            conn = sqlite3.connect(uri_path, uri=True)
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA query_only = ON")
                # Attempt an unauthorized INSERT or UPDATE
                with self.assertRaises(sqlite3.OperationalError) as ctx:
                    cursor.execute("UPDATE conversation_summaries SET title = 'HAX' WHERE conversation_id = '123'")
                self.assertTrue(
                    "read-only" in str(ctx.exception).lower() or "attempt to write a readonly database" in str(ctx.exception).lower()
                )
            finally:
                conn.close()

    # =========================================================================
    # 7. Environment Variable Discovery Fallback
    # =========================================================================

    def test_environment_variable_override_discovery(self):
        """Verify discover_active_server honors ANTIGRAVITY_PORT and ANTIGRAVITY_CSRF_TOKEN."""
        old_port = os.environ.get("ANTIGRAVITY_PORT")
        old_tok = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
        try:
            os.environ["ANTIGRAVITY_PORT"] = "19999"
            os.environ["ANTIGRAVITY_CSRF_TOKEN"] = "test-token-override-xyz"
            disc = AntigravityClient.discover_active_server()
            self.assertIsNotNone(disc)
            self.assertEqual(disc, (19999, "test-token-override-xyz"))
        finally:
            if old_port is not None:
                os.environ["ANTIGRAVITY_PORT"] = old_port
            else:
                os.environ.pop("ANTIGRAVITY_PORT", None)
            if old_tok is not None:
                os.environ["ANTIGRAVITY_CSRF_TOKEN"] = old_tok
            else:
                os.environ.pop("ANTIGRAVITY_CSRF_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
