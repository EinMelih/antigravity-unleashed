"""Official MCP stdio adapter for the Anti-Gravity Hub control plane."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as error:  # pragma: no cover - exercised by launcher smoke tests
    raise RuntimeError(
        "The optional MCP runtime is not installed. Run "
        "`python -m pip install -r requirements-mcp.lock.txt`."
    ) from error

from src.hub_control_gateway import HubControlError, HubControlGateway
from src.mcp_control import ControlMode, MCPControlError, MCPControlService


_T = TypeVar("_T")
_SQLITE_INTEGER_MAX = 9_223_372_036_854_775_807
StrictProjectId = Annotated[
    int,
    Field(strict=True, ge=1, le=_SQLITE_INTEGER_MAX),
]
StrictCustomModelId = Annotated[
    int,
    Field(strict=True, ge=1, le=_SQLITE_INTEGER_MAX),
]
StrictCandidateCount = Annotated[int, Field(strict=True, ge=1, le=100)]
StrictBoolean = Annotated[bool, Field(strict=True)]


class MCPImageAttachment(BaseModel):
    """Inline image accepted by the guarded Hub attachment validator."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=255)]
    type: Literal[
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    ]
    data: Annotated[str, Field(min_length=1)]


StrictChatAttachments = Annotated[
    list[MCPImageAttachment],
    Field(max_length=5),
]


def _env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


def _build_gateway() -> HubControlGateway:
    try:
        timeout = float(os.environ.get("ANTIGRAVITY_MCP_TIMEOUT_SECONDS", "30"))
    except ValueError as error:
        raise RuntimeError(
            "ANTIGRAVITY_MCP_TIMEOUT_SECONDS must be a positive number."
        ) from error
    return HubControlGateway(
        base_url=os.environ.get(
            "ANTIGRAVITY_HUB_URL",
            "http://127.0.0.1:8000",
        ),
        bearer_token=os.environ.get("ANTIGRAVITY_HUB_TOKEN", ""),
        allow_remote=_env_bool("ANTIGRAVITY_MCP_ALLOW_REMOTE"),
        timeout_seconds=timeout,
    )


gateway = _build_gateway()
service = MCPControlService(
    gateway,
    mode=ControlMode.parse(os.environ.get("ANTIGRAVITY_MCP_MODE", "observe")),
)


@asynccontextmanager
async def _lifespan(_server: MCPServer) -> AsyncIterator[dict[str, Any]]:
    try:
        yield {"gateway": gateway, "service": service}
    finally:
        await gateway.close()


mcp = MCPServer(
    "Anti-Gravity Hub",
    version="1.0.0",
    instructions=(
        "Read and operate the local Anti-Gravity desktop through its guarded Hub "
        "control plane. Respect the reported capability mode and never represent "
        "an MCP action as human approval."
    ),
    lifespan=_lifespan,
)


async def _invoke(awaitable: Awaitable[_T]) -> _T:
    try:
        return await awaitable
    except MCPControlError as error:
        raise ToolError(json.dumps(error.public(), sort_keys=True)) from error
    except HubControlError as error:
        raise ToolError(json.dumps(error.public(), sort_keys=True)) from error


@mcp.resource("antigravity://capabilities")
def antigravity_capabilities_resource() -> str:
    """Machine-readable authority and safety boundary for this server process."""
    return json.dumps(service.capabilities(), ensure_ascii=False, sort_keys=True)


@mcp.resource("antigravity://status")
async def antigravity_status_resource() -> str:
    """Current Hub and native desktop readiness as JSON."""
    return json.dumps(
        await _invoke(service.status()),
        ensure_ascii=False,
        sort_keys=True,
    )


@mcp.tool()
def antigravity_capabilities() -> dict[str, Any]:
    """List enabled capabilities, required modes, and non-delegated human gates."""
    return service.capabilities()


@mcp.tool()
async def antigravity_status() -> dict[str, Any]:
    """Read Hub, service, and native instance readiness without false healthy claims."""
    return await _invoke(service.status())


@mcp.tool()
async def antigravity_list_conversations(
    project_id: Optional[StrictProjectId] = None,
    include_archived: StrictBoolean = False,
    search: str = "",
) -> dict[str, Any]:
    """Search the canonical conversation catalog, optionally scoped to one project."""
    return await _invoke(
        service.list_conversations(
            project_id=project_id,
            include_archived=include_archived,
            search=search,
        )
    )


