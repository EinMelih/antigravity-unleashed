// State Management
let projects = [];
let issues = [];
let lessons = [];
let currentProjectId = null;
let currentIssueId = null;
let activeRunId = null;
let eventSource = null;
let currentBrowserPath = "";
let githubConfigured = false;
let githubOwner = "";
let projectsBaseDir = "";

const chatWindowsState = {};
let currentMaxZIndex = 1000;
let antigravityConversationType = "all";
const antigravityConversationStatuses = new Set(["running", "complete"]);
let antigravityConversationScope = "active";
let antigravityConversationSearch = "";
let antigravityConversationSearchTimer = null;
let antigravityConversationCatalog = [];
let antigravityActiveAgents = [];
let antigravityWorkerPool = {
    primary: null,
    workers: [],
    capacity: {active: 0, maximum: 4, minimum_warm: 1, queued: 0},
};
let antigravityConversationRefreshTimer = null;
let antigravityConversationLoadInFlight = false;
let antigravityConversationLastSignature = "";
let currentEmbeddedConvoId = null;
let scheduledTasks = [];
let scheduledTasksConnected = false;
let scheduledTaskProjects = [];
let controlPlanePollTimer = null;
let controlPlaneManualLoaded = false;
const pendingControlRequests = new Map();
let hubOverviewRefreshTimer = null;
let hubOverviewLoadInFlight = false;
let hubPrimaryAction = {type: "refresh"};
let hubOverviewState = {
    control: null,
    conversations: null,
    workers: null,
};

const ANTIGRAVITY_THINKING_PHASES = [
    "Kontext wird geladen",
    "Aufgabe wird eingeordnet",
    "Aktionen werden koordiniert",
    "Ergebnis wird geprüft",
    "Antwort wird zusammengesetzt",
    "Checkpoint wird vorbereitet",
];
const ANTIGRAVITY_THINKING_SYMBOLS = ["·", "✢", "✳", "✶", "✻", "✽"];

function createControlRequestId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `agy-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function controlFetch(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
        return fetch(url, options);
    }

    const headers = new Headers(options.headers || {});
    if (!headers.has("Idempotency-Key")) {
        headers.set("Idempotency-Key", createControlRequestId());
    }
    const bodySignature = typeof options.body === "string" ? options.body : "";
    const signature = `${method}|${url}|${bodySignature}`;
    const existing = pendingControlRequests.get(signature);
    if (existing) {
        const response = await existing;
        return response.clone();
    }

    const request = fetch(url, {...options, method, headers});
    pendingControlRequests.set(signature, request);
    const scheduleCleanup = () => {
        window.setTimeout(() => {
            if (pendingControlRequests.get(signature) === request) {
                pendingControlRequests.delete(signature);
            }
        }, 1500);
    };
    request.then(scheduleCleanup, scheduleCleanup);
    const response = await request;
    return response.clone();
}

function getNextZIndex() {
    currentMaxZIndex++;
    return currentMaxZIndex;
}


// Initial Setup
document.addEventListener("DOMContentLoaded", async () => {
    checkGitHubStatus();
    await loadProjects();
    loadLessons();
    requestNotificationPermission();
    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.run-history-wrapper')) {
            const dd = document.getElementById('run-history-dropdown');
            if (dd) dd.classList.remove('open');
        }
    });
    document.getElementById("scheduled-task-name")?.addEventListener("input", updateScheduledTaskIdPreview);
    document.getElementById("scheduled-task-all-projects")?.addEventListener("change", syncScheduledTaskProjectRequirement);
    document.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            openHubCommandPalette();
            return;
        }
        if (event.key === "Escape") {
            closeHubCommandPalette();
            toggleOrchestratorDrawer(false);
        }
    });
    document.addEventListener("visibilitychange", () => {
        const chatsVisible = document.getElementById("chats-tab")?.classList.contains("active");
        const dashboardVisible = document.getElementById("dashboard-tab")?.classList.contains("active");
        if (document.hidden || !chatsVisible) {
            stopConversationAutoRefresh();
        } else {
            startConversationAutoRefresh();
        }
        if (document.hidden || !dashboardVisible) {
            stopHubOverviewRefresh();
        } else {
            loadHubOverview();
            startHubOverviewRefresh();
        }
    });

    // --- Restore full dashboard state upon page reload ---
    // 1. Restore active tab
    const locationParams = new URLSearchParams(window.location.search);
    const requestedTab = locationParams.get("tab");
    const requestedReview = locationParams.get("review");
    const requestedProjectId = locationParams.get("project_id");
    const savedTab = localStorage.getItem('antigravity_active_tab');
    const initialTab = requestedReview
        ? "control-center-tab"
        : requestedTab === "dashboard"
            ? "dashboard-tab"
            : (requestedTab || savedTab);
    if (initialTab) {
        const tabEl = document.getElementById(initialTab);
        const btnEl = document.querySelector(`.nav-btn[onclick*="'${initialTab}'"]`);
        if (tabEl && btnEl) {
            switchTab(initialTab, btnEl);
        }
    }

    // 2. Restore selected project (after projects are loaded)
    const savedProjectId = localStorage.getItem('antigravity_selected_project');
    const savedProject = projects.find(project => Number(project.id) === Number(savedProjectId));
    const requestedProject = requestedProjectId === null
        ? null
        : projects.find(project => String(project.id) === requestedProjectId);
    const restoredProject = requestedProjectId !== null
        ? requestedProject
        : requestedReview
            ? null
            : savedProject;
    if (restoredProject) {
        await selectProject(Number(restoredProject.id));
    } else {
        localStorage.removeItem('antigravity_selected_project');
        renderHubHome();
    }

    // 3. Restore open chat windows
    let openChats = [];
    try {
        openChats = JSON.parse(localStorage.getItem('antigravity_open_chats')) || [];
    } catch(e) {}
    if (initialTab === "chats-tab") {
        const restorable = openChats.filter(
            convoId => convoId !== "new" || restoredProject?.antigravity_linked
        );
        if (window.matchMedia("(max-width: 820px)").matches) {
            const mostRecent = restorable.at(-1);
            if (mostRecent) await openChatInWorkspace(mostRecent);
        } else {
            restorable.forEach(convoId => openChatHistory(convoId));
        }
    }

    // 4. Restore scroll position
    const savedScroll = localStorage.getItem('antigravity_scroll_pos');
    if (savedScroll) {
        setTimeout(() => { window.scrollTo(0, parseInt(savedScroll)); }, 500);
    }

    await loadHubOverview();
    if (document.getElementById("dashboard-tab")?.classList.contains("active")) {
        startHubOverviewRefresh();
    }

    // Save scroll position on scroll (debounced)
    let scrollTimer;
    window.addEventListener('scroll', () => {
        clearTimeout(scrollTimer);
        scrollTimer = setTimeout(() => {
            localStorage.setItem('antigravity_scroll_pos', window.scrollY.toString());
        }, 300);
    });
});

// GitHub Status Check
async function checkGitHubStatus() {
    try {
        const res = await fetch("/api/github/status");
        const data = await res.json();
        githubConfigured = data.valid === true;
        githubOwner = data.login || data.owner || "";
        projectsBaseDir = data.projects_base_dir || "";

        const dot = document.getElementById("gh-status-dot");
        if (dot) {
            dot.className = `gh-dot ${githubConfigured ? 'gh-dot-ok' : 'gh-dot-err'}`;
            const statusLabels = {
                missing: "GitHub ist nicht konfiguriert",
                invalid: "GitHub-Zugangsdaten sind ungültig",
                rate_limited: "GitHub-API-Limit erreicht",
            };
            dot.title = githubConfigured
                ? `Authentifiziert als ${githubOwner}`
                : (statusLabels[data.status] || data.error || "GitHub ist nicht erreichbar");
        }
    } catch (err) {
        console.error("GitHub status check failed:", err);
    }
    renderHubOverview();
}

function scrollDashboardToProjects() {
    const dashboard = document.getElementById("dashboard-tab");
    const workspace = document.querySelector("#dashboard-tab .hub-project-workspace");
    if (!dashboard || !workspace) return;
    dashboard.scrollTop = dashboard.scrollHeight;
    dashboard.focus({preventScroll: true});
}

async function fetchHubOverviewJson(url) {
    const response = await fetch(url, {cache: "no-store"});
    let payload = {};
    try {
        payload = await response.json();
    } catch (error) {}
    if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
}

async function loadHubOverview({showErrors = false} = {}) {
    if (hubOverviewLoadInFlight || !document.getElementById("hub-overview-title")) return;
    hubOverviewLoadInFlight = true;
    try {
        const results = await Promise.allSettled([
            fetchHubOverviewJson("/api/control-center/overview"),
            fetchHubOverviewJson("/api/antigravity/conversations?type=all&status=running,complete,archived&summary_only=1"),
            fetchHubOverviewJson("/api/antigravity/workers"),
        ]);
        if (results[0].status === "fulfilled") hubOverviewState.control = results[0].value;
        if (results[1].status === "fulfilled") hubOverviewState.conversations = results[1].value;
        if (results[2].status === "fulfilled") hubOverviewState.workers = results[2].value;
        renderHubOverview();

        if (showErrors) {
            const failed = results.find(result => result.status === "rejected");
            if (failed) throw failed.reason;
            showToast("success", "Übersicht aktualisiert", "Control Plane und Worker-Zustand sind synchron.");
        }
    } catch (error) {
        if (showErrors) showToast("error", "Übersicht nicht vollständig", error.message);
    } finally {
        hubOverviewLoadInFlight = false;
    }
}

function startHubOverviewRefresh() {
    if (hubOverviewRefreshTimer || document.hidden) return;
    hubOverviewRefreshTimer = window.setInterval(() => loadHubOverview(), 5000);
}

function stopHubOverviewRefresh() {
    if (!hubOverviewRefreshTimer) return;
    window.clearInterval(hubOverviewRefreshTimer);
    hubOverviewRefreshTimer = null;
}

function getHubPrimaryAction() {
    const control = hubOverviewState.control || {};
    const conversations = hubOverviewState.conversations || {};
    const workers = hubOverviewState.workers || {};
    const policy = control.policy || {};
    const attention = control.attention || [];
    const activeAgents = conversations.active_agents || [];
    const unlinkedProject = projects.find(project => !project.antigravity_linked);
    const queued = Number(workers.capacity?.queued || 0);

    if (policy.paused) {
        return {
            type: "control",
            loop: "decide",
            label: "Pause prüfen",
            copy: `Das Control Center ist pausiert${policy.pause_reason ? `: ${policy.pause_reason}` : "."} Neue Work Orders bleiben gesperrt.`,
        };
    }
    if (attention.length) {
        const urgent = attention[0];
        return {
            type: "control",
            loop: "decide",
            label: "Entscheidung öffnen",
            copy: `${attention.length} Entscheidung${attention.length === 1 ? "" : "en"} braucht deine Aufmerksamkeit. Als Nächstes: ${urgent.title}.`,
        };
    }
    if (queued > 0) {
        return {
            type: "chats",
            loop: "act",
            label: "Worker ansehen",
            copy: `${queued} Chat-Request${queued === 1 ? "" : "s"} wartet auf einen freien AG-Worker. Die Queue arbeitet konfliktfrei weiter.`,
        };
    }
    if (activeAgents.length) {
        return {
            type: "chats",
            loop: "act",
            label: "Aktive Chats öffnen",
            copy: `${activeAgents.length} Agent${activeAgents.length === 1 ? "" : "en"} arbeitet gerade. Öffne die Live-Ansicht für Verlauf und Worker-Zuordnung.`,
        };
    }
    if (!projects.length) {
        return {
            type: "add-project",
            loop: "observe",
            label: "Repository hinzufügen",
            copy: "Beginne mit einem GitHub-Repository. Danach kannst du es eindeutig mit einem Anti-Gravity-Projekt verknüpfen.",
        };
    }
    if (unlinkedProject) {
        return {
            type: "link-project",
            projectId: Number(unlinkedProject.id),
            loop: "observe",
            label: "Projekt verknüpfen",
            copy: `${unlinkedProject.github_repo || unlinkedProject.name} ist importiert, aber noch keinem Anti-Gravity-Projekt zugeordnet.`,
        };
    }
    return {
        type: "chats",
        loop: "observe",
        label: "Chats öffnen",
        copy: "Alles ist bereit und aktuell blockiert keine menschliche Entscheidung. Du kannst eine Conversation fortsetzen oder eine neue starten.",
    };
}

function renderHubOverview() {
    const title = document.getElementById("hub-overview-title");
    if (!title) return;
    const control = hubOverviewState.control || {};
    const conversations = hubOverviewState.conversations || {};
    const workers = hubOverviewState.workers || {};
    const summary = control.summary || {};
    const policy = control.policy || {mode: "guided", paused: false};
    const counts = conversations.counts || {};
    const activeAgents = conversations.active_agents || [];
    const attention = control.attention || [];
    const workerItems = Array.isArray(workers.workers) ? workers.workers : [];
    const capacity = workers.capacity || {};
    const linkedProjects = projects.filter(project => project.antigravity_linked).length;

    hubPrimaryAction = getHubPrimaryAction();
    document.getElementById("hub-next-action-copy").textContent = hubPrimaryAction.copy;
    document.getElementById("hub-next-action-button").textContent = hubPrimaryAction.label;
    document.getElementById("hub-policy-label").textContent = policy.paused
        ? `PAUSIERT · ${String(policy.mode || "guided").toUpperCase()}`
        : `${String(policy.mode || "guided").toUpperCase()} CONTROL LOOP`;
    document.getElementById("hub-policy-dot").classList.toggle("is-paused", Boolean(policy.paused));

    document.querySelectorAll(".hub-loop-step").forEach(step => {
        step.classList.toggle("is-active", step.dataset.loopStep === hubPrimaryAction.loop);
    });

    document.getElementById("hub-stat-attention").textContent = String(summary.attention_open ?? attention.length);
    document.getElementById("hub-stat-attention-note").textContent = policy.paused
        ? "System pausiert"
        : attention.length ? "Entscheidungen offen" : "Nichts blockiert";
    document.getElementById("hub-stat-agents").textContent = String(counts.running ?? activeAgents.length);
    document.getElementById("hub-stat-agents-note").textContent = `${counts.complete ?? 0} abgeschlossen · live`;
    document.getElementById("hub-stat-workers").textContent = `${capacity.active ?? workerItems.length}/${capacity.maximum ?? 4}`;
    document.getElementById("hub-stat-workers-note").textContent = capacity.queued
        ? `${capacity.queued} wartet`
        : "Queue frei";
    document.getElementById("hub-stat-projects").textContent = String(projects.length);
    document.getElementById("hub-stat-projects-note").textContent = `${linkedProjects} verknüpft`;

    const attentionContainer = document.getElementById("hub-attention-preview");
    if (attentionContainer) {
        attentionContainer.innerHTML = attention.length
            ? attention.slice(0, 3).map(item => `
                <button class="hub-attention-row urgency-${escapeHTML(item.urgency || "normal")}" onclick="activateHubTab('control-center-tab')">
                    <span class="hub-attention-marker"></span>
                    <span><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.consequence || item.recommendation || "")}</small></span>
                    <span aria-hidden="true">→</span>
                </button>
            `).join("")
            : `<div class="hub-overview-empty is-success"><span>✓</span><div><strong>Keine Entscheidung blockiert</strong><small>Der Guided Control Loop kann ohne menschlichen Eingriff warten.</small></div></div>`;
    }

    const agentContainer = document.getElementById("hub-agent-preview");
    if (agentContainer) {
        const activeRows = activeAgents.slice(0, 3).map(chat => {
            const worker = workerItems.find(item => item.chat_id === chat.convo_id);
            return `
                <button class="hub-agent-row is-working" onclick="openHubOverviewChat('${escapeHTML(chat.convo_id)}')">
                    <span class="antigravity-activity-spinner" aria-hidden="true"></span>
                    <span><strong>${escapeHTML(chat.title || "Aktiver Chat")}</strong><small>${escapeHTML(worker?.window_id || "Worker wird zugeteilt")} · arbeitet</small></span>
                    <span aria-hidden="true">→</span>
                </button>`;
        });
        const idleRows = workerItems
            .filter(worker => !activeAgents.some(chat => chat.convo_id === worker.chat_id))
            .slice(0, Math.max(0, 3 - activeRows.length))
            .map(worker => `
                <div class="hub-agent-row">
                    <span class="hub-worker-dot state-${escapeHTML(worker.state || "idle")}"></span>
                    <span><strong>${escapeHTML(worker.window_id || "AG")}</strong><small>${escapeHTML(antigravityWorkerStateLabel(worker))}${worker.has_draft ? " · Entwurf geschützt" : ""}</small></span>
                    <code>${worker.reserved ? "LEASE" : "BEREIT"}</code>
                </div>`);
        agentContainer.innerHTML = [...activeRows, ...idleRows].join("")
            || `<div class="hub-overview-empty"><span>○</span><div><strong>Keine Worker verbunden</strong><small>Anti-Gravity wird beim nächsten Chat erneut geprüft.</small></div></div>`;
    }
}

async function runHubPrimaryAction() {
    if (hubPrimaryAction.type === "control") {
        activateHubTab("control-center-tab");
    } else if (hubPrimaryAction.type === "chats") {
        activateHubTab("chats-tab");
    } else if (hubPrimaryAction.type === "add-project") {
        openProjectModal();
    } else if (hubPrimaryAction.type === "link-project") {
        await selectProject(hubPrimaryAction.projectId);
        openAntigravityLinkModal(hubPrimaryAction.projectId);
    } else {
        loadHubOverview({showErrors: true});
    }
}

async function openHubOverviewChat(convoId) {
    activateHubTab("chats-tab");
    await openChatInWorkspace(convoId);
}

// View switching
function switchTab(tabId, btnEl) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(el => el.classList.remove("active"));

    document.getElementById(tabId).classList.add("active");
    btnEl.classList.add("active");
    document.body.classList.toggle("chat-workspace-active", tabId === "chats-tab");

    // Persist active tab
    localStorage.setItem('antigravity_active_tab', tabId);

    if (tabId === "lessons-tab") {
        loadLessons();
    }
    if (tabId === "control-center-tab" && typeof loadControlCenter === "function") {
        loadControlCenter();
    }
    if (tabId === "scheduled-tasks-tab") {
        loadScheduledTasks();
    }
    if (tabId === "chats-tab") {
        renderAntigravityChatsWorkspace();
        loadIntegrityChats();
        startConversationAutoRefresh();
    } else {
        stopConversationAutoRefresh();
    }
    if (tabId === "control-docs-tab") {
        loadControlPlaneStatus(true);
        loadControlPlaneManual();
        if (!controlPlanePollTimer) {
            controlPlanePollTimer = window.setInterval(
                () => loadControlPlaneStatus(false),
                2000,
            );
        }
    } else if (controlPlanePollTimer) {
        window.clearInterval(controlPlanePollTimer);
        controlPlanePollTimer = null;
    }
    if (tabId === "dashboard-tab") {
        loadHubOverview();
        startHubOverviewRefresh();
    } else {
        stopHubOverviewRefresh();
    }
}

function activateHubTab(tabId) {
    const button = document.querySelector(`.nav-btn[onclick*="'${tabId}'"]`);
    if (!button || !document.getElementById(tabId)) return;
    switchTab(tabId, button);
}

function openHubCommandPalette() {
    const palette = document.getElementById("hub-command-palette");
    const input = document.getElementById("hub-command-search");
    if (!palette || !input) return;
    palette.hidden = false;
    document.body.classList.add("hub-command-open");
    input.value = "";
    filterHubCommands("");
    window.setTimeout(() => input.focus(), 30);
}

function closeHubCommandPalette() {
    const palette = document.getElementById("hub-command-palette");
    if (!palette || palette.hidden) return;
    palette.hidden = true;
    document.body.classList.remove("hub-command-open");
    document.getElementById("hub-command-button")?.focus();
}

function filterHubCommands(value = "") {
    const query = String(value || "").trim().toLowerCase();
    const items = Array.from(document.querySelectorAll(".hub-command-item"));
    let visible = 0;
    items.forEach(item => {
        const matches = !query || String(item.dataset.search || "").includes(query);
        item.hidden = !matches;
        if (matches) visible += 1;
    });
    const empty = document.getElementById("hub-command-empty");
    if (empty) empty.hidden = visible !== 0;
}

function handleHubCommandKey(event) {
    if (event.key !== "Enter") return;
    const first = Array.from(document.querySelectorAll(".hub-command-item"))
        .find(item => !item.hidden);
    if (first) {
        event.preventDefault();
        first.click();
    }
}

async function runHubCommand(command) {
    closeHubCommandPalette();
    if (command.endsWith("-tab")) {
        activateHubTab(command);
        return;
    }
    if (command === "add-project") {
        activateHubTab("dashboard-tab");
        openProjectModal();
        return;
    }
    if (command === "new-conversation") {
        activateHubTab("chats-tab");
        await createIntegrityChat("normal");
        return;
    }
    if (command === "orchestrator") {
        toggleOrchestratorDrawer(true);
    }
}

function toggleOrchestratorDrawer(forceOpen = null) {
    const drawer = document.getElementById("orchestrator-sidebar");
    const backdrop = document.getElementById("orchestrator-backdrop");
    const button = document.getElementById("orchestrator-toggle-btn");
    if (!drawer || !backdrop) return;

    const shouldOpen = forceOpen === null
        ? !drawer.classList.contains("is-open")
        : Boolean(forceOpen);
    drawer.classList.toggle("is-open", shouldOpen);
    backdrop.classList.toggle("is-open", shouldOpen);
    drawer.setAttribute("aria-hidden", String(!shouldOpen));
    button?.classList.toggle("active", shouldOpen);
    if (shouldOpen) {
        window.setTimeout(() => document.getElementById("orchestrator-input")?.focus(), 120);
    }
}

async function loadControlPlaneStatus(showErrors = false) {
    const connection = document.getElementById("control-plane-connection");
    try {
        const response = await fetch("/api/control-plane/operations", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Queue-Status konnte nicht geladen werden.");

        const counts = data.counts || {};
        document.getElementById("control-queue-active-count").textContent = String(counts.active || 0);
        document.getElementById("control-queue-waiting-count").textContent = String(counts.waiting || 0);
        document.getElementById("control-queue-recent-count").textContent = String(counts.recent || 0);
        if (connection) {
            connection.className = "scheduled-connection is-online";
            connection.textContent = "● Conflict-aware FIFO aktiv";
        }
        renderControlOperations(data);
    } catch (error) {
        if (connection) {
            connection.className = "scheduled-connection is-offline";
            connection.textContent = "● Control Plane offline";
        }
        if (showErrors) showToast("error", "Control Plane", error.message);
    }
}

function renderControlOperations(data) {
    const container = document.getElementById("control-operation-list");
    if (!container) return;
    const active = data.active || [];
    const waiting = data.waiting || [];
    const recent = (data.recent || []).slice(0, 8);
    const items = [
        ...active.map(item => ({...item, display_state: "Aktiv"})),
        ...waiting.map(item => ({...item, display_state: `Wartend #${item.queue_position || "?"}`})),
        ...recent.map(item => ({...item, display_state: item.state})),
    ];
    if (!items.length) {
        container.innerHTML = '<div class="workspace-placeholder placeholder-sm">Noch keine Control-Operation protokolliert.</div>';
        return;
    }
    container.innerHTML = items.map(item => `
        <div class="control-operation-item is-${escapeHTML(item.state || "unknown")}">
            <div class="control-operation-title">
                <strong>${escapeHTML(item.display_state || item.state || "Unbekannt")}</strong>
                <code>#${escapeHTML(String(item.operation_id || "").slice(0, 10))}</code>
            </div>
            <span>${escapeHTML(item.name || "Operation")}</span>
            <small>${escapeHTML((item.resources || []).join(" · "))}</small>
            <small>Wartezeit ${Number(item.wait_ms || 0).toFixed(0)} ms · Laufzeit ${Number(item.duration_ms || 0).toFixed(0)} ms</small>
            ${item.error ? `<small class="control-operation-error">${escapeHTML(item.error)}</small>` : ""}
        </div>
    `).join("");
}

async function loadControlPlaneManual() {
    if (controlPlaneManualLoaded) return;
    const target = document.getElementById("control-plane-manual");
    if (!target) return;
    try {
        const response = await fetch("/api/control-plane/docs", {cache: "no-store"});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        target.textContent = await response.text();
        controlPlaneManualLoaded = true;
    } catch (error) {
        target.textContent = `Dokumentation konnte nicht geladen werden: ${error.message}`;
    }
}

// ============================================================
// Modals
// ============================================================
function openModal(id) {
    document.getElementById(id).style.display = "flex";
}

// Global: Close any visible modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(modal => {
            if (modal.style.display === 'flex') {
                closeModal(modal.id);
            }
        });
    }
});

// Global: Close modal when clicking on the backdrop (the dark overlay)
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal') && e.target.style.display === 'flex') {
        closeModal(e.target.id);
    }
});

function closeModal(id) {
    const modalEl = document.getElementById(id);
    if (modalEl) modalEl.style.display = "none";
    if (typeof stopControlDictationForModal === "function") {
        stopControlDictationForModal(id);
    }
    if (id === "chat-history-modal") {
        const keys = Object.keys(chatWindowsState);
        keys.forEach(convoId => {
            destroyChatWindow(convoId);
        });
        activeConvoId = null;
        if (chatPollInterval) {
            clearInterval(chatPollInterval);
            chatPollInterval = null;
        }
        stopQuotaPolling();
    }
}

function destroyChatWindow(convoId) {
    // Remove from open chats list
    let openChats = [];
    try {
        openChats = JSON.parse(localStorage.getItem('antigravity_open_chats')) || [];
    } catch(e) {}
    openChats = openChats.filter(id => id !== convoId);
    localStorage.setItem('antigravity_open_chats', JSON.stringify(openChats));

    const state = chatWindowsState[convoId];
    if (!state) return;
    const wasEmbedded = state.domElement?.classList.contains("chat-window-embedded");

    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
    if (state.modelSyncInterval) {
        clearInterval(state.modelSyncInterval);
        state.modelSyncInterval = null;
    }
    if (state.quotaPollInterval) {
        clearInterval(state.quotaPollInterval);
        state.quotaPollInterval = null;
    }
    if (state.modelSwitchTimeout) {
        clearTimeout(state.modelSwitchTimeout);
        state.modelSwitchTimeout = null;
    }
    if (state.voicePollInterval) {
        clearInterval(state.voicePollInterval);
        state.voicePollInterval = null;
    }
    if (state.voiceUiInterval) {
        clearInterval(state.voiceUiInterval);
        state.voiceUiInterval = null;
    }
    if (state.isListening || ["starting", "recording"].includes(state.voicePhase)) {
        getAuthToken().then(token => {
            const headers = token ? {Authorization: `Bearer ${token}`} : {};
            return controlFetch("/api/voice/dictation/stop", {
                method: "POST",
                headers,
            });
        }).catch(error => {
            console.warn("[Voice] Failed to stop recording while closing chat:", error);
        });
    }
    if (state.thinkingAnimationInterval) {
        clearInterval(state.thinkingAnimationInterval);
        state.thinkingAnimationInterval = null;
    }
    if (state.streamErrorTimeout) {
        clearTimeout(state.streamErrorTimeout);
        state.streamErrorTimeout = null;
    }
    if (state.domElement && state.domElement.parentNode) {
        state.domElement.parentNode.removeChild(state.domElement);
    }
    delete chatWindowsState[convoId];
    if (wasEmbedded || currentEmbeddedConvoId === convoId) {
        showChatStagePlaceholder();
    }
    if (activeConvoId === convoId) {
        activeConvoId = Object.keys(chatWindowsState)[0] || null;
    }
}


function openProjectModal() {
    const search = document.getElementById("github-repo-search");
    if (search) search.value = "";
    const localPath = document.getElementById("github-local-path");
    if (localPath) localPath.value = "";
    const basePath = document.getElementById("new-project-base-path");
    if (basePath && !basePath.value) basePath.value = projectsBaseDir || "";
    const createdId = document.getElementById("new-project-created-id");
    if (createdId) createdId.value = "";
    const status = document.getElementById("new-project-workflow-status");
    if (status) {
        status.hidden = true;
        status.querySelectorAll("[data-step]").forEach(step => {
            step.className = "";
            step.querySelector("small").textContent = "Wartet";
        });
    }
    updateNewProjectPathPreview();
    openModal("project-modal");
    loadGithubRepositories();
}

function safeWindowsProjectFolder(name) {
    return String(name || "")
        .replace(/[<>:"/\\|?*]/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/[.\s]+$/g, "");
}

function getNewProjectTargetPath() {
    const basePath = (document.getElementById("new-project-base-path")?.value || "")
        .trim()
        .replace(/[\\/]+$/g, "");
    const folderName = safeWindowsProjectFolder(
        document.getElementById("new-project-name")?.value,
    );
    return basePath && folderName ? `${basePath}\\${folderName}` : "";
}

function updateNewProjectPathPreview() {
    const preview = document.getElementById("new-project-path-preview");
    if (!preview) return;
    preview.textContent = getNewProjectTargetPath() || "Name und Basisordner eingeben";
}

function updateProjectWorkflowStep(stepName, state, text) {
    const status = document.getElementById("new-project-workflow-status");
    const step = status?.querySelector(`[data-step="${stepName}"]`);
    if (!status || !step) return;
    status.hidden = false;
    step.className = state ? `is-${state}` : "";
    step.querySelector("small").textContent = text;
}

async function createHubProjectWorkflow(event) {
    event.preventDefault();
    const name = (document.getElementById("new-project-name")?.value || "").trim();
    const targetPath = getNewProjectTargetPath();
    const createGithub = Boolean(document.getElementById("new-project-create-github")?.checked);
    const createAntigravity = Boolean(document.getElementById("new-project-create-antigravity")?.checked);
    const githubVisibility = document.getElementById("new-project-visibility")?.value || "private";
    const submit = document.getElementById("new-project-workflow-submit");
    const createdIdInput = document.getElementById("new-project-created-id");
    if (!name || !targetPath) {
        showToast("warning", "Projektangaben fehlen", "Bitte Projektname und Windows-Basisordner angeben.");
        return;
    }

    submit.disabled = true;
    submit.textContent = "Workflow läuft…";
    let projectId = Number(createdIdInput?.value || 0);
    const resumingExistingWorkflow = Boolean(projectId);
    let workflowIncomplete = false;
    try {
        let project = projects.find(item => Number(item.id) === projectId);
        if (!projectId) {
            updateProjectWorkflowStep("local", "running", "Ordner und Git werden angelegt…");
            updateProjectWorkflowStep(
                "github",
                createGithub ? "running" : "skipped",
                createGithub ? "Wird anschließend erstellt…" : "Übersprungen",
            );
            updateProjectWorkflowStep(
                "antigravity",
                createAntigravity ? "" : "skipped",
                createAntigravity ? "Wartet" : "Übersprungen",
            );
            const response = await controlFetch("/api/projects", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    name,
                    path: targetPath,
                    create_github: createGithub,
                    github_visibility: githubVisibility,
                }),
            });
            project = await response.json();
            if (!response.ok) throw new Error(project.error || "Projekt konnte nicht angelegt werden.");
            projectId = Number(project.id);
            if (createdIdInput) createdIdInput.value = String(projectId);
            updateProjectWorkflowStep("local", "success", targetPath);
            if (createGithub) {
                if (project.github_url && !project.github_error) {
                    updateProjectWorkflowStep("github", "success", project.github_url);
                } else if (project.github_url) {
                    updateProjectWorkflowStep("github", "warning", project.github_error);
                    workflowIncomplete = true;
                } else {
                    updateProjectWorkflowStep(
                        "github",
                        "warning",
                        project.github_error || "Repository noch nicht verbunden",
                    );
                    workflowIncomplete = true;
                }
            }
            await loadProjects();
            project = projects.find(item => Number(item.id) === projectId) || project;
        }

        if (createGithub && resumingExistingWorkflow) {
            updateProjectWorkflowStep("github", "running", "GitHub wird geprüft und repariert…");
            project = await requestProjectGithubReconcile(projectId);
            updateProjectWorkflowStep("github", "success", project.github_url);
            workflowIncomplete = false;
        }

        if (createAntigravity) {
            const registeredPath = project?.path || targetPath;
            if (project?.antigravity_linked) {
                updateProjectWorkflowStep(
                    "antigravity",
                    "success",
                    `${project.antigravity_project_name || name} ist verknüpft`,
                );
            } else {
                updateProjectWorkflowStep("antigravity", "running", "Add Folder wird in Anti-Gravity ausgeführt…");
                const response = await controlFetch(`/api/projects/${projectId}/antigravity-project`, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({workspace_path: registeredPath}),
                });
                const native = await response.json();
                if (!response.ok) {
                    updateProjectWorkflowStep("antigravity", "warning", native.error || "Retry erforderlich");
                    await loadProjects();
                    showToast(
                        "warning",
                        "Projekt teilweise eingerichtet",
                        "Anti-Gravity war noch nicht bereit. Der Assistent bleibt für einen sicheren Retry geöffnet.",
                    );
                    return;
                }
                updateProjectWorkflowStep(
                    "antigravity",
                    "success",
                    `${native.antigravity_project_name || name} ist verknüpft`,
                );
            }
        }

        if (workflowIncomplete) {
            await loadProjects();
            showToast(
                "warning",
                "Projekt teilweise eingerichtet",
                "GitHub ist noch nicht vollständig bereit. Klicke auf „Fehlende Schritte erneut ausführen“.",
            );
            return;
        }

        githubRepositoryCatalog = [];
        await loadProjects();
        closeModal("project-modal");
        await selectProject(projectId);
        showToast(
            "success",
            "Projekt bereit",
            "Ordner, Hub und die gewählten externen Verknüpfungen sind eingerichtet.",
        );
    } catch (error) {
        showToast("error", "Projekt-Workflow fehlgeschlagen", error.message);
    } finally {
        submit.disabled = false;
        submit.textContent = projectId ? "Fehlende Schritte erneut ausführen" : "Projekt komplett anlegen";
    }
}

async function requestProjectGithubReconcile(projectId) {
    const response = await controlFetch(`/api/projects/${projectId}/github-bootstrap`, {
        method: "POST",
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || "GitHub konnte nicht geprüft oder repariert werden.");
    }
    return data;
}

async function repairProjectGithub(projectId = 0) {
    const resolvedId = Number(
        projectId || document.getElementById("integrity-link-project-id")?.value || 0,
    );
    const button = document.getElementById("project-github-repair-btn");
    if (!resolvedId) return;
    if (button) {
        button.disabled = true;
        button.textContent = "Wird geprüft…";
    }
    try {
        const project = await requestProjectGithubReconcile(resolvedId);
        await loadProjects();
        syncProjectGithubHealth(project);
        showToast(
            "success",
            "GitHub bereit",
            "Branch, Push und Anti-Gravity-Labels wurden verifiziert.",
        );
    } catch (error) {
        showToast("error", "GitHub-Reparatur fehlgeschlagen", error.message);
    } finally {
        if (button) {
            button.disabled = false;
            const refreshed = projects.find(
                item => Number(item.id) === resolvedId,
            );
            button.textContent = refreshed?.github_bootstrap_required
                ? "GitHub reparieren"
                : "GitHub prüfen";
        }
    }
}

let githubRepositoryCatalog = [];

async function loadGithubRepositories(force = false) {
    const catalog = document.getElementById("github-repo-catalog");
    if (!catalog) return;
    if (!force && githubRepositoryCatalog.length > 0) {
        renderGithubRepositoryCatalog();
        return;
    }
    catalog.innerHTML = `<div class="workspace-placeholder placeholder-sm">Lade GitHub-Repositories…</div>`;
    try {
        const response = await fetch("/api/github/repos");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "GitHub-Repositories konnten nicht geladen werden.");
        githubRepositoryCatalog = data.repositories || [];
        renderGithubRepositoryCatalog();
    } catch (error) {
        catalog.innerHTML = `<div class="workspace-placeholder placeholder-sm text-danger">${escapeHTML(error.message)}</div>`;
    }
}

