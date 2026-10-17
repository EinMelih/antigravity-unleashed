import asyncio
import base64
import binascii
import hashlib
import json
import os
import subprocess
import sys
import re
import time
import uuid
from aiohttp import web
from typing import Dict, Any, List
from pathlib import Path

from src.database import db
from src.config import config
from src.github_client import GitHubClient
from src.project_manager import ProjectManager, git_diff, git_commit, git_discard_changes
from src.orchestrator import Orchestrator
from src.local_admin_security import local_cors_response
from src.project_archiving import ProjectArchiver, ProjectNotFoundError


MAX_CHAT_ATTACHMENTS = 5
MAX_CHAT_ATTACHMENT_BYTES = 20 * 1024 * 1024
ALLOWED_CHAT_ATTACHMENT_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
ANTIGRAVITY_CONVERSATION_ID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-"
    r"[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
    re.IGNORECASE,
)
_LIVE_SIDEBAR_CACHE: Dict[str, Any] = {
    "updated_at": 0.0,
    "payload": None,
}


def _is_technical_sidebar_title(title: str, conversation_id: str) -> bool:
    """Recognize the old bridge's non-authoritative ``Chat <id8>`` label."""
    match = re.fullmatch(r"Chat\s+([a-f0-9]{8})", title, re.IGNORECASE)
    return bool(
        match
        and str(conversation_id).lower().startswith(match.group(1).lower())
    )


def _is_catalog_title_with_sidebar_age_badge(
    sidebar_title: str,
    catalog_title: str,
) -> bool:
    """Detect a canonical title polluted by Anti-Gravity's relative-age badge."""
    if not catalog_title or not sidebar_title.startswith(catalog_title):
        return False
    suffix = sidebar_title[len(catalog_title):].strip()
    return bool(re.fullmatch(r"\d+(?:mo|s|m|h|d|w|y)", suffix, re.IGNORECASE))


async def _get_live_antigravity_sidebar_snapshot() -> Dict[str, Any]:
    """Read the canonical visible chat list from the running desktop app."""
    now = time.monotonic()
    cached = _LIVE_SIDEBAR_CACHE.get("payload")
    cache_age = now - float(_LIVE_SIDEBAR_CACHE.get("updated_at") or 0)
    if isinstance(cached, dict) and cache_age < 1.0:
        return cached

    from src.parallel_cdp import ParallelCDPManager

    manager = ParallelCDPManager()
    try:
        port = await manager.get_devtools_port()
        targets = await manager.get_all_page_targets(port)
        candidates = []
        for target in targets:
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                continue
            client = await manager.get_client_for_target(ws_url)
            payload = await client.get_chat_list()
            if isinstance(payload, dict) and not payload.get("error"):
                candidates.append({
                    **payload,
                    "target_id": target.get("id"),
                })
        if not candidates:
            raise RuntimeError("No readable Anti-Gravity sidebar was found.")
        complete_candidates = [
            item for item in candidates if item.get("complete") is True
        ]
        scan_complete = bool(complete_candidates)
        incomplete_error = None
        if scan_complete:
            payload = max(
                complete_candidates,
                key=lambda item: int(item.get("count") or 0),
            )
        else:
            largest_partial = max(
                (int(item.get("count") or 0) for item in candidates),
                default=0,
            )
            incomplete_error = (
                "Anti-Gravity sidebar scan was incomplete "
                f"({largest_partial} chat(s) materialized); retrying is required."
            )
            if not isinstance(cached, dict):
                raise RuntimeError(incomplete_error)
            payload = max(
                candidates,
                key=lambda item: int(item.get("count") or 0),
            )

        chats = []
        seen = set()
        for position, item in enumerate(payload.get("chats") or []):
            if not isinstance(item, dict):
                continue
            convo_id = str(item.get("id") or "").strip().lower()
            if (
                convo_id in seen
                or not ANTIGRAVITY_CONVERSATION_ID_RE.fullmatch(convo_id)
            ):
                continue
            seen.add(convo_id)
            chats.append({
                "id": convo_id,
                "title": str(item.get("title") or "").strip(),
                "active": bool(item.get("active")),
                "project_chat": bool(item.get("project_chat")),
                "position": position,
            })

        # A collapsed project temporarily removes its conversation rows from
        # the virtualized DOM. Keep previously discovered rows in the sidebar
        # snapshot; the current catalog reconciliation below remains the
        # authority for deletion and archive state.
        if isinstance(cached, dict):
            previous_by_id = {
                str(item.get("id") or "").strip().lower(): item
                for item in cached.get("chats") or []
                if isinstance(item, dict)
            }
            merged_chats = []
            merged_ids = set()
            for fresh in chats:
                convo_id = fresh["id"]
                previous = previous_by_id.get(convo_id)
                if previous:
                    merged = {**previous, **fresh}
                    if not fresh.get("title") and previous.get("title"):
                        merged["title"] = previous["title"]
                else:
                    merged = fresh
                merged_chats.append(merged)
                merged_ids.add(convo_id)

            for previous in cached.get("chats") or []:
                if not isinstance(previous, dict):
                    continue
                convo_id = str(previous.get("id") or "").strip().lower()
                if (
                    convo_id in merged_ids
                    or not ANTIGRAVITY_CONVERSATION_ID_RE.fullmatch(convo_id)
                ):
                    continue
                merged_chats.append({**previous, "active": False})
                merged_ids.add(convo_id)
            chats = merged_chats

        for position, item in enumerate(chats):
            item["position"] = position
        snapshot = {
            "available": True,
            "stale": not scan_complete,
            "complete": scan_complete,
            "chats": chats,
            "active_id": payload.get("active_id"),
            "count": len(chats),
            "target_id": payload.get("target_id"),
            "error": incomplete_error,
        }
        _LIVE_SIDEBAR_CACHE["updated_at"] = now
        _LIVE_SIDEBAR_CACHE["payload"] = snapshot
        return snapshot
    except Exception as error:
        if isinstance(cached, dict) and cache_age < 30.0:
            return {
                **cached,
                "stale": True,
                "error": str(error),
            }
        return {
            "available": False,
            "stale": False,
            "chats": [],
            "active_id": None,
            "count": 0,
            "error": str(error),
        }
    finally:
        await manager.close_all()


def _invalidate_live_sidebar_cache() -> None:
    _LIVE_SIDEBAR_CACHE["updated_at"] = 0.0
    _LIVE_SIDEBAR_CACHE["payload"] = None


def _deleted_managed_conversation_ids() -> set[str]:
    return {
        str(item.get("conversation_id") or "").lower()
        for item in db.list_managed_antigravity_conversations(state="deleted")
        if item.get("conversation_id")
    }


def _save_chat_attachments(
    attachments: Any,
    *,
    storage_key: str,
) -> List[Dict[str, Any]]:
    """Validate data-URL image attachments and persist them for native upload."""
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ValueError("attachments must be a list")
    if len(attachments) > MAX_CHAT_ATTACHMENTS:
        raise ValueError(
            f"A maximum of {MAX_CHAT_ATTACHMENTS} images can be attached."
        )

    safe_storage_key = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(storage_key or "pending"),
    )[:100]
    media_dir = (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "brain"
        / safe_storage_key
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Dict[str, Any]] = []

    try:
        for index, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                raise ValueError(
                    f"Attachment #{index + 1} must be an object."
                )

            raw_name = str(attachment.get("name") or "").strip()
            file_name = Path(raw_name).name
            mime_type = str(attachment.get("type") or "").strip().lower()
            data_value = attachment.get("data")
            if (
                not file_name
                or mime_type not in ALLOWED_CHAT_ATTACHMENT_TYPES
                or not isinstance(data_value, str)
                or not data_value.strip()
            ):
                raise ValueError(
                    f"Attachment #{index + 1} is incomplete or unsupported."
                )

            encoded = data_value.strip()
            if encoded.startswith("data:"):
                header, separator, encoded = encoded.partition(",")
                if not separator or ";base64" not in header.lower():
                    raise ValueError(
                        f"Attachment {file_name!r} is not valid base64 data."
                    )
                declared_type = header[5:].split(";", 1)[0].strip().lower()
                if declared_type and declared_type != mime_type:
                    raise ValueError(
                        f"Attachment {file_name!r} has conflicting MIME types."
                    )

            try:
                file_data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError(
                    f"Attachment {file_name!r} contains invalid base64 data."
                ) from error
            if not file_data:
                raise ValueError(f"Attachment {file_name!r} is empty.")
            if len(file_data) > MAX_CHAT_ATTACHMENT_BYTES:
                raise ValueError(
                    f"Attachment {file_name!r} exceeds the 20 MiB limit."
                )

            upload_dir = (
                media_dir
                / f".hub_upload_{time.time_ns()}_{uuid.uuid4().hex}"
                / str(index)
            )
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file_name
            file_path.write_bytes(file_data)
            saved.append(
                {
                    "mime_type": mime_type,
                    "file_name": file_name,
                    "file_path": str(file_path.resolve()).replace("\\", "/"),
                    "file_data": file_data,
                }
            )
    except Exception:
        for item in saved:
            try:
                Path(item["file_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return saved


# ============================================================
# API Handlers for Projects
# ============================================================

async def handle_get_projects(request: web.Request) -> web.Response:
    """GET /api/projects — List all registered projects."""
    try:
        include_archived = str(
            request.query.get("include_archived") or ""
        ).strip().lower() in {"1", "true", "yes"}
        projects = await asyncio.to_thread(
            ProjectManager.get_projects,
            include_archived=include_archived,
        )
        return web.json_response({"projects": projects})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_project(request: web.Request) -> web.Response:
    """POST /api/projects — Register a new project (directory auto-created)."""
    try:
        body = await request.json()
        name = body.get("name")
        test_command = body.get("test_command", "python -m unittest")
        custom_path = body.get("path")
        existing_github_url = body.get("github_url")
        create_github = body.get("create_github", True) is not False
        github_visibility = str(body.get("github_visibility") or "").strip().lower()
        github_private = None
        if github_visibility in {"private", "public"}:
            github_private = github_visibility == "private"

        if not name:
            return web.json_response({"error": "name is required"}, status=400)

        project = await ProjectManager.register_project(
            name,
            test_command,
            custom_path=custom_path,
            existing_github_url=existing_github_url,
            create_github=create_github,
            github_private=github_private,
        )
        return web.json_response(project, status=201)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_reconcile_project_github(request: web.Request) -> web.Response:
    """POST /api/projects/{id}/github-bootstrap — Repair and verify GitHub setup."""
    try:
        project_id = int(request.match_info["id"])
        project = await ProjectManager.reconcile_github_repository(project_id)
        return web.json_response(project)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)


async def handle_delete_project(request: web.Request) -> web.Response:
    """DELETE /api/projects/{id} — Reversibly remove a project from the Hub."""

    async def archive(inner_request: web.Request) -> web.Response:
        try:
            project_id = int(inner_request.match_info["id"])
            body: Dict[str, Any] = {}
            if inner_request.can_read_body:
                body = await inner_request.json()
                if not isinstance(body, dict):
                    raise ValueError("JSON body must be an object")
            mode = str(body.get("mode") or "hub_only").strip().lower()
            if mode != "hub_only":
                return web.json_response(
                    {
                        "error": "Only the reversible hub_only mode is supported.",
                        "code": "unsupported_project_removal_mode",
                    },
                    status=400,
                )
            if body.get("delete_remote_repository") is True:
                return web.json_response(
                    {
                        "error": (
                            "Remote repository deletion is not part of Hub project removal."
                        ),
                        "code": "remote_repository_deletion_not_supported",
                        "remote_action_performed": False,
                        "requirements": {
                            "separate_endpoint": True,
                            "explicit_repository_identity": True,
                            "separate_confirmation": True,
                            "required_permission": "delete_repo",
                        },
                    },
                    status=409,
                )
            result = await asyncio.to_thread(ProjectArchiver(db).archive, project_id)
            return web.json_response(result)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)
        except ProjectNotFoundError:
            return web.json_response({"error": "Project not found"}, status=404)
        except Exception as error:
            return web.json_response({"error": str(error)}, status=500)

    return await local_cors_response(request, archive, methods="DELETE")