@mcp.tool()
async def antigravity_read_conversation(conversation_id: str) -> dict[str, Any]:
    """Read persisted message history for one native or Hub-provider conversation."""
    return await _invoke(service.read_conversation(conversation_id))


@mcp.tool()
async def antigravity_list_instances() -> dict[str, Any]:
    """Read MAIN and AG worker activity, binding, draft state, and capacity."""
    return await _invoke(service.list_instances())


@mcp.tool()
async def antigravity_list_projects(
    include_archived: StrictBoolean = False,
) -> dict[str, Any]:
    """Read registered Hub projects; archived projects are opt-in."""
    return await _invoke(service.list_projects(include_archived=include_archived))


@mcp.tool()
async def antigravity_project_stack(project_id: StrictProjectId) -> dict[str, Any]:
    """Read detected manifests, runtime services, Docker metadata, and database schema metadata."""
    return await _invoke(service.project_stack(project_id))


@mcp.tool()
async def antigravity_project_removal_impact(
    project_id: StrictProjectId,
) -> dict[str, Any]:
    """Preview the retained and affected records before reversible Hub project archival."""
    return await _invoke(service.project_removal_impact(project_id))


@mcp.tool()
async def antigravity_engineering_overview(
    project_id: Optional[StrictProjectId] = None,
) -> dict[str, Any]:
    """Read campaigns, attention, planning, work items, evidence, and delivery state."""
    return await _invoke(service.engineering_overview(project_id=project_id))


@mcp.tool()
async def antigravity_list_operations() -> dict[str, Any]:
    """Read active, queued, and recent guarded control operations."""
    return await _invoke(service.list_operations())


@mcp.tool()
async def antigravity_list_models() -> dict[str, Any]:
    """Read the live native model catalog and explicit Hub-provider choices."""
    return await _invoke(service.list_models())


@mcp.tool()
async def antigravity_active_model(conversation_id: str) -> dict[str, Any]:
    """Read the confirmed model selection for one stable conversation."""
    return await _invoke(service.active_model(conversation_id))


@mcp.tool()
async def antigravity_list_ideas(
    project_id: Optional[StrictProjectId] = None,
) -> dict[str, Any]:
    """Read idea seeds, optionally scoped to one project."""
    return await _invoke(service.list_ideas(project_id=project_id))


@mcp.tool()
async def antigravity_list_planning_jobs(
    project_id: Optional[StrictProjectId] = None,
) -> dict[str, Any]:
    """Read grounded planning jobs and their waiting or terminal state."""
    return await _invoke(service.list_planning_jobs(project_id=project_id))


@mcp.tool()
async def antigravity_get_planning_job(job_id: str) -> dict[str, Any]:
    """Read one planning job including its current human-question handoff."""
    return await _invoke(service.planning_job(job_id))