function renderGithubRepositoryCatalog() {
    const catalog = document.getElementById("github-repo-catalog");
    if (!catalog) return;
    const query = (document.getElementById("github-repo-search")?.value || "").trim().toLowerCase();
    const repositories = githubRepositoryCatalog.filter(repository =>
        !query || repository.full_name.toLowerCase().includes(query) ||
        (repository.description || "").toLowerCase().includes(query)
    );
    if (repositories.length === 0) {
        catalog.innerHTML = `<div class="workspace-placeholder placeholder-sm">Keine passenden GitHub-Repositories gefunden.</div>`;
        return;
    }
    catalog.innerHTML = repositories.map(repository => `
        <div class="github-repo-option">
            <div class="github-repo-option-content">
                <strong>⬡ ${escapeHTML(repository.full_name)}</strong>
                <span>${escapeHTML(repository.description || "Keine Beschreibung")}</span>
                <small>${repository.private ? "Privat" : "Öffentlich"} · ${escapeHTML(repository.default_branch || "main")}</small>
                <small class="github-local-path-preview">Standard: ${escapeHTML(repository.suggested_local_path || "")}</small>
            </div>
            <button class="btn ${repository.imported ? 'btn-secondary' : 'btn-primary'} btn-sm"
                    ${repository.imported ? 'disabled' : ''}
                    onclick="importGithubRepository('${escapeHTML(repository.full_name)}')">
                ${repository.imported ? 'Hinzugefügt' : 'Hinzufügen'}
            </button>
        </div>
    `).join("");
}

async function importGithubRepository(fullName) {
    const repository = githubRepositoryCatalog.find(item => item.full_name === fullName);
    if (!repository || repository.imported) return;
    const requestedPath = (document.getElementById("github-local-path")?.value || "").trim();
    const localPath = requestedPath || repository.suggested_local_path || "";
    try {
        const response = await controlFetch("/api/projects/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ full_name: fullName, path: localPath })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "GitHub-Projekt konnte nicht hinzugefügt werden.");
        repository.imported = true;
        repository.project_id = data.id;
        renderGithubRepositoryCatalog();
        await loadProjects();
        showToast("success", "GitHub-Projekt hinzugefügt", `${fullName} ist jetzt im Anti-Gravity Hub verfügbar.`);
    } catch (error) {
        showToast("error", "GitHub-Import fehlgeschlagen", error.message);
    }
}

// ============================================================
// Projects Logic
// ============================================================
async function loadProjects() {
    try {
        const res = await fetch("/api/projects");
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "Projektliste konnte nicht geladen werden.");
        }
        projects = data.projects || [];
        if (currentProjectId && !projects.some(project => Number(project.id) === Number(currentProjectId))) {
            currentProjectId = null;
            currentIssueId = null;
            localStorage.removeItem('antigravity_selected_project');
        }
        renderProjects();
        renderHubOverview();
        return projects;
    } catch (err) {
        console.error("Failed to load projects:", err);
        showToast(
            "error",
            "Projektstatus unbekannt",
            "Die vorhandene Liste bleibt sichtbar; Änderungen sind bis zum nächsten erfolgreichen Laden unsicher.",
        );
        return projects;
    }
}

function renderProjects() {
    const list = document.getElementById("project-list");
    if (projects.length === 0) {
        list.innerHTML = `
            <div class="workspace-placeholder placeholder-sm">
                Noch keine Projekte im Hub.<br>
                <button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="openProjectModal()">Projekt hinzufügen</button>
            </div>`;
        return;
    }

    list.innerHTML = projects.map(p => `
        <div class="list-item ${p.id === currentProjectId ? 'selected' : ''}" onclick="selectProject(${p.id})">
            <div class="list-item-content">
                <div class="list-item-title">⬡ ${escapeHTML(p.github_repo || p.name)}</div>
                <div class="list-item-subtitle">${p.github_url
                    ? `<a href="${escapeHTML(p.github_url)}" target="_blank" class="gh-repo-link" onclick="event.stopPropagation()">${escapeHTML(p.github_owner)}/${escapeHTML(p.github_repo)}</a>`
                    : '<span style="color:var(--color-warning)">○ GitHub noch nicht verbunden</span>'}</div>
                ${p.github_bootstrap_required
                    ? `<div class="list-item-subtitle" style="margin-top:3px;color:var(--color-warning)">⚠ GitHub-Reparatur erforderlich</div>`
                    : ""}
                <div class="list-item-subtitle" style="margin-top:3px;color:${p.antigravity_linked ? 'var(--color-success)' : 'var(--color-text-muted)'}">
                    ${p.antigravity_linked ? `● Anti-Gravity: ${escapeHTML(p.antigravity_project_name || 'Verknüpft')}` : '○ Noch keinem Anti-Gravity-Projekt zugeordnet'}
                </div>
            </div>
            <div class="flex-align-center-gap">
                <span class="badge badge-branch">
                    ${escapeHTML(p.git_branch || 'main')}
                </span>
                <button class="btn btn-ghost btn-xs project-ide-btn"
                    onclick="event.stopPropagation(); openProjectIde(${p.id})"
                    title="Projekt in der Web-IDE öffnen"
                    aria-label="Projekt in der Web-IDE öffnen">&lt;/&gt;</button>
                <button class="btn btn-ghost btn-xs" onclick="event.stopPropagation(); openAntigravityLinkModal(${p.id})" title="Projekt-Einstellungen" style="padding:4px 6px">⚙</button>
                <button type="button" class="delete-icon"
                    onclick="event.stopPropagation(); deleteProject(${p.id})"
                    title="Projekt deregistrieren"
                    aria-label="Projekt ${escapeHTML(p.github_repo || p.name)} deregistrieren">&times;</button>
            </div>
        </div>
    `).join("");
}

let antigravityProjectSuggestions = [];

async function openAntigravityLinkModal(projectId) {
    const project = projects.find(item => Number(item.id) === Number(projectId));
    if (!project) return;
    document.getElementById('integrity-link-project-id').value = String(project.id);
    document.getElementById('integrity-link-project-name').textContent = project.name;
    document.getElementById('integrity-link-current').textContent = project.antigravity_linked
        ? `Aktuell: ${project.antigravity_project_name || 'Anti-Gravity-Projekt'}`
        : 'Aktuell besteht keine Anti-Gravity-Zuordnung.';
    document.getElementById('antigravity-create-workspace-path').value = project.path || '';
    document.getElementById('integrity-unlink-btn').style.visibility = project.antigravity_linked ? 'visible' : 'hidden';
    syncProjectGithubHealth(project);
    const select = document.getElementById('antigravity-project-select');
    select.innerHTML = '<option value="">Lade Projekte aus Anti-Gravity…</option>';
    select.disabled = true;
    openModal('integrity-link-modal');
    try {
        const response = await fetch('/api/antigravity/projects');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Anti-Gravity-Projekte konnten nicht geladen werden.');
        antigravityProjectSuggestions = data.projects || [];
        select.innerHTML = '<option value="">Projekt auswählen…</option>' + antigravityProjectSuggestions.map(item =>
            `<option value="${escapeHTML(item.id)}">${escapeHTML(item.display_name)} · ${item.chat_count} Chats</option>`
        ).join('');
        const current = antigravityProjectSuggestions.find(item =>
            item.display_name === project.antigravity_project_name || item.id === project.integrity_project_uuid
        );
        if (current) select.value = current.id;
        select.disabled = false;
    } catch (error) {
        antigravityProjectSuggestions = [];
        select.innerHTML = '<option value="">Anti-Gravity ist nicht erreichbar</option>';
        showToast('warning', 'Anti-Gravity-Projekte', error.message);
    }
}

function syncProjectGithubHealth(project) {
    const health = document.getElementById("project-github-health");
    const text = document.getElementById("project-github-health-text");
    const button = document.getElementById("project-github-repair-btn");
    if (!health || !text || !button) return;
    if (!project?.github_url) {
        health.style.display = "none";
        return;
    }
    health.style.display = "flex";
    const needsRepair = Boolean(project.github_bootstrap_required);
    health.classList.toggle("is-warning", needsRepair);
    text.textContent = needsRepair
        ? ` · Reparatur nötig: ${project.github_setup_error || "Initialer Push wurde nicht bestätigt."}`
        : ` · Bereit: ${project.github_owner}/${project.github_repo}`;
    button.textContent = needsRepair ? "GitHub reparieren" : "GitHub prüfen";
}

async function submitAntigravityProjectLink() {
    const projectId = Number(document.getElementById('integrity-link-project-id').value);
    const antigravityProjectId = document.getElementById('antigravity-project-select').value;
    if (!projectId || !antigravityProjectId) {
        showToast('warning', 'Projekt fehlt', 'Bitte ein Projekt aus der Anti-Gravity-Liste auswählen.');
        return;
    }
    try {
        const response = await controlFetch(`/api/projects/${projectId}/antigravity-link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ antigravity_project_id: antigravityProjectId }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Verknüpfung fehlgeschlagen.');
        closeModal('integrity-link-modal');
        await loadProjects();
        if (Number(currentProjectId) === projectId) loadIntegrityChats();
        showToast('success', 'Anti-Gravity zugeordnet', 'GitHub-Repo und Anti-Gravity-Projekt sind jetzt eindeutig gekoppelt.');
    } catch (error) {
        showToast('error', 'Anti-Gravity-Zuordnung fehlgeschlagen', error.message);
    }
}

async function unlinkAntigravityProject() {
    const projectId = Number(document.getElementById('integrity-link-project-id').value);
    if (!projectId || !(await hubConfirm(
        'Nur die Anti-Gravity-Zuordnung lösen? Repo, Dateien, Issues und Chats werden nicht gelöscht.',
        {title: 'Verknüpfung lösen', confirmLabel: 'Verknüpfung lösen'},
    ))) return;
    try {
        const response = await controlFetch(`/api/projects/${projectId}/antigravity-link`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Verknüpfung konnte nicht gelöst werden.');
        closeModal('integrity-link-modal');
        await loadProjects();
        if (Number(currentProjectId) === projectId) loadIntegrityChats();
        showToast('success', 'Verknüpfung gelöst', 'Das Hub-Projekt bleibt vollständig erhalten.');
    } catch (error) {
        showToast('error', 'Verknüpfung nicht gelöst', error.message);
    }
}

async function createAndLinkAntigravityProject() {
    const projectId = Number(document.getElementById('integrity-link-project-id').value);
    const workspacePath = document.getElementById('antigravity-create-workspace-path').value.trim();
    const button = document.getElementById('antigravity-create-project-btn');
    if (!projectId || !workspacePath) {
        showToast('warning', 'Projektordner fehlt', 'Der lokale GitHub-Projektordner fehlt.');
        return;
    }
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = 'Wird erstellt…';
    try {
        const response = await controlFetch(`/api/projects/${projectId}/antigravity-project`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({workspace_path: workspacePath}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Anti-Gravity-Projekt konnte nicht erstellt werden.');
        closeModal('integrity-link-modal');
        await loadProjects();
        if (Number(currentProjectId) === projectId) loadIntegrityChats();
        showToast(
            'success',
            data.created ? 'Anti-Gravity-Projekt erstellt' : 'Anti-Gravity-Projekt gefunden',
            `${data.antigravity_project_name || 'Projekt'} ist jetzt mit dem Hub verbunden.`,
        );
    } catch (error) {
        showToast('error', 'Anti-Gravity-Projektanlage fehlgeschlagen', error.message);
    } finally {
        button.disabled = false;
        button.textContent = originalLabel;
    }
}

// ============================================================
// Native Anti-Gravity Scheduled Tasks
// ============================================================

function slugifyScheduledTaskName(name) {
    return String(name || '')
        .replace(/[\/\\]/g, ' ')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9\s_-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function updateScheduledTaskIdPreview() {
    const currentId = document.getElementById('scheduled-task-id')?.value || '';
    const name = document.getElementById('scheduled-task-name')?.value || '';
    const taskId = currentId || slugifyScheduledTaskName(name);
    const preview = document.getElementById('scheduled-task-id-preview');
    if (!preview) return;
    preview.textContent = currentId
        ? `Stabile ID: ${currentId} (bleibt beim Umbenennen erhalten)`
        : taskId
            ? `ID: ${taskId}`
            : 'ID wird automatisch erzeugt.';
}

function scheduledTaskProjectName(projectId, allProjects = false) {
    if (allProjects) return 'Alle Projekte';
    const project = scheduledTaskProjects.find(item => item.id === projectId);
    return project?.display_name || projectId || 'Kein Projekt';
}

function friendlyCron(cron) {
    const parts = String(cron || '').trim().split(/\s+/);
    if (parts.length !== 5) return cron || 'Kein Zeitplan';
    const [minute, hour, day, month, weekday] = parts;
    const time = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    if (day === '*' && month === '*' && weekday === '*') return `Täglich · ${time}`;
    const weekdays = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
    if (day === '*' && month === '*' && /^[0-6]$/.test(weekday)) {
        return `${weekdays[Number(weekday)]} · ${time}`;
    }
    return `Cron · ${cron}`;
}

async function loadScheduledTaskProjects() {
    const response = await fetch('/api/antigravity/projects');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Anti-Gravity-Projekte konnten nicht geladen werden.');
    scheduledTaskProjects = data.projects || [];
    return scheduledTaskProjects;
}

async function loadScheduledTasks(force = false) {
    const list = document.getElementById('scheduled-task-list');
    if (!list) return;
    if (force || scheduledTasks.length === 0) {
        list.innerHTML = `
            <div class="glass-card workspace-placeholder placeholder-lg">
                <div class="icon">⏱</div><h3>Native Tasks werden geladen…</h3>
            </div>`;
    }
    try {
        const [taskResponse] = await Promise.all([
            fetch('/api/antigravity/scheduled-tasks'),
            loadScheduledTaskProjects().catch(() => []),
        ]);
        const data = await taskResponse.json();
        if (!taskResponse.ok) throw new Error(data.error || 'Scheduled Tasks konnten nicht geladen werden.');
        scheduledTasks = data.tasks || [];
        scheduledTasksConnected = Boolean(data.connected);
        renderScheduledTasks();
    } catch (error) {
        scheduledTasks = [];
        scheduledTasksConnected = false;
        renderScheduledTasks(error.message);
    }
}

function renderScheduledTasks(errorMessage = '') {
    const list = document.getElementById('scheduled-task-list');
    const connection = document.getElementById('scheduled-tasks-connection');
    const counts = document.getElementById('scheduled-task-counts');
    if (!list || !connection || !counts) return;

    connection.className = `scheduled-connection ${scheduledTasksConnected ? 'is-online' : 'is-offline'}`;
    connection.textContent = scheduledTasksConnected ? '● Native API online' : '● Anti-Gravity offline';
    const query = (document.getElementById('scheduled-task-search')?.value || '').trim().toLowerCase();
    const visible = scheduledTasks.filter(task => {
        const haystack = [
            task.name,
            task.id,
            task.prompt,
            task.schedule,
            scheduledTaskProjectName(task.project_id, task.all_projects),
        ].join(' ').toLowerCase();
        return !query || haystack.includes(query);
    });
    counts.textContent = `${visible.length} von ${scheduledTasks.length} Tasks`;

    if (errorMessage) {
        list.innerHTML = `
            <div class="glass-card workspace-placeholder placeholder-lg scheduled-task-error">
                <div class="icon">⚠</div>
                <h3>Native Scheduled Tasks nicht erreichbar</h3>
                <p class="placeholder-text">${escapeHTML(errorMessage)}</p>
                <button class="btn btn-secondary" onclick="loadScheduledTasks(true)">Erneut versuchen</button>
            </div>`;
        return;
    }
    if (visible.length === 0) {
        list.innerHTML = `
            <div class="glass-card workspace-placeholder placeholder-lg">
                <div class="icon">⏱</div>
                <h3>${query ? 'Keine passenden Tasks' : 'Noch keine Scheduled Tasks'}</h3>
                <p class="placeholder-text">${query ? 'Passe deine Suche an.' : 'Erstelle den ersten nativen Anti-Gravity-Zeitplan.'}</p>
            </div>`;
        return;
    }

    list.innerHTML = visible.map(task => `
        <article class="glass-card scheduled-task-card ${task.enabled ? 'is-enabled' : 'is-disabled'}">
            <div class="scheduled-task-card-header">
                <div class="scheduled-task-card-title">
                    <span class="scheduled-task-state-dot"></span>
                    <div>
                        <h3>${escapeHTML(task.name)}</h3>
                        <code>${escapeHTML(task.id)}</code>
                    </div>
                </div>
                <label class="scheduled-task-switch" title="${task.enabled ? 'Task deaktivieren' : 'Task aktivieren'}">
                    <input type="checkbox" ${task.enabled ? 'checked' : ''} onchange="setScheduledTaskEnabled('${task.id}', this.checked)">
                    <span></span>
                </label>
            </div>
            <div class="scheduled-task-meta">
                <span>◷ ${escapeHTML(friendlyCron(task.schedule))}</span>
                <span>▣ ${escapeHTML(scheduledTaskProjectName(task.project_id, task.all_projects))}</span>
                <span class="${task.last_error ? 'text-danger' : ''}">${task.last_error ? '⚠ Fehler' : task.enabled ? '● Aktiv' : '○ Pausiert'}</span>
            </div>
            <p class="scheduled-task-prompt">${escapeHTML(task.prompt)}</p>
            ${task.last_error ? `<div class="scheduled-task-last-error">${escapeHTML(task.last_error)}</div>` : ''}
            <div class="scheduled-task-actions">
                <button class="btn btn-ghost btn-sm" onclick="openScheduledTaskModal('${task.id}')">Bearbeiten</button>
                <button class="btn btn-ghost btn-sm" onclick="showScheduledTaskEvents('${task.id}')">Events</button>
                <button class="btn btn-secondary btn-sm" onclick="restartScheduledTask('${task.id}')" ${task.enabled ? '' : 'disabled'}>Task neu starten</button>
                <button class="btn btn-danger btn-sm" onclick="deleteScheduledTask('${task.id}')">Löschen</button>
            </div>
        </article>
    `).join('');
}

function syncScheduledTaskProjectRequirement() {
    const allProjects = document.getElementById('scheduled-task-all-projects').checked;
    const projectSelect = document.getElementById('scheduled-task-project');
    projectSelect.disabled = allProjects;
    projectSelect.required = !allProjects;
}

function syncScheduledTaskScheduleFields() {
    const frequency = document.getElementById('scheduled-task-frequency').value;
    document.getElementById('scheduled-task-weekday-group').style.display = frequency === 'weekly' ? '' : 'none';
    document.getElementById('scheduled-task-time-group').style.display = frequency === 'custom' ? 'none' : '';
    document.getElementById('scheduled-task-cron-group').style.display = frequency === 'custom' ? '' : 'none';
}

function parseScheduledTaskCron(cron) {
    const parts = String(cron || '').trim().split(/\s+/);
    if (parts.length === 5) {
        const [minute, hour, day, month, weekday] = parts;
        if (day === '*' && month === '*' && weekday === '*' && /^\d+$/.test(minute) && /^\d+$/.test(hour)) {
            return {frequency: 'daily', time: `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`, weekday: '1'};
        }
        if (day === '*' && month === '*' && /^[0-6]$/.test(weekday) && /^\d+$/.test(minute) && /^\d+$/.test(hour)) {
            return {frequency: 'weekly', time: `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`, weekday};
        }
    }
    return {frequency: 'custom', time: '09:00', weekday: '1'};
}

function buildScheduledTaskCron() {
    const frequency = document.getElementById('scheduled-task-frequency').value;
    if (frequency === 'custom') return document.getElementById('scheduled-task-cron').value.trim();
    const [hour, minute] = (document.getElementById('scheduled-task-time').value || '09:00').split(':');
    if (frequency === 'weekly') {
        return `${Number(minute)} ${Number(hour)} * * ${document.getElementById('scheduled-task-weekday').value}`;
    }
    return `${Number(minute)} ${Number(hour)} * * *`;
}

async function openScheduledTaskModal(taskId = '') {
    const task = scheduledTasks.find(item => item.id === taskId);
    document.getElementById('scheduled-task-modal-title').textContent = task ? 'Scheduled Task bearbeiten' : 'Neuer Scheduled Task';
    document.getElementById('scheduled-task-id').value = task?.id || '';
    document.getElementById('scheduled-task-name').value = task?.name || '';
    document.getElementById('scheduled-task-prompt').value = task?.prompt || '';
    document.getElementById('scheduled-task-enabled').checked = task?.enabled || false;
    document.getElementById('scheduled-task-all-projects').checked = task?.all_projects || false;

    try {
        if (scheduledTaskProjects.length === 0) await loadScheduledTaskProjects();
    } catch (error) {
        showToast('warning', 'Projektliste', error.message);
    }
    const projectSelect = document.getElementById('scheduled-task-project');
    projectSelect.innerHTML = '<option value="">Projekt auswählen…</option>' + scheduledTaskProjects.map(project =>
        `<option value="${escapeHTML(project.id)}">${escapeHTML(project.display_name)}</option>`
    ).join('');
    projectSelect.value = task?.project_id || '';

    const parsed = parseScheduledTaskCron(task?.schedule || '0 9 * * *');
    document.getElementById('scheduled-task-frequency').value = parsed.frequency;
    document.getElementById('scheduled-task-time').value = parsed.time;
    document.getElementById('scheduled-task-weekday').value = parsed.weekday;
    document.getElementById('scheduled-task-cron').value = task?.schedule || '0 9 * * *';
    syncScheduledTaskScheduleFields();
    syncScheduledTaskProjectRequirement();
    updateScheduledTaskIdPreview();
    openModal('scheduled-task-modal');
}

async function submitScheduledTask(event) {
    event.preventDefault();
    const taskId = document.getElementById('scheduled-task-id').value;
    const allProjects = document.getElementById('scheduled-task-all-projects').checked;
    const payload = {
        name: document.getElementById('scheduled-task-name').value.trim(),
        schedule: buildScheduledTaskCron(),
        prompt: document.getElementById('scheduled-task-prompt').value.trim(),
        project_id: allProjects ? '' : document.getElementById('scheduled-task-project').value,
        all_projects: allProjects,
        enabled: document.getElementById('scheduled-task-enabled').checked,
    };
    const button = document.getElementById('scheduled-task-submit');
    button.disabled = true;
    button.textContent = 'Speichert…';
    try {
        const response = await controlFetch(
            taskId
                ? `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}`
                : '/api/antigravity/scheduled-tasks',
            {
                method: taskId ? 'PATCH' : 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Task konnte nicht gespeichert werden.');
        closeModal('scheduled-task-modal');
        await loadScheduledTasks(true);
        showToast('success', taskId ? 'Task aktualisiert' : 'Task erstellt', `${data.name} ist in Anti-Gravity gespeichert.`);
    } catch (error) {
        showToast('error', 'Scheduled Task nicht gespeichert', error.message);
    } finally {
        button.disabled = false;
        button.textContent = 'Task speichern';
    }
}

async function setScheduledTaskEnabled(taskId, enabled) {
    const task = scheduledTasks.find(item => item.id === taskId);
    if (task) task.enabled = enabled;
    renderScheduledTasks();
    try {
        const response = await controlFetch(
            `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/${enabled ? 'enable' : 'disable'}`,
            {method: 'POST'},
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Status konnte nicht geändert werden.');
        await loadScheduledTasks(true);
        showToast('success', enabled ? 'Task aktiviert' : 'Task pausiert', data.name || taskId);
    } catch (error) {
        if (task) task.enabled = !enabled;
        renderScheduledTasks();
        showToast('error', 'Statusänderung fehlgeschlagen', error.message);
    }
}

async function restartScheduledTask(taskId) {
    if (!(await hubConfirm(
        'Den nativen Scheduler dieses Tasks neu starten? Der Prompt wird dadurch nicht sofort ausgeführt.',
        {title: 'Scheduler neu starten', confirmLabel: 'Neu starten', danger: false},
    ))) return;
    try {
        const response = await controlFetch(`/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/restart`, {method: 'POST'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Scheduler konnte nicht neu gestartet werden.');
        showToast('success', 'Scheduler neu gestartet', taskId);
        setTimeout(() => loadScheduledTasks(true), 600);
    } catch (error) {
        showToast('error', 'Scheduler-Neustart fehlgeschlagen', error.message);
    }
}

async function deleteScheduledTask(taskId) {
    const task = scheduledTasks.find(item => item.id === taskId);
    if (!(await hubConfirm(
        `Scheduled Task "${task?.name || taskId}" dauerhaft aus Anti-Gravity löschen?`,
        {title: 'Scheduled Task löschen', confirmLabel: 'Dauerhaft löschen'},
    ))) return;
    try {
        const response = await controlFetch(`/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}`, {method: 'DELETE'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Task konnte nicht gelöscht werden.');
        scheduledTasks = scheduledTasks.filter(item => item.id !== taskId);
        renderScheduledTasks();
        showToast('success', 'Task gelöscht', task?.name || taskId);
    } catch (error) {
        showToast('error', 'Löschen fehlgeschlagen', error.message);
    }
}

async function showScheduledTaskEvents(taskId) {
    const task = scheduledTasks.find(item => item.id === taskId);
    document.getElementById('scheduled-task-events-title').textContent = `Events · ${task?.name || taskId}`;
    const body = document.getElementById('scheduled-task-events-body');
    body.innerHTML = '<div class="workspace-placeholder placeholder-sm">Native Events werden geladen…</div>';
    openModal('scheduled-task-events-modal');
    try {
        const response = await fetch(`/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/events`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Events konnten nicht geladen werden.');
        const events = data.events || [];
        body.innerHTML = events.length ? events.map((item, index) => `
            <article class="scheduled-task-event">
                <div class="scheduled-task-event-header">
                    <strong>Event ${events.length - index}</strong>
                    <code>${escapeHTML(String(item.timestampMs || item.timestamp_ms || ''))}</code>
                </div>
                <pre>${escapeHTML(JSON.stringify(item, null, 2))}</pre>
            </article>
        `).join('') : '<div class="workspace-placeholder placeholder-sm">Für diesen Task sind noch keine Events vorhanden.</div>';
    } catch (error) {
        body.innerHTML = `<div class="workspace-placeholder placeholder-sm text-danger">${escapeHTML(error.message)}</div>`;
    }
}

async function selectProject(id) {
    currentProjectId = id;
    currentIssueId = null;
    activeRunId = null;
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    // Persist selected project
    localStorage.setItem('antigravity_selected_project', id.toString());

    renderProjects();
    document.getElementById("add-issue-btn").disabled = false;
    document.getElementById("sync-issues-btn").disabled = false;

    // Reset workspace to placeholder
    renderPlaceholder();

    // Load issues
    loadIssues();

    if (document.getElementById("control-center-tab")?.classList.contains("active") && typeof loadControlCenter === "function") {
        loadControlCenter();
    }
    loadHubOverview();
}

async function deleteProject(id) {
    if (!(await hubConfirm(
        "Möchtest du dieses Projekt wirklich deregistrieren? Deine Dateien auf der Festplatte werden nicht gelöscht.",
        {title: 'Projekt deregistrieren', confirmLabel: 'Deregistrieren'},
    ))) {
        return;
    }
    try {
        await fetch(`/api/projects/${id}`, { method: "DELETE" });
        if (currentProjectId === id) {
            currentProjectId = null;
            currentIssueId = null;
            document.getElementById("add-issue-btn").disabled = true;
            localStorage.removeItem('antigravity_selected_project');
            renderHubHome();
            document.getElementById("issue-list").innerHTML = `<div class="workspace-placeholder placeholder-sm">Wähle ein Projekt aus</div>`;
        }
        loadProjects();
    } catch (err) {
        console.error("Failed to delete project:", err);
    }
}

// ============================================================
// Issues Logic
// ============================================================
async function loadIssues() {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`/api/issues?project_id=${currentProjectId}`);
        const data = await res.json();
        issues = data.issues || [];
        renderIssues();
    } catch (err) {
        console.error("Failed to load issues:", err);
    }
}

function getIssueTypeIcon(type) {
    const icons = { 'bug': '🐛', 'feature': '✨', 'task': '📋', 'epic': '🎯' };
    return icons[type] || '📋';
}

function renderIssues() {
    const list = document.getElementById("issue-list");
    if (issues.length === 0) {
        list.innerHTML = `<div class="workspace-placeholder placeholder-sm">Keine Issues gefunden</div>`;
        return;
    }

    list.innerHTML = issues.map(i => `
        <div class="list-item ${i.id === currentIssueId ? 'selected' : ''}" onclick="selectIssue(${i.id})">
            <div class="list-item-content">
                <div class="list-item-title">${getIssueTypeIcon(i.issue_type || 'task')} ${escapeHTML(i.title)}</div>
                <div class="list-item-subtitle">${escapeHTML(i.description)}${i.github_number ? ` <a href="${escapeHTML(i.github_url)}" target="_blank" class="gh-issue-link" onclick="event.stopPropagation()">#${i.github_number} ↗</a>` : ''}</div>
            </div>
            <span class="badge badge-${i.status}">${i.status}</span>
        </div>
    `).join("");
}

async function selectIssue(id) {
    currentIssueId = id;
    renderIssues();

    // Load issue details and runs
    loadWorkspaceDetails();
}

function openIssueModal() {
    if (!currentProjectId) return;
    document.getElementById("issue-title").value = "";
    document.getElementById("issue-desc").value = "";
    document.getElementById("issue-type").value = "task";
    openModal("issue-modal");
}

async function submitIssue() {
    const title = document.getElementById("issue-title").value.trim();
    const desc = document.getElementById("issue-desc").value.trim();
    const issueType = document.getElementById("issue-type").value;

    if (!title || !desc) {
        showToast("warning", "Issue unvollständig", "Titel und Beschreibung sind erforderlich.");
        return;
    }

    try {
        const res = await fetch("/api/issues", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId, title, description: desc, issue_type: issueType })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || "Unknown error");
        }

        closeModal("issue-modal");
        loadIssues();
    } catch (err) {
        showToast("error", "Issue nicht erstellt", err.message);
    }
}

async function syncIssues() {
    if (!currentProjectId) return;
    const btn = document.getElementById("sync-issues-btn");
    btn.disabled = true;
    btn.textContent = "⏳";

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/sync`);
        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || "Sync fehlgeschlagen");
        }
        loadIssues();
    } catch (err) {
        showToast("error", "GitHub-Sync fehlgeschlagen", err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "🔄";
    }
}

// ============================================================
// Workspace/Execution Logic
// ============================================================
async function loadWorkspaceDetails() {
    if (!currentIssueId) return;

    try {
        // Get issue
        const resIssue = await fetch(`/api/issues`);
        const dataIssue = await resIssue.json();
        const issue = dataIssue.issues.find(i => i.id === currentIssueId);

        if (!issue) return;

        // Get runs for this issue
        const resRuns = await fetch(`/api/issues/${currentIssueId}/runs`);
        const dataRuns = await resRuns.json();
        const runs = dataRuns.runs || [];

        const activeRun = runs.find(r => r.status === "running");
        const latestRun = runs[0]; // SQLite returns DESC by started_at

        renderWorkspace(issue, activeRun, latestRun);

        if (activeRun) {
            activeRunId = activeRun.id;
            startLogStream(activeRun.id);
        } else {
            activeRunId = null;
            if (latestRun) {
                // Static view of the completed/failed latest run
                renderStaticRun(latestRun);
            }
        }
    } catch (err) {
        console.error("Failed to load workspace details:", err);
    }
}

function antigravityChatsWorkspaceHTML() {
    const project = projects.find(item => Number(item.id) === Number(currentProjectId));
    const canCreateProjectChat = Boolean(project?.antigravity_linked);
    const createTitle = canCreateProjectChat
        ? "Neuen Chat im verknüpften Anti-Gravity-Projekt starten"
        : "Dafür zuerst ein GitHub-Repo auswählen und mit einem Anti-Gravity-Projekt verknüpfen";
    return `
        <div class="antigravity-chats-shell">
            <aside class="glass-card antigravity-chat-browser">
                <div class="antigravity-history-header">
                    <div>
                        <p class="antigravity-history-eyebrow">ANTI-GRAVITY APP</p>
                        <h2>Chats</h2>
                        <p>Aktive Conversations direkt öffnen und weiterschreiben.</p>
                    </div>
                    <div class="antigravity-chat-create-actions">
                        <button class="btn btn-secondary btn-xs"
                            onclick="openProjectIde(${Number(currentProjectId) || 0})"
                            ${currentProjectId ? "" : "disabled"}
                            title="Verknüpften Projektordner in der Web-IDE öffnen">&lt;/&gt; Web-IDE</button>
                        <button class="btn btn-secondary btn-xs"
                            onclick="createIntegrityChat('normal')"
                            title="Neue normale Conversation außerhalb eines Projekts">+ Normalchat</button>
                        <button class="btn btn-primary btn-xs"
                            onclick="createIntegrityChat('project')"
                            ${canCreateProjectChat ? "" : "disabled"}
                            title="${escapeHTML(createTitle)}">+ Projektchat</button>
                    </div>
                </div>
                <div class="antigravity-chat-toolbar">
                    <label class="antigravity-history-search">
                        <span aria-hidden="true">⌕</span>
                        <input type="search"
                            value="${escapeHTML(antigravityConversationSearch)}"
                            oninput="updateConversationSearch(this.value)"
                            placeholder="Chats suchen"
                            aria-label="Chats durchsuchen">
                    </label>
                    <label class="antigravity-compact-filter" title="Chat-Bereich filtern">
                        <span class="sr-only">Chat-Bereich</span>
                        <select onchange="setConversationScope(this.value)"
                            aria-label="Chat-Bereich">
                            <option value="active" ${antigravityConversationScope === "active" ? "selected" : ""}>Aktiv</option>
                            <option value="archived" ${antigravityConversationScope === "archived" ? "selected" : ""}>Archiv</option>
                            <option value="all" ${antigravityConversationScope === "all" ? "selected" : ""}>Alle</option>
                        </select>
                    </label>
                    <label class="antigravity-compact-filter" title="Chat-Typ filtern">
                        <span class="sr-only">Chat-Typ</span>
                        <select onchange="setConversationType(this.value)"
                            aria-label="Chat-Typ">
                            <option value="all" ${antigravityConversationType === "all" ? "selected" : ""}>Alle Typen</option>
                            <option value="normal" ${antigravityConversationType === "normal" ? "selected" : ""}>Normal</option>
                            <option value="project" ${antigravityConversationType === "project" ? "selected" : ""}>Projekte</option>
                        </select>
                    </label>
                </div>
                <div id="antigravity-conversation-counts" class="antigravity-conversation-counts">Lade Chats…</div>
                <section class="antigravity-active-agents" aria-labelledby="antigravity-active-agents-title">
                    <div class="antigravity-active-agents-header">
                        <span id="antigravity-active-agents-title">Aktive Agenten</span>
                        <strong id="antigravity-active-agent-count">0</strong>
                    </div>
                    <div id="antigravity-active-agent-list" class="antigravity-active-agent-list">
                        <div class="antigravity-active-agent-empty">Gerade arbeitet kein Agent.</div>
                    </div>
                </section>
                <section class="antigravity-worker-pool" aria-labelledby="antigravity-worker-pool-title">
                    <div class="antigravity-worker-pool-header">
                        <span id="antigravity-worker-pool-title">Anti-Gravity Fenster</span>
                        <strong id="antigravity-worker-capacity">0 / 4</strong>
                    </div>
                    <div id="antigravity-worker-list" class="antigravity-worker-list">
                        <div class="antigravity-active-agent-empty">Fensterstatus wird geladen…</div>
                    </div>
                </section>
                <div id="integrity-chats-list" class="antigravity-conversation-list">
                    <div class="workspace-placeholder placeholder-sm">Lade Chats...</div>
                </div>
            </aside>
            <section id="antigravity-chat-stage" class="glass-card antigravity-chat-stage">
                ${antigravityChatStagePlaceholderHTML()}
            </section>
        </div>
    `;
}

function antigravityChatStagePlaceholderHTML() {
    return `
        <div class="antigravity-chat-stage-placeholder">
            <div class="icon">💬</div>
            <h2>Chat auswählen</h2>
            <p>Öffne links eine aktive Conversation. Verlauf, Modell und Eingabe erscheinen direkt hier.</p>
            <small>Für parallele Arbeit kannst du einen Chat zusätzlich als eigenes Fenster öffnen.</small>
        </div>
    `;
}

