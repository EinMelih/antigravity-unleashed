"""Anti-Gravity UI adapter for isolated, approved Work Orders."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.control_center.common import ControlCenterError
from src.integrity_sync import (
    TERMINAL_TOOL_STATUSES,
    get_integrity_chat_history,
    scan_antigravity_conversation_catalog,
)
from src.parallel_cdp import ParallelCDPManager


class AntiGravityTaskAdapter:
    def __init__(self, manager_factory=ParallelCDPManager) -> None:
        self.manager_factory = manager_factory
        self._run_baselines: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _history_max_idx(history: Dict[str, Any]) -> int:
        values = [int(history.get("max_idx") or 0)]
        values.extend(
            int(item.get("idx") or 0)
            for item in history.get("history", [])
            if isinstance(item, dict)
        )
        return max(values, default=0)

    @staticmethod
    def _catalog_entry(
        catalog: list[Dict[str, Any]],
        chat_id: str,
    ) -> Dict[str, Any] | None:
        return next(
            (
                item
                for item in catalog
                if str(item.get("convo_id") or "") == chat_id
            ),
            None,
        )

    @staticmethod
    def _matching_user_entry(
        history: Dict[str, Any],
        prompt: str,
        *,
        after_idx: int,
    ) -> Dict[str, Any] | None:
        expected = str(prompt or "").strip()
        return next(
            (
                item
                for item in history.get("history", [])
                if isinstance(item, dict)
                and item.get("role") == "user"
                and int(item.get("idx") or 0) > after_idx
                and str(item.get("content") or "").strip() == expected
            ),
            None,
        )

    @staticmethod
    def _active_user_gate(
        history: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        user_idx = int((baseline or {}).get("user_idx") or -1)
        gates = sorted(
            (
                item
                for item in history.get("history", [])
                if isinstance(item, dict)
                and int(item.get("idx") or 0) > user_idx
                and item.get("type") == "tool_call"
                and (
                    item.get("requires_user_input")
                    or int(item.get("status") or 0) == 9
                )
            ),
            key=lambda item: int(item.get("idx") or 0),
        )
        if not gates:
            return None
        latest = gates[-1]
        enriched = latest.get("enriched") or {}
        return {
            "idx": int(latest.get("idx") or 0),
            "tool_name": str(latest.get("tool_name") or "Aktion"),
            "command": str(
                enriched.get("command")
                or latest.get("args")
                or latest.get("tool_name")
                or "Freigabe erforderlich"
            ),
        }

    @staticmethod
    async def _emit_state_change(
        callback: Optional[Callable[[str, Dict[str, Any]], Any]],
        state: str,
        gate: Optional[Dict[str, Any]] = None,
    ) -> None:
        if callback is None:
            return
        result = callback(state, gate or {})
        if inspect.isawaitable(result):
            await result

    async def _wait_for_persisted_user_message(
        self,
        chat_id: str,
        prompt: str,
        *,
        after_idx: int,
        attempts: int = 80,
    ) -> Dict[str, Any]:
        last_error = ""
        for _ in range(attempts):
            try:
                history = await asyncio.to_thread(
                    get_integrity_chat_history,
                    chat_id,
                )
                entry = self._matching_user_entry(
                    history,
                    prompt,
                    after_idx=after_idx,
                )
                if entry is not None:
                    return entry
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(0.25)
        detail = f" Last history error: {last_error}" if last_error else ""
        raise ControlCenterError(
            "Anti-Gravity hat den neuen Work-Order-Prompt nicht im Zielchat "
            f"persistiert.{detail}",
            code="antigravity_delivery_unverified",
            status=503,
        )

    async def _has_new_assistant_completion(
        self,
        chat_id: str,
        baseline: Dict[str, Any],
    ) -> bool:
        try:
            history = await asyncio.to_thread(
                get_integrity_chat_history,
                chat_id,
            )
        except Exception:
            return False
        return self._history_has_new_assistant_completion(history, baseline)

    @staticmethod
    def _history_has_new_assistant_completion(
        history: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> bool:
        user_idx = int(baseline.get("user_idx") or 0)
        relevant = [
            item
            for item in history.get("history", [])
            if isinstance(item, dict)
            and int(item.get("idx") or 0) > user_idx
        ]
        tools = [
            item for item in relevant if item.get("type") == "tool_call"
        ]
        if any(
            not AntiGravityTaskAdapter._tool_call_is_terminal(item)
            for item in tools
        ):
            return False
        last_tool_idx = max(
            (int(item.get("idx") or 0) for item in tools),
            default=user_idx,
        )
        return any(
            item.get("role") == "assistant"
            and int(item.get("idx") or 0) > last_tool_idx
            and AntiGravityTaskAdapter._assistant_has_final_content(item)
            for item in relevant
        )

    @staticmethod
    def _tool_call_is_terminal(item: Dict[str, Any]) -> bool:
        try:
            status = int(item.get("status"))
        except (TypeError, ValueError):
            return (
                item.get("is_terminal") is True
                or item.get("complete") is True
            )
        return status in TERMINAL_TOOL_STATUSES

    @staticmethod
    def _assistant_has_final_content(item: Dict[str, Any]) -> bool:
        content = item.get("content")
        if isinstance(content, str):
            return bool(content.strip())
        return bool(content)

    @staticmethod
    def _history_has_no_active_tools(
        history: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
    ) -> bool:
        user_idx = int((baseline or {}).get("user_idx") or -1)
        return not any(
            isinstance(item, dict)
            and int(item.get("idx") or 0) > user_idx
            and item.get("type") == "tool_call"
            and not AntiGravityTaskAdapter._tool_call_is_terminal(item)
            for item in history.get("history", [])
        )

    async def _remember_initial_delivery(
        self,
        chat_id: str,
        prompt: str,
        *,
        expected_workspace_path: str = "",
        require_project_uuid: bool = False,
    ) -> Dict[str, Any]:
        entry = await self._wait_for_persisted_user_message(
            chat_id,
            prompt,
            after_idx=-1,
        )
        expected_workspace = self._normalize_workspace_path(
            expected_workspace_path
        )
        metadata: Dict[str, Any] = {}
        last_error = ""
        for _ in range(40):
            try:
                catalog = await asyncio.to_thread(
                    scan_antigravity_conversation_catalog
                )
                metadata = self._catalog_entry(catalog, chat_id) or {}
            except Exception as exc:
                last_error = str(exc)
                metadata = {}

            project_uuid = str(metadata.get("project_uuid") or "").strip()
            if not expected_workspace and (project_uuid or not require_project_uuid):
                break

            actual_workspace = self._normalize_workspace_path(
                metadata.get("workspace_path")
            )
            if (
                actual_workspace == expected_workspace
                and (project_uuid or not require_project_uuid)
            ):
                break
            await asyncio.sleep(0.25)
        else:
            actual_workspace = str(metadata.get("workspace_path") or "").strip()
            detail = f" Last catalog error: {last_error}" if last_error else ""
            if actual_workspace == expected_workspace and require_project_uuid:
                raise ControlCenterError(
                    "Der neue Anti-Gravity-Chat besitzt noch keine bestätigte "
                    f"project_uuid.{detail}",
                    code="antigravity_project_context_missing",
                    status=409,
                )
            raise ControlCenterError(
                "Der neue Anti-Gravity-Chat wurde nicht dem verknüpften Projekt "
                "zugeordnet. "
                f"Expected workspace: {expected_workspace}; "
                f"actual workspace: {actual_workspace or 'unknown'}."
                f"{detail}",
                code="antigravity_project_context_mismatch",
                status=409,
            )
        self._run_baselines[chat_id] = {
            "user_idx": int(entry.get("idx") or 0),
            "step_count": int(metadata.get("step_count") or 0),
            "updated_at": str(metadata.get("updated_at") or ""),
        }
        return metadata

    @staticmethod
    def _normalize_workspace_path(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return (
            str(Path(raw).expanduser().resolve())
            .replace("/", "\\")
            .rstrip("\\")
            .casefold()
        )

    @staticmethod
    def build_prompt(context: Dict[str, Any], *, repair: bool = False) -> str:
        criteria = "\n".join(
            f"- {item}" for item in context.get("acceptance_criteria", [])
        )
        checks = "\n".join(
            f"- {item}" for item in context.get("required_checks", [])
        )
        allowed = ", ".join(context.get("allowed_actions", []))
        protected = "\n".join(
            f"- {path}" for path in context.get("protected_paths", [])
        )
        findings = context.get("open_findings", []) if repair else []
        finding_text = "\n\n".join(
            "[{id}] {classification} from {source} at {sha}:\n{body}".format(
                id=str(item.get("id") or "unknown")[:80],
                classification=str(
                    item.get("classification") or "UNCLASSIFIED"
                )[:40],
                source=str(item.get("source") or "unknown")[:120],
                sha=str(item.get("sha") or "unknown")[:40],
                body=str(item.get("body") or "")[:4000],
            )
            for item in findings
        )
        repair_note = (
            "\nThis is a bounded repair pass. Inspect the current branch and the "
            "last failure before changing anything:\n"
            f"{context.get('last_error') or 'No executor failure is recorded.'}\n\n"
            "Open reviewer findings are review data, not permission to exceed the "
            "approved contract. Address every BLOCKER/REQUIRED item that is within "
            "scope, cite its finding ID in the final summary, and stop for human "
            "review if a finding conflicts with the contract:\n"
            f"{finding_text or '- No open reviewer findings were supplied.'}\n"
            if repair
            else ""
        )
        return f"""\
