"""aiohttp handlers for the Stage-1 Engineering Control Center."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Awaitable, Callable, Dict

from aiohttp import web

from src.config import config
from src.control_center import ControlCenterError, control_center
from src.control_center.executor_service import CONTROL_EXECUTOR_KEY
from src.control_center.github_flow import GitHubFlow
from src.local_admin_security import local_cors_response


async def _payload(request: web.Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ControlCenterError("Ungültiger JSON-Body.", code="invalid_json") from exc
    if not isinstance(body, dict):
        raise ControlCenterError("JSON-Body muss ein Objekt sein.", code="invalid_json")
    return body


def _error(exc: ControlCenterError) -> web.Response:
    return web.json_response({"error": str(exc), "code": exc.code}, status=exc.status)


async def _mutate(
    request: web.Request,
    operation: str,
    callback: Callable[[], Dict[str, Any]],
    *,
    status: int = 200,
) -> web.Response:
    key = request.headers.get("Idempotency-Key", "").strip()
    try:
        cached = control_center.get_idempotent(key, operation)
        if cached is not None:
            response = dict(cached)
            response["idempotent_replay"] = True
            return web.json_response(response, status=status)
        result = callback()
        control_center.remember_idempotent(key, operation, result)
        return web.json_response(result, status=status)
    except ControlCenterError as exc:
        return _error(exc)


async def _mutate_async(
    request: web.Request,
    operation: str,
    callback: Callable[[], Awaitable[Dict[str, Any]]],
    *,
    status: int = 200,
) -> web.Response:
    key = request.headers.get("Idempotency-Key", "").strip()
    try:
        cached = control_center.get_idempotent(key, operation)
        if cached is not None:
            response = dict(cached)
            response["idempotent_replay"] = True
            return web.json_response(response, status=status)
        result = await callback()
        control_center.remember_idempotent(key, operation, result)
        return web.json_response(result, status=status)
    except ControlCenterError as exc:
        return _error(exc)
    except RuntimeError as exc:
        return web.json_response(
            {"error": str(exc), "code": "github_error"},
            status=502,
        )


async def handle_control_overview(request: web.Request) -> web.Response:
    try:
        return web.json_response(control_center.overview(request.query.get("project_id")))
    except ControlCenterError as exc:
        return _error(exc)


async def handle_knowledge_chains(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            control_center.get_knowledge_chains(
                request.query.get("project_id"),
            )
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_control_policy(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "policy.update",
        lambda: {"policy": control_center.update_policy(
            mode=body.get("mode"),
            paused=body.get("paused", False),
            reason=body.get("reason", ""),
            actor=body.get("actor", "human"),
        )},
    )


async def handle_create_recommendation(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "recommendation.create",
        lambda: {"recommendation": control_center.create_recommendation(body)},
        status=201,
    )


async def handle_recommendation_disposition(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    recommendation_id = request.match_info["recommendation_id"]
    return await _mutate(
        request,
        f"recommendation.disposition:{recommendation_id}",
        lambda: {"recommendation": control_center.disposition_recommendation(
            recommendation_id,
            disposition=body.get("disposition"),
            reason=body.get("reason", ""),
            actor=body.get("actor", "human"),
        )},
    )


async def handle_create_campaign(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "campaign.create",
        lambda: {"campaign": control_center.create_campaign(body)},
        status=201,
    )


async def handle_create_pr_candidate(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    campaign_id = request.match_info["campaign_id"]
    return await _mutate(
        request,
        f"pr_candidate.create:{campaign_id}",
        lambda: {"pr_candidate": control_center.create_pr_candidate(campaign_id, body)},
        status=201,
    )


async def handle_approve_campaign(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    campaign_id = request.match_info["campaign_id"]
    approval_identity = ":".join(
        (
            "campaign.approve",
            campaign_id,
            str(body.get("expected_version") or ""),
            str(body.get("approval_sha") or "").strip().lower(),
            str(body.get("expected_plan_signature") or "").strip().lower(),
        )
    )
    return await _mutate(
        request,
        approval_identity,
        lambda: {"campaign": control_center.approve_campaign(
            campaign_id,
            expected_version=body.get("expected_version"),
            approval_sha=body.get("approval_sha"),
            expected_plan_signature=body.get("expected_plan_signature"),
            actor=body.get("actor", "human"),
            reason=body.get("reason", ""),
        )},
    )


async def handle_cancel_campaign(request: web.Request) -> web.StreamResponse:
    async def implementation(guarded_request: web.Request) -> web.Response:
        try:
            body = await _payload(guarded_request)
        except ControlCenterError as exc:
            return _error(exc)
        campaign_id = guarded_request.match_info["campaign_id"]
        return await _mutate(
            guarded_request,
            f"campaign.cancel:{campaign_id}",
            lambda: {
                "cancellation": control_center.cancel_campaign(
                    campaign_id,
                    actor=body.get("actor", "human"),
                    reason=body.get("reason", ""),
                )
            },
        )

    response = await local_cors_response(
        request,
        implementation,
        methods="POST, OPTIONS",
    )
    if request.method == "OPTIONS" and request.headers.get("Origin"):
        response.headers["Access-Control-Allow-Headers"] += ", Idempotency-Key"
    return response


async def handle_activate_candidate(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    candidate_id = request.match_info["candidate_id"]
    return await _mutate(
        request,
        f"work_order.approve:{candidate_id}",
        lambda: {"work_order": control_center.activate_candidate(
            candidate_id,
            approval_sha=body.get("approval_sha"),
            actor=body.get("actor", "human"),
            rationale=body.get("rationale", ""),
        )},
        status=201,
    )


async def handle_cancel_work_order(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    work_order_id = request.match_info["work_order_id"]
    return await _mutate(
        request,
        f"work_order.cancel:{work_order_id}",
        lambda: {
            "cancellation": control_center.cancel_unstarted_work_order(
                work_order_id,
                actor=body.get("actor", "human"),
                reason=body.get("reason", ""),
            )
        },
    )


async def handle_create_checkpoint(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "checkpoint.create",
        lambda: {"checkpoint": control_center.create_checkpoint(body)},
        status=201,
    )


async def handle_repository_policy(request: web.Request) -> web.Response:
    project_id = request.match_info["project_id"]
    try:
        if request.method == "GET":
            return web.json_response(
                {"policy": control_center.get_repository_policy(project_id)}
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        f"repository_policy.update:{project_id}",
        lambda: {
            "policy": control_center.update_repository_policy(
                project_id,
                body,
                actor=body.get("actor", "human"),
            )
        },
    )


async def handle_idea_seeds(request: web.Request) -> web.Response:
    try:
        if request.method == "GET":
            return web.json_response(
                {
                    "idea_seeds": control_center.list_idea_seeds(
                        request.query.get("project_id")
                    )
                }
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "idea_seed.create",
        lambda: {"idea_seed": control_center.create_idea_seed(body)},
        status=201,
    )


handle_create_idea_seed = handle_idea_seeds


async def handle_idea_seed(request: web.Request) -> web.Response:
    idea_seed_id = request.match_info["idea_seed_id"]
    try:
        if request.method == "GET":
            return web.json_response(
                {"idea_seed": control_center.get_idea_seed(idea_seed_id)}
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    actor = body.pop("actor", "human")
    return await _mutate(
        request,
        f"idea_seed.update:{idea_seed_id}",
        lambda: {
            "idea_seed": control_center.update_idea_seed(
                idea_seed_id,
                body,
                actor=actor,
            )
        },
    )


async def handle_idea_seed_disposition(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    idea_seed_id = request.match_info["idea_seed_id"]
    return await _mutate(
        request,
        f"idea_seed.disposition:{idea_seed_id}",
        lambda: {
            "idea_seed": control_center.disposition_idea_seed(
                idea_seed_id,
                disposition=body.get("disposition"),
                reason=body.get("reason", ""),
                actor=body.get("actor", "human"),
            )
        },
    )


async def handle_idea_seed_plan(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    idea_seed_id = request.match_info["idea_seed_id"]
    body["idea_seed_id"] = idea_seed_id
    return await _mutate(
        request,
        f"idea_seed.plan:{idea_seed_id}",
        lambda: {"planning_job": control_center.create_planning_job(body)},
        status=202,
    )


async def handle_planning_jobs(request: web.Request) -> web.Response:
    try:
        if request.method == "GET":
            return web.json_response(
                {
                    "planning_jobs": control_center.list_planning_jobs(
                        request.query.get("project_id")
                    )
                }
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "planning_job.create",
        lambda: {"planning_job": control_center.create_planning_job(body)},
        status=202,
    )


async def handle_planning_job(request: web.Request) -> web.Response:
    job_id = request.match_info["job_id"]
    try:
        return web.json_response(
            {"planning_job": control_center.get_planning_job(job_id)}
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_cancel_planning_job(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    job_id = request.match_info["job_id"]
    return await _mutate(
        request,
        f"planning_job.cancel:{job_id}",
        lambda: {
            "planning_job": control_center.cancel_planning_job(
                job_id,
                actor=body.get("actor", "human"),
                reason=body.get("reason", ""),
            )
        },
    )


async def handle_retry_planning_job(request: web.Request) -> web.Response:
    job_id = request.match_info["job_id"]
    return await _mutate(
        request,
        f"planning_job.retry:{job_id}",
        lambda: {"planning_job": control_center.retry_planning_job(job_id)},
        status=202,
    )


async def handle_artifacts(request: web.Request) -> web.Response:
    try:
        if request.method == "GET":
            return web.json_response(
                {
                    "artifacts": control_center.list_artifacts(
                        request.query.get("project_id"),
                        request.query.get("campaign_id", ""),
                    )
                }
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        "artifact.create",
        lambda: {
            "artifact": control_center.save_artifact(
                body,
                actor=body.get("actor", "human"),
            )
        },
        status=201,
    )


async def handle_artifact(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            {"artifact": control_center.get_artifact(request.match_info["artifact_id"])}
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_campaign_profile(request: web.Request) -> web.Response:
    campaign_id = request.match_info["campaign_id"]
    try:
        if request.method == "GET":
            return web.json_response(
                {"profile": control_center.get_campaign_profile(campaign_id)}
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        f"campaign.profile:{campaign_id}",
        lambda: {
            "profile": control_center.update_campaign_profile(
                campaign_id,
                body,
                actor=body.get("actor", "human"),
            )
        },
    )


async def handle_add_planning_question(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    campaign_id = request.match_info["campaign_id"]
    return await _mutate(
        request,
        f"planning.question:{campaign_id}",
        lambda: {
            "question": control_center.add_planning_question(campaign_id, body)
        },
        status=201,
    )


async def handle_answer_planning_question(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    question_id = request.match_info["question_id"]

    def answer() -> Dict[str, Any]:
        question = control_center.answer_planning_question(question_id, body)
        result = {"question": question}
        planning_job_id = str(question.get("planning_job_id") or "").strip()
        if planning_job_id:
            result["planning_job"] = control_center.get_planning_job(
                planning_job_id
            )
        return result

    return await _mutate(
        request,
        f"planning.answer:{question_id}",
        answer,
    )


async def handle_candidate_conflicts(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    campaign_id = request.match_info["campaign_id"]
    candidate_id = request.match_info["candidate_id"]

    def update() -> Dict[str, Any]:
        control_center.set_candidate_conflicts(
            campaign_id,
            candidate_id,
            body.get("conflicts") or [],
        )
        return {"simulation": control_center.simulate_campaign(campaign_id)}

    return await _mutate(
        request,
        f"candidate.conflicts:{candidate_id}",
        update,
    )


async def handle_campaign_simulation(request: web.Request) -> web.Response:
    campaign_id = request.match_info["campaign_id"]
    try:
        return web.json_response(
            {
                "simulation": control_center.simulate_campaign(
                    campaign_id,
                    persist=False,
                )
            }
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_campaign_readiness(request: web.Request) -> web.Response:
    campaign_id = request.match_info["campaign_id"]
    try:
        return web.json_response(
            {
                "readiness": control_center.evaluate_campaign_readiness(
                    campaign_id,
                    persist=False,
                )
            }
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_plan_amendment(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    campaign_id = request.match_info["campaign_id"]
    return await _mutate(
        request,
        f"plan.amendment:{campaign_id}",
        lambda: control_center.start_plan_amendment(campaign_id, body),
        status=201,
    )


async def handle_plan_amendment_detail(request: web.Request) -> web.Response:
    amendment_id = request.match_info["amendment_id"]
    try:
        return web.json_response(
            {"amendment": control_center.get_plan_amendment(amendment_id)}
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_decide_plan_amendment(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    amendment_id = request.match_info["amendment_id"]

    def decide() -> Dict[str, Any]:
        amendment = control_center.decide_plan_amendment(
            amendment_id,
            decision=body.get("decision"),
            actor=body.get("actor", "human"),
            approval_sha=body.get("approval_sha", ""),
            reason=body.get("reason", ""),
            expected_from_version=body.get("expected_from_version"),
            expected_before_plan_sha256=body.get("expected_before_plan_sha256"),
            expected_target_plan_sha256=body.get("expected_target_plan_sha256"),
            expected_patch_sha256=body.get("expected_patch_sha256"),
        )
        return {
            "amendment": amendment,
            "planning_job": (
                control_center.get_planning_job(amendment["planning_job_id"])
                if amendment.get("planning_job_id")
                else None
            ),
        }

    return await _mutate(
        request,
        f"plan.amendment.decide:{amendment_id}",
        decide,
    )


async def handle_activate_campaign_wave(request: web.Request) -> web.Response:
    campaign_id = request.match_info["campaign_id"]
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        f"campaign.wave:{campaign_id}",
        lambda: {
            "wave": control_center.activate_ready_wave(
                campaign_id,
                actor=body.get("actor", "human"),
            )
        },
    )


async def handle_tasks(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            {
                "tasks": control_center.list_tasks(
                    project_id=request.query.get("project_id"),
                    campaign_id=request.query.get("campaign_id", ""),
                    status=request.query.get("status", ""),
                )
            }
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_task(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            {"task": control_center.get_task(request.match_info["task_id"])}
        )
    except ControlCenterError as exc:
        return _error(exc)


async def handle_resume_task_after_fix(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    task_id = request.match_info["task_id"]
    return await _mutate(
        request,
        f"task.resume_after_fix:{task_id}",
        lambda: {
            "task": control_center.resume_task_after_operator_fix(
                task_id,
                actor=body.get("actor", "human"),
                reason=body.get("reason"),
            )
        },
    )


async def handle_task_evidence(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    try:
        if request.method == "GET":
            return web.json_response(
                {"evidence_pack": control_center.evidence_pack(task_id)}
            )
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    return await _mutate(
        request,
        f"evidence.add:{task_id}",
        lambda: {
            "evidence": control_center.add_evidence(
                task_id,
                body,
                actor=body.get("actor", "human"),
            )
        },
        status=201,
    )


async def handle_evaluate_evidence(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    return await _mutate(
        request,
        f"evidence.evaluate:{task_id}",
        lambda: {
            "evidence_pack": control_center.evaluate_evidence_pack(task_id)
        },
    )


async def handle_create_finding(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    task_id = request.match_info["task_id"]
    return await _mutate(
        request,
        f"finding.create:{task_id}",
        lambda: {
            "finding": control_center.record_finding(
                task_id,
                body,
                actor=body.get("actor", "reviewer"),
            )
        },
        status=201,
    )


async def handle_resolve_finding(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    finding_id = request.match_info["finding_id"]
    return await _mutate(
        request,
        f"finding.resolve:{finding_id}",
        lambda: {
            "finding": control_center.resolve_finding(
                finding_id,
                resolution=body.get("resolution"),
                actor=body.get("actor", "human"),
            )
        },
    )


async def handle_task_approval(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    task_id = request.match_info["task_id"]
    return await _mutate(
        request,
        f"task.approval:{task_id}:{body.get('approval_type')}",
        lambda: {
            "approval": control_center.record_human_approval(
                task_id,
                approval_type=body.get("approval_type"),
                sha=body.get("sha"),
                decision=body.get("decision"),
                actor=body.get("actor", "human"),
                reason=body.get("reason", ""),
                evidence=body.get("evidence"),
            )
        },
        status=201,
    )


async def handle_reject_protected_path(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    task_id = request.match_info["task_id"]

    async def reject() -> Dict[str, Any]:
        return {
            "repair": await GitHubFlow(
                control_center
            ).reject_protected_path_for_repair(
                task_id,
                sha=body.get("sha"),
                actor=body.get("actor", "human"),
                reason=body.get("reason"),
            )
        }

    return await _mutate_async(
        request,
        f"protected_path.reject:{task_id}:{body.get('sha')}",
        reject,
    )


async def handle_create_deployment(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    task_id = request.match_info["task_id"]
    return await _mutate(
        request,
        f"deployment.create:{task_id}:{body.get('environment')}",
        lambda: {
            "deployment": control_center.create_deployment(
                task_id,
                body,
                actor=body.get("actor", "human"),
            )
        },
        status=201,
    )


async def handle_update_deployment(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    deployment_id = request.match_info["deployment_id"]
    return await _mutate(
        request,
        f"deployment.update:{deployment_id}:{body.get('status')}",
        lambda: {
            "deployment": control_center.update_deployment(
                deployment_id,
                status=body.get("status"),
                logs=body.get("logs"),
                health=body.get("health"),
                actor=body.get("actor", "deployer"),
            )
        },
    )


async def handle_rollback_deployment(request: web.Request) -> web.Response:
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)
    deployment_id = request.match_info["deployment_id"]
    return await _mutate(
        request,
        f"deployment.rollback:{deployment_id}",
        lambda: {
            "deployment": control_center.rollback_deployment(
                deployment_id,
                reason=body.get("reason"),
                actor=body.get("actor", "human"),
            )
        },
        status=201,
    )


async def handle_sync_pull_request(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]

    async def sync() -> Dict[str, Any]:
        return {"sync": await GitHubFlow(control_center).sync_pull_request(task_id)}

    return await _mutate_async(
        request,
        f"github.sync:{task_id}",
        sync,
    )


async def handle_merge_task(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    try:
        body = await _payload(request)
    except ControlCenterError as exc:
        return _error(exc)

    async def merge() -> Dict[str, Any]:
        return {
            "merge": await GitHubFlow(control_center).merge_task(
                task_id,
                actor=body.get("actor", "human"),
            )
        }

    return await _mutate_async(
        request,
        f"github.merge:{task_id}",
        merge,
    )


async def handle_executor_status(request: web.Request) -> web.Response:
    executor = request.app.get(CONTROL_EXECUTOR_KEY)
    return web.json_response(
        {"executor": executor.status() if executor else {"running": False}}
    )


async def handle_executor_tick(request: web.Request) -> web.Response:
    executor = request.app.get(CONTROL_EXECUTOR_KEY)
    if not executor:
        return web.json_response(
            {"error": "Executor ist nicht verfügbar.", "code": "executor_unavailable"},
            status=503,
        )
    await executor.run_once()
    return web.json_response({"executor": executor.status()})


async def handle_github_webhook(request: web.Request) -> web.Response:
    secret = config.github_webhook_secret
    if not secret:
        return web.json_response(
            {
                "error": "GitHub Webhook Secret ist nicht konfiguriert; Polling bleibt aktiv.",
                "code": "webhook_secret_not_configured",
            },
            status=503,
        )
    raw = await request.read()
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return web.json_response(
            {"error": "Ungültige Webhook-Signatur.", "code": "invalid_signature"},
            status=401,
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return web.json_response(
            {"error": "Ungültiger Webhook-Body.", "code": "invalid_json"},
            status=400,
        )
    delivery = request.headers.get("X-GitHub-Delivery", "")
    event_type = request.headers.get("X-GitHub-Event", "")
    try:
        event = control_center.record_webhook_event(
            delivery_id=delivery,
            event_type=event_type,
            payload=payload,
        )
        if event["deduplicated"] and event["status"] in {"processed", "ignored"}:
            return web.json_response({"webhook": event})
        task_id = control_center.resolve_webhook_task(
            event["repository"],
            payload,
        )
        if not task_id:
            event = control_center.finish_webhook_event(
                delivery,
                status="ignored",
            )
            return web.json_response({"webhook": event, "task_id": None})
        sync = await GitHubFlow(control_center).sync_pull_request(task_id)
        event = control_center.finish_webhook_event(
            delivery,
            status="processed",
        )
        return web.json_response(
            {"webhook": event, "task_id": task_id, "sync": sync}
        )
    except ControlCenterError as exc:
        if delivery:
            try:
                control_center.finish_webhook_event(
                    delivery,
                    status="failed",
                    error=str(exc),
                )
            except ControlCenterError:
                pass
        return _error(exc)
    except RuntimeError as exc:
        if delivery:
            try:
                control_center.finish_webhook_event(
                    delivery,
                    status="failed",
                    error=str(exc),
                )
            except ControlCenterError:
                pass
        return web.json_response(
            {"error": str(exc), "code": "github_error"},
            status=502,
        )
