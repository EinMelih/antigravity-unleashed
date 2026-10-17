import io
import itertools
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from test_repack_guard import load_script
from test_injector_feedback import write_archive_fixture


class RepackShutdownTests(unittest.TestCase):
    def test_failure_after_shutdown_restarts_the_unchanged_app(self):
        repack = load_script("repack_restart_on_failure_test", "repack_and_restart.py")
        version_file = Path(repack.__file__).resolve().parent.parent / "SUPPORTED_UPSTREAM_VERSION"
        supported_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "2.22.0"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "install"
            resources = install / "resources"
            resources.mkdir(parents=True)
            executable = install / "Antigravity.exe"
            executable.write_bytes(b"test executable")
            archive = resources / "app.asar"
            write_archive_fixture(archive, supported_version)
            original_archive = archive.read_bytes()

            def extract(arguments, _log, _action):
                target = Path(arguments[-1])
                (target / "dist").mkdir(parents=True, exist_ok=True)
                (target / "package.json").write_text(f'{{"version":"{supported_version}"}}', encoding="utf-8")

            with (
                mock.patch.object(repack, "SCRATCH_DIR", root / "scratch"),
                mock.patch.object(repack, "resolve_install_paths", return_value=(install, resources, executable)),
                mock.patch.object(repack, "resolve_user_data_dir", return_value=root / "user-data"),
                mock.patch.object(repack, "claim_trigger_chat_id", return_value=None),
                mock.patch.object(repack, "get_last_active_session_id", return_value=None),
                mock.patch.object(repack, "ensure_complete_unpacked_tree"),
                mock.patch.object(repack, "run_asar", side_effect=extract),
                mock.patch.object(repack, "validate_extracted_app"),
                mock.patch.object(repack, "validate_repack_base", return_value=supported_version),
                mock.patch.object(repack, "validate_js_syntax", return_value=True),
                mock.patch.object(repack, "copy_overlay_sources"),
                mock.patch.object(repack, "stop_install_process_tree", side_effect=RuntimeError("Shutdown failed")),
                mock.patch.object(repack.time, "sleep"),
                mock.patch.object(repack.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")),
                mock.patch.object(repack.subprocess, "Popen") as restart,
            ):
                self.assertEqual(1, repack.run_repack())
                self.assertEqual(1, restart.call_count)
                self.assertEqual([str(executable)], restart.call_args.args[0])
                self.assertFalse("ELECTRON_RUN_AS_NODE" in restart.call_args.kwargs["env"])
            self.assertEqual(original_archive, archive.read_bytes())

    def test_taskkill_without_stderr_does_not_abort_after_stopping_the_app(self):
        repack = load_script("repack_shutdown_test", "repack_and_restart.py")
        result = SimpleNamespace(returncode=0, stdout="", stderr=None)
        with (
            mock.patch.object(repack, "list_install_process_ids", side_effect=[[42], [42], [], []]),
            mock.patch.object(repack.subprocess, "run", return_value=result),
            mock.patch.object(repack.time, "sleep"),
        ):
            log = io.StringIO()
            repack.stop_install_process_tree("dummy_app", log)
            self.assertIn("taskkill PID 42: exit=0", log.getvalue())

    def test_taskkill_output_keeps_failure_details_in_the_log(self):
        repack = load_script("repack_shutdown_failure_test", "repack_and_restart.py")
        result = SimpleNamespace(returncode=1, stdout="access denied", stderr="denied")
        with (
            mock.patch.object(repack, "list_install_process_ids", return_value=[42]),
            mock.patch.object(repack.subprocess, "run", return_value=result),
            mock.patch.object(repack.time, "sleep"),
            mock.patch.object(repack.time, "monotonic", side_effect=itertools.count(0, 100)),
        ):
            log = io.StringIO()
            with self.assertRaisesRegex(RuntimeError, "processes did not exit"):
                repack.stop_install_process_tree("dummy_app", log)
            self.assertIn("access denied", log.getvalue())
            self.assertIn("denied", log.getvalue())


    def test_respawned_processes_are_stopped_in_a_second_round(self):
        repack = load_script("repack_shutdown_respawn_test", "repack_and_restart.py")
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        sequence = [
            [42], [42], [77],      # round 1: kill 42, a watcher respawns 77
            [77], [77], [],        # round 2: kill 77, clear
            [],                    # stability re-check
        ]
        with (
            mock.patch.object(repack, "list_install_process_ids", side_effect=sequence),
            mock.patch.object(repack.subprocess, "run", return_value=result),
            mock.patch.object(repack.time, "sleep"),
            mock.patch.object(repack.time, "monotonic", side_effect=itertools.count(0, 100)),
        ):
            log = io.StringIO()
            repack.stop_install_process_tree("dummy_app", log)
            self.assertIn("taskkill PID 42", log.getvalue())
            self.assertIn("taskkill PID 77", log.getvalue())
            self.assertIn("Respawn", log.getvalue())


if __name__ == "__main__":
    unittest.main()
