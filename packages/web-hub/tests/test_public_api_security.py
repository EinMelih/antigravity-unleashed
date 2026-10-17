import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"test_public_api_{os.getpid()}.db"
os.environ["ANTIGRAVITY_HUB_DB"] = str(_TEST_DB_PATH)

from src import (
    api_server,
    file_browser,
    healer_server,
    proxy_server,
    session_admin_handlers,
    session_server,
    voice_handlers,
    watchdog_handlers,
)
from src.local_admin_security import validate_loopback_host


class PublicApiSecurityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        if _TEST_DB_PATH.exists():
            try:
                _TEST_DB_PATH.unlink()
            except OSError:
                pass

    async def test_dashboard_entry_points_target_react_index(self) -> None:
        response = await proxy_server.redirect_dashboard(SimpleNamespace())

        self.assertEqual(response.status, 302)
        self.assertEqual(
            response.headers["Location"],
            "/dashboard/react/index.html#/studio",
        )

    async def test_api_root_and_health_never_expose_configured_token(self) -> None:
        sentinel = "sentinel-secret-that-must-not-leak"
        fake_config = SimpleNamespace(
            api_bridge_port=8123,
            api_keys={},
            auth_token=sentinel,
        )
        cdp = SimpleNamespace(
            _connected=False,
            ws=None,
            devtools_port=None,
            backend_port=None,
        )

        with patch.object(api_server, "config", fake_config):
            root_response = await api_server.root_handler(SimpleNamespace())
            health_response = await api_server.health_handler(
                SimpleNamespace(app={"cdp": cdp})
            )

        root_payload = json.loads(root_response.text)
        health_payload = json.loads(health_response.text)
        self.assertNotIn(sentinel, root_response.text)
        self.assertNotIn(sentinel, health_response.text)
        self.assertEqual(root_payload["auth"], "Authorization: Bearer <configured-token>")
        self.assertNotIn("auth_token", health_payload)
        self.assertNotIn("devtools_port", health_payload["cdp"])
        self.assertNotIn("backend_port", health_payload["cdp"])
        self.assertNotIn("log_file", health_payload)
        self.assertTrue(health_payload["authentication"]["required"])

    async def test_health_reports_when_authentication_is_disabled(self) -> None:
        fake_config = SimpleNamespace(api_bridge_port=8123, api_keys={}, auth_token="")
        cdp = SimpleNamespace(
            _connected=False,
            ws=None,
            devtools_port=None,
            backend_port=None,
        )

        with patch.object(api_server, "config", fake_config):
            response = await api_server.health_handler(SimpleNamespace(app={"cdp": cdp}))

        self.assertFalse(json.loads(response.text)["authentication"]["required"])

    async def test_protected_api_route_rejects_missing_credentials(self) -> None:
        fake_config = SimpleNamespace(
            api_keys={},
            auth_token="sentinel-secret",
            rate_limit={"enabled": False},
        )
        request = SimpleNamespace(
            path="/v1/models",
            method="GET",
            headers={},
            remote="127.0.0.1",
        )

        with patch.object(api_server, "config", fake_config):
            response = await api_server.auth_middleware(request, AsyncMock())

        self.assertEqual(response.status, 401)
        self.assertNotIn("sentinel-secret", response.text)

    async def test_cdp_diagnostics_require_credentials(self) -> None:
        fake_config = SimpleNamespace(
            api_keys={},
            auth_token="sentinel-secret",
            rate_limit={"enabled": False},
        )
        request = SimpleNamespace(
            path="/health/cdp",
            method="GET",
            headers={},
            remote="127.0.0.1",
        )
        handler = AsyncMock()

        with patch.object(api_server, "config", fake_config):
            response = await api_server.auth_middleware(request, handler)

        self.assertEqual(response.status, 401)
        handler.assert_not_awaited()

    async def test_session_manager_never_exposes_token(self) -> None:
        sentinel = "sentinel-session-secret"
        fake_config = SimpleNamespace(auth_token=sentinel)

        with patch.object(session_admin_handlers, "config", fake_config):
            root_response = await session_admin_handlers.root_handler(SimpleNamespace())

        request = SimpleNamespace(
            path="/sessions",
            method="GET",
            headers={},
        )
        with patch.object(session_server, "config", fake_config):
            auth_response = await session_server.auth_middleware(request, AsyncMock())

        self.assertNotIn(sentinel, root_response.text)
        self.assertNotIn(sentinel, auth_response.text)
        self.assertEqual(auth_response.status, 401)

        fake_main_config = SimpleNamespace(
            auth_token=sentinel,
            load=Mock(),
            session_manager={"port": 8124},
        )
        output = io.StringIO()
        with (
            patch.object(session_server, "config", fake_main_config),
            patch.object(session_server.web, "run_app"),
            redirect_stdout(output),
        ):
            session_server.main()
        self.assertNotIn(sentinel, output.getvalue())
        self.assertIn("Bearer <configured-token>", output.getvalue())

    def test_voice_auth_trusts_loopback_but_requires_token_for_lan(self) -> None:
        fake_config = SimpleNamespace(auth_token="sentinel-voice-secret")
        local_request = SimpleNamespace(headers={}, remote="127.0.0.1")
        lan_request = SimpleNamespace(headers={}, remote="192.0.2.10")
        authorized_lan_request = SimpleNamespace(
            headers={"Authorization": "Bearer sentinel-voice-secret"},
            remote="192.0.2.10",
        )

        with patch.object(voice_handlers, "config", fake_config):
            self.assertTrue(voice_handlers.check_auth(local_request))
            self.assertFalse(voice_handlers.check_auth(lan_request))
            self.assertTrue(voice_handlers.check_auth(authorized_lan_request))

    def test_main_uses_configured_bind_host(self) -> None:
        fake_config = SimpleNamespace(
            load=Mock(),
            api_bridge_host="127.0.0.9",
            api_bridge_port=8123,
        )

        with (
            patch.object(api_server, "config", fake_config),
            patch.object(api_server.web, "run_app") as run_app,
        ):
            api_server.main()

        self.assertEqual(run_app.call_args.kwargs["host"], "127.0.0.9")
        self.assertEqual(run_app.call_args.kwargs["port"], 8123)

    def test_non_loopback_bindings_fail_closed(self) -> None:
        with patch.object(
            api_server,
            "config",
            SimpleNamespace(api_keys={}, auth_token=""),
        ):
            with self.assertRaises(RuntimeError):
                api_server.validate_bind_security("0.0.0.0")

        with patch.object(
            api_server,
            "config",
            SimpleNamespace(api_keys={}, auth_token="strong-random-token"),
        ):
            api_server.validate_bind_security("0.0.0.0")

        proxy_server.validate_listen_host("127.0.0.1")
        with self.assertRaises(RuntimeError):
            proxy_server.validate_listen_host("0.0.0.0")

        validate_loopback_host("127.0.0.1", service="Watchdog")
        with self.assertRaises(RuntimeError):
            validate_loopback_host("0.0.0.0", service="Watchdog")

    async def test_admin_services_reject_external_browser_origins(self) -> None:
        request = SimpleNamespace(
            method="POST",
            headers={"Origin": "https://untrusted.example"},
        )
        for middleware in (
            healer_server.cors_middleware,
            watchdog_handlers.cors_middleware,
        ):
            handler = AsyncMock()
            response = await middleware(request, handler)
            self.assertEqual(response.status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
            handler.assert_not_awaited()

    async def test_admin_services_allow_exact_loopback_origin(self) -> None:
        request = SimpleNamespace(
            method="GET",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        for middleware in (
            healer_server.cors_middleware,
            watchdog_handlers.cors_middleware,
        ):
            handler = AsyncMock(return_value=api_server.web.Response(status=200))
            response = await middleware(request, handler)
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.headers["Access-Control-Allow-Origin"],
                "http://127.0.0.1:8000",
            )
            self.assertNotEqual(
                response.headers["Access-Control-Allow-Origin"],
                "*",
            )

    def test_public_nginx_requires_auth_and_does_not_publish_wildcard_cors(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        nginx = (project_root / "deploy" / "nginx-antigravity.conf").read_text(encoding="utf-8")

        self.assertIn('auth_basic "Anti-Gravity Hub"', nginx)
        self.assertIn('auth_basic "Anti-Gravity Monitor"', nginx)
        self.assertGreaterEqual(
            nginx.count("auth_basic_user_file /etc/nginx/antigravity.htpasswd"),
            2,
        )
        self.assertNotIn("Access-Control-Allow-Origin' '*'", nginx)
        self.assertNotIn("return 204", nginx)
        self.assertGreaterEqual(nginx.count("proxy_hide_header Access-Control-Allow-Origin"), 3)

    def test_runtime_sources_do_not_embed_a_maintainer_home_path(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        sources = (
            (project_root / "src" / "config.py").read_text(encoding="utf-8")
            + (project_root / "src" / "project_handlers.py").read_text(encoding="utf-8")
            + (project_root / "dashboard" / "index.html").read_text(encoding="utf-8")
        )
        self.assertNotIn("EinMelih", sources)
        forbidden_backup = "D:\\" + "".join(["win11 ", "alt ", "backup"])
        self.assertNotIn(forbidden_backup, sources)

    async def test_file_preview_is_limited_to_registered_project_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            allowed = root / "registered"
            blocked = root / "registered-secret"
            allowed.mkdir()
            blocked.mkdir()
            (allowed / "README.md").write_text("safe", encoding="utf-8")
            (blocked / "secret.txt").write_text("private", encoding="utf-8")
            projects = [{"path": str(allowed), "integrity_workspace_path": ""}]

            with patch.object(file_browser.db, "get_projects", return_value=projects):
                valid = await file_browser.file_preview_handler(
                    SimpleNamespace(query={"project_path": str(allowed), "file_path": "README.md"})
                )
                invalid_root = await file_browser.file_preview_handler(
                    SimpleNamespace(query={"project_path": str(blocked), "file_path": "secret.txt"})
                )
                traversal = await file_browser.file_preview_handler(
                    SimpleNamespace(query={"project_path": str(allowed), "file_path": "../registered-secret/secret.txt"})
                )

        self.assertEqual(valid.status, 200)
        self.assertEqual(json.loads(valid.text)["content"], "safe")
        self.assertEqual(invalid_root.status, 403)
        self.assertEqual(traversal.status, 403)
        self.assertNotIn("private", invalid_root.text + traversal.text)

    async def test_file_browser_requires_and_stays_within_registered_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            allowed = root / "registered"
            child = allowed / "child"
            blocked = root / "blocked"
            child.mkdir(parents=True)
            blocked.mkdir()
            projects = [{"path": str(allowed), "integrity_workspace_path": ""}]

            with patch.object(file_browser.db, "get_projects", return_value=projects):
                missing = await file_browser.browse_handler(SimpleNamespace(query={}))
                valid_root = await file_browser.browse_handler(
                    SimpleNamespace(query={"path": str(allowed)})
                )
                valid_child = await file_browser.browse_handler(
                    SimpleNamespace(query={"path": str(child)})
                )
                invalid = await file_browser.browse_handler(
                    SimpleNamespace(query={"path": str(blocked)})
                )

        self.assertEqual(missing.status, 400)
        self.assertEqual(valid_root.status, 200)
        self.assertIsNone(json.loads(valid_root.text)["parent"])
        self.assertEqual(valid_child.status, 200)
        self.assertIsNotNone(json.loads(valid_child.text)["parent"])
        self.assertEqual(invalid.status, 403)


if __name__ == "__main__":
    unittest.main()
