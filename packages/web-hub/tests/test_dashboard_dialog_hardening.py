import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from src.proxy_server import dashboard_no_store_middleware


ROOT = Path(__file__).resolve().parents[1]


class TestDashboardDialogHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "dashboard" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        cls.control_center = (
            ROOT / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        cls.styles = (ROOT / "dashboard" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

    def test_dashboard_uses_no_browser_native_dialogs(self):
        source = f"{self.app}\n{self.control_center}"
        self.assertIsNone(
            re.search(r"\b(?:window\.)?(?:alert|confirm|prompt)\s*\(", source)
        )

    def test_shared_confirmation_dialog_is_accessible_and_injection_safe(self):
        self.assertIn('dialog.setAttribute("aria-labelledby"', self.app)
        self.assertIn('dialog.setAttribute("aria-describedby"', self.app)
        self.assertIn('querySelector("#hub-confirm-message").textContent', self.app)
        self.assertIn('data-hub-confirm="cancel"', self.app)
        self.assertIn('requestAnimationFrame(() => dialog.querySelector(\'[data-hub-confirm="cancel"]\')?.focus())', self.app)
        self.assertIn('dialog.addEventListener("cancel"', self.app)
        self.assertIn("hubConfirmReturnFocus.focus()", self.app)

    def test_destructive_legacy_actions_wait_for_confirmation(self):
        for function_name in (
            "unlinkAntigravityProject",
            "deleteScheduledTask",
            "deleteProject",
            "cancelExecution",
            "deleteIssue",
            "resetIssue",
            "gitDiscard",
            "deleteSubtask",
            "deleteIntegrityChat",
            "deleteCustomModel",
        ):
            start = self.app.index(f"async function {function_name}")
            end = self.app.find("\nasync function ", start + 1)
            body = self.app[start : end if end >= 0 else len(self.app)]
            self.assertIn("await hubConfirm(", body, function_name)

    def test_confirmation_dialog_scales_to_mobile(self):
        self.assertIn(".hub-confirm-dialog", self.styles)
        self.assertIn("calc(100vw - 28px)", self.styles)
        self.assertIn(".hub-confirm-actions .btn", self.styles)

    def test_project_removal_trigger_is_a_keyboard_button(self):
        self.assertIn('<button type="button" class="delete-icon"', self.app)
        self.assertIn('aria-label="Projekt ${escapeHTML(p.github_repo || p.name)} deregistrieren"', self.app)
        self.assertIn(".delete-icon:focus-visible", self.styles)


class TestDashboardCachePolicy(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_html_and_assets_are_never_stale(self):
        async def handler(_request):
            return web.Response(text="ok", headers={"ETag": '"proof"'})

        response = await dashboard_no_store_middleware(
            SimpleNamespace(path="/dashboard/js/app.js"),
            handler,
        )
        self.assertEqual(
            response.headers["Cache-Control"],
            "no-store, no-cache, must-revalidate",
        )
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["Expires"], "0")

    async def test_non_dashboard_routes_keep_their_own_cache_policy(self):
        async def handler(_request):
            return web.Response(text="ok", headers={"Cache-Control": "private"})

        response = await dashboard_no_store_middleware(
            SimpleNamespace(path="/api/control-center/overview"),
            handler,
        )
        self.assertEqual(response.headers["Cache-Control"], "private")


if __name__ == "__main__":
    unittest.main()
