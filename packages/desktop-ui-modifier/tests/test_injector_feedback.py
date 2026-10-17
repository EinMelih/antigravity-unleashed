from __future__ import annotations

import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from test_repack_guard import load_script


def write_archive_fixture(target, version):
    content = json.dumps({"version": version}).encode("utf-8")
    header = json.dumps({"files": {"package.json": {"size": len(content), "offset": "0"}}}).encode("utf-8")
    padded = header + b"\0" * ((-len(header)) % 4)
    header_pickle = struct.pack("<II", 4 + len(padded), len(header)) + padded
    target.write_bytes(struct.pack("<II", 4, len(header_pickle)) + header_pickle + content)


class RepackFeedbackTests(unittest.TestCase):
    def test_unsupported_update_is_reported_before_build_or_shutdown(self):
        repack = load_script("repack_preflight_test", "repack_and_restart.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "install"
            resources = install / "resources"
            resources.mkdir(parents=True)
            executable = install / "Antigravity.exe"
            executable.write_bytes(b"test executable")
            archive = resources / "app.asar"
            write_archive_fixture(archive, "9.9.9")
            original = archive.read_bytes()
            with (
                mock.patch.object(repack, "SCRATCH_DIR", root / "scratch"),
                mock.patch.object(repack, "resolve_install_paths", return_value=(install, resources, executable)),
                mock.patch.object(repack, "claim_trigger_chat_id", return_value=None),
                mock.patch.object(repack, "get_last_active_session_id", return_value=None),
                mock.patch.object(repack.os, "getcwd", return_value=str(root)),
                mock.patch.object(repack.subprocess, "run") as build,
                mock.patch.object(repack, "stop_install_process_tree") as shutdown,
            ):
                self.assertEqual(1, repack.run_repack())
                build.assert_not_called()
                shutdown.assert_not_called()
            self.assertEqual(original, archive.read_bytes())
            status = json.loads((root / "scratch/repack_status.json").read_text(encoding="utf-8"))
            self.assertEqual("blocked", status["state"])
            self.assertEqual("9.9.9", status["installed_version"])

    def test_app_launch_clears_node_mode_without_changing_the_parent_environment(self):
        repack = load_script("repack_environment_test", "repack_and_restart.py")
        with mock.patch.dict(os.environ, {"ELECTRON_RUN_AS_NODE": "1"}):
            self.assertFalse("ELECTRON_RUN_AS_NODE" in repack.application_launch_environment())
            self.assertEqual("1", os.environ["ELECTRON_RUN_AS_NODE"])

    def test_failed_repack_requests_popup_and_records_failure(self):
        repack = load_script("repack_feedback_test", "repack_and_restart.py")
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            (scratch / "repack_error.txt").write_text("Preload verification failed", encoding="utf-8")
            with (
                mock.patch.object(repack, "SCRATCH_DIR", scratch),
                mock.patch.object(repack, "acquire_repack_lock", return_value=object()),
                mock.patch.object(repack, "release_repack_lock"),
                mock.patch.object(repack, "run_repack", return_value=1),
                mock.patch.object(repack, "notify_failure", create=True) as notify,
                mock.patch("sys.stderr", new=io.StringIO()),
            ):
                self.assertEqual(1, repack.main())
                notify.assert_called_once()
            status = json.loads((scratch / "repack_status.json").read_text(encoding="utf-8"))
            self.assertEqual("error", status["state"])
            self.assertIn("Preload verification failed", status["message"])

    def test_retry_clears_failure_without_trusting_the_installation(self):
        guard = load_script("guard_retry_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            latch = scratch / "failure.json"
            state = scratch / "verified.json"
            latch.write_text('{"observed":{"source":"failed"}}', encoding="utf-8")
            state.write_text('{"source":"actually-verified"}', encoding="utf-8")
            with (
                mock.patch.object(guard, "SCRATCH_DIR", scratch),
                mock.patch.object(guard, "FAILURE_LATCH_FILE", latch),
                mock.patch.object(guard, "STATE_FILE", state),
                mock.patch.object(guard, "log"),
                mock.patch("sys.argv", ["guard", "--retry"]),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(0, guard.main())
            self.assertFalse(latch.exists())
            self.assertEqual({"source": "actually-verified"}, json.loads(state.read_text(encoding="utf-8")))


class InjectorStatusTests(unittest.TestCase):
    def setUp(self):
        self.status = load_script("injector_status_test", "injector_status.py")

    def create_archive(self, target, version):
        write_archive_fixture(target, version)


    def test_unsupported_update_does_not_launch_repack_or_repeat_the_popup(self):
        guard = load_script("guard_preflight_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "app.asar"
            write_archive_fixture(archive, "9.9.9")
            observed = {"app_asar": {"size": 100, "mtime_ns": 1}, "source": "changed"}
            polls = 0

            def sleep(_seconds):
                nonlocal polls
                polls += 1
                if polls == 5:
                    raise KeyboardInterrupt()

            with (
                mock.patch.object(guard, "SCRATCH_DIR", root),
                mock.patch.object(guard, "FAILURE_LATCH_FILE", root / "failure.json"),
                mock.patch.object(guard, "ERROR_FILE", root / "error.txt"),
                mock.patch.object(guard, "APP_ASAR", archive),
                mock.patch.object(guard, "read_state", return_value={}),
                mock.patch.object(guard, "current_state", return_value=observed),
                mock.patch.object(guard, "antigravity_is_running", return_value=True),
                mock.patch.object(guard, "repack_is_running", return_value=False),
                mock.patch.object(guard, "log"),
                mock.patch.object(guard.time, "sleep", side_effect=sleep),
                mock.patch.object(guard.subprocess, "run") as repack,
                mock.patch.object(guard.subprocess, "Popen") as popup,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    guard.run_guard(0)
                repack.assert_not_called()
                popup.assert_called_once()
            self.assertEqual("blocked", json.loads((root / "repack_status.json").read_text(encoding="utf-8"))["state"])

    def test_archive_version_is_read_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "app.asar"
            self.create_archive(archive, "2.19.1")
            self.assertEqual("2.19.1", self.status.read_archive_version(archive))
            self.assertEqual(["app.asar"], [path.name for path in archive.parent.iterdir()])

    def test_truncated_archive_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "app.asar"
            archive.write_bytes(struct.pack("<II", 4, 100))
            with self.assertRaisesRegex(RuntimeError, "ASAR"):
                self.status.read_archive_version(archive)

    def test_completion_popup_requires_a_fresh_verified_success(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            with mock.patch.object(self.status.subprocess, "Popen") as launch:
                self.status.write_status(scratch, "error", "verify", message="Missing preload")
                with self.assertRaises(RuntimeError):
                    self.status.notify_completion(scratch)
                launch.assert_not_called()
                self.status.write_status(scratch, "success", "complete", message="Verified")
                with self.assertRaises(RuntimeError):
                    self.status.notify_completion(scratch, started_at=10**12)
                launch.assert_not_called()
                self.status.notify_completion(scratch)
                launch.assert_called_once()

    def test_popup_is_requested_once_per_failure_and_does_not_block(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            self.status.write_status(scratch, "blocked", "preflight", kind="unsupported_version", message="Unsupported 9.9.9")
            with mock.patch.object(self.status.subprocess, "Popen") as launch:
                self.assertTrue(self.status.notify_failure(scratch))
                self.assertFalse(self.status.notify_failure(scratch))
                launch.assert_called_once()
                launch.return_value.wait.assert_not_called()

    def test_failed_popup_launch_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            self.status.write_status(scratch, "error", "verify", message="Missing preload")
            with mock.patch.object(self.status.subprocess, "Popen", side_effect=OSError("missing Python")):
                with self.assertRaises(OSError):
                    self.status.notify_failure(scratch)
            with mock.patch.object(self.status.subprocess, "Popen") as launch:
                self.assertTrue(self.status.notify_failure(scratch))
                launch.assert_called_once()

    def test_success_resets_popup_suppression(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            with mock.patch.object(self.status.subprocess, "Popen") as launch:
                self.status.write_status(scratch, "error", "verify", message="Missing preload")
                self.status.notify_failure(scratch)
                self.status.write_status(scratch, "success", "complete")
                self.status.clear_notification(scratch)
                self.status.write_status(scratch, "error", "verify", message="Missing preload")
                self.status.notify_failure(scratch)
                self.assertEqual(2, launch.call_count)


class VerifiedGuardStateTests(unittest.TestCase):
    def prepare(self, root, guard):
        archive = root / "app.asar"
        write_archive_fixture(archive, "2.19.1")
        skill = root / "skill"
        skill.mkdir()
        (skill / "SUPPORTED_UPSTREAM_VERSION").write_text("2.19.1", encoding="utf-8")
        contract = skill / "UPSTREAM_COMPATIBILITY.json"
        contract.write_text('{"version":"2.19.1","files":{"dist/main.js":"fixture"}}', encoding="utf-8")
        record = {
            "upstream_version": "2.19.1",
            "installed_asar_sha256": guard.sha256_file(archive),
            "upstream_contract_sha256": guard.sha256_file(contract),
            "source_signature": "a" * 64,
        }
        (root / "verified_repack_installation.json").write_text(json.dumps(record), encoding="utf-8")
        return archive, skill, record

    def test_only_the_runtime_verified_archive_and_captured_sources_are_marked(self):
        guard = load_script("guard_verified_state_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, skill, _record = self.prepare(root, guard)
            with (
                mock.patch.object(guard, "SCRATCH_DIR", root),
                mock.patch.object(guard, "STATE_FILE", root / "state.json"),
                mock.patch.object(guard, "FAILURE_LATCH_FILE", root / "failure.json"),
                mock.patch.object(guard, "APP_ASAR", archive),
                mock.patch.object(guard, "SKILL_ROOT", skill),
                mock.patch.object(guard, "source_signature", return_value="b" * 64),
            ):
                guard.mark_current_verified()
            self.assertEqual("a" * 64, json.loads((root / "state.json").read_text(encoding="utf-8"))["source"])

    def test_changed_archive_cannot_be_marked_as_verified(self):
        guard = load_script("guard_changed_archive_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, skill, _record = self.prepare(root, guard)
            archive.write_bytes(archive.read_bytes() + b"changed archive")
            with (
                mock.patch.object(guard, "SCRATCH_DIR", root),
                mock.patch.object(guard, "STATE_FILE", root / "state.json"),
                mock.patch.object(guard, "APP_ASAR", archive),
                mock.patch.object(guard, "SKILL_ROOT", skill),
            ):
                with self.assertRaisesRegex(RuntimeError, "Archivhash"):
                    guard.mark_current_verified()
            self.assertFalse((root / "state.json").exists())

    def test_live_guard_observes_a_cleared_failure_latch_and_retries(self):
        guard = load_script("guard_live_retry_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, skill, _record = self.prepare(root, guard)
            observed = {"app_asar": guard.stat_signature(archive), "source": "a" * 64}
            polls = 0

            def sleep(_seconds):
                nonlocal polls
                polls += 1
                if polls == 3:
                    guard.clear_failure_latch()
                if polls == 8:
                    raise KeyboardInterrupt()

            with (
                mock.patch.object(guard, "SCRATCH_DIR", root),
                mock.patch.object(guard, "STATE_FILE", root / "state.json"),
                mock.patch.object(guard, "FAILURE_LATCH_FILE", root / "failure.json"),
                mock.patch.object(guard, "ERROR_FILE", root / "error.txt"),
                mock.patch.object(guard, "APP_ASAR", archive),
                mock.patch.object(guard, "SKILL_ROOT", skill),
                mock.patch.object(guard, "current_state", return_value=observed),
                mock.patch.object(guard, "antigravity_is_running", return_value=True),
                mock.patch.object(guard, "repack_is_running", return_value=False),
                mock.patch.object(guard, "log"),
                mock.patch.object(guard.time, "sleep", side_effect=sleep),
                mock.patch.object(guard.subprocess, "Popen"),
                mock.patch.object(guard.subprocess, "run", side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as repack,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    guard.run_guard(0)
                self.assertEqual(2, repack.call_count)
            self.assertEqual("a" * 64, json.loads((root / "state.json").read_text(encoding="utf-8"))["source"])


if __name__ == "__main__":
    unittest.main()
