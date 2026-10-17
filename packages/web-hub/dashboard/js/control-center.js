let controlCenterState = null;
let controlCenterLoading = false;
let controlCenterRefreshTimer = null;
let controlCenterRefreshObserver = null;
let controlCenterLastUpdatedAt = 0;
let controlCenterStale = true;
let controlCenterLastError = "";
let controlCenterRenderSignature = "";
let controlCenterInteractionUntil = 0;
let protectedPathRejectContext = null;
let controlApprovalContext = null;
let controlConfirmationContext = null;
let controlFindingContext = null;

const controlCenterInFlightRequests = new Map();
const controlCenterSubmittingForms = new WeakSet();
const controlTaskPreviews = new Map();
const controlTaskPreviewChecks = new Set();

const CC_MODE_COPY = {
    observer: "Nur beobachten · Planung und alle schreibenden Aktionen sind gesperrt.",
    guided: "Planung ist erlaubt · jede Work Order braucht deine einzelne Freigabe.",
    campaign: "Freigegebene Campaigns starten konfliktfreie Waves innerhalb der Repository-Regeln.",
    autopilot: "Experimentell · Waves laufen policy-gesteuert; Merge und Production bleiben Human Gates.",
};

const CC_TASK_STAGES = [
    {id: "queued", label: "Geplant"},
    {id: "running", label: "Agent"},
    {id: "waiting_ci", label: "CI"},
    {id: "waiting_review", label: "Review"},
    {id: "waiting_human", label: "Human Gate"},
    {id: "completed", label: "Fertig"},
];

const CC_FINISHED_CANDIDATE_STATUSES = new Set([
    "completed",
    "merged",
    "deployed",
    "obsolete",
]);

const CC_LABELS = {
    agent_permission: "Anti-Gravity-Freigabe",
    plan_approval: "Plan freigeben",
    campaign_planning: "Campaign planen",
    work_order_approval: "Arbeitsauftrag freigeben",
    protected_path: "Geschützter Pfad",
    no_progress: "Kein Fortschritt",
    plan_amendment: "Planänderung",
    new: "Neu",
    accepted: "Akzeptiert",
    deferred: "Zurückgestellt",
    rejected: "Abgelehnt",
    draft: "Entwurf",
    approved: "Freigegeben",
    ready: "Bereit",
    queued: "Eingeplant",
    leased: "Reserviert",
    running: "Anti-Gravity arbeitet",
    waiting_ci: "Wartet auf CI",
    waiting_review: "Im Review",
    repair: "Repair",
    paused: "Pausiert",
    failed: "Fehlgeschlagen",
    waiting_human: "Deine Prüfung",
    completed: "Abgeschlossen",
    collecting: "Evidence offen",
    blocked: "Blockiert",
    ready_for_human: "Bereit für Human-Test",
    low: "Niedrig",
    medium: "Mittel",
    high: "Hoch",
    critical: "Kritisch",
};

const controlDictation = {
    fieldId: "",
    phase: "idle",
    pollTimer: null,
    uiTimer: null,
    startedAt: 0,
    windowId: "AG-DIKTAT",
    startPromise: null,
    stopPromise: null,
};

function ccDictationIcon() {
    return `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
            stroke-linejoin="round" aria-hidden="true">
            <rect x="9" y="2" width="6" height="12" rx="3"></rect>
            <path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"></path>
        </svg>`;
}

function initializeControlDictationFields() {
    document.querySelectorAll("[data-cc-dictation-label]").forEach(field => {
        if (!field.id || field.dataset.ccDictationReady === "true") return;
        const group = field.closest(".form-group");
        const heading = group?.querySelector(":scope > span");
        if (!group || !heading) return;

        group.classList.add("cc-dictation-group");
        heading.classList.add("cc-dictation-heading");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "cc-dictation-button";
        button.dataset.dictationTarget = field.id;
        button.setAttribute("aria-controls", field.id);
        button.setAttribute("aria-pressed", "false");
        button.setAttribute(
            "aria-label",
            `${field.dataset.ccDictationLabel || "Feld"} diktieren`,
        );
        button.title = "Mit dem nativen Anti-Gravity-Mikrofon diktieren";
        button.innerHTML = ccDictationIcon();
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            toggleControlDictation(field.id);
        });
        heading.appendChild(button);

        const status = document.createElement("div");
        status.className = "cc-dictation-status";
        status.dataset.dictationStatus = field.id;
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        status.hidden = true;
        status.innerHTML = `
            <span class="cc-dictation-status-dot" aria-hidden="true"></span>
            <span class="cc-dictation-status-copy"></span>
            <time>0:00</time>`;
        field.insertAdjacentElement("afterend", status);
        field.dataset.ccDictationReady = "true";
    });
    updateControlDictationUI();
}