async def handle_project_removal_impact(request: web.Request) -> web.Response:
    """GET /api/projects/{id}/removal-impact — Preview retained Hub data."""
    try:
        project_id = int(request.match_info["id"])
        result = await asyncio.to_thread(ProjectArchiver(db).impact, project_id)
        return web.json_response(result, headers={"Cache-Control": "no-store"})
    except (TypeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except ProjectNotFoundError:
        return web.json_response({"error": "Project not found"}, status=404)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_restore_project(request: web.Request) -> web.Response:
    """POST /api/projects/{id}/restore — Restore a soft-archived project."""

    async def restore(inner_request: web.Request) -> web.Response:
        try:
            project_id = int(inner_request.match_info["id"])
            result = await asyncio.to_thread(ProjectArchiver(db).restore, project_id)
            return web.json_response(result)
        except (TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)
        except ProjectNotFoundError:
            return web.json_response({"error": "Project not found"}, status=404)
        except Exception as error:
            return web.json_response({"error": str(error)}, status=500)

    return await local_cors_response(request, restore, methods="POST")


async def handle_delete_project_github_repository(request: web.Request) -> web.Response:
    """Delete one explicitly confirmed linked GitHub repository only."""

    async def delete_remote(inner_request: web.Request) -> web.Response:
        try:
            project_id = int(inner_request.match_info["id"])
            project = db.get_project(project_id, include_archived=True)
            if not project:
                return web.json_response({"error": "Project not found"}, status=404)
            try:
                body = await inner_request.json()
            except (json.JSONDecodeError, TypeError):
                return web.json_response({"error": "A JSON object is required."}, status=400)
            if not isinstance(body, dict) or body.get("confirm") is not True:
                return web.json_response(
                    {"error": "Explicit GitHub deletion confirmation is required.", "code": "confirmation_required"},
                    status=400,
                )
            owner = str(project.get("github_owner") or "").strip()
            repo = str(project.get("github_repo") or "").strip()
            expected = f"{owner}/{repo}" if owner and repo else ""
            confirmed = str(body.get("repository") or "").strip()
            if not expected:
                return web.json_response(
                    {"error": "This project has no linked GitHub repository.", "code": "repository_not_linked"},
                    status=409,
                )
            if confirmed != expected:
                return web.json_response(
                    {"error": "Repository confirmation does not match the linked project.", "code": "repository_identity_mismatch", "required_identity": expected},
                    status=400,
                )
            if not config.github_token:
                return web.json_response(
                    {"error": "GitHub authentication is not configured.", "code": "github_auth_missing"},
                    status=503,
                )

            from src.github_client import GitHubAPIError, GitHubClient

            client = GitHubClient(config.github_token)
            try:
                repository = await client.get_repository(owner, repo)
                if str(repository.get("full_name") or "").casefold() != expected.casefold():
                    return web.json_response(
                        {"error": "GitHub returned a different repository identity.", "code": "repository_identity_mismatch"},
                        status=409,
                    )
                await client.delete_repo(owner, repo)
            except GitHubAPIError as error:
                if error.status == 404:
                    return web.json_response({
                        "success": True,
                        "repository": expected,
                        "already_deleted": True,
                        "hub_project_archived": bool(project.get("archived_at")),
                    })
                if error.status in {401, 403}:
                    return web.json_response(
                        {"error": "GitHub denied repository deletion. The token needs repository deletion permission.", "code": "github_delete_permission_required"},
                        status=403,
                    )
                return web.json_response(
                    {"error": "GitHub repository deletion failed.", "code": "github_delete_failed"},
                    status=502,
                )
            return web.json_response({
                "success": True,
                "repository": expected,
                "already_deleted": False,
                "hub_project_archived": bool(project.get("archived_at")),
            })
        except (TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)
        except Exception:
            return web.json_response(
                {"error": "GitHub repository deletion failed.", "code": "github_delete_failed"},
                status=502,
            )

    return await local_cors_response(request, delete_remote, methods="DELETE")


async def handle_get_github_repositories(request: web.Request) -> web.Response:
    """List repositories owned by the authenticated GitHub user."""
    try:
        if not config.github_token:
            return web.json_response(
                {"error": "GitHub authentication is not configured."}, status=503
            )
        from src.github_client import GitHubClient

        repositories = await GitHubClient(config.github_token).list_repositories()
        imported = {
            (str(project.get("github_owner") or "").lower(),
             str(project.get("github_repo") or "").lower()): int(project["id"])
            for project in ProjectManager.get_projects()
        }
        for repository in repositories:
            key = (repository["owner"].lower(), repository["name"].lower())
            repository["imported"] = key in imported
            repository["project_id"] = imported.get(key)
            repository["suggested_local_path"] = str(
                (
                    Path(config.projects_base_dir).expanduser().resolve()
                    / repository["name"]
                ).resolve()
            )
        return web.json_response({"repositories": repositories})
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_import_github_repository(request: web.Request) -> web.Response:
    """Import one repository selected from the authenticated GitHub catalog."""
    try:
        body = await request.json()
        full_name = str(body.get("full_name") or "").strip().lower()
        local_path = str(body.get("path") or "").strip()
        if not full_name or "/" not in full_name:
            return web.json_response({"error": "full_name is required"}, status=400)
        if not config.github_token:
            return web.json_response(
                {"error": "GitHub authentication is not configured."}, status=503
            )

        from src.github_client import GitHubClient

        repositories = await GitHubClient(config.github_token).list_repositories()
        selected = next(
            (repo for repo in repositories if repo["full_name"].lower() == full_name),
            None,
        )
        if not selected:
            return web.json_response(
                {"error": "The selected repository is not owned by the authenticated GitHub user."},
                status=404,
            )
        project = await ProjectManager.import_github_repository(
            selected,
            custom_path=local_path or None,
        )
        return web.json_response(project, status=201)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=409)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


def _normalize_antigravity_value(value: str) -> str:
    return os.path.normcase(os.path.normpath(str(value or "").strip())).replace("/", "\\").lower()


def _is_internal_antigravity_path(path_value: str) -> bool:
    lowered = _normalize_antigravity_value(path_value)
    return "\\.gemini\\antigravity\\brain\\" in lowered and "\\.agents\\" in lowered


async def _build_live_antigravity_project_catalog() -> List[Dict[str, Any]]:
    """Combine the live app project list with conversation metadata for chat lookup."""
    from src.antigravity_project_settings import (
        is_antigravity_project_configured,
    )
    from src.cdp_client import AntigravityCDP
    from src.integrity_sync import scan_antigravity_conversation_catalog

    client = AntigravityCDP()
    try:
        await client.connect()
        live_result = await client.get_project_list()
    finally:
        await client.disconnect()

    if live_result.get("error"):
        raise ConnectionError(live_result["error"])

    conversations = await asyncio.to_thread(
        scan_antigravity_conversation_catalog
    )
    workspace_groups: Dict[str, Dict[str, Any]] = {}
    for conversation in conversations:
        raw_path = str(conversation.get("workspace_path") or "").strip()
        if not raw_path or _is_internal_antigravity_path(raw_path):
            continue
        normalized_path = _normalize_antigravity_value(raw_path)
        activity = float(
            conversation.get("updated_at")
            or conversation.get("created_at")
            or 0
        )
        group = workspace_groups.setdefault(normalized_path, {
            "workspace_path": raw_path,
            "basename": Path(raw_path).name.lower(),
            "project_uuid": "",
            "project_uuid_activity": -1.0,
            "project_uuid_candidates": {},
            "chat_count": 0,
            "last_activity": 0.0,
        })
        group["chat_count"] += 1
        group["last_activity"] = max(
            group["last_activity"], activity
        )
        project_uuid = str(conversation.get("project_uuid") or "").strip()
        if project_uuid:
            candidates = group["project_uuid_candidates"]
            candidates[project_uuid] = max(
                float(candidates.get(project_uuid, -1.0)),
                activity,
            )

    for group in workspace_groups.values():
        candidates = sorted(
            group["project_uuid_candidates"].items(),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        for project_uuid, activity in candidates:
            if is_antigravity_project_configured(
                workspace_path=str(group["workspace_path"]),
                project_uuid=str(project_uuid),
            ):
                group["project_uuid"] = str(project_uuid)
                group["project_uuid_activity"] = float(activity)
                break

    catalog: List[Dict[str, Any]] = []
    catalog_by_id: Dict[str, Dict[str, Any]] = {}
    matched_workspace_paths: set[str] = set()
    for live_project in live_result.get("projects") or []:
        display_name = str(live_project.get("display_name") or live_project.get("name") or "").strip()
        if not display_name:
            continue
        normalized_display = _normalize_antigravity_value(display_name)
        exact = workspace_groups.get(normalized_display)
        candidates = [exact] if exact else [
            item for item in workspace_groups.values()
            if item["basename"] == display_name.lower()
        ]
        candidates = [
            item
            for item in candidates
            if item
            and str(item.get("project_uuid") or "").strip()
            and is_antigravity_project_configured(
                workspace_path=str(item["workspace_path"]),
                project_uuid=str(item["project_uuid"]),
            )
        ]
        match = max(candidates, key=lambda item: item["last_activity"]) if candidates else None
        if match:
            matched_workspace_paths.add(
                _normalize_antigravity_value(str(match["workspace_path"]))
            )

        workspace_path = str(match["workspace_path"] if match else "")
        if not workspace_path and Path(display_name).is_dir():
            workspace_path = str(Path(display_name).resolve())
        project_uuid = str(match["project_uuid"] if match else "")
        stable_id = project_uuid or "live-" + hashlib.sha256(
            normalized_display.encode("utf-8")
        ).hexdigest()[:20]
        item = {
            "id": stable_id,
            "name": display_name,
            "display_name": display_name,
            "workspace_path": workspace_path,
            "project_uuid": project_uuid,
            "chat_count": int(match["chat_count"] if match else 0),
            "last_activity": float(match["last_activity"] if match else 0),
        }
        existing = catalog_by_id.get(stable_id)
        if existing:
            existing["chat_count"] = max(existing["chat_count"], item["chat_count"])
            existing["last_activity"] = max(
                existing["last_activity"], item["last_activity"]
            )
            if not existing["workspace_path"] and item["workspace_path"]:
                existing["workspace_path"] = item["workspace_path"]
            existing_is_path = bool(Path(existing["display_name"]).drive)
            item_is_path = bool(Path(item["display_name"]).drive)
            if (existing_is_path and not item_is_path) or (
                existing_is_path == item_is_path
                and len(item["display_name"]) < len(existing["display_name"])
            ):
                existing["name"] = item["name"]
                existing["display_name"] = item["display_name"]
            continue
        catalog_by_id[stable_id] = item
        catalog.append(item)

    get_projects = getattr(db, "get_projects", None)
    linked_projects = (
        get_projects(include_archived=False) if callable(get_projects) else []
    )
    for linked_project in linked_projects:
        workspace_path = str(
            linked_project.get("integrity_workspace_path") or ""
        ).strip()
        project_uuid = str(
            linked_project.get("integrity_project_uuid") or ""
        ).strip()
        normalized_workspace = _normalize_antigravity_value(workspace_path)
        group = workspace_groups.get(normalized_workspace)
        if (
            not workspace_path
            or not project_uuid
            or normalized_workspace in matched_workspace_paths
            or not Path(workspace_path).is_dir()
            or not is_antigravity_project_configured(
                workspace_path=workspace_path,
                project_uuid=project_uuid,
            )
        ):
            continue
        if not group or str(group["project_uuid"]) != project_uuid:
            continue

        display_name = str(
            linked_project.get("antigravity_project_name")
            or Path(workspace_path).name
            or workspace_path
        ).strip()
        existing = catalog_by_id.get(project_uuid)
        if existing:
            existing["workspace_path"] = workspace_path
            existing["chat_count"] = max(
                int(existing["chat_count"]), int(group["chat_count"])
            )
            existing["last_activity"] = max(
                float(existing["last_activity"]), float(group["last_activity"])
            )
            continue

        item = {
            "id": project_uuid,
            "name": display_name,
            "display_name": display_name,
            "workspace_path": workspace_path,
            "project_uuid": project_uuid,
            "chat_count": int(group["chat_count"]),
            "last_activity": float(group["last_activity"]),
        }
        catalog_by_id[project_uuid] = item
        catalog.append(item)
    return catalog


async def handle_get_antigravity_projects(request: web.Request) -> web.Response:
    """Return live projects plus confirmed links awaiting sidebar materialization."""
    try:
        catalog = await _build_live_antigravity_project_catalog()
        public_projects = [
            {key: value for key, value in item.items() if key != "workspace_path"}
            for item in catalog
        ]
        return web.json_response({"projects": public_projects})
    except Exception as error:
        return web.json_response(
            {"error": f"Anti-Gravity projects could not be read: {error}"}, status=503
        )


async def handle_get_integrity_workspaces(request: web.Request) -> web.Response:
    """Backward-compatible alias for the live Anti-Gravity project catalog."""
    try:
        catalog = await _build_live_antigravity_project_catalog()
        return web.json_response({"workspaces": catalog})
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_link_integrity_workspace(request: web.Request) -> web.Response:
    """Link a Hub repository to one live Anti-Gravity project by selection ID."""
    try:
        project_id = int(request.match_info["id"])
        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Project not found"}, status=404)
        body = await request.json()
        selected_id = str(body.get("antigravity_project_id") or "").strip()
        if not selected_id:
            return web.json_response({"error": "antigravity_project_id is required"}, status=400)
        catalog = await _build_live_antigravity_project_catalog()
        selected = next((item for item in catalog if item["id"] == selected_id), None)
        if not selected:
            return web.json_response({"error": "The selected Anti-Gravity project is no longer available."}, status=409)

        workspace_path = str(selected.get("workspace_path") or "").strip()
        if not workspace_path:
            project_basename = Path(project["path"]).name.lower()
            if project_basename == selected["display_name"].lower():
                workspace_path = str(Path(project["path"]).resolve())
        if not workspace_path:
            return web.json_response({
                "error": "This Anti-Gravity project has no resolvable workspace yet. Open one chat in it once, then refresh the list."
            }, status=409)
        path = Path(workspace_path).expanduser()
        if not path.exists() or not path.is_dir():
            return web.json_response({"error": "Anti-Gravity project directory does not exist"}, status=409)
        resolved = str(path.resolve())
        db.update_project_integrity_link(
            project_id,
            resolved,
            str(selected.get("project_uuid") or selected["id"]),
            selected["display_name"],
        )
        return web.json_response({
            "success": True,
            "project_id": project_id,
            "antigravity_project_id": selected["id"],
            "antigravity_project_name": selected["display_name"],
        })
    except (TypeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_unlink_integrity_workspace(request: web.Request) -> web.Response:
    """Remove only the Anti-Gravity mapping; the Hub repo and all files remain."""
    try:
        project_id = int(request.match_info["id"])
        if not db.get_project(project_id):
            return web.json_response({"error": "Project not found"}, status=404)
        db.update_project_integrity_link(project_id, "", "", "")
        return web.json_response({"success": True})
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_create_antigravity_project(request: web.Request) -> web.Response:
    """Create the linked native project from the Hub repository folder."""
    manager = None
    try:
        project_id = int(request.match_info["id"])
        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Project not found"}, status=404)

        body = await request.json()
        registered_path = Path(str(project.get("path") or "")).expanduser().resolve()
        requested_path = Path(
            str(body.get("workspace_path") or registered_path)
        ).expanduser().resolve()
        if requested_path != registered_path:
            return web.json_response(
                {
                    "error": (
                        "workspace_path must match the local GitHub clone. "
                        "Choose the desired folder when importing the repository."
                    )
                },
                status=400,
            )
        if not registered_path.is_dir():
            return web.json_response(
                {"error": f"Local project directory does not exist: {registered_path}"},
                status=409,
            )

        from src.parallel_cdp import ParallelCDPManager

        manager = ParallelCDPManager()
        catalog_before = await _build_live_antigravity_project_catalog()
        normalized_workspace = _normalize_antigravity_value(str(registered_path))
        saved_project_uuid = str(project.get("integrity_project_uuid") or "").strip()
        saved_project = next(
            (
                item
                for item in catalog_before
                if str(item.get("id") or "") == saved_project_uuid
                and _normalize_antigravity_value(item.get("workspace_path", ""))
                == normalized_workspace
            ),
            None,
        )
        linked_project_name = str(
            saved_project.get("display_name") if saved_project else ""
        ).strip()
        native = await manager.ensure_project_in_primary(
            str(registered_path),
            project_name=linked_project_name,
        )
        catalog = await _build_live_antigravity_project_catalog()
        selected = next(
            (
                item
                for item in catalog
                if _normalize_antigravity_value(item.get("workspace_path", ""))
                == normalized_workspace
            ),
            None,
        )
        if not selected:
            selected = next(
                (
                    item
                    for item in catalog
                    if _normalize_antigravity_value(item.get("display_name", ""))
                    in {
                        _normalize_antigravity_value(registered_path.name),
                        normalized_workspace,
                    }
                ),
                None,
            )

        native_project_id = str(selected.get("id") if selected else "")
        native_project_name = str(
            selected.get("display_name") if selected else registered_path.name
        )
        db.update_project_integrity_link(
            project_id,
            str(registered_path),
            native_project_id,
            native_project_name,
        )
        return web.json_response(
            {
                "success": True,
                "project_id": project_id,
                "workspace_path": str(registered_path),
                "antigravity_project_id": native_project_id,
                "antigravity_project_name": native_project_name,
                "created": bool(native.get("imported", False)),
                "native": native,
            },
            status=201 if native.get("imported", False) else 200,
        )
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except (ConnectionError, TimeoutError) as error:
        return web.json_response({"error": str(error)}, status=503)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)
    finally:
        if manager is not None:
            await manager.disconnect_all()


async def handle_link_github_repo(request: web.Request) -> web.Response:
    """Attach GitHub metadata to a legacy local Hub project without recreating it."""
    try:
        project_id = int(request.match_info["id"])
        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Project not found"}, status=404)
        body = await request.json()
        raw_url = str(body.get("github_url") or "").strip().rstrip("/")
        match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?",
            raw_url,
            re.IGNORECASE,
        )
        if not match:
            return web.json_response({"error": "A valid https://github.com/<owner>/<repo> URL is required"}, status=400)
        owner, repo = match.group(1), match.group(2)
        canonical = f"https://github.com/{owner}/{repo}.git"
        local_path = Path(project["path"])
        if local_path.exists() and (local_path / ".git").exists():
            remote = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(local_path), capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if remote.returncode == 0:
                normalize = lambda value: value.strip().lower().removesuffix(".git").rstrip("/")
                if normalize(remote.stdout) != normalize(canonical):
                    return web.json_response({
                        "error": f"Local origin is {remote.stdout.strip()}, not {canonical}. Correct the local remote first."
                    }, status=409)
        default_branch = str(body.get("default_branch") or project.get("default_branch") or "main")
        db.update_project_github(project_id, canonical, owner, repo)
        return web.json_response({
            "success": True, "project_id": project_id, "github_url": canonical,
            "github_owner": owner, "github_repo": repo, "default_branch": default_branch,
        })
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


