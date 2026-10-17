import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src import project_handlers
from src.integrity_sync import (
    _grpc_web_status,
    _select_language_server_candidate,
    delete_integrity_convo,
    encode_field_bytes,
    encode_varint,
    enrich_tool_call,
    get_integrity_chat_history,
    scan_antigravity_conversation_catalog,
)
from src.project_handlers import (
    handle_archive_antigravity_conversation,
    handle_create_integrity_chat,
    handle_delete_integrity_chat,
    handle_get_antigravity_conversations,
    handle_get_integrity_chats,
    handle_open_antigravity_brain_directory,
    handle_restore_antigravity_conversation,
    handle_send_integrity_message,
    handle_stream_integrity_chat,
)


def field_varint(field_number, value):
    return encode_varint(field_number << 3) + encode_varint(value)


def timestamp(seconds):
    return field_varint(1, seconds)


def summary(
    title,
    *,
    created_at,
    workspace_uri="",
    project_id="",
    archived=False,
    status_code=1,
):
    payload = (
        encode_field_bytes(1, title.encode("utf-8"))
        + field_varint(2, 3)
        + encode_field_bytes(3, timestamp(created_at + 10))
        + encode_field_bytes(4, f"trajectory-{created_at}".encode("utf-8"))
        + field_varint(5, status_code)
        + encode_field_bytes(7, timestamp(created_at))
    )
    if workspace_uri:
        payload += encode_field_bytes(
            9,
            encode_field_bytes(1, workspace_uri.encode("utf-8")),
        )
    if archived:
        payload += encode_field_bytes(
            15,
            field_varint(4, 1)
            + encode_field_bytes(5, timestamp(created_at + 20)),
        )
    metadata = encode_field_bytes(
        6,
        f"root-{created_at}".encode("utf-8"),
    )
    if project_id:
        metadata += encode_field_bytes(18, project_id.encode("utf-8"))
    payload += encode_field_bytes(17, metadata)
    return payload


def catalog_entry(conversation_id, summary_payload):
    map_entry = (
        encode_field_bytes(1, conversation_id.encode("utf-8"))
        + encode_field_bytes(2, summary_payload)
    )
    return encode_field_bytes(1, map_entry)


def grpc_web_trailers(status, message=""):
    trailer_lines = [f"grpc-status: {status}"]
    if message:
        trailer_lines.append(f"grpc-message: {message}")
    payload = ("\r\n".join(trailer_lines) + "\r\n").encode("utf-8")
    return b"\x80" + len(payload).to_bytes(4, "big") + payload


