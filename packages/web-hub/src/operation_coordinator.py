"""Conflict-aware FIFO coordination for all mutating Hub control operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

from aiohttp import web

from src.redaction import redact_sensitive_text


TERMINAL_STATES = {"succeeded", "failed", "cancelled", "timed_out"}
CONTROL_AUDIT_MAX_BYTES = 5 * 1024 * 1024
CONTROL_AUDIT_BACKUP_COUNT = 3
CONTROL_ERROR_MAX_CHARS = 1_000
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
INTENT_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RESULT_REFERENCE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
RESULT_REFERENCE_FIELDS = frozenset(
    {
        "amendment_id",
        "campaign_id",
        "candidate_id",
        "checkpoint_id",
        "conversation_id",
        "convo_id",
        "custom_model_id",
        "finding_id",
        "idea_seed_id",
        "issue_id",
        "model_id",
        "planning_job_id",
        "project_id",
        "provider_id",
        "pull_request_id",
        "pull_request_number",
        "recommendation_id",
        "run_id",
        "scheduled_task_id",
        "session_id",
        "task_id",
        "work_order_id",
        "worker_id",
    }
)
RESULT_REFERENCE_ENTITIES = {
    "amendment": "amendment_id",
    "campaign": "campaign_id",
    "candidate": "candidate_id",
    "chat": "conversation_id",
    "checkpoint": "checkpoint_id",
    "conversation": "conversation_id",
    "custom_model": "custom_model_id",
    "finding": "finding_id",
    "idea_seed": "idea_seed_id",
    "issue": "issue_id",
    "model": "model_id",
    "planning_job": "planning_job_id",
    "project": "project_id",
    "provider": "provider_id",
    "pull_request": "pull_request_id",
    "recommendation": "recommendation_id",
    "run": "run_id",
    "scheduled_task": "scheduled_task_id",
    "session": "session_id",
    "task": "task_id",
    "work_order": "work_order_id",
    "worker": "worker_id",
}
NATIVE_CONVERSATION_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
CONTROL_COORDINATOR_KEY: web.AppKey["OperationCoordinator"] = web.AppKey(
    "control_coordinator",
    object,
)


class OperationQueueTimeout(TimeoutError):
    """Raised when a control operation cannot acquire its resource lease in time."""


class IdempotencyConflictError(RuntimeError):
    """Raised when one idempotency key is reused for a different intent."""


@dataclass(frozen=True)
class ControlOperationSpec:
    """Operation name and the resources that must not overlap concurrently."""

    name: str
    resources: Tuple[str, ...]


@dataclass(frozen=True)
class OperationRunResult:
    """Result returned to the HTTP middleware after coordination."""

    value: Any
    operation: Dict[str, Any]
    deduplicated: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _stable_result_reference(value: Any) -> Optional[Any]:
    """Return one audit-safe scalar ID, never arbitrary response content."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        normalized = value.strip()
        if RESULT_REFERENCE_VALUE_PATTERN.fullmatch(normalized):
            return normalized
    return None