function renderAntigravityChatsWorkspace() {
    const root = document.getElementById("antigravity-chats-root");
    if (!root) return;
    const embeddedConvoId = currentEmbeddedConvoId;
    root.innerHTML = antigravityChatsWorkspaceHTML();
    if (embeddedConvoId && chatWindowsState[embeddedConvoId]) {
        mountChatWindowEmbedded(embeddedConvoId);
    }
}

function renderHubHome() {
    const container = document.getElementById("workspace-container");
    if (!container) return;
    container.innerHTML = `
        <div class="glass-card workspace-placeholder placeholder-lg">
            <div class="icon">🍌</div>
            <h3>Anti-Gravity Hub</h3>
            <p class="placeholder-text">Füge links GitHub-Repositories hinzu und verknüpfe sie anschließend mit einem Anti-Gravity-Projekt. Deine aktiven Conversations findest du im Tab „Chats“.</p>
        </div>
    `;
}

function renderPlaceholder() {
    const container = document.getElementById("workspace-container");
    container.innerHTML = `
        <div class="glass-card workspace-placeholder placeholder-lg">
            <div class="icon">🍌</div>
            <h3>Projekt ausgewählt</h3>
            <p class="placeholder-text">Wähle links ein Issue aus oder erstelle ein neues, um fortzufahren.</p>
        </div>
    `;
}

let planCollapsed = false;

function togglePlanCollapse() {
    const collapsible = document.getElementById("plan-panel-collapsible");
    const chevron = document.getElementById("plan-collapse-chevron");
    if (!collapsible) return;
    planCollapsed = !planCollapsed;
    if (planCollapsed) {
        collapsible.style.display = "none";
        if (chevron) chevron.classList.add("collapsed");
    } else {
        collapsible.style.display = "block";
        if (chevron) chevron.classList.remove("collapsed");
    }
}

function renderWorkspace(issue, activeRun, latestRun) {
    const container = document.getElementById("workspace-container");
    const hasActiveRun = !!activeRun;
    const isCompleted = latestRun && latestRun.status === "completed";
    const isDone = !hasActiveRun && latestRun;

    container.innerHTML = `
        <div class="glass-card">
            <div class="flex-between-start run-details-header">
                <div>
                    <h2 class="run-title">🐛 ${escapeHTML(issue.title)}</h2>
                    <p class="run-desc">${escapeHTML(issue.description)}</p>
                </div>
                <div class="flex-align-center-gap">
                    <!-- Run History Dropdown -->
                    <div class="run-history-wrapper">
                        <button class="run-history-btn" onclick="toggleRunHistory(event)">
                            📊 Run-Historie <span class="chevron-icon">▼</span>
                        </button>
                        <div id="run-history-dropdown" class="run-history-dropdown">
                            <div class="dropdown-header">Ausführungs-Verlauf</div>
                            <div id="run-history-list">Lade...</div>
                        </div>
                    </div>
                    <span class="badge badge-${issue.status}">${issue.status}</span>
                </div>
            </div>

            <!-- Controls & Mode Toggle -->
            <div class="run-controls-row">
                <div class="run-buttons-group">
                    <button id="start-run-btn" class="btn btn-primary" onclick="startExecution()" ${hasActiveRun ? 'disabled' : ''}>🤖 Auto-Repair starten</button>
                    <button id="cancel-run-btn" class="btn btn-danger" onclick="cancelExecution()" ${!hasActiveRun ? 'disabled' : ''}>✕ Beenden</button>
                    <button id="reset-issue-btn" class="btn btn-secondary" onclick="resetIssue()" ${hasActiveRun ? 'disabled' : ''} title="Issue zurücksetzen (löscht Chatverlauf &amp; Logs)">🔄 Neustarten</button>
                    <button id="delete-issue-btn" class="btn btn-danger" onclick="deleteIssue()" ${hasActiveRun ? 'disabled' : ''} title="Issue löschen">🗑️ Löschen</button>
                </div>
                <div class="full-auto-container">
                    <label class="switch">
                        <input type="checkbox" id="full-auto-toggle" ${latestRun && latestRun.full_auto === 0 ? '' : 'checked'}>
                        <span class="slider round"></span>
                    </label>
                    <span class="switch-label">Full Auto Mode</span>
                </div>
            </div>

            <!-- Execution tracker -->
            <div id="checkpoint-area" style="display: ${hasActiveRun || latestRun ? 'block' : 'none'};">
                <div class="checkpoint-tracker">
                    <div id="step-started" class="checkpoint-step">
                        <div class="checkpoint-dot">1</div>
                        <div class="checkpoint-label">Start</div>
                    </div>
                    <div id="step-planning" class="checkpoint-step">
                        <div class="checkpoint-dot">2</div>
                        <div class="checkpoint-label">Planning</div>
                    </div>
                    <div id="step-verifying" class="checkpoint-step">
                        <div class="checkpoint-dot">3</div>
                        <div class="checkpoint-label">Verifying</div>
                    </div>
                    <div id="step-completed" class="checkpoint-step">
                        <div class="checkpoint-dot">✓</div>
                        <div class="checkpoint-label">Finished</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Task Board Panel (Kanban) -->
        <div class="glass-card margin-top-md" id="task-board-panel">
            <div class="glass-panel-header class-margin-bottom-md">
                <div class="flex-align-center-gap">
                    <span>📋</span>
                    <h2>Task Board (Agent Looping)</h2>
                </div>
                <button class="btn btn-secondary btn-xs" onclick="openAddSubtaskModal()">+ Task hinzufügen</button>
            </div>

            <div class="kanban-board">
                <div class="kanban-column" id="col-todo">
                    <div class="kanban-column-header">
                        <span>Pendente Aufgaben</span>
                        <span id="todo-count" class="badge">0</span>
                    </div>
                    <div class="kanban-cards" id="cards-todo"></div>
                </div>
                <div class="kanban-column" id="col-running">
                    <div class="kanban-column-header">
                        <span>In Arbeit</span>
                        <span id="running-count" class="badge" style="background: var(--warning)">0</span>
                    </div>
                    <div class="kanban-cards" id="cards-running"></div>
                </div>
                <div class="kanban-column" id="col-completed">
                    <div class="kanban-column-header">
                        <span>Erledigt</span>
                        <span id="completed-count" class="badge" style="background: var(--success)">0</span>
                    </div>
                    <div class="kanban-cards" id="cards-completed"></div>
                </div>
            </div>
        </div>

        <!-- Terminal Logs -->
        <div class="terminal-container" id="terminal-area" style="display: ${hasActiveRun || latestRun ? 'block' : 'none'};">
            <div class="terminal-header">
                <div class="window-controls">
                    <span class="control-dot close"></span>
                    <span class="control-dot minimize"></span>
                    <span class="control-dot expand"></span>
                </div>
                <span class="terminal-title">Execution Terminal Logs</span>
                <div class="flex-align-center-gap">
                    <span id="terminal-status" class="terminal-status-text">Inaktiv</span>
                    <button class="btn-terminal-action" onclick="copyTerminalLogs()" title="Logs kopieren">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                    </button>
                </div>
            </div>
            <div class="terminal-body" id="terminal-body">
                <!-- Log entries -->
            </div>
            <!-- Quick-Action Toolbar (visible when run completed) -->
            <div class="quick-actions" id="quick-actions" style="display: ${isDone ? 'flex' : 'none'};">
                <button class="quick-action-btn btn-preview" id="preview-btn" onclick="openPreview()" title="Lokalen Server starten und Seite im Browser öffnen">
                    🌐 Preview öffnen
                </button>
                <button class="quick-action-btn" onclick="exportLogs()" title="Terminal-Logs als Textdatei herunterladen">
                    📋 Logs exportieren
                </button>
                <button class="quick-action-btn" onclick="startExecution()" title="Neuen KI-Zyklus mit frischem Kontext starten">
                    🔄 Neuer Zyklus
                </button>
                <button class="quick-action-btn" disabled title="Kommt bald">
                    🚀 Deploy
                    <span class="tooltip-text">Coming Soon</span>
                </button>
            </div>
        </div>

        <!-- Follow-Up Chat Box (visible when run is done) -->
        <div class="followup-chat" id="followup-chat" style="display: ${isDone ? 'block' : 'none'};">
            <div class="followup-chat-header">
                <span class="chat-icon">💬</span>
                Follow-Up Nachricht senden
            </div>
            <div class="followup-input-row">
                <textarea class="followup-input" id="followup-input" placeholder="z.B. 'Füge noch einen Footer hinzu' oder 'Ändere die Farben zu Blau'..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendFollowUp();}"></textarea>
                <button class="followup-send-btn" id="followup-send-btn" onclick="sendFollowUp()" title="Nachricht senden">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                </button>
            </div>
        </div>

        <!-- Implementation Plan Panel -->
        <div class="glass-card margin-top-md" id="plan-panel" style="display: none;">
            <div class="plan-header" onclick="togglePlanCollapse()">
                <div class="flex-align-center-gap">
                    <span>📋</span>
                    <h2 class="plan-title">Implementation Plan</h2>
                </div>
                <span id="plan-collapse-chevron" class="plan-chevron ${planCollapsed ? 'collapsed' : ''}">▼</span>
            </div>
            <div id="plan-panel-collapsible" style="display: ${planCollapsed ? 'none' : 'block'};">
                <div class="plan-body" id="plan-body"></div>

                <!-- Review Actions Form -->
                <div id="plan-review-actions" class="plan-review-box" style="display: none;">
                    <h4 class="plan-review-warning">
                        <span>⚠️</span> Plan-Review erforderlich: Bitte gib Feedback oder bestätige den Plan.
                    </h4>
                    <textarea id="plan-feedback-input" class="form-control plan-feedback-textarea" placeholder="Stelle eine Frage oder gib Feedback zum Plan..."></textarea>
                    <div class="flex-gap-sm">
                        <button id="approve-plan-btn" class="btn btn-success" onclick="approvePlan()">Plan freigeben (Approve)</button>
                        <button id="submit-feedback-btn" class="btn btn-secondary" onclick="submitPlanFeedback()">Frage stellen / Feedback senden</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Git Diff and Action panel -->
        <div class="glass-card margin-top-md" id="git-panel" style="display: none;">
            <div class="glass-panel-header class-margin-bottom-md">
                <h2>🔍 Generierter Git-Diff</h2>
                <div class="flex-gap-sm">
                    <button class="btn btn-secondary" onclick="gitDiscard()">Changes verwerfen</button>
                    <button class="btn btn-primary" onclick="gitCommit()">Changes committen</button>
                </div>
            </div>
            <div class="diff-container">
                <div class="diff-body" id="diff-body"></div>
            </div>
        </div>
    `;

    // Load run history for dropdown
    loadRunHistory();

    // Load subtasks for Kanban board
    loadSubtasks();
}

// Trigger Execution
async function startExecution() {
    if (!currentIssueId) return;
    const fullAutoToggle = document.getElementById("full-auto-toggle");
    const fullAuto = fullAutoToggle ? fullAutoToggle.checked : true;

    try {
        const res = await fetch(`/api/issues/${currentIssueId}/runs`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ full_auto: fullAuto })
        });
        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || "Unknown error");
        }
        const data = await res.json();

        // Refresh UI
        loadWorkspaceDetails();
        loadIssues();
    } catch (err) {
        showToast("error", "Reparatur nicht gestartet", err.message);
    }
}

async function approvePlan() {
    if (!activeRunId) return;
    const btn = document.getElementById("approve-plan-btn");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch(`/api/runs/${activeRunId}/approve`, { method: "POST" });
        if (!res.ok) throw new Error("Approval failed");
        loadWorkspaceDetails();
    } catch (err) {
        showToast("error", "Freigabe fehlgeschlagen", err.message);
        if (btn) btn.disabled = false;
    }
}

async function submitPlanFeedback() {
    if (!activeRunId) return;
    const input = document.getElementById("plan-feedback-input");
    const feedback = input ? input.value.trim() : "";
    if (!feedback) {
        showToast("warning", "Feedback fehlt", "Bitte gib ein Feedback oder eine Frage ein.");
        return;
    }
    const btn = document.getElementById("submit-feedback-btn");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch(`/api/runs/${activeRunId}/feedback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ feedback })
        });
        if (!res.ok) throw new Error("Feedback submission failed");
        if (input) input.value = "";
        loadWorkspaceDetails();
    } catch (err) {
        showToast("error", "Feedback nicht gesendet", err.message);
        if (btn) btn.disabled = false;
    }
}

// Cancel Execution
async function cancelExecution() {
    if (!activeRunId) return;
    if (!(await hubConfirm(
        "Möchtest du den laufenden AI-Agenten-Prozess wirklich abbrechen?",
        {title: 'Agentenlauf abbrechen', confirmLabel: 'Lauf abbrechen'},
    ))) return;

    try {
        const res = await fetch(`/api/runs/${activeRunId}/cancel`, { method: "POST" });
        if (res.ok) {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            loadWorkspaceDetails();
            loadIssues();
        }
    } catch (err) {
        console.error("Cancel failed:", err);
    }
}

async function deleteIssue() {
    if (!currentIssueId) return;
    if (!(await hubConfirm(
        "Möchtest du dieses Issue wirklich unwiderruflich löschen? Alle zugehörigen Agenten-Läufe, Logs und Chats werden ebenfalls gelöscht.",
        {title: 'Issue dauerhaft löschen', confirmLabel: 'Issue löschen'},
    ))) {
        return;
    }

    try {
        // Cancel active run if any
        if (activeRunId) {
            await fetch(`/api/runs/${activeRunId}/cancel`, { method: "POST" }).catch(() => {});
        }

        const deleteRes = await fetch(`/api/issues/${currentIssueId}`, { method: "DELETE" });
        if (deleteRes.ok) {
            showToast("success", "Issue gelöscht", "Das Issue und seine zugehörigen Hub-Daten wurden entfernt.");
            currentIssueId = null;
            activeRunId = null;
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            loadIssues();
            renderPlaceholder();
        } else {
            const err = await deleteRes.json();
            showToast("error", "Issue nicht gelöscht", err.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Issue nicht gelöscht", err.message);
    }
}

async function resetIssue() {
    if (!currentIssueId) return;
    if (!(await hubConfirm(
        "Möchtest du dieses Issue wirklich zurücksetzen? Dadurch werden der gesamte Chatverlauf und alle Logs gelöscht und der Status wird auf 'pending' zurückgesetzt.",
        {title: 'Issue zurücksetzen', confirmLabel: 'Zurücksetzen'},
    ))) {
        return;
    }

    try {
        // Cancel active run if any
        if (activeRunId) {
            await fetch(`/api/runs/${activeRunId}/cancel`, { method: "POST" }).catch(() => {});
        }

        const res = await fetch(`/api/issues/${currentIssueId}/reset`, { method: "POST" });
        if (res.ok) {
            showToast("success", "Issue zurückgesetzt", "Status, Chatverlauf und Logs wurden zurückgesetzt.");
            activeRunId = null;
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            loadWorkspaceDetails();
            loadIssues();
        } else {
            const err = await res.json();
            showToast("error", "Issue nicht zurückgesetzt", err.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Issue nicht zurückgesetzt", err.message);
    }
}

// Logs streaming via SSE
function startLogStream(runId) {
    if (eventSource) {
        eventSource.close();
    }

    const terminal = document.getElementById("terminal-body");
    const status = document.getElementById("terminal-status");
    const area = document.getElementById("terminal-area");

    terminal.innerHTML = "";
    status.innerText = "Verbunden (Live)";
    status.style.color = "var(--success)";

    if (area) {
        area.classList.remove("status-error", "status-done");
        area.classList.add("status-live");
    }

    eventSource = new EventSource(`/api/runs/${runId}/logs`);

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            try {
                appendLogLine(data);
            } catch (err) {
                console.error("Error in appendLogLine:", err, "for data:", data);
            }

            // Auto-scroll to bottom
            terminal.scrollTop = terminal.scrollHeight;

            // Periodically refresh the run checkpoint status
            try {
                refreshRunStatus(runId);
            } catch (err) {
                console.error("Error in refreshRunStatus:", err);
            }
        } catch (err) {
            console.error("Error parsing log stream message:", err);
        }
    };

    eventSource.addEventListener("close", () => {
        eventSource.close();
        eventSource = null;
        status.innerText = "Abgeschlossen";
        status.style.color = "var(--text-muted)";

        if (area) {
            area.classList.remove("status-live", "status-error");
            area.classList.add("status-done");
        }

        // Show Quick-Actions and Follow-Up Chat
        const qa = document.getElementById('quick-actions');
        if (qa) qa.style.display = 'flex';
        const fc = document.getElementById('followup-chat');
        if (fc) fc.style.display = 'block';

        // Desktop Notification
        sendDesktopNotification('Run abgeschlossen', 'Der KI-Agent hat die Ausführung beendet.');

        // In-app Toast
        showToast('success', 'Run abgeschlossen', 'Der KI-Agent hat die Ausführung erfolgreich beendet.');

        // Orchestrator: collect last log lines and trigger proactive analysis
        const termBodyEl = document.getElementById('terminal-body');
        let lastLogText = '';
        if (termBodyEl) {
            const logLines = termBodyEl.querySelectorAll('.log-line, .stream-block');
            const recent = Array.from(logLines).slice(-30);
            lastLogText = recent.map(el => el.textContent).join('\n');
        }
        orchestratorProactiveAnalysis('done', lastLogText);

        loadWorkspaceDetails();
        loadIssues();
    });

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        status.innerText = "Verbindung getrennt";
        status.style.color = "var(--error)";

        if (area) {
            area.classList.remove("status-live", "status-done");
            area.classList.add("status-error");
        }
    };
}

function appendLogLine(log) {
    if (!log) return;
    const terminal = document.getElementById("terminal-body");
    if (!terminal) return;

    const level = log.level || "info";
    const message = log.message || "";

    // Handle stream chunks – aggregate into a single block
    if (level === "stream") {
        let block = terminal.querySelector(".stream-block.active");
        if (!block) {
            block = document.createElement("div");
            block.className = "stream-block active";
            block.innerHTML =
                '<span class="stream-label">🧠 Agent denkt...</span>' +
                '<pre class="stream-content"></pre>';
            terminal.appendChild(block);
        }
        block.querySelector(".stream-content").textContent += message;
        terminal.scrollTop = terminal.scrollHeight;
        return;
    }

    // Close any open stream block before rendering a normal entry
    const activeBlock = terminal.querySelector(".stream-block.active");
    if (activeBlock) activeBlock.classList.remove("active");

    const div = document.createElement("div");

    // Parse prefixes to apply specific styling
    let msg = message;
    let extraClass = "";
    if (msg.startsWith("[SYSTEM]")) {
        extraClass = " system";
        let content = msg.slice(8);
        if (content.startsWith("    ")) {
            msg = `<span class="log-cat system invisible">[SYSTEM]</span>` + escapeHTML(content);
        } else {
            msg = `<span class="log-cat system">[SYSTEM]</span> ` + escapeHTML(content);
        }
    } else if (msg.startsWith("[AGENT]")) {
        extraClass = " agent";
        let content = msg.slice(7);
        if (content.startsWith("    ")) {
            msg = `<span class="log-cat agent invisible">[AGENT]</span>` + escapeHTML(content);
        } else {
            msg = `<span class="log-cat agent">[AGENT]</span> ` + escapeHTML(content);
        }
    } else if (msg.startsWith("[TESTS]")) {
        extraClass = " tests";
        let content = msg.slice(7);
        if (content.startsWith("    ")) {
            msg = `<span class="log-cat tests invisible">[TESTS]</span>` + escapeHTML(content);
        } else {
            msg = `<span class="log-cat tests">[TESTS]</span> ` + escapeHTML(content);
        }
    } else {
        msg = escapeHTML(msg);
    }

    // Post-process: make file paths clickable (matches '- [A] path', '- [M] path', '- [D] path')
    msg = msg.replace(/- \[(A|M|D)\] (.+)/g, (match, status, filePath) => {
        const trimmedPath = filePath.trim();
        const isImage = /\.(png|jpg|jpeg|gif|svg|webp|bmp|ico|avif)$/i.test(trimmedPath);
        const icon = isImage ? '🖼️' : '📄';
        const statusLower = status.toLowerCase();
        const safeDataPath = trimmedPath.replace(/'/g, '\'');
        return `- <span class="log-file-status status-${statusLower}">${status}</span>` +
               `<span class="log-file-link" data-filepath="${safeDataPath}" title="Klicke für Vorschau: ${trimmedPath}">` +
               `<span class="file-link-icon">${icon}</span>${trimmedPath}</span>`;
    });

    div.className = `log-entry ${level}${extraClass}`;

    const timestamp = log.timestamp || new Date().toISOString();
    const time = new Date(timestamp).toLocaleTimeString();
    div.innerHTML = `<span class="log-time">[${time}]</span> ${msg}`;
    terminal.appendChild(div);
}

// ============================================================
// File Preview System
// ============================================================

// Event delegation for clickable file links in the terminal
document.addEventListener('click', (e) => {
    const link = e.target.closest('.log-file-link');
    if (!link) return;
    const filePath = link.dataset.filepath;
    if (filePath) previewFile(filePath);
});

// Close preview on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const modal = document.getElementById('file-preview-modal');
        if (modal && modal.classList.contains('active')) {
            closeFilePreview();
        }
    }
});

/**
 * Get the current project's filesystem path.
 */
function getCurrentProjectPath() {
    if (!currentProjectId || !projects.length) return null;
    const proj = projects.find(p => p.id === currentProjectId);
    return proj ? proj.path : null;
}

/**
 * Format file size in human-readable form.
 */
function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Open the file preview lightbox modal and load file content from the API.
 * @param {string} relativePath - Relative file path within the project
 */
async function previewFile(relativePath) {
    const projectPath = getCurrentProjectPath();
    if (!projectPath) {
        showToast('warning', 'Kein Projekt ausgewählt', 'Bitte wähle ein Projekt, um Dateivorschauen zu nutzen.');
        return;
    }

    const modal = document.getElementById('file-preview-modal');
    const body = document.getElementById('file-preview-body');
    const filenameEl = document.getElementById('file-preview-filename');
    const iconEl = document.getElementById('file-preview-icon');
    const sizeEl = document.getElementById('file-preview-size');

    // Extract filename for display
    const basename = relativePath.split('/').pop().split('\\').pop();
    const isImage = /\.(png|jpg|jpeg|gif|svg|webp|bmp|ico|avif)$/i.test(basename);

    // Set header info
    filenameEl.textContent = relativePath;
    iconEl.textContent = isImage ? '🖼️' : '📄';
    sizeEl.textContent = '';

    // Show loading state
    body.innerHTML = `
        <div class="file-preview-loading">
            <div class="file-preview-spinner"></div>
            <span>Lade Vorschau...</span>
        </div>
    `;

    // Activate modal
    modal.classList.add('active');

    try {
        const params = new URLSearchParams({
            project_path: projectPath,
            file_path: relativePath,
        });
        const res = await fetch(`/api/files/preview?${params}`);
        const data = await res.json();

        if (data.error) {
            body.innerHTML = `
                <div class="file-preview-fallback">
                    <span class="fallback-icon">⚠️</span>
                    <span class="fallback-text">${escapeHTML(data.error)}</span>
                </div>
            `;
            return;
        }

        // Update size display
        if (data.size) {
            sizeEl.textContent = `(${formatFileSize(data.size)})`;
        }

        if (data.type === 'image') {
            iconEl.textContent = '🖼️';
            body.innerHTML = `<img src="${data.content}" alt="${escapeHTML(basename)}" />`;

        } else if (data.type === 'text') {
            iconEl.textContent = '📄';
            const lines = data.content.split('\n');
            const numbered = lines.map((line, i) => {
                const num = `<span class="line-number">${i + 1}</span>`;
                return `${num}${escapeHTML(line)}`;
            }).join('\n');
            body.innerHTML = `<pre>${numbered}</pre>`;

        } else if (data.type === 'binary') {
            iconEl.textContent = '📦';
            body.innerHTML = `
                <div class="file-preview-fallback">
                    <span class="fallback-icon">📦</span>
                    <span class="fallback-text">${escapeHTML(data.message || 'Vorschau nicht verfügbar.')}</span>
                </div>
            `;
        }

    } catch (err) {
        console.error('File preview error:', err);
        body.innerHTML = `
            <div class="file-preview-fallback">
                <span class="fallback-icon">❌</span>
                <span class="fallback-text">Fehler beim Laden der Datei: ${escapeHTML(err.message)}</span>
            </div>
        `;
    }
}

/**
 * Close the file preview lightbox modal.
 */
function closeFilePreview(event) {
    // If called from overlay click, only close if target is the overlay itself
    if (event && event.target && !event.target.classList.contains('file-preview-overlay')) {
        return;
    }
    const modal = document.getElementById('file-preview-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

async function refreshRunStatus(runId) {
    try {
        const res = await fetch(`/api/runs/${runId}`);
        const run = await res.json();
        updateCheckpointUI(run.checkpoint, run.status);

        // Show implementation plan if it exists
        const planPanel = document.getElementById("plan-panel");
        const planBody = document.getElementById("plan-body");
        if (planPanel && planBody) {
            if (run.implementation_plan) {
                planPanel.style.display = "block";
                planBody.innerHTML = renderMarkdown(run.implementation_plan);
            } else {
                planPanel.style.display = "none";
            }
        }

        const reviewActions = document.getElementById("plan-review-actions");
        if (reviewActions) {
            reviewActions.style.display = run.status === "paused" ? "block" : "none";
        }

        const statusEl = document.getElementById("terminal-status");
        if (statusEl && run.status === "paused") {
            statusEl.innerText = "Pausiert - Review erforderlich";
            statusEl.style.color = "var(--warning)";
        }
    } catch (err) {
        console.error("Failed to check status:", err);
    }
}

function updateCheckpointUI(checkpoint, status) {
    const steps = ["started", "planning", "verifying", "completed"];
    const currentIdx = steps.indexOf(checkpoint);

    steps.forEach((step, idx) => {
        const el = document.getElementById(`step-${step}`);
        if (!el) return;

        el.classList.remove("active", "completed");

        // Reset custom styles from failed/cancelled runs
        const dot = el.querySelector(".checkpoint-dot");
        if (dot) {
            dot.style.borderColor = "";
            dot.style.background = "";
            dot.style.color = "";
        }

        if (idx < currentIdx) {
            el.classList.add("completed");
        } else if (idx === currentIdx) {
            if (status === "running") {
                el.classList.add("active");
            } else if (status === "completed") {
                el.classList.add("completed");
            } else if (status === "failed") {
                el.classList.add("active");
                if (dot) {
                    dot.style.borderColor = "var(--error)";
                    dot.style.background = "var(--error)";
                    dot.style.color = "white";
                }
            } else if (status === "cancelled") {
                el.classList.add("active");
                if (dot) {
                    dot.style.borderColor = "var(--text-muted)";
                    dot.style.background = "rgba(255, 255, 255, 0.1)";
                    dot.style.color = "var(--text-muted)";
                }
            }
        }
    });
}

function renderStaticRun(run) {
    const area = document.getElementById("terminal-area");
    if (area) {
        area.className = "terminal-container status-" + run.status;
    }

    // Fill terminal logs and load plan
    fetch(`/api/runs/${run.id}`)
        .then(res => res.json())
        .then((runData) => {
            // Show implementation plan if it exists
            const planPanel = document.getElementById("plan-panel");
            const planBody = document.getElementById("plan-body");
            if (planPanel && planBody) {
                if (runData.implementation_plan) {
                    planPanel.style.display = "block";
                    planBody.innerHTML = renderMarkdown(runData.implementation_plan);
                } else {
                    planPanel.style.display = "none";
                }
            }

            const reviewActions = document.getElementById("plan-review-actions");
            if (reviewActions) {
                reviewActions.style.display = runData.status === "paused" ? "block" : "none";
            }

            const statusEl = document.getElementById("terminal-status");
            if (statusEl && runData.status === "paused") {
                statusEl.innerText = "Pausiert - Review erforderlich";
                statusEl.style.color = "var(--warning)";
            }

            // Load logs
            fetch(`/api/runs/${run.id}/logs`)
                .then(res => res.text())
                .then(text => {
                    const terminal = document.getElementById("terminal-body");
                    terminal.innerHTML = "";
                    const lines = text.split("\n\n");
                    lines.forEach(line => {
                        if (line.startsWith("data: ")) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                appendLogLine(data);
                            } catch (e) {}
                        }
                    });
                    terminal.scrollTop = terminal.scrollHeight;
                });
        });

    updateCheckpointUI(run.checkpoint, run.status);

    // Display Diff panel if diff exists
    const gitPanel = document.getElementById("git-panel");
    const diffBody = document.getElementById("diff-body");

    if (run.diff && run.diff.trim().length > 0) {
        gitPanel.style.display = "block";
        diffBody.innerHTML = formatDiff(run.diff);
    } else {
        gitPanel.style.display = "none";
    }
}

// Format Git Diff for HTML rendering (file-card based Diff Explorer)
function formatDiff(diffText) {
    if (!diffText || !diffText.trim()) return '<div class="workspace-placeholder">Keine Änderungen im Diff.</div>';

    // Split the diff text by "diff --git"
    const files = diffText.split("diff --git ");
    let html = "";

    // The first item in the split might be empty or preamble, skip it if it doesn't contain "a/"
    for (let i = 0; i < files.length; i++) {
        const fileDiff = files[i].trim();
        if (!fileDiff) continue;

        // Extract filename
        // Usually looks like: "a/src/file.py b/src/file.py"
        const lines = fileDiff.split("\n");
        const headerLine = lines[0];
        let filename = "Unbekannte Datei";

        const fileMatch = headerLine.match(/b\/(\S+)/) || headerLine.match(/a\/(\S+)/);
        if (fileMatch) {
            filename = fileMatch[1];
        }

        let linesHtml = "";
        for (let j = 1; j < lines.length; j++) {
            const line = lines[j];
            let lineClass = "diff-line";

            if (line.startsWith("+") && !line.startsWith("+++")) {
                lineClass += " diff-line-addition";
            } else if (line.startsWith("-") && !line.startsWith("---")) {
                lineClass += " diff-line-deletion";
            } else if (line.startsWith("@@")) {
                lineClass += " diff-line-header";
            }

            linesHtml += `<span class="${lineClass}">${escapeHTML(line)}</span>`;
        }

        html += `
            <div class="diff-file-card">
                <div class="diff-file-header">
                    <span class="diff-file-title">📄 ${escapeHTML(filename)}</span>
                </div>
                <div class="diff-file-body">${linesHtml}</div>
            </div>
        `;
    }

    return html;
}

// Git control actions
function gitCommit() {
    openCommitModal();
}

async function gitDiscard() {
    if (!currentProjectId) return;
    if (!(await hubConfirm(
        "Möchtest du alle Änderungen im Sandbox-Branch wirklich unwiderruflich verwerfen?",
        {title: 'Änderungen verwerfen', confirmLabel: 'Verwerfen'},
    ))) return;

    try {
        const res = await fetch("/api/git/discard", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId })
        });
        const data = await res.json();
        if (data.success) {
            showToast("success", "Änderungen verworfen", "Der Sandbox-Branch ist wieder sauber.");
            loadWorkspaceDetails();
        } else {
            showToast("error", "Änderungen nicht verworfen", data.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Änderungen nicht verworfen", err.message);
    }
}

// ============================================================
// Lessons Learned Logic
// ============================================================
async function loadLessons() {
    try {
        const res = await fetch("/api/lessons");
        const data = await res.json();
        lessons = data.lessons || [];
        renderLessons();
    } catch (err) {
        console.error("Failed to load lessons:", err);
    }
}

function renderLessons() {
    const grid = document.getElementById("lessons-grid");
    if (lessons.length === 0) {
        grid.innerHTML = `<div class="workspace-placeholder" style="min-height: 200px; grid-column: 1/-1;">Keine gelernten Techniken gefunden.</div>`;
        return;
    }

    grid.innerHTML = lessons.map(l => `
        <div class="lesson-card">
            <div class="lesson-title">💡 ${escapeHTML(l.technique)}</div>
            <div class="lesson-solution">${escapeHTML(l.solution)}</div>
            <div class="lesson-date">
                Erfasst am: ${new Date(l.created_at).toLocaleDateString()}
            </div>
        </div>
    `).join("");
}

// ============================================================
// File Browser Picker Logic
// ============================================================
function openFileBrowser() {
    currentBrowserPath = "";
    loadBrowserDirectory("");
    openModal("file-browser-modal");
}

async function loadBrowserDirectory(path) {
    const pathEl = document.getElementById("browser-path");
    const listEl = document.getElementById("browser-list");
    pathEl.innerText = "Lade Verzeichnis...";
    listEl.innerHTML = "";

    try {
        const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        const data = await res.json();

        if (data.error) {
            pathEl.innerText = "Fehler: " + data.error;
            return;
        }

        currentBrowserPath = data.path;
        pathEl.innerText = currentBrowserPath;

        let html = "";

        // Add parent directory link if exists
        if (data.parent) {
            html += `
                <div class="browser-item parent-dir" onclick="loadBrowserDirectory('${data.parent.replace(/\\/g, '\\\\')}')">
                    <span class="icon">⬆️</span> .. (Übergeordnetes Verzeichnis)
                </div>
            `;
        }

        // Filter folder elements only to act as a directory picker
        const folders = data.items.filter(i => i.type === "folder");

        if (folders.length === 0) {
            html += `<div class="browser-empty">Keine Unterverzeichnisse gefunden.</div>`;
        } else {
            html += folders.map(i => `
                <div class="browser-item folder" onclick="loadBrowserDirectory('${i.path.replace(/\\/g, '\\\\')}')">
                    <span class="icon">📁</span> ${escapeHTML(i.name)}
                </div>
            `).join("");
        }

        listEl.innerHTML = html;
    } catch (err) {
        pathEl.innerText = "Fehler beim Laden.";
        console.error(err);
    }
}

function selectBrowserPath() {
    if (currentBrowserPath) {
        document.getElementById("project-path").value = currentBrowserPath;
        closeModal("file-browser-modal");
    }
}

// ============================================================
// Utilities
// ============================================================
function displayString(value, pretty = false) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
        return String(value);
    }
    if (value instanceof Error) {
        return value.stack || value.message || String(value);
    }
    if (typeof value === "object") {
        const seen = new WeakSet();
        try {
            return JSON.stringify(value, (_key, nested) => {
                if (typeof nested === "bigint") return String(nested);
                if (typeof nested === "object" && nested !== null) {
                    if (seen.has(nested)) return "[Circular]";
                    seen.add(nested);
                }
                return nested;
            }, pretty ? 2 : 0);
        } catch (_error) {
            // Fall through to the final String conversion.
        }
    }
    try {
        return String(value);
    } catch (_error) {
        return "[Unlesbarer Wert]";
    }
}

function escapeHTML(value) {
    const str = displayString(value);
    if (!str) return "";
    return str.replace(/[&<>'"]/g,
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// Copy terminal logs utility
function copyTerminalLogs() {
    const terminalBody = document.getElementById("terminal-body");
    if (!terminalBody) return;

    let text = "";
    terminalBody.querySelectorAll(".log-entry, .stream-block").forEach(el => {
        if (el.classList.contains("log-entry")) {
            text += el.innerText + "\n";
        } else if (el.classList.contains("stream-block")) {
            const content = el.querySelector(".stream-content");
            if (content) {
                text += "[Agent denkt...]\n" + content.innerText + "\n";
            }
        }
    });

    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector(".btn-terminal-action");
        if (btn) {
            const originalHTML = btn.innerHTML;
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
            setTimeout(() => { btn.innerHTML = originalHTML; }, 2000);
        }
    }).catch(err => {
        console.error("Kopieren fehlgeschlagen: ", err);
    });
}

// Markdown-to-HTML formatter for implementation plans
function renderMarkdown(md) {
    if (!md) return "";

    // Escape HTML first to prevent XSS
    let html = escapeHTML(md);

    // Replace headings
    html = html.replace(/^### (.*?)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.*?)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.*?)$/gm, '<h2>$1</h2>');

    // Bold: **text** -> <strong>text</strong>
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // GitHub Alerts: > [!IMPORTANT] / [!WARNING] / [!NOTE]
    html = html.replace(/^&gt;\s*\[!IMPORTANT\](.*?)$/gim, '<div class="alert-important"><strong>⚠️ Wichtig:</strong>$1</div>');
    html = html.replace(/^&gt;\s*\[!WARNING\](.*?)$/gim, '<div class="alert-warning"><strong>⚠️ Warnung:</strong>$1</div>');
    html = html.replace(/^&gt;\s*\[!NOTE\](.*?)$/gim, '<div class="alert-note"><strong>ℹ️ Hinweis:</strong>$1</div>');

    // Code blocks: ```language ... ```
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

    // Inline code: `code`
    html = html.replace(/`(.*?)`/g, '<code>$1</code>');

    // Lists and checkboxes
    html = html.replace(/^\s*-\s+`\[\s*\]`\s+(.*?)$/gm, '<li class="checkbox-item unchecked"><input type="checkbox" disabled>$1</li>');
    html = html.replace(/^\s*-\s+`\[x\]`\s+(.*?)$/gm, '<li class="checkbox-item checked"><input type="checkbox" checked disabled>$1</li>');
    html = html.replace(/^\s*-\s+(.*?)$/gm, '<li>$1</li>');

    // Process paragraphs
    const lines = html.split('\n');
    let finalHtml = "";
    let inList = false;

    for (let line of lines) {
        if (line.trim().startsWith('<li')) {
            if (!inList) {
                finalHtml += '<ul>';
                inList = true;
            }
            finalHtml += line;
        } else {
            if (inList) {
                finalHtml += '</ul>';
                inList = false;
            }
            if (line.trim().startsWith('<h') || line.trim().startsWith('<pre') || line.trim().startsWith('</pre') || line.trim().startsWith('<div') || line.trim().startsWith('</div')) {
                finalHtml += line + '\n';
            } else if (line.trim().length > 0) {
                finalHtml += `<p>${line}</p>`;
            } else {
                finalHtml += '\n';
            }
        }
    }
    if (inList) {
        finalHtml += '</ul>';
    }

    return finalHtml;
}

// ============================================================
// Preview Server
// ============================================================
async function openPreview() {
    if (!currentProjectId) {
        showToast('error', 'Fehler', 'Kein Projekt ausgewählt.');
        return;
    }
    const btn = document.getElementById('preview-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Starte Server...';
    }

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/preview`, { method: 'POST' });
        const data = await res.json();

        if (data.url) {
            window.open(data.url, '_blank');
            showToast('success', 'Preview gestartet', `Server läuft auf ${data.url}`);
            if (btn) {
                btn.innerHTML = '🟢 Preview aktiv';
                btn.classList.add('active');
                btn.disabled = false;
                btn.onclick = () => stopPreview();
            }
        } else {
            throw new Error(data.error || 'Unbekannter Fehler');
        }
    } catch (err) {
        showToast('error', 'Preview Fehler', err.message);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🌐 Preview öffnen';
        }
    }
}

