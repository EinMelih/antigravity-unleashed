"""The API desktop must not inherit the private Gemini home or workspace."""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.api_profile import APIProfileRuntime


class ApiHomeIsolationTests(unittest.TestCase):
    def test_initialization_does_not_import_private_rules_or_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private"
            private_config = private / ".gemini/config"
            private_config.mkdir(parents=True)
            source = private_config / "config.json"
            source.write_text(json.dumps({"plugins": {"private-plugin": {"enabled": True}}, "sidecars": {"private-sidecar": {}}, "userSettings": {"privateRule": "PRIVATE_RULE_SENTINEL"}}), encoding="utf-8")
            (private_config / "AGENTS.md").write_text("PRIVATE_RULE_SENTINEL", encoding="utf-8")
            before = source.read_bytes()
            with (
                patch("src.api_profile.Path.home", return_value=private),
                patch.dict(os.environ, {"LOCALAPPDATA": str(private / "AppData/Local"), "APPDATA": str(private / "AppData/Roaming")}),
            ):
                runtime = APIProfileRuntime()
                runtime._seed_authentication_once()
            settings = json.loads((runtime.config_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual({"plugins": {}, "sidecars": {}, "userSettings": {}}, settings)
            self.assertNotIn("PRIVATE_RULE_SENTINEL", (runtime.config_dir / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(before, source.read_bytes())
            self.assertTrue((runtime.config_dir / "USER.md").is_file())
            self.assertTrue((runtime.config_dir / "MEMORY.md").is_file())

    def test_native_process_receives_an_independent_home_and_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"LOCALAPPDATA": temporary}):
                runtime = APIProfileRuntime()
            runtime.app_data_dir.mkdir(parents=True)
            with (
                patch.object(runtime, "get_process_ids", return_value=[]),
                patch.object(runtime, "_verify_installed_modifier"),
                patch.object(runtime, "_seed_authentication_once"),
                patch("src.api_profile.socket.socket") as socket_factory,
                patch("src.api_profile.subprocess.Popen") as launch,
            ):
                socket_factory.return_value.__enter__.return_value.connect_ex.return_value = 1
                runtime.ensure_started()
            environment = launch.call_args.kwargs["env"]
            private_home = str(Path.home()).casefold()
            self.assertNotEqual(private_home, environment.get("USERPROFILE", "").casefold())
            self.assertNotEqual(private_home, environment.get("HOME", "").casefold())
            self.assertIn("ANTIGRAVITY_PROFILE_HOME", environment)
            self.assertEqual(environment["USERPROFILE"], environment["ANTIGRAVITY_PROFILE_HOME"])
            self.assertEqual(environment["HOME"], environment["ANTIGRAVITY_PROFILE_HOME"])
            self.assertIn("cwd", launch.call_args.kwargs)
            self.assertNotEqual(Path.cwd(), Path(launch.call_args.kwargs["cwd"]))
            self.assertNotEqual(os.environ.get("APPDATA"), environment["APPDATA"])


if __name__ == "__main__":
    unittest.main()