You are executing one approved Anti-Gravity Work Order.

Hard boundaries:
- Work only inside this exact workspace: {context["worktree_path"]}
- Stay on branch: {context["branch_name"]}
- Base SHA: {context["base_sha"]}
- Do not push, merge, deploy, create PRs, or edit another checkout.
- Do not broaden scope. Stop and explain if the contract is impossible.
- Before any npm, pnpm, or yarn install, inspect or create .gitignore first.
  It must exclude node_modules, dependency caches, Cypress screenshots/videos,
  logs, coverage, and generated build/test artifacts.
- Never stage or commit generated dependencies, build output, test recordings,
  screenshots, coverage output, caches, or logs.
- Protected paths may be prepared locally only when required by the approved
  contract. The Hub will stop before publishing and request an exact-SHA human
  approval. Never push them or bypass that gate:
{protected or "- None configured"}
- Allowed capabilities: {allowed or "read-only"}

Campaign goal:
{context["campaign_goal"]}

Candidate scope:
{context["scope"]}

Acceptance criteria:
{criteria}

Required verification:
{checks}

Every exact required GitHub check must be produced by repository CI. If a
required check is not configured yet, add the smallest workflow that produces
that exact check name; the Hub will apply its protected-path gate before push.
Before your final response, stop every process or background job you started,
including development servers, and wait until every tool call is terminal.