async function stopPreview() {
    if (!currentProjectId) return;
    const btn = document.getElementById('preview-btn');

    try {
        await fetch(`/api/projects/${currentProjectId}/preview/stop`, { method: 'POST' });
        showToast('success', 'Preview gestoppt', 'Der lokale Server wurde beendet.');
    } catch (err) {
        console.error('Stop preview failed:', err);
    }

    if (btn) {
        btn.innerHTML = '🌐 Preview öffnen';
        btn.classList.remove('active');
        btn.onclick = () => openPreview();
    }
}

// ============================================================
// Follow-Up Chat
// ============================================================
async function sendFollowUp() {
    const input = document.getElementById('followup-input');
    const btn = document.getElementById('followup-send-btn');
    const message = input ? input.value.trim() : '';

    if (!message) {
        showToast('error', 'Leere Nachricht', 'Bitte gib eine Follow-Up Nachricht ein.');
        return;
    }

    if (!currentIssueId) return;

    // Find the latest completed run ID (same run will be continued)
    let targetRunId = activeRunId;
    if (!targetRunId) {
        try {
            const res = await fetch(`/api/issues/${currentIssueId}/runs`);
            const data = await res.json();
            const runs = data.runs || [];
            const completed = runs.find(r => r.status !== 'running');
            if (completed) targetRunId = completed.id;
        } catch (e) {
            console.error('Failed to find run for follow-up:', e);
        }
    }

    if (!targetRunId) {
        showToast('error', 'Kein Run', 'Kein abgeschlossener Run gefunden für Follow-Up.');
        return;
    }

    if (btn) btn.disabled = true;
    if (input) input.disabled = true;

    const fullAutoToggle = document.getElementById('full-auto-toggle');
    const fullAuto = fullAutoToggle ? fullAutoToggle.checked : true;

    try {
        const res = await fetch(`/api/runs/${targetRunId}/followup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, full_auto: fullAuto })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || 'Unbekannter Fehler');
        }

        const data = await res.json();
        showToast('success', 'Follow-Up fortgesetzt', `Run #${data.run_id} wird mit deiner Nachricht fortgesetzt.`);

        if (input) input.value = '';

        // === DYNAMIC UI UPDATE (no full re-render) ===

        // 1. Hide follow-up chat and quick actions immediately
        const followupChat = document.getElementById('followup-chat');
        if (followupChat) followupChat.style.display = 'none';
        const quickActions = document.getElementById('quick-actions');
        if (quickActions) quickActions.style.display = 'none';

        // 2. Update button states
        const startBtn = document.getElementById('start-run-btn');
        if (startBtn) startBtn.disabled = true;
        const cancelBtn = document.getElementById('cancel-run-btn');
        if (cancelBtn) cancelBtn.disabled = false;

        // 3. Set the active run ID to the SAME run (continued)
        activeRunId = data.run_id;

        // 4. Show terminal area and start live log stream
        const terminalArea = document.getElementById('terminal-area');
        if (terminalArea) {
            terminalArea.style.display = 'block';
            terminalArea.classList.remove('status-done', 'status-error');
            terminalArea.classList.add('status-live');
        }

        // 5. Start SSE stream for the SAME run (appends new logs to existing terminal)
        startLogStream(data.run_id);

        // 6. Update issue list in sidebar (status changes to running)
        loadIssues();

    } catch (err) {
        showToast('error', 'Follow-Up Fehler', err.message);
    } finally {
        if (btn) btn.disabled = false;
        if (input) input.disabled = false;
    }
}

// ============================================================
// Export Logs
// ============================================================
function exportLogs() {
    const terminalBody = document.getElementById('terminal-body');
    if (!terminalBody) return;

    let text = `Anti-Gravity Hub — Execution Logs\nExportiert: ${new Date().toLocaleString()}\n${'='.repeat(60)}\n\n`;

    terminalBody.querySelectorAll('.log-entry, .stream-block').forEach(el => {
        if (el.classList.contains('log-entry')) {
            text += el.innerText + '\n';
        } else if (el.classList.contains('stream-block')) {
            const content = el.querySelector('.stream-content');
            if (content) {
                text += '[Agent denkt...]\n' + content.innerText + '\n';
            }
        }
    });

    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `antigravity-logs-issue-${currentIssueId || 'unknown'}-${Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('success', 'Logs exportiert', 'Die Logdatei wurde heruntergeladen.');
}

// ============================================================
// Run History Dropdown
// ============================================================
function toggleRunHistory(event) {
    event.stopPropagation();
    const dd = document.getElementById('run-history-dropdown');
    if (dd) dd.classList.toggle('open');
}

async function loadRunHistory() {
    if (!currentIssueId) return;
    const listEl = document.getElementById('run-history-list');
    if (!listEl) return;

    try {
        const res = await fetch(`/api/issues/${currentIssueId}/runs`);
        const data = await res.json();
        const runs = data.runs || [];

        if (runs.length === 0) {
            listEl.innerHTML = '<div style="padding: 0.75rem; color: var(--text-muted); font-size: 0.8rem;">Noch keine Runs vorhanden.</div>';
            return;
        }

        listEl.innerHTML = runs.map(r => {
            const date = new Date(r.started_at).toLocaleString('de-DE', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
            const isSelected = r.id === activeRunId || (runs[0].id === r.id && !activeRunId);
            return `
                <div class="run-history-item ${isSelected ? 'selected' : ''}" onclick="selectHistoryRun(${r.id})">
                    <div>
                        <span class="run-id">Run #${r.id}</span>
                        <div class="run-meta">${date} · ${r.checkpoint || '—'}</div>
                    </div>
                    <span class="run-status-dot status-${r.status}"></span>
                </div>
            `;
        }).join('');
    } catch (err) {
        listEl.innerHTML = '<div style="padding: 0.75rem; color: var(--error); font-size: 0.8rem;">Fehler beim Laden.</div>';
    }
}

function selectHistoryRun(runId) {
    const dd = document.getElementById('run-history-dropdown');
    if (dd) dd.classList.remove('open');

    // Load this run's static data
    fetch(`/api/runs/${runId}`)
        .then(res => res.json())
        .then(run => {
            activeRunId = null; // Not an active run, just viewing history
            renderStaticRun(run);
        })
        .catch(err => console.error('Failed to load history run:', err));
}

// ============================================================
// Desktop Notifications
// ============================================================
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function sendDesktopNotification(title, body) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (document.visibilityState === 'visible') return; // Only when tab is in background

    try {
        const n = new Notification('🍌 Anti-Gravity Hub', {
            body: `${title}: ${body}`,
            icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🍌</text></svg>',
            tag: 'antigravity-run'
        });
        n.onclick = () => {
            window.focus();
            n.close();
        };
    } catch (e) {
        console.error('Notification failed:', e);
    }
}

// ============================================================
// Toast Notifications (In-App)
// ============================================================
function showToast(type, title, message, duration = 5000) {
    // Remove existing toast if any
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();

    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    const toast = document.createElement('div');
    toast.className = `notification-toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <div class="toast-body">
            <div class="toast-title">${escapeHTML(title)}</div>
            <div class="toast-msg">${escapeHTML(message)}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    document.body.appendChild(toast);

    // Auto-remove after duration
    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.animation = 'toast-slide-out 0.3s ease forwards';
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}

let hubConfirmResolver = null;
let hubConfirmAccepted = false;
let hubConfirmReturnFocus = null;

function ensureHubConfirmDialog() {
    let dialog = document.getElementById("hub-confirm-dialog");
    if (dialog) return dialog;

    dialog = document.createElement("dialog");
    dialog.id = "hub-confirm-dialog";
    dialog.className = "hub-confirm-dialog";
    dialog.setAttribute("aria-labelledby", "hub-confirm-title");
    dialog.setAttribute("aria-describedby", "hub-confirm-message");
    dialog.innerHTML = `
        <form method="dialog" class="hub-confirm-card">
            <div class="hub-confirm-kicker">ANTI-GRAVITY HUB</div>
            <h2 id="hub-confirm-title">Aktion bestätigen</h2>
            <p id="hub-confirm-message"></p>
            <div class="hub-confirm-actions">
                <button type="button" class="btn btn-secondary" data-hub-confirm="cancel">Abbrechen</button>
                <button type="button" class="btn btn-danger" data-hub-confirm="accept">Bestätigen</button>
            </div>
        </form>
    `;
    dialog.querySelector('[data-hub-confirm="cancel"]').addEventListener("click", () => closeHubConfirmDialog(false));
    dialog.querySelector('[data-hub-confirm="accept"]').addEventListener("click", () => closeHubConfirmDialog(true));
    dialog.addEventListener("cancel", event => {
        event.preventDefault();
        closeHubConfirmDialog(false);
    });
    dialog.addEventListener("click", event => {
        if (event.target === dialog) closeHubConfirmDialog(false);
    });
    dialog.addEventListener("close", () => {
        const resolve = hubConfirmResolver;
        hubConfirmResolver = null;
        if (resolve) resolve(hubConfirmAccepted);
        if (hubConfirmReturnFocus?.isConnected) hubConfirmReturnFocus.focus();
        hubConfirmReturnFocus = null;
    });
    document.body.appendChild(dialog);
    return dialog;
}

function closeHubConfirmDialog(accepted) {
    const dialog = document.getElementById("hub-confirm-dialog");
    if (!dialog?.open) return;
    hubConfirmAccepted = Boolean(accepted);
    dialog.close();
}

function hubConfirm(message, options = {}) {
    const dialog = ensureHubConfirmDialog();
    if (dialog.open) return Promise.resolve(false);
    hubConfirmAccepted = false;
    hubConfirmReturnFocus = document.activeElement;
    dialog.querySelector("#hub-confirm-title").textContent = options.title || "Aktion bestätigen";
    dialog.querySelector("#hub-confirm-message").textContent = String(message || "");
    const accept = dialog.querySelector('[data-hub-confirm="accept"]');
    accept.textContent = options.confirmLabel || "Bestätigen";
    accept.classList.toggle("btn-danger", options.danger !== false);
    accept.classList.toggle("btn-primary", options.danger === false);
    dialog.showModal();
    requestAnimationFrame(() => dialog.querySelector('[data-hub-confirm="cancel"]')?.focus());
    return new Promise(resolve => {
        hubConfirmResolver = resolve;
    });
}

// ============================================================
// Orchestrator Sidebar Logic
// ============================================================

let orchestratorBusy = false;

function setOrchestratorDot(state) {
    const dot = document.getElementById('orchestrator-status-dot');
    if (!dot) return;
    dot.className = 'orch-dot orch-dot-' + state;
    dot.title = state === 'thinking' ? 'Denkt nach...' : state === 'done' ? 'Fertig' : 'Bereit';
}

// Cached active chat meta (updated on run completion)
window._orchActiveChatMeta = null;

async function fetchActiveChatMeta() {
    try {
        const r = await fetch('/api/chats/active');
        if (r.ok) {
            window._orchActiveChatMeta = await r.json();
        }
    } catch (e) {
        // CDP not connected – ignore, meta stays null
    }
}

function buildOrchestratorContext() {
    const project = projects.find(p => p.id === currentProjectId) || {};
    const currentIssue = issues.find(i => i.id === currentIssueId) || {};
    const lastRunLogs = window._orchLastRunLogs || '';
    const runStatus = window._orchLastRunStatus || 'unknown';
    const chatMeta = window._orchActiveChatMeta || {};

    return {
        project: { name: project.name || '', path: project.path || '' },
        issues: issues.map(i => ({ id: i.id, title: i.title, status: i.status })),
        current_issue: {
            id: currentIssue.id,
            title: currentIssue.title || '',
            description: currentIssue.description || '',
            status: currentIssue.status || ''
        },
        last_logs: lastRunLogs,
        run_status: runStatus,
        // Live chat context from CDP
        active_chat: {
            chat_id: chatMeta.chat_id || null,
            title: chatMeta.title || '',
            model: chatMeta.model || '',
            message_count: chatMeta.message_count || 0,
            is_running: chatMeta.is_running || false,
            is_streaming: chatMeta.is_streaming || false
        }
    };
}

function clearOrchestratorWelcomeIfNeeded() {
    const welcome = document.getElementById('orchestrator-welcome');
    if (welcome) {
        welcome.remove();
    }
}

function showOrchestratorWelcome() {
    const msgs = document.getElementById('orchestrator-messages');
    if (!msgs) return;
    msgs.innerHTML = `
        <div id="orchestrator-welcome" class="orch-welcome-panel">
            <div class="orch-welcome-header">
                <span class="orch-welcome-badge">AI Co-Pilot</span>
                <h3>Wie kann ich helfen?</h3>
                <p>Der Orchestrator analysiert deine Agent-Runs, wertet Logs aus und macht proaktive Verbesserungsvorschläge.</p>
            </div>
            <div class="orch-features-list">
                <div class="orch-feature-item">
                    <span class="orch-feature-icon">🔍</span>
                    <div class="orch-feature-text">
                        <strong>Auto-Analyse</strong>
                        <span>Bewertet Läufe und Test-Ergebnisse nach jedem Run.</span>
                    </div>
                </div>
                <div class="orch-feature-item">
                    <span class="orch-feature-icon">💡</span>
                    <div class="orch-feature-text">
                        <strong>Ein-Klick-Vorschläge</strong>
                        <span>Startet direkte Code-Anpassungen per Tastendruck.</span>
                    </div>
                </div>
                <div class="orch-feature-item">
                    <span class="orch-feature-icon">💬</span>
                    <div class="orch-feature-text">
                        <strong>Kontext-Sensitiv</strong>
                        <span>Kennt dein aktives Issue, Logs und geöffnete Dateien.</span>
                    </div>
                </div>
            </div>
            <div class="orch-quick-prompts">
                <div class="orch-quick-prompts-title">Schnellstart-Fragen</div>
                <button class="orch-quick-prompt-btn" onclick="sendOrchestratorMessage('Analysiere den Status des aktuellen Issues und mach konkrete Vorschläge.')">
                    <span class="orch-quick-prompt-icon">📋</span>
                    <span class="orch-quick-prompt-text">Wie löse ich das active Issue?</span>
                    <span class="orch-quick-prompt-arrow">→</span>
                </button>
                <button class="orch-quick-prompt-btn" onclick="sendOrchestratorMessage('Welche Fehler oder Warnungen gibt es im letzten Run? Zeige Details.')">
                    <span class="orch-quick-prompt-icon">🐛</span>
                    <span class="orch-quick-prompt-text">Fehler im letzten Run?</span>
                    <span class="orch-quick-prompt-arrow">→</span>
                </button>
                <button class="orch-quick-prompt-btn" onclick="sendOrchestratorMessage('Erkläre mir die Ordnerstruktur und die Architektur dieses Projekts.')">
                    <span class="orch-quick-prompt-icon">🗺️</span>
                    <span class="orch-quick-prompt-text">Projekt-Architektur?</span>
                    <span class="orch-quick-prompt-arrow">→</span>
                </button>
            </div>
        </div>
    `;
}

function renderOrchestratorMessage(content, type) {
    const msgs = document.getElementById('orchestrator-messages');
    if (!msgs) return;
    clearOrchestratorWelcomeIfNeeded();
    const div = document.createElement('div');
    div.className = `orch-msg orch-msg-${type}`;
    const inner = document.createElement('div');
    inner.className = 'orch-msg-content';
    inner.textContent = content;
    div.appendChild(inner);
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
}

function renderOrchestratorSuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) return;
    const msgs = document.getElementById('orchestrator-messages');
    if (!msgs) return;
    clearOrchestratorWelcomeIfNeeded();

    const labelEl = document.createElement('div');
    labelEl.className = 'orch-msg orch-msg-assistant';
    const lbl = document.createElement('div');
    lbl.className = 'orch-suggestions-label';
    lbl.textContent = '▶ Direkt ausführen:';
    labelEl.appendChild(lbl);
    msgs.appendChild(labelEl);

    suggestions.forEach(s => {
        const btn = document.createElement('button');
        btn.className = 'orch-suggestion';
        btn.innerHTML = `<span class="orch-suggestion-icon">⚡</span>
                         <span class="orch-suggestion-label">${escapeHTML(s.label)}</span>
                         <span class="orch-suggestion-arrow">→</span>`;
        btn.onclick = () => executeOrchestratorSuggestion(s.prompt, s.label);
        msgs.appendChild(btn);
    });

    msgs.scrollTop = msgs.scrollHeight;
}

function showOrchestratorTyping() {
    const msgs = document.getElementById('orchestrator-messages');
    if (!msgs) return null;
    clearOrchestratorWelcomeIfNeeded();
    const wrapper = document.createElement('div');
    wrapper.className = 'orch-msg orch-msg-assistant';
    wrapper.id = 'orch-typing-indicator';
    wrapper.innerHTML = `<div class="orch-typing"><span></span><span></span><span></span></div>`;
    msgs.appendChild(wrapper);
    msgs.scrollTop = msgs.scrollHeight;
    return wrapper;
}

async function sendOrchestratorMessage(msgOverride) {
    if (orchestratorBusy) return;
    const input = document.getElementById('orchestrator-input');
    const message = msgOverride || (input ? input.value.trim() : '');
    if (!message && !msgOverride) return;

    if (input && !msgOverride) {
        input.value = '';
        renderOrchestratorMessage(message, 'user');
    }

    orchestratorBusy = true;
    setOrchestratorDot('thinking');

    const typing = showOrchestratorTyping();

    try {
        const res = await fetch('/api/orchestrator/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                context: buildOrchestratorContext()
            })
        });

        const data = await res.json();

        if (typing) typing.remove();

        if (data.error) {
            renderOrchestratorMessage('⚠️ Fehler: ' + data.error, 'assistant');
        } else {
            if (data.reply) renderOrchestratorMessage(data.reply, 'assistant');
            if (data.suggestions && data.suggestions.length > 0) {
                renderOrchestratorSuggestions(data.suggestions);
            }
        }
        setOrchestratorDot('done');
        setTimeout(() => setOrchestratorDot('idle'), 2000);
    } catch (err) {
        if (typing) typing.remove();
        renderOrchestratorMessage('⚠️ Verbindungsfehler: ' + err.message, 'assistant');
        setOrchestratorDot('idle');
    } finally {
        orchestratorBusy = false;
    }
}

async function executeOrchestratorSuggestion(prompt, label) {
    if (!currentIssueId || !activeRunId) {
        renderOrchestratorMessage('⚠️ Kein aktiver Run. Starte zuerst einen Run für das aktuelle Issue.', 'assistant');
        return;
    }

    renderOrchestratorMessage(`▶ Führe aus: "${label}"`, 'user');

    try {
        const res = await fetch(`/api/runs/${activeRunId}/followup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: prompt })
        });

        if (res.ok) {
            renderOrchestratorMessage(`✅ Follow-Up Run gestartet! Beobachte die Logs im Workspace.`, 'assistant');
            setOrchestratorDot('done');
            setTimeout(() => setOrchestratorDot('idle'), 2000);
        } else {
            const err = await res.json();
            renderOrchestratorMessage('❌ Fehler beim Starten des Runs: ' + (err.error || 'Unbekannt'), 'assistant');
        }
    } catch (err) {
        renderOrchestratorMessage('❌ Verbindungsfehler: ' + err.message, 'assistant');
    }
}

function handleOrchestratorKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendOrchestratorMessage();
    }
}

function clearOrchestratorChat() {
    showOrchestratorWelcome();
    window._orchLastRunLogs = '';
    window._orchLastRunStatus = 'unknown';
    setOrchestratorDot('idle');
}

// Proactive analysis: called after a run completes
async function orchestratorProactiveAnalysis(runStatus, lastLogs) {
    window._orchLastRunStatus = runStatus;
    window._orchLastRunLogs = lastLogs || '';

    if (!currentProjectId) return;

    // Fetch live chat metadata to enrich the orchestrator's context
    await fetchActiveChatMeta();

    const chatMeta = window._orchActiveChatMeta;
    const modelInfo = chatMeta && chatMeta.model ? ` (Modell: ${chatMeta.model})` : '';
    const msgInfo = chatMeta && chatMeta.message_count ? ` | ${chatMeta.message_count} Nachrichten` : '';

    const trigger = runStatus === 'done'
        ? `Der letzte Agent-Run${modelInfo}${msgInfo} wurde erfolgreich abgeschlossen. Analysiere kurz was gut lief und mache 2-3 konkrete Verbesserungsvorschläge mit direktem Ausführen-Button.`
        : `Der letzte Agent-Run${modelInfo}${msgInfo} ist mit einem Fehler beendet. Analysiere die Logs und mache konkrete Vorschläge zur Fehlerbehebung.`;

    setTimeout(() => {
        renderOrchestratorMessage(`🔍 Analysiere Run (Status: ${runStatus}${modelInfo})...`, 'assistant');
        sendOrchestratorMessage(trigger);
    }, 1500);
}

// Prepare a dedicated minimized Antigravity desktop window for the active chat.
async function duplicateWindow() {
    if (!activeConvoId || activeConvoId === "new") {
        showToast("warning", "Conversation fehlt", "Bitte zuerst einen gespeicherten Chat auswählen.");
        return;
    }

    try {
        const response = await controlFetch(`/api/antigravity/chats/${activeConvoId}/window`, {
            method: "POST"
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.error || "Das Chatfenster konnte nicht vorbereitet werden.");
        }
        showToast("success", "AG-Fenster bereit", "Das zugehörige Anti-Gravity-Chatfenster ist bereit und minimiert.");
    } catch (err) {
        showToast("error", "AG-Fenster nicht vorbereitet", err.message);
    }
}

// ============================================================
// Subtasks & Kanban Board Logic
// ============================================================
function openAddSubtaskModal() {
    const modal = document.getElementById("subtask-modal");
    const input = document.getElementById("subtask-title");
    if (input) input.value = "";
    if (modal) modal.style.display = "block";
}

async function submitSubtask() {
    if (!currentIssueId) return;
    const input = document.getElementById("subtask-title");
    const title = input ? input.value.trim() : "";
    if (!title) {
        showToast("warning", "Aufgabe fehlt", "Bitte gib eine Aufgabenbeschreibung ein.");
        return;
    }

    try {
        const res = await fetch(`/api/issues/${currentIssueId}/subtasks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title })
        });
        if (res.ok) {
            closeModal("subtask-modal");
            loadSubtasks();
        } else {
            const err = await res.json();
            showToast("error", "Unteraufgabe nicht hinzugefügt", err.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Unteraufgabe nicht hinzugefügt", err.message);
    }
}

async function deleteSubtask(subtaskId) {
    if (!(await hubConfirm(
        "Möchtest du diese Unteraufgabe wirklich löschen?",
        {title: 'Unteraufgabe löschen', confirmLabel: 'Löschen'},
    ))) return;
    try {
        const res = await fetch(`/api/subtasks/${subtaskId}`, { method: "DELETE" });
        if (res.ok) {
            loadSubtasks();
        } else {
            const err = await res.json();
            showToast("error", "Unteraufgabe nicht gelöscht", err.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Unteraufgabe nicht gelöscht", err.message);
    }
}

async function loadSubtasks() {
    if (!currentIssueId) return;

    try {
        const res = await fetch(`/api/issues/${currentIssueId}/subtasks`);
        const data = await res.json();
        const subtasks = data.subtasks || [];

        // Clear columns
        const colTodo = document.getElementById("cards-todo");
        const colRunning = document.getElementById("cards-running");
        const colCompleted = document.getElementById("cards-completed");

        if (colTodo) colTodo.innerHTML = "";
        if (colRunning) colRunning.innerHTML = "";
        if (colCompleted) colCompleted.innerHTML = "";

        let counts = { pending: 0, running: 0, completed: 0 };

        subtasks.forEach(task => {
            counts[task.status] = (counts[task.status] || 0) + 1;

            const card = document.createElement("div");
            card.className = "kanban-card";
            card.innerHTML = `
                <span class="kanban-card-title">${escapeHTML(task.title)}</span>
                <div class="kanban-card-actions">
                    <button class="kanban-card-btn delete" onclick="deleteSubtask(${task.id})" title="Löschen">🗑</button>
                </div>
            `;

            if (task.status === "pending" && colTodo) {
                colTodo.appendChild(card);
            } else if (task.status === "running" && colRunning) {
                colRunning.appendChild(card);
            } else if (task.status === "completed" && colCompleted) {
                colCompleted.appendChild(card);
            }
        });

        // Update badges
        const todoCount = document.getElementById("todo-count");
        const runningCount = document.getElementById("running-count");
        const completedCount = document.getElementById("completed-count");

        if (todoCount) todoCount.innerText = counts.pending;
        if (runningCount) runningCount.innerText = counts.running;
        if (completedCount) completedCount.innerText = counts.completed;

    } catch (err) {
        console.error("Failed to load subtasks:", err);
    }
}

// ============================================================
// Commit & Sync Modal UI Logic
// ============================================================
function openCommitModal() {
    const modal = document.getElementById("commit-modal");
    const input = document.getElementById("commit-msg-input");
    const hint = document.getElementById("commit-msg-hint");

    if (input) {
        const isConfig = projects.find(p => p.id === currentProjectId)?.name === "System Config";
        input.value = isConfig ? "docs(memory): update rules & learnings" : (currentIssueId ? `Fix issue #${currentIssueId}` : "chore: update project");
    }
    if (hint) hint.innerText = "";
    if (modal) modal.style.display = "block";
}

async function generateAICommitMessage() {
    if (!currentProjectId) return;
    const btn = document.getElementById("ai-commit-btn");
    const input = document.getElementById("commit-msg-input");
    const hint = document.getElementById("commit-msg-hint");

    if (btn) {
        btn.disabled = true;
        btn.innerText = "⏳ AI...";
    }
    if (hint) hint.innerText = "Generiere Nachricht...";

    try {
        const res = await fetch("/api/git/generate-commit-msg", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId })
        });
        const data = await res.json();
        if (data.suggested_message) {
            if (input) input.value = data.suggested_message;
            if (hint) hint.innerText = "AI-Vorschlag erfolgreich generiert! ✨";
        } else {
            if (hint) hint.innerText = "Keine Änderungen im Git-Diff vorhanden.";
        }
    } catch (err) {
        if (hint) hint.innerText = "Fehler: " + err.message;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = "🤖 Generieren";
        }
    }
}

async function submitCommit() {
    if (!currentProjectId) return;
    const input = document.getElementById("commit-msg-input");
    const msg = input ? input.value.trim() : "";
    if (!msg) {
        showToast("warning", "Commit-Nachricht fehlt", "Bitte gib eine Commit-Nachricht ein.");
        return;
    }

    const btn = document.getElementById("submit-commit-btn");
    if (btn) {
        btn.disabled = true;
        btn.innerText = "⏳ Committing & Syncing...";
    }

    try {
        const res = await fetch("/api/git/commit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId, message: msg })
        });
        const data = await res.json();
        if (data.success) {
            showToast("success", "Commit erfolgreich", "Changes wurden committet und synchronisiert!");
            closeModal("commit-modal");
            loadWorkspaceDetails();
            loadProjects();
        } else {
            showToast("error", "Commit/Sync fehlgeschlagen", data.error || "Unbekannter Fehler");
        }
    } catch (err) {
        showToast("error", "Commit/Sync fehlgeschlagen", err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Commit & Sync ausführen";
        }
    }
}

// ============================================================
// Anti-Gravity UI Chat Integration Logic
// ============================================================
function setConversationType(type) {
    if (!["all", "normal", "project"].includes(type)) return;
    antigravityConversationType = type;
    renderAntigravityChatsWorkspace();
    loadIntegrityChats();
}

function setConversationScope(scope) {
    if (!["active", "archived", "all"].includes(scope)) return;
    antigravityConversationScope = scope;
    antigravityConversationStatuses.clear();
    if (scope === "active" || scope === "all") {
        antigravityConversationStatuses.add("running");
        antigravityConversationStatuses.add("complete");
    }
    if (scope === "archived" || scope === "all") {
        antigravityConversationStatuses.add("archived");
    }
    renderAntigravityChatsWorkspace();
    loadIntegrityChats();
}

function toggleConversationStatus(status, checked) {
    if (!["running", "complete", "archived"].includes(status)) return;
    if (checked) {
        antigravityConversationStatuses.add(status);
    } else if (antigravityConversationStatuses.size > 1) {
        antigravityConversationStatuses.delete(status);
    } else {
        const input = Array.from(document.querySelectorAll(".antigravity-status-option input"))
            .find(candidate => candidate.nextElementSibling?.textContent.toLowerCase() === status);
        if (input) input.checked = true;
        showToast("info", "Ein Filter bleibt aktiv", "Wähle mindestens einen Conversation-Status.");
        return;
    }
    loadIntegrityChats();
}

function updateConversationSearch(value) {
    antigravityConversationSearch = String(value || "").trim();
    clearTimeout(antigravityConversationSearchTimer);
    antigravityConversationSearchTimer = setTimeout(loadIntegrityChats, 220);
}

function startConversationAutoRefresh() {
    if (document.hidden || antigravityConversationRefreshTimer) return;
    antigravityConversationRefreshTimer = window.setInterval(
        () => loadIntegrityChats({silent: true}),
        2000,
    );
}

function stopConversationAutoRefresh() {
    if (!antigravityConversationRefreshTimer) return;
    window.clearInterval(antigravityConversationRefreshTimer);
    antigravityConversationRefreshTimer = null;
}

function chatRunningLoaderHTML() {
    return `
        <div class="chat-bubble chat-bubble-assistant polling-loader" data-live-running="true">
            <span class="chat-bubble-meta">Anti-Gravity Agent</span>
            <div class="chat-bubble-content antigravity-running-message">
                <span class="antigravity-thinking-symbol" aria-hidden="true">✢</span>
                <span class="antigravity-thinking-copy">Kontext wird geladen</span>
                <span class="antigravity-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            </div>
            <small class="antigravity-thinking-hint">Der Status wechselt, sobald neue Schritte eintreffen.</small>
        </div>
    `;
}

function updateAntigravityThinkingVisual(convoId) {
    const state = chatWindowsState[convoId];
    if (!state?.domElement) return;
    state.thinkingAnimationTick = Number(state.thinkingAnimationTick || 0) + 1;
    const tick = state.thinkingAnimationTick;
    const symbol = ANTIGRAVITY_THINKING_SYMBOLS[tick % ANTIGRAVITY_THINKING_SYMBOLS.length];
    const phase = ANTIGRAVITY_THINKING_PHASES[
        Math.floor(tick / 6) % ANTIGRAVITY_THINKING_PHASES.length
    ];
    state.domElement.querySelectorAll(".antigravity-thinking-symbol").forEach(element => {
        element.textContent = symbol;
    });
    state.domElement.querySelectorAll(".antigravity-thinking-copy").forEach(element => {
        element.textContent = phase;
    });
    const headerCopy = state.domElement.querySelector(".chat-agent-activity-copy");
    if (headerCopy) {
        headerCopy.textContent = state.hasAssistantOutput ? "Antwort wird übertragen" : phase;
    }
}

function startAntigravityThinkingAnimation(convoId) {
    const state = chatWindowsState[convoId];
    if (!state || state.thinkingAnimationInterval) return;
    updateAntigravityThinkingVisual(convoId);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    state.thinkingAnimationInterval = window.setInterval(
        () => updateAntigravityThinkingVisual(convoId),
        240,
    );
}

function stopAntigravityThinkingAnimation(convoId) {
    const state = chatWindowsState[convoId];
    if (!state?.thinkingAnimationInterval) return;
    window.clearInterval(state.thinkingAnimationInterval);
    state.thinkingAnimationInterval = null;
}

function clearStreamingAssistantBubbles(convoId, exceptBubble = null) {
    const body = chatWindowsState[convoId]?.domElement?.querySelector(
        ".chat-window-body",
    );
    if (!body) return;
    body.querySelectorAll(".chat-bubble-assistant.is-streaming").forEach(
        bubble => {
            if (bubble !== exceptBubble) {
                bubble.classList.remove("is-streaming");
            }
        },
    );
}

function syncChatRunningIndicator(convoId) {
    const winState = chatWindowsState[convoId];
    const win = winState?.domElement;
    if (!win) return;
    const running = Boolean(winState.isRunning);
    win.classList.toggle("is-agent-running", running);

    const headerIndicator = win.querySelector(".chat-agent-activity");
    if (headerIndicator) headerIndicator.hidden = !running;
    if (running) startAntigravityThinkingAnimation(convoId);
    else stopAntigravityThinkingAnimation(convoId);

    const body = win.querySelector(".chat-window-body");
    if (!body) return;
    const loader = body.querySelector('.polling-loader[data-live-running="true"]');
    const shouldShowLoader = running && !winState.hasAssistantOutput;
    if (shouldShowLoader && !loader) {
        body.insertAdjacentHTML("beforeend", chatRunningLoaderHTML());
        body.scrollTop = body.scrollHeight;
        updateAntigravityThinkingVisual(convoId);
    } else if (!shouldShowLoader && loader) {
        loader.remove();
    }
    if (!running || !winState.hasAssistantOutput) {
        clearStreamingAssistantBubbles(convoId);
    }
}

function setChatRunningState(convoId, running, {hasAssistantOutput = null} = {}) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    winState.isRunning = Boolean(running);
    if (hasAssistantOutput !== null) {
        winState.hasAssistantOutput = Boolean(hasAssistantOutput);
    }
    syncChatRunningIndicator(convoId);
}