class TestConversationCatalog(unittest.TestCase):
    def test_grpc_status_text_inside_data_frame_is_not_a_trailer(self):
        payload = b"grpc-status: 0\r\n"
        body = b"\x00" + len(payload).to_bytes(4, "big") + payload

        self.assertEqual(_grpc_web_status(body), (None, ""))

    def test_language_server_selection_matches_active_desktop_backend(self):
        candidates = [
            {"pid": 1, "csrf": "first", "ports": {55506, 55508}},
            {"pid": 2, "csrf": "second", "ports": {61248, 61249, 61260}},
            {"pid": 3, "csrf": "desktop", "ports": {65015, 65016}},
        ]

        selected = _select_language_server_candidate(candidates, 65015)

        self.assertEqual(selected["pid"], 3)

    def test_language_server_selection_fails_closed_when_backend_is_unmatched(self):
        candidates = [
            {"pid": 1, "csrf": "first", "ports": {55506, 55508}},
            {"pid": 2, "csrf": "second", "ports": {61248, 61249}},
        ]

        self.assertIsNone(
            _select_language_server_candidate(candidates, 65015)
        )

    def test_catalog_decodes_normal_project_and_archived_conversations(self):
        normal_id = "11111111-1111-4111-8111-111111111111"
        project_id = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            (conversation_dir / f"{normal_id}.db").touch()
            (conversation_dir / f"{project_id}.db").touch()
            catalog = (
                catalog_entry(
                    normal_id,
                    summary("Normal conversation", created_at=100),
                )
                + catalog_entry(
                    project_id,
                    summary(
                        "Archived project conversation",
                        created_at=200,
                        workspace_uri="file:///D:/work/Antigravity%20Agent",
                        project_id="project-uuid",
                        archived=True,
                    ),
                )
            )
            (antigravity_dir / "agyhub_summaries_proto.pb").write_bytes(catalog)

            with patch("src.integrity_sync.Path.home", return_value=home):
                conversations = scan_antigravity_conversation_catalog()

        self.assertEqual(
            [item["convo_id"] for item in conversations],
            [project_id, normal_id],
        )
        by_id = {item["convo_id"]: item for item in conversations}
        self.assertEqual(by_id[normal_id]["conversation_type"], "normal")
        self.assertFalse(by_id[normal_id]["archived"])
        self.assertEqual(by_id[project_id]["conversation_type"], "project")
        self.assertEqual(by_id[project_id]["project_name"], "Antigravity Agent")
        self.assertEqual(by_id[project_id]["project_uuid"], "project-uuid")
        self.assertTrue(by_id[project_id]["archived"])
        self.assertEqual(by_id[project_id]["archived_at"], 220.0)

    def test_delete_rejects_non_uuid_target(self):
        with self.assertRaisesRegex(ValueError, "Invalid Anti-Gravity"):
            delete_integrity_convo("../not-a-conversation")

    def test_delete_fails_closed_when_summary_index_is_unreadable(self):
        conversation_id = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            antigravity_dir.mkdir(parents=True)
            (antigravity_dir / "agyhub_summaries_proto.pb").touch()

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.Path.read_bytes",
                    side_effect=OSError("temporary read failure"),
                ),
            ):
                result = delete_integrity_convo(conversation_id)

        self.assertFalse(result["success"])
        self.assertTrue(result["found"])
        self.assertEqual(result["code"], "native_delete_unconfirmed")
        self.assertIsNone(result["summary_present"])

    def test_delete_preserves_files_when_grpc_status_is_missing(self):
        conversation_id = "33333333-3333-4333-8333-333333333333"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            database_path = conversation_dir / f"{conversation_id}.db"
            database_path.touch()
            (antigravity_dir / "agyhub_summaries_proto.pb").write_bytes(
                catalog_entry(
                    conversation_id,
                    summary("Unconfirmed deletion", created_at=300),
                )
            )
            response = MagicMock(status=200, headers={})
            response.read.return_value = b""
            connection = MagicMock()
            connection.getresponse.return_value = response

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch("src.integrity_sync.get_ls_grpc_port", return_value=65015),
                patch(
                    "src.integrity_sync.http.client.HTTPConnection",
                    return_value=connection,
                ),
                patch("time.sleep"),
            ):
                result = delete_integrity_convo(conversation_id)

            self.assertFalse(result["success"])
            self.assertIsNone(result["grpc_status"])
            self.assertTrue(database_path.exists())

    def test_delete_preserves_files_when_grpc_status_is_nonzero(self):
        conversation_id = "44444444-4444-4444-8444-444444444444"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            (antigravity_dir / "agyhub_summaries_proto.pb").touch()
            database_path = conversation_dir / f"{conversation_id}.db"
            database_path.touch()
            response = MagicMock(status=200, headers={})
            response.read.return_value = grpc_web_trailers(5, "not found")
            connection = MagicMock()
            connection.getresponse.return_value = response

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch("src.integrity_sync.get_ls_grpc_port", return_value=65015),
                patch(
                    "src.integrity_sync.http.client.HTTPConnection",
                    return_value=connection,
                ),
                patch("time.sleep"),
            ):
                result = delete_integrity_convo(conversation_id)

            self.assertFalse(result["success"])
            self.assertEqual(result["grpc_status"], 5)
            self.assertTrue(database_path.exists())

    def test_delete_requires_summary_entry_to_disappear_before_file_cleanup(self):
        conversation_id = "55555555-5555-4555-8555-555555555555"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            database_path = conversation_dir / f"{conversation_id}.db"
            database_path.touch()
            (antigravity_dir / "agyhub_summaries_proto.pb").write_bytes(
                catalog_entry(
                    conversation_id,
                    summary("Still indexed", created_at=500),
                )
            )
            response = MagicMock(status=200, headers={})
            response.read.return_value = grpc_web_trailers(0)
            connection = MagicMock()
            connection.getresponse.return_value = response

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch("src.integrity_sync.get_ls_grpc_port", return_value=65015),
                patch(
                    "src.integrity_sync.http.client.HTTPConnection",
                    return_value=connection,
                ),
                patch("time.sleep"),
            ):
                result = delete_integrity_convo(conversation_id)

            self.assertFalse(result["success"])
            self.assertEqual(result["grpc_status"], 0)
            self.assertTrue(result["summary_present"])
            self.assertTrue(database_path.exists())

    def test_delete_repairs_confirmed_orphaned_summary_entry(self):
        conversation_id = "66666666-6666-4666-8666-666666666666"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            summary_path = antigravity_dir / "agyhub_summaries_proto.pb"
            summary_path.write_bytes(
                catalog_entry(
                    conversation_id,
                    summary("Orphaned deletion", created_at=600),
                )
            )
            response = MagicMock(status=200, headers={})

            def remove_summary_entry():
                summary_path.write_bytes(b"")
                return grpc_web_trailers(0)

            response.read.side_effect = remove_summary_entry
            connection = MagicMock()
            connection.getresponse.return_value = response

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch("src.integrity_sync.get_ls_grpc_port", return_value=65015),
                patch(
                    "src.integrity_sync.http.client.HTTPConnection",
                    return_value=connection,
                ),
                patch("time.sleep"),
            ):
                result = delete_integrity_convo(conversation_id)

            self.assertTrue(result["success"])
            self.assertTrue(result["found"])
            self.assertFalse(result["summary_present"])
            self.assertEqual(result["removed_files"], [])

    def test_deleted_tombstone_allows_local_only_cleanup_retry(self):
        conversation_id = "99999999-9999-4999-8999-999999999999"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            antigravity_dir = home / ".gemini" / "antigravity"
            conversation_dir = antigravity_dir / "conversations"
            conversation_dir.mkdir(parents=True)
            database_path = conversation_dir / f"{conversation_id}.db"
            database_path.touch()
            (antigravity_dir / "agyhub_summaries_proto.pb").touch()

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch(
                    "src.integrity_sync._has_deleted_tombstone",
                    return_value=True,
                ),
                patch("src.integrity_sync.http.client.HTTPConnection") as http,
                patch("time.sleep"),
            ):
                result = delete_integrity_convo(conversation_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["native_method"], "tombstone-local-cleanup")
        self.assertFalse(database_path.exists())
        http.assert_not_called()


class TestConversationCatalogAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.managed_list_patcher = patch(
            "src.project_handlers.db.list_managed_antigravity_conversations",
            return_value=[],
        )
        self.managed_upsert_patcher = patch(
            "src.project_handlers.db.upsert_managed_antigravity_conversation",
        )
        self.managed_state_patcher = patch(
            "src.project_handlers.db.set_managed_antigravity_conversation_state",
        )
        self.managed_list_patcher.start()
        self.managed_upsert_patcher.start()
        self.managed_state_patcher.start()
        app = web.Application()
        app.router.add_get(
            "/api/antigravity/conversations",
            handle_get_antigravity_conversations,
        )
        app.router.add_get(
            "/api/antigravity/chats",
            handle_get_integrity_chats,
        )
        app.router.add_post(
            "/api/antigravity/chats/{convo_id}/brain/open",
            handle_open_antigravity_brain_directory,
        )
        app.router.add_post(
            "/api/antigravity/chats/{convo_id}/archive",
            handle_archive_antigravity_conversation,
        )
        app.router.add_post(
            "/api/antigravity/chats/{convo_id}/restore",
            handle_restore_antigravity_conversation,
        )
        app.router.add_post(
            "/api/antigravity/chats/{convo_id}/message",
            handle_send_integrity_message,
        )
        app.router.add_post(
            "/api/antigravity/chats",
            handle_create_integrity_chat,
        )
        app.router.add_delete(
            "/api/antigravity/chats/{convo_id}",
            handle_delete_integrity_chat,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.managed_state_patcher.stop()
        self.managed_upsert_patcher.stop()
        self.managed_list_patcher.stop()

    async def test_delete_rejects_busy_worker_without_closing_or_deleting(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": False,
            "code": "conversation_busy",
            "conversation_id": conversation_id,
            "retryable": True,
            "detail_code": "worker_working",
            "worker": {
                "instance_id": "AG-07",
                "activity": "working",
                "detail_code": "worker_working",
                "has_draft": False,
                "binding_status": "confirmed",
            },
        }
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch("src.integrity_sync.delete_integrity_convo") as delete_files,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        payload = await response.json()
        self.assertEqual(response.status, 409, payload)
        self.assertEqual(payload["code"], "conversation_busy")
        self.assertEqual(payload["conversation_id"], conversation_id)
        self.assertEqual(payload["worker"]["instance_id"], "AG-07")
        self.assertEqual(payload["worker"]["activity"], "working")
        manager.prepare_chat_deletion.assert_awaited_once_with(
            conversation_id,
            delete_callback=delete_files,
        )
        delete_files.assert_not_called()
        manager.close_all.assert_awaited_once()

    async def test_delete_allows_reconciled_idle_worker(self):
        conversation_id = "22222222-2222-4222-8222-222222222222"
        deletion = {
            "success": True,
            "found": True,
            "conversation_id": conversation_id,
            "removed_files": [f"{conversation_id}.db"],
            "remaining_files": [],
            "grpc_http_status": 200,
            "grpc_status": 0,
            "grpc_confirmed": True,
            "summary_present": False,
        }
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": True,
            "conversation_id": conversation_id,
            "window_closed": True,
            "deletion_result": deletion,
        }
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch(
                "src.integrity_sync.delete_integrity_convo",
                return_value=deletion,
            ) as delete_files,
            patch("src.project_handlers.db.delete_proxy_messages") as delete_proxy,
            patch("src.project_handlers.db.delete_provider_messages") as delete_provider,
            patch(
                "src.project_handlers.db.upsert_managed_antigravity_conversation",
                create=True,
            ) as upsert_managed,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        self.assertEqual(response.status, 200, await response.text())
        manager.prepare_chat_deletion.assert_awaited_once_with(
            conversation_id,
            delete_callback=delete_files,
        )
        delete_files.assert_not_called()
        delete_proxy.assert_called_once_with(conversation_id)
        delete_provider.assert_called_once_with(conversation_id)
        upsert_managed.assert_called_once_with(conversation_id, state="deleted")
        manager.close_all.assert_awaited_once()

    async def test_delete_does_not_finalize_unconfirmed_native_deletion(self):
        conversation_id = "77777777-7777-4777-8777-777777777777"
        deletion = {
            "success": False,
            "found": True,
            "code": "native_delete_unconfirmed",
            "conversation_id": conversation_id,
            "removed_files": [],
            "remaining_files": [f"{conversation_id}.db"],
            "grpc_http_status": 200,
            "grpc_status": 5,
            "grpc_message": "private backend detail",
            "grpc_confirmed": False,
            "summary_present": True,
        }
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": True,
            "conversation_id": conversation_id,
            "window_closed": False,
            "deletion_result": deletion,
        }
        with (
            patch("src.parallel_cdp.ParallelCDPManager", return_value=manager),
            patch("src.project_handlers.db.delete_proxy_messages") as delete_proxy,
            patch("src.project_handlers.db.delete_provider_messages") as delete_provider,
            patch(
                "src.project_handlers.db.upsert_managed_antigravity_conversation",
            ) as upsert_managed,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        payload = await response.json()
        self.assertEqual(response.status, 503, payload)
        self.assertEqual(payload["code"], "native_delete_unconfirmed")
        self.assertNotIn("grpc_message", payload)
        delete_proxy.assert_not_called()
        delete_provider.assert_not_called()
        upsert_managed.assert_not_called()
        manager.close_all.assert_awaited_once()

    async def test_delete_hides_native_chat_when_local_cleanup_is_incomplete(self):
        conversation_id = "88888888-8888-4888-8888-888888888888"
        private_path = f"C:/private/{conversation_id}.db"
        deletion = {
            "success": False,
            "found": True,
            "code": "local_cleanup_incomplete",
            "conversation_id": conversation_id,
            "removed_files": [],
            "remaining_files": [private_path],
            "grpc_http_status": 200,
            "grpc_status": 0,
            "grpc_confirmed": True,
            "native_method": "DeleteCascadeTrajectory",
            "summary_present": False,
        }
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": True,
            "conversation_id": conversation_id,
            "window_closed": False,
            "deletion_result": deletion,
        }
        with (
            patch("src.parallel_cdp.ParallelCDPManager", return_value=manager),
            patch(
                "src.project_handlers.db.upsert_managed_antigravity_conversation",
            ) as upsert_managed,
            patch("src.project_handlers._invalidate_live_sidebar_cache") as invalidate,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        payload = await response.json()
        self.assertEqual(response.status, 503, payload)
        self.assertEqual(payload["code"], "local_cleanup_incomplete")
        self.assertEqual(payload["remaining_file_count"], 1)
        self.assertNotIn(private_path, await response.text())
        upsert_managed.assert_called_once_with(conversation_id, state="deleted")
        invalidate.assert_called_once_with()
        manager.close_all.assert_awaited_once()

    async def test_delete_normalizes_native_uuid_before_guard_and_deletion(self):
        normalized_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        requested_id = normalized_id.upper()
        deletion = {
            "success": True,
            "found": True,
            "conversation_id": normalized_id,
            "removed_files": [f"{normalized_id}.db"],
            "remaining_files": [],
            "grpc_http_status": 200,
            "grpc_status": 0,
            "grpc_confirmed": True,
            "summary_present": False,
        }
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": True,
            "conversation_id": normalized_id,
            "window_closed": False,
            "deletion_result": deletion,
        }
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch(
                "src.integrity_sync.delete_integrity_convo",
                return_value=deletion,
            ) as delete_files,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{requested_id}"
            )

        self.assertEqual(response.status, 200, await response.text())
        manager.prepare_chat_deletion.assert_awaited_once_with(
            normalized_id,
            delete_callback=delete_files,
        )
        delete_files.assert_not_called()

    async def test_delete_reports_unavailable_native_state_as_sanitized_503(self):
        conversation_id = "88888888-8888-4888-8888-888888888888"
        manager = AsyncMock()
        manager.prepare_chat_deletion.return_value = {
            "allowed": False,
            "code": "conversation_state_unavailable",
            "conversation_id": conversation_id,
            "retryable": True,
            "detail_code": "desktop_state_unavailable",
        }
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch("src.integrity_sync.delete_integrity_convo") as delete_files,
        ):
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        payload = await response.json()
        self.assertEqual(response.status, 503, payload)
        self.assertEqual(payload, {
            "success": False,
            "error": "Conversation state could not be verified.",
            "code": "conversation_state_unavailable",
            "conversation_id": conversation_id,
            "retryable": True,
            "detail_code": "desktop_state_unavailable",
        })
        delete_files.assert_not_called()
        manager.close_all.assert_awaited_once()

    async def test_delete_preserves_provider_conversation_id_case(self):
        conversation_id = "provider-CaseSensitive-ID"
        with patch(
            "src.project_handlers.db.delete_provider_conversation",
            return_value=True,
        ) as delete_provider:
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(
            (await response.json())["conversation_id"],
            conversation_id,
        )
        delete_provider.assert_called_once_with(conversation_id)

    async def test_delete_preserves_proxy_conversation_id_case(self):
        conversation_id = "proxy-CaseSensitive-ID"
        with patch(
            "src.project_handlers.db.delete_proxy_conversation",
            return_value=True,
        ) as delete_proxy:
            response = await self.client.delete(
                f"/api/antigravity/chats/{conversation_id}"
            )

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(
            (await response.json())["conversation_id"],
            conversation_id,
        )
        delete_proxy.assert_called_once_with(conversation_id)

    async def test_active_agents_are_returned_independently_from_visible_filter(self):
        running = {
            "convo_id": "11111111-1111-4111-8111-111111111111",
            "title": "Agent is working",
            "conversation_type": "normal",
            "status": "running",
            "archived": False,
            "updated_at": 300.0,
        }
        archived = {
            "convo_id": "22222222-2222-4222-8222-222222222222",
            "title": "Archived chat",
            "conversation_type": "project",
            "status": "complete",
            "archived": True,
            "updated_at": 200.0,
        }
        with patch(
            "src.integrity_sync.scan_antigravity_conversation_catalog",
            return_value=[running, archived],
        ), patch(
            "src.project_handlers._get_live_antigravity_sidebar_snapshot",
            new=AsyncMock(return_value={
                "available": True,
                "stale": False,
                "chats": [{
                    "id": running["convo_id"],
                    "title": running["title"],
                    "position": 0,
                }],
                "active_id": running["convo_id"],
                "count": 1,
            }),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations?status=archived&type=all"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(
            [item["convo_id"] for item in payload["conversations"]],
            [archived["convo_id"]],
        )
        self.assertEqual(
            [item["convo_id"] for item in payload["active_agents"]],
            [running["convo_id"]],
        )
        self.assertEqual(payload["counts"]["running"], 1)

    async def test_summary_only_keeps_counts_and_active_agents_without_catalog(self):
        running = {
            "convo_id": "11111111-1111-4111-8111-111111111111",
            "title": "Agent is working",
            "conversation_type": "normal",
            "status": "running",
            "archived": False,
            "updated_at": 300.0,
        }
        with patch(
            "src.integrity_sync.scan_antigravity_conversation_catalog",
            return_value=[running],
        ), patch(
            "src.project_handlers._get_live_antigravity_sidebar_snapshot",
            new=AsyncMock(return_value={
                "available": True,
                "stale": False,
                "chats": [{
                    "id": running["convo_id"],
                    "title": running["title"],
                    "position": 0,
                }],
                "active_id": running["convo_id"],
                "count": 1,
            }),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations?summary_only=1"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload["conversations"], [])
        self.assertEqual(payload["counts"]["running"], 1)
        self.assertEqual(payload["active_agents"][0]["convo_id"], running["convo_id"])
        self.assertTrue(payload["filters"]["summary_only"])

    async def test_catalog_excludes_non_sidebar_database_history(self):
        visible_id = "11111111-1111-4111-8111-111111111111"
        hidden_id = "22222222-2222-4222-8222-222222222222"
        archived_id = "33333333-3333-4333-8333-333333333333"
        deleted_id = "44444444-4444-4444-8444-444444444444"
        catalog = [
            {
                "convo_id": visible_id,
                "title": "Visible in Anti-Gravity",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 300.0,
            },
            {
                "convo_id": hidden_id,
                "title": "Old internal database",
                "conversation_type": "project",
                "status": "complete",
                "archived": False,
                "updated_at": 200.0,
            },
            {
                "convo_id": archived_id,
                "title": "Archived conversation",
                "conversation_type": "project",
                "status": "complete",
                "archived": True,
                "updated_at": 100.0,
            },
            {
                "convo_id": deleted_id,
                "title": "Deleted conversation",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 250.0,
            },
        ]
        sidebar = {
            "available": True,
            "stale": False,
            "chats": [
                {
                    "id": visible_id,
                    "title": "Visible live title",
                    "position": 0,
                },
                {
                    "id": archived_id,
                    "title": "Archived conversation",
                    "position": 1,
                },
                {
                    "id": deleted_id,
                    "title": "Deleted conversation",
                    "position": 2,
                },
            ],
            "active_id": visible_id,
            "count": 3,
        }
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=catalog,
            ),
            patch(
                "src.project_handlers._get_live_antigravity_sidebar_snapshot",
                new=AsyncMock(return_value=sidebar),
            ),
            patch(
                "src.project_handlers.db.list_managed_antigravity_conversations",
                side_effect=lambda *, state=None: (
                    [{"conversation_id": deleted_id, "state": "deleted"}]
                    if state == "deleted"
                    else []
                ),
            ),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(
            [item["convo_id"] for item in payload["conversations"]],
            [visible_id, archived_id],
        )
        self.assertEqual(payload["counts"]["visible"], 1)
        self.assertEqual(payload["counts"]["all"], 2)
        self.assertEqual(payload["counts"]["archived"], 1)
        self.assertEqual(payload["visible_conversation_ids"], [visible_id])
        self.assertEqual(payload["archived_conversation_ids"], [archived_id])
        self.assertEqual(
            payload["conversations"][0]["title"],
            "Visible live title",
        )

    async def test_legacy_chat_catalog_excludes_deleted_tombstones(self):
        conversation_id = "55555555-5555-4555-8555-555555555555"
        catalog = [{
            "convo_id": conversation_id,
            "title": "Locally locked deleted chat",
            "conversation_type": "normal",
            "status": "complete",
            "archived": True,
            "updated_at": 100.0,
        }]
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=catalog,
            ),
            patch(
                "src.project_handlers.db.list_managed_antigravity_conversations",
                side_effect=lambda *, state=None: (
                    [{"conversation_id": conversation_id, "state": "deleted"}]
                    if state == "deleted"
                    else []
                ),
            ),
        ):
            response = await self.client.get("/api/antigravity/chats")

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(await response.json(), [])

    async def test_catalog_title_wins_over_technical_sidebar_fallback(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        catalog = [{
            "convo_id": conversation_id,
            "title": "Request about API usage",
            "conversation_type": "normal",
            "status": "complete",
            "archived": False,
            "updated_at": 300.0,
        }]
        sidebar = {
            "available": True,
            "stale": False,
            "chats": [{
                "id": conversation_id,
                "title": "Chat 11111111",
                "position": 0,
            }],
            "active_id": conversation_id,
            "count": 1,
        }
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=catalog,
            ),
            patch(
                "src.project_handlers._get_live_antigravity_sidebar_snapshot",
                new=AsyncMock(return_value=sidebar),
            ),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        conversation = next(
            item
            for item in payload["conversations"]
            if item["convo_id"] == conversation_id
        )
        self.assertEqual(conversation["title"], "Request about API usage")

    async def test_catalog_title_wins_over_sidebar_age_badge(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        catalog = [{
            "convo_id": conversation_id,
            "title": "Request about API usage",
            "conversation_type": "normal",
            "status": "complete",
            "archived": False,
            "updated_at": 300.0,
        }]
        sidebar = {
            "available": True,
            "stale": False,
            "chats": [{
                "id": conversation_id,
                "title": "Request about API usage1d",
                "position": 0,
            }],
            "active_id": conversation_id,
            "count": 1,
        }
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=catalog,
            ),
            patch(
                "src.project_handlers._get_live_antigravity_sidebar_snapshot",
                new=AsyncMock(return_value=sidebar),
            ),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        conversation = next(
            item
            for item in payload["conversations"]
            if item["convo_id"] == conversation_id
        )
        self.assertEqual(conversation["title"], "Request about API usage")

    async def test_collapsed_refresh_keeps_previously_discovered_project_chat(self):
        normal_id = "11111111-1111-4111-8111-111111111111"
        project_id = "22222222-2222-4222-8222-222222222222"
        newly_seen_id = "33333333-3333-4333-8333-333333333333"
        catalog = [
            {
                "convo_id": normal_id,
                "title": "Normal conversation",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 300.0,
            },
            {
                "convo_id": project_id,
                "title": "Project conversation",
                "conversation_type": "project",
                "status": "complete",
                "archived": False,
                "updated_at": 200.0,
            },
            {
                "convo_id": newly_seen_id,
                "title": "Newly seen conversation",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 100.0,
            },
        ]
        client = AsyncMock()
        client.get_chat_list.side_effect = [
            {
                "chats": [
                    {"id": normal_id, "title": "Normal conversation"},
                    {"id": project_id, "title": "Project conversation"},
                ],
                "active_id": normal_id,
                "count": 2,
                "complete": True,
            },
            {
                "chats": [
                    {"id": normal_id, "title": "Normal conversation"},
                    {"id": newly_seen_id, "title": "Newly seen conversation"},
                ],
                "active_id": normal_id,
                "count": 2,
                "complete": False,
                "limit_reached": True,
            },
        ]
        manager = AsyncMock()
        manager.get_devtools_port.return_value = 9222
        manager.get_all_page_targets.return_value = [{
            "id": "sidebar-target",
            "webSocketDebuggerUrl": "ws://127.0.0.1/sidebar-target",
        }]
        manager.get_client_for_target.return_value = client

        project_handlers._invalidate_live_sidebar_cache()
        try:
            with (
                patch(
                    "src.integrity_sync.scan_antigravity_conversation_catalog",
                    return_value=catalog,
                ),
                patch(
                    "src.parallel_cdp.ParallelCDPManager",
                    return_value=manager,
                ),
            ):
                first_response = await self.client.get(
                    "/api/antigravity/conversations"
                )
                project_handlers._LIVE_SIDEBAR_CACHE["updated_at"] = 0.0
                collapsed_response = await self.client.get(
                    "/api/antigravity/conversations"
                )
        finally:
            project_handlers._invalidate_live_sidebar_cache()

        self.assertEqual(first_response.status, 200, await first_response.text())
        self.assertEqual(
            collapsed_response.status,
            200,
            await collapsed_response.text(),
        )
        payload = await collapsed_response.json()
        visible_ids = set(payload["visible_conversation_ids"])
        self.assertEqual(
            visible_ids & {normal_id, project_id, newly_seen_id},
            {normal_id, project_id, newly_seen_id},
        )
        self.assertEqual(payload["sidebar"]["count"], 3)
        self.assertTrue(payload["sidebar"]["stale"])
        self.assertFalse(payload["sidebar"]["complete"])

    async def test_incomplete_cold_sidebar_scan_is_not_published(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        client = AsyncMock()
        client.get_chat_list.return_value = {
            "chats": [{"id": conversation_id, "title": "Partial conversation"}],
            "active_id": conversation_id,
            "count": 1,
            "complete": False,
            "limit_reached": True,
        }
        manager = AsyncMock()
        manager.get_devtools_port.return_value = 9222
        manager.get_all_page_targets.return_value = [{
            "id": "partial-sidebar-target",
            "webSocketDebuggerUrl": "ws://127.0.0.1/partial-sidebar-target",
        }]
        manager.get_client_for_target.return_value = client

        project_handlers._invalidate_live_sidebar_cache()
        try:
            with patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ):
                snapshot = await (
                    project_handlers._get_live_antigravity_sidebar_snapshot()
                )
        finally:
            project_handlers._invalidate_live_sidebar_cache()

        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["chats"], [])
        self.assertIn("incomplete", snapshot["error"].lower())

    async def test_sidebar_snapshot_keeps_fresh_order_before_cached_rows(self):
        first_id = "11111111-1111-4111-8111-111111111111"
        second_id = "22222222-2222-4222-8222-222222222222"
        client = AsyncMock()
        client.get_chat_list.side_effect = [
            {
                "chats": [
                    {"id": first_id, "title": "First conversation"},
                    {"id": second_id, "title": "Second conversation"},
                ],
                "active_id": first_id,
                "count": 2,
                "complete": True,
            },
            {
                "chats": [
                    {"id": second_id, "title": "Second conversation"},
                ],
                "active_id": second_id,
                "count": 1,
                "complete": True,
            },
        ]
        manager = AsyncMock()
        manager.get_devtools_port.return_value = 9222
        manager.get_all_page_targets.return_value = [{
            "id": "sidebar-target",
            "webSocketDebuggerUrl": "ws://127.0.0.1/sidebar-target",
        }]
        manager.get_client_for_target.return_value = client

        project_handlers._invalidate_live_sidebar_cache()
        try:
            with patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ):
                await project_handlers._get_live_antigravity_sidebar_snapshot()
                project_handlers._LIVE_SIDEBAR_CACHE["updated_at"] = 0.0
                refreshed = await (
                    project_handlers._get_live_antigravity_sidebar_snapshot()
                )
        finally:
            project_handlers._invalidate_live_sidebar_cache()

        self.assertEqual(
            [item["id"] for item in refreshed["chats"]],
            [second_id, first_id],
        )

    async def test_catalog_keeps_registered_hub_chat_outside_sidebar_viewport(self):
        visible_id = "11111111-1111-4111-8111-111111111111"
        managed_id = "22222222-2222-4222-8222-222222222222"
        unrelated_id = "33333333-3333-4333-8333-333333333333"
        catalog = [
            {
                "convo_id": visible_id,
                "title": "Visible chat",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 300.0,
            },
            {
                "convo_id": managed_id,
                "title": "Hub-created chat",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 200.0,
            },
            {
                "convo_id": unrelated_id,
                "title": "Unrelated old database",
                "conversation_type": "normal",
                "status": "complete",
                "archived": False,
                "updated_at": 100.0,
            },
        ]
        sidebar = {
            "available": True,
            "stale": False,
            "chats": [{
                "id": visible_id,
                "title": "Visible live title",
                "position": 0,
            }],
            "active_id": visible_id,
            "count": 1,
        }
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=catalog,
            ),
            patch(
                "src.project_handlers._get_live_antigravity_sidebar_snapshot",
                new=AsyncMock(return_value=sidebar),
            ),
            patch(
                "src.project_handlers.db.list_managed_antigravity_conversations",
                create=True,
                side_effect=lambda *, state=None: (
                    [{
                        "conversation_id": managed_id,
                        "state": "active",
                    }]
                    if state == "active"
                    else []
                ),
            ),
        ):
            response = await self.client.get(
                "/api/antigravity/conversations"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(
            [item["convo_id"] for item in payload["conversations"]],
            [visible_id, managed_id],
        )
        managed = payload["conversations"][1]
        self.assertTrue(managed["managed_by_hub"])
        self.assertFalse(managed["visible_in_sidebar"])

    async def test_verified_create_registers_native_chat(self):
        conversation_id = "44444444-4444-4444-8444-444444444444"
        message = "Create and remember this Hub chat"
        manager = AsyncMock()
        manager.create_new_normal_chat_window.return_value = {
            "chat_id": conversation_id,
            "target_id": "target-04",
            "instance_id": "AG-04",
        }
        with (
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch(
                "src.integrity_sync.get_integrity_chat_history",
                return_value={
                    "history": [{
                        "idx": 7,
                        "role": "user",
                        "content": message,
                    }],
                    "max_idx": 7,
                },
            ),
            patch(
                "src.integrity_sync.scan_integrity_convos",
                return_value=[{
                    "convo_id": conversation_id,
                    "workspace_path": "",
                }],
            ),
            patch(
                "src.project_handlers.db.upsert_managed_antigravity_conversation",
                create=True,
            ) as register_chat,
        ):
            response = await self.client.post(
                "/api/antigravity/chats",
                json={
                    "conversation_type": "normal",
                    "message": message,
                },
            )

        self.assertEqual(response.status, 200, await response.text())
        register_chat.assert_called_once_with(
            conversation_id,
            project_id=None,
            state="active",
        )
        manager.close_all.assert_awaited_once()

    async def test_archived_conversation_cannot_receive_native_message(self):
        convo_id = "11111111-1111-4111-8111-111111111111"
        with patch(
            "src.integrity_sync.scan_antigravity_conversation_catalog",
            return_value=[{
                "convo_id": convo_id,
                "archived": True,
                "status": "complete",
            }],
        ):
            response = await self.client.post(
                f"/api/antigravity/chats/{convo_id}/message",
                json={"message": "must be blocked"},
            )

        self.assertEqual(response.status, 409, await response.text())
        payload = await response.json()
        self.assertEqual(payload["code"], "conversation_archived")
        self.assertTrue(payload["requires_restore"])

    async def test_archive_and_restore_use_verified_worker_action(self):
        convo_id = "11111111-1111-4111-8111-111111111111"
        manager = AsyncMock()
        manager.set_chat_archived.return_value = {
            "window_id": "AG-02",
            "verified": True,
        }
        metadata = {
            "convo_id": convo_id,
            "archived": False,
            "project_uuid": "project-section",
        }
        with (
            patch(
                "src.integrity_sync.scan_antigravity_conversation_catalog",
                return_value=[metadata],
            ),
            patch(
                "src.parallel_cdp.ParallelCDPManager",
                return_value=manager,
            ),
            patch(
                "src.project_handlers.db.set_managed_antigravity_conversation_state",
                create=True,
            ) as set_managed_state,
        ):
            response = await self.client.post(
                f"/api/antigravity/chats/{convo_id}/archive"
            )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["archived"])
        manager.set_chat_archived.assert_awaited_once_with(
            convo_id,
            True,
            section="project-section",
            minimize=True,
        )
        set_managed_state.assert_called_once_with(convo_id, "archived")
        manager.close_all.assert_awaited_once()

    async def test_brain_directory_open_is_conversation_scoped(self):
        convo_id = "11111111-1111-4111-8111-111111111111"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            target = home / ".gemini" / "antigravity" / "brain" / convo_id
            target.mkdir(parents=True)
            with (
                patch("src.project_handlers.Path.home", return_value=home),
                patch("src.project_handlers._open_local_directory") as open_directory,
            ):
                response = await self.client.post(
                    f"/api/antigravity/chats/{convo_id}/brain/open"
                )

        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertTrue(payload["success"])
        open_directory.assert_called_once_with(target.resolve())

    async def test_brain_directory_rejects_traversal(self):
        response = await self.client.post(
            "/api/antigravity/chats/not-a-uuid/brain/open"
        )
        self.assertEqual(response.status, 400, await response.text())


class TestConversationStreamCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.router.add_get(
            "/api/antigravity/chats/{convo_id}/stream",
            handle_stream_integrity_chat,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_completed_assistant_step_emits_stream_end_without_five_minute_wait(self):
        convo_id = "11111111-1111-4111-8111-111111111111"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            conversation_dir = home / ".gemini" / "antigravity" / "conversations"
            conversation_dir.mkdir(parents=True)
            db_path = conversation_dir / f"{convo_id}.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB, status INTEGER)"
                )
                connection.execute(
                    "INSERT INTO steps VALUES (?, ?, ?, ?)",
                    (1, 15, b"assistant", 3),
                )
                connection.commit()
            finally:
                connection.close()
            with (
                patch("src.project_handlers.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.get_agent_response_from_payload",
                    return_value=("Antwort fertig", ""),
                ),
            ):
                response = await self.client.get(
                    f"/api/antigravity/chats/{convo_id}/stream?after=0"
                )
                body = await response.text()

        self.assertEqual(response.status, 200)
        self.assertIn('"content": "Antwort fertig"', body)
        self.assertIn('"reason": "assistant_complete"', body)

    async def test_running_server_does_not_block_later_assistant_response(self):
        convo_id = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            conversation_dir = home / ".gemini" / "antigravity" / "conversations"
            conversation_dir.mkdir(parents=True)
            db_path = conversation_dir / f"{convo_id}.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB, status INTEGER)"
                )
                connection.executemany(
                    "INSERT INTO steps VALUES (?, ?, ?, ?)",
                    (
                        (1, 21, b"command", 2),
                        (2, 15, b"assistant", 3),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            with (
                patch("src.project_handlers.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.parse_tool_call",
                    return_value=(
                        "run_command",
                        '{"CommandLine":"npx vite --port 5173 --host"}',
                    ),
                ),
                patch(
                    "src.integrity_sync.get_agent_response_from_payload",
                    return_value=("Antwort nach Serverstart", ""),
                ),
            ):
                response = await self.client.get(
                    f"/api/antigravity/chats/{convo_id}/stream?after=0"
                )
                body = await response.text()

        self.assertEqual(response.status, 200)
        self.assertIn('"type": "tool_call"', body)
        self.assertIn('"is_running": true', body)
        self.assertIn('"background_task": true', body)
        self.assertIn('"port": 5173', body)
        self.assertIn('"content": "Antwort nach Serverstart"', body)
        self.assertIn('"reason": "assistant_complete"', body)

    async def test_user_approval_gate_is_explicit_in_stream(self):
        convo_id = "55555555-5555-4555-8555-555555555555"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            conversation_dir = home / ".gemini" / "antigravity" / "conversations"
            conversation_dir.mkdir(parents=True)
            db_path = conversation_dir / f"{convo_id}.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "CREATE TABLE steps ("
                    "idx INTEGER, step_type INTEGER, step_payload BLOB, "
                    "status INTEGER)"
                )
                connection.executemany(
                    "INSERT INTO steps VALUES (?, ?, ?, ?)",
                    (
                        (1, 21, b"command", 9),
                        (2, 15, b"assistant", 3),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            with (
                patch("src.project_handlers.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.parse_tool_call",
                    return_value=(
                        "run_command",
                        '{"CommandLine":"python validate_json.py"}',
                    ),
                ),
                patch(
                    "src.integrity_sync.get_agent_response_from_payload",
                    return_value=("Nach Freigabe fortgesetzt", ""),
                ),
            ):
                response = await self.client.get(
                    f"/api/antigravity/chats/{convo_id}/stream?after=0"
                )
                body = await response.text()

        self.assertEqual(response.status, 200)
        self.assertIn('"status": 9', body)
        self.assertIn('"requires_user_input": true', body)
        self.assertIn('"is_running": false', body)
        self.assertIn('"state": "waiting_user"', body)
        self.assertIn('"reason": "assistant_complete"', body)


class TestToolRuntimeMetadata(unittest.TestCase):
    def test_vite_command_is_enriched_as_running_background_task(self):
        enriched = enrich_tool_call(
            "run_command",
            (
                '{"CommandLine":"npx vite --port 5173 --host",'
                '"Cwd":"C:\\\\workspace\\\\todo-app",'
                '"WaitMsBeforeAsync":2500,'
                '"toolAction":"Starting local dev server",'
                '"toolSummary":"Start Vite dev server"}'
            ),
            2,
        )

        self.assertEqual(enriched["kind"], "command")
        self.assertEqual(enriched["state"], "running")
        self.assertTrue(enriched["server_command"])
        self.assertTrue(enriched["background_task"])
        self.assertEqual(enriched["port"], 5173)
        self.assertEqual(enriched["url"], "http://127.0.0.1:5173")

    def test_history_preserves_running_tool_status(self):
        conversation_id = "33333333-3333-4333-8333-333333333333"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            conversation_dir = (
                home / ".gemini" / "antigravity" / "conversations"
            )
            conversation_dir.mkdir(parents=True)
            database_path = conversation_dir / f"{conversation_id}.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE steps ("
                    "idx INTEGER, step_type INTEGER, step_payload BLOB, "
                    "status INTEGER)"
                )
                connection.execute(
                    "INSERT INTO steps VALUES (?, ?, ?, ?)",
                    (19, 21, b"command", 2),
                )
                connection.commit()
            finally:
                connection.close()

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.parse_tool_call",
                    return_value=(
                        "run_command",
                        '{"CommandLine":"npx vite --port 5173 --host"}',
                    ),
                ),
            ):
                history = get_integrity_chat_history(conversation_id)

        command = history["history"][0]
        self.assertEqual(command["status"], 2)
        self.assertTrue(command["is_running"])
        self.assertFalse(command["complete"])
        self.assertEqual(command["enriched"]["state"], "running")
        self.assertEqual(command["enriched"]["port"], 5173)

    def test_history_marks_user_approval_gate(self):
        conversation_id = "44444444-4444-4444-8444-444444444444"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            conversation_dir = (
                home / ".gemini" / "antigravity" / "conversations"
            )
            conversation_dir.mkdir(parents=True)
            database_path = conversation_dir / f"{conversation_id}.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE steps ("
                    "idx INTEGER, step_type INTEGER, step_payload BLOB, "
                    "status INTEGER)"
                )
                connection.execute(
                    "INSERT INTO steps VALUES (?, ?, ?, ?)",
                    (23, 21, b"command", 9),
                )
                connection.commit()
            finally:
                connection.close()

            with (
                patch("src.integrity_sync.Path.home", return_value=home),
                patch(
                    "src.integrity_sync.parse_tool_call",
                    return_value=(
                        "run_command",
                        '{"CommandLine":"python validate_json.py"}',
                    ),
                ),
            ):
                history = get_integrity_chat_history(conversation_id)

        command = history["history"][0]
        self.assertEqual(command["status"], 9)
        self.assertTrue(command["requires_user_input"])
        self.assertFalse(command["is_running"])
        self.assertFalse(command["complete"])
        self.assertEqual(command["enriched"]["state"], "waiting_user")


