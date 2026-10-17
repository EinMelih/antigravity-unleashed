"""HTTP handlers for Hub-managed OpenAI-compatible custom models."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from typing import Any, Dict, Iterable, List

from aiohttp import web

from src.custom_model_proxy import (
    CustomModelError,
    protect_extra_headers,
    protect_secret,
    public_provider,
    send_chat_completion,
    test_provider,
    unprotect_extra_headers,
    validate_provider_payload,
)
from src.database import db


def _error_response(error: Exception, status: int = 400) -> web.Response:
    return web.json_response({"error": str(error)}, status=status)


def _provider(custom_model_id: int) -> Dict[str, Any]:
    provider = db.get_custom_model(custom_model_id)
    if not provider:
        raise CustomModelError("Custom model not found.")
    return provider


def _message_content(message: str, attachments: Iterable[Dict[str, Any]]) -> Any:
    """Build OpenAI-compatible text/image content without forwarding local paths."""
    safe_images: List[Dict[str, Any]] = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        data = str(attachment.get("data") or "")
        media_type = str(attachment.get("type") or "")
        if data.startswith("data:image/") or (media_type.startswith("image/") and data.startswith("data:")):
            safe_images.append({"type": "image_url", "image_url": {"url": data}})
    if not safe_images:
        return message
    content: List[Dict[str, Any]] = []
    if message:
        content.append({"type": "text", "text": message})
    content.extend(safe_images)
    return content


def _context_messages(conversation_id: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    if not conversation_id.startswith("proxy-"):
        from src.integrity_sync import get_integrity_chat_history

        history = get_integrity_chat_history(conversation_id).get("history", [])
        for entry in history:
            if entry.get("type") != "message" or entry.get("role") not in {"user", "assistant"}:
                continue
            content = str(entry.get("content") or "")
            attachments = entry.get("attachments") if entry.get("role") == "user" else []
            if content or attachments:
                messages.append({
                    "role": entry["role"],
                    "content": _message_content(content, attachments or []),
                })

    for entry in db.get_proxy_messages(conversation_id):
        content = str(entry.get("content") or "")
        attachments = entry.get("attachments") if entry.get("role") == "user" else []
        messages.append({
            "role": entry["role"],
            "content": _message_content(content, attachments or []),
        })
    return messages


def _title(message: str) -> str:
    compact = " ".join(message.split()).strip()
    return compact[:72] or "New proxy chat"


async def handle_list_custom_models(request: web.Request) -> web.Response:
    models = [public_provider(item) for item in db.list_custom_models()]
    return web.json_response({"models": models})


async def handle_save_custom_model(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        custom_model_id = body.get("id")
        existing_provider = None
        if custom_model_id is not None:
            custom_model_id = int(custom_model_id)
            existing_provider = _provider(custom_model_id)

        validation_body = dict(body)
        if existing_provider is not None:
            existing_headers = unprotect_extra_headers(existing_provider.get("extra_headers"))
            if "extra_headers" not in body:
                validation_body["extra_headers"] = existing_headers
            else:
                incoming_headers = body.get("extra_headers")
                if isinstance(incoming_headers, str):
                    try:
                        incoming_headers = json.loads(incoming_headers)
                    except json.JSONDecodeError as error:
                        raise CustomModelError(f"Extra headers are not valid JSON: {error.msg}.") from error
                if isinstance(incoming_headers, dict):
                    validation_body["extra_headers"] = {
                        str(name): existing_headers[str(name)]
                        if value is None and str(name) in existing_headers
                        else value
                        for name, value in incoming_headers.items()
                    }

        values = validate_provider_payload(validation_body)
        values["extra_headers"] = protect_extra_headers(values["extra_headers"])
        raw_key = body.get("api_key")
        encrypted_key = protect_secret(str(raw_key)) if raw_key not in (None, "") else None
        saved_id = db.save_custom_model(values, encrypted_key, custom_model_id)
        return web.json_response({"model": public_provider(_provider(saved_id))}, status=201 if custom_model_id is None else 200)
    except sqlite3.IntegrityError:
        return _error_response(CustomModelError("A custom model with this name already exists."), 409)
    except (CustomModelError, TypeError, ValueError) as error:
        return _error_response(error)
    except Exception as error:
        return _error_response(error, 500)


async def handle_delete_custom_model(request: web.Request) -> web.Response:
    try:
        custom_model_id = int(request.match_info["custom_model_id"])
        if db.custom_model_usage_count(custom_model_id):
            return _error_response(
                CustomModelError("This model is still used by a chat. Delete that chat or select another model first."),
                409,
            )
        deleted = db.delete_custom_model(custom_model_id)
        if not deleted:
            return _error_response(CustomModelError("Custom model not found."), 404)
        return web.json_response({"success": True})
    except ValueError as error:
        return _error_response(error)
    except sqlite3.IntegrityError:
        return _error_response(CustomModelError("This model is still used by a proxy chat."), 409)
    except Exception as error:
        return _error_response(error, 500)


async def handle_test_custom_model(request: web.Request) -> web.Response:
    try:
        provider = _provider(int(request.match_info["custom_model_id"]))
        result = await asyncio.to_thread(test_provider, provider)
        return web.json_response(result)
    except (CustomModelError, TypeError, ValueError) as error:
        return _error_response(error, 502 if isinstance(error, CustomModelError) else 400)
    except Exception as error:
        return _error_response(error, 500)


async def handle_create_proxy_chat(request: web.Request) -> web.Response:
    """Create a Hub-local conversation after the first provider call succeeds."""
    try:
        body = await request.json()
        if str(body.get("source") or "").strip().lower() in {"custom", "codex"}:
            from src.provider_chat_handlers import handle_create_provider_chat

            return await handle_create_provider_chat(request, body=body)
        project_id = int(body.get("project_id"))
        if not db.get_project(project_id):
            return _error_response(CustomModelError("Project not found."), 404)
        custom_model_id = int(body.get("custom_model_id"))
        provider = _provider(custom_model_id)
        message = str(body.get("message") or "").strip()
        attachments = body.get("attachments") or []
        if not message and not attachments:
            return _error_response(CustomModelError("Message or attachment is required."))

        user_content = _message_content(message, attachments)
        result = await asyncio.to_thread(
            send_chat_completion,
            provider,
            [{"role": "user", "content": user_content}],
        )
        conversation_id = f"proxy-{uuid.uuid4()}"
        db.create_proxy_conversation(conversation_id, project_id, custom_model_id, _title(message))
        db.set_custom_model_preference(conversation_id, custom_model_id)
        user_id = db.add_proxy_message(conversation_id, custom_model_id, "user", message, attachments)
        assistant_id = db.add_proxy_message(conversation_id, custom_model_id, "assistant", result["content"])
        return web.json_response({
            "success": True,
            "verified": True,
            "convo_id": conversation_id,
            "model": public_provider(provider),
            "user": {"idx": 1_000_000_000 + user_id, "role": "user", "content": message, "attachments": attachments},
            "assistant": {"idx": 1_000_000_000 + assistant_id, "role": "assistant", "content": result["content"]},
            "usage": result.get("usage"),
        }, status=201)
    except (CustomModelError, TypeError, ValueError) as error:
        return _error_response(error, 502 if isinstance(error, CustomModelError) else 400)
    except Exception as error:
        return _error_response(error, 500)


async def handle_send_proxy_message(request: web.Request) -> web.Response:
    try:
        conversation_id = request.match_info["convo_id"]
        if not conversation_id.startswith("proxy-"):
            from src.integrity_sync import (
                scan_antigravity_conversation_catalog,
            )

            conversations = await asyncio.to_thread(
                scan_antigravity_conversation_catalog
            )
            metadata = next(
                (
                    item
                    for item in conversations
                    if item.get("convo_id") == conversation_id
                ),
                None,
            )
            if metadata and metadata.get("archived"):
                return web.json_response(
                    {
                        "error": (
                            "This conversation is archived. Restore it before "
                            "sending a message."
                        ),
                        "code": "conversation_archived",
                        "requires_restore": True,
                        "conversation_id": conversation_id,
                    },
                    status=409,
                )
        body = await request.json()
        message = str(body.get("message") or "").strip()
        attachments = body.get("attachments") or []
        if not message and not attachments:
            return _error_response(CustomModelError("Message or attachment is required."))

        requested_id = body.get("custom_model_id")
        preference = db.get_custom_model_preference(conversation_id)
        custom_model_id = int(requested_id or (preference or {}).get("id") or 0)
        provider = _provider(custom_model_id)
        context = _context_messages(conversation_id)
        context.append({"role": "user", "content": _message_content(message, attachments)})
        result = await asyncio.to_thread(send_chat_completion, provider, context)

        db.set_custom_model_preference(conversation_id, custom_model_id)
        user_id = db.add_proxy_message(conversation_id, custom_model_id, "user", message, attachments)
        assistant_id = db.add_proxy_message(conversation_id, custom_model_id, "assistant", result["content"])
        return web.json_response({
            "success": True,
            "verified": True,
            "model": public_provider(provider),
            "user": {"idx": 1_000_000_000 + user_id, "role": "user", "content": message, "attachments": attachments},
            "assistant": {"idx": 1_000_000_000 + assistant_id, "role": "assistant", "content": result["content"]},
            "usage": result.get("usage"),
        })
    except (CustomModelError, TypeError, ValueError) as error:
        return _error_response(error, 502 if isinstance(error, CustomModelError) else 400)
    except Exception as error:
        return _error_response(error, 500)