# ============================================================
# API Handlers for Issues
# ============================================================

async def handle_get_issues(request: web.Request) -> web.Response:
    """GET /api/issues — List all issues or filter by project_id."""
    try:
        project_id_str = request.query.get("project_id")
        project_id = int(project_id_str) if project_id_str else None
        issues = ProjectManager.get_issues(project_id)
        return web.json_response({"issues": issues})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_issue(request: web.Request) -> web.Response:
    """POST /api/issues — Add a new issue to resolve."""
    try:
        body = await request.json()
        project_id = body.get("project_id")
        title = body.get("title")
        description = body.get("description")
        source = body.get("source", "manual")
        issue_type = body.get("issue_type", "task")

        if not project_id or not title or not description:
            return web.json_response({"error": "project_id, title, and description are required"}, status=400)

        issue = await ProjectManager.add_issue(
            int(project_id), title, description, source, issue_type
        )
        return web.json_response(issue, status=201)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_delete_issue(request: web.Request) -> web.Response:
    """DELETE /api/issues/{id} — Delete an issue."""
    try:
        issue_id = int(request.match_info["id"])

        # Stop any active run for this issue first
        orchestrator = Orchestrator()
        active_runs = [rid for rid, t in orchestrator.active_tasks.items() if db.get_agent_run(rid) and db.get_agent_run(rid)["issue_id"] == issue_id]
        for rid in active_runs:
            await orchestrator.cancel_run(rid)

        db.delete_issue(issue_id)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_reset_issue(request: web.Request) -> web.Response:
    """POST /api/issues/{id}/reset — Reset/restart an issue."""
    try:
        issue_id = int(request.match_info["id"])

        # Stop any active run for this issue first
        orchestrator = Orchestrator()
        active_runs = [rid for rid, t in orchestrator.active_tasks.items() if db.get_agent_run(rid) and db.get_agent_run(rid)["issue_id"] == issue_id]
        for rid in active_runs:
            await orchestrator.cancel_run(rid)

        db.reset_issue(issue_id)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ============================================================
# API Handlers for GitHub Sync
# ============================================================

async def handle_sync_issues(request: web.Request) -> web.Response:
    """GET /api/projects/{id}/sync — Sync issues from GitHub."""
    try:
        project_id = int(request.match_info["id"])
        result = await ProjectManager.sync_issues_from_github(project_id)
        return web.json_response(result)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_github_status(request: web.Request) -> web.Response:
    """GET /api/github/status — Validate the configured GitHub credentials."""
    base = {
        "configured": config.github_configured,
        "valid": False,
        "status": "missing",
        "owner": config.github_owner,
        "projects_base_dir": config.projects_base_dir,
        "error": "",
    }
    if not config.github_configured:
        return web.json_response(base)

    try:
        user = await GitHubClient(config.github_token).check_token()
        base.update(
            {
                "valid": True,
                "status": "valid",
                "owner": user.get("login") or config.github_owner,
                "login": user.get("login") or "",
            }
        )
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        base.update(
            {
                "status": (
                    "rate_limited"
                    if "rate limit" in lowered or "status 403" in lowered
                    else "invalid"
                ),
                "error": message,
            }
        )
    return web.json_response(base)


# ============================================================
# API Handlers for Agent Runs
# ============================================================

async def handle_get_issue_runs(request: web.Request) -> web.Response:
    """GET /api/issues/{id}/runs — List all runs for an issue."""
    try:
        issue_id = int(request.match_info["id"])
        runs = db.get_agent_runs_by_issue(issue_id)
        return web.json_response({"runs": runs})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_issue_run(request: web.Request) -> web.Response:
    """POST /api/issues/{id}/runs — Trigger a new AI execution run."""
    try:
        issue_id = int(request.match_info["id"])

        full_auto = True
        try:
            body = await request.json()
            full_auto = body.get("full_auto", True)
        except Exception:
            pass

        # Switch to sandbox branch
        ProjectManager.prepare_issue_sandbox(issue_id)

        # Start execution
        orchestrator = Orchestrator()
        run_id = orchestrator.start_run(issue_id, full_auto=full_auto)

        return web.json_response({"run_id": run_id, "status": "started"}, status=201)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_approve_run(request: web.Request) -> web.Response:
    """POST /api/runs/{id}/approve — Approve a paused run."""
    try:
        run_id = int(request.match_info["id"])
        orchestrator = Orchestrator()
        success = orchestrator.approve_run(run_id)
        if success:
            orchestrator.broadcast_log(run_id, "info", "[SYSTEM] Plan approved by user. Resuming...")
            db.update_agent_run(run_id, "planning", "running")
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_feedback_run(request: web.Request) -> web.Response:
    """POST /api/runs/{id}/feedback — Submit feedback/questions for a paused run."""
    try:
        run_id = int(request.match_info["id"])
        body = await request.json()
        feedback = body.get("feedback", "")
        if not feedback:
            return web.json_response({"error": "feedback is required"}, status=400)

        orchestrator = Orchestrator()
        success = orchestrator.submit_feedback(run_id, feedback)
        if success:
            orchestrator.broadcast_log(run_id, "info", f"[SYSTEM] User feedback received: {feedback}. Resuming...")
            db.update_agent_run(run_id, "planning", "running")
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_run(request: web.Request) -> web.Response:
    """GET /api/runs/{id} — Get details of a specific execution run."""
    try:
        run_id = int(request.match_info["id"])
        run = db.get_agent_run(run_id)
        if not run:
            return web.json_response({"error": "Run not found"}, status=404)

        run_dict = dict(run)

        # Load implementation plan if it exists
        plan_content = None
        from pathlib import Path

        # Check in project directory first
        try:
            issue = db.get_issue(run["issue_id"])
            if issue:
                project = db.get_project(issue["project_id"])
                if project:
                    project_plan_path = Path(project["path"]) / "implementation_plan.md"
                    if project_plan_path.exists():
                        plan_content = project_plan_path.read_text(encoding='utf-8')
        except Exception:
            pass

        # Fallback to session brain folder
        conv_id = run_dict.get("conversation_id")
        if not plan_content and conv_id:
            try:
                brain_plan_path = (
                    Path.home()
                    / ".gemini"
                    / "antigravity"
                    / "brain"
                    / str(conv_id)
                    / "implementation_plan.md"
                )
                if brain_plan_path.exists():
                    plan_content = brain_plan_path.read_text(encoding='utf-8')
            except Exception:
                pass

        if plan_content:
            run_dict["implementation_plan"] = plan_content

        return web.json_response(run_dict)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_cancel_run(request: web.Request) -> web.Response:
    """POST /api/runs/{id}/cancel — Cancels a running agent process."""
    try:
        run_id = int(request.match_info["id"])
        orchestrator = Orchestrator()
        success = await orchestrator.cancel_run(run_id)
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_run_logs_sse(request: web.Request) -> web.StreamResponse:
    """GET /api/runs/{id}/logs — SSE stream of real-time execution logs."""
    run_id = int(request.match_info["id"])

    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*'
        }
    )
    await response.prepare(request)

    # 1. Send all existing logs first
    existing_logs = db.get_run_logs(run_id)
    for log in existing_logs:
        data = json.dumps({
            "timestamp": log["timestamp"],
            "level": log["level"],
            "message": log["message"]
        })
        await response.write(f"data: {data}\n\n".encode('utf-8'))
        await response.drain()

    # 2. Stream live logs if active
    orchestrator = Orchestrator()
    if run_id in orchestrator.active_tasks:
        queue = asyncio.Queue()
        orchestrator.register_log_queue(run_id, queue)
        try:
            while run_id in orchestrator.active_tasks:
                try:
                    log_item = await asyncio.wait_for(queue.get(), timeout=2.0)
                    data = json.dumps(log_item)
                    await response.write(f"data: {data}\n\n".encode('utf-8'))
                    await response.drain()
                    queue.task_done()
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    await response.drain()

            # Drain any remaining log items in the queue
            while not queue.empty():
                log_item = queue.get_nowait()
                data = json.dumps(log_item)
                await response.write(f"data: {data}\n\n".encode('utf-8'))
                await response.drain()
                queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            orchestrator.unregister_log_queue(run_id, queue)

    await response.write(b"event: close\ndata: end\n\n")
    await response.drain()
    return response


# ============================================================
# API Handlers for Lessons & Git Control
# ============================================================

async def handle_get_lessons(request: web.Request) -> web.Response:
    """GET /api/lessons — List all lessons learned across projects."""
    try:
        project_id_str = request.query.get("project_id")
        project_id = int(project_id_str) if project_id_str else None
        lessons = db.get_lessons(project_id)
        return web.json_response({"lessons": lessons})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_git_commit(request: web.Request) -> web.Response:
    """POST /api/git/commit — Commit sandbox changes in project repository."""
    try:
        body = await request.json()
        project_id = int(body.get("project_id"))
        message = body.get("message", "Commit from Anti-Gravity Hub")

        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Project not found"}, status=404)

        success = git_commit(project["path"], message)
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_git_discard(request: web.Request) -> web.Response:
    """POST /api/git/discard — Discard sandbox changes in project repository."""
    try:
        body = await request.json()
        project_id = int(body.get("project_id"))

        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Project not found"}, status=404)

        success = git_discard_changes(project["path"])
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ============================================================
# API Handlers for Preview & Follow-Up
# ============================================================

# Global registry of preview server subprocesses. Keys are namespaced so a
# project preview and an isolated Control Center task preview cannot collide.
_preview_servers: Dict[str, Dict[str, Any]] = {}