function ccDictationElapsed() {
    if (!controlDictation.startedAt) return "0:00";
    const seconds = Math.max(
        0,
        Math.floor((Date.now() - controlDictation.startedAt) / 1000),
    );
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function updateControlDictationUI() {
    const active = controlDictation.fieldId;
    const phase = controlDictation.phase;
    const copies = {
        starting: `${controlDictation.windowId} wird gestartet…`,
        recording: `${controlDictation.windowId} · Aufnahme läuft`,
        stopping: `${controlDictation.windowId} · Aufnahme wird beendet…`,
    };

    document.querySelectorAll(".cc-dictation-button").forEach(button => {
        const isActive = button.dataset.dictationTarget === active;
        button.classList.toggle("is-starting", isActive && phase === "starting");
        button.classList.toggle("is-recording", isActive && phase === "recording");
        button.classList.toggle("is-stopping", isActive && phase === "stopping");
        button.disabled = Boolean(active) && (
            !isActive || phase === "starting" || phase === "stopping"
        );
        button.setAttribute(
            "aria-pressed",
            String(isActive && phase === "recording"),
        );
        button.title = isActive && phase === "recording"
            ? "Aufnahme beenden"
            : "Mit dem nativen Anti-Gravity-Mikrofon diktieren";
    });

    document.querySelectorAll(".cc-dictation-status").forEach(status => {
        const isActive = status.dataset.dictationStatus === active && phase !== "idle";
        status.hidden = !isActive;
        status.dataset.phase = isActive ? phase : "idle";
        if (!isActive) return;
        status.querySelector(".cc-dictation-status-copy").textContent =
            copies[phase] || "Diktat wird vorbereitet…";
        status.querySelector("time").textContent = ccDictationElapsed();
    });
}

function setControlDictationPhase(phase) {
    controlDictation.phase = phase;
    if (controlDictation.uiTimer) {
        clearInterval(controlDictation.uiTimer);
        controlDictation.uiTimer = null;
    }
    if (phase === "recording") {
        controlDictation.startedAt ||= Date.now();
        controlDictation.uiTimer = setInterval(updateControlDictationUI, 1000);
    }
    updateControlDictationUI();
}

function clearControlDictationTimers() {
    if (controlDictation.pollTimer) {
        clearInterval(controlDictation.pollTimer);
        controlDictation.pollTimer = null;
    }
    if (controlDictation.uiTimer) {
        clearInterval(controlDictation.uiTimer);
        controlDictation.uiTimer = null;
    }
}

function resetControlDictation() {
    clearControlDictationTimers();
    controlDictation.fieldId = "";
    controlDictation.phase = "idle";
    controlDictation.startedAt = 0;
    controlDictation.windowId = "AG-DIKTAT";
    updateControlDictationUI();
}

async function ccDictationHeaders({json = false} = {}) {
    const headers = {};
    if (json) headers["Content-Type"] = "application/json";
    if (typeof getAuthToken === "function") {
        const token = await getAuthToken();
        if (token) headers.Authorization = `Bearer ${token}`;
    }
    return headers;
}

function applyControlDictationText(field, text) {
    if (!field || typeof text !== "string") return;
    const maximum = Number(field.maxLength || 0);
    const nextValue = maximum > 0 ? text.slice(0, maximum) : text;
    if (field.value === nextValue) return;
    field.value = nextValue;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    field.dispatchEvent(new Event("change", {bubbles: true}));
    field.setSelectionRange?.(nextValue.length, nextValue.length);
}

async function toggleControlDictation(fieldId) {
    if (
        controlDictation.fieldId === fieldId
        && controlDictation.phase === "recording"
    ) {
        await stopControlDictation();
        return;
    }
    if (controlDictation.fieldId) {
        await stopControlDictation({silent: true});
    }

    const field = document.getElementById(fieldId);
    if (!field || field.disabled || field.readOnly) return;
    controlDictation.fieldId = fieldId;
    controlDictation.startedAt = 0;
    setControlDictationPhase("starting");

    controlDictation.startPromise = (async () => {
        const response = await controlFetch("/api/voice/dictation/start", {
            method: "POST",
            headers: await ccDictationHeaders({json: true}),
            body: JSON.stringify({
                text: field.value || "",
                field_label: field.dataset.ccDictationLabel || field.id,
            }),
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || data.success !== true) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        controlDictation.windowId = data.window?.window_id || "AG-DIKTAT";
        applyControlDictationText(field, data.text);
        controlDictation.startedAt = Date.now();
        setControlDictationPhase("recording");
        controlDictation.pollTimer = setInterval(pollControlDictation, 300);
        ccNotify(
            "info",
            "Diktat läuft",
            `${controlDictation.windowId} transkribiert direkt in „${field.dataset.ccDictationLabel}“.`,
        );
    })();

    try {
        await controlDictation.startPromise;
    } catch (error) {
        ccNotify("error", "Mikrofon nicht gestartet", error.message);
        resetControlDictation();
    } finally {
        controlDictation.startPromise = null;
    }
}

async function pollControlDictation() {
    const fieldId = controlDictation.fieldId;
    if (!fieldId || controlDictation.phase !== "recording") return;
    try {
        const response = await fetch("/api/voice/dictation/status", {
            headers: await ccDictationHeaders(),
            cache: "no-store",
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || data.success === false) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        const field = document.getElementById(fieldId);
        applyControlDictationText(field, data.text);
        controlDictation.windowId = data.window?.window_id || controlDictation.windowId;
        if (data.isRecording === false) {
            resetControlDictation();
            ccNotify("success", "Diktat übernommen", "Der erkannte Text steht im Formularfeld.");
        } else {
            updateControlDictationUI();
        }
    } catch (error) {
        clearControlDictationTimers();
        resetControlDictation();
        ccNotify("error", "Diktatverbindung unterbrochen", error.message);
    }
}

async function stopControlDictation({silent = false} = {}) {
    if (!controlDictation.fieldId) return;
    if (controlDictation.stopPromise) return controlDictation.stopPromise;
    if (controlDictation.startPromise) {
        try { await controlDictation.startPromise; } catch (_) { return; }
    }

    const fieldId = controlDictation.fieldId;
    clearControlDictationTimers();
    setControlDictationPhase("stopping");
    controlDictation.stopPromise = (async () => {
        const response = await controlFetch("/api/voice/dictation/stop", {
            method: "POST",
            headers: await ccDictationHeaders(),
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok && response.status !== 400) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applyControlDictationText(document.getElementById(fieldId), data.text);
        return data;
    })();

    try {
        await controlDictation.stopPromise;
        if (!silent) {
            ccNotify("success", "Diktat übernommen", "Der erkannte Text steht im Formularfeld.");
        }
    } catch (error) {
        if (!silent) {
            ccNotify("error", "Aufnahme nicht sauber beendet", error.message);
        }
    } finally {
        controlDictation.stopPromise = null;
        resetControlDictation();
    }
}

async function finishControlDictationForForm(form) {
    const field = document.getElementById(controlDictation.fieldId);
    if (field && form?.contains(field)) {
        await stopControlDictation({silent: true});
    }
}

function stopControlDictationForModal(modalId) {
    const modal = document.getElementById(modalId);
    const field = document.getElementById(controlDictation.fieldId);
    if (modal && field && modal.contains(field)) {
        stopControlDictation({silent: true});
    }
}

document.addEventListener("DOMContentLoaded", initializeControlDictationFields);
document.addEventListener("DOMContentLoaded", () => {
    const tab = document.getElementById("control-center-tab");
    if (tab && typeof MutationObserver === "function") {
        controlCenterRefreshObserver?.disconnect();
        controlCenterRefreshObserver = new MutationObserver(syncControlCenterRefreshLifecycle);
        controlCenterRefreshObserver.observe(tab, {
            attributes: true,
            attributeFilter: ["class"],
        });
    }
    if (tab) {
        const hold = event => {
            const target = event.target instanceof Element ? event.target : null;
            if (!target?.closest("button, select, input, textarea, summary, [contenteditable='true']")) return;
            ccHoldControlInteraction(target.matches("select, input, textarea") ? 10000 : 1200);
        };
        tab.addEventListener("pointerdown", hold, true);
        tab.addEventListener("mousedown", hold, true);
        tab.addEventListener("keydown", hold, true);
        tab.addEventListener("focusin", hold, true);
        tab.addEventListener("input", () => ccHoldControlInteraction(10000), true);
        tab.addEventListener("change", () => ccHoldControlInteraction(1600), true);
        tab.addEventListener("focusout", () => {
            window.setTimeout(ccFlushDeferredControlRender, 180);
        }, true);
    }
    document.querySelectorAll(".btn[data-cc-help]").forEach(element => {
        element.title = element.dataset.ccHelp || "";
    });
    document.addEventListener("visibilitychange", syncControlCenterRefreshLifecycle);
    syncControlCenterRefreshLifecycle();
});

function ccProject() {
    return projects.find(project => Number(project.id) === Number(currentProjectId)) || null;
}

function ccNotify(type, title, message) {
    if (typeof showToast === "function") showToast(type, title, message);
    else console[type === "error" ? "error" : "log"](`${title}: ${message}`);
}

function requestControlConfirmation({
    title,
    message,
    detail = "",
    confirmLabel = "Bestätigen",
    reasonLabel = "",
    reasonRequired = false,
    hint = "",
    danger = true,
}) {
    if (controlConfirmationContext?.resolve) {
        controlConfirmationContext.observer?.disconnect();
        controlConfirmationContext.resolve(null);
    }
    return new Promise(resolve => {
        const modal = document.getElementById("cc-confirm-modal");
        const observer = new MutationObserver(() => {
            if (
                controlConfirmationContext?.observer === observer
                && modal.style.display !== "flex"
            ) {
                const context = controlConfirmationContext;
                controlConfirmationContext = null;
                observer.disconnect();
                context.resolve(null);
            }
        });
        controlConfirmationContext = {resolve, reasonRequired, observer};
        document.getElementById("cc-confirm-title").textContent = title;
        document.getElementById("cc-confirm-message").textContent = message;
        const detailElement = document.getElementById("cc-confirm-detail");
        detailElement.textContent = detail;
        detailElement.hidden = !detail;
        const reasonGroup = document.getElementById("cc-confirm-reason-group");
        const reasonField = document.getElementById("cc-confirm-reason");
        reasonGroup.hidden = !reasonLabel;
        document.getElementById("cc-confirm-reason-label").textContent =
            reasonLabel || "Begründung";
        reasonField.value = "";
        reasonField.required = Boolean(reasonRequired);
        reasonField.setCustomValidity("");
        document.getElementById("cc-confirm-hint").textContent = hint;
        const submit = document.getElementById("cc-confirm-submit");
        submit.textContent = confirmLabel;
        submit.classList.toggle("btn-danger", danger);
        submit.classList.toggle("btn-primary", !danger);
        openModal("cc-confirm-modal");
        observer.observe(modal, {attributes: true, attributeFilter: ["style"]});
        window.setTimeout(() => {
            if (reasonLabel) reasonField.focus();
            else submit.focus();
        }, 0);
    });
}

function settleControlConfirmation(accepted) {
    const context = controlConfirmationContext;
    if (!context) return;
    const reasonField = document.getElementById("cc-confirm-reason");
    const reason = reasonField.value.trim();
    if (accepted && context.reasonRequired && reason.length < 3) {
        reasonField.setCustomValidity(
            "Bitte gib einen nachvollziehbaren Grund mit mindestens drei Zeichen an.",
        );
        reasonField.reportValidity();
        return;
    }
    reasonField.setCustomValidity("");
    controlConfirmationContext = null;
    context.observer?.disconnect();
    closeModal("cc-confirm-modal");
    context.resolve(accepted ? {confirmed: true, reason} : null);
}

function cancelControlConfirmation() {
    settleControlConfirmation(false);
}

function submitControlConfirmation(event) {
    event.preventDefault();
    settleControlConfirmation(true);
}

function ccControlCenterVisible() {
    const tab = document.getElementById("control-center-tab");
    return Boolean(tab?.classList.contains("active") && !document.hidden);
}

function ccCurrentMode() {
    return String(controlCenterState?.policy?.mode || "observer");
}

function ccMutationBlockReason(url = "", method = "POST") {
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(String(method).toUpperCase())) {
        return "";
    }
    if (url.includes("/preview") || url.endsWith("/ide/open")) {
        return "";
    }
    if (controlCenterStale || !controlCenterState) {
        return "Die Control-Center-Daten sind nicht aktuell. Lade die Ansicht neu, bevor du etwas änderst.";
    }
    const mode = ccCurrentMode();
    if (mode === "observer" && url !== "/api/control-center/policy") {
        return "Observer ist schreibgeschützt. Wechsle zuerst in Guided, Campaign oder Autopilot.";
    }
    if (url.includes("/pr-candidates/") && url.endsWith("/activate") && mode !== "guided") {
        return "Einzelne Work Orders können nur im Guided-Modus freigegeben werden.";
    }
    if (url.endsWith("/activate-wave") && !["campaign", "autopilot"].includes(mode)) {
        return "Konfliktfreie Waves benötigen den Campaign- oder Autopilot-Modus.";
    }
    if (controlCenterState.policy.paused && (
        url.endsWith("/activate")
        || url.endsWith("/activate-wave")
        || url.endsWith("/executor/tick")
    )) {
        return "Neue Arbeit ist pausiert. Setze das Control Center zuerst fort.";
    }
    return "";
}

function ccSetElementPending(element, pending) {
    if (!(element instanceof HTMLElement)) return;
    const count = Number(element.dataset.ccPendingCount || 0);
    if (pending) {
        if (count === 0) {
            element.dataset.ccPendingWasDisabled = element.disabled ? "true" : "false";
            element.setAttribute("aria-busy", "true");
            element.classList.add("is-pending");
            element.disabled = true;
        }
        element.dataset.ccPendingCount = String(count + 1);
        return;
    }
    const next = Math.max(0, count - 1);
    if (next > 0) {
        element.dataset.ccPendingCount = String(next);
        return;
    }
    delete element.dataset.ccPendingCount;
    element.removeAttribute("aria-busy");
    element.classList.remove("is-pending");
    if (element.dataset.ccPendingWasDisabled !== "true") element.disabled = false;
    delete element.dataset.ccPendingWasDisabled;
    applyControlCenterInteractivity();
}

function ccRequestTrigger() {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return null;
    const element = active.closest("button, select, input[type='submit']");
    if (!element) return null;
    return element.closest("#control-center-tab, [id^='cc-'].modal") ? element : null;
}

function ccBeginFormSubmission(form) {
    if (!(form instanceof HTMLFormElement)) return () => {};
    if (controlCenterSubmittingForms.has(form)) {
        ccNotify("info", "Aktion läuft bereits", "Bitte warte, bis der aktuelle Vorgang abgeschlossen ist.");
        return null;
    }
    controlCenterSubmittingForms.add(form);
    const submitters = Array.from(form.querySelectorAll("button[type='submit'], input[type='submit']"));
    submitters.forEach(element => ccSetElementPending(element, true));
    return () => {
        controlCenterSubmittingForms.delete(form);
        submitters.forEach(element => ccSetElementPending(element, false));
    };
}

function ccElementBlockReason(element) {
    if (!(element instanceof HTMLElement)) return "";
    if (element.matches("[data-cc-stale-lock]") && controlCenterStale) {
        return "Die Ansicht ist nicht aktuell. Erst neu laden.";
    }
    if (!element.matches("[data-cc-mutation]")) return "";
    if (controlCenterStale || !controlCenterState) {
        return "Die Ansicht ist nicht aktuell. Schreibende Aktionen sind gesperrt.";
    }
    const mode = ccCurrentMode();
    if (mode === "observer") {
        return "Observer ist schreibgeschützt. Wähle für Änderungen zuerst einen anderen globalen Betriebsmodus.";
    }
    const allowedModes = String(element.dataset.ccAllowedModes || "")
        .split(/\s+/)
        .filter(Boolean);
    if (allowedModes.length && !allowedModes.includes(mode)) {
        return allowedModes.length === 1 && allowedModes[0] === "guided"
            ? "Diese Aktion ist nur im Guided-Modus verfügbar."
            : `Diese Aktion benötigt einen der Modi: ${allowedModes.join(", ")}.`;
    }
    if (element.hasAttribute("data-cc-requires-running") && controlCenterState.policy.paused) {
        return "Neue Arbeit ist pausiert. Setze das Control Center zuerst fort.";
    }
    return "";
}

function applyControlCenterInteractivity() {
    const mode = ccCurrentMode();
    const explanation = document.getElementById("cc-mode-explanation");
    if (explanation) explanation.textContent = `${CC_MODE_COPY[mode] || mode} Gilt global für alle Repositories.`;

    document.querySelectorAll("[data-cc-mutation], [data-cc-stale-lock]").forEach(element => {
        if (!(element instanceof HTMLElement) || Number(element.dataset.ccPendingCount || 0) > 0) return;
        const reason = ccElementBlockReason(element);
        if (reason) {
            if (!element.hasAttribute("data-cc-policy-lock")) {
                element.dataset.ccPolicyWasDisabled = element.disabled ? "true" : "false";
                element.dataset.ccPolicyTitle = element.getAttribute("title") || "";
            }
            element.setAttribute("data-cc-policy-lock", "true");
            element.disabled = true;
            element.title = reason;
        } else if (element.hasAttribute("data-cc-policy-lock")) {
            if (element.dataset.ccPolicyWasDisabled !== "true") element.disabled = false;
            element.title = element.dataset.ccPolicyTitle || "";
            delete element.dataset.ccPolicyWasDisabled;
            delete element.dataset.ccPolicyTitle;
            element.removeAttribute("data-cc-policy-lock");
        }
    });
}

function ccRelativeUpdateTime() {
    if (!controlCenterLastUpdatedAt) return "noch nie";
    const seconds = Math.max(0, Math.round((Date.now() - controlCenterLastUpdatedAt) / 1000));
    if (seconds < 5) return "gerade eben";
    if (seconds < 60) return `vor ${seconds} s`;
    return new Date(controlCenterLastUpdatedAt).toLocaleTimeString("de-DE", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function setControlCenterFreshness(state, error = "") {
    const status = document.getElementById("cc-live-status");
    const staleNotice = document.getElementById("cc-stale-notice");
    const staleMessage = document.getElementById("cc-stale-message");
    const tab = document.getElementById("control-center-tab");

    if (state === "fresh") {
        controlCenterStale = false;
        controlCenterLastError = "";
        controlCenterLastUpdatedAt = Date.now();
    } else if (state === "error") {
        controlCenterStale = true;
        controlCenterLastError = error || "Unbekannter Verbindungsfehler";
    }

    if (status) {
        status.className = `cc-live-status is-${state}`;
        const label = status.querySelector("strong");
        const time = status.querySelector("time");
        if (label) {
            label.textContent = state === "fresh"
                ? "Live"
                : state === "error"
                    ? "Verbindung gestört"
                    : "Synchronisiert…";
        }
        if (time) time.textContent = ccRelativeUpdateTime();
        status.title = state === "error" ? controlCenterLastError : "";
    }
    if (staleNotice) staleNotice.hidden = state !== "error";
    if (staleMessage && state === "error") {
        staleMessage.textContent = `${controlCenterLastError} Schreibende Aktionen bleiben bis zu einer erfolgreichen Aktualisierung gesperrt.`;
    }
    tab?.classList.toggle("is-stale", controlCenterStale);
    applyControlCenterInteractivity();
}

function ccHasLiveControlActivity() {
    const executor = controlCenterState?.executor || {};
    const activeTasks = executor.active_task_ids || [];
    const syncing = executor.syncing_task_ids || [];
    const planning = controlCenterState?.planning_jobs || [];
    const tasks = controlCenterState?.tasks || [];
    const deployments = controlCenterState?.deployments || [];
    return Boolean(
        activeTasks.length
        || syncing.length
        || planning.some(item => ["queued", "running"].includes(item.status))
        || tasks.some(item => ["queued", "leased", "running", "waiting_ci", "waiting_review", "repair"].includes(item.status))
        || deployments.some(item => ["planned", "running"].includes(item.status))
    );
}

function ccDomainStateSignature(state) {
    if (!state || typeof state !== "object") return "";
    const {executor: _volatileExecutor, ...domainState} = state;
    return JSON.stringify(domainState);
}

function ccHasOpenModal() {
    return Array.from(document.querySelectorAll("[id^='cc-'].modal"))
        .some(modal => modal.style.display === "flex");
}

function ccHoldControlInteraction(milliseconds = 1200) {
    controlCenterInteractionUntil = Math.max(
        controlCenterInteractionUntil,
        Date.now() + Number(milliseconds || 0),
    );
}

function ccControlInteractionActive() {
    const tab = document.getElementById("control-center-tab");
    const active = document.activeElement;
    const editableActive = Boolean(
        tab?.contains(active)
        && active instanceof Element
        && active.matches("select, input, textarea, [contenteditable='true']"),
    );
    return editableActive || Date.now() < controlCenterInteractionUntil;
}

function ccFlushDeferredControlRender() {
    if (
        !controlCenterState
        || ccHasOpenModal()
        || ccControlInteractionActive()
    ) return;
    const signature = ccDomainStateSignature(controlCenterState);
    if (signature === controlCenterRenderSignature) return;
    controlCenterRenderSignature = signature;
    renderControlCenter();
}

function stopControlCenterRefresh() {
    if (controlCenterRefreshTimer) {
        clearTimeout(controlCenterRefreshTimer);
        controlCenterRefreshTimer = null;
    }
}

function scheduleControlCenterRefresh(delay = null) {
    stopControlCenterRefresh();
    if (!ccControlCenterVisible()) return;
    const selectedDelay = Number(delay || (ccHasLiveControlActivity() ? 2000 : 8000));
    controlCenterRefreshTimer = window.setTimeout(() => {
        controlCenterRefreshTimer = null;
        loadControlCenter({background: true});
    }, selectedDelay);
}

function syncControlCenterRefreshLifecycle() {
    if (!ccControlCenterVisible()) {
        stopControlCenterRefresh();
        return;
    }
    if (!controlCenterLoading && (!controlCenterState || controlCenterStale)) {
        loadControlCenter({background: true});
    } else {
        scheduleControlCenterRefresh();
    }
}

function ccKey(prefix) {
    const random = String(
        globalThis.crypto?.randomUUID?.()
        || `${Date.now()}-${Math.random().toString(16).slice(2)}`
    ).replace(/[^A-Za-z0-9._:-]+/g, "-");
    const maxPrefixLength = Math.max(1, 127 - random.length);
    const safePrefix = String(prefix || "cc")
        .replace(/[^A-Za-z0-9._:-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, maxPrefixLength) || "cc";
    return `${safePrefix}:${random}`;
}

async function ccApi(url, { method = "GET", body = null, key = "" } = {}) {
    const normalizedMethod = String(method || "GET").toUpperCase();
    const serializedBody = body === null ? "" : JSON.stringify(body);
    const signature = `${normalizedMethod}|${url}|${serializedBody}`;
    const existing = controlCenterInFlightRequests.get(signature);
    if (existing) return existing;

    const blockReason = ccMutationBlockReason(url, normalizedMethod);
    if (blockReason) throw new Error(blockReason);

    const trigger = ccRequestTrigger();
    ccSetElementPending(trigger, true);
    const request = (async () => {
        const options = { method: normalizedMethod, headers: {}, cache: "no-store" };
        if (body !== null) {
            options.headers["Content-Type"] = "application/json";
            options.body = serializedBody;
        }
        if (["POST", "PUT", "PATCH", "DELETE"].includes(normalizedMethod)) {
            options.headers["Idempotency-Key"] = key || ccKey(`${normalizedMethod}:${url}`);
        }
        const response = await fetch(url, options);
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    })();
    controlCenterInFlightRequests.set(signature, request);
    try {
        return await request;
    } finally {
        if (controlCenterInFlightRequests.get(signature) === request) {
            controlCenterInFlightRequests.delete(signature);
        }
        ccSetElementPending(trigger, false);
    }
}

function ccDate(value) {
    if (!value) return "—";
    const normalized = String(value).includes("T") ? value : `${String(value).replace(" ", "T")}Z`;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? escapeHTML(String(value)) : parsed.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

function ccShortSha(value) {
    return value ? escapeHTML(String(value).slice(0, 10)) : "kein Git-SHA";
}

function ccBadge(value, kind = "status") {
    const safe = String(value || "unknown").toLowerCase();
    return `<span class="cc-badge cc-${kind}-${escapeHTML(safe)}">${escapeHTML(CC_LABELS[safe] || safe)}</span>`;
}

async function loadControlCenter({background = false} = {}) {
    if (controlCenterLoading) return;
    controlCenterLoading = true;
    stopControlCenterRefresh();
    setControlCenterFreshness("loading");
    const project = ccProject();
    try {
        const suffix = project ? `?project_id=${encodeURIComponent(project.id)}` : "";
        const [overview, executor] = await Promise.all([
            ccApi(`/api/control-center/overview${suffix}`),
            ccApi("/api/control-center/executor").catch(error => ({
                executor: { running: false, last_error: error.message, active_task_ids: [] },
            })),
        ]);
        const nextState = { ...overview, executor: executor.executor || {} };
        const nextSignature = ccDomainStateSignature(nextState);
        const requiresFullRender = (
            !controlCenterState
            || nextSignature !== controlCenterRenderSignature
        );
        controlCenterState = nextState;
        const interactionBlocksRender = ccHasOpenModal() || ccControlInteractionActive();
        if (requiresFullRender && !interactionBlocksRender) {
            controlCenterRenderSignature = nextSignature;
            renderControlCenter();
        } else {
            renderControlExecutor();
            applyControlCenterInteractivity();
        }
        setControlCenterFreshness("fresh");
    } catch (error) {
        const wasStale = controlCenterStale;
        setControlCenterFreshness("error", error.message);
        if (!background || !wasStale) ccNotify("error", "Control Center", error.message);
    } finally {
        controlCenterLoading = false;
        scheduleControlCenterRefresh(controlCenterStale ? 3000 : null);
    }
}

function renderControlCenter() {
    if (!controlCenterState) return;
    const state = controlCenterState;
    const project = ccProject();
    document.getElementById("cc-project-label").textContent = project?.name || "Alle importierten Projekte";
    document.getElementById("cc-scope-notice").style.display = project ? "none" : "block";
    document.getElementById("cc-add-recommendation").disabled = !project;
    document.getElementById("cc-add-campaign").disabled = !project;
    document.getElementById("cc-plan-wish").disabled = !project;
    document.getElementById("cc-repository-policy-button").disabled = !project;
    document.querySelectorAll(".cc-focus-quick-actions [data-cc-mutation]").forEach(element => {
        element.disabled = !project;
    });
    const modeSelect = document.getElementById("cc-mode-select");
    if (modeSelect && modeSelect.value !== state.policy.mode) {
        modeSelect.value = state.policy.mode;
    }
    const pauseButton = document.getElementById("cc-pause-button");
    pauseButton.textContent = state.policy.paused ? "Neue Arbeit fortsetzen" : "Neue Arbeit pausieren";
    pauseButton.className = `btn ${state.policy.paused ? "btn-success" : "btn-danger"}`;
    pauseButton.title = state.policy.paused
        ? state.policy.pause_reason || "Neue Arbeit ist pausiert"
        : "Stoppt neue Planung, Work-Order-Freigaben und neue Executor-Leases; bereits laufende Tasks enden kontrolliert.";

    document.getElementById("cc-stat-attention").textContent = state.summary.attention_open;
    document.getElementById("cc-stat-campaigns").textContent = state.summary.campaigns_open;
    document.getElementById("cc-stat-tasks").textContent = state.summary.tasks_active || 0;
    document.getElementById("cc-stat-human").textContent =
        state.summary.human_gates_open ?? state.summary.tasks_waiting_human ?? 0;
    document.getElementById("cc-stat-work-orders").textContent = state.summary.work_orders_approved;
    document.getElementById("cc-stat-deployments").textContent = state.summary.deployments_active || 0;
    renderControlExecutor();
    renderControlFocus();
    renderControlAttention();
    renderControlRecommendations();
    renderPlanningJobs();
    renderControlCampaigns();
    renderControlTasks();
    renderControlDeployments();
    renderControlCheckpoints();
    renderControlAudit();
    applyControlCenterInteractivity();
}

function renderPlanningJobs() {
    const container = document.getElementById("cc-planning-job-list");
    const jobs = controlCenterState?.planning_jobs || [];
    container.innerHTML = jobs.map(job => {
        const gate = job.agent_gate;
        const busy = ["queued", "running"].includes(job.status) && !gate;
        const dotClass = job.status === "failed" ? "is-error" : busy ? "is-busy" : "is-live";
        const detail = gate
            ? `Freigabe erforderlich · ${gate.consequence}`
            : job.status === "failed"
            ? job.last_error
            : job.antigravity_chat_id
                ? `AG Chat ${job.antigravity_chat_id}`
                : `${job.planning_depth} · bis ${job.max_candidates} PRs`;
        const openChat = gate && job.antigravity_chat_id
            ? `<button class="btn btn-primary btn-xs" onclick="openHubOverviewChat('${job.antigravity_chat_id}')">Anti-Gravity-Chat öffnen</button>`
            : "";
        const actions = job.status === "failed"
            ? Number(job.attempt || 0) < 3
                ? `<button class="btn btn-secondary btn-xs" onclick="retryPlanningJob('${job.id}')" data-cc-mutation>Erneut planen</button>`
                : `<button class="btn btn-secondary btn-xs" onclick="replanPlanningJob('${job.id}')" data-cc-mutation>Neuen Plan anlegen</button>`
            : job.campaign_id
                ? `<button class="btn btn-secondary btn-xs" onclick="inspectCampaignPlan('${job.campaign_id}')">Campaign prüfen</button>`
                : "";
        return `<article class="cc-planning-job">
            <span class="cc-live-dot ${dotClass}"></span>
            <div class="cc-planning-job-copy"><strong>${escapeHTML(job.wish)}</strong><small>${escapeHTML(detail || job.status)}</small></div>
            <div class="cc-planning-job-actions">${ccBadge(gate ? "waiting_human" : job.status)}${openChat}${actions}</div>
        </article>`;
    }).join("");
}

function renderControlExecutor() {
    const executor = controlCenterState?.executor || {};
    const active = executor.active_task_ids || [];
    const visibleGateEntities = new Set([
        ...(controlCenterState?.planning_jobs || []).map(
            item => `planning_job:${item.id}`,
        ),
        ...(controlCenterState?.tasks || []).map(
            item => `agent_task:${item.id}`,
        ),
    ]);
    const gates = (executor.waiting_human || []).filter(
        gate => visibleGateEntities.has(
            `${gate.entity_type}:${gate.entity_id}`,
        ),
    );
    const dot = document.getElementById("cc-executor-dot");
    dot.className = `cc-live-dot ${executor.last_error ? "is-error" : active.length ? "is-busy" : executor.running ? "is-live" : ""}`;
    document.getElementById("cc-executor-title").textContent = executor.last_error
        ? "Executor meldet einen Fehler"
        : gates.length
            ? `${gates.length} Anti-Gravity-Freigabe${gates.length === 1 ? "" : "n"} offen`
        : active.length
            ? `${active.length} Anti-Gravity Task${active.length === 1 ? "" : "s"} arbeitet`
            : executor.running ? "Executor bereit" : "Executor gestoppt";
    document.getElementById("cc-executor-detail").textContent = executor.last_error
        || (gates.length
            ? "Der Lauf bleibt reserviert und wird nach deiner Entscheidung fortgesetzt."
            : executor.syncing_task_ids?.length
            ? `${executor.syncing_task_ids.length} PR-Syncs laufen`
            : "Leases, CI-Polling und Recovery aktiv");
    document.getElementById("cc-executor-workers").textContent = `${active.length} / ${executor.worker_limit || 4} AG Worker`;
}

function renderControlAttention() {
    const container = document.getElementById("cc-attention-list");
    const items = controlCenterState.attention || [];
    if (!items.length) {
        container.innerHTML = `<div class="cc-empty"><span>✓</span> Gerade ist keine menschliche Entscheidung blockierend.</div>`;
        return;
    }
    container.innerHTML = items.map(item => `
        <article class="cc-attention-item cc-urgency-${escapeHTML(item.urgency)}">
            <div class="cc-item-meta">${ccBadge(item.category, "category")} <code>${escapeHTML(item.entity_id)}</code></div>
            <h3>${escapeHTML(item.title)}</h3>
            <p>${escapeHTML(item.consequence)}</p>
            <div class="cc-recommendation-line"><strong>Empfehlung:</strong> ${escapeHTML(item.recommendation)}</div>
        </article>
    `).join("");
}

function renderControlRecommendations() {
    const container = document.getElementById("cc-recommendation-list");
    const allItems = controlCenterState.recommendations || [];
    const items = allItems.filter(item => item.status !== "rejected");
    if (!items.length) {
        const removed = allItems.length - items.length;
        container.innerHTML = `<div class="cc-empty">Ideen und belegte Verbesserungen landen hier, bevor daraus Arbeit wird.${removed ? ` ${removed} entfernte Einträge bleiben nur im Audit erhalten.` : ""}</div>`;
        return;
    }
    const scoped = Boolean(ccProject());
    container.innerHTML = items.map(item => {
        const actions = scoped && (item.status === "new" || item.status === "deferred") ? `
            <div class="cc-inline-actions">
                <button class="btn btn-primary btn-xs" onclick="dispositionRecommendation('${item.id}', 'accepted')" data-cc-mutation>Akzeptieren</button>
                ${item.status === "new" ? `<button class="btn btn-secondary btn-xs" onclick="dispositionRecommendation('${item.id}', 'deferred')" data-cc-mutation>Später</button>` : ""}
                <button class="btn btn-ghost btn-xs" onclick="dispositionRecommendation('${item.id}', 'rejected')" data-cc-mutation>Entfernen</button>
            </div>` : scoped && item.status === "accepted" ? `
            <div class="cc-inline-actions"><button class="btn btn-secondary btn-xs" onclick="openCampaignModal('${item.id}')" data-cc-mutation>Campaign daraus planen</button></div>` : "";
        return `<article class="cc-recommendation-item">
            <div class="cc-item-meta"><code>${escapeHTML(item.id)}</code>${ccBadge(item.status)}${ccBadge(item.risk_level, "risk")}</div>
            <h3>${escapeHTML(item.title)}</h3>
            <p>${escapeHTML(item.summary)}</p>
            ${item.evidence ? `<details><summary>Belege</summary><div class="cc-evidence">${escapeHTML(item.evidence)}</div></details>` : ""}
            ${actions}
        </article>`;
    }).join("");
}

function ccCandidateDependencyState(campaign, candidate) {
    const dependencyIds = Array.isArray(candidate?.depends_on)
        ? candidate.depends_on.map(String)
        : [];
    if (!dependencyIds.length) {
        return {complete: true, text: "Keine Vorgänger", unresolved: []};
    }

    const candidatesById = new Map(
        (campaign?.pr_candidates || []).map(item => [String(item.id), item]),
    );
    const dependencies = dependencyIds.map(id => {
        const dependency = candidatesById.get(id);
        return {
            id,
            title: String(dependency?.title || id),
            status: String(dependency?.status || "missing"),
        };
    });
    const unresolved = dependencies.filter(
        item => !CC_FINISHED_CANDIDATE_STATUSES.has(item.status),
    );
    const formatDependency = item =>
        `${item.title} (${CC_LABELS[item.status] || item.status})`;
    if (unresolved.length) {
        return {
            complete: false,
            text: `Wartet auf: ${unresolved.map(formatDependency).join(", ")}`,
            unresolved,
        };
    }
    return {
        complete: true,
        text: `Vorgänger abgeschlossen: ${dependencies.map(formatDependency).join(", ")}`,
        unresolved: [],
    };
}

function ccCandidateActivationState(campaign, candidate) {
    const dependencyState = ccCandidateDependencyState(campaign, candidate);
    if (campaign?.status !== "approved") {
        return {allowed: false, reason: "Zuerst muss der aktuelle Plan freigegeben werden.", dependencyState};
    }
    if (candidate?.status !== "ready") {
        return {allowed: false, reason: "Dieser PR-Slice ist nicht im Status „Bereit“.", dependencyState};
    }
    if (!candidate?.base_sha) {
        return {allowed: false, reason: "Der PR-Slice besitzt keinen freigabefähigen Basis-SHA.", dependencyState};
    }
    if (!dependencyState.complete) {
        return {
            allowed: false,
            reason: `Noch nicht aktivierbar. ${dependencyState.text}`,
            dependencyState,
        };
    }
    return {allowed: true, reason: "", dependencyState};
}

function renderControlCampaigns() {
    const container = document.getElementById("cc-campaign-list");
    const campaigns = controlCenterState.campaigns || [];
    if (!campaigns.length) {
        container.innerHTML = `<div class="cc-empty">Eine Campaign hält Ziel, Baseline, Planversion und kleine PR-Slices zusammen.</div>`;
        return;
    }
    const scoped = Boolean(ccProject());
    container.innerHTML = campaigns.map(campaign => {
        const candidates = campaign.pr_candidates || [];
        const profile = campaign.profile || {};
        const campaignActions = scoped && campaign.status === "draft" ? `
            <button class="btn btn-secondary btn-xs" onclick="openPrCandidateModal('${campaign.id}')" data-cc-mutation>+ PR-Slice</button>
            <button class="btn btn-secondary btn-xs" onclick="openCampaignPlanDocuments('${campaign.id}')" data-cc-mutation>Plan-Dokumente</button>
            <button class="btn btn-secondary btn-xs" onclick="inspectCampaignPlan('${campaign.id}')">Plan prüfen</button>
            <button class="btn btn-primary btn-xs" onclick="approveCampaign('${campaign.id}')" data-cc-mutation ${!candidates.length || !campaign.base_sha ? "disabled" : ""}>Plan v${campaign.version} freigeben</button>
        ` : scoped && ["approved", "active"].includes(campaign.status) && ["campaign_wave", "autopilot"].includes(profile.activation_policy) ? `
            <button class="btn btn-primary btn-xs" onclick="activateCampaignWave('${campaign.id}')" data-cc-mutation data-cc-allowed-modes="campaign autopilot" data-cc-requires-running>Nächste sichere Wave</button>
        ` : "";
        const candidateHtml = candidates.length ? candidates.map(candidate => {
            const activationState = ccCandidateActivationState(campaign, candidate);
            const dependencyState = activationState.dependencyState;
            const candidateDomId = `cc-candidate-${candidate.id}`;
            const showActivation = campaign.status === "approved" && candidate.status === "ready";
            const activeWorkOrder = candidate.work_order?.status === "approved"
                ? candidate.work_order
                : null;
            const canWithdraw = activeWorkOrder
                && candidate.task?.status === "queued"
                && Number(candidate.task?.attempt || 0) === 0
                && !candidate.task?.started_at
                && !candidate.task?.lease_owner
                && !candidate.task?.current_sha
                && !candidate.task?.worktree_path
                && !candidate.task?.antigravity_chat_id
                && !candidate.task?.issue_number
                && !candidate.task?.pr_number;
            const activationButton = showActivation ? `
                <button
                    id="${candidateDomId}-activate"
                    class="btn btn-primary btn-xs"
                    onclick="activatePrCandidate('${candidate.id}')"
                    data-cc-action="activate-candidate"
                    data-cc-candidate-id="${escapeHTML(candidate.id)}"
                    data-cc-mutation
                    data-cc-allowed-modes="guided"
                    data-cc-requires-running
                    aria-describedby="${candidateDomId}-dependencies${activationState.allowed ? "" : ` ${candidateDomId}-activation-reason`}"
                    ${activationState.allowed ? "" : `disabled aria-disabled="true" title="${escapeHTML(activationState.reason)}"`}>
                    ${activationState.allowed ? "Work Order freigeben" : "Wartet auf Vorgänger"}
                </button>
                ${activationState.allowed ? "" : `<small id="${candidateDomId}-activation-reason" class="cc-candidate-block-reason">${escapeHTML(activationState.reason)}</small>`}
            ` : "";
            return `<article
                id="${candidateDomId}"
                class="cc-candidate${dependencyState.complete ? "" : " is-dependency-blocked"}"
                data-cc-candidate-id="${escapeHTML(candidate.id)}"
                data-cc-dependency-state="${dependencyState.complete ? "ready" : "blocked"}">
                <div class="cc-candidate-order">${escapeHTML(candidate.id)}</div>
                <div class="cc-candidate-body">
                    <div class="cc-item-meta">${ccBadge(candidate.status)}${ccBadge(candidate.risk_level, "risk")}<span>Wave ${candidate.contract?.wave || "—"}</span><span>${candidate.acceptance_criteria.length} Kriterien</span></div>
                    <h4>${escapeHTML(candidate.title)}</h4>
                    <p>${escapeHTML(candidate.scope)}</p>
                    <small id="${candidateDomId}-dependencies" class="cc-candidate-dependency${dependencyState.complete ? "" : " is-blocked"}">${escapeHTML(dependencyState.text)}</small>
                </div>
                <div class="cc-candidate-action" data-cc-candidate-action-for="${escapeHTML(candidate.id)}">
                    ${activeWorkOrder ? `
                        <span class="cc-approved-stamp">✓ ${escapeHTML(activeWorkOrder.id)}<small>${ccShortSha(activeWorkOrder.approval_sha)}</small></span>
                        ${canWithdraw ? `<button class="btn btn-secondary btn-xs" onclick="cancelUnstartedWorkOrder('${activeWorkOrder.id}', '${candidate.id}')" data-cc-mutation>Zurücknehmen</button>` : ""}
                    ` : `
                        ${candidate.work_order?.status === "cancelled" ? `<small class="cc-candidate-block-reason">Vor Ausführung zurückgenommen</small>` : ""}
                        ${activationButton}
                    `}
                </div>
            </article>`;
        }).join("") : `<div class="cc-empty cc-empty-compact">Noch kein überprüfbarer PR-Slice.</div>`;
        return `<article class="cc-campaign">
            <header class="cc-campaign-header">
                <div>
                    <div class="cc-item-meta"><code>${escapeHTML(campaign.id)}</code>${ccBadge(campaign.status)}${ccBadge(campaign.risk_level, "risk")}<span>Plan v${campaign.version}</span></div>
                    <h3>${escapeHTML(campaign.title)}</h3>
                </div>
                <div class="cc-inline-actions">${campaignActions}</div>
            </header>
            <p class="cc-campaign-goal">${escapeHTML(campaign.goal)}</p>
            <div class="cc-baseline"><span>Baseline</span><code>${ccShortSha(campaign.base_sha)}</code>${campaign.approved_sha ? `<span>freigegeben von ${escapeHTML(campaign.approved_by)}</span>` : ""}</div>
            <div class="cc-plan-strip">
                <span>Planung <strong>${escapeHTML(profile.planning_depth || "compact")}</strong></span>
                <span>Limit <strong>${Number(profile.requested_max_candidates || 5)} PRs</strong></span>
                <span>Aktivierung <strong>${escapeHTML(profile.activation_policy || "per_candidate")}</strong></span>
                <span>Readiness <strong>${Math.round(Number(profile.readiness_score || 0))}%</strong></span>
                <span>Fragen <strong>${(campaign.questions || []).filter(item => !["answered", "grounded", "resolved", "deferred", "assumption-accepted", "discovery-assigned"].includes(item.status)).length} offen</strong></span>
            </div>
            <div class="cc-candidate-list">${candidateHtml}</div>
        </article>`;
    }).join("");
}

function ccTaskContext(taskId) {
    for (const campaign of controlCenterState?.campaigns || []) {
        for (const candidate of campaign.pr_candidates || []) {
            if (candidate.task?.id === taskId) return { campaign, candidate, task: candidate.task };
        }
    }
    const task = (controlCenterState?.tasks || []).find(item => item.id === taskId);
    return { campaign: null, candidate: null, task };
}

function ccFocusedTask() {
    const tasks = controlCenterState?.tasks || [];
    if (!tasks.length) return null;
    const requested = new URLSearchParams(window.location.search).get("review");
    if (requested) {
        const selected = tasks.find(item => String(item.id) === requested);
        if (selected) return selected;
    }
    return ccNextActiveTask() || tasks[0];
}

function ccNextActiveTask(excludeTaskId = "") {
    const tasks = controlCenterState?.tasks || [];
    const priority = [
        "waiting_human",
        "waiting_review",
        "failed",
        "paused",
        "repair",
        "waiting_ci",
        "running",
        "leased",
        "queued",
    ];
    for (const status of priority) {
        const selected = tasks.find(item => item.status === status && String(item.id) !== String(excludeTaskId));
        if (selected) return selected;
    }
    return null;
}

function openControlTaskReview(taskId) {
    const url = new URL(window.location.href);
    url.searchParams.set("review", String(taskId));
    window.history.replaceState({}, "", url);
    renderControlFocus();
    applyControlCenterInteractivity();
}

function ccFocusWorkflowIndex(task, candidate) {
    if (task.status === "completed") return 5;
    const approvals = (candidate?.approvals || []).filter(
        item => !item.revoked_at && item.decision === "approved" && item.sha === task.current_sha,
    );
    if (approvals.some(item => item.approval_type === "merge")) return 4;
    if (approvals.some(item => item.approval_type === "human_test")) return 3;
    if (["waiting_review", "waiting_human"].includes(task.status)) return 2;
    return task.status === "queued" ? 0 : 1;
}

function renderHumanWorkflow(task, candidate) {
    const container = document.getElementById("cc-human-workflow");
    if (!container) return;
    const labels = ["1 · Plan", "2 · Agent", "3 · Lokal testen", "4 · Freigeben", "5 · Merge"];
    const current = ccFocusWorkflowIndex(task, candidate);
    container.innerHTML = labels.map((label, index) => {
        const className = index < current
            ? "is-done"
            : index === current && current < labels.length
                ? "is-active"
                : "";
        return `<span class="${className}">${label}</span>`;
    }).join("");
}

function ccTaskActivityCopy(task, pack) {
    const status = String(task.status || "queued");
    if (task.agent_gate) return {
        title: "Anti-Gravity wartet auf deine Entscheidung",
        detail: task.agent_gate.consequence,
        ready: true,
    };
    if (status === "queued") return {
        title: "Arbeitsauftrag ist eingeplant",
        detail: "Ein freier Anti-Gravity-Worker übernimmt ihn automatisch.",
        ready: false,
    };
    if (["leased", "running", "repair"].includes(status)) return {
        title: "Anti-Gravity arbeitet am Code",
        detail: task.antigravity_chat_id
            ? `Worker-Chat ${task.antigravity_chat_id} · Änderungen entstehen im isolierten PR-Ordner.`
            : "Workspace und Worker werden vorbereitet.",
        ready: false,
    };
    if (status === "waiting_ci") return {
        title: "GitHub prüft den Pull Request",
        detail: "Automatische Tests laufen. Der Status aktualisiert sich live.",
        ready: false,
    };
    if (["waiting_review", "waiting_human"].includes(status)) return {
        title: pack?.status === "ready_for_human"
            ? "Bereit für deinen lokalen Test"
            : "Automatische Checks sind fertig – Nachweise prüfen",
        detail: "Starte unten die lokale Website. Melde einen Fehler oder bestätige die sichtbaren Prüfpunkte.",
        ready: true,
    };
    if (status === "completed") return {
        title: "Pull Request ist abgeschlossen",
        detail: task.merged_sha
            ? `Der geprüfte Code wurde als ${String(task.merged_sha).slice(0, 10)} gemergt.`
            : "Der Arbeitsauftrag ist abgeschlossen.",
        ready: true,
    };
    if (status === "failed") return {
        title: "Task benötigt Reparatur",
        detail: task.last_error || "Öffne die technischen Details für den letzten Fehler.",
        ready: true,
    };
    return {
        title: CC_LABELS[status] || status,
        detail: task.last_error || "Der Status wird live aktualisiert.",
        ready: false,
    };
}

function ccFocusPreviewHtml(task) {
    const preview = controlTaskPreviews.get(String(task.id));
    const active = Boolean(preview?.active && preview?.url);
    const status = preview?.checking
        ? "Preview-Status wird geprüft…"
        : active
            ? "Lokale Website läuft"
            : preview?.error
                ? preview.error
                : "Noch nicht gestartet";
    const url = active ? String(preview.url) : "http://127.0.0.1 · Port wird automatisch gewählt";
    return `<div id="cc-focus-preview" class="cc-preview-box ${active ? "is-running" : ""}">
        <span class="cc-preview-status">${escapeHTML(status)}</span>
        <span class="cc-preview-url">${escapeHTML(url)}</span>
        <small>${active
            ? `Statischer Server · ${escapeHTML(preview.path || task.worktree_path || "")}`
            : "Nur lokal erreichbar; Deployment-Rechte sind dafür nicht nötig."}</small>
        <div class="cc-focus-actions">
            ${active
                ? `<a class="btn btn-primary btn-xs" href="${escapeHTML(preview.url)}" target="_blank" rel="noopener">Website öffnen ↗</a>
                   <button class="btn btn-secondary btn-xs" type="button" onclick="stopControlTaskPreview('${task.id}')">Preview stoppen</button>`
                : `<button class="btn btn-primary btn-xs" type="button" onclick="startControlTaskPreview('${task.id}')" ${preview?.checking ? "disabled" : ""}>Website lokal starten</button>`}
            <button class="btn btn-secondary btn-xs" type="button" onclick="openControlTaskIde('${task.id}')">Dateien in Web‑IDE</button>
        </div>
    </div>`;
}

function ccFocusNextAction(task, candidate, pack, missing) {
    const activeApprovals = (candidate?.approvals || []).filter(
        item => !item.revoked_at && item.decision === "approved" && item.sha === task.current_sha,
    );
    const approvalTypes = new Set(activeApprovals.map(item => item.approval_type));
    if (["leased", "running", "repair", "waiting_ci", "queued"].includes(task.status)) {
        return ["Warten – Anti-Gravity arbeitet", "Du kannst den Task live verfolgen; neue Schritte erscheinen automatisch."];
    }
    if (task.status === "failed") {
        return ["Fehler prüfen", "Öffne den Anti-Gravity-Chat oder die technischen Details und starte danach denselben Task kontrolliert neu."];
    }
    if (missing.length) {
        return ["Website testen und offene Punkte bestätigen", `${missing.length} Nachweise fehlen noch. Bestätige nur, was du wirklich geprüft hast.`];
    }
    if (!approvalTypes.has("human_test") && pack.status === "ready_for_human") {
        return ["Lokalen Test freigeben", "Bestätige, dass genau dieser Code-Stand bei dir funktioniert."];
    }
    if (approvalTypes.has("human_test") && !approvalTypes.has("merge")) {
        return ["Merge freigeben", "Damit erlaubst du den Merge nur für den bereits geprüften Commit."];
    }
    if (approvalTypes.has("merge") && task.status !== "completed") {
        return ["Pull Request mergen", "Der Hub prüft vor dem Merge erneut Commit, CI, Findings und Freigaben."];
    }
    return ["Abgeschlossen", "Dieser Pull Request benötigt keine weitere Aktion."];
}

function renderControlFocus() {
    const container = document.getElementById("cc-focus-task");
    if (!container) return;
    const task = ccFocusedTask();
    if (!task) {
        document.getElementById("cc-focus-heading").textContent = "Bereit für ein neues Vorhaben";
        container.innerHTML = `<div class="cc-empty"><span>✓</span> Kein PR wartet auf Arbeit oder Prüfung. Starte oben einen Wunsch oder öffne die Systemdetails.</div>`;
        return;
    }

    const {candidate} = ccTaskContext(task.id);
    const pack = candidate?.evidence_pack || {};
    const testPack = pack.test_pack || {};
    const missing = Array.isArray(testPack.missing) ? testPack.missing : [];
    const activity = ccTaskActivityCopy(task, pack);
    const latestCheckpoint = (controlCenterState?.checkpoints || []).find(
        item => String(item.entity_id) === String(task.id),
    );
    const path = String(task.worktree_path || ccProject()?.path || "Noch nicht angelegt");
    const checksByKey = new Map([
        ...(testPack.acceptance_criteria || []),
        ...(testPack.required_checks || []),
        ...(testPack.manual_tests || []),
    ].map(item => [String(item.key), item]));
    const manualKeys = missing.filter(key => key.startsWith("acceptance:") || key.startsWith("manual:"));
    const activeApprovals = (candidate?.approvals || []).filter(
        item => !item.revoked_at && item.decision === "approved" && item.sha === task.current_sha,
    );
    const approvalTypes = new Set(activeApprovals.map(item => item.approval_type));
    const taskActions = [];
    const nextActiveTask = task.status === "completed" ? ccNextActiveTask(task.id) : null;
    if (task.status !== "completed" && task.current_sha) {
        taskActions.push(`<button class="btn btn-secondary btn-xs" type="button" onclick="openTaskFindingModal('${task.id}')">Problem melden</button>`);
        taskActions.push(`<button class="btn btn-secondary btn-xs" type="button" onclick="evaluateTaskEvidence('${task.id}')" data-cc-mutation>Prüfstatus aktualisieren</button>`);
    }
    if (task.status !== "completed" && task.pr_number) {
        taskActions.push(`<button class="btn btn-secondary btn-xs" type="button" onclick="syncControlTask('${task.id}')" data-cc-mutation>GitHub neu laden</button>`);
    }
    if (pack.status === "ready_for_human" && !approvalTypes.has("human_test")) {
        taskActions.push(`<button class="btn btn-primary btn-xs" type="button" onclick="approveTaskStage('${task.id}', 'human_test')" data-cc-mutation>Lokalen Test freigeben</button>`);
    }
    if (approvalTypes.has("human_test") && !approvalTypes.has("merge")) {
        taskActions.push(`<button class="btn btn-primary btn-xs" type="button" onclick="approveTaskStage('${task.id}', 'merge')" data-cc-mutation>Code für Merge freigeben</button>`);
    }
    if (approvalTypes.has("merge") && task.pr_number && task.status !== "completed") {
        taskActions.push(`<button class="btn btn-danger btn-xs" type="button" onclick="mergeControlTask('${task.id}')" data-cc-mutation>PR #${task.pr_number} mergen</button>`);
    }
    if (nextActiveTask) {
        taskActions.push(`<button class="btn btn-primary btn-xs" type="button" onclick="openControlTaskReview('${nextActiveTask.id}')">Aktiven PR öffnen</button>`);
    }
    const [nextTitle, nextDetail] = ccFocusNextAction(task, candidate, pack, missing);
    document.getElementById("cc-focus-heading").textContent = candidate?.title || `Task ${task.id}`;
    renderHumanWorkflow(task, candidate);
    container.innerHTML = `<article class="cc-focus-card">
        <div class="cc-focus-main">
            <div class="cc-focus-title">
                <div>
                    <div class="cc-item-meta">${ccBadge(task.status)}${ccBadge(pack.status || "collecting")}<code>${escapeHTML(task.id)}</code></div>
                    <h3>${escapeHTML(candidate?.title || task.candidate_id || task.id)}</h3>
                    <p>${escapeHTML(candidate?.description || "Isolierter Pull-Request-Arbeitsauftrag")}</p>
                </div>
                <div class="cc-task-links">
                    ${task.pr_url ? `<a class="btn btn-ghost btn-xs" href="${escapeHTML(task.pr_url)}" target="_blank" rel="noopener">GitHub PR #${task.pr_number} ↗</a>` : ""}
                </div>
            </div>
            <div class="cc-activity-line ${activity.ready ? "is-ready" : ""}">
                <span class="cc-activity-orbit" aria-hidden="true"></span>
                <div class="cc-activity-copy"><strong>${escapeHTML(activity.title)}</strong><small>${escapeHTML(latestCheckpoint?.summary || activity.detail)}</small></div>
            </div>
            <div class="cc-focus-paths">
                <div class="cc-focus-path-row"><span>PR-Ordner</span><code title="${escapeHTML(path)}">${escapeHTML(path)}</code><button class="btn btn-ghost btn-xs" type="button" onclick="copyControlValue('${task.id}', 'path')">Kopieren</button></div>
                <div class="cc-focus-path-row"><span>Branch</span><code>${escapeHTML(task.branch_name || "Noch nicht angelegt")}</code><button class="btn btn-ghost btn-xs" type="button" onclick="copyControlValue('${task.id}', 'branch')">Kopieren</button></div>
                <div class="cc-focus-path-row"><span>Code-Stand</span><code title="${escapeHTML(task.current_sha || task.base_sha || "")}">${ccShortSha(task.current_sha || task.base_sha)}</code><button class="cc-help-trigger" type="button" data-cc-help="Das ist der eindeutige Fingerabdruck des Codes. Deine Test- und Merge-Freigabe gilt ausschließlich für diesen Stand." aria-label="Code-Stand erklären">?</button></div>
            </div>
            <div class="cc-next-action"><strong>${escapeHTML(nextTitle)}</strong><span>${escapeHTML(nextDetail)}</span></div>
            <div class="cc-focus-actions">${taskActions.join("")}</div>
        </div>
        <aside class="cc-focus-testing">
            <h4>Website selbst prüfen</h4>
            <p>Der Server verwendet exakt den PR-Ordner oben. So testest du nicht versehentlich den Hauptbranch.</p>
            ${ccFocusPreviewHtml(task)}
            ${manualKeys.length ? `<div class="cc-manual-checks"><strong>Noch selbst zu prüfen</strong>${manualKeys.slice(0, 6).map(key => {
                const item = checksByKey.get(String(key));
                return `<div class="cc-manual-check"><span>${escapeHTML(item?.text || key)}</span><button class="btn btn-ghost btn-xs" type="button" onclick="markTaskEvidence('${task.id}', '${escapeHTML(key)}', '${key.startsWith("manual:") ? "manual_test" : "acceptance"}')" data-cc-mutation>Bestanden</button></div>`;
            }).join("")}</div>` : `<div class="cc-all-checks-passed">✓ Alle manuellen Prüfpunkte sind bestätigt.</div>`}
        </aside>
    </article>`;
    if (!controlTaskPreviews.has(String(task.id))) {
        syncControlTaskPreview(task.id);
    }
}

async function syncControlTaskPreview(taskId) {
    const key = String(taskId);
    if (controlTaskPreviewChecks.has(key)) return;
    controlTaskPreviewChecks.add(key);
    controlTaskPreviews.set(key, {checking: true});
    try {
        const preview = await ccApi(`/api/control-center/tasks/${encodeURIComponent(key)}/preview`);
        controlTaskPreviews.set(key, preview);
    } catch (error) {
        controlTaskPreviews.set(key, {active: false, error: error.message});
    } finally {
        controlTaskPreviewChecks.delete(key);
        if (String(ccFocusedTask()?.id || "") === key) renderControlFocus();
    }
}

async function startControlTaskPreview(taskId) {
    const key = String(taskId);
    controlTaskPreviews.set(key, {checking: true});
    renderControlFocus();
    try {
        const preview = await ccApi(`/api/control-center/tasks/${encodeURIComponent(key)}/preview`, {
            method: "POST",
            key: ccKey(`task-preview-${key}`),
            body: {},
        });
        controlTaskPreviews.set(key, preview);
        ccNotify("success", "Lokale Website gestartet", `${preview.url} verwendet den PR-Ordner.`);
    } catch (error) {
        controlTaskPreviews.set(key, {active: false, error: error.message});
        ccNotify("error", "Preview nicht gestartet", error.message);
    }
    renderControlFocus();
}

async function stopControlTaskPreview(taskId) {
    const key = String(taskId);
    try {
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(key)}/preview/stop`, {
            method: "POST",
            key: ccKey(`task-preview-stop-${key}`),
            body: {},
        });
        controlTaskPreviews.set(key, {active: false, status: "stopped"});
        ccNotify("success", "Preview gestoppt", "Der lokale Port wurde wieder freigegeben.");
    } catch (error) {
        ccNotify("error", "Preview nicht gestoppt", error.message);
    }
    renderControlFocus();
}

function openControlTaskIde(taskId) {
    if (typeof requestWebIde !== "function") {
        ccNotify("error", "Web‑IDE", "Die Web‑IDE-Funktion ist noch nicht geladen.");
        return;
    }
    requestWebIde(
        `/api/control-center/tasks/${encodeURIComponent(taskId)}/ide/open`,
        `PR-Workspace ${taskId}`,
    );
}

async function copyControlValue(taskId, kind) {
    const {task} = ccTaskContext(taskId);
    const value = kind === "branch" ? task?.branch_name : task?.worktree_path;
    if (!value) return;
    try {
        await navigator.clipboard.writeText(String(value));
        ccNotify("success", "Kopiert", kind === "branch" ? "Branch kopiert." : "PR-Ordner kopiert.");
    } catch (_) {
        ccNotify("error", "Nicht kopiert", "Der Browser hat den Zwischenablagezugriff blockiert.");
    }
}

function ccTaskStage(task) {
    const status = String(task?.status || "queued");
    const normalized = status === "leased" || status === "repair" ? "running" : status;
    const exactIndex = CC_TASK_STAGES.findIndex(stage => stage.id === normalized);
    if (exactIndex >= 0) return {index: exactIndex, modifier: ""};

    let inferredIndex = 0;
    if (task?.merged_sha) inferredIndex = 5;
    else if (task?.current_sha && task?.pr_number) inferredIndex = 3;
    else if (task?.pr_number) inferredIndex = 2;
    else if (task?.antigravity_chat_id || task?.branch_name) inferredIndex = 1;
    return {
        index: inferredIndex,
        modifier: ["failed", "paused"].includes(status) ? status : "",
    };
}

function ccTaskProgress(task) {
    const stage = ccTaskStage(task);
    return `<div class="cc-task-progress" role="list" aria-label="Taskfortschritt">
        ${CC_TASK_STAGES.map((item, index) => {
            const classes = [
                "cc-task-progress-step",
                index < stage.index ? "is-done" : "",
                index === stage.index ? "is-active" : "",
                index === stage.index && stage.modifier ? `is-${stage.modifier}` : "",
            ].filter(Boolean).join(" ");
            return `<div class="${classes}" role="listitem" aria-current="${index === stage.index ? "step" : "false"}"><span></span><small>${escapeHTML(item.label)}</small></div>`;
        }).join("")}
    </div>`;
}

function renderControlTasks() {
    const container = document.getElementById("cc-task-list");
    const tasks = controlCenterState.tasks || [];
    if (!tasks.length) {
        container.innerHTML = `<div class="cc-empty">Nach einer Work-Order-Freigabe erscheint hier der komplette Weg bis Evidence, Review und Merge.</div>`;
        return;
    }
    container.innerHTML = tasks.map(task => {
        const { campaign, candidate } = ccTaskContext(task.id);
        const pack = candidate?.evidence_pack || {};
        const allFindings = candidate?.findings || [];
        const findings = allFindings.filter(item => item.status === "open");
        const resolvedFindings = allFindings.filter(item => item.status === "resolved");
        const blocking = findings.filter(item => ["BLOCKER", "REQUIRED"].includes(item.classification));
        const activeApprovals = (candidate?.approvals || []).filter(item => !item.revoked_at && item.decision === "approved");
        const headApprovalTypes = new Set(activeApprovals.filter(item => item.sha === task.current_sha).map(item => item.approval_type));
        const mergeApprovalTypes = new Set(activeApprovals.filter(item => item.sha === task.merged_sha).map(item => item.approval_type));
        const testPack = pack.test_pack || {};
        const missing = testPack.missing || [];
        const acceptanceMissing = missing.filter(item => item.startsWith("acceptance:"));
        const manualMissing = missing.filter(item => item.startsWith("manual:"));
        const actions = [];
        if (task.status === "paused" && task.wake_reason === "protected_path_approval" && task.current_sha) {
            actions.push(`<button class="btn btn-danger btn-xs" onclick="approveTaskStage('${task.id}', 'protected_path')" data-cc-mutation>Geschützte Änderungen freigeben</button>`);
            actions.push(`<button class="btn btn-secondary btn-xs" onclick="rejectProtectedPathForRepair('${task.id}')" data-cc-mutation>Ablehnen &amp; reparieren</button>`);
        }
        if (task.status === "repair" && task.wake_reason === "protected_path_rejected") {
            actions.push(`<button class="btn btn-primary btn-xs" onclick="resumeControlTaskAfterFix('${task.id}')" data-cc-mutation>Repair erneut starten</button>`);
        }
        const resumableSystemFailure = (
            (task.status === "repair" && task.wake_reason === "retry:executor_failure")
            || (
                task.status === "failed"
                && (
                    task.wake_reason === "failed:executor_failure"
                    || (
                        task.wake_reason === "agent_execution"
                        && String(task.last_error || "").startsWith("Executor-Fehler:")
                    )
                )
            )
        );
        if (resumableSystemFailure) {
            actions.push(`<button class="btn btn-primary btn-xs" onclick="resumeControlTaskAfterFix('${task.id}')" data-cc-mutation>Nach Systemfix fortsetzen</button>`);
        }
        if (task.agent_gate && task.antigravity_chat_id) actions.push(`<button class="btn btn-primary btn-xs" onclick="openHubOverviewChat('${task.antigravity_chat_id}')">Anti-Gravity-Chat öffnen</button>`);
        if (task.current_sha) actions.push(`<button class="btn btn-secondary btn-xs" onclick="openTaskFindingModal('${task.id}')">Finding erfassen</button>`);
        if (task.pr_number) actions.push(`<button class="btn btn-secondary btn-xs" onclick="syncControlTask('${task.id}')" data-cc-mutation>GitHub synchronisieren</button>`);
        if (task.current_sha) actions.push(`<button class="btn btn-secondary btn-xs" onclick="evaluateTaskEvidence('${task.id}')" data-cc-mutation>Evidence prüfen</button>`);
        acceptanceMissing.slice(0, 4).forEach(key => actions.push(`<button class="btn btn-ghost btn-xs" onclick="markTaskEvidence('${task.id}', '${key}', 'acceptance')" data-cc-mutation>✓ ${escapeHTML(key)}</button>`));
        manualMissing.slice(0, 4).forEach(key => actions.push(`<button class="btn btn-ghost btn-xs" onclick="markTaskEvidence('${task.id}', '${key}', 'manual_test')" data-cc-mutation>✓ ${escapeHTML(key)}</button>`));
        if (pack.status === "ready_for_human" && !headApprovalTypes.has("human_test")) actions.push(`<button class="btn btn-primary btn-xs" onclick="approveTaskStage('${task.id}', 'human_test')" data-cc-mutation>Human-Test freigeben</button>`);
        if (headApprovalTypes.has("human_test") && !headApprovalTypes.has("merge")) actions.push(`<button class="btn btn-primary btn-xs" onclick="approveTaskStage('${task.id}', 'merge')" data-cc-mutation>Merge freigeben</button>`);
        if (headApprovalTypes.has("merge") && task.pr_number && task.status !== "completed") actions.push(`<button class="btn btn-danger btn-xs" onclick="mergeControlTask('${task.id}')" data-cc-mutation>PR jetzt mergen</button>`);
        if (task.current_sha && task.status !== "completed") actions.push(`<button class="btn btn-secondary btn-xs" onclick="deployControlTask('${task.id}', 'staging')" data-cc-mutation>Staging planen</button>`);
        if (task.status === "completed" && task.merged_sha && !mergeApprovalTypes.has("production")) actions.push(`<button class="btn btn-primary btn-xs" onclick="approveTaskStage('${task.id}', 'production')" data-cc-mutation>Production freigeben</button>`);
        if (task.status === "completed" && task.merged_sha && mergeApprovalTypes.has("production")) actions.push(`<button class="btn btn-danger btn-xs" onclick="deployControlTask('${task.id}', 'production')" data-cc-mutation>Production planen</button>`);
        const taskClasses = [
            "cc-task-card",
            blocking.length ? "is-blocked" : "",
            task.status === "waiting_human" || task.agent_gate ? "is-human" : "",
            task.status === "failed" ? "is-failed" : "",
            task.status === "paused" ? "is-paused" : "",
        ].filter(Boolean).join(" ");
        const findingRows = findings.map(item => `
            <article class="cc-finding-row is-${escapeHTML(String(item.classification || "finding").toLowerCase())}">
                <div class="cc-finding-meta"><code>${escapeHTML(item.id)}</code>${ccBadge(item.classification)}<span>${escapeHTML(item.source)}</span><code title="Finding-SHA ${escapeHTML(item.sha)}">${ccShortSha(item.sha)}</code></div>
                <p>${escapeHTML(item.body)}</p>
                <button type="button" class="btn btn-secondary btn-xs" onclick="resolveControlFinding('${task.id}', '${item.id}')" data-cc-mutation>Mit Begründung auflösen</button>
            </article>
        `).join("");
        return `<article class="${taskClasses}">
            <header class="cc-task-header">
                <div><div class="cc-item-meta"><code>${escapeHTML(task.id)}</code>${ccBadge(task.status)}${ccBadge(pack.status || "collecting")}</div><h3>${escapeHTML(candidate?.title || task.candidate_id)}</h3></div>
                <div class="cc-task-links">${task.issue_url ? `<a class="btn btn-ghost btn-xs" href="${escapeHTML(task.issue_url)}" target="_blank" rel="noopener">Issue #${task.issue_number}</a>` : ""}${task.pr_url ? `<a class="btn btn-ghost btn-xs" href="${escapeHTML(task.pr_url)}" target="_blank" rel="noopener">PR #${task.pr_number}</a>` : ""}</div>
            </header>
            ${ccTaskProgress(task)}
            <div class="cc-task-meta">
                <div><span>Anti-Gravity Chat</span><strong>${escapeHTML(task.antigravity_chat_id || "noch nicht zugewiesen")}</strong></div>
                <div><span>Geprüfter PR-SHA</span><strong>${ccShortSha(task.current_sha || task.base_sha)}</strong></div>
                ${task.merged_sha ? `<div><span>Merge-SHA</span><strong>${ccShortSha(task.merged_sha)}</strong></div>` : ""}
                <div><span>Branch</span><strong>${escapeHTML(task.branch_name)}</strong></div>
                <div><span>Versuch</span><strong>${Number(task.attempt || 0)}</strong></div>
            </div>
            ${task.agent_gate ? `<div class="cc-task-state-message is-paused"><strong>Anti-Gravity wartet auf deine Freigabe</strong><span>${escapeHTML(task.agent_gate.consequence)}</span></div>` : task.last_error ? `<div class="cc-task-state-message is-error"><strong>Letzter Fehler</strong><span>${escapeHTML(task.last_error)}</span></div>` : task.status === "paused" ? `<div class="cc-task-state-message is-paused"><strong>Task pausiert</strong><span>Die bisherige Position bleibt erhalten; neue Schritte starten erst nach einer bewussten Fortsetzung.</span></div>` : ""}
            ${findings.length ? `<div class="cc-task-findings"><div class="cc-findings-summary"><strong>${findings.length} offene Findings · ${blocking.length} blockierend</strong>${resolvedFindings.length ? `<span>${resolvedFindings.length} bereits aufgelöst</span>` : ""}</div>${findingRows}</div>` : resolvedFindings.length ? `<div class="cc-task-findings is-resolved"><strong>${resolvedFindings.length} Findings aufgelöst</strong></div>` : ""}
            <details class="cc-task-evidence"><summary>Test Pack · ${missing.length} Gates offen</summary><div class="cc-evidence-list">
                ${(testPack.acceptance_criteria || []).map(item => `<div class="cc-evidence-row ${missing.includes(item.key) ? "" : "is-passed"}"><span>${escapeHTML(item.text)}</span><strong>${missing.includes(item.key) ? "offen" : "✓"}</strong></div>`).join("")}
                ${(testPack.required_checks || []).map(item => `<div class="cc-evidence-row ${missing.includes(item.key) ? "" : "is-passed"}"><span>${escapeHTML(item.text)}</span><strong>${missing.includes(item.key) ? "wartet" : "✓"}</strong></div>`).join("")}
                ${(testPack.manual_tests || []).map(item => `<div class="cc-evidence-row ${missing.includes(item.key) ? "" : "is-passed"}"><span>${escapeHTML(item.text)}</span><strong>${missing.includes(item.key) ? "manuell prüfen" : "✓"}</strong></div>`).join("")}
            </div></details>
            <div class="cc-task-actions">${actions.join("")}</div>
        </article>`;
    }).join("");
}

function renderControlDeployments() {
    const container = document.getElementById("cc-deployment-list");
    if (!container) return;
    const deployments = controlCenterState.deployments || [];
    if (!deployments.length) {
        container.innerHTML = `<div class="cc-empty">Noch kein Deployment geplant. Preview/Staging und Production bleiben capability- und SHA-gebunden.</div>`;
        return;
    }
    container.innerHTML = deployments.map(deployment => {
        const health = deployment.health || {};
        const logs = deployment.logs || [];
        const actions = [];
        if (deployment.status === "planned") actions.push(`<button class="btn btn-secondary btn-xs" onclick="updateControlDeployment('${deployment.id}', 'running')" data-cc-mutation>Start bestätigen</button>`);
        if (deployment.status === "running") {
            actions.push(`<button class="btn btn-primary btn-xs" onclick="updateControlDeployment('${deployment.id}', 'healthy')" data-cc-mutation>Health grün</button>`);
            actions.push(`<button class="btn btn-danger btn-xs" onclick="updateControlDeployment('${deployment.id}', 'failed')" data-cc-mutation>Fehlgeschlagen</button>`);
        }
        if (["healthy", "failed"].includes(deployment.status) && deployment.previous_stable_sha) actions.push(`<button class="btn btn-danger btn-xs" onclick="rollbackControlDeployment('${deployment.id}')" data-cc-mutation>Rollback</button>`);
        return `<article class="cc-deployment-card">
            <div class="cc-deployment-main">
                <div class="cc-item-meta"><code>${escapeHTML(deployment.id)}</code>${ccBadge(deployment.environment)}${ccBadge(deployment.status)}</div>
                <strong>${ccShortSha(deployment.sha)}</strong>
                <small>${ccDate(deployment.created_at)}${deployment.rollback_of ? ` · Rollback von ${escapeHTML(deployment.rollback_of)}` : ""}</small>
            </div>
            <div class="cc-deployment-health">
                <span>Health</span><strong>${health.ok === true ? "✓ gesund" : health.ok === false ? "✕ fehlerhaft" : "noch offen"}</strong>
                ${logs.length ? `<small>${escapeHTML(String(logs[logs.length - 1]))}</small>` : ""}
            </div>
            <div class="cc-task-actions">${actions.join("")}</div>
        </article>`;
    }).join("");
}

function renderControlCheckpoints() {
    const container = document.getElementById("cc-checkpoint-list");
    const items = controlCenterState.checkpoints || [];
    if (!items.length) {
        container.innerHTML = `<div class="cc-empty">Agentenläufe können ihren Zustand später über die Checkpoint-API dauerhaft übergeben.</div>`;
        return;
    }
    container.innerHTML = items.map(item => `<article class="cc-timeline-item">
        <div class="cc-timeline-dot"></div><div><div class="cc-item-meta"><code>${escapeHTML(item.id)}</code><span>${ccDate(item.created_at)}</span></div><strong>${escapeHTML(item.summary)}</strong><small>${escapeHTML(item.actor)} · ${escapeHTML(item.entity_id)}</small></div>
    </article>`).join("");
}

function renderControlAudit() {
    const container = document.getElementById("cc-audit-list");
    const items = controlCenterState.audit || [];
    if (!items.length) {
        container.innerHTML = `<div class="cc-empty">Jede Freigabe und Statusänderung erscheint hier.</div>`;
        return;
    }
    container.innerHTML = items.map(item => `<article class="cc-timeline-item">
        <div class="cc-timeline-dot"></div><div><div class="cc-item-meta"><span>${ccDate(item.created_at)}</span><code>${escapeHTML(item.entity_id)}</code></div><strong>${escapeHTML(item.action)}</strong><small>${escapeHTML(item.actor)}${item.from_state || item.to_state ? ` · ${escapeHTML(item.from_state || "∅")} → ${escapeHTML(item.to_state || "∅")}` : ""}</small>${item.reason ? `<p>${escapeHTML(item.reason)}</p>` : ""}</div>
    </article>`).join("");
}

function requireControlProject() {
    const project = ccProject();
    if (!project) {
        ccNotify("warning", "Projekt auswählen", "Wähle zuerst links im Dashboard ein importiertes GitHub-Projekt aus.");
        return null;
    }
    return project;
}

function openRecommendationModal() {
    const project = requireControlProject();
    if (!project) return;
    document.getElementById("cc-recommendation-project").textContent = `Repository: ${project.name}`;
    document.getElementById("cc-recommendation-title").value = "";
    document.getElementById("cc-recommendation-summary").value = "";
    document.getElementById("cc-recommendation-evidence").value = "";
    document.getElementById("cc-recommendation-risk").value = "medium";
    openModal("cc-recommendation-modal");
}

async function submitRecommendation(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const project = requireControlProject();
        if (!project) return;
        await ccApi("/api/control-center/recommendations", {
            method: "POST",
            key: ccKey("recommendation"),
            body: {
                project_id: project.id,
                title: document.getElementById("cc-recommendation-title").value,
                summary: document.getElementById("cc-recommendation-summary").value,
                evidence: document.getElementById("cc-recommendation-evidence").value,
                risk_level: document.getElementById("cc-recommendation-risk").value,
            },
        });
        closeModal("cc-recommendation-modal");
        ccNotify("success", "Recommendation gespeichert", "Die Idee ist erfasst, aber noch kein Arbeitsauftrag.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Speichern fehlgeschlagen", error.message); }
    finally { finishSubmission(); }
}

async function dispositionRecommendation(id, disposition) {
    let reason = "";
    if (disposition === "deferred" || disposition === "rejected") {
        const label = disposition === "deferred" ? "zurückstellen" : "aus dem Ideeneingang entfernen";
        const confirmation = await requestControlConfirmation({
            title: `Recommendation ${label}`,
            message: `Diese Recommendation wirklich ${label}?`,
            detail: `Recommendation: ${id}`,
            confirmLabel: disposition === "deferred" ? "Zurückstellen" : "Entfernen",
            reasonLabel: "Audit-Begründung",
            reasonRequired: true,
            hint: "Die Entscheidung und Begründung bleiben im Control Center nachvollziehbar.",
        });
        if (!confirmation) return;
        reason = confirmation.reason;
    }
    try {
        await ccApi(`/api/control-center/recommendations/${encodeURIComponent(id)}/disposition`, {
            method: "POST", key: ccKey(`recommendation-${id}`), body: { disposition, reason },
        });
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Entscheidung fehlgeschlagen", error.message); }
}

function openCampaignModal(recommendationId = "") {
    const project = requireControlProject();
    if (!project) return;
    document.getElementById("cc-campaign-project").textContent = `Repository: ${project.name}`;
    const select = document.getElementById("cc-campaign-recommendation");
    const accepted = (controlCenterState?.recommendations || []).filter(item => item.status === "accepted");
    select.innerHTML = `<option value="">Ohne Verknüpfung</option>${accepted.map(item => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.title)}</option>`).join("")}`;
    select.value = recommendationId;
    document.getElementById("cc-campaign-title").value = accepted.find(item => item.id === recommendationId)?.title || "";
    document.getElementById("cc-campaign-goal").value = "";
    document.getElementById("cc-campaign-non-goals").value = "";
    document.getElementById("cc-campaign-depth").value = "balanced";
    document.getElementById("cc-campaign-max-candidates").value = "12";
    document.getElementById("cc-campaign-activation").value = "per_candidate";
    document.getElementById("cc-campaign-pivotal-fork").value = "";
    document.getElementById("cc-campaign-success-metrics").value = "";
    document.getElementById("cc-campaign-acceptance-matrix").value = "";
    document.getElementById("cc-campaign-rollout").value = "";
    document.getElementById("cc-campaign-rollback").value = "Revert the merge commit and restore the last verified stable SHA.";
    document.getElementById("cc-campaign-risk").value = "medium";
    openModal("cc-campaign-modal");
}

function syncCampaignCandidateLimit() {
    const limits = { compact: 5, balanced: 12, deep: 30, exhaustive: 100 };
    const depth = document.getElementById("cc-campaign-depth").value;
    document.getElementById("cc-campaign-max-candidates").value = limits[depth] || 12;
}

function syncWishCandidateLimit() {
    const limits = { compact: 5, balanced: 12, deep: 30, exhaustive: 100 };
    const depth = document.getElementById("cc-wish-plan-depth").value;
    document.getElementById("cc-wish-plan-limit").value = limits[depth] || 12;
}

function openWishPlanModal() {
    const project = requireControlProject();
    if (!project) return;
    document.getElementById("cc-wish-plan-project").textContent = `Repository: ${project.name}`;
    document.getElementById("cc-wish-plan-text").value = "";
    document.getElementById("cc-wish-plan-depth").value = "balanced";
    document.getElementById("cc-wish-plan-limit").value = "12";
    document.getElementById("cc-wish-plan-activation").value = "per_candidate";
    document.getElementById("cc-wish-plan-constraints").value = "Production remains a separate human approval.";
    openModal("cc-wish-plan-modal");
}

function replanPlanningJob(jobId) {
    const job = (controlCenterState?.planning_jobs || []).find(
        item => item.id === jobId,
    );
    openWishPlanModal();
    if (!job) return;
    document.getElementById("cc-wish-plan-text").value = job.wish || "";
    document.getElementById("cc-wish-plan-depth").value =
        job.planning_depth || "balanced";
    document.getElementById("cc-wish-plan-limit").value =
        Number(job.max_candidates || 12);
    document.getElementById("cc-wish-plan-activation").value =
        job.activation_policy || "per_candidate";
    document.getElementById("cc-wish-plan-constraints").value =
        (job.constraints || []).join("\n");
}

async function submitWishPlan(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const project = requireControlProject();
        if (!project) return;
        await ccApi("/api/control-center/planning-jobs", {
            method: "POST",
            key: ccKey(`planning-job-${project.id}`),
            body: {
                project_id: project.id,
                wish: document.getElementById("cc-wish-plan-text").value,
                planning_depth: document.getElementById("cc-wish-plan-depth").value,
                max_candidates: Number(document.getElementById("cc-wish-plan-limit").value),
                activation_policy: document.getElementById("cc-wish-plan-activation").value,
                constraints: ccLines("cc-wish-plan-constraints"),
            },
        });
        closeModal("cc-wish-plan-modal");
        ccNotify("success", "Read-only Planung eingeplant", "Ein begrenzter Anti-Gravity Worker analysiert das Repository. Es entstehen noch keine PRs.");
        await tickControlExecutor();
    } catch (error) { ccNotify("error", "Planung nicht gestartet", error.message); }
    finally { finishSubmission(); }
}

async function retryPlanningJob(jobId) {
    try {
        await ccApi(`/api/control-center/planning-jobs/${encodeURIComponent(jobId)}/retry`, {
            method: "POST",
            key: ccKey(`planning-retry-${jobId}`),
            body: {},
        });
        await tickControlExecutor();
    } catch (error) { ccNotify("error", "Planning-Retry", error.message); }
}

function ccLines(id) {
    return document.getElementById(id).value
        .split("\n")
        .map(item => item.trim())
        .filter(Boolean);
}

async function submitCampaign(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const project = requireControlProject();
        if (!project) return;
        await ccApi("/api/control-center/campaigns", {
            method: "POST", key: ccKey("campaign"), body: {
                project_id: project.id,
                recommendation_id: document.getElementById("cc-campaign-recommendation").value || null,
                title: document.getElementById("cc-campaign-title").value,
                goal: document.getElementById("cc-campaign-goal").value,
                non_goals: document.getElementById("cc-campaign-non-goals").value,
                risk_level: document.getElementById("cc-campaign-risk").value,
                planning_depth: document.getElementById("cc-campaign-depth").value,
                max_candidates: Number(document.getElementById("cc-campaign-max-candidates").value),
                activation_policy: document.getElementById("cc-campaign-activation").value,
                pivotal_fork: document.getElementById("cc-campaign-pivotal-fork").value,
                success_metrics: ccLines("cc-campaign-success-metrics"),
                acceptance_matrix: ccLines("cc-campaign-acceptance-matrix"),
                rollout_plan: document.getElementById("cc-campaign-rollout").value,
                rollback_plan: document.getElementById("cc-campaign-rollback").value,
            },
        });
        closeModal("cc-campaign-modal");
        ccNotify("success", "Campaign angelegt", "Ergänze jetzt kleine PR-Slices, bevor du Plan v1 freigibst.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Campaign fehlgeschlagen", error.message); }
    finally { finishSubmission(); }
}

function openPrCandidateModal(campaignId) {
    const campaign = (controlCenterState?.campaigns || []).find(item => item.id === campaignId);
    if (!campaign) return;
    document.getElementById("cc-candidate-campaign-id").value = campaignId;
    document.getElementById("cc-candidate-campaign-label").textContent = `${campaign.title} · Plan v${campaign.version}`;
    document.getElementById("cc-candidate-title").value = "";
    document.getElementById("cc-candidate-scope").value = "";
    document.getElementById("cc-candidate-criteria").value = "";
    document.getElementById("cc-candidate-checks").value = "unit";
    document.getElementById("cc-candidate-manual-tests").value = "";
    document.getElementById("cc-candidate-dod").value = "All acceptance criteria and required checks are proven for the exact final SHA.";
    document.getElementById("cc-candidate-non-goals").value = "";
    document.getElementById("cc-candidate-risk").value = "medium";
    document.getElementById("cc-candidate-priority").value = "100";
    document.getElementById("cc-candidate-dependencies").innerHTML = (campaign.pr_candidates || []).map(item => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.title)} · ${escapeHTML(item.id)}</option>`).join("");
    openModal("cc-candidate-modal");
}

async function submitPrCandidate(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const campaignId = document.getElementById("cc-candidate-campaign-id").value;
        const dependencySelect = document.getElementById("cc-candidate-dependencies");
        const criteria = document.getElementById("cc-candidate-criteria").value.split("\n").map(item => item.trim()).filter(Boolean);
        await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/pr-candidates`, {
            method: "POST", key: ccKey(`candidate-${campaignId}`), body: {
                title: document.getElementById("cc-candidate-title").value,
                scope: document.getElementById("cc-candidate-scope").value,
                acceptance_criteria: criteria,
                required_checks: ccLines("cc-candidate-checks"),
                manual_tests: ccLines("cc-candidate-manual-tests"),
                definition_of_done: document.getElementById("cc-candidate-dod").value,
                non_goals: document.getElementById("cc-candidate-non-goals").value,
                risk_level: document.getElementById("cc-candidate-risk").value,
                priority: Number(document.getElementById("cc-candidate-priority").value),
                depends_on: Array.from(dependencySelect.selectedOptions).map(option => option.value),
            },
        });
        closeModal("cc-candidate-modal");
        ccNotify("success", "PR-Slice gespeichert", "Die Campaign-Version wurde automatisch erhöht.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "PR-Slice fehlgeschlagen", error.message); }
    finally { finishSubmission(); }
}

async function approveCampaign(campaignId) {
    const campaign = (controlCenterState?.campaigns || []).find(item => item.id === campaignId);
    if (!campaign?.base_sha) return;
    let readiness;
    try {
        const result = await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/readiness`);
        readiness = result.readiness;
    } catch (error) {
        ccNotify("error", "Planprüfung fehlgeschlagen", error.message);
        return;
    }
    if (!readiness?.ready || !readiness.plan_signature) {
        ccNotify(
            "warning",
            `Plan noch nicht bereit · ${Math.round(Number(readiness?.score || 0))}%`,
            (readiness?.missing || ["Readiness-Nachweis fehlt"]).join(", "),
        );
        return;
    }
    const confirmation = await requestControlConfirmation({
        title: "Campaign-Plan freigeben",
        message: `Plan v${campaign.version} wird an den exakt angezeigten Plan und Baseline-Commit gebunden.`,
        detail: `Campaign: ${campaignId}\nSHA: ${campaign.base_sha}\nPlan-Signatur v${readiness.plan_signature_version}: ${readiness.plan_signature}`,
        confirmLabel: "Plan freigeben",
        hint: "Jeder PR-Slice benötigt danach weiterhin einen eigenen Arbeitsauftrag.",
        danger: false,
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/approve`, {
            method: "POST", key: ccKey(`approve-${campaignId}`), body: {
                expected_version: campaign.version,
                approval_sha: campaign.base_sha,
                expected_plan_signature: readiness.plan_signature,
                reason: "Plan im Anti-Gravity Hub geprüft und freigegeben.",
            },
        });
        ccNotify("success", "Plan freigegeben", "Die Freigabe ist an Version, Commit-SHA und Plan-Signatur gebunden.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Freigabe fehlgeschlagen", error.message); }
}

async function activatePrCandidate(candidateId) {
    const campaign = (controlCenterState?.campaigns || []).find(item => item.pr_candidates?.some(candidate => candidate.id === candidateId));
    const candidate = campaign?.pr_candidates.find(item => item.id === candidateId);
    const activationState = ccCandidateActivationState(campaign, candidate);
    if (!activationState.allowed) {
        ccNotify("warning", "Work Order gesperrt", activationState.reason);
        return;
    }
    const confirmation = await requestControlConfirmation({
        title: "Arbeitsauftrag freigeben",
        message: "Der Executor darf diesen abgegrenzten PR-Slice bearbeiten.",
        detail: `PR-Slice: ${candidate.id}\nSHA: ${candidate.base_sha}`,
        confirmLabel: "Work Order anlegen",
        hint: "Dies führt weder Merge noch Deployment aus.",
        danger: false,
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/pr-candidates/${encodeURIComponent(candidateId)}/activate`, {
            method: "POST", key: ccKey(`work-order-${candidateId}`), body: {
                approval_sha: candidate.base_sha,
                rationale: "Scope und Akzeptanzkriterien im Hub geprüft.",
            },
        });
        ccNotify("success", "Work Order freigegeben", "Der Arbeitsauftrag ist dauerhaft und SHA-gebunden gespeichert.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Aktivierung fehlgeschlagen", error.message); }
}

async function cancelUnstartedWorkOrder(workOrderId, candidateId) {
    const campaign = (controlCenterState?.campaigns || []).find(item =>
        item.pr_candidates?.some(candidate => candidate.id === candidateId)
    );
    const candidate = campaign?.pr_candidates?.find(item => item.id === candidateId);
    const task = candidate?.task;
    const isUnstarted = candidate?.work_order?.id === workOrderId
        && candidate.work_order.status === "approved"
        && task?.status === "queued"
        && Number(task?.attempt || 0) === 0
        && !task?.started_at
        && !task?.lease_owner
        && !task?.current_sha
        && !task?.worktree_path
        && !task?.antigravity_chat_id
        && !task?.issue_number
        && !task?.pr_number;
    if (!isUnstarted) {
        ccNotify(
            "warning",
            "Rücknahme nicht möglich",
            "Der Arbeitsauftrag wurde bereits vom Executor übernommen.",
        );
        return;
    }
    const confirmation = await requestControlConfirmation({
        title: "Arbeitsauftrag zurücknehmen",
        message: "Der noch nicht gestartete Task wird auditierbar abgebrochen.",
        detail: `Work Order: ${workOrderId}`,
        confirmLabel: "Work Order zurücknehmen",
        reasonLabel: "Grund für die Rücknahme",
        reasonRequired: true,
        hint: "Task und Arbeitsauftrag bleiben im Audit Trail erhalten.",
    });
    if (!confirmation) return;
    const reason = confirmation.reason;
    try {
        await ccApi(
            `/api/control-center/work-orders/${encodeURIComponent(workOrderId)}/cancel`,
            {
                method: "POST",
                key: ccKey(`cancel-${workOrderId}-${Date.now()}`),
                body: {reason},
            },
        );
        ccNotify(
            "success",
            "Work Order zurückgenommen",
            "Task und Arbeitsauftrag bleiben auditierbar; der PR-Slice ist wieder bereit.",
        );
        await loadControlCenter();
    } catch (error) {
        ccNotify("error", "Rücknahme fehlgeschlagen", error.message);
    }
}

async function updateControlPolicy() {
    if (!controlCenterState) return;
    const mode = document.getElementById("cc-mode-select").value;
    try {
        await ccApi("/api/control-center/policy", {
            method: "POST", key: ccKey("policy"), body: {
                mode,
                paused: controlCenterState.policy.paused,
                reason: controlCenterState.policy.pause_reason,
            },
        });
        await loadControlCenter();
    } catch (error) {
        document.getElementById("cc-mode-select").value = controlCenterState.policy.mode;
        ccNotify("error", "Moduswechsel fehlgeschlagen", error.message);
    }
}

function openControlPauseModal() {
    const reasonField = document.getElementById("cc-pause-reason");
    reasonField.value = "";
    openModal("cc-pause-modal");
    window.setTimeout(() => reasonField.focus(), 0);
}

async function setControlPauseState(pause, reason = "") {
    try {
        await ccApi("/api/control-center/policy", {
            method: "POST", key: ccKey("pause"), body: {
                mode: controlCenterState.policy.mode,
                paused: pause,
                reason: String(reason || "").trim(),
            },
        });
        ccNotify(
            "success",
            pause ? "Neue Arbeit pausiert" : "Neue Arbeit fortgesetzt",
            pause
                ? "Neue Planung, Work Orders und Executor-Leases sind gesperrt; laufende Tasks enden kontrolliert."
                : "Neue Planung und Ausführung sind im gewählten Betriebsmodus wieder möglich.",
        );
        await loadControlCenter();
        return true;
    } catch (error) {
        ccNotify("error", "Policy-Änderung fehlgeschlagen", error.message);
        return false;
    }
}

async function toggleControlPause() {
    if (!controlCenterState) return;
    if (!controlCenterState.policy.paused) {
        openControlPauseModal();
        return;
    }
    await setControlPauseState(false);
}

async function submitControlPause(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        const reasonField = document.getElementById("cc-pause-reason");
        const reason = reasonField.value.trim();
        if (!reason) {
            reasonField.setCustomValidity("Bitte gib einen Grund für die Pause an.");
            reasonField.reportValidity();
            return;
        }
        reasonField.setCustomValidity("");
        const saved = await setControlPauseState(true, reason);
        if (saved) closeModal("cc-pause-modal");
    } finally {
        finishSubmission();
    }
}

async function inspectCampaignPlan(campaignId) {
    try {
        const result = await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/readiness`);
        const readiness = result.readiness;
        if (readiness.ready) {
            ccNotify("success", `Plan bereit · ${Math.round(readiness.score)}%`, `Signatur ${readiness.plan_signature.slice(0, 12)} · ${readiness.simulation.max_wave} sichere Waves`);
        } else {
            ccNotify("warning", `Plan noch nicht bereit · ${Math.round(readiness.score)}%`, readiness.missing.join(", "));
        }
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Planprüfung fehlgeschlagen", error.message); }
}

function openCampaignPlanDocuments(campaignId) {
    const campaign = (controlCenterState?.campaigns || []).find(item => item.id === campaignId);
    if (!campaign) return;
    const latest = type => (campaign.artifacts || []).find(item => item.artifact_type === type);
    document.getElementById("cc-plan-docs-campaign-id").value = campaignId;
    document.getElementById("cc-plan-docs-label").textContent = `${campaign.title} · Plan v${campaign.version}`;
    document.getElementById("cc-plan-repository-map").value = latest("repository_map")?.content_text || "";
    document.getElementById("cc-plan-design-document").value = latest("design_document")?.content_text || "";
    document.getElementById("cc-plan-adr").value = latest("adr")?.content_text || "";
    openModal("cc-plan-docs-modal");
}

async function submitCampaignPlanDocuments(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const project = requireControlProject();
        const campaignId = document.getElementById("cc-plan-docs-campaign-id").value;
        const campaign = (controlCenterState?.campaigns || []).find(item => item.id === campaignId);
        if (!project || !campaign) return;
        const simulation = await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/simulation`);
        const documents = [
            {
                artifact_type: "repository_map",
                title: `${campaign.title} Repository Map`,
                content: document.getElementById("cc-plan-repository-map").value,
                status: "current",
            },
            {
                artifact_type: "design_document",
                title: `${campaign.title} Design Document`,
                content: document.getElementById("cc-plan-design-document").value,
                status: "proposed",
            },
            {
                artifact_type: "plan_simulation",
                title: `${campaign.title} Plan Simulation v${campaign.version}`,
                content: `# Plan Simulation\n\n\`\`\`json\n${JSON.stringify(simulation.simulation, null, 2)}\n\`\`\``,
                status: "current",
            },
        ];
        const adr = document.getElementById("cc-plan-adr").value.trim();
        if (adr) documents.push({
            artifact_type: "adr",
            title: `${campaign.title} Architecture Decision`,
            content: adr,
            status: "proposed",
        });
        for (const document of documents) {
            await ccApi("/api/control-center/artifacts", {
                method: "POST",
                key: ccKey(`artifact-${campaignId}-${document.artifact_type}`),
                body: {
                    project_id: project.id,
                    campaign_id: campaignId,
                    materialize: false,
                    ...document,
                },
            });
        }
        closeModal("cc-plan-docs-modal");
        ccNotify("success", "Plan-Dokumente versioniert", `${documents.length} Artefakte und die aktuelle Wave-Simulation wurden gespeichert.`);
        await inspectCampaignPlan(campaignId);
    } catch (error) { ccNotify("error", "Plan-Dokumente", error.message); }
    finally { finishSubmission(); }
}

async function activateCampaignWave(campaignId) {
    const confirmation = await requestControlConfirmation({
        title: "Nächste Campaign-Wave aktivieren",
        message: "Alle aktuell konfliktfreien und freigabefähigen PR-Slices werden als Work Orders angelegt.",
        detail: `Campaign: ${campaignId}`,
        confirmLabel: "Wave aktivieren",
        hint: "Abhängige oder konfliktbehaftete Slices bleiben gesperrt.",
        danger: false,
    });
    if (!confirmation) return;
    try {
        const result = await ccApi(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/activate-wave`, {
            method: "POST",
            key: ccKey(`wave-${campaignId}`),
            body: { actor: "human" },
        });
        ccNotify("success", "Wave aktiviert", `${result.wave.activated.length} Tasks wurden eingeplant.`);
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Wave nicht aktiviert", error.message); }
}

async function tickControlExecutor() {
    try {
        await ccApi("/api/control-center/executor/tick", { method: "POST", body: {} });
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Executor", error.message); }
}

async function syncControlTask(taskId) {
    try {
        ccNotify("info", "GitHub-Sync", "Checks und Reviews werden aktualisiert.");
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(taskId)}/github/sync`, {
            method: "POST",
            key: ccKey(`sync-${taskId}`),
            body: {},
        });
        await loadControlCenter();
    } catch (error) { ccNotify("error", "GitHub-Sync fehlgeschlagen", error.message); }
}

async function evaluateTaskEvidence(taskId) {
    try {
        const result = await ccApi(`/api/control-center/tasks/${encodeURIComponent(taskId)}/evidence/evaluate`, {
            method: "POST",
            key: ccKey(`evidence-evaluate-${taskId}`),
            body: {},
        });
        const missing = result.evidence_pack?.test_pack?.missing || [];
        if (missing.length) {
            ccNotify(
                "info",
                `${missing.length} Prüfpunkte sind noch offen`,
                missing.slice(0, 4).join(" · ") + (missing.length > 4 ? " · …" : ""),
            );
        } else {
            ccNotify("success", "Prüfstatus vollständig", "Der Code-Stand ist bereit für deinen lokalen Human-Test.");
        }
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Evidence-Prüfung", error.message); }
}

async function markTaskEvidence(taskId, criterionKey, kind) {
    const { task } = ccTaskContext(taskId);
    if (!task?.current_sha) return;
    const confirmation = await requestControlConfirmation({
        title: "Manuellen Beleg bestätigen",
        message: `„${criterionKey}“ wurde am exakten Task-Commit geprüft.`,
        detail: `Task: ${taskId}\nSHA: ${task.current_sha}`,
        confirmLabel: "Als bestanden speichern",
        hint: "Der Beleg wird SHA-gebunden im Evidence Pack gespeichert.",
        danger: false,
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(taskId)}/evidence`, {
            method: "POST",
            key: ccKey(`evidence-${taskId}-${criterionKey}`),
            body: {
                kind,
                criterion_key: criterionKey,
                title: criterionKey,
                status: "passed",
                sha: task.current_sha,
                result: "Human verified in Anti-Gravity Hub.",
                actor: "human",
            },
        });
        await evaluateTaskEvidence(taskId);
    } catch (error) { ccNotify("error", "Evidence nicht gespeichert", error.message); }
}

function openTaskFindingModal(taskId) {
    const { task } = ccTaskContext(taskId);
    const targetSha = String(task?.current_sha || "").trim();
    if (!task || !targetSha) {
        ccNotify("warning", "Finding nicht möglich", "Der Task besitzt noch keinen prüfbaren PR-SHA.");
        return;
    }
    controlFindingContext = {taskId, targetSha};
    document.getElementById("cc-finding-task").textContent = taskId;
    document.getElementById("cc-finding-sha").textContent = targetSha;
    document.getElementById("cc-finding-classification").value = "REQUIRED";
    document.getElementById("cc-finding-source").value = "human_review";
    const body = document.getElementById("cc-finding-body");
    body.value = "";
    body.setCustomValidity("");
    openModal("cc-finding-modal");
    window.setTimeout(() => body.focus(), 0);
}

function closeTaskFindingModal() {
    controlFindingContext = null;
    closeModal("cc-finding-modal");
}

async function submitTaskFinding(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        await finishControlDictationForForm(event.currentTarget);
        const context = controlFindingContext;
        const { task } = ccTaskContext(context?.taskId);
        const currentSha = String(task?.current_sha || "").trim();
        if (!context || !currentSha || currentSha !== context.targetSha) {
            closeTaskFindingModal();
            ccNotify(
                "error",
                "Finding abgebrochen",
                "Der Task oder sein SHA hat sich geändert. Bitte den aktuellen Stand erneut prüfen.",
            );
            await loadControlCenter();
            return;
        }
        const source = document.getElementById("cc-finding-source").value.trim();
        const body = document.getElementById("cc-finding-body").value.trim();
        if (body.length < 3) {
            const bodyField = document.getElementById("cc-finding-body");
            bodyField.setCustomValidity("Bitte beschreibe das Finding nachvollziehbar.");
            bodyField.reportValidity();
            return;
        }
        document.getElementById("cc-finding-body").setCustomValidity("");
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(context.taskId)}/findings`, {
            method: "POST",
            key: ccKey(`finding-${context.taskId}-${context.targetSha}-${Date.now()}`),
            body: {
                classification: document.getElementById("cc-finding-classification").value,
                source,
                body,
                sha: context.targetSha,
                actor: "human",
            },
        });
        closeTaskFindingModal();
        ccNotify("success", "Finding gespeichert", "Der Review-Hinweis ist SHA-gebunden und im Audit Trail erfasst.");
        await evaluateTaskEvidence(context.taskId);
    } catch (error) {
        ccNotify("error", "Finding nicht gespeichert", error.message);
    } finally {
        finishSubmission();
    }
}

async function resolveControlFinding(taskId, findingId) {
    const { candidate, task } = ccTaskContext(taskId);
    const finding = (candidate?.findings || []).find(
        item => item.id === findingId && item.status === "open",
    );
    const targetSha = String(task?.current_sha || "").trim();
    if (!finding || !targetSha) {
        ccNotify("warning", "Finding nicht auflösbar", "Finding oder aktueller Task-SHA ist nicht mehr verfügbar.");
        await loadControlCenter();
        return;
    }
    const confirmation = await requestControlConfirmation({
        title: "Review-Finding auflösen",
        message: `${finding.classification}: ${finding.body}`,
        detail: `Finding: ${finding.id}\nFinding-SHA: ${finding.sha}\nAktueller Task-SHA: ${targetSha}`,
        confirmLabel: "Finding auflösen",
        reasonLabel: "Behebung oder begründete Entscheidung",
        reasonRequired: true,
        hint: "Die Auflösung wird im Audit Trail gespeichert; anschließend wird das Evidence Pack neu bewertet.",
        danger: false,
    });
    if (!confirmation) return;

    const latest = ccTaskContext(taskId);
    const latestSha = String(latest.task?.current_sha || "").trim();
    const stillOpen = (latest.candidate?.findings || []).some(
        item => item.id === findingId && item.status === "open",
    );
    if (!stillOpen || latestSha !== targetSha) {
        ccNotify("error", "Auflösung abgebrochen", "Finding oder Task-SHA hat sich inzwischen geändert.");
        await loadControlCenter();
        return;
    }
    try {
        await ccApi(`/api/control-center/findings/${encodeURIComponent(findingId)}/resolve`, {
            method: "POST",
            key: ccKey(`finding-resolve-${findingId}-${targetSha}`),
            body: {resolution: confirmation.reason, actor: "human"},
        });
        ccNotify("success", "Finding aufgelöst", "Die Begründung wurde gespeichert und das Evidence Pack wird neu bewertet.");
        await evaluateTaskEvidence(taskId);
    } catch (error) {
        ccNotify("error", "Finding nicht aufgelöst", error.message);
    }
}

function approveTaskStage(taskId, approvalType) {
    const { task } = ccTaskContext(taskId);
    const targetSha = approvalType === "production" ? task?.merged_sha : task?.current_sha;
    const allowedTypes = new Set(["protected_path", "human_test", "merge", "production"]);
    if (!targetSha || !allowedTypes.has(approvalType)) return;
    const label = approvalType === "protected_path"
        ? "Geschützte Änderungen"
        : approvalType === "human_test"
            ? "Human-Test"
            : approvalType === "production"
                ? "Production"
                : "Merge";
    controlApprovalContext = {taskId, approvalType, targetSha, label};
    document.getElementById("cc-approval-task").textContent = taskId;
    document.getElementById("cc-approval-type").textContent = label;
    document.getElementById("cc-approval-sha").textContent = targetSha;
    document.getElementById("cc-approval-copy").textContent =
        `${label} wird ausschließlich für diesen exakten Code-Stand freigegeben. `
        + "Ändert sich der Commit, verfällt diese Entscheidung automatisch.";
    openModal("cc-approval-modal");
}

async function submitControlApproval(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        const context = controlApprovalContext;
        const { task } = ccTaskContext(context?.taskId);
        const currentTargetSha = context?.approvalType === "production"
            ? String(task?.merged_sha || "").trim()
            : String(task?.current_sha || "").trim();
        if (!context || !currentTargetSha || currentTargetSha !== context.targetSha) {
            closeModal("cc-approval-modal");
            controlApprovalContext = null;
            ccNotify(
                "error",
                "Code-Freigabe abgebrochen",
                "Der Task oder sein Code-Stand hat sich inzwischen geändert. Bitte den aktuellen Stand neu prüfen.",
            );
            await loadControlCenter();
            return;
        }
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(context.taskId)}/approvals`, {
            method: "POST",
            key: ccKey(`approval-${context.taskId}-${context.approvalType}-${context.targetSha}`),
            body: {
                approval_type: context.approvalType,
                sha: context.targetSha,
                decision: "approved",
                actor: "human",
                reason: `${context.label} im Anti-Gravity Hub geprüft.`,
            },
        });
        closeModal("cc-approval-modal");
        controlApprovalContext = null;
        ccNotify(
            "success",
            "Code-Stand verbindlich freigegeben",
            `${context.label} gilt nur für Commit ${context.targetSha.slice(0, 10)}.`,
        );
        await loadControlCenter();
    } catch (error) {
        ccNotify(
            "error",
            `${controlApprovalContext?.label || "SHA"}-Freigabe`,
            error.message,
        );
    } finally {
        finishSubmission();
    }
}

function rejectProtectedPathForRepair(taskId) {
    const { task } = ccTaskContext(taskId);
    const targetSha = String(task?.current_sha || "").trim();
    if (
        !task
        || task.status !== "paused"
        || task.wake_reason !== "protected_path_approval"
        || !targetSha
    ) {
        ccNotify(
            "error",
            "Ablehnung nicht möglich",
            "Dieser Task wartet nicht mehr auf eine Protected-Path-Entscheidung.",
        );
        return;
    }

    protectedPathRejectContext = {taskId, targetSha};
    document.getElementById("cc-protected-reject-task").textContent = taskId;
    document.getElementById("cc-protected-reject-sha").textContent = targetSha;
    const reasonField = document.getElementById("cc-protected-reject-reason");
    reasonField.value = "";
    reasonField.setCustomValidity("");
    openModal("cc-protected-reject-modal");
    window.setTimeout(() => reasonField.focus(), 0);
}

async function submitProtectedPathReject(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        const context = protectedPathRejectContext;
        const reasonField = document.getElementById("cc-protected-reject-reason");
        const reason = reasonField.value.trim();
        if (reason.length < 3) {
            reasonField.setCustomValidity(
                "Bitte gib einen nachvollziehbaren Grund mit mindestens drei Zeichen an.",
            );
            reasonField.reportValidity();
            return;
        }
        reasonField.setCustomValidity("");

        const { task } = ccTaskContext(context?.taskId);
        const currentSha = String(task?.current_sha || "").trim();
        if (
            !context
            || task?.status !== "paused"
            || task?.wake_reason !== "protected_path_approval"
            || currentSha !== context.targetSha
        ) {
            closeModal("cc-protected-reject-modal");
            protectedPathRejectContext = null;
            ccNotify(
                "error",
                "Ablehnung nicht möglich",
                "Der Task oder sein SHA hat sich inzwischen geändert. Bitte den aktuellen Stand neu prüfen.",
            );
            await loadControlCenter();
            return;
        }

        await ccApi(
            `/api/control-center/tasks/${encodeURIComponent(context.taskId)}/protected-path/reject`,
            {
                method: "POST",
                key: ccKey(`protected-reject-${context.taskId}-${context.targetSha}`),
                body: {
                    sha: context.targetSha,
                    actor: "human",
                    reason,
                },
            },
        );
        closeModal("cc-protected-reject-modal");
        protectedPathRejectContext = null;
        ccNotify(
            "success",
            "Geschützte Änderung abgelehnt",
            "Der lokale Commit wurde aus der Branch-Historie gelöst und als Repair eingeplant.",
        );
        await loadControlCenter();
    } catch (error) {
        ccNotify("error", "Ablehnung nicht ausgeführt", error.message);
    } finally {
        finishSubmission();
    }
}

async function resumeControlTaskAfterFix(taskId) {
    const { task } = ccTaskContext(taskId);
    const protectedRepair = Boolean(
        task
        && task.status === "repair"
        && task.wake_reason === "protected_path_rejected"
    );
    const systemRepair = Boolean(
        task
        && (
            (task.status === "repair" && task.wake_reason === "retry:executor_failure")
            || (
                task.status === "failed"
                && (
                    task.wake_reason === "failed:executor_failure"
                    || (
                        task.wake_reason === "agent_execution"
                        && String(task.last_error || "").startsWith("Executor-Fehler:")
                    )
                )
            )
        )
    );
    if (!protectedRepair && !systemRepair) {
        ccNotify(
            "error",
            "Repair nicht startbereit",
            "Der Task wartet nicht auf einen freigegebenen System- oder Protected-Path-Repair.",
        );
        return;
    }
    if (!controlCenterState?.policy?.paused) {
        ccNotify(
            "error",
            "Control Center zuerst pausieren",
            "Der Versuch kann nur unter globaler Pause sicher zurückerstattet werden.",
        );
        return;
    }
    try {
        await ccApi(
            `/api/control-center/tasks/${encodeURIComponent(taskId)}/resume-after-fix`,
            {
                method: "POST",
                key: ccKey(`resume-after-fix-${taskId}`),
                body: {
                    actor: "human",
                    reason: protectedRepair
                        ? "Protected-Path-Commit geprüft; bereinigtes Repair-Overlay erneut freigegeben."
                        : "Hub-Infrastrukturfehler behoben; derselbe Task wird kontrolliert fortgesetzt.",
                },
            },
        );
        ccNotify(
            "success",
            "Repair eingeplant",
            "Ein Versuch wurde zurückerstattet. Der Task startet erst nach dem globalen Fortsetzen.",
        );
        await loadControlCenter();
    } catch (error) {
        ccNotify("error", "Repair nicht eingeplant", error.message);
    }
}

async function mergeControlTask(taskId) {
    const { task } = ccTaskContext(taskId);
    if (!task?.current_sha) return;
    const confirmation = await requestControlConfirmation({
        title: "Pull Request mergen",
        message: `PR #${task.pr_number} wird nur gemergt, wenn GitHub weiterhin den geprüften Head-SHA meldet.`,
        detail: `Task: ${taskId}\nSHA: ${task.current_sha}`,
        confirmLabel: "Exakten PR mergen",
        hint: "CI, Reviews, Evidence und die separate Merge-Freigabe bleiben serverseitige Pflichtgates.",
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(taskId)}/github/merge`, {
            method: "POST",
            key: ccKey(`merge-${taskId}`),
            body: { actor: "human" },
        });
        ccNotify("success", "Pull Request gemergt", "GitHub und Evidence Pack wurden synchron abgeschlossen.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Merge nicht ausgeführt", error.message); }
}

async function deployControlTask(taskId, environment) {
    const { task } = ccTaskContext(taskId);
    const targetSha = task?.status === "completed" && task?.merged_sha
        ? task.merged_sha
        : task?.current_sha;
    if (!targetSha) return;
    const label = environment === "production" ? "Production" : "Staging";
    const confirmation = await requestControlConfirmation({
        title: `${label}-Deployment planen`,
        message: `Das Deployment wird verbindlich an den geprüften ${label}-Commit gebunden.`,
        detail: `Task: ${taskId}\nSHA: ${targetSha}`,
        confirmLabel: `${label} planen`,
        hint: environment === "production"
            ? "Production benötigt zusätzlich eine separate SHA-Freigabe."
            : "Der Deployment-Status wird anschließend explizit bestätigt.",
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/tasks/${encodeURIComponent(taskId)}/deployments`, {
            method: "POST",
            key: ccKey(`deployment-${taskId}-${environment}-${targetSha}`),
            body: {
                environment,
                sha: targetSha,
                actor: "human",
            },
        });
        ccNotify("success", `${label} geplant`, `Deployment ist exakt an ${targetSha.slice(0, 10)} gebunden.`);
        await loadControlCenter();
    } catch (error) { ccNotify("error", `${label}-Deployment`, error.message); }
}