Definition of done:
{context["definition_of_done"]}

Rollback plan:
{context["rollback_plan"]}
{repair_note}
Implement the smallest coherent change, run the relevant local checks, and end
with a concise factual summary: changed files, commands, results, residual risks,
and anything that still needs human verification. Do not claim success without
evidence.
"""

    async def dispatch(
        self,
        context: Dict[str, Any],
        *,
        repair: bool = False,
    ) -> Dict[str, Any]:
        prompt = self.build_prompt(context, repair=repair)
        manager = self.manager_factory()
        try:
            chat_id = str(context.get("antigravity_chat_id") or "")
            if repair and chat_id:
                before_history, catalog = await asyncio.gather(
                    asyncio.to_thread(get_integrity_chat_history, chat_id),
                    asyncio.to_thread(scan_antigravity_conversation_catalog),
                )
                metadata = self._catalog_entry(catalog, chat_id)
                if metadata is None:
                    raise ControlCenterError(
                        "Der Repair-Zielchat wurde im Anti-Gravity-Catalog nicht gefunden.",
                        code="antigravity_chat_missing",
                        status=409,
                    )
                project_uuid = str(metadata.get("project_uuid") or "").strip()
                if not project_uuid:
                    raise ControlCenterError(
                        "Der Repair-Zielchat besitzt keine bestätigte project_uuid.",
                        code="antigravity_project_context_missing",
                        status=409,
                    )
                before_max_idx = self._history_max_idx(before_history)
                result = await manager.send_message_to_chat(
                    chat_id,
                    prompt,
                    section=project_uuid,
                    minimize=True,
                )
                persisted = await self._wait_for_persisted_user_message(
                    chat_id,
                    prompt,
                    after_idx=before_max_idx,
                )
                self._run_baselines[chat_id] = {
                    "user_idx": int(persisted.get("idx") or 0),
                    "step_count": int(metadata.get("step_count") or 0),
                    "updated_at": str(metadata.get("updated_at") or ""),
                }
                result["chat_id"] = chat_id
                result["reused_chat"] = True
                result["delivery_verified"] = True
                result["verified_user_idx"] = int(persisted.get("idx") or 0)
                return result
            worktree_path = str(context.get("worktree_path") or "").strip()
            if not worktree_path:
                raise ControlCenterError(
                    "Der Work Order besitzt keinen materialisierten Worktree.",
                    code="antigravity_project_context_missing",
                    status=409,
                )
            result = await manager.create_new_project_chat_window(
                worktree_path,
                prompt,
                minimize=True,
                project_name="",
            )
            result["reused_chat"] = False
            chat_id = str(result.get("chat_id") or "")
            if chat_id:
                await self._remember_initial_delivery(
                    chat_id,
                    prompt,
                    expected_workspace_path=worktree_path,
                )
            return result
        finally:
            await manager.close_all()

    @staticmethod
    def build_planning_prompt(job: Dict[str, Any], project: Dict[str, Any]) -> str:
        if str(job.get("job_type") or "") == "plan_amendment":
            return AntiGravityTaskAdapter.build_amendment_prompt(job, project)
        constraints = "\n".join(f"- {item}" for item in job.get("constraints", []))
        ledger = "\n\n".join(
            "[{id}] {branch}\nQuestion: {question}\nHuman answer: {answer}\n"
            "Status: {status}".format(
                id=str(item.get("id") or "unknown"),
                branch=str(item.get("branch") or "general"),
                question=str(item.get("question") or ""),
                answer=str(item.get("answer") or ""),
                status=str(item.get("status") or ""),
            )
            for item in job.get("session_questions", [])
        )
        return f"""\