def _find_free_port() -> int:
    """Finds a free TCP port on localhost."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def handle_project_preview(request: web.Request) -> web.Response:
    """POST /api/projects/{id}/preview — Startet einen lokalen HTTP-Server im Projektverzeichnis."""
    try:
        project_id = int(request.match_info["id"])
        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Projekt nicht gefunden"}, status=404)

        project_path = project["path"]
        from pathlib import Path
        pp = Path(project_path)
        if not pp.exists():
            return web.json_response({"error": f"Projektverzeichnis existiert nicht: {project_path}"}, status=400)

        result, started = await _ensure_preview_server(
            f"project:{project_id}",
            pp,
            source="project",
        )
        return web.json_response(result, status=201 if started else 200)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_stop_preview(request: web.Request) -> web.Response:
    """POST /api/projects/{id}/preview/stop — Stoppt den Preview-Server."""
    try:
        project_id = int(request.match_info["id"])
        result = _stop_preview_server(f"project:{project_id}")
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _preview_payload(info: Dict[str, Any], status: str) -> Dict[str, Any]:
    return {
        "active": True,
        "url": f"http://127.0.0.1:{info['port']}",
        "port": info["port"],
        "status": status,
        "pid": info["proc"].pid,
        "path": str(info["path"]),
        "source": info["source"],
        "server_kind": "static",
    }


async def _ensure_preview_server(
    key: str,
    path: Path,
    *,
    source: str,
) -> tuple[Dict[str, Any], bool]:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"Preview-Verzeichnis existiert nicht: {resolved}")

    info = _preview_servers.get(key)
    if info and info["proc"].poll() is None:
        return _preview_payload(info, "already_running"), False
    if info:
        _preview_servers.pop(key, None)

    port = _find_free_port()
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(resolved),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    info = {
        "proc": proc,
        "port": port,
        "path": resolved,
        "source": source,
    }
    _preview_servers[key] = info
    await asyncio.sleep(0.35)
    if proc.poll() is not None:
        _preview_servers.pop(key, None)
        raise RuntimeError("Der lokale Preview-Server wurde unerwartet beendet.")
    return _preview_payload(info, "started"), True


def _preview_status(key: str, *, path: Path, source: str) -> Dict[str, Any]:
    info = _preview_servers.get(key)
    if info and info["proc"].poll() is None:
        return _preview_payload(info, "running")
    if info:
        _preview_servers.pop(key, None)
    return {
        "active": False,
        "status": "stopped",
        "path": str(path.resolve()),
        "source": source,
        "server_kind": "static",
    }


def _stop_preview_server(key: str) -> Dict[str, Any]:
    info = _preview_servers.pop(key, None)
    if not info:
        return {"success": True, "active": False, "status": "already_stopped"}
    try:
        info["proc"].terminate()
        info["proc"].wait(timeout=3)
    except Exception:
        try:
            info["proc"].kill()
        except Exception:
            pass
    return {
        "success": True,
        "active": False,
        "status": "stopped",
        "path": str(info["path"]),
    }


def _control_task_preview_workspace(task_id: str) -> Dict[str, Any]:
    from src.ide_server import resolve_control_task_workspace

    return resolve_control_task_workspace(task_id)


async def handle_control_task_preview_status(request: web.Request) -> web.Response:
    """GET task preview state without starting a process."""
    task_id = request.match_info["task_id"]
    try:
        workspace = await asyncio.to_thread(_control_task_preview_workspace, task_id)
        return web.json_response(_preview_status(
            f"task:{task_id}",
            path=workspace["path"],
            source=workspace["source"],
        ))
    except LookupError as error:
        return web.json_response({"error": str(error)}, status=404)
    except FileNotFoundError as error:
        return web.json_response({"error": str(error)}, status=409)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)


async def handle_control_task_preview(request: web.Request) -> web.Response:
    """POST a static localhost preview for the exact PR task workspace."""
    task_id = request.match_info["task_id"]
    try:
        workspace = await asyncio.to_thread(_control_task_preview_workspace, task_id)
        result, started = await _ensure_preview_server(
            f"task:{task_id}",
            workspace["path"],
            source=workspace["source"],
        )
        result.update({
            "task_id": task_id,
            "branch_name": workspace.get("branch_name", ""),
        })
        return web.json_response(result, status=201 if started else 200)
    except LookupError as error:
        return web.json_response({"error": str(error)}, status=404)
    except FileNotFoundError as error:
        return web.json_response({"error": str(error)}, status=409)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_stop_control_task_preview(request: web.Request) -> web.Response:
    """POST stop for a task-local preview. The operation is idempotent."""
    task_id = request.match_info["task_id"]
    return web.json_response(_stop_preview_server(f"task:{task_id}"))


async def handle_run_followup(request: web.Request) -> web.Response:
    """POST /api/runs/{id}/followup — Setzt den gleichen Run mit einer Follow-Up-Nachricht fort."""
    try:
        run_id = int(request.match_info["id"])
        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            return web.json_response({"error": "message ist erforderlich"}, status=400)

        # Get the completed run
        run = db.get_agent_run(run_id)
        if not run:
            return web.json_response({"error": "Run nicht gefunden"}, status=404)

        if run["status"] == "running":
            return web.json_response({"error": "Run läuft noch — bitte warten"}, status=409)

        issue_id = run["issue_id"]
        issue = db.get_issue(issue_id)
        if not issue:
            return web.json_response({"error": "Issue nicht gefunden"}, status=404)

        # Reuse the SAME run — add follow-up message to existing chat history
        db.add_chat_message(run_id, "user", message)

        # Reset run status to "running" so the agent continues
        db.update_agent_run(run_id, "started", "running")
        db.update_issue_status(issue_id, "running")

        # Continue execution in the same conversation context
        orchestrator = Orchestrator()
        orchestrator.continue_run(run_id)

        orchestrator.broadcast_log(run_id, "info",
            f"[SYSTEM] 💬 Follow-Up Nachricht erhalten: {message[:100]}..." if len(message) > 100
            else f"[SYSTEM] 💬 Follow-Up Nachricht erhalten: {message}")

        return web.json_response({
            "run_id": run_id,
            "status": "continued",
            "message": "Run wird mit Follow-Up fortgesetzt"
        }, status=200)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ============================================================
# Orchestrator Chat Handler
# ============================================================

ORCHESTRATOR_SYSTEM_PROMPT = """Du bist ein proaktiver Software-Orchestrator im Anti-Gravity Hub.
Du hast Zugriff auf das aktuelle Projekt, alle Issues und die letzten Logs.
Analysiere den Status, erkenne Verbesserungspotenzial und mache konkrete Vorschläge.

Regeln:
- Antworte IMMER auf Deutsch
- Gib maximal 2-3 kurze, direkt ausführbare Verbesserungsvorschläge
- Jeder Vorschlag ist ein konkreter Follow-Up Prompt
- Sei präzise, technisch, kein Smalltalk
- Antworte NUR als JSON:
{"reply": "Analyse...", "suggestions": [{"label": "Button-Text", "prompt": "Vollständiger Prompt..."}]}
"""


async def handle_orchestrator_chat(request: web.Request) -> web.Response:
    """POST /api/orchestrator/chat — Context-aware AI analysis with actionable suggestions."""
    try:
        body = await request.json()
        user_message = body.get("message", "")
        ctx = body.get("context", {})

        project = ctx.get("project", {})
        issues = ctx.get("issues", [])
        last_logs = ctx.get("last_logs", "")
        run_status = ctx.get("run_status", "unknown")
        current_issue = ctx.get("current_issue", {})

        context_block = f"""=== KONTEXT ===
