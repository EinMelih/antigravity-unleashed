import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestControlCenterUiHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PROJECT_ROOT / "dashboard" / "index.html").read_text(
            encoding="utf-8"
        )
        cls.script = (
            PROJECT_ROOT / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        cls.style = (
            PROJECT_ROOT / "dashboard" / "css" / "control-center.css"
        ).read_text(encoding="utf-8")

    def test_live_refresh_is_scoped_to_visible_control_center(self):
        self.assertIn('id="cc-live-status"', self.html)
        self.assertIn('id="cc-stale-notice"', self.html)
        self.assertIn("ccControlCenterVisible", self.script)
        self.assertIn('tab?.classList.contains("active") && !document.hidden', self.script)
        self.assertIn("MutationObserver(syncControlCenterRefreshLifecycle)", self.script)
        self.assertIn(
            'document.addEventListener("visibilitychange", syncControlCenterRefreshLifecycle)',
            self.script,
        )
        self.assertIn("ccHasLiveControlActivity() ? 2000 : 8000", self.script)
        self.assertIn('setControlCenterFreshness("error", error.message)', self.script)

    def test_unchanged_live_poll_does_not_replace_interactive_task_dom(self):
        self.assertIn("let controlCenterRenderSignature = \"\"", self.script)
        self.assertIn("function ccDomainStateSignature(state)", self.script)
        self.assertIn("const {executor: _volatileExecutor, ...domainState} = state", self.script)
        self.assertIn("function ccHasOpenModal()", self.script)
        self.assertIn("function ccControlInteractionActive()", self.script)
        self.assertIn("function ccHoldControlInteraction", self.script)
        self.assertIn("ccFlushDeferredControlRender", self.script)
        self.assertIn("nextSignature !== controlCenterRenderSignature", self.script)
        self.assertIn(
            "const interactionBlocksRender = ccHasOpenModal() || ccControlInteractionActive()",
            self.script,
        )
        self.assertIn("if (requiresFullRender && !interactionBlocksRender)", self.script)
        self.assertIn("renderControlExecutor();", self.script)
        self.assertIn(
            "if (modeSelect && modeSelect.value !== state.policy.mode)",
            self.script,
        )
        self.assertIn('tab.addEventListener("mousedown", hold, true)', self.script)
        self.assertIn('tab.addEventListener("keydown", hold, true)', self.script)

    def test_default_view_prioritizes_human_review_over_system_detail(self):
        self.assertIn('id="cc-focus-task"', self.html)
        self.assertIn('id="cc-human-workflow"', self.html)
        self.assertIn('class="cc-advanced-shell"', self.html)
        self.assertNotIn('<details class="cc-advanced-shell" open', self.html)
        self.assertIn("function renderControlFocus()", self.script)
        self.assertIn("function ccFocusedTask()", self.script)
        self.assertIn('new URLSearchParams(window.location.search).get("review")', self.script)
        self.assertIn("Website lokal starten", self.script)
        self.assertIn("Dateien in Web‑IDE", self.script)
        self.assertIn("PR-Ordner", self.script)

    def test_task_preview_and_ide_use_server_resolved_workspace(self):
        self.assertIn(
            "/api/control-center/tasks/${encodeURIComponent(key)}/preview",
            self.script,
        )
        self.assertIn(
            "/api/control-center/tasks/${encodeURIComponent(taskId)}/ide/open",
            self.script,
        )
        self.assertIn("Lokale Vorschau und Web‑IDE benötigen keine Deployment-Capability", self.html)

    def test_stale_state_and_observer_lock_mutations(self):
        self.assertIn("controlCenterStale = true", self.script)
        self.assertIn("[data-cc-mutation], [data-cc-stale-lock]", self.script)
        self.assertIn('mode === "observer"', self.script)
        self.assertIn(
            "Observer ist schreibgeschützt. Wechsle zuerst", self.script
        )
        self.assertIn('data-cc-allowed-modes="guided"', self.script)
        self.assertIn(
            'data-cc-allowed-modes="campaign autopilot"', self.script
        )
        self.assertIn("Arbeitsweise", self.html)
        self.assertIn('id="cc-mode-explanation"', self.html)

    def test_repository_settings_remain_readable_in_observer_mode(self):
        settings_button = re.search(
            r'<button id="cc-repository-policy-button"[^>]*>', self.html
        )
        self.assertIsNotNone(settings_button)
        self.assertNotIn("data-cc-mutation", settings_button.group(0))
        self.assertIn('type="submit" class="btn btn-primary" data-cc-mutation', self.html)

    def test_completed_review_offers_the_next_active_pull_request(self):
        self.assertIn("function ccNextActiveTask(excludeTaskId", self.script)
        self.assertIn("function openControlTaskReview(taskId)", self.script)
        self.assertIn('task.status !== "completed" && task.current_sha', self.script)
        self.assertIn('task.status !== "completed" && task.pr_number', self.script)
        self.assertIn("Aktiven PR öffnen", self.script)

    def test_mutations_are_deduplicated_and_forms_are_locked(self):
        self.assertIn("const controlCenterInFlightRequests = new Map()", self.script)
        self.assertIn("const controlCenterSubmittingForms = new WeakSet()", self.script)
        self.assertIn("controlCenterInFlightRequests.get(signature)", self.script)
        self.assertIn("ccBeginFormSubmission(event.currentTarget)", self.script)
        self.assertIn('element.setAttribute("aria-busy", "true")', self.script)
        self.assertIn(".btn.is-pending", self.style)

    def test_generated_idempotency_keys_sanitize_api_paths(self):
        self.assertIn(
            '.replace(/[^A-Za-z0-9._:-]+/g, "-")',
            self.script,
        )
        self.assertIn(
            "const maxPrefixLength = Math.max(1, 127 - random.length)",
            self.script,
        )
        self.assertIn(
            'ccApi("/api/control-center/executor/tick"',
            self.script,
        )

    def test_task_progress_has_six_named_states_and_error_output(self):
        match = re.search(
            r"const CC_TASK_STAGES = \[(.*?)\];",
            self.script,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        stages = re.findall(r'\{id: "([^"]+)", label: "([^"]+)"\}', match.group(1))
        self.assertEqual(
            stages,
            [
                ("queued", "Geplant"),
                ("running", "Agent"),
                ("waiting_ci", "CI"),
                ("waiting_review", "Review"),
                ("waiting_human", "Human Gate"),
                ("completed", "Fertig"),
            ],
        )
        self.assertIn("grid-template-columns: repeat(6", self.style)
        self.assertIn('function ccTaskProgress(task)', self.script)
        self.assertIn('index === stage.index && stage.modifier', self.script)
        self.assertIn("task.last_error", self.script)
        self.assertIn("cc-task-state-message is-error", self.script)
        self.assertIn("cc-task-card.is-failed", self.style)
        self.assertIn("cc-task-card.is-paused", self.style)

    def test_agent_permission_gates_are_visible_and_open_the_target_chat(self):
        self.assertIn('agent_permission: "Anti-Gravity-Freigabe"', self.script)
        self.assertIn("executor.waiting_human || []", self.script)
        self.assertIn("job.agent_gate", self.script)
        self.assertIn("task.agent_gate", self.script)
        self.assertIn("Anti-Gravity-Chat öffnen", self.script)
        self.assertIn("openHubOverviewChat", self.script)
        self.assertIn("Der Lauf bleibt reserviert", self.script)
        self.assertIn("Geschützte Änderungen freigeben", self.script)
        self.assertIn('approvalType === "protected_path"', self.script)
        self.assertIn("Neuen Plan anlegen", self.script)
        self.assertIn("function replanPlanningJob(jobId)", self.script)
        self.assertIn("visibleGateEntities", self.script)
        self.assertIn("warten auf dich", self.html)

    def test_candidate_activation_is_dependency_gated_and_unambiguous(self):
        match = re.search(
            r"const CC_FINISHED_CANDIDATE_STATUSES = new Set\(\[(.*?)\]\);",
            self.script,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            re.findall(r'"([^"]+)"', match.group(1)),
            ["completed", "merged", "deployed", "obsolete"],
        )
        self.assertIn("function ccCandidateDependencyState(campaign, candidate)", self.script)
        self.assertIn("function ccCandidateActivationState(campaign, candidate)", self.script)
        self.assertIn("if (!dependencyState.complete)", self.script)
        self.assertIn(
            'data-cc-dependency-state="${dependencyState.complete ? "ready" : "blocked"}"',
            self.script,
        )
        self.assertIn('data-cc-action="activate-candidate"', self.script)
        self.assertGreaterEqual(
            self.script.count('data-cc-candidate-id="${escapeHTML(candidate.id)}"'),
            2,
        )
        self.assertIn(
            'data-cc-candidate-action-for="${escapeHTML(candidate.id)}"',
            self.script,
        )
        self.assertIn('disabled aria-disabled="true"', self.script)
        self.assertIn("Wartet auf Vorgänger", self.script)
        self.assertIn(
            'ccNotify("warning", "Work Order gesperrt", activationState.reason)',
            self.script,
        )

    def test_pause_reason_uses_a_hub_form_instead_of_native_prompt(self):
        self.assertIn('id="cc-pause-modal"', self.html)
        self.assertIn('onsubmit="submitControlPause(event)"', self.html)
        self.assertIn('id="cc-pause-reason"', self.html)
        self.assertIn('maxlength="500" required', self.html)
        self.assertIn("function openControlPauseModal()", self.script)
        self.assertIn("async function submitControlPause(event)", self.script)
        self.assertIn("const saved = await setControlPauseState(true, reason)", self.script)
        self.assertNotIn(
            'prompt("Warum wird das Control Center pausiert?")',
            self.script,
        )

    def test_protected_rejection_uses_a_sha_bound_hub_form(self):
        self.assertIn('id="cc-protected-reject-modal"', self.html)
        self.assertIn('onsubmit="submitProtectedPathReject(event)"', self.html)
        self.assertIn('id="cc-protected-reject-reason"', self.html)
        self.assertIn('id="cc-protected-reject-sha"', self.html)
        self.assertIn("let protectedPathRejectContext = null", self.script)
        self.assertIn("function rejectProtectedPathForRepair(taskId)", self.script)
        self.assertIn("async function submitProtectedPathReject(event)", self.script)
        self.assertIn("currentSha !== context.targetSha", self.script)
        self.assertNotIn("window.prompt", self.script)

    def test_sha_approvals_use_a_commit_bound_hub_form(self):
        self.assertIn('id="cc-approval-modal"', self.html)
        self.assertIn('onsubmit="submitControlApproval(event)"', self.html)
        self.assertIn('id="cc-approval-sha"', self.html)
        self.assertIn("let controlApprovalContext = null", self.script)
        self.assertIn("function approveTaskStage(taskId, approvalType)", self.script)
        self.assertIn("async function submitControlApproval(event)", self.script)
        self.assertIn("currentTargetSha !== context.targetSha", self.script)
        self.assertIn("Ändert sich der Commit, verfällt diese Entscheidung automatisch.", self.script)
        self.assertNotIn("if (!confirm(`${label} verbindlich für SHA", self.script)

    def test_all_control_actions_use_hub_dialogs_not_browser_popups(self):
        self.assertIn('id="cc-confirm-modal"', self.html)
        self.assertIn('onsubmit="submitControlConfirmation(event)"', self.html)
        self.assertIn("let controlConfirmationContext = null", self.script)
        self.assertIn("function requestControlConfirmation({", self.script)
        self.assertIn("function settleControlConfirmation(accepted)", self.script)
        self.assertIn("reasonField.reportValidity()", self.script)
        self.assertIn("const observer = new MutationObserver", self.script)
        self.assertIn("context.observer?.disconnect()", self.script)
        self.assertNotRegex(self.script, r"\bconfirm\s*\(")
        self.assertNotRegex(self.script, r"\bprompt\s*\(")
        self.assertNotRegex(self.script, r"\balert\s*\(")

    def test_rejected_protected_commit_can_be_resumed_from_the_task_card(self):
        self.assertIn(
            'task.status === "repair" && task.wake_reason === "protected_path_rejected"',
            self.script,
        )
        self.assertIn("Repair erneut starten", self.script)
        self.assertIn("async function resumeControlTaskAfterFix(taskId)", self.script)
        self.assertIn(
            "`/api/control-center/tasks/${encodeURIComponent(taskId)}/resume-after-fix`",
            self.script,
        )
        self.assertIn("Der Task startet erst nach dem globalen Fortsetzen.", self.script)


if __name__ == "__main__":
    unittest.main()
