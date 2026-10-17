import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import config as config_module


class ConfigLocationTests(unittest.TestCase):
    def test_default_config_is_outside_repository(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            resolved = config_module.resolve_config_path()

        self.assertEqual(resolved, config_module.DEFAULT_CONFIG_PATH.resolve())
        self.assertNotEqual(resolved.parent, config_module.BASE_DIR)
        self.assertNotEqual(resolved, config_module.BASE_DIR / "config.json")

    def test_environment_can_override_config_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "hub-config.json"
            with patch.dict(
                os.environ,
                {config_module.CONFIG_ENV_VAR: str(expected)},
                clear=False,
            ):
                resolved = config_module.resolve_config_path()

        self.assertEqual(resolved, expected.resolve())

    def test_api_bridge_host_defaults_to_loopback(self) -> None:
        manager = config_module.ConfigurationManager.__new__(
            config_module.ConfigurationManager
        )
        manager.config_dict = {}

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(manager.api_bridge_host, "127.0.0.1")

    def test_api_bridge_host_allows_explicit_lan_opt_in(self) -> None:
        manager = config_module.ConfigurationManager.__new__(
            config_module.ConfigurationManager
        )
        manager.config_dict = {"host": "0.0.0.0"}

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(manager.api_bridge_host, "0.0.0.0")

    def test_api_bridge_host_environment_override_wins(self) -> None:
        manager = config_module.ConfigurationManager.__new__(
            config_module.ConfigurationManager
        )
        manager.config_dict = {"host": "127.0.0.1"}

        with patch.dict(
            os.environ,
            {config_module.API_HOST_ENV_VAR: "0.0.0.0"},
            clear=False,
        ):
            self.assertEqual(manager.api_bridge_host, "0.0.0.0")

    def test_watchdog_host_defaults_to_loopback(self) -> None:
        manager = config_module.ConfigurationManager.__new__(
            config_module.ConfigurationManager
        )
        manager.config_dict = {"watchdog": {}}

        self.assertEqual(manager.watchdog["host"], "127.0.0.1")

    def test_portable_projects_directory_and_safe_debug_default(self) -> None:
        manager = config_module.ConfigurationManager.__new__(
            config_module.ConfigurationManager
        )
        manager.config_dict = {"projects_base_dir": ""}

        self.assertEqual(manager.projects_base_dir, str(Path.home() / "Projects"))
        self.assertFalse(manager.debug_mode)

    def test_linux_launchers_pass_the_documented_config_path(self) -> None:
        start_script = (config_module.BASE_DIR / "start.sh").read_text(encoding="utf-8")
        self.assertIn(
            'CONFIG_FILE="${ANTIGRAVITY_HUB_CONFIG:-${SCRIPT_DIR}/config.json}"',
            start_script,
        )
        self.assertIn('export ANTIGRAVITY_HUB_CONFIG="${CONFIG_FILE}"', start_script)

        unit_names = (
            "antigravity-bridge.service",
            "antigravity-proxy.service",
            "antigravity-sessions.service",
            "antigravity-healer.service",
            "antigravity-watchdog.service",
        )
        for unit_name in unit_names:
            unit = (config_module.BASE_DIR / "deploy" / unit_name).read_text(encoding="utf-8")
            self.assertIn(
                "Environment=ANTIGRAVITY_HUB_CONFIG=/opt/antigravity-web/config.json",
                unit,
            )


if __name__ == "__main__":
    unittest.main()
