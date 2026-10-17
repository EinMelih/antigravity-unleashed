import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.watchdog_db import UptimeDB


class UptimeDatabaseTests(unittest.TestCase):
    def test_new_database_uses_incremental_auto_vacuum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = UptimeDB(Path(temp_dir) / "uptime.db")

            connection = database._get_conn()
            try:
                mode = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
            finally:
                connection.close()

            self.assertEqual(mode, 2)

    def test_service_history_uses_index_without_temporary_sort(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = UptimeDB(Path(temp_dir) / "uptime.db")

            connection = database._get_conn()
            try:
                query_plan = [
                    str(row[3])
                    for row in connection.execute(
                        "EXPLAIN QUERY PLAN SELECT * FROM health_checks "
                        "WHERE service = ? ORDER BY id DESC LIMIT ?",
                        ("hub", 50),
                    )
                ]
            finally:
                connection.close()

            self.assertTrue(
                any("idx_hc_service_id" in detail for detail in query_plan),
                query_plan,
            )
            self.assertFalse(
                any("TEMP B-TREE" in detail for detail in query_plan),
                query_plan,
            )

    def test_cleanup_removes_only_expired_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = UptimeDB(Path(temp_dir) / "uptime.db")
            old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            connection = database._get_conn()
            try:
                connection.execute(
                    "INSERT INTO health_checks(timestamp, service, status) VALUES (?, ?, ?)",
                    (old_timestamp, "hub", "up"),
                )
                connection.execute(
                    "INSERT INTO health_checks(timestamp, service, status) VALUES (?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), "hub", "up"),
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(database.cleanup_old(7), 1)
            connection = database._get_conn()
            try:
                remaining = int(connection.execute("SELECT COUNT(*) FROM health_checks").fetchone()[0])
            finally:
                connection.close()
            self.assertEqual(remaining, 1)


if __name__ == "__main__":
    unittest.main()