@mcp.tool()
async def antigravity_list_work_items(
    project_id: Optional[StrictProjectId] = None,
    campaign_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Read agent work items by project, campaign, or status."""
    return await _invoke(
        service.list_work_items(
            project_id=project_id,
            campaign_id=campaign_id,
            status=status,
        )
    )


@mcp.tool()
async def antigravity_get_work_item(task_id: str) -> dict[str, Any]:
    """Read one work item without changing its execution or approval state."""
    return await _invoke(service.work_item(task_id))


@mcp.tool()
async def antigravity_create_chat(
    message: str,
    idempotency_key: str,
    conversation_type: str = "normal",
    project_id: Optional[StrictProjectId] = None,
    attachments: Optional[StrictChatAttachments] = None,
) -> dict[str, Any]:
    """Create a native chat with text or inline images. Requires operate mode."""
    return await _invoke(
        service.create_chat(
            message=message,
            idempotency_key=idempotency_key,
            conversation_type=conversation_type,
            project_id=project_id,
            attachments=[item.model_dump() for item in attachments or []],
        )
    )


@mcp.tool()
async def antigravity_send_message(
    conversation_id: str,
    message: str,
    idempotency_key: str,
    attachments: Optional[StrictChatAttachments] = None,
) -> dict[str, Any]:
    """Send text or inline images and verify persistence. Requires operate mode."""
    return await _invoke(
        service.send_message(
            conversation_id=conversation_id,
            message=message,
            idempotency_key=idempotency_key,
            attachments=[item.model_dump() for item in attachments or []],
        )
    )


@mcp.tool()
async def antigravity_open_chat(
    conversation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Prepare or reuse the dedicated native worker for one chat."""
    return await _invoke(
        service.open_chat(
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_archive_chat(
    conversation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Archive one conversation through the native verified bridge."""
    return await _invoke(
        service.archive_chat(
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_restore_chat(
    conversation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Restore one archived conversation through the native verified bridge."""
    return await _invoke(
        service.restore_chat(
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_set_model(
    conversation_id: str,
    model: str,
    idempotency_key: str,
    source: Literal["native", "custom"] = "native",
    custom_model_id: Optional[StrictCustomModelId] = None,
) -> dict[str, Any]:
    """Select a native model, or a saved custom provider by custom_model_id."""
    return await _invoke(
        service.set_model(
            conversation_id=conversation_id,
            model=model,
            idempotency_key=idempotency_key,
            source=source,
            custom_model_id=custom_model_id,
        )
    )


@mcp.tool()
async def antigravity_create_project(
    name: str,
    idempotency_key: str,
    create_github: StrictBoolean = False,
    confirm_remote_creation: StrictBoolean = False,
) -> dict[str, Any]:
    """Create a Hub project in the configured root; remote GitHub creation needs explicit confirmation."""
    return await _invoke(
        service.create_project(
            name=name,
            idempotency_key=idempotency_key,
            create_github=create_github,
            confirm_remote_creation=confirm_remote_creation,
        )
    )


@mcp.tool()
async def antigravity_create_native_project(
    project_id: StrictProjectId,
    idempotency_key: str,
) -> dict[str, Any]:
    """Import one registered repository into the running Anti-Gravity desktop app."""
    return await _invoke(
        service.create_native_project(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_create_idea(
    project_id: StrictProjectId,
    title: str,
    note: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create an idea seed for an existing project. Requires operate mode."""
    return await _invoke(
        service.create_idea(
            project_id=project_id,
            title=title,
            note=note,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_plan_idea(
    idea_seed_id: str,
    idempotency_key: str,
    planning_depth: str = "balanced",
    max_candidates: StrictCandidateCount = 12,
    activation_policy: str = "per_candidate",
    constraints: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Start repository-grounded idea-to-PR planning without approving the resulting plan."""
    return await _invoke(
        service.plan_idea(
            idea_seed_id=idea_seed_id,
            idempotency_key=idempotency_key,
            planning_depth=planning_depth,
            max_candidates=max_candidates,
            activation_policy=activation_policy,
            constraints=constraints,
        )
    )


@mcp.tool()
async def antigravity_retry_planning(
    job_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Retry one failed planning job through the existing durable planner."""
    return await _invoke(
        service.retry_planning(job_id=job_id, idempotency_key=idempotency_key)
    )


@mcp.tool()
async def antigravity_advance_campaign_wave(
    campaign_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Advance the next wave of a human-approved campaign policy; grants no approval."""
    return await _invoke(
        service.advance_campaign_wave(
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_run_executor_once(
    idempotency_key: str,
) -> dict[str, Any]:
    """Wake one executor cycle for work that already passed its policy gates."""
    return await _invoke(
        service.run_executor_once(idempotency_key=idempotency_key)
    )


@mcp.tool()
async def antigravity_sync_task(
    task_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Synchronize GitHub/CI/review state for one work item without approving or merging it."""
    return await _invoke(
        service.sync_task(task_id=task_id, idempotency_key=idempotency_key)
    )


@mcp.tool()
async def antigravity_evaluate_evidence(
    task_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Evaluate SHA-bound machine evidence without recording a human approval."""
    return await _invoke(
        service.evaluate_evidence(
            task_id=task_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_restore_project(
    project_id: StrictProjectId,
    idempotency_key: str,
) -> dict[str, Any]:
    """Restore a reversibly archived Hub project. Requires operate mode."""
    return await _invoke(
        service.restore_project(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_delete_chat(
    conversation_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Delete one exact chat; native IDs pass live safety gates. Requires administer mode."""
    return await _invoke(
        service.delete_chat(
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_close_worker(
    target_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Close one exact idle and draft-free AG worker. Requires administer mode."""
    return await _invoke(
        service.close_worker(
            target_id=target_id,
            idempotency_key=idempotency_key,
        )
    )


@mcp.tool()
async def antigravity_archive_project(
    project_id: StrictProjectId,
    idempotency_key: str,
) -> dict[str, Any]:
    """Reversibly archive one Hub project; never deletes its GitHub repository."""
    return await _invoke(
        service.archive_project(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
    )


def main() -> None:
    """Run the local server over MCP's default stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