def _extract_result_reference(response: Any) -> Dict[str, Any]:
    """Extract stable identifiers from a successful aiohttp JSON response.

    The audit deliberately keeps no response bodies, prompts, URLs, or filesystem
    paths. Generic nested ``id`` fields are accepted only for known entity names.
    """

    if not isinstance(response, web.Response) or not 200 <= response.status < 400:
        return {}
    content_type = (response.content_type or "").lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        return {}
    body = response.body
    if not isinstance(body, (bytes, bytearray, memoryview)):
        return {}
    try:
        payload = json.loads(bytes(body).decode(response.charset or "utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    result: Dict[str, Any] = {}

    def visit(item: Dict[str, Any]) -> None:
        for key, value in item.items():
            if key in RESULT_REFERENCE_FIELDS:
                stable = _stable_result_reference(value)
                if stable is not None:
                    result.setdefault(key, stable)

            canonical_key = RESULT_REFERENCE_ENTITIES.get(key)
            if canonical_key and isinstance(value, dict):
                stable = _stable_result_reference(value.get("id"))
                if stable is not None:
                    result.setdefault(canonical_key, stable)

            # Known ID field names remain safe inside ordinary JSON wrappers such
            # as ``result`` or ``data``. Lists are intentionally not traversed:
            # an operation reference identifies one stable result, not a payload.
            if isinstance(value, dict):
                visit(value)

    visit(payload)
    return dict(sorted(result.items()))


def classify_control_operation(method: str, path: str) -> Optional[ControlOperationSpec]:
    """Map a mutating API request to conflict resources.

    Resource choices are intentionally coarse outside chat delivery. Conversation
    operations are keyed per conversation so distinct duplicate windows can remain
    parallel while messages targeting the same chat are always serialized.
    """

    method = method.upper()
    path = path.split("?", 1)[0]
    is_sync_get = bool(re.fullmatch(r"/api/projects/\d+/sync", path))
    if method in {"GET", "HEAD", "OPTIONS"} and not is_sync_get:
        return None
    if not path.startswith("/api/"):
        return None

    canonical_path = path.replace("/api/integrity/", "/api/antigravity/")
    parts = _segments(canonical_path)
    name = f"{method} {canonical_path}"

    if canonical_path.startswith('/api/desktop/ams/'):
        resources = ['antigravity:desktop-primary']
        if parts[-1] in {'commitAndPush', 'generateCommitMsg', 'consolidateMemory'}:
            resources.append('hub:git-control')
        return ControlOperationSpec(name, tuple(resources))

    if canonical_path.startswith("/api/antigravity/scheduled-tasks"):
        return ControlOperationSpec(name, ("antigravity:scheduler",))

    chat_match = re.match(r"^/api/antigravity/chats/([^/]+)", canonical_path)
    if chat_match:
        conversation_id = chat_match.group(1).strip()
        resource_id = (
            conversation_id.lower()
            if NATIVE_CONVERSATION_ID_PATTERN.fullmatch(conversation_id)
            else conversation_id
        )
        resource_prefix = (
            "proxy-conversation"
            if conversation_id.lower().startswith("proxy-")
            else "antigravity:conversation"
        )
        resources = [f"{resource_prefix}:{resource_id}"]
        if canonical_path.endswith("/ide/open"):
            resources.append("hub:web-ide")
        return ControlOperationSpec(
            name,
            tuple(resources),
        )
    if canonical_path == "/api/antigravity/chats":
        return ControlOperationSpec(
            name,
            ("antigravity:desktop-primary", "antigravity:window-registry"),
        )

    if canonical_path.startswith("/api/antigravity/active-model"):
        return ControlOperationSpec(
            name,
            ("antigravity:desktop-primary", "antigravity:model-selection"),
        )
    if canonical_path.startswith("/api/antigravity/custom-models"):
        return ControlOperationSpec(name, ("hub:custom-models",))
    if canonical_path.startswith("/api/antigravity/proxy-chats"):
        return ControlOperationSpec(name, ("hub:proxy-conversations",))

    project_match = re.match(r"^/api/projects/(\d+)", canonical_path)
    if project_match:
        project_id = project_match.group(1)
        resources = [f"hub:project:{project_id}"]
        if canonical_path.endswith("/antigravity-project"):
            resources.extend(
                ["antigravity:desktop-primary", "antigravity:project-registry"]
            )
        elif canonical_path.endswith(("/antigravity-link", "/integrity-link")):
            resources.append("antigravity:project-registry")
        elif canonical_path.endswith(("/preview", "/preview/stop")):
            resources.append("hub:previews")
        elif canonical_path.endswith("/ide/open"):
            resources.append("hub:web-ide")
        elif canonical_path.endswith("/sync"):
            resources.append("hub:github-sync")
        else:
            resources.append("hub:projects")
        return ControlOperationSpec(name, tuple(sorted(set(resources))))
    if canonical_path.startswith("/api/projects"):
        return ControlOperationSpec(name, ("hub:projects",))

    if canonical_path.startswith("/api/chats/") and canonical_path.endswith("/navigate"):
        return ControlOperationSpec(name, ("antigravity:desktop-primary",))
    if canonical_path.startswith("/api/voice/dictation/"):
        return ControlOperationSpec(
            name,
            ("antigravity:dictation-worker", "antigravity:voice"),
        )
    if canonical_path.startswith("/api/voice/"):
        return ControlOperationSpec(
            name,
            ("antigravity:desktop-primary", "antigravity:voice"),
        )
    if canonical_path.startswith("/api/git/"):
        return ControlOperationSpec(name, ("hub:git-control",))
    if canonical_path.startswith("/api/control-center/"):
        return ControlOperationSpec(name, ("hub:engineering-control",))
    if canonical_path.startswith("/api/orchestrator/"):
        return ControlOperationSpec(name, ("hub:orchestrator",))

    issue_match = re.match(r"^/api/issues/(\d+)", canonical_path)
    if issue_match:
        return ControlOperationSpec(
            name,
            (f"hub:issue:{issue_match.group(1)}",),
        )
    if canonical_path.startswith("/api/issues"):
        return ControlOperationSpec(name, ("hub:issues",))

    run_match = re.match(r"^/api/runs/(\d+)", canonical_path)
    if run_match:
        return ControlOperationSpec(name, (f"hub:run:{run_match.group(1)}",))
    subtask_match = re.match(r"^/api/subtasks/(\d+)", canonical_path)
    if subtask_match:
        return ControlOperationSpec(
            name,
            (f"hub:subtask:{subtask_match.group(1)}",),
        )

    fallback = ":".join(parts[1:3]) if len(parts) > 1 else "api"
    return ControlOperationSpec(name, (f"hub:{fallback}",))


class OperationCoordinator:
    """Coordinate mutating operations with resource leases and durable audit."""

    def __init__(
        self,
        *,
        audit_path: Optional[Path] = None,
        history_limit: int = 100,
        wait_timeout_seconds: float = 120.0,
    ) -> None:
        self.audit_path = Path(audit_path) if audit_path else None
        self.history_limit = max(10, int(history_limit))
        self.wait_timeout_seconds = max(1.0, float(wait_timeout_seconds))
        self._condition = asyncio.Condition()
        self._audit_lock = asyncio.Lock()
        self._records: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._waiting: list[str] = []
        self._active: set[str] = set()
        self._completion: Dict[str, asyncio.Future] = {}
        self._idempotency: Dict[str, str] = {}
        self._last_audit_error = ""
        self._load_audit_tail()

    def _load_audit_tail(self) -> None:
        if not self.audit_path:
            return
        audit_paths = [
            self.audit_path.with_name(f"{self.audit_path.name}.{index}")
            for index in range(CONTROL_AUDIT_BACKUP_COUNT, 0, -1)
        ] + [self.audit_path]
        lines: list[str] = []
        for audit_path in audit_paths:
            try:
                if audit_path.is_file():
                    lines.extend(
                        audit_path.read_text(encoding="utf-8").splitlines()
                    )
            except (OSError, UnicodeError) as error:
                self._last_audit_error = redact_sensitive_text(
                    f"{type(error).__name__}: {error}",
                    maximum=CONTROL_ERROR_MAX_CHARS,
                )
                # A damaged generation must not hide valid rotated audit records
                # or prevent the Hub from starting.
                continue
        for line in lines[-self.history_limit :]:
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                # A corrupt old audit line must never prevent the Hub from starting.
                continue
            if not isinstance(item, dict):
                # JSONL recovery accepts only operation objects. Valid JSON scalar
                # or array lines can come from legacy/corrupt files and are ignored.
                continue
            operation_id = str(item.get("operation_id") or "")
            if not operation_id or item.get("state") not in TERMINAL_STATES:
                continue
            item["error"] = redact_sensitive_text(
                item.get("error"),
                maximum=CONTROL_ERROR_MAX_CHARS,
            )
            self._records[operation_id] = item
            idempotency_key = str(item.get("idempotency_key") or "")
            if idempotency_key:
                self._idempotency[idempotency_key] = operation_id

    @staticmethod
    def validate_idempotency_key(value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        value = value.strip()
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
            raise ValueError(
                "Idempotency-Key must contain 1-128 letters, digits, '.', '_', ':' or '-'."
            )
        return value

    async def run(
        self,
        spec: ControlOperationSpec,
        callback: Callable[[], Awaitable[Any]],
        *,
        idempotency_key: Optional[str] = None,
        intent_fingerprint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OperationRunResult:
        """Wait for a compatible lease, run once, and persist the outcome."""

        idempotency_key = self.validate_idempotency_key(idempotency_key)
        intent_sha256 = (
            self._resolve_intent_fingerprint(spec, intent_fingerprint)
            if idempotency_key
            else ""
        )
        duplicate = await self._find_duplicate(idempotency_key, intent_sha256)
        if duplicate is not None:
            return OperationRunResult(None, duplicate, deduplicated=True)

        operation_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        record: Dict[str, Any] = {
            "operation_id": operation_id,
            "name": spec.name,
            "resources": sorted(set(spec.resources)),
            "state": "queued",
            "queued_at": _utc_now(),
            "started_at": None,
            "finished_at": None,
            "wait_ms": None,
            "duration_ms": None,
            "http_status": None,
            "error": "",
            "result_ref": {},
            "metadata": dict(metadata or {}),
            "idempotency_key": idempotency_key or "",
            "intent_sha256": intent_sha256,
            "_queued_monotonic": time.monotonic(),
            "_started_monotonic": None,
        }
        completion = loop.create_future()

        timed_out_record: Optional[Dict[str, Any]] = None
        cancelled_waiting_record: Optional[Dict[str, Any]] = None
        cancelled_waiting_error: Optional[asyncio.CancelledError] = None
        async with self._condition:
            # Recheck after acquiring the condition to close the duplicate race.
            existing_id = self._idempotency.get(idempotency_key or "")
            if existing_id:
                existing_future = self._completion.get(existing_id)
                existing_record = self._records.get(existing_id)
            else:
                existing_future = None
                existing_record = None

            if existing_record is not None:
                self._ensure_matching_intent(existing_record, intent_sha256)
            else:
                self._records[operation_id] = record
                self._completion[operation_id] = completion
                self._waiting.append(operation_id)
                if idempotency_key:
                    self._idempotency[idempotency_key] = operation_id
                deadline = loop.time() + self.wait_timeout_seconds
                while not self._can_start(operation_id):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        timed_out_record = self._finish_locked(
                            operation_id,
                            state="timed_out",
                            error="Timed out waiting for conflicting control operations.",
                        )
                        break
                    try:
                        await asyncio.wait_for(self._condition.wait(), remaining)
                    except asyncio.TimeoutError:
                        timed_out_record = self._finish_locked(
                            operation_id,
                            state="timed_out",
                            error="Timed out waiting for conflicting control operations.",
                        )
                        break
                    except asyncio.CancelledError as error:
                        cancelled_waiting_error = error
                        cancelled_waiting_record = self._finish_locked(
                            operation_id,
                            state="cancelled",
                            error="Operation was cancelled while waiting.",
                        )
                        break
                if (
                    timed_out_record is None
                    and cancelled_waiting_record is None
                ):
                    record["state"] = "running"
                    record["started_at"] = _utc_now()
                    record["_started_monotonic"] = time.monotonic()
                    record["wait_ms"] = round(
                        (record["_started_monotonic"] - record["_queued_monotonic"])
                        * 1000,
                        2,
                    )
                    self._waiting.remove(operation_id)
                    self._active.add(operation_id)

        if existing_record is not None:
            if existing_record.get("state") not in TERMINAL_STATES and existing_future:
                await asyncio.shield(existing_future)
            async with self._condition:
                resolved = dict(self._records.get(existing_id, existing_record))
            return OperationRunResult(None, self._public_record(resolved), True)

        if timed_out_record is not None:
            await self._persist(timed_out_record)
            raise OperationQueueTimeout(timed_out_record["error"])
        if cancelled_waiting_record is not None:
            await asyncio.shield(self._persist(cancelled_waiting_record))
            raise cancelled_waiting_error or asyncio.CancelledError()

        try:
            value = await callback()
            http_status = int(getattr(value, "status", 200) or 200)
            state = "succeeded" if http_status < 400 else "failed"
            error = "" if state == "succeeded" else f"HTTP {http_status}"
            result_ref = (
                _extract_result_reference(value)
                if state == "succeeded"
                else {}
            )
        except asyncio.CancelledError:
            completed = await self._finish(
                operation_id,
                state="cancelled",
                error="Operation was cancelled.",
            )
            await self._persist(completed)
            raise
        except BaseException as error:
            completed = await self._finish(
                operation_id,
                state="failed",
                error=f"{type(error).__name__}: {error}",
            )
            await self._persist(completed)
            raise

        completed = await self._finish(
            operation_id,
            state=state,
            http_status=http_status,
            error=error,
            result_ref=result_ref,
        )
        await self._persist(completed)
        return OperationRunResult(value, self._public_record(completed), False)

    async def _find_duplicate(
        self,
        idempotency_key: Optional[str],
        intent_sha256: str,
    ) -> Optional[Dict[str, Any]]:
        if not idempotency_key:
            return None
        future = None
        async with self._condition:
            operation_id = self._idempotency.get(idempotency_key)
            if not operation_id:
                return None
            record = self._records.get(operation_id)
            if not record:
                return None
            self._ensure_matching_intent(record, intent_sha256)
            if record.get("state") in TERMINAL_STATES:
                return self._public_record(record)
            future = self._completion.get(operation_id)
        if future:
            await asyncio.shield(future)
        async with self._condition:
            record = self._records.get(operation_id, record)
            return self._public_record(record)

    @staticmethod
    def _resolve_intent_fingerprint(
        spec: ControlOperationSpec,
        intent_fingerprint: Optional[str],
    ) -> str:
        if intent_fingerprint is None:
            encoded = json.dumps(
                {
                    "name": spec.name,
                    "resources": sorted(set(spec.resources)),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()

        normalized = intent_fingerprint.strip().lower()
        if not INTENT_FINGERPRINT_PATTERN.fullmatch(normalized):
            raise ValueError("intent_fingerprint must be a SHA-256 hex digest.")
        return normalized

    @staticmethod
    def _ensure_matching_intent(
        record: Dict[str, Any],
        intent_sha256: str,
    ) -> None:
        if str(record.get("intent_sha256") or "") != intent_sha256:
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used for a different request intent."
            )

    def _can_start(self, operation_id: str) -> bool:
        record = self._records[operation_id]
        resources = set(record["resources"])
        for active_id in self._active:
            if resources.intersection(self._records[active_id]["resources"]):
                return False
        for waiting_id in self._waiting:
            if waiting_id == operation_id:
                break
            if resources.intersection(self._records[waiting_id]["resources"]):
                return False
        return True

    async def _finish(
        self,
        operation_id: str,
        *,
        state: str,
        http_status: Optional[int] = None,
        error: str = "",
        result_ref: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        async with self._condition:
            return self._finish_locked(
                operation_id,
                state=state,
                http_status=http_status,
                error=error,
                result_ref=result_ref,
            )

    def _finish_locked(
        self,
        operation_id: str,
        *,
        state: str,
        http_status: Optional[int] = None,
        error: str = "",
        result_ref: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = self._records[operation_id]
        now_monotonic = time.monotonic()
        record["state"] = state
        record["finished_at"] = _utc_now()
        record["http_status"] = http_status
        record["error"] = redact_sensitive_text(
            error,
            maximum=CONTROL_ERROR_MAX_CHARS,
        )
        if result_ref is not None:
            record["result_ref"] = dict(result_ref)
        started = record.get("_started_monotonic")
        if started is not None:
            record["duration_ms"] = round((now_monotonic - started) * 1000, 2)
        if operation_id in self._waiting:
            self._waiting.remove(operation_id)
        self._active.discard(operation_id)
        future = self._completion.get(operation_id)
        if future and not future.done():
            future.set_result(self._public_record(record))
        self._trim_history_locked()
        self._condition.notify_all()
        return dict(record)

    def _trim_history_locked(self) -> None:
        terminal_ids = [
            operation_id
            for operation_id, record in self._records.items()
            if record.get("state") in TERMINAL_STATES
        ]
        excess = len(terminal_ids) - self.history_limit
        for operation_id in terminal_ids[: max(0, excess)]:
            record = self._records.pop(operation_id, None)
            self._completion.pop(operation_id, None)
            if record:
                key = str(record.get("idempotency_key") or "")
                if key and self._idempotency.get(key) == operation_id:
                    self._idempotency.pop(key, None)

    async def _persist(self, record: Dict[str, Any]) -> None:
        if not self.audit_path:
            return
        payload = self._serializable_record(record)
        async with self._audit_lock:
            try:
                await asyncio.to_thread(self._append_audit_line, payload)
            except OSError as error:
                # The API action already ran. Expose audit health without making a
                # safe client retry execute the completed action a second time.
                self._last_audit_error = redact_sensitive_text(
                    f"{type(error).__name__}: {error}",
                    maximum=CONTROL_ERROR_MAX_CHARS,
                )
            else:
                self._last_audit_error = ""

    def _append_audit_line(self, record: Dict[str, Any]) -> None:
        if not self.audit_path:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        self._rotate_audit_if_needed(len(encoded.encode("utf-8")))
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)

    def _rotate_audit_if_needed(self, incoming_bytes: int) -> None:
        if not self.audit_path:
            return
        try:
            current_bytes = self.audit_path.stat().st_size
        except FileNotFoundError:
            return
        if current_bytes + incoming_bytes <= CONTROL_AUDIT_MAX_BYTES:
            return
        oldest = self.audit_path.with_name(
            f"{self.audit_path.name}.{CONTROL_AUDIT_BACKUP_COUNT}"
        )
        oldest.unlink(missing_ok=True)
        for index in range(CONTROL_AUDIT_BACKUP_COUNT - 1, 0, -1):
            source = self.audit_path.with_name(f"{self.audit_path.name}.{index}")
            if source.exists():
                source.replace(
                    self.audit_path.with_name(f"{self.audit_path.name}.{index + 1}")
                )
        self.audit_path.replace(self.audit_path.with_name(f"{self.audit_path.name}.1"))

    @staticmethod
    def _serializable_record(record: Dict[str, Any]) -> Dict[str, Any]:
        serialized = {
            key: value
            for key, value in record.items()
            if not key.startswith("_")
        }
        serialized["error"] = redact_sensitive_text(
            serialized.get("error"),
            maximum=CONTROL_ERROR_MAX_CHARS,
        )
        return serialized

    @classmethod
    def _public_record(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        public = cls._serializable_record(record)
        public.pop("idempotency_key", None)
        public.pop("intent_sha256", None)
        public.setdefault("result_ref", {})
        public["idempotent"] = bool(record.get("idempotency_key"))
        return public

    async def status(self) -> Dict[str, Any]:
        async with self._condition:
            active = [
                self._public_record(self._records[operation_id])
                for operation_id in self._active
            ]
            waiting = []
            for position, operation_id in enumerate(self._waiting, start=1):
                item = self._public_record(self._records[operation_id])
                item["queue_position"] = position
                waiting.append(item)
            recent = [
                self._public_record(record)
                for record in reversed(self._records.values())
                if record.get("state") in TERMINAL_STATES
            ][: self.history_limit]
        return {
            "policy": {
                "mode": "conflict-aware-fifo",
                "wait_timeout_seconds": self.wait_timeout_seconds,
                "parallel_non_conflicting": True,
                "same_conversation_serialized": True,
                "idempotency_supported": True,
                "audit_persistent": bool(self.audit_path),
                "audit_error": self._last_audit_error,
            },
            "counts": {
                "active": len(active),
                "waiting": len(waiting),
                "recent": len(recent),
            },
            "active": active,
            "waiting": waiting,
            "recent": recent,
        }