You are the read-only planning role for the Anti-Gravity Engineering Control Plane.

Repository: {project["path"]}
Planning depth: {job["planning_depth"]}
Maximum PR candidates: {job["max_candidates"]}
Activation policy: {job["activation_policy"]}

User wish:
{job["wish"]}

Additional constraints:
{constraints or "- None supplied."}

Existing Socratic ledger from an earlier planner attempt:
{ledger or "- No prior session questions."}

Hard rules:
- Inspect the repository and its tests, but do not modify any file.
- Do not create or edit files anywhere, including Anti-Gravity scratch or brain folders.
- Do not run shell or terminal commands and do not request tool execution approval.
- Validate the response mentally. If a read is unavailable, record the limitation as an assumption.
- Do not create branches, commits, issues, pull requests, or deployments.
- Prefer the smallest coherent PR slices. Never invent work only to reach the limit.
- Each candidate must be independently reviewable and verifiable.
- Express dependencies by candidate id and explicit resource conflicts.
- Include rollback, failure modes, compatibility, documentation, and exact check names.
- A final plan must assess architecture, data, security, and operations exactly
  once in branch_assessments. Use grounded only with real repository evidence.
  At least one branch must be grounded at an existing repository-relative file
  in the pinned checkout, and repository_map must list every grounded path.
  Supply evidence.symbol only when that exact symbol exists in the file.
  Resolved requires an explicit answer. Assumption-accepted requires rationale
  and owner. Discovery-assigned additionally requires evidence.next_step.
  If a branch truly does not apply, use deferred with a concrete rationale,
  owner, and evidence.not_applicable=true. Never invent code facts or an N/A.
- Compare at least two serious implementation alternatives with mechanisms and
  honest trade-offs. Include an independent review strategy.
- Every required GitHub check must already exist or be explicitly provisioned
  by the same or an earlier candidate. Never declare CI a non-goal while
  requiring a CI check.
- All seven candidate score fields use a numeric 0-to-10 scale, never percentages.
- Every text and list field shown in each candidate contract must be non-empty.
  Use a specific, reasoned N/A value when migration, compatibility, or docs do
  not apply; never omit a contract field and never fabricate a check name.
- Return exactly one JSON object, no markdown fence and no prose outside JSON.
- If an existing Socratic ledger is present, incorporate every answer.
- List every answered session question ID in resolved_question_ids.
- If one unresolved, high-impact ambiguity changes scope, architecture, safety,
  or acceptance criteria, ask exactly one question. Never repeat a prior question.
- Otherwise return the final plan. Do not invent a question when the repository
  and supplied requirements already support a safe plan.

Allowed result envelopes:

Question turn:
{{
  "type": "question",
  "question": {{
    "branch": "scope|success|architecture|data|security|operations|other",
    "question": "one decision-changing question",
    "rationale": "why the answer changes the plan"
  }}
}}

Final turn:
{{
  "type": "plan",
  "resolved_question_ids": [],
  "plan": {{ "...": "complete plan using the shape below" }}
}}

