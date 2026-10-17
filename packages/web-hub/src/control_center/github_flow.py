"""Idempotent GitHub materialization and synchronization for agent tasks."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import config
from src.control_center.common import (
    SHA_PATTERN,
    ControlCenterError,
    clean_text,
    public_id,
)
from src.control_center.worktrees import WorktreeManager
from src.github_client import GitHubAPIError, GitHubClient


def _matches_protected(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/")
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if any(fnmatch.fnmatch(normalized, candidate) for candidate in candidates):
            return True
    return False


class GitHubFlow:
    def __init__(
        self,
        store,
        *,
        client: Optional[GitHubClient] = None,
        worktrees: Optional[WorktreeManager] = None,
    ) -> None:
        self.store = store
        if client is None:
            if not config.github_token:
                raise ControlCenterError(
                    "GitHub-Token ist nicht konfiguriert.",
                    code="github_not_configured",
                    status=409,
                )
            client = GitHubClient(config.github_token)
        self.client = client
        self.worktrees = worktrees or WorktreeManager()

    def _context(self, task_id: str) -> Dict[str, Any]:
        with self.store.db._get_connection() as conn:
            row = conn.execute(
                """SELECT task.*, project.name AS project_name,
                          project.path AS project_path,
                          project.github_owner, project.github_repo,
                          project.github_url, project.default_branch,
                          project.test_command,
                          candidate.title AS candidate_title,
                          candidate.scope, candidate.acceptance_criteria_json,
                          candidate.non_goals AS candidate_non_goals,
                          candidate.risk_level AS candidate_risk,
                          contract.required_checks_json,
                          contract.manual_tests_json,
                          contract.definition_of_done,
                          contract.wave AS candidate_wave,
                          campaign.title AS campaign_title,
                          campaign.goal AS campaign_goal,
                          profile.rollback_plan,
                          profile.activation_policy,
                          (SELECT COUNT(*)
                             FROM control_pr_dependencies dependency
                            WHERE dependency.candidate_id = task.candidate_id)
                              AS dependency_count
                   FROM control_agent_tasks task
                   JOIN projects project ON project.id = task.project_id
                   JOIN control_pr_candidates candidate
                     ON candidate.id = task.candidate_id
                   JOIN control_candidate_contracts contract
                     ON contract.candidate_id = candidate.id
                   JOIN control_campaigns campaign ON campaign.id = task.campaign_id
                   JOIN control_campaign_profiles profile
                     ON profile.campaign_id = campaign.id
                   WHERE task.id = ?""",
                (task_id,),
            ).fetchone()
            findings = [
                dict(finding)
                for finding in conn.execute(
                    """SELECT id, classification, source, body, sha
                       FROM control_findings
                       WHERE task_id = ? AND status = 'open'
                       ORDER BY CASE classification
                           WHEN 'BLOCKER' THEN 0
                           WHEN 'REQUIRED' THEN 1
                           WHEN 'QUESTION' THEN 2
                           WHEN 'SUGGESTION' THEN 3
                           ELSE 4 END,
                           created_at ASC
                       LIMIT 20""",
                    (task_id,),
                ).fetchall()
            ]
        if not row:
            raise ControlCenterError(
                "Agent Task nicht gefunden.",
                code="task_not_found",
                status=404,
            )
        context = dict(row)
        for field in (
            "acceptance_criteria_json",
            "required_checks_json",
            "manual_tests_json",
            "allowed_actions_json",
            "protected_paths_json",
        ):
            context[field.removesuffix("_json")] = json.loads(context[field] or "[]")
        context["open_findings"] = findings
        return context

    @staticmethod
    def _project(context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": context["project_id"],
            "name": context["project_name"],
            "path": context["project_path"],
            "github_owner": context["github_owner"],
            "github_repo": context["github_repo"],
            "github_url": context["github_url"],
            "default_branch": context["default_branch"],
        }

    @staticmethod
    def _require_lease(
        context: Dict[str, Any],
        worker_id: str,
        lease_token: str,
    ) -> None:
        if (
            context["lease_owner"] != worker_id
            or context["lease_token"] != lease_token
            or context["status"] not in {"leased", "running"}
        ):
            raise ControlCenterError(
                "Eine gültige Worker-Lease ist erforderlich.",
                code="invalid_task_lease",
                status=409,
            )

    @staticmethod
    def _issue_marker(task_id: str) -> str:
        return f"<!-- antigravity-task:{task_id} -->"

    def _issue_body(self, context: Dict[str, Any]) -> str:
        criteria = "\n".join(
            f"- [ ] {item}" for item in context["acceptance_criteria"]
        )
        checks = "\n".join(
            f"- [ ] `{item}`" for item in context["required_checks"]
        )
        return f"""\
{self._issue_marker(context["id"])}