Projekt: {project.get('name', '?')} | Pfad: {project.get('path', '-')}
Issues gesamt: {len(issues)}
"""
        if current_issue:
            context_block += f"Aktuelles Issue: [{current_issue.get('status','?').upper()}] {current_issue.get('title','?')} — {current_issue.get('description','')[:200]}\n"

        open_issues = [i for i in issues if i.get('status') not in ('done', 'cancelled')]
        if open_issues:
            context_block += "Offene Issues: " + ", ".join(
                f"#{i.get('id')}: {i.get('title','?')[:40]}" for i in open_issues[:5]
            ) + "\n"

        context_block += f"Letzter Run-Status: {run_status}\n"
        if last_logs:
            context_block += f"\n=== LOGS ===\n{last_logs[-2000:]}\n"

        full_prompt = f"{context_block}\n=== USER ===\n{user_message}" if user_message else context_block

        import aiohttp as _aio
        api_url = "http://127.0.0.1:8001/api/chat"
        auth_token = config.auth_token

        async with _aio.ClientSession() as session:
            async with session.post(
                api_url,
                json={"message": f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{full_prompt}", "model": "gemini-2.5-flash"},
                headers={"Authorization": f"Bearer {auth_token}"},
                timeout=_aio.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return web.json_response({"error": f"API Bridge Fehler: {err[:200]}"}, status=502)
                api_data = await resp.json()
                raw = api_data.get("response") or api_data.get("content") or api_data.get("message", "")

        import re as _re
        m = _re.search(r'\{[\s\S]*\}', raw)
        if m:
            try:
                return web.json_response(json.loads(m.group()))
            except Exception:
                pass

        return web.json_response({"reply": raw or "Keine Antwort.", "suggestions": []})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ============================================================
# API Handlers for Subtasks
# ============================================================

async def handle_get_subtasks(request: web.Request) -> web.Response:
    """GET /api/issues/{id}/subtasks — List all subtasks for an issue."""
    try:
        issue_id = int(request.match_info["id"])
        subtasks = db.get_subtasks(issue_id)
        return web.json_response({"subtasks": subtasks})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_subtask(request: web.Request) -> web.Response:
    """POST /api/issues/{id}/subtasks — Create a new subtask."""
    try:
        issue_id = int(request.match_info["id"])
        body = await request.json()
        title = body.get("title", "").strip()
        if not title:
            return web.json_response({"error": "title is required"}, status=400)

        subtask_id = db.add_subtask(issue_id, title)
        return web.json_response({"id": subtask_id, "issue_id": issue_id, "title": title, "status": "pending"}, status=201)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_subtask_status(request: web.Request) -> web.Response:
    """POST /api/subtasks/{subtask_id}/status — Update subtask status."""
    try:
        subtask_id = int(request.match_info["subtask_id"])
        body = await request.json()
        status = body.get("status", "").strip()
        if status not in ("pending", "running", "completed"):
            return web.json_response({"error": "invalid status"}, status=400)

        db.update_subtask_status(subtask_id, status)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_delete_subtask(request: web.Request) -> web.Response:
    """DELETE /api/subtasks/{subtask_id} — Delete a subtask."""
    try:
        subtask_id = int(request.match_info["subtask_id"])
        db.delete_subtask(subtask_id)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_generate_commit_msg(request: web.Request) -> web.Response:
    """POST /api/git/generate-commit-msg — Generiert eine AI-gestützte Commit-Nachricht basierend auf dem Git-Diff."""
    try:
        body = await request.json()
        project_id = int(body.get("project_id"))

        project = db.get_project(project_id)
        if not project:
            return web.json_response({"error": "Projekt nicht gefunden"}, status=404)

        # Get diff
        diff_text = git_diff(project["path"])
        if not diff_text or not diff_text.strip():
            return web.json_response({"suggested_message": ""})

        prompt = (
            f"Suggest a clean, concise, single-line conventional commit message (max 72 chars) "
            f"based on the following git diff. Focus on the core changes. "
            f"Respond ONLY with the raw commit message itself, without any quotes, formatting, explanation or markdown:\n\n"
            f"{diff_text[:3000]}"
        )

        import aiohttp as _aio
        api_url = "http://127.0.0.1:8001/api/chat"
        auth_token = config.auth_token

        async with _aio.ClientSession() as session:
            async with session.post(
                api_url,
                json={"message": prompt, "model": "gemini-2.5-flash"},
                headers={"Authorization": f"Bearer {auth_token}"},
                timeout=_aio.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return web.json_response({"error": f"API Bridge Fehler: {err[:200]}"}, status=502)
                api_data = await resp.json()
                raw_msg = api_data.get("response") or api_data.get("content") or api_data.get("message", "")

        # Clean up any potential markdown code blocks or quotes in the AI response
        raw_msg = raw_msg.strip().strip('"\'`').replace("commit:", "").strip()

        return web.json_response({"suggested_message": raw_msg})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_integrity_chats(request: web.Request) -> web.Response:
    """List Anti-Gravity chats, optionally scoped to one linked Hub project."""
    try:
        project_id_str = request.query.get("project_id")
        from src.integrity_sync import scan_antigravity_conversation_catalog

        conversations = await asyncio.to_thread(
            scan_antigravity_conversation_catalog
        )
        deleted_ids = _deleted_managed_conversation_ids()
        conversations = [
            conversation
            for conversation in conversations
            if str(conversation.get("convo_id") or "").lower()
            not in deleted_ids
        ]
        project_path = ""
        if project_id_str:
            project = db.get_project(int(project_id_str))
            if not project:
                return web.json_response({"error": "Project not found"}, status=404)
            linked_workspace = str(
                project.get("integrity_workspace_path") or ""
            ).strip()
            if not linked_workspace:
                return web.json_response([])
            project_path = str(Path(linked_workspace).resolve())
            expected_path = os.path.normcase(os.path.normpath(project_path))
            conversations = [
                conversation
                for conversation in conversations
                if conversation.get("workspace_path")
                and os.path.normcase(
                    os.path.normpath(
                        str(Path(conversation["workspace_path"]).resolve())
                    )
                ) == expected_path
            ]

            for proxy_chat in db.list_proxy_conversations(int(project_id_str)):
                conversations.append({
                    **proxy_chat,
                    "workspace_path": project_path,
                    "project_uuid": "",
                    "project_name": Path(project_path).name,
                    "conversation_type": "project",
                    "archived": False,
                    "status": "complete",
                    "source": "custom",
                })

        conversations.sort(
            key=lambda item: float(
                item.get("updated_at") or item.get("created_at") or 0
            ),
            reverse=True,
        )
        return web.json_response(conversations)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_antigravity_conversations(
    request: web.Request,
) -> web.Response:
    """Return the complete Conversation History catalog with stable filters."""
    try:
        from src.integrity_sync import scan_antigravity_conversation_catalog

        conversations = await asyncio.to_thread(
            scan_antigravity_conversation_catalog
        )
        deleted_ids = _deleted_managed_conversation_ids()
        conversations = [
            conversation
            for conversation in conversations
            if str(conversation.get("convo_id") or "").lower()
            not in deleted_ids
        ]
        sidebar_snapshot = await _get_live_antigravity_sidebar_snapshot()
        type_filter = str(request.query.get("type") or "all").strip().lower()
        status_values = {
            value.strip().lower()
            for value in str(
                request.query.get("status") or "running,complete,archived"
            ).split(",")
            if value.strip()
        }
        search = str(request.query.get("search") or "").strip().lower()
        summary_only = str(
            request.query.get("summary_only") or ""
        ).strip().lower() in {"1", "true", "yes"}
        project_id_str = request.query.get("project_id")

        if project_id_str:
            project = db.get_project(int(project_id_str))
            if not project:
                return web.json_response({"error": "Project not found"}, status=404)
            linked_workspace = str(
                project.get("integrity_workspace_path") or ""
            ).strip()
            if not linked_workspace:
                conversations = []
            else:
                expected_path = os.path.normcase(
                    os.path.normpath(str(Path(linked_workspace).resolve()))
                )
                conversations = [
                    conversation
                    for conversation in conversations
                    if conversation.get("workspace_path")
                    and os.path.normcase(
                        os.path.normpath(
                            str(Path(conversation["workspace_path"]).resolve())
                        )
                    ) == expected_path
                ]

        catalog_by_id = {
            str(item.get("convo_id") or "").lower(): item
            for item in conversations
            if item.get("convo_id")
        }
        managed_by_id = {
            str(item.get("conversation_id") or "").lower(): item
            for item in db.list_managed_antigravity_conversations(
                state="active"
            )
            if item.get("conversation_id")
        }
        sidebar_chats = [
            item
            for item in sidebar_snapshot.get("chats") or []
            if str(item.get("id") or "").lower() not in deleted_ids
        ]
        visible_conversations = []
        visible_ids = set()
        for sidebar_item in sidebar_chats:
            convo_id = str(sidebar_item.get("id") or "").lower()
            metadata = catalog_by_id.get(convo_id)
            if not metadata or metadata.get("archived"):
                continue
            visible = dict(metadata)
            live_title = str(sidebar_item.get("title") or "").strip()
            catalog_title = str(metadata.get("title") or "").strip()
            if live_title and not _is_technical_sidebar_title(
                live_title,
                convo_id,
            ) and not _is_catalog_title_with_sidebar_age_badge(
                live_title,
                catalog_title,
            ):
                visible["title"] = live_title
            visible["visible_in_sidebar"] = True
            visible["sidebar_position"] = int(
                sidebar_item.get("position") or 0
            )
            visible["managed_by_hub"] = convo_id in managed_by_id
            visible_conversations.append(visible)
            visible_ids.add(convo_id)

        for convo_id in managed_by_id:
            if convo_id in visible_ids:
                continue
            metadata = catalog_by_id.get(convo_id)
            if not metadata or metadata.get("archived"):
                continue
            visible_conversations.append({
                **metadata,
                "visible_in_sidebar": False,
                "sidebar_position": None,
                "managed_by_hub": True,
            })
            visible_ids.add(convo_id)

        archived_conversations = [
            {
                **item,
                "visible_in_sidebar": False,
                "sidebar_position": None,
            }
            for item in conversations
            if item.get("archived")
        ]
        local_project_id = int(project_id_str) if project_id_str else None
        for provider_chat in db.list_provider_conversations(local_project_id):
            linked_project = (
                db.get_project(int(provider_chat["project_id"]))
                if provider_chat.get("project_id") is not None
                else None
            )
            if provider_chat.get("project_id") is not None and not linked_project:
                continue
            archived = bool(provider_chat.get("archived"))
            local_item = {
                **provider_chat,
                "workspace_path": str(provider_chat.get("project_path") or ""),
                "project_uuid": "",
                "project_name": str(provider_chat.get("project_name") or ""),
                "repository_name": str(provider_chat.get("repository_name") or ""),
                "conversation_type": "project" if provider_chat.get("project_id") else "normal",
                "archived": archived,
                "status": "complete",
                "source": str(provider_chat.get("provider_type") or "custom"),
                "model_name": str(provider_chat.get("display_name") or ""),
                "visible_in_sidebar": not archived,
                "sidebar_position": None,
            }
            (archived_conversations if archived else visible_conversations).append(local_item)

        for proxy_chat in db.list_proxy_conversations(local_project_id):
            linked_project = db.get_project(int(proxy_chat["project_id"]))
            if not linked_project:
                continue
            visible_conversations.append({
                **proxy_chat,
                "workspace_path": str(linked_project.get("path") or ""),
                "project_uuid": "",
                "project_name": str(linked_project.get("name") or ""),
                "repository_name": str(linked_project.get("github_repo") or ""),
                "conversation_type": "project",
                "archived": False,
                "status": "complete",
                "source": "custom",
                "visible_in_sidebar": True,
                "sidebar_position": None,
                "step_count": len(db.get_proxy_messages(str(proxy_chat["convo_id"]))),
            })

        conversations = visible_conversations + archived_conversations

        active_agents = [
            conversation
            for conversation in visible_conversations
            if conversation.get("status") == "running"
        ]
        counts = {
            "all": len(conversations),
            "visible": len(visible_conversations),
            "normal": sum(
                item.get("conversation_type") == "normal"
                for item in visible_conversations
            ),
            "project": sum(
                item.get("conversation_type") == "project"
                for item in visible_conversations
            ),
            "running": sum(
                item.get("status") == "running"
                for item in visible_conversations
            ),
            "complete": sum(
                item.get("status") == "complete"
                for item in visible_conversations
            ),
            "archived": len(archived_conversations),
        }

        if type_filter in {"normal", "project"}:
            conversations = [
                item
                for item in conversations
                if item.get("conversation_type") == type_filter
            ]
        if status_values:
            conversations = [
                item
                for item in conversations
                if (
                    "archived" in status_values and item.get("archived")
                )
                or (
                    not item.get("archived")
                    and item.get("status") in status_values
                )
            ]
        if search:
            conversations = [
                item
                for item in conversations
                if search in " ".join(
                    str(item.get(key) or "").lower()
                    for key in (
                        "title",
                        "project_name",
                        "repository_name",
                        "workspace_path",
                        "convo_id",
                    )
                )
            ]

        return web.json_response({
            "conversations": [] if summary_only else conversations,
            "active_agents": active_agents,
            "counts": counts,
            "visible_conversation_ids": [
                item["convo_id"]
                for item in visible_conversations
            ],
            "archived_conversation_ids": [
                item["convo_id"]
                for item in archived_conversations
            ],
            "filters": {
                "type": type_filter,
                "status": sorted(status_values),
                "search": search,
                "summary_only": summary_only,
                "project_id": int(project_id_str) if project_id_str else None,
            },
            "sidebar": {
                "available": bool(sidebar_snapshot.get("available")),
                "stale": bool(sidebar_snapshot.get("stale")),
                "complete": bool(sidebar_snapshot.get("complete")),
                "count": len(sidebar_chats),
                "active_id": (
                    None
                    if str(sidebar_snapshot.get("active_id") or "").lower()
                    in deleted_ids
                    else sidebar_snapshot.get("active_id")
                ),
                "error": sidebar_snapshot.get("error"),
            },
        })
    except (TypeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


async def handle_create_integrity_chat(request: web.Request) -> web.Response:
    """Create a verified normal or project chat in a dedicated Antigravity window."""
    cdp_manager = None
    convo_id = None
    try:
        body = await request.json()
        project_id = body.get("project_id")
        conversation_type = str(
            body.get("conversation_type")
            or ("project" if project_id else "normal")
        ).strip().lower()
        message = str(body.get("message") or "")
        attachments = body.get("attachments") or []
        if conversation_type not in {"normal", "project"}:
            return web.json_response(
                {"error": "conversation_type must be normal or project"},
                status=400,
            )
        if conversation_type == "project" and not project_id:
            return web.json_response(
                {"error": "project_id is required for a project chat"},
                status=400,
            )
        if not message.strip() and not attachments:
            return web.json_response(
                {
                    "error": (
                        "The first chat message must contain text "
                        "or an attachment."
                    )
                },
                status=400,
            )
        if not isinstance(attachments, list):
            return web.json_response({"error": "attachments must be a list"}, status=400)

        from src.parallel_cdp import ParallelCDPManager
        from src.integrity_sync import (
            get_integrity_chat_history,
            scan_integrity_convos,
        )

        cdp_manager = ParallelCDPManager()
        saved_attachments: List[Dict[str, Any]] = []
        try:
            project_path = ""
            if conversation_type == "project":
                try:
                    project_id = int(project_id)
                except (TypeError, ValueError):
                    return web.json_response(
                        {"error": "project_id must be an integer"},
                        status=400,
                    )
                project = db.get_project(project_id)
                if not project:
                    return web.json_response({"error": "Project not found"}, status=404)
                linked_workspace = str(
                    project.get("integrity_workspace_path") or ""
                ).strip()
                if not linked_workspace:
                    return web.json_response(
                        {
                            "error": (
                                "The GitHub project is not linked to an "
                                "Anti-Gravity project."
                            )
                        },
                        status=409,
                    )
                project_path = str(Path(linked_workspace).resolve())
                if not Path(project_path).is_dir():
                    return web.json_response(
                        {"error": f"Project directory does not exist: {project_path}"},
                        status=400,
                    )
                linked_project_name = str(
                    project.get("antigravity_project_name") or ""
                ).strip()
                saved_attachments = _save_chat_attachments(
                    attachments,
                    storage_key=f"_hub_upload_{uuid.uuid4().hex}",
                )
                window_info = await cdp_manager.create_new_project_chat_window(
                    project_path,
                    message,
                    minimize=True,
                    project_name=linked_project_name,
                    attachment_paths=[
                        item["file_path"] for item in saved_attachments
                    ],
                )
            else:
                saved_attachments = _save_chat_attachments(
                    attachments,
                    storage_key=f"_hub_upload_{uuid.uuid4().hex}",
                )
                window_info = await cdp_manager.create_new_normal_chat_window(
                    message,
                    minimize=True,
                    attachment_paths=[
                        item["file_path"] for item in saved_attachments
                    ],
                )
            convo_id = window_info["chat_id"]
            print(
                f"[API] Antigravity created conversation {convo_id}; verifying persisted delivery...",
                flush=True,
            )
        except Exception as cdp_err:
            status = 400 if isinstance(cdp_err, ValueError) else 503
            return web.json_response(
                {"error": f"Failed to create a dedicated Anti-Gravity chat window: {cdp_err}"},
                status=status,
            )

        verified_entry = None
        verified_workspace = ""
        verified_type = False
        expected_workspace = (
            os.path.normcase(os.path.normpath(project_path))
            if project_path
            else ""
        )
        for _ in range(80):
            history_result = await asyncio.to_thread(get_integrity_chat_history, convo_id)
            verified_entry = next(
                (
                    entry for entry in history_result.get("history", [])
                    if entry.get("role") == "user"
                    and str(entry.get("content") or "").strip() == message.strip()
                    and (
                        not saved_attachments
                        or len(entry.get("attachments") or [])
                        >= len(saved_attachments)
                    )
                ),
                None,
            )
            if verified_entry:
                conversations = await asyncio.to_thread(scan_integrity_convos)
                metadata = next(
                    (item for item in conversations if item.get("convo_id") == convo_id),
                    None,
                )
                if (
                    conversation_type == "project"
                    and metadata
                    and metadata.get("workspace_path")
                ):
                    actual_workspace = os.path.normcase(
                        os.path.normpath(str(Path(metadata["workspace_path"]).resolve()))
                    )
                    if actual_workspace == expected_workspace:
                        verified_workspace = metadata["workspace_path"]
                        verified_type = True
                elif (
                    conversation_type == "normal"
                    and metadata is not None
                    and not metadata.get("workspace_path")
                ):
                    verified_type = True
            if verified_entry and verified_type:
                break
            await asyncio.sleep(0.25)

        if not verified_entry or not verified_type:
            return web.json_response(
                {
                    "error": (
                        "The first message was submitted, but its "
                        f"{conversation_type} chat delivery could not be verified."
                    ),
                    "sent": True,
                    "verified": False,
                    "convo_id": convo_id,
                    "conversation_id": convo_id,
                    "window": window_info,
                },
                status=504,
            )

        db.upsert_managed_antigravity_conversation(
            convo_id,
            project_id=project_id if conversation_type == "project" else None,
            state="active",
        )
        _invalidate_live_sidebar_cache()
        return web.json_response(
            {
                "success": True,
                "verified": True,
                "verified_idx": verified_entry["idx"],
                "verified_workspace": verified_workspace,
                "convo_id": convo_id,
                "conversation_id": convo_id,
                "window": window_info,
                "method": "AntiGravityDuplicateWindow",
                "conversation_type": conversation_type,
            }
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    finally:
        if cdp_manager is not None:
            await cdp_manager.close_all()


async def handle_open_integrity_chat_window(request: web.Request) -> web.Response:
    """POST /api/integrity/chats/{convo_id}/window — Prepare a dedicated chat window."""
    from src.parallel_cdp import ParallelCDPManager

    convo_id = request.match_info["convo_id"]
    if not convo_id or convo_id == "new":
        return web.json_response({"error": "A stable conversation ID is required."}, status=400)
    if convo_id.startswith(("proxy-", "provider-")):
        return web.json_response({"success": True, "hub_local": True})

    cdp_manager = ParallelCDPManager()
    try:
        from src.integrity_sync import scan_antigravity_conversation_catalog

        conversations = await asyncio.to_thread(
            scan_antigravity_conversation_catalog
        )
        metadata = next(
            (item for item in conversations if item.get("convo_id") == convo_id),
            None,
        )
        if metadata is None:
            return web.json_response(
                {"error": "Conversation not found."},
                status=404,
            )
        if metadata.get("archived"):
            return web.json_response(
                {
                    "error": (
                        "This conversation is archived. Restore it before "
                        "opening a writable worker."
                    ),
                    "code": "conversation_archived",
                    "requires_restore": True,
                    "conversation_id": convo_id,
                },
                status=409,
            )
        section = str((metadata or {}).get("project_uuid") or "").strip() or None
        window_info = await cdp_manager.ensure_chat_window(
            convo_id,
            minimize=True,
            section=section,
        )
        return web.json_response({"success": True, "window": window_info})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=503)
    finally:
        await cdp_manager.close_all()


async def handle_get_antigravity_workers(request: web.Request) -> web.Response:
    """Return the live main window and bounded Hub worker pool."""
    del request
    from src.parallel_cdp import ParallelCDPManager
    from src.integrity_sync import scan_antigravity_conversation_catalog

    manager = ParallelCDPManager()
    try:
        snapshot, conversations = await asyncio.gather(
            manager.get_worker_pool_snapshot(),
            asyncio.to_thread(scan_antigravity_conversation_catalog),
        )
        by_id = {
            str(item.get("convo_id") or ""): item
            for item in conversations
            if item.get("convo_id")
        }
        rows = list(snapshot.get("workers") or [])
        if snapshot.get("primary"):
            rows.append(snapshot["primary"])
        for row in rows:
            metadata = by_id.get(str(row.get("chat_id") or ""))
            if metadata:
                row["chat"] = {
                    "convo_id": metadata.get("convo_id"),
                    "title": metadata.get("title"),
                    "status": metadata.get("status"),
                    "conversation_type": metadata.get("conversation_type"),
                    "project_name": metadata.get("project_name"),
                    "repository_name": metadata.get("repository_name"),
                }
        return web.json_response({"success": True, **snapshot})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=503)
    finally:
        await manager.close_all()


async def handle_get_antigravity_instances(request: web.Request) -> web.Response:
    """Return the canonical, read-only Anti-Gravity desktop instance model."""
    del request
    from src.instance_registry import build_instance_read_model
    from src.integrity_sync import scan_antigravity_conversation_catalog
    from src.parallel_cdp import MAX_WORKERS, ParallelCDPManager

    manager = ParallelCDPManager()
    try:
        snapshot_result, conversations_result = await asyncio.gather(
            manager.get_worker_pool_snapshot(),
            asyncio.to_thread(scan_antigravity_conversation_catalog),
            return_exceptions=True,
        )
        if isinstance(snapshot_result, asyncio.CancelledError):
            raise snapshot_result
        if isinstance(conversations_result, asyncio.CancelledError):
            raise conversations_result
        if isinstance(snapshot_result, Exception):
            snapshot = {
                "primary": None,
                "workers": [],
                "capacity": {"maximum": MAX_WORKERS, "queued": 0},
            }
        else:
            snapshot = snapshot_result
        conversations = (
            []
            if isinstance(conversations_result, Exception)
            else conversations_result
        )
        return web.json_response(
            build_instance_read_model(snapshot, conversations)
        )
    finally:
        try:
            await manager.close_all()
        except Exception:
            pass


async def handle_close_antigravity_worker(request: web.Request) -> web.Response:
    """Close one idle Hub worker by exact CDP target ID."""
    from src.parallel_cdp import ParallelCDPManager

    target_id = str(request.match_info.get("target_id") or "").strip()
    if not target_id:
        return web.json_response({"error": "A worker target ID is required."}, status=400)
    manager = ParallelCDPManager()
    try:
        result = await manager.close_worker_window(target_id)
        if not result.get("found"):
            return web.json_response({"error": "Worker not found."}, status=404)
        if result.get("not_idle"):
            return web.json_response(
                {
                    **result,
                    "error": (
                        "The worker is busy and cannot be closed."
                        if result.get("busy")
                        else "The worker is not confirmed idle and cannot be closed."
                    ),
                },
                status=409,
            )
        if result.get("busy"):
            return web.json_response(
                {
                    **result,
                    "error": "The worker is busy and cannot be closed.",
                },
                status=409,
            )
        if result.get("has_draft"):
            return web.json_response(
                {
                    **result,
                    "error": "The worker contains an unsent draft.",
                },
                status=409,
            )
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=503)
    finally:
        await manager.close_all()


_ANTIGRAVITY_CONVERSATION_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _antigravity_brain_directory(convo_id: str) -> Path:
    """Resolve one real conversation folder without allowing path traversal."""
    if not _ANTIGRAVITY_CONVERSATION_ID.fullmatch(str(convo_id or "")):
        raise ValueError("Invalid Anti-Gravity conversation ID.")
    root = (Path.home() / ".gemini" / "antigravity" / "brain").resolve()
    target = (root / convo_id).resolve()
    if target.parent != root:
        raise ValueError("Conversation folder is outside the Anti-Gravity brain.")
    return target


def _open_local_directory(path: Path) -> None:
    """Open a verified local directory with the operating-system file browser."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


