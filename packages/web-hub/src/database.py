import sqlite3
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Setup database path
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
DB_ENV_VAR = "ANTIGRAVITY_HUB_DB"
DATABASE_SCHEMA_VERSION = 5
MANAGED_ANTIGRAVITY_CONVERSATION_STATES = frozenset(
    {"active", "archived", "deleted"}
)
_DEFAULT_DB_PATH = (
    Path("/data/antigravity-api/dashboard.db")
    if os.name != "nt" and (os.environ.get("ANTIGRAVITY_DOCKER") == "1" or Path("/data/antigravity-api").exists())
    else (BASE_DIR / "dashboard.db")
)
DB_PATH = Path(os.environ.get(DB_ENV_VAR, _DEFAULT_DB_PATH)).expanduser().resolve()
CORE_INDEX_QUERIES = (
    """
    CREATE INDEX IF NOT EXISTS idx_issues_project_github_number
    ON issues(project_id, github_number)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_projects_active_source_created
    ON projects(archived_at, source_kind, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_conversations_project_updated
    ON provider_conversations(project_id, archived, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_provider_messages_conversation_id
    ON provider_messages(conversation_id, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_managed_antigravity_conversations_state_updated
    ON managed_antigravity_conversations(state, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_request_logs_created_at
    ON api_request_logs(created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_request_logs_conversation_id
    ON api_request_logs(conversation_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_revert_events_conversation_id
    ON api_revert_events(conversation_id, created_at DESC)
    """,
)


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then release the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    """SQLite Database wrapper for managing Antigravity Hub persistence."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            factory=_ClosingConnection,
        )
        conn.row_factory = sqlite3.Row
        # Enable foreign key support
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def init_db(self) -> None:
        """Initializes the database schema if tables do not exist."""
        queries = [
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                test_command TEXT DEFAULT 'python -m unittest',
                github_url TEXT DEFAULT '',
                github_owner TEXT DEFAULT '',
                github_repo TEXT DEFAULT '',
                default_branch TEXT DEFAULT 'main',
                source_kind TEXT NOT NULL DEFAULT 'legacy',
                github_setup_status TEXT NOT NULL DEFAULT 'not_requested',
                github_setup_error TEXT DEFAULT '',
                integrity_workspace_path TEXT DEFAULT '',
                integrity_project_uuid TEXT DEFAULT '',
                antigravity_project_name TEXT DEFAULT '',
                archived_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT DEFAULT 'ai_scan',
                status TEXT DEFAULT 'pending', -- 'pending', 'running', 'done', 'failed'
                github_number INTEGER,
                github_url TEXT DEFAULT '',
                issue_type TEXT DEFAULT 'task', -- 'task', 'bug', 'feature'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER,
                status TEXT DEFAULT 'running', -- 'running', 'completed', 'failed', 'cancelled'
                checkpoint TEXT NOT NULL,      -- 'started', 'planning', 'edits_applied', 'verifying', 'completed'
                diff TEXT,                     -- Git-Diff before commit
                summary TEXT,                  -- AI report on changes
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS run_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                level TEXT NOT NULL,           -- 'info', 'warning', 'error', 'success'
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                role TEXT NOT NULL,            -- 'user', 'assistant', 'system'
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                issue_id INTEGER,
                technique TEXT NOT NULL,       -- e.g. 'Fix import error in model X'
                solution TEXT NOT NULL,        -- Explanation of repair
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE SET NULL
            );
            """
            ,
            """
            CREATE TABLE IF NOT EXISTS subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending', -- 'pending', 'running', 'completed'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS custom_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                base_url TEXT NOT NULL,
                model_id TEXT NOT NULL,
                api_key_protected BLOB,
                api_key_header TEXT NOT NULL DEFAULT 'Authorization',
                api_key_prefix TEXT NOT NULL DEFAULT 'Bearer',
                extra_headers TEXT NOT NULL DEFAULT '{}',
                system_prompt TEXT NOT NULL DEFAULT '',
                temperature REAL DEFAULT 0.7,
                verify_tls INTEGER NOT NULL DEFAULT 1,
                timeout_seconds INTEGER NOT NULL DEFAULT 60,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS proxy_conversations (
                id TEXT PRIMARY KEY,
                project_id INTEGER NOT NULL,
                custom_model_id INTEGER,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE SET NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS proxy_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                custom_model_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE SET NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_model_preferences (
                conversation_id TEXT PRIMARY KEY,
                custom_model_id INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_native_model_preferences (
                conversation_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                window_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS provider_conversations (
                id TEXT PRIMARY KEY,
                project_id INTEGER,
                provider_type TEXT NOT NULL,
                custom_model_id INTEGER,
                model_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                reasoning_effort TEXT NOT NULL DEFAULT '',
                external_thread_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE SET NULL,
                CHECK(provider_type IN ('custom', 'codex'))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS provider_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                provider_type TEXT NOT NULL,
                custom_model_id INTEGER,
                model_name TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE SET NULL,
                CHECK(provider_type IN ('custom', 'codex'))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_provider_preferences (
                conversation_id TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL,
                custom_model_id INTEGER,
                model_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                reasoning_effort TEXT NOT NULL DEFAULT '',
                external_thread_id TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(custom_model_id) REFERENCES custom_models(id) ON DELETE CASCADE,
                CHECK(provider_type IN ('custom', 'codex'))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS managed_antigravity_conversations (
                conversation_id TEXT PRIMARY KEY,
                project_id INTEGER,
                state TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
                CHECK(state IN ('active', 'archived', 'deleted'))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS api_request_logs (
                req_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                client_ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                api_key_name TEXT NOT NULL DEFAULT '',
                source_framework TEXT NOT NULL DEFAULT 'openai',
                endpoint TEXT NOT NULL DEFAULT '/v1/chat/completions',
                engine_mode TEXT NOT NULL DEFAULT 'rpc',
                workspace_slot TEXT NOT NULL DEFAULT '',
                conversation_id TEXT NOT NULL DEFAULT '',
                model_requested TEXT NOT NULL DEFAULT '',
                model_actual TEXT NOT NULL DEFAULT '',
                reasoning_effort TEXT NOT NULL DEFAULT '',
                stream INTEGER NOT NULL DEFAULT 0,
                status_code INTEGER NOT NULL DEFAULT 200,
                duration_ms REAL NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                thinking_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                context_used_tokens INTEGER NOT NULL DEFAULT 0,
                context_max_tokens INTEGER NOT NULL DEFAULT 0,
                token_source TEXT NOT NULL DEFAULT 'exact_rpc',
                messages_json TEXT NOT NULL DEFAULT '[]',
                system_prompt TEXT NOT NULL DEFAULT '',
                user_prompt_preview TEXT NOT NULL DEFAULT '',
                response_text TEXT NOT NULL DEFAULT '',
                tool_calls_json TEXT NOT NULL DEFAULT '[]',
                shield_metadata_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                reverted_at TEXT DEFAULT NULL,
                reverted_to_step INTEGER DEFAULT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS api_revert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                target_step_index INTEGER NOT NULL,
                previous_step_count INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                triggered_by_ip TEXT NOT NULL DEFAULT '',
                engine_mode TEXT NOT NULL DEFAULT 'rpc'
            );
            """
        ]

        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            for q in queries:
                conn.execute(q)
            conn.commit()
        self._migrate()
        self._ensure_indexes()
        with self._get_connection() as conn:
            conn.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION};")
            conn.commit()

    def _migrate(self) -> None:
        """Add columns missing from an older database and fail atomically."""
        migrations = [
            ("projects", "github_url", "TEXT DEFAULT ''"),
            ("projects", "github_owner", "TEXT DEFAULT ''"),
            ("projects", "github_repo", "TEXT DEFAULT ''"),
            ("projects", "default_branch", "TEXT DEFAULT 'main'"),
            ("projects", "source_kind", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("projects", "github_setup_status", "TEXT NOT NULL DEFAULT 'not_requested'"),
            ("projects", "github_setup_error", "TEXT DEFAULT ''"),
            ("projects", "integrity_workspace_path", "TEXT DEFAULT ''"),
            ("projects", "integrity_project_uuid", "TEXT DEFAULT ''"),
            ("projects", "antigravity_project_name", "TEXT DEFAULT ''"),
            ("projects", "archived_at", "TIMESTAMP"),
            ("issues", "github_number", "INTEGER"),
            ("issues", "github_url", "TEXT DEFAULT ''"),
            ("issues", "issue_type", "TEXT DEFAULT 'task'"),
            ("agent_runs", "conversation_id", "TEXT DEFAULT ''"),
            ("agent_runs", "full_auto", "INTEGER DEFAULT 1"),
        ]
        with self._get_connection() as conn:
            columns_by_table: Dict[str, set[str]] = {}
            for table, column, definition in migrations:
                if table not in columns_by_table:
                    columns_by_table[table] = {
                        str(row[1])
                        for row in conn.execute(f'PRAGMA table_info("{table}")')
                    }
                if column in columns_by_table[table]:
                    continue
                conn.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                )
                columns_by_table[table].add(column)
            conn.commit()

    def _ensure_indexes(self) -> None:
        """Create indexes only after legacy columns have been migrated."""
        with self._get_connection() as conn:
            for statement in CORE_INDEX_QUERIES:
                conn.execute(statement)
            conn.commit()

    # --- Projects API ---
    def add_project(
        self,
        name: str,
        path: str,
        test_command: str = "python -m unittest",
        github_url: str = "",
        github_owner: str = "",
        github_repo: str = "",
        default_branch: str = "main",
        source_kind: str = "legacy",
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name, path, test_command, github_url, github_owner, github_repo, default_branch, source_kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, path, test_command, github_url, github_owner, github_repo, default_branch, source_kind),
            )
            conn.commit()
            return cursor.lastrowid

    def get_projects(
        self,
        source_kind: Optional[str] = None,
        *,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return registered projects, hiding archived rows by default."""
        clauses: List[str] = []
        params: List[Any] = []
        if source_kind is not None:
            clauses.append("source_kind = ?")
            params.append(source_kind)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM projects{where} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_project(
        self,
        project_id: int,
        *,
        include_archived: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            query = "SELECT * FROM projects WHERE id = ?"
            if not include_archived:
                query += " AND archived_at IS NULL"
            row = conn.execute(query, (project_id,)).fetchone()
            return dict(row) if row else None

    def get_project_by_github(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE lower(github_owner) = lower(?) AND lower(github_repo) = lower(?)",
                (owner, repo),
            ).fetchone()
            return dict(row) if row else None

    def get_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE lower(name) = lower(?)",
                (name,),
            ).fetchone()
            return dict(row) if row else None

    def delete_project(self, project_id: int) -> None:
        """Physically delete a project row for internal/test cleanup only."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

    def archive_project(self, project_id: int) -> bool:
        """Soft-archive one project without deleting related records or files."""
        with self._get_connection() as conn:
            result = conn.execute(
                """UPDATE projects
                   SET archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP)
                   WHERE id = ?""",
                (project_id,),
            )
            conn.commit()
            return result.rowcount == 1

    def restore_project(self, project_id: int) -> bool:
        """Restore one archived project to all standard Hub lists."""
        with self._get_connection() as conn:
            result = conn.execute(
                "UPDATE projects SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",
                (project_id,),
            )
            conn.commit()
            return result.rowcount == 1

    def delete_issue(self, issue_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            conn.commit()

    def reset_issue(self, issue_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM agent_runs WHERE issue_id = ?", (issue_id,))
            conn.execute("UPDATE issues SET status = 'pending' WHERE id = ?", (issue_id,))
            conn.commit()

    # --- Issues API ---
    def add_issue(
        self,
        project_id: int,
        title: str,
        description: str,
        source: str = "ai_scan",
        status: str = "pending",
        issue_type: str = "task",
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO issues (project_id, title, description, source, status, issue_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, title, description, source, status, issue_type),
            )
            conn.commit()
            return cursor.lastrowid

    def get_issues(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if project_id is not None:
                rows = conn.execute(
                    """SELECT issue.* FROM issues issue
                       JOIN projects project ON project.id = issue.project_id
                       WHERE issue.project_id = ? AND project.archived_at IS NULL
                       ORDER BY issue.created_at DESC""",
                    (project_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT issue.* FROM issues issue
                       JOIN projects project ON project.id = issue.project_id
                       WHERE project.archived_at IS NULL
                       ORDER BY issue.created_at DESC"""
                ).fetchall()
            return [dict(r) for r in rows]

    def get_issue(self, issue_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            return dict(row) if row else None

    def update_issue_status(self, issue_id: int, status: str) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE issues SET status = ? WHERE id = ?", (status, issue_id))
            conn.commit()

    # --- GitHub Linking Helpers ---

    def update_project_github(
        self,
        project_id: int,
        github_url: str,
        github_owner: str,
        github_repo: str,
        default_branch: Optional[str] = None,
    ) -> None:
        """Updates GitHub metadata on an existing project."""
        with self._get_connection() as conn:
            if default_branch:
                conn.execute(
                    "UPDATE projects SET github_url = ?, github_owner = ?, github_repo = ?, "
                    "default_branch = ?, source_kind = 'github' WHERE id = ?",
                    (
                        github_url,
                        github_owner,
                        github_repo,
                        default_branch,
                        project_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE projects SET github_url = ?, github_owner = ?, github_repo = ? WHERE id = ?",
                    (github_url, github_owner, github_repo, project_id),
                )
            conn.commit()

    def update_project_github_setup(
        self,
        project_id: int,
        status: str,
        error: str = "",
    ) -> None:
        """Persist the resumable GitHub bootstrap state for a project."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET github_setup_status = ?, github_setup_error = ? "
                "WHERE id = ?",
                (status, error, project_id),
            )
            conn.commit()

    def promote_github_project(
        self,
        project_id: int,
        name: str,
        path: str,
        github_url: str,
        github_owner: str,
        github_repo: str,
        default_branch: str,
    ) -> None:
        """Make an explicit GitHub import visible without recreating legacy data."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET name = ?, path = ?, github_url = ?, github_owner = ?, "
                "github_repo = ?, default_branch = ?, source_kind = 'github', archived_at = NULL, "
                "github_setup_status = 'ready', github_setup_error = '' WHERE id = ?",
                (name, path, github_url, github_owner, github_repo, default_branch, project_id),
            )
            conn.commit()

    def update_project_integrity_link(
        self,
        project_id: int,
        workspace_path: str,
        project_uuid: str = "",
        project_name: str = "",
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET integrity_workspace_path = ?, integrity_project_uuid = ?, "
                "antigravity_project_name = ? WHERE id = ?",
                (workspace_path, project_uuid, project_name, project_id),
            )
            conn.commit()

    def update_issue_github(
        self, issue_id: int, github_number: int, github_url: str
    ) -> None:
        """Links a local issue to its GitHub counterpart."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE issues SET github_number = ?, github_url = ? WHERE id = ?",
                (github_number, github_url, issue_id),
            )
            conn.commit()

    def get_issue_by_github_number(
        self, project_id: int, github_number: int
    ) -> Optional[Dict[str, Any]]:
        """Finds a local issue by its GitHub issue number within a project."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM issues WHERE project_id = ? AND github_number = ?",
                (project_id, github_number),
            ).fetchone()
            return dict(row) if row else None

    # --- Agent Runs API ---
    def create_agent_run(self, issue_id: int, checkpoint: str = "started", status: str = "running", full_auto: bool = True) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_runs (issue_id, status, checkpoint, full_auto) VALUES (?, ?, ?, ?)",
                (issue_id, status, checkpoint, 1 if full_auto else 0)
            )
            conn.commit()
            return cursor.lastrowid

    def update_agent_run(self, run_id: int, checkpoint: str, status: str, diff: Optional[str] = None, summary: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET checkpoint = ?, status = ?, diff = COALESCE(?, diff), summary = COALESCE(?, summary), updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (checkpoint, status, diff, summary, run_id)
            )
            conn.commit()

    def update_agent_run_conversation_id(self, run_id: int, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE agent_runs SET conversation_id = ? WHERE id = ?", (conversation_id, run_id))
            conn.commit()

    def get_agent_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def get_agent_runs_by_issue(self, issue_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM agent_runs WHERE issue_id = ? ORDER BY started_at DESC", (issue_id,)).fetchall()
            return [dict(r) for r in rows]

    # --- Logs API ---
    def add_run_log(self, run_id: int, level: str, message: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO run_logs (run_id, level, message) VALUES (?, ?, ?)",
                (run_id, level, message)
            )
            conn.commit()
            return cursor.lastrowid

    def get_run_logs(self, run_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM run_logs WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    # --- Chat Messages API ---
    def add_chat_message(self, run_id: int, role: str, content: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO chat_messages (run_id, role, content) VALUES (?, ?, ?)",
                (run_id, role, content)
            )
            conn.commit()
            return cursor.lastrowid

    def get_chat_messages(self, run_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM chat_messages WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    # --- Lessons Learned API ---
    def add_lesson(self, project_id: int, issue_id: Optional[int], technique: str, solution: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO lessons (project_id, issue_id, technique, solution) VALUES (?, ?, ?, ?)",
                (project_id, issue_id, technique, solution)
            )
            conn.commit()
            return cursor.lastrowid

    def get_lessons(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if project_id is not None:
                rows = conn.execute(
                    """SELECT lessons.*
                       FROM lessons
                       JOIN projects ON projects.id = lessons.project_id
                       WHERE lessons.project_id = ?
                         AND projects.archived_at IS NULL
                       ORDER BY lessons.created_at DESC, lessons.id DESC""",
                    (project_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT lessons.*
                       FROM lessons
                       LEFT JOIN projects ON projects.id = lessons.project_id
                       WHERE lessons.project_id IS NULL
                          OR projects.archived_at IS NULL
                       ORDER BY lessons.created_at DESC, lessons.id DESC"""
                ).fetchall()
            return [dict(r) for r in rows]

    # --- Subtasks API ---
    def add_subtask(self, issue_id: int, title: str, status: str = "pending") -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO subtasks (issue_id, title, status) VALUES (?, ?, ?)",
                (issue_id, title, status),
            )
            conn.commit()
            return cursor.lastrowid

    def get_subtasks(self, issue_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM subtasks WHERE issue_id = ? ORDER BY id ASC",
                (issue_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_subtask_status(self, subtask_id: int, status: str) -> None:
        completed_at = datetime.now().isoformat() if status == "completed" else None
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE subtasks SET status = ?, completed_at = ? WHERE id = ?",
                (status, completed_at, subtask_id),
            )
            conn.commit()

    def delete_subtask(self, subtask_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
            conn.commit()

    def reset_subtasks(self, issue_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE subtasks SET status = 'pending', completed_at = NULL WHERE issue_id = ?",
                (issue_id,),
            )
            conn.commit()

    # --- Custom OpenAI-compatible models ---
    def list_custom_models(self) -> List[Dict[str, Any]]:
        """Return public provider metadata without encrypted API-key material."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, base_url, model_id, api_key_header, api_key_prefix,
                       extra_headers, system_prompt, temperature, verify_tls,
                       timeout_seconds, created_at, updated_at,
                       CASE WHEN length(api_key_protected) > 0 THEN 1 ELSE 0 END AS has_api_key
                FROM custom_models
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_custom_model(self, custom_model_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM custom_models WHERE id = ?",
                (custom_model_id,),
            ).fetchone()
            return dict(row) if row else None

    def save_custom_model(
        self,
        values: Dict[str, Any],
        api_key_protected: Optional[bytes],
        custom_model_id: Optional[int] = None,
    ) -> int:
        with self._get_connection() as conn:
            params = (
                values["name"],
                values["base_url"],
                values["model_id"],
                values["api_key_header"],
                values["api_key_prefix"],
                json.dumps(values["extra_headers"], ensure_ascii=False),
                values["system_prompt"],
                values["temperature"],
                1 if values["verify_tls"] else 0,
                values["timeout_seconds"],
            )
            if custom_model_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO custom_models (
                        name, base_url, model_id, api_key_protected,
                        api_key_header, api_key_prefix, extra_headers,
                        system_prompt, temperature, verify_tls, timeout_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params[:3] + (api_key_protected,) + params[3:],
                )
                conn.commit()
                return int(cursor.lastrowid)

            if api_key_protected is None:
                conn.execute(
                    """
                    UPDATE custom_models
                    SET name = ?, base_url = ?, model_id = ?, api_key_header = ?,
                        api_key_prefix = ?, extra_headers = ?, system_prompt = ?,
                        temperature = ?, verify_tls = ?, timeout_seconds = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    params + (custom_model_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE custom_models
                    SET name = ?, base_url = ?, model_id = ?, api_key_header = ?,
                        api_key_prefix = ?, extra_headers = ?, system_prompt = ?,
                        temperature = ?, verify_tls = ?, timeout_seconds = ?,
                        api_key_protected = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    params + (api_key_protected, custom_model_id),
                )
            conn.commit()
            return custom_model_id

    def delete_custom_model(self, custom_model_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM custom_models WHERE id = ?", (custom_model_id,))
            conn.commit()
            return cursor.rowcount > 0

    def custom_model_usage_count(self, custom_model_id: int) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM proxy_conversations WHERE custom_model_id = ?) +
                    (SELECT COUNT(*) FROM conversation_model_preferences WHERE custom_model_id = ?) +
                    (SELECT COUNT(*) FROM provider_conversations WHERE custom_model_id = ?) +
                    (SELECT COUNT(*) FROM conversation_provider_preferences WHERE custom_model_id = ?)
                    AS usage_count
                """,
                (custom_model_id, custom_model_id, custom_model_id, custom_model_id),
            ).fetchone()
            return int(row["usage_count"] if row else 0)

    # --- Hub-local proxy conversations and turns ---
    def create_proxy_conversation(
        self,
        conversation_id: str,
        project_id: int,
        custom_model_id: int,
        title: str,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO proxy_conversations (id, project_id, custom_model_id, title)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, project_id, custom_model_id, title),
            )
            conn.commit()

    def list_proxy_conversations(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            where = "WHERE pc.project_id = ?" if project_id is not None else ""
            params: tuple[Any, ...] = (project_id,) if project_id is not None else ()
            rows = conn.execute(
                """
                SELECT pc.id AS convo_id, pc.project_id, pc.custom_model_id,
                       pc.title,
                       CAST(strftime('%s', pc.created_at) AS INTEGER) AS created_at,
                       CAST(strftime('%s', pc.updated_at) AS INTEGER) AS updated_at,
                       cm.name AS model_name
                FROM proxy_conversations pc
                LEFT JOIN custom_models cm ON cm.id = pc.custom_model_id
                """ + where + """
                ORDER BY pc.updated_at DESC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_proxy_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM proxy_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_proxy_conversation(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM proxy_messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute(
                "DELETE FROM conversation_model_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                """
                DELETE FROM conversation_native_model_preferences
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            cursor = conn.execute("DELETE FROM proxy_conversations WHERE id = ?", (conversation_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_proxy_message(
        self,
        conversation_id: str,
        custom_model_id: int,
        role: str,
        content: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO proxy_messages (
                    conversation_id, custom_model_id, role, content, attachments_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    custom_model_id,
                    role,
                    content,
                    json.dumps(attachments or [], ensure_ascii=False),
                ),
            )
            conn.execute(
                "UPDATE proxy_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_proxy_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT pm.*, cm.name AS model_name
                FROM proxy_messages pm
                LEFT JOIN custom_models cm ON cm.id = pm.custom_model_id
                WHERE pm.conversation_id = ?
                ORDER BY pm.id ASC
                """,
                (conversation_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
                except json.JSONDecodeError:
                    item["attachments"] = []
                result.append(item)
            return result

    def delete_proxy_messages(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM proxy_messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute(
                "DELETE FROM conversation_model_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                """
                DELETE FROM conversation_native_model_preferences
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            conn.commit()

    def set_custom_model_preference(self, conversation_id: str, custom_model_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_model_preferences (
                    conversation_id, custom_model_id, updated_at
                ) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    custom_model_id = excluded.custom_model_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (conversation_id, custom_model_id),
            )
            conn.commit()

    def clear_custom_model_preference(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM conversation_model_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()

    def get_custom_model_preference(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT cm.*
                FROM conversation_model_preferences pref
                JOIN custom_models cm ON cm.id = pref.custom_model_id
                WHERE pref.conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    # --- Unified Hub-local Codex and custom-provider conversations ---
    def create_provider_conversation(
        self,
        conversation_id: str,
        *,
        project_id: Optional[int],
        provider_type: str,
        model_id: str,
        display_name: str,
        title: str,
        custom_model_id: Optional[int] = None,
        reasoning_effort: str = "",
        external_thread_id: str = "",
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO provider_conversations (
                    id, project_id, provider_type, custom_model_id, model_id,
                    display_name, reasoning_effort, external_thread_id, title
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    project_id,
                    provider_type,
                    custom_model_id,
                    model_id,
                    display_name,
                    reasoning_effort,
                    external_thread_id,
                    title,
                ),
            )
            conn.commit()

    def list_provider_conversations(
        self,
        project_id: Optional[int] = None,
        *,
        include_archived: bool = True,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if project_id is not None:
            clauses.append("pc.project_id = ?")
            params.append(project_id)
        if not include_archived:
            clauses.append("pc.archived = 0")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT pc.id AS convo_id, pc.project_id, pc.provider_type,
                       pc.custom_model_id, pc.model_id, pc.display_name,
                       pc.reasoning_effort, pc.external_thread_id, pc.title,
                       pc.archived,
                       CAST(strftime('%s', pc.created_at) AS INTEGER) AS created_at,
                       CAST(strftime('%s', pc.updated_at) AS INTEGER) AS updated_at,
                       (SELECT COUNT(*) FROM provider_messages pm
                        WHERE pm.conversation_id = pc.id) AS step_count,
                       p.name AS project_name, p.path AS project_path,
                       p.github_repo AS repository_name
                FROM provider_conversations pc
                LEFT JOIN projects p ON p.id = pc.project_id
                """ + where + " ORDER BY pc.updated_at DESC",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_provider_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_provider_conversation_model(
        self,
        conversation_id: str,
        *,
        provider_type: str,
        model_id: str,
        display_name: str,
        custom_model_id: Optional[int] = None,
        reasoning_effort: str = "",
        external_thread_id: str = "",
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE provider_conversations
                SET provider_type = ?, custom_model_id = ?, model_id = ?,
                    display_name = ?, reasoning_effort = ?, external_thread_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    provider_type,
                    custom_model_id,
                    model_id,
                    display_name,
                    reasoning_effort,
                    external_thread_id,
                    conversation_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_provider_thread(self, conversation_id: str, thread_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """UPDATE provider_conversations
                   SET external_thread_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (thread_id, conversation_id),
            )
            conn.execute(
                """UPDATE conversation_provider_preferences
                   SET external_thread_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE conversation_id = ?""",
                (thread_id, conversation_id),
            )
            conn.commit()

    def set_provider_conversation_archived(self, conversation_id: str, archived: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """UPDATE provider_conversations
                   SET archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (1 if archived else 0, conversation_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_provider_conversation(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM provider_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM conversation_provider_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor = conn.execute(
                "DELETE FROM provider_conversations WHERE id = ?",
                (conversation_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def add_provider_message(
        self,
        conversation_id: str,
        *,
        provider_type: str,
        model_name: str,
        role: str,
        content: str,
        custom_model_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO provider_messages (
                    conversation_id, provider_type, custom_model_id, model_name,
                    role, content, attachments_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    provider_type,
                    custom_model_id,
                    model_name,
                    role,
                    content,
                    json.dumps(attachments or [], ensure_ascii=False),
                ),
            )
            conn.execute(
                """UPDATE provider_conversations
                   SET updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (conversation_id,),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_provider_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM provider_messages
                   WHERE conversation_id = ? ORDER BY id ASC""",
                (conversation_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
                except json.JSONDecodeError:
                    item["attachments"] = []
                result.append(item)
            return result

    def delete_provider_messages(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM provider_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM conversation_provider_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()

    def set_provider_preference(
        self,
        conversation_id: str,
        *,
        provider_type: str,
        model_id: str,
        display_name: str,
        custom_model_id: Optional[int] = None,
        reasoning_effort: str = "",
        external_thread_id: str = "",
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_provider_preferences (
                    conversation_id, provider_type, custom_model_id, model_id,
                    display_name, reasoning_effort, external_thread_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    provider_type = excluded.provider_type,
                    custom_model_id = excluded.custom_model_id,
                    model_id = excluded.model_id,
                    display_name = excluded.display_name,
                    reasoning_effort = excluded.reasoning_effort,
                    external_thread_id = excluded.external_thread_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    conversation_id,
                    provider_type,
                    custom_model_id,
                    model_id,
                    display_name,
                    reasoning_effort,
                    external_thread_id,
                ),
            )
            conn.commit()

    def get_provider_preference(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM conversation_provider_preferences
                   WHERE conversation_id = ?""",
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def clear_provider_preference(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM conversation_provider_preferences WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()

    def set_native_model_preference(
        self,
        conversation_id: str,
        model_name: str,
        window_id: Optional[str] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_native_model_preferences (
                    conversation_id, model_name, window_id, updated_at
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    model_name = excluded.model_name,
                    window_id = excluded.window_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (conversation_id, model_name, window_id),
            )
            conn.commit()

    def get_native_model_preference(
        self,
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT conversation_id, model_name, window_id, updated_at
                FROM conversation_native_model_preferences
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def clear_native_model_preference(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                DELETE FROM conversation_native_model_preferences
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            conn.commit()

    # --- Native Anti-Gravity conversations created by the Hub ---
    def upsert_managed_antigravity_conversation(
        self,
        conversation_id: str,
        *,
        project_id: Optional[int] = None,
        state: str = "active",
    ) -> None:
        normalized_id = str(conversation_id or "").strip().lower()
        normalized_state = str(state or "").strip().lower()
        if not normalized_id:
            raise ValueError("conversation_id is required")
        if normalized_state not in MANAGED_ANTIGRAVITY_CONVERSATION_STATES:
            raise ValueError(f"Unsupported managed conversation state: {state}")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO managed_antigravity_conversations (
                    conversation_id, project_id, state, updated_at,
                    last_verified_at
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    project_id = COALESCE(
                        excluded.project_id,
                        managed_antigravity_conversations.project_id
                    ),
                    state = excluded.state,
                    updated_at = CURRENT_TIMESTAMP,
                    last_verified_at = CURRENT_TIMESTAMP
                """,
                (normalized_id, project_id, normalized_state),
            )
            conn.commit()

    def list_managed_antigravity_conversations(
        self,
        *,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_state = None
        if state is not None:
            normalized_state = str(state).strip().lower()
            if normalized_state not in MANAGED_ANTIGRAVITY_CONVERSATION_STATES:
                raise ValueError(
                    f"Unsupported managed conversation state: {state}"
                )
        query = "SELECT * FROM managed_antigravity_conversations"
        parameters: tuple[Any, ...] = ()
        if normalized_state is not None:
            query += " WHERE state = ?"
            parameters = (normalized_state,)
        query += " ORDER BY updated_at DESC, conversation_id ASC"
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute(query, parameters).fetchall()]

    def set_managed_antigravity_conversation_state(
        self,
        conversation_id: str,
        state: str,
    ) -> bool:
        normalized_id = str(conversation_id or "").strip().lower()
        normalized_state = str(state or "").strip().lower()
        if normalized_state not in MANAGED_ANTIGRAVITY_CONVERSATION_STATES:
            raise ValueError(f"Unsupported managed conversation state: {state}")
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE managed_antigravity_conversations
                SET state = ?, updated_at = CURRENT_TIMESTAMP,
                    last_verified_at = CURRENT_TIMESTAMP
                WHERE conversation_id = ?
                """,
                (normalized_state, normalized_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # --- Persistent API Audit Logs & Revert Events ---
    def insert_api_request_log(self, entry: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO api_request_logs (
                    req_id, created_at, client_ip, user_agent, api_key_name,
                    source_framework, endpoint, engine_mode, workspace_slot,
                    conversation_id, model_requested, model_actual, reasoning_effort,
                    stream, status_code, duration_ms, prompt_tokens, completion_tokens,
                    cached_tokens, thinking_tokens, total_tokens, context_used_tokens,
                    context_max_tokens, token_source, messages_json, system_prompt,
                    user_prompt_preview, response_text, tool_calls_json,
                    shield_metadata_json, error_text, reverted_at, reverted_to_step
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    str(entry.get("req_id") or ""),
                    str(entry.get("created_at") or datetime.utcnow().isoformat() + "Z"),
                    str(entry.get("client_ip") or ""),
                    str(entry.get("user_agent") or ""),
                    str(entry.get("api_key_name") or ""),
                    str(entry.get("source_framework") or "openai"),
                    str(entry.get("endpoint") or "/v1/chat/completions"),
                    str(entry.get("engine_mode") or "rpc"),
                    str(entry.get("workspace_slot") or ""),
                    str(entry.get("conversation_id") or ""),
                    str(entry.get("model_requested") or ""),
                    str(entry.get("model_actual") or ""),
                    str(entry.get("reasoning_effort") or ""),
                    1 if entry.get("stream") else 0,
                    int(entry.get("status_code") or 200),
                    float(entry.get("duration_ms") or 0.0),
                    int(entry.get("prompt_tokens") or 0),
                    int(entry.get("completion_tokens") or 0),
                    int(entry.get("cached_tokens") or 0),
                    int(entry.get("thinking_tokens") or 0),
                    int(entry.get("total_tokens") or 0),
                    int(entry.get("context_used_tokens") or 0),
                    int(entry.get("context_max_tokens") or 0),
                    str(entry.get("token_source") or "exact_rpc"),
                    json.dumps(entry.get("messages") or [], ensure_ascii=False)
                    if not isinstance(entry.get("messages_json"), str)
                    else entry["messages_json"],
                    str(entry.get("system_prompt") or ""),
                    str(entry.get("user_prompt_preview") or ""),
                    str(entry.get("response_text") or ""),
                    json.dumps(entry.get("tool_calls") or [], ensure_ascii=False)
                    if not isinstance(entry.get("tool_calls_json"), str)
                    else entry["tool_calls_json"],
                    json.dumps(entry.get("shield_metadata") or {}, ensure_ascii=False)
                    if not isinstance(entry.get("shield_metadata_json"), str)
                    else entry["shield_metadata_json"],
                    str(entry.get("error_text") or ""),
                    entry.get("reverted_at"),
                    entry.get("reverted_to_step"),
                ),
            )
            conn.commit()

    def list_api_request_logs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        model: Optional[str] = None,
        status: Optional[str] = None,
        framework: Optional[str] = None,
        engine_mode: Optional[str] = None,
        conversation_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if model:
            clauses.append("(lower(model_requested) LIKE lower(?) OR lower(model_actual) LIKE lower(?))")
            params.extend([f"%{model}%", f"%{model}%"])
        if status == "reverted":
            clauses.append("reverted_at IS NOT NULL")
        elif status == "error":
            clauses.append("status_code >= 400")
        elif status == "ok":
            clauses.append("status_code < 400")
        elif status and status.isdigit():
            clauses.append("status_code = ?")
            params.append(int(status))
        if framework:
            clauses.append("lower(source_framework) = lower(?)")
            params.append(framework)
        if engine_mode:
            clauses.append("lower(engine_mode) = lower(?)")
            params.append(engine_mode)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if search:
            clauses.append(
                "(lower(user_prompt_preview) LIKE lower(?) OR lower(response_text) LIKE lower(?) "
                "OR lower(conversation_id) LIKE lower(?) OR lower(req_id) LIKE lower(?))"
            )
            params.extend([f"%{search}%"] * 4)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM api_request_logs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(limit, 1000)), max(0, offset)])
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_api_request_log(self, req_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM api_request_logs WHERE req_id = ?", (req_id,)
            ).fetchone()
            return dict(row) if row else None

    def mark_conversation_logs_reverted(
        self,
        conversation_id: str,
        target_step_index: int,
        reverted_at: str,
        *,
        previous_step_count: int = 0,
        reason: str = "",
        triggered_by_ip: str = "",
        engine_mode: str = "rpc",
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO api_revert_events (
                    created_at, conversation_id, target_step_index,
                    previous_step_count, reason, triggered_by_ip, engine_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reverted_at,
                    conversation_id,
                    int(target_step_index),
                    int(previous_step_count),
                    reason,
                    triggered_by_ip,
                    engine_mode,
                ),
            )
            conn.execute(
                """
                UPDATE api_request_logs
                SET reverted_at = ?, reverted_to_step = ?
                WHERE conversation_id = ? AND reverted_at IS NULL
                """,
                (reverted_at, int(target_step_index), conversation_id),
            )
            conn.commit()

    def list_api_revert_events(
        self, *, limit: int = 100, conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM api_revert_events"
        params: List[Any] = []
        if conversation_id:
            query += " WHERE conversation_id = ?"
            params.append(conversation_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._get_connection() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def get_api_logs_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) AS success_requests,
                    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_requests,
                    SUM(CASE WHEN reverted_at IS NOT NULL THEN 1 ELSE 0 END) AS reverted_requests,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(thinking_tokens), 0) AS thinking_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
                FROM api_request_logs
                """
            ).fetchone()
            by_model_rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(model_actual, ''), NULLIF(model_requested, ''), 'unknown') AS model,
                    COUNT(*) AS requests,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(thinking_tokens), 0) AS thinking_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
                FROM api_request_logs
                GROUP BY model
                ORDER BY total_tokens DESC
                """
            ).fetchall()
            by_framework_rows = conn.execute(
                """
                SELECT
                    source_framework,
                    COUNT(*) AS requests,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM api_request_logs
                GROUP BY source_framework
                ORDER BY requests DESC
                """
            ).fetchall()
            reverts_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM api_revert_events"
            ).fetchone()

        return {
            "totals": dict(totals) if totals else {},
            "by_model": [dict(r) for r in by_model_rows],
            "by_framework": [dict(r) for r in by_framework_rows],
            "total_revert_events": int(reverts_count["cnt"]) if reverts_count else 0,
        }

    def clear_api_request_logs(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM api_request_logs")
            conn.execute("DELETE FROM api_revert_events")
            conn.commit()


# Singleton instance
db = Database()

