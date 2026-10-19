import asyncio
import os
import re
import socket
from ipaddress import ip_address
from pathlib import Path
from aiohttp import web

from src.port_finder import find_active_ports
from src.app_keys import BACKEND_PORT_KEY, CODE_SERVER_PORT_KEY
from src.workspace_authorization import handle_workspace_authorization
from src.file_browser import browse_handler, file_preview_handler
from src.proxy_handlers import (
    docs_handler,
    stats_proxy_handler,
    proxy_handler,
    close_proxy_session
)
from src.desktop_ams import desktop_bundle_handler, native_rpc_handler


async def redirect_dashboard(request):
    """Route every dashboard entry point to the built React application."""
    from src.config import get_runtime_mode

    if get_runtime_mode() == "headless_linux":
        return web.HTTPFound('/dashboard/react/index.html#/api-logs')
    return web.HTTPFound('/dashboard/react/index.html#/studio')
from src.project_handlers import (
    handle_get_projects,
    handle_post_project,
    handle_reconcile_project_github,
    handle_delete_project,
    handle_project_removal_impact,
    handle_restore_project,
    handle_delete_project_github_repository,
    handle_get_github_repositories,
    handle_import_github_repository,
    handle_get_antigravity_projects,
    handle_get_integrity_workspaces,
    handle_link_integrity_workspace,
    handle_unlink_integrity_workspace,
    handle_create_antigravity_project,
    handle_link_github_repo,
    handle_get_issues,
    handle_post_issue,
    handle_get_issue_runs,
    handle_post_issue_run,
    handle_get_run,
    handle_post_cancel_run,
    handle_run_logs_sse,
    handle_get_lessons,
    handle_git_commit,
    handle_git_discard,
    handle_sync_issues,
    handle_github_status,
    handle_post_approve_run,
    handle_post_feedback_run,
    handle_delete_issue,
    handle_reset_issue,
    handle_project_preview,
    handle_stop_preview,
    handle_control_task_preview,
    handle_control_task_preview_status,
    handle_stop_control_task_preview,
    handle_run_followup,
    handle_orchestrator_chat,
    handle_get_subtasks,
    handle_post_subtask,
    handle_post_subtask_status,
    handle_delete_subtask,
    handle_generate_commit_msg,
    handle_get_antigravity_conversations,
    handle_get_integrity_chats,
    handle_create_integrity_chat,
    handle_get_integrity_chat_history,
    handle_open_antigravity_brain_directory,
    handle_delete_integrity_chat,
    handle_archive_antigravity_conversation,
    handle_restore_antigravity_conversation,
    handle_send_integrity_message,
    handle_open_integrity_chat_window,
    handle_get_antigravity_instances,
    handle_get_antigravity_workers,
    handle_close_antigravity_worker,
    handle_get_integrity_media,
    handle_get_integrity_quota,
    handle_get_integrity_models,
    handle_get_integrity_tokens,
    handle_stream_integrity_chat,
    handle_get_active_model,
    handle_set_active_model,
)
from src.custom_model_handlers import (
    handle_create_proxy_chat,
    handle_delete_custom_model,
    handle_list_custom_models,
    handle_save_custom_model,
    handle_send_proxy_message,
    handle_test_custom_model,
)
from src.codex_app_server import close_codex_manager
from src.codex_handlers import register_codex_routes
from src.orchestrator import Orchestrator
from src.chat_handlers import (
    handle_get_chats,
    handle_get_active_chat,
    handle_get_chat_snapshot,
    handle_stream_chat,
    handle_navigate_chat,
)
from src.voice_handlers import (
    handle_voice_start,
    handle_voice_stop,
    handle_voice_status,
    handle_dictation_start,
    handle_dictation_stop,
    handle_dictation_status,
    close_voice_session,
)
from src.control_center_handlers import (
    handle_activate_candidate,
    handle_activate_campaign_wave,
    handle_add_planning_question,
    handle_answer_planning_question,
    handle_approve_campaign,
    handle_artifact,
    handle_artifacts,
    handle_campaign_profile,
    handle_campaign_readiness,
    handle_campaign_simulation,
    handle_cancel_planning_job,
    handle_cancel_campaign,
    handle_cancel_work_order,
    handle_candidate_conflicts,
    handle_control_overview,
    handle_control_policy,
    handle_create_deployment,
    handle_create_campaign,
    handle_create_checkpoint,
    handle_create_finding,
    handle_create_pr_candidate,
    handle_create_recommendation,
    handle_decide_plan_amendment,
    handle_evaluate_evidence,
    handle_executor_status,
    handle_executor_tick,
    handle_github_webhook,
    handle_idea_seed,
    handle_idea_seed_disposition,
    handle_idea_seed_plan,
    handle_idea_seeds,
    handle_knowledge_chains,
    handle_merge_task,
    handle_plan_amendment,
    handle_plan_amendment_detail,
    handle_planning_job,
    handle_planning_jobs,
    handle_recommendation_disposition,
    handle_repository_policy,
    handle_retry_planning_job,
    handle_resolve_finding,
    handle_reject_protected_path,
    handle_resume_task_after_fix,
    handle_rollback_deployment,
    handle_sync_pull_request,
    handle_task,
    handle_task_approval,
    handle_task_evidence,
    handle_tasks,
    handle_update_deployment,
)
from src.scheduled_task_handlers import (
    handle_create_scheduled_task,
    handle_delete_scheduled_task,
    handle_disable_scheduled_task,
    handle_enable_scheduled_task,
    handle_get_scheduled_task_events,
    handle_list_scheduled_tasks,
    handle_restart_scheduled_task,
    handle_run_scheduled_task,
    handle_update_scheduled_task,
)
from src.project_runtime_handlers import (
    handle_capture_project_screenshot,
    handle_project_runtime,
    handle_project_screenshot_image,
    handle_save_project_runtime,
    handle_setup_project_runtime,
    handle_start_project_runtime,
    handle_stop_project_runtime,
)
from src.project_stack_handlers import handle_project_stack
from src.control_plane_handlers import (
    handle_control_operations,
    handle_control_plane_docs,
)
from src.control_plane_middleware import control_plane_middleware
from src.operation_coordinator import (
    CONTROL_COORDINATOR_KEY,
    OperationCoordinator,
)
from src.ide_server import (
    CODE_SERVER_PORT,
    code_server_status,
    discover_code_server,
    handle_ide_status,
    handle_open_conversation_ide,
    handle_open_project_ide,
    handle_open_control_task_ide,
    ensure_code_server,
)
from src.control_center import control_center
from src.system_overview import handle_system_overview
from src.control_center.executor_service import (
    CONTROL_EXECUTOR_KEY,
    ControlCenterExecutor,
)

