"""Tests for Cross-Platform Linux/Docker Headless API & API-Logs UI Migration."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_linux_auth_seed import export_linux_auth_seed
from src import api_handlers, api_server, api_window, proxy_handlers, proxy_server, window_tiling
from src.api_profile import APIProfileRuntime, resolve_api_profile_home
from src.config import ConfigurationManager, get_runtime_mode
from src.rpc_client import DirectConnectRPCClient
from src.rpc_pool import DirectRPCPool


class LinuxHeadlessMigrationTests(unittest.IsolatedAsyncioTestCase):
    def test_win32_modules_are_safe_noops_on_posix(self) -> None:
        with patch.object(window_tiling, "os") as mock_os:
            mock_os.name = "posix"
            self.assertEqual(window_tiling.get_antigravity_hwnds(), [])
            self.assertIsNone(window_tiling.tile_windows([101, 202]))

        with patch.object(api_window, "os") as mock_os:
            mock_os.name = "posix"
            self.assertEqual(api_window.apply_visibility({1234}, True), 0)
            self.assertIsNone(api_window.start_enforcer(9229))

    def test_resolve_api_profile_home_supports_env_and_posix_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            custom_home = Path(tmp) / "custom-api-home"
            with patch.dict(os.environ, {"ANTIGRAVITY_API_HOME": str(custom_home)}):
                self.assertEqual(resolve_api_profile_home(), custom_home)
                client = DirectConnectRPCClient()
                self.assertEqual(client.profile_home, custom_home)
                pool = DirectRPCPool(rpc_client=client, slot_count=2)
                self.assertEqual(pool.profile_home, custom_home)
                self.assertTrue((custom_home / "workspaces" / "ws-00").is_dir())

        with (
            patch("src.api_profile.is_windows_os", return_value=False),
            patch.dict(os.environ, {"ANTIGRAVITY_API_HOME": "", "ANTIGRAVITY_DOCKER": "1"}, clear=False),
        ):
            self.assertEqual(resolve_api_profile_home().as_posix(), "/data/antigravity-api/home")

        with tempfile.TemporaryDirectory() as tmp:
            xdg_dir = Path(tmp) / "xdg-data"
            with (
                patch("src.api_profile.is_windows_os", return_value=False),
                patch("src.api_profile.Path.exists", return_value=False),
                patch.dict(
                    os.environ,
                    {"ANTIGRAVITY_API_HOME": "", "ANTIGRAVITY_DOCKER": "0", "XDG_DATA_HOME": str(xdg_dir)},
                    clear=False,
                ),
            ):
                resolved = resolve_api_profile_home()
                self.assertEqual(resolved, xdg_dir / "AntigravityApiProfile/home")

    def test_api_profile_runtime_uses_posix_paths_without_appdata_roaming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_home = Path(tmp) / "linux-api-home"
            private_home = Path(tmp) / "linux-private-home"
            private_home.mkdir(parents=True)
            with (
                patch("src.api_profile.is_windows_os", return_value=False),
                patch("src.api_profile.Path.home", return_value=private_home),
                patch.dict(
                    os.environ,
                    {"ANTIGRAVITY_API_HOME": str(api_home), "XDG_CONFIG_HOME": str(private_home / ".config")},
                    clear=False,
                ),
            ):
                runtime = APIProfileRuntime()
                self.assertEqual(runtime.profile_home, api_home)
                self.assertEqual(runtime.user_data_dir, api_home / ".config/Antigravity-api")
                self.assertEqual(runtime.user_data_dir.relative_to(api_home).as_posix(), ".config/Antigravity-api")
                runtime._seed_authentication_once()
                self.assertTrue((api_home / ".cache/tmp").is_dir())
                self.assertTrue((runtime.config_dir / "config.json").is_file())
                self.assertTrue((runtime.app_data_dir / "api_profile_seed.json").is_file())

    def test_wait_for_rpc_ready_detects_listening_socket_and_exited_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"ANTIGRAVITY_API_HOME": str(Path(tmp) / "api-home")}):
                runtime = APIProfileRuntime()
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
                    srv.bind(("127.0.0.1", 0))
                    srv.listen(1)
                    port = srv.getsockname()[1]
                    self.assertTrue(runtime._wait_for_rpc_ready(port, timeout=1.0))

                dead_proc = SimpleNamespace(poll=lambda: 1)
                self.assertFalse(runtime._wait_for_rpc_ready(65431, proc=dead_proc, timeout=0.5))

    def test_posix_psutil_discovery_finds_headless_language_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_home = Path(tmp) / "api-home"
            client = DirectConnectRPCClient(profile_home=api_home)
            fake_proc = MagicMock()
            fake_proc.info = {
                "pid": 4242,
                "name": "language_server_linux_x64",
                "cmdline": [
                    "/opt/antigravity/bin/language_server_linux_x64",
                    "--standalone",
                    "--headless",
                    "--https_server_port=44123",
                    "--csrf_token=linux-csrf-token-123",
                    f"--app_data_dir={api_home}/.gemini/antigravity-api",
                ],
            }
            fake_proc.net_connections.return_value = []

            with (
                patch("src.config.is_windows_os", return_value=False),
                patch("psutil.process_iter", return_value=[fake_proc]),
                patch.object(client, "_probe_port_sync", return_value=True) as probe,
            ):
                discovered = client._discover_api_language_server()
                self.assertEqual(discovered, (44123, "linux-csrf-token-123"))
                probe.assert_called_once_with(44123, "linux-csrf-token-123")

    async def test_headless_linux_runtime_mode_redirects_and_allows_container_bind(self) -> None:
        with patch.dict(os.environ, {"ANTIGRAVITY_DOCKER": "1"}, clear=False):
            self.assertEqual(get_runtime_mode(), "headless_linux")
            proxy_server.validate_listen_host("0.0.0.0")
            api_server.validate_bind_security("0.0.0.0")

            dash_resp = await proxy_server.redirect_dashboard(SimpleNamespace())
            self.assertEqual(dash_resp.status, 302)
            self.assertEqual(dash_resp.headers["Location"], "/dashboard/react/index.html#/api-logs")

            root_req = SimpleNamespace(method="GET", path="/", app={})
            root_resp = await proxy_handlers.proxy_handler(root_req)
            self.assertEqual(root_resp.status, 302)
            self.assertEqual(root_resp.headers["Location"], "/dashboard/react/index.html#/api-logs")

            mode_resp = await api_handlers.api_engine_mode_handler(SimpleNamespace(method="GET"))
            mode_payload = json.loads(mode_resp.text)
            self.assertEqual(mode_payload["runtime_mode"], "headless_linux")

    def test_api_bridge_enabled_respects_config_and_env_override(self) -> None:
        cfg = ConfigurationManager()
        cfg.config_dict["api_bridge_enabled"] = True
        with patch.dict(os.environ, {"ANTIGRAVITY_DISABLE_LOCAL_API": "", "ANTIGRAVITY_ENABLE_LOCAL_API": ""}, clear=False):
            self.assertTrue(cfg.api_bridge_enabled)

        with patch.dict(os.environ, {"ANTIGRAVITY_DISABLE_LOCAL_API": "1"}, clear=False):
            self.assertFalse(cfg.api_bridge_enabled)

        cfg.config_dict["api_bridge_enabled"] = False
        with patch.dict(os.environ, {"ANTIGRAVITY_DISABLE_LOCAL_API": "", "ANTIGRAVITY_ENABLE_LOCAL_API": ""}, clear=False):
            self.assertFalse(cfg.api_bridge_enabled)

    def test_export_linux_auth_seed_copies_state_and_filters_cookies(self) -> None:
        from contextlib import closing

        with tempfile.TemporaryDirectory() as tmp:
            src_user_data = Path(tmp) / "win-user-data"
            (src_user_data / "User/globalStorage").mkdir(parents=True)
            (src_user_data / "Network").mkdir(parents=True)
            (src_user_data / "Local State").write_text(
                json.dumps({"os_crypt": {"encrypted_key": "test-key"}, "other": "ignored"}),
                encoding="utf-8",
            )
            state_db = src_user_data / "User/globalStorage/state.vscdb"
            with closing(sqlite3.connect(str(state_db))) as conn:
                conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
                conn.execute("INSERT INTO ItemTable VALUES ('antigravityAuthStatus', '{\"email\":\"test@example.com\"}')")
                conn.commit()

            cookies_db = src_user_data / "Network/Cookies"
            with closing(sqlite3.connect(str(cookies_db))) as conn:
                conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
                conn.execute("INSERT INTO cookies VALUES ('.google.com', 'SID', 'google-session')")
                conn.execute("INSERT INTO cookies VALUES ('example.org', 'TRACK', 'should-be-removed')")
                conn.commit()

            out_dir = Path(tmp) / "docker-data"
            manifest = export_linux_auth_seed(out_dir, source_user_data_dir=src_user_data)
            self.assertIn("state.vscdb", manifest["copied"])
            self.assertIn("local_state", manifest["copied"])
            self.assertIn("authentication_cookies", manifest["copied"])
            self.assertTrue((out_dir / "home/workspaces/ws-00").is_dir())
            self.assertTrue((out_dir / "home/workspaces/ws-09").is_dir())

            exported_cookies = out_dir / "home/.config/Antigravity-api/Network/Cookies"
            with closing(sqlite3.connect(str(exported_cookies))) as conn:
                hosts = [row[0] for row in conn.execute("SELECT host_key FROM cookies").fetchall()]
            self.assertEqual(hosts, [".google.com"])

    def test_root_docker_files_are_present(self) -> None:
        self.assertTrue((REPO_ROOT / "Dockerfile").is_file())
        self.assertTrue((REPO_ROOT / "docker-compose.yml").is_file())
        self.assertTrue((REPO_ROOT / "scripts/docker-entrypoint.sh").is_file())
        compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("./docker-data:/data/antigravity-api", compose_text)
        self.assertIn("8000", compose_text)
        self.assertIn("8001", compose_text)


if __name__ == "__main__":
    unittest.main()