async def handle_open_antigravity_brain_directory(
    request: web.Request,
) -> web.Response:
    """Open the verified Brain directory for one native Anti-Gravity chat."""
    try:
        convo_id = request.match_info["convo_id"]
        if convo_id.startswith(("proxy-", "provider-")):
            return web.json_response(
                {"error": "Hub-local provider chats do not have an Anti-Gravity Brain directory."},
                status=409,
            )
        target = _antigravity_brain_directory(convo_id)
        if not target.is_dir():
            return web.json_response(
                {"error": "For this conversation no Brain directory exists."},
                status=404,
            )
        await asyncio.to_thread(_open_local_directory, target)
        return web.json_response({
            "success": True,
            "convo_id": convo_id,
            "path": str(target),
        })
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except OSError as error:
        return web.json_response(
            {"error": f"File browser could not be opened: {error}"},
            status=503,
        )


async def handle_get_integrity_chat_history(request: web.Request) -> web.Response:
    """GET /api/integrity/chats/{convo_id}/history — Fetch chat message history."""
    try:
        convo_id = request.match_info["convo_id"]
        if convo_id.startswith(("proxy-", "provider-")):
            result = {"history": [], "max_idx": 0}
        else:
            from src.integrity_sync import get_integrity_chat_history
            result = get_integrity_chat_history(convo_id)

        for item in db.get_proxy_messages(convo_id):
            idx = 1_000_000_000 + int(item["id"])
            result["history"].append({
                "idx": idx,
                "type": "message",
                "role": item["role"],
                "content": item.get("content") or "",
                "attachments": item.get("attachments") or [],
                "model_name": item.get("model_name"),
                "source": "custom",
            })
            result["max_idx"] = max(result.get("max_idx", 0), idx)
        for item in db.get_provider_messages(convo_id):
            idx = 2_000_000_000 + int(item["id"])
            result["history"].append({
                "idx": idx,
                "type": "message",
                "role": item["role"],
                "content": item.get("content") or "",
                "attachments": item.get("attachments") or [],
                "model_name": item.get("model_name"),
                "source": item.get("provider_type") or "custom",
            })
            result["max_idx"] = max(result.get("max_idx", 0), idx)
        result["history"].sort(key=lambda entry: entry.get("idx", 0))
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_delete_integrity_chat(request: web.Request) -> web.Response:
    """Delete one normal, archived, project, or Hub-proxy conversation."""
    cdp_manager = None
    try:
        convo_id = str(request.match_info.get("convo_id") or "").strip()
        lowered_convo_id = convo_id.lower()
        if lowered_convo_id.startswith("provider-"):
            if not db.delete_provider_conversation(convo_id):
                return web.json_response({"error": "Chat not found"}, status=404)
            return web.json_response({
                "success": True,
                "conversation_id": convo_id,
                "source": "provider",
            })
        if lowered_convo_id.startswith("proxy-"):
            if not db.delete_proxy_conversation(convo_id):
                return web.json_response({"error": "Chat not found"}, status=404)
            return web.json_response({
                "success": True,
                "conversation_id": convo_id,
                "source": "custom",
            })
        else:
            from src.integrity_sync import delete_integrity_convo

            from src.parallel_cdp import ParallelCDPManager
            convo_id = lowered_convo_id
            if not ANTIGRAVITY_CONVERSATION_ID_RE.fullmatch(convo_id):
                raise ValueError("Invalid Anti-Gravity conversation ID.")
            cdp_manager = ParallelCDPManager()
            deletion_gate = await cdp_manager.prepare_chat_deletion(
                convo_id,
                delete_callback=delete_integrity_convo,
            )
            if not deletion_gate.get("allowed"):
                code = str(
                    deletion_gate.get("code")
                    or "conversation_state_unavailable"
                )
                is_busy = code == "conversation_busy"
                payload = {
                    "success": False,
                    "error": (
                        "Conversation is active in Anti-Gravity and cannot be deleted."
                        if is_busy
                        else "Conversation state could not be verified."
                    ),
                    "code": code,
                    "conversation_id": convo_id,
                    "retryable": True,
                    "detail_code": str(
                        deletion_gate.get("detail_code")
                        or (
                            "conversation_busy"
                            if is_busy
                            else "desktop_state_unavailable"
                        )
                    ),
                }
                worker_status = deletion_gate.get("worker")
                if isinstance(worker_status, dict):
                    payload["worker"] = {
                        "instance_id": worker_status.get("instance_id"),
                        "activity": worker_status.get("activity"),
                        "detail_code": worker_status.get("detail_code"),
                        "has_draft": bool(worker_status.get("has_draft")),
                        "binding_status": worker_status.get("binding_status"),
                    }
                return web.json_response(payload, status=409 if is_busy else 503)
            window_closed = bool(deletion_gate.get("window_closed"))
            result = deletion_gate.get("deletion_result") or {}
            if not result.get("found"):
                return web.json_response({"error": "Chat not found"}, status=404)
            native_removed = bool(result.get("grpc_confirmed")) and (
                result.get("summary_present") is False
            )
            if native_removed:
                db.upsert_managed_antigravity_conversation(
                    convo_id,
                    state="deleted",
                )
                _invalidate_live_sidebar_cache()
            public_result = {
                "found": bool(result.get("found")),
                "conversation_id": convo_id,
                "grpc_http_status": result.get("grpc_http_status"),
                "grpc_status": result.get("grpc_status"),
                "grpc_confirmed": bool(result.get("grpc_confirmed")),
                "native_method": result.get("native_method"),
                "summary_present": result.get("summary_present"),
                "removed_file_count": len(result.get("removed_files") or []),
                "remaining_file_count": len(result.get("remaining_files") or []),
            }
            if not result.get("success"):
                error_code = str(
                    result.get("code") or "conversation_delete_incomplete"
                )
                return web.json_response(
                    {
                        "error": (
                            "Native conversation deletion could not be confirmed."
                            if error_code == "native_delete_unconfirmed"
                            else (
                                "The native conversation was removed, but local cleanup is incomplete."
                                if error_code == "local_cleanup_incomplete"
                                else "Conversation deletion is incomplete."
                            )
                        ),
                        "code": error_code,
                        "conversation_id": convo_id,
                        "window_closed": window_closed,
                        **public_result,
                    },
                    status=503,
                )
            db.delete_proxy_messages(convo_id)
            db.delete_provider_messages(convo_id)
            if not native_removed:
                db.upsert_managed_antigravity_conversation(
                    convo_id,
                    state="deleted",
                )
                _invalidate_live_sidebar_cache()
            return web.json_response({
                **public_result,
                "success": True,
                "window_closed": window_closed,
                "source": "antigravity",
            })
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)
    finally:
        if cdp_manager is not None:
            await cdp_manager.close_all()


async def _set_antigravity_conversation_archived(
    request: web.Request,
    *,
    archived: bool,
) -> web.Response:
    """Change one native conversation's archive state through Anti-Gravity."""
    convo_id = str(request.match_info.get("convo_id") or "").strip().lower()
    if convo_id.startswith("provider-"):
        if not db.set_provider_conversation_archived(convo_id, archived):
            return web.json_response({"error": "Conversation not found."}, status=404)
        return web.json_response({
            "success": True,
            "verified": True,
            "conversation_id": convo_id,
            "archived": archived,
            "source": "provider",
        })
    if not ANTIGRAVITY_CONVERSATION_ID_RE.fullmatch(convo_id):
        return web.json_response(
            {"error": "A valid Anti-Gravity conversation ID is required."},
            status=400,
        )

    from src.integrity_sync import scan_antigravity_conversation_catalog

    conversations = await asyncio.to_thread(
        scan_antigravity_conversation_catalog
    )
    metadata = next(
        (
            item
            for item in conversations
            if str(item.get("convo_id") or "").lower() == convo_id
        ),
        None,
    )
    if metadata is None:
        return web.json_response({"error": "Conversation not found."}, status=404)
    if bool(metadata.get("archived")) is archived:
        db.set_managed_antigravity_conversation_state(
            convo_id,
            "archived" if archived else "active",
        )
        _invalidate_live_sidebar_cache()
        return web.json_response({
            "success": True,
            "verified": True,
            "unchanged": True,
            "conversation_id": convo_id,
            "archived": archived,
        })

    from src.parallel_cdp import ParallelCDPManager

    manager = ParallelCDPManager()
    try:
        section = str(metadata.get("project_uuid") or "").strip() or None
        window = await manager.set_chat_archived(
            convo_id,
            archived,
            section=section,
            minimize=True,
        )
        db.set_managed_antigravity_conversation_state(
            convo_id,
            "archived" if archived else "active",
        )
        _invalidate_live_sidebar_cache()
        return web.json_response({
            "success": True,
            "verified": True,
            "conversation_id": convo_id,
            "archived": archived,
            "window": window,
        })
    except Exception as error:
        return web.json_response(
            {
                "error": (
                    "Anti-Gravity could not confirm the archive state: "
                    f"{error}"
                )
            },
            status=503,
        )
    finally:
        await manager.close_all()


async def handle_archive_antigravity_conversation(
    request: web.Request,
) -> web.Response:
    return await _set_antigravity_conversation_archived(
        request,
        archived=True,
    )


async def handle_restore_antigravity_conversation(
    request: web.Request,
) -> web.Response:
    return await _set_antigravity_conversation_archived(
        request,
        archived=False,
    )