# Constants
LISTEN_PORT = 8000
BACKEND_HOST = "127.0.0.1"
LISTEN_HOST = os.environ.get("ANTIGRAVITY_HUB_HOST", "127.0.0.1").strip() or "127.0.0.1"
BASE_DIR = Path(__file__).resolve().parent.parent
_HASHED_REACT_ASSET_RE = re.compile(
    r"^/dashboard/react/assets/[^/]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9.]+$"
)


def validate_listen_host(host: str) -> None:
    """Keep the privileged Hub UI on loopback; use authenticated Nginx remotely or Docker headless flags."""
    if (
        os.environ.get("ANTIGRAVITY_DOCKER", "").strip().lower() in ("1", "true", "yes")
        or os.environ.get("ANTIGRAVITY_HEADLESS_UI", "").strip().lower() in ("1", "true", "yes")
    ):
        return
    normalized = str(host or "").strip().lower()
    try:
        loopback = normalized == "localhost" or ip_address(normalized).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise RuntimeError(
            "The Anti-Gravity Hub UI must bind to loopback. Use the authenticated "
            "Nginx deployment profile for remote access."
        )


@web.middleware
async def dashboard_no_store_middleware(request, handler):
    """Cache immutable build assets while keeping all Hub shells fresh."""
    response = await handler(request)
    if (
        200 <= response.status < 400
        and _HASHED_REACT_ASSET_RE.fullmatch(request.path)
    ):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
    elif request.path == "/dashboard" or request.path.startswith("/dashboard/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def on_startup(app: web.Application) -> None:
    """Lifecycle handler to run on proxy application startup."""
    # Trigger crash recovery for active runs
    orchestrator = Orchestrator()
    await orchestrator.recover_active_runs()
    executor = ControlCenterExecutor(control_center)
    app[CONTROL_EXECUTOR_KEY] = executor
    await executor.start()


async def on_shutdown(app: web.Application) -> None:
    """Cleanup handler to run on proxy application shutdown."""
    executor = app.get(CONTROL_EXECUTOR_KEY)
    if executor:
        await executor.stop()
    await close_proxy_session()
    await close_voice_session()
    await asyncio.to_thread(close_codex_manager)


def create_app(backend_port=None) -> web.Application:
    """Build the Hub application without starting processes or binding a port."""
    app = web.Application(
        client_max_size=50 * 1024 * 1024,
        middlewares=[dashboard_no_store_middleware, control_plane_middleware],
    )

    # Store shared state in the app dict
    app[BACKEND_PORT_KEY] = backend_port
    app[CODE_SERVER_PORT_KEY] = CODE_SERVER_PORT
    app[CONTROL_COORDINATOR_KEY] = OperationCoordinator(
        audit_path=BASE_DIR / "logs" / "control_operations.jsonl",
    )

    # Project & Issue API
    app.router.add_get('/api/system/overview', handle_system_overview)
    app.router.add_post('/api/internal/workspace-authorization', handle_workspace_authorization)
    app.router.add_get('/api/projects', handle_get_projects)
    app.router.add_get('/api/projects/{id}/stack', handle_project_stack)
    app.router.add_post('/api/projects', handle_post_project)
    app.router.add_post(
        '/api/projects/{id}/github-bootstrap',
        handle_reconcile_project_github,
    )
    app.router.add_post('/api/projects/import', handle_import_github_repository)
    app.router.add_get('/api/projects/{id}/removal-impact', handle_project_removal_impact)
    app.router.add_delete('/api/projects/{id}', handle_delete_project)
    app.router.add_post('/api/projects/{id}/restore', handle_restore_project)
    app.router.add_delete(
        '/api/projects/{id}/github-repository',
        handle_delete_project_github_repository,
    )
    app.router.add_get('/api/antigravity/projects', handle_get_antigravity_projects)
    app.router.add_post('/api/projects/{id}/antigravity-link', handle_link_integrity_workspace)
    app.router.add_delete('/api/projects/{id}/antigravity-link', handle_unlink_integrity_workspace)
    app.router.add_post(
        '/api/projects/{id}/antigravity-project',
        handle_create_antigravity_project,
    )
    app.router.add_get('/api/integrity/workspaces', handle_get_integrity_workspaces)
    app.router.add_post('/api/projects/{id}/integrity-link', handle_link_integrity_workspace)
    app.router.add_delete('/api/projects/{id}/integrity-link', handle_unlink_integrity_workspace)
    app.router.add_post('/api/projects/{id}/github-link', handle_link_github_repo)

    app.router.add_get('/api/issues', handle_get_issues)
    app.router.add_post('/api/issues', handle_post_issue)
    app.router.add_delete('/api/issues/{id}', handle_delete_issue)
    app.router.add_post('/api/issues/{id}/reset', handle_reset_issue)
    app.router.add_get('/api/issues/{id}/runs', handle_get_issue_runs)
    app.router.add_post('/api/issues/{id}/runs', handle_post_issue_run)

    # Subtasks API
    app.router.add_get('/api/issues/{id}/subtasks', handle_get_subtasks)
    app.router.add_post('/api/issues/{id}/subtasks', handle_post_subtask)
    app.router.add_post('/api/subtasks/{subtask_id}/status', handle_post_subtask_status)
    app.router.add_delete('/api/subtasks/{subtask_id}', handle_delete_subtask)

    app.router.add_get('/api/runs/{id}', handle_get_run)
    app.router.add_post('/api/runs/{id}/cancel', handle_post_cancel_run)
    app.router.add_get('/api/runs/{id}/logs', handle_run_logs_sse)
    app.router.add_post('/api/runs/{id}/approve', handle_post_approve_run)
    app.router.add_post('/api/runs/{id}/feedback', handle_post_feedback_run)

    app.router.add_get('/api/lessons', handle_get_lessons)
    app.router.add_post('/api/git/commit', handle_git_commit)
    app.router.add_post('/api/git/discard', handle_git_discard)
    app.router.add_post('/api/git/generate-commit-msg', handle_generate_commit_msg)

    # Anti-Gravity Chats API (legacy /api/integrity aliases remain registered)
    app.router.add_get('/api/integrity/custom-models', handle_list_custom_models)
    app.router.add_post('/api/integrity/custom-models', handle_save_custom_model)
    app.router.add_delete('/api/integrity/custom-models/{custom_model_id}', handle_delete_custom_model)
    app.router.add_post('/api/integrity/custom-models/{custom_model_id}/test', handle_test_custom_model)
    app.router.add_post('/api/integrity/proxy-chats', handle_create_proxy_chat)
    app.router.add_get('/api/antigravity/custom-models', handle_list_custom_models)
    app.router.add_post('/api/antigravity/custom-models', handle_save_custom_model)
    app.router.add_delete('/api/antigravity/custom-models/{custom_model_id}', handle_delete_custom_model)
    app.router.add_post('/api/antigravity/custom-models/{custom_model_id}/test', handle_test_custom_model)
    app.router.add_post('/api/antigravity/proxy-chats', handle_create_proxy_chat)
    register_codex_routes(app)
    app.router.add_get('/api/antigravity/chats', handle_get_integrity_chats)
    app.router.add_get('/api/antigravity/conversations', handle_get_antigravity_conversations)
    app.router.add_post('/api/antigravity/chats', handle_create_integrity_chat)
    app.router.add_get('/api/antigravity/chats/{convo_id}/history', handle_get_integrity_chat_history)
    app.router.add_post('/api/antigravity/chats/{convo_id}/brain/open', handle_open_antigravity_brain_directory)
    app.router.add_delete('/api/antigravity/chats/{convo_id}', handle_delete_integrity_chat)
    app.router.add_post('/api/antigravity/chats/{convo_id}/archive', handle_archive_antigravity_conversation)
    app.router.add_post('/api/antigravity/chats/{convo_id}/restore', handle_restore_antigravity_conversation)
    app.router.add_post('/api/antigravity/chats/{convo_id}/message', handle_send_integrity_message)
    app.router.add_post('/api/antigravity/chats/{convo_id}/proxy-message', handle_send_proxy_message)
    app.router.add_post('/api/antigravity/chats/{convo_id}/window', handle_open_integrity_chat_window)
    app.router.add_get('/api/antigravity/instances', handle_get_antigravity_instances)
    app.router.add_get('/api/antigravity/workers', handle_get_antigravity_workers)
    app.router.add_delete('/api/antigravity/workers/{target_id}', handle_close_antigravity_worker)
    app.router.add_get('/api/antigravity/chats/{convo_id}/stream', handle_stream_integrity_chat)
    app.router.add_get('/api/antigravity/quota', handle_get_integrity_quota)
    app.router.add_get('/api/antigravity/models', handle_get_integrity_models)
    app.router.add_get('/api/antigravity/tokens/{convo_id}', handle_get_integrity_tokens)
    app.router.add_get('/api/antigravity/active-model', handle_get_active_model)
    app.router.add_post('/api/antigravity/active-model', handle_set_active_model)
    app.router.add_get('/api/antigravity/media', handle_get_integrity_media)
    app.router.add_get('/api/integrity/chats', handle_get_integrity_chats)
    app.router.add_get('/api/integrity/conversations', handle_get_antigravity_conversations)
    app.router.add_post('/api/integrity/chats', handle_create_integrity_chat)
    app.router.add_get('/api/integrity/chats/{convo_id}/history', handle_get_integrity_chat_history)
    app.router.add_post('/api/integrity/chats/{convo_id}/brain/open', handle_open_antigravity_brain_directory)
    app.router.add_delete('/api/integrity/chats/{convo_id}', handle_delete_integrity_chat)
    app.router.add_post('/api/integrity/chats/{convo_id}/archive', handle_archive_antigravity_conversation)
    app.router.add_post('/api/integrity/chats/{convo_id}/restore', handle_restore_antigravity_conversation)
    app.router.add_post('/api/integrity/chats/{convo_id}/message', handle_send_integrity_message)
    app.router.add_post('/api/integrity/chats/{convo_id}/proxy-message', handle_send_proxy_message)
    app.router.add_post('/api/integrity/chats/{convo_id}/window', handle_open_integrity_chat_window)
    app.router.add_get('/api/integrity/quota', handle_get_integrity_quota)
    app.router.add_get('/api/integrity/models', handle_get_integrity_models)
    app.router.add_get('/api/integrity/tokens/{convo_id}', handle_get_integrity_tokens)
    app.router.add_get('/api/integrity/chats/{convo_id}/stream', handle_stream_integrity_chat)
    app.router.add_get('/api/integrity/active-model', handle_get_active_model)
    app.router.add_post('/api/integrity/active-model', handle_set_active_model)
    app.router.add_get('/api/integrity/media', handle_get_integrity_media)

    # Native Anti-Gravity scheduled tasks (Sidecars)
    app.router.add_get(
        '/api/antigravity/scheduled-tasks',
        handle_list_scheduled_tasks,
    )
    app.router.add_post(
        '/api/antigravity/scheduled-tasks',
        handle_create_scheduled_task,
    )
    app.router.add_patch(
        '/api/antigravity/scheduled-tasks/{task_id}',
        handle_update_scheduled_task,
    )
    app.router.add_post(
        '/api/antigravity/scheduled-tasks/{task_id}/enable',
        handle_enable_scheduled_task,
    )
    app.router.add_post(
        '/api/antigravity/scheduled-tasks/{task_id}/disable',
        handle_disable_scheduled_task,
    )
    app.router.add_post(
        '/api/antigravity/scheduled-tasks/{task_id}/run',
        handle_run_scheduled_task,
    )
    app.router.add_post(
        '/api/antigravity/scheduled-tasks/{task_id}/restart',
        handle_restart_scheduled_task,
    )
    app.router.add_get(
        '/api/antigravity/scheduled-tasks/{task_id}/events',
        handle_get_scheduled_task_events,
    )
    app.router.add_delete(
        '/api/antigravity/scheduled-tasks/{task_id}',
        handle_delete_scheduled_task,
    )

    # GitHub Integration API
    app.router.add_get('/api/projects/{id}/sync', handle_sync_issues)
    app.router.add_get('/api/github/status', handle_github_status)
    app.router.add_get('/api/github/repos', handle_get_github_repositories)

    # Preview & Follow-Up API
    app.router.add_post('/api/projects/{id}/preview', handle_project_preview)
    app.router.add_post('/api/projects/{id}/preview/stop', handle_stop_preview)
    app.router.add_get('/api/projects/{id}/runtime', handle_project_runtime)
    app.router.add_put('/api/projects/{id}/runtime', handle_save_project_runtime)
    app.router.add_post('/api/projects/{id}/runtime/{service}/start', handle_start_project_runtime)
    app.router.add_post('/api/projects/{id}/runtime/{service}/setup', handle_setup_project_runtime)
    app.router.add_post('/api/projects/{id}/runtime/{service}/stop', handle_stop_project_runtime)
    app.router.add_post('/api/projects/{id}/runtime/screenshot', handle_capture_project_screenshot)
    app.router.add_get('/api/projects/{id}/runtime/screenshot/image', handle_project_screenshot_image)
    app.router.add_get(
        '/api/control-center/tasks/{task_id}/preview',
        handle_control_task_preview_status,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/preview',
        handle_control_task_preview,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/preview/stop',
        handle_stop_control_task_preview,
    )
    app.router.add_post('/api/runs/{id}/followup', handle_run_followup)

    # Safe local browser IDE. Workspace paths are always resolved server-side.
    app.router.add_get('/api/ide/status', handle_ide_status)
    app.router.add_post('/api/projects/{id}/ide/open', handle_open_project_ide)
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/ide/open',
        handle_open_control_task_ide,
    )
    app.router.add_post(
        '/api/antigravity/chats/{convo_id}/ide/open',
        handle_open_conversation_ide,
    )

    # Orchestrator Chat API
    app.router.add_post('/api/orchestrator/chat', handle_orchestrator_chat)

    # Engineering Control Plane: planning, execution, evidence, and delivery
    app.router.add_get('/api/control-center/overview', handle_control_overview)
    app.router.add_get(
        '/api/control-center/knowledge-chains',
        handle_knowledge_chains,
    )
    app.router.add_post('/api/control-center/policy', handle_control_policy)
    app.router.add_get(
        '/api/control-center/projects/{project_id}/policy',
        handle_repository_policy,
    )
    app.router.add_put(
        '/api/control-center/projects/{project_id}/policy',
        handle_repository_policy,
    )
    app.router.add_get('/api/control-center/idea-seeds', handle_idea_seeds)
    app.router.add_post('/api/control-center/idea-seeds', handle_idea_seeds)
    app.router.add_get(
        '/api/control-center/idea-seeds/{idea_seed_id}',
        handle_idea_seed,
    )
    app.router.add_patch(
        '/api/control-center/idea-seeds/{idea_seed_id}',
        handle_idea_seed,
    )
    app.router.add_post(
        '/api/control-center/idea-seeds/{idea_seed_id}/disposition',
        handle_idea_seed_disposition,
    )
    app.router.add_post(
        '/api/control-center/idea-seeds/{idea_seed_id}/plan',
        handle_idea_seed_plan,
    )
    app.router.add_get('/api/control-center/planning-jobs', handle_planning_jobs)
    app.router.add_post('/api/control-center/planning-jobs', handle_planning_jobs)
    app.router.add_get(
        '/api/control-center/planning-jobs/{job_id}',
        handle_planning_job,
    )
    app.router.add_post(
        '/api/control-center/planning-jobs/{job_id}/cancel',
        handle_cancel_planning_job,
    )
    app.router.add_post(
        '/api/control-center/planning-jobs/{job_id}/retry',
        handle_retry_planning_job,
    )
    app.router.add_get('/api/control-center/artifacts', handle_artifacts)
    app.router.add_post('/api/control-center/artifacts', handle_artifacts)
    app.router.add_get(
        '/api/control-center/artifacts/{artifact_id}',
        handle_artifact,
    )
    app.router.add_post('/api/control-center/recommendations', handle_create_recommendation)
    app.router.add_post(
        '/api/control-center/recommendations/{recommendation_id}/disposition',
        handle_recommendation_disposition,
    )
    app.router.add_post('/api/control-center/campaigns', handle_create_campaign)
    app.router.add_get(
        '/api/control-center/campaigns/{campaign_id}/profile',
        handle_campaign_profile,
    )
    app.router.add_put(
        '/api/control-center/campaigns/{campaign_id}/profile',
        handle_campaign_profile,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/questions',
        handle_add_planning_question,
    )
    app.router.add_post(
        '/api/control-center/questions/{question_id}/answer',
        handle_answer_planning_question,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/pr-candidates',
        handle_create_pr_candidate,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/pr-candidates/{candidate_id}/conflicts',
        handle_candidate_conflicts,
    )
    app.router.add_get(
        '/api/control-center/campaigns/{campaign_id}/simulation',
        handle_campaign_simulation,
    )
    app.router.add_get(
        '/api/control-center/campaigns/{campaign_id}/readiness',
        handle_campaign_readiness,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/amendments',
        handle_plan_amendment,
    )
    app.router.add_get(
        '/api/control-center/amendments/{amendment_id}',
        handle_plan_amendment_detail,
    )
    app.router.add_post(
        '/api/control-center/amendments/{amendment_id}/decision',
        handle_decide_plan_amendment,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/approve',
        handle_approve_campaign,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/cancel',
        handle_cancel_campaign,
    )
    app.router.add_options(
        '/api/control-center/campaigns/{campaign_id}/cancel',
        handle_cancel_campaign,
    )
    app.router.add_post(
        '/api/control-center/campaigns/{campaign_id}/activate-wave',
        handle_activate_campaign_wave,
    )
    app.router.add_post(
        '/api/control-center/pr-candidates/{candidate_id}/activate',
        handle_activate_candidate,
    )
    app.router.add_post(
        '/api/control-center/work-orders/{work_order_id}/cancel',
        handle_cancel_work_order,
    )
    app.router.add_post('/api/control-center/checkpoints', handle_create_checkpoint)
    app.router.add_get('/api/control-center/tasks', handle_tasks)
    app.router.add_get('/api/control-center/tasks/{task_id}', handle_task)
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/resume-after-fix',
        handle_resume_task_after_fix,
    )
    app.router.add_get(
        '/api/control-center/tasks/{task_id}/evidence',
        handle_task_evidence,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/evidence',
        handle_task_evidence,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/evidence/evaluate',
        handle_evaluate_evidence,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/findings',
        handle_create_finding,
    )
    app.router.add_post(
        '/api/control-center/findings/{finding_id}/resolve',
        handle_resolve_finding,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/approvals',
        handle_task_approval,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/protected-path/reject',
        handle_reject_protected_path,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/github/sync',
        handle_sync_pull_request,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/github/merge',
        handle_merge_task,
    )
    app.router.add_post(
        '/api/control-center/tasks/{task_id}/deployments',
        handle_create_deployment,
    )
    app.router.add_patch(
        '/api/control-center/deployments/{deployment_id}',
        handle_update_deployment,
    )
    app.router.add_post(
        '/api/control-center/deployments/{deployment_id}/rollback',
        handle_rollback_deployment,
    )
    app.router.add_get(
        '/api/control-center/executor',
        handle_executor_status,
    )
    app.router.add_post(
        '/api/control-center/executor/tick',
        handle_executor_tick,
    )
    app.router.add_post(
        '/api/control-center/github/webhook',
        handle_github_webhook,
    )

    # Conflict-aware operation queue, audit, and canonical operator manual
    app.router.add_get('/api/control-plane/operations', handle_control_operations)
    app.router.add_get('/api/control-plane/docs', handle_control_plane_docs)
    app.router.add_get(
        '/api/control-plane/docs/{document_id}',
        handle_control_plane_docs,
    )

    # Chat Reading & Streaming API
    # NOTE: /api/chats/active MUST be registered before /api/chats/{chat_id}
    # so that the literal 'active' path is not captured by the parameterised route.
    app.router.add_get('/api/chats', handle_get_chats)
    app.router.add_get('/api/chats/active', handle_get_active_chat)
    app.router.add_get('/api/chats/{chat_id}/stream', handle_stream_chat)
    app.router.add_get('/api/chats/{chat_id}', handle_get_chat_snapshot)
    app.router.add_post('/api/chats/{chat_id}/navigate', handle_navigate_chat)

    # Voice Bridge API
    app.router.add_post('/api/voice/start', handle_voice_start)
    app.router.add_post('/api/voice/stop', handle_voice_stop)
    app.router.add_get('/api/voice/status', handle_voice_status)
    app.router.add_post('/api/voice/dictation/start', handle_dictation_start)
    app.router.add_post('/api/voice/dictation/stop', handle_dictation_stop)
    app.router.add_get('/api/voice/dictation/status', handle_dictation_status)

    # Static Dashboard setup
    dashboard_path = BASE_DIR / "dashboard"
    dashboard_path.mkdir(parents=True, exist_ok=True)

    # React is the default dashboard. The original UI remains available as a
    # reversible fallback while the new surface proves itself in daily use.
    app.router.add_get('/dashboard', redirect_dashboard)
    app.router.add_get('/dashboard/', redirect_dashboard)
    app.router.add_get('/dashboard/react', redirect_dashboard)
    app.router.add_get('/dashboard/react/', redirect_dashboard)

    async def serve_legacy_dashboard(request):
        return web.FileResponse(str(dashboard_path / "index.html"))
    app.router.add_get('/dashboard/legacy', serve_legacy_dashboard)
    app.router.add_get('/dashboard/legacy/', serve_legacy_dashboard)

    app.router.add_static('/dashboard/', path=str(dashboard_path), show_index=False)

    # Routing falling back to proxying to the main Tauri UI
    app.router.add_get('/docs/control-plane', handle_control_plane_docs)
    app.router.add_get(
        '/docs/control-plane/{document_id}',
        handle_control_plane_docs,
    )
    app.router.add_get('/docs', docs_handler)
    app.router.add_get('/docs/', docs_handler)
    app.router.add_route('*', '/api/stats', stats_proxy_handler)
    app.router.add_get('/ams/desktop.js', desktop_bundle_handler)
    app.router.add_route('*', '/api/desktop/ams/{operation}', native_rpc_handler)
    app.router.add_get('/api/browse', browse_handler)
    app.router.add_get('/api/files/preview', file_preview_handler)

    from src.api_handlers import (
        api_audit_log_detail_handler,
        api_audit_logs_clear_handler,
        api_audit_logs_export_handler,
        api_audit_logs_list_handler,
        api_audit_logs_stats_handler,
        api_audit_reverts_list_handler,
        api_engine_mode_handler,
        revert_chat_handler,
    )
    app.router.add_get('/api/logs/stats', api_audit_logs_stats_handler)
    app.router.add_get('/api/logs/reverts', api_audit_reverts_list_handler)
    app.router.add_get('/api/logs/export', api_audit_logs_export_handler)
    app.router.add_get('/api/logs', api_audit_logs_list_handler)
    app.router.add_delete('/api/logs', api_audit_logs_clear_handler)
    app.router.add_get('/api/logs/{req_id}', api_audit_log_detail_handler)
    app.router.add_get('/api/engine-mode', api_engine_mode_handler)
    app.router.add_post('/api/engine-mode', api_engine_mode_handler)
    app.router.add_post('/v1/chat/revert', revert_chat_handler)

    async def hub_health_handler(request):
        from src.config import config, get_runtime_mode

        runtime_mode = get_runtime_mode()
        backend = request.app.get(BACKEND_PORT_KEY)
        connected = False
        probe_port = backend or (config.api_bridge_port if runtime_mode == "headless_linux" else None)
        if probe_port:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.2)
            try:
                connected = probe.connect_ex((BACKEND_HOST, probe_port)) == 0
            finally:
                probe.close()
        control_status = await request.app[CONTROL_COORDINATOR_KEY].status()
        return web.json_response({
            "status": "ok",
            "hub": "healthy",
            "runtime_mode": runtime_mode,
            "antigravity_backend": {"connected": connected, "port": probe_port},
            "web_ide": await asyncio.to_thread(code_server_status),
            "control_plane": {
                "mode": control_status["policy"]["mode"],
                **control_status["counts"],
            },
        })

    app.router.add_get('/health', hub_health_handler)
    app.router.add_route('*', '/{path_info:.*}', proxy_handler)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


