import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestControlCenterReviewUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        cls.script = (
            ROOT / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        cls.app_script = (
            ROOT / "dashboard" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        cls.styles = (
            ROOT / "dashboard" / "css" / "control-center.css"
        ).read_text(encoding="utf-8")

    def test_active_control_center_owns_vertical_scrolling(self):
        self.assertIn(".tab-content#control-center-tab.active", self.styles)
        self.assertIn("overflow-y: auto", self.styles)
        self.assertIn("scrollbar-gutter: stable", self.styles)

    def test_review_finding_modal_has_bounded_fields_and_dictation(self):
        self.assertIn('id="cc-finding-modal"', self.index)
        self.assertIn('onsubmit="submitTaskFinding(event)"', self.index)
        for classification in (
            "BLOCKER",
            "REQUIRED",
            "QUESTION",
            "SUGGESTION",
            "NIT",
        ):
            self.assertIn(f'value="{classification}"', self.index)
        self.assertIn('maxlength="120"', self.index)
        self.assertIn('maxlength="10000"', self.index)
        self.assertIn('data-cc-dictation-label="Review-Finding · Beobachtung"', self.index)

    def test_finding_creation_is_bound_to_the_current_sha(self):
        self.assertIn("controlFindingContext = {taskId, targetSha}", self.script)
        self.assertIn("currentSha !== context.targetSha", self.script)
        self.assertIn("sha: context.targetSha", self.script)
        self.assertIn(
            "/api/control-center/tasks/${encodeURIComponent(context.taskId)}/findings",
            self.script,
        )

    def test_open_findings_are_individually_rendered_and_resolvable(self):
        self.assertIn('item.status === "open"', self.script)
        self.assertIn('class="cc-finding-row is-${escapeHTML', self.script)
        self.assertIn("Mit Begründung auflösen", self.script)
        self.assertIn("reasonRequired: true", self.script)
        self.assertIn(
            "/api/control-center/findings/${encodeURIComponent(findingId)}/resolve",
            self.script,
        )
        self.assertIn("latestSha !== targetSha", self.script)

    def test_review_controls_remain_compact_on_mobile(self):
        self.assertIn(".cc-finding-row", self.styles)
        self.assertIn(".cc-finding-meta", self.styles)
        self.assertIn(".cc-finding-row .btn", self.styles)

    def test_human_review_focus_explains_commit_without_sha_jargon(self):
        self.assertIn("Code-Stand verbindlich freigegeben", self.script)
        self.assertIn("Ändert sich der Commit", self.script)
        self.assertIn("Das ist der eindeutige Fingerabdruck des Codes", self.script)
        self.assertIn("Problem melden", self.script)
        self.assertIn("Noch selbst zu prüfen", self.script)

    def test_review_deep_link_activates_control_center_and_selects_task(self):
        self.assertIn('const requestedReview = locationParams.get("review")', self.app_script)
        self.assertIn('const requestedProjectId = locationParams.get("project_id")', self.app_script)
        self.assertIn('? "control-center-tab"', self.app_script)
        self.assertIn('projects.find(project => String(project.id) === requestedProjectId)', self.app_script)
        self.assertIn('requestedReview\n            ? null\n            : savedProject', self.app_script)
        self.assertIn('new URLSearchParams(window.location.search).get("review")', self.script)
        self.assertIn("tasks.find(item => String(item.id) === requested)", self.script)


if __name__ == "__main__":
    unittest.main()