async def handle_send_integrity_message(request: web.Request) -> web.Response:
    """Send a message only after its dedicated window is ready and delivery is verified."""
    cdp_manager = None
    try:
        convo_id = request.match_info["convo_id"]
        body = await request.json()
        message_value = body.get("message")
        if message_value is not None and not isinstance(message_value, str):
            return web.json_response(
                {"error": "message must be a string"},
                status=400,
            )
        message = message_value or ""
        attachments = body.get("attachments")
        if attachments is None:
            attachments = []

        if not convo_id or convo_id == "new":
            return web.json_response({"error": "A stable conversation ID is required."}, status=400)
        if not message.strip() and not attachments:
            return web.json_response({"error": "Message or attachment is required."}, status=400)

        if db.get_provider_conversation(convo_id) or db.get_provider_preference(convo_id):
            from src.provider_chat_handlers import handle_send_provider_message

            return await handle_send_provider_message(request)
        if convo_id.startswith("proxy-") or db.get_custom_model_preference(convo_id):
            from src.custom_model_handlers import handle_send_proxy_message

            return await handle_send_proxy_message(request)

        from src.integrity_sync import (
            get_integrity_chat_history,
            record_web_sent_message,
            scan_antigravity_conversation_catalog,
        )
        record_web_sent_message(convo_id, message)
        conversations = await asyncio.to_thread(
            scan_antigravity_conversation_catalog
        )
        metadata = next(
            (item for item in conversations if item.get("convo_id") == convo_id),
            None,
        )
        if metadata is None:
            return web.json_response(
                {"error": "Conversation not found."},
                status=404,
            )
        if metadata.get("archived"):
            return web.json_response(
                {
                    "error": (
                        "This conversation is archived. Restore it before "
                        "sending a message."
                    ),
                    "code": "conversation_archived",
                    "requires_restore": True,
                    "conversation_id": convo_id,
                },
                status=409,
            )
        before = await asyncio.to_thread(get_integrity_chat_history, convo_id)
        before_max_idx = int(before.get("max_idx") or 0)
        section = str((metadata or {}).get("project_uuid") or "").strip() or None

        # A message is sent only through the exact dedicated Anti-Gravity window.
        from src.parallel_cdp import ParallelCDPManager
        cdp_manager = ParallelCDPManager()

        try:
            saved_attachments = _save_chat_attachments(
                attachments,
                storage_key=convo_id,
            )
        except ValueError as attachment_error:
            return web.json_response(
                {"error": str(attachment_error)},
                status=400,
            )

        try:
            window_info = await cdp_manager.send_message_to_chat(
                convo_id,
                message,
                section=section,
                minimize=True,
                attachment_paths=[
                    item["file_path"] for item in saved_attachments
                ],
            )
        except Exception as window_exc:
            return web.json_response(
                {
                    "error": (
                        "Dedicated Anti-Gravity chat delivery failed: "
                        f"{window_exc}"
                    )
                },
                status=503,
            )

        verified_entry = None
        for _ in range(40):
            history_result = await asyncio.to_thread(get_integrity_chat_history, convo_id)
            verified_entry = next(
                (
                    entry for entry in history_result.get("history", [])
                    if entry.get("role") == "user"
                    and int(entry.get("idx") or 0) > before_max_idx
                    and str(entry.get("content") or "").strip() == message.strip()
                    and (
                        not saved_attachments
                        or len(entry.get("attachments") or [])
                        >= len(saved_attachments)
                    )
                ),
                None,
            )
            if verified_entry:
                break
            await asyncio.sleep(0.25)

        if not verified_entry:
            return web.json_response(
                {
                    "success": True,
                    "accepted": True,
                    "sent": True,
                    "verified": False,
                    "pending_verification": True,
                    "conversation_id": convo_id,
                    "window": window_info,
                },
                status=202,
            )

        return web.json_response(
            {
                "success": True,
                "verified": True,
                "verified_idx": verified_entry["idx"],
                "conversation_id": convo_id,
                "window": window_info,
                "method": "AntiGravityDuplicateWindow",
            }
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)
    finally:
        if cdp_manager is not None:
            await cdp_manager.close_all()