def main() -> None:
    """Discover local services and launch the reverse proxy."""
    validate_listen_host(LISTEN_HOST)
    _, backend_port = find_active_ports()
    if not backend_port:
        print("[HUB] Anti-Gravity backend is not running yet; dashboard stays available.", flush=True)

    cs_path = discover_code_server()
    ide_status = ensure_code_server(timeout_seconds=3.0)
    if ide_status.get("running"):
        print(f"[IDE] code-server ready on :{CODE_SERVER_PORT}", flush=True)
    elif cs_path:
        print(f"[IDE] code-server unavailable: {ide_status.get('error', 'unknown error')}", flush=True)
    else:
        print("[IDE] code-server not installed (Web IDE API stays available)", flush=True)
    app = create_app(backend_port)

    print(f"\n{'='*55}", flush=True)
    print("  Antigravity UI (Browser) v5 - Refactored", flush=True)
    display_host = "127.0.0.1" if LISTEN_HOST in {"0.0.0.0", "::"} else LISTEN_HOST
    print(f"  --> http://{display_host}:{LISTEN_PORT}/dashboard <--", flush=True)
    backend_label = f"https://{BACKEND_HOST}:{backend_port}" if backend_port else "disconnected"
    print(f"  Backend: {backend_label}", flush=True)
    print(f"  IDE:     http://127.0.0.1:{CODE_SERVER_PORT}", flush=True)
    print(f"  Docs:    http://127.0.0.1:{LISTEN_PORT}/docs", flush=True)
    print("  Stats:   /api/stats (proxy -> :8001)", flush=True)
    print("  Files:   /api/browse?path=...", flush=True)
    print(f"{'='*55}\n", flush=True)

    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, print=None)


if __name__ == "__main__":
    main()
