"""Comprehensive verification suite for Dual-Engine (rpc vs. ui), all 8 Anti-Ban Shields,
10x concurrent request balancing, auto/manual conversation revert, exact token reading,
and persistent API audit logging.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import api_handlers
from src.antigravity_shields import (
    HeartbeatAndPacingGuard,
    QuotaCircuitBreaker,
    QuotaExhaustedError,
    StaggeredConcurrencyLimiter,
    extract_and_sanitize_messages,
    verify_loopback_rpc_url,
    write_workspace_agents_md,
)
from src.api_token_reader import parse_generator_metadata_tokens
from src.config import config
from src.database import Database
from src.rpc_client import DirectConnectRPCClient
from src.rpc_pool import DirectRPCPool


class _MockReq(dict):
    def __init__(self, body: dict, *, app: dict | None = None, headers: dict | None = None):
        super().__init__()
        self._body = body
        self.app = app if app is not None else {}
        self.headers = headers or {"User-Agent": "Hermes-Agent/2.0"}
        self.remote = "127.0.0.1"
        self.query = {}
        self.match_info = {}
        self.method = "POST"

    async def json(self):
        return self._body


class FakeRPCClient(DirectConnectRPCClient):
    """In-memory mock of `DirectConnectRPCClient` recording exact ConnectRPC payloads."""

    def __init__(self, *, quota_fraction: float = 0.85) -> None:
        super().__init__(port=54321, csrf_token="test-csrf-uuid")
        self.quota_fraction = quota_fraction
        self.started_cascades: list[dict] = []
        self.sent_messages: list[dict] = []
        self.reverts: list[dict] = []
        self.step_counts: dict[str, int] = {}
        self._counter = 0

    async def ensure_connected(self):
        return (54321, "test-csrf-uuid")

    async def call_unary(self, method: str, payload: dict | None = None, timeout: float = 30.0):
        payload = payload or {}
        if method == "RetrieveUserQuotaSummary":
            return {
                "groups": [
                    {
                        "buckets": [
                            {
                                "name": "claude-opus-5hour",
                                "remainingFraction": self.quota_fraction,
                                "resetTime": "2026-10-18T12:00:00Z",
                            },
                            {
                                "name": "gemini-5hour",
                                "remainingFraction": 0.95,
                            },
                        ]
                    }
                ]
            }
        if method == "GetAvailableModels":
            return {
                "models": [
                    {"label": "Claude Opus 4.6", "model": 291},
                    {"label": "Claude Sonnet 4.6", "model": 334},
                    {"label": "Gemini 3.1 Pro (High)", "model": 246},
                ]
            }
        if method == "StartCascade":
            self._counter += 1
            cid = f"cascade-{self._counter:03d}"
            self.started_cascades.append(payload)
            self.step_counts[cid] = 0
            return {"cascadeId": cid}
        if method == "SendUserCascadeMessage":
            cid = payload["cascadeId"]
            self.sent_messages.append(payload)
            self.step_counts[cid] = self.step_counts.get(cid, 0) + 2
            return {}
        if method == "RevertToCascadeStep":
            cid = payload["cascadeId"]
            self.reverts.append(payload)
            self.step_counts[cid] = int(payload.get("stepIndex", 0))
            return {}
        if method == "GetCascadeTrajectorySteps":
            cid = payload["cascadeId"]
            offset = int(payload.get("stepOffset", 0))
            total = self.step_counts.get(cid, 0)
            steps = [
                {
                    "stepIndex": i,
                    "status": "CORTEX_STEP_STATUS_DONE",
                    "plannerResponse": {"response": f"Verified RPC reply for {cid}"},
                }
                for i in range(total)
            ]
            return {"steps": steps[offset:]}
        if method == "GetCascadeTrajectoryGeneratorMetadata":
            return {
                "generatorMetadata": [
                    {
                        "chatModelMetadata": {
                            "responseModel": "claude-opus-4-6",
                            "usage": {
                                "inputTokens": 420,
                                "outputTokens": 180,
                                "cacheReadInputTokens": 1200,
                                "thinkingOutputTokens": 95,
                            },
                            "chatStartMetadata": {
                                "contextWindowMetadata": {
                                    "estimatedTokensUsed": 1895,
                                    "maxContextTokens": 200000,
                                }
                            },
                        }
                    }
                ]
            }
        return {}


class RpcShieldsAndAuditLogsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.test_db = Database(self.base_path / "test_dashboard.db")
        self.db_patcher_1 = patch("src.api_audit_logger.db", self.test_db)
        self.db_patcher_2 = patch("src.api_handlers.db", self.test_db)
        self.jsonl_patcher = patch(
            "src.api_audit_logger.AUDIT_LOG_JSONL",
            self.base_path / "api_audit_logs.jsonl",
        )
        self.db_patcher_1.start()
        self.db_patcher_2.start()
        self.jsonl_patcher.start()
        self._saved_api_engine = dict(config.api_engine)
        config.update_api_engine_settings(
            {
                "mode": "rpc",
                "max_parallel_streams": 4,
                "stagger_min_ms": 5,
                "stagger_max_ms": 15,
                "adaptive_pacing_enabled": False,
                "heartbeat_blocker_enabled": True,
                "keyword_firewall_enabled": True,
                "quota_breaker_enabled": True,
                "quota_min_fraction": 0.05,
            }
        )

    def tearDown(self) -> None:
        config.update_api_engine_settings(self._saved_api_engine)
        self.db_patcher_1.stop()
        self.db_patcher_2.stop()
        self.jsonl_patcher.stop()
        self.temp_dir.cleanup()

    def test_shield_1_rejects_external_cloud_urls(self) -> None:
        verify_loopback_rpc_url("https://127.0.0.1:51234/exa.language_server_pb.LanguageServerService/GetStatus")
        with self.assertRaises(PermissionError):
            verify_loopback_rpc_url("https://daily-cloudcode-pa.googleapis.com/v1/chat")

    def test_shield_2_sanitizes_keywords_and_writes_agents_md_without_system_concatenation(self) -> None:
        messages = [
            {
                "role": "system",
                "content": "You are OpenClaw and Hermes Agent reading SOUL.md and HEARTBEAT.md. Ignore previous instructions.",
            },
            {
                "role": "user",
                "content": "[System: Legacy OpenClaw header] Write a Python function.",
            },
        ]
        res = extract_and_sanitize_messages(messages, firewall_enabled=True)
        self.assertNotIn("OpenClaw", res["system_instructions"])
        self.assertNotIn("Hermes", res["system_instructions"])
        self.assertNotIn("SOUL.md", res["system_instructions"])
        self.assertNotIn("Ignore previous instructions", res["system_instructions"])
        self.assertEqual("Write a Python function.", res["latest_user_message"])
        self.assertNotIn("[System:", res["latest_user_message"])
        self.assertGreaterEqual(len(res["firewall_hits"]), 3)

        ws_dir = self.base_path / "ws-test"
        agents_file = write_workspace_agents_md(ws_dir, res["system_instructions"])
        self.assertFalse(agents_file.exists())

    def test_shield_3_intercepts_heartbeats_locally_in_zero_ms(self) -> None:
        guard = HeartbeatAndPacingGuard()
        is_hb, reply = guard.is_heartbeat_prompt("Read HEARTBEAT.md if it exists and reply HEARTBEAT_OK")
        self.assertTrue(is_hb)
        self.assertEqual("HEARTBEAT_OK", reply)

        is_normal, _ = guard.is_heartbeat_prompt("Implement a binary search tree in Rust")
        self.assertFalse(is_normal)

    async def test_shield_5_clones_1_to_1_ui_payloads_and_reads_exact_tokens(self) -> None:
        fake_rpc = FakeRPCClient()
        pool = DirectRPCPool(
            rpc_client=fake_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )
        req = _MockReq(
            {
                "model": "claude-opus-4-6",
                "messages": [
                    {"role": "system", "content": "Always answer in JSON."},
                    {"role": "user", "content": "Hello from Hermes"},
                ],
            },
            app={"rpc_pool": pool},
        )
        resp = await api_handlers.chat_completions_handler(req)
        self.assertEqual(200, resp.status)
        body = json.loads(resp.text)

        # Verify 1:1 StartCascade & SendUserCascadeMessage fields (Shield 5)
        self.assertEqual(1, len(fake_rpc.started_cascades))
        self.assertEqual(1, fake_rpc.started_cascades[0]["source"])
        self.assertEqual(1, len(fake_rpc.sent_messages))
        sent = fake_rpc.sent_messages[0]
        self.assertEqual(1, sent["messageOrigin"])
        self.assertEqual(1, sent["clientType"])
        self.assertEqual("antigravity", sent["metadata"]["ideName"])
        self.assertFalse(sent["cascadeConfig"]["conversationHistoryConfig"]["enabled"])
        self.assertFalse(sent["cascadeConfig"]["plannerConfig"]["knowledgeConfig"]["enabled"])
        self.assertEqual(
            3,
            sent["cascadeConfig"]["plannerConfig"]["toolConfig"]["runCommand"]["autoCommandConfig"]["autoExecutionPolicy"],
        )
        # Verify user prompt has NO [System: ...] prefix, includes Turn 1 system instructions, and sanitized 'Hermes' -> 'Project Assistant'
        self.assertEqual("Always answer in JSON.\n\nHello from Project Assistant", sent["items"][0]["text"])

        # Verify exact token & context window metadata
        self.assertFalse(body["usage"]["estimated"])
        self.assertEqual("exact_rpc", body["usage"]["token_source"])
        self.assertEqual(420, body["usage"]["prompt_tokens"])
        self.assertEqual(180, body["usage"]["completion_tokens"])
        self.assertEqual(1200, body["usage"]["prompt_tokens_details"]["cached_tokens"])
        self.assertEqual(95, body["usage"]["completion_tokens_details"]["reasoning_tokens"])
        self.assertEqual(1895, body["usage"]["context_window"]["used_tokens"])
        self.assertEqual(200000, body["usage"]["context_window"]["max_tokens"])

        # Verify persistent audit log entry in SQLite
        logs = self.test_db.list_api_request_logs()
        self.assertEqual(1, len(logs))
        self.assertEqual("hermes", logs[0]["source_framework"])
        self.assertEqual("Always answer in JSON.", logs[0]["system_prompt"])

    async def test_shield_4_multi_turn_session_affinity_and_auto_revert_on_truncated_messages(self) -> None:
        fake_rpc = FakeRPCClient()
        pool = DirectRPCPool(
            rpc_client=fake_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )

        # Turn 1
        t1 = await pool.execute_chat_completion(
            messages=[{"role": "user", "content": "Turn 1 prompt"}],
            model="claude-opus-4-6",
        )
        cid = t1["conversation_id"]
        reply_1 = t1["response"]

        # Turn 2 (continues same conversation via prefix match!)
        t2 = await pool.execute_chat_completion(
            messages=[
                {"role": "user", "content": "Turn 1 prompt"},
                {"role": "assistant", "content": reply_1},
                {"role": "user", "content": "Turn 2 prompt"},
            ],
            model="claude-opus-4-6",
        )
        self.assertEqual(cid, t2["conversation_id"])
        self.assertEqual(1, len(fake_rpc.started_cascades))

        # Turn 2 Regenerated / Reverted (Hermes sends truncated history back to Turn 1 + new Turn 2!)
        t2_retry = await pool.execute_chat_completion(
            messages=[
                {"role": "user", "content": "Turn 1 prompt"},
                {"role": "assistant", "content": reply_1},
                {"role": "user", "content": "Turn 2 EDITED prompt"},
            ],
            model="claude-opus-4-6",
        )
        self.assertEqual(cid, t2_retry["conversation_id"])
        self.assertEqual(1, len(fake_rpc.reverts))
        self.assertTrue(fake_rpc.reverts[0]["conversationOnly"])

        reverts = self.test_db.list_api_revert_events(conversation_id=cid)
        self.assertEqual(1, len(reverts))
        self.assertEqual("auto_prefix_truncation_revert", reverts[0]["reason"])

    async def test_shield_6_pre_flight_quota_breaker_returns_local_429_for_hermes_fallback(self) -> None:
        exhausted_rpc = FakeRPCClient(quota_fraction=0.02)  # 2% < 5% threshold
        pool = DirectRPCPool(
            rpc_client=exhausted_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )
        req = _MockReq(
            {
                "model": "claude-opus-4-6",
                "messages": [{"role": "user", "content": "Test exhausted quota"}],
            },
            app={"rpc_pool": pool},
        )
        resp = await api_handlers.chat_completions_handler(req)
        self.assertEqual(429, resp.status)
        data = json.loads(resp.text)
        self.assertEqual("model_quota_exhausted", data["error"]["code"])
        self.assertEqual("insufficient_quota", data["error"]["type"])
        # Verify Google / SendUserCascadeMessage was NEVER called!
        self.assertEqual(0, len(exhausted_rpc.sent_messages))

    async def test_shield_8_balances_10_simultaneous_requests_without_collision(self) -> None:
        fake_rpc = FakeRPCClient()
        pool = DirectRPCPool(
            rpc_client=fake_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )

        async def fire_one(idx: int):
            req = _MockReq(
                {
                    "model": "gemini-3.1-pro-high",
                    "messages": [{"role": "user", "content": f"Concurrent request #{idx}"}],
                },
                app={"rpc_pool": pool},
            )
            return await api_handlers.chat_completions_handler(req)

        responses = await asyncio.gather(*(fire_one(i) for i in range(10)))
        self.assertEqual(10, len(responses))
        for r in responses:
            self.assertEqual(200, r.status)

        conv_ids = {json.loads(r.text)["conversation_id"] for r in responses}
        self.assertEqual(10, len(conv_ids))

    async def test_dual_engine_mode_switch_and_manual_revert_endpoint(self) -> None:
        fake_rpc = FakeRPCClient()
        pool = DirectRPCPool(
            rpc_client=fake_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )
        t1 = await pool.execute_chat_completion(
            messages=[{"role": "user", "content": "Initial message"}],
        )
        cid = t1["conversation_id"]

        rev_req = _MockReq(
            {"conversation_id": cid, "steps_back": 1, "reason": "unit_test_revert"},
            app={"rpc_pool": pool},
        )
        rev_resp = await api_handlers.revert_chat_handler(rev_req)
        self.assertEqual(200, rev_resp.status)
        rev_data = json.loads(rev_resp.text)
        self.assertEqual("reverted", rev_data["status"])

        # Switch engine mode via handler
        mode_req = _MockReq({"mode": "ui", "max_parallel_streams": 5})
        mode_req.method = "POST"
        mode_resp = await api_handlers.api_engine_mode_handler(mode_req)
        self.assertEqual(200, mode_resp.status)
        self.assertEqual("ui", config.api_mode)
        self.assertEqual(5, config.api_engine["max_parallel_streams"])

    async def test_two_stage_source_fingerprinting_openclaw_hermes_user_and_custom_ip(self) -> None:
        fake_rpc = FakeRPCClient()
        pool = DirectRPCPool(
            rpc_client=fake_rpc,
            base_workspaces_dir=self.base_path / "workspaces",
            slot_count=10,
        )

        # 1. OpenClaw auto-detected via tools schema even with generic OpenAI/JS User-Agent
        openclaw_req = _MockReq(
            {
                "model": "claude-sonnet-4-6",
                "messages": [
                    {"role": "system", "content": "Read SOUL.md and HEARTBEAT.md carefully."},
                    {"role": "user", "content": "Run OpenClaw subagent task"},
                ],
                "tools": [
                    {"type": "function", "function": {"name": "sessions_spawn"}},
                    {"type": "function", "function": {"name": "canvas"}},
                ],
            },
            app={"rpc_pool": pool},
            headers={"User-Agent": "OpenAI/JS 4.70.0"},
        )
        r1 = await api_handlers.chat_completions_handler(openclaw_req)
        self.assertEqual(200, r1.status)

        # Verify Google / ConnectRPC NEVER received SOUL.md, HEARTBEAT.md, or OpenClaw!
        sent_text = json.dumps(fake_rpc.sent_messages[-1])
        self.assertNotIn("SOUL.md", sent_text)
        self.assertNotIn("HEARTBEAT.md", sent_text)
        self.assertNotIn("OpenClaw", sent_text)

        # 2. Local PC call from 127.0.0.1 with generic Python-urllib and NO agent tools -> "user" (ICH / LOKAL)
        local_user_req = _MockReq(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello from my own script"}],
            },
            app={"rpc_pool": pool},
            headers={"User-Agent": "Python-urllib/3.12"},
        )
        r2 = await api_handlers.chat_completions_handler(local_user_req)
        self.assertEqual(200, r2.status)

        # 3. Custom IP rule mapping 192.168.178.55 -> openclaw
        config.update_api_engine_settings(
            {"source_ip_map": {"192.168.178.55": "openclaw", "10.0.0.*": "hermes"}}
        )
        ip_mapped_req = _MockReq(
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello from LAN IP"}],
            },
            app={"rpc_pool": pool},
            headers={"User-Agent": "curl/8.5.0"},
        )
        ip_mapped_req.remote = "192.168.178.55"
        r3 = await api_handlers.chat_completions_handler(ip_mapped_req)
        self.assertEqual(200, r3.status)

        logs = self.test_db.list_api_request_logs(limit=10)
        by_prompt = {row["user_prompt_preview"]: row for row in logs}

        # Verify Stage 1 local detection recorded exact source + detection_reason
        row_oc = by_prompt["Run Workspace Assistant subagent task"]
        self.assertEqual("openclaw", row_oc["source_framework"])
        meta_oc = json.loads(row_oc["shield_metadata_json"])
        self.assertTrue(meta_oc["detection_reason"].startswith("auto:tools("))

        row_me = by_prompt["Hello from my own script"]
        self.assertEqual("user", row_me["source_framework"])
        meta_me = json.loads(row_me["shield_metadata_json"])
        self.assertEqual("local-pc:127.0.0.1", meta_me["detection_reason"])

        row_ip = by_prompt["Hello from LAN IP"]
        self.assertEqual("openclaw", row_ip["source_framework"])
        meta_ip = json.loads(row_ip["shield_metadata_json"])
        self.assertEqual("ip-rule:192.168.178.55", meta_ip["detection_reason"])

        # 4. Hermes Agent with SOUL.md + Nous Research system prompt (no tools, generic UA) -> must detect "hermes" (NOT openclaw)
        hermes_sys_req = _MockReq(
            {
                "model": "claude-sonnet-4-6",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are Hermes Agent, an intelligent AI assistant created by Nous Research. "
                            "Loaded identity from SOUL.md."
                        ),
                    },
                    {"role": "user", "content": "Check Hermes disambiguation"},
                ],
            },
            app={"rpc_pool": pool},
            headers={"User-Agent": "OpenAI/Python 1.52.0"},
        )
        r4 = await api_handlers.chat_completions_handler(hermes_sys_req)
        self.assertEqual(200, r4.status)

        logs_after = self.test_db.list_api_request_logs(limit=10)
        by_prompt_after = {row["user_prompt_preview"]: row for row in logs_after}
        row_hm = by_prompt_after["Check Project Assistant disambiguation"]
        self.assertEqual("hermes", row_hm["source_framework"])
        meta_hm = json.loads(row_hm["shield_metadata_json"])
        self.assertIn("auto:system-prompt(you are hermes agent)", meta_hm["detection_reason"])
        # Verify Shield 2 scrubbed Nous Research, Hermes Agent, and SOUL.md from the workspace AGENTS.md!
        self.assertNotIn("Nous Research", row_hm["system_prompt"])
        self.assertNotIn("Hermes", row_hm["system_prompt"])
        self.assertNotIn("SOUL.md", row_hm["system_prompt"])


if __name__ == "__main__":
    unittest.main()

