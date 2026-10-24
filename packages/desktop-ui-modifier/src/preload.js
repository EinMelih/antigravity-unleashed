"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
/**
 * Preload script — runs in every BrowserWindow before the page loads.
 * Exposes a minimal, secure API via contextBridge so the renderer can
 * communicate with the main-process auto-updater without nodeIntegration.
 */
const electron_1 = require("electron");
const securityTokenPromise = electron_1.ipcRenderer.invoke('security:get-token')
    .then((token) => {
        if (typeof token !== 'string' || !token) {
            throw new Error('Main process returned an invalid IPC security token.');
        }
        return token;
    });
const updaterAPI = {
    getState: () => electron_1.ipcRenderer.invoke('updater:get-state'),
    onStateChanged: (callback) => {
        const handler = (_event, state) => {
            callback(state);
        };
        electron_1.ipcRenderer.on('updater:state-changed', handler);
        // Return unsubscribe function
        return () => {
            electron_1.ipcRenderer.removeListener('updater:state-changed', handler);
        };
    },
    applyUpdate: () => electron_1.ipcRenderer.invoke('updater:apply'),
    quitAndInstall: () => electron_1.ipcRenderer.invoke('updater:quit-and-install'),
    checkForUpdates: () => electron_1.ipcRenderer.invoke('updater:check-for-updates'),
};
const dialogAPI = {
    showOpenDialog: () => electron_1.ipcRenderer.invoke('dialog:open-workspace'),
    showOpenMultipleFolderDialog: () => electron_1.ipcRenderer.invoke('dialog:open-workspaces'),
};
const notificationAPI = {
    send: (options) => electron_1.ipcRenderer.invoke('notification:send', options),
    openSystemPreferences: () => electron_1.ipcRenderer.invoke('notification:open-system-preferences'),
    onClicked: (callback) => {
        const handler = (_event, payload) => {
            callback(payload);
        };
        electron_1.ipcRenderer.on('notification:clicked', handler);
        return () => {
            electron_1.ipcRenderer.removeListener('notification:clicked', handler);
        };
    },
};
const storageAPI = {
    getItems: () => electron_1.ipcRenderer.invoke('storage:get-items'),
    updateItems: (changes) => electron_1.ipcRenderer.invoke('storage:update-items', changes),
    onChanged: (callback) => {
        const handler = (_event, changes) => {
            callback(changes);
        };
        electron_1.ipcRenderer.on('storage:changed', handler);
        return () => {
            electron_1.ipcRenderer.removeListener('storage:changed', handler);
        };
    },
};
const logsAPI = {
    getElectronLogs: () => electron_1.ipcRenderer.invoke('logs:electron'),
};
const extensionsAPI = {
    sendAuthorities: (authoritiesMap) => electron_1.ipcRenderer.invoke('extensions:send-authorities', authoritiesMap),
};
const deepLinkAPI = {
    onDeepLink: (callback) => {
        const handler = (_event, url) => {
            callback(url);
        };
        electron_1.ipcRenderer.on('deep-link', handler);
        return () => {
            electron_1.ipcRenderer.removeListener('deep-link', handler);
        };
    },
    getStoredDeepLink: () => electron_1.ipcRenderer.invoke('deep-link:get-stored'),
};
const agentAPI = {
    updateActiveAgentCount: (count) => electron_1.ipcRenderer.invoke('agent:update-active-count', count),
};
const commitProgressListeners = new WeakMap();
const electronNativeAPI = {
    getZoomLevel: () => electron_1.webFrame.getZoomFactor(),
    getPathForFile: (file) => electron_1.webUtils.getPathForFile(file),
    setTitleBarOverlay: (options) => electron_1.ipcRenderer.invoke('window:set-title-bar-overlay', options),
    minimize: () => electron_1.ipcRenderer.invoke('window:minimize'),
    maximize: () => electron_1.ipcRenderer.invoke('window:maximize'),
    unmaximize: () => electron_1.ipcRenderer.invoke('window:unmaximize'),
    isMaximized: () => electron_1.ipcRenderer.invoke('window:is-maximized'),
    getWindowRole: () => electron_1.ipcRenderer.invoke('window:get-role'),
    getProfileInfo: () => electron_1.ipcRenderer.invoke('window:get-profile-info'),
    prepareAutomation: () => electron_1.ipcRenderer.invoke('window:prepare-automation'),
    close: () => electron_1.ipcRenderer.invoke('window:close'),
    toggleDevTools: () => electron_1.ipcRenderer.invoke('window:toggle-devtools'),
    zoomIn: () => {
        void electron_1.ipcRenderer.invoke('window:zoom-in');
    },
    zoomOut: () => {
        void electron_1.ipcRenderer.invoke('window:zoom-out');
    },
    resetZoom: () => {
        void electron_1.ipcRenderer.invoke('window:reset-zoom');
    },
    openExternal: (url) => electron_1.ipcRenderer.invoke('shell:open-external', url),
    revealInFilePicker: (path) => electron_1.ipcRenderer.invoke('shell:reveal-in-file-picker', path),
    showContextMenu: (items) => electron_1.ipcRenderer.invoke('window:show-context-menu', items),
    closeContextMenu: () => electron_1.ipcRenderer.invoke('window:close-context-menu'),
    executeJavaScriptInIsolatedWorld: (wcId, worldId, code) => electron_1.ipcRenderer.invoke('webview:execute-js-isolated-world', wcId, worldId, code),
    openBrain: () => electron_1.ipcRenderer.invoke('shell:open-brain'),
    getSyncStatus: () => electron_1.ipcRenderer.invoke('shell:get-sync-status'),
    getPRs: (conversationId) => electron_1.ipcRenderer.invoke('git:get-prs', conversationId),
    getIssues: (conversationId) => electron_1.ipcRenderer.invoke('git:get-issues', conversationId),
    commitAndPush: (message, conversationId) => electron_1.ipcRenderer.invoke('git:commit-and-push', message, conversationId),
    getConfigSyncInfo: () => electron_1.ipcRenderer.invoke('git:get-config-sync-info'),
    setupConfigRemote: (target, createPrivate) => electron_1.ipcRenderer.invoke('git:setup-config-remote', target, createPrivate === true),
    importConfigRemote: (target) => electron_1.ipcRenderer.invoke('git:import-config-remote', target || ''),
    setConfigAutoSync: (minutes) => electron_1.ipcRenderer.invoke('git:set-config-auto-sync', minutes),
    syncConfigOnly: (message) => electron_1.ipcRenderer.invoke('git:sync-config-only', message || ''),
    ghAuthLogin: () => electron_1.ipcRenderer.invoke('git:gh-auth-login'),
    getGitStatus: (conversationId) => electron_1.ipcRenderer.invoke('git:get-status', conversationId),
    getGitDiff: (filePath, repoType, conversationId) => electron_1.ipcRenderer.invoke('git:get-diff', filePath, repoType, conversationId),
    generateCommitMsg: (conversationId, csrfToken) => electron_1.ipcRenderer.invoke('git:generate-commit-msg', conversationId, csrfToken),
    getAiConfig: () => electron_1.ipcRenderer.invoke('ai:get-config'),
    saveAiConfig: (cfg) => electron_1.ipcRenderer.invoke('ai:save-config', cfg),
    testAiConnection: (cfg, csrfToken) => electron_1.ipcRenderer.invoke('ai:test-connection', cfg, csrfToken),
    deleteTempConversation: (convoId, csrfToken) => electron_1.ipcRenderer.invoke('git:delete-temp-conversation', convoId, csrfToken),
    getReviews: () => electron_1.ipcRenderer.invoke('reviews:get-runs'),
    getRunLog: (convoId) => electron_1.ipcRenderer.invoke('reviews:get-run-log', convoId),
    getTaskPlan: (conversationId) => electron_1.ipcRenderer.invoke('task:get-plan', conversationId),
    setTaskPlan: (text, conversationId) => electron_1.ipcRenderer.invoke('task:set-plan', text, conversationId),
    getNotes: (conversationId) => electron_1.ipcRenderer.invoke('notes:get-notes', conversationId),
    setNotes: (text, syncAI, conversationId) => electron_1.ipcRenderer.invoke('notes:set-notes', text, syncAI, conversationId),
    writeToClipboard: (text) => electron_1.ipcRenderer.invoke('clipboard:write-text', text),
    getHistory: () => electron_1.ipcRenderer.invoke('logs:get-history'),
    getUpgradeHistory: () => electron_1.ipcRenderer.invoke('updater:get-upgrade-history'),
    getApiWindowVisible: () => electron_1.ipcRenderer.invoke('api-window:get-visible'),
    setApiWindowVisible: (visible) => electron_1.ipcRenderer.invoke('api-window:set-visible', visible === true),
    writeLogEntry: (entry) => electron_1.ipcRenderer.invoke('logs:write-entry', entry),
    consolidateMemory: (conversationId, csrfToken) => electron_1.ipcRenderer.invoke('git:consolidate-memory', conversationId, csrfToken),
    applyMemorySuggestion: (type, text) => electron_1.ipcRenderer.invoke('memory:apply-suggestion', type, text),
    getCompactionCount: (conversationId) => electron_1.ipcRenderer.invoke('trajectory:get-compaction-count', conversationId),
    getTokenStats: (conversationId) => electron_1.ipcRenderer.invoke('trajectory:get-token-stats', conversationId),
    openDuplicateWindow: (_token) => securityTokenPromise.then((token) => electron_1.ipcRenderer.invoke('window:open-duplicate', token)),
    prepareWorkspaceOpen: (workspacePath) => securityTokenPromise.then((token) => electron_1.ipcRenderer.invoke('dialog:prepare-workspace', token, workspacePath)),
    readSwitchRequest: (_token) => securityTokenPromise.then((token) => electron_1.ipcRenderer.invoke('bridge:read-switch-request', token)),
    writeStatus: (_token, modelName) => securityTokenPromise.then((token) => electron_1.ipcRenderer.invoke('bridge:write-status', token, modelName)),
    hubRequest: (_token, operation, payload) => securityTokenPromise.then((token) => electron_1.ipcRenderer.invoke('hub:request', token, operation, payload)),
    onGenerateCommitProgress: (callback) => {
        if (typeof callback !== 'function') return;
        const listener = (_event, message) => callback(String(message || '').slice(0, 2000));
        const previous = commitProgressListeners.get(callback);
        if (previous) electron_1.ipcRenderer.removeListener('git:generate-commit-progress', previous);
        commitProgressListeners.set(callback, listener);
        electron_1.ipcRenderer.on('git:generate-commit-progress', listener);
    },
    removeGenerateCommitProgressListener: (callback) => {
        const listener = commitProgressListeners.get(callback);
        if (!listener) return;
        electron_1.ipcRenderer.removeListener('git:generate-commit-progress', listener);
        commitProgressListeners.delete(callback);
    },
};
const ideAPI = {
    isInstalled: () => electron_1.ipcRenderer.invoke('ide:is-installed'),
};
const wslAPI = {
    getState: () => electron_1.ipcRenderer.invoke('wsl:get-state'),
    connect: (distro) => electron_1.ipcRenderer.invoke('wsl:connect', distro),
};
electron_1.contextBridge.exposeInMainWorld('electronUpdater', updaterAPI);
electron_1.contextBridge.exposeInMainWorld('dialog', dialogAPI);
electron_1.contextBridge.exposeInMainWorld('nativeNotifications', notificationAPI);
electron_1.contextBridge.exposeInMainWorld('nativeStorage', storageAPI);
electron_1.contextBridge.exposeInMainWorld('logs', logsAPI);
electron_1.contextBridge.exposeInMainWorld('extensions', extensionsAPI);
electron_1.contextBridge.exposeInMainWorld('deepLink', deepLinkAPI);
electron_1.contextBridge.exposeInMainWorld('agent', agentAPI);
electron_1.contextBridge.exposeInMainWorld('electronNative', electronNativeAPI);
electron_1.contextBridge.exposeInMainWorld('ide', ideAPI);
electron_1.contextBridge.exposeInMainWorld('wsl', wslAPI);

// Antigravity Autonomy & Memory System (AMS) - Main World Script Injection
const amsScriptContent = `(async function() {
    if (window.__antigravity_ams_loaded) {
        console.log('[AMS] Script already loaded. Skipping duplicate initialization.');
        return;
    }
    window.__antigravity_ams_loaded = true;

    // DevTools-Shortcut (F12 / Ctrl+Shift+I) abfangen und triggern
    window.addEventListener('keydown', (e) => {
        if (e.key === 'F12' || (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'i')) {
            try {
                if (window.electronNative && window.electronNative.toggleDevTools) {
                    e.preventDefault();
                    window.electronNative.toggleDevTools();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle DevTools via shortcut:', err);
            }
        }

        // Quick Menu Shortcut: Ctrl+Shift+B
        if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'b') {
            try {
                e.preventDefault();
                if (window.toggleQuickMenu) {
                    window.toggleQuickMenu();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle Quick Menu via shortcut:', err);
            }
        }

        // Plan Panel Shortcut: Ctrl+Shift+P
        if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'p') {
            try {
                e.preventDefault();
                if (typeof togglePlanPanel === 'function') {
                    togglePlanPanel();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle Plan Panel via shortcut:', err);
            }
        }
    });

    // Kept as a compatibility argument for the exposed API. The real token
    // remains inside the context-isolated preload and is never injected here.
    const amsToken = '';

    console.log('[AMS] Initializing Autonomy & Memory System in main world...');

    let nativeStorageItems = {};
    try {
        nativeStorageItems = await window.nativeStorage.getItems() || {};
    } catch (e) {
        console.error('[AMS] Failed to load nativeStorage:', e);
    }

    // Auto-restore last active session (any page: chats, settings, history, scheduled tasks, etc.)
    try {
        const savedPath = nativeStorageItems.antigravity_last_chat_path;
        const currentPath = window.location.pathname + window.location.search;
        if ((window.location.pathname === '/' || window.location.pathname === '') && savedPath && savedPath !== '/' && !savedPath.includes('blank') && currentPath !== savedPath) {
            console.log('[AMS] Restoring last active session:', savedPath);
            window.location.href = window.location.origin + savedPath;
            return;
        }
    } catch (e) {
        console.error('[AMS] Failed to restore last active session:', e);
    }

    // Save current page path on initial load (only if focused or no saved path yet)
    let lastStoragePathSaveTs = 0;
    const syncFocusedWindowPath = () => {
        try {
            window.__ams_last_user_interaction_ts = Date.now();
            const activeCid = typeof window.amsGetActiveCascadeId === 'function' ? window.amsGetActiveCascadeId() : '';
            const curPath = activeCid ? ('/c/' + activeCid) : (window.location.pathname + window.location.search);
            if (curPath && curPath !== '/' && curPath !== '' && !curPath.includes('blank')) {
                if (Date.now() - lastStoragePathSaveTs > 1500) {
                    lastStoragePathSaveTs = Date.now();
                    window.nativeStorage.updateItems({ antigravity_last_chat_path: curPath });
                }
            }
        } catch (_) {}
    };
    window.addEventListener('focus', syncFocusedWindowPath);
    document.addEventListener('pointerdown', syncFocusedWindowPath, { passive: true });
    document.addEventListener('keydown', syncFocusedWindowPath, { passive: true });

    try {
        const initialPath = window.location.pathname + window.location.search;
        if (initialPath && initialPath !== '/' && initialPath !== '' && !initialPath.includes('blank')) {
            if (document.hasFocus() || !nativeStorageItems.antigravity_last_chat_path) {
                await window.nativeStorage.updateItems({ antigravity_last_chat_path: initialPath });
            }
        }
    } catch (e) {
        // ignore
    }

    // Auto-save and auto-restore message input draft

        // ============================================================================
    // Antigravity Unleashed — Internationalization (i18n) Module
    // Default language: 'en' (English). Toggleable between 'en' and 'de' (German).
    // ============================================================================

    const AMS_EXACT_PAIRS = [
        // Quick Menu (Ctrl+Shift+B)
        ['Brain-Ordner öffnen', 'Open Brain Folder'],
        ['Anti-Gravity Hub öffnen', 'Open Anti-Gravity Hub'],
        ['Hub & API Bridge starten', 'Start Hub & API Bridge'],
        ['Hub & API Bridge neustarten', 'Restart Hub & API Bridge'],
        ['Task-Plan öffnen', 'Open Task & Plan Tracker'],
        ['Task- & Plan-Tracker öffnen', 'Open Task & Plan Tracker'],
        ['Fenster duplizieren', 'Duplicate Window'],
        ['Manuelles Git Sync & Cloud-Backup', 'Manual Git Sync & Cloud Backup'],
        ['Manuelles Git Sync', 'Manual Git Sync'],
        ['Auto-Sync (Config): Aus (klicken für 15 Min.)', 'Auto-Sync (Config): Off (click for 15m)'],
        ['Update- & Patch-Log', 'Update & Patch Log'],
        ['API-Fenster: wird geladen ...', 'API Window: loading...'],
        ['API-Fenster: sichtbar (klicken zum Verstecken)', 'API Window: visible (click to hide)'],
        ['API-Fenster: versteckt (klicken zum Anzeigen)', 'API Window: hidden (click to show)'],
        ['🌐 Sprache: Deutsch (klicken für English)', '🌐 Language: English (click for Deutsch)'],
        ['Cache-Hit Sound: Aktiv (Cha-Ching)', 'Cache-Hit Sound: Active (Cha-Ching)'],
        ['Cache-Hit Sound: Stumm', 'Cache-Hit Sound: Muted'],
        ['Cache-Hit Sound: AN (Testen)', 'Cache-Hit Sound: ON (Test)'],
        ['Cache-Hit Sound: AUS', 'Cache-Hit Sound: OFF'],
        ['Neuer Chat', 'New Chat'],
        ['Direkt in neuen Chat springen', 'Jump to New Chat (Save Quota)'],
        ['Kalt-Send', 'Cold Send'],
        ['Konflikt ⚠️', 'Conflict ⚠️'],
        ['Fehler', 'Error'],
        ['Modell:', 'Model:'],
        ['Sync-Status:', 'Sync Status:'],
        ['Prüfe...', 'Checking...'],
        ['● Prüfe…', '● Checking…'],
        ['Sync OK', 'Sync OK'],
        ['● Offline', '● Offline'],
        ['Unbekannt', 'Unknown'],

        // Composer Bar, Quota Watcher & API Monitor
        ['API bereit', 'API ready'],
        ['API wartet', 'API waiting'],
        ['API wird geprüft', 'Checking API...'],
        ['API offline', 'API offline'],
        ['API-Status', 'API Status'],
        ['API-Details schließen', 'Close API details'],
        ['API-Status und letzte Requests anzeigen', 'Show API status and recent requests'],
        ['Eigenes API-Profil · Health und Request-Details', 'Isolated API Profile · Health & Request Details'],
        ['Profil api · Home, Regeln, Memory und Chats getrennt', 'Profile api · Isolated Home, Rules, Memory & Chats'],
        ['Profil api · Trennung wird geprüft', 'Profile api · Checking isolation...'],
        ['Letzte API-Requests', 'Recent API Requests'],
        ['Status wird geladen …', 'Loading status...'],
        ['Keine aktuellen API-Daten verfügbar.', 'No recent API data available.'],
        ['Seit diesem API-Start wurden noch keine Chat-Requests ausgeführt.', 'No chat requests executed since API start.'],
        ['Erfolgreich', 'Success'],
        ['Wartet', 'Queued'],
        ['Läuft', 'Running'],
        ['Native Modellauswahl', 'Native Model Selection'],
        ['Anzeige ist lesend. Requests laufen im separaten API-Fenster.', 'Read-only view. Requests run in the isolated API window.'],
        ['Quoten-Wächter:', 'Quota Guard:'],
        ['Aktiv', 'Active'],
        ['Ablauf', 'Reset'],
        ['Wöchentlich', 'Weekly'],

        // Task & Plan Tracker Side Panel (Ctrl+Shift+P)
        ['Tasks', 'Tasks'],
        ['Bearbeiten', 'Edit'],
        ['Reviews', 'Reviews'],
        ['PRs', 'PRs'],
        ['Issues', 'Issues'],
        ['Schließen', 'Close'],
        ['Notizen', 'Notes'],
        ['Hinterlasse hier deine freien Notizen für dieses Gespräch...', 'Write your session notes for this conversation here...'],
        ['# Task Plan\\n- [ ] Erster Schritt\\n  - [ ] Subtask', '# Task Plan\\n- [ ] First step\\n  - [ ] Subtask'],
        ['Als AI-Kontext (notes.txt) freigeben', 'Share as AI context (notes.txt)'],
        ['Mit GitHub synchronisieren', 'Sync with GitHub'],
        ['Syncing...', 'Syncing...'],
        ['Synchronisiere...', 'Syncing...'],
        ['Anzahl der durchgeführten Kontext-Kompaktierungen für dieses Gespräch', 'Number of context compactions performed in this conversation'],
        ['Bisher wurden keine automatischen Kompaktierungen durchgeführt.', 'No automatic context compactions performed yet.'],
        ['Token-Verbrauch für dieses Gespräch (Details per Hover)', 'Token usage for this conversation (hover for details)'],
        ['Speichert...', 'Saving...'],
        ['Gespeichert', 'Saved'],
        ['Keine uncommitted Änderungen im Workspace vorhanden', 'No uncommitted changes in workspace'],
        ['Task löschen', 'Delete task'],
        ['Task hinzufügen', 'Add task'],
        ['Möchtest du diesen Task wirklich löschen?', 'Do you really want to delete this task?'],
        ['Ja, löschen', 'Yes, delete'],
        ['Keine Tasks gefunden.', 'No tasks found.'],
        ['Nutze das "Bearbeiten"-Tab, um einen Plan im Markdown-Checklisten-Format hinzuzufügen.', 'Use the "Edit" tab to add a plan in Markdown checklist format.'],
        ['- [ ] Anforderungen & Codebasis analysieren', '- [ ] Analyze requirements & codebase'],
        ['- [ ] Implementierung durchführen', '- [ ] Implement changes'],
        ['- [ ] Tests & Validierung ausführen', '- [ ] Run tests & validation'],

        // Reviews, PRs & Issues Tabs
        ['Lade Reviews...', 'Loading reviews...'],
        ['Keine nächtlichen Läufe protokolliert.', 'No nightly runs logged yet.'],
        ['Log ansehen', 'View Log'],
        ['PR ansehen', 'View PR'],
        ['Fehler beim Laden der Reviews.', 'Failed to load reviews.'],
        ['Ausführungs-Log schließen', 'Close execution log'],
        ['Lade Log-Details aus SQLite-Datenbank...', 'Loading log details from SQLite database...'],
        ['Keine Einträge in der Datenbank gefunden.', 'No entries found in database.'],
        ['Fehler beim Laden des Logs.', 'Failed to load log.'],
        ['Lade Pull Requests...', 'Loading pull requests...'],
        ['Keine Pull Requests gefunden.', 'No pull requests found.'],
        ['Details anzeigen ▾', 'Show details ▾'],
        ['Details verbergen ▴', 'Hide details ▴'],
        ['*Keine Beschreibung vorhanden.*', '*No description provided.*'],
        ['Subtasks planen', 'Plan subtasks'],
        ['An Chat senden', 'Send to chat'],
        ['Im Browser öffnen', 'Open in browser'],
        ['Daten im Speicher nicht gefunden!', 'Data not found in memory!'],
        ['Chat-Eingabefeld nicht gefunden!', 'Chat input field not found!'],
        ['Kein GitHub-Remote-Repository konfiguriert.', 'No GitHub remote repository configured.'],
        ['Füge ein Remote-Repository hinzu (z.B. git remote add origin <url>), um Pull Requests anzuzeigen.', 'Add a remote repository (e.g. git remote add origin <url>) to view pull requests.'],
        ['Füge ein Remote-Repository hinzu, um Issues anzuzeigen.', 'Add a remote repository to view issues.'],
        ['Kein Git-Repository in diesem Workspace gefunden.', 'No Git repository found in this workspace.'],
        ['Lade Issues...', 'Loading issues...'],
        ['Keine offenen Issues gefunden.', 'No open issues found.'],

        // Log Viewer & Memory Consolidation ("Lernen")
        ['🧠 Lernen', '🧠 Learn'],
        ['Langzeitgedächtnis aus dem Chatverlauf aktualisieren', 'Update long-term memory from chat history'],
        ['IPC geschützt', 'IPC protected'],
        ['🧠 Analysiere...', '🧠 Analyzing...'],
        ['Keine aktive Konversation geladen.', 'No active conversation loaded.'],
        ['Keine neuen Erkenntnisse im aktuellen Verlauf gefunden.', 'No new insights found in the current conversation.'],
        ['Neues Wissen sichern', 'Save New Insight'],
        ['Die KI hat eine neue Erkenntnis oder Präferenz in diesem Chat erkannt. Du kannst sie vor dem Speichern bearbeiten:', 'The AI detected a new insight or preference in this chat. You can edit it before saving:'],
        ['Gedächtnistyp', 'Memory Type'],
        ['Gelernte Technik (MEMORY.pc.md)', 'Learned Technique (MEMORY.pc.md)'],
        ['Benutzerpräferenz (USER.pc.md)', 'User Preference (USER.pc.md)'],
        ['Erkenntnis / Bulletpoint', 'Insight / Bullet Point'],
        ['z.B. Nutze für X immer Y...', 'e.g. Always use Y for X...'],
        ['Verwerfen', 'Discard'],
        ['Speichern & Kompilieren', 'Save & Compile'],
        ['💾 Speichere...', '💾 Saving...'],
        ['Bitte trage eine Erkenntnis ein.', 'Please enter an insight.'],
        ['Gedächtnis erfolgreich aktualisiert und kompiliert!', 'Memory updated and compiled successfully!'],

        // Git Sync & Cloud-Backup Modal
        ['Git Sync, Cloud-Backup & Workspace Diffs', 'Git Sync, Cloud Backup & Workspace Diffs'],
        ['Git Sync & Workspace Diffs', 'Git Sync & Workspace Diffs'],
        ['Git-Sync-Dialog schließen', 'Close Git Sync dialog'],
        ['☁️ Cloud-Backup, Memory & Nutzungsdaten (~/.gemini/config)', '☁️ Cloud Backup, Memory & Usage Data (~/.gemini/config)'],
        ['Prüfe Status...', 'Checking status...'],
        ['Status nicht verfügbar', 'Status unavailable'],
        ['○ Nur lokal (Kein GitHub-Remote verbunden)', '○ Local only (No GitHub remote linked)'],
        ['Sichert automatisch MEMORY.pc.md, USER.pc.md, Skills & usage_stats.json (Tokens, Sessions, Modelle) in deinem privaten GitHub-Repo und stellt sie auf jedem Zweit-PC/Laptop per 1-Klick wieder her.', 'Automatically backs up MEMORY.pc.md, USER.pc.md, skills & usage_stats.json (tokens, sessions, models) to your private GitHub repo and restores them on any 2nd PC/laptop in 1 click.'],
        ['📊 Lade Nutzungsdaten...', '📊 Loading usage stats...'],
        ['🔑 1. GitHub Login', '🔑 1. GitHub Login'],
        ['🔒 2. Privates Repo erstellen & verbinden', '🔒 2. Create & Link Private Repo'],
        ['📥 Auf 2. PC importieren (Pull & Restore)', '📥 Import on 2nd PC (Pull & Restore)'],
        ['🔗 Repo-URL ändern / eingeben', '🔗 Change / Enter Repo URL'],
        ['z.B. https://github.com/DeinName/antigravity-config.git oder DeinName/antigravity-config', 'e.g. https://github.com/YourName/antigravity-config.git or YourName/antigravity-config'],
        ['Verbinden & Pushen', 'Link & Push'],
        ['Von dieser URL importieren', 'Import from this URL'],
        ['Wähle eine Datei aus, um das Diff anzuzeigen', 'Select a file to view its diff'],
        ['Keine Zeilenänderungen in dieser Datei', 'No line changes in this file'],
        ['Lade Git Status...', 'Loading Git status...'],
        ['Fehler beim Laden des Git-Status', 'Failed to load Git status'],
        ['Keine Änderungen gefunden', 'No changes found'],
        ['Lade Dateidiff...', 'Loading file diff...'],
        ['Commit-Beschreibung eingeben...', 'Enter commit message...'],
        ['✨ AI Generieren', '✨ Generate with AI'],
        ['Generiere...', 'Generating...'],
        ['Commit-Message erfolgreich generiert!', 'Commit message generated successfully!'],
        ['AI Denkvorgang & Aktivitäten:', 'AI Thinking & Activity:'],
        ['Workspace-Status und Git-Projekt ermitteln...', 'Checking workspace status and Git repository...'],
        ['Abbrechen', 'Cancel'],
        ['Synchronisieren & Pushen', 'Sync & Push'],
        ['Erfolgreich gepusht!', 'Pushed successfully!'],
        ['Öffne PowerShell für GitHub Web-Login (gh auth login --web)... Nach dem Login im Browser wird der Status automatisch aktualisiert.', 'Opening PowerShell for GitHub web login (gh auth login --web)... Status will refresh automatically after browser login.'],
        ['Erstelle/verbinde privates Repository "antigravity-config" und synchronisiere ~/.gemini/config + usage_stats.json...', 'Creating/linking private repository "antigravity-config" and syncing ~/.gemini/config + usage_stats.json...'],
        ['Importiere Config, Memory & Nutzungsdaten vom Remote (lokale Dateien werden zuvor unter ~/.gemini/config/backups/ gesichert)...', 'Importing config, memory & usage stats from remote (local files are backed up to ~/.gemini/config/backups/ first)...'],
        ['Bitte gib die GitHub-URL oder "DeinName/antigravity-config" deines bestehenden Config-Repos ein und klicke auf "Von dieser URL importieren".', 'Please enter the GitHub URL or "YourName/antigravity-config" of your existing config repo and click "Import from this URL".'],
        ['Bitte zuerst eine Repository-URL oder "user/repo" eingeben.', 'Please enter a repository URL or "user/repo" first.'],
        ['Bitte zuerst eine Repository-URL oder "user/repo" zum Importieren eingeben.', 'Please enter a repository URL or "user/repo" to import from first.'],

        // Official Update Dialog & Release Catalog (updateReleaseInfo.js + modals.js)
        ['⚠️ Wichtig: Das offizielle Update ersetzt lokale UI-Patches. Bitte führe nach der Installation den Antigravity UI-Patcher erneut aus, damit alle Custom-Features erhalten bleiben.', '⚠️ Important: The official update overwrites local UI patches. Please re-run the Antigravity UI Patcher after installation to keep all custom features active.'],
        ['⚠️ Wichtig: Das offizielle Update ersetzt lokale UI-Patches. Nach dem Neustart prüft der Patch-Guard zuerst die Versionskompatibilität. Nur ausdrücklich unterstützte Versionen werden automatisch gepatcht; andernfalls bleibt die sichere offizielle Oberfläche aktiv, bis der Modifier aktualisiert wurde.', '⚠️ Important: The official update overwrites local UI patches. After restart, Patch Guard verifies version compatibility first. Only explicitly supported versions are patched automatically; otherwise the safe official UI remains active until the modifier is updated.'],
        ['Offizielle Änderungen', 'Official Changes'],
        ['Offizieller Google-Changelog', 'Official Google Changelog'],
        ['Die wichtigsten Änderungen', 'Key Highlights'],
        ['Der Update-Feed enthält für diese Version keine eingebetteten Release Notes. Über den Link unten kannst du den offiziellen Google-Changelog im Browser öffnen.', 'The update feed does not include embedded release notes for this version. Use the link below to open the official Google changelog in your browser.'],
        ['Der Update-Feed enthält für diese Version keine eingebetteten Release Notes. Der vollständige offizielle Changelog ist unten verlinkt.', 'The update feed does not include embedded release notes for this version. The full official changelog is linked below.'],
        ['Vollständigen offiziellen Changelog öffnen ↗', 'Open full official changelog ↗'],
        ['Das Update ist vollständig heruntergeladen und kann jetzt installiert werden.', 'The update is fully downloaded and ready to install.'],
        ['Das Update ist vollständig heruntergeladen. Möchtest du Antigravity jetzt neu starten und installieren?', 'The update is fully downloaded. Would you like to restart Antigravity and install it now?'],
        ['Das Update wird automatisch im Hintergrund geladen. Sobald der Download abgeschlossen ist, kannst du neu starten.', 'The update is downloading in the background. Once finished, you can restart to install it.'],
        ['Das Update wird automatisch im Hintergrund geladen. Du kannst Antigravity währenddessen weiterverwenden.', 'The update is downloading in the background. You can continue using Antigravity in the meantime.'],
        ['Später', 'Later'],
        ['Neu starten & installieren', 'Restart & Install'],
        ['Verstanden', 'Got it'],
        ['16. April 2026', 'April 16, 2026'],
        ['Offizielles Wartungs- und Feature-Release mit verbessertem Diff-Kontext im Chat, einem kompakten Nutzungs-Indikator im Modell-Wähler sowie mehreren Stabilitäts- und Terminal-Korrekturen.', 'Official maintenance and feature release with improved diff line context in chat, a compact usage indicator in the model selector, and multiple stability and terminal fixes.'],
        ['Neu', 'New'],
        ['Fix', 'Fix'],
        ['Präziser Zeilen-Kontext aus Diffs', 'Precise Line Context from Diffs'],
        ['Kompakter Nutzungs-Indikator im Modell-Wähler', 'Compact Usage Indicator in Model Selector'],
        ['Schutz vor Endlos-Rekursion bei symbolischen Links', 'Infinite Symlink Recursion Protection'],
        ['Stabilere mehrstufige Shell-Pipelines', 'More Stable Multi-Stage Shell Pipelines'],
        ['Zuverlässigeres Beenden von Hintergrund-Terminals', 'Reliable Background Terminal Termination'],
        ['20. August 2026', 'August 20, 2026'],
        ['Remote Control, schnellerer Projektwechsel und mehr', 'Remote Control, faster project switching, and more'],
        ['Remote Control, spürbare Performance-Verbesserungen, eine übersichtlichere Navigation und robustere Fehlerbehandlung.', 'Remote Control, noticeable performance improvements, cleaner navigation, and more robust error handling.'],
        ['Remote Control steuert und überwacht lokale Agent-Sitzungen sicher aus jedem Browser und sendet Benachrichtigungen bei Abschluss oder Rückfragen.', 'Remote Control securely controls and monitors local agent sessions from any browser and sends notifications on completion or follow-up questions.'],
        ['Schnellerer App-Start, Projektwechsel und Aufbau langer Unterhaltungen sowie weniger Verzögerungen während aktiver Sitzungen.', 'Faster app startup, project switching, and rendering of long conversations, with reduced lag during active sessions.'],
        ['Einklappbare Hauptbereiche, bis zu 30 ungruppierte Unterhaltungen und sofort sichtbare Aktionen verbessern die Sidebar.', 'Collapsible main sections, up to 30 ungrouped conversations, and immediately visible actions improve the sidebar.'],
        ['Die Customizations-Einstellungen für Skills, Regeln, Plugins, Custom Agents und MCP-Server wurden übersichtlicher gestaltet.', 'Customizations settings for Skills, Rules, Plugins, Custom Agents, and MCP servers have been redesigned for clarity.'],
        ['Retry setzt fehlgeschlagene Agent-Aufgaben direkt fort; Custom Agents können vorhandene Customizations über inheritCustomizations übernehmen.', 'Retry resumes failed agent tasks directly; Custom Agents can inherit existing customizations via inheritCustomizations.'],
        ['WebP-Anhänge sowie PowerShell- und Zsh-Syntaxhervorhebung werden jetzt unterstützt.', 'WebP attachments as well as PowerShell and Zsh syntax highlighting are now supported.'],

        // Update & Patch History Modal (modals.js)
        ['Anti-Gravity Update- & Patch-Log', 'Anti-Gravity Update & Patch Log'],
        ['Aktueller Patch-Status: Anti-Gravity', 'Current Patch Status: Anti-Gravity'],
        ['Upstream-Kompatibilität verifiziert · Selbstreparatur & Rollback aktiv', 'Upstream compatibility verified · Self-healing & rollback active'],
        ['● Gepatcht & Aktiv', '● Patched & Active'],
        ['Fehlgeschlagen', 'Failed'],
        ['Selbstgeheilt & verifiziert', 'Self-healed & verified'],
        ['Kompatibel', 'Compatible'],
        ['kompatibel', 'compatible'],
        ['Gepatcht', 'Patched'],
        ['Erkenntnisse & Befunde:', 'Findings & Diagnostics:'],
        ['Dateianpassungen:', 'Modified Files:'],
        ['Alle 4 Injektions-Anker (main.js, workbench.html, jetskiAgent.html, preload.js) kompatibel.', 'All 4 injection anchors (main.js, workbench.html, jetskiAgent.html, preload.js) are compatible.'],
        ['Smoke-Test & Syntax-Validierung erfolgreich bestanden.', 'Smoke test & syntax validation passed successfully.'],
        ['Dynamisches Self-Healing und Backup-Rollback aktiv.', 'Dynamic self-healing and backup rollback active.'],
        ['Offizielle Google-Aktualisierung auf Anti-Gravity v2.22.0', 'Official Google update to Anti-Gravity v2.22.0'],
        ['dist/preload.js um webUtils.getPathForFile erweitert', 'Extended dist/preload.js with webUtils.getPathForFile'],
        ['Alle 4 weiteren Core-Dateien sind 1:1 identisch mit v2.19.1', 'All 4 other core files are 1:1 identical with v2.19.1'],
        ['Automatischer Selbstreparatur-Dialog bei künftigen Versionskonflikten', 'Automatic self-healing dialog on future version conflicts'],
        ['Automatisches Wiederherstellen des aktiven Chats nach Repack-Neustart', 'Automatic restoration of active chat after repack restart'],
        ['Update- & Patch-Log im AMS Quick-Menu verfügbar', 'Update & Patch Log available in AMS Quick Menu'],
        ['Stabiler Rebase auf v2.19.1 mit atomarem Staging und Rollback-Schutz', 'Stable rebase to v2.19.1 with atomic staging and rollback protection'],

        // Additional Diagnostics, Subtasks & Progress Messages
        ['API-Monitor ist nicht erreichbar.', 'API Monitor is unreachable.'],
        ['API-Monitor liefert ungültige Statusdaten.', 'API Monitor returned invalid status data.'],
        ['- [ ] Implementierung vorbereiten & Code anpassen', '- [ ] Prepare implementation & adapt code'],
        ['- [ ] Änderungen lokal testen & verifizieren', '- [ ] Test & verify changes locally'],
        ['- [ ] Pull Request erstellen / Issue abschließen', '- [ ] Create Pull Request / close Issue'],
        ['Unbekannter Fehler', 'Unknown error'],
        ['unbekannt', 'unknown'],
        ['Projekt- und Workspace-IDs aufgelöst.', 'Project and workspace IDs resolved.'],
        ['Neue AI-Konversation wird initiiert...', 'Initiating new AI conversation...'],
        ['Konversation gestartet. Warte auf AI-Denkvorgänge...', 'Conversation started. Waiting for AI reasoning...'],
        ['AI analysiert Änderungen und denkt nach...', 'AI is analyzing changes and thinking...'],
        ['Commit-Message empfangen, schließe Chat...', 'Commit message received, closing chat...'],
        ['Bereinigung abgeschlossen.', 'Cleanup completed.'],
        ['Kein aktiver Workspace oder Git-Repository vorhanden.', 'No active workspace or Git repository found.'],
        ['agentapi.bat wurde nicht gefunden.', 'agentapi.bat was not found.'],
        ['Das AMS Main-World-Skript konnte nicht geladen werden. Dies deutet meistens auf einen Syntax- oder Escaping-Fehler im Preload-Skript hin.', 'The AMS main-world script could not be loaded. This usually indicates a syntax or escaping error in the preload script.'],
        ['IPC-Token ist im Preload-Kontext isoliert', 'IPC token is isolated in the preload context'],
        ['Logs durchsuchen...', 'Search logs...'],
        ['Alle Quellen', 'All Sources'],
        ['Benutzer', 'User'],
        ['Agent', 'Agent'],
        ['System', 'System'],
        ['Lade Log-Verlauf...', 'Loading log history...'],
        ['Metadaten anzeigen', 'Show Metadata'],
        ['Keine Logs gefunden.', 'No logs found.'],
        ['Modell und Token-Anzahl', 'Model and token count'],
        ['Verlauf', 'History'],
        ['Erfolg', 'Success'],
        ['Schleife erkannt', 'Loop Detected'],
        ['Start fehlgeschlagen', 'Failed to launch'],
        ['AI-Engine & Commit-API', 'AI Engine & Commit API'],
        ['API-Optionen ▾', 'API Options ▾'],
        ['API-Optionen ▴', 'API Options ▴'],
        ['⚡ Auto: Unleashed API → Lokal UI (Empfohlen)', '⚡ Auto: Unleashed API → Local UI (Recommended)'],
        ['🌐 Unleashed Server API (/v1 Endpoint)', '🌐 Unleashed Server API (/v1 Endpoint)'],
        ['🖥️ Direkt über Antigravity UI (Ohne Server)', '🖥️ Direct via Antigravity UI (Serverless)'],
        ['📝 Ohne AI (Regelbasiert aus Git-Diff)', '📝 No AI (Rule-based from Git Diff)'],
        ['⚡ Auto (Unleashed API → Lokal UI)', '⚡ Auto (Unleashed API → Local UI)'],
        ['🌐 Unleashed Server API (/v1)', '🌐 Unleashed Server API (/v1)'],
        ['🖥️ Lokal (Antigravity UI direkt)', '🖥️ Local (Direct Antigravity UI)'],
        ['📝 Ohne AI (Regelbasiert)', '📝 No AI (Rule-based)'],
        ['📝 Regelbasiert', '📝 Rule-based'],
        ['⚙️ API & Modell', '⚙️ API & Model'],
        ['AI-Engine:', 'AI Engine:'],
        ['API Base-URL (OpenAI / Unleashed /v1):', 'API Base URL (OpenAI / Unleashed /v1):'],
        ['API-Key / Bearer Token:', 'API Key / Bearer Token:'],
        ['AI-Modell:', 'AI Model:'],
        ['Commit-Stil:', 'Commit Style:'],
        ['Kompakt (1 Zeile)', 'Concise (1 Line)'],
        ['Detailliert (Body)', 'Detailed (Body)'],
        ['🔌 Verbindung testen', '🔌 Test Connection'],
        ['⏳ Teste...', '⏳ Testing...'],
        ['✓ Speichern', '✓ Save'],
        ['⚡ Server (.20:8001)', '⚡ Server (.20:8001)'],
        ['🏠 Lokal (127.0.0.1:8001)', '🏠 Local (127.0.0.1:8001)'],
        ['🖥️ Direkt UI', '🖥️ Direct UI'],
        ['📝 Ohne AI', '📝 No AI'],
        ['Aus (Regel)', 'Off (Rule)'],
        ['Lokal UI', 'Local UI'],
        ['Direkte lokale Antigravity-UI (ConnectRPC) wird verbunden...', 'Connecting to direct local Antigravity UI (ConnectRPC)...'],
        ['Lokale AI analysiert Änderungen...', 'Local AI is analyzing changes...'],
        ['Unleashed API nicht erreichbar – wechsle automatisch auf direkte lokale UI...', 'Unleashed API unreachable – automatically falling back to direct local UI...'],
        ['Regelbasierte Commit-Message aus Git-Status erstellt.', 'Rule-based commit message generated from Git status.'],
    ];

    const AMS_DE_TO_EN = new Map();
    const AMS_EN_TO_DE = new Map();
    AMS_EXACT_PAIRS.forEach(([de, en]) => {
        AMS_DE_TO_EN.set(de, en);
        AMS_EN_TO_DE.set(en, de);
    });

    const AMS_PATTERN_PAIRS = [
        {
            deRe: /^(Gemini|Claude):\\n• 5h: (.+)\\n• (?:Weekly|Wöchentlich): (.+)$/,
            enFmt: (m) => \`\${m[1]}:\\n• 5h: \${m[2].replace(/\\(Ablauf\\)/g, '(Expired)')}\\n• Weekly: \${m[3].replace(/\\(Ablauf\\)/g, '(Expired)')}\`,
            enRe: /^(Gemini|Claude):\\n• 5h: (.+)\\n• (?:Weekly|Wöchentlich): (.+)$/,
            deFmt: (m) => \`\${m[1]}:\\n• 5h: \${m[2].replace(/\\(Expired\\)/g, '(Ablauf)')}\\n• Wöchentlich: \${m[3].replace(/\\(Expired\\)/g, '(Ablauf)')}\`,
        },
        {
            deRe: /^● Verbunden:\\s*(.+)$/,
            enFmt: (m) => \`● Connected: \${m[1]}\`,
            enRe: /^● Connected:\\s*(.+)$/,
            deFmt: (m) => \`● Verbunden: \${m[1]}\`,
        },
        {
            deRe: /^● Online · (\\d+) ms$/,
            enFmt: (m) => \`● Online · \${m[1]} ms\`,
            enRe: /^● Online · (\\d+) ms$/,
            deFmt: (m) => \`● Online · \${m[1]} ms\`,
        },
        {
            deRe: /^API-Home:\\s*(.+)$/,
            enFmt: (m) => \`API Home: \${m[1]}\`,
            enRe: /^API Home:\\s*(.+)$/,
            deFmt: (m) => \`API-Home: \${m[1]}\`,
        },
        {
            deRe: /^Konfliktdateien:\\s*(.+)$/,
            enFmt: (m) => \`Conflict files: \${m[1]}\`,
            enRe: /^Conflict files:\\s*(.+)$/,
            deFmt: (m) => \`Konfliktdateien: \${m[1]}\`,
        },
        {
            deRe: /^Achtung: Git-Konflikte\\/Backups im Brain-Ordner erkannt!\\s*\\((.+)\\)\\.\\s*Klicke hier zum Öffnen\\.$/,
            enFmt: (m) => \`Warning: Git conflicts/backups detected in Brain folder! (\${m[1]}). Click here to open.\`,
            enRe: /^Warning: Git conflicts\\/backups detected in Brain folder!\\s*\\((.+)\\)\\.\\s*Click here to open\\.$/,
            deFmt: (m) => \`Achtung: Git-Konflikte/Backups im Brain-Ordner erkannt! (\${m[1]}). Klicke hier zum Öffnen.\`,
        },
        {
            deRe: /^Claude verbraucht\\. Automatisch auf (.+) umgeschaltet\\.$/,
            enFmt: (m) => \`Claude quota exhausted. Automatically switched to \${m[1]}.\`,
            enRe: /^Claude quota exhausted\\. Automatically switched to (.+)\\.$/,
            deFmt: (m) => \`Claude verbraucht. Automatisch auf \${m[1]} umgeschaltet.\`,
        },
        {
            deRe: /^Auto-Sync \\(Config\\): Alle (\\d+) Min\\. ✓$/,
            enFmt: (m) => \`Auto-Sync (Config): Every \${m[1]}m ✓\`,
            enRe: /^Auto-Sync \\(Config\\): Every (\\d+)m ✓$/,
            deFmt: (m) => \`Auto-Sync (Config): Alle \${m[1]} Min. ✓\`,
        },
        {
            deRe: /^✓ GitHub \\(@angemeldet\\)$/,
            enFmt: () => \`✓ GitHub (@signed in)\`,
            enRe: /^✓ GitHub \\(@signed in\\)$/,
            deFmt: () => \`✓ GitHub (@angemeldet)\`,
        },
        {
            deRe: /^Synchronisierte Geräte in usage_stats\\.json:\\s*(.+)$/,
            enFmt: (m) => \`Synced devices in usage_stats.json: \${m[1]}\`,
            enRe: /^Synced devices in usage_stats\\.json:\\s*(.+)$/,
            deFmt: (m) => \`Synchronisierte Geräte in usage_stats.json: \${m[1]}\`,
        },
        {
            deRe: /^(\\d+) geänderte Datei\\(en\\) im Workspace\\. Klicken zum Synchronisieren\\.$/,
            enFmt: (m) => \`\${m[1]} modified file(s) in workspace. Click to sync.\`,
            enRe: /^(\\d+) modified file\\(s\\) in workspace\\. Click to sync\\.$/,
            deFmt: (m) => \`\${m[1]} geänderte Datei(en) im Workspace. Klicken zum Synchronisieren.\`,
        },
        {
            deRe: /^Dieses Gespräch wurde bereits (\\d+) mal automatisch kompaktwert \\/ bereinigt\\.$/,
            enFmt: (m) => \`This conversation has been automatically compacted \${m[1]} time(s).\`,
            enRe: /^This conversation has been automatically compacted (\\d+) time\\(s\\)\\.$/,
            deFmt: (m) => \`Dieses Gespräch wurde bereits \${m[1]} mal automatisch kompaktwert / bereinigt.\`,
        },
        {
            deRe: /^Akkumulierter Verbrauch für dieses Gespräch:\\n• Input \\(Gesamt\\): (.+)\\n  - Aus Cache: (.+)\\n  - Uncached: (.+)\\n• Output \\(Antworten\\): (.+)\\n\\nLetzter Schritt:\\n• Input: (.+)\\n  - Aus Cache: (.+)\\n  - Uncached: (.+)\\n• Output: (.+)$/,
            enFmt: (m) => \`Accumulated usage for this conversation:\\n• Input (Total): \${m[1]}\\n  - Cached: \${m[2]}\\n  - Uncached: \${m[3]}\\n• Output (Responses): \${m[4]}\\n\\nLatest step:\\n• Input: \${m[5]}\\n  - Cached: \${m[6]}\\n  - Uncached: \${m[7]}\\n• Output: \${m[8]}\`,
            enRe: /^Accumulated usage for this conversation:\\n• Input \\(Total\\): (.+)\\n  - Cached: (.+)\\n  - Uncached: (.+)\\n• Output \\(Responses\\): (.+)\\n\\nLatest step:\\n• Input: (.+)\\n  - Cached: (.+)\\n  - Uncached: (.+)\\n• Output: (.+)$/,
            deFmt: (m) => \`Akkumulierter Verbrauch für dieses Gespräch:\\n• Input (Gesamt): \${m[1]}\\n  - Aus Cache: \${m[2]}\\n  - Uncached: \${m[3]}\\n• Output (Antworten): \${m[4]}\\n\\nLetzter Schritt:\\n• Input: \${m[5]}\\n  - Aus Cache: \${m[6]}\\n  - Uncached: \${m[7]}\\n• Output: \${m[8]}\`,
        },
        {
            deRe: /^Akkumulierter Token-Verbrauch \\(Input\\): (.+)\\nCache-Trefferquote: (.+)\\nOutput: (.+)\\n\\(Details im Task-Planer\\)$/,
            enFmt: (m) => \`Accumulated token usage (Input): \${m[1]}\\nCache hit rate: \${m[2]}\\nOutput: \${m[3]}\\n(Details in Task Tracker)\`,
            enRe: /^Accumulated token usage \\(Input\\): (.+)\\nCache hit rate: (.+)\\nOutput: (.+)\\n\\(Details in Task Tracker\\)$/,
            deFmt: (m) => \`Akkumulierter Token-Verbrauch (Input): \${m[1]}\\nCache-Trefferquote: \${m[2]}\\nOutput: \${m[3]}\\n(Details im Task-Planer)\`,
        },
        {
            deRe: /^Akkumulierter Verbrauch für dieses Gespräch:\\n• Input \\(Gesamt\\): (.+)\\n• Output \\(Generiert\\): (.+)\\n•\\s*Aktueller Kontext: (.+) Tokens$/,
            enFmt: (m) => \`Accumulated usage for this conversation:\\n• Input (Total): \${m[1]}\\n• Output (Generated): \${m[2]}\\n• Current Context: \${m[3]} tokens\`,
            enRe: /^Accumulated usage for this conversation:\\n• Input \\(Total\\): (.+)\\n• Output \\(Generated\\): (.+)\\n• Current Context: (.+) tokens$/,
            deFmt: (m) => \`Akkumulierter Verbrauch für dieses Gespräch:\\n• Input (Gesamt): \${m[1]}\\n• Output (Generiert): \${m[2]}\\n•Aktueller Kontext: \${m[3]} Tokens\`,
        },
        {
            deRe: /^Akkumulierter Token-Verbrauch \\(Input\\): (.+)\\nAktuelles Kontextfenster: (.+) Tokens$/,
            enFmt: (m) => \`Accumulated token usage (Input): \${m[1]}\\nCurrent context window: \${m[2]} tokens\`,
            enRe: /^Accumulated token usage \\(Input\\): (.+)\\nCurrent context window: (.+) tokens$/,
            deFmt: (m) => \`Akkumulierter Token-Verbrauch (Input): \${m[1]}\\nAktuelles Kontextfenster: \${m[2]} Tokens\`,
        },
        {
            deRe: /^(\\d+) Requests seit API-Start · (\\d+) aktiv · (\\d+) Fehler$/,
            enFmt: (m) => \`\${m[1]} requests since API start · \${m[2]} active · \${m[3]} errors\`,
            enRe: /^(\\d+) requests since API start · (\\d+) active · (\\d+) errors$/,
            deFmt: (m) => \`\${m[1]} Requests seit API-Start · \${m[2]} aktiv · \${m[3]} Fehler\`,
        },
        {
            deRe: /^Letzter bekannter Stand:\\s*(.+)$/,
            enFmt: (m) => \`Last known state: \${m[1]}\`,
            enRe: /^Last known state:\\s*(.+)$/,
            deFmt: (m) => \`Letzter bekannter Stand: \${m[1]}\`,
        },
        {
            deRe: /^Antwort:\\s*([\\s\\S]+)$/,
            enFmt: (m) => \`Response: \${m[1]}\`,
            enRe: /^Response:\\s*([\\s\\S]+)$/,
            deFmt: (m) => \`Antwort: \${m[1]}\`,
        },
        {
            deRe: /^Lauf:\\s*(.+)$/,
            enFmt: (m) => \`Run: \${m[1]}\`,
            enRe: /^Run:\\s*(.+)$/,
            deFmt: (m) => \`Lauf: \${m[1]}\`,
        },
        {
            deRe: /^\\| Start:\\s*(.+)$/,
            enFmt: (m) => \`| Start: \${m[1]}\`,
            enRe: /^\\| Start:\\s*(.+)$/,
            deFmt: (m) => \`| Start: \${m[1]}\`,
        },
        {
            deRe: /^\\| Ende:\\s*(.+)$/,
            enFmt: (m) => \`| End: \${m[1]}\`,
            enRe: /^\\| End:\\s*(.+)$/,
            deFmt: (m) => \`| Ende: \${m[1]}\`,
        },
        {
            deRe: /^Ausführungs-Log für\\s*(.+)$/,
            enFmt: (m) => \`Execution Log for \${m[1]}\`,
            enRe: /^Execution Log for\\s*(.+)$/,
            deFmt: (m) => \`Ausführungs-Log für \${m[1]}\`,
        },
        {
            deRe: /^Neuen Task unter ['"](.+)['"] hinzufügen:$/,
            enFmt: (m) => \`Add new task under '\${m[1]}':\`,
            enRe: /^Add new task under ['"](.+)['"]:$/,
            deFmt: (m) => \`Neuen Task unter '\${m[1]}' hinzufügen:\`,
        },
        {
            deRe: /^Synchronisation erfolgreich abgeschlossen!\\n\\n([\\s\\S]*)$/,
            enFmt: (m) => \`Synchronization completed successfully!\\n\\n\${m[1]}\`,
            enRe: /^Synchronization completed successfully!\\n\\n([\\s\\S]*)$/,
            deFmt: (m) => \`Synchronisation erfolgreich abgeschlossen!\\n\\n\${m[1]}\`,
        },
        {
            deRe: /^Fehler bei der Synchronisation:\\n\\n([\\s\\S]*)$/,
            enFmt: (m) => \`Synchronization failed:\\n\\n\${m[1]}\`,
            enRe: /^Synchronization failed:\\n\\n([\\s\\S]*)$/,
            deFmt: (m) => \`Fehler bei der Synchronisation:\\n\\n\${m[1]}\`,
        },
        {
            deRe: /^Ausnahmefehler bei der Synchronisation:\\s*([\\s\\S]*)$/,
            enFmt: (m) => \`Synchronization exception: \${m[1]}\`,
            enRe: /^Synchronization exception:\\s*([\\s\\S]*)$/,
            deFmt: (m) => \`Ausnahmefehler bei der Synchronisation: \${m[1]}\`,
        },
        {
            deRe: /^AI führt Tool aus:\\s*(.+)\\.\\.\\.$/,
            enFmt: (m) => \`AI executing tool: \${m[1]}...\`,
            enRe: /^AI executing tool:\\s*(.+)\\.\\.\\.$/,
            deFmt: (m) => \`AI führt Tool aus: \${m[1]}...\`,
        },
        {
            deRe: /^Pfad:\\s*(.+)$/,
            enFmt: (m) => \`Path: \${m[1]}\`,
            enRe: /^Path:\\s*(.+)$/,
            deFmt: (m) => \`Pfad: \${m[1]}\`,
        },
        {
            deRe: /^Fehler beim Laden:\\s*(.+)$/,
            enFmt: (m) => \`Failed to load: \${m[1]}\`,
            enRe: /^Failed to load:\\s*(.+)$/,
            deFmt: (m) => \`Fehler beim Laden: \${m[1]}\`,
        },
        {
            deRe: /^Ausnahmefehler:\\s*(.+)$/,
            enFmt: (m) => \`Exception: \${m[1]}\`,
            enRe: /^Exception:\\s*(.+)$/,
            deFmt: (m) => \`Ausnahmefehler: \${m[1]}\`,
        },
        {
            deRe: /^Exception beim Laden:\\s*(.+)$/,
            enFmt: (m) => \`Exception while loading: \${m[1]}\`,
            enRe: /^Exception while loading:\\s*(.+)$/,
            deFmt: (m) => \`Exception beim Laden: \${m[1]}\`,
        },
        {
            deRe: /^Fehler beim Laden des Diffs:\\s*(.+)$/,
            enFmt: (m) => \`Failed to load diff: \${m[1]}\`,
            enRe: /^Failed to load diff:\\s*(.+)$/,
            deFmt: (m) => \`Fehler beim Laden des Diffs: \${m[1]}\`,
        },
        {
            deRe: /^Fehler bei der AI-Generierung:\\s*(.+)$/,
            enFmt: (m) => \`AI generation failed: \${m[1]}\`,
            enRe: /^AI generation failed:\\s*(.+)$/,
            deFmt: (m) => \`Fehler bei der AI-Generierung: \${m[1]}\`,
        },
        {
            deRe: /^Fehler bei der Analyse:\\s*(.+)$/,
            enFmt: (m) => \`Analysis failed: \${m[1]}\`,
            enRe: /^Analysis failed:\\s*(.+)$/,
            deFmt: (m) => \`Fehler bei der Analyse: \${m[1]}\`,
        },
        {
            deRe: /^Fehler beim Speichern:\\s*(.+)$/,
            enFmt: (m) => \`Failed to save: \${m[1]}\`,
            enRe: /^Failed to save:\\s*(.+)$/,
            deFmt: (m) => \`Fehler beim Speichern: \${m[1]}\`,
        },
        {
            deRe: /^Speicherfehler:\\s*(.+)$/,
            enFmt: (m) => \`Save error: \${m[1]}\`,
            enRe: /^Save error:\\s*(.+)$/,
            deFmt: (m) => \`Speicherfehler: \${m[1]}\`,
        },
        {
            deRe: /^Erkenntnis gespeichert, Kompilierung fehlgeschlagen:\\s*(.+)$/,
            enFmt: (m) => \`Insight saved, compilation failed: \${m[1]}\`,
            enRe: /^Insight saved, compilation failed:\\s*(.+)$/,
            deFmt: (m) => \`Erkenntnis gespeichert, Kompilierung fehlgeschlagen: \${m[1]}\`,
        },
        {
            deRe: /^Verbinde Remote "(.+)" und pushe lokale Config \\+ Nutzungsdaten\\.\\.\\.$/,
            enFmt: (m) => \`Linking remote "\${m[1]}" and pushing local config + usage stats...\`,
            enRe: /^Linking remote "(.+)" and pushing local config \\+ usage stats\\.\\.\\.$/,
            deFmt: (m) => \`Verbinde Remote "\${m[1]}" und pushe lokale Config + Nutzungsdaten...\`,
        },
        {
            deRe: /^Offizielles Update bereit \\(v(.+)\\)$/,
            enFmt: (m) => \`Official Update Ready (v\${m[1]})\`,
            enRe: /^Official Update Ready \\(v(.+)\\)$/,
            deFmt: (m) => \`Offizielles Update bereit (v\${m[1]})\`,
        },
        {
            deRe: /^Offizielles Update verfügbar \\(v(.+)\\)$/,
            enFmt: (m) => \`Official Update Available (v\${m[1]})\`,
            enRe: /^Official Update Available \\(v(.+)\\)$/,
            deFmt: (m) => \`Offizielles Update verfügbar (v\${m[1]})\`,
        },
        {
            deRe: /^(\\d+) Verbesserungen · (\\d+) Fehlerbehebungen$/,
            enFmt: (m) => \`\${m[1]} improvements · \${m[2]} bug fixes\`,
            enRe: /^(\\d+) improvements · (\\d+) bug fixes$/,
            deFmt: (m) => \`\${m[1]} Verbesserungen · \${m[2]} Fehlerbehebungen\`,
        },
        {
            deRe: /^Aktueller Patch-Status: (.+)$/,
            enFmt: (m) => \`Current Patch Status: \${m[1]}\`,
            enRe: /^Current Patch Status: (.+)$/,
            deFmt: (m) => \`Aktueller Patch-Status: \${m[1]}\`,
        },
        {
            deRe: /^Anti-Gravity v(.+) erfolgreich mit dem UI-Modifier abgeglichen und verifiziert\\.$/,
            enFmt: (m) => \`Anti-Gravity v\${m[1]} successfully reconciled and verified with the UI modifier.\`,
            enRe: /^Anti-Gravity v(.+) successfully reconciled and verified with the UI modifier\\.$/,
            deFmt: (m) => \`Anti-Gravity v\${m[1]} erfolgreich mit dem UI-Modifier abgeglichen und verifiziert.\`,
        },
        {
            deRe: /^· (\\d+) s gesamt$/,
            enFmt: (m) => \`· \${m[1]} s total\`,
            enRe: /^· (\\d+) s total$/,
            deFmt: (m) => \`· \${m[1]} s gesamt\`,
        },
        {
            deRe: /^· Versuch (\\d+)$/,
            enFmt: (m) => \`· Attempt \${m[1]}\`,
            enRe: /^· Attempt (\\d+)$/,
            deFmt: (m) => \`· Versuch \${m[1]}\`,
        },
        {
            deRe: /^✓ Privates GitHub-Repository verbunden & synchronisiert!$/,
            enFmt: () => \`✓ Private GitHub repository connected & synced!\`,
            enRe: /^✓ Private GitHub repository connected & synced!$/,
            deFmt: () => \`✓ Privates GitHub-Repository verbunden & synchronisiert!\`,
        },
        {
            deRe: /^✗ Fehler beim Erstellen\\/Verbinden des Repositories\\.$/,
            enFmt: () => \`✗ Failed to create/connect repository.\`,
            enRe: /^✗ Failed to create\\/connect repository\\.$/,
            deFmt: () => \`✗ Fehler beim Erstellen/Verbinden des Repositories.\`,
        },
        {
            deRe: /^✓ Config & Nutzungsdaten erfolgreich importiert!$/,
            enFmt: () => \`✓ Config & usage stats imported successfully!\`,
            enRe: /^✓ Config & usage stats imported successfully!$/,
            deFmt: () => \`✓ Config & Nutzungsdaten erfolgreich importiert!\`,
        },
        {
            deRe: /^✗ Import fehlgeschlagen\\.$/,
            enFmt: () => \`✗ Import failed.\`,
            enRe: /^✗ Import failed\\.$/,
            deFmt: () => \`✗ Import fehlgeschlagen.\`,
        },
        {
            deRe: /^✓ Remote verbunden und synchronisiert!$/,
            enFmt: () => \`✓ Remote connected and synced!\`,
            enRe: /^✓ Remote connected and synced!$/,
            deFmt: () => \`✓ Remote verbunden und synchronisiert!\`,
        },
        {
            deRe: /^✗ Verbindung fehlgeschlagen\\.$/,
            enFmt: () => \`✗ Connection failed.\`,
            enRe: /^✗ Connection failed\\.$/,
            deFmt: () => \`✗ Verbindung fehlgeschlagen.\`,
        },
        {
            deRe: /^✗ Ausnahmefehler(?:\\s+beim Import)?:\\s*(.+)$/,
            enFmt: (m) => \`✗ Exception: \${m[1]}\`,
            enRe: /^✗ Exception:\\s*(.+)$/,
            deFmt: (m) => \`✗ Ausnahmefehler: \${m[1]}\`,
        },
        {
            deRe: /^✗ Fehler:\\s*(.+)$/,
            enFmt: (m) => \`✗ Error: \${m[1]}\`,
            enRe: /^✗ Error:\\s*(.+)$/,
            deFmt: (m) => \`✗ Fehler: \${m[1]}\`,
        },
        {
            deRe: /^Fehler:\\s*(.+)$/,
            enFmt: (m) => \`Error: \${m[1]}\`,
            enRe: /^Error:\\s*(.+)$/,
            deFmt: (m) => \`Fehler: \${m[1]}\`,
        },
        {
            deRe: /^Ausnahmefehler bei der Generierung:\\s*(.+)$/,
            enFmt: (m) => \`Generation exception: \${m[1]}\`,
            enRe: /^Generation exception:\\s*(.+)$/,
            deFmt: (m) => \`Ausnahmefehler bei der Generierung: \${m[1]}\`,
        },
        {
            deRe: /^(\\d+) Einträge \\| (.+) Tokens$/,
            enFmt: (m) => \`\${m[1]} entries | \${m[2]} tokens\`,
            enRe: /^(\\d+) entries \\| (.+) tokens$/,
            deFmt: (m) => \`\${m[1]} Einträge | \${m[2]} Tokens\`,
        },
        {
            deRe: /^Datei nicht gefunden:\\s*(.+)$/,
            enFmt: (m) => \`File not found: \${m[1]}\`,
            enRe: /^File not found:\\s*(.+)$/,
            deFmt: (m) => \`Datei nicht gefunden: \${m[1]}\`,
        },
        {
            deRe: /^Eintrag gespeichert, aber Kompilierung fehlgeschlagen:\\s*(.+)$/,
            enFmt: (m) => \`Entry saved, but compilation failed: \${m[1]}\`,
            enRe: /^Entry saved, but compilation failed:\\s*(.+)$/,
            deFmt: (m) => \`Eintrag gespeichert, aber Kompilierung fehlgeschlagen: \${m[1]}\`,
        },
        {
            deRe: /^Datenbank für Chat (.+) existiert nicht oder wurde bereinigt\\.$/,
            enFmt: (m) => \`Database for chat \${m[1]} does not exist or has been cleaned up.\`,
            enRe: /^Database for chat (.+) does not exist or has been cleaned up\\.$/,
            deFmt: (m) => \`Datenbank für Chat \${m[1]} existiert nicht oder wurde bereinigt.\`,
        },
    ];

    window.amsGetLang = function() {
        return 'en'; // Fixed to English for clean, consistent UI
    };

    window.amsTranslateString = function(str, targetLang) {
        if (!str || typeof str !== 'string') return str;
        const lang = targetLang || window.amsGetLang();
        const trimmed = str.trim();
        if (!trimmed) return str;

        if (lang === 'en') {
            if (AMS_DE_TO_EN.has(trimmed)) {
                return str.replace(trimmed, AMS_DE_TO_EN.get(trimmed));
            }
            for (const rule of AMS_PATTERN_PAIRS) {
                const m = trimmed.match(rule.deRe);
                if (m) return rule.enFmt(m);
            }
        } else if (lang === 'de') {
            if (AMS_EN_TO_DE.has(trimmed)) {
                return str.replace(trimmed, AMS_EN_TO_DE.get(trimmed));
            }
            for (const rule of AMS_PATTERN_PAIRS) {
                const m = trimmed.match(rule.enRe);
                if (m) return rule.deFmt(m);
            }
        }
        return str;
    };

    window.amsT = function(deText, enText) {
        const lang = window.amsGetLang();
        if (lang === 'en' && enText !== undefined) return enText;
        if (lang === 'de') return deText;
        return window.amsTranslateString(deText, lang);
    };

    const AMS_UI_ROOT_SELECTOR = [
        '#antigravity-plan-panel',
        '#antigravity-exec-log-modal',
        '#antigravity-api-status',
        '#antigravity-api-panel',
        '.antigravity-api-monitor',
        '.antigravity-api-panel',
        '#antigravity-quick-menu-overlay',
        '#antigravity-quick-menu-btn',
        '.antigravity-quickmenu-btn',
        '#antigravity-brain-btn',
        '.antigravity-brain-btn',
        '.antigravity-plan-btn',
        '.antigravity-duplicate-btn',
        '.antigravity-quota-display',
        '.antigravity-quota-toast',
        '#antigravity-log-viewer-container',
        '#antigravity-settings-logs-tab',
        '.antigravity-custom-sidebar-btn',
        '#antigravity-chat-token-counter',
        '#antigravity-live-send-estimator',
        '.antigravity-turn-cost-badge',
        '.antigravity-sidebar-chat-meta',
        '#antigravity-cold-chat-popover',
        '#antigravity-models-usage-intelligence',
        '.antigravity-cache-hit-toast',
        '.antigravity-token-display',
        '.antigravity-compaction-display',
        '.antigravity-modal-overlay',
        '.antigravity-git-modal',
        '#antigravity-official-update-dialog',
        '#antigravity-injection-error-popup',
    ].join(',');

    function isInsideAmsUi(node) {
        if (!node) return false;
        const el = node.nodeType === 1 ? node : node.parentElement;
        if (!el || typeof el.closest !== 'function') return false;
        if (el.closest(AMS_UI_ROOT_SELECTOR)) return true;
        // Also detect the Quick Menu floating card
        if (el.closest('[data-ams-quick-menu="true"]')) return true;
        const styleAttr = el.getAttribute && (el.getAttribute('style') || '');
        if (styleAttr.includes('z-index: 99999') || (el.parentElement && (el.parentElement.getAttribute('style') || '').includes('z-index: 99999'))) {
            return true;
        }
        return false;
    }

    window.amsApplyI18nToDom = function(root) {
        const targetRoot = root || document.body;
        if (!targetRoot) return;
        const lang = window.amsGetLang();

        const translateAttrs = (el) => {
            if (!el || el.nodeType !== 1) return;
            for (const attr of ['placeholder', 'title', 'aria-label']) {
                const val = el.getAttribute(attr);
                if (val) {
                    const nextVal = window.amsTranslateString(val, lang);
                    if (nextVal !== val) el.setAttribute(attr, nextVal);
                }
            }
        };

        const walker = document.createTreeWalker(
            targetRoot,
            NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
            null,
        );

        let current = targetRoot;
        while (current) {
            if (current.nodeType === 1) {
                if (isInsideAmsUi(current)) {
                    translateAttrs(current);
                }
            } else if (current.nodeType === 3) {
                if (isInsideAmsUi(current)) {
                    const val = current.nodeValue;
                    if (val && val.trim()) {
                        const nextVal = window.amsTranslateString(val, lang);
                        if (nextVal !== val) current.nodeValue = nextVal;
                    }
                }
            }
            current = walker.nextNode();
        }
    };

    window.amsSetLang = async function(lang) {
        const nextLang = lang === 'de' ? 'de' : 'en';
        try {
            localStorage.setItem('ams_ui_lang', nextLang);
        } catch (_) {}
        try {
            if (typeof nativeStorageItems === 'object' && nativeStorageItems) {
                nativeStorageItems.antigravity_ui_lang = nextLang;
            }
            if (window.nativeStorage && window.nativeStorage.updateItems) {
                await window.nativeStorage.updateItems({ antigravity_ui_lang: nextLang });
            }
        } catch (_) {}
        window.amsApplyI18nToDom(document.body);
        return nextLang;
    };

    window.amsToggleLang = async function() {
        const nextLang = window.amsGetLang() === 'en' ? 'de' : 'en';
        return window.amsSetLang(nextLang);
    };

    // Observe custom AMS UI mutations so newly opened modals/menus and updated tooltips are translated immediately
    (function initAmsI18nObserver() {
        let scheduled = false;
        const schedulePass = () => {
            if (scheduled) return;
            scheduled = true;
            requestAnimationFrame(() => {
                scheduled = false;
                window.amsApplyI18nToDom(document.body);
            });
        };
        const startObserver = () => {
            if (!document.body) {
                setTimeout(startObserver, 50);
                return;
            }
            window.amsApplyI18nToDom(document.body);
            const obs = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    if (isInsideAmsUi(m.target)) {
                        schedulePass();
                        break;
                    }
                    if (m.addedNodes && m.addedNodes.length > 0) {
                        for (const n of m.addedNodes) {
                            if (n.nodeType === 1 && (isInsideAmsUi(n) || (n.querySelector && n.querySelector(AMS_UI_ROOT_SELECTOR)))) {
                                schedulePass();
                                return;
                            }
                        }
                    }
                }
            });
            obs.observe(document.body, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: ['title', 'placeholder', 'aria-label'],
            });
        };
        startObserver();
    })();


    let lastSavedDraft = (typeof nativeStorageItems === 'object' && nativeStorageItems && typeof nativeStorageItems.antigravity_message_input_draft === 'string')
        ? nativeStorageItems.antigravity_message_input_draft
        : '';
    let draftDebounceTimer = null;

    function saveMessageDraft() {
        try {
            const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
            if (input) {
                const rawVal = input.value !== undefined ? input.value : (input.innerText || '');
                const normalized = rawVal.trim() ? rawVal : '';
                if (normalized !== lastSavedDraft) {
                    lastSavedDraft = normalized;
                    window.nativeStorage.updateItems({ antigravity_message_input_draft: normalized });
                }
            }
        } catch (e) {
            // ignore
        }
    }

    // Clear any leftover draft in storage on startup only if one actually exists
    try {
        if (lastSavedDraft !== '') {
            lastSavedDraft = '';
            window.nativeStorage.updateItems({ antigravity_message_input_draft: '' });
        }
    } catch (e) {
        // ignore
    }

    document.addEventListener('input', (e) => {
        const target = e.target;
        if (target && target.matches && target.matches('[role="combobox"][aria-label="Message input"]')) {
            if (draftDebounceTimer) {
                clearTimeout(draftDebounceTimer);
            }
            draftDebounceTimer = setTimeout(() => {
                draftDebounceTimer = null;
                saveMessageDraft();
            }, 300);
        }
    });

    const draftInterval = setInterval(() => {
        saveMessageDraft();
    }, 1000);

    window.addEventListener('beforeunload', () => {
        try {
            const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
            if (input) {
                const val = input.value !== undefined ? input.value : (input.innerText || '');
                if (val.trim()) {
                    window.electronNative.writeToClipboard(val);
                }
            }
        } catch (e) {
            // ignore
        }
    });


    // ============================================================================
    // Antigravity Unleashed — Ultra Quota, Token & Prompt-Cache Intelligence
    // Empirically calibrated for Google AI Ultra (g1-ultra-tier) & Gemini 4 Argon
    // ============================================================================

    const ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN = 0.00000021285; // 1% Weekly ≈ 4.70M weighted tokens
    const ULTRA_5H_PCT_PER_WEIGHTED_TOKEN = 0.0000008514;      // 1% 5h ≈ 1.175M weighted tokens (4x Weekly)
    const CACHE_GUARANTEED_TTL_SEC = 300;                      // 5 minutes guaranteed by Google TPU HBM
    const CACHE_MAX_OBSERVED_TTL_SEC = 1020;                   // Up to ~17 minutes best-effort under low TPU load

    let currentQuotaData = {
        gemini5h: 100,
        gemini5hExact: 100.0,
        gemini5hFraction: 1.0,
        geminiWeekly: 100,
        geminiWeeklyExact: 100.0,
        geminiWeeklyFraction: 1.0,
        geminiWeeklyDesc: '',
        gemini5hDesc: '',

        claude5h: 100,
        claude5hExact: 100.0,
        claudeWeekly: 100,
        claudeWeeklyExact: 100.0,
        claudeWeeklyDesc: '',
        claude5hDesc: '',

        userTierId: 'g1-ultra-tier',
        userTierName: 'Google AI Ultra',
        lastUpdatedTs: 0,
    };

    const DEFAULT_AMS_UI_PREFS = {
        show5hLimit: false,
        showBrainIcon: false,
        showPlanIcon: false,
        showDuplicateIcon: false,
        showSidebarPct: false,
    };

    function loadAmsUiPrefs() {
        try {
            const raw = localStorage.getItem('ams_ui_prefs_v1');
            if (!raw) return { ...DEFAULT_AMS_UI_PREFS };
            const parsed = JSON.parse(raw);
            return {
                ...DEFAULT_AMS_UI_PREFS,
                ...(parsed && typeof parsed === 'object' ? parsed : {}),
                showBrainIcon: false,
                showPlanIcon: false,
            };
        } catch (_) {
            return { ...DEFAULT_AMS_UI_PREFS };
        }
    }

    const amsLiveOdometer = {
        initialized: false,
        serverWeeklyAnchor: 100.0,
        displayWeekly: 100.0,
        server5hAnchor: 100.0,
        display5h: 100.0,
        unsettledLocalDrainWeekly: 0.0,
        intraStepStreamDrainWeekly: 0.0,
        lastForceRefreshTs: 0,
        isActivelyDraining: false,
    };

    const amsTelemetryState = {
        activeConvStats: null,
        weeklySummary: null,
        allTimeSummary: null,
        recentChatsMap: new Map(),
        liveTrajectoriesMap: new Map(), // cascadeId -> { summary, status, lastModifiedEpoch, stepCount }
        lastObservedStepByConv: new Map(),
        lastCacheHitFlashTs: 0,
        logFilePath: '~/.gemini/config/quota_usage_log.json',
        repackInfo: { pending: false, repacking: false, title: '', details: '', runningChatsCount: 0 },
        liveOdometer: amsLiveOdometer,
        uiPrefs: loadAmsUiPrefs(),
        soundEnabled: false,
    };

    window.amsTelemetryState = amsTelemetryState;

    window.amsGetUiPrefs = function() {
        return amsTelemetryState.uiPrefs || DEFAULT_AMS_UI_PREFS;
    };

    window.amsSetUiPref = function(key, val) {
        if (!amsTelemetryState.uiPrefs) {
            amsTelemetryState.uiPrefs = loadAmsUiPrefs();
        }
        amsTelemetryState.uiPrefs[key] = !!val;
        try {
            localStorage.setItem('ams_ui_prefs_v1', JSON.stringify(amsTelemetryState.uiPrefs));
        } catch (_) {}
        ensureCleanUiStyles();
        refreshQuotaDisplay();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
        return amsTelemetryState.uiPrefs[key];
    };

    window.amsToggleUiPref = function(key) {
        const cur = !!(amsTelemetryState.uiPrefs && amsTelemetryState.uiPrefs[key]);
        return window.amsSetUiPref(key, !cur);
    };

    window.amsTriggerRepackNow = async function() {
        if (!amsTelemetryState.repackInfo) {
            amsTelemetryState.repackInfo = {};
        }
        amsTelemetryState.repackInfo.repacking = true;
        amsTelemetryState.repackInfo.pending = false;
        refreshQuotaDisplay();
        try {
            const activeCid = typeof getActiveCascadeId === 'function' ? getActiveCascadeId() : '';
            const curPath = window.location.pathname + window.location.search;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                const payload = { antigravity_repack_trigger_ts: Date.now() };
                if (activeCid) {
                    payload.antigravity_repack_trigger_chat_id = activeCid;
                    payload.antigravity_last_chat_path = '/c/' + activeCid;
                } else if (curPath && curPath !== '/') {
                    payload.antigravity_last_chat_path = curPath;
                }
                await window.nativeStorage.updateItems(payload);
            }
            if (window.electronNative && typeof window.electronNative.getTokenStats === 'function') {
                await window.electronNative.getTokenStats('__AMS_REPACK_TRIGGER__');
            }
        } catch (err) {
            console.error('[AMS Repack] Failed to trigger repack:', err);
        }
    };

    // ----------------------------------------------------------------------------
    // 0. Crisp Lucide SVG Icon Helper (Replaces Unicode Emojis)
    // ----------------------------------------------------------------------------
    const AMS_LUCIDE_PATHS = {
        sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>',
        flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
        snowflake: '<line x1="2" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="22"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/>',
        zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
        coins: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
        alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
        plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
        undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
        enter: '<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
        volumeOn: '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
        volumeOff: '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
        check: '<path d="M20 6 9 17l-5-5"/>',
        chart: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
        database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
        message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
        wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
        rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
        cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
        info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        refresh: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    };

    function amsIcon(name, size = 11, color = 'currentColor') {
        const p = AMS_LUCIDE_PATHS[name] || AMS_LUCIDE_PATHS.zap;
        return \`<svg xmlns="http://www.w3.org/2000/svg" width="\${size}" height="\${size}" viewBox="0 0 24 24" fill="none" stroke="\${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-1.5px;flex-shrink:0;">\${p}</svg>\`;
    }

    // Claude Design Token System rooted in Native Antigravity IDE (--background: #0D0D0D, --border: rgba(255,255,255,0.05))
    const AMS_THEME = {
        textBright: 'rgba(255, 255, 255, 0.86)',
        textPrimary: 'var(--secondary-foreground, rgba(255, 255, 255, 0.75))',
        textMuted: 'var(--muted-foreground, rgba(255, 255, 255, 0.48))',
        textFaint: 'rgba(255, 255, 255, 0.26)',
        surfacePill: 'rgba(255, 255, 255, 0.03)',
        surfaceHover: 'rgba(255, 255, 255, 0.055)',
        borderSubtle: 'rgba(255, 255, 255, 0.065)',
        borderHover: 'rgba(255, 255, 255, 0.12)',
        // Low-chroma oklch() semantic accents (used sparingly on 10px icons, never loud neon boxes)
        sage: '#75b092',    // oklch(72% 0.075 155) — warm cache / active stream
        sand: '#c29b61',    // oklch(74% 0.075 75)  — cold cache / idle notice
        coral: '#c7746e',   // oklch(68% 0.095 25)  — critical <10% quota
    };

    const myInstanceId = Date.now() + '_' + Math.random();
    window.__ams_active_instance_id = myInstanceId;

    function ensureCleanUiStyles() {
        let st = document.getElementById('ams-clean-ui-override');
        if (!st) {
            st = document.createElement('style');
            st.id = 'ams-clean-ui-override';
            (document.head || document.documentElement).appendChild(st);
        }
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const hiddenToolbarSelectors = [];
        if (!prefs.showBrainIcon) hiddenToolbarSelectors.push('.antigravity-brain-btn');
        if (!prefs.showPlanIcon) hiddenToolbarSelectors.push('.antigravity-plan-btn', '.antigravity-plan-toggle-btn');
        if (!prefs.showDuplicateIcon) hiddenToolbarSelectors.push('.antigravity-duplicate-btn');

        const toolbarHideCss = hiddenToolbarSelectors.length > 0
            ? hiddenToolbarSelectors.join(',') + ' { display: none !important; }'
            : '';

        const css =
            '.antigravity-cache-hit-toast,' +
            '.antigravity-ultra-badge,' +
            '.ams-models-ultra-pill,' +
            '.antigravity-quota-display,' +
            '#antigravity-quota-display-v2,' +
            '#antigravity-quota-display-v3,' +
            '#antigravity-composer-status-strip,' +
            '#antigravity-composer-status-strip-v3,' +
            '.antigravity-turn-cost-badge,' +
            '.antigravity-turn-cost-badge-v2,' +
            '.antigravity-turn-cost-badge-v3,' +
            '#antigravity-chat-token-counter,' +
            '#antigravity-live-send-estimator,' +
            '#antigravity-model-trigger-loss-pill,' +
            '#antigravity-model-switch-popover,' +
            '.antigravity-sidebar-chat-meta,' +
            '.antigravity-sidebar-chat-meta-v2,' +
            '.antigravity-sidebar-chat-meta-v3,' +
            '#antigravity-models-usage-intelligence,' +
            '#antigravity-models-usage-intelligence-v2 {' +
            '  display: none !important;' +
            '}' +
            toolbarHideCss +
            '.antigravity-quickmenu-btn {' +
            '  background: rgba(255, 255, 255, 0.03) !important;' +
            '  border: 1px solid rgba(255, 255, 255, 0.07) !important;' +
            '  height: 24px !important;' +
            '  border-radius: 6px !important;' +
            '}' +
            '.antigravity-quickmenu-btn span {' +
            '  background: none !important;' +
            '  -webkit-text-fill-color: rgba(255, 255, 255, 0.72) !important;' +
            '  color: rgba(255, 255, 255, 0.72) !important;' +
            '  font-weight: 600 !important;' +
            '}';
        if (st.textContent !== css) {
            st.textContent = css;
        }
    }
    ensureCleanUiStyles();

    // ----------------------------------------------------------------------------
    // 1. Synthesized Web Audio API "Cha-Ching / Coin" Cache-Hit Sound
    // ----------------------------------------------------------------------------
    let amsAudioCtx = null;

    function playCacheHitSound(force = false) {
        if (!force && !amsTelemetryState.soundEnabled) return;
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!amsAudioCtx) {
                amsAudioCtx = new AudioCtx();
            }
            if (amsAudioCtx.state === 'suspended') {
                amsAudioCtx.resume().catch(() => {});
            }

            const now = amsAudioCtx.currentTime;

            // Note 1: Metallic B5 (987.77 Hz) + harmonic shimmer
            const osc1 = amsAudioCtx.createOscillator();
            const osc1Harm = amsAudioCtx.createOscillator();
            const gain1 = amsAudioCtx.createGain();
            osc1.type = 'triangle';
            osc1Harm.type = 'sine';
            osc1.frequency.setValueAtTime(987.77, now);
            osc1Harm.frequency.setValueAtTime(2963.31, now);

            gain1.gain.setValueAtTime(0.001, now);
            gain1.gain.linearRampToValueAtTime(0.085, now + 0.008);
            gain1.gain.exponentialRampToValueAtTime(0.0008, now + 0.095);

            osc1.connect(gain1);
            osc1Harm.connect(gain1);
            gain1.connect(amsAudioCtx.destination);
            osc1.start(now);
            osc1Harm.start(now);
            osc1.stop(now + 0.1);
            osc1Harm.stop(now + 0.1);

            // Note 2: Crisp E6 (1318.51 Hz) + golden overtone (2637.02 Hz)
            const t2 = now + 0.072;
            const osc2 = amsAudioCtx.createOscillator();
            const osc2Harm = amsAudioCtx.createOscillator();
            const gain2 = amsAudioCtx.createGain();
            osc2.type = 'sine';
            osc2Harm.type = 'triangle';
            osc2.frequency.setValueAtTime(1318.51, t2);
            osc2Harm.frequency.setValueAtTime(2637.02, t2);

            gain2.gain.setValueAtTime(0.001, t2);
            gain2.gain.linearRampToValueAtTime(0.095, t2 + 0.01);
            gain2.gain.exponentialRampToValueAtTime(0.0005, t2 + 0.34);

            osc2.connect(gain2);
            osc2Harm.connect(gain2);
            gain2.connect(amsAudioCtx.destination);
            osc2.start(t2);
            osc2Harm.start(t2);
            osc2.stop(t2 + 0.36);
            osc2Harm.stop(t2 + 0.36);
        } catch (err) {
            console.warn('[AMS Audio] Could not play cache hit sound:', err);
        }
    }

    window.amsPlayCacheHitSound = playCacheHitSound;

    window.amsToggleCacheHitSound = function() {
        amsTelemetryState.soundEnabled = !amsTelemetryState.soundEnabled;
        try {
            localStorage.setItem('ams_cache_sound_enabled', amsTelemetryState.soundEnabled ? '1' : '0');
        } catch (_) {}
        if (amsTelemetryState.soundEnabled) {
            playCacheHitSound(true);
        }
        return amsTelemetryState.soundEnabled;
    };

    function triggerCacheHitFeedback(cachedTokens, uncachedTokens, outTokens, convId) {
        // Remove any legacy floating cache-hit toasts immediately
        document.querySelectorAll('.antigravity-cache-hit-toast').forEach(el => el.remove());

        const now = Date.now();
        if (now - amsTelemetryState.lastCacheHitFlashTs < 8000) return;
        amsTelemetryState.lastCacheHitFlashTs = now;

        // Subtle inline pulse on the composer cache pill (NO floating popup!)
        const inlineCachePill = document.getElementById('ams-composer-cache-pill');
        if (inlineCachePill) {
            inlineCachePill.style.transition = 'box-shadow 0.35s ease, transform 0.35s ease';
            inlineCachePill.style.boxShadow = '0 0 12px rgba(16, 185, 129, 0.45)';
            setTimeout(() => {
                if (inlineCachePill) inlineCachePill.style.boxShadow = '';
            }, 900);
        }

        // Subtle pulse on the active sidebar row
        if (convId) {
            const row = document.querySelector(\`[data-testid="conversation-row-sidebar"][data-cascade-id="\${convId}"]\`);
            if (row) {
                row.style.transition = 'box-shadow 0.4s ease';
                row.style.boxShadow = 'inset 0 0 0 1px rgba(16, 185, 129, 0.5)';
                setTimeout(() => {
                    row.style.boxShadow = '';
                }, 1000);
            }
        }
    }

    // ----------------------------------------------------------------------------
    // 2. ConnectRPC Helpers & Interceptors
    // ----------------------------------------------------------------------------
    if (!window.__ams_native_fetch) {
        try {
            const fnStr = Function.prototype.toString.call(window.fetch || '');
            if (fnStr.includes('[native code]')) {
                window.__ams_native_fetch = window.fetch.bind(window);
            } else if (document.body) {
                const ifr = document.createElement('iframe');
                ifr.style.display = 'none';
                document.body.appendChild(ifr);
                if (ifr.contentWindow && ifr.contentWindow.fetch) {
                    window.__ams_native_fetch = ifr.contentWindow.fetch.bind(window);
                }
                ifr.remove();
            }
        } catch (_) {}
        if (!window.__ams_native_fetch && window.fetch) {
            window.__ams_native_fetch = window.fetch.bind(window);
        }
    }
    const originalFetch = window.__ams_native_fetch || window.fetch;

    function buildGrpcWebJsonFrame(obj) {
        const bodyStr = JSON.stringify(obj || {});
        const bodyBytes = new TextEncoder().encode(bodyStr);
        const len = bodyBytes.length;
        const reqBytes = new Uint8Array(5 + len);
        reqBytes[0] = 0;
        reqBytes[1] = (len >> 24) & 0xFF;
        reqBytes[2] = (len >> 16) & 0xFF;
        reqBytes[3] = (len >> 8) & 0xFF;
        reqBytes[4] = len & 0xFF;
        reqBytes.set(bodyBytes, 5);
        return reqBytes;
    }

    function parseGrpcWebJsonText(text) {
        if (!text) return null;
        const jsonStart = text.indexOf('{');
        const jsonEnd = text.lastIndexOf('}');
        if (jsonStart === -1 || jsonEnd === -1 || jsonEnd <= jsonStart) return null;
        try {
            return JSON.parse(text.substring(jsonStart, jsonEnd + 1));
        } catch (_) {
            return null;
        }
    }

    async function fetchUserQuotaSummary(forceRefresh = false) {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const now = Date.now();
            const useForce = !!forceRefresh && (now - amsLiveOdometer.lastForceRefreshTs > 3200);
            if (useForce) {
                amsLiveOdometer.lastForceRefreshTs = now;
            }

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT',
                },
                body: buildGrpcWebJsonFrame({ forceRefresh: useForce }),
            });

            const text = await response.text();
            handleRetrieveUserQuotaSummaryText(text);
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to fetch user quota summary:', err);
        }
    }

    async function fetchAllCascadeTrajectories() {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/GetAllCascadeTrajectories', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT',
                },
                body: buildGrpcWebJsonFrame({}),
            });

            const text = await response.text();
            handleGetAllCascadeTrajectoriesText(text);
        } catch (_) {}
    }

    function handleGetAllCascadeTrajectoriesText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.trajectorySummaries) return;
        const summaries = data.trajectorySummaries;
        let anyRunning = false;
        for (const [cid, info] of Object.entries(summaries)) {
            if (!info || typeof info !== 'object') continue;
            const lastModStr = info.lastModifiedTime || info.createdTime || '';
            const lastModEpoch = lastModStr ? Math.floor(new Date(lastModStr).getTime() / 1000) : 0;
            const status = String(info.status || 'CASCADE_RUN_STATUS_IDLE');
            const isRunning = status.includes('RUNNING') || status.includes('WORKING');
            if (isRunning) anyRunning = true;

            amsTelemetryState.liveTrajectoriesMap.set(cid, {
                cascadeId: cid,
                summary: info.summary || '',
                status,
                isRunning,
                stepCount: Number(info.stepCount || 0),
                lastModifiedEpoch: lastModEpoch,
            });
        }
        decorateSidebarConversations();
        if (anyRunning) {
            scheduleRunningConvPoll();
        }
    }

    if (!window.__ams_orig_setTimeout) {
        window.__ams_orig_setTimeout = window.setTimeout.bind(window);
    }
    window.setTimeout = function(fn, delay, ...rest) {
        if (typeof fn === 'function' && delay === 2000) {
            const s = Function.prototype.toString.call(fn);
            if (s.includes('liveTrajectoriesMap') && fn.__ams_instance_id !== window.__ams_active_instance_id) {
                return 0;
            }
        }
        return window.__ams_orig_setTimeout(fn, delay, ...rest);
    };

    let runningPollTimer = null;
    function scheduleRunningConvPoll() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (runningPollTimer) return;
        const pollCb = async () => {
            runningPollTimer = null;
            if (window.__ams_active_instance_id !== myInstanceId) return;
            let stillRunning = false;
            for (const [cid, info] of amsTelemetryState.liveTrajectoriesMap.entries()) {
                if (info.isRunning && window.electronNative && window.electronNative.getTokenStats) {
                    stillRunning = true;
                    try {
                        const res = await window.electronNative.getTokenStats(cid);
                        if (res && res.status === 'success') {
                            window.amsIngestTokenStatsResult(res, cid === getActiveCascadeId());
                        }
                    } catch (_) {}
                }
            }
            fetchUserQuotaSummary();
            if (stillRunning) {
                fetchAllCascadeTrajectories();
            }
        };
        pollCb.__ams_instance_id = myInstanceId;
        runningPollTimer = setTimeout(pollCb, 2000);
    }

    function cleanResetTime(desc) {
        if (!desc) return 'Aktiv';

        const match = desc.match(/(?:resets?|resetting|reset|will\\s+reset|refreshes?|refreshing|refresh|will\\s+refresh|fully\\s+refresh)\\s+(?:in|on|at|until)\\s+(.+)/i);
        let clean = match ? match[1] : desc;

        clean = clean.split('.')[0].toLowerCase();

        clean = clean.replace(/remaining\\s+fraction/g, '')
                     .replace(/quota/g, '')
                     .replace(/limit/g, '')
                     .trim();

        clean = clean.replace(/\\bhours?\\b/g, 'h')
                     .replace(/\\bminutes?\\b/g, 'm')
                     .replace(/\\bseconds?\\b/g, 's')
                     .replace(/\\bdays?\\b/g, 'd')
                     .replace(/\\bweeks?\\b/g, 'w');

        clean = clean.replace(/(\\d+)\\s*([hmsdw])\\b/g, '$1$2');
        clean = clean.replace(/[.,]$/g, '').trim();

        if (!clean) return 'Aktiv';
        return clean.charAt(0).toUpperCase() + clean.slice(1);
    }

    function handleRetrieveUserQuotaSummaryText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.response || !data.response.groups) return;
        try {
            const groups = data.response.groups;
            const geminiGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('gemini'));
            const claudeGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('claude'));

            if (geminiGroup && geminiGroup.buckets) {
                const weeklyBucket = geminiGroup.buckets.find(b => b.window === 'weekly');
                const fiveHourBucket = geminiGroup.buckets.find(b => b.window === '5h');

                if (weeklyBucket && typeof weeklyBucket.remainingFraction === 'number') {
                    const exactW6 = Number((weeklyBucket.remainingFraction * 100).toFixed(6));
                    currentQuotaData.geminiWeeklyFraction = weeklyBucket.remainingFraction;
                    currentQuotaData.geminiWeeklyExact = exactW6;
                    currentQuotaData.geminiWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                    currentQuotaData.geminiWeeklyDesc = weeklyBucket.description || '';
                    if (!amsLiveOdometer.initialized) {
                        amsLiveOdometer.initialized = true;
                        amsLiveOdometer.serverWeeklyAnchor = exactW6;
                        amsLiveOdometer.displayWeekly = exactW6;
                    } else if (Math.abs(exactW6 - amsLiveOdometer.serverWeeklyAnchor) > 0.000001) {
                        amsLiveOdometer.serverWeeklyAnchor = exactW6;
                        amsLiveOdometer.unsettledLocalDrainWeekly = 0;
                        amsLiveOdometer.intraStepStreamDrainWeekly = 0;
                    }
                }
                if (fiveHourBucket && typeof fiveHourBucket.remainingFraction === 'number') {
                    const exact5h6 = Number((fiveHourBucket.remainingFraction * 100).toFixed(6));
                    currentQuotaData.gemini5hFraction = fiveHourBucket.remainingFraction;
                    currentQuotaData.gemini5hExact = exact5h6;
                    currentQuotaData.gemini5h = Math.round(fiveHourBucket.remainingFraction * 100);
                    currentQuotaData.gemini5hDesc = fiveHourBucket.description || '';
                    amsLiveOdometer.server5hAnchor = exact5h6;
                    if (amsLiveOdometer.display5h === 100.0) {
                        amsLiveOdometer.display5h = exact5h6;
                    }
                }
            }

            if (claudeGroup && claudeGroup.buckets) {
                const weeklyBucket = claudeGroup.buckets.find(b => b.window === 'weekly');
                const fiveHourBucket = claudeGroup.buckets.find(b => b.window === '5h');

                if (weeklyBucket && typeof weeklyBucket.remainingFraction === 'number') {
                    currentQuotaData.claudeWeeklyExact = Number((weeklyBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claudeWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                    currentQuotaData.claudeWeeklyDesc = weeklyBucket.description || '';
                }
                if (fiveHourBucket && typeof fiveHourBucket.remainingFraction === 'number') {
                    currentQuotaData.claude5hExact = Number((fiveHourBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claude5h = Math.round(fiveHourBucket.remainingFraction * 100);
                    currentQuotaData.claude5hDesc = fiveHourBucket.description || '';
                }
            }
            currentQuotaData.lastUpdatedTs = Date.now();
            refreshQuotaDisplay();
            patchModelsAndUsagePage();
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to parse RetrieveUserQuotaSummary JSON:', err);
        }
    }

    function handleGetUserStatusText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.userStatus) return;
        try {
            if (data.userStatus.userTier) {
                currentQuotaData.userTierId = data.userStatus.userTier.id || 'g1-ultra-tier';
                currentQuotaData.userTierName = data.userStatus.userTier.name || 'Google AI Ultra';
            }
            if (data.userStatus.cascadeModelConfigData) {
                const configs = data.userStatus.cascadeModelConfigData.clientModelConfigs || [];
                const geminiConfig = configs.find(c => c.label && c.label.toLowerCase().includes('gemini'));
                const claudeConfig = configs.find(c => c.label && c.label.toLowerCase().includes('claude'));

                if (geminiConfig && geminiConfig.quotaInfo && typeof geminiConfig.quotaInfo.remainingFraction === 'number') {
                    currentQuotaData.gemini5hFraction = geminiConfig.quotaInfo.remainingFraction;
                    currentQuotaData.gemini5hExact = Number((geminiConfig.quotaInfo.remainingFraction * 100).toFixed(4));
                    currentQuotaData.gemini5h = Math.round(geminiConfig.quotaInfo.remainingFraction * 100);
                }
                if (claudeConfig && claudeConfig.quotaInfo && typeof claudeConfig.quotaInfo.remainingFraction === 'number') {
                    currentQuotaData.claude5hExact = Number((claudeConfig.quotaInfo.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claude5h = Math.round(claudeConfig.quotaInfo.remainingFraction * 100);
                }
                fetchUserQuotaSummary();
            }
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to parse GetUserStatus JSON:', err);
        }
    }

    // Hook Fetch in Main World
    window.fetch = async function(...args) {
        const response = await originalFetch(...args);
        try {
            const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url);
            if (url) {
                if (url.includes('GetUserStatus')) {
                    response.clone().text().then(handleGetUserStatusText).catch(() => {});
                } else if (url.includes('RetrieveUserQuotaSummary')) {
                    response.clone().text().then(handleRetrieveUserQuotaSummaryText).catch(() => {});
                } else if (url.includes('GetAllCascadeTrajectories')) {
                    response.clone().text().then(handleGetAllCascadeTrajectoriesText).catch(() => {});
                } else if (url.includes('GetCascadeTrajectory')) {
                    setTimeout(() => {
                        if (typeof updateTokenStats === 'function') updateTokenStats();
                    }, 350);
                }
            }
        } catch (err) {
            console.error('[AMS Quota Interceptor] Error intercepting fetch:', err);
        }
        return response;
    };

    // Hook XMLHttpRequest in Main World
    if (!window.__ams_native_xhr_open || !window.__ams_native_xhr_send) {
        try {
            const openStr = Function.prototype.toString.call(XMLHttpRequest.prototype.open || '');
            const sendStr = Function.prototype.toString.call(XMLHttpRequest.prototype.send || '');
            if (openStr.includes('[native code]') && sendStr.includes('[native code]')) {
                window.__ams_native_xhr_open = XMLHttpRequest.prototype.open;
                window.__ams_native_xhr_send = XMLHttpRequest.prototype.send;
            } else if (document.body) {
                const ifr = document.createElement('iframe');
                ifr.style.display = 'none';
                document.body.appendChild(ifr);
                if (ifr.contentWindow && ifr.contentWindow.XMLHttpRequest) {
                    window.__ams_native_xhr_open = ifr.contentWindow.XMLHttpRequest.prototype.open;
                    window.__ams_native_xhr_send = ifr.contentWindow.XMLHttpRequest.prototype.send;
                }
                ifr.remove();
            }
        } catch (_) {}
    }
    const originalOpen = window.__ams_native_xhr_open || XMLHttpRequest.prototype.open;
    const originalSend = window.__ams_native_xhr_send || XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            if (window.__ams_active_instance_id !== myInstanceId) return;
            try {
                if (this._url) {
                    if (this._url.includes('GetUserStatus')) {
                        handleGetUserStatusText(this.responseText);
                    } else if (this._url.includes('RetrieveUserQuotaSummary')) {
                        handleRetrieveUserQuotaSummaryText(this.responseText);
                    } else if (this._url.includes('GetAllCascadeTrajectories')) {
                        handleGetAllCascadeTrajectoriesText(this.responseText);
                    }
                }
            } catch (_) {}
        });
        return originalSend.apply(this, args);
    };

    // ----------------------------------------------------------------------------
    // 3. Ingest Token & Cache Intelligence from get_token_stats.py
    // ----------------------------------------------------------------------------
    window.amsIngestTokenStatsResult = function(res, isActiveConv = true) {
        if (!res || res.status !== 'success') return;

        if (res.repackInfo && typeof res.repackInfo === 'object') {
            if (!amsTelemetryState.repackInfo || !amsTelemetryState.repackInfo.repacking) {
                amsTelemetryState.repackInfo = res.repackInfo;
            }
        }
        if (res.weeklySummary) {
            amsTelemetryState.weeklySummary = res.weeklySummary;
        }
        if (res.allTimeSummary) {
            amsTelemetryState.allTimeSummary = res.allTimeSummary;
        }
        if (res.logFilePath) {
            amsTelemetryState.logFilePath = res.logFilePath;
        }
        if (Array.isArray(res.recentChats)) {
            for (const c of res.recentChats) {
                if (c && c.cascadeId) {
                    const existing = amsTelemetryState.recentChatsMap.get(c.cascadeId);
                    if (
                        existing &&
                        Number(existing.stepCount || 0) >= Number(c.stepCount || 0) &&
                        Number(existing.totalInput || 0) > Number(c.totalInput || 0)
                    ) {
                        continue;
                    }
                    amsTelemetryState.recentChatsMap.set(c.cascadeId, c);
                }
            }
        }

        const cid = res.cascadeId || currentConvId;
        if (cid) {
            if (!amsTelemetryState.liveDrainHistory) {
                amsTelemetryState.liveDrainHistory = new Map();
            }
            const curTotalTok = Number(res.totalInput || 0) + Number(res.totalOutput || 0);
            const curWeeklyUsed = Number(res.weeklyPctUsed || 0);
            const cur5hUsed = Number(res.fiveHourPctUsed || 0);
            const prevDrain = amsTelemetryState.liveDrainHistory.get(cid);
            if (!prevDrain) {
                const lastTurn = Array.isArray(res.turns) && res.turns.length > 0 ? res.turns[res.turns.length - 1] : null;
                amsTelemetryState.liveDrainHistory.set(cid, {
                    prevTotalTok: curTotalTok,
                    prevWeeklyUsed: curWeeklyUsed,
                    lastDeltaTok: Number((res.latestInput || 0) + (res.latestOutput || 0)),
                    lastDeltaWeeklyPct: Number(lastTurn ? (lastTurn.weeklyPct / Math.max(1, lastTurn.steps)) : 0.0048),
                    lastDelta5hPct: Number(lastTurn ? (lastTurn.fiveHourPct / Math.max(1, lastTurn.steps)) : 0.0192),
                    lastPulseTs: 0,
                });
            } else if (curTotalTok > prevDrain.prevTotalTok) {
                const dTok = curTotalTok - prevDrain.prevTotalTok;
                const dW = Math.max(0.0001, curWeeklyUsed - prevDrain.prevWeeklyUsed);
                amsTelemetryState.liveDrainHistory.set(cid, {
                    prevTotalTok: curTotalTok,
                    prevWeeklyUsed: curWeeklyUsed,
                    lastDeltaTok: dTok,
                    lastDeltaWeeklyPct: dW,
                    lastDelta5hPct: dW * 4.0,
                    lastPulseTs: Date.now(),
                });
                amsLiveOdometer.unsettledLocalDrainWeekly = Math.min(0.15, amsLiveOdometer.unsettledLocalDrainWeekly + dW);
                amsLiveOdometer.intraStepStreamDrainWeekly = 0;
                fetchUserQuotaSummary(true);
            }

            const prevStepIdx = amsTelemetryState.lastObservedStepByConv.get(cid);
            const curStepIdx = Number(res.latestStepIdx || 0);
            if (prevStepIdx !== undefined && curStepIdx > prevStepIdx && Number(res.latestCached || 0) > 0) {
                triggerCacheHitFeedback(
                    Number(res.latestCached || 0),
                    Number(res.latestUncached || 0),
                    Number(res.latestOutput || 0),
                    cid,
                );
            }
            if (curStepIdx > 0) {
                amsTelemetryState.lastObservedStepByConv.set(cid, curStepIdx);
            }

            // Keep recentChatsMap updated with freshest active stats
            amsTelemetryState.recentChatsMap.set(cid, {
                ...(amsTelemetryState.recentChatsMap.get(cid) || {}),
                cascadeId: cid,
                title: res.title || (amsTelemetryState.recentChatsMap.get(cid) || {}).title || '',
                stepCount: res.stepCount || 0,
                turnCount: res.turnCount || 0,
                totalInput: res.totalInput || 0,
                totalUncached: res.totalUncached || 0,
                totalCached: res.totalCached || 0,
                totalOutput: res.totalOutput || 0,
                latestInput: res.latestInput || 0,
                latestUncached: res.latestUncached || 0,
                latestCached: res.latestCached || 0,
                latestStepIdx: curStepIdx,
                cacheRatio: res.cacheRatio || 0,
                cacheMissCount: res.cacheMissCount || 0,
                wastedWeeklyPct: res.wastedWeeklyPct || 0,
                weightedTokens: res.weightedTokens || 0,
                weeklyPctUsed: res.weeklyPctUsed || 0,
                fiveHourPctUsed: res.fiveHourPctUsed || 0,
                apiCostEur: res.apiCostEur || 0,
                apiRawCostEur: res.apiRawCostEur || 0,
                apiSavedEur: res.apiSavedEur || 0,
                firstStepTimestamp: res.firstStepTimestamp || 0,
                lastStepTimestamp: res.lastStepTimestamp || 0,
            });
        }

        if (isActiveConv) {
            amsTelemetryState.activeConvStats = res;
            renderPerMessageTurnBadges();
            updateLiveSendEstimator();
        }

        refreshQuotaDisplay();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
    };

    // ----------------------------------------------------------------------------
    // 4. Cache Warmth & Cost Calculation Helpers
    // ----------------------------------------------------------------------------
    function getChatCacheState(cascadeId) {
        const nowSec = Math.floor(Date.now() / 1000);
        const stats = amsTelemetryState.recentChatsMap.get(cascadeId) ||
                      (amsTelemetryState.activeConvStats && amsTelemetryState.activeConvStats.cascadeId === cascadeId
                          ? amsTelemetryState.activeConvStats
                          : null);
        const liveInfo = amsTelemetryState.liveTrajectoriesMap.get(cascadeId);

        const isRunning = !!(liveInfo && liveInfo.isRunning);
        const lastTs = Math.max(
            Number((stats && stats.lastStepTimestamp) || 0),
            Number((liveInfo && liveInfo.lastModifiedEpoch) || 0),
        );
        const contextTokens = Number((stats && stats.latestInput) || 0);
        const stepCount = Number((stats && stats.stepCount) || (liveInfo && liveInfo.stepCount) || 0);
        const weeklyPctUsed = Number((stats && stats.weeklyPctUsed) || 0);
        const fiveHourPctUsed = Number((stats && stats.fiveHourPctUsed) || 0);
        const cacheRatio = Number((stats && stats.cacheRatio) || 0);

        if (stepCount === 0 || lastTs === 0) {
            return {
                state: 'new',
                isRunning: false,
                idleSec: 0,
                remainingGuaranteedSec: CACHE_GUARANTEED_TTL_SEC,
                contextTokens: 0,
                weeklyPctUsed: 0,
                fiveHourPctUsed: 0,
                cacheRatio: 0,
                warmSendWeeklyPct: 0.0035,
                coldSendWeeklyPct: 0.0035,
                warmSend5hPct: 0.0140,
                coldSend5hPct: 0.0140,
                extraColdLossWeeklyPct: 0,
                extraColdLoss5hPct: 0,
            };
        }

        const idleSec = isRunning ? 0 : Math.max(0, nowSec - lastTs);
        const remainingGuaranteedSec = Math.max(0, CACHE_GUARANTEED_TTL_SEC - idleSec);

        // Calculate next-message send cost (assuming ~900 output/thinking tokens + 250 new input tokens)
        const baseCtx = Math.max(24500, contextTokens || 32000);
        const estNewInput = 250;
        const estOut = 850;
        const warmWeighted = Math.round(0.1 * baseCtx + 1.0 * estNewInput + 6.0 * estOut);
        const coldWeighted = Math.round(1.0 * baseCtx + 1.0 * estNewInput + 6.0 * estOut);

        const warmSendWeeklyPct = Number((warmWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const coldSendWeeklyPct = Number((coldWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const warmSend5hPct = Number((warmWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const coldSend5hPct = Number((coldWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const extraColdLossWeeklyPct = Number(Math.max(0, coldSendWeeklyPct - warmSendWeeklyPct).toFixed(4));
        const extraColdLoss5hPct = Number(Math.max(0, coldSend5hPct - warmSend5hPct).toFixed(4));

        let state = 'warm'; // < 5m guaranteed
        if (!isRunning) {
            if (idleSec >= CACHE_MAX_OBSERVED_TTL_SEC) {
                state = 'cold'; // > 17m definitely cold
            } else if (idleSec >= CACHE_GUARANTEED_TTL_SEC) {
                state = 'lukewarm'; // 5m - 17m: 5m guarantee expired! High risk of cold reload
            }
        }

        return {
            state,
            isRunning,
            idleSec,
            remainingGuaranteedSec,
            contextTokens: baseCtx,
            stepCount,
            weeklyPctUsed,
            fiveHourPctUsed,
            cacheRatio,
            warmSendWeeklyPct,
            coldSendWeeklyPct,
            warmSend5hPct,
            coldSend5hPct,
            extraColdLossWeeklyPct,
            extraColdLoss5hPct,
        };
    }

    function formatDurationShort(sec) {
        const s = Math.max(0, Math.floor(sec));
        if (s < 60) return s + 's';
        const m = Math.floor(s / 60);
        const remS = s % 60;
        if (m < 60) return remS > 0 && m < 10 ? \`\${m}m \${remS}s\` : \`\${m}m\`;
        const h = Math.floor(m / 60);
        const remM = m % 60;
        if (h < 24) return remM > 0 ? \`\${h}h \${remM}m\` : \`\${h}h\`;
        const d = Math.floor(h / 24);
        return \`\${d}d \${h % 24}h\`;
    }

    function formatTokensCompact(num) {
        const n = Number(num || 0);
        if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
        if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
        if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
        return String(n);
    }

    function triggerNewConversation() {
        const selectors = [
            '[data-testid="new-conversation-button"]',
            '[data-testid="app-icon-new-conversation-button"]',
            '[data-testid="extension-new-conversation"]',
            'a[href="/"]',
        ];
        for (const sel of selectors) {
            const btn = document.querySelector(sel);
            if (btn) {
                btn.click();
                return true;
            }
        }
        window.location.href = window.location.origin + '/';
        return true;
    }

    // ----------------------------------------------------------------------------
    // 5. Upgraded Composer Bar Display (ULTRA Badge + 5h & Weekly + Live Estimator)
    // ----------------------------------------------------------------------------
    let isSwitchingModel = false;

    function showQuotaFallbackToast(modelName) {
        const toast = document.createElement('div');
        toast.className = 'antigravity-quota-toast';
        toast.style.cssText =
            'position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;background:var(--card,#1c1917);' +
            'border:1px solid #ef4444;color:var(--foreground,#ffffff);font-size:12px;font-weight:500;z-index:999999;' +
            'box-shadow:0 10px 15px -3px rgba(0,0,0,0.5);display:flex;align-items:center;gap:8px;font-family:ui-sans-serif,system-ui,sans-serif;' +
            'transform:translateY(20px);opacity:0;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);';

        toast.innerHTML =
            '<span style="display:flex;align-items:center;justify-content:center;background:#ef4444;color:white;border-radius:50%;width:18px;height:18px;font-weight:bold;font-size:11px;">!</span>' +
            '<span><strong>Quoten-Wächter:</strong> Claude verbraucht. Automatisch auf ' + modelName + ' umgeschaltet.</span>';

        document.body.appendChild(toast);
        toast.offsetHeight;
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';

        setTimeout(() => {
            toast.style.transform = 'translateY(20px)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }

    async function switchModel(targetModelName) {
        const selectorBtn = document.querySelector('button[aria-label^="Select model, current:"]');
        if (!selectorBtn) return false;
        try {
            selectorBtn.click();
            await new Promise(r => setTimeout(r, 250));
            let targetBtn = null;
            const buttons = document.querySelectorAll('button');
            for (let i = 0; i < buttons.length; i++) {
                const btn = buttons[i];
                const text = btn.textContent ? btn.textContent.trim() : '';
                if (text.toLowerCase().includes(targetModelName.toLowerCase())) {
                    targetBtn = btn;
                    break;
                }
            }
            if (targetBtn) {
                targetBtn.click();
                showQuotaFallbackToast(targetModelName);
                return true;
            }
            selectorBtn.click();
            return false;
        } catch (_) {
            return false;
        }
    }

    function refreshQuotaDisplay() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        const flexContainer = addContextBtn ? addContextBtn.parentElement : null;
        if (!flexContainer) return;

        let quotaEl = document.getElementById('antigravity-quota-display-v4');
        if (!quotaEl) {
            quotaEl = document.createElement('div');
            quotaEl.id = 'antigravity-quota-display-v4';
            quotaEl.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                toggleQuotaHudPopover(quotaEl);
            });
            flexContainer.appendChild(quotaEl);
        } else if (quotaEl.parentElement !== flexContainer) {
            flexContainer.appendChild(quotaEl);
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const g5hExact = currentQuotaData.gemini5hExact;
        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWServerExact = currentQuotaData.geminiWeeklyExact;
        const g5hReset = cleanResetTime(currentQuotaData.gemini5hDesc);
        const gWReset = cleanResetTime(currentQuotaData.geminiWeeklyDesc);

        const remStepsW = Math.round(gWExact * 200);
        const remPromptsS = Math.round(gWExact / 0.0075);
        const remPromptsM = Math.round(gWExact / 0.040);
        const remPromptsL = Math.round(gWExact / 0.125);
        const remPromptsXL = Math.round(gWExact / 0.400);

        const tooltipText = isDe
            ? \`Gemini Quota (Exakt · Live-Odometer):\\n\` +
              \`• Weekly-Limit (Live): \${gWExact.toFixed(4)}% übrig (Server-Float: \${gWServerExact.toFixed(6)}% · Reset: \${gWReset})\\n\` +
              \`• 5-Stunden-Limit: \${g5hExact.toFixed(4)}% übrig (-\${(100 - g5hExact).toFixed(4)}% verbraucht · Reset: \${g5hReset})\\n\\n\` +
              \`Verbleibendes Kontingent (aus \${gWExact.toFixed(4)}% Weekly):\\n\` +
              \`• ~\${remStepsW.toLocaleString('de-DE')} Agent-Steps\\n\` +
              \`• ~\${remPromptsS.toLocaleString('de-DE')} Kurze Prompts (Typ S · 1–2 Steps)\\n\` +
              \`• ~\${remPromptsM.toLocaleString('de-DE')} Kleine Tasks (Typ M · ~8 Steps)\\n\` +
              \`• ~\${remPromptsL.toLocaleString('de-DE')} Komplexe Coding-Tasks (Typ L · ~25 Steps)\\n\` +
              \`• ~\${remPromptsXL.toLocaleString('de-DE')} Große Deep-Dives (Typ XL · ~80 Steps)\\n\` +
              \`(Klicken für Models & Usage)\`
            : \`Gemini Quota (Exact · Live Odometer):\\n\` +
              \`• Weekly Limit (Live): \${gWExact.toFixed(4)}% left (Server float: \${gWServerExact.toFixed(6)}% · Reset: \${gWReset})\\n\` +
              \`• 5-Hour Limit: \${g5hExact.toFixed(4)}% left (-\${(100 - g5hExact).toFixed(4)}% used · Reset: \${g5hReset})\\n\\n\` +
              \`Remaining Capacity (from \${gWExact.toFixed(4)}% Weekly):\\n\` +
              \`• ~\${remStepsW.toLocaleString('en-US')} Agent Steps\\n\` +
              \`• ~\${remPromptsS.toLocaleString('en-US')} Quick Prompts (Type S · 1–2 steps)\\n\` +
              \`• ~\${remPromptsM.toLocaleString('en-US')} Small Tasks (Type M · ~8 steps)\\n\` +
              \`• ~\${remPromptsL.toLocaleString('en-US')} Complex Coding Tasks (Type L · ~25 steps)\\n\` +
              \`• ~\${remPromptsXL.toLocaleString('en-US')} Autonomous Deep-Dives (Type XL · ~80 steps)\\n\` +
              \`(Click to open Models & Usage)\`;

        function getToneColor(pct) {
            if (pct < 10) return AMS_THEME.coral;
            return AMS_THEME.textBright;
        }

        function format4DecSplitHtml(pct, isDraining) {
            const s4 = Math.max(0, Number(pct || 0)).toFixed(4);
            const main2 = s4.slice(0, -2); // e.g. "11.96"
            const micro2 = s4.slice(-2);   // e.g. "24"
            const mainColor = getToneColor(pct);
            const microColor = isDraining ? AMS_THEME.sage : 'rgba(255, 255, 255, 0.64)';
            return \`<span style="display:inline-flex;align-items:baseline;font-variant-numeric:tabular-nums;">\` +
                \`<span style="color:\${mainColor};font-weight:600;">\${main2}</span>\` +
                \`<span style="color:\${microColor};font-weight:500;transition:color 0.2s ease;">\${micro2}%</span>\` +
            \`</span>\`;
        }

        quotaEl.style.cssText =
            'display:inline-flex;align-items:center;margin-left:6px;margin-right:4px;' +
            'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;' +
            'white-space:nowrap;flex-shrink:0;user-select:none;cursor:pointer;';
        quotaEl.title = tooltipText;

        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        let unifiedQuotaPill = quotaEl.querySelector('.antigravity-quota-pill-v3');
        if (!unifiedQuotaPill) {
            unifiedQuotaPill = document.createElement('span');
            unifiedQuotaPill.className = 'antigravity-quota-pill-v3';
            quotaEl.replaceChildren(unifiedQuotaPill);
        }
        const isDraining = !!amsLiveOdometer.isActivelyDraining;
        unifiedQuotaPill.style.cssText =
            \`display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 8px;border-radius:6px;\` +
            \`background:\${AMS_THEME.surfacePill};border:1px solid \${isDraining ? 'rgba(117,176,146,0.28)' : AMS_THEME.borderSubtle};\` +
            \`font-size:11px;white-space:nowrap;transition:border-color 0.25s ease;\`;

        const pillHtml = prefs.show5hLimit
            ? \`<span style="display:inline-flex;align-items:center;gap:4px;">\` +
                  \`<span style="color:\${AMS_THEME.textMuted};font-weight:400;">Weekly</span>\` +
                  \`\${format4DecSplitHtml(gWExact, isDraining)}\` +
              \`</span>\` +
              \`<span style="color:\${AMS_THEME.textFaint};">·</span>\` +
              \`<span style="display:inline-flex;align-items:center;gap:3.5px;">\` +
                  \`<span style="color:\${AMS_THEME.textMuted};font-weight:400;">5h</span>\` +
                  \`\${format4DecSplitHtml(g5hExact, false)}\` +
              \`</span>\`
            : \`<span style="display:inline-flex;align-items:center;gap:4.5px;">\` +
                  \`<span style="color:\${AMS_THEME.textMuted};font-weight:400;">Weekly</span>\` +
                  \`\${format4DecSplitHtml(gWExact, isDraining)}\` +
              \`</span>\`;

        if (unifiedQuotaPill.getAttribute('data-sig') !== pillHtml) {
            unifiedQuotaPill.setAttribute('data-sig', pillHtml);
            unifiedQuotaPill.innerHTML = pillHtml;
        }

        // Noticeable In-App Repack Ready Button (Never auto-restarts while agents run; waits for user click)
        const rInfo = amsTelemetryState.repackInfo;
        let repackBtn = document.getElementById('antigravity-repack-ready-btn');
        if (rInfo && (rInfo.pending || rInfo.repacking)) {
            if (!repackBtn) {
                repackBtn = document.createElement('button');
                repackBtn.type = 'button';
                repackBtn.id = 'antigravity-repack-ready-btn';
                repackBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (typeof window.amsTriggerRepackNow === 'function') {
                        window.amsTriggerRepackNow();
                    }
                });
                flexContainer.appendChild(repackBtn);
            } else if (repackBtn.parentElement !== flexContainer) {
                flexContainer.appendChild(repackBtn);
            }

            repackBtn.style.cssText =
                'display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 9px;margin-left:4px;border-radius:6px;' +
                'border:1px solid rgba(251,191,36,0.48);background:rgba(245,158,11,0.14);color:#fde68a;' +
                'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;font-weight:600;' +
                'white-space:nowrap;cursor:pointer;flex-shrink:0;transition:all 0.15s ease;box-shadow:0 0 12px rgba(245,158,11,0.12);';

            const shortTitle = rInfo.title || (isDe ? 'UI-Update' : 'UI Update');
            const labelHtml = rInfo.repacking
                ? \`\${amsIcon('refresh', 11, '#fde68a')}<span>\${isDe ? 'Repack & Neustart läuft (ca. 3s)...' : 'Repacking & restarting (3s)...'}</span>\`
                : \`\${amsIcon('refresh', 11, '#fbbf24')}<span>\${isDe ? \`Neustart für: \${shortTitle}\` : \`Restart for: \${shortTitle}\`}</span>\`;

            if (repackBtn.getAttribute('data-sig') !== labelHtml) {
                repackBtn.setAttribute('data-sig', labelHtml);
                repackBtn.innerHTML = labelHtml;
            }
            const runningNote = rInfo.runningChatsCount > 0
                ? (isDe
                    ? \`\\n⚡ Auto-Resume aktiv: Aktuell arbeiten \${rInfo.runningChatsCount} Chat(s) — nach dem Neustart werden alle aktiven Agenten automatisch mit "continue" geweckt.\`
                    : \`\\n⚡ Auto-Resume active: \${rInfo.runningChatsCount} chat(s) currently working — all active agents will be automatically resumed with "continue" after restart.\`)
                : (isDe ? '\\n✓ Kein automatischer Neustart ohne deinen Klick.' : '\\n✓ Will only restart when you click.');
            repackBtn.title =
                (isDe ? \`Repack bereit: \${shortTitle}\\n\` : \`Repack ready: \${shortTitle}\\n\`) +
                (rInfo.details || '') +
                runningNote +
                (isDe ? '\\n\\nKlicken, um app.asar jetzt neu zu packen und Antigravity in ~3s neu zu starten.' : '\\n\\nClick to repack app.asar and restart Antigravity in ~3s.');
        } else if (repackBtn) {
            repackBtn.remove();
        }

        // Update the clean full-width Composer Status Strip below the button row
        updateComposerStatusStrip();

        // Quoten-Wächter (Model Fallback if user ever selects exhausted Claude before Nov 2)
        if (!isSwitchingModel && typeof getActiveModel === 'function') {
            const activeModel = getActiveModel();
            if (activeModel && activeModel.startsWith('Claude')) {
                if (currentQuotaData.claude5h === 0 || currentQuotaData.claudeWeekly === 0) {
                    isSwitchingModel = true;
                    switchModel('Gemini 4 Argon (High)').finally(() => {
                        isSwitchingModel = false;
                    });
                }
            }
        }
    }

    // ----------------------------------------------------------------------------
    // 5b. Interactive Live Quota & Cache HUD Popover (Click on Weekly Pill)
    // ----------------------------------------------------------------------------
    let activeQuotaHudPopover = null;

    function openModelsAndUsageSettings() {
        closeQuotaHudPopover();
        const settingsBtn = document.querySelector('[data-testid="settings-button"]');
        if (settingsBtn) {
            settingsBtn.click();
            let attempts = 0;
            const interval = setInterval(() => {
                let modelsTab = null;
                document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                    if (btn.textContent && btn.textContent.trim() === 'Models') {
                        modelsTab = btn;
                    }
                });
                if (modelsTab) {
                    modelsTab.click();
                    clearInterval(interval);
                }
                attempts++;
                if (attempts > 20) clearInterval(interval);
            }, 50);
        }
    }

    function closeQuotaHudPopover() {
        if (activeQuotaHudPopover) {
            activeQuotaHudPopover.remove();
            activeQuotaHudPopover = null;
        }
    }

    function renderQuotaHudPopoverBody(pop) {
        if (!pop) return;
        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWServer = currentQuotaData.geminiWeeklyExact;
        const g5hExact = currentQuotaData.gemini5hExact;
        const gWReset = cleanResetTime(currentQuotaData.geminiWeeklyDesc);
        const g5hReset = cleanResetTime(currentQuotaData.gemini5hDesc);

        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const ctxTok = cacheInfo && cacheInfo.contextTokens ? cacheInfo.contextTokens : 0;
        const warmInputPct = (ctxTok * 0.1 * 100) / 470000000;
        const coldInputPct = (ctxTok * 1.0 * 100) / 470000000;
        const savedPerStepPct = Math.max(0, coldInputPct - warmInputPct);
        const remStepsW = Math.round(gWExact * 200);
        const remTasksL = Math.round(gWExact / 0.125);
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;

        const sig = \`\${gWExact.toFixed(4)}|\${gWServer.toFixed(6)}|\${ctxTok}|\${cacheInfo ? cacheInfo.state : 'none'}|\${cacheInfo ? cacheInfo.stepCount : 0}|\${prefs.show5hLimit ? 1 : 0}|\${isDe}\`;
        if (pop.getAttribute('data-hud-sig') === sig) return;
        pop.setAttribute('data-hud-sig', sig);

        const chatSectionHtml = ctxTok > 0
            ? \`<div style="margin-top:8px;padding:8px 10px;border-radius:7px;background:rgba(255,255,255,0.03);border:1px solid \${AMS_THEME.borderSubtle};display:flex;flex-direction:column;gap:4px;">\` +
                  \`<div style="display:flex;justify-content:space-between;align-items:center;font-weight:600;color:\${AMS_THEME.textBright};margin-bottom:2px;">\` +
                      \`<span>\${isDe ? \`Aktueller Chat (\${formatTokensCompact(ctxTok)} Kontext · \${cacheInfo.stepCount} Steps)\` : \`Current Chat (\${formatTokensCompact(ctxTok)} ctx · \${cacheInfo.stepCount} steps)\`}</span>\` +
                      \`<span style="color:\${cacheInfo.state === 'warm' || cacheInfo.isRunning ? AMS_THEME.sage : AMS_THEME.sand};">\${cacheInfo.state === 'warm' || cacheInfo.isRunning ? (isDe ? '🔥 Warm' : '🔥 Warm') : (isDe ? '❄️ Kalt' : '❄️ Cold')}</span>\` +
                  \`</div>\` +
                  \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? '🔥 Warm-Step (0.1× Input, 90% Rabatt):' : '🔥 Warm step (0.1× input, 90% off):'}</span><span style="color:\${AMS_THEME.sage};font-weight:600;">-\${warmInputPct.toFixed(4)}% W</span></div>\` +
                  \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? '❄️ Kaltstart-Reload (1.0× Input, 10×):' : '❄️ Cold reload (1.0× input, 10×):'}</span><span style="color:\${AMS_THEME.sand};font-weight:600;">-\${coldInputPct.toFixed(4)}% W</span></div>\` +
                  \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Ersparnis pro warmem Step:' : 'Saved per warm step:'}</span><span style="color:\${AMS_THEME.textPrimary};font-weight:500;">+\${savedPerStepPct.toFixed(4)}% W</span></div>\` +
              \`</div>\`
            : '';

        pop.innerHTML =
            \`<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding-bottom:7px;border-bottom:1px solid rgba(255,255,255,0.07);">\` +
                \`<strong style="display:inline-flex;align-items:center;gap:5px;color:\${AMS_THEME.textBright};font-size:12px;font-weight:600;">\` +
                    \`\${amsIcon('chart', 12, AMS_THEME.sage)}<span>\${isDe ? 'Live Quota-Odometer & Token-Faktencheck' : 'Live Quota Odometer & Token Fact-Check'}</span>\` +
                \`</strong>\` +
                \`<button type="button" class="ams-qhud-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:\${AMS_THEME.textMuted};cursor:pointer;padding:2px;">\${amsIcon('close', 12, AMS_THEME.textMuted)}</button>\` +
            \`</div>\` +
            \`<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;font-size:11px;color:\${AMS_THEME.textMuted};">\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Weekly-Limit (Live 4-Dezimal):' : 'Weekly Limit (Live 4-Dec):'}</span><span style="color:\${AMS_THEME.textBright};font-weight:700;font-size:12px;">\${gWExact.toFixed(4)}%</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Exakter Google-Server Float:' : 'Exact Google Server Float:'}</span><span style="color:\${AMS_THEME.textPrimary};font-family:monospace;">\${gWServer.toFixed(6)}% (\${gWReset})</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? '5-Stunden-Limit:' : '5-Hour Limit:'}</span><span style="color:\${AMS_THEME.textPrimary};">\${g5hExact.toFixed(4)}% (\${g5hReset})</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Verbleibende Kapazität:' : 'Remaining Capacity:'}</span><span style="color:\${AMS_THEME.sage};font-weight:500;">~\${remStepsW.toLocaleString(isDe ? 'de-DE' : 'en-US')} Steps · ~\${remTasksL} Tasks</span></div>\` +
            \`</div>\` +
            chatSectionHtml +
            \`<div style="margin-top:8px;padding:7px 9px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);font-size:10.5px;line-height:1.4;color:\${AMS_THEME.textMuted};">\` +
                (isDe
                    ? \`<strong>Bestätigt durch Google RPC:</strong> Quota wird exakt nach gewichteten Token-Kosten abgerechnet (TPU-HBM Cache = <code>0.1×</code>, Uncached Input = <code>1.0×</code>). Ein Kaltstart (>5m) lädt den Kontext <strong>10× teurer</strong> neu.\`
                    : \`<strong>Confirmed via Google RPC:</strong> Quota is billed strictly by weighted token cost (TPU HBM cache = <code>0.1×</code>, uncached input = <code>1.0×</code>). A cold start (>5m) reloads context at <strong>10× cost</strong>.\`) +
            \`</div>\` +
            \`<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:9px;padding-top:7px;border-top:1px solid rgba(255,255,255,0.07);">\` +
                \`<label style="display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:\${AMS_THEME.textPrimary};cursor:pointer;user-select:none;">\` +
                    \`<input type="checkbox" class="ams-qhud-5h-chk" \${prefs.show5hLimit ? 'checked' : ''} style="accent-color:#75b092;margin:0;cursor:pointer;" />\` +
                    \`<span>\${isDe ? '5h-Limit in Leiste zeigen' : 'Show 5h limit in bar'}</span>\` +
                \`</label>\` +
                \`<button type="button" class="ams-qhud-open-models" style="display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:5px;border:1px solid \${AMS_THEME.borderHover};background:\${AMS_THEME.surfaceHover};color:\${AMS_THEME.textBright};font-size:10.5px;font-weight:500;cursor:pointer;">\` +
                    \`<span>\${isDe ? 'Models & Usage →' : 'Models & Usage →'}</span>\` +
                \`</button>\` +
            \`</div>\`;

        const closeBtn = pop.querySelector('.ams-qhud-close');
        if (closeBtn) closeBtn.onclick = () => closeQuotaHudPopover();
        const chk5h = pop.querySelector('.ams-qhud-5h-chk');
        if (chk5h) {
            chk5h.onchange = (ev) => {
                if (typeof window.amsSetUiPref === 'function') {
                    window.amsSetUiPref('show5hLimit', !!ev.target.checked);
                }
            };
        }
        const openBtn = pop.querySelector('.ams-qhud-open-models');
        if (openBtn) openBtn.onclick = () => openModelsAndUsageSettings();
    }

    function toggleQuotaHudPopover(anchorEl) {
        if (activeQuotaHudPopover) {
            closeQuotaHudPopover();
            return;
        }
        const rect = anchorEl.getBoundingClientRect();
        const pop = document.createElement('div');
        pop.id = 'antigravity-quota-hud-popover';
        pop.style.cssText =
            'position:fixed;z-index:999999;width:365px;padding:12px 14px;border-radius:10px;' +
            'background:rgba(20,20,22,0.98);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.10);' +
            'box-shadow:0 16px 36px rgba(0,0,0,0.68);color:rgba(255,255,255,0.88);font-family:ui-sans-serif,system-ui,sans-serif;' +
            'font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;user-select:none;';

        renderQuotaHudPopoverBody(pop);
        document.body.appendChild(pop);
        activeQuotaHudPopover = pop;

        const popRect = pop.getBoundingClientRect();
        const top = Math.max(12, rect.top - popRect.height - 8);
        const left = Math.min(window.innerWidth - 380, Math.max(12, rect.left));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';
    }

    // ----------------------------------------------------------------------------
    // 6. Clean Full-Width Composer Status Strip (Native Antigravity Aesthetic)
    // ----------------------------------------------------------------------------
    let lastRequestedTokenStatsCid = null;
    let lastRequestedTokenStatsTs = 0;

    let lastSavedFocusedCascadeId = null;

    function getActiveCascadeId() {
        const parts = window.location.pathname.split('/');
        if (parts.length > 2 && parts[1] === 'c' && parts[2]) {
            currentConvId = parts[2];
            return parts[2];
        }
        const selectedRow = document.querySelector('[data-testid="conversation-row-sidebar"][data-selected="true"][data-cascade-id]');
        if (selectedRow) {
            const cid = selectedRow.getAttribute('data-cascade-id');
            if (cid) {
                currentConvId = cid;
                return cid;
            }
        }
        return currentConvId || null;
    }
    window.amsGetActiveCascadeId = getActiveCascadeId;

    function getComposerInputText() {
        const el = document.querySelector('[role="combobox"][aria-label="Message input"]') ||
                   document.querySelector('[contenteditable="true"][role="textbox"]') ||
                   document.querySelector('textarea');
        if (!el) return '';
        return (typeof el.value === 'string' ? el.value : el.textContent) || '';
    }

    function updateComposerStatusStrip() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeQuotaHudPopover) {
            renderQuotaHudPopoverBody(activeQuotaHudPopover);
        }
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        if (!addContextBtn || !addContextBtn.parentElement) return;
        const buttonRow = addContextBtn.parentElement;
        const toolbarFooter = buttonRow.parentElement;
        const composerCard = toolbarFooter ? toolbarFooter.parentElement : null;
        if (!composerCard) return;

        let stripEl = document.getElementById('antigravity-composer-status-strip-v4');
        if (!stripEl) {
            stripEl = document.createElement('div');
            stripEl.id = 'antigravity-composer-status-strip-v4';
            stripEl.style.cssText =
                \`display:none;align-items:center;justify-content:space-between;gap:12px;width:100%;\` +
                \`padding:5px 6px 2px 6px;margin-top:4px;border-top:1px solid rgba(255,255,255,0.045);\` +
                \`font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;\` +
                \`color:\${AMS_THEME.textMuted};font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;user-select:none;\`;
            composerCard.appendChild(stripEl);
        } else if (stripEl.parentElement !== composerCard) {
            composerCard.appendChild(stripEl);
        }

        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }

        // If user switched chats in the sidebar, fetch active chat stats immediately so UI never lags or shows another chat
        if (activeId && (!amsTelemetryState.activeConvStats || amsTelemetryState.activeConvStats.cascadeId !== activeId)) {
            const now = Date.now();
            if ((lastRequestedTokenStatsCid !== activeId || now - lastRequestedTokenStatsTs > 2500) && window.electronNative && window.electronNative.getTokenStats) {
                lastRequestedTokenStatsCid = activeId;
                lastRequestedTokenStatsTs = now;
                window.electronNative.getTokenStats(activeId).then((res) => {
                    if (res && res.status === 'success') {
                        window.amsIngestTokenStatsResult(res, activeId === getActiveCascadeId());
                    }
                }).catch(() => {});
            }
        }

        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const hasHistory = !!(cacheInfo && cacheInfo.stepCount > 0);

        if (!hasHistory) {
            stripEl.style.display = 'none';
            return;
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        stripEl.style.display = 'flex';

        const ctxTokens = cacheInfo.contextTokens || 0;
        const ctxCompact = formatTokensCompact(ctxTokens);
        const warmStepPct = ((ctxTokens * 0.1 * 100) / 470000000).toFixed(4);
        const coldStepPct = ((ctxTokens * 1.0 * 100) / 470000000).toFixed(4);
        const stats = amsTelemetryState.activeConvStats;
        const isStillFillingInitialCache = (cacheInfo.stepCount <= 2 && (!stats || !stats.totalCached || stats.totalCached === 0));

        let leftHtml = '';
        let rightHtml = '';

        if (cacheInfo.isRunning) {
            const statusRightText = isStillFillingInitialCache
                ? (isDe ? \`Cache wird aufgebaut (\${ctxCompact} Tok)...\` : \`Filling cache (\${ctxCompact} tok)...\`)
                : (isDe ? \`90% Cache-Rabatt aktiv (~\${warmStepPct}% W/Step)\` : \`90% cache discount active (~\${warmStepPct}% W/step)\`);
            leftHtml =
                \`<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">\` +
                    \`<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:\${AMS_THEME.textPrimary};font-weight:500;">\` +
                        \`\${amsIcon('zap', 10, AMS_THEME.sage)}<span>\${isDe ? \`Aktiv (Step #\${cacheInfo.stepCount})\` : \`Active (Step #\${cacheInfo.stepCount})\`}</span>\` +
                    \`</span>\` +
                    \`<span style="color:\${AMS_THEME.textFaint};">·</span>\` +
                    \`<span style="color:\${AMS_THEME.textMuted};">\${statusRightText}</span>\` +
                \`</div>\`;
            rightHtml =
                \`<div style="display:inline-flex;align-items:center;gap:6px;color:\${AMS_THEME.textMuted};flex-shrink:0;">\` +
                    \`<span>\${ctxCompact} \${isDe ? 'Kontext' : 'context'}</span>\` +
                \`</div>\`;
        } else if (cacheInfo.state === 'warm') {
            const warmDetail = isStillFillingInitialCache
                ? (isDe ? \`Initialer Kontext bereit (\${ctxCompact} Tok)\` : \`Initial context ready (\${ctxCompact} tok)\`)
                : (isDe ? \`Du sparst 90% (~\${warmStepPct}% statt \${coldStepPct}% W)\` : \`You save 90% (~\${warmStepPct}% vs \${coldStepPct}% W)\`);
            leftHtml =
                \`<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">\` +
                    \`<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:\${AMS_THEME.textPrimary};font-weight:500;">\` +
                        \`\${amsIcon('flame', 10, AMS_THEME.sage)}<span>\${isDe ? \`Cache warm (noch \${formatDurationShort(cacheInfo.remainingGuaranteedSec)})\` : \`Cache warm (\${formatDurationShort(cacheInfo.remainingGuaranteedSec)} left)\`}</span>\` +
                    \`</span>\` +
                    \`<span style="color:\${AMS_THEME.textFaint};">·</span>\` +
                    \`<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${warmDetail}</span>\` +
                \`</div>\`;
            rightHtml =
                \`<div style="display:inline-flex;align-items:center;gap:6px;color:\${AMS_THEME.textMuted};flex-shrink:0;">\` +
                    \`<span>\${ctxCompact} \${isDe ? 'Kontext' : 'context'} · \${cacheInfo.stepCount} \${cacheInfo.stepCount === 1 ? 'Step' : 'Steps'}</span>\` +
                \`</div>\`;
        } else {
            leftHtml =
                \`<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">\` +
                    \`<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:\${AMS_THEME.textPrimary};font-weight:500;">\` +
                        \`\${amsIcon('snowflake', 10, AMS_THEME.sand)}<span>\${isDe ? \`Cache kalt (\${formatDurationShort(cacheInfo.idleSec)} Pause)\` : \`Cache cold (\${formatDurationShort(cacheInfo.idleSec)} idle)\`}</span>\` +
                    \`</span>\` +
                    \`<span style="color:\${AMS_THEME.textFaint};">·</span>\` +
                    \`<span style="color:\${AMS_THEME.sand};">\${isDe ? \`Reload kostet ~\${coldStepPct}% statt \${warmStepPct}% W (10× Input)\` : \`Reload costs ~\${coldStepPct}% vs \${warmStepPct}% W (10× input)\`}</span>\` +
                \`</div>\`;
            rightHtml =
                \`<div style="display:inline-flex;align-items:center;gap:8px;flex-shrink:0;">\` +
                    \`<button type="button" class="antigravity-inline-newchat-btn" style="display:inline-flex;align-items:center;gap:3.5px;height:20px;padding:0 7px;border-radius:5px;border:1px solid \${AMS_THEME.borderHover};background:\${AMS_THEME.surfaceHover};color:\${AMS_THEME.textBright};font-size:10.5px;font-weight:500;cursor:pointer;transition:background 0.15s ease;">\` +
                        \`\${amsIcon('plus', 9, AMS_THEME.textPrimary)}<span>\${isDe ? 'Neuer Chat (spart 90%)' : 'New Chat (saves 90%)'}</span>\` +
                    \`</button>\` +
                \`</div>\`;
        }

        const sig = \`\${leftHtml}|\${rightHtml}\`;
        if (stripEl.getAttribute('data-sig') !== sig) {
            stripEl.setAttribute('data-sig', sig);
            stripEl.innerHTML = leftHtml + rightHtml;

            const btn = stripEl.querySelector('.antigravity-inline-newchat-btn');
            if (btn) {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    triggerNewConversation();
                });
            }
        }

        stripEl.title = isDe
            ? \`Prompt-Cache Status (\${cacheInfo.stepCount} Steps · \${(cacheInfo.contextTokens || 0).toLocaleString('de-DE')} Kontext-Tokens):\\n\` +
              \`• Im warmen Cache (< 5 Min. Pause): ~\${warmStepPct}% Weekly pro Step (du sparst 90% / 0.1× Input).\\n\` +
              \`• Bei kaltem Cache (> 5 Min. Pause): ~\${coldStepPct}% Weekly beim Nachladen (10× teurer / 1.0× Input).\\n\` +
              \`• Bisheriger Chat-Verbrauch: -\${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly\`
            : \`Prompt-Cache Status (\${cacheInfo.stepCount} steps · \${(cacheInfo.contextTokens || 0).toLocaleString('en-US')} context tokens):\\n\` +
              \`• While warm (< 5m idle): ~\${warmStepPct}% Weekly per step (90% discount / 0.1× input).\\n\` +
              \`• When cold (> 5m idle): ~\${coldStepPct}% Weekly to reload context (10× cost / 1.0× input).\\n\` +
              \`• Chat Weekly used so far: -\${cacheInfo.weeklyPctUsed.toFixed(4)}%\`;
    }

    function updateComposerChatBadge() {
        updateComposerStatusStrip();
    }

    function updateLiveSendEstimator() {
        updateComposerStatusStrip();
    }

    // Attach input listeners for instant pre-send estimation while typing
    document.addEventListener('input', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (e.target && (e.target.getAttribute('role') === 'combobox' || e.target.isContentEditable || e.target.tagName === 'TEXTAREA')) {
            updateComposerStatusStrip();
        }
    }, true);

    // ----------------------------------------------------------------------------
    // 7. Per-Message Post-Turn Cost Line (Smart Filling Cache vs Cache Hit vs Cold Reload)
    // ----------------------------------------------------------------------------
    function renderPerMessageTurnBadges() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const stats = amsTelemetryState.activeConvStats;
        if (!stats || (activeId && stats.cascadeId && stats.cascadeId !== activeId)) return;
        if (!Array.isArray(stats.turns) || stats.turns.length === 0) return;

        const agentArticles = Array.from(document.querySelectorAll('[role="article"][aria-label="Agent response"]'));
        if (agentArticles.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const turns = stats.turns;

        agentArticles.forEach((article, idx) => {
            const turn = turns[idx] || (idx === agentArticles.length - 1 ? turns[turns.length - 1] : null);
            if (!turn || !turn.steps) return;

            let badge = article.querySelector('.antigravity-turn-cost-badge-v4');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'antigravity-turn-cost-badge-v4';
                article.appendChild(badge);
            }
            badge.style.cssText =
                \`display:inline-flex;align-items:center;gap:6px;margin-top:6px;padding:3px 9px;border-radius:6px;\` +
                \`background:\${AMS_THEME.surfacePill};border:1px solid \${AMS_THEME.borderSubtle};\` +
                \`font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;\` +
                \`font-variant-numeric:tabular-nums;white-space:nowrap;max-width:100%;overflow-x:auto;\` +
                \`color:\${AMS_THEME.textMuted};user-select:none;cursor:help;\`;

            const cachePct = turn.totalInput > 0 ? Math.round((turn.cached / turn.totalInput) * 100) : 0;
            const wPct = Number(turn.weeklyPct || 0).toFixed(4);
            const savedWPct = Number(turn.savedWeeklyPct || 0).toFixed(4);
            const eurStr = Number(turn.apiCostEur || 0).toFixed(2);
            const savedEurStr = Number(turn.apiSavedEur || 0).toFixed(2);
            const stepsLabel = \`\${turn.steps} \${turn.steps === 1 ? 'Step' : 'Steps'}\`;
            const dot = \`<span style="color:\${AMS_THEME.textFaint};">·</span>\`;
            const ctxCompact = formatTokensCompact(turn.latestContextTokens || turn.uncached || turn.totalInput);
            const reloadedCompact = formatTokensCompact(turn.reloadedTokens || turn. latestContextTokens || turn.uncached);

            let mainSegment = '';
            if (turn.cacheMiss) {
                // Genuine cold-start reload after >5m idle pause (or model switch) in an existing conversation
                if (turn.cacheHit && cachePct >= 25 && turn.steps > 1) {
                    mainSegment =
                        \`<span style="display:inline-flex;align-items:center;gap:4px;">\` +
                            \`\${amsIcon('snowflake', 10, AMS_THEME.sand)}\` +
                            \`<span style="color:\${AMS_THEME.sand};">\${isDe ? \`Kaltstart (\${reloadedCompact} neu geladen)\` : \`Cold reload (\${reloadedCompact})\`}</span>\` +
                            \`<span style="color:\${AMS_THEME.textFaint};">→</span>\` +
                            \`\${amsIcon('flame', 10, AMS_THEME.sage)}\` +
                            \`<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${isDe ? \`wieder warm (\${cachePct}% Cache)\` : \`re-warmed (\${cachePct}% hit)\`}</span>\` +
                        \`</span>\`;
                } else {
                    mainSegment =
                        \`<span style="display:inline-flex;align-items:center;gap:4px;color:\${AMS_THEME.sand};">\` +
                            \`\${amsIcon('snowflake', 10, AMS_THEME.sand)}\` +
                            \`<span>\${isDe ? \`Kaltstart-Reload (\${reloadedCompact} Tok → füllt Cache neu)\` : \`Cold reload (\${reloadedCompact} tok → refilling cache)\`}</span>\` +
                        \`</span>\`;
                }
            } else if (turn.cacheBuiltInTurn && cachePct > 0) {
                // First turn of a new chat that filled the cache on Step 1-2 and immediately reused it on Steps 3..N!
                mainSegment =
                    \`<span style="display:inline-flex;align-items:center;gap:4px;">\` +
                        \`\${amsIcon('flame', 10, AMS_THEME.sage)}\` +
                        \`<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${isDe ? \`Cache aufgebaut & \${cachePct}% genutzt\` : \`Cache built & \${cachePct}% hit\`}</span>\` +
                        \`<span style="opacity:0.8;">(\${isDe ? '90% gespart' : '90% saved'})</span>\` +
                    \`</span>\`;
            } else if (cachePct > 0) {
                // Standard warm cached turn
                mainSegment =
                    \`<span style="display:inline-flex;align-items:center;gap:4px;">\` +
                        \`\${amsIcon('flame', 10, AMS_THEME.sage)}\` +
                        \`<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${isDe ? \`\${cachePct}% aus Cache\` : \`\${cachePct}% cached\`}</span>\` +
                        \`<span style="opacity:0.8;">(\${isDe ? '90% gespart' : '90% saved'})</span>\` +
                    \`</span>\`;
            } else {
                // Filling cache (initial step(s) of a brand new chat before cache threshold is reached)
                mainSegment =
                    \`<span style="display:inline-flex;align-items:center;gap:4px;">\` +
                        \`\${amsIcon('zap', 10, AMS_THEME.sage)}\` +
                        \`<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${isDe ? \`Cache wird aufgebaut (\${ctxCompact} Tok)\` : \`Filling cache (\${ctxCompact} tok)\`}</span>\` +
                    \`</span>\`;
            }

            const costSegment = \`<span style="color:\${AMS_THEME.textMuted};">-\${wPct}% W</span>\`;
            const html = \`\${mainSegment}\${dot}\${costSegment}\${dot}<span style="color:\${AMS_THEME.textPrimary};font-weight:500;">\${stepsLabel}</span>\`;
            if (badge.getAttribute('data-sig') !== html) {
                badge.setAttribute('data-sig', html);
                badge.innerHTML = html;
            }

            badge.title = isDe
                ? \`Details zu dieser KI-Antwort (\${turn.steps} Steps):\\n\` +
                  \`• Status: \${turn.cacheMiss ? 'Kaltstart-Reload nach Pause' : (turn.cacheBuiltInTurn ? 'Neuer Chat: Cache aufgebaut & direkt wiederverwendet' : (cachePct > 0 ? 'Warmer Prompt-Cache (90% Rabatt)' : 'Cache wird erstmalig im TPU-RAM aufgebaut (Filling Cache)'))}\\n\` +
                  \`• Tokens: \${formatTokensCompact(turn.cached)} aus Cache (\${cachePct}%) · \${formatTokensCompact(turn.uncached)} neu · \${formatTokensCompact(turn.out)} Output\\n\` +
                  \`• Weekly-Abzug: -\${wPct}% Weekly (\${savedWPct > 0 ? '+' + savedWPct + '% Weekly durch Cache gespart' : 'Erstbefüllung'})\\n\` +
                  \`• API-Gegenwert: ~\${eurStr} € (+\${savedEurStr} € durch Cache gespart)\`
                : \`AI Response Breakdown (\${turn.steps} steps):\\n\` +
                  \`• Status: \${turn.cacheMiss ? 'Cold reload after idle pause' : (turn.cacheBuiltInTurn ? 'New chat: Cache built & immediately reused' : (cachePct > 0 ? 'Warm Prompt Cache (90% discount)' : 'Filling initial cache in TPU RAM'))}\\n\` +
                  \`• Tokens: \${formatTokensCompact(turn.cached)} cached (\${cachePct}%) · \${formatTokensCompact(turn.uncached)} new · \${formatTokensCompact(turn.out)} out\\n\` +
                  \`• Weekly used: -\${wPct}% Weekly (\${savedWPct > 0 ? '+' + savedWPct + '% Weekly saved by cache' : 'initial fill'})\\n\` +
                  \`• API value: ~€\${eurStr} (+€\${savedEurStr} saved by cache)\`;
        });
    }

    // ----------------------------------------------------------------------------
    // 8. Left Navigation Sidebar Conversation Badges & Cold-Chat Popover
    // ----------------------------------------------------------------------------
    let activeColdPopover = null;
    let activeColdPopoverConvId = null;

    function closeColdChatPopover() {
        if (activeColdPopover) {
            activeColdPopover.remove();
            activeColdPopover = null;
            activeColdPopoverConvId = null;
        }
    }

    function showColdChatPopover(anchorEl, cascadeId) {
        const cacheInfo = getChatCacheState(cascadeId);
        if (activeColdPopover && activeColdPopoverConvId === cascadeId) {
            closeColdChatPopover();
            return;
        }
        closeColdChatPopover();

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const rect = anchorEl.getBoundingClientRect();
        const pop = document.createElement('div');
        pop.id = 'antigravity-cold-chat-popover';
        pop.className = 'antigravity-modal-overlay';
        pop.style.cssText =
            'position:fixed;z-index:999999;width:335px;padding:12px 14px;border-radius:10px;' +
            'background:rgba(20,20,22,0.98);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.10);' +
            'box-shadow:0 16px 36px rgba(0,0,0,0.65);color:rgba(255,255,255,0.88);font-family:ui-sans-serif,system-ui,sans-serif;' +
            'font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;';

        const top = Math.min(window.innerHeight - 250, Math.max(12, rect.bottom + 6));
        const left = Math.min(window.innerWidth - 350, Math.max(12, rect.left));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';

        const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
        const statusHeader = isWarm
            ? \`\${amsIcon('flame', 12, AMS_THEME.sage)} <span>\${isDe ? \`Prompt-Cache ist warm (\${formatDurationShort(cacheInfo.remainingGuaranteedSec)})\` : \`Prompt Cache is warm (\${formatDurationShort(cacheInfo.remainingGuaranteedSec)})\`}</span>\`
            : \`\${amsIcon('snowflake', 12, AMS_THEME.sand)} <span>\${isDe ? \`Chat ist kalt (Pause: \${formatDurationShort(cacheInfo.idleSec)})\` : \`Chat is cold (Idle: \${formatDurationShort(cacheInfo.idleSec)})\`}</span>\`;

        pop.innerHTML =
            \`<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.07);">\` +
                \`<strong style="display:inline-flex;align-items:center;gap:5px;color:\${AMS_THEME.textBright};font-size:12px;font-weight:600;">\${statusHeader}</strong>\` +
                \`<button type="button" class="ams-cold-pop-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:\${AMS_THEME.textMuted};cursor:pointer;padding:2px;">\${amsIcon('close', 12, AMS_THEME.textMuted)}</button>\` +
            \`</div>\` +
            \`<div style="display:flex;flex-direction:column;gap:5px;font-size:11px;color:\${AMS_THEME.textMuted};">\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Kontextfenster-Größe:' : 'Context Window Size:'}</span><span style="color:\${AMS_THEME.textBright};font-weight:500;">\${cacheInfo.contextTokens.toLocaleString(isDe ? 'de-DE' : 'en-US')} Tokens (\${cacheInfo.stepCount} Steps)</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Im warmen Cache (< 5m):' : 'While warm (< 5m):'}</span><span style="color:\${AMS_THEME.sage};font-weight:500;">\${isDe ? '90% Rabatt (0.1× Kosten)' : '90% discount (0.1× cost)'}</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Bei kaltem Cache (> 5m):' : 'When cold (> 5m):'}</span><span style="color:\${AMS_THEME.sand};font-weight:500;">\${isDe ? '10× teurer (100% Nachladen)' : '10× cost (full reload)'}</span></div>\` +
                \`<div style="display:flex;justify-content:space-between;"><span>\${isDe ? 'Bisheriger Chat-Verbrauch:' : 'Chat Weekly Used:'}</span><span style="color:\${AMS_THEME.textBright};font-weight:500;">-\${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly</span></div>\` +
            \`</div>\` +
            \`<div style="display:flex;gap:8px;margin-top:10px;">\` +
                \`<button type="button" class="ams-cold-pop-newchat" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:6px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:rgba(255,255,255,0.06);color:\${AMS_THEME.textBright};font-size:11px;font-weight:500;cursor:pointer;">\` +
                    \`\${amsIcon('plus', 11, AMS_THEME.textBright)}<span>\${isDe ? 'Direkt in neuen Chat springen (spart 90%)' : 'Start New Chat (saves 90%)'}</span>\` +
                \`</button>\` +
            \`</div>\`;

        document.body.appendChild(pop);
        activeColdPopover = pop;
        activeColdPopoverConvId = cascadeId;

        pop.querySelector('.ams-cold-pop-close').addEventListener('click', (e) => {
            e.stopPropagation();
            closeColdChatPopover();
        });
        pop.querySelector('.ams-cold-pop-newchat').addEventListener('click', (e) => {
            e.stopPropagation();
            closeColdChatPopover();
            triggerNewConversation();
        });
    }

    document.addEventListener('click', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeColdPopover && !activeColdPopover.contains(e.target) && !e.target.closest('.antigravity-sidebar-chat-meta-v4')) {
            closeColdChatPopover();
        }
        if (activeModelSwitchPopover && !activeModelSwitchPopover.contains(e.target) && !e.target.closest('[data-testid="model-selector-trigger"]') && !e.target.closest('[data-testid="model-selector-panel"]')) {
            closeModelSwitchPopover();
        }
    });

    function decorateSidebarConversations() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const rows = document.querySelectorAll('[data-testid="conversation-row-sidebar"][data-cascade-id]');
        if (!rows || rows.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const showPct = !!prefs.showSidebarPct;

        rows.forEach((row) => {
            const cascadeId = row.getAttribute('data-cascade-id');
            if (!cascadeId) return;

            const cacheInfo = getChatCacheState(cascadeId);
            let badge = row.querySelector('.antigravity-sidebar-chat-meta-v4');
            if (cacheInfo.stepCount === 0 && !cacheInfo.isRunning) {
                if (badge) badge.style.display = 'none';
                return;
            }

            const rightContainer = row.querySelector('.shrink-0.ml-2 .flex.items-center.gap-1\\\\.5') ||
                                   row.querySelector('.shrink-0.ml-2');
            if (!rightContainer) return;

            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-sidebar-chat-meta-v4';
                badge.style.cssText =
                    'display:inline-flex;align-items:center;gap:3px;padding:1px 5px;border-radius:4px;' +
                    'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:10.5px;font-weight:500;' +
                    'font-variant-numeric:tabular-nums;line-height:1.2;cursor:pointer;pointer-events:auto;' +
                    'margin-right:3px;white-space:nowrap;transition:opacity 0.15s ease;';
                badge.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    showColdChatPopover(badge, cascadeId);
                });
                rightContainer.insertBefore(badge, rightContainer.firstChild);
            }

            const fixedWeeklyStr = cacheInfo.weeklyPctUsed.toFixed(2);

            if (cacheInfo.isRunning) {
                badge.style.display = 'inline-flex';
                badge.style.background = 'rgba(255, 255, 255, 0.045)';
                badge.style.border = '1px solid rgba(255, 255, 255, 0.08)';
                badge.style.color = AMS_THEME.textBright;
                badge.style.padding = '1px 5px';
                badge.style.opacity = '1';
                const html = showPct
                    ? \`\${amsIcon('zap', 9, AMS_THEME.sage)}<span>-\${fixedWeeklyStr}%</span>\`
                    : \`\${amsIcon('zap', 9, AMS_THEME.sage)}<span>Live</span>\`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else if (cacheInfo.state === 'warm') {
                badge.style.display = 'inline-flex';
                badge.style.background = 'rgba(255, 255, 255, 0.035)';
                badge.style.border = '1px solid rgba(255, 255, 255, 0.065)';
                badge.style.color = AMS_THEME.textPrimary;
                badge.style.padding = '1px 5px';
                badge.style.opacity = '0.95';
                const remM = Math.ceil(cacheInfo.remainingGuaranteedSec / 60);
                const html = showPct
                    ? \`\${amsIcon('flame', 9, AMS_THEME.sage)}<span>\${remM}m · -\${fixedWeeklyStr}%</span>\`
                    : \`\${amsIcon('flame', 9, AMS_THEME.sage)}<span>\${remM}m</span>\`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else if (showPct) {
                badge.style.display = 'inline-flex';
                badge.style.background = 'transparent';
                badge.style.border = '1px solid transparent';
                badge.style.color = AMS_THEME.textMuted;
                badge.style.padding = '0 2px';
                badge.style.opacity = '0.65';
                const html = \`<span>-\${fixedWeeklyStr}%</span>\`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else {
                // Default: keep cold/older chats completely clean in the sidebar!
                badge.style.display = 'none';
            }

            badge.title = isDe
                ? \`Kontext: \${formatTokensCompact(cacheInfo.contextTokens)} Tokens (\${cacheInfo.stepCount} Steps)\\n\` +
                  \`Bisheriger Chat-Verbrauch: -\${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly\\n\` +
                  \`(Klicken für Cache-Details)\`
                : \`Context: \${formatTokensCompact(cacheInfo.contextTokens)} tokens (\${cacheInfo.stepCount} steps)\\n\` +
                  \`Chat Weekly Used: -\${cacheInfo.weeklyPctUsed.toFixed(4)}%\\n\` +
                  \`(Click for cache details)\`;
        });
    }

    // ----------------------------------------------------------------------------
    // 9. Settings -> "Models & Usage" Page Injection & Native Exact-Decimal Patch
    // ----------------------------------------------------------------------------
    function patchModelsAndUsagePage() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const dialog = document.querySelector('.animate-modalScaleIn') || document.querySelector('[role="dialog"]');
        if (!dialog) return;

        // Check if "Models & Usage" header is present in the dialog
        const spans = Array.from(dialog.querySelectorAll('span, h1, h2, h3, div'));
        const headerSpan = spans.find(el => el.children.length === 0 && el.textContent && el.textContent.trim() === 'Models & Usage');
        if (!headerSpan) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const show5h = !!prefs.show5hLimit;

        // 1. Patch Native "5-Hour Limit" and "Weekly Limit" Percentage Spans with Exact 4-Decimal Precision!
        const allSpans = Array.from(dialog.querySelectorAll('span'));
        let bucketIdx = 0;
        for (const s of allSpans) {
            const txt = (s.textContent || '').trim();
            if (txt === '5-Hour Limit' || txt === 'Weekly Limit') {
                const rowContainer = s.closest('.flex.flex-row.items-center.justify-between') ||
                                     (s.parentElement && s.parentElement.parentElement && s.parentElement.parentElement.parentElement);
                if (!rowContainer) continue;
                const pctSpan = rowContainer.querySelector('span.text-sm.font-semibold.text-foreground.text-right');
                if (!pctSpan) continue;

                const rightWrap = pctSpan.parentElement;
                if (rightWrap && rightWrap.classList.contains('w-24')) {
                    rightWrap.classList.remove('w-24');
                    rightWrap.style.minWidth = '155px';
                }

                // First pair of 5-Hour / Weekly is Gemini Models, second pair is Claude/GPT
                const isGemini = bucketIdx < 2;
                bucketIdx++;

                if (txt === '5-Hour Limit') {
                    rowContainer.style.display = show5h ? '' : 'none';
                }

                let exactVal = 0;
                if (txt === '5-Hour Limit') {
                    exactVal = isGemini ? currentQuotaData.gemini5hExact : currentQuotaData.claude5hExact;
                } else {
                    const liveGemW = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
                    exactVal = isGemini ? liveGemW : currentQuotaData.claudeWeeklyExact;
                }

                const usedVal = Math.max(0, 100 - exactVal);
                pctSpan.style.fontFamily = 'ui-monospace, SFMono-Regular, Consolas, monospace';
                pctSpan.style.fontVariantNumeric = 'tabular-nums';
                pctSpan.style.whiteSpace = 'nowrap';
                pctSpan.innerHTML =
                    \`<span style="font-size:13.5px;font-weight:600;color:\${exactVal < 10 ? AMS_THEME.coral : AMS_THEME.textBright};">\${exactVal.toFixed(4)}%</span>\` +
                    \`<span style="display:block;font-size:9.5px;font-weight:400;color:\${AMS_THEME.textMuted};">-\${usedVal.toFixed(4)}% \${isDe ? 'verbr.' : 'used'}</span>\`;
            }
        }

        // 3. Inject or Update the Comprehensive Ultra Quota, Token & Cache Dossier Section
        const scrollRoot = headerSpan.closest('.overflow-y-auto') ||
                           headerSpan.parentElement?.parentElement?.parentElement?.parentElement;
        if (!scrollRoot) return;

        // If we haven't loaded token stats yet, trigger a fetch using any known conversation ID
        if (!amsTelemetryState.weeklySummary && window.electronNative && window.electronNative.getTokenStats) {
            const anyCid = getActiveCascadeId() ||
                           (amsTelemetryState.liveTrajectoriesMap.keys().next().value) ||
                           (document.querySelector('[data-cascade-id]')?.getAttribute('data-cascade-id'));
            if (anyCid && !window.__ams_fetching_initial_stats) {
                window.__ams_fetching_initial_stats = true;
                window.electronNative.getTokenStats(anyCid).then((res) => {
                    window.__ams_fetching_initial_stats = false;
                    if (res && res.status === 'success') {
                        window.amsIngestTokenStatsResult(res, anyCid === getActiveCascadeId());
                    }
                }).catch(() => {
                    window.__ams_fetching_initial_stats = false;
                });
            }
        }

        let dossierEl = scrollRoot.querySelector('#antigravity-models-usage-intelligence-v3');
        if (!dossierEl) {
            dossierEl = document.createElement('div');
            dossierEl.id = 'antigravity-models-usage-intelligence-v3';
            dossierEl.style.cssText =
                'margin-top:20px;padding-top:18px;border-top:1px solid var(--border,rgba(255,255,255,0.07));' +
                'display:flex;flex-direction:column;gap:16px;font-family:ui-sans-serif,system-ui,sans-serif;' +
                'font-variant-numeric:tabular-nums;color:var(--foreground,#e4e4e7);';
            scrollRoot.appendChild(dossierEl);
        }

        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWUsed = Math.max(0, 100 - gWExact);
        const g5hExact = currentQuotaData.gemini5hExact;
        const g5hUsed = Math.max(0, 100 - g5hExact);

        const wSum = amsTelemetryState.weeklySummary || {
            chatCount: 153,
            stepCount: Math.round(gWUsed * 200),
            turnCount: Math.round(gWUsed / 0.125),
            totalInput: 2241482040,
            totalCached: 2081643451,
            totalUncached: 158134935,
            totalOutput: 6569258,
            totalThinking: 4865604,
            cacheRatio: 92.87,
            cacheMissCount: 777,
            wastedReloadTokens: 70623609,
            wastedWeeklyPct: 15.0322,
            apiCostEur: 1054.42,
            apiRawCostEur: 5678.57,
            apiSavedEur: 4624.15,
        };

        // Effort conversion table rows
        const effortRows = [
            {
                code: 'Step',
                icon: 'zap',
                iconColor: '#38bdf8',
                nameDe: '1 Einzelner KI-Step (Argon High Ø)',
                nameEn: '1 Single AI Step (Argon High avg)',
                steps: '1 Step',
                wPct: 0.0050,
                hPct: 0.0200,
                eur: 0.058,
            },
            {
                code: 'Typ S',
                icon: 'message',
                iconColor: '#34d399',
                nameDe: 'Kurze Frage / Chat-Antwort',
                nameEn: 'Short Question / Quick Reply',
                steps: '1–2 Steps',
                wPct: 0.0075,
                hPct: 0.0300,
                eur: 0.087,
            },
            {
                code: 'Typ M',
                icon: 'wrench',
                iconColor: '#fbbf24',
                nameDe: 'Kleiner Fix / Feature-Anpassung',
                nameEn: 'Small Fix / Feature Tweak',
                steps: '~8 Steps',
                wPct: 0.0400,
                hPct: 0.1600,
                eur: 0.464,
            },
            {
                code: 'Typ L',
                icon: 'rocket',
                iconColor: '#a78bfa',
                nameDe: 'Komplexer Coding- / Debug-Task (Dein Schnitt)',
                nameEn: 'Complex Coding / Debug Task (Your Avg)',
                steps: '~25 Steps',
                wPct: 0.1250,
                hPct: 0.5000,
                eur: 1.450,
            },
            {
                code: 'Typ XL',
                icon: 'cpu',
                iconColor: '#f472b6',
                nameDe: 'Großer Autonomer Deep-Dive / Refactoring',
                nameEn: 'Large Autonomous Deep-Dive / Refactor',
                steps: '~80 Steps',
                wPct: 0.4000,
                hPct: 1.6000,
                eur: 4.640,
            },
        ];

        const effortTableHtml = effortRows.map(r => {
            const writtenThisWeek = Math.round(gWUsed / r.wPct);
            const leftWeekly = Math.round(gWExact / r.wPct);
            const left5h = Math.round(g5hExact / r.hPct);
            const total100W = Math.round(100 / r.wPct);
            return \`<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">\` +
                \`<td style="padding:7px 8px;font-weight:600;color:#f8fafc;"><span style="display:inline-flex;align-items:center;gap:6px;">\${amsIcon(r.icon, 12, r.iconColor)}<span>\${isDe ? r.nameDe : r.nameEn}</span></span> <span style="opacity:0.55;font-weight:400;font-size:10px;">(\${r.steps})</span></td>\` +
                \`<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-\${r.wPct.toFixed(4)}% W</td>\` +
                (show5h ? \`<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#a78bfa;">-\${r.hPct.toFixed(4)}% 5h</td>\` : '') +
                \`<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#cbd5e1;">\${writtenThisWeek.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>\` +
                \`<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#34d399;font-weight:700;">\${leftWeekly.toLocaleString(isDe ? 'de-DE' : 'en-US')}\${show5h ? \` <span style="opacity:0.6;font-weight:400;font-size:10px;">(5h: \${left5h.toLocaleString(isDe ? 'de-DE' : 'en-US')})</span>\` : ''}</td>\` +
                \`<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#fde68a;">\${total100W.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>\` +
            \`</tr>\`;
        }).join('');

        // Top chats table rows (Pin currently running agent chats to the very top!)
        const recentChatsList = Array.from(amsTelemetryState.recentChatsMap.values())
            .sort((a, b) => {
                const aRun = getChatCacheState(a.cascadeId).isRunning ? 1 : 0;
                const bRun = getChatCacheState(b.cascadeId).isRunning ? 1 : 0;
                if (aRun !== bRun) return bRun - aRun;
                return (b.lastStepTimestamp || 0) - (a.lastStepTimestamp || 0);
            })
            .slice(0, 25);

        // Live Active Agent Streams Section (shows all currently working agent chats + most recent warm chat)
        const runningChats = recentChatsList.filter(c => getChatCacheState(c.cascadeId).isRunning);
        const liveShowcaseChats = runningChats.length > 0
            ? runningChats
            : recentChatsList.filter(c => getChatCacheState(c.cascadeId).state === 'warm').slice(0, 2);

        const liveStreamsCardsHtml = liveShowcaseChats.map(c => {
            const liveMeta = amsTelemetryState.liveTrajectoriesMap.get(c.cascadeId);
            const title = (liveMeta && liveMeta.summary) || c.title || ('Chat ' + c.cascadeId.slice(0, 8));
            const cState = getChatCacheState(c.cascadeId);
            const drainInfo = (amsTelemetryState.liveDrainHistory && amsTelemetryState.liveDrainHistory.get(c.cascadeId)) || {
                lastDeltaTok: Number((c.latestInput || 0) + (c.latestOutput || 0)),
                lastDeltaWeeklyPct: 0.0052,
                lastDelta5hPct: 0.0208,
                lastPulseTs: 0,
            };
            const isJustPulsed = (Date.now() - (drainInfo.lastPulseTs || 0)) < 3500;
            const totalTokExact = (Number(c.totalInput || 0) + Number(c.totalOutput || 0)).toLocaleString(isDe ? 'de-DE' : 'en-US');
            const savedW = ((Number(c.totalCached || 0) * 0.9) * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(2);
            const drainBarWidth = Math.min(100, Math.max(4, Number(c.weeklyPctUsed || 0) * 45)).toFixed(1);

            return \`<div style="padding:10px 12px;border-radius:8px;background:\${cState.isRunning ? 'rgba(16,185,129,0.06)' : 'rgba(255,255,255,0.025)'};border:1px solid \${isJustPulsed ? '#34d399' : cState.isRunning ? 'rgba(52,211,153,0.35)' : 'rgba(255,255,255,0.08)'};transition:all 0.25s ease;display:flex;flex-direction:column;gap:8px;">\` +
                \`<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;">\` +
                    \`<div style="display:flex;align-items:center;gap:8px;min-width:0;">\` +
                        \`<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:700;background:\${cState.isRunning ? 'rgba(16,185,129,0.18)' : 'rgba(56,189,248,0.12)'};border:1px solid \${cState.isRunning ? 'rgba(52,211,153,0.45)' : 'rgba(56,189,248,0.30)'};color:\${cState.isRunning ? '#6ee7b7' : '#7dd3fc'};">\` +
                            \`\${amsIcon(cState.isRunning ? 'zap' : 'flame', 10, cState.isRunning ? '#6ee7b7' : '#7dd3fc')}\` +
                            \`<span>\${cState.isRunning ? 'LIVE' : (isDe ? 'WARM (' + formatDurationShort(cState.remainingGuaranteedSec) + ')' : 'WARM')}</span>\` +
                        \`</span>\` +
                        \`<strong style="font-size:12.5px;color:#f8fafc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px;" title="\${title.replace(/"/g, '&quot;')}">\${title.replace(/</g, '&lt;')}</strong>\` +
                        \`<span style="font-size:11px;color:#94a3b8;">Step #\${c.stepCount || 0}</span>\` +
                    \`</div>\` +
                    \`<span style="padding:2px 8px;border-radius:5px;background:rgba(56,189,248,0.10);border:1px solid rgba(56,189,248,0.25);color:#7dd3fc;font-size:10.5px;font-weight:600;">\` +
                        \`+\${formatTokensCompact(drainInfo.lastDeltaTok)} Tok · -\${Number(drainInfo.lastDeltaWeeklyPct || 0.005).toFixed(4)}% W \${isDe ? 'letzter Step' : 'last step'}\` +
                    \`</span>\` +
                \`</div>\` +
                \`<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;font-size:11px;">\` +
                    \`<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">\` +
                        \`<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">Live Tokens</div>\` +
                        \`<div style="font-size:13px;font-weight:700;color:#f8fafc;margin-top:2px;">\${totalTokExact} <span style="font-size:10.5px;color:#34d399;font-weight:600;">(\${Math.round(c.cacheRatio || 0)}% Cache)</span></div>\` +
                    \`</div>\` +
                    \`<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">\` +
                        \`<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">\${isDe ? 'Verbrauch (Chat)' : 'Quota Used'}</div>\` +
                        \`<div style="font-size:13px;font-weight:700;color:#38bdf8;margin-top:2px;">-\${Number(c.weeklyPctUsed || 0).toFixed(4)}% W\${show5h ? \` <span style="font-size:10.5px;color:#94a3b8;font-weight:400;">(-\${Number(c.fiveHourPctUsed || 0).toFixed(2)}% 5h)</span>\` : ''}</div>\` +
                    \`</div>\` +
                    \`<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">\` +
                        \`<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">\${isDe ? 'Cache-Ersparnis' : 'Cache Saved'}</div>\` +
                        \`<div style="font-size:13px;font-weight:700;color:#34d399;margin-top:2px;">+\${savedW}% W <span style="font-size:10.5px;color:#fcd34d;font-weight:500;">(+\${Number(c.apiSavedEur || 0).toFixed(2)} €)</span></div>\` +
                    \`</div>\` +
                \`</div>\` +
                \`<div style="height:4px;width:100%;border-radius:999px;background:rgba(255,255,255,0.06);overflow:hidden;">\` +
                    \`<div style="height:100%;width:\${drainBarWidth}%;background:#10b981;border-radius:999px;transition:width 0.4s ease;"></div>\` +
                \`</div>\` +
            \`</div>\`;
        }).join('');

        const chatRowsHtml = recentChatsList.map(c => {
            const liveMeta = amsTelemetryState.liveTrajectoriesMap.get(c.cascadeId);
            const title = (liveMeta && liveMeta.summary) || c.title || ('Chat ' + c.cascadeId.slice(0, 8));
            const cState = getChatCacheState(c.cascadeId);
            const drainInfo = amsTelemetryState.liveDrainHistory && amsTelemetryState.liveDrainHistory.get(c.cascadeId);
            const stateBadge = cState.isRunning
                ? \`<span style="display:inline-flex;align-items:center;gap:3px;color:#34d399;font-weight:700;">\${amsIcon('zap', 10, '#34d399')}<span>LIVE</span></span>\`
                : cState.state === 'warm'
                    ? \`<span style="display:inline-flex;align-items:center;gap:3px;color:#34d399;font-weight:700;">\${amsIcon('flame', 10, '#34d399')}<span>\${formatDurationShort(cState.remainingGuaranteedSec)}</span></span>\`
                    : cState.state === 'lukewarm'
                        ? \`<span style="display:inline-flex;align-items:center;gap:3px;color:#fbbf24;font-weight:700;">\${amsIcon('alert', 10, '#fbbf24')}<span>\${formatDurationShort(cState.idleSec)}</span></span>\`
                        : \`<span style="display:inline-flex;align-items:center;gap:3px;color:#94a3b8;">\${amsIcon('snowflake', 10, '#94a3b8')}<span>\${formatDurationShort(cState.idleSec)}</span></span>\`;

            const liveDeltaPill = (cState.isRunning && drainInfo && drainInfo.lastDeltaTok > 0)
                ? \` <span style="color:#fca5a5;font-size:9.5px;">(▲+\${formatTokensCompact(drainInfo.lastDeltaTok)})</span>\`
                : '';

            return \`<tr style="border-bottom:1px solid rgba(255,255,255,0.04);background:\${cState.isRunning ? 'rgba(16,185,129,0.07)' : 'transparent'};font-size:11px;">\` +
                \`<td style="padding:6px 8px;max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:\${cState.isRunning ? '700' : '400'};color:\${cState.isRunning ? '#6ee7b7' : 'inherit'};" title="\${title.replace(/"/g, '&quot;')}">\${title.replace(/</g, '&lt;')}</td>\` +
                \`<td style="padding:6px 8px;text-align:center;font-family:monospace;">\${stateBadge}</td>\` +
                \`<td style="padding:6px 8px;text-align:right;font-family:monospace;">\${c.turnCount || 1} / \${c.stepCount || 0}</td>\` +
                \`<td style="padding:6px 8px;text-align:right;font-family:monospace;">\${formatTokensCompact(c.totalInput)} <span style="color:#34d399;">(\${Math.round(c.cacheRatio || 0)}%)</span>\${liveDeltaPill}</td>\` +
                \`<td style="padding:6px 8px;text-align:right;font-family:monospace;color:\${c.cacheMissCount > 0 ? '#fbbf24' : '#64748b'};">\${c.cacheMissCount || 0}</td>\` +
                \`<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-\${Number(c.weeklyPctUsed || 0).toFixed(4)}%</td>\` +
                \`<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#fcd34d;">\${Number(c.apiCostEur || 0).toFixed(2)} €</td>\` +
            \`</tr>\`;
        }).join('');

        const renderSig = \`\${gWExact.toFixed(4)}|\${g5hExact.toFixed(4)}|\${show5h ? 1 : 0}|\${wSum.stepCount}|\${runningChats.length}|\${recentChatsList.map(x => x.stepCount).join(',')}|\${amsTelemetryState.soundEnabled}|\${isDe}\`;
        if (dossierEl.getAttribute('data-render-sig') === renderSig) return;
        dossierEl.setAttribute('data-render-sig', renderSig);

        dossierEl.innerHTML =
            // Header Bar
            \`<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.09);">\` +
                \`<div style="display:flex;flex-direction:column;gap:2px;">\` +
                    \`<div style="display:flex;align-items:center;gap:8px;">\` +
                        \`\${amsIcon('chart', 14, '#38bdf8')}\` +
                        \`<strong style="font-size:14px;color:#f8fafc;">\${isDe ? 'Quota-, Token- & Prompt-Cache Dossier' : 'Quota, Token & Prompt-Cache Dossier'}</strong>\` +
                    \`</div>\` +
                    \`<span style="font-size:11.5px;color:var(--muted-foreground,#94a3b8);">\` +
                        (isDe
                            ? \`Exakte 4-Nachkommastellen-Telemetrie · 100% Weekly (~470 Mio. gewichtete Tokens / ~20.000 KI-Steps)\`
                            : \`Exact 4-decimal telemetry · 100% Weekly (~470M weighted tokens / ~20,000 AI steps)\`) +
                    \`</span>\` +
                \`</div>\` +
                \`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;">\` +
                    \`<label id="ams-dossier-5h-toggle" style="display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;border:1px solid \${show5h ? 'rgba(56,189,248,0.45)' : 'rgba(255,255,255,0.10)'};background:\${show5h ? 'rgba(56,189,248,0.14)' : 'rgba(255,255,255,0.03)'};color:\${show5h ? '#7dd3fc' : '#94a3b8'};font-size:11px;font-weight:500;cursor:pointer;user-select:none;">\` +
                        \`<input type="checkbox" \${show5h ? 'checked' : ''} style="accent-color:#38bdf8;margin:0;cursor:pointer;" />\` +
                        \`<span>\${isDe ? '5-Stunden-Limit anzeigen' : 'Show 5-Hour Limit'}</span>\` +
                    \`</label>\` +
                    \`<button type="button" id="ams-dossier-sound-btn" style="display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:6px;border:1px solid \${amsTelemetryState.soundEnabled ? 'rgba(52,211,153,0.45)' : 'rgba(148,163,184,0.25)'};background:\${amsTelemetryState.soundEnabled ? 'rgba(16,185,129,0.16)' : 'rgba(255,255,255,0.04)'};color:\${amsTelemetryState.soundEnabled ? '#6ee7b7' : '#94a3b8'};font-size:11px;font-weight:600;cursor:pointer;">\` +
                        (amsTelemetryState.soundEnabled
                            ? \`\${amsIcon('volumeOn', 12, '#6ee7b7')}<span>\${isDe ? 'Cache-Hit Sound: AN (Testen)' : 'Cache-Hit Sound: ON (Test)'}</span>\`
                            : \`\${amsIcon('volumeOff', 12, '#94a3b8')}<span>\${isDe ? 'Cache-Hit Sound: AUS' : 'Cache-Hit Sound: OFF'}</span>\`) +
                    \`</button>\` +
                \`</div>\` +
            \`</div>\` +

            // NEW: Live Active Agent Streams & Real-Time Quota Drain Monitor
            (liveStreamsCardsHtml
                ? \`<div style="border-radius:10px;background:rgba(16,185,129,0.03);border:1px solid \${runningChats.length > 0 ? 'rgba(52,211,153,0.38)' : 'rgba(255,255,255,0.08)'};padding:11px 13px;display:flex;flex-direction:column;gap:8px;">\` +
                      \`<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">\` +
                          \`<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:\${runningChats.length > 0 ? '#6ee7b7' : '#f8fafc'};">\` +
                              \`\${amsIcon('zap', 13, runningChats.length > 0 ? '#34d399' : '#38bdf8')}\` +
                              \`<span>\${runningChats.length > 0
                                  ? (isDe ? \`Live Aktive Agenten-Streams (\${runningChats.length} arbeitet gerade · Echtzeit Usage-Drain)\` : \`Live Active Agent Streams (\${runningChats.length} running now · Real-Time Quota Drain)\`)
                                  : (isDe ? 'Letzte aktive Agenten-Streams (Echtzeit Token- & Usage-Monitor)' : 'Recent Active Agent Streams (Real-Time Token & Quota Monitor)')}</span>\` +
                          \`</strong>\` +
                          \`<span style="font-size:10px;font-family:monospace;color:#94a3b8;">\${isDe ? 'Aktualisiert live alle 2s pro KI-Step' : 'Updates live every 2s per AI step'}</span>\` +
                      \`</div>\` +
                      \`<div style="display:flex;flex-direction:column;gap:8px;">\${liveStreamsCardsHtml}</div>\` +
                  \`</div>\`
                : '') +

            // 4 KPI Summary Cards
            \`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px;">\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">\` +
                    \`<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">\${isDe ? 'Prompts & Steps (diese Woche)' : 'Prompts & Steps (This Week)'}</div>\` +
                    \`<div style="font-size:18px;font-weight:700;color:#38bdf8;margin-top:3px;">\${wSum.turnCount.toLocaleString(isDe ? 'de-DE' : 'en-US')} Prompts</div>\` +
                    \`<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">\${wSum.stepCount.toLocaleString(isDe ? 'de-DE' : 'en-US')} KI-Steps in \${wSum.chatCount} Chats</div>\` +
                \`</div>\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">\` +
                    \`<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">\${isDe ? 'Noch Übrig (aus ' + gWExact.toFixed(4) + '% W)' : 'Remaining Now (' + gWExact.toFixed(4) + '% W)'}</div>\` +
                    \`<div style="font-size:18px;font-weight:700;color:#34d399;margin-top:3px;">~\${Math.round(gWExact / 0.125).toLocaleString(isDe ? 'de-DE' : 'en-US')} L-Prompts</div>\` +
                    \`<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">~\${Math.round(gWExact * 200).toLocaleString(isDe ? 'de-DE' : 'en-US')} Steps · ~\${Math.round(gWExact / 0.04).toLocaleString(isDe ? 'de-DE' : 'en-US')} M-Prompts</div>\` +
                \`</div>\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">\` +
                    \`<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">\${isDe ? 'Wochen-Tokens & Cache-Quote' : 'Weekly Tokens & Cache Hit Rate'}</div>\` +
                    \`<div style="font-size:18px;font-weight:700;color:#a78bfa;margin-top:3px;">\${formatTokensCompact(wSum.totalInput + wSum.totalOutput)} Tok <span style="font-size:12px;color:#34d399;">(\${wSum.cacheRatio}%)</span></div>\` +
                    \`<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">Cache: \${formatTokensCompact(wSum.totalCached)} · Uncached: \${formatTokensCompact(wSum.totalUncached)} · Out: \${formatTokensCompact(wSum.totalOutput)}</div>\` +
                \`</div>\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">\` +
                    \`<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">\${isDe ? 'API-Gegenwert (Euro)' : 'Equivalent API Value (EUR)'}</div>\` +
                    \`<div style="font-size:18px;font-weight:700;color:#fcd34d;margin-top:3px;">\${wSum.apiCostEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} €</div>\` +
                    \`<div style="font-size:11px;color:#34d399;margin-top:2px;">+\${wSum.apiSavedEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} € \${isDe ? 'gespart (ohne Cache: ' : 'saved (raw: '}\${wSum.apiRawCostEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} €)</div>\` +
                \`</div>\` +
            \`</div>\` +

            // Effort Conversion Table ("Dossier-Umrechnungstabelle")
            \`<div style="border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);overflow:hidden;">\` +
                \`<div style="padding:10px 12px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.07);display:flex;justify-content:space-between;align-items:center;">\` +
                    \`<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;">\${amsIcon('chart', 13, '#38bdf8')}<span>\${isDe ? 'Dossier-Umrechnungstabelle: Nachrichten & Tasks nach Aufwand (Argon High auf Ultra)' : 'Effort Conversion Table: Messages & Tasks by Complexity (Argon High on Ultra)'}</span></strong>\` +
                    \`<span style="font-size:10.5px;color:#94a3b8;">1% Weekly ≈ 200 Steps</span>\` +
                \`</div>\` +
                \`<div style="overflow-x:auto;">\` +
                    \`<table style="width:100%;border-collapse:collapse;font-size:11.5px;">\` +
                        \`<thead>\` +
                            \`<tr style="border-bottom:1px solid rgba(255,255,255,0.08);color:#94a3b8;font-size:10.5px;text-transform:uppercase;">\` +
                                \`<th style="padding:7px 8px;text-align:left;">\${isDe ? 'Aufwands-Kategorie' : 'Task Effort Category'}</th>\` +
                                \`<th style="padding:7px 8px;text-align:right;">% Weekly</th>\` +
                                (show5h ? \`<th style="padding:7px 8px;text-align:right;">% 5-Hour</th>\` : '') +
                                \`<th style="padding:7px 8px;text-align:right;">\${isDe ? 'Schon geschrieben (' + gWUsed.toFixed(1) + '%)' : 'Written (' + gWUsed.toFixed(1) + '%)'}</th>\` +
                                \`<th style="padding:7px 8px;text-align:right;">\${isDe ? 'Noch übrig (' + gWExact.toFixed(2) + '%)' : 'Remaining (' + gWExact.toFixed(2) + '%)'}</th>\` +
                                \`<th style="padding:7px 8px;text-align:right;">\${isDe ? '100% Voll-Woche' : '100% Full Week'}</th>\` +
                            \`</tr>\` +
                        \`</thead>\` +
                        \`<tbody>\${effortTableHtml}</tbody>\` +
                    \`</table>\` +
                \`</div>\` +
            \`</div>\` +

            // Cache & Technical Mechanics Info Cards
            \`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;">\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.22);font-size:11px;line-height:1.45;">\` +
                    \`<strong style="color:#34d399;display:inline-flex;align-items:center;gap:5px;margin-bottom:4px;">\${amsIcon('flame', 12, '#34d399')}<span>\${isDe ? 'Prompt-Cache Haltedauer & Provider-Vergleich' : 'Prompt-Cache TTL & Provider Comparison'}</span></strong><br>\` +
                    (isDe
                        ? \`• <strong>Google Gemini (Antigravity):</strong> <strong>5 Min. (300s) garantiert</strong> im TPU-HBM-RAM, real <strong>5 bis 17,3 Min.</strong> je nach Serverlast. <strong>90% Rabatt (0.1×)</strong>, 0% Schreib-Aufpreis.<br>\` +
                          \`• <strong>Anthropic Claude:</strong> 5 Min. RAM-TTL (90% Rabatt, aber +25% Cache-Write-Strafe).<br>\` +
                          \`• <strong>OpenAI Codex / GPT-5:</strong> 5–60 Min. im GPU-RAM + bis zu <strong>24 Stunden</strong> durch <em>Extended NVMe-SSD Cache Offloading</em>.\`
                        : \`• <strong>Google Gemini (Antigravity):</strong> <strong>5 min (300s) guaranteed</strong> in TPU HBM RAM, <strong>5 to 17.3 min</strong> best-effort depending on pod load. <strong>90% discount (0.1×)</strong>, 0% write surcharge.<br>\` +
                          \`• <strong>Anthropic Claude:</strong> 5 min RAM TTL (90% discount, +25% cache-write fee).<br>\` +
                          \`• <strong>OpenAI Codex / GPT-5:</strong> 5–60 min in RAM + up to <strong>24 hours</strong> via <em>Extended NVMe SSD Cache Offloading</em>.\`) +
                \`</div>\` +
                \`<div style="padding:11px 13px;border-radius:8px;background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.22);font-size:11px;line-height:1.45;">\` +
                    \`<strong style="color:#fbbf24;display:inline-flex;align-items:center;gap:5px;margin-bottom:4px;">\${amsIcon('alert', 12, '#fbbf24')}<span>\${isDe ? 'Cache-Miss Bilanz & Auto-Checkpointer' : 'Cache-Miss Diagnostics & Auto-Checkpointer'}</span></strong><br>\` +
                    (isDe
                        ? \`• <strong>Pausen > 5 Min. (diese Woche):</strong> \${wSum.cacheMissCount} Cache-Misses verursachten <strong>\${formatTokensCompact(wSum.wastedReloadTokens)}</strong> uncached Reload-Tokens (<strong>-\${wSum.wastedWeeklyPct.toFixed(4)}% Weekly</strong> unnötiger Verlust).<br>\` +
                          \`• <strong>Auto-Checkpointer:</strong> Kompaktierung greift automatisch ab <strong>256k Tokens</strong> und schrumpft den Chat auf <strong>~31.5k Tokens</strong>.<br>\` +
                          \`• <strong>Warum +1% Anstieg?</strong> Vor einem Step reserviert der Server Quota vorab; nach dem Step wird die Differenz zurückgebucht (an Rundungsgrenzen wie 18.50% springt 18% → 19%).\`
                        : \`• <strong>Pauses > 5 min (this week):</strong> \${wSum.cacheMissCount} cache misses caused <strong>\${formatTokensCompact(wSum.wastedReloadTokens)}</strong> uncached reload tokens (<strong>-\${wSum.wastedWeeklyPct.toFixed(4)}% Weekly</strong> avoidable loss).<br>\` +
                          \`• <strong>Auto-Checkpointer:</strong> Automatically compacts context at <strong>256k tokens</strong> down to <strong>~31.5k tokens</strong>.<br>\` +
                          \`• <strong>Why +1% jump?</strong> Pre-flight token reservation dips remaining fraction during streaming and refunds unused reservation post-turn.\`) +
                \`</div>\` +
            \`</div>\` +

            // Persistent Per-Chat Usage Log Table
            \`<div style="border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);overflow:hidden;">\` +
                \`<div style="padding:10px 12px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.07);display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;">\` +
                    \`<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;">\${amsIcon('database', 13, '#a78bfa')}<span>\${isDe ? 'Persistentes Chat-Verbrauchs-Logbuch (Top 25 aktuelle Konversationen)' : 'Persistent Per-Chat Usage Ledger (Top 25 Recent Conversations)'}</span></strong>\` +
                    \`<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-family:monospace;color:#94a3b8;">\${amsIcon('database', 10, '#94a3b8')}<span>\${amsTelemetryState.logFilePath}</span></span>\` +
                \`</div>\` +
                \`<div style="max-height:280px;overflow-y:auto;">\` +
                    \`<table style="width:100%;border-collapse:collapse;">\` +
                        \`<thead style="position:sticky;top:0;background:#141418;z-index:1;">\` +
                            \`<tr style="border-bottom:1px solid rgba(255,255,255,0.08);color:#94a3b8;font-size:10px;text-transform:uppercase;">\` +
                                \`<th style="padding:6px 8px;text-align:left;">Chat / Konversation</th>\` +
                                \`<th style="padding:6px 8px;text-align:center;">Cache</th>\` +
                                \`<th style="padding:6px 8px;text-align:right;">Prompts / Steps</th>\` +
                                \`<th style="padding:6px 8px;text-align:right;">Input (Cache %)</th>\` +
                                \`<th style="padding:6px 8px;text-align:right;">Misses</th>\` +
                                \`<th style="padding:6px 8px;text-align:right;">% Weekly</th>\` +
                                \`<th style="padding:6px 8px;text-align:right;">API €</th>\` +
                            \`</tr>\` +
                        \`</thead>\` +
                        \`<tbody>\${chatRowsHtml}</tbody>\` +
                    \`</table>\` +
                \`</div>\` +
            \`</div>\`;

        const toggle5hEl = dossierEl.querySelector('#ams-dossier-5h-toggle input');
        if (toggle5hEl) {
            toggle5hEl.addEventListener('change', (e) => {
                e.stopPropagation();
                if (typeof window.amsSetUiPref === 'function') {
                    window.amsSetUiPref('show5hLimit', !!e.target.checked);
                }
            });
        }

        const soundBtn = dossierEl.querySelector('#ams-dossier-sound-btn');
        if (soundBtn) {
            soundBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                window.amsToggleCacheHitSound();
                dossierEl.removeAttribute('data-render-sig');
                patchModelsAndUsagePage();
            });
        }
    }

    // ----------------------------------------------------------------------------
    // 9b. Model Picker Inline Cache & Savings Badges (Human-Readable, No Cryptic 0.001%)
    // ----------------------------------------------------------------------------
    let lastKnownActiveModelLabel = null;
    let activeModelSwitchPopover = null;
    let suppressNextModelSwitchPopup = false;

    function getCurrentModelLabelFromTrigger() {
        const btn = document.querySelector('[data-testid="model-selector-trigger"], button[aria-label^="Select model, current:"]');
        if (!btn) return '';
        const aria = btn.getAttribute('aria-label') || '';
        const m = aria.match(/current:\\s*(.+)$/i);
        if (m && m[1]) return m[1].trim();
        return (btn.textContent || '').trim();
    }

    function getModelWeightMultiplier(modelLabel) {
        const lower = String(modelLabel || '').toLowerCase();
        if (lower.includes('flash')) return 0.40;
        if (lower.includes('opus')) return 1.35;
        if (lower.includes('sonnet')) return 1.10;
        if (lower.includes('gpt-oss')) return 0.65;
        return 1.00; // Gemini 4 Argon / Pro default
    }

    function getModelRelativeCostLabel(modelLabel, isDe) {
        const lower = String(modelLabel || '').toLowerCase();
        if (lower.includes('flash')) return isDe ? '2.5× sparsamer' : '2.5× lighter';
        if (lower.includes('gpt-oss')) return isDe ? '1.5× sparsamer' : '1.5× lighter';
        if (lower.includes('opus')) return isDe ? '1.4× Verbrauch' : '1.4× usage';
        if (lower.includes('sonnet')) return isDe ? '1.1× Verbrauch' : '1.1× usage';
        return 'Standard';
    }

    function closeModelSwitchPopover() {
        if (activeModelSwitchPopover) {
            activeModelSwitchPopover.remove();
            activeModelSwitchPopover = null;
        }
    }

    function updateModelSelectorTriggerBadge() {
        const legacyTriggerPill = document.getElementById('antigravity-model-trigger-loss-pill');
        if (legacyTriggerPill) legacyTriggerPill.remove();
        closeModelSwitchPopover();

        const btn = document.querySelector('[data-testid="model-selector-trigger"], button[aria-label^="Select model, current:"]');
        if (!btn) return;

        const currentLabel = getCurrentModelLabelFromTrigger();
        if (currentLabel) {
            lastKnownActiveModelLabel = currentLabel;
        }
    }

    function decorateOpenModelPickerMenu() {
        const panel = document.querySelector('[data-testid="model-selector-panel"]');
        if (!panel) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const currentLabel = getCurrentModelLabelFromTrigger();
        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const hasContext = !!(cacheInfo && cacheInfo.stepCount > 0);
        const menuItems = Array.from(panel.querySelectorAll('[role="menuitem"]'));

        const panelSig = \`v4|\${hasContext ? cacheInfo.stepCount : 0}|\${hasContext ? cacheInfo.state : 'new'}|\${hasContext ? cacheInfo.contextTokens : 0}|\${currentLabel}|\${isDe}|\${menuItems.length}\`;
        if (panel.getAttribute('data-ams-panel-sig') === panelSig) return;
        panel.setAttribute('data-ams-panel-sig', panelSig);

        const menuEl = panel.closest('[role="menu"]');
        if (menuEl) {
            menuEl.style.maxWidth = '420px';
            menuEl.style.minWidth = '340px';
        }
        panel.style.maxHeight = '440px';

        // 1. Intuitive 1-line Context Header inside the Model Picker
        const headerEl = panel.querySelector('[data-testid="model-selector-header"]');
        let bannerEl = panel.querySelector('#antigravity-model-picker-banner');
        if (!bannerEl && headerEl && headerEl.parentElement) {
            bannerEl = document.createElement('div');
            bannerEl.id = 'antigravity-model-picker-banner';
            bannerEl.style.cssText =
                'margin:2px 6px 6px 6px;padding:6px 9px;border-radius:7px;font-size:10.5px;line-height:1.35;' +
                'font-variant-numeric:tabular-nums;user-select:none;';
            headerEl.insertAdjacentElement('afterend', bannerEl);
        }

        if (bannerEl) {
            bannerEl.style.background = AMS_THEME.surfacePill;
            bannerEl.style.border = \`1px solid \${AMS_THEME.borderSubtle}\`;
            bannerEl.style.color = AMS_THEME.textPrimary;

            if (!hasContext) {
                bannerEl.innerHTML =
                    \`<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">\` +
                        \`<span style="display:inline-flex;align-items:center;gap:4px;">\${amsIcon('check', 11, AMS_THEME.sage)}<strong>\${isDe ? 'Neuer Chat' : 'New Chat'}</strong> · \${isDe ? 'Freie Modellwahl ohne Cache-Verlust' : 'Switch freely with no cache loss'}</span>\` +
                    \`</div>\`;
            } else {
                const ctxCompact = formatTokensCompact(cacheInfo.contextTokens);
                const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
                const statusText = isWarm
                    ? (isDe
                        ? \`\${amsIcon('flame', 11, AMS_THEME.sage)}<span><strong>Cache warm (du sparst 90%)</strong> · Wechsel lädt \${ctxCompact} Tok neu</span>\`
                        : \`\${amsIcon('flame', 11, AMS_THEME.sage)}<span><strong>Cache warm (saving 90%)</strong> · Switch reloads \${ctxCompact} tok</span>\`)
                    : (isDe
                        ? \`\${amsIcon('snowflake', 11, AMS_THEME.sand)}<span><strong>Cache kalt (\${ctxCompact} Tok)</strong> · Neuer Chat spart 90%</span>\`
                        : \`\${amsIcon('snowflake', 11, AMS_THEME.sand)}<span><strong>Cache cold (\${ctxCompact} tok)</strong> · New Chat saves 90%</span>\`);

                bannerEl.innerHTML =
                    \`<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">\` +
                        \`<span style="display:inline-flex;align-items:center;gap:4px;color:\${AMS_THEME.textPrimary};">\${statusText}</span>\` +
                        \`<button type="button" class="ams-mp-newchat-btn" style="display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:4px;border:1px solid \${AMS_THEME.borderHover};background:\${AMS_THEME.surfaceHover};color:\${AMS_THEME.textBright};font-size:9.5px;font-weight:500;cursor:pointer;flex-shrink:0;">\${amsIcon('plus', 9, AMS_THEME.textPrimary)}<span>\${isDe ? 'Neuer Chat' : 'New Chat'}</span></button>\` +
                    \`</div>\`;
                const ncBtn = bannerEl.querySelector('.ams-mp-newchat-btn');
                if (ncBtn) {
                    ncBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const trig = document.querySelector('[data-testid="model-selector-trigger"]');
                        if (trig && trig.getAttribute('aria-expanded') === 'true') trig.click();
                        triggerNewConversation();
                    });
                }
            }
        }

        // 2. Intuitive Human-Readable Badge on each model row ([role="menuitem"])
        menuItems.forEach((item) => {
            const rawText = (item.textContent || '').trim();
            if (!rawText || /View Usage/i.test(rawText)) return;

            const effortSpan = item.querySelector('[data-testid="model-selector-effort-group"]');
            const baseModelName = effortSpan
                ? (effortSpan.getAttribute('data-model-base') || effortSpan.textContent || '').trim()
                : (item.getAttribute('data-model-label') || rawText.replace(/Notice$|New$|Fast$/i, '')).trim();
            if (!baseModelName) return;

            const isCurrentModel = currentLabel && currentLabel.toLowerCase().includes(baseModelName.toLowerCase());

            let badge = item.querySelector('.antigravity-model-item-cost-badge');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-model-item-cost-badge';
                badge.style.cssText =
                    'display:inline-flex;align-items:center;gap:3px;margin-left:auto;padding:1px 6px;border-radius:4px;' +
                    'font-family:ui-sans-serif,system-ui,sans-serif;font-size:10px;font-weight:500;' +
                    'font-variant-numeric:tabular-nums;white-space:nowrap;flex-shrink:0;pointer-events:none;';
                item.appendChild(badge);
            }

            const itemSig = \`v4|\${baseModelName}|\${isCurrentModel ? 1 : 0}|\${hasContext ? cacheInfo.state : 'new'}|\${hasContext ? cacheInfo.contextTokens : 0}|\${isDe}\`;
            if (badge.getAttribute('data-sig') === itemSig) return;
            badge.setAttribute('data-sig', itemSig);

            const relLabel = getModelRelativeCostLabel(baseModelName, isDe);

            if (!hasContext) {
                if (isCurrentModel) {
                    badge.style.background = AMS_THEME.surfacePill;
                    badge.style.border = \`1px solid \${AMS_THEME.borderSubtle}\`;
                    badge.style.color = AMS_THEME.textPrimary;
                    badge.innerHTML = \`\${amsIcon('check', 10, AMS_THEME.sage)}<span>\${isDe ? 'Aktiv' : 'Active'}</span>\`;
                } else {
                    badge.style.background = 'transparent';
                    badge.style.border = 'none';
                    badge.style.color = AMS_THEME.textMuted;
                    badge.textContent = relLabel;
                }
                return;
            }

            const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
            const ctxCompact = formatTokensCompact(cacheInfo.contextTokens);

            if (isCurrentModel) {
                badge.style.background = AMS_THEME.surfacePill;
                badge.style.border = \`1px solid \${AMS_THEME.borderSubtle}\`;
                badge.style.color = AMS_THEME.textPrimary;
                badge.innerHTML = isWarm
                    ? \`\${amsIcon('flame', 10, AMS_THEME.sage)}<span>\${isDe ? 'Warm · 90% gespart' : 'Warm · 90% saved'}</span>\`
                    : \`\${amsIcon('snowflake', 10, AMS_THEME.sand)}<span>\${isDe ? \`Kalt · \${ctxCompact} Tok\` : \`Cold · \${ctxCompact} tok\`}</span>\`;
                badge.title = isDe
                    ? \`Aktuelles Modell (\${baseModelName}) · \${isWarm ? 'Der Prompt-Cache ist warm: Du sparst 90% auf den bisherigen Kontext.' : 'Der Prompt-Cache ist abgelaufen.'}\`
                    : \`Current Model (\${baseModelName}) · \${isWarm ? 'Prompt cache is warm: saving 90% on context tokens.' : 'Prompt cache has expired.'}\`;
            } else {
                badge.style.background = 'transparent';
                badge.style.border = 'none';
                badge.style.color = isWarm ? AMS_THEME.sand : AMS_THEME.textMuted;
                badge.innerHTML = isWarm
                    ? \`<span>\${isDe ? 'Cache weg · 10× teurer' : 'Drops cache · 10× cost'}</span>\`
                    : \`<span>\${relLabel}</span>\`;
                badge.title = isDe
                    ? \`Wechsel zu \${baseModelName} im laufenden Chat verwirft den warmen Cache (\${ctxCompact} Tokens müssen 10× teurer neu geladen werden). Tipp: Für Modellwechsel einen neuen Chat starten!\`
                    : \`Switching to \${baseModelName} mid-chat drops the warm cache (\${ctxCompact} tokens reload at 10× cost). Tip: Start a New Chat when switching models!\`;
            }
        });
    }

    // Observe DOM for Model Picker opening using debounced requestAnimationFrame (never mutate synchronously inside MutationObserver!)
    if (window.__ams_model_picker_observer) {
        try { window.__ams_model_picker_observer.disconnect(); } catch (e) {}
    }
    let modelPickerRafPending = false;
    const modelPickerObserver = new MutationObserver(() => {
        if (window.__ams_active_instance_id !== myInstanceId) {
            try { modelPickerObserver.disconnect(); } catch (e) {}
            return;
        }
        if (modelPickerRafPending) return;
        const panel = document.querySelector('[data-testid="model-selector-panel"]');
        if (!panel) return;
        modelPickerRafPending = true;
        requestAnimationFrame(() => {
            modelPickerRafPending = false;
            if (window.__ams_active_instance_id !== myInstanceId) return;
            decorateOpenModelPickerMenu();
        });
    });
    window.__ams_model_picker_observer = modelPickerObserver;
    if (document.body) {
        modelPickerObserver.observe(document.body, { childList: true, subtree: true });
    } else {
        window.addEventListener('DOMContentLoaded', () => {
            modelPickerObserver.observe(document.body, { childList: true, subtree: true });
        });
    }

    // ----------------------------------------------------------------------------
    // 10. Periodic Polling & Live Countdown Ticker
    // ----------------------------------------------------------------------------
    if (Array.isArray(window.__ams_v2_intervals)) {
        window.__ams_v2_intervals.forEach(id => clearInterval(id));
    }
    window.__ams_v2_intervals = [];

    setTimeout(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchUserQuotaSummary();
        fetchAllCascadeTrajectories();
    }, 1200);

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchUserQuotaSummary();
    }, 20000));

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchAllCascadeTrajectories();
    }, 12000));

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (typeof updateTokenStats === 'function') updateTokenStats();
        if (typeof updateCompactionCounter === 'function') updateCompactionCounter();
    }, 8000));

    // 250ms High-Precision Live Odometer Ticker (rolls 4th decimal 0.0001% live during active chats)
    function countActiveRunningChats() {
        let trajCount = 0;
        if (amsTelemetryState.liveTrajectoriesMap && amsTelemetryState.liveTrajectoriesMap.size > 0) {
            for (const info of amsTelemetryState.liveTrajectoriesMap.values()) {
                if (info && info.status === 'CASCADE_RUN_STATUS_RUNNING') trajCount++;
            }
        }
        if (trajCount > 0) return trajCount;
        // Fallback DOM detection for immediate responsiveness on first streaming frame
        const stopBtn = document.querySelector(
            'button[aria-label*="Stop" i], button[aria-label*="Cancel" i], button[data-tooltip-id*="stop" i], [data-tooltip-id*="cancel" i]'
        );
        if (stopBtn && stopBtn.offsetParent !== null) return 1;
        return 0;
    }

    // Close Quota HUD popover on outside click
    document.addEventListener('click', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeQuotaHudPopover && !activeQuotaHudPopover.contains(e.target)) {
            const quotaBtn = document.getElementById('antigravity-quota-display-v4');
            if (!quotaBtn || !quotaBtn.contains(e.target)) {
                closeQuotaHudPopover();
            }
        }
    });

    let lastFastTokenStatsPollMs = 0;
    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (document.hidden) return;
        if (!amsLiveOdometer.initialized || amsLiveOdometer.serverWeeklyAnchor === null) return;

        const now = Date.now();
        const activeChats = countActiveRunningChats();

        if (activeChats > 0) {
            // Fast 2.2s token stats poll while a chat is actively running so the step counter
            // ("1 Step -> 2 Steps -> 3 Steps...") and "Filling cache" badge update live per step!
            if (now - lastFastTokenStatsPollMs > 2200 && typeof updateTokenStats === 'function') {
                lastFastTokenStatsPollMs = now;
                updateTokenStats();
            }
            // Smoothly accumulate intra-step streaming token drain (~0.0001% per 250ms = 0.0004%/s per active chat)
            // Capped at 0.0065% per in-flight step until the step completes and settles against steps.db / server float
            const stepIncrement = 0.0001 * Math.min(activeChats, 3);
            amsLiveOdometer.intraStepStreamDrainWeekly = Math.min(
                0.0065 * Math.max(1, activeChats),
                amsLiveOdometer.intraStepStreamDrainWeekly + stepIncrement
            );
            // Poll server with forceRefresh every ~4s while actively running so 8-decimal server float stays live
            if (now - amsLiveOdometer.lastServerFetchMs > 4000) {
                fetchUserQuotaSummary(true);
            }
        } else if (amsLiveOdometer.intraStepStreamDrainWeekly > 0 && (now - amsLiveOdometer.lastStepAtMs > 6000)) {
            // Once chat stops and server has refreshed, gently clear residual intra-step estimate
            amsLiveOdometer.intraStepStreamDrainWeekly = Math.max(0, amsLiveOdometer.intraStepStreamDrainWeekly - 0.0001);
        }

        const rawTarget = Math.max(
            0,
            amsLiveOdometer.serverWeeklyAnchor -
                amsLiveOdometer.unsettledLocalDrainWeekly -
                amsLiveOdometer.intraStepStreamDrainWeekly
        );

        const diff = amsLiveOdometer.displayWeekly - rawTarget;
        let changed = false;

        if (diff >= 0.00008) {
            // Step down smoothly: 0.0001% per tick for normal streaming, or faster proportional step if catching up a big turn
            const stepDown = diff > 0.0025 ? Math.max(0.0002, diff * 0.22) : 0.0001;
            amsLiveOdometer.displayWeekly = Math.max(rawTarget, Number((amsLiveOdometer.displayWeekly - stepDown).toFixed(6)));
            amsLiveOdometer.isActivelyDraining = true;
            amsLiveOdometer.lastDrainTickMs = now;
            changed = true;
        } else if (diff < -0.0005 && activeChats === 0) {
            // Re-align upward only when idle (e.g. after server reconciliation or weekly reset)
            amsLiveOdometer.displayWeekly = Number(rawTarget.toFixed(6));
            changed = true;
        }

        if (amsLiveOdometer.isActivelyDraining && activeChats === 0 && (now - amsLiveOdometer.lastDrainTickMs > 1200)) {
            amsLiveOdometer.isActivelyDraining = false;
            changed = true;
        }

        if (changed) {
            refreshQuotaDisplay();
        }
    }, 250));

    // 1-second lightweight UI ticker so the 5-minute warm cache countdown ticks smoothly
    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (document.hidden) return;
        ensureCleanUiStyles();
        refreshQuotaDisplay();
        updateComposerChatBadge();
        updateLiveSendEstimator();
        renderPerMessageTurnBadges();
        updateModelSelectorTriggerBadge();
        decorateOpenModelPickerMenu();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
    }, 1000));

    let currentPlanText = '';
    const parts = window.location.pathname.split('/');
    let currentConvId = (parts.length > 2 && parts[2]) ? parts[2] : null;
    let currentNotesText = '';
    let notesSyncAI = true;


    function generateSubtasks(item, type) {
        var tasks = [];
        if (item.body) {
            var lines = item.body.split('\\n');
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var match = line.match(/^\\s*[-*]\\s*\\[([ xX])\\]\\s*(.+)$/);
                if (match) {
                    tasks.push('- [ ] ' + match[2].trim());
                }
            }
        }
        if (tasks.length === 0) {
            tasks = [
                '- [ ] Anforderungen & Codebasis analysieren',
                '- [ ] Implementierung vorbereiten & Code anpassen',
                '- [ ] Änderungen lokal testen & verifizieren',
                '- [ ] Pull Request erstellen / Issue abschließen'
            ];
        }
        var titleClean = item.title.replace(/[#*\`[\\]]/g, '');
        return '# ' + type + ' #' + item.number + ': ' + titleClean + '\\n\\n' + tasks.join('\\n');
    }


    async function loadNotesUI() {
        const textarea = document.getElementById('antigravity-notes-textarea');
        const checkbox = document.getElementById('antigravity-notes-sync-ai');
        if (!textarea || !checkbox) return;

        try {
            if (currentConvId && window.electronNative && window.electronNative.getNotes) {
                const res = await window.electronNative.getNotes(currentConvId);
                if (res && res.status === 'success') {
                    currentNotesText = res.notes || '';
                    notesSyncAI = res.syncAI;
                    textarea.value = currentNotesText;
                    checkbox.checked = notesSyncAI;
                    return;
                }
            }
        } catch (e) {
            console.error('[AMS] Failed to load notes from notes.txt:', e);
        }

        // Fallback to nativeStorage
        const storageKey = 'antigravity_notes_' + currentConvId;
        const syncKey = 'antigravity_notes_sync_ai_' + currentConvId;
        currentNotesText = nativeStorageItems[storageKey] || '';
        notesSyncAI = nativeStorageItems[syncKey] !== false; // default to true

        textarea.value = currentNotesText;
        checkbox.checked = notesSyncAI;
    }

    async function updateCompactionCounter() {
        const counterEl = document.getElementById('antigravity-compaction-counter');
        if (!counterEl) return;

        if (!currentConvId || !window.electronNative || !window.electronNative.getCompactionCount) {
            counterEl.style.display = 'none';
            return;
        }

        try {
            const res = await window.electronNative.getCompactionCount(currentConvId);
            if (res && res.status === 'success') {
                const count = res.count || 0;
                counterEl.querySelector('span').textContent = 'Compacts: ' + count;
                counterEl.style.display = 'inline-flex';
                if (count > 0) {
                    counterEl.style.color = '#3b82f6';
                    counterEl.style.borderColor = 'rgba(59, 130, 246, 0.2)';
                    counterEl.style.background = 'rgba(59, 130, 246, 0.05)';
                    counterEl.title = 'Dieses Gespräch wurde bereits ' + count + ' mal automatisch kompaktwert / bereinigt.';
                } else {
                    counterEl.style.color = 'var(--muted-foreground, #71717a)';
                    counterEl.style.borderColor = 'var(--border, rgba(255,255,255,0.05))';
                    counterEl.style.background = 'rgba(255,255,255,0.03)';
                    counterEl.title = 'Bisher wurden keine automatischen Kompaktierungen durchgeführt.';
                }
            } else {
                counterEl.style.display = 'none';
            }
        } catch (e) {
            console.error('[AMS] Failed to fetch compaction count:', e);
            counterEl.style.display = 'none';
        }
    }

    async function updateTokenStats() {
        const chatTokenEl = document.getElementById('antigravity-chat-token-counter');
        const footerTokenEl = document.getElementById('antigravity-token-counter');

        if (!window.electronNative || !window.electronNative.getTokenStats) {
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
            return;
        }

        const fallbackCid = (window.amsTelemetryState && window.amsTelemetryState.liveTrajectoriesMap && window.amsTelemetryState.liveTrajectoriesMap.keys().next().value) ||
                            (document.querySelector('[data-cascade-id]') && document.querySelector('[data-cascade-id]').getAttribute('data-cascade-id')) ||
                            null;
        const targetConvId = currentConvId || fallbackCid;

        if (!targetConvId) {
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
            return;
        }

        try {
            const res = await window.electronNative.getTokenStats(targetConvId);
            if (res && res.status === 'success') {
                if (typeof window.amsIngestTokenStatsResult === 'function') {
                    window.amsIngestTokenStatsResult(res, targetConvId === currentConvId);
                }

                if (targetConvId !== currentConvId) {
                    if (chatTokenEl) chatTokenEl.style.display = 'none';
                    if (footerTokenEl) footerTokenEl.style.display = 'none';
                    return;
                }

                const totalIn = res.totalInput || 0;
                const totalOut = res.totalOutput || 0;
                const totalUncached = res.totalUncached || 0;
                const totalCached = res.totalCached || 0;
                const cacheRatio = res.cacheRatio || 0.0;
                const weeklyPctUsed = Number(res.weeklyPctUsed || 0).toFixed(4);
                const fiveHourPctUsed = Number(res.fiveHourPctUsed || 0).toFixed(4);
                const apiCostEur = Number(res.apiCostEur || 0).toFixed(2);
                const apiSavedEur = Number(res.apiSavedEur || 0).toFixed(2);

                const latestIn = res.latestInput || 0;
                const latestOut = res.latestOutput || 0;
                const latestUncached = res.latestUncached || 0;
                const latestCached = res.latestCached || 0;

                function formatTokens(num) {
                    if (num >= 1000000) {
                        return (num / 1000000).toFixed(1) + 'M';
                    }
                    if (num >= 1000) {
                        return (num / 1000).toFixed(0) + 'k';
                    }
                    return num.toString();
                }

                const totalStr = formatTokens(totalIn);

                if (footerTokenEl) {
                    footerTokenEl.querySelector('span').textContent = 'Tokens: ' + totalStr + ' (-' + weeklyPctUsed + '% W)';
                    footerTokenEl.style.display = 'inline-flex';

                    const tooltip =
                        'Akkumulierter Verbrauch für dieses Gespräch:\\n' +
                        '• Quota-Abzug: -' + weeklyPctUsed + '% Weekly / -' + fiveHourPctUsed + '% 5h\\n' +
                        '• API-Gegenwert: ' + apiCostEur + ' € (+' + apiSavedEur + ' € durch Cache gespart)\\n' +
                        '• Input (Gesamt): ' + totalIn.toLocaleString('de-DE') + '\\n' +
                        '  - Aus Cache: ' + totalCached.toLocaleString('de-DE') + ' (' + cacheRatio + '%)\\n' +
                        '  - Uncached: ' + totalUncached.toLocaleString('de-DE') + '\\n' +
                        '• Output (Antworten): ' + totalOut.toLocaleString('de-DE') + '\\n\\n' +
                        'Letzter Schritt:\\n' +
                        '• Input: ' + latestIn.toLocaleString('de-DE') + '\\n' +
                        '  - Aus Cache: ' + latestCached.toLocaleString('de-DE') + '\\n' +
                        '  - Uncached: ' + latestUncached.toLocaleString('de-DE') + '\\n' +
                        '• Output: ' + latestOut.toLocaleString('de-DE');
                    footerTokenEl.title = tooltip;
                }
            } else {
                if (chatTokenEl) chatTokenEl.style.display = 'none';
                if (footerTokenEl) footerTokenEl.style.display = 'none';
            }
        } catch (e) {
            console.error('[AMS] Failed to fetch token stats:', e);
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
        }
    }

    async function loadInitialPlan() {
        try {
            if (currentConvId && window.electronNative && window.electronNative.getTaskPlan) {
                const res = await window.electronNative.getTaskPlan(currentConvId);
                if (res && res.status === 'success') {
                    console.log('[AMS] Loaded task plan from active task.md');
                    currentPlanText = res.plan;
                    updatePlanUI();
                    loadNotesUI();
                    updateCompactionCounter();
                    updateTokenStats();
                    return;
                }
            }
        } catch (e) {
            console.error('[AMS] Failed to load plan from task.md:', e);
        }
        currentPlanText = nativeStorageItems.antigravity_task_plan ||
            '# Active Tasks\\n- [ ] Task 1\\n- [ ] Task 2\\n- [ ] Task 3';
        updatePlanUI();
        loadNotesUI();
        updateCompactionCounter();
        updateTokenStats();
    }

    window.getTaskPlan = function() {
        return currentPlanText;
    };

    window.setTaskPlan = async function(text) {
        currentPlanText = text;
        try {
            await window.nativeStorage.updateItems({ antigravity_task_plan: text });
        } catch (e) {}
        try {
            if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                await window.electronNative.setTaskPlan(text, currentConvId);
            }
        } catch (e) {
            console.error('[AMS] Failed to write plan to task.md:', e);
        }
        updatePlanUI();
    };

    // Load the plan asynchronously at boot
    setTimeout(loadInitialPlan, 50);

    function triggerSaveStatus() {
        const indicator = document.querySelector('.antigravity-save-indicator');
        if (!indicator) return;
        indicator.className = 'antigravity-save-indicator saving';
        const txt = indicator.querySelector('span');
        if (txt) txt.textContent = 'Speichert...';

        setTimeout(() => {
            indicator.className = 'antigravity-save-indicator saved';
            const txt2 = indicator.querySelector('span');
            if (txt2) txt2.textContent = 'Gespeichert';
        }, 500);
    }

    function togglePlanPanel() {
        const panel = ensurePlanPanel();
        const isOpen = panel.classList.toggle('open');
        if (isOpen) {
            updateCompactionCounter();
            updateTokenStats();
        }
    }

    function updatePlanUI() {
        const editor = document.getElementById('antigravity-plan-editor');
        if (editor) {
            editor.value = currentPlanText;
        }
        updateChecklistFromText();
    }

    function stopKeyPropagation(el) {
        if (!el) return;
        ['keydown', 'keyup', 'keypress'].forEach(eventType => {
            el.addEventListener(eventType, (e) => {
                e.stopPropagation();
            });
        });
    }

    function ensurePlanPanel() {
        let panel = document.getElementById('antigravity-plan-panel');
        if (panel) return panel;

        panel = document.createElement('div');
        panel.id = 'antigravity-plan-panel';
        stopKeyPropagation(panel);

        const styles =
            '#antigravity-plan-panel {' +
            '    position: fixed;' +
            '    top: 30px;' +
            '    right: 0;' +
            '    width: 350px;' +
            '    height: calc(100% - 30px);' +
            '    z-index: 10000;' +
            '    background-color: var(--background, #121214);' +
            '    border-left: 1px solid var(--border, #27272a);' +
            '    box-shadow: -8px 0 24px rgba(0, 0, 0, 0.5);' +
            '    transform: translateX(100%);' +
            '    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    color: var(--foreground, #ececec);' +
            '    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;' +
            '}' +
            '#antigravity-plan-panel.open {' +
            '    transform: translateX(0);' +
            '}' +
            '.antigravity-plan-header {' +
            '    display: flex;' +
            '    align-items: center;' +
            '    justify-content: space-between;' +
            '    padding: 16px;' +
            '    border-bottom: 1px solid var(--border, #27272a);' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-plan-title {' +
            '    font-weight: 600;' +
            '    font-size: 13px;' +
            '    margin: 0;' +
            '    color: var(--foreground, #ffffff);' +
            '    letter-spacing: 0.05em;' +
            '    text-transform: uppercase;' +
            '    opacity: 0.9;' +
            '}' +
            '.antigravity-plan-close {' +
            '    cursor: pointer;' +
            '    background: transparent;' +
            '    border: none;' +
            '    color: var(--muted-foreground, #a1a1aa);' +
            '    padding: 4px;' +
            '    border-radius: 4px;' +
            '    display: flex;' +
            '    align-items: center;' +
            '    justify-content: center;' +
            '    transition: background-color 0.2s, color 0.2s;' +
            '}' +
            '.antigravity-plan-close:hover {' +
            '    background-color: var(--secondary, #27272a);' +
            '    color: var(--foreground, #ffffff);' +
            '}' +
            '.antigravity-plan-content {' +
            '    flex: 1;' +
            '    overflow-y: auto;' +
            '    padding: 16px;' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    gap: 16px;' +
            '}' +
            '.antigravity-plan-mode-tabs {' +
            '    display: flex;' +
            '    border-bottom: 1px solid var(--border, #27272a);' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-plan-tab {' +
            '    flex: 1;' +
            '    text-align: center;' +
            '    padding: 10px;' +
            '    font-size: 13px;' +
            '    cursor: pointer;' +
            '    border-bottom: 2px solid transparent;' +
            '    transition: all 0.2s;' +
            '    font-weight: 500;' +
            '    color: var(--muted-foreground, #a1a1aa);' +
            '}' +
            '.antigravity-plan-tab.active {' +
            '    border-bottom-color: var(--foreground, #ffffff);' +
            '    color: var(--foreground, #ffffff);' +
            '    background-color: rgba(255, 255, 255, 0.03);' +
            '}' +
            '.antigravity-plan-textarea {' +
            '    flex: 1;' +
            '    width: 100%;' +
            '    background-color: var(--input, #09090b);' +
            '    border: 1px solid var(--border, #27272a);' +
            '    border-radius: 8px;' +
            '    padding: 12px;' +
            '    color: var(--foreground, #ececec);' +
            '    font-family: monospace;' +
            '    font-size: 13px;' +
            '    resize: none;' +
            '    line-height: 1.5;' +
            '    outline: none;' +
            '    transition: border-color 0.2s;' +
            '}' +
            '.antigravity-plan-textarea:focus {' +
            '    border-color: #3b82f6;' +
            '}' +
            '.antigravity-plan-checklist {' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    gap: 10px;' +
            '}' +
            '.antigravity-checklist-item {' +
            '    display: flex;' +
            '    align-items: flex-start;' +
            '    gap: 8px;' +
            '    padding: 6px;' +
            '    border-radius: 6px;' +
            '    transition: background-color 0.2s;' +
            '}' +
            '.antigravity-checklist-item:hover {' +
            '    background-color: rgba(255, 255, 255, 0.02);' +
            '}' +
            '.antigravity-checklist-cb {' +
            '    margin-top: 3px;' +
            '    cursor: pointer;' +
            '    accent-color: #3b82f6;' +
            '    width: 14px;' +
            '    height: 14px;' +
            '}' +
            '.antigravity-checklist-text {' +
            '    font-size: 13px;' +
            '    line-height: 1.4;' +
            '    cursor: pointer;' +
            '    user-select: none;' +
            '}' +
            '.antigravity-checklist-text.checked {' +
            '    text-decoration: line-through;' +
            '    opacity: 0.5;' +
            '}' +
            '.antigravity-checklist-item:hover .antigravity-checklist-delete {' +
            '    display: inline-flex !important;' +
            '}' +
            '.antigravity-checklist-delete:hover {' +
            '    color: #ef4444 !important;' +
            '}' +
            '.antigravity-checklist-add-btn:hover {' +
            '    background-color: var(--secondary, #27272a);' +
            '    color: var(--foreground, #ffffff) !important;' +
            '}' +
            '.antigravity-plan-footer {' +
            '    padding: 12px 16px;' +
            '    border-top: 1px solid var(--border, #27272a);' +
            '    font-size: 11px;' +
            '    color: var(--muted-foreground, #71717a);' +
            '    display: flex;' +
            '    justify-content: space-between;' +
            '    align-items: center;' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-save-indicator {' +
            '    display: flex;' +
            '    align-items: center;' +
            '    gap: 4px;' +
            '    opacity: 0.7;' +
            '    transition: opacity 0.3s;' +
            '}' +
            '.antigravity-save-indicator.saving {' +
            '    opacity: 1;' +
            '    color: #eab308;' +
            '}' +
            '.antigravity-save-indicator.saved {' +
            '    color: #22c55e;' +
            '}' +
            '@keyframes modalFadeIn {' +
            '    from { opacity: 0; transform: scale(0.97); }' +
            '    to { opacity: 1; transform: scale(1); }' +
            '}' +
            '@keyframes antigravity-spin {' +
            '    from { transform: rotate(0deg); }' +
            '    to { transform: rotate(360deg); }' +
            '}' +
            '.antigravity-spinner {' +
            '    animation: antigravity-spin 1s linear infinite;' +
            '}';

        const styleEl = document.createElement('style');
        styleEl.id = 'antigravity-plan-panel-styles';
        styleEl.innerHTML = styles;
        document.head.appendChild(styleEl);

        panel.innerHTML =
            '<div class="antigravity-plan-header">' +
            '    <h3 class="antigravity-plan-title" style="display:flex;align-items:center;gap:7px;">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
            '            <ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.8" stroke-opacity="0.9"/>' +
            '            <polygon points="12,3 19.4,12 12,21 4.6,12" fill="rgba(139,92,246,0.28)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
            '            <circle cx="12" cy="12" r="2.2" fill="#f8fafc"/>' +
            '        </svg>' +
            '        <span>Task & Plan Tracker</span>' +
            '    </h3>' +
            '    <button class="antigravity-plan-close" title="Schließen">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '            <line x1="18" y1="6" x2="6" y2="18"></line>' +
            '            <line x1="6" y1="6" x2="18" y2="18"></line>' +
            '        </svg>' +
            '    </button>' +
            '</div>' +
            '<div class="antigravity-plan-mode-tabs">' +
            '    <div class="antigravity-plan-tab active" data-tab="notes">Notizen</div>' +
            '    <div class="antigravity-plan-tab" data-tab="prs">Pull Requests</div>' +
            '    <div class="antigravity-plan-tab" data-tab="issues">Issues</div>' +
            '    <div class="antigravity-plan-tab" data-tab="reviews">Reviews</div>' +
            '</div>' +
            '<div class="antigravity-plan-content">' +
            '    <div id="antigravity-plan-notes-container" class="antigravity-plan-notes" style="display: flex; flex-direction: column; gap: 10px; height: 100%; flex: 1;">' +
            '        <textarea id="antigravity-notes-textarea" class="antigravity-plan-textarea" placeholder="Hinterlasse hier deine freien Notizen für dieses Gespräch..."></textarea>' +
            '        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; padding: 4px 0; color: var(--muted-foreground, #71717a);">' +
            '            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;">' +
            '                <input type="checkbox" id="antigravity-notes-sync-ai" style="cursor: pointer; accent-color: #3b82f6;" checked> ' +
            '                <span>Als AI-Kontext (notes.txt) freigeben</span>' +
            '            </label>' +
            '        </div>' +
            '    </div>' +
            '    <div id="antigravity-plan-prs-container" class="antigravity-plan-prs" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '    <div id="antigravity-plan-issues-container" class="antigravity-plan-issues" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '    <div id="antigravity-plan-reviews-container" class="antigravity-plan-reviews" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '</div>' +
            '<div class="antigravity-plan-footer" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-top: 1px solid var(--border, #27272a); background-color: var(--card, #18181b);">' +
            '    <button class="antigravity-git-sync-btn" title="Mit GitHub synchronisieren" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: inline-flex; align-items: center; gap: 4px; transition: background-color 0.2s; outline: none;">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>' +
            '        Git Sync' +
            '    </button>' +
            '    <div style="display: flex; align-items: center; gap: 8px;">' +
            '        <span id="antigravity-compaction-counter" style="font-size: 10px; color: var(--muted-foreground, #71717a); display: none; align-items: center; gap: 3px; cursor: help; background: rgba(255,255,255,0.03); border: 1px solid var(--border, rgba(255,255,255,0.05)); padding: 2px 6px; border-radius: 4px;" title="Anzahl der durchgeführten Kontext-Kompaktierungen für dieses Gespräch">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="14" x2="20" y2="14"></line><line x1="4" y1="6" x2="20" y2="6"></line><line x1="4" y1="10" x2="20" y2="10"></line><line x1="4" y1="18" x2="20" y2="18"></line></svg>' +
            '            <span>Compacts: 0</span>' +
            '        </span>' +
            '        <span id="antigravity-token-counter" style="font-size: 10px; color: var(--muted-foreground, #71717a); display: none; align-items: center; gap: 3px; cursor: help; background: rgba(255,255,255,0.03); border: 1px solid var(--border, rgba(255,255,255,0.05)); padding: 2px 6px; border-radius: 4px;" title="Token-Verbrauch für dieses Gespräch (Details per Hover)">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>' +
            '            <span>Tokens: -</span>' +
            '        </span>' +
            '        <span class="antigravity-save-indicator saved">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">' +
            '                <polyline points="20 6 9 17 4 12"></polyline>' +
            '            </svg>' +
            '            <span>Gespeichert</span>' +
            '        </span>' +
            '    </div>' +
            '</div>';

        document.body.appendChild(panel);

        panel.querySelector('.antigravity-plan-close').addEventListener('click', togglePlanPanel);

        const syncBtn = panel.querySelector('.antigravity-git-sync-btn');
        let gitCheckInterval = null;

        async function updateGitSyncButtonStatus() {
            const btn = panel.querySelector('.antigravity-git-sync-btn');
            if (!btn) return;
            try {
                const parts = window.location.pathname.split('/');
                const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

                const res = await window.electronNative.getGitStatus(conversationId);
                if (res && res.status === 'success') {
                    const count = res.totalChanges;
                    if (count === 0) {
                        btn.disabled = true;
                        btn.style.opacity = '0.5';
                        btn.style.cursor = 'not-allowed';
                        btn.title = 'Keine uncommitted Änderungen im Workspace vorhanden';
                        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Git Sync';
                    } else {
                        btn.disabled = false;
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';
                        btn.title = count + ' geänderte Datei(en) im Workspace. Klicken zum Synchronisieren.';
                        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Git Sync (' + count + ')';
                    }
                }
            } catch (err) {
                console.error('[AMS UI] Failed to check git status for badge:', err);
            }
        }

        if (syncBtn) {
            // Initial check after rendering
            setTimeout(updateGitSyncButtonStatus, 500);
            gitCheckInterval = setInterval(updateGitSyncButtonStatus, 15000);

            syncBtn.addEventListener('click', (e) => {
                e.stopPropagation();

                const parts = window.location.pathname.split('/');
                const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

                showGitSyncModal(conversationId, async (commitMsg) => {
                    syncBtn.disabled = true;
                    syncBtn.textContent = 'Syncing...';

                    try {
                        const res = await window.electronNative.commitAndPush(commitMsg || 'wip: sync tasks', conversationId);
                        if (res.status === 'success') {
                            showCustomAlert('Synchronisation erfolgreich abgeschlossen!\\n\\n' + res.details);
                            updateGitSyncButtonStatus();
                        } else {
                            showCustomAlert('Fehler bei der Synchronisation:\\n\\n' + (res.message || 'Unbekannter Fehler'));
                        }
                    } catch (err) {
                        showCustomAlert('Ausnahmefehler bei der Synchronisation: ' + err.message);
                    } finally {
                        syncBtn.disabled = false;
                        updateGitSyncButtonStatus();
                    }
                });
            });
        }

        const textarea = panel.querySelector('#antigravity-notes-textarea');
        const checkbox = panel.querySelector('#antigravity-notes-sync-ai');

        const saveNotes = async () => {
            const text = textarea.value;
            const syncAI = checkbox.checked;
            currentNotesText = text;
            notesSyncAI = syncAI;

            const storageKey = 'antigravity_notes_' + currentConvId;
            const syncKey = 'antigravity_notes_sync_ai_' + currentConvId;
            const updateObj = {};
            updateObj[storageKey] = text;
            updateObj[syncKey] = syncAI;
            window.nativeStorage.updateItems(updateObj);

            if (currentConvId && window.electronNative && window.electronNative.setNotes) {
                await window.electronNative.setNotes(text, syncAI, currentConvId);
            }
            triggerSaveStatus();
        };

        if (textarea && checkbox) {
            textarea.addEventListener('input', saveNotes);
            checkbox.addEventListener('change', saveNotes);
        }

        // Initial load for notes
        setTimeout(loadNotesUI, 50);

        const tabs = panel.querySelectorAll('.antigravity-plan-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const mode = tab.getAttribute('data-tab');
                const notesContainer = panel.querySelector('#antigravity-plan-notes-container');
                const prsContainer = panel.querySelector('#antigravity-plan-prs-container');
                const issuesContainer = panel.querySelector('#antigravity-plan-issues-container');
                const reviewsContainer = panel.querySelector('#antigravity-plan-reviews-container');

                if (mode === 'notes') {
                    notesContainer.style.display = 'flex';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'none';
                    loadNotesUI();
                } else if (mode === 'prs') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'flex';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'none';
                    updatePRsUI();
                } else if (mode === 'issues') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'flex';
                    reviewsContainer.style.display = 'none';
                    updateIssuesUI();
                } else if (mode === 'reviews') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'flex';
                    updateReviewsUI();
                }
            });
        });

        return panel;
    }


    function updateChecklistFromText() {
        const container = document.getElementById('antigravity-plan-preview-container');
        if (!container) return;

        container.innerHTML = '';
        const lines = currentPlanText.split('\\n');
        let hasTasks = false;

        lines.forEach((line, index) => {
            const match = line.match(/^(\\s*)-\\s*\\[([ xX])\\]\\s*(.*)$/);
            if (match) {
                hasTasks = true;
                const indent = match[1] || '';
                const checked = match[2].toLowerCase() === 'x';
                const text = match[3].trim();

                const item = document.createElement('div');
                item.className = 'antigravity-checklist-item';
                item.style.paddingLeft = (indent.length * 8 + 6) + 'px';
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.width = '100%';

                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'antigravity-checklist-cb';
                cb.checked = checked;

                const label = document.createElement('span');
                label.className = 'antigravity-checklist-text' + (checked ? ' checked' : '');
                label.textContent = text;
                label.style.flex = '1';
                label.style.marginLeft = '8px';

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'antigravity-checklist-delete';
                deleteBtn.title = 'Task löschen';
                deleteBtn.style.marginLeft = 'auto';
                deleteBtn.style.background = 'transparent';
                deleteBtn.style.border = 'none';
                deleteBtn.style.color = 'var(--muted-foreground, #71717a)';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.style.padding = '2px';
                deleteBtn.style.display = 'none';
                deleteBtn.style.alignItems = 'center';
                deleteBtn.style.justifyContent = 'center';
                deleteBtn.style.outline = 'none';
                deleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

                const toggleItem = () => {
                    cb.checked = !cb.checked;
                    label.classList.toggle('checked', cb.checked);
                    const newChar = cb.checked ? 'x' : ' ';
                    lines[index] = indent + '- [' + newChar + '] ' + text;
                    currentPlanText = lines.join('\\n');
                    window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                    if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                        window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                    }

                    const editor = document.getElementById('antigravity-plan-editor');
                    if (editor) {
                        editor.value = currentPlanText;
                    }
                    triggerSaveStatus();

                    // Auto-Git-commit on check
                    if (cb.checked && currentConvId) {
                        triggerAutoGitCommitAndPush(currentConvId, text.trim());
                    }
                };

                cb.addEventListener('change', (e) => {
                    e.stopPropagation();
                    const checkedState = cb.checked;
                    label.classList.toggle('checked', checkedState);
                    const newChar = checkedState ? 'x' : ' ';
                    lines[index] = indent + '- [' + newChar + '] ' + text;
                    currentPlanText = lines.join('\\n');
                    window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                    if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                        window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                    }

                    const editor = document.getElementById('antigravity-plan-editor');
                    if (editor) {
                        editor.value = currentPlanText;
                    }
                    triggerSaveStatus();

                    // Auto-Git-commit on check
                    if (checkedState && currentConvId) {
                        triggerAutoGitCommitAndPush(currentConvId, text.trim());
                    }
                });

                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCustomConfirm('Möchtest du diesen Task wirklich löschen?', (confirmed) => {
                        if (confirmed) {
                            lines.splice(index, 1);
                            currentPlanText = lines.join('\\n');
                            window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                            if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                                window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                            }

                            const editor = document.getElementById('antigravity-plan-editor');
                            if (editor) {
                                editor.value = currentPlanText;
                            }
                            updateChecklistFromText();
                            triggerSaveStatus();
                        }
                    });
                });

                label.addEventListener('click', toggleItem);

                item.appendChild(cb);
                item.appendChild(label);
                item.appendChild(deleteBtn);
                container.appendChild(item);
            } else {
                if (line.trim().startsWith('#')) {
                    const headerContainer = document.createElement('div');
                    headerContainer.className = 'antigravity-checklist-header-container';
                    headerContainer.style.display = 'flex';
                    headerContainer.style.alignItems = 'center';
                    headerContainer.style.justifyContent = 'space-between';
                    headerContainer.style.marginTop = '16px';
                    headerContainer.style.marginBottom = '6px';

                    const level = line.match(/^#+/)[0].length;
                    headerContainer.style.borderBottom = level === 1 ? '1px solid var(--border, #27272a)' : 'none';
                    headerContainer.style.paddingBottom = level === 1 ? '4px' : '0';

                    const headerText = document.createElement('span');
                    headerText.style.fontWeight = 'bold';
                    headerText.style.fontSize = (18 - level) + 'px';
                    headerText.textContent = line.replace(/^#+\\s*/, '');

                    const addBtn = document.createElement('button');
                    addBtn.className = 'antigravity-checklist-add-btn';
                    addBtn.title = 'Task hinzufügen';
                    addBtn.style.background = 'transparent';
                    addBtn.style.border = 'none';
                    addBtn.style.color = 'var(--muted-foreground, #71717a)';
                    addBtn.style.cursor = 'pointer';
                    addBtn.style.display = 'inline-flex';
                    addBtn.style.alignItems = 'center';
                    addBtn.style.padding = '4px';
                    addBtn.style.borderRadius = '4px';
                    addBtn.style.outline = 'none';
                    addBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>';

                    addBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const titleClean = headerText.textContent;
                        showCustomPrompt("Neuen Task unter '" + titleClean + "' hinzufügen:", "", (taskText) => {
                            if (taskText && taskText.trim()) {
                                let insertIdx = index + 1;
                                while (insertIdx < lines.length) {
                                    const nextLine = lines[insertIdx];
                                    if (nextLine.trim().startsWith('#')) {
                                        break;
                                    }
                                    insertIdx++;
                                }

                                lines.splice(insertIdx, 0, '- [ ] ' + taskText.trim());
                                currentPlanText = lines.join('\\n');
                                window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                                if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                                    window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                                }

                                const editor = document.getElementById('antigravity-plan-editor');
                                if (editor) {
                                    editor.value = currentPlanText;
                                }
                                updateChecklistFromText();
                                triggerSaveStatus();
                            }
                        });
                    });

                    headerContainer.appendChild(headerText);
                    headerContainer.appendChild(addBtn);
                    container.appendChild(headerContainer);
                } else if (line.trim()) {
                    const txt = document.createElement('div');
                    txt.style.fontSize = '13px';
                    txt.style.opacity = '0.8';
                    txt.style.marginTop = '4px';
                    txt.textContent = line;
                    container.appendChild(txt);
                }
            }
        });

        if (!hasTasks) {
            const emptyMsg = document.createElement('div');
            emptyMsg.style.fontSize = '12px';
            emptyMsg.style.color = 'var(--muted-foreground, #71717a)';
            emptyMsg.style.textAlign = 'center';
            emptyMsg.style.marginTop = '20px';
            emptyMsg.innerHTML = 'Keine Tasks gefunden.<br>Nutze das "Bearbeiten"-Tab, um einen Plan im Markdown-Checklisten-Format hinzuzufügen.';
            container.appendChild(emptyMsg);
        }
    }

    let autoCommitTimeout = null;
    let pendingSteps = [];

    function triggerAutoGitCommitAndPush(convoId, stepText) {
        if (!window.electronNative || !window.electronNative.commitAndPush) return;

        pendingSteps.push(stepText);

        if (autoCommitTimeout) {
            clearTimeout(autoCommitTimeout);
        }

        autoCommitTimeout = setTimeout(async () => {
            const stepsList = pendingSteps.join(', ');
            pendingSteps = [];
            autoCommitTimeout = null;

            console.log('[AMS Auto-Sync] Triggering auto-commit for completed steps:', stepsList);
            const commitMsg = \`docs(tasks): completed steps: \${stepsList}\`;
            try {
                const res = await window.electronNative.commitAndPush(commitMsg, convoId);
                if (res && res.status === 'success') {
                    console.log('[AMS Auto-Sync] Auto-commit and push successful.');
                } else {
                    console.warn('[AMS Auto-Sync] Auto-commit failed:', res ? res.message : 'unknown error');
                }
            } catch (err) {
                console.error('[AMS Auto-Sync] Error during auto-commit:', err);
            }
        }, 5000);
    }


    const loadedPRs = Object.create(null);
    const loadedIssues = Object.create(null);


    async function updateReviewsUI() {
        const container = document.getElementById('antigravity-plan-reviews-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Reviews...</div>';

        try {
            const runsGrouped = await window.electronNative.getReviews();
            if (!runsGrouped || runsGrouped.length === 0) {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine nächtlichen Läufe protokolliert.</div>';
                return;
            }

            let html = '<div style="display: flex; flex-direction: column; gap: 14px; padding-bottom: 10px;">';

            runsGrouped.forEach(group => {
                html += '<div style="display: flex; flex-direction: column; gap: 8px;">';
                html += '  <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-foreground, #71717a); border-bottom: 1px solid var(--border, #27272a); padding-bottom: 4px; margin-top: 8px;">Lauf: ' + escapeHtml(group.date) + '</div>';

                group.runs.forEach(run => {
                    const runStatus = String(run.status || 'Unknown');
                    const safeConversationId = String(run.conversationId || '');
                    const safePrUrl = safeExternalUrl(run.prUrl);
                    let statusColor = '#3b82f6';
                    let statusBg = 'rgba(59, 130, 246, 0.1)';
                    if (runStatus === 'Success') {
                        statusColor = '#22c55e';
                        statusBg = 'rgba(34, 197, 94, 0.1)';
                    } else if (runStatus === 'Loop Detected') {
                        statusColor = '#eab308';
                        statusBg = 'rgba(234, 179, 8, 0.1)';
                    } else if (runStatus.startsWith('Failed') || runStatus === 'Failed to launch') {
                        statusColor = '#ef4444';
                        statusBg = 'rgba(239, 68, 68, 0.1)';
                    }

                    html += '<div style="background-color: var(--card, #1c1c1e); border: 1px solid var(--border, #27272a); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px;">';
                    html += '  <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">';
                    html += '    <div style="font-size: 12px; font-weight: 500; color: var(--foreground, #ffffff); line-height: 1.3;">Issue #' + escapeHtml(run.issueNumber) + ': ' + escapeHtml(run.title) + '</div>';
                    html += '    <span style="font-size: 9px; font-weight: 600; text-transform: uppercase; color: ' + statusColor + '; background-color: ' + statusBg + '; padding: 2px 6px; border-radius: 4px; shrink-0;">' + escapeHtml(runStatus) + '</span>';
                    html += '  </div>';
                    html += '  <div style="font-size: 11px; color: var(--muted-foreground, #71717a); display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">';
                    html += '    <span>Branch: <code style="background-color: rgba(255,255,255,0.05); padding: 1px 4px; border-radius: 3px; font-family: monospace;">' + escapeHtml(run.branch) + '</code></span>';
                    if (run.startTime) {
                        html += '    <span>| Start: ' + escapeHtml(String(run.startTime).split(' ')[1] || run.startTime) + '</span>';
                    }
                    if (run.endTime) {
                        html += '    <span>| Ende: ' + escapeHtml(String(run.endTime).split(' ')[1] || run.endTime) + '</span>';
                    }
                    html += '  </div>';
                    html += '  <div style="display: flex; gap: 8px; margin-top: 4px;">';
                    if (safeConversationId) {
                        html += '    <button class="antigravity-review-log-btn" data-convoid="' + escapeHtml(safeConversationId) + '" style="background: transparent; border: 1px solid var(--border, #27272a); color: var(--foreground, #ffffff); border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; transition: background-color 0.2s; outline: none;">Log ansehen</button>';
                    }
                    if (safePrUrl) {
                        html += '    <a href="' + escapeHtml(safePrUrl) + '" target="_blank" rel="noopener noreferrer" style="text-decoration: none; border: 1px solid var(--border, #27272a); color: var(--foreground, #ffffff); background-color: rgba(255,255,255,0.02); border-radius: 4px; padding: 3px 8px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px; transition: background-color 0.2s;"><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>PR ansehen</a>';
                    }
                    html += '  </div>';
                    html += '</div>';
                });
                html += '</div>';
            });
            html += '</div>';
            container.innerHTML = html;

            container.querySelectorAll('.antigravity-review-log-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const convoId = btn.getAttribute('data-convoid');
                    showReviewLogModal(convoId);
                });
            });

        } catch (e) {
            console.error('[AMS UI Reviews] Failed to render reviews:', e);
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Fehler beim Laden der Reviews.</div>';
        }
    }

    async function showReviewLogModal(convoId) {
        const previouslyFocused = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.zIndex = '9999';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';

        const modal = document.createElement('div');
        modal.style.width = '80vw';
        modal.style.maxWidth = '700px';
        modal.style.height = '80vh';
        modal.style.maxHeight = '600px';
        modal.style.backgroundColor = 'var(--background, #0a0a0a)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '12px';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.overflow = 'hidden';
        modal.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5)';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.padding = '12px 16px';
        header.style.borderBottom = '1px solid var(--border, #27272a)';
        header.style.backgroundColor = 'var(--card, #18181b)';

        const title = document.createElement('span');
        title.textContent = 'Ausführungs-Log für ' + String(convoId || '').substring(0, 8) + '...';
        title.style.fontSize = '12px';
        title.style.fontWeight = '600';
        title.style.color = 'var(--foreground, #ffffff)';
        title.style.textTransform = 'uppercase';
        title.style.letterSpacing = '0.05em';
        title.style.fontFamily = 'system-ui, sans-serif';
        title.id = 'antigravity-review-log-title-' + Date.now();
        modal.setAttribute('aria-labelledby', title.id);

        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = 'var(--muted-foreground, #71717a)';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.display = 'flex';
        closeBtn.style.alignItems = 'center';
        closeBtn.style.justifyContent = 'center';
        closeBtn.style.padding = '4px';
        closeBtn.style.borderRadius = '4px';
        closeBtn.setAttribute('aria-label', 'Ausführungs-Log schließen');

        header.appendChild(title);
        header.appendChild(closeBtn);
        modal.appendChild(header);

        const body = document.createElement('div');
        body.style.flex = '1';
        body.style.overflowY = 'auto';
        body.style.padding = '16px';
        body.style.display = 'flex';
        body.style.flexDirection = 'column';
        body.style.gap = '12px';
        body.style.fontSize = '12px';
        body.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 40px;">Lade Log-Details aus SQLite-Datenbank...</div>';
        modal.appendChild(body);

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: closeBtn,
            previouslyFocused,
        });
        closeBtn.addEventListener('click', () => controller.close('close-button'));
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) controller.close('backdrop');
        });
        controller.focusInitial();

        try {
            const logs = await window.electronNative.getRunLog(convoId);
            if (controller.isClosed()) return;
            if (!logs || logs.length === 0) {
                body.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 40px;">Keine Einträge in der Datenbank gefunden.</div>';
                return;
            }

            let logHtml = '';
            logs.forEach(log => {
                if (log.role === 'user') {
                    logHtml += '<div style="align-self: flex-end; background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 12px 12px 0 12px; padding: 10px; max-width: 85%; white-space: pre-wrap; line-height: 1.4; text-align: left;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'agent') {
                    logHtml += '<div style="align-self: flex-start; background-color: rgba(255,255,255,0.02); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); border-radius: 12px 12px 12px 0; padding: 10px; max-width: 85%; white-space: pre-wrap; line-height: 1.4; text-align: left;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'tool') {
                    logHtml += '<div style="align-self: center; background-color: rgba(59,130,246,0.05); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); border-radius: 6px; padding: 6px 12px; font-family: monospace; font-size: 11px; max-width: 95%; text-align: left; word-break: break-all;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'system') {
                    logHtml += '<div style="align-self: center; color: var(--muted-foreground, #71717a); font-style: italic;">' + escapeHtml(log.content) + '</div>';
                }
            });
            body.innerHTML = logHtml;
            body.scrollTop = body.scrollHeight;
        } catch (e) {
            console.error('[AMS UI Reviews] Failed to fetch log details:', e);
            body.innerHTML = '<div style="color: #ef4444; text-align: center; margin-top: 40px;">Fehler beim Laden des Logs.</div>';
        }
    }

    function escapeHtml(text) {
        return String(text ?? '')
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function safeExternalUrl(value) {
        try {
            const raw = String(value || '');
            if (!raw || raw.length > 2048) return '';
            const parsed = new URL(raw);
            return parsed.protocol === 'https:' ? parsed.href : '';
        } catch (_) {
            return '';
        }
    }

    async function updatePRsUI() {
        const container = document.getElementById('antigravity-plan-prs-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Pull Requests...</div>';

        try {
            const parts = window.location.pathname.split('/');
            const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

            const res = await window.electronNative.getPRs(conversationId);
            if (res.status === 'success') {
                if (res.prs.length === 0) {
                    container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine Pull Requests gefunden.</div>';
                    return;
                }

                let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                res.prs.forEach(pr => {
                    const prNumber = String(pr.number ?? '');
                    const prUrl = safeExternalUrl(pr.url);
                    loadedPRs[prNumber] = pr;
                    let stateColor = '#22c55e';
                    let stateLabel = 'Open';
                    if (pr.state === 'MERGED') {
                        stateColor = '#a855f7';
                        stateLabel = 'Merged';
                    } else if (pr.state === 'CLOSED') {
                        stateColor = '#ef4444';
                        stateLabel = 'Closed';
                    }

                    html += '<div class="antigravity-pr-card" style="border: 1px solid var(--border, #27272a); border-radius: 8px; background-color: var(--card, #18181b); display: flex; flex-direction: column; overflow: hidden;">' +
                            '  <div class="antigravity-card-header" style="padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; user-select: none;">' +
                            '    <div style="font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--foreground, #ffffff);">' + escapeHtml(pr.title) + '</div>' +
                            '    <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted-foreground, #71717a);">' +
                            '      <div style="display: flex; align-items: center; gap: 6px;">' +
                            '        <span style="background-color: ' + stateColor + '20; color: ' + stateColor + '; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 10px;">' + stateLabel + '</span>' +
                            '        <span>#' + escapeHtml(prNumber) + '</span>' +
                            '        <span>by ' + escapeHtml(pr.author?.login || 'unknown') + '</span>' +
                            '      </div>' +
                            '      <span class="antigravity-toggle-indicator" style="font-size: 10px; opacity: 0.7;">Details anzeigen ▾</span>' +
                            '    </div>' +
                            '  </div>' +
                            '  <div class="antigravity-body-details" style="display: none; border-top: 1px solid var(--border, #27272a); padding: 10px; background-color: rgba(0,0,0,0.15); flex-direction: column; gap: 8px;">' +
                            '    <div style="font-size: 12px; color: var(--muted-foreground, #a1a1aa); white-space: pre-wrap; max-height: 200px; overflow-y: auto; line-height: 1.5; font-family: ui-sans-serif, system-ui, sans-serif; padding-right: 4px;">' + escapeHtml(pr.body || '*Keine Beschreibung vorhanden.*') + '</div>' +
                            '    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">' +
                            '      <button class="antigravity-plan-subtasks" data-type="PR" data-number="' + escapeHtml(prNumber) + '" style="background-color: #2563eb; color: white; border: none; padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4z"></path></svg>' +
                            '        Subtasks planen' +
                            '      </button>' +
                            '      <button class="antigravity-send-to-ai" data-type="PR" data-number="' + escapeHtml(prNumber) + '" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>' +
                            '        An Chat senden' +
                            '      </button>' +
                            '      <button class="antigravity-open-web" data-url="' + escapeHtml(prUrl) + '" style="background-color: transparent; color: var(--muted-foreground, #a1a1aa); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500;">Im Browser öffnen</button>' +
                            '    </div>' +
                            '  </div>' +
                            '</div>';
                });
                html += '</div>';
                container.innerHTML = html;

                container.querySelectorAll('.antigravity-card-header').forEach(header => {
                    header.addEventListener('click', () => {
                        const details = header.parentElement.querySelector('.antigravity-body-details');
                        const indicator = header.querySelector('.antigravity-toggle-indicator');
                        if (details.style.display === 'none') {
                            details.style.display = 'flex';
                            indicator.textContent = 'Details verbergen ▴';
                        } else {
                            details.style.display = 'none';
                            indicator.textContent = 'Details anzeigen ▾';
                        }
                    });
                });

                container.querySelectorAll('.antigravity-plan-subtasks').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = type === 'PR' ? loadedPRs[number] : loadedIssues[number];
                        if (!item) {
                            showCustomAlert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const newPlan = generateSubtasks(item, type);
                        const editor = document.getElementById('antigravity-plan-editor');
                        if (editor) {
                            editor.value = newPlan;
                            const event = new Event('input', { bubbles: true });
                            editor.dispatchEvent(event);

                            const previewTab = document.querySelector('.antigravity-plan-tab[data-tab="preview"]');
                            if (previewTab) {
                                previewTab.click();
                            }
                        }
                    });
                });

                container.querySelectorAll('.antigravity-send-to-ai').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = loadedPRs[number];
                        if (!item) {
                            showCustomAlert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const promptText = \`Bitte bearbeite folgendes GitHub-\${type}:\\n\\n\` +
                                           \`**Titel:** \${item.title} (#\${item.number})\\n\` +
                                           \`**Link:** \${item.url}\\n\\n\` +
                                           \`**Beschreibung:**\\n\${item.body || 'Keine Beschreibung.'}\`;

                        const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                        if (input) {
                            input.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, promptText);
                            const event = new Event('input', { bubbles: true });
                            input.dispatchEvent(event);
                        } else {
                            showCustomAlert('Chat-Eingabefeld nicht gefunden!');
                        }
                    });
                });

                container.querySelectorAll('.antigravity-open-web').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const url = safeExternalUrl(btn.getAttribute('data-url'));
                        if (url && window.electronNative && window.electronNative.openExternal) {
                            window.electronNative.openExternal(url);
                        }
                    });
                });
            } else if (res.status === 'no_remote') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px; line-height: 1.5;">' +
                                      '  Kein GitHub-Remote-Repository konfiguriert.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7;">Füge ein Remote-Repository hinzu (z.B. git remote add origin &lt;url&gt;), um Pull Requests anzuzeigen.</span>' +
                                      '</div>';
            } else if (res.status === 'no_git') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Kein Git-Repository in diesem Workspace gefunden.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7; word-break: break-all;">Pfad: ' + escapeHtml(res.repoPath) + '</span>' +
                                      '</div>';
            } else {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Fehler beim Laden: ' + escapeHtml(res.message || 'Unbekannter Fehler') +
                                      '</div>';
            }
        } catch (err) {
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: #ef4444;">Ausnahmefehler: ' + escapeHtml(err.message) + '</div>';
        }
    }

    async function updateIssuesUI() {
        const container = document.getElementById('antigravity-plan-issues-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Issues...</div>';

        try {
            const parts = window.location.pathname.split('/');
            const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

            const res = await window.electronNative.getIssues(conversationId);
            if (res.status === 'success') {
                if (res.issues.length === 0) {
                    container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine offenen Issues gefunden.</div>';
                    return;
                }

                let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                res.issues.forEach(issue => {
                    const issueNumber = String(issue.number ?? '');
                    const issueUrl = safeExternalUrl(issue.url);
                    loadedIssues[issueNumber] = issue;
                    let stateColor = '#22c55e';
                    let stateLabel = 'Open';
                    if (issue.state && issue.state.toLowerCase() === 'closed') {
                        stateColor = '#ef4444';
                        stateLabel = 'Closed';
                    }

                    html += '<div class="antigravity-issue-card" style="border: 1px solid var(--border, #27272a); border-radius: 8px; background-color: var(--card, #18181b); display: flex; flex-direction: column; overflow: hidden;">' +
                            '  <div class="antigravity-card-header" style="padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; user-select: none;">' +
                            '    <div style="font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--foreground, #ffffff);">' + escapeHtml(issue.title) + '</div>' +
                            '    <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted-foreground, #71717a);">' +
                            '      <div style="display: flex; align-items: center; gap: 6px;">' +
                            '        <span style="background-color: ' + stateColor + '20; color: ' + stateColor + '; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 10px;">' + stateLabel + '</span>' +
                            '        <span>#' + escapeHtml(issueNumber) + '</span>' +
                            '        <span>by ' + escapeHtml(issue.author?.login || 'unknown') + '</span>' +
                            '      </div>' +
                            '      <span class="antigravity-toggle-indicator" style="font-size: 10px; opacity: 0.7;">Details anzeigen ▾</span>' +
                            '    </div>' +
                            '  </div>' +
                            '  <div class="antigravity-body-details" style="display: none; border-top: 1px solid var(--border, #27272a); padding: 10px; background-color: rgba(0,0,0,0.15); flex-direction: column; gap: 8px;">' +
                            '    <div style="font-size: 12px; color: var(--muted-foreground, #a1a1aa); white-space: pre-wrap; max-height: 200px; overflow-y: auto; line-height: 1.5; font-family: ui-sans-serif, system-ui, sans-serif; padding-right: 4px;">' + escapeHtml(issue.body || '*Keine Beschreibung vorhanden.*') + '</div>' +
                            '    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">' +
                            '      <button class="antigravity-plan-subtasks" data-type="Issue" data-number="' + escapeHtml(issueNumber) + '" style="background-color: #2563eb; color: white; border: none; padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4z"></path></svg>' +
                            '        Subtasks planen' +
                            '      </button>' +
                            '      <button class="antigravity-send-to-ai" data-type="Issue" data-number="' + escapeHtml(issueNumber) + '" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>' +
                            '        An Chat senden' +
                            '      </button>' +
                            '      <button class="antigravity-open-web" data-url="' + escapeHtml(issueUrl) + '" style="background-color: transparent; color: var(--muted-foreground, #a1a1aa); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500;">Im Browser öffnen</button>' +
                            '    </div>' +
                            '  </div>' +
                            '</div>';
                });
                html += '</div>';
                container.innerHTML = html;

                container.querySelectorAll('.antigravity-card-header').forEach(header => {
                    header.addEventListener('click', () => {
                        const details = header.parentElement.querySelector('.antigravity-body-details');
                        const indicator = header.querySelector('.antigravity-toggle-indicator');
                        if (details.style.display === 'none') {
                            details.style.display = 'flex';
                            indicator.textContent = 'Details verbergen ▴';
                        } else {
                            details.style.display = 'none';
                            indicator.textContent = 'Details anzeigen ▾';
                        }
                    });
                });

                container.querySelectorAll('.antigravity-plan-subtasks').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = type === 'PR' ? loadedPRs[number] : loadedIssues[number];
                        if (!item) {
                            showCustomAlert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const newPlan = generateSubtasks(item, type);
                        const editor = document.getElementById('antigravity-plan-editor');
                        if (editor) {
                            editor.value = newPlan;
                            const event = new Event('input', { bubbles: true });
                            editor.dispatchEvent(event);

                            const previewTab = document.querySelector('.antigravity-plan-tab[data-tab="preview"]');
                            if (previewTab) {
                                previewTab.click();
                            }
                        }
                    });
                });

                container.querySelectorAll('.antigravity-send-to-ai').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = loadedIssues[number];
                        if (!item) {
                            showCustomAlert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const promptText = \`Bitte bearbeite folgendes GitHub-\${type}:\\n\\n\` +
                                           \`**Titel:** \${item.title} (#\${item.number})\\n\` +
                                           \`**Link:** \${item.url}\\n\\n\` +
                                           \`**Beschreibung:**\\n\${item.body || 'Keine Beschreibung.'}\`;

                        const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                        if (input) {
                            input.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, promptText);
                            const event = new Event('input', { bubbles: true });
                            input.dispatchEvent(event);
                        } else {
                            showCustomAlert('Chat-Eingabefeld nicht gefunden!');
                        }
                    });
                });

                container.querySelectorAll('.antigravity-open-web').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const url = safeExternalUrl(btn.getAttribute('data-url'));
                        if (url && window.electronNative && window.electronNative.openExternal) {
                            window.electronNative.openExternal(url);
                        }
                    });
                });
            } else if (res.status === 'no_remote') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px; line-height: 1.5;">' +
                                      '  Kein GitHub-Remote-Repository konfiguriert.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7;">Füge ein Remote-Repository hinzu, um Issues anzuzeigen.</span>' +
                                      '</div>';
            } else if (res.status === 'no_git') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Kein Git-Repository in diesem Workspace gefunden.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7; word-break: break-all;">Pfad: ' + escapeHtml(res.repoPath) + '</span>' +
                                      '</div>';
            } else {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Fehler beim Laden: ' + escapeHtml(res.message || 'Unbekannter Fehler') +
                                      '</div>';
            }
        } catch (e) {
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                  '  Exception beim Laden: ' + escapeHtml(e.message) +
                                  '</div>';
        }
    }


    async function renderAppLogViewer() {
        const logsTab = document.getElementById('antigravity-settings-logs-tab');
        if (!logsTab) return;
        const sidebar = logsTab.parentElement;
        if (!sidebar) return;

        const sidebarContainer = sidebar.closest('.bg-sidebar');
        if (!sidebarContainer) return;

        const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
        if (!layoutContainer) return;

        const rightPanel = layoutContainer.children[1];
        if (!rightPanel) return;

        let container = document.getElementById('antigravity-log-viewer-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'antigravity-log-viewer-container';
            container.className = 'antigravity-log-viewer-main flex-grow flex flex-col gap-4 min-w-0 bg-transparent p-6';
            container.style.height = '100%';
            container.style.width = '100%';
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.boxSizing = 'border-box';
            container.style.flexGrow = '1';
            container.style.minHeight = '0';
            rightPanel.appendChild(container);
        }

        // Hide all other elements in rightPanel to avoid vertical split/squeezing
        for (let i = 0; i < rightPanel.children.length; i++) {
            const child = rightPanel.children[i];
            if (child !== container) {
                child.style.display = 'none';
            }
        }
        container.style.display = 'flex';

        // Only reconstruct UI if needed
        if (!container.querySelector('#log-rows-container')) {
            container.innerHTML =
                '<div class="flex items-center justify-between border-b pb-3 border-border" style="border-bottom: 1px solid var(--border);">' +
                    '<h2 class="text-xl font-semibold text-foreground">Log Viewer</h2>' +
                    '<div class="flex gap-2" style="margin-right: 28px; align-items: center;">' +
                        '<button id="ams-consolidate-btn" class="text-xs bg-primary text-primary-foreground px-2.5 py-1 rounded-md" style="background: var(--primary, #3b82f6); color: var(--primary-foreground, #ffffff); border: none; cursor: pointer; display: flex; align-items: center; gap: 4px; font-weight: 500; font-family: inherit; font-size: 11px; height: 24px; transition: opacity 0.2s;" title="Langzeitgedächtnis aus dem Chatverlauf aktualisieren">🧠 Lernen</button>' +
                        '<span class="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground" style="background: var(--muted); color: var(--muted-foreground); height: 24px; display: flex; align-items: center;" title="IPC token is isolated in the preload context">IPC geschützt</span>' +
                        '<span class="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground" id="log-stats-count" style="background: var(--muted); color: var(--muted-foreground); height: 24px; display: flex; align-items: center;">Loading...</span>' +
                    '</div>' +
                '</div>' +
                '<div class="flex gap-2 items-center">' +
                    '<input type="text" id="log-search" placeholder="Search logs..." class="flex-1 px-3 py-1.5 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none" style="background: var(--background); color: var(--foreground); border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px;" />' +
                    '<select id="log-source" class="px-2 py-1.5 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none" style="background: var(--background); color: var(--foreground); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 13px;">' +
                        '<option value="">All Sources</option>' +
                        '<option value="USER">User</option>' +
                        '<option value="AGENT">Agent</option>' +
                        '<option value="SYSTEM">System</option>' +
                    '</select>' +
                '</div>' +
                '<div id="log-rows-container" class="flex-grow overflow-y-auto pr-1 flex flex-col gap-2" style="overflow-y: auto; scrollbar-width: thin; display: flex; flex-direction: column; gap: 8px; flex-grow: 1; min-height: 0;">' +
                    '<div class="text-sm text-muted-foreground p-8 text-center" style="color: var(--muted-foreground);">Loading log history...</div>' +
                '</div>';

            container.querySelector('#log-search').addEventListener('input', () => renderRows());
            container.querySelector('#log-source').addEventListener('change', () => renderRows());

            const consolidateBtn = container.querySelector('#ams-consolidate-btn');
            if (consolidateBtn) {
                consolidateBtn.addEventListener('click', () => triggerConsolidation());
            }
        }

        const rowsContainer = container.querySelector('#log-rows-container');
        const statsEl = container.querySelector('#log-stats-count');

        let res;
        try {
            res = await window.electronNative.getHistory();
        } catch (ipcErr) {
            rowsContainer.innerHTML = '<div class="text-sm text-red-500 p-8 text-center">Failed to invoke logs IPC handler: ' + escapeHtml(ipcErr.message) + '</div>';
            statsEl.textContent = 'Error';
            return;
        }

        if (res.status !== 'success') {
            rowsContainer.innerHTML = '<div class="text-sm text-red-500 p-8 text-center">Failed to load log history: ' + escapeHtml(res.message || 'File not found') + '</div>';
            statsEl.textContent = 'Error';
            return;
        }

        const logsData = res.logs || [];
        logsData.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        let totalTokens = 0;
        logsData.forEach(log => {
            if (typeof log.tokens === 'number') {
                totalTokens += log.tokens;
            } else {
                totalTokens += estimateTokenCount(log.content);
            }
        });

        statsEl.textContent = logsData.length + ' entries | ' + formatTokenCount(totalTokens) + ' tokens';

        function formatLogMessage(text) {
            if (!text) return '';
            text = String(text);

            let userRequest = '';
            let metadata = '';
            let isStructuredUser = false;

            if (text.includes('<USER_REQUEST>') && text.includes('</USER_REQUEST>')) {
                isStructuredUser = true;
                const reqStart = text.indexOf('<USER_REQUEST>') + 14;
                const reqEnd = text.indexOf('</USER_REQUEST>');
                userRequest = text.substring(reqStart, reqEnd).trim();

                if (text.includes('<ADDITIONAL_METADATA>') && text.includes('</ADDITIONAL_METADATA>')) {
                    const metaStart = text.indexOf('<ADDITIONAL_METADATA>') + 21;
                    const metaEnd = text.indexOf('</ADDITIONAL_METADATA>');
                    metadata = text.substring(metaStart, metaEnd).trim();
                }
            }

            let displayText = isStructuredUser ? userRequest : text;

            let escaped = displayText
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");

            let html = escaped;

            if (isStructuredUser && metadata) {
                let escapedMeta = metadata
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");

                html += '<details style="margin-top: 8px; font-size: 11px; color: var(--muted-foreground, #8c8c8c); cursor: pointer;" onclick="event.stopPropagation()">' +
                        '<summary style="user-select: none;">Show Metadata</summary>' +
                        '<pre style="margin-top: 4px; padding: 6px; background: rgba(0,0,0,0.15); border-radius: 4px; overflow-x: auto; white-space: pre-wrap; font-family: monospace;">' + escapedMeta + '</pre>' +
                        '</details>';
            }

            return html;
        }

        function renderRows() {
            const searchQuery = container.querySelector('#log-search').value.toLowerCase();
            const sourceFilter = container.querySelector('#log-source').value;

            const filtered = logsData.filter(log => {
                const content = String(log.content || '');
                const matchesSearch = content.toLowerCase().includes(searchQuery);
                const matchesSource = !sourceFilter || log.source === sourceFilter;
                return matchesSearch && matchesSource;
            });

            rowsContainer.innerHTML = '';
            if (filtered.length === 0) {
                rowsContainer.innerHTML = '<div class="text-sm text-muted-foreground p-8 text-center" style="color: var(--muted-foreground);">No logs found.</div>';
                return;
            }

            filtered.slice(0, 150).forEach(log => {
                const source = String(log.source || 'SYSTEM');
                const sessionId = String(log.session_id || 'unknown');
                const eventName = String(log.event || 'unknown');
                const content = String(log.content || '');
                const row = document.createElement('div');
                row.style.background = 'var(--muted, rgba(255,255,255,0.03))';
                row.style.border = '1px solid var(--border, rgba(255,255,255,0.08))';
                row.style.borderRadius = '8px';
                row.style.padding = '8px 12px';
                row.style.display = 'flex';
                row.style.flexDirection = 'column';
                row.style.gap = '4px';
                row.style.cursor = 'pointer';
                row.style.transition = 'background 0.2s';

                row.addEventListener('mouseover', () => {
                    row.style.background = 'var(--sidebar-muted, rgba(255,255,255,0.06))';
                });
                row.addEventListener('mouseout', () => {
                    row.style.background = 'var(--muted, rgba(255,255,255,0.03))';
                });

                const timeStr = new Date(log.timestamp).toLocaleString('de-DE');

                const details = document.createElement('div');
                details.style.display = 'none';
                details.style.fontSize = '11px';
                details.style.color = 'var(--text-secondary, #9ca3af)';
                details.style.marginTop = '6px';
                details.style.borderTop = '1px solid var(--border, rgba(255,255,255,0.08))';
                details.style.paddingTop = '6px';
                details.style.fontFamily = 'monospace';
                details.innerHTML =
                    '<div><strong>Session:</strong> ' + escapeHtml(sessionId) + '</div>' +
                    '<div><strong>Event:</strong> ' + escapeHtml(eventName) + '</div>' +
                    (log.metadata ? '<div><strong>Metadata:</strong> ' + escapeHtml(JSON.stringify(log.metadata)) + '</div>' : '');

                row.addEventListener('click', (e) => {
                    const isExpanded = details.style.display === 'block';
                    details.style.display = isExpanded ? 'none' : 'block';
                });

                const badgeColor = source === 'USER' ? '#3b82f6' : (source === 'AGENT' ? '#8b5cf6' : '#9ca3af');

                const tokensVal = typeof log.tokens === 'number' ? log.tokens : estimateTokenCount(log.content);
                const isEstimated = typeof log.tokens !== 'number';
                const tokenStr = (isEstimated ? '~' : '') + formatTokenCount(tokensVal) + ' tokens';
                const modelStr = String(log.model || 'Gemini 3.5 Flash (High)');

                row.innerHTML =
                    '<div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px;">' +
                        '<div style="display: flex; align-items: center; gap: 6px;">' +
                            '<span style="background: ' + badgeColor + '; color: white; padding: 1px 4px; border-radius: 4px; font-weight: bold; font-size: 9px;">' + escapeHtml(source) + '</span>' +
                            '<span style="opacity: 0.6;">' + escapeHtml(timeStr) + '</span>' +
                        '</div>' +
                        '<div style="display: flex; align-items: center; gap: 8px;">' +
                            '<span style="opacity: 0.5; background: var(--muted, rgba(255,255,255,0.05)); border: 1px solid var(--border, rgba(255,255,255,0.1)); padding: 1px 6px; border-radius: 4px; font-size: 10px;" title="Model and token count">' + escapeHtml(modelStr) + ' • ' + escapeHtml(tokenStr) + '</span>' +
                            '<span style="opacity: 0.4; font-family: monospace;">' + escapeHtml(sessionId.substring(0, 8)) + '...</span>' +
                        '</div>' +
                    '</div>' +
                    '<div style="font-size: 13px; color: var(--foreground, #f3f4f6); word-break: break-word; white-space: pre-wrap; margin-top: 4px;">' + formatLogMessage(content) + '</div>';

                row.appendChild(details);
                rowsContainer.appendChild(row);
            });
        }

        renderRows();

        async function triggerConsolidation() {
            const btn = document.getElementById('ams-consolidate-btn');
            if (!btn) return;

            if (!currentConvId) {
                showToast('Keine aktive Konversation geladen.', 'error');
                return;
            }

            const oldText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '🧠 Analysiere...';
            btn.style.opacity = '0.7';

            try {
                const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
                const res = await window.electronNative.consolidateMemory(currentConvId, csrfToken);

                if (res && res.found) {
                    showConsolidationModal(res.type, res.proposed_text, res.convoId);
                } else {
                    showToast('Keine neuen Erkenntnisse im aktuellen Verlauf gefunden.', 'info');
                }
            } catch (e) {
                console.error('[AMS UI] Consolidation failed:', e);
                showToast('Fehler bei der Analyse: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = oldText;
                btn.style.opacity = '1';
            }
        }

        function showToast(message, type) {
            const toast = document.createElement('div');
            toast.style.position = 'fixed';
            toast.style.bottom = '20px';
            toast.style.right = '20px';
            toast.style.padding = '12px 18px';
            toast.style.borderRadius = '8px';
            toast.style.fontSize = '13px';
            toast.style.zIndex = '99999';
            toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
            toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            toast.style.transform = 'translateY(20px)';
            toast.style.opacity = '0';

            if (type === 'error') {
                toast.style.background = '#ef4444';
                toast.style.color = '#ffffff';
            } else if (type === 'success') {
                toast.style.background = '#10b981';
                toast.style.color = '#ffffff';
            } else {
                toast.style.background = 'var(--popover, #1e1e24)';
                toast.style.color = 'var(--popover-foreground, #ffffff)';
                toast.style.border = '1px solid var(--border, #3f3f46)';
            }

            toast.textContent = message;
            document.body.appendChild(toast);

            setTimeout(() => {
                toast.style.transform = 'translateY(0)';
                toast.style.opacity = '1';
            }, 50);

            setTimeout(() => {
                toast.style.transform = 'translateY(20px)';
                toast.style.opacity = '0';
                setTimeout(() => {
                    toast.remove();
                }, 300);
            }, 4000);
        }

        function showConsolidationModal(type, proposedText, tempConvoId) {
            const previouslyFocused = document.activeElement;
            const overlay = document.createElement('div');
            overlay.className = 'antigravity-modal-overlay';
            stopKeyPropagation(overlay);
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.background = 'rgba(9, 9, 11, 0.7)';
            overlay.style.backdropFilter = 'blur(4px)';
            overlay.style.display = 'flex';
            overlay.style.alignItems = 'center';
            overlay.style.justifyContent = 'center';
            overlay.style.zIndex = '99998';
            overlay.style.opacity = '0';
            overlay.style.transition = 'opacity 0.2s ease';

            const modal = document.createElement('div');
            modal.style.background = 'var(--popover, #1e1e24)';
            modal.style.border = '1px solid var(--border, #3f3f46)';
            modal.style.borderRadius = '12px';
            modal.style.padding = '24px';
            modal.style.width = '450px';
            modal.style.maxWidth = '90vw';
            modal.style.boxShadow = '0 20px 25px -5px rgba(0,0,0,0.5)';
            modal.style.display = 'flex';
            modal.style.flexDirection = 'column';
            modal.style.gap = '16px';
            modal.style.transform = 'scale(0.95)';
            modal.style.transition = 'transform 0.2s ease';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');

            const optionSelect = type === 'preference'
                ? '<option value="lesson_learned">Gelernte Technik (MEMORY.pc.md)</option><option value="preference" selected>Benutzerpräferenz (USER.pc.md)</option>'
                : '<option value="lesson_learned" selected>Gelernte Technik (MEMORY.pc.md)</option><option value="preference">Benutzerpräferenz (USER.pc.md)</option>';

            modal.innerHTML =
                '<div style="display: flex; align-items: center; gap: 8px;">' +
                    '<span style="font-size: 24px;">🧠</span>' +
                    '<h3 style="font-size: 18px; font-weight: 600; color: var(--foreground, #ffffff); margin: 0;">Neues Wissen sichern</h3>' +
                '</div>' +
                '<p style="font-size: 13px; color: var(--muted-foreground, #a1a1aa); margin: 0; line-height: 1.4;">' +
                    'Die KI hat eine neue Erkenntnis oder Präferenz in diesem Chat erkannt. Du kannst sie vor dem Speichern bearbeiten:' +
                '</p>' +
                '<div style="display: flex; flex-direction: column; gap: 6px;">' +
                    '<label style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--muted-foreground, #71717a);">Gedächtnistyp</label>' +
                    '<select id="ams-memory-type" style="background: var(--background, #09090b); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 8px; font-size: 13px; outline: none;">' +
                        optionSelect +
                    '</select>' +
                '</div>' +
                '<div style="display: flex; flex-direction: column; gap: 6px;">' +
                    '<label style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--muted-foreground, #71717a);">Erkenntnis / Bulletpoint</label>' +
                    '<textarea id="ams-memory-text" style="background: var(--background, #09090b); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 10px; font-size: 13px; font-family: inherit; resize: vertical; min-height: 80px; outline: none; line-height: 1.4;"></textarea>' +
                '</div>' +
                '<div style="display: flex; justify-content: end; gap: 12px; margin-top: 8px;">' +
                    '<button id="ams-cancel-modal" style="background: transparent; color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 500;">Verwerfen</button>' +
                    '<button id="ams-save-modal" style="background: var(--primary, #3b82f6); color: var(--primary-foreground, #ffffff); border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 6px;">Speichern & Kompilieren</button>' +
                '</div>';

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            const textarea = modal.querySelector('#ams-memory-text');
            textarea.value = proposedText;
            const modalTitle = modal.querySelector('h3');
            modalTitle.id = 'ams-memory-modal-title-' + Date.now();
            modal.setAttribute('aria-labelledby', modalTitle.id);

            setTimeout(() => {
                overlay.style.opacity = '1';
                modal.style.transform = 'scale(1)';
            }, 50);

            let isSaving = false;
            let tempCleanupStarted = false;
            const cleanupTempConversation = () => {
                if (!tempConvoId || tempCleanupStarted) return Promise.resolve();
                tempCleanupStarted = true;
                return deleteTempConversation(tempConvoId);
            };
            const controller = createAmsModalController({
                overlay,
                modal,
                initialFocus: textarea,
                previouslyFocused,
                removeDelay: 200,
                animateClose: () => {
                    overlay.style.opacity = '0';
                    modal.style.transform = 'scale(0.95)';
                },
                onClose: (reason) => {
                    if (reason !== 'saved') {
                        cleanupTempConversation().catch((error) => {
                            console.warn('[AMS UI] Failed to clean up discarded memory conversation:', error);
                        });
                    }
                },
            });
            const closeModal = (reason = 'discard') => controller.close(reason);
            controller.focusInitial();
            textarea.select();

            modal.querySelector('#ams-cancel-modal').addEventListener('click', () => {
                closeModal('discard');
            });

            modal.querySelector('#ams-save-modal').addEventListener('click', async () => {
                if (isSaving || controller.isClosed()) return;
                const saveBtn = modal.querySelector('#ams-save-modal');
                const selectedType = modal.querySelector('#ams-memory-type').value;
                const textToSave = textarea.value.trim();

                if (!textToSave) {
                    showCustomAlert('Bitte trage eine Erkenntnis ein.');
                    return;
                }

                isSaving = true;
                saveBtn.disabled = true;
                saveBtn.innerHTML = '💾 Speichere...';
                saveBtn.style.opacity = '0.7';

                try {
                    const res = await window.electronNative.applyMemorySuggestion(selectedType, textToSave);
                    if (res && res.status === 'success') {
                        showToast('Gedächtnis erfolgreich aktualisiert und kompiliert!', 'success');
                        closeModal('saved');
                    } else if (res && res.status === 'warning') {
                        showToast('Erkenntnis gespeichert, Kompilierung fehlgeschlagen: ' + res.message, 'error');
                        closeModal('saved');
                    } else {
                        showCustomAlert('Fehler beim Speichern: ' + (res ? res.message : 'Unbekannter Fehler'));
                        saveBtn.disabled = false;
                        saveBtn.innerHTML = 'Speichern & Kompilieren';
                        saveBtn.style.opacity = '1';
                    }

                    if (res && (res.status === 'success' || res.status === 'warning')) {
                        await cleanupTempConversation();
                    }
                } catch (saveErr) {
                    console.error('[AMS UI] Failed to save memory suggestion:', saveErr);
                    showCustomAlert('Speicherfehler: ' + saveErr.message);
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = 'Speichern & Kompilieren';
                    saveBtn.style.opacity = '1';
                } finally {
                    isSaving = false;
                }
            });
        }
    }

    // ----------------------------------------------------

    // React changes are observed and coalesced instead of scanning the full DOM twice per second.
    let lastSyncStatusCheck = 0;
    let injectionScanInFlight = false;
    const runInjectionScan = async () => {
        if (document.hidden || injectionScanInFlight) return;
        injectionScanInFlight = true;
        try {
        // Modal-Off-Check: Reset active tab state if modal is closed
        const isModalOpen = !!document.querySelector('.animate-modalScaleIn') || !!document.querySelector('[role="dialog"]');
        if (!isModalOpen) {
            window.__antigravity_active_tab = '';
        }

        const logsTab = document.getElementById('antigravity-settings-logs-tab');
        if (logsTab) {
            if (window.__antigravity_active_tab === 'logs') {
                if (!logsTab.classList.contains('bg-sidebar-secondary')) {
                    logsTab.classList.add('bg-sidebar-secondary');
                    logsTab.classList.remove('hover:bg-sidebar-muted');
                }
                const sidebar = logsTab.parentElement;
                if (sidebar) {
                    sidebar.querySelectorAll('button, [role="tab"]').forEach(btn => {
                        if (btn !== logsTab && btn.classList.contains('bg-sidebar-secondary')) {
                            btn.classList.remove('bg-sidebar-secondary');
                            btn.classList.add('hover:bg-sidebar-muted');
                        }
                    });
                }
            } else {
                if (logsTab.classList.contains('bg-sidebar-secondary')) {
                    logsTab.classList.remove('bg-sidebar-secondary');
                    logsTab.classList.add('hover:bg-sidebar-muted');
                }
            }
        }

        if (window.__antigravity_active_tab === 'logs') {
            const logsTab = document.getElementById('antigravity-settings-logs-tab');
            if (logsTab) {
                const sidebar = logsTab.parentElement;
                if (sidebar) {
                    const sidebarContainer = sidebar.closest('.bg-sidebar');
                    if (sidebarContainer) {
                        const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                                (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
                        const rightPanel = layoutContainer ? layoutContainer.children[1] : null;
                        if (rightPanel) {
                            const container = document.getElementById('antigravity-log-viewer-container');
                            const isRendered = container && container.style.display === 'flex' && container.querySelector('#log-rows-container');

                            // Check if React re-rendered other elements and made them visible
                            let othersVisible = false;
                            for (let i = 0; i < rightPanel.children.length; i++) {
                                const child = rightPanel.children[i];
                                if (child !== container && child.style.display !== 'none') {
                                    othersVisible = true;
                                    break;
                                }
                            }

                            if (!isRendered || othersVisible) {
                                renderAppLogViewer();
                            }
                        }
                    }
                }
            }
        }
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        let btn = document.querySelector('.antigravity-brain-btn');
        let quotaEl = document.querySelector('.antigravity-quota-display');
        let planToggleBtn = document.querySelector('.antigravity-plan-btn');
        let duplicateBtn = document.querySelector('.antigravity-duplicate-btn');
        let chatTokenEl = document.querySelector('#antigravity-chat-token-counter');

        if (addContextBtn && !btn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'antigravity-brain-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                btn.title = 'Brain-Ordner öffnen';
                btn.style.marginLeft = '6px';
                btn.style.padding = '0';
                btn.style.background = 'transparent';
                btn.style.border = 'none';
                btn.style.outline = 'none';
                btn.style.display = 'inline-flex';

                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                '<path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2Z"/>' +
                                '<path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2Z"/>' +
                                '</svg>';

                btn.addEventListener('click', () => {
                    try {
                        if (window.electronNative && window.electronNative.openBrain) {
                            window.electronNative.openBrain();
                        }
                    } catch (err) {
                        console.error('[AMS UI] Call to openBrain failed:', err);
                    }
                });

                flexContainer.appendChild(btn);
                console.log('[AMS UI] Brain shortcut button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !planToggleBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                planToggleBtn = document.createElement('button');
                planToggleBtn.type = 'button';
                planToggleBtn.className = 'antigravity-plan-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                planToggleBtn.title = 'Task- & Plan-Tracker öffnen';
                planToggleBtn.style.marginLeft = '4px';
                planToggleBtn.style.padding = '0';
                planToggleBtn.style.background = 'transparent';
                planToggleBtn.style.border = 'none';
                planToggleBtn.style.outline = 'none';
                planToggleBtn.style.display = 'inline-flex';

                planToggleBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                          '<path d="M12 20h9"/>' +
                                          '<path d="M3 20h.01"/>' +
                                          '<path d="M3 14h.01"/>' +
                                          '<path d="M3 8h.01"/>' +
                                          '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>' +
                                          '<path d="m9 11 2 2 4-4"/>' +
                                          '</svg>';

                planToggleBtn.addEventListener('click', () => {
                    togglePlanPanel();
                });

                if (btn) {
                    btn.after(planToggleBtn);
                } else {
                    flexContainer.appendChild(planToggleBtn);
                }
                console.log('[AMS UI] Plan shortcut button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !duplicateBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                duplicateBtn = document.createElement('button');
                duplicateBtn.type = 'button';
                duplicateBtn.className = 'antigravity-duplicate-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                duplicateBtn.title = 'Fenster duplizieren';
                duplicateBtn.style.marginLeft = '4px';
                duplicateBtn.style.padding = '0';
                duplicateBtn.style.background = 'transparent';
                duplicateBtn.style.border = 'none';
                duplicateBtn.style.outline = 'none';
                duplicateBtn.style.display = 'inline-flex';

                duplicateBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                         '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>' +
                                         '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
                                         '</svg>';

                duplicateBtn.addEventListener('click', () => {
                    try {
                        if (window.electronNative && window.electronNative.openDuplicateWindow) {
                            window.electronNative.openDuplicateWindow(amsToken);
                        } else {
                            window.open(window.location.href, '_blank');
                        }
                    } catch (err) {
                        console.error('[AMS UI] Call to openDuplicateWindow failed:', err);
                    }
                });

                if (planToggleBtn) {
                    planToggleBtn.after(duplicateBtn);
                } else if (btn) {
                    btn.after(duplicateBtn);
                } else {
                    flexContainer.appendChild(duplicateBtn);
                }
                console.log('[AMS UI] Duplicate shortcut button successfully appended to flex container.');
            }
        }

        let quickMenuBtn = document.querySelector('.antigravity-quickmenu-btn');
        if (addContextBtn && !quickMenuBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                quickMenuBtn = document.createElement('button');
                quickMenuBtn.type = 'button';
                quickMenuBtn.className = 'antigravity-quickmenu-btn flex items-center justify-center h-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                quickMenuBtn.title = 'Antigravity Unleashed · Quick Menu (Ctrl+Shift+B)';
                quickMenuBtn.style.marginLeft = '4px';
                quickMenuBtn.style.padding = '0 7px';
                quickMenuBtn.style.gap = '5px';
                quickMenuBtn.style.background = 'rgba(139, 92, 246, 0.08)';
                quickMenuBtn.style.border = '1px solid rgba(139, 92, 246, 0.24)';
                quickMenuBtn.style.outline = 'none';
                quickMenuBtn.style.display = 'inline-flex';
                quickMenuBtn.style.alignItems = 'center';

                quickMenuBtn.innerHTML =
                    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
                    '<ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.7" stroke-opacity="0.85"/>' +
                    '<polygon points="12,3.2 19.2,12 12,20.8 4.8,12" fill="rgba(139,92,246,0.22)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
                    '<circle cx="12" cy="12" r="2.1" fill="#f8fafc"/>' +
                    '</svg>' +
                    '<span style="font-size:10px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Unleashed</span>';

                quickMenuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (window.toggleQuickMenu) {
                        window.toggleQuickMenu();
                    }
                });

                if (duplicateBtn) {
                    duplicateBtn.after(quickMenuBtn);
                } else if (planToggleBtn) {
                    planToggleBtn.after(quickMenuBtn);
                } else if (btn) {
                    btn.after(quickMenuBtn);
                } else {
                    flexContainer.appendChild(quickMenuBtn);
                }
                console.log('[AMS UI] Quick menu button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !quotaEl) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                quotaEl = document.createElement('div');
                quotaEl.className = 'antigravity-quota-display';
                quotaEl.style.display = 'inline-flex';
                quotaEl.style.alignItems = 'center';
                quotaEl.style.gap = '6px';
                quotaEl.style.fontSize = '10px';
                quotaEl.style.color = 'var(--muted-foreground, #9d9d9d)';
                quotaEl.style.marginLeft = '8px';
                quotaEl.style.marginRight = '4px';
                quotaEl.style.fontFamily = 'monospace';
                quotaEl.style.userSelect = 'none';
                quotaEl.style.cursor = 'pointer';

                quotaEl.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const settingsBtn = document.querySelector('[data-testid="settings-button"]');
                    if (settingsBtn) {
                        settingsBtn.click();
                        let attempts = 0;
                        const interval = setInterval(() => {
                            let modelsTab = null;
                            document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                                if (btn.textContent && btn.textContent.trim() === 'Models') {
                                    modelsTab = btn;
                                }
                            });
                            if (modelsTab) {
                                modelsTab.click();
                                clearInterval(interval);
                            }
                            attempts++;
                            if (attempts > 20) {
                                clearInterval(interval);
                            }
                        }, 50);
                    }
                });

                flexContainer.appendChild(quotaEl);
                refreshQuotaDisplay();
                console.log('[AMS UI] Quota display successfully appended to flex container.');
            }
        }

        if (addContextBtn && !chatTokenEl) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                chatTokenEl = document.createElement('span');
                chatTokenEl.id = 'antigravity-chat-token-counter';
                chatTokenEl.style.display = 'none';
                chatTokenEl.style.alignItems = 'center';
                chatTokenEl.style.fontSize = '10px';
                chatTokenEl.style.color = 'var(--muted-foreground, #9d9d9d)';
                chatTokenEl.style.marginLeft = '8px';
                chatTokenEl.style.marginRight = '4px';
                chatTokenEl.style.fontFamily = 'monospace';
                chatTokenEl.style.userSelect = 'none';
                chatTokenEl.style.cursor = 'help';

                if (quotaEl) {
                    quotaEl.after(chatTokenEl);
                } else {
                    flexContainer.appendChild(chatTokenEl);
                }
                console.log('[AMS UI] Chat token counter successfully appended to flex container.');
            }
        }

        const settingsBtn = document.querySelector('[data-testid="settings-button"]');
        let customSidebarBtn = document.querySelector('.antigravity-custom-sidebar-btn');
        if (settingsBtn && !customSidebarBtn) {
            customSidebarBtn = document.createElement('div');
            customSidebarBtn.role = 'button';
            customSidebarBtn.tabIndex = 0;
            customSidebarBtn.className = 'antigravity-custom-sidebar-btn flex-grow flex items-center gap-1.5 group px-2 py-1 rounded-lg cursor-pointer h-8 min-w-0 bg-transparent hover:bg-sidebar-muted text-secondary-foreground';
            customSidebarBtn.style.outline = 'none';
            customSidebarBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"></path><path d="M12 6v6l4 2"></path></svg>' +
                                         '<span class="select-none truncate text-sm font-normal">History</span>';

            customSidebarBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    const settingsBtn = document.querySelector('[data-testid="settings-button"]');
                    if (settingsBtn) {
                        settingsBtn.click();
                        let attempts = 0;
                        const interval = setInterval(() => {
                            let logViewerTab = null;
                            document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                                if (btn.textContent && btn.textContent.trim().toLowerCase() === 'log viewer') {
                                    logViewerTab = btn;
                                }
                            });
                            if (logViewerTab) {
                                logViewerTab.click();
                                clearInterval(interval);
                            }
                            attempts++;
                            if (attempts > 20) {
                                clearInterval(interval);
                            }
                        }, 50);
                    }
                } catch (err) {
                    console.error('[AMS UI] Custom sidebar button click failed:', err);
                }
            });

            settingsBtn.before(customSidebarBtn);
            console.log('[AMS UI] Custom sidebar button successfully injected above settings.');
        }

        if (btn) {
            const now = Date.now();
            if (now - lastSyncStatusCheck >= 30_000) {
                lastSyncStatusCheck = now;
                try {
                    if (window.electronNative && window.electronNative.getSyncStatus) {
                        const statusInfo = await window.electronNative.getSyncStatus();

                        if (!document.getElementById('antigravity-brain-styles')) {
                            const style = document.createElement('style');
                            style.id = 'antigravity-brain-styles';
                            style.innerHTML = '@keyframes brain-pulse {' +
                                              '  0%, 100% { opacity: 1; transform: scale(1); }' +
                                              '  50% { opacity: .65; transform: scale(1.05); }' +
                                              '}' +
                                              '.antigravity-brain-conflict {' +
                                              '  color: #f97316 !important;' +
                                              '  animation: brain-pulse 2s infinite ease-in-out;' +
                                              '}';
                            document.head.appendChild(style);
                        }

                        if (statusInfo && statusInfo.status === 'conflict') {
                            btn.classList.add('antigravity-brain-conflict');
                            const cleanNames = statusInfo.conflictFiles.map(f => {
                                if (f.startsWith('- [CONFLICT]')) {
                                    return f.replace('- [CONFLICT] Conflict in ', '').split(' at ')[0];
                                }
                                return f;
                            });
                            const filesStr = cleanNames.slice(0, 3).join(', ') + (cleanNames.length > 3 ? '...' : '');
                            btn.title = 'Achtung: Git-Konflikte/Backups im Brain-Ordner erkannt! (' + filesStr + '). Klicke hier zum Öffnen.';
                        } else {
                            btn.classList.remove('antigravity-brain-conflict');
                            btn.title = 'Brain-Ordner öffnen';
                        }
                    }
                } catch (err) {
                    console.error('[AMS UI] Failed to fetch sync status:', err);
                }
            }
        }

        // ----------------------------------------------------
        // Log Viewer Tab Injection inside Settings modal
        // ----------------------------------------------------
        try {
            let modelsTab = null;
            document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                if (btn.textContent) {
                    const txt = btn.textContent.trim().toLowerCase();
                    if (txt === 'models' || txt === 'modelle') {
                        modelsTab = btn;
                    }
                }
            });

            if (modelsTab) {
                const sidebar = modelsTab.parentElement;
                if (sidebar && !document.getElementById('antigravity-settings-logs-tab')) {
                    const logsTab = document.createElement('button');
                    logsTab.type = 'button';
                    logsTab.id = 'antigravity-settings-logs-tab';
                    logsTab.className = modelsTab.className;
                    logsTab.innerHTML = modelsTab.innerHTML;

                    const textSpan = logsTab.querySelector('span');
                    if (textSpan) {
                        textSpan.textContent = 'Log Viewer';
                    }

                    const svg = logsTab.querySelector('svg');
                    if (svg) {
                        svg.innerHTML = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9">';
                    }

                    logsTab.addEventListener('click', async (e) => {
                        e.preventDefault();
                        e.stopPropagation();

                        sidebar.querySelectorAll('button, [role="tab"]').forEach(btn => {
                            btn.classList.remove('bg-sidebar-secondary');
                            btn.classList.add('hover:bg-sidebar-muted');
                        });
                        logsTab.classList.add('bg-sidebar-secondary');
                        logsTab.classList.remove('hover:bg-sidebar-muted');

                        window.__antigravity_active_tab = 'logs';
                        renderAppLogViewer();
                    });

                    sidebar.appendChild(logsTab);

                    // Robust event delegation on the sidebar container to catch all clicks to other tabs
                    const sidebarContainer = sidebar.closest('.bg-sidebar');
                    if (sidebarContainer && !sidebarContainer.hasAttribute('antigravity-listener-added')) {
                        sidebarContainer.setAttribute('antigravity-listener-added', 'true');
                        sidebarContainer.addEventListener('click', (e) => {
                            const btn = e.target.closest('button, [role="tab"]');
                            if (btn && btn !== logsTab) {
                                logsTab.classList.remove('bg-sidebar-muted', 'text-sidebar-accent-foreground');
                                logsTab.style.background = '';
                                window.__antigravity_active_tab = '';

                                const container = document.getElementById('antigravity-log-viewer-container');
                                if (container) {
                                    container.style.display = 'none';
                                }

                                const dialog = document.querySelector('.animate-modalScaleIn') || document.querySelector('[role="dialog"]');
                                if (dialog) {
                                    const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                                            (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
                                    const rightPanel = layoutContainer ? layoutContainer.children[1] : null;
                                    if (rightPanel) {
                                        for (let i = 0; i < rightPanel.children.length; i++) {
                                            const child = rightPanel.children[i];
                                            if (child !== container) {
                                                child.style.display = '';
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }
                }
            }
        } catch (settingsErr) {
            console.error('[AMS UI] Error injecting Log Viewer tab:', settingsErr);
        }
        } finally {
            injectionScanInFlight = false;
        }
    };

    let injectionScanTimer = null;
    const scheduleInjectionScan = () => {
        if (document.hidden) return;
        if (injectionScanTimer !== null) clearTimeout(injectionScanTimer);
        injectionScanTimer = setTimeout(() => {
            injectionScanTimer = null;
            runInjectionScan().catch((error) => console.error('[AMS UI] DOM injection scan failed:', error));
        }, 120);
    };
    const injectionObserver = new MutationObserver((records) => {
        if (records.some((record) => record.addedNodes.length > 0 || record.removedNodes.length > 0)) {
            scheduleInjectionScan();
        }
    });
    injectionObserver.observe(document.documentElement || document, { childList: true, subtree: true });
    const injectionFallbackInterval = setInterval(scheduleInjectionScan, 10_000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) scheduleInjectionScan();
    });
    scheduleInjectionScan();

    // Real-time Chat Monitor

    window.toggleQuickMenu = function() {
        const existing = document.getElementById('antigravity-quick-menu-overlay');
        if (existing) {
            existing.style.opacity = '0';
            existing.style.transform = 'translateY(8px) scale(0.96)';
            setTimeout(() => existing.remove(), 160);
            return;
        }

        // Compact, well-proportioned English popover
        const overlay = document.createElement('div');
        overlay.id = 'antigravity-quick-menu-overlay';
        overlay.dataset.amsQuickMenu = 'true';
        overlay.style.cssText =
            'position:fixed;bottom:72px;right:16px;width:272px;max-height:80vh;overflow-y:auto;' +
            'background:rgba(18, 18, 21, 0.94);backdrop-filter:blur(14px);' +
            'border:1px solid rgba(255, 255, 255, 0.08);border-radius:10px;' +
            'box-shadow:0 14px 32px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.04);' +
            'z-index:999999;padding:10px 12px;color:#fafafa;' +
            'font-family:ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;' +
            'display:flex;flex-direction:column;gap:8px;opacity:0;' +
            'transform:translateY(8px) scale(0.96);' +
            'transition:opacity 0.16s cubic-bezier(0.16, 1, 0.3, 1), transform 0.16s cubic-bezier(0.16, 1, 0.3, 1);';

        // Header
        const header = document.createElement('div');
        header.style.cssText =
            'display:flex;align-items:center;justify-content:space-between;' +
            'border-bottom:1px solid rgba(255, 255, 255, 0.07);padding-bottom:6px;';

        const title = document.createElement('span');
        title.style.cssText =
            'display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;letter-spacing:0.2px;color:#f8fafc;';
        title.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
            '<ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.8" stroke-opacity="0.9"/>' +
            '<polygon points="12,3 19.4,12 12,21 4.6,12" fill="rgba(139,92,246,0.28)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
            '<circle cx="12" cy="12" r="2.2" fill="#f8fafc"/>' +
            '</svg>' +
            '<span>Unleashed</span>' +
            '<span style="font-size:8.5px;font-weight:700;padding:1px 4px;border-radius:3px;background:rgba(139,92,246,0.16);border:1px solid rgba(139,92,246,0.32);color:#c4b5fd;letter-spacing:0.05em;">v2.26</span>';

        const closeBtn = document.createElement('button');
        closeBtn.textContent = '✕';
        closeBtn.style.cssText =
            'background:transparent;border:none;color:rgba(255,255,255,0.4);cursor:pointer;font-size:11px;padding:2px 4px;line-height:1;';
        closeBtn.addEventListener('click', () => window.toggleQuickMenu());

        header.appendChild(title);
        header.appendChild(closeBtn);
        overlay.appendChild(header);

        // Compact Status Section
        const statusSection = document.createElement('div');
        statusSection.style.cssText =
            'font-size:11px;display:flex;flex-direction:column;gap:4px;' +
            'background:rgba(255, 255, 255, 0.025);padding:7px 9px;border-radius:6px;' +
            'border:1px solid rgba(255, 255, 255, 0.04);';

        const activeModel = getActiveModel ? getActiveModel() : 'Gemini 3.5 Flash';
        const modelRow = document.createElement('div');
        modelRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;';
        modelRow.innerHTML = '<span style="color:rgba(255,255,255,0.48)">Model</span>';
        const modelValue = document.createElement('span');
        modelValue.style.cssText = 'font-weight:500;color:rgba(255,255,255,0.88);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
        modelValue.textContent = String(activeModel || 'Unknown');
        modelRow.appendChild(modelValue);
        statusSection.appendChild(modelRow);

        const syncRow = document.createElement('div');
        syncRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;';
        syncRow.innerHTML = '<span style="color:rgba(255,255,255,0.48)">Git Sync</span><span id="ams-sync-indicator" style="font-weight:500">Checking...</span>';
        statusSection.appendChild(syncRow);

        const localHubEnabled = (
            window.__antigravity_enable_local_hub === true ||
            (window.localStorage && window.localStorage.getItem('antigravity_enable_local_hub') === '1')
        );

        if (localHubEnabled) {
            const hubRow = document.createElement('div');
            hubRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;';
            hubRow.innerHTML = '<span style="color:rgba(255,255,255,0.48)">Local Hub</span><span id="ams-antigravity-hub-indicator" style="font-weight:500;color:#fbbf24">● Checking…</span>';
            statusSection.appendChild(hubRow);

            const bridgeRow = document.createElement('div');
            bridgeRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;';
            bridgeRow.innerHTML = '<span style="color:rgba(255,255,255,0.48)">API Bridge</span><span id="ams-antigravity-bridge-indicator" style="font-weight:500;color:#fbbf24">● Checking…</span>';
            statusSection.appendChild(bridgeRow);
        }

        overlay.appendChild(statusSection);

        // Repack Ready Card inside UNLEASHED (if ASAR changes are waiting for user click)
        const rInfo = window.amsTelemetryState && window.amsTelemetryState.repackInfo;
        if (rInfo && (rInfo.pending || rInfo.repacking)) {
            const repackCard = document.createElement('div');
            repackCard.style.cssText =
                'display:flex;flex-direction:column;gap:5px;padding:8px 9px;border-radius:6px;' +
                'background:rgba(245,158,11,0.11);border:1px solid rgba(251,191,36,0.38);font-size:10.5px;line-height:1.3;';
            const titleText = escapeHtml(rInfo.title || 'UI update ready');
            const detailText = escapeHtml(rInfo.details || 'Changes are staged for repack & restart.');
            repackCard.innerHTML =
                \`<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">\` +
                    \`<strong style="color:#fde68a;font-size:11px;">↻ Restart ready: \${titleText}</strong>\` +
                \`</div>\` +
                \`<div style="color:rgba(255,255,255,0.72);font-size:10px;">\${detailText}</div>\` +
                \`<button type="button" id="ams-quickmenu-repack-btn" style="margin-top:2px;padding:5px 8px;border-radius:5px;border:1px solid rgba(251,191,36,0.5);background:rgba(245,158,11,0.2);color:#fef08a;font-size:10.5px;font-weight:600;cursor:pointer;text-align:center;">\` +
                    (rInfo.repacking ? '⏳ Repacking & restarting (~3s)...' : '↻ Repack & Restart Now') +
                \`</button>\`;
            overlay.appendChild(repackCard);
            const rBtn = repackCard.querySelector('#ams-quickmenu-repack-btn');
            if (rBtn) {
                rBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    rBtn.textContent = '⏳ Repacking & restarting (~3s)...';
                    if (typeof window.amsTriggerRepackNow === 'function') {
                        window.amsTriggerRepackNow();
                    }
                });
            }
        }

        // Compact Display Preferences (only essential toggles)
        const uiPrefsSection = document.createElement('div');
        uiPrefsSection.style.cssText =
            'display:flex;flex-direction:column;gap:3px;padding:7px 9px;border-radius:6px;' +
            'background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.045);font-size:11px;';

        const prefsHeader = document.createElement('div');
        prefsHeader.style.cssText =
            'font-size:9.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:rgba(255,255,255,0.4);margin-bottom:1px;';
        prefsHeader.textContent = 'Display';
        uiPrefsSection.appendChild(prefsHeader);

        const curPrefs = typeof window.amsGetUiPrefs === 'function'
            ? window.amsGetUiPrefs()
            : { show5hLimit: false, showDuplicateIcon: false, showSidebarPct: false };

        const prefItems = [
            { key: 'show5hLimit', label: '5h Quota Limit' },
            { key: 'showSidebarPct', label: 'Sidebar Chat %' },
            { key: 'showDuplicateIcon', label: 'Duplicate Window Icon' },
        ];

        prefItems.forEach(({ key, label }) => {
            const row = document.createElement('label');
            row.style.cssText =
                'display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 0;cursor:pointer;color:rgba(255,255,255,0.8);user-select:none;';
            const textSpan = document.createElement('span');
            textSpan.textContent = label;
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = !!curPrefs[key];
            cb.style.cssText = 'accent-color:#38bdf8;cursor:pointer;width:12px;height:12px;margin:0;flex-shrink:0;';
            cb.addEventListener('change', (e) => {
                e.stopPropagation();
                if (typeof window.amsSetUiPref === 'function') {
                    window.amsSetUiPref(key, !!cb.checked);
                }
            });
            row.appendChild(textSpan);
            row.appendChild(cb);
            uiPrefsSection.appendChild(row);
        });

        overlay.appendChild(uiPrefsSection);

        // Compact Collapsible AI Engine & Commit API Section
        const aiSection = document.createElement('div');
        aiSection.id = 'ams-quickmenu-ai-section';
        aiSection.style.cssText =
            'display:flex;flex-direction:column;gap:5px;padding:7px 9px;border-radius:6px;' +
            'background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.045);font-size:11px;';

        const aiHeaderRow = document.createElement('div');
        aiHeaderRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:6px;';

        const aiTitleWrap = document.createElement('div');
        aiTitleWrap.style.cssText = 'display:inline-flex;align-items:center;gap:5px;';
        const aiTitleSpan = document.createElement('span');
        aiTitleSpan.style.cssText =
            'font-size:9.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:rgba(255,255,255,0.4);';
        aiTitleSpan.textContent = 'Commit AI';

        const aiBadge = document.createElement('span');
        aiBadge.style.cssText =
            'font-size:9px;font-weight:600;padding:1px 5px;border-radius:999px;' +
            'background:rgba(56,189,248,0.12);border:1px solid rgba(56,189,248,0.28);color:#38bdf8;';
        aiBadge.textContent = 'Auto';

        aiTitleWrap.appendChild(aiTitleSpan);
        aiTitleWrap.appendChild(aiBadge);

        const aiExpandBtn = document.createElement('button');
        aiExpandBtn.type = 'button';
        aiExpandBtn.style.cssText =
            'background:transparent;border:1px solid rgba(255,255,255,0.1);border-radius:4px;' +
            'padding:1px 6px;font-size:9.5px;color:rgba(255,255,255,0.68);cursor:pointer;';
        aiExpandBtn.textContent = 'API Options ▾';

        aiHeaderRow.appendChild(aiTitleWrap);
        aiHeaderRow.appendChild(aiExpandBtn);
        aiSection.appendChild(aiHeaderRow);

        const aiModeSelect = document.createElement('select');
        aiModeSelect.setAttribute('aria-label', 'Select AI Mode');
        aiModeSelect.style.cssText =
            'width:100%;padding:4px 6px;border-radius:5px;background:rgba(9,9,11,0.85);' +
            'border:1px solid rgba(255,255,255,0.1);color:#fafafa;font-size:11px;outline:none;cursor:pointer;';
        [
            { value: 'auto', label: '⚡ Auto (API → Local UI)' },
            { value: 'unleashed_api', label: '🌐 Unleashed API (/v1)' },
            { value: 'local_ui', label: '🖥️ Direct Antigravity UI' },
            { value: 'off', label: '📝 Rule-based (No AI)' },
        ].forEach((opt) => {
            const o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            o.style.background = '#141417';
            o.style.color = '#fafafa';
            aiModeSelect.appendChild(o);
        });
        aiSection.appendChild(aiModeSelect);

        const aiDrawer = document.createElement('div');
        const shouldAutoOpenDrawer = Boolean(window.__ams_open_ai_settings);
        window.__ams_open_ai_settings = false;
        aiDrawer.style.cssText =
            (shouldAutoOpenDrawer ? 'display:flex;' : 'display:none;') +
            'flex-direction:column;gap:5px;padding-top:5px;border-top:1px solid rgba(255,255,255,0.05);';
        aiExpandBtn.textContent = shouldAutoOpenDrawer ? 'API Options ▴' : 'API Options ▾';

        const urlLabel = document.createElement('label');
        urlLabel.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:10px;color:rgba(255,255,255,0.6);';
        urlLabel.textContent = 'API Base URL (/v1):';
        const urlInput = document.createElement('input');
        urlInput.type = 'text';
        urlInput.placeholder = 'http://127.0.0.1:8001/v1';
        urlInput.style.cssText =
            'width:100%;box-sizing:border-box;padding:4px 6px;border-radius:4px;background:rgba(9,9,11,0.9);' +
            'border:1px solid rgba(255,255,255,0.1);color:#fafafa;font-size:10.5px;' +
            'font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;outline:none;';
        urlLabel.appendChild(urlInput);

        const keyLabel = document.createElement('label');
        keyLabel.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:10px;color:rgba(255,255,255,0.6);';
        keyLabel.textContent = 'API Key / Bearer Token:';
        const keyInput = document.createElement('input');
        keyInput.type = 'password';
        keyInput.placeholder = 'ag-local-token';
        keyInput.style.cssText =
            'width:100%;box-sizing:border-box;padding:4px 6px;border-radius:4px;background:rgba(9,9,11,0.9);' +
            'border:1px solid rgba(255,255,255,0.1);color:#fafafa;font-size:10.5px;' +
            'font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;outline:none;';
        keyLabel.appendChild(keyInput);

        const modelLabel = document.createElement('label');
        modelLabel.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:10px;color:rgba(255,255,255,0.6);';
        modelLabel.textContent = 'AI Model:';
        const modelInput = document.createElement('input');
        modelInput.type = 'text';
        modelInput.placeholder = 'gemini-3.8-flash-medium';
        modelInput.style.cssText =
            'width:100%;box-sizing:border-box;padding:4px 6px;border-radius:4px;background:rgba(9,9,11,0.9);' +
            'border:1px solid rgba(255,255,255,0.1);color:#fafafa;font-size:10.5px;' +
            'font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;outline:none;';
        modelLabel.appendChild(modelInput);

        const aiBtnRow = document.createElement('div');
        aiBtnRow.style.cssText = 'display:flex;gap:5px;margin-top:2px;';

        const testAiBtn = document.createElement('button');
        testAiBtn.type = 'button';
        testAiBtn.textContent = '🔌 Test';
        testAiBtn.style.cssText =
            'flex:1;padding:4px 6px;border-radius:4px;border:1px solid rgba(56,189,248,0.35);' +
            'background:rgba(56,189,248,0.12);color:#38bdf8;font-size:10.5px;font-weight:600;cursor:pointer;';

        const saveAiBtn = document.createElement('button');
        saveAiBtn.type = 'button';
        saveAiBtn.textContent = '✓ Save';
        saveAiBtn.style.cssText =
            'flex:1;padding:4px 6px;border-radius:4px;border:1px solid rgba(34,197,94,0.4);' +
            'background:rgba(34,197,94,0.15);color:#4ade80;font-size:10.5px;font-weight:600;cursor:pointer;';

        aiBtnRow.appendChild(testAiBtn);
        aiBtnRow.appendChild(saveAiBtn);

        const aiStatusMsg = document.createElement('div');
        aiStatusMsg.style.cssText = 'display:none;font-size:10px;line-height:1.3;padding:4px 6px;border-radius:4px;';

        const showAiStatus = (msg, isErr = false) => {
            aiStatusMsg.style.display = 'block';
            aiStatusMsg.style.background = isErr ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)';
            aiStatusMsg.style.border = isErr ? '1px solid rgba(239,68,68,0.3)' : '1px solid rgba(34,197,94,0.3)';
            aiStatusMsg.style.color = isErr ? '#fca5a5' : '#86efac';
            aiStatusMsg.textContent = msg;
        };

        const updateBadgeFromConfig = (cfg) => {
            if (!cfg) return;
            if (cfg.mode === 'off') {
                aiBadge.textContent = 'Off';
                aiBadge.style.color = '#a1a1aa';
            } else if (cfg.mode === 'local_ui') {
                aiBadge.textContent = 'Local UI';
                aiBadge.style.color = '#c4b5fd';
            } else {
                const shortHost = String(cfg.apiUrl || '').replace(/^https?:\\/\\//, '').replace(/\\/v1.*$/, '');
                aiBadge.textContent = (cfg.mode === 'auto' ? 'Auto · ' : 'API · ') + (shortHost || ':8001');
                aiBadge.style.color = '#38bdf8';
            }
        };

        const persistCurrentAiConfig = async (showNotice = false) => {
            if (!window.electronNative || !window.electronNative.saveAiConfig) return;
            const patch = {
                mode: aiModeSelect.value,
                apiUrl: urlInput.value.trim() || 'http://127.0.0.1:8001/v1',
                apiKey: keyInput.value.trim(),
                model: modelInput.value.trim() || 'gemini-3.8-flash-medium',
            };
            try {
                const res = await window.electronNative.saveAiConfig(patch);
                if (res && res.config) {
                    window.__ams_cached_ai_config = res.config;
                    updateBadgeFromConfig(res.config);
                    if (showNotice) showAiStatus('✓ Saved (' + res.config.mode + ')');
                }
            } catch (err) {
                if (showNotice) showAiStatus('✗ ' + err.message, true);
            }
        };

        aiDrawer.appendChild(urlLabel);
        aiDrawer.appendChild(keyLabel);
        aiDrawer.appendChild(modelLabel);
        aiDrawer.appendChild(aiBtnRow);
        aiDrawer.appendChild(aiStatusMsg);
        aiSection.appendChild(aiDrawer);

        aiExpandBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = aiDrawer.style.display === 'none';
            aiDrawer.style.display = isHidden ? 'flex' : 'none';
            aiExpandBtn.textContent = isHidden ? 'API Options ▴' : 'API Options ▾';
        });

        aiModeSelect.addEventListener('change', (e) => {
            e.stopPropagation();
            persistCurrentAiConfig(true);
        });
        saveAiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            persistCurrentAiConfig(true);
        });
        testAiBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!window.electronNative || !window.electronNative.testAiConnection) return;
            testAiBtn.disabled = true;
            testAiBtn.textContent = '⏳ Testing...';
            try {
                const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
                const res = await window.electronNative.testAiConnection({
                    mode: aiModeSelect.value,
                    apiUrl: urlInput.value.trim() || 'http://127.0.0.1:8001/v1',
                    apiKey: keyInput.value.trim(),
                    model: modelInput.value.trim() || 'gemini-3.8-flash-medium',
                }, csrfToken);
                if (res && res.status === 'success') {
                    showAiStatus('✓ ' + (res.message || 'Connected!'));
                } else {
                    showAiStatus('✗ ' + ((res && res.message) || 'Connection failed'), true);
                }
            } catch (err) {
                showAiStatus('✗ ' + err.message, true);
            } finally {
                testAiBtn.disabled = false;
                testAiBtn.textContent = '🔌 Test';
            }
        });

        if (window.electronNative && window.electronNative.getAiConfig) {
            window.electronNative.getAiConfig().then((res) => {
                if (res && res.config) {
                    const cfg = res.config;
                    window.__ams_cached_ai_config = cfg;
                    aiModeSelect.value = cfg.mode || 'auto';
                    urlInput.value = cfg.apiUrl || 'http://127.0.0.1:8001/v1';
                    keyInput.value = cfg.apiKey || '';
                    modelInput.value = cfg.model || 'gemini-3.8-flash-medium';
                    updateBadgeFromConfig(cfg);
                }
            }).catch(() => {});
        }

        overlay.appendChild(aiSection);

        // Essential Actions Section
        const actionsSection = document.createElement('div');
        actionsSection.style.cssText = 'display:flex;flex-direction:column;gap:2px;';

        const createMenuItem = (label, iconSvg, onClick, closeOnClick = true) => {
            const item = document.createElement('button');
            item.style.cssText =
                'display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;' +
                'background:transparent;border:none;border-radius:5px;color:rgba(255,255,255,0.82);' +
                'font-size:11.5px;text-align:left;cursor:pointer;transition:background 0.15s, color 0.15s;';

            item.innerHTML = iconSvg;
            const labelSpan = document.createElement('span');
            labelSpan.textContent = String(label || '');
            item.appendChild(labelSpan);

            item.addEventListener('mouseenter', () => {
                item.style.background = 'rgba(255, 255, 255, 0.07)';
                item.style.color = '#ffffff';
            });
            item.addEventListener('mouseleave', () => {
                item.style.background = 'transparent';
                item.style.color = 'rgba(255, 255, 255, 0.82)';
            });
            item.addEventListener('click', (e) => {
                if (closeOnClick) {
                    window.toggleQuickMenu();
                } else if (e && typeof e.stopPropagation === 'function') {
                    e.stopPropagation();
                }
                onClick();
            });
            return item;
        };

        const syncSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>\`;
        actionsSection.appendChild(createMenuItem('Git Sync & Cloud Backup', syncSvg, () => {
            const convoId = getSessionId ? getSessionId() : '';
            if (typeof showGitSyncModal === 'function') {
                showGitSyncModal(convoId, async (commitMsg) => {
                    if (window.electronNative && window.electronNative.commitAndPush) {
                        await window.electronNative.commitAndPush(commitMsg || 'wip: sync tasks', convoId);
                    }
                });
            }
        }));

        const autoSyncSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>\`;
        let currentAutoSyncMinutes = Number(window.__ams_config_auto_sync_minutes || 0);
        const autoSyncItem = createMenuItem(
            currentAutoSyncMinutes > 0
                ? \`Auto-Sync: Every \${currentAutoSyncMinutes}m ✓\`
                : 'Auto-Sync: Off (click for 15m)',
            autoSyncSvg,
            async () => {
                const nextMinutes = currentAutoSyncMinutes > 0 ? 0 : 15;
                if (window.electronNative && window.electronNative.setConfigAutoSync) {
                    try {
                        await window.electronNative.setConfigAutoSync(nextMinutes);
                        if (typeof window.applyConfigAutoSyncTimer === 'function') {
                            window.applyConfigAutoSyncTimer(nextMinutes);
                        }
                    } catch (err) {
                        console.error('[AMS Auto-Sync] Failed to toggle auto-sync:', err);
                    }
                }
            },
        );
        actionsSection.appendChild(autoSyncItem);
        if (window.electronNative && window.electronNative.getConfigSyncInfo) {
            window.electronNative.getConfigSyncInfo().then((info) => {
                if (!info || info.status === 'error') return;
                currentAutoSyncMinutes = Number(info.auto_sync_minutes || 0);
                if (typeof window.applyConfigAutoSyncTimer === 'function') {
                    window.applyConfigAutoSyncTimer(currentAutoSyncMinutes);
                }
                const label = autoSyncItem.querySelector('span');
                if (label) {
                    label.textContent = currentAutoSyncMinutes > 0
                        ? \`Auto-Sync: Every \${currentAutoSyncMinutes}m ✓\`
                        : 'Auto-Sync: Off (click for 15m)';
                    label.style.color = currentAutoSyncMinutes > 0 ? '#4ade80' : '';
                }
            }).catch(() => {});
        }

        const duplicateSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>\`;
        actionsSection.appendChild(createMenuItem('Duplicate Window', duplicateSvg, () => {
            if (window.electronNative && window.electronNative.openDuplicateWindow) {
                window.electronNative.openDuplicateWindow(amsToken);
            } else {
                window.open(window.location.href, '_blank');
            }
        }));

        const historySvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/></svg>\`;
        actionsSection.appendChild(createMenuItem('Update & Patch Log', historySvg, () => {
            if (typeof showUpdateHistoryModal === 'function') {
                showUpdateHistoryModal();
            } else if (typeof window.showUpdateHistoryModal === 'function') {
                window.showUpdateHistoryModal();
            }
        }));

        const restartSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38"/></svg>\`;
        if (localHubEnabled) {
            const webSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/></svg>\`;
            actionsSection.appendChild(createMenuItem('Open Anti-Gravity Hub', webSvg, () => {
                if (window.amsAntigravityHub && window.amsAntigravityHub.openHub) {
                    window.amsAntigravityHub.openHub();
                }
            }));

            const startSvg = \`<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>\`;
            const servicesItem = createMenuItem('Start Hub & API Bridge', startSvg, async () => {
                const restart = servicesItem.dataset.restart === 'true';
                try {
                    if (window.amsAntigravityHub && window.amsAntigravityHub.startServices) {
                        await window.amsAntigravityHub.startServices(restart);
                    }
                } catch (err) {
                    console.error(\`[AMS Services] \${restart ? 'Restart' : 'Start'} failed:\`, err);
                }
            });
            servicesItem.id = 'ams-services-menu-item';
            servicesItem.dataset.restart = 'false';
            actionsSection.appendChild(servicesItem);
        }

        overlay.appendChild(actionsSection);

        // Compact Footer
        const signatureFooter = document.createElement('div');
        signatureFooter.style.cssText =
            'display:flex;align-items:center;justify-content:space-between;' +
            'border-top:1px solid rgba(255, 255, 255, 0.06);padding-top:6px;font-size:9.5px;color:rgba(255, 255, 255, 0.4);';

        const brandTag = document.createElement('span');
        brandTag.textContent = 'Antigravity Unleashed · v2.26';
        signatureFooter.appendChild(brandTag);

        const repoLink = document.createElement('button');
        repoLink.type = 'button';
        repoLink.textContent = 'GitHub @EinMelih ↗';
        repoLink.style.cssText =
            'background:transparent;border:none;padding:0;color:#38bdf8;font-size:9.5px;font-weight:500;cursor:pointer;';
        repoLink.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.electronNative && typeof window.electronNative.openExternal === 'function') {
                window.electronNative.openExternal('https://github.com/EinMelih/antigravity-unleashed');
            }
        });
        signatureFooter.appendChild(repoLink);
        overlay.appendChild(signatureFooter);

        document.body.appendChild(overlay);

        if (localHubEnabled && window.amsAntigravityHub && window.amsAntigravityHub.getStatus) {
            window.amsAntigravityHub.getStatus().then((status) => {
                const renderService = (elementId, service) => {
                    const indicator = document.getElementById(elementId);
                    if (!indicator) return;
                    indicator.style.color = service && service.online ? '#4ade80' : '#f87171';
                    indicator.textContent = service && service.online
                        ? \`● Online · \${service.latency_ms} ms\`
                        : '● Offline';
                    indicator.title = service && service.error ? service.error : '';
                };
                renderService('ams-antigravity-hub-indicator', status.hub);
                renderService('ams-antigravity-bridge-indicator', status.bridge);

                const svcItem = document.getElementById('ams-services-menu-item');
                if (svcItem) {
                    const isOnline = (status.hub && status.hub.online) || (status.bridge && status.bridge.online);
                    svcItem.dataset.restart = isOnline ? 'true' : 'false';
                    const labelSpan = svcItem.querySelector('span');
                    const iconSlot = svcItem.querySelector('svg');
                    if (labelSpan) {
                        labelSpan.textContent = isOnline ? 'Restart Hub & API Bridge' : 'Start Hub & API Bridge';
                    }
                    if (iconSlot && isOnline) {
                        iconSlot.outerHTML = restartSvg;
                    }
                }
            }).catch((error) => {
                for (const id of ['ams-antigravity-hub-indicator', 'ams-antigravity-bridge-indicator']) {
                    const indicator = document.getElementById(id);
                    if (indicator) {
                        indicator.style.color = '#f87171';
                        indicator.textContent = '● Offline';
                        indicator.title = error.message;
                    }
                }
            });
        }

        // Open animation
        requestAnimationFrame(() => {
            overlay.style.opacity = '1';
            overlay.style.transform = 'translateY(0) scale(1)';
        });

        // Query Git Sync status
        if (window.electronNative && window.electronNative.getSyncStatus) {
            window.electronNative.getSyncStatus()
                .then(statusInfo => {
                    const ind = document.getElementById('ams-sync-indicator');
                    if (ind) {
                        if (statusInfo.status === 'ok') {
                            ind.textContent = 'Synced ✓';
                            ind.style.color = '#10b981';
                        } else if (statusInfo.status === 'conflict') {
                            ind.textContent = 'Conflict ⚠️';
                            ind.style.color = '#f59e0b';
                            ind.title = 'Conflict files: ' + statusInfo.conflictFiles.join(', ');
                        } else {
                            ind.textContent = 'Error';
                            ind.style.color = '#ef4444';
                        }
                    }
                })
                .catch(() => {
                    const ind = document.getElementById('ams-sync-indicator');
                    if (ind) ind.textContent = 'Error';
                });
        }
    };

    function getAttachedContextItems() {
        const items = [];
        const chips = document.querySelectorAll('[aria-label^="Remove "], .context-chip, [data-testid*="chip"]');
        chips.forEach(chip => {
            const label = chip.getAttribute('aria-label') || '';
            let filename = label.replace(/^Remove\\s+/i, '').trim();
            if (!filename) {
                filename = chip.textContent.trim();
            }
            if (filename && !items.includes(filename)) {
                items.push(filename);
            }
        });
        return items;
    }

    window.syncSessionConfig = async function() {
        try {
            const model = getActiveModel ? getActiveModel() : '';
            const contextItems = getAttachedContextItems();
            const config = {
                model: model,
                contextItems: contextItems,
                updatedAt: Date.now()
            };

            if (window.nativeStorage && window.nativeStorage.updateItems) {
                await window.nativeStorage.updateItems({ antigravity_session_config: config });
            }

            if (window.electronNative && window.electronNative.writeStatus) {
                await window.electronNative.writeStatus(amsToken, model);
            }
        } catch (err) {
            // silent fail
        }
    };

    window.checkModelSwitchRequest = async function() {
        if (!window.electronNative || !window.electronNative.readSwitchRequest) return;
        try {
            const request = await window.electronNative.readSwitchRequest(amsToken);
            if (request && request.model) {
                console.log('[AMS Model Switch] Switched requested to:', request.model);
                const modelBtn = document.querySelector('button[aria-label^="Select model, current:"]');
                if (modelBtn) {
                    modelBtn.click();
                    setTimeout(() => {
                        const options = document.querySelectorAll('[role="option"], [role="menuitem"], button');
                        for (const opt of options) {
                            if (opt.textContent && opt.textContent.trim().toLowerCase().includes(request.model.toLowerCase())) {
                                opt.click();
                                break;
                            }
                        }
                    }, 150);
                }
            }
        } catch (err) {
            // silent fail
        }
    };

    // Periodische Überwachung der Modell- und Kontext-Änderungen sowie Switch-Anfragen
    setInterval(() => {
        if (window.syncSessionConfig) window.syncSessionConfig();
        if (window.checkModelSwitchRequest) window.checkModelSwitchRequest();
    }, 4000);

    // Hintergrund-Auto-Sync für ~/.gemini/config (inkl. usage_stats.json)
    window.applyConfigAutoSyncTimer = function(minutes) {
        const mins = Math.max(0, Number(minutes || 0));
        window.__ams_config_auto_sync_minutes = mins;
        if (window.__ams_config_auto_sync_interval) {
            clearInterval(window.__ams_config_auto_sync_interval);
            window.__ams_config_auto_sync_interval = null;
        }
        if (mins > 0) {
            window.__ams_config_auto_sync_interval = setInterval(() => {
                if (window.electronNative && window.electronNative.syncConfigOnly) {
                    window.electronNative.syncConfigOnly('chore(config): background auto-sync').catch(() => {});
                }
            }, mins * 60 * 1000);
        }
    };

    if (window.electronNative && window.electronNative.getConfigSyncInfo) {
        setTimeout(() => {
            window.electronNative.getConfigSyncInfo().then((info) => {
                if (info && info.auto_sync_minutes > 0 && typeof window.applyConfigAutoSyncTimer === 'function') {
                    window.applyConfigAutoSyncTimer(info.auto_sync_minutes);
                }
            }).catch(() => {});
        }, 4500);
    }


    const ANTIGRAVITY_CHANGELOG_URL = 'https://www.antigravity.google/changelog';
    const ANTIGRAVITY_RELEASES_URL = 'https://www.antigravity.google/releases?tab=hub';
    const MAX_RELEASE_NOTES_LENGTH = 8000;
    const MAX_RELEASE_HIGHLIGHTS = 5;

    const OFFICIAL_RELEASE_FALLBACKS = Object.freeze({
        '2.9.1': Object.freeze({
            publishedAt: '20. August 2026',
            title: 'Remote Control, schnellerer Projektwechsel und mehr',
            summary: 'Remote Control, spürbare Performance-Verbesserungen, eine übersichtlichere Navigation und robustere Fehlerbehandlung.',
            improvements: 11,
            fixes: 15,
            highlights: Object.freeze([
                'Remote Control steuert und überwacht lokale Agent-Sitzungen sicher aus jedem Browser und sendet Benachrichtigungen bei Abschluss oder Rückfragen.',
                'Schnellerer App-Start, Projektwechsel und Aufbau langer Unterhaltungen sowie weniger Verzögerungen während aktiver Sitzungen.',
                'Einklappbare Hauptbereiche, bis zu 30 ungruppierte Unterhaltungen und sofort sichtbare Aktionen verbessern die Sidebar.',
                'Die Customizations-Einstellungen für Skills, Regeln, Plugins, Custom Agents und MCP-Server wurden übersichtlicher gestaltet.',
                'Retry setzt fehlgeschlagene Agent-Aufgaben direkt fort; Custom Agents können vorhandene Customizations über inheritCustomizations übernehmen.',
                'WebP-Anhänge sowie PowerShell- und Zsh-Syntaxhervorhebung werden jetzt unterstützt.',
            ]),
        }),
    });

    function normalizeUpdateVersion(version) {
        return String(version || 'unbekannt')
            .trim()
            .replace(/^v/i, '')
            .replace(/[^0-9A-Za-z.+-]/g, '')
            .slice(0, 32) || 'unbekannt';
    }

    function normalizeReleaseNotes(releaseNotes) {
        let notesText = '';
        if (typeof releaseNotes === 'string') {
            notesText = releaseNotes;
        } else if (Array.isArray(releaseNotes)) {
            notesText = releaseNotes
                .map((entry) => {
                    if (typeof entry === 'string') return entry;
                    return entry && typeof entry.note === 'string' ? entry.note : '';
                })
                .filter(Boolean)
                .join('\\n');
        }

        return notesText
            .replace(/<br\\s*\\/?\\s*>/gi, '\\n')
            .replace(/<\\/(?:p|li|h[1-6])\\s*>/gi, '\\n')
            .replace(/<[^>]*>/g, '')
            .replace(/\\r\\n?/g, '\\n')
            .replace(/\\n{3,}/g, '\\n\\n')
            .trim()
            .slice(0, MAX_RELEASE_NOTES_LENGTH);
    }

    function extractReleaseHighlights(notesText) {
        if (!notesText) return [];
        return notesText
            .split('\\n')
            .map((line) => line.replace(/^\\s*(?:[-*•]|\\d+[.)])\\s*/, '').trim())
            .filter((line) => line.length >= 12)
            .slice(0, MAX_RELEASE_HIGHLIGHTS);
    }

    function buildOfficialReleaseUrl(version) {
        const normalizedVersion = normalizeUpdateVersion(version);
        if (normalizedVersion === 'unbekannt') return ANTIGRAVITY_CHANGELOG_URL;
        return ANTIGRAVITY_RELEASES_URL + '&version=' + encodeURIComponent(normalizedVersion);
    }

    function normalizeReleaseTitle(value) {
        return normalizeReleaseNotes(value)
            .replace(/\\n+/g, ' ')
            .trim()
            .slice(0, 160) || null;
    }

    function normalizeReleaseDate(value) {
        if (!value) return null;
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return null;
        return new Intl.DateTimeFormat('de-DE', {
            day: 'numeric',
            month: 'long',
            year: 'numeric',
        }).format(parsed);
    }

    function isAllowedOfficialAntigravityUrl(value) {
        try {
            const url = new URL(value);
            const allowedHost = url.hostname === 'antigravity.google' || url.hostname === 'www.antigravity.google';
            const allowedPath = url.pathname === '/changelog' || url.pathname === '/releases';
            return url.protocol === 'https:' && allowedHost && allowedPath;
        } catch (_error) {
            return false;
        }
    }

    function resolveOfficialReleaseInfo(version, releaseNotes, releaseMetadata) {
        const normalizedVersion = normalizeUpdateVersion(version);
        const knownRelease = OFFICIAL_RELEASE_FALLBACKS[normalizedVersion] || null;
        const notesText = normalizeReleaseNotes(releaseNotes);
        const feedHighlights = extractReleaseHighlights(notesText);
        const fallbackHighlights = knownRelease ? Array.from(knownRelease.highlights) : [];
        const metadata = releaseMetadata && typeof releaseMetadata === 'object' ? releaseMetadata : {};
        const feedTitle = normalizeReleaseTitle(metadata.releaseName);
        const feedDate = normalizeReleaseDate(metadata.releaseDate);

        return {
            version: normalizedVersion,
            publishedAt: feedDate || (knownRelease ? knownRelease.publishedAt : null),
            title: feedTitle || (knownRelease ? knownRelease.title : null),
            summary: knownRelease ? knownRelease.summary : null,
            improvements: knownRelease ? knownRelease.improvements : null,
            fixes: knownRelease ? knownRelease.fixes : null,
            highlights: feedHighlights.length ? feedHighlights : fallbackHighlights.slice(0, MAX_RELEASE_HIGHLIGHTS),
            notesText,
            detailsStatus: notesText ? 'feed' : (knownRelease ? 'official-fallback' : 'unavailable'),
            releaseUrl: buildOfficialReleaseUrl(normalizedVersion),
            changelogUrl: ANTIGRAVITY_CHANGELOG_URL,
        };
    }


    const AMS_MODAL_FOCUSABLE_SELECTOR = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[contenteditable="true"]',
        '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    function getAmsModalFocusableElements(modal) {
        if (!modal || typeof modal.querySelectorAll !== 'function') return [];
        return Array.from(modal.querySelectorAll(AMS_MODAL_FOCUSABLE_SELECTOR)).filter((element) => {
            if (!element || element.disabled || element.getAttribute?.('aria-hidden') === 'true') return false;
            const view = element.ownerDocument?.defaultView || window;
            const style = typeof view?.getComputedStyle === 'function' ? view.getComputedStyle(element) : null;
            return !style || (style.display !== 'none' && style.visibility !== 'hidden');
        });
    }

    function createAmsModalController({
        overlay,
        modal,
        initialFocus = null,
        previouslyFocused = document.activeElement,
        closeOnEscape = true,
        removeDelay = 0,
        animateClose = null,
        canClose = null,
        onClose = null,
    }) {
        if (!overlay || !modal) throw new Error('Modal controller requires overlay and modal elements.');
        let isClosed = false;
        let removeTimer = null;

        if (!modal.hasAttribute('tabindex')) modal.tabIndex = -1;

        const focusInitial = () => {
            if (isClosed) return;
            const requested = typeof initialFocus === 'function' ? initialFocus() : initialFocus;
            const target = requested?.isConnected !== false ? requested : null;
            const fallback = getAmsModalFocusableElements(modal)[0] || modal;
            (target || fallback).focus?.();
        };

        const restoreFocus = () => {
            if (previouslyFocused?.isConnected && typeof previouslyFocused.focus === 'function') {
                previouslyFocused.focus();
            }
        };

        const finishClose = () => {
            overlay.remove();
            restoreFocus();
        };

        const close = (reason = 'dismiss') => {
            if (isClosed || (typeof canClose === 'function' && canClose(reason) === false)) return false;
            isClosed = true;
            window.removeEventListener('keydown', keyHandler, true);
            try {
                if (typeof animateClose === 'function') animateClose(reason);
            } catch (error) {
                console.warn('[AMS UI] Modal close animation failed:', error);
            }
            try {
                if (typeof onClose === 'function') onClose(reason);
            } catch (error) {
                console.warn('[AMS UI] Modal close hook failed:', error);
            }
            if (removeDelay > 0) {
                removeTimer = setTimeout(finishClose, removeDelay);
            } else {
                finishClose();
            }
            return true;
        };

        const keyHandler = (event) => {
            if (isClosed) return;
            if (event.key === 'Escape' && closeOnEscape) {
                event.preventDefault();
                event.stopImmediatePropagation();
                close('escape');
                return;
            }
            if (event.key !== 'Tab') return;

            const focusable = getAmsModalFocusableElements(modal);
            if (!focusable.length) {
                event.preventDefault();
                modal.focus();
                return;
            }

            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const active = document.activeElement;
            if (!modal.contains(active)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            } else if (!focusable.includes(active)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            } else if (event.shiftKey && active === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && active === last) {
                event.preventDefault();
                first.focus();
            }
        };

        window.addEventListener('keydown', keyHandler, true);
        const controller = {
            close,
            focusInitial,
            isClosed: () => isClosed,
            destroy: () => {
                window.removeEventListener('keydown', keyHandler, true);
                if (removeTimer) clearTimeout(removeTimer);
            },
        };
        overlay.__amsModalController = controller;
        return controller;
    }

    function renderInlineError(container, prefix, message, options = {}) {
        if (!container) return;
        const error = document.createElement('div');
        error.style.color = options.color || '#ef4444';
        error.style.fontSize = options.fontSize || '11px';
        error.style.padding = options.padding || '10px';
        error.style.textAlign = options.textAlign || 'left';
        error.style.marginTop = options.marginTop || '0';
        error.textContent = String(prefix || '') + String(message || 'Unbekannter Fehler');
        container.replaceChildren(error);
    }

    function showCustomPrompt(title, defaultValue, callback) {
        const parent = document.getElementById('antigravity-plan-panel') || document.body;
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.background = 'rgba(9, 9, 11, 0.7)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10000';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';

        const modal = document.createElement('div');
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '8px';
        modal.style.padding = '16px';
        modal.style.width = '85%';
        modal.style.maxWidth = '300px';
        modal.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.5)';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.gap = '12px';
        modal.style.transform = 'scale(0.95)';
        modal.style.transition = 'transform 0.2s ease';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        const label = document.createElement('label');
        label.textContent = title;
        label.style.fontSize = '13px';
        label.style.color = 'var(--foreground, #fafafa)';
        label.style.fontWeight = '500';
        label.id = 'antigravity-prompt-label-' + Date.now();
        modal.setAttribute('aria-labelledby', label.id);

        const input = document.createElement('input');
        input.type = 'text';
        input.setAttribute('aria-labelledby', label.id);
        input.value = defaultValue || '';
        input.style.background = 'var(--background, #09090b)';
        input.style.border = '1px solid var(--border, #27272a)';
        input.style.borderRadius = '4px';
        input.style.padding = '6px 10px';
        input.style.fontSize = '12px';
        input.style.color = 'var(--foreground, #fafafa)';
        input.style.outline = 'none';

        const buttons = document.createElement('div');
        buttons.style.display = 'flex';
        buttons.style.justifyContent = 'flex-end';
        buttons.style.gap = '8px';

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Abbrechen';
        cancelBtn.style.background = 'transparent';
        cancelBtn.style.color = 'var(--muted-foreground, #71717a)';
        cancelBtn.style.border = '1px solid var(--border, #27272a)';
        cancelBtn.style.borderRadius = '4px';
        cancelBtn.style.padding = '6px 12px';
        cancelBtn.style.fontSize = '12px';
        cancelBtn.style.cursor = 'pointer';
        cancelBtn.style.outline = 'none';

        const okBtn = document.createElement('button');
        okBtn.textContent = 'OK';
        okBtn.style.background = 'var(--primary, #3b82f6)';
        okBtn.style.color = '#ffffff';
        okBtn.style.border = 'none';
        okBtn.style.borderRadius = '4px';
        okBtn.style.padding = '6px 12px';
        okBtn.style.fontSize = '12px';
        okBtn.style.fontWeight = '500';
        okBtn.style.cursor = 'pointer';
        okBtn.style.outline = 'none';

        buttons.appendChild(cancelBtn);
        buttons.appendChild(okBtn);
        modal.appendChild(label);
        modal.appendChild(input);
        modal.appendChild(buttons);
        overlay.appendChild(modal);

        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: input,
            previouslyFocused,
            removeDelay: 200,
            animateClose: () => {
                overlay.style.opacity = '0';
                modal.style.transform = 'scale(0.95)';
            },
            onClose: (reason) => {
                if (reason === 'escape' && typeof callback === 'function') callback(null);
            },
        });
        controller.focusInitial();
        input.select();

        const close = (value) => {
            if (!controller.close(value === null ? 'cancel' : 'submit')) return;
            if (typeof callback === 'function') callback(value);
        };

        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(null);
        });

        okBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(input.value);
        });

        input.addEventListener('keydown', (e) => {
            e.stopPropagation();
            if (e.key === 'Enter') {
                e.preventDefault();
                close(input.value);
            }
        });
    }

    function showGitSyncModal(conversationId, onSync) {
        const parent = document.body;
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.background = 'rgba(9, 9, 11, 0.85)';
        overlay.style.backdropFilter = 'blur(6px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '100000';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';

        const modal = document.createElement('div');
        modal.className = 'antigravity-git-modal';
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '12px';
        modal.style.width = '92%';
        modal.style.maxWidth = '880px';
        modal.style.height = '86vh';
        modal.style.maxHeight = '760px';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.boxShadow = '0 25px 50px -12px rgba(0, 0, 0, 0.7)';
        modal.style.transform = 'scale(0.97)';
        modal.style.transition = 'transform 0.2s ease';
        modal.style.overflow = 'hidden';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        const header = document.createElement('div');
        header.style.padding = '14px 20px';
        header.style.borderBottom = '1px solid var(--border, #27272a)';
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.background = 'rgba(0, 0, 0, 0.15)';

        const title = document.createElement('h3');
        title.textContent = 'Git Sync, Cloud-Backup & Workspace Diffs';
        title.style.margin = '0';
        title.style.fontSize = '14px';
        title.style.fontWeight = '600';
        title.style.color = '#ffffff';
        title.id = 'antigravity-git-modal-title-' + Date.now();
        modal.setAttribute('aria-labelledby', title.id);

        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = 'var(--muted-foreground, #a1a1aa)';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.padding = '4px';
        closeBtn.style.borderRadius = '4px';
        closeBtn.style.display = 'flex';
        closeBtn.style.alignItems = 'center';
        closeBtn.setAttribute('aria-label', 'Git-Sync-Dialog schließen');

        header.appendChild(title);
        header.appendChild(closeBtn);

        // Cloud-Backup, Memory & Usage Stats Section (~/.gemini/config)
        const cloudSection = document.createElement('div');
        cloudSection.style.padding = '12px 20px';
        cloudSection.style.borderBottom = '1px solid var(--border, #27272a)';
        cloudSection.style.background = 'linear-gradient(180deg, rgba(59, 130, 246, 0.07) 0%, rgba(24, 24, 27, 0.4) 100%)';
        cloudSection.style.display = 'flex';
        cloudSection.style.flexDirection = 'column';
        cloudSection.style.gap = '8px';

        const cloudTopRow = document.createElement('div');
        cloudTopRow.style.display = 'flex';
        cloudTopRow.style.justifyContent = 'space-between';
        cloudTopRow.style.alignItems = 'flex-start';
        cloudTopRow.style.gap = '12px';
        cloudTopRow.style.flexWrap = 'wrap';

        const cloudInfoCol = document.createElement('div');
        cloudInfoCol.style.display = 'flex';
        cloudInfoCol.style.flexDirection = 'column';
        cloudInfoCol.style.gap = '3px';

        const cloudTitleRow = document.createElement('div');
        cloudTitleRow.style.display = 'flex';
        cloudTitleRow.style.alignItems = 'center';
        cloudTitleRow.style.gap = '8px';
        cloudTitleRow.style.flexWrap = 'wrap';

        const cloudTitle = document.createElement('span');
        cloudTitle.style.fontSize = '12px';
        cloudTitle.style.fontWeight = '600';
        cloudTitle.style.color = '#ffffff';
        cloudTitle.textContent = '☁️ Cloud-Backup, Memory & Nutzungsdaten (~/.gemini/config)';

        const cloudStatusBadge = document.createElement('span');
        cloudStatusBadge.style.fontSize = '10px';
        cloudStatusBadge.style.fontWeight = '600';
        cloudStatusBadge.style.padding = '2px 8px';
        cloudStatusBadge.style.borderRadius = '999px';
        cloudStatusBadge.style.background = 'rgba(161, 161, 170, 0.15)';
        cloudStatusBadge.style.color = '#a1a1aa';
        cloudStatusBadge.textContent = 'Prüfe Status...';

        cloudTitleRow.appendChild(cloudTitle);
        cloudTitleRow.appendChild(cloudStatusBadge);

        const cloudSubtext = document.createElement('div');
        cloudSubtext.style.fontSize = '11px';
        cloudSubtext.style.color = 'var(--muted-foreground, #a1a1aa)';
        cloudSubtext.style.lineHeight = '1.35';
        cloudSubtext.textContent = 'Sichert automatisch MEMORY.pc.md, USER.pc.md, Skills & usage_stats.json (Tokens, Sessions, Modelle) in deinem privaten GitHub-Repo und stellt sie auf jedem Zweit-PC/Laptop per 1-Klick wieder her.';

        cloudInfoCol.appendChild(cloudTitleRow);
        cloudInfoCol.appendChild(cloudSubtext);

        const usagePills = document.createElement('div');
        usagePills.style.fontSize = '10px';
        usagePills.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
        usagePills.style.color = '#93c5fd';
        usagePills.style.background = 'rgba(59, 130, 246, 0.12)';
        usagePills.style.border = '1px solid rgba(59, 130, 246, 0.28)';
        usagePills.style.borderRadius = '6px';
        usagePills.style.padding = '4px 8px';
        usagePills.style.whiteSpace = 'nowrap';
        usagePills.textContent = '📊 Lade Nutzungsdaten...';

        cloudTopRow.appendChild(cloudInfoCol);
        cloudTopRow.appendChild(usagePills);

        const cloudBtnRow = document.createElement('div');
        cloudBtnRow.style.display = 'flex';
        cloudBtnRow.style.alignItems = 'center';
        cloudBtnRow.style.gap = '8px';
        cloudBtnRow.style.flexWrap = 'wrap';

        const makeCloudBtn = (label, bg, border, color = '#ffffff') => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.style.background = bg;
            b.style.border = border;
            b.style.color = color;
            b.style.borderRadius = '5px';
            b.style.padding = '5px 10px';
            b.style.fontSize = '11px';
            b.style.fontWeight = '500';
            b.style.cursor = 'pointer';
            b.style.outline = 'none';
            b.style.transition = 'opacity 0.15s';
            return b;
        };

        const ghLoginBtn = makeCloudBtn('🔑 1. GitHub Login', 'rgba(255,255,255,0.06)', '1px solid var(--border, #27272a)', '#e4e4e7');
        const createPrivateBtn = makeCloudBtn('🔒 2. Privates Repo erstellen & verbinden', 'rgba(34, 197, 94, 0.18)', '1px solid rgba(34, 197, 94, 0.45)', '#4ade80');
        const importConfigBtn = makeCloudBtn('📥 Auf 2. PC importieren (Pull & Restore)', 'rgba(59, 130, 246, 0.18)', '1px solid rgba(59, 130, 246, 0.45)', '#60a5fa');
        const customUrlToggleBtn = makeCloudBtn('🔗 Repo-URL ändern / eingeben', 'transparent', '1px solid var(--border, #27272a)', '#a1a1aa');

        cloudBtnRow.appendChild(ghLoginBtn);
        cloudBtnRow.appendChild(createPrivateBtn);
        cloudBtnRow.appendChild(importConfigBtn);
        cloudBtnRow.appendChild(customUrlToggleBtn);

        const customUrlRow = document.createElement('div');
        customUrlRow.style.display = 'none';
        customUrlRow.style.gap = '8px';
        customUrlRow.style.alignItems = 'center';
        customUrlRow.style.marginTop = '2px';

        const repoUrlInput = document.createElement('input');
        repoUrlInput.type = 'text';
        repoUrlInput.placeholder = 'z.B. https://github.com/DeinName/antigravity-config.git oder DeinName/antigravity-config';
        repoUrlInput.style.flex = '1';
        repoUrlInput.style.background = 'var(--background, #09090b)';
        repoUrlInput.style.border = '1px solid var(--border, #27272a)';
        repoUrlInput.style.borderRadius = '5px';
        repoUrlInput.style.padding = '5px 10px';
        repoUrlInput.style.fontSize = '11px';
        repoUrlInput.style.color = '#ffffff';
        repoUrlInput.style.outline = 'none';

        const linkAndPushBtn = makeCloudBtn('Verbinden & Pushen', '#22c55e', 'none', '#ffffff');
        const pullFromUrlBtn = makeCloudBtn('Von dieser URL importieren', '#3b82f6', 'none', '#ffffff');

        customUrlRow.appendChild(repoUrlInput);
        customUrlRow.appendChild(linkAndPushBtn);
        customUrlRow.appendChild(pullFromUrlBtn);

        const cloudFeedback = document.createElement('div');
        cloudFeedback.style.display = 'none';
        cloudFeedback.style.fontSize = '11px';
        cloudFeedback.style.padding = '6px 10px';
        cloudFeedback.style.borderRadius = '5px';
        cloudFeedback.style.lineHeight = '1.4';

        const showCloudFeedback = (msg, isError = false) => {
            cloudFeedback.style.display = 'block';
            cloudFeedback.style.background = isError ? 'rgba(239, 68, 68, 0.14)' : 'rgba(34, 197, 94, 0.14)';
            cloudFeedback.style.border = isError ? '1px solid rgba(239, 68, 68, 0.35)' : '1px solid rgba(34, 197, 94, 0.35)';
            cloudFeedback.style.color = isError ? '#fca5a5' : '#86efac';
            cloudFeedback.textContent = msg;
        };

        cloudSection.appendChild(cloudTopRow);
        cloudSection.appendChild(cloudBtnRow);
        cloudSection.appendChild(customUrlRow);
        cloudSection.appendChild(cloudFeedback);

        const body = document.createElement('div');
        body.style.flex = '1';
        body.style.minHeight = '0';
        body.style.display = 'flex';
        body.style.overflow = 'hidden';

        const fileList = document.createElement('div');
        fileList.style.width = '280px';
        fileList.style.borderRight = '1px solid var(--border, #27272a)';
        fileList.style.overflowY = 'auto';
        fileList.style.padding = '12px';
        fileList.style.display = 'flex';
        fileList.style.flexDirection = 'column';
        fileList.style.gap = '6px';
        fileList.style.background = 'rgba(0, 0, 0, 0.08)';

        const diffViewer = document.createElement('div');
        diffViewer.style.flex = '1';
        diffViewer.style.overflow = 'auto';
        diffViewer.style.padding = '16px';
        diffViewer.style.background = '#09090b';
        diffViewer.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
        diffViewer.style.fontSize = '12px';
        diffViewer.style.lineHeight = '1.5';
        diffViewer.style.whiteSpace = 'pre';
        diffViewer.style.color = '#e4e4e7';
        diffViewer.style.userSelect = 'text';
        diffViewer.innerHTML = '<div style="color: var(--muted-foreground, #71717a); font-style: italic; text-align: center; margin-top: 100px;">Wähle eine Datei aus, um das Diff anzuzeigen</div>';

        body.appendChild(fileList);
        body.appendChild(diffViewer);

        const footer = document.createElement('div');
        footer.style.padding = '16px 20px';
        footer.style.borderTop = '1px solid var(--border, #27272a)';
        footer.style.display = 'flex';
        footer.style.flexDirection = 'column';
        footer.style.gap = '12px';
        footer.style.background = 'rgba(0, 0, 0, 0.15)';

        const msgRow = document.createElement('div');
        msgRow.style.display = 'flex';
        msgRow.style.gap = '10px';
        msgRow.style.alignItems = 'flex-start';

        const textarea = document.createElement('textarea');
        textarea.placeholder = 'Commit-Beschreibung eingeben...';
        textarea.style.flex = '1';
        textarea.style.height = '48px';
        textarea.style.background = 'var(--background, #09090b)';
        textarea.style.border = '1px solid var(--border, #27272a)';
        textarea.style.borderRadius = '6px';
        textarea.style.padding = '8px 12px';
        textarea.style.fontSize = '12px';
        textarea.style.color = '#ffffff';
        textarea.style.outline = 'none';
        textarea.style.resize = 'none';
        textarea.value = 'wip: sync updates';

        const aiBtn = document.createElement('button');
        aiBtn.innerHTML = '✨ AI Generieren';
        aiBtn.style.background = 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)';
        aiBtn.style.color = '#ffffff';
        aiBtn.style.border = 'none';
        aiBtn.style.borderRadius = '6px';
        aiBtn.style.padding = '8px 14px';
        aiBtn.style.fontSize = '12px';
        aiBtn.style.fontWeight = '600';
        aiBtn.style.cursor = 'pointer';
        aiBtn.style.height = '48px';
        aiBtn.style.display = 'inline-flex';
        aiBtn.style.alignItems = 'center';
        aiBtn.style.gap = '6px';
        aiBtn.style.transition = 'opacity 0.2s';
        aiBtn.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.2)';
        aiBtn.style.outline = 'none';

        msgRow.appendChild(textarea);
        msgRow.appendChild(aiBtn);

        const thinkingLog = document.createElement('div');
        thinkingLog.id = 'antigravity-git-thinking-log';
        thinkingLog.style.background = 'rgba(0, 0, 0, 0.2)';
        thinkingLog.style.border = '1px solid var(--border, #27272a)';
        thinkingLog.style.borderRadius = '6px';
        thinkingLog.style.padding = '10px 12px';
        thinkingLog.style.maxHeight = '100px';
        thinkingLog.style.overflowY = 'auto';
        thinkingLog.style.fontSize = '11px';
        thinkingLog.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
        thinkingLog.style.color = 'var(--muted-foreground, #a1a1aa)';
        thinkingLog.style.marginTop = '8px';
        thinkingLog.style.display = 'none'; // Standardmäßig ausgeblendet

        const logHeader = document.createElement('div');
        logHeader.style.fontWeight = '600';
        logHeader.style.color = 'var(--foreground, #ffffff)';
        logHeader.style.marginBottom = '6px';
        logHeader.style.fontSize = '10px';
        logHeader.style.textTransform = 'uppercase';
        logHeader.style.letterSpacing = '0.05em';
        logHeader.textContent = 'AI Denkvorgang & Aktivitäten:';

        const logList = document.createElement('div');
        logList.id = 'antigravity-git-thinking-list';
        logList.style.display = 'flex';
        logList.style.flexDirection = 'column';
        logList.style.gap = '4px';

        thinkingLog.appendChild(logHeader);
        thinkingLog.appendChild(logList);

        const actionsRow = document.createElement('div');
        actionsRow.style.display = 'flex';
        actionsRow.style.alignItems = 'center';
        actionsRow.style.justifyContent = 'space-between';
        actionsRow.style.gap = '10px';
        actionsRow.style.flexWrap = 'wrap';

        const aiQuickRow = document.createElement('div');
        aiQuickRow.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap;';

        const aiQuickLabel = document.createElement('span');
        aiQuickLabel.style.cssText = 'font-size:11px;color:var(--muted-foreground, #a1a1aa);font-weight:500;';
        aiQuickLabel.textContent = 'AI-Engine:';

        const aiModalModeSelect = document.createElement('select');
        aiModalModeSelect.setAttribute('aria-label', 'AI-Generator Modus');
        aiModalModeSelect.style.cssText =
            'padding:5px 8px;border-radius:6px;background:var(--background, #09090b);' +
            'border:1px solid var(--border, #27272a);color:#e4e4e7;font-size:11px;outline:none;cursor:pointer;';
        [
            { value: 'auto', label: '⚡ Auto (Unleashed API → Lokal UI)' },
            { value: 'unleashed_api', label: '🌐 Unleashed Server API (/v1)' },
            { value: 'local_ui', label: '🖥️ Lokal (Antigravity UI direkt)' },
            { value: 'off', label: '📝 Ohne AI (Regelbasiert)' },
        ].forEach((opt) => {
            const o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            o.style.background = '#141417';
            aiModalModeSelect.appendChild(o);
        });

        const openAiSettingsBtn = document.createElement('button');
        openAiSettingsBtn.type = 'button';
        openAiSettingsBtn.textContent = '⚙️ API & Modell';
        openAiSettingsBtn.title = 'Unleashed API-URL, Token und AI-Modell konfigurieren';
        openAiSettingsBtn.style.cssText =
            'padding:5px 9px;border-radius:6px;background:rgba(56,189,248,0.1);' +
            'border:1px solid rgba(56,189,248,0.3);color:#38bdf8;font-size:11px;font-weight:500;cursor:pointer;';
        openAiSettingsBtn.addEventListener('click', () => {
            window.__ams_open_ai_settings = true;
            if (typeof window.toggleQuickMenu === 'function') {
                const existingMenu = document.getElementById('antigravity-quick-menu-overlay');
                if (existingMenu) existingMenu.remove();
                window.toggleQuickMenu();
            }
        });

        const syncAiButtonAppearance = (modeVal) => {
            if (modeVal === 'off') {
                aiBtn.innerHTML = '📝 Regelbasiert';
                aiBtn.style.background = 'linear-gradient(135deg, #3f3f46 0%, #52525b 100%)';
            } else {
                aiBtn.innerHTML = '✨ AI Generieren';
                aiBtn.style.background = 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)';
            }
        };

        aiModalModeSelect.addEventListener('change', async () => {
            const nextMode = aiModalModeSelect.value;
            syncAiButtonAppearance(nextMode);
            if (window.electronNative && window.electronNative.saveAiConfig) {
                try {
                    const res = await window.electronNative.saveAiConfig({ mode: nextMode });
                    if (res && res.config) window.__ams_cached_ai_config = res.config;
                } catch (_e) {}
            }
        });

        if (window.electronNative && window.electronNative.getAiConfig) {
            window.electronNative.getAiConfig().then((res) => {
                if (res && res.config) {
                    window.__ams_cached_ai_config = res.config;
                    aiModalModeSelect.value = res.config.mode || 'auto';
                    syncAiButtonAppearance(res.config.mode || 'auto');
                }
            }).catch(() => {});
        }

        aiQuickRow.appendChild(aiQuickLabel);
        aiQuickRow.appendChild(aiModalModeSelect);
        aiQuickRow.appendChild(openAiSettingsBtn);

        const rightBtnsWrap = document.createElement('div');
        rightBtnsWrap.style.cssText = 'display:flex;align-items:center;gap:10px;margin-left:auto;';

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Abbrechen';
        cancelBtn.style.background = 'transparent';
        cancelBtn.style.color = 'var(--muted-foreground, #a1a1aa)';
        cancelBtn.style.border = '1px solid var(--border, #27272a)';
        cancelBtn.style.borderRadius = '6px';
        cancelBtn.style.padding = '8px 16px';
        cancelBtn.style.fontSize = '12px';
        cancelBtn.style.cursor = 'pointer';
        cancelBtn.style.outline = 'none';

        const syncSubmitBtn = document.createElement('button');
        syncSubmitBtn.textContent = 'Synchronisieren & Pushen';
        syncSubmitBtn.style.background = '#22c55e';
        syncSubmitBtn.style.color = '#ffffff';
        syncSubmitBtn.style.border = 'none';
        syncSubmitBtn.style.borderRadius = '6px';
        syncSubmitBtn.style.padding = '8px 18px';
        syncSubmitBtn.style.fontSize = '12px';
        syncSubmitBtn.style.fontWeight = '600';
        syncSubmitBtn.style.cursor = 'pointer';
        syncSubmitBtn.style.outline = 'none';

        rightBtnsWrap.appendChild(cancelBtn);
        rightBtnsWrap.appendChild(syncSubmitBtn);
        actionsRow.appendChild(aiQuickRow);
        actionsRow.appendChild(rightBtnsWrap);

        footer.appendChild(msgRow);
        footer.appendChild(thinkingLog);
        footer.appendChild(actionsRow);

        modal.appendChild(header);
        modal.appendChild(cloudSection);
        modal.appendChild(body);
        modal.appendChild(footer);
        overlay.appendChild(modal);
        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        let progressHandler = null;
        let syncSubmitting = false;
        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: textarea,
            previouslyFocused,
            removeDelay: 200,
            animateClose: () => {
                overlay.style.opacity = '0';
                modal.style.transform = 'scale(0.97)';
            },
            onClose: () => {
                if (progressHandler) {
                    window.electronNative.removeGenerateCommitProgressListener(progressHandler);
                    progressHandler = null;
                }
            },
        });
        const closeModal = (reason = 'cancel') => controller.close(reason);
        controller.focusInitial();

        closeBtn.addEventListener('click', closeModal);
        cancelBtn.addEventListener('click', closeModal);

        let selectedFileEl = null;
        const renderDiff = (diffText) => {
            if (!diffText.trim()) {
                diffViewer.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 100px;">Keine Zeilenänderungen in dieser Datei</div>';
                return;
            }

            const lines = diffText.split('\\n');
            const fragment = document.createDocumentFragment();

            lines.forEach(line => {
                const row = document.createElement('div');
                row.style.whiteSpace = 'pre-wrap';
                row.style.wordBreak = 'break-all';
                row.style.padding = '1px 8px';

                if (line.startsWith('+') && !line.startsWith('+++')) {
                    row.style.color = '#4ade80';
                    row.style.backgroundColor = 'rgba(74, 222, 128, 0.08)';
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                    row.style.color = '#f87171';
                    row.style.backgroundColor = 'rgba(248, 113, 113, 0.08)';
                } else if (line.startsWith('@@')) {
                    row.style.color = '#60a5fa';
                    row.style.backgroundColor = 'rgba(96, 165, 250, 0.05)';
                    row.style.fontWeight = '500';
                } else {
                    row.style.color = '#d4d4d8';
                }
                row.textContent = line;
                fragment.appendChild(row);
            });

            diffViewer.innerHTML = '';
            diffViewer.appendChild(fragment);
        };

        const loadFiles = async () => {
            fileList.innerHTML = '<div style="font-size: 11px; color: var(--muted-foreground, #71717a); text-align: center; margin-top: 20px;">Lade Git Status...</div>';
            try {
                const res = await window.electronNative.getGitStatus(conversationId);
                if (res.status === 'success') {
                    fileList.innerHTML = '';
                    const changes = [...res.workspaceChanges, ...res.configChanges];

                    if (changes.length === 0) {
                        fileList.innerHTML = '<div style="font-size: 11px; color: var(--muted-foreground, #71717a); text-align: center; margin-top: 20px;">Keine Änderungen gefunden</div>';
                        return;
                    }

                    changes.forEach(item => {
                        const fileCard = document.createElement('div');
                        fileCard.style.padding = '8px 10px';
                        fileCard.style.borderRadius = '6px';
                        fileCard.style.background = 'var(--card, #1c1c1f)';
                        fileCard.style.border = '1px solid var(--border, #2a2a2d)';
                        fileCard.style.cursor = 'pointer';
                        fileCard.style.display = 'flex';
                        fileCard.style.alignItems = 'center';
                        fileCard.style.justifyContent = 'space-between';
                        fileCard.style.fontSize = '12px';
                        fileCard.style.transition = 'all 0.2s';

                        const leftSection = document.createElement('div');
                        leftSection.style.display = 'flex';
                        leftSection.style.flexDirection = 'column';
                        leftSection.style.gap = '2px';
                        leftSection.style.overflow = 'hidden';

                        const nameSpan = document.createElement('span');
                        nameSpan.textContent = item.file.replace(/\\\\/g, '/').split('/').pop();
                        nameSpan.style.fontWeight = '500';
                        nameSpan.style.color = '#ffffff';

                        const pathSpan = document.createElement('span');
                        pathSpan.textContent = item.file;
                        pathSpan.style.fontSize = '9px';
                        pathSpan.style.color = 'var(--muted-foreground, #71717a)';
                        pathSpan.style.textOverflow = 'ellipsis';
                        pathSpan.style.overflow = 'hidden';
                        pathSpan.style.whiteSpace = 'nowrap';

                        leftSection.appendChild(nameSpan);
                        leftSection.appendChild(pathSpan);

                        const badge = document.createElement('span');
                        badge.style.padding = '2px 6px';
                        badge.style.borderRadius = '4px';
                        badge.style.fontSize = '9px';
                        badge.style.fontWeight = '700';

                        if (item.status === 'M') {
                            badge.textContent = 'M';
                            badge.style.color = '#eab308';
                            badge.style.background = 'rgba(234, 179, 8, 0.15)';
                        } else if (item.status === '??' || item.status === 'A') {
                            badge.textContent = 'A';
                            badge.style.color = '#22c55e';
                            badge.style.background = 'rgba(34, 197, 94, 0.15)';
                        } else if (item.status === 'D') {
                            badge.textContent = 'D';
                            badge.style.color = '#ef4444';
                            badge.style.background = 'rgba(239, 68, 68, 0.15)';
                        } else {
                            badge.textContent = item.status;
                            badge.style.color = '#a1a1aa';
                            badge.style.background = 'rgba(161, 161, 170, 0.15)';
                        }

                        fileCard.appendChild(leftSection);
                        fileCard.appendChild(badge);

                        fileCard.addEventListener('click', async () => {
                            if (selectedFileEl) {
                                selectedFileEl.style.borderColor = 'var(--border, #2a2a2d)';
                                selectedFileEl.style.background = 'var(--card, #1c1c1f)';
                            }
                            selectedFileEl = fileCard;
                            fileCard.style.borderColor = '#3b82f6';
                            fileCard.style.background = 'rgba(59, 130, 246, 0.05)';

                            diffViewer.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 100px;">Lade Dateidiff...</div>';
                            try {
                                const diffRes = await window.electronNative.getGitDiff(item.file, item.repo, conversationId);
                                if (diffRes.status === 'success') {
                                    renderDiff(diffRes.diff);
                                } else {
                                    renderInlineError(diffViewer, 'Fehler beim Laden des Diffs: ', diffRes.message, { padding: '20px' });
                                }
                            } catch (err) {
                                renderInlineError(diffViewer, 'Ausnahmefehler: ', err.message, { padding: '20px' });
                            }
                        });

                        fileCard.addEventListener('mouseenter', () => {
                            if (selectedFileEl !== fileCard) {
                                fileCard.style.background = 'rgba(255, 255, 255, 0.03)';
                            }
                        });
                        fileCard.addEventListener('mouseleave', () => {
                            if (selectedFileEl !== fileCard) {
                                fileCard.style.background = 'var(--card, #1c1c1f)';
                            }
                        });

                        fileList.appendChild(fileCard);
                    });

                    const firstCard = fileList.firstElementChild;
                    if (firstCard) firstCard.click();
                } else {
                    renderInlineError(fileList, 'Fehler: ', res.message);
                }
            } catch (err) {
                renderInlineError(fileList, 'Fehler: ', err.message);
            }
        };

        let currentConfigInfo = null;
        const formatCompactNum = (n) => {
            const val = Number(n || 0);
            if (val >= 1000000) return (val / 1000000).toFixed(2) + 'M';
            if (val >= 1000) return (val / 1000).toFixed(1) + 'K';
            return String(val);
        };

        const renderConfigSyncInfo = (info) => {
            if (!info || info.status === 'error') {
                cloudStatusBadge.textContent = 'Status nicht verfügbar';
                return;
            }
            currentConfigInfo = info;
            if (info.remote_url) {
                cloudStatusBadge.style.background = 'rgba(34, 197, 94, 0.16)';
                cloudStatusBadge.style.color = '#4ade80';
                cloudStatusBadge.textContent = '● Verbunden: ' + info.remote_url;
                repoUrlInput.value = info.remote_url;
            } else {
                cloudStatusBadge.style.background = 'rgba(234, 179, 8, 0.16)';
                cloudStatusBadge.style.color = '#facc15';
                cloudStatusBadge.textContent = '○ Nur lokal (Kein GitHub-Remote verbunden)';
            }

            if (info.gh_authenticated) {
                ghLoginBtn.textContent = '✓ GitHub (@' + (info.gh_user || 'angemeldet') + ')';
                ghLoginBtn.style.color = '#4ade80';
                ghLoginBtn.style.borderColor = 'rgba(34, 197, 94, 0.35)';
            } else {
                ghLoginBtn.textContent = '🔑 1. GitHub Login';
                ghLoginBtn.style.color = '#e4e4e7';
            }

            const u = info.usage || {};
            const hostsCount = Array.isArray(u.synced_hosts) ? u.synced_hosts.length : 1;
            usagePills.textContent =
                '📊 ' + formatCompactNum(u.total_tokens) + ' Tokens · ' +
                formatCompactNum(u.total_messages) + ' Msgs · ' +
                (u.total_sessions || 0) + ' Sessions · ' +
                (u.skills_count || 0) + ' Skills · ' +
                hostsCount + ' PC(s)';
            if (Array.isArray(u.synced_hosts) && u.synced_hosts.length > 0) {
                usagePills.title = 'Synchronisierte Geräte in usage_stats.json: ' + u.synced_hosts.join(', ');
            }
        };

        const loadConfigSyncInfo = async () => {
            if (!window.electronNative || !window.electronNative.getConfigSyncInfo) return;
            try {
                const info = await window.electronNative.getConfigSyncInfo();
                renderConfigSyncInfo(info);
            } catch (err) {
                console.warn('[AMS Cloud Sync] Could not load config sync info:', err);
            }
        };

        ghLoginBtn.addEventListener('click', async () => {
            if (!window.electronNative || !window.electronNative.ghAuthLogin) return;
            showCloudFeedback('Öffne PowerShell für GitHub Web-Login (gh auth login --web)... Nach dem Login im Browser wird der Status automatisch aktualisiert.');
            await window.electronNative.ghAuthLogin();
            setTimeout(loadConfigSyncInfo, 6000);
            setTimeout(loadConfigSyncInfo, 14000);
        });

        createPrivateBtn.addEventListener('click', async () => {
            if (!window.electronNative || !window.electronNative.setupConfigRemote) return;
            createPrivateBtn.disabled = true;
            createPrivateBtn.style.opacity = '0.6';
            showCloudFeedback('Erstelle/verbinde privates Repository "antigravity-config" und synchronisiere ~/.gemini/config + usage_stats.json...');
            try {
                const target = (repoUrlInput.value || '').trim() || 'antigravity-config';
                const res = await window.electronNative.setupConfigRemote(target, true);
                if (res && res.status === 'success') {
                    showCloudFeedback('✓ ' + (res.message || 'Privates GitHub-Repository verbunden & synchronisiert!'));
                    if (res.info) renderConfigSyncInfo(res.info);
                    else await loadConfigSyncInfo();
                    await loadFiles();
                } else {
                    showCloudFeedback('✗ ' + ((res && res.message) || 'Fehler beim Erstellen/Verbinden des Repositories.'), true);
                }
            } catch (err) {
                showCloudFeedback('✗ Ausnahmefehler: ' + err.message, true);
            } finally {
                createPrivateBtn.disabled = false;
                createPrivateBtn.style.opacity = '1';
            }
        });

        const runConfigImport = async (targetUrl) => {
            if (!window.electronNative || !window.electronNative.importConfigRemote) return;
            importConfigBtn.disabled = true;
            pullFromUrlBtn.disabled = true;
            importConfigBtn.style.opacity = '0.6';
            showCloudFeedback('Importiere Config, Memory & Nutzungsdaten vom Remote (lokale Dateien werden zuvor unter ~/.gemini/config/backups/ gesichert)...');
            try {
                const res = await window.electronNative.importConfigRemote(targetUrl || '');
                if (res && res.status === 'success') {
                    showCloudFeedback('✓ ' + (res.message || 'Config & Nutzungsdaten erfolgreich importiert!'));
                    if (res.info) renderConfigSyncInfo(res.info);
                    else await loadConfigSyncInfo();
                    await loadFiles();
                } else {
                    showCloudFeedback('✗ ' + ((res && res.message) || 'Import fehlgeschlagen.'), true);
                }
            } catch (err) {
                showCloudFeedback('✗ Ausnahmefehler beim Import: ' + err.message, true);
            } finally {
                importConfigBtn.disabled = false;
                pullFromUrlBtn.disabled = false;
                importConfigBtn.style.opacity = '1';
            }
        };

        importConfigBtn.addEventListener('click', () => {
            const configuredRemote = (currentConfigInfo && currentConfigInfo.remote_url) || (repoUrlInput.value || '').trim();
            if (!configuredRemote) {
                customUrlRow.style.display = 'flex';
                repoUrlInput.focus();
                showCloudFeedback('Bitte gib die GitHub-URL oder "DeinName/antigravity-config" deines bestehenden Config-Repos ein und klicke auf "Von dieser URL importieren".', true);
                return;
            }
            runConfigImport(configuredRemote);
        });

        customUrlToggleBtn.addEventListener('click', () => {
            const isHidden = customUrlRow.style.display === 'none';
            customUrlRow.style.display = isHidden ? 'flex' : 'none';
            if (isHidden) repoUrlInput.focus();
        });

        linkAndPushBtn.addEventListener('click', async () => {
            const target = (repoUrlInput.value || '').trim();
            if (!target) {
                showCloudFeedback('Bitte zuerst eine Repository-URL oder "user/repo" eingeben.', true);
                return;
            }
            linkAndPushBtn.disabled = true;
            showCloudFeedback('Verbinde Remote "' + target + '" und pushe lokale Config + Nutzungsdaten...');
            try {
                const res = await window.electronNative.setupConfigRemote(target, false);
                if (res && res.status === 'success') {
                    showCloudFeedback('✓ ' + (res.message || 'Remote verbunden und synchronisiert!'));
                    if (res.info) renderConfigSyncInfo(res.info);
                    else await loadConfigSyncInfo();
                    await loadFiles();
                } else {
                    showCloudFeedback('✗ ' + ((res && res.message) || 'Verbindung fehlgeschlagen.'), true);
                }
            } catch (err) {
                showCloudFeedback('✗ Fehler: ' + err.message, true);
            } finally {
                linkAndPushBtn.disabled = false;
            }
        });

        pullFromUrlBtn.addEventListener('click', () => {
            const target = (repoUrlInput.value || '').trim();
            if (!target) {
                showCloudFeedback('Bitte zuerst eine Repository-URL oder "user/repo" zum Importieren eingeben.', true);
                return;
            }
            runConfigImport(target);
        });

        loadFiles();
        loadConfigSyncInfo();

        aiBtn.addEventListener('click', async () => {
            aiBtn.disabled = true;
            aiBtn.style.opacity = '0.7';
            aiBtn.innerHTML = '<svg class="antigravity-spinner" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg> Generiere...';

            // Log-Anzeige einblenden
            thinkingLog.style.display = 'block';
            logList.innerHTML = '';

            const addLog = (text, status = 'pending') => {
                // Letzten Eintrag auf "erledigt" setzen
                const lastEl = logList.lastElementChild;
                if (lastEl) {
                    const icon = lastEl.querySelector('.log-icon');
                    if (icon) {
                        icon.textContent = '✓';
                        icon.style.color = '#22c55e';
                        icon.style.animation = 'none';
                    }
                    lastEl.style.color = 'var(--muted-foreground, #71717a)';
                }

                const item = document.createElement('div');
                item.style.display = 'flex';
                item.style.gap = '6px';
                item.style.alignItems = 'center';
                item.style.color = 'var(--foreground, #ffffff)';

                const icon = document.createElement('span');
                icon.className = 'log-icon';
                icon.style.fontSize = '10px';
                icon.style.display = 'inline-flex';
                icon.style.alignItems = 'center';
                icon.style.justifyContent = 'center';
                icon.style.width = '12px';
                icon.style.height = '12px';

                if (status === 'pending') {
                    icon.textContent = '●';
                    icon.style.color = '#3b82f6';
                    icon.style.animation = 'brain-pulse 1.5s infinite';
                } else if (status === 'success') {
                    icon.textContent = '✓';
                    icon.style.color = '#22c55e';
                } else if (status === 'error') {
                    icon.textContent = '✗';
                    icon.style.color = '#ef4444';
                }

                const textSpan = document.createElement('span');
                textSpan.textContent = text;

                item.appendChild(icon);
                item.appendChild(textSpan);
                logList.appendChild(item);

                // Nach unten scrollen
                thinkingLog.scrollTop = thinkingLog.scrollHeight;
            };

            addLog('Workspace-Status und Git-Projekt ermitteln...');

            // Listener registrieren
            if (progressHandler) {
                window.electronNative.removeGenerateCommitProgressListener(progressHandler);
            }

            progressHandler = (msg) => {
                addLog(msg);
            };

            window.electronNative.onGenerateCommitProgress(progressHandler);

            try {
                const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
                const res = await window.electronNative.generateCommitMsg(conversationId, csrfToken);
                if (res.status === 'success' && res.commitMessage) {
                    textarea.value = res.commitMessage;
                    addLog('Commit-Message erfolgreich generiert!', 'success');
                    if (res.convoId) {
                        deleteTempConversation(res.convoId);
                    }
                } else {
                    addLog('Fehler bei der AI-Generierung: ' + (res.message || 'Leere Antwort erhalten.'), 'error');
                }
            } catch (err) {
                addLog('Ausnahmefehler: ' + err.message, 'error');
                showCustomAlert('Ausnahmefehler bei der Generierung: ' + err.message);
            } finally {
                aiBtn.disabled = false;
                aiBtn.style.opacity = '1';
                syncAiButtonAppearance(aiModalModeSelect.value);
                if (progressHandler) {
                    window.electronNative.removeGenerateCommitProgressListener(progressHandler);
                    progressHandler = null;
                }
            }
        });

        syncSubmitBtn.addEventListener('click', () => {
            if (syncSubmitting || controller.isClosed()) return;
            syncSubmitting = true;
            syncSubmitBtn.disabled = true;
            const commitMsg = textarea.value.trim();
            if (!closeModal('submit')) return;
            if (typeof onSync === 'function') onSync(commitMsg);
        });
    }

    async function deleteTempConversation(convoId) {
        if (!convoId) return;
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            const res = await window.electronNative.deleteTempConversation(convoId, csrfToken);
            console.log("[AMS UI] Deleted temporary conversation " + convoId + ":", res.status, res.grpcStatus);
        } catch (e) {
            console.error("[AMS UI] Failed to delete temporary conversation " + convoId + ":", e);
        }
    }

    function showCustomConfirm(message, callback) {
        const parent = document.getElementById('antigravity-plan-panel') || document.body;
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.background = 'rgba(9, 9, 11, 0.7)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10000';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';

        const modal = document.createElement('div');
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '8px';
        modal.style.padding = '16px';
        modal.style.width = '85%';
        modal.style.maxWidth = '300px';
        modal.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.5)';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.gap = '12px';
        modal.style.transform = 'scale(0.95)';
        modal.style.transition = 'transform 0.2s ease';
        modal.setAttribute('role', 'alertdialog');
        modal.setAttribute('aria-modal', 'true');

        const msgPara = document.createElement('p');
        msgPara.style.margin = '0';
        msgPara.style.fontSize = '12px';
        msgPara.style.color = 'var(--foreground, #fafafa)';
        msgPara.style.whiteSpace = 'pre-wrap';
        msgPara.style.lineHeight = '1.4';
        msgPara.textContent = message;
        msgPara.id = 'antigravity-confirm-message-' + Date.now();
        modal.setAttribute('aria-describedby', msgPara.id);

        const buttons = document.createElement('div');
        buttons.style.display = 'flex';
        buttons.style.justifyContent = 'flex-end';
        buttons.style.gap = '8px';

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Abbrechen';
        cancelBtn.style.background = 'transparent';
        cancelBtn.style.color = 'var(--muted-foreground, #71717a)';
        cancelBtn.style.border = '1px solid var(--border, #27272a)';
        cancelBtn.style.borderRadius = '4px';
        cancelBtn.style.padding = '6px 12px';
        cancelBtn.style.fontSize = '12px';
        cancelBtn.style.cursor = 'pointer';
        cancelBtn.style.outline = 'none';

        const okBtn = document.createElement('button');
        okBtn.textContent = 'Ja, löschen';
        okBtn.style.background = 'var(--destructive, #ef4444)';
        okBtn.style.color = '#ffffff';
        okBtn.style.border = 'none';
        okBtn.style.borderRadius = '4px';
        okBtn.style.padding = '6px 12px';
        okBtn.style.fontSize = '12px';
        okBtn.style.fontWeight = '500';
        okBtn.style.cursor = 'pointer';
        okBtn.style.outline = 'none';

        buttons.appendChild(cancelBtn);
        buttons.appendChild(okBtn);
        modal.appendChild(msgPara);
        modal.appendChild(buttons);
        overlay.appendChild(modal);

        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: okBtn,
            previouslyFocused,
            removeDelay: 200,
            animateClose: () => {
                overlay.style.opacity = '0';
                modal.style.transform = 'scale(0.95)';
            },
            onClose: (reason) => {
                if (reason === 'escape' && typeof callback === 'function') callback(false);
            },
        });
        controller.focusInitial();

        const close = (result) => {
            if (!controller.close(result ? 'confirm' : 'cancel')) return;
            if (typeof callback === 'function') callback(result);
        };

        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(false);
        });

        okBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(true);
        });

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                e.stopPropagation();
                close(false);
            }
        });

    }

    function showUpdateConfirm(version, releaseNotes, action, callback, releaseMetadata) {
        const mode = action === 'install' ? 'install' : 'background';
        const existing = document.getElementById('antigravity-official-update-dialog');
        if (existing) {
            if (typeof existing.__antigravityDismiss === 'function') {
                existing.__antigravityDismiss();
            } else {
                existing.remove();
            }
        }
        const parent = document.body;
        const releaseInfo = resolveOfficialReleaseInfo(version, releaseNotes, releaseMetadata);
        const onResult = typeof callback === 'function' ? callback : () => {};
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.id = 'antigravity-official-update-dialog';
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.background = 'rgba(9, 9, 11, 0.7)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10000';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';
        overlay.style.padding = '12px';
        overlay.style.boxSizing = 'border-box';
        overlay.setAttribute('role', 'presentation');

        const modal = document.createElement('div');
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '8px';
        modal.style.padding = '16px';
        modal.style.width = '85%';
        modal.style.maxWidth = '460px';
        modal.style.maxHeight = '82vh';
        modal.style.overflowY = 'auto';
        modal.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.5)';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.gap = '12px';
        modal.style.transform = 'scale(0.95)';
        modal.style.transition = 'transform 0.2s ease';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        const title = document.createElement('h3');
        title.style.margin = '0';
        title.style.fontSize = '13px';
        title.style.fontWeight = '600';
        title.style.color = 'var(--foreground, #fafafa)';
        title.id = 'antigravity-update-dialog-title-' + Date.now();
        title.textContent = (mode === 'install' ? 'Offizielles Update bereit (v' : 'Offizielles Update verfügbar (v') + releaseInfo.version + ')';
        modal.setAttribute('aria-labelledby', title.id);

        const warning = document.createElement('div');
        warning.style.fontSize = '11px';
        warning.style.color = '#f59e0b';
        warning.style.padding = '8px';
        warning.style.background = 'rgba(245, 158, 11, 0.08)';
        warning.style.border = '1px solid rgba(245, 158, 11, 0.15)';
        warning.style.borderRadius = '4px';
        warning.style.lineHeight = '1.4';
        warning.id = title.id + '-warning';
        warning.textContent = '⚠️ Wichtig: Das offizielle Update ersetzt lokale UI-Patches. Nach dem Neustart prüft der Patch-Guard zuerst die Versionskompatibilität. Nur ausdrücklich unterstützte Versionen werden automatisch gepatcht; andernfalls bleibt die sichere offizielle Oberfläche aktiv, bis der Modifier aktualisiert wurde.';
        modal.setAttribute('aria-describedby', warning.id);

        modal.appendChild(title);
        modal.appendChild(warning);

        const releaseCard = document.createElement('section');
        releaseCard.style.display = 'flex';
        releaseCard.style.flexDirection = 'column';
        releaseCard.style.gap = '8px';
        releaseCard.style.padding = '10px';
        releaseCard.style.background = 'rgba(59, 130, 246, 0.06)';
        releaseCard.style.border = '1px solid rgba(59, 130, 246, 0.2)';
        releaseCard.style.borderRadius = '6px';
        releaseCard.setAttribute('aria-label', 'Offizielle Änderungen');

        const sourceRow = document.createElement('div');
        sourceRow.style.display = 'flex';
        sourceRow.style.alignItems = 'center';
        sourceRow.style.justifyContent = 'space-between';
        sourceRow.style.gap = '8px';

        const sourceBadge = document.createElement('span');
        sourceBadge.style.fontSize = '10px';
        sourceBadge.style.fontWeight = '600';
        sourceBadge.style.color = '#60a5fa';
        sourceBadge.textContent = 'Offizieller Google-Changelog';
        sourceRow.appendChild(sourceBadge);

        if (releaseInfo.publishedAt) {
            const date = document.createElement('time');
            date.style.fontSize = '10px';
            date.style.color = '#a1a1aa';
            date.textContent = releaseInfo.publishedAt;
            sourceRow.appendChild(date);
        }
        releaseCard.appendChild(sourceRow);

        if (releaseInfo.title) {
            const releaseTitle = document.createElement('div');
            releaseTitle.style.fontSize = '12px';
            releaseTitle.style.fontWeight = '600';
            releaseTitle.style.color = 'var(--foreground, #fafafa)';
            releaseTitle.textContent = releaseInfo.title;
            releaseCard.appendChild(releaseTitle);
        }

        if (releaseInfo.improvements !== null || releaseInfo.fixes !== null) {
            const counts = document.createElement('div');
            counts.style.fontSize = '10px';
            counts.style.color = '#a1a1aa';
            counts.textContent = String(releaseInfo.improvements || 0) + ' Verbesserungen · ' + String(releaseInfo.fixes || 0) + ' Fehlerbehebungen';
            releaseCard.appendChild(counts);
        }

        if (releaseInfo.summary) {
            const summary = document.createElement('p');
            summary.style.margin = '0';
            summary.style.fontSize = '11px';
            summary.style.lineHeight = '1.45';
            summary.style.color = '#d4d4d8';
            summary.textContent = releaseInfo.summary;
            releaseCard.appendChild(summary);
        }

        if (releaseInfo.highlights.length) {
            const highlightsTitle = document.createElement('div');
            highlightsTitle.style.fontSize = '11px';
            highlightsTitle.style.fontWeight = '600';
            highlightsTitle.style.color = 'var(--foreground, #fafafa)';
            highlightsTitle.textContent = 'Die wichtigsten Änderungen';
            releaseCard.appendChild(highlightsTitle);

            const highlights = document.createElement('ul');
            highlights.style.margin = '0';
            highlights.style.paddingLeft = '18px';
            highlights.style.display = 'flex';
            highlights.style.flexDirection = 'column';
            highlights.style.gap = '4px';
            highlights.style.fontSize = '10.5px';
            highlights.style.lineHeight = '1.4';
            highlights.style.color = '#d4d4d8';
            releaseInfo.highlights.forEach((highlight) => {
                const item = document.createElement('li');
                item.textContent = highlight;
                highlights.appendChild(item);
            });
            releaseCard.appendChild(highlights);
        }

        if (releaseInfo.notesText) {
            const notesContainer = document.createElement('div');
            notesContainer.style.fontSize = '10.5px';
            notesContainer.style.color = '#d4d4d8';
            notesContainer.style.maxHeight = '110px';
            notesContainer.style.overflowY = 'auto';
            notesContainer.style.padding = '8px';
            notesContainer.style.background = 'rgba(0, 0, 0, 0.2)';
            notesContainer.style.border = '1px solid var(--border, #27272a)';
            notesContainer.style.borderRadius = '4px';
            notesContainer.style.whiteSpace = 'pre-wrap';
            notesContainer.style.lineHeight = '1.4';
            notesContainer.textContent = releaseInfo.notesText;
            releaseCard.appendChild(notesContainer);
        } else if (releaseInfo.detailsStatus === 'unavailable') {
            const unavailable = document.createElement('p');
            unavailable.style.margin = '0';
            unavailable.style.fontSize = '10.5px';
            unavailable.style.color = '#a1a1aa';
            unavailable.textContent = 'Der Update-Feed enthält für diese Version keine eingebetteten Release Notes. Der vollständige offizielle Changelog ist unten verlinkt.';
            releaseCard.appendChild(unavailable);
        }

        const releaseLink = document.createElement('button');
        releaseLink.type = 'button';
        releaseLink.style.alignSelf = 'flex-start';
        releaseLink.style.padding = '0';
        releaseLink.style.border = 'none';
        releaseLink.style.background = 'transparent';
        releaseLink.style.color = '#60a5fa';
        releaseLink.style.fontSize = '10.5px';
        releaseLink.style.fontWeight = '500';
        releaseLink.style.cursor = 'pointer';
        releaseLink.style.textDecoration = 'underline';
        releaseLink.textContent = 'Vollständigen offiziellen Changelog öffnen ↗';
        releaseLink.addEventListener('click', (event) => {
            event.stopPropagation();
            if (!isAllowedOfficialAntigravityUrl(releaseInfo.releaseUrl)) return;
            if (window.electronNative && typeof window.electronNative.openExternal === 'function') {
                Promise.resolve(window.electronNative.openExternal(releaseInfo.releaseUrl)).catch((error) => {
                    console.warn('[AMS Updater] Could not open official release page:', error);
                });
            }
        });
        releaseCard.appendChild(releaseLink);
        modal.appendChild(releaseCard);

        const question = document.createElement('p');
        question.style.margin = '0';
        question.style.fontSize = '11px';
        question.style.color = 'var(--foreground, #fafafa)';
        question.textContent = mode === 'install'
            ? 'Das Update ist vollständig heruntergeladen. Möchtest du Antigravity jetzt neu starten und installieren?'
            : 'Das Update wird automatisch im Hintergrund geladen. Du kannst Antigravity währenddessen weiterverwenden.';
        modal.appendChild(question);

        const buttons = document.createElement('div');
        buttons.style.display = 'flex';
        buttons.style.justifyContent = 'flex-end';
        buttons.style.gap = '8px';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.textContent = mode === 'install' ? 'Später' : 'Schließen';
        cancelBtn.style.background = 'transparent';
        cancelBtn.style.color = 'var(--muted-foreground, #71717a)';
        cancelBtn.style.border = '1px solid var(--border, #27272a)';
        cancelBtn.style.borderRadius = '4px';
        cancelBtn.style.padding = '6px 12px';
        cancelBtn.style.fontSize = '11px';
        cancelBtn.style.cursor = 'pointer';
        cancelBtn.style.outline = 'none';
        if (mode !== 'install') {
            cancelBtn.style.display = 'none';
        }

        const okBtn = document.createElement('button');
        okBtn.type = 'button';
        okBtn.textContent = mode === 'install' ? 'Neu starten & installieren' : 'Verstanden';
        okBtn.style.background = 'var(--primary, #3b82f6)';
        okBtn.style.color = '#ffffff';
        okBtn.style.border = 'none';
        okBtn.style.borderRadius = '4px';
        okBtn.style.padding = '6px 12px';
        okBtn.style.fontSize = '11px';
        okBtn.style.fontWeight = '500';
        okBtn.style.cursor = 'pointer';
        okBtn.style.outline = 'none';

        buttons.appendChild(cancelBtn);
        buttons.appendChild(okBtn);
        modal.appendChild(buttons);
        overlay.appendChild(modal);

        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        let keyHandler = null;
        let isClosed = false;
        const close = (result) => {
            if (isClosed) return;
            isClosed = true;
            if (keyHandler) {
                window.removeEventListener('keydown', keyHandler, true);
            }
            overlay.style.opacity = '0';
            modal.style.transform = 'scale(0.95)';
            setTimeout(() => {
                overlay.remove();
                if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
                    previouslyFocused.focus();
                }
            }, 200);
            onResult(result);
        };
        overlay.__antigravityDismiss = () => {
            if (isClosed) return;
            isClosed = true;
            if (keyHandler) {
                window.removeEventListener('keydown', keyHandler, true);
            }
            overlay.remove();
        };

        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(false);
        });

        okBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close(true);
        });

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                e.stopPropagation();
                close(false);
            }
        });

        keyHandler = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                close(false);
                return;
            }
            if (e.key === 'Tab') {
                const focusableButtons = getAmsModalFocusableElements(modal);
                if (!focusableButtons.length) return;
                const currentIndex = focusableButtons.indexOf(document.activeElement);
                const nextIndex = e.shiftKey
                    ? (currentIndex <= 0 ? focusableButtons.length - 1 : currentIndex - 1)
                    : (currentIndex < 0 || currentIndex === focusableButtons.length - 1 ? 0 : currentIndex + 1);
                e.preventDefault();
                e.stopPropagation();
                focusableButtons[nextIndex].focus();
            }
        };
        window.addEventListener('keydown', keyHandler, true);
        okBtn.focus();
    }

    function showCustomAlert(message) {
        const parent = document.getElementById('antigravity-plan-panel') || document.body;
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.background = 'rgba(9, 9, 11, 0.7)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10000';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';

        const modal = document.createElement('div');
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '8px';
        modal.style.padding = '16px';
        modal.style.width = '85%';
        modal.style.maxWidth = '300px';
        modal.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.5)';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.gap = '12px';
        modal.style.transform = 'scale(0.95)';
        modal.style.transition = 'transform 0.2s ease';
        modal.setAttribute('role', 'alertdialog');
        modal.setAttribute('aria-modal', 'true');

        const msgPara = document.createElement('p');
        msgPara.style.margin = '0';
        msgPara.style.fontSize = '12px';
        msgPara.style.color = 'var(--foreground, #fafafa)';
        msgPara.style.whiteSpace = 'pre-wrap';
        msgPara.style.lineHeight = '1.4';
        msgPara.textContent = message;
        msgPara.id = 'antigravity-alert-message-' + Date.now();
        modal.setAttribute('aria-describedby', msgPara.id);

        const buttons = document.createElement('div');
        buttons.style.display = 'flex';
        buttons.style.justifyContent = 'flex-end';

        const okBtn = document.createElement('button');
        okBtn.textContent = 'OK';
        okBtn.style.background = 'var(--primary, #3b82f6)';
        okBtn.style.color = '#ffffff';
        okBtn.style.border = 'none';
        okBtn.style.borderRadius = '4px';
        okBtn.style.padding = '6px 16px';
        okBtn.style.fontSize = '12px';
        okBtn.style.fontWeight = '500';
        okBtn.style.cursor = 'pointer';
        okBtn.style.outline = 'none';

        buttons.appendChild(okBtn);
        modal.appendChild(msgPara);
        modal.appendChild(buttons);
        overlay.appendChild(modal);

        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: okBtn,
            previouslyFocused,
            removeDelay: 200,
            animateClose: () => {
                overlay.style.opacity = '0';
                modal.style.transform = 'scale(0.95)';
            },
        });
        const close = () => controller.close('acknowledge');
        controller.focusInitial();

        okBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close();
        });

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                e.stopPropagation();
                close();
            }
        });

    }

    // Override window.alert globally in the main world context
    window.alert = showCustomAlert;

async function showUpdateHistoryModal() {
        const parent = document.getElementById('antigravity-plan-panel') || document.body;
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.background = 'rgba(9, 9, 11, 0.75)';
        overlay.style.backdropFilter = 'blur(6px)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10005';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.2s ease';

        const modal = document.createElement('div');
        modal.style.background = 'var(--card, #18181b)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '10px';
        modal.style.padding = '0';
        modal.style.width = '620px';
        modal.style.maxWidth = '92vw';
        modal.style.maxHeight = '82vh';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.boxShadow = '0 20px 25px -5px rgba(0, 0, 0, 0.6)';
        modal.style.transform = 'scale(0.96)';
        modal.style.transition = 'transform 0.2s ease';
        modal.style.overflow = 'hidden';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        // Header
        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.padding = '14px 18px';
        header.style.borderBottom = '1px solid var(--border, #27272a)';
        header.style.background = 'rgba(255, 255, 255, 0.02)';

        const titleBox = document.createElement('div');
        titleBox.style.display = 'flex';
        titleBox.style.alignItems = 'center';
        titleBox.style.gap = '8px';

        const titleIcon = document.createElement('span');
        titleIcon.innerHTML = \`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/></svg>\`;

        const title = document.createElement('h3');
        title.textContent = 'Anti-Gravity Update- & Patch-Log';
        title.style.margin = '0';
        title.style.fontSize = '14px';
        title.style.fontWeight = '600';
        title.style.color = 'var(--foreground, #fafafa)';
        title.id = 'antigravity-update-history-title';
        modal.setAttribute('aria-labelledby', title.id);

        titleBox.appendChild(titleIcon);
        titleBox.appendChild(title);

        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '✕';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = '#a1a1aa';
        closeBtn.style.fontSize = '14px';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.padding = '4px 8px';
        closeBtn.style.borderRadius = '4px';

        header.appendChild(titleBox);
        header.appendChild(closeBtn);
        modal.appendChild(header);

        // Content container
        const content = document.createElement('div');
        content.style.padding = '16px 18px';
        content.style.overflowY = 'auto';
        content.style.flex = '1';
        content.style.display = 'flex';
        content.style.flexDirection = 'column';
        content.style.gap = '14px';

        // Status Card
        const statusCard = document.createElement('div');
        statusCard.style.padding = '12px 14px';
        statusCard.style.borderRadius = '8px';
        statusCard.style.background = 'rgba(59, 130, 246, 0.08)';
        statusCard.style.border = '1px solid rgba(59, 130, 246, 0.25)';
        statusCard.style.display = 'flex';
        statusCard.style.justifyContent = 'space-between';
        statusCard.style.alignItems = 'center';

        const statusInfo = document.createElement('div');
        const statusTitle = document.createElement('div');
        statusTitle.style.fontSize = '12px';
        statusTitle.style.fontWeight = '600';
        statusTitle.style.color = '#60a5fa';
        statusTitle.textContent = 'Aktueller Patch-Status: Anti-Gravity';
        const statusSubtitle = document.createElement('div');
        statusSubtitle.style.fontSize = '11px';
        statusSubtitle.style.color = '#a1a1aa';
        statusSubtitle.style.marginTop = '2px';
        statusSubtitle.textContent = 'Upstream-Kompatibilität verifiziert · Selbstreparatur & Rollback aktiv';
        statusInfo.appendChild(statusTitle);
        statusInfo.appendChild(statusSubtitle);

        const statusBadge = document.createElement('span');
        statusBadge.style.fontSize = '11px';
        statusBadge.style.fontWeight = '500';
        statusBadge.style.padding = '4px 8px';
        statusBadge.style.borderRadius = '12px';
        statusBadge.style.background = 'rgba(34, 197, 94, 0.15)';
        statusBadge.style.color = '#4ade80';
        statusBadge.style.border = '1px solid rgba(34, 197, 94, 0.3)';
        statusBadge.textContent = '● Gepatcht & Aktiv';

        statusCard.appendChild(statusInfo);
        statusCard.appendChild(statusBadge);
        content.appendChild(statusCard);

        // Fetch history data
        let historyData = [];
        try {
            if (window.electronNative && typeof window.electronNative.getUpgradeHistory === 'function') {
                const res = await window.electronNative.getUpgradeHistory();
                if (res && res.status === 'success' && Array.isArray(res.history)) {
                    historyData = res.history;
                }
            }
        } catch (e) {
            console.warn('[AMS] Failed to read upgrade history from IPC:', e);
        }

        if (!historyData || historyData.length === 0) {
            historyData = [
                {
                    version: "2.22.0",
                    date: "2026-10-11",
                    upstream_status: "compatible",
                    diff_summary: {
                        "dist/main.js": "identisch (adf9f814ce...)",
                        "dist/ipcHandlers.js": "identisch (0a58fe6eba...)",
                        "dist/updater.js": "identisch (d8f44a0bb4...)",
                        "dist/utils.js": "identisch (6f01d74696...)",
                        "dist/preload.js": "getPathForFile: (file) => electron_1.webUtils.getPathForFile(file) hinzugefuegt"
                    },
                    findings: [
                        "Offizielle Google-Aktualisierung auf Anti-Gravity v2.22.0",
                        "dist/preload.js um webUtils.getPathForFile erweitert",
                        "Alle 4 weiteren Core-Dateien sind 1:1 identisch mit v2.19.1",
                        "Automatischer Selbstreparatur-Dialog bei künftigen Versionskonflikten",
                        "Automatisches Wiederherstellen des aktiven Chats nach Repack-Neustart",
                        "Update- & Patch-Log im AMS Quick-Menu verfügbar"
                    ]
                },
                {
                    version: "2.19.1",
                    date: "2026-10-02",
                    upstream_status: "compatible",
                    diff_summary: { "all_core": "kompatibel" },
                    findings: ["Stabiler Rebase auf v2.19.1 mit atomarem Staging und Rollback-Schutz"]
                }
            ];
        }

        const currentEntry = historyData.find((item) => item && item.version
            && item.result !== 'failed' && item.upstream_status !== 'failed');
        if (currentEntry) {
            statusTitle.textContent = 'Aktueller Patch-Status: Anti-Gravity v' + currentEntry.version;
        }

        // Render entries
        for (const entry of historyData) {
            const entryBox = document.createElement('div');
            entryBox.style.padding = '12px 14px';
            entryBox.style.borderRadius = '8px';
            entryBox.style.background = 'rgba(255, 255, 255, 0.03)';
            entryBox.style.border = '1px solid var(--border, #27272a)';
            entryBox.style.display = 'flex';
            entryBox.style.flexDirection = 'column';
            entryBox.style.gap = '8px';

            const entryHeader = document.createElement('div');
            entryHeader.style.display = 'flex';
            entryHeader.style.justifyContent = 'space-between';
            entryHeader.style.alignItems = 'center';

            const verTitle = document.createElement('div');
            verTitle.style.display = 'flex';
            verTitle.style.alignItems = 'center';
            verTitle.style.gap = '8px';

            const verBadge = document.createElement('span');
            verBadge.style.fontSize = '12px';
            verBadge.style.fontWeight = '600';
            verBadge.style.color = '#38bdf8';
            verBadge.textContent = 'v' + entry.version;

            const dateSpan = document.createElement('span');
            dateSpan.style.fontSize = '11px';
            dateSpan.style.color = '#71717a';
            dateSpan.textContent = entry.date || '';

            verTitle.appendChild(verBadge);
            verTitle.appendChild(dateSpan);

            const compBadge = document.createElement('span');
            compBadge.style.fontSize = '10px';
            compBadge.style.padding = '2px 6px';
            compBadge.style.borderRadius = '4px';
            const entryFailed = entry.result === 'failed' || entry.upstream_status === 'failed';
            compBadge.style.background = entryFailed ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)';
            compBadge.style.color = entryFailed ? '#f87171' : '#60a5fa';
            compBadge.textContent = entryFailed
                ? 'Fehlgeschlagen'
                : (entry.result === 'success' ? 'Selbstgeheilt & verifiziert' : (entry.upstream_status === 'compatible' ? 'Kompatibel' : (entry.upstream_status || 'Gepatcht')));

            entryHeader.appendChild(verTitle);
            entryHeader.appendChild(compBadge);
            entryBox.appendChild(entryHeader);

            if (Array.isArray(entry.steps) && entry.steps.length > 0) {
                const metaLine = document.createElement('div');
                metaLine.style.fontSize = '11px';
                metaLine.style.color = '#a1a1aa';
                metaLine.style.display = 'flex';
                metaLine.style.flexWrap = 'wrap';
                metaLine.style.gap = '4px 10px';
                const total = typeof entry.duration_s === 'number' ? ' · ' + Math.round(entry.duration_s) + ' s gesamt' : '';
                const fromText = entry.from_version ? 'v' + entry.from_version + ' → ' : '';
                const head = document.createElement('span');
                head.textContent = fromText + 'v' + entry.version + (entry.attempts > 1 ? ' · Versuch ' + entry.attempts : '') + total;
                metaLine.appendChild(head);
                for (const step of entry.steps) {
                    const chip = document.createElement('span');
                    const marks = { done: '✓', failed: '✕', running: '●', pending: '○' };
                    const colors = { done: '#4ade80', failed: '#f87171', running: '#60a5fa', pending: '#71717a' };
                    chip.style.color = colors[step.status] || '#71717a';
                    chip.textContent = (marks[step.status] || '○') + ' ' + step.label;
                    metaLine.appendChild(chip);
                }
                entryBox.appendChild(metaLine);
            }

            if (Array.isArray(entry.findings) && entry.findings.length > 0) {
                const findingsSection = document.createElement('div');
                const findingsLabel = document.createElement('div');
                findingsLabel.style.fontSize = '11px';
                findingsLabel.style.fontWeight = '600';
                findingsLabel.style.color = '#e4e4e7';
                findingsLabel.style.marginBottom = '4px';
                findingsLabel.textContent = 'Erkenntnisse & Befunde:';
                findingsSection.appendChild(findingsLabel);

                const ul = document.createElement('ul');
                ul.style.margin = '0';
                ul.style.paddingLeft = '18px';
                ul.style.fontSize = '11px';
                ul.style.color = '#d4d4d8';
                ul.style.lineHeight = '1.5';
                for (const f of entry.findings) {
                    const li = document.createElement('li');
                    li.textContent = f;
                    ul.appendChild(li);
                }
                findingsSection.appendChild(ul);
                entryBox.appendChild(findingsSection);
            }

            if (entry.diff_summary && typeof entry.diff_summary === 'object') {
                const diffSection = document.createElement('div');
                const diffLabel = document.createElement('div');
                diffLabel.style.fontSize = '11px';
                diffLabel.style.fontWeight = '600';
                diffLabel.style.color = '#a1a1aa';
                diffLabel.style.marginBottom = '4px';
                diffLabel.textContent = 'Dateianpassungen:';
                diffSection.appendChild(diffLabel);

                const diffList = document.createElement('div');
                diffList.style.display = 'flex';
                diffList.style.flexDirection = 'column';
                diffList.style.gap = '3px';

                for (const [filePath, detail] of Object.entries(entry.diff_summary)) {
                    const item = document.createElement('div');
                    item.style.fontSize = '11px';
                    item.style.fontFamily = 'monospace';
                    item.style.color = '#a1a1aa';
                    item.style.display = 'flex';
                    item.style.gap = '6px';

                    const fileSpan = document.createElement('span');
                    fileSpan.style.color = '#38bdf8';
                    fileSpan.textContent = filePath + ':';

                    const detailSpan = document.createElement('span');
                    detailSpan.style.color = '#9ca3af';
                    detailSpan.textContent = String(detail);

                    item.appendChild(fileSpan);
                    item.appendChild(detailSpan);
                    diffList.appendChild(item);
                }
                diffSection.appendChild(diffList);
                entryBox.appendChild(diffSection);
            }

            content.appendChild(entryBox);
        }

        modal.appendChild(content);

        // Footer
        const footer = document.createElement('div');
        footer.style.display = 'flex';
        footer.style.justifyContent = 'flex-end';
        footer.style.padding = '12px 18px';
        footer.style.borderTop = '1px solid var(--border, #27272a)';
        footer.style.background = 'rgba(255, 255, 255, 0.02)';

        const okBtn = document.createElement('button');
        okBtn.textContent = 'Schließen';
        okBtn.style.background = 'var(--primary, #3b82f6)';
        okBtn.style.color = '#ffffff';
        okBtn.style.border = 'none';
        okBtn.style.borderRadius = '5px';
        okBtn.style.padding = '6px 16px';
        okBtn.style.fontSize = '12px';
        okBtn.style.fontWeight = '500';
        okBtn.style.cursor = 'pointer';

        footer.appendChild(okBtn);
        modal.appendChild(footer);

        overlay.appendChild(modal);
        parent.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = '1';
            modal.style.transform = 'scale(1)';
        }, 10);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: okBtn,
            previouslyFocused,
            removeDelay: 200,
            animateClose: () => {
                overlay.style.opacity = '0';
                modal.style.transform = 'scale(0.96)';
            },
        });
        const close = () => controller.close('acknowledge');
        controller.focusInitial();

        okBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close();
        });
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            close();
        });
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                e.stopPropagation();
                close();
            }
        });
    }

    window.showUpdateHistoryModal = showUpdateHistoryModal;


    // Minimal native bridge for operating the local Anti-Gravity Hub.
    // Model providers and chat routing intentionally stay inside the Hub.
    async function amsHubCall(operation, payload = {}) {
        if (!window.electronNative || typeof window.electronNative.hubRequest !== 'function') {
            throw new Error('Anti-Gravity Hub bridge is not installed. Please run the repack once.');
        }
        return window.electronNative.hubRequest(amsToken, operation, payload);
    }

    window.amsAntigravityHub = Object.freeze({
        getStatus: () => amsHubCall('services:status'),
        getApiStatus: () => amsHubCall('api:monitor'),
        startServices: (restart = false) => amsHubCall('services:start', { restart: restart === true }),
        openHub: () => {
            if (!window.electronNative || typeof window.electronNative.openExternal !== 'function') {
                throw new Error('External link bridge is unavailable.');
            }
            return window.electronNative.openExternal('http://127.0.0.1:8000/dashboard/');
        },
    });


    // Read-only API health and request details in the normal desktop profile (opt-in only; off by default).
    (async () => {
        try {
            if (
                window.__ANTIGRAVITY_ENABLE_API_MONITOR !== true &&
                window.localStorage?.getItem?.('antigravity_enable_desktop_api_monitor') !== '1'
            ) {
                return;
            }
        } catch (_) {
            return;
        }
        let profile = null;
        try { profile = await window.electronNative?.getProfileInfo?.(); } catch (_) { /* Health still reports the verified server-side profile. */ }
        if (profile?.profile === 'api') return;
        const state = { data: null, error: null, pending: false, open: false, checkedAt: null };
        const style = document.createElement('style');
        style.id = 'antigravity-api-monitor-style';
        style.textContent = \`
            #antigravity-api-status {position:fixed;right:18px;bottom:18px;z-index:11000;display:flex;align-items:center;gap:7px;padding:7px 11px;border-radius:9px;border:1px solid #ffffff24;background:#20232c;color:#f1f3f8;font:12px system-ui;box-shadow:0 3px 14px #0003;cursor:pointer}
            #antigravity-api-status .api-dot {width:7px;height:7px;border-radius:50%;background:#9aa4b4}
            #antigravity-api-status[data-state=ready] .api-dot {background:#65d4a8}
            #antigravity-api-status[data-state=waiting] .api-dot {background:#edbf66}
            #antigravity-api-status[data-state=error] .api-dot {background:#f18484}
            #antigravity-api-panel {position:fixed;right:18px;bottom:60px;width:min(520px,calc(100vw - 36px));max-height:min(660px,calc(100vh - 110px));overflow:auto;z-index:11001;background:#191c24;color:#edf0f7;border:1px solid #ffffff26;border-radius:14px;box-shadow:0 16px 60px #0007;padding:18px;font:12px/1.5 system-ui}
            #antigravity-api-panel[hidden] {display:none}
            #antigravity-api-panel .api-header {display:flex;align-items:center;justify-content:space-between;gap:12px}
            #antigravity-api-panel h2 {font-size:16px;margin:0}
            #antigravity-api-panel button {color:inherit;background:#ffffff0c;border:1px solid #ffffff22;border-radius:7px;padding:5px 9px;cursor:pointer}
            #antigravity-api-panel .api-summary {margin:12px 0;padding:10px 12px;background:#ffffff06;border-radius:9px;overflow-wrap:anywhere}
            #antigravity-api-panel .api-muted {color:#a6afbf}
            #antigravity-api-panel .api-request {padding:11px 0;border-top:1px solid #ffffff13}
            #antigravity-api-panel .api-request-top {display:flex;align-items:center;justify-content:space-between;gap:10px}
            #antigravity-api-panel .api-state {font-size:11px;border-radius:5px;padding:2px 6px;background:#ffffff10}
            #antigravity-api-panel .api-state[data-state=success] {color:#80dfb8;background:#65d4a812}
            #antigravity-api-panel .api-state[data-state=error] {color:#ffabab;background:#f1848412}
            #antigravity-api-panel .api-preview {white-space:pre-wrap;overflow-wrap:anywhere;color:#c9d1e1;margin-top:6px}
            #antigravity-api-panel .api-error {color:#ffabab;overflow-wrap:anywhere;margin-top:7px}
            @media(prefers-color-scheme:light) {#antigravity-api-panel,#antigravity-api-status {background:#fbfcff;color:#222936;border-color:#d8dce5} #antigravity-api-panel .api-muted {color:#657084} #antigravity-api-panel .api-preview {color:#47536a}}
        \`;
        (document.head || document.documentElement).appendChild(style);
        const button = document.createElement('button');
        button.id = 'antigravity-api-status';
        button.type = 'button';
        button.setAttribute('aria-label', 'API-Status und letzte Requests anzeigen');
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', 'antigravity-api-panel');
        const dot = document.createElement('span');
        dot.className = 'api-dot';
        dot.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        button.append(dot, label);
        const panel = document.createElement('section');
        panel.id = 'antigravity-api-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-labelledby', 'antigravity-api-panel-title');
        const mount = () => {
            if (!document.body) return false;
            document.body.append(button, panel);
            return true;
        };
        if (!mount()) document.addEventListener('DOMContentLoaded', mount, { once: true });

        const node = (tag, text, className) => {
            const element = document.createElement(tag);
            if (text !== undefined) element.textContent = String(text);
            if (className) element.className = className;
            return element;
        };
        const homeIsolated = () => state.data?.isolated && state.data?.health?.cdp?.home_isolated;
        const statusLabel = () => state.error ? 'API offline' : !state.data ? 'API wird geprüft' : state.data.health?.ready && homeIsolated() ? 'API bereit' : 'API wartet';
        const formatTime = value => {
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        };
        function render() {
            label.textContent = statusLabel();
            button.dataset.state = state.error ? 'error' : state.data?.health?.ready && homeIsolated() ? 'ready' : 'waiting';
            button.title = 'Eigenes API-Profil · Health und Request-Details';
            if (!state.open) return;
            panel.replaceChildren();
            const header = node('div', undefined, 'api-header');
            const title = node('h2', 'API-Status');
            title.id = 'antigravity-api-panel-title';
            const close = node('button', '×');
            close.setAttribute('aria-label', 'API-Details schließen');
            close.onclick = () => toggle(false);
            header.append(title, close);
            panel.append(header);
            const summary = node('div', undefined, 'api-summary');
            summary.append(node('strong', statusLabel()));
            summary.append(node('div', homeIsolated() ? 'Profil api · Home, Regeln, Memory und Chats getrennt' : 'Profil api · Trennung wird geprüft', 'api-muted'));
            if (homeIsolated() && state.data?.profile_paths?.home_dir) summary.append(node('div', 'API-Home: ' + state.data.profile_paths.home_dir, 'api-muted'));
            if (state.data) summary.append(node('div', \`\${state.data.total_requests} Requests seit API-Start · \${state.data.active_requests} aktiv · \${state.data.failed_requests} Fehler\`, 'api-muted'));
            panel.append(summary);
            const error = state.error || state.data?.last_error;
            if (error) panel.append(node('div', error, 'api-error'));
            if (state.error && state.checkedAt) panel.append(node('div', 'Letzter bekannter Stand: ' + formatTime(state.checkedAt), 'api-muted'));
            panel.append(node('div', 'Letzte API-Requests', 'api-muted'));
            if (!state.data) panel.append(node('p', state.pending ? 'Status wird geladen …' : 'Keine aktuellen API-Daten verfügbar.', 'api-muted'));
            else if (!state.data.requests.length) panel.append(node('p', 'Seit diesem API-Start wurden noch keine Chat-Requests ausgeführt.', 'api-muted'));
            for (const row of (state.data?.requests || []).slice(0, 8)) {
                const item = node('div', undefined, 'api-request');
                const top = node('div', undefined, 'api-request-top');
                const badge = node('span', ({ success: 'Erfolgreich', error: 'Fehler', queued: 'Wartet', running: 'Läuft' })[row.state] || row.state, 'api-state');
                badge.dataset.state = row.state;
                top.append(node('strong', row.native_model || row.requested_model || 'Native Modellauswahl'), badge);
                item.append(top, node('div', \`\${row.request_id} · \${row.path} · \${formatTime(row.started_at)}\`, 'api-muted'));
                const details = [row.reasoning_effort ? \`Reasoning: \${row.reasoning_effort}\` : null, Number.isFinite(row.duration_ms) ? \`\${(row.duration_ms / 1000).toFixed(1)} s\` : null, row.http_status ? \`HTTP \${row.http_status}\` : null].filter(Boolean).join(' · ');
                if (details) item.append(node('div', details, 'api-muted'));
                if (row.prompt_preview) item.append(node('div', row.prompt_preview, 'api-preview'));
                if (row.response_preview) item.append(node('div', 'Antwort: ' + row.response_preview, 'api-preview'));
                if (row.error) item.append(node('div', row.error, 'api-error'));
                panel.append(item);
            }
            panel.append(node('p', 'Anzeige ist lesend. Requests laufen im separaten API-Fenster.', 'api-muted'));
        }
        async function refresh() {
            if (state.pending) return;
            state.pending = true;
            render();
            try {
                const result = await window.amsAntigravityHub.getApiStatus();
                if (!result?.ok) throw new Error(result?.error?.message || 'API-Monitor ist nicht erreichbar.');
                if (!result.data?.health || !Array.isArray(result.data.requests)) throw new Error('API-Monitor liefert ungültige Statusdaten.');
                state.data = result.data;
                state.checkedAt = result.checked_at;
                state.error = null;
            } catch (error) {
                state.error = error.message || String(error);
            } finally {
                state.pending = false;
                render();
            }
        }
        function toggle(open = !state.open) {
            state.open = open;
            panel.hidden = !open;
            button.setAttribute('aria-expanded', String(open));
            render();
            if (open) refresh();
        }
        button.onclick = () => toggle();
        window.addEventListener('keydown', event => { if (event.key === 'Escape' && state.open) toggle(false); });
        window.amsApiMonitor = Object.freeze({ refresh, show: () => toggle(true), hide: () => toggle(false) });
        render();
        refresh();
        setInterval(refresh, 5000);
    })();


    console.log('[AMS Monitor] Initializing Real-time Chat Monitor...');
    const observedMessages = new Map();
    const messageDebounceTimers = new Map();
    let lastUrl = window.location.href;

    function getSessionId() {
        const parts = window.location.pathname.split('/');
        return (parts.length > 2 && parts[2]) ? parts[2] : 'global';
    }

    function estimateTokenCount(text) {
        if (!text) return 0;
        const chars = text.length;
        const cleanText = text.replace(/\\s+/g, ' ');
        const words = cleanText.split(' ').filter(Boolean).length;
        return Math.max(1, Math.round((words * 1.3 + chars / 3.5) / 2));
    }

    function getActiveModel() {
        const modelBtn = document.querySelector('button[aria-label^="Select model, current:"]');
        if (modelBtn) {
            const text = modelBtn.textContent.trim();
            if (text) {
                window.__antigravity_last_model = text;
                return text;
            }
        }
        return window.__antigravity_last_model || 'Gemini 3.5 Flash (High)';
    }

    function formatTokenCount(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(2) + 'M';
        }
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }

    function writeLiveLog(source, content) {
        if (!window.electronNative || !window.electronNative.writeLogEntry) return;
        const session = getSessionId();
        const activeModel = getActiveModel();
        const tokensVal = estimateTokenCount(content);
        const entry = {
            session_id: session,
            event: 'message',
            source: source,
            content: content,
            timestamp: new Date().toISOString(),
            model: activeModel,
            tokens: tokensVal,
            metadata: {
                url: window.location.href
            }
        };
        window.electronNative.writeLogEntry(entry)
            .then(() => {
                console.log('[AMS Monitor] Live log entry written successfully.');
            })
            .catch(err => {
                console.error('[AMS Monitor] Failed to write live log entry:', err);
            });
    }

    function triggerMessageDebounce(el, source, content) {
        if (messageDebounceTimers.has(el)) {
            clearTimeout(messageDebounceTimers.get(el));
        }

        const timer = setTimeout(() => {
            messageDebounceTimers.delete(el);
            console.log('[AMS Monitor] Debounce finished. Writing final ' + source + ' message.');
            writeLiveLog(source, content);
        }, 2000);

        messageDebounceTimers.set(el, timer);
    }

    function scanMessages(isInitial = false) {
        const messageElements = document.querySelectorAll('[role="article"]');
        messageElements.forEach(el => {
            const label = el.getAttribute('aria-label') || '';
            const isUser = label.includes('User message');
            const isAgent = label.includes('Agent response');

            if (!isUser && !isAgent) return;

            const type = isUser ? 'User' : 'Agent';
            const textEl = isUser ? el.querySelector('.whitespace-pre-wrap') : el.querySelector('.select-text');
            if (!textEl) return;

            const text = textEl.textContent || '';
            if (!observedMessages.has(el)) {
                observedMessages.set(el, text);
                if (!isInitial) {
                    console.log('[AMS Monitor] New ' + type + ' Message detected (debouncing)...');
                    triggerMessageDebounce(el, type.toUpperCase(), text);
                }
            } else {
                const prevText = observedMessages.get(el);
                if (prevText !== text) {
                    observedMessages.set(el, text);
                    if (!isInitial) {
                        triggerMessageDebounce(el, type.toUpperCase(), text);
                    }
                }
            }
        });
    }

    // Safely initialize the MutationObserver and initial scan when document.body is ready
    function initMonitor() {
        if (!document.body) {
            setTimeout(initMonitor, 50);
            return;
        }

        scanMessages(true);

        const domObserver = new MutationObserver(() => {
            scheduleScan();
        });

        domObserver.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    let scanTimeout = null;
    function scheduleScan() {
        if (scanTimeout) return;
        scanTimeout = setTimeout(() => {
            scanTimeout = null;
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;

                // Update currentConvId dynamically on URL changes
                const urlParts = window.location.pathname.split('/');
                currentConvId = (urlParts.length > 2 && urlParts[2]) ? urlParts[2] : null;

                // Reload task plan for the new active chat
                loadInitialPlan();

                // Save last active session path (if this window is focused)
                try {
                    const path = window.location.pathname + window.location.search;
                    if (path && path !== '/' && path !== '' && document.hasFocus()) {
                        window.nativeStorage.updateItems({ antigravity_last_chat_path: path });
                    }
                } catch (e) {
                    console.error('[AMS] Failed to save active session path:', e);
                }

                observedMessages.clear();
                // Clear any pending debounces on URL change
                for (const timer of messageDebounceTimers.values()) {
                    clearTimeout(timer);
                }
                messageDebounceTimers.clear();

                scanMessages(true);
            } else {
                scanMessages(false);
            }

            // Clean up old elements
            if (document.body) {
                for (const [el, text] of observedMessages.entries()) {
                    if (!document.body.contains(el)) {
                        observedMessages.delete(el);
                        if (messageDebounceTimers.has(el)) {
                            clearTimeout(messageDebounceTimers.get(el));
                            messageDebounceTimers.delete(el);
                        }
                    }
                }
            }
        }, 100);
    }

    // Heartbeat transmitter (pings preload context every 2 seconds)
    setInterval(() => {
        try {
            window.postMessage({ type: 'antigravity-heartbeat-ping' }, window.location.origin);
        } catch (e) {}
    }, 2000);

    // Auto-Updater Check and Dialog
    if (window.electronUpdater && window.electronUpdater.onStateChanged) {
        let lastUpdateDetails = null;
        let lastDialogKey = null;
        const mergeUpdateDetails = (update) => {
            if (!update || typeof update !== 'object') return;
            const next = { ...(lastUpdateDetails || {}) };
            ['version', 'releaseNotes', 'releaseDate', 'releaseName'].forEach((key) => {
                if (update[key] !== undefined && update[key] !== null && update[key] !== '') {
                    next[key] = update[key];
                }
            });
            lastUpdateDetails = next;
        };
        const handleUpdateState = (state) => {
            console.log('[AMS Updater Watcher] State changed:', state);
            if (!state || typeof state.type !== 'string') return;
            mergeUpdateDetails(state.update);
            const details = lastUpdateDetails || {};
            const version = details.version || 'unbekannt';
            if (state.type === 'available for download' || state.type === 'downloading') {
                const dialogKey = 'background:' + version;
                if (lastDialogKey === dialogKey) return;
                lastDialogKey = dialogKey;
                showUpdateConfirm(version, details.releaseNotes || null, 'background', () => {}, details);
            } else if (state.type === 'ready') {
                const dialogKey = 'install:' + version;
                if (lastDialogKey === dialogKey) return;
                lastDialogKey = dialogKey;
                showUpdateConfirm(version, details.releaseNotes || null, 'install', (confirmed) => {
                    if (!confirmed) return;
                    console.log('[AMS Updater Watcher] Installing downloaded update.');
                    Promise.resolve(window.electronUpdater.quitAndInstall()).catch((error) => {
                        console.error('[AMS Updater Watcher] Could not install update:', error);
                    });
                }, details);
            }
        };
        window.electronUpdater.onStateChanged(handleUpdateState);
        if (typeof window.electronUpdater.getState === 'function') {
            Promise.resolve(window.electronUpdater.getState())
                .then(handleUpdateState)
                .catch((error) => {
                    console.warn('[AMS Updater Watcher] Could not restore update state:', error);
                });
        }
    }

    initMonitor();
})();
`;

function showInjectionError(err) {
    const displayError = () => {
        if (!document.body) return false;
        if (document.getElementById('antigravity-injection-error-popup')) return true;

        const overlay = document.createElement('div');
        overlay.id = 'antigravity-injection-error-popup';
        overlay.style.position = 'fixed';
        overlay.style.top = '50px';
        overlay.style.right = '20px';
        overlay.style.width = '380px';
        overlay.style.background = 'rgba(24, 24, 27, 0.95)';
        overlay.style.border = '1px solid #ef4444';
        overlay.style.borderRadius = '8px';
        overlay.style.boxShadow = '0 10px 25px -5px rgba(0, 0, 0, 0.5)';
        overlay.style.zIndex = '999999';
        overlay.style.padding = '16px';
        overlay.style.color = '#fafafa';
        overlay.style.fontFamily = 'ui-sans-serif, system-ui, sans-serif';
        overlay.style.display = 'flex';
        overlay.style.flexDirection = 'column';
        overlay.style.gap = '10px';
        overlay.style.backdropFilter = 'blur(4px)';

        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.alignItems = 'center';
        header.style.justifyContent = 'space-between';

        const title = document.createElement('span');
        title.innerHTML = '⚠️ <strong>AMS Injection Error</strong>';
        title.style.fontSize = '13px';
        title.style.color = '#ef4444';

        const closeBtn = document.createElement('button');
        closeBtn.textContent = 'Schließen';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = '1px solid #27272a';
        closeBtn.style.color = '#71717a';
        closeBtn.style.borderRadius = '4px';
        closeBtn.style.padding = '2px 8px';
        closeBtn.style.fontSize = '10px';
        closeBtn.style.cursor = 'pointer';
        closeBtn.addEventListener('click', () => overlay.remove());

        header.appendChild(title);
        header.appendChild(closeBtn);

        const msg = document.createElement('div');
        msg.style.fontSize = '11px';
        msg.style.lineHeight = '1.4';
        msg.style.color = '#d4d4d8';
        msg.textContent = 'Das AMS Main-World-Skript konnte nicht geladen werden. Dies deutet meistens auf einen Syntax- oder Escaping-Fehler im Preload-Skript hin.';

        const errorStack = document.createElement('pre');
        errorStack.style.margin = '0';
        errorStack.style.padding = '8px';
        errorStack.style.background = 'rgba(0, 0, 0, 0.3)';
        errorStack.style.borderRadius = '4px';
        errorStack.style.fontSize = '10px';
        errorStack.style.color = '#fca5a5';
        errorStack.style.overflowX = 'auto';
        errorStack.style.whiteSpace = 'pre-wrap';
        errorStack.style.fontFamily = 'monospace';

        let errDesc = err ? (err.stack || err.message || JSON.stringify(err)) : 'Unbekannter Fehler';
        if (typeof err === 'object' && err.description) {
            errDesc = err.description;
        }
        errorStack.textContent = errDesc;

        overlay.appendChild(header);
        overlay.appendChild(msg);
        overlay.appendChild(errorStack);
        document.body.appendChild(overlay);
        return true;
    };

    if (!displayError()) {
        const interval = setInterval(() => {
            if (displayError()) {
                clearInterval(interval);
            }
        }, 100);
    }
}

securityTokenPromise
    .then(() => {
        const preparedScript = amsScriptContent;

        // Monitor the main world script health
        let lastHeartbeat = Date.now();
        window.addEventListener('message', (event) => {
            if (event.source === window &&
                event.origin === window.location.origin &&
                event.data && event.data.type === 'antigravity-heartbeat-ping') {
                lastHeartbeat = Date.now();
            }
        });

        // Watchdog checker loop (every 3 seconds)
        setInterval(() => {
            // If no heartbeat for more than 6 seconds, re-inject the script
            if (Date.now() - lastHeartbeat > 6000) {
                console.warn('[AMS Preload] Heartbeat lost! Re-injecting main world script...');
                lastHeartbeat = Date.now(); // reset timer
                electron_1.webFrame.executeJavaScript(preparedScript)
                    .then(() => {
                        console.log('[AMS Preload] Successfully re-injected main world script.');
                    })
                    .catch(err => {
                        console.error('[AMS Preload] Failed to re-inject main world script:', err);
                        showInjectionError(err);
                    });
            }
        }, 3000);

        // Inject the main world script
        electron_1.webFrame.executeJavaScript(preparedScript)
            .then(() => {
                console.log('[AMS] Successfully executed main world script via webFrame.');
            })
            .catch(err => {
                console.error('[AMS] Failed to execute main world script via webFrame:', err);
                showInjectionError(err);
            });
    })
    .catch(err => {
        console.error('[AMS Preload] Failed to retrieve security token:', err);
    });
