"""End-to-End Readiness Tests for Headless Linux OAuth, OpenClaw & Hermes Compatibility."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api_handlers import (
    chat_completions_handler,
    oauth_status_handler,
    oauth_token_import_handler,
)
from src.api_profile import APIProfileRuntime
from src.rpc_pool import DirectRPCPool


class FakeHeadlessRPCClient:
    """Simulated DirectConnectRPCClient for testing OpenClaw & Hermes payloads end-to-end."""

    def __init__(self) -> None:
        self.started_workspaces: List[str] = []
        self.sent_messages: List[Dict[str, Any]] = []
        self.mock_response_text: str = "Standard assistant reply."
        self.quota_summary: Dict[str, Any] = {
            "models": [
                {"model": "MODEL_PLACEHOLDER_M37", "remainingFraction": 0.85},
                {"model": "MODEL_PLACEHOLDER_M47", "remainingFraction": 0.90},
            ]
        }
        self._steps_by_cascade: Dict[str, List[Dict[str, Any]]] = {}

    async def retrieve_user_quota_summary(self) -> Dict[str, Any]:
        return self.quota_summary

    async def start_cascade(
        self, workspace_dir: Path, *, model: Optional[str] = None
    ) -> str:
        self.started_workspaces.append(str(workspace_dir))
        cid = f"conv-{len(self.started_workspaces):04d}"
        self._steps_by_cascade[cid] = []
        return cid

    async def get_trajectory_steps(
        self, cascade_id: str, step_offset: int = 0
    ) -> List[Dict[str, Any]]:
        steps = self._steps_by_cascade.get(cascade_id, [])
        return steps[step_offset:]

    async def send_user_cascade_message(
        self,
        cascade_id: str,
        prompt: str,
        workspace_dir: Path,
        *,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        blocking: bool = False,
    ) -> Dict[str, Any]:
        self.sent_messages.append(
            {
                "cascade_id": cascade_id,
                "prompt": prompt,
                "workspace_dir": str(workspace_dir),
                "model": model,
            }
        )
        steps = self._steps_by_cascade.setdefault(cascade_id, [])
        steps.append({"type": "CORTEX_STEP_TYPE_USER_INPUT"})
        steps.append(
            {
                "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                "plannerResponse": {"ModifiedResponse": self.mock_response_text},
            }
        )
        return {"ok": True}

    async def stream_response_deltas(
        self,
        cascade_id: str,
        baseline_step_count: int,
        *,
        timeout: float = 120.0,
    ) -> AsyncIterator[str]:
        text = self.mock_response_text
        mid = max(1, len(text) // 2)
        yield text[:mid]
        yield text[mid:]

    @staticmethod
    def extract_planner_response_text(
        steps: List[Dict[str, Any]],
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        for step in reversed(steps):
            pr = step.get("plannerResponse") or {}
            txt = pr.get("ModifiedResponse") or pr.get("Response") or ""
            if txt:
                return txt, step
        return "", None

    async def get_generator_metadata(self, cascade_id: str) -> List[Dict[str, Any]]:
        return [
            {
                "chatModel": {
                    "usage": {
                        "inputTokens": "120",
                        "outputTokens": "45",
                    }
                }
            }
        ]

    @staticmethod
    def resolve_canonical_model_id(
        model: Optional[str], reasoning_effort: Optional[str] = None
    ) -> Tuple[str, str]:
        m = model or "gemini-3-flash"
        return m, m


def _build_test_app(pool: DirectRPCPool) -> web.Application:
    app = web.Application()
    app["rpc_pool"] = pool
    app.router.add_post("/v1/chat/completions", chat_completions_handler)
    app.router.add_post("/openclaw/v1/chat/completions", chat_completions_handler)
    app.router.add_post("/hermes/v1/chat/completions", chat_completions_handler)
    app.router.add_get("/v1/auth/status", oauth_status_handler)
    app.router.add_post("/v1/auth/token", oauth_token_import_handler)
    return app


class OpenClawHermesE2ETests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from src.antigravity_shields import quota_breaker
        quota_breaker._exhausted_until.clear()
        quota_breaker._cached_at = 0.0

    def tearDown(self) -> None:
        from src.antigravity_shields import quota_breaker
        quota_breaker._exhausted_until.clear()
        quota_breaker._cached_at = 0.0

    def test_headless_oauth_token_persistence_and_isolation(self) -> None:
        """Verify headless Linux OAuth token import, auto-refresh, and strict /data/antigravity-api isolation."""
        with tempfile.TemporaryDirectory() as tmp:
            isolated_root = Path(tmp) / "antigravity-api"
            env_patch = {
                "ANTIGRAVITY_DOCKER": "1",
                "ANTIGRAVITY_DATA_DIR": str(isolated_root),
                "ANTIGRAVITY_API_HOME": str(isolated_root / "home"),
                "ANTIGRAVITY_OAUTH_TOKEN": "",
                "JETSKI_OAUTH_TOKEN": "",
            }
            with patch.dict(os.environ, env_patch, clear=False):
                runtime = APIProfileRuntime()
                runtime._seed_authentication_once()
                self.assertEqual(runtime.profile_home, isolated_root / "home")
                slots = sorted(p.name for p in runtime.workspaces_pool_dir.glob("ws-*"))
                self.assertEqual(len(slots), 10)

                imported = runtime.import_oauth_token(
                    {
                        "access_token": "ya29.initial-token",
                        "refresh_token": "1//09-refresh-token-xyz",
                        "expires_in": 3600,
                    },
                    restart_rpc=False,
                )
                self.assertEqual(imported["access_token"], "ya29.initial-token")
                self.assertEqual(imported["refresh_token"], "1//09-refresh-token-xyz")
                self.assertTrue((isolated_root / "oauth_token.json").exists())

                resolved = runtime.resolve_headless_access_token(auto_refresh=False)
                self.assertEqual(resolved, "ya29.initial-token")

                status = runtime.get_oauth_status()
                self.assertTrue(status["configured"])
                self.assertTrue(status["has_access_token"])
                self.assertTrue(status["has_refresh_token"])

    async def test_openclaw_e2e_tool_calls_markdown_fenced_sync_and_stream(self) -> None:
        """Verify OpenClaw payloads with SOUL.md/HEARTBEAT.md sanitization and Markdown-fenced tool_calls."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.dict(os.environ, {"ANTIGRAVITY_API_HOME": str(tmp_path / "home")}, clear=False):
                fake_client = FakeHeadlessRPCClient()
                pool = DirectRPCPool(rpc_client=fake_client, slot_count=10)
                fake_client.mock_response_text = (
                    "Ich prüfe das Verzeichnis für dich.\n"
                    "```json\n"
                    '{"tool_calls": [{"id": "call_openclaw_1", "name": "exec_command", "arguments": {"cmd": "ls -la /workspace"}}]}\n'
                    "```"
                )

                openclaw_payload = {
                    "model": "gemini-3-flash",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are OpenClaw Autonomous Agent. Read SOUL.md and HEARTBEAT.md before acting."
                            ),
                        },
                        {
                            "role": "user",
                            "content": "List the files in /workspace using exec_command.",
                        },
                    ],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "exec_command",
                                "description": "Execute a shell command",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"cmd": {"type": "string"}},
                                    "required": ["cmd"],
                                },
                            },
                        }
                    ],
                    "tool_choice": "auto",
                }

                app = _build_test_app(pool)
                async with TestClient(TestServer(app)) as client:
                    # 1. Non-streaming OpenClaw request
                    resp = await client.post("/openclaw/v1/chat/completions", json=openclaw_payload)
                    self.assertEqual(resp.status, 200)
                    data = await resp.json()

                    choice = data["choices"][0]
                    self.assertEqual(choice["finish_reason"], "tool_calls")
                    tool_calls = choice["message"]["tool_calls"]
                    self.assertEqual(len(tool_calls), 1)
                    self.assertEqual(tool_calls[0]["id"], "call_openclaw_1")
                    self.assertEqual(tool_calls[0]["type"], "function")
                    self.assertEqual(tool_calls[0]["function"]["name"], "exec_command")
                    self.assertEqual(
                        json.loads(tool_calls[0]["function"]["arguments"]),
                        {"cmd": "ls -la /workspace"},
                    )

                    # Verify Shield 2 + 4: Forbidden keywords ("OpenClaw", "SOUL.md", "HEARTBEAT.md") were sanitized
                    # and no redundant workspace AGENTS.md file is left behind
                    slot_name = data["workspace_slot"]
                    self.assertFalse((pool.base_workspaces_dir / slot_name / "AGENTS.md").exists())
                    sent_prompt = fake_client.sent_messages[-1]["prompt"]
                    self.assertNotIn("OpenClaw", sent_prompt)
                    self.assertNotIn("SOUL.md", sent_prompt)
                    self.assertNotIn("HEARTBEAT.md", sent_prompt)
                    self.assertIn("PROJECT_CONTEXT.md", sent_prompt)
                    self.assertIn("STATUS_CHECK.md", sent_prompt)

                    # 2. Streaming (stream: true) OpenClaw request with Markdown-fenced tool_calls
                    stream_payload = dict(openclaw_payload, stream=True)
                    sresp = await client.post("/openclaw/v1/chat/completions", json=stream_payload)
                    self.assertEqual(sresp.status, 200)
                    raw_sse = await sresp.text()

                    sse_events = []
                    for line in raw_sse.splitlines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            sse_events.append(json.loads(line[6:]))

                    tc_events = [
                        ev for ev in sse_events if ev["choices"][0].get("delta", {}).get("tool_calls")
                    ]
                    self.assertTrue(len(tc_events) >= 1, f"Expected delta.tool_calls in SSE: {sse_events}")
                    streamed_tc = tc_events[0]["choices"][0]["delta"]["tool_calls"][0]
                    self.assertEqual(streamed_tc["function"]["name"], "exec_command")
                    self.assertEqual(
                        json.loads(streamed_tc["function"]["arguments"]),
                        {"cmd": "ls -la /workspace"},
                    )
                    self.assertEqual(sse_events[-1]["choices"][0]["finish_reason"], "tool_calls")

    async def test_hermes_multi_turn_session_reuse_heartbeat_and_quota_429(self) -> None:
        """Verify Hermes multi-turn session reuse, 0ms HEARTBEAT_OK, and 5% Quota Circuit Breaker (HTTP 429)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.dict(os.environ, {"ANTIGRAVITY_API_HOME": str(tmp_path / "home")}, clear=False):
                fake_client = FakeHeadlessRPCClient()
                pool = DirectRPCPool(rpc_client=fake_client, slot_count=10)
                fake_client.mock_response_text = "Hermes task step 1 completed."

                app = _build_test_app(pool)
                async with TestClient(TestServer(app)) as client:
                    # 1. Turn 1 (Hermes)
                    turn1_messages = [
                        {"role": "system", "content": "You are Hermes Agent."},
                        {"role": "user", "content": "Start deployment check on server."},
                    ]
                    r1 = await client.post(
                        "/hermes/v1/chat/completions",
                        json={"model": "gemini-3-flash", "messages": turn1_messages},
                    )
                    self.assertEqual(r1.status, 200)
                    d1 = await r1.json()
                    conv1 = d1["conversation_id"]
                    self.assertEqual(len(fake_client.started_workspaces), 1)

                    # 2. Turn 2 (Hermes multi-turn history without explicit conversation_id) -> reuses same cascade!
                    turn2_messages = turn1_messages + [
                        {"role": "assistant", "content": "Hermes task step 1 completed."},
                        {"role": "user", "content": "Now verify container status."},
                    ]
                    fake_client.mock_response_text = "Hermes task step 2 verified."
                    r2 = await client.post(
                        "/hermes/v1/chat/completions",
                        json={"model": "gemini-3-flash", "messages": turn2_messages},
                    )
                    self.assertEqual(r2.status, 200)
                    d2 = await r2.json()
                    self.assertEqual(d2["conversation_id"], conv1)
                    self.assertEqual(len(fake_client.started_workspaces), 1)
                    self.assertEqual(fake_client.sent_messages[-1]["prompt"], "Now verify container status.")

                    # 3. Shield 3: 0ms Heartbeat Ping
                    hb_resp = await client.post(
                        "/openclaw/v1/chat/completions",
                        json={
                            "model": "gemini-3-flash",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Read HEARTBEAT.md if it exists. If nothing needs attention, reply HEARTBEAT_OK.",
                                }
                            ],
                        },
                    )
                    self.assertEqual(hb_resp.status, 200)
                    hb_data = await hb_resp.json()
                    self.assertEqual(hb_data["choices"][0]["message"]["content"], "HEARTBEAT_OK")
                    self.assertEqual(len(fake_client.sent_messages), 2)

                    # 4. Shield 6: 5% Quota Circuit Breaker returns HTTP 429 in BOTH sync and stream modes
                    from src.antigravity_shields import quota_breaker

                    fake_client.quota_summary = {
                        "groups": [
                            {
                                "buckets": [
                                    {"name": "gemini-5hour", "remainingFraction": 0.02},
                                ]
                            }
                        ]
                    }
                    quota_breaker._cached_at = 0.0
                    q_sync = await client.post(
                        "/hermes/v1/chat/completions",
                        json={
                            "model": "gemini-3-flash",
                            "messages": [{"role": "user", "content": "Run with low quota"}],
                        },
                    )
                    self.assertEqual(q_sync.status, 429)
                    q_sync_body = await q_sync.json()
                    self.assertEqual(q_sync_body["error"]["code"], "model_quota_exhausted")

                    q_stream = await client.post(
                        "/hermes/v1/chat/completions",
                        json={
                            "model": "gemini-3-flash",
                            "stream": True,
                            "messages": [{"role": "user", "content": "Run stream with low quota"}],
                        },
                    )
                    self.assertEqual(q_stream.status, 429)
                    q_stream_body = await q_stream.json()
                    self.assertEqual(q_stream_body["error"]["code"], "model_quota_exhausted")


if __name__ == "__main__":
    unittest.main()