## Campaign
{context["campaign_title"]}

## Goal
{context["campaign_goal"]}

## Scope
{context["scope"]}

## Acceptance criteria
{criteria or "- [ ] Scope is demonstrably complete."}

## Required checks
{checks or "- [ ] Repository checks pass."}

## Non-goals
{context["candidate_non_goals"] or "None specified."}

## Control-plane contract
- Task: `{context["id"]}`
- Candidate: `{context["candidate_id"]}`
- Base SHA: `{context["base_sha"]}`
- Risk: `{context["candidate_risk"]}`
- Definition of done: {context["definition_of_done"]}
"""

    def _rebaseline_wave_successor(
        self,
        context: Dict[str, Any],
        *,
        actor: str,
    ) -> Dict[str, Any]:
        """Move later campaign waves to the current remote default-branch SHA."""

        is_successor = (
            int(context.get("candidate_wave") or 1) > 1
            or int(context.get("dependency_count") or 0) > 0
        )
        if not is_successor:
            return context
        current_default_sha = self.worktrees.default_branch_sha(
            self._project(context),
            fetch=True,
        )
        previous_sha = str(context.get("base_sha") or "").lower()
        if current_default_sha == previous_sha:
            return context
        with self.store.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET base_sha = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND current_sha = '' AND pr_number IS NULL""",
                (current_default_sha, context["id"]),
            )
            if conn.total_changes != 1:
                raise ControlCenterError(
                    "Der Wave-Nachfolger wurde bereits materialisiert und kann "
                    "nicht mehr automatisch neu baselined werden.",
                    code="successor_rebaseline_too_late",
                    status=409,
                )
            conn.execute(
                """UPDATE control_pr_candidates
                   SET base_sha = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (current_default_sha, context["candidate_id"]),
            )
            conn.execute(
                """UPDATE control_work_orders
                   SET approval_sha = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (current_default_sha, context["work_order_id"]),
            )
            self.store._audit(
                conn,
                project_id=int(context["project_id"]),
                entity_type="agent_task",
                entity_id=str(context["id"]),
                action="agent_task.successor_rebaselined",
                actor=str(actor or "orchestrator")[:120],
                from_state=previous_sha,
                to_state=current_default_sha,
                evidence={
                    "wave": int(context.get("candidate_wave") or 1),
                    "dependency_count": int(context.get("dependency_count") or 0),
                    "default_branch": context.get("default_branch") or "main",
                },
            )
            conn.commit()
        return self._context(str(context["id"]))

    def _pull_request_body(self, context: Dict[str, Any]) -> str:
        checks = "\n".join(
            f"- [ ] `{item}`" for item in context["required_checks"]
        )
        return f"""\
{self._issue_marker(context["id"])}

## Scope
{context["scope"]}

## Verification contract
{checks or "- [ ] Repository checks pass."}

## Evidence and gates
- Evidence Pack: `{context["id"]}`
- Exact base SHA: `{context["base_sha"]}`
- Human test and merge approvals are bound to the final head SHA.
- Production remains disabled unless its separate capability and approval are enabled.

Closes #{context["issue_number"]}
"""

    async def materialize_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_token: str,
    ) -> Dict[str, Any]:
        context = self._context(task_id)
        self._require_lease(context, worker_id, lease_token)
        context = self._rebaseline_wave_successor(
            context,
            actor=worker_id,
        )
        policy = self.store.get_repository_policy(context["project_id"])
        if not policy["capability"].get("create_issue", False):
            raise ControlCenterError(
                "Issue-Erstellung ist für dieses Repository gesperrt.",
                code="create_issue_denied",
                status=403,
            )
        owner = str(context["github_owner"] or "")
        repo = str(context["github_repo"] or "")
        if not owner or not repo:
            raise ControlCenterError(
                "Das Projekt ist nicht mit GitHub verknüpft.",
                code="github_repository_not_linked",
                status=409,
            )
        issue_number = context["issue_number"]
        issue_url = context["issue_url"]
        if not issue_number:
            existing = await self.client.find_issue_by_marker(
                owner,
                repo,
                self._issue_marker(task_id),
            )
            issue = existing or await self.client.create_issue(
                owner,
                repo,
                context["candidate_title"],
                body=self._issue_body(context),
                labels=["antigravity-managed", "task"],
            )
            issue_number = int(issue["number"])
            issue_url = str(issue["html_url"])
        worktree = self.worktrees.ensure_worktree(
            self._project(context),
            context,
        )
        return self.store.transition_task(
            task_id,
            to_state="running",
            actor=worker_id,
            lease_token=lease_token,
            reason="GitHub issue and isolated worktree materialized.",
            fields={
                "issue_number": issue_number,
                "issue_url": issue_url,
                "worktree_path": str(worktree),
                "wake_reason": "agent_execution",
            },
        )

    async def publish_draft_pull_request(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_token: str,
    ) -> Dict[str, Any]:
        context = self._context(task_id)
        self._require_lease(context, worker_id, lease_token)
        policy = self.store.get_repository_policy(context["project_id"])
        for capability in ("push_branch", "create_draft_pr"):
            if not policy["capability"].get(capability, False):
                raise ControlCenterError(
                    f"Capability {capability} ist gesperrt.",
                    code=f"{capability}_denied",
                    status=403,
                )
        worktree = Path(str(context["worktree_path"] or "")).resolve()
        if not worktree.is_dir():
            raise ControlCenterError(
                "Der Task-Worktree fehlt.",
                code="worktree_missing",
                status=409,
            )
        self.worktrees.assert_commit_hygiene(
            worktree,
            base_sha=context["base_sha"],
        )
        changed_files = self.worktrees.changed_files(worktree, context["base_sha"])
        sha = self.worktrees.commit_changes(
            worktree,
            f"{context['candidate_title']} ({context['candidate_id']})",
        )
        if sha == str(context["base_sha"]).lower():
            self.store.record_task_progress(
                task_id,
                worker_id=worker_id,
                lease_token=lease_token,
                progress={
                    "summary": "No repository diff produced.",
                    "base_sha": context["base_sha"],
                },
            )
            raise ControlCenterError(
                "Der Task hat keinen prüfbaren Repository-Diff erzeugt.",
                code="no_repository_diff",
                status=409,
            )
        self.store.set_task_revision(task_id, sha=sha, actor=worker_id)
        protected = [
            path
            for path in changed_files
            if _matches_protected(path, context["protected_paths"])
        ]
        with self.store.db._get_connection() as conn:
            protected_approved = self.store._active_approval(
                conn,
                task_id,
                "protected_path",
                sha,
            )
        if protected and not protected_approved:
            with self.store.db._get_connection() as conn:
                self.store._attention(
                    conn,
                    project_id=int(context["project_id"]),
                    category="protected_path",
                    entity_type="agent_task",
                    entity_id=task_id,
                    title="Änderung an geschütztem Pfad prüfen",
                    consequence=(
                        "Branch und Draft-PR werden bis zur Freigabe nicht "
                        f"publiziert. SHA {sha[:12]} · "
                        + ", ".join(protected)
                    ),
                    recommendation=(
                        "Betroffene Pfade und Sicherheitsauswirkung prüfen "
                        "und nur den angezeigten Commit-SHA freigeben."
                    ),
                    urgency="critical",
                )
                conn.commit()
            self.store.transition_task(
                task_id,
                to_state="paused",
                actor="orchestrator",
                reason="Protected paths require explicit human approval.",
                fields={
                    "last_error": "Protected paths: " + ", ".join(protected),
                    "wake_reason": "protected_path_approval",
                },
            )
            raise ControlCenterError(
                "Geschützte Pfade benötigen eine explizite Freigabe: "
                + ", ".join(protected),
                code="protected_path_approval_required",
                status=409,
            )
        if protected:
            with self.store.db._get_connection() as conn:
                self.store._resolve_attention(
                    conn,
                    "agent_task",
                    task_id,
                    "protected_path",
                )
                conn.commit()
        self.worktrees.push_branch(worktree, context["branch_name"])
        owner = context["github_owner"]
        repo = context["github_repo"]
        pull = None
        if context["pr_number"]:
            pull = await self.client.get_pull_request(
                owner,
                repo,
                int(context["pr_number"]),
            )
        if pull is None:
            pull = await self.client.find_pull_request_by_head(
                owner,
                repo,
                context["branch_name"],
            )
        latest = {**context, "issue_number": context["issue_number"]}
        body = self._pull_request_body(latest)
        if pull is None:
            pull = await self.client.create_pull_request(
                owner,
                repo,
                title=context["candidate_title"],
                head=context["branch_name"],
                base=context["default_branch"] or "main",
                body=body,
                draft=True,
            )
        else:
            pull = await self.client.update_pull_request(
                owner,
                repo,
                int(pull["number"]),
                title=context["candidate_title"],
                body=body,
            )
        return self.store.transition_task(
            task_id,
            to_state="waiting_ci",
            actor=worker_id,
            lease_token=lease_token,
            reason="Draft PR published; waiting for required checks.",
            fields={
                "pr_number": int(pull["number"]),
                "pr_url": str(pull["html_url"]),
                "current_sha": sha,
                "wake_reason": "github_checks",
            },
        )

    @staticmethod
    def _require_rejectable_protected_task(
        task: Dict[str, Any],
        expected_sha: str,
    ) -> None:
        if (
            task.get("status") != "paused"
            or task.get("wake_reason") != "protected_path_approval"
        ):
            raise ControlCenterError(
                "Der Task wartet nicht auf eine Protected-Path-Entscheidung.",
                code="protected_path_approval_not_required",
                status=409,
            )
        current_sha = str(task.get("current_sha") or "").strip().lower()
        if not current_sha or current_sha != expected_sha:
            raise ControlCenterError(
                "Die Ablehnung gilt nur für den exakten angezeigten Task-SHA.",
                code="approval_sha_mismatch",
                status=409,
            )
        if task.get("lease_owner") or task.get("lease_token") or task.get("lease_until"):
            raise ControlCenterError(
                "Der pausierte Task besitzt noch eine aktive Lease.",
                code="protected_repair_active_lease",
                status=409,
            )
        if task.get("pr_number") or str(task.get("pr_url") or "").strip():
            raise ControlCenterError(
                "Ein bereits veröffentlichter Pull Request darf nicht lokal zurückgesetzt werden.",
                code="protected_repair_pull_request_exists",
                status=409,
            )

    async def reject_protected_path_for_repair(
        self,
        task_id: str,
        *,
        sha: str,
        actor: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Reject one unpublished protected-path commit and queue a repair."""

        normalized_sha = str(sha or "").strip().lower()
        if not SHA_PATTERN.fullmatch(normalized_sha):
            raise ControlCenterError(
                "Ein gültiger exakter Commit-SHA ist erforderlich.",
                code="invalid_sha",
            )
        actor_name = clean_text(actor or "human", "actor", maximum=120)
        rejection_reason = clean_text(reason, "reason", minimum=3, maximum=2000)
        context = self._context(task_id)
        self._require_rejectable_protected_task(context, normalized_sha)

        owner = str(context["github_owner"])
        repo = str(context["github_repo"])
        branch = str(context["branch_name"])
        remote_ref = await self.client.get_ref(owner, repo, f"heads/{branch}")
        if remote_ref is not None:
            raise ControlCenterError(
                "Der Task-Branch ist bereits auf GitHub veröffentlicht.",
                code="protected_repair_branch_published",
                status=409,
            )
        pull = await self.client.find_pull_request_by_head(owner, repo, branch)
        if pull is not None:
            raise ControlCenterError(
                "Für den Task-Branch existiert bereits ein Pull Request.",
                code="protected_repair_pull_request_exists",
                status=409,
            )

        worktree = Path(str(context["worktree_path"] or "")).resolve()
        rewind: Dict[str, Any] | None = None
        try:
            with self.store.db._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                locked_row = conn.execute(
                    "SELECT * FROM control_agent_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if not locked_row:
                    raise ControlCenterError(
                        "Agent Task nicht gefunden.",
                        code="task_not_found",
                        status=404,
                    )
                locked_task = dict(locked_row)
                self._require_rejectable_protected_task(
                    locked_task,
                    normalized_sha,
                )
                rewind = self.worktrees.rewind_unpublished_task_commit(
                    self._project(context),
                    locked_task,
                    expected_head=normalized_sha,
                )

                conn.execute(
                    """UPDATE control_human_approvals
                       SET revoked_at = CURRENT_TIMESTAMP
                       WHERE entity_type = 'agent_task' AND entity_id = ?
                         AND approval_type = 'protected_path'
                         AND revoked_at IS NULL""",
                    (task_id,),
                )
                approval_id = public_id("APR")
                approval_evidence = {
                    "old_sha": rewind["old_sha"],
                    "base_sha": rewind["base_sha"],
                    "branch_name": rewind["branch_name"],
                    "worktree_path": rewind["worktree_path"],
                    "changed_files": rewind["changed_files"],
                    "overlay_tree": rewind["overlay_tree"],
                    "excluded_generated_count": rewind[
                        "excluded_generated_count"
                    ],
                    "excluded_generated_sample": rewind[
                        "excluded_generated_sample"
                    ],
                    "unpublished": True,
                }
                conn.execute(
                    """INSERT INTO control_human_approvals (
                           id, project_id, entity_type, entity_id, approval_type,
                           sha, decision, actor, reason, evidence_json
                       ) VALUES (?, ?, 'agent_task', ?, 'protected_path',
                                 ?, 'rejected', ?, ?, ?)""",
                    (
                        approval_id,
                        int(locked_task["project_id"]),
                        task_id,
                        normalized_sha,
                        actor_name,
                        rejection_reason,
                        json.dumps(approval_evidence, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'repair',
                           wake_reason = 'protected_path_rejected',
                           current_sha = '',
                           last_error = ?,
                           wake_at = NULL,
                           finished_at = NULL,
                           lease_owner = '', lease_token = '', lease_until = NULL,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (
                        "Protected-path changes rejected: " + rejection_reason,
                        task_id,
                    ),
                )
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = 'running', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (locked_task["candidate_id"],),
                )
                self.store._resolve_attention(
                    conn,
                    "agent_task",
                    task_id,
                    "protected_path",
                )
                self.store._audit(
                    conn,
                    project_id=int(locked_task["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    action="protected_path.rejected_for_repair",
                    actor=actor_name,
                    from_state="paused",
                    to_state="repair",
                    reason=rejection_reason,
                    evidence={
                        "approval_id": approval_id,
                        **approval_evidence,
                    },
                )
                conn.commit()
        except Exception:
            if rewind is not None:
                try:
                    self.worktrees.restore_unpublished_task_head(
                        worktree,
                        base_sha=str(rewind["base_sha"]),
                        old_sha=str(rewind["old_sha"]),
                        overlay_tree=str(rewind["overlay_tree"]),
                    )
                except Exception as compensation_error:
                    raise ControlCenterError(
                        "Persistenzfehler nach lokalem Branch-Rücklauf; "
                        "die automatische Wiederherstellung ist fehlgeschlagen.",
                        code="protected_repair_compensation_failed",
                        status=500,
                    ) from compensation_error
            raise

        return {
            "task": self.store.get_task(task_id),
            "approval": {
                "id": approval_id,
                "approval_type": "protected_path",
                "sha": normalized_sha,
                "decision": "rejected",
                "actor": actor_name,
                "reason": rejection_reason,
                "evidence": approval_evidence,
            },
            "rewind": rewind,
        }

    def _reconcile_remote_pull_terminal(
        self,
        task_id: str,
        context: Dict[str, Any],
        *,
        pull: Optional[Dict[str, Any]],
        reason: str,
    ) -> Dict[str, Any]:
        """Persist a GitHub-owned terminal PR state without mutating GitHub."""

        if reason not in {"missing", "closed", "merged"}:
            raise ValueError(f"Unsupported remote PR terminal reason: {reason}")

        is_merged = reason == "merged"
        merge_sha = ""
        if is_merged:
            for value in (
                (pull or {}).get("merge_commit_sha"),
                (pull or {}).get("head_sha"),
                context.get("current_sha"),
            ):
                candidate = str(value or "").strip().lower()
                if SHA_PATTERN.fullmatch(candidate):
                    merge_sha = candidate
                    break
            if not merge_sha:
                raise ControlCenterError(
                    "GitHub meldet den Pull Request als gemergt, liefert aber "
                    "keinen prüfbaren Merge-SHA.",
                    code="pull_request_merge_sha_missing",
                    status=409,
                )

        campaign_completed = False
        changed = False
        stale_sync_ignored = False
        with self.store.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not task:
                raise ControlCenterError(
                    "Agent Task nicht gefunden.",
                    code="task_not_found",
                    status=404,
                )
            task_status = str(task["status"])
            same_pull_request = str(task["pr_number"] or "") == str(
                context["pr_number"] or ""
            )
            if task_status in {"completed", "cancelled"}:
                pass
            elif (
                task_status not in {"waiting_ci", "waiting_review", "waiting_human"}
                or not same_pull_request
            ):
                stale_sync_ignored = True
            else:
                changed = True
                if is_merged:
                    conn.execute(
                        """UPDATE control_agent_tasks
                           SET status = 'completed', finished_at = CURRENT_TIMESTAMP,
                               wake_reason = 'github_pr_merged', last_error = '',
                               lease_owner = '', lease_token = '', lease_until = NULL,
                               merged_sha = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (merge_sha, task_id),
                    )
                    conn.execute(
                        """UPDATE control_pr_candidates
                           SET status = 'merged', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (context["candidate_id"],),
                    )
                    campaign_completed = self.store._complete_campaign_if_done(
                        conn,
                        str(context["campaign_id"]),
                        actor="github",
                    )
                    action = "agent_task.merged"
                    to_state = "completed"
                    audit_reason = "Pull request was merged outside Anti-Gravity."
                else:
                    wake_reason = (
                        "github_pr_missing"
                        if reason == "missing"
                        else "github_pr_closed"
                    )
                    conn.execute(
                        """UPDATE control_agent_tasks
                           SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP,
                               wake_reason = ?, last_error = '', lease_owner = '',
                               lease_token = '', lease_until = NULL,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (wake_reason, task_id),
                    )
                    conn.execute(
                        """UPDATE control_pr_candidates
                           SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?
                             AND status NOT IN ('completed', 'merged', 'deployed')""",
                        (context["candidate_id"],),
                    )
                    conn.execute(
                        """UPDATE control_work_orders
                           SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'approved'""",
                        (context["work_order_id"],),
                    )
                    conn.execute(
                        """UPDATE control_evidence_packs
                           SET status = 'cancelled',
                               summary = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE task_id = ?""",
                        (
                            "GitHub pull request is no longer available."
                            if reason == "missing"
                            else "GitHub pull request was closed without merging.",
                            task_id,
                        ),
                    )
                    action = "agent_task.cancelled"
                    to_state = "cancelled"
                    audit_reason = (
                        "Pull request no longer exists on GitHub."
                        if reason == "missing"
                        else "Pull request was closed outside Anti-Gravity."
                    )

                self.store._resolve_attention(
                    conn,
                    "agent_task",
                    task_id,
                    "agent_permission",
                )
                self.store._resolve_attention(
                    conn,
                    "pr_candidate",
                    str(context["candidate_id"]),
                    "work_order_approval",
                )
                self.store._audit(
                    conn,
                    project_id=int(context["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    action=action,
                    actor="github",
                    from_state=str(task["status"]),
                    to_state=to_state,
                    reason=audit_reason,
                    evidence={
                        "pr": context["pr_number"],
                        "remote_state": reason,
                        "merge_sha": merge_sha,
                    },
                )
            conn.commit()

        return {
            "task": self.store.get_task(task_id),
            "pull_request": pull,
            "checks": [],
            "statuses": {"state": "terminal", "statuses": []},
            "reviews": [],
            "comments": [],
            "evidence_pack": self.store.evidence_pack(task_id),
            "remote_reconciled": reason,
            "campaign_completed": campaign_completed,
            "terminal_noop": not changed,
            "stale_sync_ignored": stale_sync_ignored,
        }

    async def sync_pull_request(self, task_id: str) -> Dict[str, Any]:
        context = self._context(task_id)
        if context["status"] in {"completed", "cancelled"}:
            return {
                "task": self.store.get_task(task_id),
                "pull_request": None,
                "checks": [],
                "statuses": {"state": "terminal", "statuses": []},
                "reviews": [],
                "comments": [],
                "evidence_pack": self.store.evidence_pack(task_id),
                "terminal_noop": True,
            }
        if not context["pr_number"]:
            raise ControlCenterError(
                "Der Task hat noch keinen Pull Request.",
                code="pull_request_missing",
                status=409,
            )
        owner = context["github_owner"]
        repo = context["github_repo"]
        number = int(context["pr_number"])
        try:
            pull = await self.client.get_pull_request(owner, repo, number)
        except GitHubAPIError as exc:
            if exc.status != 404:
                raise
            return self._reconcile_remote_pull_terminal(
                task_id,
                context,
                pull=None,
                reason="missing",
            )
        if bool(pull.get("merged")):
            return self._reconcile_remote_pull_terminal(
                task_id,
                context,
                pull=pull,
                reason="merged",
            )
        if str(pull.get("state") or "").lower() == "closed":
            return self._reconcile_remote_pull_terminal(
                task_id,
                context,
                pull=pull,
                reason="closed",
            )
        head_sha = str(pull["head_sha"] or "").lower()
        if not head_sha:
            raise ControlCenterError(
                "GitHub liefert noch keinen prüfbaren PR-Head-SHA.",
                code="pull_request_sha_missing",
                status=409,
            )
        if head_sha and head_sha != str(context["current_sha"] or "").lower():
            self.store.set_task_revision(task_id, sha=head_sha, actor="github")
            context["current_sha"] = head_sha
        checks = await self.client.get_check_runs(owner, repo, head_sha)
        statuses = await self.client.get_commit_status(owner, repo, head_sha)
        observed = {
            check["name"]: check["conclusion"] or check["status"] for check in checks
        }
        observed.update(
            {item["context"]: item["state"] for item in statuses["statuses"]}
        )
        for required in context["required_checks"]:
            conclusion = str(observed.get(required) or "pending").lower()
            status = (
                "passed"
                if conclusion in {"success", "neutral", "skipped"}
                else "failed"
                if conclusion in {"failure", "error", "cancelled", "timed_out"}
                else "pending"
            )
            self.store.add_evidence(
                task_id,
                {
                    "kind": "ci_check",
                    "criterion_key": f"check:{required}",
                    "title": required,
                    "status": status,
                    "sha": head_sha,
                    "result": conclusion,
                    "payload": {"observed": observed},
                },
                actor="github",
            )
        reviews = await self.client.get_pull_request_reviews(owner, repo, number)
        comments = await self.client.get_review_comments(owner, repo, number)
        for review in reviews:
            if review["state"].upper() == "CHANGES_REQUESTED":
                self.store.record_finding(
                    task_id,
                    {
                        "classification": "REQUIRED",
                        "source": "github_review",
                        "external_id": f"review:{review['id']}",
                        "body": review["body"] or "Reviewer requested changes.",
                        "sha": review["commit_id"] or head_sha,
                    },
                    actor=review["user"] or "github",
                )
        for comment in comments:
            body = str(comment["body"] or "")
            lowered = body.lower()
            classification = (
                "BLOCKER"
                if "[blocker]" in lowered
                else "REQUIRED"
                if "[required]" in lowered
                else "QUESTION"
                if "?" in body
                else "SUGGESTION"
            )
            self.store.record_finding(
                task_id,
                {
                    "classification": classification,
                    "source": "github_review_comment",
                    "external_id": f"comment:{comment['id']}",
                    "body": f"{comment['path']}:{comment['line'] or ''} {body}".strip(),
                    "sha": comment["commit_id"] or head_sha,
                },
                actor=comment["user"] or "github",
            )
        required_results = [
            str(observed.get(required) or "pending").lower()
            for required in context["required_checks"]
        ]
        # No configured checks means there is no CI gate to wait for. Evidence
        # evaluation and the SHA-bound human gate still run below.
        if (
            context["status"] == "waiting_ci"
            and all(
                result in {"success", "neutral", "skipped"}
                for result in required_results
            )
        ):
            transition_reason = (
                "All required GitHub checks passed."
                if required_results
                else "No required GitHub checks are configured."
            )
            self.store.transition_task(
                task_id,
                to_state="waiting_review",
                actor="github",
                reason=transition_reason,
                fields={"wake_reason": "review_and_evidence"},
            )
        elif (
            context["status"] in {"waiting_ci", "waiting_review", "waiting_human"}
            and any(
                result in {"failure", "error", "cancelled", "timed_out"}
                for result in required_results
            )
        ):
            self.store.transition_task(
                task_id,
                to_state="repair",
                actor="github",
                reason="At least one required GitHub check failed.",
                fields={"wake_reason": "ci_repair"},
            )
        pack = self.store.evaluate_evidence_pack(task_id)
        return {
            "task": self.store.get_task(task_id),
            "pull_request": pull,
            "checks": checks,
            "statuses": statuses,
            "reviews": reviews,
            "comments": comments,
            "evidence_pack": pack,
        }

    async def merge_task(
        self,
        task_id: str,
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        context = self._context(task_id)
        sha = str(context["current_sha"] or "").lower()
        policy = self.store.get_repository_policy(context["project_id"])
        if not policy["capability"].get("merge_pr", False):
            raise ControlCenterError(
                "Merge-Capability ist nicht freigegeben.",
                code="merge_capability_denied",
                status=403,
            )
        with self.store.db._get_connection() as conn:
            if not self.store._active_approval(conn, task_id, "merge", sha):
                raise ControlCenterError(
                    "Eine separate SHA-gebundene Merge-Freigabe fehlt.",
                    code="merge_approval_required",
                    status=409,
                )
        pull = await self.client.get_pull_request(
            context["github_owner"],
            context["github_repo"],
            int(context["pr_number"]),
        )
        if str(pull.get("state") or "").lower() != "open":
            raise ControlCenterError(
                "Der Pull Request ist nicht mehr offen.",
                code="pull_request_not_open",
                status=409,
            )
        remote_sha = str(pull.get("head_sha") or "").lower()
        if remote_sha != sha:
            if remote_sha:
                self.store.set_task_revision(
                    task_id,
                    sha=remote_sha,
                    actor="github",
                )
            raise ControlCenterError(
                "Der GitHub PR-Head hat sich seit der Freigabe geändert. "
                "Evidence und Human-Gates müssen erneut geprüft werden.",
                code="pull_request_revision_changed",
                status=409,
            )
        if pull.get("draft"):
            await self.client.mark_pull_request_ready(
                context["github_owner"],
                context["github_repo"],
                int(context["pr_number"]),
            )
        result = await self.client.merge_pull_request(
            context["github_owner"],
            context["github_repo"],
            int(context["pr_number"]),
            commit_title=context["candidate_title"],
            commit_message=f"Anti-Gravity task {task_id}",
            merge_method=policy["merge_strategy"],
            expected_sha=sha,
        )
        if not result["merged"]:
            raise ControlCenterError(
                f"GitHub hat den Merge abgelehnt: {result['message']}",
                code="github_merge_rejected",
                status=409,
            )
        with self.store.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'completed', finished_at = CURRENT_TIMESTAMP,
                       wake_reason = 'merged', lease_owner = '', lease_token = '',
                       lease_until = NULL, merged_sha = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (str(result["sha"] or "").lower(), task_id),
            )
            conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'merged', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (context["candidate_id"],),
            )
            self.store._resolve_attention(
                conn,
                "pr_candidate",
                str(context["candidate_id"]),
                "work_order_approval",
            )
            campaign_completed = self.store._complete_campaign_if_done(
                conn,
                str(context["campaign_id"]),
                actor=actor,
            )
            self.store._audit(
                conn,
                project_id=int(context["project_id"]),
                entity_type="agent_task",
                entity_id=task_id,
                action="agent_task.merged",
                actor=str(actor or "human")[:120],
                from_state=str(context["status"]),
                to_state="completed",
                evidence={"merge_sha": result["sha"], "pr": context["pr_number"]},
            )
            conn.commit()
        issue_close_warning = ""
        if context["issue_number"]:
            try:
                await self.client.close_issue(
                    context["github_owner"],
                    context["github_repo"],
                    int(context["issue_number"]),
                    comment=(
                        f"Merged via Anti-Gravity Evidence Pack from `{sha}` "
                        f"as `{str(result['sha'] or '').lower()}`."
                    ),
                )
            except RuntimeError as exc:
                issue_close_warning = str(exc)[:2000]
                with self.store.db._get_connection() as conn:
                    self.store._attention(
                        conn,
                        project_id=int(context["project_id"]),
                        category="github_followup",
                        entity_type="agent_task",
                        entity_id=task_id,
                        title="Gemergtes GitHub Issue manuell prüfen",
                        consequence=(
                            "Der Pull Request ist gemergt; nur der nachgelagerte "
                            "Issue-Abschluss konnte nicht bestätigt werden."
                        ),
                        recommendation=issue_close_warning,
                        urgency="normal",
                    )
                    self.store._audit(
                        conn,
                        project_id=int(context["project_id"]),
                        entity_type="agent_task",
                        entity_id=task_id,
                        action="agent_task.issue_close_failed",
                        actor="github",
                        reason=issue_close_warning,
                        evidence={"issue_number": context["issue_number"]},
                    )
                    conn.commit()
        return {
            "task": self.store.get_task(task_id),
            "merge": result,
            "campaign_completed": campaign_completed,
            "issue_close_warning": issue_close_warning,
        }
