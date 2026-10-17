"""Curated machine-control surface for Anti-Gravity MCP adapters.

The service deliberately talks to the public Hub HTTP control plane.  It never
calls CDP, database, DOM, or handler internals directly, so the existing lease,
idempotency, audit, workspace, and human-review contracts remain authoritative.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional

from src.hub_control_gateway import (
    HubControlClient,
    HubControlError,
    HubResult,
)


class ControlMode(IntEnum):
    """Maximum authority granted to one MCP server process."""

    OBSERVE = 0
    OPERATE = 1
    ADMINISTER = 2

    @classmethod
    def parse(cls, value: str) -> "ControlMode":
        normalized = str(value or "observe").strip().lower()
        aliases = {
            "observe": cls.OBSERVE,
            "read": cls.OBSERVE,
            "operate": cls.OPERATE,
            "write": cls.OPERATE,
            "administer": cls.ADMINISTER,
            "admin": cls.ADMINISTER,
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise ValueError(
                "ANTIGRAVITY_MCP_MODE must be observe, operate, or administer."
            ) from error

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Capability:
    name: str
    kind: str
    minimum_mode: ControlMode
    summary: str
    reversible: bool = True
    requires_desktop: bool = False

    def public(self, active_mode: ControlMode) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "minimum_mode": self.minimum_mode.label,
            "enabled": active_mode >= self.minimum_mode,
            "reversible": self.reversible,
            "requires_desktop": self.requires_desktop,
            "summary": self.summary,
        }


CAPABILITIES: tuple[Capability, ...] = (
    Capability("status", "read", ControlMode.OBSERVE, "Read Hub, services, and native desktop readiness."),
    Capability("conversations", "read", ControlMode.OBSERVE, "Search the canonical Anti-Gravity conversation catalog."),
    Capability("conversation_history", "read", ControlMode.OBSERVE, "Read persisted native or Hub-provider conversation history."),
    Capability("instances", "read", ControlMode.OBSERVE, "Read MAIN and AG worker identity, activity, binding, and capacity."),
    Capability("projects", "read", ControlMode.OBSERVE, "Read registered projects and one project's detected stack."),
    Capability("engineering", "read", ControlMode.OBSERVE, "Read ideas, planning jobs, work items, evidence state, and operation audit."),
    Capability("models", "read", ControlMode.OBSERVE, "Read the live native and Hub-provider model catalog."),
    Capability("create_chat", "write", ControlMode.OPERATE, "Create and verify a native normal or project chat.", requires_desktop=True),
    Capability("send_message", "write", ControlMode.OPERATE, "Send through the exact bound worker and verify persistence.", requires_desktop=True),
    Capability("manage_chat", "write", ControlMode.OPERATE, "Open, archive, restore, and select a conversation model.", requires_desktop=True),
    Capability("create_project", "write", ControlMode.OPERATE, "Create a registered project and optionally its private GitHub repository."),
    Capability("link_native_project", "write", ControlMode.OPERATE, "Import a registered repository into the running desktop app.", requires_desktop=True),
    Capability("idea_to_plan", "write", ControlMode.OPERATE, "Create an idea and start grounded planning; waiting questions are handed to a human in the Hub."),
    Capability("advance_campaign_wave", "write", ControlMode.OPERATE, "Materialize the next wave allowed by a previously human-approved campaign policy."),
    Capability("run_executor_once", "write", ControlMode.OPERATE, "Wake one executor cycle for already approved work; grants no approval.", requires_desktop=True),
    Capability("task_machine_actions", "write", ControlMode.OPERATE, "Synchronize GitHub state and evaluate task evidence without approving it."),
    Capability("restore_project", "write", ControlMode.OPERATE, "Restore a reversibly archived Hub project."),
    Capability("delete_chat", "destructive", ControlMode.ADMINISTER, "Delete one exact chat; native chats pass live busy/draft/binding gates, while provider/proxy chats use their local stored-record contract.", reversible=False, requires_desktop=True),
    Capability("close_worker", "destructive", ControlMode.ADMINISTER, "Close one exact idle, draft-free AG worker.", reversible=False, requires_desktop=True),
    Capability("archive_project", "administrative", ControlMode.ADMINISTER, "Reversibly remove one project from active Hub views."),
)


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_PLANNING_DEPTHS = {"compact", "balanced", "deep", "exhaustive"}
_ACTIVATION_POLICIES = {"per_candidate", "campaign_wave", "autopilot"}
_SQLITE_INTEGER_MAX = 9_223_372_036_854_775_807
_MAX_CHAT_ATTACHMENTS = 5


class MCPControlError(RuntimeError):
    """Stable public error raised before a request reaches the Hub."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

    def public(self) -> Dict[str, Any]:
        return {"error": str(self), "code": self.code}


def _require_text(value: Any, field: str, *, maximum: int = 50_000) -> str:
    text = str(value or "").strip()
    if not text:
        raise MCPControlError(f"{field} is required.", code=f"{field}_required")
    if len(text) > maximum:
        raise MCPControlError(
            f"{field} exceeds {maximum} characters.",
            code=f"{field}_too_long",
        )
    return text


def _require_idempotency_key(value: Any) -> str:
    key = str(value or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise MCPControlError(
            "idempotency_key must contain 1-128 letters, digits, '.', '_', ':' or '-'.",
            code="invalid_idempotency_key",
        )
    return key


def _chat_attachment_payloads(
    attachments: Optional[Iterable[Mapping[str, Any]]],
) -> list[Dict[str, Any]]:
    if attachments is None:
        return []
    if isinstance(attachments, (str, bytes, Mapping)):
        raise MCPControlError(
            "attachments must be a list of image objects.",
            code="invalid_chat_attachment",
        )
    try:
        items = list(attachments)
    except TypeError as error:
        raise MCPControlError(
            "attachments must be a list of image objects.",
            code="invalid_chat_attachment",
        ) from error
    payloads: list[Dict[str, Any]] = []
    required_fields = {"name", "type", "data"}
    for item in items:
        if not isinstance(item, Mapping) or set(item) != required_fields:
            raise MCPControlError(
                "Each attachment must contain only name, type, and data.",
                code="invalid_chat_attachment",
            )
        payloads.append({field: item[field] for field in ("name", "type", "data")})
    if len(payloads) > _MAX_CHAT_ATTACHMENTS:
        raise MCPControlError(
            f"A maximum of {_MAX_CHAT_ATTACHMENTS} images can be attached.",
            code="too_many_chat_attachments",
        )
    return payloads


def _require_bounded_integer(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = _SQLITE_INTEGER_MAX,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        if minimum == 1 and maximum == _SQLITE_INTEGER_MAX:
            message = f"{field} must be a positive SQLite integer."
        else:
            message = f"{field} must be an integer between {minimum} and {maximum}."
        raise MCPControlError(message, code=f"invalid_{field}")
    return value


def _require_boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise MCPControlError(
            f"{field} must be true or false.",
            code=f"invalid_{field}",
        )
    return value


def _public_result(result: HubResult) -> Dict[str, Any]:
    response: Dict[str, Any] = {
        "data": result.payload,
        "control": {
            "http_status": result.status,
            "operation_id": result.operation_id,
            "deduplicated": result.deduplicated,
        },
    }
    return response


class MCPControlService:
    """Semantic Anti-Gravity commands backed by a replaceable Hub gateway."""

    def __init__(
        self,
        gateway: HubControlClient,
        *,
        mode: ControlMode = ControlMode.OBSERVE,
    ) -> None:
        self.gateway = gateway
        self.mode = mode

    def capabilities(self) -> Dict[str, Any]:
        return {
            "protocol": "antigravity-mcp",
            "version": "1.0",
            "mode": self.mode.label,
            "capabilities": [item.public(self.mode) for item in CAPABILITIES],
            "human_gates": {
                "delegated": False,
                "excluded_actions": [
                    "campaign_approval",
                    "planning_question_answer",
                    "direct_manual_work_order_approval",
                    "human_test_approval",
                    "merge_approval",
                    "github_merge",
                    "deployment",
                    "rollback",
                    "remote_github_repository_deletion",
                ],
                "handoff": {
                    "surface": "Hub > Automation > Braucht deine Entscheidung",
                    "instruction": (
                        "Open the planning job in the Hub and let a human answer "
                        "the waiting question there."
                    ),
                },
            },
            "raw_access": {
                "dom": False,
                "javascript": False,
                "database_rows": False,
                "filesystem": False,
                "secrets": False,
            },
        }

    def _require_mode(self, required: ControlMode, action: str) -> None:
        if self.mode < required:
            raise MCPControlError(
                f"{action} requires MCP mode {required.label}; current mode is {self.mode.label}.",
                code="mcp_capability_denied",
            )

    async def _partial_read(
        self,
        name: str,
        call: Callable[[], Awaitable[HubResult]],
    ) -> tuple[str, Dict[str, Any], bool]:
        try:
            result = await call()
            return name, _public_result(result), True
        except HubControlError as error:
            return name, {"error": error.public()}, False

    async def status(self) -> Dict[str, Any]:
        parts = await asyncio.gather(
            self._partial_read("hub", lambda: self.gateway.get("/health")),
            self._partial_read(
                "system", lambda: self.gateway.get("/api/system/overview")
            ),
            self._partial_read(
                "instances", lambda: self.gateway.get("/api/antigravity/instances")
            ),
        )
        payload = {name: value for name, value, _ in parts}
        healthy = all(ok for _, _, ok in parts)
        hub_data = payload.get("hub", {}).get("data", {})
        system_data = payload.get("system", {}).get("data", {})
        instances_data = payload.get("instances", {}).get("data", {})
        backend_connected = bool(
            (hub_data.get("antigravity_backend") or {}).get("connected")
        )
        integration_connected = bool(
            ((system_data.get("integrations") or {}).get("antigravity") or {}).get(
                "connected"
            )
        )
        system_healthy = (
            str(system_data.get("status") or "").strip().lower() == "healthy"
        )
        instance_online = (
            instances_data.get("connection") == "online"
            and any(
                item.get("availability") == "online"
                for item in instances_data.get("instances") or []
                if isinstance(item, dict)
            )
        )
        api_bridge = next(
            (
                item
                for item in system_data.get("services") or []
                if isinstance(item, dict) and item.get("id") == "api_bridge"
            ),
            {},
        )
        bridge_details = api_bridge.get("details") or {}
        bridge_ready = (
            api_bridge.get("status") == "healthy"
            and bridge_details.get("ready") is True
            and bridge_details.get("cdp_status") == "connected"
            and bridge_details.get("bridge") == "injected"
        )
        native_ready = (
            backend_connected
            and integration_connected
            and instance_online
            and bridge_ready
        )
        return {
            "status": (
                "ready"
                if healthy and system_healthy and native_ready
                else "degraded"
            ),
            "hub_reachable": "error" not in payload.get("hub", {}),
            "native_ready": native_ready,
            "parts": payload,
            "note": (
                "Native readiness requires the allowlisted API-bridge injection proof; "
                "Hub or TCP health alone is insufficient."
            ),
        }

    async def list_conversations(
        self,
        *,
        project_id: Optional[int] = None,
        include_archived: bool = False,
        search: str = "",
    ) -> Dict[str, Any]:
        include_archived = _require_boolean(include_archived, "include_archived")
        statuses = "running,complete,archived" if include_archived else "running,complete"
        query: Dict[str, Any] = {"type": "all", "status": statuses}
        if project_id is not None:
            query["project_id"] = _require_bounded_integer(project_id, "project_id")
        if str(search or "").strip():
            query["search"] = str(search).strip()[:500]
        return _public_result(
            await self.gateway.get("/api/antigravity/conversations", query=query)
        )

    async def read_conversation(self, conversation_id: str) -> Dict[str, Any]:
        conversation_id = _require_text(conversation_id, "conversation_id", maximum=200)
        return _public_result(
            await self.gateway.get(
                "/api/antigravity/chats/{conversation_id}/history",
                path_params={"conversation_id": conversation_id},
            )
        )

    async def list_instances(self) -> Dict[str, Any]:
        return _public_result(await self.gateway.get("/api/antigravity/instances"))

    async def list_projects(self, *, include_archived: bool = False) -> Dict[str, Any]:
        include_archived = _require_boolean(include_archived, "include_archived")
        return _public_result(
            await self.gateway.get(
                "/api/projects",
                query={"include_archived": "true"} if include_archived else None,
            )
        )

    async def project_stack(self, project_id: int) -> Dict[str, Any]:
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.get(
                "/api/projects/{project_id}/stack",
                path_params={"project_id": project_id},
            )
        )

    async def project_removal_impact(self, project_id: int) -> Dict[str, Any]:
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.get(
                "/api/projects/{project_id}/removal-impact",
                path_params={"project_id": project_id},
            )
        )

    async def engineering_overview(
        self, *, project_id: Optional[int] = None
    ) -> Dict[str, Any]:
        query = (
            {"project_id": _require_bounded_integer(project_id, "project_id")}
            if project_id is not None
            else None
        )
        return _public_result(
            await self.gateway.get("/api/control-center/overview", query=query)
        )

    async def list_operations(self) -> Dict[str, Any]:
        return _public_result(await self.gateway.get("/api/control-plane/operations"))

    async def list_models(self) -> Dict[str, Any]:
        return _public_result(await self.gateway.get("/api/antigravity/models"))

    async def active_model(self, conversation_id: str) -> Dict[str, Any]:
        conversation_id = _require_text(conversation_id, "conversation_id", maximum=200)
        return _public_result(
            await self.gateway.get(
                "/api/antigravity/active-model",
                query={"convo_id": conversation_id},
            )
        )

    async def list_ideas(self, *, project_id: Optional[int] = None) -> Dict[str, Any]:
        query = (
            {"project_id": _require_bounded_integer(project_id, "project_id")}
            if project_id is not None
            else None
        )
        return _public_result(
            await self.gateway.get("/api/control-center/idea-seeds", query=query)
        )

    async def list_planning_jobs(
        self, *, project_id: Optional[int] = None
    ) -> Dict[str, Any]:
        query = (
            {"project_id": _require_bounded_integer(project_id, "project_id")}
            if project_id is not None
            else None
        )
        return _public_result(
            await self.gateway.get("/api/control-center/planning-jobs", query=query)
        )

    async def planning_job(self, job_id: str) -> Dict[str, Any]:
        job_id = _require_text(job_id, "job_id", maximum=200)
        return _public_result(
            await self.gateway.get(
                "/api/control-center/planning-jobs/{job_id}",
                path_params={"job_id": job_id},
            )
        )

    async def list_work_items(
        self,
        *,
        project_id: Optional[int] = None,
        campaign_id: str = "",
        status: str = "",
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if project_id is not None:
            query["project_id"] = _require_bounded_integer(project_id, "project_id")
        if str(campaign_id or "").strip():
            query["campaign_id"] = str(campaign_id).strip()
        if str(status or "").strip():
            query["status"] = str(status).strip()
        return _public_result(
            await self.gateway.get("/api/control-center/tasks", query=query or None)
        )

    async def work_item(self, task_id: str) -> Dict[str, Any]:
        task_id = _require_text(task_id, "task_id", maximum=200)
        return _public_result(
            await self.gateway.get(
                "/api/control-center/tasks/{task_id}",
                path_params={"task_id": task_id},
            )
        )

    async def create_chat(
        self,
        *,
        message: str,
        idempotency_key: str,
        conversation_type: str = "normal",
        project_id: Optional[int] = None,
        attachments: Optional[Iterable[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "create_chat")
        attachment_payload = _chat_attachment_payloads(attachments)
        message = str(message or "").strip()
        if message:
            message = _require_text(message, "message")
        elif not attachment_payload:
            message = _require_text(message, "message")
        key = _require_idempotency_key(idempotency_key)
        chat_type = str(conversation_type or "normal").strip().lower()
        if chat_type not in {"normal", "project"}:
            raise MCPControlError(
                "conversation_type must be normal or project.",
                code="invalid_conversation_type",
            )
        if chat_type == "project" and project_id is None:
            raise MCPControlError(
                "project_id is required for a project chat.",
                code="project_id_required",
            )
        body: Dict[str, Any] = {
            "message": message,
            "attachments": attachment_payload,
            "conversation_type": chat_type,
        }
        if project_id is not None:
            body["project_id"] = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.mutate(
                "POST", "/api/antigravity/chats", json_body=body, idempotency_key=key
            )
        )

    async def send_message(
        self,
        *,
        conversation_id: str,
        message: str,
        attachments: Optional[Iterable[Mapping[str, Any]]] = None,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "send_message")
        conversation_id = _require_text(conversation_id, "conversation_id", maximum=200)
        attachment_payload = _chat_attachment_payloads(attachments)
        message = str(message or "").strip()
        if message:
            message = _require_text(message, "message")
        elif not attachment_payload:
            message = _require_text(message, "message")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/antigravity/chats/{conversation_id}/message",
                path_params={"conversation_id": conversation_id},
                json_body={"message": message, "attachments": attachment_payload},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def _conversation_action(
        self,
        action: str,
        conversation_id: str,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, action)
        conversation_id = _require_text(conversation_id, "conversation_id", maximum=200)
        return _public_result(
            await self.gateway.mutate(
                "POST",
                f"/api/antigravity/chats/{{conversation_id}}/{action}",
                path_params={"conversation_id": conversation_id},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def open_chat(
        self, *, conversation_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        return await self._conversation_action("window", conversation_id, idempotency_key)

    async def archive_chat(
        self, *, conversation_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        return await self._conversation_action("archive", conversation_id, idempotency_key)

    async def restore_chat(
        self, *, conversation_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        return await self._conversation_action("restore", conversation_id, idempotency_key)

    async def set_model(
        self,
        *,
        conversation_id: str,
        model: str,
        idempotency_key: str,
        source: str = "native",
        custom_model_id: Optional[int] = None,
        model_id: str = "",
        reasoning_effort: str = "",
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "set_model")
        model_source = str(source or "native").strip().lower()
        if model_source not in {"native", "custom"}:
            raise MCPControlError(
                "source must be native or custom.",
                code="invalid_model_source",
            )
        normalized_model_id = str(model_id or "").strip()
        if len(normalized_model_id) > 300:
            raise MCPControlError(
                "model_id exceeds 300 characters.",
                code="model_id_too_long",
            )
        normalized_reasoning_effort = str(reasoning_effort or "").strip()
        if len(normalized_reasoning_effort) > 50:
            raise MCPControlError(
                "reasoning_effort exceeds 50 characters.",
                code="reasoning_effort_too_long",
            )
        if normalized_model_id:
            raise MCPControlError(
                "model_id is not accepted for native or custom sources.",
                code="model_id_not_allowed",
            )
        if normalized_reasoning_effort:
            raise MCPControlError(
                "reasoning_effort is not accepted for native or custom sources.",
                code="reasoning_effort_not_allowed",
            )
        normalized_custom_model_id: Optional[int] = None
        if model_source == "custom":
            if custom_model_id is None:
                raise MCPControlError(
                    "custom_model_id is required when source is custom.",
                    code="custom_model_id_required",
                )
            normalized_custom_model_id = _require_bounded_integer(
                custom_model_id,
                "custom_model_id",
            )
        elif custom_model_id is not None:
            raise MCPControlError(
                "custom_model_id is only valid when source is custom.",
                code="custom_model_id_not_allowed",
            )
        body: Dict[str, Any] = {
            "convo_id": _require_text(conversation_id, "conversation_id", maximum=200),
            "model": _require_text(model, "model", maximum=300),
            "source": model_source,
        }
        if normalized_custom_model_id is not None:
            body["custom_model_id"] = normalized_custom_model_id
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/antigravity/active-model",
                json_body=body,
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def create_project(
        self,
        *,
        name: str,
        idempotency_key: str,
        create_github: bool = False,
        confirm_remote_creation: bool = False,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "create_project")
        create_github = _require_boolean(create_github, "create_github")
        confirm_remote_creation = _require_boolean(
            confirm_remote_creation,
            "confirm_remote_creation",
        )
        if create_github and not confirm_remote_creation:
            raise MCPControlError(
                "confirm_remote_creation=true is required before creating a GitHub repository.",
                code="remote_creation_confirmation_required",
            )
        body = {
            "name": _require_text(name, "name", maximum=100),
            "create_github": create_github,
            "github_visibility": "private",
        }
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/projects",
                json_body=body,
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def create_native_project(
        self, *, project_id: int, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "create_native_project")
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/projects/{project_id}/antigravity-project",
                path_params={"project_id": project_id},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def create_idea(
        self,
        *,
        project_id: int,
        title: str,
        note: str,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "create_idea")
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/idea-seeds",
                json_body={
                    "project_id": project_id,
                    "title": _require_text(title, "title", maximum=200),
                    "note": _require_text(note, "note", maximum=5000),
                    "source": "mcp-agent",
                    "provenance": {"channel": "mcp", "human_approved": False},
                },
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def plan_idea(
        self,
        *,
        idea_seed_id: str,
        idempotency_key: str,
        planning_depth: str = "balanced",
        max_candidates: int = 12,
        activation_policy: str = "per_candidate",
        constraints: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "plan_idea")
        depth = str(planning_depth or "balanced").strip().lower()
        activation = str(activation_policy or "per_candidate").strip().lower()
        if depth not in _PLANNING_DEPTHS:
            raise MCPControlError("Unknown planning_depth.", code="invalid_planning_depth")
        if activation not in _ACTIVATION_POLICIES:
            raise MCPControlError(
                "Unknown activation_policy.", code="invalid_activation_policy"
            )
        maximum = _require_bounded_integer(
            max_candidates,
            "max_candidates",
            maximum=100,
        )
        clean_constraints = [
            str(item).strip()[:2000]
            for item in (constraints or [])
            if str(item).strip()
        ]
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/idea-seeds/{idea_seed_id}/plan",
                path_params={"idea_seed_id": _require_text(idea_seed_id, "idea_seed_id", maximum=200)},
                json_body={
                    "planning_depth": depth,
                    "max_candidates": maximum,
                    "activation_policy": activation,
                    "constraints": clean_constraints,
                    "actor": "mcp-agent",
                },
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def retry_planning(
        self, *, job_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "retry_planning")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/planning-jobs/{job_id}/retry",
                path_params={"job_id": _require_text(job_id, "job_id", maximum=200)},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def advance_campaign_wave(
        self, *, campaign_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        """Materialize the next wave allowed by an approved campaign policy."""
        self._require_mode(ControlMode.OPERATE, "advance_campaign_wave")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/campaigns/{campaign_id}/activate-wave",
                path_params={
                    "campaign_id": _require_text(
                        campaign_id,
                        "campaign_id",
                        maximum=200,
                    )
                },
                json_body={"actor": "mcp-orchestrator"},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def run_executor_once(
        self, *, idempotency_key: str
    ) -> Dict[str, Any]:
        """Run one executor cycle for work that already passed its policy gates."""
        self._require_mode(ControlMode.OPERATE, "run_executor_once")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/executor/tick",
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def sync_task(
        self, *, task_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "sync_task")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/tasks/{task_id}/github/sync",
                path_params={"task_id": _require_text(task_id, "task_id", maximum=200)},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def evaluate_evidence(
        self, *, task_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "evaluate_evidence")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/control-center/tasks/{task_id}/evidence/evaluate",
                path_params={"task_id": _require_text(task_id, "task_id", maximum=200)},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def restore_project(
        self, *, project_id: int, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.OPERATE, "restore_project")
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.mutate(
                "POST",
                "/api/projects/{project_id}/restore",
                path_params={"project_id": project_id},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def delete_chat(
        self, *, conversation_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.ADMINISTER, "delete_chat")
        return _public_result(
            await self.gateway.mutate(
                "DELETE",
                "/api/antigravity/chats/{conversation_id}",
                path_params={"conversation_id": _require_text(conversation_id, "conversation_id", maximum=200)},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def close_worker(
        self, *, target_id: str, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.ADMINISTER, "close_worker")
        return _public_result(
            await self.gateway.mutate(
                "DELETE",
                "/api/antigravity/workers/{target_id}",
                path_params={"target_id": _require_text(target_id, "target_id", maximum=300)},
                json_body={},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )

    async def archive_project(
        self, *, project_id: int, idempotency_key: str
    ) -> Dict[str, Any]:
        self._require_mode(ControlMode.ADMINISTER, "archive_project")
        project_id = _require_bounded_integer(project_id, "project_id")
        return _public_result(
            await self.gateway.mutate(
                "DELETE",
                "/api/projects/{project_id}",
                path_params={"project_id": project_id},
                json_body={"mode": "hub_only", "delete_remote_repository": False},
                idempotency_key=_require_idempotency_key(idempotency_key),
            )
        )
