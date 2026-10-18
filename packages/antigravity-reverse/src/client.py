"""
Antigravity Headless Client
Zero-CDP direct HTTP/Connect-Web client talking to local Antigravity Language Server.
Handles CSRF handshake, self-signed TLS certificates, and local SQLite conversation metadata.
"""

import json
import os
import re
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class LanguageServerError(Exception):
    """Base exception for Antigravity Language Server interactions."""
    pass


class AuthenticationError(LanguageServerError):
    """Raised when CSRF token authentication fails (HTTP 401)."""
    pass


class ConnectionError(LanguageServerError):
    """Raised when the client cannot connect to the Language Server."""
    pass


class AntigravityClient:
    """
    Headless client for Google Antigravity Language Server.
    Connects directly over loopback HTTPS via Connect-Web protocol.
    """

    DEFAULT_SERVICE = "exa.language_server_pb.LanguageServerService"

    def __init__(
        self,
        port: Optional[int] = None,
        csrf_token: Optional[str] = None,
        host: str = "127.0.0.1",
        timeout: float = 10.0,
        db_path: Optional[str] = None,
    ):
        self.host = host
        self.timeout = timeout
        self.db_path = db_path

        # If port or token are omitted, discover automatically from running process
        if port is None or csrf_token is None:
            discovered = self.discover_active_server()
            if discovered is not None:
                d_port, d_token = discovered
                self.port = port or d_port
                self.csrf_token = csrf_token or d_token
            else:
                self.port = port
                self.csrf_token = csrf_token
        else:
            self.port = port
            self.csrf_token = csrf_token

        # Configure SSL context for local self-signed certificates
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    @classmethod
    def discover_active_server(cls, timeout: float = 1.0) -> Optional[Tuple[int, str]]:
        """
        Automatically discovers active Language Server port and CSRF token.
        Inspects running language_server.exe processes and probes listening ports.
        """
        # 1. Check environment variables
        env_port = os.environ.get("ANTIGRAVITY_PORT")
        env_token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
        if env_port and env_token:
            try:
                return int(env_port), env_token
            except ValueError:
                pass

        # 2. On Windows, inspect running processes via PowerShell / WMI
        if os.name == "nt":
            try:
                cmd = [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | "
                    "Select-Object ProcessId, CommandLine | ConvertTo-Json"
                ]
                proc_out = subprocess.check_output(cmd, encoding="utf-8", errors="ignore", timeout=5).strip()
                if not proc_out:
                    return None

                data = json.loads(proc_out)
                procs = [data] if isinstance(data, dict) else data

                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                for p in procs:
                    pid = p.get("ProcessId")
                    cline = p.get("CommandLine") or ""
                    m = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cline)
                    if not m or not pid:
                        continue
                    token = m.group(1)

                    # Query listening ports for this PID
                    port_cmd = [
                        "powershell", "-NoProfile", "-Command",
                        f"Get-NetTCPConnection -OwningProcess {pid} -State Listen | "
                        "Select-Object -ExpandProperty LocalPort"
                    ]
                    try:
                        port_out = subprocess.check_output(port_cmd, encoding="utf-8", errors="ignore", timeout=3).strip()
                        ports = [int(x) for x in port_out.split() if x.isdigit()]
                    except Exception:
                        continue

                    # Probe ports in descending order (highest port is typically the Connect HTTPS endpoint)
                    for port in sorted(ports, reverse=True):
                        req = urllib.request.Request(
                            f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetStatus",
                            data=b"{}",
                            headers={
                                "Connect-Protocol-Version": "1",
                                "Content-Type": "application/json",
                                "x-codeium-csrf-token": token,
                            }
                        )
                        try:
                            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                                if resp.status == 200:
                                    return port, token
                        except Exception:
                            pass
            except Exception:
                pass

        return None

    def _ensure_connected(self):
        if not self.port or not self.csrf_token:
            raise ConnectionError(
                "Language Server port or CSRF token is not configured and could not be auto-discovered. "
                "Ensure Antigravity is running or pass port and csrf_token explicitly."
            )

    def _post(self, service: str, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes an HTTP/1.1 POST call to the Language Server using Connect-Web JSON protocol.
        """
        self._ensure_connected()
        url = f"https://{self.host}:{self.port}/{service}/{method}"
        body_bytes = json.dumps(payload or {}).encode("utf-8")

        headers = {
            "Connect-Protocol-Version": "1",
            "Content-Type": "application/json",
            "x-codeium-csrf-token": self.csrf_token,
        }

        req = urllib.request.Request(url, data=body_bytes, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 401:
                raise AuthenticationError(f"CSRF authentication rejected (HTTP 401): {err_body}")
            raise LanguageServerError(f"Language Server error (HTTP {e.code}): {err_body}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Language Server at {url}: {e.reason}")
        except Exception as e:
            raise LanguageServerError(f"Unexpected error communicating with Language Server: {e}")

    # --- High-Level RPC Methods ---

    def get_status(self) -> Dict[str, Any]:
        """Queries server health and baseline status (GetStatus)."""
        return self._post(self.DEFAULT_SERVICE, "GetStatus")

    def get_user_status(self) -> Dict[str, Any]:
        """Queries authenticated user account, plan details, and active tier (GetUserStatus)."""
        return self._post(self.DEFAULT_SERVICE, "GetUserStatus")

    def get_available_models(self) -> Dict[str, Any]:
        """Retrieves list of active LLM models, provider mapping, and token capabilities (GetAvailableModels)."""
        return self._post(self.DEFAULT_SERVICE, "GetAvailableModels")

    def get_user_quota_summary(self) -> Dict[str, Any]:
        """Retrieves current 5-hour and weekly token limits and reset countdowns (RetrieveUserQuotaSummary)."""
        return self._post(self.DEFAULT_SERVICE, "RetrieveUserQuotaSummary")

    def get_cascade_trajectory(self, cascade_id: str, disable_rehydration: bool = False) -> Dict[str, Any]:
        """
        Retrieves the complete step trajectory and execution metadata for a cascade session (GetCascadeTrajectory).
        """
        payload = {
            "cascadeId": cascade_id,
            "disableRehydration": disable_rehydration
        }
        return self._post(self.DEFAULT_SERVICE, "GetCascadeTrajectory", payload)

    # --- Local SQLite Storage Inspection ---

    def list_conversations(self, limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lists stored conversation summaries from local SQLite storage (conversation_summaries.db)
        in strictly read-only mode.
        """
        target_db = db_path or self.db_path
        if target_db is None:
            candidates = [
                Path(os.path.expanduser("~/.gemini/antigravity/conversation_summaries.db")),
                Path(os.path.expandvars(r"%APPDATA%\Antigravity\conversation_summaries.db")),
                Path(os.path.expandvars(r"%LOCALAPPDATA%\antigravity\conversation_summaries.db")),
                Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity\conversation_summaries.db")),
            ]
            for c in candidates:
                if c.exists():
                    target_db = str(c)
                    break

        if not target_db or not os.path.exists(target_db):
            return []

        # Open in strictly read-only mode with query_only pragma
        uri_path = f"file:{Path(target_db).resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri_path, uri=True)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA query_only = ON")
            query = """
                SELECT conversation_id, title, preview, step_count, last_modified_time, last_user_input_time, status, agent_name
                FROM conversation_summaries
                ORDER BY last_modified_time DESC
                LIMIT ?
            """
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            results = []
            for r in rows:
                results.append({
                    "conversation_id": r[0],
                    "title": r[1],
                    "preview": r[2],
                    "step_count": r[3],
                    "last_modified_time": r[4],
                    "last_user_input_time": r[5],
                    "status": r[6],
                    "agent_name": r[7]
                })
            return results
        finally:
            conn.close()
