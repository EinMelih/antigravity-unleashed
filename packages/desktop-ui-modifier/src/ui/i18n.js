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
        ['Fenster duplizieren', 'Duplicate Window'],
        ['Manuelles Git Sync & Cloud-Backup', 'Manual Git Sync & Cloud Backup'],
        ['Manuelles Git Sync', 'Manual Git Sync'],
        ['Auto-Sync (Config): Aus (klicken für 15 Min.)', 'Auto-Sync (Config): Off (click for 15m)'],
        ['Update- & Patch-Log', 'Update & Patch Log'],
        ['API-Fenster: wird geladen ...', 'API Window: loading...'],
        ['API-Fenster: sichtbar (klicken zum Verstecken)', 'API Window: visible (click to hide)'],
        ['API-Fenster: versteckt (klicken zum Anzeigen)', 'API Window: hidden (click to show)'],
        ['🌐 Sprache: Deutsch (klicken für English)', '🌐 Language: English (click for Deutsch)'],
        ['Konflikt ⚠️', 'Conflict ⚠️'],
        ['Fehler', 'Error'],

        // Composer Bar & API Monitor
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

        // Task & Plan Tracker Side Panel (Ctrl+Shift+P)
        ['Schließen', 'Close'],
        ['Notizen', 'Notes'],
        ['Hinterlasse hier deine freien Notizen für dieses Gespräch...', 'Write your session notes for this conversation here...'],
        ['Als AI-Kontext (notes.txt) freigeben', 'Share as AI context (notes.txt)'],
        ['Mit GitHub synchronisieren', 'Sync with GitHub'],
        ['Anzahl der durchgeführten Kontext-Kompaktierungen für dieses Gespräch', 'Number of context compactions performed in this conversation'],
        ['Bisher wurden keine automatischen Kompaktierungen durchgeführt.', 'No automatic context compactions performed yet.'],
        ['Token-Verbrauch für dieses Gespräch (Details per Hover)', 'Token usage for this conversation (hover for details)'],
        ['Speichert...', 'Saving...'],
        ['Gespeichert', 'Saved'],
        ['Keine uncommitted Änderungen im Workspace vorhanden', 'No uncommitted changes in workspace'],
        ['Task löschen', 'Delete task'],
        ['Task hinzufügen', 'Add task'],
        ['Möchtest du diesen Task wirklich löschen?', 'Do you really want to delete this task?'],
        ['Lade Reviews...', 'Loading reviews...'],
        ['Keine nächtlichen Läufe protokolliert.', 'No nightly runs logged yet.'],
        ['Log ansehen', 'View Log'],
        ['PR ansehen', 'View PR'],
        ['Fehler beim Laden der Reviews.', 'Failed to load reviews.'],
        ['Ausführungs-Log schließen', 'Close execution log'],
        ['Lade Log-Details aus SQLite-Datenbank...', 'Loading log details from SQLite database...'],

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
        ['Keine Änderungen gefunden', 'No changes found'],
        ['Lade Dateidiff...', 'Loading file diff...'],
        ['Commit-Beschreibung eingeben...', 'Enter commit message...'],
        ['✨ AI Generieren', '✨ Generate with AI'],
        ['AI Denkvorgang & Aktivitäten:', 'AI Thinking & Activity:'],
        ['Workspace-Status und Git-Projekt ermitteln...', 'Checking workspace status and Git repository...'],
        ['Abbrechen', 'Cancel'],
        ['Synchronisieren & Pushen', 'Sync & Push'],
        ['Öffne PowerShell für GitHub Web-Login (gh auth login --web)... Nach dem Login im Browser wird der Status automatisch aktualisiert.', 'Opening PowerShell for GitHub web login (gh auth login --web)... Status will refresh automatically after browser login.'],
        ['Erstelle/verbinde privates Repository "antigravity-config" und synchronisiere ~/.gemini/config + usage_stats.json...', 'Creating/linking private repository "antigravity-config" and syncing ~/.gemini/config + usage_stats.json...'],
        ['Importiere Config, Memory & Nutzungsdaten vom Remote (lokale Dateien werden zuvor unter ~/.gemini/config/backups/ gesichert)...', 'Importing config, memory & usage stats from remote (local files are backed up to ~/.gemini/config/backups/ first)...'],
        ['Bitte gib die GitHub-URL oder "DeinName/antigravity-config" deines bestehenden Config-Repos ein und klicke auf "Von dieser URL importieren".', 'Please enter the GitHub URL or "YourName/antigravity-config" of your existing config repo and click "Import from this URL".'],
        ['Bitte zuerst eine Repository-URL oder "user/repo" eingeben.', 'Please enter a repository URL or "user/repo" first.'],
        ['Bitte zuerst eine Repository-URL oder "user/repo" zum Importieren eingeben.', 'Please enter a repository URL or "user/repo" to import from first.'],
    ];

    const AMS_DE_TO_EN = new Map();
    const AMS_EN_TO_DE = new Map();
    AMS_EXACT_PAIRS.forEach(([de, en]) => {
        AMS_DE_TO_EN.set(de, en);
        AMS_EN_TO_DE.set(en, de);
    });

    const AMS_PATTERN_PAIRS = [
        {
            deRe: /^● Verbunden:\s*(.+)$/,
            enFmt: (m) => `● Connected: ${m[1]}`,
            enRe: /^● Connected:\s*(.+)$/,
            deFmt: (m) => `● Verbunden: ${m[1]}`,
        },
        {
            deRe: /^Auto-Sync \(Config\): Alle (\d+) Min\. ✓$/,
            enFmt: (m) => `Auto-Sync (Config): Every ${m[1]}m ✓`,
            enRe: /^Auto-Sync \(Config\): Every (\d+)m ✓$/,
            deFmt: (m) => `Auto-Sync (Config): Alle ${m[1]} Min. ✓`,
        },
        {
            deRe: /^✓ GitHub \(@angemeldet\)$/,
            enFmt: () => `✓ GitHub (@signed in)`,
            enRe: /^✓ GitHub \(@signed in\)$/,
            deFmt: () => `✓ GitHub (@angemeldet)`,
        },
        {
            deRe: /^Synchronisierte Geräte in usage_stats\.json:\s*(.+)$/,
            enFmt: (m) => `Synced devices in usage_stats.json: ${m[1]}`,
            enRe: /^Synced devices in usage_stats\.json:\s*(.+)$/,
            deFmt: (m) => `Synchronisierte Geräte in usage_stats.json: ${m[1]}`,
        },
        {
            deRe: /^(\d+) geänderte Datei\(en\) im Workspace\. Klicken zum Synchronisieren\.$/,
            enFmt: (m) => `${m[1]} modified file(s) in workspace. Click to sync.`,
            enRe: /^(\d+) modified file\(s\) in workspace\. Click to sync\.$/,
            deFmt: (m) => `${m[1]} geänderte Datei(en) im Workspace. Klicken zum Synchronisieren.`,
        },
        {
            deRe: /^Dieses Gespräch wurde bereits (\d+) mal automatisch kompaktwert \/ bereinigt\.$/,
            enFmt: (m) => `This conversation has been automatically compacted ${m[1]} time(s).`,
            enRe: /^This conversation has been automatically compacted (\d+) time\(s\)\.$/,
            deFmt: (m) => `Dieses Gespräch wurde bereits ${m[1]} mal automatisch kompaktwert / bereinigt.`,
        },
        {
            deRe: /^(\d+) Requests seit API-Start · (\d+) aktiv · (\d+) Fehler$/,
            enFmt: (m) => `${m[1]} requests since API start · ${m[2]} active · ${m[3]} errors`,
            enRe: /^(\d+) requests since API start · (\d+) active · (\d+) errors$/,
            deFmt: (m) => `${m[1]} Requests seit API-Start · ${m[2]} aktiv · ${m[3]} Fehler`,
        },
        {
            deRe: /^Letzter bekannter Stand:\s*(.+)$/,
            enFmt: (m) => `Last known state: ${m[1]}`,
            enRe: /^Last known state:\s*(.+)$/,
            deFmt: (m) => `Letzter bekannter Stand: ${m[1]}`,
        },
        {
            deRe: /^Antwort:\s*([\s\S]+)$/,
            enFmt: (m) => `Response: ${m[1]}`,
            enRe: /^Response:\s*([\s\S]+)$/,
            deFmt: (m) => `Antwort: ${m[1]}`,
        },
        {
            deRe: /^Lauf:\s*(.+)$/,
            enFmt: (m) => `Run: ${m[1]}`,
            enRe: /^Run:\s*(.+)$/,
            deFmt: (m) => `Lauf: ${m[1]}`,
        },
        {
            deRe: /^Ausführungs-Log für\s*(.+)$/,
            enFmt: (m) => `Execution Log for ${m[1]}`,
            enRe: /^Execution Log for\s*(.+)$/,
            deFmt: (m) => `Ausführungs-Log für ${m[1]}`,
        },
    ];

    window.amsGetLang = function() {
        try {
            const stored = localStorage.getItem('ams_ui_lang');
            if (stored === 'de' || stored === 'en') return stored;
        } catch (_) {}
        if (typeof nativeStorageItems === 'object' && nativeStorageItems) {
            const nsLang = nativeStorageItems.antigravity_ui_lang;
            if (nsLang === 'de' || nsLang === 'en') return nsLang;
        }
        return 'en'; // Default is English for open-source users
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
        '#antigravity-api-status',
        '#antigravity-api-panel',
        '#antigravity-quick-menu-btn',
        '#antigravity-brain-btn',
        '#antigravity-chat-token-counter',
        '.antigravity-modal-overlay',
        '.antigravity-git-modal',
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

    // Observe custom AMS UI mutations so newly opened modals/menus are translated immediately
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
            });
        };
        startObserver();
    })();
