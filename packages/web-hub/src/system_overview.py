"""Sanitized operational overview for the Anti-Gravity system page."""

from __future__ import annotations

import asyncio
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import aiohttp
from aiohttp import web

from src.config import config
from src.database import db
from src.ide_server import CODE_SERVER_PORT, code_server_status
from src.app_keys import BACKEND_PORT_KEY


BASE_DIR = Path(__file__).resolve().parent.parent
STARTED_MONOTONIC = time.monotonic()
DEFAULT_HUB_VERSION = "0.1.0-dev"
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

SERVICE_SPECS = (
    ("api_bridge", "API Bridge", "Agenten- und Modellzugriff", 8001, "/health"),
    ("sessions", "Session Manager", "Sitzungen und Routing", 8002, "/health"),
    ("healer", "Auto-Healer", "Recovery und Selbstheilung", 8007, "/health"),
    ("watchdog", "Watchdog", "Health, Uptime und Alerts", 8010, "/health"),
)

DATABASE_COUNTERS = (
    ("projects", "Projekte"),
    ("issues", "Issues"),
    ("agent_runs", "Agentenläufe"),
    ("control_campaigns", "Campaigns"),
    ("control_pr_candidates", "PR-Kandidaten"),
    ("control_agent_tasks", "Agentenaufgaben"),
    ("control_human_approvals", "Human-Gates"),
    ("control_findings", "Review-Befunde"),
    ("control_audit_events", "Audit-Ereignisse"),
)