function renderAntigravityActiveAgents(activeAgents = []) {
    antigravityActiveAgents = Array.isArray(activeAgents) ? activeAgents : [];
    const count = document.getElementById("antigravity-active-agent-count");
    const container = document.getElementById("antigravity-active-agent-list");
    if (count) count.textContent = String(antigravityActiveAgents.length);

    if (container) {
        if (!antigravityActiveAgents.length) {
            container.innerHTML = `<div class="antigravity-active-agent-empty">Gerade arbeitet kein Agent.</div>`;
        } else {
            container.innerHTML = antigravityActiveAgents.map(chat => {
                const isProject = chat.conversation_type === "project";
                const location = isProject
                    ? (chat.project_name || chat.repository_name || "Projekt")
                    : "Normale Conversation";
                const shortId = String(chat.convo_id || "").slice(0, 8);
                const assignedWorker = (antigravityWorkerPool.workers || []).find(
                    worker => worker.chat_id === chat.convo_id
                );
                const windowId = assignedWorker?.window_id
                    || chatWindowsState[chat.convo_id]?.desktopWindowId;
                return `
                    <button type="button" class="antigravity-active-agent"
                        onclick="openChatInWorkspace('${chat.convo_id}')"
                        title="${escapeHTML(chat.title || shortId)} öffnen">
                        <span class="antigravity-activity-spinner" aria-hidden="true"></span>
                        <span class="antigravity-active-agent-copy">
                            <strong>${escapeHTML(chat.title || "Aktiver Chat")}</strong>
                            <small>${escapeHTML(location)} · #${escapeHTML(shortId)}${windowId ? ` · Fenster ${escapeHTML(windowId)}` : ""}</small>
                        </span>
                    </button>
                `;
            }).join("");
        }
    }

    const runningIds = new Set(
        antigravityActiveAgents.map(chat => String(chat.convo_id || ""))
    );
    Object.keys(chatWindowsState).forEach(convoId => {
        const state = chatWindowsState[convoId];
        const recentlyCompleted = Number(state?.streamCompletedAt || 0) > 0
            && Date.now() - Number(state.streamCompletedAt) < 30000;
        const running = runningIds.has(convoId) && !recentlyCompleted;
        setChatRunningState(convoId, running);
        if (
            running
            && state
            && !state.eventSource
            && !convoId.startsWith("proxy-")
            && state.selectedModel?.source !== "custom"
        ) {
            startChatPollingForConvo(convoId);
        }
    });
}

function antigravityWorkerStateLabel(worker) {
    const labels = {
        idle: "Frei",
        preparing: "Lädt Chat",
        sending: "Sendet",
        working: "Arbeitet",
        dictation_preparing: "Diktat wird vorbereitet",
        dictation_ready: "Diktat bereit",
        dictation_recording: "Nimmt Sprache auf",
        error: "Fehler",
        user: "Dein Fenster",
    };
    return labels[worker?.state] || worker?.detail || "Bereit";
}

function syncWorkerAssignmentsToChats() {
    const workers = antigravityWorkerPool.workers || [];
    Object.entries(chatWindowsState).forEach(([convoId, state]) => {
        if (!state || convoId === "new" || convoId.startsWith("proxy-")) return;
        const worker = workers.find(item => item.chat_id === convoId);
        const status = state.domElement?.querySelector(".desktop-window-status");
        if (!worker) {
            state.desktopWindowReady = false;
            state.desktopWindowId = null;
            state.desktopWindowUpdatedAt = 0;
            if (status) {
                status.textContent = "○ Worker wird bei Bedarf zugeteilt";
                status.dataset.state = "loading";
                status.title = "Der Pool weist beim nächsten Versand automatisch ein AG-Fenster zu.";
            }
            return;
        }
        state.desktopWindowReady = true;
        state.desktopWindowId = worker.window_id || "AG";
        state.desktopWindowUpdatedAt = Date.now();
        if (status) {
            const label = antigravityWorkerStateLabel(worker);
            status.textContent = `● ${state.desktopWindowId} · ${label}`;
            status.dataset.state = worker.state === "error" ? "error" : "ready";
            status.title = `${state.desktopWindowId} ist diesem Chat aktuell zugeordnet.`;
        }
    });
}

function renderAntigravityWorkerPool(pool = {}) {
    antigravityWorkerPool = {
        primary: pool.primary || null,
        workers: Array.isArray(pool.workers) ? pool.workers : [],
        capacity: pool.capacity || {active: 0, maximum: 4, minimum_warm: 1, queued: 0},
    };
    const capacity = antigravityWorkerPool.capacity;
    const capacityEl = document.getElementById("antigravity-worker-capacity");
    const list = document.getElementById("antigravity-worker-list");
    if (capacityEl) {
        const queued = Number(capacity.queued || 0);
        capacityEl.textContent = `${capacity.active || 0} / ${capacity.maximum || 4}${queued ? ` · ${queued} wartet` : ""}`;
    }
    if (!list) return;

    const rows = [];
    if (antigravityWorkerPool.primary) {
        rows.push({...antigravityWorkerPool.primary, isPrimary: true});
    }
    rows.push(...antigravityWorkerPool.workers);
    if (!rows.length) {
        list.innerHTML = `<div class="antigravity-active-agent-empty">Anti-Gravity ist nicht verbunden.</div>`;
        syncWorkerAssignmentsToChats();
        return;
    }

    list.innerHTML = rows.map(worker => {
        const chat = worker.chat || {};
        const chatId = worker.chat_id || chat.convo_id || "";
        const isDictation = worker.purpose === "dictation";
        const title = isDictation
            ? "Nativer Diktatdienst"
            : (chat.title || (worker.isPrimary ? "Manuelle Arbeit" : "Noch kein Chat"));
        const project = isDictation
            ? "Formulare & Chat-Composer"
            : (chat.conversation_type === "project"
                ? (chat.project_name || chat.repository_name || "Projekt")
                : (chatId ? "Normale Conversation" : "Warm bereit"));
        const canClose = !worker.isPrimary
            && !worker.reserved
            && !worker.has_draft
            && !["preparing", "sending", "working"].includes(worker.state);
        const stateLabel = antigravityWorkerStateLabel(worker);
        const click = chatId && !isDictation
            ? `onclick="openChatInWorkspace('${escapeHTML(chatId)}')"`
            : "";
        return `
            <article class="antigravity-worker-card state-${escapeHTML(worker.state || "idle")} ${worker.isPrimary ? "is-primary" : ""} ${isDictation ? "is-dictation" : ""}"
                ${click}
                title="${escapeHTML(isDictation ? `${worker.window_id} ist ausschließlich für Spracheingabe reserviert` : (chatId ? `${worker.window_id} öffnen` : `${worker.window_id} ist frei`))}">
                <span class="antigravity-worker-stamp">${escapeHTML(worker.window_id || "AG")}</span>
                <span class="antigravity-worker-copy">
                    <strong>${escapeHTML(title)}</strong>
                    <small>${escapeHTML(project)} · ${escapeHTML(stateLabel)}</small>
                </span>
                <span class="antigravity-worker-state" aria-label="${escapeHTML(stateLabel)}"></span>
                ${canClose ? `
                    <button type="button" class="antigravity-worker-close"
                        onclick="event.stopPropagation(); closeAntigravityWorker('${escapeHTML(worker.target_id)}')"
                        title="${escapeHTML(worker.window_id)} schließen">×</button>
                ` : ""}
            </article>
        `;
    }).join("");
    syncWorkerAssignmentsToChats();
}

async function closeAntigravityWorker(targetId) {
    if (!targetId) return;
    try {
        const response = await controlFetch(
            `/api/antigravity/workers/${encodeURIComponent(targetId)}`,
            {method: "DELETE"}
        );
        const result = await response.json();
        if (!response.ok || result.success !== true) {
            throw new Error(result.error || "Worker konnte nicht geschlossen werden.");
        }
        showToast("success", "Worker geschlossen", `${result.window_id || "AG"} wurde sauber beendet.`);
        await loadIntegrityChats({silent: true});
    } catch (error) {
        showToast("error", "Worker bleibt aktiv", error.message);
    }
}

function applyConversationArchivedState(convoId, archived) {
    const winState = chatWindowsState[convoId];
    if (!winState?.domElement) return;
    winState.isArchived = Boolean(archived);
    const win = winState.domElement;
    win.classList.toggle("is-archived", winState.isArchived);

    const lock = win.querySelector(".chat-archive-lock");
    if (lock) lock.hidden = !winState.isArchived;
    const toggle = win.querySelector(".chat-archive-toggle-btn");
    if (toggle) {
        toggle.textContent = winState.isArchived ? "↺" : "▣";
        toggle.title = winState.isArchived
            ? "Conversation wiederherstellen"
            : "Conversation archivieren";
        toggle.setAttribute(
            "aria-label",
            winState.isArchived
                ? "Conversation wiederherstellen"
                : "Conversation archivieren",
        );
    }

    const composerControls = [
        win.querySelector(".chat-send-input"),
        win.querySelector(".chat-send-btn"),
        win.querySelector(".button-attach"),
        win.querySelector(".chat-file-input"),
        win.querySelector(".chat-mic-btn"),
        win.querySelector(".model-dropdown-btn"),
    ].filter(Boolean);
    if (winState.isArchived) {
        composerControls.forEach(control => {
            control.disabled = true;
        });
        if (winState.eventSource) {
            winState.eventSource.close();
            winState.eventSource = null;
        }
        setChatRunningState(convoId, false, {hasAssistantOutput: false});
    } else if (!winState.isModelSwitching) {
        composerControls.forEach(control => {
            control.disabled = false;
        });
    }
}

function syncOpenChatArchiveStates(payload) {
    const visibleIds = new Set(payload.visible_conversation_ids || []);
    const archivedIds = new Set(payload.archived_conversation_ids || []);
    Object.keys(chatWindowsState).forEach(convoId => {
        if (convoId === "new" || convoId.startsWith("proxy-")) return;
        if (archivedIds.has(convoId)) {
            applyConversationArchivedState(convoId, true);
        } else if (visibleIds.has(convoId)) {
            applyConversationArchivedState(convoId, false);
        }
    });
}

async function setConversationArchived(convoId, archived) {
    const action = archived ? "archive" : "restore";
    const buttons = Array.from(document.querySelectorAll(
        ".conversation-archive-toggle, .chat-archive-toggle-btn, .chat-restore-btn"
    )).filter(button => button.dataset.convoId === convoId);
    buttons.forEach(button => {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
    });

    try {
        const response = await controlFetch(
            `/api/antigravity/chats/${encodeURIComponent(convoId)}/${action}`,
            {method: "POST"},
        );
        const result = await response.json();
        if (!response.ok || result.verified !== true) {
            throw new Error(
                result.error
                || "Anti-Gravity konnte den Archivstatus nicht bestätigen."
            );
        }
        applyConversationArchivedState(convoId, archived);
        await loadIntegrityChats({silent: true});
        showToast(
            "success",
            archived ? "Conversation archiviert" : "Conversation wiederhergestellt",
            archived
                ? "Der Chat ist jetzt schreibgeschützt und liegt im Archiv."
                : "Der Chat ist wieder aktiv und kann beschrieben werden.",
        );
        if (!archived) {
            await ensureDedicatedAntigravityWindow(convoId).catch(() => {});
        }
    } catch (error) {
        showToast(
            "error",
            archived ? "Archivieren fehlgeschlagen" : "Restore fehlgeschlagen",
            error.message,
        );
    } finally {
        buttons.forEach(button => {
            button.disabled = false;
            button.removeAttribute("aria-busy");
        });
    }
}

async function loadIntegrityChats(options = {}) {
    const silent = Boolean(options.silent);
    const listContainer = document.getElementById("integrity-chats-list");
    if (!listContainer || antigravityConversationLoadInFlight) return;
    const countContainer = document.getElementById("antigravity-conversation-counts");
    antigravityConversationLoadInFlight = true;
    if (!silent) listContainer.setAttribute("aria-busy", "true");

    try {
        const params = new URLSearchParams({
            type: antigravityConversationType,
            status: Array.from(antigravityConversationStatuses).join(",")
        });
        if (antigravityConversationSearch) {
            params.set("search", antigravityConversationSearch);
        }
        const [res, workerResponse] = await Promise.all([
            fetch(
                `/api/antigravity/conversations?${params.toString()}`,
                {cache: "no-store"},
            ),
            fetch("/api/antigravity/workers", {cache: "no-store"}).catch(() => null),
        ]);
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.error || "Conversations konnten nicht geladen werden");
        let workerPayload = antigravityWorkerPool;
        if (workerResponse?.ok) {
            workerPayload = await workerResponse.json();
        }
        renderAntigravityWorkerPool(workerPayload);
        const chats = payload.conversations || [];
        const activeAgents = payload.active_agents || [];
        antigravityConversationCatalog = chats;
        syncOpenChatWindowTitles();
        syncOpenChatArchiveStates(payload);
        const counts = payload.counts || {};
        if (countContainer) {
            const liveState = payload.sidebar?.available
                ? (payload.sidebar?.stale ? "verzögert" : "live")
                : "offline";
            countContainer.dataset.state = liveState;
            countContainer.title = liveState === "live"
                ? "Live mit Anti-Gravity synchronisiert"
                : (liveState === "verzögert"
                    ? "Letzter bekannter Anti-Gravity-Stand"
                    : "Anti-Gravity ist momentan nicht erreichbar");
            countContainer.textContent = `${counts.visible || 0} Chats · ${counts.archived || 0} archiviert`;
        }
        renderAntigravityActiveAgents(activeAgents);
        const signature = JSON.stringify({
            counts,
            workers: (antigravityWorkerPool.workers || []).map(worker => [
                worker.target_id,
                worker.window_id,
                worker.state,
                worker.chat_id,
                worker.reserved,
                worker.purpose,
            ]),
            active_agents: activeAgents.map(chat => [
                chat.convo_id,
                chat.title,
                chat.status,
                chat.updated_at,
                chat.project_name,
            ]),
            chats: chats.map(chat => [
                chat.convo_id,
                chat.title,
                chat.status,
                Boolean(chat.archived),
                chat.updated_at,
                chat.project_name,
                Boolean(chat.visible_in_sidebar),
            ]),
        });
        if (silent && signature === antigravityConversationLastSignature) return;
        antigravityConversationLastSignature = signature;

        if (!chats || chats.length === 0) {
            listContainer.innerHTML = `
                <div class="workspace-placeholder placeholder-sm">
                    Keine Conversations für diese Filter gefunden.
                </div>
            `;
            return;
        }

        listContainer.innerHTML = chats.map(c => {
            const timestamp = Number(c.updated_at || c.created_at || 0);
            const dateStr = timestamp ? new Date(timestamp * 1000).toLocaleString("de-DE", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit"
            }) : "Unbekannt";
            const isProject = c.conversation_type === "project";
            const location = isProject
                ? (c.project_name || c.repository_name || "Projekt")
                : "Outside of Project";
            const state = c.archived ? "archived" : (c.status || "complete");
            const stateLabel = {
                running: "Agent arbeitet",
                complete: "Aktiv",
                archived: "Archiviert"
            }[state] || "Complete";
            const shortId = String(c.convo_id || "").slice(0, 8);
            return `
                <article class="antigravity-conversation-row ${currentEmbeddedConvoId === c.convo_id ? "is-selected" : ""} ${state === "running" ? "is-running" : ""} ${state === "archived" ? "is-archived" : ""}"
                    data-convo-id="${escapeHTML(c.convo_id)}"
                    onclick="openChatInWorkspace('${c.convo_id}')">
                    <div class="antigravity-conversation-main">
                        <div class="antigravity-conversation-title">${escapeHTML(c.title || "Neuer Chat")}</div>
                        <div class="antigravity-conversation-meta">
                            <span class="antigravity-location-badge ${isProject ? "project" : "normal"}">${isProject ? "⌑" : "○"} ${escapeHTML(location)}</span>
                            ${state === "running" ? `<span class="antigravity-status-badge running"><span class="antigravity-activity-spinner" aria-hidden="true"></span>${stateLabel}</span>` : ""}
                            ${state === "archived" ? `<span class="antigravity-status-badge archived">${stateLabel}</span>` : ""}
                            <span>${dateStr}</span>
                            <code title="${escapeHTML(c.convo_id)}">#${escapeHTML(shortId)}</code>
                        </div>
                    </div>
                    <div class="antigravity-conversation-actions">
                        <button class="antigravity-open-window"
                            onclick="event.stopPropagation(); openChatFloating('${c.convo_id}')"
                            title="${state === "archived" ? "Archivierten Verlauf ansehen" : "Als eigenes paralleles Fenster öffnen"}"
                            aria-label="Conversation ${escapeHTML(c.title || shortId)} öffnen">${state === "archived" ? "◉" : "↗"}</button>
                        <button class="conversation-archive-toggle"
                            data-convo-id="${escapeHTML(c.convo_id)}"
                            onclick="event.stopPropagation(); setConversationArchived('${c.convo_id}', ${state !== "archived"})"
                            title="${state === "archived" ? "Conversation wiederherstellen" : "Conversation archivieren"}"
                            aria-label="${state === "archived" ? "Conversation wiederherstellen" : "Conversation archivieren"}">${state === "archived" ? "↺" : "▣"}</button>
                        <button class="antigravity-delete-conversation"
                            onclick="event.stopPropagation(); deleteIntegrityChat('${c.convo_id}')"
                            title="Conversation dauerhaft löschen"
                            aria-label="Conversation ${escapeHTML(c.title || shortId)} löschen">🗑</button>
                    </div>
                </article>
            `;
        }).join("");
    } catch (err) {
        if (!silent) {
            listContainer.innerHTML = `<div class="workspace-placeholder placeholder-sm text-danger">Fehler: ${escapeHTML(err.message)}</div>`;
            if (countContainer) countContainer.textContent = "Katalog nicht verfügbar";
        }
    } finally {
        antigravityConversationLoadInFlight = false;
        if (!silent) listContainer.removeAttribute("aria-busy");
    }
}

function refreshConversationSelection() {
    document.querySelectorAll(".antigravity-conversation-row").forEach(row => {
        row.classList.toggle("is-selected", row.dataset.convoId === currentEmbeddedConvoId);
    });
}

function showChatStagePlaceholder() {
    const stage = document.getElementById("antigravity-chat-stage");
    if (stage) stage.innerHTML = antigravityChatStagePlaceholderHTML();
    currentEmbeddedConvoId = null;
    refreshConversationSelection();
}

function mountChatWindowEmbedded(convoId) {
    const stage = document.getElementById("antigravity-chat-stage");
    const winState = chatWindowsState[convoId];
    const win = winState?.domElement;
    if (!stage || !win) return;

    stage.innerHTML = "";
    stage.appendChild(win);
    win.classList.add("chat-window-embedded");
    ["position", "left", "top", "width", "height", "z-index"].forEach(property => {
        win.style.removeProperty(property);
    });
    const header = win.querySelector(".chat-window-header");
    if (header) header.style.cursor = "default";
    const catalogEntry = antigravityConversationCatalog.find(item => item.convo_id === convoId);
    const title = win.querySelector(".chat-history-title");
    if (title) title.textContent = catalogEntry?.title || `Chat #${convoId.substring(0, 8)}`;
    currentEmbeddedConvoId = convoId;
    refreshConversationSelection();
}

function mountChatWindowFloating(convoId) {
    const winState = chatWindowsState[convoId];
    const win = winState?.domElement;
    if (!win) return;
    if (window.matchMedia("(max-width: 820px)").matches) {
        activateHubTab("chats-tab");
        mountChatWindowEmbedded(convoId);
        return;
    }

    win.classList.remove("chat-window-embedded");
    document.body.appendChild(win);
    const floatingCount = document.querySelectorAll(".chat-window:not(.chat-window-embedded)").length;
    let state = {};
    try {
        state = JSON.parse(localStorage.getItem(`chat-window-state-${convoId}`)) || {};
    } catch (error) {}
    win.style.position = "fixed";
    win.style.width = `${state.width || 420}px`;
    win.style.height = `${state.height || 600}px`;
    win.style.left = `${state.left ?? 20 + Math.max(0, floatingCount - 1) * 32}px`;
    win.style.top = `${state.top ?? 92 + Math.max(0, floatingCount - 1) * 24}px`;
    win.style.zIndex = getNextZIndex();
    const header = win.querySelector(".chat-window-header");
    if (header) header.style.cursor = "move";
    if (currentEmbeddedConvoId === convoId) showChatStagePlaceholder();
}

async function openChatInWorkspace(convoId) {
    try {
        if (currentEmbeddedConvoId && currentEmbeddedConvoId !== convoId) {
            const previous = chatWindowsState[currentEmbeddedConvoId]?.domElement;
            if (previous?.classList.contains("chat-window-embedded")) {
                destroyChatWindow(currentEmbeddedConvoId);
            }
        }
        await openChatHistory(convoId);
        mountChatWindowEmbedded(convoId);
        return true;
    } catch (error) {
        console.error("[ChatWorkspace] Existing chat could not be opened:", error);
        showToast(
            "error",
            "Chat konnte nicht geöffnet werden",
            error?.message || "Unbekannter Fehler",
        );
        return false;
    }
}

async function openChatFloating(convoId) {
    try {
        if (chatWindowsState[convoId]) {
            mountChatWindowFloating(convoId);
            return true;
        }
        await openChatHistory(convoId);
        return true;
    } catch (error) {
        console.error("[ChatWorkspace] Floating chat could not be opened:", error);
        showToast(
            "error",
            "Chatfenster konnte nicht geöffnet werden",
            error?.message || "Unbekannter Fehler",
        );
        return false;
    }
}

async function createIntegrityChat(conversationType = "project") {
    if (!["normal", "project"].includes(conversationType)) return;
    if (conversationType === "project") {
        if (!currentProjectId) {
            showToast("info", "Kein Projekt ausgewählt", "Wähle zuerst ein GitHub-Repository aus.");
            return;
        }
        const project = projects.find(item => Number(item.id) === Number(currentProjectId));
        if (!project?.antigravity_linked) {
            openAntigravityLinkModal(currentProjectId);
            return;
        }
    }
    await openChatInWorkspace("new");
    const winState = chatWindowsState.new;
    if (winState) {
        winState.newConversationType = conversationType;
        const title = winState.domElement?.querySelector(".chat-history-title");
        if (title) {
            title.textContent = conversationType === "project"
                ? "Neuer Projektchat"
                : "Neue Conversation";
        }
    }
    const input = chatWindowsState.new?.domElement.querySelector(".chat-send-input");
    if (input) input.focus();
}

