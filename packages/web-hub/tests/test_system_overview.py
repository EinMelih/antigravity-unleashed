import tempfile
import unittest
from pathlib import Path

from src.database import DATABASE_SCHEMA_VERSION, Database
from src.proxy_server import create_app
from src.system_overview import (
    _service_health_details,
    database_snapshot,
    deployment_snapshot,
)


class SystemOverviewTests(unittest.TestCase):
    def test_api_bridge_health_details_are_allowlisted_and_gate_readiness(self):
        details = _service_health_details(
            "api_bridge",
            {
                "ready": False,
                "cdp": {"status": "connected", "bridge": "missing"},
                "authentication": {"token": "must-not-leak"},
            },
        )

        self.assertEqual(
            details,
            {
                "ready": False,
                "cdp_status": "connected",
                "bridge": "missing",
            },
        )
        self.assertNotIn("authentication", details)

    def test_database_snapshot_is_integrity_checked_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "private" / "system.db")

            snapshot = database_snapshot(database)

            self.assertEqual(snapshot["engine"], "SQLite")
            self.assertEqual(snapshot["filename"], "system.db")
            self.assertEqual(snapshot["journal_mode"], "wal")
            self.assertEqual(snapshot["schema_version"], DATABASE_SCHEMA_VERSION)
            self.assertEqual(snapshot["quick_check"], "ok")
            self.assertEqual(snapshot["foreign_key_violations"], 0)
            self.assertNotIn(temp_dir, str(snapshot))

    def test_deployment_snapshot_requires_persistent_state(self):
        root = Path(__file__).resolve().parents[1]

        snapshot = deployment_snapshot(root)

        checks = {item["id"]: item for item in snapshot["checks"]}
        self.assertTrue(checks["persistent_database"]["ready"])
        self.assertTrue(checks["persistent_projects"]["ready"])
        self.assertTrue(snapshot["source_manifest_available"])
        self.assertTrue(snapshot["configured"])

    def test_system_overview_route_is_registered(self):
        app = create_app(backend_port=9222)

        resources = {resource.canonical for resource in app.router.resources()}

        self.assertIn("/api/system/overview", resources)


if __name__ == "__main__":
    unittest.main()
