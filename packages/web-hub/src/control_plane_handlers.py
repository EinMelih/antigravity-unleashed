"""HTTP surface for operation status and Control Plane documentation."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from src.operation_coordinator import CONTROL_COORDINATOR_KEY


BASE_DIR = Path(__file__).resolve().parent.parent
CONTROL_DOC_PATH = BASE_DIR / "docs" / "antigravity-control-plane.md"
CONTROL_DOC_PATHS = {
    "operator": CONTROL_DOC_PATH,
    "index": BASE_DIR / "docs" / "README.md",
    "api": BASE_DIR / "docs" / "API_REFERENCE.md",
    "database": BASE_DIR / "docs" / "DATABASE_SCHEMA.md",
    "codebase": BASE_DIR / "docs" / "CODEBASE_GUIDE.md",
    "dependencies": BASE_DIR / "docs" / "DEPENDENCIES.md",
    "configuration": BASE_DIR / "docs" / "CONFIGURATION.md",
    "operations": BASE_DIR / "docs" / "OPERATIONS.md",
    "knowledge-chain": BASE_DIR / "docs" / "KNOWLEDGE_CHAIN.md",
    "plan-amendments": BASE_DIR / "docs" / "PLAN_AMENDMENTS.md",
    "routes": BASE_DIR / "docs" / "generated" / "HTTP_ROUTES.md",
    "schema": BASE_DIR / "docs" / "generated" / "SQLITE_SCHEMA.md",
    "imports": BASE_DIR / "docs" / "generated" / "PYTHON_IMPORT_GRAPH.md",
    "frontend-imports": BASE_DIR / "docs" / "generated" / "FRONTEND_IMPORT_GRAPH.md",
    "readme": BASE_DIR / "README.md",
    "open-source": BASE_DIR / "OPEN_SOURCE_READINESS.md",
    "architecture": BASE_DIR / "docs" / "ARCHITECTURE.md",
    "control-plane-architecture": BASE_DIR / "docs" / "ENGINEERING_CONTROL_PLANE_ARCHITECTURE.md",
    "masterplan": BASE_DIR / "docs" / "AI_ENGINEERING_CONTROL_HUB_MASTERPLAN.md",
    "implementation-status": BASE_DIR / "docs" / "MASTERPLAN_IMPLEMENTATION_STATUS.md",
    "parity": BASE_DIR / "docs" / "MASTERPLAN_PARITY_LEDGER.md",
    "github-workflow": BASE_DIR / "docs" / "GITHUB_FIRST_WORKFLOW.md",
    "custom-models": BASE_DIR / "docs" / "CUSTOM_MODELS.md",
    "control-center-stage1": BASE_DIR / "docs" / "CONTROL_CENTER_STAGE1.md",
    "react-api-contracts": BASE_DIR / "docs" / "react-migration" / "API_CONTRACTS.md",
    "react-local-development": BASE_DIR / "docs" / "react-migration" / "LOCAL_DEVELOPMENT.md",
    "react-test-matrix": BASE_DIR / "docs" / "react-migration" / "TEST_MATRIX.md",
    "react-migration-log": BASE_DIR / "docs" / "react-migration" / "MIGRATION_LOG.md",
    "dependency-inventory": BASE_DIR / "docs" / "generated" / "DEPENDENCY_INVENTORY.md",
    "routes-json": BASE_DIR / "docs" / "generated" / "http_routes.json",
    "schema-json": BASE_DIR / "docs" / "generated" / "database_schema.json",
    "imports-json": BASE_DIR / "docs" / "generated" / "python_import_graph.json",
    "frontend-imports-json": BASE_DIR / "docs" / "generated" / "frontend_import_graph.json",
    "dependencies-json": BASE_DIR / "docs" / "generated" / "dependencies.json",
    "contributing": BASE_DIR / "CONTRIBUTING.md",
    "security": BASE_DIR / "SECURITY.md",
    "conduct": BASE_DIR / "CODE_OF_CONDUCT.md",
    "deploy": BASE_DIR / "deploy" / "DEPLOY.md",
    "config-example": BASE_DIR / "config.example.json",
}


async def handle_control_operations(request: web.Request) -> web.Response:
    """Return active, waiting, and recently completed control operations."""
    coordinator = request.app[CONTROL_COORDINATOR_KEY]
    return web.json_response(await coordinator.status())


async def handle_control_plane_docs(request: web.Request) -> web.Response:
    """Serve an allowlisted Markdown document without accepting file paths."""
    document_id = request.match_info.get("document_id", "operator")
    document_path = CONTROL_DOC_PATHS.get(document_id)
    if document_path is None:
        return web.json_response(
            {"error": "Documentation was not found."},
            status=404,
        )
    if not document_path.is_file():
        return web.json_response(
            {"error": "Documentation is missing."},
            status=404,
        )
    return web.Response(
        text=document_path.read_text(encoding="utf-8"),
        content_type="text/markdown",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )
