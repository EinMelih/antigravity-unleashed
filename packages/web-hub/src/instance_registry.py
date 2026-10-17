"""Canonical, read-only Anti-Gravity desktop instance read model."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


_ACTIVITY_MAP = {
    "user": "manual",
    "idle": "idle",
    "preparing": "preparing",
    "sending": "sending",
    "working": "working",
    "waiting_human": "waiting_human",
    "error": "error",
    "dictation_preparing": "preparing",
    "dictation_ready": "idle",
    "dictation_recording": "working",
}
_BUSY_ACTIVITIES = {"preparing", "sending", "working", "waiting_human"}


def _utc_timestamp(value: Optional[str]) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _conversation_summary(
    conversation_id: Optional[str],
    conversations: Mapping[str, Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    if not conversation_id:
        return None
    source = conversations.get(conversation_id) or {}
    return {
        "conversation_id": conversation_id,
        "title": source.get("title"),
        "status": source.get("status"),
        "kind": source.get("conversation_type"),
        "project_name": source.get("project_name"),
        "repository_name": source.get("repository_name"),
    }


def _instance_row(
    source: Mapping[str, Any],
    *,
    role: str,
    conversations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    assigned_chat_id = str(source.get("chat_id") or "") or None
    if role == "primary":
        live_chat_id = assigned_chat_id
        binding_status = "none"
    else:
        live_chat_id = str(source.get("loaded_chat_id") or "") or None
        if assigned_chat_id is None and live_chat_id is None:
            binding_status = "none"
        elif assigned_chat_id == live_chat_id:
            binding_status = "confirmed"
        else:
            binding_status = "mismatch"

    availability = (
        "unreachable"
        if source.get("runtime_reachable") is False
        else "online"
    )
    activity = _ACTIVITY_MAP.get(str(source.get("state") or ""), "unknown")
    if availability == "unreachable":
        activity = "unknown"

    instance_id = "MAIN" if role == "primary" else str(source.get("window_id") or "")
    detail_code = (
        "runtime_unreachable"
        if availability == "unreachable"
        else (
            "conversation_mismatch"
            if binding_status == "mismatch"
            else f"{role}_{activity}"
        )
    )
    return {
        "instance_ref": str(source.get("target_id") or ""),
        "instance_id": instance_id,
        "role": role,
        "availability": availability,
        "activity": activity,
        "detail_code": detail_code,
        "conversation": _conversation_summary(live_chat_id, conversations),
        "binding_status": binding_status,
        "focused": bool(source.get("focused")),
        "has_draft": bool(source.get("has_draft")),
        "can_close": bool(
            role == "worker"
            and availability == "online"
            and activity == "idle"
            and not source.get("reserved")
            and not source.get("has_draft")
        ),
        "can_focus": bool(source.get("can_focus")) and availability == "online",
        "can_snap": bool(source.get("can_snap")) and availability == "online",
        "updated_at": source.get("updated_at"),
    }


def build_instance_read_model(
    snapshot: Optional[Mapping[str, Any]],
    conversations: Iterable[Mapping[str, Any]] = (),
    *,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Reconcile one live CDP snapshot into the stable Hub instance contract."""
    conversation_index = {
        str(item.get("convo_id")): item
        for item in conversations
        if item.get("convo_id")
    }
    snapshot = snapshot or {}
    instances = []
    primary = snapshot.get("primary")
    if isinstance(primary, Mapping):
        instances.append(
            _instance_row(primary, role="primary", conversations=conversation_index)
        )
    for worker in snapshot.get("workers") or []:
        if not isinstance(worker, Mapping):
            continue
        role = "dictation" if worker.get("purpose") == "dictation" else "worker"
        instances.append(
            _instance_row(worker, role=role, conversations=conversation_index)
        )

    worker_instances = [item for item in instances if item["role"] == "worker"]
    online_count = sum(item["availability"] == "online" for item in instances)
    unreachable_count = len(instances) - online_count
    if not instances or online_count == 0:
        connection = "offline"
    elif unreachable_count or primary is None:
        connection = "degraded"
    else:
        connection = "online"

    raw_capacity = snapshot.get("capacity") or {}
    capacity = {
        "open_workers": len(worker_instances),
        "busy_workers": sum(
            item["availability"] == "online"
            and item["activity"] in _BUSY_ACTIVITIES
            for item in worker_instances
        ),
        "idle_workers": sum(
            item["availability"] == "online" and item["activity"] == "idle"
            for item in worker_instances
        ),
        "maximum_workers": int(raw_capacity.get("maximum") or 0),
        "queued": int(raw_capacity.get("queued") or 0),
    }
    revision_source = {
        "connection": connection,
        "stale": connection != "online",
        "instances": instances,
        "capacity": capacity,
    }
    revision = hashlib.sha256(
        json.dumps(revision_source, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "connection": connection,
        "observed_at": _utc_timestamp(observed_at),
        "revision": revision,
        "stale": connection != "online",
        "instances": instances,
        "capacity": capacity,
    }