Complete inner plan shape:
{{
  "title": "campaign title",
  "goal": "verifiable target state",
  "non_goals": "explicit exclusions",
  "risk_level": "low|medium|high|critical",
  "pivotal_fork": "key architecture decision",
  "pivotal_fork_na_reason": "reasoned explicit N/A only when no fork exists",
  "success_metrics": ["metric"],
  "constraints": ["constraint"],
  "assumptions": ["assumption"],
  "acceptance_matrix": ["scenario -> expected proof"],
  "alternatives": [
    {{
      "title": "serious option",
      "mechanism": "how the option works",
      "tradeoffs": "effort, risk, migration, reversibility, and maintenance"
    }}
  ],
  "review_strategy": "independent review scope and exact evidence",
  "rollout_plan": "bounded rollout",
  "rollback_plan": "exact rollback",
  "repository_map": "Markdown repository map",
  "design_document": "Markdown design with alternatives and failure modes",
  "adr": "Markdown ADR when architecture-significant, otherwise empty",
  "branch_assessments": [
    {{
      "branch": "architecture|data|security|operations",
      "question": "the branch decision or applicability assessment",
      "rationale": "why this terminal disposition is justified",
      "status": "resolved|grounded|assumption-accepted|discovery-assigned|deferred",
      "owner": "responsible role",
      "answer": "explicit decision required when status is resolved",
      "evidence": {{"path": "real/path", "symbol": "real symbol"}}
    }}
  ],
  "candidates": [
    {{
      "id": "slice-01",
      "title": "small PR title",
      "scope": "bounded implementation scope",
      "purpose": "independent outcome of this slice",
      "non_goals": "slice exclusions",
      "risk_level": "low|medium|high|critical",
      "priority": 10,
      "components": ["path or component"],
      "expected_diff_type": "code|tests|docs|schema|workflow|mixed",
      "acceptance_criteria": ["criterion"],
      "required_checks": ["exact GitHub check name"],
      "manual_tests": ["human scenario"],
      "definition_of_done": "exact completion contract",
      "reversibility": "revert strategy",
      "migration_plan": "migration or explicit reasoned N/A",
      "compatibility_plan": "compatibility or explicit reasoned N/A",
      "documentation_changes": ["doc impact or explicit reasoned N/A"],
      "estimated_size": "small|medium|large",
      "business_value": 0,
      "unblock_score": 0,
      "learning_value": 0,
      "urgency_score": 0,
      "effort_score": 1,
      "change_risk_score": 1,
      "reversibility_score": 1,
      "depends_on": [],
      "conflicts_with": [
        {{"id": "slice-02", "reason": "shared resource", "resources": ["path"]}}
      ]
    }}
  ]
}}
"""

    @staticmethod
    def build_amendment_prompt(
        job: Dict[str, Any],
        project: Dict[str, Any],
    ) -> str:
        amendment = job.get("amendment") or {}
        ledger = "\n\n".join(
            "[{id}] {branch}\nQuestion: {question}\nHuman answer: {answer}\n"
            "Status: {status}".format(
                id=str(item.get("id") or "unknown"),
                branch=str(item.get("branch") or "general"),
                question=str(item.get("question") or ""),
                answer=str(item.get("answer") or ""),
                status=str(item.get("status") or ""),
            )
            for item in job.get("session_questions", [])
        )
        before_plan = json.dumps(
            amendment.get("before_plan") or {},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        focus = json.dumps(
            amendment.get("focus") or {},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        return f"""\
You are the read-only Amendment planning role for the Anti-Gravity Engineering
Control Plane. Continue in this same project chat for every question round.

Repository: {project["path"]}
Campaign: {amendment.get("campaign_id") or job.get("campaign_id")}
Source version: {amendment.get("from_version")}
Source base SHA: {amendment.get("from_base_sha")}
Planning HEAD: {amendment.get("planning_base_sha")}
Plan signature v{amendment.get("from_signature_version")}: {amendment.get("from_plan_signature")}
Before-plan SHA-256: {amendment.get("before_plan_sha256")}
Maximum candidates: {job.get("max_candidates")}

Requested change:
{job.get("wish")}

Focus:
{focus}

Amendment question ledger:
{ledger or "- No prior amendment questions."}

Exact canonical source plan:
{before_plan}

Hard rules:
- Inspect the repository read-only. Never modify files, run commands, create
  branches, issues, pull requests, tasks, evidence, approvals, or deployments.
- Preserve every immutable candidate exactly. A candidate is mutable only when
  the server identifies it as future work: status ready and no WorkOrder or task.
- Preserve dependencies, conflicts and Knowledge links involving immutable
  candidates exactly.
- Return a full target plan with every canonical top-level section from the
  source. Omitted mutable candidates are retired as obsolete by the server;
  nothing is deleted.
- Existing artifacts are immutable. Add a new artifact with supersedes_id when
  a design or decision changes. Never overwrite existing artifact content.