def _service_health_details(
    service_id: str,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Return only non-sensitive health evidence used by the system page."""
    if service_id != "api_bridge" or not isinstance(payload, Mapping):
        return {}
    cdp = payload.get("cdp")
    cdp = cdp if isinstance(cdp, Mapping) else {}
    return {
        "ready": payload.get("ready") is True,
        "cdp_status": str(cdp.get("status") or "unknown"),
        "bridge": str(cdp.get("bridge") or "unknown"),
    }


async def _probe_http_service(
    session: aiohttp.ClientSession,
    service_id: str,
    name: str,
    role: str,
    port: int,
    path: str,
) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        async with session.get(f"http://127.0.0.1:{port}{path}") as response:
            try:
                payload = await response.json(content_type=None)
            except (aiohttp.ClientError, ValueError):
                await response.read()
                payload = {}
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            details = _service_health_details(service_id, payload)
            ready = 200 <= response.status < 400
            if service_id == "api_bridge":
                ready = ready and (
                    details.get("ready") is True
                    and details.get("cdp_status") == "connected"
                    and details.get("bridge") == "injected"
                )
            result = {
                "id": service_id,
                "name": name,
                "role": role,
                "port": port,
                "status": "healthy" if ready else "attention",
                "http_status": response.status,
                "latency_ms": latency_ms,
            }
            if details:
                result["details"] = details
            return result
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return {
            "id": service_id,
            "name": name,
            "role": role,
            "port": port,
            "status": "offline",
            "http_status": None,
            "latency_ms": None,
        }


async def _probe_tcp(port: int | None) -> Dict[str, Any]:
    if not port:
        return {"connected": False, "port": None, "latency_ms": None}
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", int(port)),
            timeout=1.0,
        )
        writer.close()
        await writer.wait_closed()
        return {
            "connected": True,
            "port": int(port),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except (OSError, asyncio.TimeoutError, ValueError):
        return {"connected": False, "port": int(port), "latency_ms": None}


def _table_names(connection: Any) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def database_snapshot(database: Any = db) -> Dict[str, Any]:
    """Return metadata and allowlisted counters, never stored row contents."""
    with database._get_connection() as connection:
        tables = _table_names(connection)
        counts = []
        for table, label in DATABASE_COUNTERS:
            if table not in tables:
                continue
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            counts.append({"table": table, "label": label, "count": count})

        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_key_violations = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])

    database_path = Path(database.db_path)
    modified_at = None
    if database_path.exists():
        modified_at = datetime.fromtimestamp(
            database_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()

    return {
        "engine": "SQLite",
        "filename": database_path.name,
        "size_bytes": page_count * page_size,
        "table_count": len(tables),
        "journal_mode": journal_mode,
        "schema_version": schema_version,
        "quick_check": quick_check,
        "foreign_key_violations": foreign_key_violations,
        "last_modified": modified_at,
        "record_counts": counts,
        "privacy": "Nur Metadaten und freigegebene Zähler – keine Zeileninhalte.",
    }


def _contains_all(text: str, values: Iterable[str]) -> bool:
    return all(value in text for value in values)


def build_metadata(base_dir: Path = BASE_DIR) -> Dict[str, str]:
    """Resolve non-sensitive build identity without invoking Git."""
    version = os.environ.get("ANTIGRAVITY_HUB_VERSION", DEFAULT_HUB_VERSION).strip()
    revision = os.environ.get("ANTIGRAVITY_HUB_BUILD_SHA", "").strip()
    if not revision:
        head_file = base_dir / ".git" / "HEAD"
        try:
            head = head_file.read_text(encoding="utf-8").strip()
            if head.startswith("ref: "):
                revision = (base_dir / ".git" / head[5:]).read_text(
                    encoding="utf-8"
                ).strip()
            else:
                revision = head
        except OSError:
            revision = ""
    return {
        "hub_version": version or DEFAULT_HUB_VERSION,
        "build_sha": revision[:12] if revision else "development",
    }


def deployment_snapshot(base_dir: Path = BASE_DIR) -> Dict[str, Any]:
    manifest_root = (
        base_dir
        if (base_dir / "Dockerfile").exists()
        else base_dir / "deployment"
    )
    dockerfile = manifest_root / "Dockerfile"
    compose_file = manifest_root / "docker-compose.yml"
    docker_text = dockerfile.read_text(encoding="utf-8") if dockerfile.exists() else ""
    compose_text = compose_file.read_text(encoding="utf-8") if compose_file.exists() else ""

    checks = [
        {
            "id": "dockerfile",
            "label": "Multi-Stage Dockerfile",
            "ready": dockerfile.exists() and "AS frontend-build" in docker_text,
            "detail": "React-Build und schlankes Python-Runtime-Image",
        },
        {
            "id": "non_root",
            "label": "Non-Root Container",
            "ready": "USER antigravity" in docker_text,
            "detail": "Runtime läuft ohne Root-Rechte",
        },
        {
            "id": "reduced_privileges",
            "label": "Reduzierte Containerrechte",
            "ready": _contains_all(
                compose_text,
                ("cap_drop:", "- ALL", "no-new-privileges:true"),
            ) and "pid: host" not in compose_text,
            "detail": "Keine Linux-Capabilities und kein Zugriff auf Host-PIDs",
        },
        {
            "id": "healthcheck",
            "label": "Container-Healthcheck",
            "ready": "HEALTHCHECK" in docker_text,
            "detail": "Alle fünf Kerndienste werden geprüft",
        },
        {
            "id": "locked_dependencies",
            "label": "Abhängigkeiten gelockt",
            "ready": (
                (base_dir / "requirements.lock.txt").exists()
                and (base_dir / "frontend" / "package-lock.json").exists()
            ) or (
                (manifest_root / "requirements.lock.txt").exists()
                and (manifest_root / "package-lock.json").exists()
            ),
            "detail": "Python- und Node-Versionen reproduzierbar",
        },
        {
            "id": "external_config",
            "label": "Externe Konfiguration",
            "ready": "read_only: true" in compose_text
            and "ANTIGRAVITY_HUB_CONFIG" in compose_text,
            "detail": "Secrets bleiben außerhalb des Images",
        },
        {
            "id": "persistent_database",
            "label": "Persistente Datenbank",
            "ready": _contains_all(
                compose_text,
                ("antigravity-data", "/app/data", "ANTIGRAVITY_HUB_DB"),
            ),
            "detail": "SQLite-Daten liegen in einem benannten Volume",
        },
        {
            "id": "persistent_logs",
            "label": "Persistente Logs",
            "ready": _contains_all(compose_text, ("antigravity-logs", "/app/logs")),
            "detail": "Diagnose- und Auditlogs überleben Neustarts",
        },
        {
            "id": "persistent_projects",
            "label": "Persistente Projekte",
            "ready": _contains_all(
                compose_text,
                ("antigravity-projects", "/home/antigravity/Projects"),
            ),
            "detail": "Geklonte Repositories überleben Containerwechsel",
        },
    ]

    configured = all(bool(item["ready"]) for item in checks)
    return {
        "model": "Aktuell nativ · optional als ein Docker-Stack betreibbar",
        "containerized": Path("/.dockerenv").exists(),
        "runtime_verified": Path("/.dockerenv").exists(),
        "source_manifest_available": dockerfile.exists() and compose_file.exists(),
        "compose_service": "hub",
        "network_mode": "host",
        "checks": checks,
        "configured": configured,
    }


async def handle_system_overview(request: web.Request) -> web.Response:
    timeout = aiohttp.ClientTimeout(total=2.0, connect=0.75)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        probed = await asyncio.gather(
            *(
                _probe_http_service(session, *spec)
                for spec in SERVICE_SPECS
            )
        )

    services = [
        {
            "id": "hub",
            "name": "Hub UI",
            "role": "React-Oberfläche und API-Gateway",
            "port": 8000,
            "status": "healthy",
            "http_status": 200,
            "latency_ms": 0.0,
        },
        *probed,
    ]
    backend = await _probe_tcp(request.app.get(BACKEND_PORT_KEY))
    database, deployment = await asyncio.gather(
        asyncio.to_thread(database_snapshot),
        asyncio.to_thread(deployment_snapshot),
    )
    ide_status = await asyncio.to_thread(code_server_status)
    policy = await asyncio.to_thread(control_policy_snapshot)
    build = build_metadata()

    required_services_healthy = all(
        item["status"] == "healthy" for item in services
    )
    database_healthy = (
        database["quick_check"] == "ok"
        and database["foreign_key_violations"] == 0
    )
    overall_status = (
        "healthy"
        if required_services_healthy
        and database_healthy
        and deployment["configured"]
        and backend["connected"]
        else "attention"
    )

    return web.json_response(
        {
            "status": overall_status,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "services": services,
            "database": database,
            "deployment": deployment,
            "runtime": {
                "python_version": platform.python_version(),
                **build,
                "platform": platform.system(),
                "architecture": platform.machine(),
                "cpu_count": os.cpu_count(),
                "uptime_seconds": int(time.monotonic() - STARTED_MONOTONIC),
                "watchdog_retention_days": config.watchdog.get("retention_days", 30),
                "api_content_logging": str(
                    os.environ.get("ANTIGRAVITY_LOG_API_CONTENT") or ""
                ).strip().lower() in TRUTHY_ENV_VALUES,
                "control_mode": policy["mode"],
                "paused": policy["paused"],
            },
            "integrations": {
                "antigravity": backend,
                "web_ide": {
                    "running": bool(ide_status.get("running")),
                    "port": CODE_SERVER_PORT,
                },
            },
        }
    )


def control_policy_snapshot() -> Dict[str, Any]:
    from src.control_center import control_center

    policy = control_center.get_policy()
    return {"mode": str(policy.get("mode") or "guided"), "paused": bool(policy.get("paused"))}
