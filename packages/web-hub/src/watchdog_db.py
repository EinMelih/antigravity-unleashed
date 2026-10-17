import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# Setup database path
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
LOG_DIR = BASE_DIR / "logs"
DB_PATH = LOG_DIR / "uptime.db"


class UptimeDB:
    """SQLite Database wrapper for health check history logs and alerts."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            # New databases release deleted pages incrementally instead of
            # keeping their historical high-water mark forever.
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS health_checks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    service     TEXT    NOT NULL,
                    status      TEXT    NOT NULL,
                    response_ms REAL,
                    error       TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_hc_service_ts
                    ON health_checks(service, timestamp);
                CREATE INDEX IF NOT EXISTS idx_hc_service_id
                    ON health_checks(service, id DESC);
                CREATE INDEX IF NOT EXISTS idx_hc_ts
                    ON health_checks(timestamp);

                CREATE TABLE IF NOT EXISTS alerts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    service     TEXT    NOT NULL,
                    level       TEXT    NOT NULL,
                    message     TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_ts
                    ON alerts(timestamp);
            """)
            conn.commit()
            print(f"[DB] Initialisiert: {self.db_path}", flush=True)
        finally:
            conn.close()

    def log_check(self, service: str, status: str, response_ms: Optional[float], error: Optional[str]) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO health_checks (timestamp, service, status, response_ms, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), service, status, response_ms, error),
            )
            conn.commit()
        finally:
            conn.close()

    def log_alert(self, service: str, level: str, message: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO alerts (timestamp, service, level, message) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), service, level, message),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_checks_for_service(self, service: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM health_checks WHERE service = ? ORDER BY id DESC LIMIT ?",
                (service, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def calc_uptime(self, service: str, hours: int) -> Optional[float]:
        """Calculates the percentage uptime over the last N hours."""
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM health_checks WHERE service = ? AND timestamp >= ?",
                (service, since),
            ).fetchone()[0]
            if total == 0:
                return None
            up = conn.execute(
                "SELECT COUNT(*) FROM health_checks "
                "WHERE service = ? AND timestamp >= ? AND status = 'up'",
                (service, since),
            ).fetchone()[0]
            return round((up / total) * 100, 2)
        finally:
            conn.close()

    def cleanup_old(self, days: int = 30) -> int:
        """Prunes check logs and alert logs older than N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM health_checks WHERE timestamp < ?", (cutoff,)
            )
            deleted_checks = cur.rowcount
            cur2 = conn.execute(
                "DELETE FROM alerts WHERE timestamp < ?", (cutoff,)
            )
            deleted_alerts = cur2.rowcount
            conn.commit()
            total = deleted_checks + deleted_alerts
            conn.execute("PRAGMA incremental_vacuum(512)")
            conn.execute("PRAGMA optimize")
            if total > 0:
                print(f"[DB] Bereinigt: {deleted_checks} Checks, {deleted_alerts} Alerts (älter als {days} Tage)", flush=True)
            return total
        finally:
            conn.close()