async function deleteIntegrityChat(convoId) {
    if (!(await hubConfirm(
        "Diese Conversation wird dauerhaft aus Anti-Gravity und dem Hub gelöscht. Fortfahren?",
        {title: 'Conversation dauerhaft löschen', confirmLabel: 'Conversation löschen'},
    ))) return;
    try {
        const res = await controlFetch(`/api/antigravity/chats/${encodeURIComponent(convoId)}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Löschung fehlgeschlagen");
        if (data.success) {
            destroyChatWindow(convoId);
            showToast("success", "Conversation gelöscht", "Die Conversation wurde dauerhaft entfernt.");
            await loadIntegrityChats();
        }
    } catch (err) {
        showToast("error", "Conversation nicht gelöscht", err.message);
    }
}

let activeConvoId = null;
let chatPollInterval = null;
let pendingMessage = null;

let quotaPollInterval = null;

async function loadIntegrityQuota() {
    try {
        const res = await fetch("/api/antigravity/quota");
        if (!res.ok) throw new Error("Fehler beim Laden der Quoten");
        const data = await res.json();

        if (data && data.response && data.response.groups) {
            const groups = data.response.groups;
            const geminiGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('gemini'));
            const claudeGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('claude'));

            let g5h = 100, gW = 100, g5hDesc = "", gWDesc = "";
            if (geminiGroup && geminiGroup.buckets) {
                const weekly = geminiGroup.buckets.find(b => b.window === 'weekly');
                const fiveHour = geminiGroup.buckets.find(b => b.window === '5h');
                if (weekly) {
                    gW = Math.round(weekly.remainingFraction * 100);
                    gWDesc = weekly.description || '';
                }
                if (fiveHour) {
                    g5h = Math.round(fiveHour.remainingFraction * 100);
                    g5hDesc = fiveHour.description || '';
                }
            }

            let c5h = 100, cW = 100, c5hDesc = "", cWDesc = "";
            if (claudeGroup && claudeGroup.buckets) {
                const weekly = claudeGroup.buckets.find(b => b.window === 'weekly');
                const fiveHour = claudeGroup.buckets.find(b => b.window === '5h');
                if (weekly) {
                    cW = Math.round(weekly.remainingFraction * 100);
                    cWDesc = weekly.description || '';
                }
                if (fiveHour) {
                    c5h = Math.round(fiveHour.remainingFraction * 100);
                    c5hDesc = fiveHour.description || '';
                }
            }

            const gTooltip = `Gemini:\n${getPercentColorTooltip('5h', g5h, g5hDesc)}\n${getPercentColorTooltip('Weekly', gW, gWDesc)}`;
            const cTooltip = `Claude:\n${getPercentColorTooltip('5h', c5h, c5hDesc)}\n${getPercentColorTooltip('Weekly', cW, cWDesc)}`;

            const gEl = document.getElementById("quota-gemini");
            const cEl = document.getElementById("quota-claude");

            if (gEl) {
                gEl.innerText = `G: ${g5h}%`;
                gEl.title = gTooltip;
                gEl.style.color = g5h > 50 ? "" : (g5h > 20 ? "#eab308" : "#ef4444");
            }
            if (cEl) {
                cEl.innerText = `C: ${c5h}%`;
                cEl.title = cTooltip;
                cEl.style.color = c5h > 50 ? "" : (c5h > 20 ? "#eab308" : "#ef4444");
            }

            // Update quota display in all open chat windows
            const gElements = document.querySelectorAll(".quota-gemini");
            const cElements = document.querySelectorAll(".quota-claude");
            gElements.forEach(el => {
                el.innerText = `G: ${g5h}%`;
                el.title = gTooltip;
                el.style.color = g5h > 50 ? "" : (g5h > 20 ? "#eab308" : "#ef4444");
            });
            cElements.forEach(el => {
                el.innerText = `C: ${c5h}%`;
                el.title = cTooltip;
                el.style.color = c5h > 50 ? "" : (c5h > 20 ? "#eab308" : "#ef4444");
            });

            // Quota-Wächter check:
            const modelSpans = document.querySelectorAll(".current-selected-model");
            const geminiFallback = (_cachedModels || []).find(model =>
                model.source !== "custom"
                && String(model.label || "").startsWith("Gemini")
            );
            modelSpans.forEach(modelSpan => {
                const activeModel = modelSpan.textContent.trim();
                const cleanActiveModel = activeModel.replace(/^[^\w]*/, '').trim();
                if (cleanActiveModel.startsWith("Claude") && (c5h === 0 || cW === 0)) {
                    if (!geminiFallback?.label) {
                        showToast(
                            "warning",
                            "Quoten-Wächter",
                            "Claude-Quote verbraucht. Öffne die native Modellliste und wähle ein verfügbares Modell.",
                            8000,
                        );
                        return;
                    }
                    const win = modelSpan.closest(".chat-window");
                    if (win) {
                        const convoId = win.getAttribute("data-convo-id");
                        selectChatModelForConvo(convoId, geminiFallback);
                        showToast("error", "Quoten-Wächter", `Claude-Quote verbraucht. Automatisch auf ${geminiFallback.label} umgeschaltet.`, 8000);
                    } else {
                        // Fallback for single/legacy model span
                        selectChatModel(geminiFallback);
                        showToast("error", "Quoten-Wächter", `Claude-Quote verbraucht. Automatisch auf ${geminiFallback.label} umgeschaltet.`, 8000);
                    }
                }
            });
        }
    } catch (e) {
        console.error("[Quota] Failed to load quota info:", e);
    }
}


function getPercentColorTooltip(label, pct, desc) {
    if (!desc || desc === 'Aktiv' || desc === pct + '%') {
        return `• ${label}: ${pct}%`;
    }
    return `• ${label}: ${pct}% (${desc})`;
}

function startQuotaPolling() {
    if (quotaPollInterval) clearInterval(quotaPollInterval);
    loadIntegrityQuota();
    loadTokenStats();
    quotaPollInterval = setInterval(() => {
        loadIntegrityQuota();
        loadTokenStats();
    }, 15000);
}

function stopQuotaPolling() {
    if (quotaPollInterval) {
        clearInterval(quotaPollInterval);
        quotaPollInterval = null;
    }
}

async function loadTokenStats() {
    if (!activeConvoId) return;
    const tEl = document.getElementById("quota-token");
    if (!tEl) return;

    try {
        const res = await fetch(`/api/antigravity/tokens/${activeConvoId}`);
        if (!res.ok) throw new Error("Token fetch failed");
        const data = await res.json();

        const totalIn = data.totalInput || 0;
        const totalOut = data.totalOutput || 0;
        const totalUncached = data.totalUncached || 0;
        const cacheRatio = data.cacheRatio || 0;

        function formatTokens(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(0) + 'k';
            return num.toString();
        }

        const totalStr = formatTokens(totalIn);
        tEl.innerText = `T: ${totalStr}`;
        tEl.title = `Akkumulierter Verbrauch:\n• Input: ${totalIn.toLocaleString('de-DE')}\n  - Cached: ${(totalIn - totalUncached).toLocaleString('de-DE')} (${cacheRatio}%)\n  - Uncached: ${totalUncached.toLocaleString('de-DE')}\n• Output: ${totalOut.toLocaleString('de-DE')}`;

        if (totalIn > 0) {
            tEl.style.display = '';
        }
    } catch (e) {
        tEl.innerText = "T: --";
        tEl.title = "Token-Daten nicht verfügbar";
    }
}

// Voice Input (Backend API integration)
let isListening = false;
let voicePollInterval = null;
let voiceAuthToken = null;

async function getAuthToken() {
    if (voiceAuthToken) return voiceAuthToken;
    // Loopback Hub requests are trusted server-side. When the Hub is
    // deliberately exposed to the LAN, users can provide the configured token
    // locally without retrieving it from a public health endpoint.
    voiceAuthToken = (localStorage.getItem("auth_token") || "").trim();
    return voiceAuthToken;
}

async function toggleVoiceInput() {
    const micBtn = document.getElementById("chat-mic-btn");
    const input = document.getElementById("chat-send-input");

    if (isListening) {
        await stopVoiceInput();
        return;
    }

    isListening = true;
    if (micBtn) {
        micBtn.classList.add("is-recording");
        micBtn.setAttribute("aria-pressed", "true");
        micBtn.title = "Aufnahme beenden";
    }
    showToast("info", "Aufnahme gestartet", "Sprich jetzt...");

    const currentText = input ? input.value : "";

    try {
        const token = await getAuthToken();
        const headers = { "Content-Type": "application/json" };
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const res = await controlFetch("/api/voice/dictation/start", {
            method: "POST",
            headers: headers,
            body: JSON.stringify({ text: currentText })
        });

        if (!res.ok) {
            throw new Error(`HTTP-Fehler ${res.status}`);
        }

        // Poll status every 300ms
        voicePollInterval = setInterval(pollVoiceStatus, 300);

    } catch (err) {
        console.error("[Voice] Start failed:", err);
        showToast("error", "Fehler", "Sprachaufnahme konnte nicht gestartet werden: " + err.message);
        resetVoiceUI();
    }
}

async function pollVoiceStatus() {
    const input = document.getElementById("chat-send-input");
    try {
        const token = await getAuthToken();
        const headers = {};
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const res = await fetch("/api/voice/dictation/status", { headers });
        if (!res.ok) {
            throw new Error(`HTTP-Fehler ${res.status}`);
        }

        const data = await res.json();

        // Update input field with returned text
        if (input && data.text !== undefined) {
            input.value = data.text;
        }

        // Stop if isRecording is false (supporting camelCase and snake_case)
        const isRecording = data.isRecording !== undefined ? data.isRecording : data.is_recording;
        if (isRecording === false) {
            cleanupVoicePolling();
            resetVoiceUI();
        }
    } catch (err) {
        console.error("[Voice] Polling failed:", err);
        cleanupVoicePolling();
        resetVoiceUI();
        getAuthToken().then(token => {
            const headers = {};
            if (token) {
                headers["Authorization"] = `Bearer ${token}`;
            }
            controlFetch("/api/voice/dictation/stop", { method: "POST", headers: headers })
                .catch(e => console.error("[Voice] Auto-stop on poll fail failed:", e));
        }).catch(e => console.error("[Voice] Failed to get token on poll fail:", e));
    }
}

async function stopVoiceInput() {
    cleanupVoicePolling();
    resetVoiceUI();

    try {
        const token = await getAuthToken();
        const headers = {};
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const response = await controlFetch("/api/voice/dictation/stop", {
            method: "POST",
            headers: headers
        });
        if (!response.ok) {
            throw new Error(`HTTP-Fehler ${response.status}`);
        }
        const data = await response.json();
        const input = document.getElementById("chat-send-input");
        if (input && typeof data.text === "string") {
            input.value = data.text;
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        showToast("success", "Aufnahme beendet", "Sprachaufnahme verarbeitet.");
    } catch (err) {
        console.error("[Voice] Stop failed:", err);
    }
}

function cleanupVoicePolling() {
    if (voicePollInterval) {
        clearInterval(voicePollInterval);
        voicePollInterval = null;
    }
}

function resetVoiceUI() {
    isListening = false;
    const micBtn = document.getElementById("chat-mic-btn");
    if (micBtn) {
        micBtn.classList.remove("is-recording", "is-starting", "is-stopping");
        micBtn.setAttribute("aria-pressed", "false");
        micBtn.title = "Sprachnachricht aufnehmen";
    }
}

function toggleModelDropdown(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById("model-dropdown-menu");
    if (!menu) return;
    const isShowing = menu.style.display === "block";
    if (isShowing) {
        menu.style.display = "none";
    } else {
        loadModelList(); // Dynamisch laden
        menu.style.display = "block";
    }
}

let _cachedModels = null;
async function loadModelList() {
    const menu = document.getElementById("model-dropdown-menu");
    if (!menu) return;

    const currentModel = document.getElementById('current-selected-model');
    const currentText = currentModel ? currentModel.innerText : '';

    function renderModels(list) {
        menu.innerHTML = '';
        const hdr = document.createElement('div');
        hdr.style.cssText = 'padding: 6px 12px; font-size: 10px; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--color-border-default);';
        hdr.innerText = 'Model';
        menu.appendChild(hdr);

        list.forEach(m => {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            if (m.label === currentText) {
                item.style.fontWeight = 'bold';
                item.style.color = 'var(--color-accent-neon)';
            }

            let html = m.label;
            if (m.badge) {
                html += ` <span style="opacity: 0.5; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 1px 6px; border-radius: 4px; font-size: 9px; margin-left: 4px;">${m.badge}</span>`;
            }
            item.innerHTML = html;
            item.onclick = function(e) { selectChatModel(m.label, e); };
            menu.appendChild(item);
        });
    }

    // Render cache immediately if available
    if (_cachedModels && _cachedModels.length > 0) {
        renderModels(_cachedModels);
    } else {
        menu.innerHTML = '<div class="dropdown-item" style="opacity: 0.5;">Lade Modelle...</div>';
    }

    try {
        const res = await fetch('/api/antigravity/models', {cache: 'no-store'});
        if (!res.ok) throw new Error('API error');
        const data = await res.json();
        _cachedModels = data.models || [];
        if (_cachedModels.length > 0) {
            renderModels(_cachedModels);
        } else {
            menu.innerHTML = '<div class="dropdown-item" style="opacity: 0.65;">Native Modelle sind gerade nicht lesbar.</div>';
        }
    } catch (e) {
        console.error('[Models] Failed to load model list:', e);
        if (_cachedModels?.length) renderModels(_cachedModels);
        else menu.innerHTML = '<div class="dropdown-item" style="opacity: 0.65;">Anti-Gravity-Modellliste nicht erreichbar.</div>';
    }
}

function normalizeModelSelection(model) {
    if (model && typeof model === "object") {
        return {
            ...model,
            label: model.label || model.name || model.model || "Unbekanntes Modell",
            source: model.source === "custom" ? "custom" : "official"
        };
    }
    const modelName = String(model || "");
    return (_cachedModels || []).find(item => item.label === modelName) || {
        label: modelName,
        source: "official"
    };
}

function getChatModelIcon(model) {
    const selected = normalizeModelSelection(model);
    if (selected.source === "custom") return "🔌 ";
    if (selected.label.startsWith("Gemini")) return "✨ ";
    if (selected.label.startsWith("Claude")) return "⚛️ ";
    if (selected.label.startsWith("GPT-OSS")) return "🤖 ";
    return "";
}

function updateChatModelLabel(winState, model) {
    const selected = normalizeModelSelection(model);
    const currentModelEl = winState?.domElement?.querySelector(".current-selected-model");
    if (currentModelEl) currentModelEl.innerText = getChatModelIcon(selected) + selected.label;
    if (winState) winState.selectedModel = selected;
}

function setChatModelSwitching(
    convoId,
    switching,
    {targetLabel = "", windowId = ""} = {},
) {
    const winState = chatWindowsState[convoId];
    const win = winState?.domElement;
    if (!winState || !win) return;

    const controls = Array.from(win.querySelectorAll(
        ".chat-send-input, .chat-send-btn, .button-attach, "
        + ".chat-mic-btn, .model-dropdown-btn",
    ));
    const lock = win.querySelector(".model-switch-lock");
    const target = win.querySelector(".model-switch-target");
    const location = win.querySelector(".model-switch-location");
    const dropdown = win.querySelector(".model-dropdown-menu");

    winState.isModelSwitching = Boolean(switching);
    win.classList.toggle("is-model-switching", Boolean(switching));

    if (switching) {
        winState.modelSwitchControlState = controls.map(control => ({
            control,
            disabled: Boolean(control.disabled),
        }));
        controls.forEach(control => {
            control.disabled = true;
        });
        if (dropdown) dropdown.style.display = "none";
        if (target) target.textContent = targetLabel || "Gewähltes Modell";
        if (location) {
            location.textContent = windowId
                ? `Bestätigung läuft in ${windowId}`
                : "Das zugeordnete AG-Fenster bestätigt die Auswahl";
        }
        if (lock) lock.hidden = false;
    } else {
        (winState.modelSwitchControlState || []).forEach(entry => {
            if (entry.control?.isConnected) {
                entry.control.disabled = Boolean(entry.disabled);
            }
        });
        winState.modelSwitchControlState = null;
        if (lock) lock.hidden = true;
        if (winState.isArchived) {
            applyConversationArchivedState(convoId, true);
        }
    }

    const modelButton = win.querySelector(".model-dropdown-btn");
    if (modelButton) {
        modelButton.setAttribute("aria-busy", switching ? "true" : "false");
    }
}

async function selectChatModelForConvo(convoId, model) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    if (winState.isModelSwitching) {
        showToast(
            "info",
            "Modellwechsel läuft",
            "Bitte warte auf die Bestätigung des zugeordneten AG-Fensters.",
        );
        return;
    }

    const selected = normalizeModelSelection(model);
    const previous = winState.selectedModel;
    if (convoId.startsWith("proxy-") && selected.source !== "custom") {
        showToast("warning", "Modellwechsel nicht möglich", "Ein lokaler Proxy-Chat bleibt bei API-Modellen. Starte für Anti-Gravity einen neuen Chat.");
        return;
    }

    const menu = winState.domElement.querySelector(".model-dropdown-menu");
    if (menu) menu.style.display = "none";
    setChatModelSwitching(convoId, true, {
        targetLabel: selected.label,
        windowId: winState.desktopWindowId,
    });

    try {
        const res = await controlFetch('/api/antigravity/active-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                convo_id: convoId,
                model: selected.label,
                source: selected.source,
                custom_model_id: selected.custom_model_id || null
            })
        });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || "Fehler beim Wechseln.");
        const confirmed = data.confirmed === true;
        const confirmedSelection = {
            ...selected,
            label: data.model || selected.label,
            source: data.source === "custom" ? "custom" : selected.source,
        };
        updateChatModelLabel(winState, confirmedSelection);
        localStorage.setItem(
            "antigravity_selected_model_" + convoId,
            confirmedSelection.label,
        );
        localStorage.setItem(
            "antigravity_selected_model",
            confirmedSelection.label,
        );
        localStorage.setItem(
            "antigravity_selected_model_config_" + convoId,
            JSON.stringify(confirmedSelection),
        );
        if (data.window?.window_id) {
            winState.desktopWindowId = data.window.window_id;
            winState.desktopWindowReady = true;
            winState.desktopWindowUpdatedAt = Date.now();
            const status = winState.domElement.querySelector(
                ".desktop-window-status",
            );
            if (status) {
                status.textContent = `● ${data.window.window_id} · Modell bereit`;
                status.dataset.state = "ready";
            }
        }
        const detail = selected.source === "custom"
            ? `${confirmedSelection.label} wird über den Hub-Proxy verwendet.`
            : confirmed
                ? `${confirmedSelection.label} wurde in ${data.window?.window_id || "Anti-Gravity"} bestätigt.`
                : `${confirmedSelection.label} wurde für den nächsten stabilen Chat vorgemerkt.`;
        showToast(
            confirmed ? "success" : "info",
            confirmed ? "Modell bestätigt" : "Modell vorgemerkt",
            detail,
        );
    } catch (e) {
        console.error('[ModelSync] Failed to switch model:', e);
        if (previous) updateChatModelLabel(winState, previous);
        showToast("warning", "Modellwechsel", e.message || "Fehler beim Wechseln.");
    } finally {
        setChatModelSwitching(convoId, false);
    }
}

function selectChatModel(modelName, event) {
    let convoId = activeConvoId;
    if (event) {
        event.preventDefault();
        event.stopPropagation();
        const win = event.target.closest(".chat-window");
        if (win) {
            convoId = win.getAttribute("data-convo-id");
        }
    }
    if (convoId) {
        selectChatModelForConvo(convoId, modelName);
    } else {
        // Fallback for single layout
        const currentModelEl = document.getElementById("current-selected-model");
        if (currentModelEl) {
            let icon = "";
            if (modelName.startsWith("Gemini")) icon = "✨ ";
            else if (modelName.startsWith("Claude")) icon = "⚛️ ";
            else if (modelName.startsWith("GPT-OSS")) icon = "🤖 ";
            currentModelEl.innerText = icon + modelName;
        }
        const menu = document.getElementById("model-dropdown-menu");
        if (menu) menu.style.display = "none";
        localStorage.setItem("antigravity_selected_model", modelName);

        window._isModelSwitching = true;
        if (window._modelSwitchTimeout) clearTimeout(window._modelSwitchTimeout);
        window._modelSwitchTimeout = setTimeout(() => {
            window._isModelSwitching = false;
        }, 6000);

        controlFetch('/api/antigravity/active-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelName })
        }).then(res => res.json()).then(data => {
            if (data.success) {
                showToast("info", "Modell gewechselt", `Aktives Modell: ${modelName} (wird in ~2s angewendet)`);
            } else {
                showToast("warning", "Modellwechsel", data.error || "Fehler beim Wechseln.");
                window._isModelSwitching = false;
            }
        }).catch(e => {
            console.error('[ModelSync] Failed to switch model:', e);
            window._isModelSwitching = false;
        });
    }
}

// Close dropdown on click outside
document.addEventListener("click", function() {
    const menu = document.getElementById("model-dropdown-menu");
    if (menu) menu.style.display = "none";
    document.querySelectorAll(".model-dropdown-menu").forEach(m => {
        m.style.display = "none";
    });
});


// Clipboard Paste Event Listener (Strg+V)
document.addEventListener("paste", function(event) {
    if (!activeConvoId) return; // Only trigger paste if chat modal is active

    const items = (event.clipboardData || event.originalEvent.clipboardData).items;
    const previewContainer = document.getElementById("chat-attachment-preview");
    if (!previewContainer) return;

    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.indexOf("image") !== -1) {
            const file = item.getAsFile();
            if (chatUploadedImages.length >= 5) {
                showToast("error", "Limit erreicht", "Es können maximal 5 Bilder angehängt werden.");
                return;
            }

            const reader = new FileReader();
            reader.onload = function(e) {
                const dataUrl = e.target.result;
                const timestamp = Date.now();
                const name = `pasted_image_${timestamp}.png`;

                chatUploadedImages.push({
                    name: name,
                    type: "image/png",
                    data: dataUrl
                });

                const thumbIdx = chatUploadedImages.length - 1;
                const thumb = document.createElement("div");
                thumb.className = "chat-attachment-thumbnail";
                thumb.setAttribute("data-index", thumbIdx);
                thumb.innerHTML = `
                    <img src="${dataUrl}" alt="Pasted Image">
                    <span class="chat-attachment-remove" onclick="removeChatUploadedImage(${thumbIdx})">&times;</span>
                `;
                previewContainer.appendChild(thumb);
                previewContainer.style.display = "flex";
            };
            reader.readAsDataURL(file);
        }
    }
});

function resetChatComposerHeight(input) {
    if (!input) return;
    input.style.height = "36px";
}

function takeChatComposerDraft(convoId, input) {
    const winState = chatWindowsState[convoId];
    return {
        message: String(input?.value || "").trim(),
        attachments: Array.isArray(winState?.uploadedImages)
            ? [...winState.uploadedImages]
            : [],
    };
}

function clearChatComposerDraft(convoId, input) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    if (input) {
        input.value = "";
        resetChatComposerHeight(input);
    }
    winState.uploadedImages = [];
    renderChatAttachmentPreviewsForConvo(convoId);
}

function restoreChatComposerDraft(convoId, input, draft) {
    const winState = chatWindowsState[convoId];
    if (!winState || !draft) return;
    if (input) {
        input.value = draft.message || "";
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
    }
    winState.uploadedImages = Array.isArray(draft.attachments)
        ? [...draft.attachments]
        : [];
    renderChatAttachmentPreviewsForConvo(convoId);
}

function setChatDeliveryPhase(convoId, phase, {
    windowId = "",
    detail = "",
} = {}) {
    const winState = chatWindowsState[convoId];
    const body = winState?.domElement?.querySelector(".chat-window-body");
    if (!winState || !body) return;

    let status = body.querySelector(".chat-delivery-status");
    if (!phase) {
        status?.remove();
        winState.deliveryPhase = "";
        return;
    }
    if (!status) {
        status = document.createElement("div");
        status.className = "chat-delivery-status";
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        status.innerHTML = `
            <span class="chat-delivery-spinner" aria-hidden="true"></span>
            <span class="chat-delivery-copy">
                <strong></strong>
                <small></small>
            </span>
        `;
        body.appendChild(status);
    }

    const phases = {
        window: {
            title: "Anti-Gravity-Fenster wird gestartet",
            description: "Einen Moment – der Hub fährt ein freies Arbeitsfenster hoch und verbindet diesen Chat.",
        },
        preparing: {
            title: windowId
                ? `${windowId} bereitet die Zustellung vor`
                : "Zustellung wird vorbereitet",
            description: "Der richtige Chat und sein Composer werden sicher geprüft.",
        },
        verifying: {
            title: "Zustellung wird bestätigt",
            description: "Die Nachricht wurde an Anti-Gravity übergeben und wird im Zielchat verifiziert.",
        },
        confirmed: {
            title: "Nachricht zugestellt",
            description: "Anti-Gravity hat die Nachricht im richtigen Chat bestätigt.",
        },
        error: {
            title: "Zustellung nicht abgeschlossen",
            description: detail || "Der Entwurf wurde wieder in den Composer eingesetzt.",
        },
    };
    const copy = phases[phase] || phases.preparing;
    status.dataset.phase = phase;
    status.querySelector("strong").textContent = copy.title;
    status.querySelector("small").textContent = copy.description;
    winState.deliveryPhase = phase;
    body.appendChild(status);
    body.scrollTop = body.scrollHeight;
}

function finishChatDeliveryPhase(convoId, delay = 900) {
    const winState = chatWindowsState[convoId];
    const status = winState?.domElement?.querySelector(".chat-delivery-status");
    if (!status) return;
    window.setTimeout(() => {
        if (status.isConnected && status.dataset.phase === "confirmed") {
            status.remove();
            if (chatWindowsState[convoId]) {
                chatWindowsState[convoId].deliveryPhase = "";
            }
        }
    }, delay);
}

async function ensureDedicatedAntigravityWindow(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState || convoId === "new" || convoId.startsWith("proxy-")) {
        return { ready: true, skipped: true };
    }
    if (
        winState.desktopWindowReady
        && Date.now() - Number(winState.desktopWindowUpdatedAt || 0) < 15000
    ) {
        return { ready: true, reused: true };
    }
    if (winState.desktopWindowPromise) {
        return winState.desktopWindowPromise;
    }

    const status = winState.domElement?.querySelector(".desktop-window-status");
    if (status) {
        status.textContent = "○ Fenster wird vorbereitet…";
        status.dataset.state = "loading";
    }
    if (winState.pendingMessage) {
        setChatDeliveryPhase(convoId, "window");
    }
    winState.desktopWindowPromise = (async () => {
        const response = await controlFetch(
            `/api/antigravity/chats/${encodeURIComponent(convoId)}/window`,
            { method: "POST" }
        );
        const result = await response.json();
        if (!response.ok || !result.success || result.window?.ready !== true) {
            throw new Error(result.error || "Das dedizierte Anti-Gravity-Fenster ist nicht bereit.");
        }
        winState.desktopWindowReady = true;
        winState.desktopWindowId = result.window.window_id
            || result.window.target_id?.substring(0, 8)
            || "AG";
        winState.desktopWindowUpdatedAt = Date.now();
        if (status) {
            status.textContent = result.window.reused
                ? `● ${winState.desktopWindowId} bereit`
                : `● ${winState.desktopWindowId} bereit & minimiert`;
            status.title = `Anti-Gravity-Duplikat ${winState.desktopWindowId}`;
            status.dataset.state = "ready";
        }
        if (winState.pendingMessage) {
            setChatDeliveryPhase(convoId, "preparing", {
                windowId: winState.desktopWindowId,
            });
        }
        return result.window;
    })();

    try {
        return await winState.desktopWindowPromise;
    } catch (error) {
        winState.desktopWindowReady = false;
        if (status) {
            status.textContent = "× Fenster nicht bereit";
            status.dataset.state = "error";
            status.title = error.message;
        }
        throw error;
    } finally {
        winState.desktopWindowPromise = null;
    }
}

function antigravityConversationTitle(convoId) {
    if (convoId === "new") return "Neue Conversation";
    const conversation = antigravityConversationCatalog.find(
        item => item.convo_id === convoId
    );
    return String(conversation?.title || "").trim()
        || String(chatWindowsState[convoId]?.displayTitle || "").trim()
        || `Chat #${String(convoId || "").slice(0, 8)}`;
}

function syncChatWindowTitle(convoId) {
    const state = chatWindowsState[convoId];
    const title = state?.domElement?.querySelector(".chat-history-title");
    if (!title) return;
    const displayTitle = antigravityConversationTitle(convoId);
    title.textContent = displayTitle;
    title.title = displayTitle;
}

function syncOpenChatWindowTitles() {
    Object.keys(chatWindowsState).forEach(syncChatWindowTitle);
}

async function openChatHistory(convoId) {
    // Save to open chats list
    let openChats = [];
    try {
        openChats = JSON.parse(localStorage.getItem('antigravity_open_chats')) || [];
    } catch(e) {}
    if (!openChats.includes(convoId)) {
        openChats.push(convoId);
        localStorage.setItem('antigravity_open_chats', JSON.stringify(openChats));
    }

    // 1. Check if window already exists in DOM
    let win = document.getElementById(`chat-window-${convoId}`);
    if (win) {
        const catalogEntry = antigravityConversationCatalog.find(
            item => item.convo_id === convoId
        );
        if (catalogEntry) {
            chatWindowsState[convoId].displayTitle = catalogEntry.title;
            applyConversationArchivedState(
                convoId,
                Boolean(catalogEntry.archived),
            );
        }
        activeConvoId = convoId;
        win.style.zIndex = getNextZIndex();
        syncChatWindowTitle(convoId);
        if (
            convoId !== "new"
            && !convoId.startsWith("proxy-")
            && !chatWindowsState[convoId].isArchived
        ) {
            ensureDedicatedAntigravityWindow(convoId).catch(() => {});
        }
        return;
    }

    // 2. Create state
    const catalogEntry = antigravityConversationCatalog.find(
        item => item.convo_id === convoId
    );
    const winState = {
        convoId: convoId,
        displayTitle: catalogEntry?.title || "",
        isArchived: Boolean(catalogEntry?.archived),
        eventSource: null,
        modelSyncInterval: null,
        quotaPollInterval: null,
        lastStreamIdx: 0,
        pendingMessage: null,
        uploadedImages: [],
        selectedModel: { label: "", source: "official" },
        isModelSwitching: false,
        modelSwitchTimeout: null,
        modelSwitchControlState: null,
        domElement: null,
        isRecording: false,
        isListening: false,
        voicePhase: "idle",
        voiceStartedAt: 0,
        voiceUiInterval: null,
        voiceStopPromise: null,
        voicePollInterval: null,
        backgroundTasks: {},
        isRunning: antigravityActiveAgents.some(chat => chat.convo_id === convoId),
        hasAssistantOutput: false,
        thinkingAnimationInterval: null,
        thinkingAnimationTick: 0,
        streamCompletedAt: 0,
        streamErrorTimeout: null,
        desktopWindowReady: convoId === "new" || convoId.startsWith("proxy-"),
        desktopWindowPromise: null,
        desktopWindowId: null,
        desktopWindowUpdatedAt: 0,
        deliveryPhase: "",
        newConversationType: "project",
    };
    chatWindowsState[convoId] = winState;
    activeConvoId = convoId;

    // 3. Create DOM
    win = createChatWindowDOM(convoId);
    winState.domElement = win;
    applyConversationArchivedState(convoId, winState.isArchived);

    if (!winState.desktopWindowReady && !winState.isArchived) {
        ensureDedicatedAntigravityWindow(convoId).catch(error => {
            console.error("[Anti-Gravity Window]", error);
        });
    }

    // 5. Attach Drag & Resize Logic
    const header = win.querySelector(".chat-window-header");
    let isDragging = false;
    let startX, startY;
    let initialLeft, initialTop;

    header.addEventListener("mousedown", (e) => {
        if (win.classList.contains("chat-window-embedded")) return;
        if (e.target.closest("button") || e.target.closest(".modal-close-btn")) return;
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        initialLeft = parseInt(win.style.left) || 0;
        initialTop = parseInt(win.style.top) || 0;
        win.style.zIndex = getNextZIndex();
        e.preventDefault();
    });

    let isResizing = false;
    let startResizeX, startResizeY;
    let startWidth, startHeight;

    const resizeHandle = win.querySelector(".chat-resize-handle");
    if (resizeHandle) {
        resizeHandle.addEventListener("mousedown", (e) => {
            if (win.classList.contains("chat-window-embedded")) return;
            isResizing = true;
            startResizeX = e.clientX;
            startResizeY = e.clientY;
            startWidth = win.offsetWidth;
            startHeight = win.offsetHeight;
            win.style.zIndex = getNextZIndex();
            e.preventDefault();
            e.stopPropagation();
        });
    }

    const onMouseMove = (e) => {
        if (isDragging) {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            let newLeft = initialLeft + dx;
            let newTop = initialTop + dy;

            const vWidth = window.innerWidth;
            const vHeight = window.innerHeight;
            const winWidth = win.offsetWidth;
            const winHeight = win.offsetHeight;

            newLeft = Math.max(0, Math.min(newLeft, vWidth - winWidth));
            newTop = Math.max(0, Math.min(newTop, vHeight - winHeight));

            win.style.left = `${newLeft}px`;
            win.style.top = `${newTop}px`;
        }
        if (isResizing) {
            const dx = e.clientX - startResizeX;
            const dy = e.clientY - startResizeY;
            let newWidth = startWidth + dx;
            let newHeight = startHeight + dy;

            const vWidth = window.innerWidth;
            const vHeight = window.innerHeight;
            const currentLeft = parseInt(win.style.left) || 0;
            const currentTop = parseInt(win.style.top) || 0;

            newWidth = Math.max(300, Math.min(newWidth, vWidth - currentLeft));
            newHeight = Math.max(300, Math.min(newHeight, vHeight - currentTop));

            win.style.width = `${newWidth}px`;
            win.style.height = `${newHeight}px`;
        }
    };

    const onMouseUp = () => {
        if (isDragging || isResizing) {
            isDragging = false;
            isResizing = false;
            const state = {
                left: parseInt(win.style.left) || 0,
                top: parseInt(win.style.top) || 0,
                width: win.offsetWidth,
                height: win.offsetHeight
            };
            localStorage.setItem(`chat-window-state-${convoId}`, JSON.stringify(state));
        }
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);

    // 4. Attach Close Listener
    win.querySelector(".close-window-btn").addEventListener("click", () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        destroyChatWindow(convoId);
    });
    win.querySelector(".chat-popout-btn")?.addEventListener("click", () => {
        mountChatWindowFloating(convoId);
    });
    win.querySelector(".chat-archive-toggle-btn")?.addEventListener("click", () => {
        setConversationArchived(convoId, !winState.isArchived);
    });
    win.querySelector(".chat-restore-btn")?.addEventListener("click", () => {
        setConversationArchived(convoId, false);
    });

    // 6. Stacking focus click listener
    win.addEventListener("mousedown", () => {
        activeConvoId = convoId;
        win.style.zIndex = getNextZIndex();
    });

    // 7. Attach Attach File logic
    const attachBtn = win.querySelector(".button-attach");
    const fileInput = win.querySelector(".chat-file-input");
    attachBtn.addEventListener("click", () => {
        fileInput.click();
    });
    fileInput.addEventListener("change", (e) => {
        handleChatFileInputForConvo(convoId, e);
    });

    // 8. Attach Mic logic
    const micBtn = win.querySelector(".chat-mic-btn");
    micBtn.addEventListener("click", () => {
        toggleVoiceInputForConvo(convoId);
    });

    // 9. Attach Send Button click
    const sendBtn = win.querySelector(".chat-send-btn");
    sendBtn.addEventListener("click", () => {
        sendIntegrityChatMessageForConvo(convoId);
    });

    // 10. Attach Model Dropdown btn
    const dropdownBtn = win.querySelector(".model-dropdown-btn");
    dropdownBtn.addEventListener("click", (e) => {
        toggleModelDropdownForConvo(convoId, e);
    });

    // 11. Attach the safe, conversation-scoped Brain directory action.
    const brainBtn = win.querySelector(".button-brain-dir");
    brainBtn.addEventListener("click", () => {
        openConvoBrainDirForConvo(convoId);
    });
    win.querySelector(".button-web-ide")?.addEventListener("click", () => {
        openConversationIde(convoId);
    });

    // 12. Textarea Auto-Resizing & Key Handling (R2)
    const chatInput = win.querySelector(".chat-send-input");
    chatInput.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight) + "px";
    });
    chatInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendIntegrityChatMessageForConvo(convoId);
        }
    });

    // 13. Fetch Active Model
    try {
        const modelRes = await fetch(`/api/antigravity/active-model?convo_id=${convoId}`);
        if (modelRes.ok) {
            const modelData = await modelRes.json();
            if (modelData.model) {
                updateChatModelLabel(winState, {
                    label: modelData.model,
                    source: modelData.source === "custom" ? "custom" : "official",
                    custom_model_id: modelData.custom_model_id,
                    model_id: modelData.model_id
                });
                localStorage.setItem("antigravity_selected_model_" + convoId, modelData.model);
            }
        }
    } catch (e) {
        console.error('[ModelSync] Failed to fetch active model:', e);
    }

    // 14. Start Model Sync Polling (every 3 seconds)
    winState.modelSyncInterval = setInterval(async () => {
        if (winState.isModelSwitching) return;
        try {
            const res = await fetch(`/api/antigravity/active-model?convo_id=${convoId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.model && winState.selectedModel?.label !== data.model) {
                    updateChatModelLabel(winState, {
                        label: data.model,
                        source: data.source === "custom" ? "custom" : "official",
                        custom_model_id: data.custom_model_id,
                        model_id: data.model_id
                    });
                    localStorage.setItem("antigravity_selected_model_" + convoId, data.model);
                }
            }
        } catch (e) { /* ignore */ }
    }, 3000);

    // 15. Start Quota Polling (every 15 seconds)
    loadIntegrityQuota();
    winState.quotaPollInterval = setInterval(() => {
        loadIntegrityQuota();
        loadTokenStatsForConvo(convoId);
    }, 15000);

    // 16. Load History
    const body = win.querySelector(".chat-window-body");
    body.innerHTML = `
        <div class="workspace-placeholder placeholder-sm">
            <div class="file-preview-spinner" style="margin: 0 auto var(--space-2) auto;"></div>
            <span>Lade Verlauf...</span>
        </div>
    `;

    try {
        const res = await fetch(`/api/antigravity/chats/${convoId}/history`);
        if (!res.ok) throw new Error("Fehler beim Laden del Verlaufs");
        const data = await res.json();

        const history = data.history || data;
        const maxIdx = data.max_idx || 0;

        renderHistoryListForConvo(convoId, history);
        winState.lastStreamIdx = maxIdx;

        // Hub-local proxy replies are returned directly and do not use Antigravity SSE.
        if (
            !winState.isArchived
            && winState.selectedModel?.source !== "custom"
            && !convoId.startsWith("proxy-")
        ) {
            startChatPollingForConvo(convoId);
            loadTokenStatsForConvo(convoId);
        }

    } catch (err) {
        body.innerHTML = `<div class="workspace-placeholder placeholder-sm text-danger">Fehler: ${escapeHTML(err.message)}</div>`;
    }
}

const CHAT_IMAGE_LIMIT = 5;
const CHAT_IMAGE_MAX_BYTES = 20 * 1024 * 1024;

function queueChatImageForConvo(convoId, file, fallbackName = "") {
    const winState = chatWindowsState[convoId];
    if (!winState || !file) return false;
    if (!String(file.type || "").startsWith("image/")) {
        showToast("error", "Datei nicht unterstützt", "Bitte wähle eine PNG-, JPG-, GIF- oder WebP-Datei.");
        return false;
    }
    if (Number(file.size || 0) > CHAT_IMAGE_MAX_BYTES) {
        showToast("error", "Bild zu groß", "Ein Bild darf maximal 20 MiB groß sein.");
        return false;
    }
    if (winState.uploadedImages.length >= CHAT_IMAGE_LIMIT) {
        showToast("error", "Limit erreicht", `Es können maximal ${CHAT_IMAGE_LIMIT} Bilder angehängt werden.`);
        return false;
    }

    const reader = new FileReader();
    reader.onload = function(event) {
        const dataUrl = event.target?.result;
        if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/")) {
            showToast("error", "Bild nicht gelesen", "Die ausgewählte Bilddatei konnte nicht verarbeitet werden.");
            return;
        }
        winState.uploadedImages.push({
            name: file.name || fallbackName || `image_${Date.now()}.png`,
            type: file.type || "image/png",
            data: dataUrl
        });
        renderChatAttachmentPreviewsForConvo(convoId);
    };
    reader.onerror = function() {
        showToast("error", "Bild nicht gelesen", file.name || fallbackName || "Unbekannte Datei");
    };
    reader.readAsDataURL(file);
    return true;
}

function handleChatFileInputForConvo(convoId, event) {
    const files = event.target.files;
    if (!files) return;
    Array.from(files).forEach(file => {
        queueChatImageForConvo(convoId, file);
    });

    event.target.value = "";
}

function removeChatUploadedImageForConvo(convoId, index) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    winState.uploadedImages.splice(index, 1);
    renderChatAttachmentPreviewsForConvo(convoId);
}

function renderChatAttachmentPreviewsForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const previewContainer = winState.domElement.querySelector(".chat-attachment-preview");
    if (!previewContainer) return;

    previewContainer.innerHTML = "";
    if (winState.uploadedImages.length === 0) {
        previewContainer.style.display = "none";
    } else {
        previewContainer.style.display = "flex";
        winState.uploadedImages.forEach((img, idx) => {
            const thumb = document.createElement("div");
            thumb.className = "chat-attachment-thumbnail";
            thumb.setAttribute("data-index", idx);
            thumb.innerHTML = `
                <img src="${img.data}" alt="${escapeHTML(img.name)}">
                <span class="chat-attachment-remove">&times;</span>
            `;
            thumb.querySelector(".chat-attachment-remove").addEventListener("click", () => {
                removeChatUploadedImageForConvo(convoId, idx);
            });
            previewContainer.appendChild(thumb);
        });
    }
}

async function openConvoBrainDirForConvo(convoId) {
    if (convoId === "new" || convoId.startsWith("proxy-")) {
        showToast("info", "Noch kein Brain-Ordner", "Der Ordner entsteht erst, nachdem Anti-Gravity die Conversation angelegt hat.");
        return;
    }
    try {
        const res = await controlFetch(`/api/antigravity/chats/${encodeURIComponent(convoId)}/brain/open`, {
            method: "POST",
        });
        const result = await res.json();
        if (!res.ok || result.success !== true) {
            throw new Error(result.error || "Brain-Ordner konnte nicht geöffnet werden.");
        }
        showToast("success", "Ordner geöffnet", "Der Conversation-Ordner wurde im Windows Explorer geöffnet.");
    } catch (e) {
        showToast("error", "Ordner nicht geöffnet", e.message);
    }
}

function reserveIdeWindow(label) {
    const popup = window.open("", "_blank");
    if (!popup) return null;
    popup.document.title = "Anti-Gravity Web IDE";
    popup.document.body.innerHTML = `
        <main style="min-height:100vh;display:grid;place-items:center;background:#0c0b12;color:#f3efff;font:16px system-ui;padding:24px;box-sizing:border-box">
            <section style="max-width:520px;text-align:center">
                <div style="font-size:38px;margin-bottom:16px">&lt;/&gt;</div>
                <h1 style="font-size:22px;margin:0 0 10px">Web-IDE wird vorbereitet</h1>
                <p style="margin:0;color:#aaa4b8">${escapeHTML(label || "Workspace wird aufgelöst…")}</p>
            </section>
        </main>
    `;
    return popup;
}

async function requestWebIde(endpoint, label) {
    const popup = reserveIdeWindow(label);
    try {
        const response = await controlFetch(endpoint, { method: "POST" });
        const result = await response.json();
        if (!response.ok || result.success !== true || !result.url) {
            const installInfo = result.install_hint
                ? ` ${result.install_hint}`
                : "";
            const nodeInfo = result.node_version
                ? ` Installiert ist ${result.node_version}; empfohlen wird Node.js 22.`
                : "";
            throw new Error(
                (result.error || "Web-IDE ist nicht bereit.")
                + installInfo
                + nodeInfo
            );
        }
        if (!String(result.url).startsWith("http://127.0.0.1:8080/")) {
            throw new Error("Der Hub hat eine unerwartete IDE-Adresse geliefert.");
        }
        if (!popup) {
            showToast(
                "warning",
                "Popup blockiert",
                "Erlaube Popups für den Hub und öffne die Web-IDE erneut.",
            );
            return;
        }
        popup.location.replace(result.url);
        showToast(
            "success",
            "Web-IDE geöffnet",
            `${result.workspace?.label || label || "Workspace"} läuft lokal in code-server.`,
        );
    } catch (error) {
        if (popup && !popup.closed) popup.close();
        showToast("error", "Web-IDE nicht geöffnet", error.message);
    }
}

function openProjectIde(projectId = currentProjectId) {
    const numericId = Number(projectId);
    if (!numericId) {
        showToast("info", "Kein Projekt gewählt", "Wähle zuerst ein Hub-Projekt aus.");
        return;
    }
    const project = projects.find(item => Number(item.id) === numericId);
    requestWebIde(
        `/api/projects/${numericId}/ide/open`,
        project?.name || "Projekt-Workspace",
    );
}

function openConversationIde(convoId) {
    if (convoId === "new" || convoId.startsWith("proxy-")) {
        showToast(
            "info",
            "Noch kein nativer Workspace",
            "Lege die Conversation zuerst in Anti-Gravity an.",
        );
        return;
    }
    requestWebIde(
        `/api/antigravity/chats/${encodeURIComponent(convoId)}/ide/open`,
        antigravityConversationTitle(convoId),
    );
}

function createChatWindowDOM(convoId) {
    const win = document.createElement("div");
    win.className = "chat-window glass-card";
    win.id = `chat-window-${convoId}`;
    win.setAttribute("data-convo-id", convoId);
    win.style.zIndex = getNextZIndex();

    // Arrange side-by-side by default
    const existingWindows = document.querySelectorAll(".chat-window");
    const offsetCount = existingWindows.length;
    const defaultWidth = 420;
    const defaultHeight = 600;
    const spacing = 20;

    let leftPos = spacing + offsetCount * (defaultWidth + spacing);
    let topPos = 100;
    let width = defaultWidth;
    let height = defaultHeight;

    const savedState = localStorage.getItem(`chat-window-state-${convoId}`);
    if (savedState) {
        try {
            const state = JSON.parse(savedState);
            if (typeof state.left === 'number') leftPos = state.left;
            if (typeof state.top === 'number') topPos = state.top;
            if (typeof state.width === 'number') width = state.width;
            if (typeof state.height === 'number') height = state.height;

            const vWidth = window.innerWidth;
            const vHeight = window.innerHeight;
            width = Math.max(300, Math.min(width, vWidth - 50));
            height = Math.max(300, Math.min(height, vHeight - 50));
            leftPos = Math.max(0, Math.min(leftPos, vWidth - width));
            topPos = Math.max(0, Math.min(topPos, vHeight - height));
        } catch(e) {}
    }

    win.style.width = `${width}px`;
    win.style.height = `${height}px`;
    win.style.left = `${leftPos}px`;
    win.style.top = `${topPos}px`;
    win.style.position = "fixed";
    const displayTitle = antigravityConversationTitle(convoId);

    win.innerHTML = `
        <div class="chat-window-header modal-header" style="cursor: move; user-select: none;">
            <div class="chat-window-heading">
                <h3 class="chat-history-title" title="${escapeHTML(displayTitle)}">${escapeHTML(displayTitle)}</h3>
                <span class="desktop-window-status" data-state="${convoId === 'new' || convoId.startsWith('proxy-') ? 'ready' : 'loading'}">
                    ${convoId === 'new' || convoId.startsWith('proxy-') ? '● Hub-Chat bereit' : '○ Fenster wird vorbereitet…'}
                </span>
                <span class="chat-agent-activity" ${chatWindowsState[convoId]?.isRunning ? "" : "hidden"}>
                    <span class="antigravity-thinking-symbol" aria-hidden="true">✢</span>
                    <span class="chat-agent-activity-copy">Agent arbeitet</span>
                </span>
            </div>
            <div style="display: flex; gap: var(--space-2); align-items: center;">
                <button class="btn btn-ghost btn-xs chat-popout-btn" title="Als eigenes paralleles Fenster öffnen">↗</button>
                <button class="btn btn-ghost btn-xs button-web-ide"
                    ${convoId === "new" || convoId.startsWith("proxy-") ? "hidden" : ""}
                    title="Workspace in der Web-IDE öffnen"
                    aria-label="Workspace in der Web-IDE öffnen">&lt;/&gt;</button>
                <button class="btn btn-ghost btn-xs button-brain-dir" title="Brain-Ordner öffnen">📁</button>
                <button class="btn btn-ghost btn-xs chat-archive-toggle-btn"
                    data-convo-id="${escapeHTML(convoId)}"
                    ${convoId === "new" || convoId.startsWith("proxy-") ? "hidden" : ""}
                    title="Conversation archivieren"
                    aria-label="Conversation archivieren">▣</button>
                <span class="modal-close-btn close-window-btn">&times;</span>
            </div>
        </div>
        <div class="chat-window-body modal-body" style="flex: 1; overflow-y: auto; padding: var(--space-4); background: rgba(0,0,0,0.15); display: flex; flex-direction: column; gap: var(--space-3); min-height: 0;">
            <!-- Chat history bubbles loaded dynamically -->
        </div>
        <div class="modal-input-area" style="border-top: 1px solid var(--color-border-default); background: var(--color-bg-secondary); display: flex; flex-direction: column; flex-shrink: 0;">
            <div class="chat-archive-lock" hidden role="status" aria-live="polite">
                <span class="chat-archive-lock-icon" aria-hidden="true">▣</span>
                <span class="chat-archive-lock-copy">
                    <strong>Conversation archiviert</strong>
                    <small>Dieser Verlauf ist schreibgeschützt. Stelle ihn zuerst in Anti-Gravity wieder her.</small>
                </span>
                <button class="btn btn-secondary btn-sm chat-restore-btn"
                    data-convo-id="${escapeHTML(convoId)}">Wiederherstellen</button>
            </div>
            <div class="model-switch-lock" hidden role="status" aria-live="polite">
                <span class="model-switch-spinner" aria-hidden="true"></span>
                <span class="model-switch-copy">
                    <strong>Modell wird gewechselt</strong>
                    <span class="model-switch-target">Gewähltes Modell</span>
                    <small class="model-switch-location">Das zugeordnete AG-Fenster bestätigt die Auswahl</small>
                </span>
            </div>
            <div class="chat-attachment-preview" style="display: none; padding: var(--space-2) var(--space-4); gap: var(--space-2); flex-wrap: wrap; background: rgba(0,0,0,0.1); border-bottom: 1px solid var(--color-border-default);">
                <!-- Uploaded thumbnails dynamically added here -->
            </div>
            <div class="chat-voice-status" hidden role="status" aria-live="polite">
                <span class="chat-voice-live-dot" aria-hidden="true"></span>
                <span class="chat-voice-status-copy">
                    <strong>Aufnahme läuft</strong>
                    <small>Mikrofon erneut drücken, um die Aufnahme zu beenden.</small>
                </span>
                <time class="chat-voice-elapsed">0:00</time>
            </div>

            <div class="chat-composer-row" style="padding: var(--space-3) var(--space-4); display: flex; gap: var(--space-2); align-items: center;">
                <button class="btn btn-secondary button-attach" title="Bild anhängen" style="border-radius: 50%; width: 36px; height: 36px; padding: 0; display: flex; align-items: center; justify-content: center; shrink: 0;">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 -960 960 960" fill="currentColor"><path d="M450-450H220v-60H450V-740h60v230H740v60H510v230H450V-450Z"></path></svg>
                </button>
                <input type="file" class="chat-file-input" accept="image/*" multiple style="display: none;">

                <textarea class="chat-send-input form-control" placeholder="Schreibe eine Nachricht an den Agenten..." style="flex: 1; min-height: 36px; max-height: 200px; resize: none; overflow-y: auto;"></textarea>

                <button class="btn btn-secondary chat-mic-btn" title="Sprachnachricht aufnehmen" aria-label="Sprachnachricht aufnehmen" aria-pressed="false" style="border-radius: 50%; width: 36px; height: 36px; padding: 0; display: flex; align-items: center; justify-content: center; shrink: 0; opacity: 0.7;">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 -960 960 960" fill="currentColor" style="width:16px; height:16px;"><path d="M409.04-449.04Q380-478.08 380-520V-760q0-41.92 29.04-70.96T480-860t70.96,29.04T580-760v240q0,41.92-29.04,70.96T480-420t-70.96-29.04ZM480-640ZM450-130V-261.85q-99-11.31-164.5-84.92T220-520h60q0,83 58.5,141.5T480-320t141.5-58.5T680-520h60q0,99.61-65.5,173.23T510-261.85V-130H450Zm58.5-361.5Q520-503 520-520V-760q0-17-11.5-28.5T480-800t-28.5,11.5T440-760v240q0,17 11.5,28.5T480-480t28.5-11.5Z"></path></svg>
                </button>

                <button class="btn btn-primary chat-send-btn" title="Nachricht senden" style="border-radius: 50%; width: 36px; height: 36px; padding: 0; display: flex; align-items: center; justify-content: center; shrink: 0; background: var(--color-accent-neon); border-color: var(--color-accent-neon);">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 -960 960 960" fill="currentColor" style="color: var(--color-bg-primary);"><path d="M120-160v-640l760 320-760 320Zm60-93 544-227-544-230v168l242 62-242 60v167Zm0 0v-457 457Z"></path></svg>
                </button>
            </div>

            <div style="padding: var(--space-2) var(--space-4); border-top: 1px solid rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: space-between; font-size: 11px; background: rgba(0,0,0,0.15);">
                <div style="display: flex; align-items: center; gap: var(--space-2);">
                    <div class="model-dropdown-container" style="position: relative; display: inline-block;">
                        <button type="button" id="model-dropdown-btn" class="btn btn-secondary model-dropdown-btn" style="height: 24px; padding: 0 var(--space-2); font-size: 10px; display: flex; align-items: center; gap: 4px; border-radius: var(--radius-sm);">
                            <span id="current-selected-model" class="current-selected-model">Modell wird geladen…</span>
                            <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 -960 960 960" fill="currentColor"><path d="M480-541.85l-184,184L253.85-400L480-626.15L706.15-400L664-357.85l-184-184Z"></path></svg>
                        </button>
                        <div id="model-dropdown-menu" class="dropdown-menu model-dropdown-menu" style="display: none; position: absolute; bottom: 30px; left: 0; background: var(--color-bg-primary); border: 1px solid var(--color-border-default); border-radius: var(--radius-md); box-shadow: 0 4px 12px rgba(0,0,0,0.5); z-index: 1000; min-width: 220px;">
                            <div style="padding: var(--space-2) var(--space-3); font-size: 10px; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--color-border-default);">Model</div>
                        </div>
                    </div>
                </div>

                <div class="antigravity-quota-display" style="font-family: var(--font-mono); color: var(--color-text-secondary); font-size: 10px; display: flex; align-items: center; gap: var(--space-1); cursor: pointer; user-select: none;">
                    <span id="quota-gemini" class="quota-gemini" title="Gemini Quota">G: --%</span>
                    <span style="opacity: 0.3;">|</span>
                    <span id="quota-claude" class="quota-claude" title="Claude Quota">C: --%</span>
                    <span style="opacity: 0.3;">|</span>
                    <span id="quota-token" class="quota-token" title="Token count">T: --</span>
                </div>
            </div>
            <div class="chat-resize-handle" style="position: absolute; bottom: 0; right: 0; width: 20px; height: 20px; cursor: se-resize; z-index: 10; display: flex; align-items: center; justify-content: center; color: var(--color-text-secondary); opacity: 0.5;">
                <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"><path d="M12 12H4v-1h7V4h1v8z"/></svg>
            </div>
        </div>
    `;

    document.body.appendChild(win);
    return win;
}

async function loadTokenStatsForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const tEl = winState.domElement.querySelector(".quota-token");
    if (!tEl) return;

    try {
        const res = await fetch(`/api/antigravity/tokens/${convoId}`);
        if (!res.ok) throw new Error("Token fetch failed");
        const data = await res.json();

        const totalIn = data.totalInput || 0;
        const totalOut = data.totalOutput || 0;
        const totalUncached = data.totalUncached || 0;
        const cacheRatio = data.cacheRatio || 0;

        function formatTokens(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(0) + 'k';
            return num.toString();
        }

        const totalStr = formatTokens(totalIn);
        tEl.innerText = `T: ${totalStr}`;
        tEl.title = `Akkumulierter Verbrauch:\n• Input: ${totalIn.toLocaleString('de-DE')}\n  - Cached: ${(totalIn - totalUncached).toLocaleString('de-DE')} (${cacheRatio}%)\n  - Uncached: ${totalUncached.toLocaleString('de-DE')}\n• Output: ${totalOut.toLocaleString('de-DE')}`;

        if (totalIn > 0) {
            tEl.style.display = '';
        }
    } catch (e) {
        tEl.innerText = "T: --";
        tEl.title = "Token-Daten nicht verfügbar";
    }
}

function renderHistoryListForConvo(convoId, history) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const body = winState.domElement.querySelector(".chat-window-body");
    if (!body) return;

    let entries = [];
    if (history && history.length > 0) {
        entries = [...history];
    }

    if (winState.pendingMessage) {
        const alreadyInDb = entries.some(msg => msg.type === "message" && msg.role === "user" && msg.content === winState.pendingMessage);
        if (alreadyInDb) {
            winState.pendingMessage = null;
        } else {
            entries.push({
                type: "message",
                role: "user",
                content: winState.pendingMessage,
                attachments: []
            });
        }
    }

    if (entries.length === 0) {
        winState.backgroundTasks = {};
        body.innerHTML = `<div class="workspace-placeholder placeholder-sm">Dieser Chat enthält noch keine Nachrichten oder Denkprozesse.</div>`;
        return;
    }

    winState.backgroundTasks = {};
    entries.forEach(entry => {
        const info = getToolCommandInfo(entry);
        if (info?.backgroundTask) {
            winState.backgroundTasks[String(entry.idx)] = entry;
        }
    });

    const groupedEntries = [];
    let pendingToolEntries = [];
    const flushToolEntries = () => {
        if (!pendingToolEntries.length) return;
        groupedEntries.push({
            type: "tool_activity_group",
            entries: pendingToolEntries,
        });
        pendingToolEntries = [];
    };
    entries.forEach(msg => {
        if (msg.type === "tool_call" || msg.type === "tool_output") {
            pendingToolEntries.push(msg);
            return;
        }
        flushToolEntries();
        groupedEntries.push(msg);
    });
    flushToolEntries();

    let html = groupedEntries.map(msg => {
        if (msg.type === "tool_activity_group") {
            return getToolActivityGroupHtml(msg.entries);
        }
        if (msg.type === "message") {
            const roleLabel = msg.role === "user"
                ? "Du"
                : (msg.source === "custom" ? `Proxy · ${msg.model_name || "API-Modell"}` : "Anti-Gravity Agent");
            const bubbleClass = msg.role === "user" ? "chat-bubble-user" : "chat-bubble-assistant";

            let attsHtml = "";
            if (msg.attachments && msg.attachments.length > 0) {
                attsHtml = `<div class="chat-message-attachments-container">`;
                msg.attachments.forEach(att => {
                    const mediaUrl = String(att.data || "").startsWith("data:image/")
                        ? att.data
                        : `/api/antigravity/media?path=${encodeURIComponent(att.file_path || "")}`;
                    const fileName = att.file_name || att.name || "Bild";
                    attsHtml += `
                        <img src="${mediaUrl}" alt="${escapeHTML(fileName)}" class="chat-message-image">
                    `;
                });
                attsHtml += `</div>`;
            }

            let thinkingHtml = "";
            if (msg.role === "assistant" && msg.thinking) {
                thinkingHtml = getThoughtHtml(msg.thinking, entries.indexOf(msg));
            }

            return `
                <div class="chat-bubble ${bubbleClass}" data-idx="${msg.idx || ''}">
                    <span class="chat-bubble-meta">${escapeHTML(roleLabel)}</span>
                    ${thinkingHtml}
                    <div class="chat-bubble-content">${
                        msg.role === "assistant"
                            ? renderMarkdownContent(msg.content)
                            : escapeHTML(msg.content).replace(/\n/g, "<br>")
                    }</div>
                    ${attsHtml}
                </div>
            `;
        } else if (msg.type === "tool_call") {
            return getToolHtml(msg);
        } else if (msg.type === "tool_output") {
            return getToolOutputHtml(msg);
        }
        return "";
    }).join("");

    if (winState.isRunning && !winState.hasAssistantOutput) {
        html += chatRunningLoaderHTML();
    }
    html += getBackgroundTasksPanelHtml(
        Object.values(winState.backgroundTasks),
    );

    body.innerHTML = html;
    if (winState.isRunning) startAntigravityThinkingAnimation(convoId);
    body.scrollTop = body.scrollHeight;
}

function appendPendingUserBubble(convoId, message, attachments, pendingId, metaText) {
    const winState = chatWindowsState[convoId];
    const body = winState?.domElement?.querySelector(".chat-window-body");
    if (!body) return null;
    body.querySelector(".workspace-placeholder")?.remove();

    const attachmentHtml = (attachments || []).map(attachment => `
        <img src="${attachment.data}"
            class="chat-message-image"
            alt="${escapeHTML(attachment.name || "Bild")}">
    `).join("");
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble chat-bubble-user chat-bubble-new";
    bubble.id = pendingId;
    bubble.innerHTML = `
        <span class="chat-bubble-meta">${escapeHTML(metaText)}</span>
        <div class="chat-bubble-content">${escapeHTML(message).replace(/\n/g, "<br>")}</div>
        ${attachmentHtml
            ? `<div class="chat-message-attachments-container">${attachmentHtml}</div>`
            : ""}
    `;
    body.appendChild(bubble);
    body.scrollTop = body.scrollHeight;
    return bubble;
}

async function sendCustomProxyMessageForConvo(convoId, message) {
    const winState = chatWindowsState[convoId];
    if (!winState || winState.selectedModel?.source !== "custom") return;
    const input = winState.domElement.querySelector(".chat-send-input");
    const btn = winState.domElement.querySelector(".chat-send-btn");
    const attachBtn = winState.domElement.querySelector(".button-attach");
    const fileInput = winState.domElement.querySelector(".chat-file-input");
    const attachments = [...winState.uploadedImages];
    const draft = {message, attachments};
    const pendingId = `pending-proxy-${Date.now()}`;

    input.disabled = true;
    if (btn) btn.disabled = true;
    clearChatComposerDraft(convoId, input);
    appendPendingUserBubble(
        convoId,
        message,
        attachments,
        pendingId,
        "Du · Proxy antwortet…",
    );

    try {
        if (convoId === "new" && !currentProjectId) {
            throw new Error("Bitte zuerst ein Projekt auswählen.");
        }
        const isNew = convoId === "new";
        const endpoint = isNew
            ? "/api/antigravity/proxy-chats"
            : `/api/antigravity/chats/${encodeURIComponent(convoId)}/proxy-message`;
        const response = await controlFetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_id: isNew ? currentProjectId : undefined,
                custom_model_id: winState.selectedModel.custom_model_id,
                message,
                attachments
            })
        });
        const result = await response.json();
        if (!response.ok || result.verified !== true) {
            throw new Error(result.error || "Die Proxy-Antwort konnte nicht bestätigt werden.");
        }

        if (isNew) {
            const reopenEmbedded = winState.domElement.classList.contains("chat-window-embedded");
            destroyChatWindow(convoId);
            await loadIntegrityChats();
            if (reopenEmbedded) {
                await openChatInWorkspace(result.convo_id);
            } else {
                await openChatHistory(result.convo_id);
            }
        } else {
            const historyResponse = await fetch(`/api/antigravity/chats/${encodeURIComponent(convoId)}/history`);
            const historyData = await historyResponse.json();
            if (!historyResponse.ok) throw new Error(historyData.error || "Proxy-Verlauf konnte nicht geladen werden.");
            renderHistoryListForConvo(convoId, historyData.history || []);
            winState.lastStreamIdx = historyData.max_idx || winState.lastStreamIdx;
        }
        showToast("success", "Proxy-Antwort erhalten", `${winState.selectedModel.label} hat über die konfigurierte API geantwortet.`);
    } catch (error) {
        winState.domElement.querySelector(`#${pendingId}`)?.remove();
        restoreChatComposerDraft(convoId, input, draft);
        showToast("error", "Proxy-Anfrage fehlgeschlagen", error.message);
    } finally {
        input.disabled = false;
        if (btn) btn.disabled = false;
        input.focus();
    }
}

async function sendIntegrityChatMessageForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    if (winState.isArchived) {
        showToast(
            "info",
            "Conversation ist archiviert",
            "Stelle den Chat zuerst wieder her, bevor du eine Nachricht sendest.",
        );
        return;
    }
    if (winState.isModelSwitching) {
        showToast(
            "info",
            "Modellwechsel läuft",
            "Die Nachricht bleibt gesperrt, bis Anti-Gravity das Modell bestätigt hat.",
        );
        return;
    }

    const input = winState.domElement.querySelector(".chat-send-input");
    const btn = winState.domElement.querySelector(".chat-send-btn");
    const attachBtn = winState.domElement.querySelector(".button-attach");
    const fileInput = winState.domElement.querySelector(".chat-file-input");
    if (!input) return;

    const message = input.value.trim();
    if (!message && winState.uploadedImages.length === 0) return;

    if (winState.selectedModel?.source === "custom") {
        await sendCustomProxyMessageForConvo(convoId, message);
        return;
    }

    const isNewConversation = convoId === "new";
    const conversationType = winState.newConversationType || "project";
    if (
        isNewConversation
        && conversationType === "project"
        && !currentProjectId
    ) {
        showToast(
            "error",
            "Projekt fehlt",
            "Bitte zuerst ein Projekt auswählen.",
        );
        return;
    }

    const draft = takeChatComposerDraft(convoId, input);
    const sendAttachments = [...draft.attachments];
    const pendingId = `pending-delivery-${convoId}-${Date.now()}`;

    input.disabled = true;
    if (btn) btn.disabled = true;
    if (attachBtn) attachBtn.disabled = true;
    if (fileInput) fileInput.disabled = true;
    winState.pendingMessage = message;
    clearChatComposerDraft(convoId, input);
    appendPendingUserBubble(
        convoId,
        message,
        sendAttachments,
        pendingId,
        isNewConversation || !winState.desktopWindowReady
            ? "Du · Anti-Gravity-Fenster wird gestartet…"
            : "Du · Zustellung wird vorbereitet…",
    );
    setChatDeliveryPhase(
        convoId,
        isNewConversation || !winState.desktopWindowReady
            ? "window"
            : "preparing",
        {windowId: winState.desktopWindowId || ""},
    );

    if (isNewConversation) {
        try {
            const createResponse = await controlFetch("/api/antigravity/chats", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    project_id: conversationType === "project" ? currentProjectId : null,
                    conversation_type: conversationType,
                    message: message,
                    attachments: sendAttachments
                })
            });
            const created = await createResponse.json();
            if (!createResponse.ok || created.verified !== true || !created.convo_id || created.convo_id === "new") {
                throw new Error(created.error || "Der Chat hat keine gültige ID erhalten.");
            }

            const reopenEmbedded = winState.domElement.classList.contains("chat-window-embedded");
            destroyChatWindow(convoId);
            await loadIntegrityChats();
            if (reopenEmbedded) {
                await openChatInWorkspace(created.convo_id);
            } else {
                await openChatHistory(created.convo_id);
            }
            showToast(
                "success",
                conversationType === "project" ? "Projektchat erstellt" : "Conversation erstellt",
                conversationType === "project"
                    ? "Projekt, Chat und erste Nachricht wurden in Anti-Gravity bestätigt."
                    : "Normale Conversation und erste Nachricht wurden in Anti-Gravity bestätigt."
            );
            return;
        } catch (err) {
            winState.domElement.querySelector(`#${pendingId}`)?.remove();
            winState.pendingMessage = null;
            restoreChatComposerDraft(convoId, input, draft);
            setChatDeliveryPhase(convoId, "error", {detail: err.message});
            showToast(
                "error",
                "Chat-Erstellung fehlgeschlagen",
                err.message,
            );
            input.disabled = false;
            if (btn) btn.disabled = false;
            if (attachBtn) attachBtn.disabled = false;
            if (fileInput) fileInput.disabled = false;
            input.focus();
            return;
        }
    }

    try {
        await ensureDedicatedAntigravityWindow(convoId);
    } catch (error) {
        winState.domElement.querySelector(`#${pendingId}`)?.remove();
        winState.pendingMessage = null;
        restoreChatComposerDraft(convoId, input, draft);
        setChatDeliveryPhase(convoId, "error", {detail: error.message});
        input.disabled = false;
        if (btn) btn.disabled = false;
        if (attachBtn) attachBtn.disabled = false;
        if (fileInput) fileInput.disabled = false;
        showToast(
            "error",
            "Anti-Gravity-Fenster nicht bereit",
            error.message,
        );
        input.focus();
        return;
    }
    setChatDeliveryPhase(convoId, "preparing", {
        windowId: winState.desktopWindowId || "",
    });

    try {
        const res = await controlFetch(`/api/antigravity/chats/${convoId}/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                attachments: sendAttachments
            })
        });
        const result = await res.json();
        const pendingVerification = (
            result.accepted === true
            && result.pending_verification === true
        );
        if (!res.ok || (result.verified !== true && !pendingVerification)) {
            throw new Error(result.error || "Die Zustellung konnte nicht bestätigt werden.");
        }
        if (result.window?.window_id) {
            winState.desktopWindowId = result.window.window_id;
            winState.desktopWindowReady = true;
            winState.desktopWindowUpdatedAt = Date.now();
            const workerStatus = winState.domElement.querySelector(".desktop-window-status");
            if (workerStatus) {
                workerStatus.textContent = `● ${result.window.window_id} · Arbeitet`;
                workerStatus.dataset.state = "ready";
            }
        }

        const pendingBubble = winState.domElement.querySelector(`#${pendingId}`);
        const pendingMeta = pendingBubble?.querySelector(".chat-bubble-meta");
        if (pendingMeta) {
            pendingMeta.textContent = pendingVerification
                ? "Du · An Anti-Gravity gesendet · Bestätigung läuft…"
                : "Du · Zugestellt ✓";
        }
        setChatDeliveryPhase(
            convoId,
            pendingVerification ? "verifying" : "confirmed",
        );
        if (!pendingVerification) {
            finishChatDeliveryPhase(convoId);
        }
        winState.pendingMessage = null;
        winState.streamCompletedAt = 0;
        setChatRunningState(convoId, true, {hasAssistantOutput: false});
        startChatPollingForConvo(convoId);
        loadIntegrityChats({silent: true});
    } catch (err) {
        const pendingBubble = winState.domElement.querySelector(`#${pendingId}`);
        if (pendingBubble) pendingBubble.remove();
        winState.pendingMessage = null;
        restoreChatComposerDraft(convoId, input, draft);
        setChatDeliveryPhase(convoId, "error", {detail: err.message});
        showToast(
            "error",
            "Nachricht nicht bestätigt",
            err.message,
        );
    } finally {
        input.disabled = false;
        if (btn) btn.disabled = false;
        if (attachBtn) attachBtn.disabled = false;
        if (fileInput) fileInput.disabled = false;
        input.focus();
    }
}

function startChatPollingForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    if (winState.isArchived) return;
    if (convoId.startsWith("proxy-") || winState.selectedModel?.source === "custom") return;

    if (winState.eventSource) {
        winState.eventSource.close();
        winState.eventSource = null;
    }

    let lastIdx = winState.lastStreamIdx || 0;
    const url = `/api/antigravity/chats/${convoId}/stream?after=${lastIdx}`;
    const eventSource = new EventSource(url);
    winState.eventSource = eventSource;

    let agentBubbleEl = null;
    let agentContent = '';
    let agentThinking = '';

    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            const body = winState.domElement.querySelector(".chat-window-body");
            if (!body) return;
            if (winState.streamErrorTimeout) {
                window.clearTimeout(winState.streamErrorTimeout);
                winState.streamErrorTimeout = null;
            }

            if (data.type === 'stream_end') {
                eventSource.close();
                winState.eventSource = null;
                const input = winState.domElement.querySelector(".chat-send-input");
                const btn = winState.domElement.querySelector(".chat-send-btn");
                if (input) input.disabled = false;
                if (btn) btn.disabled = false;
                winState.pendingMessage = null;
                winState.streamCompletedAt = Date.now();

                const loader = body.querySelector('.polling-loader');
                if (loader) loader.remove();
                const typingEl = body.querySelector('[id^="typing-indicator-"]');
                if (typingEl) typingEl.remove();
                if (winState.deliveryPhase === "verifying") {
                    setChatDeliveryPhase(convoId, "confirmed");
                    finishChatDeliveryPhase(convoId);
                }
                setChatRunningState(convoId, false, {hasAssistantOutput: false});
                loadIntegrityChats({silent: true});
                return;
            }

            if (data.idx) {
                winState.lastStreamIdx = data.idx;
            }

            const pendingEl = body.querySelector('.chat-pending-indicator');
            if (pendingEl) pendingEl.remove();

            // Remove typing indicator only when NEW assistant data arrives
            // (not replayed history — check if this is an assistant or tool response)
            if (data.role === 'assistant' || data.type === 'tool_call') {
                const typingIndicator = body.querySelector('[id^="typing-indicator-"]');
                if (typingIndicator) typingIndicator.remove();
            }

            if (data.type === 'message' && data.role === 'user') {
                setChatRunningState(convoId, true, {hasAssistantOutput: false});
                agentBubbleEl = null;
                agentContent = '';
                agentThinking = '';

                let bubble = body.querySelector(`[data-idx="${data.idx}"]`);
                if (!bubble) {
                    const userBubbles = body.querySelectorAll('.chat-bubble-user');
                    let contentMatchedBubble = null;
                    userBubbles.forEach(b => {
                        const contentEl = b.querySelector('.chat-bubble-content');
                        if (contentEl && contentEl.textContent.trim() === (data.content || '').trim() && !b.hasAttribute('data-idx')) {
                            contentMatchedBubble = b;
                        }
                    });

                    if (contentMatchedBubble) {
                        contentMatchedBubble.setAttribute('data-idx', data.idx);
                        const meta = contentMatchedBubble.querySelector('.chat-bubble-meta');
                        if (meta) meta.textContent = 'Du · Zugestellt ✓';
                    } else {
                        let html = `<div class="chat-bubble chat-bubble-user" data-idx="${data.idx}"><span class="chat-bubble-meta">Du</span><div class="chat-bubble-content">`;
                        html += escapeHTML(data.content || '').replace(/\n/g, '<br>');
                        if (data.attachments && data.attachments.length > 0) {
                            html += `<div style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px;">`;
                            data.attachments.forEach(att => {
                                if (att.path) {
                                    html += `<img src="/api/antigravity/media?path=${encodeURIComponent(att.path)}" style="max-width: 120px; max-height: 80px; border-radius: 4px; border: 1px solid var(--color-border-default);">`;
                                }
                            });
                            html += `</div>`;
                        }
                        html += `</div></div>`;
                        body.insertAdjacentHTML('beforeend', html);
                        body.scrollTop = body.scrollHeight;
                    }
                }
                if (winState.deliveryPhase === "verifying") {
                    setChatDeliveryPhase(convoId, "confirmed");
                    finishChatDeliveryPhase(convoId);
                }
                winState.pendingMessage = null;

            } else if (data.type === 'message' && data.role === 'assistant') {
                const hasAssistantOutput = Boolean(
                    String(data.content || "").trim()
                    || String(data.thinking || "").trim()
                );
                setChatRunningState(convoId, true, {hasAssistantOutput});
                let bubble = body.querySelector(`[data-idx="${data.idx}"]`);
                if (!bubble) {
                    bubble = document.createElement('div');
                    bubble.className = 'chat-bubble chat-bubble-assistant';
                    bubble.setAttribute('data-idx', data.idx);
                    bubble.innerHTML = `<span class="chat-bubble-meta">Anti-Gravity Agent</span><div class="chat-bubble-content"></div>`;
                    body.appendChild(bubble);
                }
                clearStreamingAssistantBubbles(convoId, bubble);
                agentBubbleEl = bubble;
                bubble.classList.toggle("is-streaming", hasAssistantOutput);

                agentContent = data.content || '';
                agentThinking = data.thinking || '';

                let contentHtml = '';
                if (agentThinking) {
                    contentHtml += getThoughtHtml(agentThinking, data.idx);
                }
                contentHtml += renderMarkdownContent(agentContent);

                bubble.querySelector('.chat-bubble-content').innerHTML = contentHtml;
                body.scrollTop = body.scrollHeight;

                const input = winState.domElement.querySelector(".chat-send-input");
                const btn = winState.domElement.querySelector(".chat-send-btn");
                if (input) input.disabled = false;
                if (btn) btn.disabled = false;

            } else if (data.type === 'tool_call') {
                setChatRunningState(convoId, true, {hasAssistantOutput: false});
                agentBubbleEl = null;
                let tcall = body.querySelector(`[data-idx="${data.idx}"]`);
                if (!tcall) {
                    const toolHtml = getToolHtml(data);
                    appendLiveToolActivity(body, data, toolHtml);
                } else {
                    const activityGroup = tcall.closest(
                        ".chat-tool-activity-group",
                    );
                    const holder = document.createElement("div");
                    holder.innerHTML = getToolHtml(data).trim();
                    const replacement = holder.firstElementChild;
                    if (replacement) tcall.replaceWith(replacement);
                    refreshToolActivityGroupLabel(activityGroup);
                }
                syncBackgroundTaskFromToolEvent(convoId, data);
                body.scrollTop = body.scrollHeight;

            } else if (data.type === 'tool_output') {
                setChatRunningState(convoId, true, {hasAssistantOutput: false});
                let tout = body.querySelector(`[data-idx="${data.idx}"]`);
                if (!tout) {
                    appendLiveToolActivity(
                        body,
                        data,
                        getToolOutputHtml(data),
                    );
                    body.scrollTop = body.scrollHeight;
                }
            }
        } catch (e) {
            console.error('[SSE] Failed to parse event:', e, event.data);
        }
    };

    eventSource.onerror = function(e) {
        console.warn('[SSE] Stream error or closed:', e);
        if (winState.streamErrorTimeout) return;
        winState.streamErrorTimeout = window.setTimeout(async () => {
            winState.streamErrorTimeout = null;
            try {
                const response = await fetch(
                    `/api/antigravity/chats/${encodeURIComponent(convoId)}/history`,
                    {cache: "no-store"},
                );
                const payload = await response.json();
                if (!response.ok) return;
                const history = payload.history || [];
                const lastMessage = [...history].reverse().find(
                    item => item.type === "message"
                );
                if (
                    lastMessage?.role === "assistant"
                    && String(lastMessage.content || lastMessage.thinking || "").trim()
                ) {
                    renderHistoryListForConvo(convoId, history);
                    winState.lastStreamIdx = payload.max_idx || winState.lastStreamIdx;
                    winState.streamCompletedAt = Date.now();
                    if (winState.deliveryPhase === "verifying") {
                        setChatDeliveryPhase(convoId, "confirmed");
                        finishChatDeliveryPhase(convoId);
                    }
                    setChatRunningState(convoId, false, {hasAssistantOutput: false});
                    eventSource.close();
                    if (winState.eventSource === eventSource) {
                        winState.eventSource = null;
                    }
                }
            } catch (error) {
                console.warn("[SSE] Completion fallback failed:", error);
            }
        }, 3000);
    };
}

function formatVoiceElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
}

function updateVoiceRecordingDurationForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState?.voiceStartedAt) return;
    const elapsed = winState.domElement?.querySelector(".chat-voice-elapsed");
    if (elapsed) {
        elapsed.textContent = formatVoiceElapsed(
            Date.now() - winState.voiceStartedAt,
        );
    }
}

function setVoiceUIForConvo(convoId, phase) {
    const winState = chatWindowsState[convoId];
    if (!winState?.domElement) return;
    const micBtn = winState.domElement.querySelector(".chat-mic-btn");
    const status = winState.domElement.querySelector(".chat-voice-status");
    const statusTitle = status?.querySelector("strong");
    const statusHint = status?.querySelector("small");
    const elapsed = status?.querySelector(".chat-voice-elapsed");
    const activePhase = phase || "idle";
    const copies = {
        starting: {
            title: "Mikrofon wird gestartet",
            hint: "Die Aufnahmeverbindung wird vorbereitet.",
        },
        recording: {
            title: "Aufnahme läuft",
            hint: "Mikrofon erneut drücken, um die Aufnahme zu beenden.",
        },
        stopping: {
            title: "Aufnahme wird beendet",
            hint: "Die Sprache wird noch verarbeitet.",
        },
    };

    winState.voicePhase = activePhase;
    if (micBtn) {
        micBtn.classList.toggle("is-starting", activePhase === "starting");
        micBtn.classList.toggle("is-recording", activePhase === "recording");
        micBtn.classList.toggle("is-stopping", activePhase === "stopping");
        micBtn.disabled = ["starting", "stopping"].includes(activePhase);
        micBtn.setAttribute(
            "aria-pressed",
            activePhase === "recording" ? "true" : "false",
        );
        micBtn.setAttribute(
            "aria-label",
            activePhase === "recording"
                ? "Sprachaufnahme beenden"
                : "Sprachnachricht aufnehmen",
        );
        micBtn.title = activePhase === "recording"
            ? "Aufnahme beenden"
            : "Sprachnachricht aufnehmen";
    }
    if (status) {
        const visible = activePhase !== "idle";
        status.hidden = !visible;
        status.dataset.phase = activePhase;
        if (visible) {
            statusTitle.textContent = copies[activePhase].title;
            statusHint.textContent = copies[activePhase].hint;
        }
    }
    if (elapsed) {
        elapsed.hidden = activePhase !== "recording";
    }

    if (activePhase === "recording") {
        if (!winState.voiceStartedAt) {
            winState.voiceStartedAt = Date.now();
        }
        updateVoiceRecordingDurationForConvo(convoId);
        if (!winState.voiceUiInterval) {
            winState.voiceUiInterval = window.setInterval(
                () => updateVoiceRecordingDurationForConvo(convoId),
                1000,
            );
        }
    } else if (winState.voiceUiInterval) {
        window.clearInterval(winState.voiceUiInterval);
        winState.voiceUiInterval = null;
    }

    if (activePhase === "idle") {
        winState.voiceStartedAt = 0;
        if (elapsed) elapsed.textContent = "0:00";
    }
}

async function toggleVoiceInputForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const input = winState.domElement.querySelector(".chat-send-input");

    if (winState.isListening) {
        await stopVoiceInputForConvo(convoId);
        return;
    }

    winState.isListening = true;
    setVoiceUIForConvo(convoId, "starting");

    const currentText = input ? input.value : "";

    try {
        const token = await getAuthToken();
        const headers = { "Content-Type": "application/json" };
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const res = await controlFetch("/api/voice/dictation/start", {
            method: "POST",
            headers: headers,
            body: JSON.stringify({ text: currentText })
        });

        if (!res.ok) {
            throw new Error(`HTTP-Fehler ${res.status}`);
        }

        winState.voiceStartedAt = Date.now();
        setVoiceUIForConvo(convoId, "recording");
        showToast("info", "Aufnahme läuft", "Das Mikrofon ist jetzt aktiv.");
        winState.voicePollInterval = setInterval(() => pollVoiceStatusForConvo(convoId), 300);

    } catch (err) {
        console.error("[Voice] Start failed:", err);
        showToast("error", "Fehler", "Sprachaufnahme konnte nicht gestartet werden: " + err.message);
        resetVoiceUIForConvo(convoId);
    }
}

async function pollVoiceStatusForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const input = winState.domElement.querySelector(".chat-send-input");
    try {
        const token = await getAuthToken();
        const headers = {};
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const res = await fetch("/api/voice/dictation/status", { headers });
        if (!res.ok) {
            throw new Error(`HTTP-Fehler ${res.status}`);
        }

        const data = await res.json();

        if (input && data.text !== undefined) {
            input.value = data.text;
            input.style.height = "auto";
            input.style.height = (input.scrollHeight) + "px";
        }

        const isRecording = data.isRecording !== undefined ? data.isRecording : data.is_recording;
        if (isRecording === false) {
            if (winState.voicePhase === "stopping") return;
            cleanupVoicePollingForConvo(convoId);
            resetVoiceUIForConvo(convoId);
            showToast("success", "Aufnahme beendet", "Sprachaufnahme verarbeitet.");
        }
    } catch (err) {
        if (winState.voicePhase === "stopping") return;
        console.error("[Voice] Polling failed:", err);
        cleanupVoicePollingForConvo(convoId);
        resetVoiceUIForConvo(convoId);
        getAuthToken().then(token => {
            const headers = {};
            if (token) {
                headers["Authorization"] = `Bearer ${token}`;
            }
            controlFetch("/api/voice/dictation/stop", { method: "POST", headers: headers })
                .catch(e => console.error("[Voice] Auto-stop on poll fail failed:", e));
        }).catch(e => console.error("[Voice] Failed to get token on poll fail:", e));
    }
}