class TestConversationCatalogDashboard(unittest.TestCase):
    def test_dashboard_exposes_live_agents_and_responsive_assets(self):
        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "dashboard" / "index.html").read_text(encoding="utf-8")
        script = (project_root / "dashboard" / "js" / "app.js").read_text(encoding="utf-8")
        style = (project_root / "dashboard" / "css" / "style.css").read_text(encoding="utf-8")

        self.assertIn("js/app.js?v=20260824-16", html)
        self.assertIn("css/style.css?v=20260727-14", html)
        self.assertIn('id="hub-attention-preview"', html)
        self.assertIn('id="hub-agent-preview"', html)
        self.assertIn('id="hub-command-palette"', html)
        self.assertIn('id="antigravity-active-agent-list"', script)
        self.assertIn("payload.active_agents", script)
        self.assertIn("ANTIGRAVITY_THINKING_PHASES", script)
        self.assertIn("syncOpenChatWindowTitles", script)
        self.assertIn("/brain/open", script)
        self.assertNotIn('button-planer', script)
        self.assertNotIn('fetch("/api/command"', script)
        self.assertIn("/api/antigravity/workers", script)
        self.assertIn("renderAntigravityWorkerPool", script)
        self.assertIn("hub-command-center", style)
        self.assertIn("antigravity-thinking-symbol", style)
        self.assertIn("antigravity-worker-card", style)
        self.assertIn("antigravity-activity-spinner", style)
        self.assertIn("@media (max-width: 520px)", style)
        self.assertIn(".orchestrator-sidebar:not(.is-open)", style)
        self.assertIn("overflow-x: clip", style)
        self.assertIn("100dvh", style)
        self.assertIn("#chats-tab {\n    overflow: hidden;", style)
        self.assertIn("#antigravity-chats-root {\n    display: flex;", style)
        self.assertIn(".antigravity-chat-browser {\n    display: flex;", style)
        self.assertIn("max-width: min(1560px, calc(100% - 32px));", style)
        self.assertIn("#antigravity-chats-root {\n        display: block;", style)
        self.assertIn("visible_conversation_ids", script)
        self.assertIn("Conversation ist archiviert", script)
        self.assertIn("setConversationArchived", script)
        self.assertIn("chat-tool-activity-group", script)
        self.assertIn("backgroundTasks: {}", script)
        self.assertIn("getBackgroundTasksPanelHtml", script)
        self.assertIn("syncBackgroundTaskFromToolEvent", script)
        self.assertIn("chat-command-row state-", script)
        self.assertIn(".chat-background-tasks", style)
        self.assertIn(".chat-command-row.state-running", style)
        self.assertIn("antigravity-chat-toolbar", script)
        self.assertIn("Chats · ${counts.archived || 0} archiviert", script)
        self.assertNotIn("angezeigt · ${counts.visible", script)
        self.assertIn("flex: 0 1 auto;", style)
        self.assertIn(".antigravity-compact-filter select", style)
        self.assertIn(".chat-archive-lock", style)
        self.assertIn(".conversation-archive-toggle", style)
        self.assertIn(".chat-delivery-status", style)
        self.assertIn(".chat-mic-btn.is-recording", style)


if __name__ == "__main__":
    unittest.main()
