"""Focused tests for the local Codex app-server integration."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.codex_app_server import (
    CodexAppServerManager,
    CodexBinaryNotFound,
    CodexRequestTimeout,
    CodexValidationError,
    resolve_codex_binary,
)
from src.codex_handlers import register_codex_routes
from src.proxy_server import create_app


class _QueueReader:
    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()
        self._closed = False

    def push(self, message) -> None:
        if isinstance(message, str):
            line = message
        else:
            line = json.dumps(message)
        self._lines.put(line + ("" if line.endswith("\n") else "\n"))

    def readline(self) -> str:
        return self._lines.get(timeout=2.0)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._lines.put("")


class _FakeStdin:
    def __init__(self, process: "_FakeProcess") -> None:
        self.process = process
        self.closed = False

    def write(self, payload: str) -> int:
        if self.closed:
            raise ValueError("closed")
        for line in payload.splitlines():
            if line.strip():
                self.process.receive(json.loads(line))
        return len(payload)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _QueueReader()
        self.stderr = _QueueReader()
        self.stdin = _FakeStdin(self)
        self.returncode = None
        self.messages = []
        self.threads = {}
        self.projects = {}
        self.project_keys = {}

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.close()
        self.stderr.close()

    def kill(self) -> None:
        self.terminate()

    def emit(self, message) -> None:
        self.stdout.push(message)

    def receive(self, message) -> None:
        self.messages.append(message)
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialized" or request_id is None:
            return
        if method == "initialize":
            self.emit({"id": request_id, "result": {"serverInfo": {"name": "codex"}}})
        elif method == "account/read":
            self.emit({
                "id": request_id,
                "result": {
                    "account": {
                        "type": "chatgpt",
                        "email": "private@example.test",
                        "planType": "pro",
                    },
                    "requiresOpenaiAuth": True,
                },
            })
        elif method == "account/login/start":
            self.emit({
                "id": request_id,
                "result": {
                    "type": "chatgpt",
                    "loginId": "login-123",
                    "authUrl": "https://auth.openai.com/codex",
                },
            })
        elif method == "account/login/cancel":
            self.emit({"id": request_id, "result": {"status": "canceled"}})
        elif method == "account/logout":
            self.emit({"id": request_id, "result": {}})
        elif method == "model/list":
            self.emit({
                "id": request_id,
                "result": {
                    "data": [{
                        "id": "gpt-5.3-codex",
                        "model": "gpt-5.3-codex",
                        "displayName": "GPT-5.3-Codex",
                        "description": "Coding model",
                        "hidden": False,
                        "supportedReasoningEfforts": [{
                            "reasoningEffort": "high",
                            "description": "Deep reasoning",
                        }],
                        "defaultReasoningEffort": "high",
                        "inputModalities": ["text", "image"],
                        "serviceTiers": [{
                            "id": "priority",
                            "name": "Priority",
                            "description": "Fast",
                        }],
                        "defaultServiceTier": "priority",
                        "isDefault": True,
                    }],
                    "nextCursor": None,
                },
            })
        elif method == "project/create":
            params = message.get("params") or {}
            idempotency_key = params.get("idempotencyKey")
            project_id = self.project_keys.get(idempotency_key)
            if not project_id:
                project_id = "project-123"
                self.project_keys[idempotency_key] = project_id
                self.projects[project_id] = {
                    "id": project_id,
                    "name": params.get("name"),
                    "roots": params.get("roots"),
                    "metadata": params.get("metadata") or {},
                }
            self.emit({
                "id": request_id,
                "result": {"project": self.projects[project_id]},
            })
        elif method == "project/read":
            params = message.get("params") or {}
            project_id = params.get("projectId")
            self.emit({
                "id": request_id,
                "result": {"project": self.projects.get(project_id)},
            })
        elif method == "thread/start":
            params = message.get("params") or {}
            thread = {
                "id": "thread-123",
                "projectId": params.get("projectId"),
                "cwd": params.get("cwd"),
            }
            self.threads["thread-123"] = thread
            self.emit({
                "id": request_id,
                "result": {
                    "thread": thread,
                    "model": "gpt-5.3-codex",
                },
            })
        elif method == "thread/resume":
            params = message.get("params") or {}
            thread_id = params.get("threadId")
            thread = dict(self.threads.get(thread_id) or {})
            thread["id"] = thread_id
            thread["cwd"] = params.get("cwd")
            self.threads[thread_id] = thread
            self.emit({"id": request_id, "result": {"thread": thread}})
        elif method == "turn/start":
            params = message.get("params") or {}
            workspace = Path(params.get("cwd") or ".")
            changed_file = workspace / "src" / "example.py"
            outside_file = workspace.parent / "outside-secret.txt"
            self.emit({"id": request_id, "result": {"turn": {"id": "turn-123"}}})
            self.emit({
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "itemId": "item-1",
                    "delta": "Hallo ",
                },
            })
            self.emit({
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "itemId": "item-1",
                    "delta": "Welt",
                },
            })
            self.emit({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "another-turn",
                    "item": {
                        "type": "fileChange",
                        "id": "foreign-change",
                        "status": "completed",
                        "changes": [{
                            "path": str(workspace / "foreign.py"),
                            "kind": "add",
                            "diff": "+must not be exposed\n",
                        }],
                    },
                },
            })
            self.emit({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "item": {
                        "type": "fileChange",
                        "id": "x" * 500,
                        "status": "completed",
                        "changes": [{
                            "path": str(workspace / "oversized-id.py"),
                            "kind": "add",
                            "diff": "+must not be exposed\n",
                        }],
                    },
                },
            })
            self.emit({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "item": {
                        "type": "commandExecution",
                        "id": "command-1",
                        "command": "python -m unittest",
                        "cwd": str(workspace),
                        "status": "completed",
                        "exitCode": 0,
                        "durationMs": 25,
                        "aggregatedOutput": "private command output",
                    },
                },
            })
            self.emit({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "item": {
                        "type": "fileChange",
                        "id": "change-1",
                        "status": "completed",
                        "changes": [
                            {
                                "path": str(changed_file),
                                "kind": "update",
                                "diff": (
                                    f"--- {changed_file}\n"
                                    f"+++ {changed_file}\n"
                                    "+print('ok')\n"
                                ),
                            },
                            {
                                "path": str(outside_file),
                                "kind": "update",
                                "diff": "+must not be exposed\n",
                            },
                        ],
                    },
                },
            })
            self.emit({
                "method": "item/completed",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "item": {
                        "type": "agentMessage",
                        "id": "item-1",
                        "text": "Stale event message",
                    },
                },
            })
            self.emit({
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "tokenUsage": {
                        "last": {
                            "inputTokens": 10,
                            "cachedInputTokens": 2,
                            "outputTokens": 5,
                            "reasoningOutputTokens": 1,
                            "totalTokens": 15,
                        },
                        "total": {
                            "inputTokens": 20,
                            "cachedInputTokens": 4,
                            "outputTokens": 10,
                            "reasoningOutputTokens": 2,
                            "totalTokens": 30,
                        },
                        "modelContextWindow": 200000,
                    },
                },
            })
            self.emit({
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-123",
                    "turn": {
                        "id": "turn-123",
                        "status": "completed",
                        "items": [{
                            "type": "agentMessage",
                            "id": "item-1",
                            "text": "Hallo Welt",
                        }],
                    },
                },
            })


class _FakeFactory:
    def __init__(self) -> None:
        self.processes = []
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        process = _FakeProcess()
        self.processes.append(process)
        return process


class TestCodexBinaryResolver(unittest.TestCase):
    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "codex.exe"
            executable.write_bytes(b"fake")
            selected = resolve_codex_binary({
                "ANTIGRAVITY_CODEX_BIN": str(executable),
                "LOCALAPPDATA": "",
            }, which=lambda _: None)
            self.assertEqual(Path(selected), executable.resolve())

    def test_invalid_override_does_not_silently_fall_back(self):
        with self.assertRaises(CodexBinaryNotFound):
            resolve_codex_binary(
                {"ANTIGRAVITY_CODEX_BIN": "missing-codex.exe"},
                which=lambda _: "another-codex.exe",
            )

    def test_desktop_install_prefers_newest_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "OpenAI" / "Codex" / "bin"
            old = root / "old" / "codex.exe"
            new = root / "new" / "codex.exe"
            old.parent.mkdir(parents=True)
            new.parent.mkdir(parents=True)
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            os.utime(old, (1, 1))
            os.utime(new, (2, 2))
            selected = resolve_codex_binary(
                {"LOCALAPPDATA": directory}, which=lambda _: None
            )
            self.assertEqual(Path(selected), new.resolve())

    def test_windowsapps_path_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "WindowsApps" / "codex.exe"
            alias.parent.mkdir()
            alias.write_bytes(b"alias")
            with self.assertRaises(CodexBinaryNotFound):
                resolve_codex_binary({}, which=lambda _: str(alias))


class TestCodexAppServerManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="codex_manager_test_")
        self.factory = _FakeFactory()
        self.manager = CodexAppServerManager(
            binary_resolver=lambda: "C:\\fake\\codex.exe",
            popen_factory=self.factory,
            workspace_root=self.temp_dir.name,
            request_timeout=0.2,
            chat_timeout=0.5,
            start_timeout=0.2,
            shutdown_timeout=0.1,
        )

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_status_is_redacted_and_initializes_protocol(self):
        status = self.manager.status()
        self.assertEqual(status, {
            "available": True,
            "running": True,
            "authenticated": True,
            "requires_openai_auth": True,
            "account_type": "chatgpt",
            "plan_type": "pro",
        })
        self.assertNotIn("private@example.test", repr(status))
        messages = self.factory.processes[0].messages
        self.assertEqual(messages[0]["method"], "initialize")
        self.assertEqual(messages[1], {"method": "initialized"})
        self.assertEqual(messages[2]["method"], "account/read")
        self.assertEqual(
            self.factory.calls[0][0],
            ["C:\\fake\\codex.exe", "app-server", "--listen", "stdio://"],
        )

    def test_auth_and_model_methods_use_public_shapes(self):
        self.assertEqual(self.manager.login_start(), {
            "login_id": "login-123",
            "auth_url": "https://auth.openai.com/codex",
        })
        self.assertEqual(
            self.manager.login_cancel("login-123"), {"status": "canceled"}
        )
        models = self.manager.list_models()
        self.assertEqual(models[0]["id"], "gpt-5.3-codex")
        self.assertEqual(
            models[0]["supported_reasoning_efforts"],
            [{"value": "high", "description": "Deep reasoning"}],
        )
        self.assertNotIn("upgradeInfo", models[0])
        self.manager.logout()

    def test_chat_collects_deltas_and_forces_safe_turn_policy(self):
        result = self.manager.chat(
            "gpt-5.3-codex", "Sag hallo", reasoning_effort="high"
        )
        self.assertEqual(result["content"], "Hallo Welt")
        self.assertEqual(result["thread_id"], "thread-123")
        process = self.factory.processes[0]
        initialize_request = next(
            item for item in process.messages if item.get("method") == "initialize"
        )
        self.assertTrue(
            initialize_request["params"]["capabilities"]["experimentalApi"]
        )
        thread_request = next(
            item for item in process.messages if item.get("method") == "thread/start"
        )
        self.assertEqual(thread_request["params"]["sandbox"], "read-only")
        self.assertEqual(thread_request["params"]["approvalPolicy"], "never")
        turn_request = next(
            item for item in process.messages if item.get("method") == "turn/start"
        )
        self.assertEqual(
            turn_request["params"]["sandboxPolicy"],
            {"type": "readOnly", "networkAccess": False},
        )
        self.assertEqual(turn_request["params"]["approvalPolicy"], "never")
        self.assertEqual(turn_request["params"]["environments"], [])

    def test_timeout_stops_process_and_next_call_restarts(self):
        with self.assertRaises(CodexRequestTimeout):
            self.manager.request("test/no-response", {}, timeout=0.05)
        self.assertFalse(self.manager.running)
        status = self.manager.status()
        self.assertTrue(status["running"])
        self.assertEqual(len(self.factory.processes), 2)

    def test_chat_validates_browser_controlled_identifiers(self):
        with self.assertRaises(CodexValidationError):
            self.manager.chat("../bad", "prompt")
        with self.assertRaises(CodexValidationError):
            self.manager.chat("gpt-5.3-codex", "")
        with self.assertRaises(CodexValidationError):
            self.manager.chat(
                "gpt-5.3-codex", "prompt", thread_id="bad/thread"
            )

    def test_agent_turn_is_workspace_bound_and_returns_public_activity(self):
        result = self.manager.agent_turn(
            "gpt-5.3-codex",
            "Implement the change",
            workspace_path=self.temp_dir.name,
            conversation_id="conversation-123",
            reasoning_effort="high",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["message"], "Hallo Welt")
        self.assertEqual(result["changes"]["files_changed"], ["src/example.py"])
        self.assertIn("### src/example.py (update)", result["changes"]["diff"])
        self.assertNotIn(str(Path(self.temp_dir.name).resolve()), repr(result))
        self.assertNotIn("outside-secret", repr(result))
        self.assertNotIn("foreign.py", repr(result))
        self.assertNotIn("oversized-id.py", repr(result))
        self.assertNotIn("Stale event message", repr(result))
        self.assertNotIn("private command output", repr(result))
        self.assertEqual(result["activity"][0], {
            "type": "command",
            "title": "python -m unittest",
            "status": "completed",
            "detail": "Exit code: 0 · Duration: 25 ms",
        })
        self.assertEqual(result["usage"]["last"]["input_tokens"], 10)

        process = self.factory.processes[0]
        thread_request = next(
            item for item in process.messages if item.get("method") == "thread/start"
        )
        project_request = next(
            item for item in process.messages if item.get("method") == "project/create"
        )
        self.assertRegex(
            project_request["params"]["idempotencyKey"],
            r"^antigravity-[0-9a-f]{64}$",
        )
        self.assertEqual(project_request["params"]["roots"], [{
            "path": str(Path(self.temp_dir.name).resolve())
        }])
        self.assertEqual(
            project_request["params"]["metadata"][
                "antigravity.conversation_id"
            ],
            "conversation-123",
        )
        self.assertRegex(
            project_request["params"]["metadata"][
                "antigravity.workspace_marker"
            ],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(thread_request["params"]["sandbox"], "workspace-write")
        self.assertEqual(thread_request["params"]["approvalPolicy"], "never")
        self.assertFalse(thread_request["params"]["ephemeral"])
        self.assertNotIn("environments", thread_request["params"])
        self.assertEqual(thread_request["params"]["projectId"], "project-123")
        turn_request = next(
            item for item in process.messages if item.get("method") == "turn/start"
        )
        self.assertEqual(turn_request["params"]["approvalPolicy"], "never")
        self.assertNotIn("environments", turn_request["params"])
        self.assertEqual(turn_request["params"]["sandboxPolicy"], {
            "type": "workspaceWrite",
            "writableRoots": [str(Path(self.temp_dir.name).resolve())],
            "networkAccess": False,
        })

    def test_agent_turn_resumes_only_the_bound_conversation(self):
        first = self.manager.agent_turn(
            "gpt-5.3-codex",
            "First turn",
            workspace_path=self.temp_dir.name,
            conversation_id="conversation-123",
        )
        second = self.manager.agent_turn(
            "gpt-5.3-codex",
            "Second turn",
            workspace_path=self.temp_dir.name,
            conversation_id="conversation-123",
            thread_id=first["thread_id"],
        )
        self.assertEqual(second["thread_id"], first["thread_id"])
        resume_request = next(
            item
            for item in self.factory.processes[0].messages
            if item.get("method") == "thread/resume"
        )
        self.assertEqual(resume_request["params"]["sandbox"], "workspace-write")
        self.assertEqual(resume_request["params"]["runtimeWorkspaceRoots"], [
            str(Path(self.temp_dir.name).resolve())
        ])
        project_read_request = next(
            item
            for item in self.factory.processes[0].messages
            if item.get("method") == "project/read"
        )
        self.assertEqual(project_read_request["params"], {
            "projectId": "project-123"
        })

    def test_agent_turn_rejects_mismatched_project_metadata_and_root(self):
        first = self.manager.agent_turn(
            "gpt-5.3-codex",
            "First turn",
            workspace_path=self.temp_dir.name,
            conversation_id="conversation-123",
        )
        process = self.factory.processes[0]
        project = process.projects["project-123"]
        project["metadata"]["antigravity.conversation_id"] = "another-conversation"
        with self.assertRaises(CodexValidationError):
            self.manager.agent_turn(
                "gpt-5.3-codex",
                "Must not start",
                workspace_path=self.temp_dir.name,
                conversation_id="conversation-123",
                thread_id=first["thread_id"],
            )

        project["metadata"]["antigravity.conversation_id"] = "conversation-123"
        other_root = Path(self.temp_dir.name) / "other-root"
        other_root.mkdir()
        project["roots"] = [{"path": str(other_root)}]
        with self.assertRaises(CodexValidationError):
            self.manager.agent_turn(
                "gpt-5.3-codex",
                "Still must not start",
                workspace_path=self.temp_dir.name,
                conversation_id="conversation-123",
                thread_id=first["thread_id"],
            )

        turn_requests = [
            item
            for item in process.messages
            if item.get("method") == "turn/start"
        ]
        self.assertEqual(len(turn_requests), 1)

    def test_agent_turn_rejects_unusable_workspace_and_bad_conversation(self):
        with self.assertRaises(CodexValidationError):
            self.manager.agent_turn(
                "gpt-5.3-codex",
                "prompt",
                workspace_path="relative/path",
                conversation_id="conversation-123",
            )
        with self.assertRaises(CodexValidationError):
            self.manager.agent_turn(
                "gpt-5.3-codex",
                "prompt",
                workspace_path=self.temp_dir.name,
                conversation_id="bad/conversation",
            )


class _HandlerManager:
    def __init__(self):
        self.agent_turn_calls = []

    def status(self):
        return {
            "available": True,
            "running": True,
            "authenticated": True,
            "requires_openai_auth": False,
            "account_type": "chatgpt",
            "plan_type": "pro",
        }

    def login_start(self):
        return {
            "login_id": "login-123",
            "auth_url": "https://auth.openai.com/codex",
        }

    def login_cancel(self, login_id):
        return {"status": "canceled"}

    def logout(self):
        return None

    def list_models(self):
        return [{"id": "gpt-5.3-codex", "display_name": "GPT-5.3-Codex"}]

    def chat(self, model, prompt, **kwargs):
        if not model or not prompt:
            raise CodexValidationError("A model and prompt are required.")
        return {
            "thread_id": kwargs.get("thread_id") or "thread-123",
            "turn_id": "turn-123",
            "content": "Hallo",
            "status": "completed",
            "model": model,
            "reasoning_effort": kwargs.get("reasoning_effort"),
        }

    def agent_turn(self, model, prompt, **kwargs):
        self.agent_turn_calls.append((model, prompt, kwargs))
        return {
            "success": True,
            "status": "completed",
            "thread_id": kwargs.get("thread_id") or "thread-123",
            "turn_id": "turn-123",
            "message": "Implemented",
            "activity": [],
            "changes": {"files_changed": [], "summary": "No files changed."},
        }


class TestCodexHandlers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = _HandlerManager()
        self.manager_patch = patch(
            "src.codex_handlers.get_codex_manager", return_value=self.manager
        )
        self.manager_patch.start()
        self.workspace_patch = patch(
            "src.codex_handlers.authorized_workspace_kind",
            return_value="project",
        )
        self.workspace_patch.start()
        app = web.Application()
        register_codex_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.workspace_patch.stop()
        self.manager_patch.stop()

    async def test_status_models_login_and_chat(self):
        response = await self.client.get("/api/antigravity/codex/status")
        self.assertEqual(response.status, 200)
        status_text = await response.text()
        self.assertNotIn("email", status_text.lower())

        response = await self.client.get("/api/antigravity/codex/models")
        self.assertEqual((await response.json())["models"][0]["id"], "gpt-5.3-codex")

        response = await self.client.post("/api/antigravity/codex/login/start")
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["login_id"], "login-123")

        response = await self.client.post(
            "/api/antigravity/codex/chat",
            json={
                "model": "gpt-5.3-codex",
                "prompt": "Hallo",
                "reasoning_effort": "high",
            },
        )
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["content"], "Hallo")

    async def test_external_origin_is_rejected_before_manager_use(self):
        with patch(
            "src.codex_handlers.get_codex_manager",
            side_effect=AssertionError("manager must not be called"),
        ):
            response = await self.client.get(
                "/api/antigravity/codex/status",
                headers={"Origin": "https://attacker.example"},
            )
        self.assertEqual(response.status, 403)

    async def test_local_preflight_and_invalid_chat(self):
        response = await self.client.options(
            "/api/antigravity/codex/chat",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(response.status, 204)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "http://127.0.0.1:8000",
        )

        response = await self.client.post(
            "/api/antigravity/codex/chat", json={"model": "", "prompt": ""}
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["code"], "codex_invalid_request")

    async def test_agent_turn_uses_only_an_authorized_internal_workspace(self):
        response = await self.client.post(
            "/api/antigravity/codex/agent-turn",
            json={
                "workspace_path": "D:\\registered-project",
                "conversation_id": "conversation-123",
                "model": "gpt-5.3-codex",
                "reasoning_effort": "high",
                "prompt": "Implement the change",
            },
        )
        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        _, _, kwargs = self.manager.agent_turn_calls[0]
        self.assertEqual(kwargs["workspace_path"], "D:\\registered-project")
        self.assertEqual(kwargs["conversation_id"], "conversation-123")
        self.assertEqual(kwargs["reasoning_effort"], "high")

    async def test_agent_turn_rejects_an_unregistered_workspace(self):
        with patch(
            "src.codex_handlers.authorized_workspace_kind", return_value=""
        ):
            response = await self.client.post(
                "/api/antigravity/codex/agent-turn",
                json={
                    "workspace_path": "D:\\not-registered",
                    "conversation_id": "conversation-123",
                    "model": "gpt-5.3-codex",
                    "prompt": "Do not run",
                },
            )
        self.assertEqual(response.status, 403)
        self.assertEqual(
            (await response.json())["code"], "codex_workspace_unauthorized"
        )
        self.assertEqual(self.manager.agent_turn_calls, [])


class TestCodexRouteRegistration(unittest.TestCase):
    def test_create_app_registers_all_codex_routes(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertTrue({
            "/api/antigravity/codex/status",
            "/api/antigravity/codex/login/start",
            "/api/antigravity/codex/login/cancel",
            "/api/antigravity/codex/logout",
            "/api/antigravity/codex/models",
            "/api/antigravity/codex/chat",
            "/api/antigravity/codex/agent-turn",
        }.issubset(paths))


if __name__ == "__main__":
    unittest.main()