async def handle_get_integrity_media(request: web.Request) -> web.Response:
    """GET /api/integrity/media?path=... — Serve images safely from the brain directory."""
    try:
        path_str = request.query.get("path")
        if not path_str:
            return web.Response(status=400, text="path query parameter is required")

        file_path = Path(path_str).resolve()

        # Resolve both paths before the containment check so sibling prefixes,
        # symlinks, and junctions cannot escape the managed media directory.
        allowed_root = (
            Path.home() / ".gemini" / "antigravity" / "brain"
        ).resolve()
        if not file_path.is_relative_to(allowed_root):
            return web.Response(status=403, text="Access denied")

        if not file_path.exists() or not file_path.is_file():
            return web.Response(status=404, text="File not found")

        # Determine content type
        mime = "application/octet-stream"
        ext = file_path.suffix.lower()
        if ext in (".png", ".apng"): mime = "image/png"
        elif ext in (".jpg", ".jpeg"): mime = "image/jpeg"
        elif ext == ".gif": mime = "image/gif"
        elif ext == ".webp": mime = "image/webp"

        with open(file_path, "rb") as f:
            data = f.read()

        return web.Response(body=data, content_type=mime)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def fetch_real_quota():
    """Queries the real language server gRPC-web service for RetrieveUserQuotaSummary."""
    import http.client
    import json
    from src.integrity_sync import get_ls_grpc_port

    ls_port = get_ls_grpc_port()
    if not ls_port:
        return None

    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")

    body_str = '{"forceRefresh":false}'
    body_bytes = body_str.encode('utf-8')
    len_val = len(body_bytes)

    header = bytes([
        0,
        (len_val >> 24) & 0xff,
        (len_val >> 16) & 0xff,
        (len_val >> 8) & 0xff,
        len_val & 0xff
    ])
    body = header + body_bytes

    try:
        conn = http.client.HTTPConnection("127.0.0.1", ls_port, timeout=3)
        conn.request(
            "POST",
            "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
            body=body,
            headers={
                "content-type": "application/grpc-web+json",
                "x-grpc-web": "1",
                "x-codeium-csrf-token": csrf
            }
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()

        if len(data) > 5:
            json_data = data[5:].decode('utf-8', errors='ignore')
            json_start = json_data.find('{')
            json_end = json_data.rfind('}')
            if json_start != -1 and json_end != -1:
                return json.loads(json_data[json_start:json_end+1])
    except Exception as e:
        print(f"[Quota] Failed to query real language server quota: {e}", flush=True)
    return None


async def handle_get_integrity_quota(request: web.Request) -> web.Response:
    """GET /api/integrity/quota — Returns either the real language server quota or a realistic fallback."""
    try:
        quota = fetch_real_quota()
        if quota:
            return web.json_response(quota)

        # Realistic mock fallback
        fallback = {
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini",
                        "buckets": [
                            {"window": "weekly", "remainingFraction": 0.83, "description": "resets in 2d 12h"},
                            {"window": "5h", "remainingFraction": 0.91, "description": "resets in 4h 12m"}
                        ]
                    },
                    {
                        "displayName": "Claude",
                        "buckets": [
                            {"window": "weekly", "remainingFraction": 1.0, "description": "resets in 5d 2h"},
                            {"window": "5h", "remainingFraction": 1.0, "description": "resets in 3h 1m"}
                        ]
                    }
                ]
            }
        }
        return web.json_response(fallback)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def fetch_real_models():
    """Queries the real language server gRPC-web service for GetUserStatus to extract available models."""
    import http.client
    import json
    from src.integrity_sync import get_ls_grpc_port

    ls_port = get_ls_grpc_port()
    if not ls_port:
        return None

    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")

    # Empty request body for GetUserStatus
    body_str = '{}'
    body_bytes = body_str.encode('utf-8')
    len_val = len(body_bytes)

    header = bytes([
        0,
        (len_val >> 24) & 0xff,
        (len_val >> 16) & 0xff,
        (len_val >> 8) & 0xff,
        len_val & 0xff
    ])
    body = header + body_bytes

    try:
        conn = http.client.HTTPConnection("127.0.0.1", ls_port, timeout=5)
        conn.request(
            "POST",
            "/exa.language_server_pb.LanguageServerService/GetUserStatus",
            body=body,
            headers={
                "content-type": "application/grpc-web+json",
                "x-grpc-web": "1",
                "x-codeium-csrf-token": csrf
            }
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()

        if len(data) > 5:
            json_data = data[5:].decode('utf-8', errors='ignore')
            json_start = json_data.find('{')
            json_end = json_data.rfind('}')
            if json_start != -1 and json_end != -1:
                parsed = json.loads(json_data[json_start:json_end+1])
                # Extract model configs from userStatus.cascadeModelConfigData.clientModelConfigs
                user_status = parsed.get("userStatus", {})
                model_config_data = user_status.get("cascadeModelConfigData", {})
                client_configs = model_config_data.get("clientModelConfigs", [])

                models = []
                for cfg in client_configs:
                    label = cfg.get("label", "")
                    if label:
                        badge = cfg.get("badge", "")
                        models.append({
                            "label": label,
                            "badge": badge
                        })

                if models:
                    return models
    except Exception as e:
        print(f"[Models] Failed to query real language server models: {e}", flush=True)
    return None


_NATIVE_MODEL_CACHE: Dict[str, Any] = {
    "models": [],
    "current": "",
    "source": "",
    "updated_at": 0.0,
}


async def handle_get_integrity_models(request: web.Request) -> web.Response:
    """Return the native Anti-Gravity combobox plus configured proxy models."""
    manager = None
    try:
        now = asyncio.get_running_loop().time()
        native_models: List[Dict[str, Any]] = []
        current_model = ""
        source = "native_combobox"
        stale = False
        native_error = ""

        cache_age = now - float(_NATIVE_MODEL_CACHE.get("updated_at") or 0)
        if _NATIVE_MODEL_CACHE["models"] and cache_age < 10:
            native_models = list(_NATIVE_MODEL_CACHE["models"])
            current_model = str(_NATIVE_MODEL_CACHE.get("current") or "")
            source = str(_NATIVE_MODEL_CACHE.get("source") or "model") + "_cache"
        else:
            try:
                from src.parallel_cdp import ParallelCDPManager

                manager = ParallelCDPManager()
                native = await asyncio.wait_for(
                    manager.read_native_models_from_primary(),
                    timeout=12,
                )
                native_models = list(native.get("models") or [])
                current_model = str(native.get("current") or "")
                _NATIVE_MODEL_CACHE.update({
                    "models": native_models,
                    "current": current_model,
                    "source": "native_combobox",
                    "updated_at": now,
                })
            except Exception as error:
                native_error = str(error)
                print(
                    f"[Models] Native combobox read failed: {native_error}",
                    flush=True,
                )

        if not native_models:
            language_server_models = await asyncio.to_thread(fetch_real_models)
            if language_server_models:
                native_models = language_server_models
                source = "language_server"
                _NATIVE_MODEL_CACHE.update({
                    "models": native_models,
                    "current": current_model,
                    "source": "language_server",
                    "updated_at": now,
                })
            elif _NATIVE_MODEL_CACHE["models"]:
                native_models = list(_NATIVE_MODEL_CACHE["models"])
                current_model = str(_NATIVE_MODEL_CACHE.get("current") or "")
                source = str(_NATIVE_MODEL_CACHE.get("source") or "model") + "_cache"
                stale = True
            else:
                source = "unavailable"

        models = []
        seen = set()
        for native_model in native_models:
            label = str(native_model.get("label") or "").strip()
            key = label.casefold()
            if not label or key in seen:
                continue
            seen.add(key)
            models.append({
                "label": label,
                "badge": str(native_model.get("badge") or ""),
                "source": "official",
                "model_id": label,
                "selection_id": f"native:{label}",
            })

        for custom in db.list_custom_models():
            models.append({
                "label": custom["name"],
                "badge": "Proxy",
                "source": "custom",
                "custom_model_id": custom["id"],
                "model_id": custom["model_id"],
                "base_url": custom["base_url"],
                "selection_id": f"custom:{custom['id']}",
            })
        codex_error = ""
        try:
            from src.codex_app_server import get_codex_manager

            codex_status = await asyncio.to_thread(get_codex_manager().status)
            if codex_status.get("authenticated"):
                codex_models = await asyncio.wait_for(
                    asyncio.to_thread(get_codex_manager().list_models),
                    timeout=12,
                )
                for codex_model in codex_models:
                    model_id = str(codex_model.get("model") or codex_model.get("id") or "").strip()
                    if not model_id:
                        continue
                    display_name = str(codex_model.get("display_name") or model_id).strip()
                    models.append({
                        "label": f"Codex · {display_name}",
                        "badge": "Codex",
                        "source": "codex",
                        "model_id": model_id,
                        "selection_id": f"codex:{model_id}",
                        "default_reasoning_effort": str(codex_model.get("default_reasoning_effort") or ""),
                        "supported_reasoning_efforts": [
                            str(item.get("value") or "")
                            for item in codex_model.get("supported_reasoning_efforts") or []
                            if isinstance(item, dict) and item.get("value")
                        ],
                    })
        except Exception as error:
            codex_error = str(error)
        return web.json_response({
            "models": models,
            "current": current_model,
            "source": source,
            "stale": stale,
            "native_error": native_error,
            "codex_error": codex_error,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    finally:
        if manager is not None:
            await manager.disconnect_all()


async def handle_get_integrity_tokens(request: web.Request) -> web.Response:
    """GET /api/integrity/tokens/{convo_id} — Returns real token stats by running get_token_stats.py."""
    try:
        convo_id = request.match_info['convo_id']
        if not convo_id:
            return web.json_response({"error": "convo_id required"}, status=400)

        convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
        db_path = convo_dir / f"{convo_id}.db"

        if not db_path.exists():
            return web.json_response({"totalInput": 0, "totalOutput": 0, "cacheRatio": 0})

        script_path = Path.home() / ".gemini" / "config" / "skills" / "antigravity_desktop_ui_modifier" / "scripts" / "get_token_stats.py"

        if not script_path.exists():
            return web.json_response({"totalInput": 0, "totalOutput": 0, "cacheRatio": 0, "error": "script_missing"})

        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "python", str(script_path), str(db_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home())
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0 and stdout:
            import json as json_mod
            data = json_mod.loads(stdout.decode('utf-8').strip())
            return web.json_response(data)
        else:
            return web.json_response({"totalInput": 0, "totalOutput": 0, "cacheRatio": 0})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_stream_integrity_chat(request: web.Request) -> web.Response:
    """GET /api/integrity/chats/{convo_id}/stream — SSE stream of new chat steps (polled every 250ms)."""
    import asyncio
    import json as json_mod

    convo_id = request.match_info["convo_id"]
    last_idx = int(request.query.get("after", "0"))

    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
    db_path = convo_dir / f"{convo_id}.db"

    heartbeat_count = 0
    idle_count = 0
    max_idle = 1200  # ~5 minutes of idle before closing (1200 * 250ms)
    completed_assistant_quiet_cycles = 0
    completed_assistant_grace_cycles = 6  # 1.5s for a possible follow-up step.

    from src.integrity_sync import (
        extract_step_timing,
        get_user_prompt_from_payload,
        get_agent_response_from_payload,
        parse_tool_call,
        parse_tool_output
    )

    last_sent_content = {}

    try:
        while True:
            if not db_path.exists():
                await asyncio.sleep(0.5)
                idle_count += 2
                if idle_count >= max_idle:
                    break
                continue

            try:
                import sqlite3
                db_uri = str(db_path.resolve()).replace('\\', '/')
                conn = sqlite3.connect(f"file:{db_uri}?mode=ro", uri=True)
                # Keep polling earlier background commands while allowing newer
                # conversation steps to stream past a long-running server.
                query_suffix = (
                    "FROM steps WHERE idx >= ? "
                    "OR (step_type IN (17, 21) AND status = 2) "
                    "ORDER BY idx ASC"
                )
                try:
                    rows = conn.execute(
                        "SELECT idx, step_type, step_payload, status, metadata "
                        + query_suffix,
                        (last_idx,),
                    ).fetchall()
                except sqlite3.OperationalError as error:
                    if "metadata" not in str(error).lower():
                        raise
                    legacy_rows = conn.execute(
                        "SELECT idx, step_type, step_payload, status " + query_suffix,
                        (last_idx,),
                    ).fetchall()
                    rows = [(*row, None) for row in legacy_rows]
                latest_step = conn.execute(
                    "SELECT idx, step_type, status FROM steps ORDER BY idx DESC LIMIT 1"
                ).fetchone()
                conn.close()
                latest_is_completed_assistant = bool(
                    latest_step
                    and latest_step[1] == 15
                    and latest_step[2] in (3, 7)
                )
                emitted_event = False

                if rows:
                    idle_count = 0
                    new_last_idx = last_idx
                    for idx, stype, payload, status, metadata in rows:
                        event_data = None
                        is_background_task = False
                        timing = extract_step_timing(metadata, status)

                        if stype == 14:
                            txt, atts = get_user_prompt_from_payload(payload)
                            current_state = (txt, str(atts))
                            if last_sent_content.get(idx) != current_state:
                                event_data = {
                                    "idx": idx,
                                    "type": "message",
                                    "role": "user",
                                    "content": txt,
                                    "attachments": atts
                                }
                                last_sent_content[idx] = current_state
                        elif stype == 15:
                            txt, thinking = get_agent_response_from_payload(payload)
                            current_state = (txt, thinking)
                            if last_sent_content.get(idx) != current_state:
                                event_data = {
                                    "idx": idx,
                                    "type": "message",
                                    "role": "assistant",
                                    "content": txt,
                                    "thinking": thinking,
                                    "complete": status in (3, 7),
                                }
                                last_sent_content[idx] = current_state
                        elif stype in (17, 21):
                            tname, targs = parse_tool_call(payload)
                            current_state = (tname, targs, status)
                            if last_sent_content.get(idx) != current_state:
                                from src.integrity_sync import enrich_tool_call
                                enriched = enrich_tool_call(tname, targs, status)
                                event_data = {
                                    "idx": idx,
                                    "type": "tool_call",
                                    "tool_name": tname,
                                    "args": targs,
                                    "status": status,
                                    "is_running": status == 2,
                                    "complete": status in (3, 7),
                                    "requires_user_input": status == 9,
                                }
                                if enriched:
                                    event_data["enriched"] = enriched
                                    is_background_task = bool(
                                        enriched.get("background_task")
                                    )
                                last_sent_content[idx] = current_state
                        elif stype in (8, 9):
                            tout = parse_tool_output(payload, stype)
                            current_state = tout
                            if last_sent_content.get(idx) != current_state:
                                event_data = {
                                    "idx": idx,
                                    "type": "tool_output",
                                    "output": tout[:2000] if len(tout) > 2000 else tout
                                }
                                last_sent_content[idx] = current_state
                        elif stype == 5:
                            current_state = "permission_request"
                            if last_sent_content.get(idx) != current_state:
                                event_data = {
                                    "idx": idx,
                                    "type": "status",
                                    "status": "permission_request"
                                }
                                last_sent_content[idx] = current_state

                        if event_data:
                            event_data.update(timing)
                            sse = f"data: {json_mod.dumps(event_data, ensure_ascii=False)}\n\n"
                            await response.write(sse.encode("utf-8"))
                            emitted_event = True

                        if idx < last_idx:
                            continue

                        # A long-running server is a tracked background task,
                        # not a barrier for newer assistant/tool steps.
                        if status in (3, 7) or is_background_task:
                            new_last_idx = max(new_last_idx, idx + 1)
                        else:
                            new_last_idx = idx
                            break

                    last_idx = new_last_idx
                else:
                    idle_count += 1

                if latest_is_completed_assistant:
                    completed_assistant_quiet_cycles = (
                        0 if emitted_event
                        else completed_assistant_quiet_cycles + 1
                    )
                else:
                    completed_assistant_quiet_cycles = 0

            except Exception as db_err:
                # DB locked or not ready, just wait
                idle_count += 1

            # Heartbeat every 20 cycles (~5s)
            heartbeat_count += 1
            if heartbeat_count >= 20:
                heartbeat_count = 0
                await response.write(b": heartbeat\n\n")

            if completed_assistant_quiet_cycles >= completed_assistant_grace_cycles:
                await response.write(b"data: {\"type\": \"stream_end\", \"reason\": \"assistant_complete\"}\n\n")
                break

            if idle_count >= max_idle:
                await response.write(b"data: {\"type\": \"stream_end\", \"reason\": \"idle_timeout\"}\n\n")
                break

            await asyncio.sleep(0.25)  # 250ms polling

    except (ConnectionResetError, asyncio.CancelledError):
        pass

    return response


def get_active_model_from_gen_metadata(convo_id=None):
    """Reads the model name from the last gen_metadata entry of the most recent conversation."""
    import sqlite3
    import json as json_mod

    convo_dir = Path.home() / ".gemini" / "antigravity" / "conversations"

    if convo_id:
        db_paths = [convo_dir / f"{convo_id}.db"]
    else:
        # Find most recently modified .db
        if not convo_dir.exists():
            return None
        db_files = sorted(convo_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        db_paths = db_files[:3]  # Check last 3 recent convos

    # Import get_token_stats parser for protobuf field extraction
    script_path = Path.home() / ".gemini" / "config" / "skills" / "antigravity_desktop_ui_modifier" / "scripts" / "get_token_stats.py"

    for db_path in db_paths:
        if not db_path.exists():
            continue
        try:
            db_uri = str(db_path.resolve()).replace('\\', '/')
            conn = sqlite3.connect(f"file:{db_uri}?mode=ro", uri=True)
            rows = conn.execute("SELECT data FROM gen_metadata ORDER BY idx DESC LIMIT 1").fetchall()
            conn.close()

            if rows and rows[0][0]:
                data = rows[0][0]
                # Try to extract model name from protobuf
                # The model name is typically a UTF-8 string inside field 1 -> subfield
                # Look for readable model name patterns
                text = data.decode('utf-8', errors='ignore')
                import re
                patterns = [
                    r'(Gemini \d[\d.]+ (?:Flash|Pro) \([^)]+\))',
                    r'(Claude (?:Sonnet|Opus|Haiku) [\d.]+ \([^)]+\))',
                    r'(GPT-[\w]+ [\d]+B \([^)]+\))',
                ]
                for pat in patterns:
                    match = re.search(pat, text)
                    if match:
                        return match.group(1)
        except Exception:
            continue
    return None


async def handle_get_active_model(request: web.Request) -> web.Response:
    """GET /api/integrity/active-model — Returns the currently active model name.
    Conversation-scoped preferences are authoritative. The global preload status
    is only a fallback when no conversation was requested.
    """
    try:
        import json as json_mod

        convo_id = request.query.get("convo_id")
        if convo_id:
            provider = db.get_provider_conversation(convo_id) or db.get_provider_preference(convo_id)
            if provider:
                provider_type = str(provider.get("provider_type") or "custom")
                model_id = str(provider.get("model_id") or "")
                display_name = str(provider.get("display_name") or model_id)
                return web.json_response({
                    "model": display_name,
                    "source": provider_type,
                    "selection_id": f"{provider_type}:{model_id if provider_type == 'codex' else provider.get('custom_model_id')}",
                    "custom_model_id": provider.get("custom_model_id"),
                    "model_id": model_id,
                    "reasoning_effort": provider.get("reasoning_effort") or "",
                    "confirmed": True,
                })
            custom = db.get_custom_model_preference(convo_id)
            if custom:
                return web.json_response({
                    "model": custom["name"],
                    "source": "custom",
                    "custom_model_id": custom["id"],
                    "model_id": custom["model_id"],
                    "selection_id": f"custom:{custom['id']}",
                    "confirmed": True,
                })
            native = db.get_native_model_preference(convo_id)
            if native:
                return web.json_response({
                    "model": native["model_name"],
                    "source": "native_preference",
                    "window_id": native.get("window_id"),
                    "confirmed": True,
                    "selection_id": f"native:{native['model_name']}",
                })

            model = get_active_model_from_gen_metadata(convo_id)
            if model:
                return web.json_response({
                    "model": model,
                    "source": "gen_metadata",
                    "confirmed": True,
                    "selection_id": f"native:{model}",
                })
            return web.json_response({
                "model": None,
                "source": "unavailable",
                "confirmed": False,
            })

        # The preload file describes one app-wide foreground state. It is safe
        # only for legacy callers that did not request a specific conversation.
        status_file = Path.home() / ".gemini" / "antigravity" / "active_model_status.json"
        if status_file.exists():
            try:
                data = json_mod.loads(status_file.read_text(encoding='utf-8'))
                model = data.get("model")
                if model:
                    return web.json_response({
                        "model": model,
                        "source": "preload",
                        "confirmed": False,
                    })
            except Exception:
                pass

        return web.json_response({
            "model": None,
            "source": "unavailable",
            "confirmed": False,
        })
    except Exception as e:
        return web.json_response(
            {"error": str(e), "model": None, "source": "unavailable"},
            status=503,
        )


async def handle_set_active_model(request: web.Request) -> web.Response:
    """Switch a model in the exact AG worker and return only after confirmation."""
    cdp_manager = None
    try:
        import json as json_mod

        body = await request.json()
        model_name = body.get("model")
        if not model_name:
            return web.json_response({"error": "model required"}, status=400)

        convo_id = str(body.get("convo_id") or "")
        custom_model_id = body.get("custom_model_id")
        requested_source = str(body.get("source") or "").strip().lower()
        if requested_source in {"custom", "codex"} or custom_model_id:
            from src.codex_app_server import CodexAppServerError
            from src.provider_chat_handlers import (
                ProviderChatError,
                resolve_provider_selection,
            )

            selection_body = dict(body)
            if not requested_source and custom_model_id:
                selection_body["source"] = "custom"
            try:
                selection = await resolve_provider_selection(selection_body)
            except ProviderChatError as error:
                return web.json_response({"error": str(error)}, status=400)
            except CodexAppServerError as error:
                return web.json_response(
                    {"error": error.public_message, "code": error.code},
                    status=503,
                )
            local_provider_chat = db.get_provider_conversation(convo_id) if convo_id else None
            if local_provider_chat:
                db.update_provider_conversation_model(
                    convo_id,
                    provider_type=selection["provider_type"],
                    custom_model_id=selection["custom_model_id"],
                    model_id=selection["model_id"],
                    display_name=selection["display_name"],
                    reasoning_effort=selection["reasoning_effort"],
                    external_thread_id="",
                )
            if convo_id and convo_id != "new":
                if not local_provider_chat:
                    db.set_provider_preference(
                        convo_id,
                        provider_type=selection["provider_type"],
                        custom_model_id=selection["custom_model_id"],
                        model_id=selection["model_id"],
                        display_name=selection["display_name"],
                        reasoning_effort=selection["reasoning_effort"],
                        external_thread_id="",
                    )
                db.clear_custom_model_preference(convo_id)
                db.clear_native_model_preference(convo_id)
            return web.json_response({
                "success": True,
                "model": selection["display_name"],
                "source": selection["provider_type"],
                "selection_id": f"{selection['provider_type']}:{selection['model_id'] if selection['provider_type'] == 'codex' else selection['custom_model_id']}",
                "custom_model_id": selection["custom_model_id"],
                "model_id": selection["model_id"],
                "reasoning_effort": selection["reasoning_effort"],
                "method": "hub_proxy",
                "confirmed": True,
            })

        if convo_id.startswith(("proxy-", "provider-")):
            return web.json_response(
                {"error": "Proxy chats cannot switch to an Antigravity model. Start a new chat instead."},
                status=409,
            )

        if convo_id and convo_id != "new":
            from src.integrity_sync import scan_antigravity_conversation_catalog
            from src.parallel_cdp import ParallelCDPManager

            conversations = await asyncio.to_thread(
                scan_antigravity_conversation_catalog
            )
            metadata = next(
                (
                    item
                    for item in conversations
                    if item.get("convo_id") == convo_id
                ),
                None,
            )
            section = str((metadata or {}).get("project_uuid") or "").strip() or None
            cdp_manager = ParallelCDPManager()
            window = await cdp_manager.select_model_for_chat(
                convo_id,
                str(model_name),
                section=section,
                minimize=True,
            )
            confirmed_model = str(window.get("model") or model_name)
            db.clear_custom_model_preference(convo_id)
            db.clear_provider_preference(convo_id)
            db.set_native_model_preference(
                convo_id,
                confirmed_model,
                str(window.get("window_id") or "") or None,
            )
            return web.json_response({
                "success": True,
                "model": confirmed_model,
                "source": "native",
                "method": "dedicated_cdp",
                "confirmed": True,
                "selection_id": f"native:{confirmed_model}",
                "window": window,
            })

        # Legacy/new-chat fallback: no stable conversation exists to bind to a
        # dedicated worker yet, so the preload bridge can only queue the choice.
        switch_file = Path.home() / ".gemini" / "antigravity" / "model_switch_request.json"
        switch_file.parent.mkdir(parents=True, exist_ok=True)
        switch_file.write_text(
            json_mod.dumps({
                "model": model_name,
                "convo_id": convo_id or None,
                "timestamp": int(os.environ.get("TIMESTAMP", 0))
                or __import__('time').time(),
            }),
            encoding='utf-8'
        )

        print(f"[ModelSync] Wrote model switch request: {model_name}", flush=True)
        return web.json_response({
            "success": True,
            "model": model_name,
            "method": "file_bridge",
            "confirmed": False,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    finally:
        if cdp_manager is not None:
            await cdp_manager.close_all()


async def handle_get_available_models(request: web.Request) -> web.Response:
    """Backward-compatible alias for the dynamic Anti-Gravity model catalog."""
    return await handle_get_integrity_models(request)