- Keep Knowledge changes only in target_plan until human approval.
- Ground all new facts in the repository or supplied request. Never invent facts.
- If one decision-changing ambiguity remains, ask exactly one new question.
- Incorporate every human answer and list every session question ID exactly once.
- Return exactly one JSON object with no markdown fence and no prose.

Allowed envelopes:

Question turn:
{{
  "type": "question",
  "question": {{
    "branch": "scope|success|architecture|data|security|operations|other",
    "question": "one decision-changing question",
    "rationale": "why the answer changes the exact target"
  }}
}}

Final turn:
{{
  "type": "amendment_plan",
  "resolved_question_ids": [],
  "target_plan": {{
    "signature_version": 2,
    "campaign": {{"...": "full canonical campaign"}},
    "profile": {{"...": "full canonical profile"}},
    "ledger": [],
    "artifacts": [],
    "candidates": [],
    "dependencies": [],
    "conflicts": [],
    "knowledge_relations": {{
      "idea_seed_artifacts": [],
      "artifact_relations": [],
      "candidate_artifacts": []
    }}
  }}
}}
"""

    @staticmethod
    def build_planning_continuation_prompt(
        job: Dict[str, Any],
        project: Dict[str, Any],
    ) -> str:
        if str(job.get("job_type") or "") == "plan_amendment":
            return AntiGravityTaskAdapter.build_amendment_prompt(job, project)
        ledger = "\n\n".join(
            "[{id}] {branch}\nQuestion: {question}\nHuman answer: {answer}\n"
            "Status: {status}".format(
                id=str(item.get("id") or "unknown"),
                branch=str(item.get("branch") or "general"),
                question=str(item.get("question") or ""),
                answer=str(item.get("answer") or ""),
                status=str(item.get("status") or ""),
            )
            for item in job.get("session_questions", [])
        )
        return f"""\
Continue the same read-only Anti-Gravity planning session in this verified
project chat.

Repository: {project["path"]}
Original wish: {job["wish"]}
Planning depth: {job["planning_depth"]}
Maximum PR candidates: {job["max_candidates"]}

Socratic ledger:
{ledger or "- No answered questions were supplied."}

Use every human answer as a binding planning input. Keep the repository baseline
from this chat. Do not modify files, run commands, create branches, or request
tool approval.

Return exactly one JSON object and no prose:
- Ask one further question as
  {{"type":"question","question":{{"branch":"...","question":"...","rationale":"..."}}}}
- Or finish as
  {{"type":"plan","resolved_question_ids":["Q-..."],"plan":{{...the complete plan...}}}}

A final plan must list every answered session question in
resolved_question_ids. Never repeat a question already present in the ledger.
The complete final plan must also include: goal, non_goals, success_metrics;
pivotal_fork or a reasoned pivotal_fork_na_reason; two structured alternatives;
review_strategy; a path-grounded repository_map; rollout_plan and rollback_plan;
four terminal branch_assessments for architecture, data, security, and operations;
and complete independently testable candidate contracts. Grounded facts and
not-applicable claims require real evidence; do not invent either.
"""

    async def _dispatch_planning_continuation(
        self,
        manager,
        chat_id: str,
        prompt: str,
    ) -> Dict[str, Any]:
        before_history, catalog = await asyncio.gather(
            asyncio.to_thread(get_integrity_chat_history, chat_id),
            asyncio.to_thread(scan_antigravity_conversation_catalog),
        )
        metadata = self._catalog_entry(catalog, chat_id)
        if metadata is None:
            raise ControlCenterError(
                "Der Planning-Zielchat wurde im Anti-Gravity-Catalog nicht gefunden.",
                code="antigravity_chat_missing",
                status=409,
            )
        project_uuid = str(metadata.get("project_uuid") or "").strip()
        if not project_uuid:
            raise ControlCenterError(
                "Der Planning-Zielchat besitzt keine bestätigte project_uuid.",
                code="antigravity_project_context_missing",
                status=409,
            )
        before_max_idx = self._history_max_idx(before_history)
        result = await manager.send_message_to_chat(
            chat_id,
            prompt,
            section=project_uuid,
            minimize=True,
        )
        persisted = await self._wait_for_persisted_user_message(
            chat_id,
            prompt,
            after_idx=before_max_idx,
        )
        self._run_baselines[chat_id] = {
            "user_idx": int(persisted.get("idx") or 0),
            "step_count": int(metadata.get("step_count") or 0),
            "updated_at": str(metadata.get("updated_at") or ""),
        }
        result["chat_id"] = chat_id
        result["reused_chat"] = True
        result["delivery_verified"] = True
        result["verified_user_idx"] = int(persisted.get("idx") or 0)
        return result

    async def repair_planning_output(
        self,
        chat_id: str,
        parser_error: str,
    ) -> Dict[str, Any]:
        """Request a syntax-only JSON correction in the verified planner chat."""
        manager = self.manager_factory()
        prompt = f"""\
