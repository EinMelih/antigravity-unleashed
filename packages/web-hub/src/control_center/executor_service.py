"""Durable background executor for approved engineering campaigns."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from typing import Any, Dict, Optional

from aiohttp import web

from src.control_center.agent_adapter import AntiGravityTaskAdapter
from src.control_center.common import ControlCenterError
from src.control_center.github_flow import GitHubFlow
from src.control_center.worktrees import WorktreeManager


MAX_ANTIGRAVITY_WORKERS = 4
MAX_PLANNING_OUTPUT_REPAIRS = 2
CONTROL_EXECUTOR_KEY = web.AppKey(
    "control_center_executor",
    object,
)


class ControlCenterExecutor:
    def __init__(
        self,
        store,
        *,
        adapter: Optional[AntiGravityTaskAdapter] = None,
        flow_factory=GitHubFlow,
        worktree_manager: Optional[WorktreeManager] = None,
        poll_seconds: float = 3.0,
        heartbeat_interval_seconds: Optional[float] = None,
        planning_status_poll_seconds: float = 0.25,
    ) -> None:
        self.store = store
        self.adapter = adapter or AntiGravityTaskAdapter()
        self.flow_factory = flow_factory
        self.worktrees = worktree_manager or WorktreeManager()
        self.poll_seconds = max(0.25, float(poll_seconds))
        self.heartbeat_interval_seconds = (
            max(0.01, float(heartbeat_interval_seconds))
            if heartbeat_interval_seconds is not None
            else None
        )
        self.planning_status_poll_seconds = max(
            0.01,
            float(planning_status_poll_seconds),
        )
        self._loop_task: Optional[asyncio.Task] = None
        self._active: Dict[str, asyncio.Task] = {}
        self._syncing: set[str] = set()
        self._agent_gates: Dict[str, Dict[str, Any]] = {}
        self._stopping = False
        self.last_error = ""

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stopping = False
        stale_gates = await asyncio.to_thread(
            self.store.resolve_all_agent_permission_attention,
        )
        if stale_gates:
            print(
                f"[ControlCenter] Resolved {stale_gates} stale agent gate(s).",
                flush=True,
            )
        recovered_plans = await asyncio.to_thread(
            self.store.recover_interrupted_planning_jobs,
        )
        if recovered_plans:
            print(
                "[ControlCenter] Recovered "
                f"{recovered_plans} interrupted planning job(s).",
                flush=True,
            )
        recovered = await asyncio.to_thread(self.store.recover_expired_leases)
        if recovered:
            print(
                f"[ControlCenter] Recovered {recovered} expired task leases.",
                flush=True,
            )
        self._loop_task = asyncio.create_task(
            self._run_loop(),
            name="antigravity-control-center-executor",
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        active = list(self._active.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        await asyncio.to_thread(
            self.store.resolve_all_agent_permission_attention,
        )
        self._active.clear()
        self._syncing.clear()
        self._agent_gates.clear()

    def status(self) -> Dict[str, Any]:
        return {
            "running": bool(self._loop_task and not self._loop_task.done()),
            "stopping": self._stopping,
            "active_task_ids": sorted(self._active),
            "syncing_task_ids": sorted(self._syncing),
            "waiting_human": [
                self._agent_gates[key]
                for key in sorted(self._agent_gates)
            ],
            "worker_limit": MAX_ANTIGRAVITY_WORKERS,
            "last_error": self.last_error,
        }

    async def _wait_for_adapter(
        self,
        chat_id: str,
        *,
        timeout_seconds: int,
        on_state_change,
    ) -> Dict[str, Any]:
        parameters = inspect.signature(
            self.adapter.wait_until_complete
        ).parameters
        kwargs: Dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if (
            "on_state_change" in parameters
            or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        ):
            kwargs["on_state_change"] = on_state_change
        return await self.adapter.wait_until_complete(chat_id, **kwargs)

    async def _set_agent_gate(
        self,
        *,
        project_id: int,
        entity_type: str,
        entity_id: str,
        state: str,
        gate: Optional[Dict[str, Any]] = None,
    ) -> None:
        key = f"{entity_type}:{entity_id}"
        payload = {
            **(gate or {}),
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        if state == "waiting_human":
            await asyncio.to_thread(
                self.store.set_agent_permission_attention,
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                gate=payload,
            )
            self._agent_gates[key] = payload
            return
        await asyncio.to_thread(
            self.store.set_agent_permission_attention,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            gate=None,
        )
        self._agent_gates.pop(key, None)

    async def _wait_for_agent_with_heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_token: str,
        chat_id: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Keep the durable lease alive while Anti-Gravity performs long work."""

        task = await asyncio.to_thread(self.store.get_task, task_id)
        policy = await asyncio.to_thread(
            self.store.get_repository_policy,
            task["project_id"],
        )
        interval = self.heartbeat_interval_seconds
        if interval is None:
            interval = max(
                1.0,
                min(30.0, float(policy["lease_seconds"]) / 3.0),
            )
        waiter = asyncio.create_task(
            self._wait_for_adapter(
                chat_id,
                timeout_seconds=timeout_seconds,
                on_state_change=lambda state, gate: self._set_agent_gate(
                    project_id=int(task["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    state=state,
                    gate=gate,
                ),
            ),
            name=f"antigravity-wait:{task_id}",
        )
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {waiter},
                    timeout=interval,
                )
                if waiter in done:
                    return await waiter
                await asyncio.to_thread(
                    self.store.heartbeat_task,
                    task_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                )
        finally:
            if not waiter.done():
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter

    async def _wait_for_planning_job(
        self,
        *,
        job_id: str,
        project_id: int,
        chat_id: str,
        timeout_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        """Wait locally while the durable planning job remains active."""
        waiter = asyncio.create_task(
            self._wait_for_adapter(
                chat_id,
                timeout_seconds=timeout_seconds,
                on_state_change=lambda state, gate: self._set_agent_gate(
                    project_id=project_id,
                    entity_type="planning_job",
                    entity_id=job_id,
                    state=state,
                    gate=gate,
                ),
            ),
            name=f"antigravity-planning-wait:{job_id}",
        )
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {waiter},
                    timeout=self.planning_status_poll_seconds,
                )
                if waiter in done:
                    return await waiter
                current = await asyncio.to_thread(
                    self.store.get_planning_job,
                    job_id,
                )
                if str(current["status"]) != "running":
                    return None
        finally:
            if not waiter.done():
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter

    async def _run_loop(self) -> None:
        while not self._stopping:
            try:
                await self.run_once()
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                print(f"[ControlCenter] Executor loop error: {exc}", flush=True)
            await asyncio.sleep(self.poll_seconds)

    async def run_once(self) -> None:
        policy = await asyncio.to_thread(self.store.get_policy)
        if policy["paused"] or policy["mode"] == "observer":
            return
        await asyncio.to_thread(self.store.recover_expired_leases)
        if policy["mode"] in {"campaign", "autopilot"}:
            await self._activate_campaign_waves()
        await self._sync_waiting_tasks()
        self._active = {
            task_id: task
            for task_id, task in self._active.items()
            if not task.done()
        }
        while len(self._active) < MAX_ANTIGRAVITY_WORKERS:
            planning_job = await asyncio.to_thread(
                self.store.claim_planning_job,
            )
            if not planning_job:
                break
            job_id = str(planning_job["id"])
            runner = asyncio.create_task(
                self._execute_planning_job(planning_job),
                name=f"planning-job:{job_id}",
            )
            active_key = f"plan:{job_id}"
            self._active[active_key] = runner
            runner.add_done_callback(
                lambda _future, selected=active_key: self._active.pop(selected, None)
            )
        while len(self._active) < MAX_ANTIGRAVITY_WORKERS:
            worker_id = f"control-executor-{len(self._active) + 1}"
            task = await asyncio.to_thread(
                self.store.lease_next_task,
                worker_id,
            )
            if not task:
                break
            task_id = str(task["id"])
            runner = asyncio.create_task(
                self._execute_task(task, worker_id),
                name=f"control-task:{task_id}",
            )
            self._active[task_id] = runner
            runner.add_done_callback(
                lambda _future, selected=task_id: self._active.pop(selected, None)
            )

    async def _execute_planning_job(self, job: Dict[str, Any]) -> None:
        job_id = str(job["id"])
        project: Optional[Dict[str, Any]] = None
        try:
            project = await asyncio.to_thread(
                self.store._project,
                job["project_id"],
            )
            planning_project = {
                **project,
                "path": str(
                    project.get("integrity_workspace_path") or project["path"]
                ).strip(),
            }
            repository_before = await asyncio.to_thread(
                self.worktrees.repository_snapshot,
                planning_project,
            )
            await asyncio.to_thread(
                self.store.assert_planning_dispatch_allowed,
                job_id,
            )
            dispatched = await self.adapter.dispatch_planning(job, project)
            chat_id = str(dispatched.get("chat_id") or "")
            if not chat_id:
                raise ControlCenterError(
                    "Anti-Gravity Planner lieferte keine Conversation-ID.",
                    code="planning_chat_id_missing",
                    status=409,
                )
            project_context = dispatched.get("project_context") or {}
            project_uuid = str(project_context.get("project_uuid") or "").strip()
            workspace_path = str(
                project_context.get("workspace_path") or ""
            ).strip()
            if project_uuid and workspace_path:
                await asyncio.to_thread(
                    self.store.db.update_project_integrity_link,
                    int(project["id"]),
                    workspace_path,
                    project_uuid,
                    str(project_context.get("project_name") or "").strip(),
                )
            await asyncio.to_thread(
                self.store.update_planning_job_chat,
                job_id,
                chat_id,
            )
            wait_result = await self._wait_for_planning_job(
                job_id=job_id,
                project_id=int(project["id"]),
                chat_id=chat_id,
                timeout_seconds=3600,
            )
            if wait_result is None:
                return
            plan: Optional[Dict[str, Any]] = None
            for repair_round in range(MAX_PLANNING_OUTPUT_REPAIRS + 1):
                repository_after = await asyncio.to_thread(
                    self.worktrees.repository_snapshot,
                    planning_project,
                )
                if (
                    repository_after["fingerprint"]
                    != repository_before["fingerprint"]
                ):
                    raise ControlCenterError(
                        "Read-only planning modified the repository. "
                        "The planning job was stopped for human review.",
                        code="planning_repository_mutated",
                        status=409,
                    )
                try:
                    plan = await asyncio.to_thread(
                        self.adapter.read_planning_result,
                        chat_id,
                    )
                    break
                except ControlCenterError as parse_error:
                    repair_output = getattr(
                        self.adapter,
                        "repair_planning_output",
                        None,
                    )
                    if (
                        parse_error.code != "invalid_planning_output"
                        or repair_round >= MAX_PLANNING_OUTPUT_REPAIRS
                        or not callable(repair_output)
                    ):
                        raise
                    await repair_output(chat_id, str(parse_error))
                    wait_result = await self._wait_for_planning_job(
                        job_id=job_id,
                        project_id=int(project["id"]),
                        chat_id=chat_id,
                        timeout_seconds=3600,
                    )
                    if wait_result is None:
                        return
            if plan is None:
                raise ControlCenterError(
                    "Planner lieferte nach der Formatkorrektur keinen Plan.",
                    code="invalid_planning_output",
                    status=409,
                )
            completed_job = await asyncio.to_thread(
                self.store.complete_planning_job,
                job_id,
                plan,
            )
            if (
                completed_job.get("status") == "waiting_human"
                and completed_job.get("waiting_reason") == "question"
            ):
                return
            try:
                await self.adapter.archive_chat(chat_id)
            except Exception as exc:
                print(
                    f"[ControlCenter] Planner chat {chat_id} archive failed: {exc}",
                    flush=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await asyncio.to_thread(
                    self.store.fail_planning_job,
                    job_id,
                    str(exc),
                )
            except ControlCenterError as transition_error:
                if transition_error.code != "planning_job_not_running":
                    raise
        finally:
            if project is not None:
                with contextlib.suppress(Exception):
                    await self._set_agent_gate(
                        project_id=int(project["id"]),
                        entity_type="planning_job",
                        entity_id=job_id,
                        state="running",
                    )

    async def _activate_campaign_waves(self) -> None:
        with self.store.db._get_connection() as conn:
            rows = conn.execute(
                """SELECT id FROM control_campaigns
                   WHERE status IN ('approved', 'active')
                   ORDER BY created_at ASC"""
            ).fetchall()
        for row in rows:
            try:
                await asyncio.to_thread(
                    self.store.activate_ready_wave,
                    str(row["id"]),
                    actor="orchestrator",
                )
            except ControlCenterError as exc:
                if exc.code not in {
                    "wave_activation_not_allowed",
                    "campaign_not_approved",
                }:
                    raise

    async def _execute_task(self, task: Dict[str, Any], worker_id: str) -> None:
        task_id = str(task["id"])
        lease_token = str(task["lease_token"])
        flow = self.flow_factory(self.store)
        try:
            context = flow._context(task_id)
            if (
                context.get("wake_reason") == "protected_path_approved"
                and context.get("worktree_path")
                and context.get("issue_number")
                and context.get("current_sha")
            ):
                await asyncio.to_thread(
                    self.store.transition_task,
                    task_id,
                    to_state="running",
                    actor=worker_id,
                    lease_token=lease_token,
                    reason="Exact-SHA protected-path approval received.",
                    fields={"wake_reason": "publishing_approved_revision"},
                )
                await flow.publish_draft_pull_request(
                    task_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                )
                return
            # A resumed task is a repair only when a real prior chat exists.
            # Infrastructure failures before first delivery still preserve the
            # materialized worktree/issue, but the new chat must receive the
            # original Work Order without a misleading repair-error preface.
            is_repair = bool(context.get("antigravity_chat_id"))
            if not context.get("worktree_path") or not context.get("issue_number"):
                await flow.materialize_task(
                    task_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                )
            else:
                await asyncio.to_thread(
                    self.store.transition_task,
                    task_id,
                    to_state="running",
                    actor=worker_id,
                    lease_token=lease_token,
                    reason="Bounded repair pass started." if is_repair else "Task started.",
                    fields={"wake_reason": "agent_execution"},
                )
            context = flow._context(task_id)
            dispatched = await self.adapter.dispatch(context, repair=is_repair)
            chat_id = str(dispatched.get("chat_id") or "")
            if not chat_id:
                raise ControlCenterError(
                    "Anti-Gravity lieferte keine Conversation-ID.",
                    code="antigravity_chat_id_missing",
                    status=409,
                )
            await asyncio.to_thread(
                self.store.transition_task,
                task_id,
                to_state="running",
                actor=worker_id,
                lease_token=lease_token,
                reason="Anti-Gravity project chat accepted the Work Order.",
                fields={
                    "antigravity_chat_id": chat_id,
                    "last_error": "",
                    "wake_reason": "agent_running",
                },
            )
            result = await self._wait_for_agent_with_heartbeat(
                task_id=task_id,
                worker_id=worker_id,
                lease_token=lease_token,
                chat_id=chat_id,
                timeout_seconds=int(context.get("budget_seconds") or 3600),
            )
            await asyncio.to_thread(
                self.store.record_task_progress,
                task_id,
                worker_id=worker_id,
                lease_token=lease_token,
                progress=self.adapter.progress_payload(result),
            )
            await flow.publish_draft_pull_request(
                task_id,
                worker_id=worker_id,
                lease_token=lease_token,
            )
        except asyncio.CancelledError:
            raise
        except ControlCenterError as exc:
            await self._handle_execution_error(task_id, exc, worker_id)
        except Exception as exc:
            await self._handle_execution_error(
                task_id,
                ControlCenterError(
                    f"Executor-Fehler: {exc}",
                    code="executor_failure",
                    status=500,
                ),
                worker_id,
            )
        finally:
            with contextlib.suppress(Exception):
                await self._set_agent_gate(
                    project_id=int(task["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    state="running",
                )

    async def _handle_execution_error(
        self,
        task_id: str,
        error: ControlCenterError,
        worker_id: str,
    ) -> None:
        task = await asyncio.to_thread(self.store.get_task, task_id)
        if task["status"] in {"paused", "cancelled", "completed", "failed"}:
            return
        policy = await asyncio.to_thread(
            self.store.get_repository_policy,
            task["project_id"],
        )
        retryable = error.code not in {
            "protected_path_approval_required",
            "create_issue_denied",
            "push_branch_denied",
            "create_draft_pr_denied",
            "github_repository_not_linked",
            "github_remote_mismatch",
        }
        if retryable and int(task["attempt"]) <= int(policy["max_retry_attempts"]):
            await asyncio.to_thread(
                self.store.transition_task,
                task_id,
                to_state="repair",
                actor="orchestrator",
                reason=str(error),
                fields={
                    "last_error": str(error)[:5000],
                    "wake_reason": f"retry:{error.code}",
                },
            )
            return
        lease_token = str(task.get("lease_token") or "")
        if lease_token:
            await asyncio.to_thread(
                self.store.transition_task,
                task_id,
                to_state="failed",
                actor=worker_id,
                lease_token=lease_token,
                reason=str(error),
                fields={
                    "last_error": str(error)[:5000],
                    "wake_reason": f"failed:{error.code}",
                },
            )
        else:
            await asyncio.to_thread(
                self.store.transition_task,
                task_id,
                to_state="paused",
                actor="orchestrator",
                reason=str(error),
                fields={
                    "last_error": str(error)[:5000],
                    "wake_reason": "human_attention",
                },
            )

    async def _sync_waiting_tasks(self) -> None:
        tasks = await asyncio.to_thread(self.store.list_tasks)
        for task in tasks:
            task_id = str(task["id"])
            if (
                task["status"]
                not in {"waiting_ci", "waiting_review", "waiting_human"}
                or not task.get("pr_number")
                or task_id in self._syncing
            ):
                continue
            self._syncing.add(task_id)
            try:
                flow = self.flow_factory(self.store)
                result = await flow.sync_pull_request(task_id)
                pack = result["evidence_pack"]
                if pack["status"] == "blocked":
                    current = await asyncio.to_thread(self.store.get_task, task_id)
                    policy = await asyncio.to_thread(
                        self.store.get_repository_policy,
                        current["project_id"],
                    )
                    if (
                        current["status"] in {"waiting_ci", "waiting_review"}
                        and policy["capability"].get("respond_to_review", False)
                        and int(current["attempt"]) <= int(policy["max_retry_attempts"])
                    ):
                        await asyncio.to_thread(
                            self.store.transition_task,
                            task_id,
                            to_state="repair",
                            actor="orchestrator",
                            reason="Blocking CI/review finding requires a bounded repair.",
                            fields={"wake_reason": "review_repair"},
                        )
            except ControlCenterError as exc:
                # Polling failures do not destroy state. The next loop retries,
                # while deterministic CI/review failures are represented by the
                # task state and findings inside GitHubFlow.
                self.last_error = f"{task_id}: {exc}"
            except Exception as exc:
                # Network errors, rate limits, and GitHub 5xx responses are not
                # evidence that a pull request disappeared. Preserve local
                # state and let the next polling cycle retry this task.
                self.last_error = f"{task_id}: {exc}"
            finally:
                self._syncing.discard(task_id)