async function stopVoiceInputForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState || winState.voiceStopPromise) return;
    cleanupVoicePollingForConvo(convoId);
    winState.isListening = false;
    setVoiceUIForConvo(convoId, "stopping");
    winState.voiceStopPromise = (async () => {
        const token = await getAuthToken();
        const headers = {};
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const response = await controlFetch("/api/voice/dictation/stop", {
            method: "POST",
            headers: headers
        });
        if (!response.ok) {
            throw new Error(`HTTP-Fehler ${response.status}`);
        }
        const data = await response.json();
        const input = winState.domElement.querySelector(".chat-send-input");
        if (input && typeof data.text === "string") {
            input.value = data.text;
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
    })();

    try {
        await winState.voiceStopPromise;
        showToast("success", "Aufnahme beendet", "Sprachaufnahme verarbeitet.");
    } catch (err) {
        console.error("[Voice] Stop failed:", err);
        showToast("error", "Aufnahme nicht sauber beendet", err.message);
    } finally {
        winState.voiceStopPromise = null;
        resetVoiceUIForConvo(convoId);
    }
}

function cleanupVoicePollingForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (winState && winState.voicePollInterval) {
        clearInterval(winState.voicePollInterval);
        winState.voicePollInterval = null;
    }
}

function resetVoiceUIForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    winState.isListening = false;
    setVoiceUIForConvo(convoId, "idle");
}

function toggleModelDropdownForConvo(convoId, event) {
    if (event) event.stopPropagation();
    const winState = chatWindowsState[convoId];
    if (!winState) return;
    if (winState.isModelSwitching) return;

    const menu = winState.domElement.querySelector(".model-dropdown-menu");
    if (!menu) return;

    const isShowing = menu.style.display === "block";
    if (isShowing) {
        menu.style.display = "none";
    } else {
        loadModelListForConvo(convoId);
        menu.style.display = "block";
    }
}

async function loadModelListForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const menu = winState.domElement.querySelector(".model-dropdown-menu");
    if (!menu) return;

    const currentTextClean = winState.selectedModel?.label || '';

    const geminiQuotaEl = document.getElementById("quota-gemini");
    const claudeQuotaEl = document.getElementById("quota-claude");
    const geminiQuotaText = geminiQuotaEl ? geminiQuotaEl.innerText.trim() : "G: --%";
    const claudeQuotaText = claudeQuotaEl ? claudeQuotaEl.innerText.trim() : "C: --%";

    function renderModels(list) {
        menu.innerHTML = '';
        const hdr = document.createElement('div');
        hdr.style.cssText = 'padding: 6px 12px; font-size: 10px; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--color-border-default);';
        hdr.innerText = 'Model';
        menu.appendChild(hdr);

        list.forEach(m => {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            if (m.label === currentTextClean) {
                item.style.fontWeight = 'bold';
                item.style.color = 'var(--color-accent-neon)';
            }

            let icon = getChatModelIcon(m);
            let quotaSuffix = "";
            if (m.source !== "custom" && m.label.startsWith("Gemini")) {
                quotaSuffix = ` (${geminiQuotaText})`;
            } else if (m.source !== "custom" && m.label.startsWith("Claude")) {
                quotaSuffix = ` (${claudeQuotaText})`;
            }

            const title = document.createElement('span');
            title.textContent = icon + m.label + quotaSuffix;
            item.appendChild(title);
            if (m.badge) {
                const badge = document.createElement('span');
                badge.style.cssText = 'opacity: 0.65; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 1px 6px; border-radius: 4px; font-size: 9px; margin-left: 4px;';
                badge.textContent = m.badge;
                item.appendChild(badge);
            }
            if (m.source === "custom") {
                const detail = document.createElement('small');
                detail.style.cssText = 'display: block; opacity: 0.55; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
                detail.textContent = `${m.model_id || ""} · ${m.base_url || ""}`;
                item.appendChild(detail);
            }
            item.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                selectChatModelForConvo(convoId, m);
            };
            menu.appendChild(item);
        });

        const manage = document.createElement('div');
        manage.className = 'dropdown-item model-manager-item';
        manage.textContent = '＋ Eigenes API-Modell verwalten…';
        manage.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            menu.style.display = 'none';
            openCustomModelManager(convoId);
        };
        menu.appendChild(manage);
    }

    if (_cachedModels && _cachedModels.length > 0) {
        renderModels(_cachedModels);
    } else {
        menu.innerHTML = '<div class="dropdown-item" style="opacity: 0.5;">Lade Modelle...</div>';
    }

    try {
        const res = await fetch('/api/antigravity/models', {cache: 'no-store'});
        if (!res.ok) throw new Error('API error');
        const data = await res.json();
        _cachedModels = data.models || [];
        renderModels(_cachedModels);
    } catch (e) {
        console.error('[Models] Failed to load model list:', e);
        if (_cachedModels?.length) renderModels(_cachedModels);
        else renderModels([]);
    }
}

let _customModels = [];
let _customModelTargetConvoId = null;

function setCustomModelStatus(message, type = "") {
    const status = document.getElementById("custom-model-status");
    if (!status) return;
    status.textContent = message || "";
    status.className = `custom-model-status ${type}`.trim();
}

async function openCustomModelManager(convoId = null) {
    _customModelTargetConvoId = convoId;
    openModal("custom-model-modal");
    resetCustomModelForm();
    await loadCustomModelsForManager();
}

async function loadCustomModelsForManager() {
    const list = document.getElementById("custom-model-list");
    if (!list) return;
    list.innerHTML = '<div class="custom-model-empty">Lade Modelle…</div>';
    try {
        const response = await fetch("/api/antigravity/custom-models");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Modelle konnten nicht geladen werden.");
        _customModels = data.models || [];
        list.innerHTML = "";
        if (_customModels.length === 0) {
            list.innerHTML = '<div class="custom-model-empty">Noch kein eigenes Modell eingerichtet.</div>';
            return;
        }
        const selectedId = Number(document.getElementById("custom-model-id")?.value || 0);
        _customModels.forEach(model => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "custom-model-list-item" + (selectedId === model.id ? " active" : "");
            const title = document.createElement("strong");
            title.textContent = `🔌 ${model.name}`;
            const detail = document.createElement("small");
            detail.textContent = model.model_id;
            item.append(title, detail);
            item.onclick = () => editCustomModel(model.id);
            list.appendChild(item);
        });
    } catch (error) {
        list.innerHTML = `<div class="custom-model-empty">${escapeHTML(error.message)}</div>`;
        setCustomModelStatus(error.message, "error");
    }
}

function resetCustomModelForm() {
    const form = document.getElementById("custom-model-form");
    if (!form) return;
    form.reset();
    document.getElementById("custom-model-id").value = "";
    document.getElementById("custom-model-api-key-header").value = "Authorization";
    document.getElementById("custom-model-api-key-prefix").value = "Bearer";
    document.getElementById("custom-model-temperature").value = "0.7";
    document.getElementById("custom-model-timeout").value = "60";
    document.getElementById("custom-model-extra-headers").value = "{}";
    document.getElementById("custom-model-verify-tls").checked = true;
    document.getElementById("custom-model-test-btn").disabled = true;
    document.getElementById("custom-model-delete-btn").disabled = true;
    setCustomModelStatus("");
    document.querySelectorAll(".custom-model-list-item.active").forEach(item => item.classList.remove("active"));
}

function editCustomModel(modelId) {
    const model = _customModels.find(item => item.id === Number(modelId));
    if (!model) return;
    document.getElementById("custom-model-id").value = String(model.id);
    document.getElementById("custom-model-name").value = model.name || "";
    document.getElementById("custom-model-model-id").value = model.model_id || "";
    document.getElementById("custom-model-base-url").value = model.base_url || "";
    document.getElementById("custom-model-api-key").value = "";
    document.getElementById("custom-model-api-key-header").value = model.api_key_header || "Authorization";
    document.getElementById("custom-model-api-key-prefix").value = model.api_key_prefix ?? "Bearer";
    document.getElementById("custom-model-temperature").value = String(model.temperature ?? 0.7);
    document.getElementById("custom-model-timeout").value = String(model.timeout_seconds ?? 60);
    document.getElementById("custom-model-extra-headers").value = JSON.stringify(model.extra_headers || {}, null, 2);
    document.getElementById("custom-model-system-prompt").value = model.system_prompt || "";
    document.getElementById("custom-model-verify-tls").checked = model.verify_tls !== false;
    document.getElementById("custom-model-test-btn").disabled = false;
    document.getElementById("custom-model-delete-btn").disabled = false;
    setCustomModelStatus(model.has_api_key ? "Ein verschlüsselter API-Key ist hinterlegt." : "Für dieses Modell ist kein API-Key hinterlegt.");
    loadCustomModelsForManager();
}

function customModelFormPayload() {
    return {
        id: document.getElementById("custom-model-id").value || null,
        name: document.getElementById("custom-model-name").value.trim(),
        model_id: document.getElementById("custom-model-model-id").value.trim(),
        base_url: document.getElementById("custom-model-base-url").value.trim(),
        api_key: document.getElementById("custom-model-api-key").value,
        api_key_header: document.getElementById("custom-model-api-key-header").value.trim(),
        api_key_prefix: document.getElementById("custom-model-api-key-prefix").value.trim(),
        temperature: Number(document.getElementById("custom-model-temperature").value),
        timeout_seconds: Number(document.getElementById("custom-model-timeout").value),
        extra_headers: document.getElementById("custom-model-extra-headers").value.trim() || "{}",
        system_prompt: document.getElementById("custom-model-system-prompt").value,
        verify_tls: document.getElementById("custom-model-verify-tls").checked
    };
}

async function saveCustomModel(event) {
    event?.preventDefault();
    const button = document.getElementById("custom-model-save-btn");
    button.disabled = true;
    setCustomModelStatus("Speichere…");
    try {
        const response = await controlFetch("/api/antigravity/custom-models", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(customModelFormPayload())
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Modell konnte nicht gespeichert werden.");
        _cachedModels = null;
        await loadCustomModelsForManager();
        editCustomModel(data.model.id);
        setCustomModelStatus("Modell sicher gespeichert.", "success");
        if (_customModelTargetConvoId && chatWindowsState[_customModelTargetConvoId]) {
            await selectChatModelForConvo(_customModelTargetConvoId, {
                label: data.model.name,
                badge: "Proxy",
                source: "custom",
                custom_model_id: data.model.id,
                model_id: data.model.model_id,
                base_url: data.model.base_url
            });
        }
    } catch (error) {
        setCustomModelStatus(error.message, "error");
    } finally {
        button.disabled = false;
    }
}

async function testCustomModel() {
    const modelId = Number(document.getElementById("custom-model-id").value || 0);
    if (!modelId) return;
    const button = document.getElementById("custom-model-test-btn");
    button.disabled = true;
    setCustomModelStatus("Prüfe /models…");
    try {
        const response = await controlFetch(`/api/antigravity/custom-models/${modelId}/test`, { method: "POST" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Verbindungstest fehlgeschlagen.");
        const count = Number.isInteger(data.model_count) ? ` (${data.model_count} Modelle gefunden)` : "";
        setCustomModelStatus(`Verbindung erfolgreich${count}.`, "success");
    } catch (error) {
        setCustomModelStatus(error.message, "error");
    } finally {
        button.disabled = false;
    }
}

async function deleteCustomModel() {
    const modelId = Number(document.getElementById("custom-model-id").value || 0);
    if (!modelId || !(await hubConfirm(
        "Dieses eigene Modell wirklich löschen?",
        {title: 'Eigenes Modell löschen', confirmLabel: 'Modell löschen'},
    ))) return;
    setCustomModelStatus("Lösche…");
    try {
        const response = await controlFetch(`/api/antigravity/custom-models/${modelId}`, { method: "DELETE" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Modell konnte nicht gelöscht werden.");
        _cachedModels = null;
        resetCustomModelForm();
        await loadCustomModelsForManager();
        setCustomModelStatus("Modell gelöscht.", "success");
    } catch (error) {
        setCustomModelStatus(error.message, "error");
    }
}

// Fallback legacy global aliases
let chatUploadedImages = [];
async function sendIntegrityChatMessage() {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        await sendIntegrityChatMessageForConvo(keys[0]);
    }
}

async function toggleVoiceInput() {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        await toggleVoiceInputForConvo(keys[0]);
    }
}

function removeChatUploadedImage(index) {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        removeChatUploadedImageForConvo(keys[0], index);
    }
}

function handleChatFileInput(event) {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        handleChatFileInputForConvo(keys[0], event);
    }
}

async function openConvoBrainDir() {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        await openConvoBrainDirForConvo(keys[0]);
    }
}

async function openConvoPlaner() {
    const keys = Object.keys(chatWindowsState);
    if (keys.length > 0) {
        await openConvoPlanerForConvo(keys[0]);
    }
}

document.addEventListener("paste", function(event) {
    const win = event.target.closest(".chat-window");
    if (!win) return;
    const convoId = win.getAttribute("data-convo-id");
    const winState = chatWindowsState[convoId];
    if (!winState) return;

    const clipboard = event.clipboardData || event.originalEvent?.clipboardData;
    const items = clipboard?.items || [];
    let imageQueued = false;

    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.indexOf("image") !== -1) {
            const file = item.getAsFile();
            imageQueued = queueChatImageForConvo(
                convoId,
                file,
                `pasted_image_${Date.now()}.png`,
            ) || imageQueued;
        }
    }
    if (imageQueued) event.preventDefault();
});


function renderMarkdownContent(text) {
    const normalizedText = displayString(text, typeof text === "object");
    if (!normalizedText) return '';
    const lines = normalizedText.replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];

    function inlineMarkdown(value) {
        const codeTokens = [];
        let html = escapeHTML(String(value || ""));
        html = html.replace(/`([^`\n]+)`/g, (_match, code) => {
            const token = `\u0000CODE${codeTokens.length}\u0000`;
            codeTokens.push(`<code class="chat-markdown-inline-code">${code}</code>`);
            return token;
        });
        html = html.replace(
            /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
        );
        html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
        html = html.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
        html = html.replace(
            /(^|[\s(])\*([^*\n]+)\*(?=$|[\s.,!?;)])/g,
            "$1<em>$2</em>",
        );
        codeTokens.forEach((code, index) => {
            html = html.replace(`\u0000CODE${index}\u0000`, code);
        });
        return html;
    }

    function tableCells(line) {
        let value = String(line || "").trim();
        if (value.startsWith("|")) value = value.slice(1);
        if (value.endsWith("|")) value = value.slice(0, -1);
        return value.split("|").map(cell => cell.trim());
    }

    function isTableDelimiter(line) {
        const cells = tableCells(line);
        return cells.length > 0
            && cells.every(cell => /^:?-{3,}:?$/.test(cell));
    }

    function isBlockStart(index) {
        const line = lines[index] || "";
        const trimmed = line.trim();
        return (
            !trimmed
            || /^```/.test(trimmed)
            || /^#{1,6}\s+/.test(trimmed)
            || /^>\s?/.test(trimmed)
            || /^[-*+]\s+/.test(trimmed)
            || /^\d+[.)]\s+/.test(trimmed)
            || /^([-*_])(?:\s*\1){2,}$/.test(trimmed)
            || (
                trimmed.includes("|")
                && index + 1 < lines.length
                && isTableDelimiter(lines[index + 1])
            )
        );
    }

    let index = 0;
    while (index < lines.length) {
        const line = lines[index];
        const trimmed = line.trim();
        if (!trimmed) {
            index += 1;
            continue;
        }

        const fence = trimmed.match(/^```([\w.+-]*)\s*$/);
        if (fence) {
            const codeLines = [];
            index += 1;
            while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
                codeLines.push(lines[index]);
                index += 1;
            }
            if (index < lines.length) index += 1;
            const language = fence[1] || "text";
            blocks.push(
                `<pre class="chat-markdown-code"><code data-language="${escapeHTML(language)}">`
                + `${escapeHTML(codeLines.join("\n"))}</code></pre>`,
            );
            continue;
        }

        const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            const level = Math.min(6, heading[1].length + 2);
            blocks.push(
                `<h${level} class="chat-markdown-heading">`
                + `${inlineMarkdown(heading[2])}</h${level}>`,
            );
            index += 1;
            continue;
        }

        if (/^([-*_])(?:\s*\1){2,}$/.test(trimmed)) {
            blocks.push('<hr class="chat-markdown-rule">');
            index += 1;
            continue;
        }

        if (
            trimmed.includes("|")
            && index + 1 < lines.length
            && isTableDelimiter(lines[index + 1])
        ) {
            const headers = tableCells(line);
            const delimiters = tableCells(lines[index + 1]);
            const alignments = delimiters.map(cell => (
                cell.startsWith(":") && cell.endsWith(":")
                    ? "center"
                    : cell.endsWith(":") ? "right" : "left"
            ));
            index += 2;
            const rows = [];
            while (
                index < lines.length
                && lines[index].trim()
                && lines[index].includes("|")
            ) {
                rows.push(tableCells(lines[index]));
                index += 1;
            }
            const head = headers.map((cell, cellIndex) =>
                `<th data-align="${alignments[cellIndex] || "left"}">`
                + `${inlineMarkdown(cell)}</th>`
            ).join("");
            const body = rows.map(row =>
                `<tr>${headers.map((_cell, cellIndex) =>
                    `<td data-align="${alignments[cellIndex] || "left"}">`
                    + `${inlineMarkdown(row[cellIndex] || "")}</td>`
                ).join("")}</tr>`
            ).join("");
            blocks.push(
                '<div class="chat-markdown-table-wrap"><table>'
                + `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`
                + '</table></div>',
            );
            continue;
        }

        if (/^>\s?/.test(trimmed)) {
            const quoteLines = [];
            while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
                quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
                index += 1;
            }
            blocks.push(
                `<blockquote>${renderMarkdownContent(quoteLines.join("\n"))}</blockquote>`,
            );
            continue;
        }

        const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
        const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
        if (unordered || ordered) {
            const orderedList = Boolean(ordered);
            const items = [];
            const pattern = orderedList ? /^\d+[.)]\s+(.+)$/ : /^[-*+]\s+(.+)$/;
            while (index < lines.length) {
                const match = lines[index].trim().match(pattern);
                if (!match) break;
                items.push(`<li>${inlineMarkdown(match[1])}</li>`);
                index += 1;
            }
            const tag = orderedList ? "ol" : "ul";
            blocks.push(`<${tag}>${items.join("")}</${tag}>`);
            continue;
        }

        const paragraph = [trimmed];
        index += 1;
        while (index < lines.length && !isBlockStart(index)) {
            paragraph.push(lines[index].trim());
            index += 1;
        }
        blocks.push(`<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`);
    }

    return `<div class="chat-markdown">${blocks.join("")}</div>`;
}

// --- Original Antigravity UI Elements Helper functions ---
function getThoughtHtml(thinking, index) {
    const thinkingText = displayString(
        thinking,
        typeof thinking === "object",
    );
    if (!thinkingText) return '';
    const secs = Math.max(1, Math.round(thinkingText.length / 150));

    return `
        <details class="thought-block" data-thought-index="${escapeHTML(index ?? "")}">
            <summary class="thought-toggle">
                <span class="thought-arrow">▶</span>
                <span>Thought for ${secs}s</span>
            </summary>
            <div class="thought-content-box">${renderMarkdownContent(thinkingText)}</div>
        </details>
    `;
}

function parseToolArguments(msg) {
    let parsed = msg?.args;
    for (let attempt = 0; attempt < 2 && typeof parsed === "string"; attempt++) {
        try {
            parsed = JSON.parse(parsed);
        } catch (_error) {
            return null;
        }
    }
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed
        : null;
}

function getToolCommandInfo(msg) {
    const toolName = displayString(msg?.tool_name).trim();
    if (toolName !== "run_command") return null;
    const args = parseToolArguments(msg) || {};
    const enriched = msg?.enriched?.kind === "command"
        ? msg.enriched
        : {};
    const command = displayString(
        enriched.command
        || args.CommandLine
        || args.command
        || args.cmd,
    ).trim();
    if (!command) return null;

    const portMatch = command.match(
        /(?:--port(?:=|\s+)|\s-p\s+|localhost:|127\.0\.0\.1:)(\d{2,5})(?:\D|$)/i,
    );
    const port = Number(enriched.port || portMatch?.[1] || 0) || null;
    const state = msg?.is_running
        ? "running"
        : (msg?.complete
            ? "complete"
            : displayString(enriched.state || "pending"));
    const serverCommand = Boolean(
        enriched.server_command
        || /\b(vite|next\s+dev|nuxt\s+dev|ng\s+serve|http-server|http\.server|uvicorn|gunicorn|flask\s+run|npm\s+run\s+(?:dev|start)|pnpm\s+(?:dev|start)|yarn\s+(?:dev|start))\b/i.test(command),
    );
    return {
        command,
        cwd: displayString(enriched.cwd || args.Cwd || args.cwd).trim(),
        action: displayString(
            enriched.action || args.toolAction || args.action,
        ).trim(),
        summary: displayString(
            enriched.summary || args.toolSummary || args.summary,
        ).trim(),
        port,
        url: displayString(
            enriched.url || (port ? `http://127.0.0.1:${port}` : ""),
        ).trim(),
        state,
        serverCommand,
        backgroundTask: Boolean(
            state === "running"
            && (enriched.background_task || serverCommand)
        ),
    };
}

function getToolActivityLabel(entries) {
    const calls = (entries || []).filter(entry => entry?.type === "tool_call");
    const count = Math.max(1, calls.length);
    const commandCalls = calls.filter(entry => entry?.tool_name === "run_command");
    const runningCommands = commandCalls.filter(
        entry => getToolCommandInfo(entry)?.state === "running",
    );
    const fileChanges = calls.filter(
        entry => entry?.enriched?.kind === "file_change",
    );
    const fileReads = calls.filter(entry => [
        "view_file",
        "read_file",
        "grep_search",
        "list_dir",
    ].includes(entry?.tool_name));

    if (commandCalls.length === calls.length && calls.length) {
        if (runningCommands.length) {
            return `${runningCommands.length} ${
                runningCommands.length === 1 ? "Befehl läuft" : "Befehle laufen"
            }`;
        }
        return `${count} ${count === 1 ? "Befehl ausgeführt" : "Befehle ausgeführt"}`;
    }
    if (fileChanges.length === calls.length && calls.length) {
        return `${count} ${count === 1 ? "Datei geändert" : "Dateien geändert"}`;
    }
    if (fileReads.length === calls.length && calls.length) {
        return `${count} ${count === 1 ? "Datei geprüft" : "Dateien geprüft"}`;
    }
    return `${count} ${count === 1 ? "Arbeitsschritt" : "Arbeitsschritte"}`;
}

function getBackgroundTasksPanelHtml(tasks) {
    const safeTasks = Array.isArray(tasks) ? tasks : [];
    if (!safeTasks.length) return "";
    const rows = safeTasks.map(task => {
        const info = getToolCommandInfo(task);
        if (!info) return "";
        const label = info.summary || info.action || "Lokaler Server";
        return `
            <article class="chat-background-task" data-background-task-idx="${escapeHTML(task.idx || "")}">
                <span class="chat-background-task-spinner" aria-hidden="true"></span>
                <span class="chat-background-task-copy">
                    <strong>${escapeHTML(label)}</strong>
                    <code title="${escapeHTML(info.command)}">${escapeHTML(info.command)}</code>
                    ${info.cwd ? `<small title="${escapeHTML(info.cwd)}">${escapeHTML(info.cwd)}</small>` : ""}
                </span>
                <span class="chat-background-task-meta">
                    ${info.port ? `<span class="chat-background-task-port">Port ${info.port}</span>` : ""}
                    ${info.url ? `<a href="${escapeHTML(info.url)}" target="_blank" rel="noopener noreferrer">Öffnen ↗</a>` : ""}
                </span>
            </article>
        `;
    }).join("");
    const count = safeTasks.length;
    return `
        <details class="chat-background-tasks" open>
            <summary>
                <span class="chat-background-task-spinner" aria-hidden="true"></span>
                <strong>${count} ${count === 1 ? "Background-Task läuft" : "Background-Tasks laufen"}</strong>
                <span class="chat-background-task-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div class="chat-background-task-list">${rows}</div>
        </details>
    `;
}

function renderBackgroundTasksForConvo(convoId) {
    const winState = chatWindowsState[convoId];
    const body = winState?.domElement?.querySelector(".chat-window-body");
    if (!winState || !body) return;
    const tasks = Object.values(winState.backgroundTasks || {});
    const existing = body.querySelector(".chat-background-tasks");
    if (!tasks.length) {
        existing?.remove();
        return;
    }
    const html = getBackgroundTasksPanelHtml(tasks);
    if (existing) {
        existing.outerHTML = html;
    } else {
        body.insertAdjacentHTML("beforeend", html);
    }
    body.scrollTop = body.scrollHeight;
}

function syncBackgroundTaskFromToolEvent(convoId, event) {
    const winState = chatWindowsState[convoId];
    const info = getToolCommandInfo(event);
    if (!winState || !info) return;
    if (info.backgroundTask) {
        winState.backgroundTasks[String(event.idx)] = event;
    } else {
        delete winState.backgroundTasks[String(event.idx)];
    }
    renderBackgroundTasksForConvo(convoId);
}

function getToolActivityGroupHtml(entries, live = false) {
    const safeEntries = Array.isArray(entries) ? entries : [];
    const actionCount = Math.max(
        1,
        safeEntries.filter(entry => entry?.type === "tool_call").length,
    );
    const details = safeEntries.map(entry => (
        entry?.type === "tool_output"
            ? getToolOutputHtml(entry)
            : getToolHtml(entry)
    )).join("");
    const label = getToolActivityLabel(safeEntries);
    return `
        <details class="chat-tool-activity-group${live ? " is-live" : ""}"
            data-action-count="${actionCount}">
            <summary>
                <span class="chat-tool-activity-chevron" aria-hidden="true">▶</span>
                <span class="chat-tool-activity-label">${escapeHTML(label)}</span>
                <span class="chat-tool-activity-hint">Details anzeigen</span>
            </summary>
            <div class="chat-tool-activity-items">${details}</div>
        </details>
    `;
}

function refreshToolActivityGroupLabel(group) {
    if (!group) return;
    const label = group.querySelector(".chat-tool-activity-label");
    if (!label) return;
    const commands = Array.from(group.querySelectorAll(".chat-command-row"));
    const fileChanges = Array.from(group.querySelectorAll(".git-diff-card"));
    const fileReads = Array.from(group.querySelectorAll(".tool-exec-card"));
    const genericCalls = Array.from(group.querySelectorAll(".chat-tool-call"));
    const total = commands.length + fileChanges.length
        + fileReads.length + genericCalls.length;

    if (commands.length && total === commands.length) {
        const running = commands.filter(
            command => command.classList.contains("state-running"),
        ).length;
        label.textContent = running
            ? `${running} ${running === 1 ? "Befehl läuft" : "Befehle laufen"}`
            : `${commands.length} ${
                commands.length === 1 ? "Befehl ausgeführt" : "Befehle ausgeführt"
            }`;
    } else if (fileChanges.length && total === fileChanges.length) {
        label.textContent = `${fileChanges.length} ${
            fileChanges.length === 1 ? "Datei geändert" : "Dateien geändert"
        }`;
    } else if (fileReads.length && total === fileReads.length) {
        label.textContent = `${fileReads.length} ${
            fileReads.length === 1 ? "Datei geprüft" : "Dateien geprüft"
        }`;
    } else {
        const count = Math.max(1, total);
        label.textContent = `${count} ${
            count === 1 ? "Arbeitsschritt" : "Arbeitsschritte"
        }`;
    }
    group.dataset.actionCount = String(Math.max(1, total));
}

function appendLiveToolActivity(body, entry, itemHtml) {
    if (!body) return;
    const backgroundTasks = body.querySelector(".chat-background-tasks");
    const lastElement = backgroundTasks
        ? backgroundTasks.previousElementSibling
        : body.lastElementChild;
    let group = (
        lastElement?.classList.contains("chat-tool-activity-group")
        && lastElement.classList.contains("is-live")
    ) ? lastElement : null;
    if (!group) {
        const html = getToolActivityGroupHtml([entry], true);
        if (backgroundTasks) {
            backgroundTasks.insertAdjacentHTML("beforebegin", html);
        } else {
            body.insertAdjacentHTML("beforeend", html);
        }
        return;
    }

    const items = group.querySelector(".chat-tool-activity-items");
    items?.insertAdjacentHTML("beforeend", itemHtml);
    refreshToolActivityGroupLabel(group);
}

function getToolOutputHtml(msg) {
    const rawOutput = msg?.output;
    let formatted = displayString(
        rawOutput,
        rawOutput !== null && typeof rawOutput === "object",
    );
    let format = "Log";
    if (rawOutput !== null && typeof rawOutput === "object") {
        format = "JSON";
    } else {
        try {
            formatted = JSON.stringify(JSON.parse(formatted), null, 2);
            format = "JSON";
        } catch (_error) {}
    }
    const toolName = displayString(msg?.tool_name).trim();
    const label = toolName ? `Ausgabe · ${toolName}` : "Tool-Ausgabe";
    const idxAttr = msg?.idx ? `data-idx="${escapeHTML(msg.idx)}"` : "";
    return `
        <details class="chat-tool-output" ${idxAttr}>
            <summary>
                <span class="chat-tool-output-icon" aria-hidden="true">▣</span>
                <span class="chat-tool-output-label">${escapeHTML(label)}</span>
                <span class="chat-tool-output-meta">${format} · ${formatted.length.toLocaleString("de-DE")} Zeichen</span>
            </summary>
            <pre class="chat-tool-output-content"><code>${escapeHTML(formatted)}</code></pre>
        </details>
    `;
}

function getFileIcon(filename) {
    const normalizedFilename = displayString(filename);
    if (!normalizedFilename) return '📄';
    const ext = normalizedFilename.split('.').pop().toLowerCase();
    if (ext === 'py') return '🐍';
    if (ext === 'js' || ext === 'ts') return '🟨';
    if (ext === 'html') return '🌐';
    if (ext === 'css') return '🎨';
    if (ext === 'md') return '📝';
    if (ext === 'json') return '⚙️';
    if (ext === 'db' || ext === 'sqlite') return '🗄️';
    return '📄';
}

function getToolHtml(msg) {
    const tname = displayString(msg?.tool_name);
    const idxAttr = msg?.idx ? `data-idx="${escapeHTML(msg.idx)}"` : '';
    const commandInfo = getToolCommandInfo(msg);

    if (commandInfo) {
        const stateLabel = {
            running: commandInfo.backgroundTask
                ? "Background-Task läuft"
                : "Befehl läuft",
            complete: "Ausgeführt",
            pending: "Wird vorbereitet",
        }[commandInfo.state] || "Befehl";
        const actionLabel = commandInfo.summary
            || commandInfo.action
            || "Befehl ausführen";
        return `
            <div class="chat-command-row state-${escapeHTML(commandInfo.state)}" ${idxAttr}>
                <span class="chat-command-state" aria-hidden="true"></span>
                <span class="chat-command-copy">
                    <span class="chat-command-heading">
                        <strong>${escapeHTML(actionLabel)}</strong>
                        <small>${escapeHTML(stateLabel)}</small>
                    </span>
                    <code title="${escapeHTML(commandInfo.command)}">${escapeHTML(commandInfo.command)}</code>
                    ${commandInfo.cwd
                        ? `<span class="chat-command-cwd" title="${escapeHTML(commandInfo.cwd)}">${escapeHTML(commandInfo.cwd)}</span>`
                        : ""}
                </span>
                <span class="chat-command-meta">
                    ${commandInfo.port
                        ? `<span class="chat-command-port">:${commandInfo.port}</span>`
                        : ""}
                    ${commandInfo.url
                        ? `<a href="${escapeHTML(commandInfo.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(commandInfo.url)}">Öffnen ↗</a>`
                        : ""}
                </span>
            </div>
        `;
    }

    if (msg.enriched?.kind === "file_change" || msg.enriched?.file_name) {
        const file = displayString(msg.enriched.file_name);
        const added = msg.enriched.lines_added;
        const removed = msg.enriched.lines_removed;
        const icon = getFileIcon(file);
        const encodedDiff = encodeURIComponent(displayString(msg.enriched.diff));

        return `
            <div class="git-diff-card" ${idxAttr}>
                <div class="git-diff-left">
                    <span class="git-diff-file-icon">${icon}</span>
                    <span>${escapeHTML(file)}</span>
                    <span class="git-diff-badges">
                        <span class="git-diff-badge-added">+${added}</span>
                        <span class="git-diff-badge-removed">-${removed}</span>
                    </span>
                </div>
                <button class="git-diff-review-btn" onclick="window.triggerCodeReview('${escapeHTML(file)}', '${encodedDiff}')">
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" style="display:inline-block;vertical-align:middle;margin-right:2px;"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 01-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.35 3.12.9.01.64.01 1.24.01 1.41 0 .21-.15.47-.56.38A8.013 8.013 0 010 8c0-4.42 3.58-8 8-8z"></path></svg>
                    Review
                </button>
            </div>
        `;
    }

    let parsedArgs = null;
    try {
        parsedArgs = typeof msg.args === 'string' ? JSON.parse(msg.args) : msg.args;
    } catch(e) {}

    if (parsedArgs && (tname === 'view_file' || tname === 'grep_search' || tname === 'read_file')) {
        const file_path = displayString(
            parsedArgs.AbsolutePath
            || parsedArgs.SearchPath
            || parsedArgs.TargetFile,
        );
        const file_name = file_path.split('/').pop().split('\\').pop() || 'file';
        const start_line = parsedArgs.StartLine || 1;
        const end_line = parsedArgs.EndLine || '';
        const icon = getFileIcon(file_name);

        let actionText = tname === 'grep_search' ? 'Searched in' : 'Explored';
        let lineSuffix = end_line ? `#L${start_line}-${end_line}` : `#L${start_line}`;
        if (tname === 'grep_search') lineSuffix = ` for "${escapeHTML(parsedArgs.Query || '')}"`;

        return `
            <div class="tool-exec-card" ${idxAttr}>
                <div class="tool-exec-header">
                    <span class="tool-exec-icon">${icon}</span>
                    <span class="tool-exec-action-text">${actionText} ${escapeHTML(file_name)}</span>
                    <a href="#" class="tool-exec-line-link" onclick="event.preventDefault();">${lineSuffix}</a>
                </div>
            </div>
        `;
    }

    let argsText = displayString(msg?.args, typeof msg?.args === "object");
    if (parsedArgs) {
        argsText = JSON.stringify(parsedArgs, null, 2);
    }

    return `
        <details class="chat-tool-call" ${idxAttr}>
            <summary>
                <span class="chat-tool-icon" aria-hidden="true">◇</span>
                <span class="chat-tool-name">${escapeHTML(tname || "Tool")}</span>
                <span class="chat-tool-call-meta">Parameter</span>
            </summary>
            <pre class="chat-tool-args"><code>${escapeHTML(argsText)}</code></pre>
        </details>
    `;
}

// --- Code Review Modal functions (Original Antigravity design) ---
function openReviewModal(filename, diffText) {
    const overlay = document.getElementById("review-modal-overlay");
    const titleEl = document.getElementById("review-modal-filename");
    const container = document.getElementById("review-diff-container");
    if (!overlay || !container) return;

    if (titleEl) titleEl.innerText = filename;

    // Parse diff text into colored lines
    const lines = diffText.split('\n');
    let html = '';
    lines.forEach(line => {
        let cls = 'diff-line';
        if (line.startsWith('+') && !line.startsWith('+++')) {
            cls += ' added';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
            cls += ' removed';
        } else if (line.startsWith('@@')) {
            cls += ' header';
        }
        html += `<span class="${cls}">${escapeHTML(line)}</span>`;
    });

    container.innerHTML = html;
    overlay.style.display = "flex";
}

function closeReviewModal(event) {
    if (event) event.stopPropagation();
    const overlay = document.getElementById("review-modal-overlay");
    if (overlay) overlay.style.display = "none";
}

// Global hooks
window.triggerCodeReview = function(filename, encodedDiff) {
    try {
        const decoded = decodeURIComponent(encodedDiff);
        window._activeCodeReview = {
            filename,
            conversationId: activeConvoId,
            projectId: currentProjectId,
        };
        openReviewModal(filename, decoded);
    } catch(e) {
        console.error("Failed to decode diff:", e);
    }
};
window.openCodeReviewWorkspace = function() {
    const review = window._activeCodeReview || {};
    if (
        review.conversationId
        && review.conversationId !== "new"
        && !String(review.conversationId).startsWith("proxy-")
    ) {
        openConversationIde(review.conversationId);
        return;
    }
    openProjectIde(review.projectId);
};
window.closeReviewModal = closeReviewModal;
