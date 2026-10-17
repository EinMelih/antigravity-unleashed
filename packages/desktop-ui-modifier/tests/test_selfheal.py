import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "selfheal.py"
POPUP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "notification_popup.py"
GUARD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "auto_repack_guard.py"


def load():
    spec = importlib.util.spec_from_file_location("selfheal_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_popup():
    spec = importlib.util.spec_from_file_location("notification_popup_under_test", POPUP_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelfHealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scratch = self.root / "scratch"
        self.history = self.root / "UPGRADE_HISTORY.json"
        self.sh = load()
        patcher = mock.patch.object(self.sh, "_history_paths", return_value=[self.history])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_begin_marks_detected_done_and_analysis_running(self):
        state = self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.assertTrue(state["active"])
        self.assertEqual("done", state["steps"]["detected"]["status"])
        self.assertEqual("running", state["steps"]["analysis"]["status"])
        self.assertGreater(state["percent"], 0)
        self.assertLess(state["percent"], 100)

    def test_percent_grows_monotonically_through_the_steps(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        last = self.sh.read_state(self.scratch)["percent"]
        for step in ("analysis", "adapt", "tests", "repack", "restart"):
            self.sh.set_step(step, "done", scratch=self.scratch)
            current = self.sh.read_state(self.scratch)["percent"]
            self.assertGreater(current, last)
            last = current
        self.assertLess(last, 100)

    def test_finishing_a_step_completes_all_earlier_steps(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.set_step("repack", "running", scratch=self.scratch)
        self.sh.set_step("repack", "done", scratch=self.scratch)
        steps = self.sh.read_state(self.scratch)["steps"]
        for earlier in ("detected", "analysis", "adapt", "tests", "repack"):
            self.assertEqual("done", steps[earlier]["status"], earlier)

    def test_starting_a_later_step_completes_steps_the_agent_forgot_to_report(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)  # analysis stays 'running'
        self.sh.mirror_repack_status("running", "pack", "", self.scratch)
        steps = self.sh.read_state(self.scratch)["steps"]
        for earlier in ("detected", "analysis", "adapt", "tests"):
            self.assertEqual("done", steps[earlier]["status"], earlier)
        self.assertEqual("running", steps["repack"]["status"])

    def test_repack_phases_are_mirrored_only_while_a_run_is_active(self):
        self.sh.mirror_repack_status("running", "pack", "", self.scratch)
        self.assertEqual({}, self.sh.read_state(self.scratch))
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.mirror_repack_status("running", "pack", "", self.scratch)
        self.assertEqual("running", self.sh.read_state(self.scratch)["steps"]["repack"]["status"])
        self.sh.mirror_repack_status("running", "verify", "", self.scratch)
        self.assertEqual("running", self.sh.read_state(self.scratch)["steps"]["restart"]["status"])

    def test_plain_repack_on_live_scratch_starts_a_run_and_the_window(self):
        with mock.patch.object(self.sh, "SCRATCH_DIR", self.scratch), \
                mock.patch.object(self.sh, "launch_window", return_value=True) as launch:
            self.sh.mirror_repack_status("running", "build", "", self.scratch)
            launch.assert_called_once()
            state = self.sh.read_state(self.scratch)
            self.assertTrue(state["active"])
            self.assertEqual("done", state["steps"]["adapt"]["status"])
            self.assertEqual("running", state["steps"]["tests"]["status"])
            # a second phase must not start another window
            self.sh.mirror_repack_status("running", "pack", "", self.scratch)
            launch.assert_called_once()


    def test_rollback_marks_the_running_step_failed_and_sets_failed_result(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.mirror_repack_status("running", "install", "", self.scratch)
        self.sh.mirror_repack_status("running", "rollback", "", self.scratch)
        state = self.sh.read_state(self.scratch)
        self.assertEqual("failed", state["result"])
        self.assertEqual("failed", state["steps"]["repack"]["status"])
        self.assertTrue(state["active"], "failed runs stay active so the user can retry")

    def test_guard_and_preflight_errors_do_not_fail_the_run(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.mirror_repack_status("blocked", "preflight", "unsupported", self.scratch)
        self.sh.mirror_repack_status("error", "guard", "x", self.scratch)
        self.assertEqual("running", self.sh.read_state(self.scratch)["result"])

    def test_success_reaches_100_percent_and_closes_the_run(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.mirror_repack_status("success", "complete", "", self.scratch)
        state = self.sh.read_state(self.scratch)
        self.assertEqual("success", state["result"])
        self.assertEqual(100, state["percent"])
        self.assertFalse(state["active"])

    def test_retry_after_failure_resets_the_failure_when_the_step_runs_again(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.set_step("adapt", "failed", "boom", scratch=self.scratch)
        self.assertEqual("failed", self.sh.read_state(self.scratch)["result"])
        self.sh.set_step("adapt", "running", scratch=self.scratch)
        state = self.sh.read_state(self.scratch)
        self.assertEqual("running", state["result"])
        self.assertNotIn("failed_step", state)

    def test_history_is_persisted_per_version_and_merged_not_replaced(self):
        self.history.write_text(json.dumps([
            {"version": "2.19.1", "date": "2026-10-02", "findings": ["old"], "diff_summary": {}, "upstream_status": "compatible"},
        ]), encoding="utf-8")
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        self.sh.add_finding("preload.js erweitert", self.scratch)
        self.sh.add_finding("preload.js erweitert", self.scratch)  # duplicate ignored
        self.sh.set_diff("dist/preload.js", "getPathForFile ergaenzt", self.scratch)
        self.sh.mirror_repack_status("success", "complete", "", self.scratch)
        history = json.loads(self.history.read_text(encoding="utf-8"))
        self.assertEqual(["2.22.0", "2.19.1"], [item["version"] for item in history])
        new = history[0]
        self.assertEqual("success", new["result"])
        self.assertEqual(["preload.js erweitert"], new["findings"])
        self.assertEqual("getPathForFile ergaenzt", new["diff_summary"]["dist/preload.js"])
        self.assertEqual(len(self.sh.STEPS), len(new["steps"]))
        self.assertEqual(["old"], history[1]["findings"], "older versions stay untouched")

    def test_failed_run_is_documented_as_failed(self):
        self.sh.begin("2.19.1", "2.23.0", self.scratch)
        self.sh.set_step("tests", "failed", "Tests rot", scratch=self.scratch)
        self.sh.finish("failed", self.scratch)
        history = json.loads(self.history.read_text(encoding="utf-8"))
        self.assertEqual("failed", history[0]["upstream_status"])
        self.assertEqual("failed", history[0]["result"])

    def test_history_is_bounded(self):
        entries = [{"version": f"1.{i}.0", "findings": [], "diff_summary": {}} for i in range(80)]
        self.history.write_text(json.dumps(entries), encoding="utf-8")
        self.sh.begin("1.0.0", "3.0.0", self.scratch)
        self.sh.finish("success", self.scratch)
        self.assertLessEqual(len(json.loads(self.history.read_text(encoding="utf-8"))), self.sh.HISTORY_LIMIT)

    def test_stale_runs_are_not_considered_active(self):
        self.sh.begin("2.19.1", "2.22.0", self.scratch)
        state = self.sh.read_state(self.scratch)
        state["updated_at"] -= self.sh.STALE_AFTER_SECONDS + 5
        (self.scratch / self.sh.STATE_NAME).write_text(json.dumps(state), encoding="utf-8")
        self.assertFalse(self.sh.is_active(self.scratch))

    def test_repair_prompt_contains_progress_commands_and_retry_context(self):
        first = self.sh.build_repair_prompt("2.23.0", "2.22.0")
        self.assertIn("step analysis", first)
        self.assertIn("finding", first)
        self.assertNotIn("Versuch 2", first)
        retry = self.sh.build_repair_prompt("2.23.0", "2.22.0", attempt=2)
        self.assertIn("Versuch 2", retry)
        self.assertIn("repack_and_restart.log", retry)
        self.assertIn("upstream_baselines", first)

    def test_agent_repair_window_holds_until_repack_starts(self):
        self.sh.begin("2.22.0", "2.23.0", self.scratch)
        self.assertTrue(self.sh.agent_repair_in_progress(scratch=self.scratch))
        self.sh.set_step("tests", "done", scratch=self.scratch)
        self.assertTrue(self.sh.agent_repair_in_progress(scratch=self.scratch))
        self.sh.mirror_repack_status("running", "save_state", "", self.scratch)
        self.assertFalse(self.sh.agent_repair_in_progress(scratch=self.scratch))

    def test_agent_repair_window_is_bounded_and_ends_on_failure(self):
        self.sh.begin("2.22.0", "2.23.0", self.scratch)
        state = self.sh.read_state(self.scratch)
        later = state["updated_at"] + self.sh.AGENT_EDIT_HOLD_SECONDS + 1
        self.assertFalse(self.sh.agent_repair_in_progress(state, now=later))
        self.sh.set_step("adapt", "failed", "boom", scratch=self.scratch)
        self.assertFalse(self.sh.agent_repair_in_progress(scratch=self.scratch))

    def test_plain_repack_never_holds_the_guard(self):
        with mock.patch.object(self.sh, "SCRATCH_DIR", self.scratch), \
                mock.patch.object(self.sh, "launch_window", return_value=True):
            self.sh.mirror_repack_status("running", "build", "", self.scratch)
        self.assertEqual("repack", self.sh.read_state(self.scratch)["kind"])
        self.assertFalse(self.sh.agent_repair_in_progress(scratch=self.scratch))

    def test_find_latest_local_app_url_extracts_most_recent_port(self):
        popup = load_popup()
        logs = self.root / "logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text(
            "[info] Local: https://127.0.0.1:59001/\n"
            "[info] [Auto-Restart] Port changed! Reloading all windows with URL: https://127.0.0.1:60512/\n",
            encoding="utf-8",
        )
        self.assertEqual("https://127.0.0.1:60512/", popup.find_latest_local_app_url(self.root))

    def test_guard_process_filter_excludes_node_sidecars_and_renderers(self):
        guard_src = GUARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(r"--type=|dist/server\\.cjs|--import=", guard_src)


if __name__ == "__main__":
    unittest.main()
