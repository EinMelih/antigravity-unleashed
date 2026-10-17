import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from src.antigravity_project_settings import (
    HUB_AGENT_SETTINGS,
    AntigravityProjectSettingsError,
    enforce_hub_project_settings,
    is_antigravity_project_configured,
)


def project_payload(project_uuid: str, workspace: Path) -> dict:
    uri_path = "/" + str(workspace.resolve()).replace("\\", "/")
    return {
        "id": project_uuid,
        "name": str(workspace),
        "projectResources": {
            "resources": [{
                "gitFolder": {
                    "folderUri": "file://" + urllib.parse.quote(uri_path),
                    "defaultBranch": "main",
                }
            }]
        },
        "settings": {"unrelatedSetting": "preserved"},
        "unrelatedTopLevel": {"preserved": True},
    }


class TestAntigravityProjectSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        self.workspace = Path(self.temp.name) / "worktree"
        self.workspace.mkdir()
        self.project_uuid = "2ef7621b-a22a-4eec-96e4-c5ce5b578b5e"
        self.config_path = self.root / f"{self.project_uuid}.json"
        self.config_path.write_text(
            json.dumps(project_payload(self.project_uuid, self.workspace)),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_workspace_resolution_updates_only_required_policy(self):
        result = enforce_hub_project_settings(
            workspace_path=str(self.workspace),
            config_root=self.root,
            wait_timeout=0,
        )
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertEqual(result["project_uuid"], self.project_uuid)
        self.assertEqual(payload["settings"]["unrelatedSetting"], "preserved")
        self.assertEqual(payload["unrelatedTopLevel"], {"preserved": True})
        for key, value in HUB_AGENT_SETTINGS.items():
            self.assertEqual(payload["settings"][key], value)

    def test_second_call_is_idempotent(self):
        enforce_hub_project_settings(
            project_uuid=self.project_uuid,
            config_root=self.root,
            wait_timeout=0,
        )
        first = self.config_path.read_text(encoding="utf-8")
        result = enforce_hub_project_settings(
            project_uuid=self.project_uuid,
            config_root=self.root,
            wait_timeout=0,
        )

        self.assertFalse(result["changed"])
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), first)

    def test_uuid_and_workspace_mismatch_is_rejected(self):
        other = Path(self.temp.name) / "other-worktree"
        other.mkdir()

        with self.assertRaises(AntigravityProjectSettingsError):
            enforce_hub_project_settings(
                project_uuid=self.project_uuid,
                workspace_path=str(other),
                config_root=self.root,
                wait_timeout=0,
            )

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("fileAccessPolicy", payload["settings"])

    def test_read_only_identity_check_requires_matching_native_config(self):
        self.assertTrue(is_antigravity_project_configured(
            workspace_path=str(self.workspace),
            project_uuid=self.project_uuid,
            config_root=self.root,
        ))

        other = Path(self.temp.name) / "other-worktree"
        other.mkdir()
        self.assertFalse(is_antigravity_project_configured(
            workspace_path=str(other),
            project_uuid=self.project_uuid,
            config_root=self.root,
        ))

        self.config_path.unlink()
        self.assertFalse(is_antigravity_project_configured(
            workspace_path=str(self.workspace),
            project_uuid=self.project_uuid,
            config_root=self.root,
        ))

    def test_ambiguous_workspace_is_rejected(self):
        duplicate_uuid = "9f3a4dad-3102-4edb-9473-75de4a14b986"
        (self.root / f"{duplicate_uuid}.json").write_text(
            json.dumps(project_payload(duplicate_uuid, self.workspace)),
            encoding="utf-8",
        )

        with self.assertRaises(AntigravityProjectSettingsError):
            enforce_hub_project_settings(
                workspace_path=str(self.workspace),
                config_root=self.root,
                wait_timeout=0,
            )

    def test_dedicated_workspace_wins_over_multifolder_overlap(self):
        old_workspace = Path(self.temp.name) / "old-worktree"
        old_workspace.mkdir()
        old_uuid = "7129c10f-9c44-4f42-a5e7-b64b41c27713"
        old_payload = project_payload(old_uuid, old_workspace)
        old_payload["projectResources"]["resources"].append(
            project_payload(old_uuid, self.workspace)["projectResources"]
            ["resources"][0]
        )
        old_path = self.root / f"{old_uuid}.json"
        old_path.write_text(json.dumps(old_payload), encoding="utf-8")

        self.assertTrue(is_antigravity_project_configured(
            workspace_path=str(self.workspace),
            project_uuid=self.project_uuid,
            config_root=self.root,
        ))
        self.assertFalse(is_antigravity_project_configured(
            workspace_path=str(self.workspace),
            project_uuid=old_uuid,
            config_root=self.root,
        ))

        result = enforce_hub_project_settings(
            workspace_path=str(self.workspace),
            config_root=self.root,
            wait_timeout=0,
        )

        dedicated = json.loads(self.config_path.read_text(encoding="utf-8"))
        overlapping = json.loads(old_path.read_text(encoding="utf-8"))
        self.assertEqual(result["project_uuid"], self.project_uuid)
        for key, value in HUB_AGENT_SETTINGS.items():
            self.assertEqual(dedicated["settings"][key], value)
            self.assertNotIn(key, overlapping["settings"])


if __name__ == "__main__":
    unittest.main()