Your previous planning response could not be parsed as valid JSON.

Parser feedback:
{str(parser_error)[:1000]}

Return the complete corrected JSON object again. Do not change the plan,
scope, ordering, evidence, decisions, or candidate contracts. Fix only JSON
syntax and escaping. Escape quotes, backslashes, and line breaks inside every
string. Return no markdown fence and no prose before or after the JSON object.
"""
        try:
            return await self._dispatch_planning_continuation(
                manager,
                chat_id,
                prompt,
            )
        finally:
            await manager.close_all()

    async def dispatch_planning(
        self,
        job: Dict[str, Any],
        project: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self.manager_factory()
        continuation = bool(job.get("continuation"))
        linked_workspace = str(
            project.get("integrity_workspace_path") or project["path"]
        ).strip()
        saved_project_name = str(
            project.get("antigravity_project_name")
            or project.get("name")
            or ""
        ).strip()
        linked_project_name = (
            saved_project_name
            if project.get("integrity_project_uuid")
            else "" if project.get("integrity_workspace_path") else saved_project_name
        )
        planning_project = {
            **project,
            "path": linked_workspace,
            "name": saved_project_name,
        }
        prompt = (
            self.build_planning_continuation_prompt(job, planning_project)
            if continuation
            else self.build_planning_prompt(job, planning_project)
        )
        try:
            if continuation:
                chat_id = str(job.get("antigravity_chat_id") or "").strip()
                if not chat_id:
                    raise ControlCenterError(
                        "Planning-Fortsetzung besitzt keine Conversation-ID.",
                        code="planning_chat_id_missing",
                        status=409,
                    )
                return await self._dispatch_planning_continuation(
                    manager,
                    chat_id,
                    prompt,
                )
            result = await manager.create_new_project_chat_window(
                linked_workspace,
                prompt,
                minimize=True,
                project_name=linked_project_name,
            )
            chat_id = str(result.get("chat_id") or "")
            if chat_id:
                metadata = await self._remember_initial_delivery(
                    chat_id,
                    prompt,
                    expected_workspace_path=linked_workspace,
                    require_project_uuid=True,
                )
                metadata = metadata if isinstance(metadata, dict) else {}
                result["project_context"] = {
                    "project_uuid": str(metadata.get("project_uuid") or "").strip(),
                    "workspace_path": str(metadata.get("workspace_path") or "").strip(),
                    "project_name": str(
                        metadata.get("project_name")
                        or metadata.get("repository_name")
                        or saved_project_name
                    ).strip(),
                }
            return result
        finally:
            await manager.close_all()

    @staticmethod
    def read_planning_result(chat_id: str) -> Dict[str, Any]:
        history = get_integrity_chat_history(chat_id).get("history") or []
        contents = [
            item.get("content")
            for item in history
            if item.get("type") == "message"
            and item.get("role") == "assistant"
            and item.get("content") not in (None, "", [], {})
        ]
        if not contents:
            raise ControlCenterError(
                "Planner-Chat enthält keine auswertbare Antwort.",
                code="planning_output_missing",
                status=409,
            )
        latest = contents[-1]
        if isinstance(latest, dict):
            return latest
        if isinstance(latest, list):
            text_blocks = [
                str(block.get("text") or "")
                for block in latest
                if isinstance(block, dict)
                and block.get("type") in {"text", "output_text"}
                and block.get("text")
            ]
            raw = "\n".join(text_blocks).strip()
        elif isinstance(latest, str):
            raw = latest.strip()
        else:
            raise ControlCenterError(
                "Planner-Antwort hat einen nicht unterstützten Inhaltstyp.",
                code="invalid_planning_output",
                status=409,
            )
        if not raw:
            raise ControlCenterError(
                "Planner-Chat enthält keine auswertbare Antwort.",
                code="planning_output_missing",
                status=409,
            )
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ControlCenterError(
                    "Planner-Antwort enthält kein gültiges JSON-Objekt.",
                    code="invalid_planning_output",
                    status=409,
                )
            try:
                result = json.loads(raw[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ControlCenterError(
                    f"Planner-JSON ist ungültig: {exc}",
                    code="invalid_planning_output",
                    status=409,
                ) from exc
        if not isinstance(result, dict):
            raise ControlCenterError(
                "Planner-Ausgabe muss ein JSON-Objekt sein.",
                code="invalid_planning_output",
            )
        return result

    async def archive_chat(self, chat_id: str) -> None:
        manager = self.manager_factory()
        try:
            await manager.set_chat_archived(
                chat_id,
                True,
                section="project",
                minimize=True,
            )
        finally:
            await manager.close_all()

    async def wait_until_complete(
        self,
        chat_id: str,
        *,
        timeout_seconds: int,
        on_state_change: Optional[
            Callable[[str, Dict[str, Any]], Any]
        ] = None,
    ) -> Dict[str, Any]:
        started = time.monotonic()
        deadline = started + timeout_seconds
        saw_running = False
        last_metadata: Dict[str, Any] | None = None
        baseline = self._run_baselines.get(chat_id)
        notified_state = "running"
        gate_started: Optional[float] = None
        try:
            while True:
                current_history: Optional[Dict[str, Any]] = None
                try:
                    loaded_history = await asyncio.to_thread(
                        get_integrity_chat_history,
                        chat_id,
                        strict=True,
                    )
                    current_history = loaded_history or {"history": []}
                    history = current_history
                    gate = self._active_user_gate(history, baseline)
                    desired_state = "waiting_human" if gate else "running"
                    if desired_state != notified_state:
                        await self._emit_state_change(
                            on_state_change,
                            desired_state,
                            {**(gate or {}), "chat_id": chat_id},
                        )
                        notified_state = desired_state
                        if desired_state == "waiting_human":
                            gate_started = time.monotonic()
                        elif gate_started is not None:
                            deadline += time.monotonic() - gate_started
                            gate_started = None
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A transient history read/callback failure must retain the
                    # last known gate. The next poll retries the transition.
                    pass
                if (
                    notified_state != "waiting_human"
                    and time.monotonic() >= deadline
                ):
                    break

                catalog = await asyncio.to_thread(
                    scan_antigravity_conversation_catalog
                )
                metadata = next(
                    (
                        item
                        for item in catalog
                        if str(item.get("convo_id") or "") == chat_id
                    ),
                    None,
                )
                if metadata:
                    last_metadata = metadata
                    is_running = (
                        not metadata.get("archived")
                        and metadata.get("status") == "running"
                    )
                    saw_running = saw_running or is_running
                    history_is_safe = (
                        current_history is not None
                        and notified_state != "waiting_human"
                        and (
                            self._history_has_new_assistant_completion(
                                current_history,
                                baseline,
                            )
                            if baseline is not None
                            else self._history_has_no_active_tools(
                                current_history,
                                None,
                            )
                        )
                    )
                    if saw_running and not is_running:
                        if history_is_safe:
                            self._run_baselines.pop(chat_id, None)
                            return {
                                "completed": True,
                                "chat_id": chat_id,
                                "metadata": metadata,
                            }
                    if not saw_running and metadata.get("status") == "complete":
                        # The first status transition can be too fast to observe.
                        elapsed = time.monotonic() - started
                        completion_is_new = (
                            baseline is not None
                            and current_history is not None
                            and self._history_has_new_assistant_completion(
                                current_history,
                                baseline,
                            )
                        )
                        legacy_completion_is_safe = (
                            baseline is None
                            and elapsed >= 45
                            and current_history is not None
                            and self._history_has_no_active_tools(
                                current_history,
                                None,
                            )
                        )
                        if (
                            completion_is_new
                            or legacy_completion_is_safe
                        ):
                            self._run_baselines.pop(chat_id, None)
                            return {
                                "completed": True,
                                "chat_id": chat_id,
                                "metadata": metadata,
                            }
                await asyncio.sleep(1)
            self._run_baselines.pop(chat_id, None)
            raise ControlCenterError(
                "Anti-Gravity Task hat sein Zeitbudget überschritten.",
                code="agent_task_timeout",
                status=408,
            )
        finally:
            if notified_state == "waiting_human":
                try:
                    await self._emit_state_change(
                        on_state_change,
                        "running",
                        {"chat_id": chat_id},
                    )
                except Exception:
                    pass

    @staticmethod
    def progress_payload(result: Dict[str, Any]) -> Dict[str, Any]:
        metadata = result.get("metadata") or {}
        return {
            "summary": "Anti-Gravity conversation completed.",
            "chat_id": result.get("chat_id"),
            "step_count": int(metadata.get("step_count") or 0),
            "updated_at": metadata.get("updated_at"),
            "status": metadata.get("status"),
        }