async function updateControlDeployment(deploymentId, status) {
    const health = status === "healthy" ? { ok: true } : status === "failed" ? { ok: false } : {};
    try {
        await ccApi(`/api/control-center/deployments/${encodeURIComponent(deploymentId)}`, {
            method: "PATCH",
            key: ccKey(`deployment-${deploymentId}-${status}`),
            body: {
                status,
                health,
                logs: [`${status} confirmed in Anti-Gravity Hub.`],
                actor: "human",
            },
        });
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Deployment-Status", error.message); }
}

async function rollbackControlDeployment(deploymentId) {
    const confirmation = await requestControlConfirmation({
        title: "Deployment zurückrollen",
        message: "Der vorherige stabile SHA wird als Recovery-Deployment angelegt.",
        detail: `Deployment: ${deploymentId}`,
        confirmLabel: "Rollback starten",
        reasonLabel: "Grund für den Rollback",
        reasonRequired: true,
        hint: "Die Begründung wird dauerhaft im Audit Trail gespeichert.",
    });
    if (!confirmation) return;
    try {
        await ccApi(`/api/control-center/deployments/${encodeURIComponent(deploymentId)}/rollback`, {
            method: "POST",
            key: ccKey(`rollback-${deploymentId}`),
            body: { reason: confirmation.reason, actor: "human" },
        });
        ccNotify("success", "Rollback gestartet", "Der vorherige stabile SHA wurde als Recovery-Deployment angelegt.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Rollback nicht gestartet", error.message); }
}

async function openRepositoryPolicyModal() {
    const project = requireControlProject();
    if (!project) return;
    try {
        const result = await ccApi(`/api/control-center/projects/${encodeURIComponent(project.id)}/policy`);
        const policy = result.policy;
        const githubLabel = project.github_owner && project.github_repo
            ? `${project.github_owner}/${project.github_repo}`
            : "GitHub noch nicht verknüpft";
        document.getElementById("cc-policy-project").innerHTML = `
            <strong>${escapeHTML(project.name)}</strong>
            <span>GitHub: ${escapeHTML(githubLabel)}</span>
            <code title="${escapeHTML(project.path || "")}">${escapeHTML(project.path || "Kein lokaler Pfad")}</code>`;
        document.getElementById("cc-policy-parallel").value = policy.max_parallel_tasks;
        document.getElementById("cc-policy-open-prs").value = policy.max_open_prs;
        document.getElementById("cc-policy-candidates").value = policy.max_candidates;
        document.getElementById("cc-policy-retries").value = policy.max_retry_attempts;
        document.getElementById("cc-policy-no-progress").value = policy.no_progress_limit;
        document.getElementById("cc-cap-merge").checked = Boolean(policy.capability?.merge_pr);
        document.getElementById("cc-cap-staging").checked = Boolean(policy.capability?.deploy_staging);
        document.getElementById("cc-cap-production").checked = Boolean(policy.capability?.deploy_production);
        document.getElementById("cc-cap-rollback").checked = Boolean(policy.capability?.rollback);
        openModal("cc-repository-policy-modal");
    } catch (error) { ccNotify("error", "Repository-Regeln", error.message); }
}

async function submitRepositoryPolicy(event) {
    event.preventDefault();
    const finishSubmission = ccBeginFormSubmission(event.currentTarget);
    if (!finishSubmission) return;
    try {
        const project = requireControlProject();
        if (!project) return;
        await ccApi(`/api/control-center/projects/${encodeURIComponent(project.id)}/policy`, {
            method: "PUT",
            key: ccKey(`repository-policy-${project.id}`),
            body: {
                max_parallel_tasks: Number(document.getElementById("cc-policy-parallel").value),
                max_open_prs: Number(document.getElementById("cc-policy-open-prs").value),
                max_candidates: Number(document.getElementById("cc-policy-candidates").value),
                max_retry_attempts: Number(document.getElementById("cc-policy-retries").value),
                no_progress_limit: Number(document.getElementById("cc-policy-no-progress").value),
                capability: {
                    merge_pr: document.getElementById("cc-cap-merge").checked,
                    deploy_staging: document.getElementById("cc-cap-staging").checked,
                    deploy_production: document.getElementById("cc-cap-production").checked,
                    rollback: document.getElementById("cc-cap-rollback").checked,
                },
                reason: "Repository-Regeln im Anti-Gravity Hub aktualisiert.",
            },
        });
        closeModal("cc-repository-policy-modal");
        ccNotify("success", "Repository-Regeln gespeichert", "Sensible Capabilities bleiben zusätzlich Human-Gate-gebunden.");
        await loadControlCenter();
    } catch (error) { ccNotify("error", "Regeln nicht gespeichert", error.message); }
    finally { finishSubmission(); }
}
