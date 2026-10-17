from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parent.parent


def load_script(module_name: str, script_name: str):
    script_path = SKILL_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(script_path.parent), *sys.path]):
        spec.loader.exec_module(module)
    return module


class AutoRepackGuardTests(unittest.TestCase):
    def test_orphaned_staging_directory_is_not_a_running_repack(self):
        guard = load_script("auto_repack_guard_under_test", "auto_repack_guard.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            staging_dir = Path(temp_dir) / "repack-staging"
            staging_dir.mkdir()
            no_process = SimpleNamespace(stdout="", stderr="", returncode=0)

            with (
                mock.patch.object(guard, "STAGING_DIR", staging_dir),
                mock.patch.object(guard.subprocess, "run", return_value=no_process),
            ):
                self.assertFalse(guard.repack_is_running())


class RepackCleanupTests(unittest.TestCase):
    def test_version_mismatch_removes_staging_before_return(self):
        repack = load_script("repack_and_restart_under_test", "repack_and_restart.py")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_dir = root / "Antigravity"
            resources_dir = install_dir / "resources"
            resources_dir.mkdir(parents=True)
            app_path = install_dir / "Antigravity.exe"
            app_asar_path = resources_dir / "app.asar"
            app_path.write_bytes(b"fake executable")
            app_asar_path.write_bytes(b"fake asar")
            staging_dir = resources_dir / "repack-staging"

            def fake_run_asar(command_args, _log_file, _action):
                self.assertEqual("extract", command_args[0])
                extracted_dir = Path(command_args[-1])
                (extracted_dir / "dist").mkdir(parents=True, exist_ok=True)
                (extracted_dir / "package.json").write_text(
                    '{"version":"9.9.9"}',
                    encoding="utf-8",
                )

            build_ok = SimpleNamespace(returncode=0, stdout="", stderr="")
            with (
                mock.patch.object(repack, "SCRATCH_DIR", root / "scratch"),
                mock.patch.object(
                    repack,
                    "resolve_install_paths",
                    return_value=(install_dir, resources_dir, app_path),
                ),
                mock.patch.object(repack, "claim_trigger_chat_id", return_value=None),
                mock.patch.object(repack, "get_last_active_session_id", return_value=None),
                mock.patch.object(repack, "ensure_complete_unpacked_tree"),
                mock.patch.object(repack, "version_info", return_value={"installed_version": "2.19.1", "supported_version": "2.19.1"}),
                mock.patch.object(repack, "run_asar", side_effect=fake_run_asar),
                mock.patch.object(repack, "validate_extracted_app"),
                mock.patch.object(repack.subprocess, "run", return_value=build_ok),
            ):
                with mock.patch("sys.stdout", new=io.StringIO()):
                    result = repack.run_repack()

            self.assertEqual(1, result)
            self.assertFalse(staging_dir.exists())


class UpstreamCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.repack = load_script(
            "repack_and_restart_compatibility_under_test",
            "repack_and_restart.py",
        )

    def create_contract(self, root: Path, content: bytes = b"official upstream") -> Path:
        target = root / "dist" / "main.js"
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
        (root / "package.json").write_text(
            '{"version":"2.11.0"}',
            encoding="utf-8",
        )
        contract_path = root.parent / "UPSTREAM_COMPATIBILITY.json"
        contract_path.write_text(
            json.dumps(
                {
                    "version": "2.11.0",
                    "files": {
                        "dist/main.js": hashlib.sha256(content).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )
        return contract_path

    def test_exact_upstream_contract_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "extracted"
            contract_path = self.create_contract(root)

            version = self.repack.validate_upstream_contract(
                root,
                contract_path,
                "2.11.0",
                io.StringIO(),
            )

            self.assertEqual("2.11.0", version)

    def test_modified_upstream_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "extracted"
            contract_path = self.create_contract(root)
            (root / "dist" / "main.js").write_bytes(b"unexpected hotfix")

            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                self.repack.validate_upstream_contract(
                    root,
                    contract_path,
                    "2.11.0",
                    io.StringIO(),
                )

    def test_verified_modifier_archive_is_accepted_as_next_repack_base(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            extracted_root = temp_root / "extracted"
            contract_path = self.create_contract(extracted_root)
            app_asar_path = temp_root / "app.asar"
            record_path = temp_root / "verified-installation.json"
            app_asar_path.write_bytes(b"verified patched archive")
            (extracted_root / "dist" / "main.js").write_bytes(b"patched overlay")

            self.repack.write_verified_installation_record(
                app_asar_path,
                contract_path,
                "2.11.0",
                record_path,
            )
            version = self.repack.validate_repack_base(
                extracted_root,
                app_asar_path,
                contract_path,
                "2.11.0",
                record_path,
                io.StringIO(),
            )

            self.assertEqual("2.11.0", version)

    def test_modified_archive_is_not_accepted_by_verified_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            extracted_root = temp_root / "extracted"
            contract_path = self.create_contract(extracted_root)
            app_asar_path = temp_root / "app.asar"
            record_path = temp_root / "verified-installation.json"
            app_asar_path.write_bytes(b"verified patched archive")
            (extracted_root / "dist" / "main.js").write_bytes(b"patched overlay")
            self.repack.write_verified_installation_record(
                app_asar_path,
                contract_path,
                "2.11.0",
                record_path,
            )
            app_asar_path.write_bytes(b"tampered archive")

            with self.assertRaisesRegex(RuntimeError, "verified installation hash mismatch"):
                self.repack.validate_repack_base(
                    extracted_root,
                    app_asar_path,
                    contract_path,
                    "2.11.0",
                    record_path,
                    io.StringIO(),
                )


class DevToolsDiscoveryTests(unittest.TestCase):
    def test_listener_fallback_works_without_devtools_port_file(self):
        repack = load_script(
            "repack_and_restart_devtools_under_test",
            "repack_and_restart.py",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_port_file = Path(temp_dir) / "DevToolsActivePort"
            app_path = Path(temp_dir) / "Antigravity.exe"
            with (
                mock.patch.object(
                    repack,
                    "list_install_listener_ports",
                    return_value=[65500, 59118],
                ),
                mock.patch.object(
                    repack,
                    "is_devtools_port",
                    side_effect=lambda port: port == 59118,
                ),
            ):
                result = repack.find_devtools_port(
                    missing_port_file,
                    app_path,
                    io.StringIO(),
                )

            self.assertEqual(59118, result)


class UpstreamBaselineTests(unittest.TestCase):
    setUp = UpstreamCompatibilityTests.setUp
    create_contract = UpstreamCompatibilityTests.create_contract

    def test_pristine_upstream_is_snapshotted_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "extracted"
            contract_path = self.create_contract(root)
            (root / "dist" / "languageServer.js").write_text("exports.x = 1;", encoding="utf-8")
            (root / "dist" / "main.test.js").write_text("test", encoding="utf-8")
            baselines = Path(temp_dir) / "baselines"

            stored = self.repack.save_upstream_baseline(root, contract_path, "2.11.0", io.StringIO(), baselines)

            self.assertEqual(baselines / "2.11.0", stored)
            self.assertTrue((stored / "dist" / "languageServer.js").is_file())
            self.assertFalse((stored / "dist" / "main.test.js").exists())
            manifest = json.loads((stored / "baseline.json").read_text(encoding="utf-8"))
            self.assertIn("dist/main.js", manifest["files"])

    def test_modified_base_is_never_snapshotted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "extracted"
            contract_path = self.create_contract(root)
            (root / "dist" / "main.js").write_bytes(b"patched overlay")
            baselines = Path(temp_dir) / "baselines"

            stored = self.repack.save_upstream_baseline(root, contract_path, "2.11.0", io.StringIO(), baselines)

            self.assertIsNone(stored)
            self.assertFalse(baselines.exists())

    def test_only_newest_baselines_are_kept(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            baselines = Path(temp_dir) / "baselines"
            for old in ("2.9.0", "2.10.0", "2.10.5"):
                (baselines / old).mkdir(parents=True)
            root = Path(temp_dir) / "extracted"
            contract_path = self.create_contract(root)

            self.repack.save_upstream_baseline(root, contract_path, "2.11.0", io.StringIO(), baselines)

            self.assertEqual(
                ["2.10.0", "2.10.5", "2.11.0"],
                sorted(item.name for item in baselines.iterdir()),
            )


class GuardHoldTests(unittest.TestCase):
    def setUp(self):
        self.guard = load_script("auto_repack_guard_hold_under_test", "auto_repack_guard.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(self.guard, "PAUSE_FILE", Path(self.tmp.name) / "pause.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        scratch = mock.patch.object(self.guard, "SCRATCH_DIR", Path(self.tmp.name))
        scratch.start()
        self.addCleanup(scratch.stop)

    def test_source_only_change_waits_for_quiet_period(self):
        installed = {"app_asar": {"size": 1}, "source": "old"}
        observed = {"app_asar": {"size": 1}, "source": "new"}
        quiet = self.guard.SOURCE_QUIET_SECONDS
        self.assertFalse(self.guard.ready_to_repack(installed, observed, 5, 1000.0, 1000.0 + quiet - 1))
        self.assertTrue(self.guard.ready_to_repack(installed, observed, 5, 1000.0, 1000.0 + quiet))

    def test_app_update_keeps_short_stability_check(self):
        installed = {"app_asar": {"size": 1}, "source": "same"}
        observed = {"app_asar": {"size": 2}, "source": "same"}
        self.assertFalse(self.guard.ready_to_repack(installed, observed, 2, 1000.0, 1000.0))
        self.assertTrue(self.guard.ready_to_repack(installed, observed, 3, 1000.0, 1000.0))

    def test_pause_holds_and_expires(self):
        with mock.patch.object(self.guard, "agent_repair_active", return_value=False):
            self.assertIsNone(self.guard.hold_reason())
            until = self.guard.write_pause(10)
            self.assertEqual("paused", self.guard.hold_reason())
            self.assertIsNone(self.guard.hold_reason(now=until + 1))
            self.guard.clear_pause()
            self.assertIsNone(self.guard.hold_reason())

    def test_pause_is_capped(self):
        import time as _time
        until = self.guard.write_pause(100000)
        self.assertLessEqual(until - _time.time(), self.guard.MAX_PAUSE_MINUTES * 60 + 1)

    def test_agent_repair_holds_repack(self):
        with mock.patch.object(self.guard, "agent_repair_active", return_value=True):
            self.assertEqual("agent_repair", self.guard.hold_reason())

    def test_signature_stored_by_finished_repack_prevents_second_repack(self):
        class StopLoop(BaseException):
            pass

        old_state = {"app_asar": {"size": 1, "mtime_ns": 1}, "source": "s"}
        new_state = {"app_asar": {"size": 2, "mtime_ns": 2}, "source": "s"}
        reads = {"count": 0}

        def read_state():
            reads["count"] += 1
            # The loop read still sees the pre-repack state; the pre-launch re-read
            # sees the signature that the finished repack just stored.
            return old_state if reads["count"] <= 3 else new_state

        sleeps = {"count": 0}

        def fake_sleep(_seconds):
            sleeps["count"] += 1
            if sleeps["count"] > 6:
                raise StopLoop()

        with (
            mock.patch.object(self.guard, "read_state", side_effect=read_state),
            mock.patch.object(self.guard, "current_state", return_value=new_state),
            mock.patch.object(self.guard, "read_failure_latch", return_value=None),
            mock.patch.object(self.guard, "antigravity_is_running", return_value=True),
            mock.patch.object(self.guard, "repack_is_running", return_value=False),
            mock.patch.object(self.guard, "agent_repair_active", return_value=False),
            mock.patch.object(self.guard, "version_info", return_value={"installed_version": "1", "supported_version": "1"}),
            mock.patch.object(self.guard, "log"),
            mock.patch.object(self.guard.time, "sleep", side_effect=fake_sleep),
            mock.patch.object(self.guard.subprocess, "run") as run,
        ):
            with self.assertRaises(StopLoop):
                self.guard.run_guard(4.0)
        run.assert_not_called()

    def test_running_repack_restarts_the_stability_window(self):
        class StopLoop(BaseException):
            pass

        state = {"app_asar": {"size": 1}, "source": "s"}
        observed = {"app_asar": {"size": 2}, "source": "s"}
        running = iter([True] * 5 + [False] * 10)
        sleeps = {"count": 0}

        def fake_sleep(_seconds):
            sleeps["count"] += 1
            if sleeps["count"] > 6:
                raise StopLoop()

        with (
            mock.patch.object(self.guard, "read_state", return_value=state),
            mock.patch.object(self.guard, "current_state", return_value=observed),
            mock.patch.object(self.guard, "read_failure_latch", return_value=None),
            mock.patch.object(self.guard, "antigravity_is_running", return_value=True),
            mock.patch.object(self.guard, "repack_is_running", side_effect=lambda: next(running)),
            mock.patch.object(self.guard, "agent_repair_active", return_value=False),
            mock.patch.object(self.guard, "version_info", return_value={"installed_version": "1", "supported_version": "1"}),
            mock.patch.object(self.guard, "log"),
            mock.patch.object(self.guard.time, "sleep", side_effect=fake_sleep),
            mock.patch.object(self.guard.subprocess, "run") as run,
        ):
            with self.assertRaises(StopLoop):
                self.guard.run_guard(4.0)
        # Five polls with a running repack, then only one non-running poll before
        # the loop stops: the fresh window (3 polls) must not have elapsed yet.
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
