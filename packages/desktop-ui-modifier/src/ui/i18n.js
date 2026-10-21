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
        ['🔊 Cache-Hit Sound: Aktiv (Cha-Ching)', '🔊 Cache-Hit Sound: Active (Cha-Ching)'],
        ['🔇 Cache-Hit Sound: Stumm', '🔇 Cache-Hit Sound: Muted'],
        ['🔊 Cache-Hit Sound: AN (Testen)', '🔊 Cache-Hit Sound: ON (Test)'],
        ['🔇 Cache-Hit Sound: AUS', '🔇 Cache-Hit Sound: OFF'],
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
        ['# Task Plan\n- [ ] Erster Schritt\n  - [ ] Subtask', '# Task Plan\n- [ ] First step\n  - [ ] Subtask'],
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
    ];

    const AMS_DE_TO_EN = new Map();
    const AMS_EN_TO_DE = new Map();
    AMS_EXACT_PAIRS.forEach(([de, en]) => {
        AMS_DE_TO_EN.set(de, en);
        AMS_EN_TO_DE.set(en, de);
    });

    const AMS_PATTERN_PAIRS = [
        {
            deRe: /^(Gemini|Claude):\n• 5h: (.+)\n• (?:Weekly|Wöchentlich): (.+)$/,
            enFmt: (m) => `${m[1]}:\n• 5h: ${m[2].replace(/\(Ablauf\)/g, '(Expired)')}\n• Weekly: ${m[3].replace(/\(Ablauf\)/g, '(Expired)')}`,
            enRe: /^(Gemini|Claude):\n• 5h: (.+)\n• (?:Weekly|Wöchentlich): (.+)$/,
            deFmt: (m) => `${m[1]}:\n• 5h: ${m[2].replace(/\(Expired\)/g, '(Ablauf)')}\n• Wöchentlich: ${m[3].replace(/\(Expired\)/g, '(Ablauf)')}`,
        },
        {
            deRe: /^● Verbunden:\s*(.+)$/,
            enFmt: (m) => `● Connected: ${m[1]}`,
            enRe: /^● Connected:\s*(.+)$/,
            deFmt: (m) => `● Verbunden: ${m[1]}`,
        },
        {
            deRe: /^● Online · (\d+) ms$/,
            enFmt: (m) => `● Online · ${m[1]} ms`,
            enRe: /^● Online · (\d+) ms$/,
            deFmt: (m) => `● Online · ${m[1]} ms`,
        },
        {
            deRe: /^API-Home:\s*(.+)$/,
            enFmt: (m) => `API Home: ${m[1]}`,
            enRe: /^API Home:\s*(.+)$/,
            deFmt: (m) => `API-Home: ${m[1]}`,
        },
        {
            deRe: /^Konfliktdateien:\s*(.+)$/,
            enFmt: (m) => `Conflict files: ${m[1]}`,
            enRe: /^Conflict files:\s*(.+)$/,
            deFmt: (m) => `Konfliktdateien: ${m[1]}`,
        },
        {
            deRe: /^Achtung: Git-Konflikte\/Backups im Brain-Ordner erkannt!\s*\((.+)\)\.\s*Klicke hier zum Öffnen\.$/,
            enFmt: (m) => `Warning: Git conflicts/backups detected in Brain folder! (${m[1]}). Click here to open.`,
            enRe: /^Warning: Git conflicts\/backups detected in Brain folder!\s*\((.+)\)\.\s*Click here to open\.$/,
            deFmt: (m) => `Achtung: Git-Konflikte/Backups im Brain-Ordner erkannt! (${m[1]}). Klicke hier zum Öffnen.`,
        },
        {
            deRe: /^Claude verbraucht\. Automatisch auf (.+) umgeschaltet\.$/,
            enFmt: (m) => `Claude quota exhausted. Automatically switched to ${m[1]}.`,
            enRe: /^Claude quota exhausted\. Automatically switched to (.+)\.$/,
            deFmt: (m) => `Claude verbraucht. Automatisch auf ${m[1]} umgeschaltet.`,
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
            deRe: /^Akkumulierter Verbrauch für dieses Gespräch:\n• Input \(Gesamt\): (.+)\n  - Aus Cache: (.+)\n  - Uncached: (.+)\n• Output \(Antworten\): (.+)\n\nLetzter Schritt:\n• Input: (.+)\n  - Aus Cache: (.+)\n  - Uncached: (.+)\n• Output: (.+)$/,
            enFmt: (m) => `Accumulated usage for this conversation:\n• Input (Total): ${m[1]}\n  - Cached: ${m[2]}\n  - Uncached: ${m[3]}\n• Output (Responses): ${m[4]}\n\nLatest step:\n• Input: ${m[5]}\n  - Cached: ${m[6]}\n  - Uncached: ${m[7]}\n• Output: ${m[8]}`,
            enRe: /^Accumulated usage for this conversation:\n• Input \(Total\): (.+)\n  - Cached: (.+)\n  - Uncached: (.+)\n• Output \(Responses\): (.+)\n\nLatest step:\n• Input: (.+)\n  - Cached: (.+)\n  - Uncached: (.+)\n• Output: (.+)$/,
            deFmt: (m) => `Akkumulierter Verbrauch für dieses Gespräch:\n• Input (Gesamt): ${m[1]}\n  - Aus Cache: ${m[2]}\n  - Uncached: ${m[3]}\n• Output (Antworten): ${m[4]}\n\nLetzter Schritt:\n• Input: ${m[5]}\n  - Aus Cache: ${m[6]}\n  - Uncached: ${m[7]}\n• Output: ${m[8]}`,
        },
        {
            deRe: /^Akkumulierter Token-Verbrauch \(Input\): (.+)\nCache-Trefferquote: (.+)\nOutput: (.+)\n\(Details im Task-Planer\)$/,
            enFmt: (m) => `Accumulated token usage (Input): ${m[1]}\nCache hit rate: ${m[2]}\nOutput: ${m[3]}\n(Details in Task Tracker)`,
            enRe: /^Accumulated token usage \(Input\): (.+)\nCache hit rate: (.+)\nOutput: (.+)\n\(Details in Task Tracker\)$/,
            deFmt: (m) => `Akkumulierter Token-Verbrauch (Input): ${m[1]}\nCache-Trefferquote: ${m[2]}\nOutput: ${m[3]}\n(Details im Task-Planer)`,
        },
        {
            deRe: /^Akkumulierter Verbrauch für dieses Gespräch:\n• Input \(Gesamt\): (.+)\n• Output \(Generiert\): (.+)\n•\s*Aktueller Kontext: (.+) Tokens$/,
            enFmt: (m) => `Accumulated usage for this conversation:\n• Input (Total): ${m[1]}\n• Output (Generated): ${m[2]}\n• Current Context: ${m[3]} tokens`,
            enRe: /^Accumulated usage for this conversation:\n• Input \(Total\): (.+)\n• Output \(Generated\): (.+)\n• Current Context: (.+) tokens$/,
            deFmt: (m) => `Akkumulierter Verbrauch für dieses Gespräch:\n• Input (Gesamt): ${m[1]}\n• Output (Generiert): ${m[2]}\n•Aktueller Kontext: ${m[3]} Tokens`,
        },
        {
            deRe: /^Akkumulierter Token-Verbrauch \(Input\): (.+)\nAktuelles Kontextfenster: (.+) Tokens$/,
            enFmt: (m) => `Accumulated token usage (Input): ${m[1]}\nCurrent context window: ${m[2]} tokens`,
            enRe: /^Accumulated token usage \(Input\): (.+)\nCurrent context window: (.+) tokens$/,
            deFmt: (m) => `Akkumulierter Token-Verbrauch (Input): ${m[1]}\nAktuelles Kontextfenster: ${m[2]} Tokens`,
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
            deRe: /^\| Start:\s*(.+)$/,
            enFmt: (m) => `| Start: ${m[1]}`,
            enRe: /^\| Start:\s*(.+)$/,
            deFmt: (m) => `| Start: ${m[1]}`,
        },
        {
            deRe: /^\| Ende:\s*(.+)$/,
            enFmt: (m) => `| End: ${m[1]}`,
            enRe: /^\| End:\s*(.+)$/,
            deFmt: (m) => `| Ende: ${m[1]}`,
        },
        {
            deRe: /^Ausführungs-Log für\s*(.+)$/,
            enFmt: (m) => `Execution Log for ${m[1]}`,
            enRe: /^Execution Log for\s*(.+)$/,
            deFmt: (m) => `Ausführungs-Log für ${m[1]}`,
        },
        {
            deRe: /^Neuen Task unter ['"](.+)['"] hinzufügen:$/,
            enFmt: (m) => `Add new task under '${m[1]}':`,
            enRe: /^Add new task under ['"](.+)['"]:$/,
            deFmt: (m) => `Neuen Task unter '${m[1]}' hinzufügen:`,
        },
        {
            deRe: /^Synchronisation erfolgreich abgeschlossen!\n\n([\s\S]*)$/,
            enFmt: (m) => `Synchronization completed successfully!\n\n${m[1]}`,
            enRe: /^Synchronization completed successfully!\n\n([\s\S]*)$/,
            deFmt: (m) => `Synchronisation erfolgreich abgeschlossen!\n\n${m[1]}`,
        },
        {
            deRe: /^Fehler bei der Synchronisation:\n\n([\s\S]*)$/,
            enFmt: (m) => `Synchronization failed:\n\n${m[1]}`,
            enRe: /^Synchronization failed:\n\n([\s\S]*)$/,
            deFmt: (m) => `Fehler bei der Synchronisation:\n\n${m[1]}`,
        },
        {
            deRe: /^Ausnahmefehler bei der Synchronisation:\s*([\s\S]*)$/,
            enFmt: (m) => `Synchronization exception: ${m[1]}`,
            enRe: /^Synchronization exception:\s*([\s\S]*)$/,
            deFmt: (m) => `Ausnahmefehler bei der Synchronisation: ${m[1]}`,
        },
        {
            deRe: /^AI führt Tool aus:\s*(.+)\.\.\.$/,
            enFmt: (m) => `AI executing tool: ${m[1]}...`,
            enRe: /^AI executing tool:\s*(.+)\.\.\.$/,
            deFmt: (m) => `AI führt Tool aus: ${m[1]}...`,
        },
        {
            deRe: /^Pfad:\s*(.+)$/,
            enFmt: (m) => `Path: ${m[1]}`,
            enRe: /^Path:\s*(.+)$/,
            deFmt: (m) => `Pfad: ${m[1]}`,
        },
        {
            deRe: /^Fehler beim Laden:\s*(.+)$/,
            enFmt: (m) => `Failed to load: ${m[1]}`,
            enRe: /^Failed to load:\s*(.+)$/,
            deFmt: (m) => `Fehler beim Laden: ${m[1]}`,
        },
        {
            deRe: /^Ausnahmefehler:\s*(.+)$/,
            enFmt: (m) => `Exception: ${m[1]}`,
            enRe: /^Exception:\s*(.+)$/,
            deFmt: (m) => `Ausnahmefehler: ${m[1]}`,
        },
        {
            deRe: /^Exception beim Laden:\s*(.+)$/,
            enFmt: (m) => `Exception while loading: ${m[1]}`,
            enRe: /^Exception while loading:\s*(.+)$/,
            deFmt: (m) => `Exception beim Laden: ${m[1]}`,
        },
        {
            deRe: /^Fehler beim Laden des Diffs:\s*(.+)$/,
            enFmt: (m) => `Failed to load diff: ${m[1]}`,
            enRe: /^Failed to load diff:\s*(.+)$/,
            deFmt: (m) => `Fehler beim Laden des Diffs: ${m[1]}`,
        },
        {
            deRe: /^Fehler bei der AI-Generierung:\s*(.+)$/,
            enFmt: (m) => `AI generation failed: ${m[1]}`,
            enRe: /^AI generation failed:\s*(.+)$/,
            deFmt: (m) => `Fehler bei der AI-Generierung: ${m[1]}`,
        },
        {
            deRe: /^Fehler bei der Analyse:\s*(.+)$/,
            enFmt: (m) => `Analysis failed: ${m[1]}`,
            enRe: /^Analysis failed:\s*(.+)$/,
            deFmt: (m) => `Fehler bei der Analyse: ${m[1]}`,
        },
        {
            deRe: /^Fehler beim Speichern:\s*(.+)$/,
            enFmt: (m) => `Failed to save: ${m[1]}`,
            enRe: /^Failed to save:\s*(.+)$/,
            deFmt: (m) => `Fehler beim Speichern: ${m[1]}`,
        },
        {
            deRe: /^Speicherfehler:\s*(.+)$/,
            enFmt: (m) => `Save error: ${m[1]}`,
            enRe: /^Save error:\s*(.+)$/,
            deFmt: (m) => `Speicherfehler: ${m[1]}`,
        },
        {
            deRe: /^Erkenntnis gespeichert, Kompilierung fehlgeschlagen:\s*(.+)$/,
            enFmt: (m) => `Insight saved, compilation failed: ${m[1]}`,
            enRe: /^Insight saved, compilation failed:\s*(.+)$/,
            deFmt: (m) => `Erkenntnis gespeichert, Kompilierung fehlgeschlagen: ${m[1]}`,
        },
        {
            deRe: /^Verbinde Remote "(.+)" und pushe lokale Config \+ Nutzungsdaten\.\.\.$/,
            enFmt: (m) => `Linking remote "${m[1]}" and pushing local config + usage stats...`,
            enRe: /^Linking remote "(.+)" and pushing local config \+ usage stats\.\.\.$/,
            deFmt: (m) => `Verbinde Remote "${m[1]}" und pushe lokale Config + Nutzungsdaten...`,
        },
        {
            deRe: /^Offizielles Update bereit \(v(.+)\)$/,
            enFmt: (m) => `Official Update Ready (v${m[1]})`,
            enRe: /^Official Update Ready \(v(.+)\)$/,
            deFmt: (m) => `Offizielles Update bereit (v${m[1]})`,
        },
        {
            deRe: /^Offizielles Update verfügbar \(v(.+)\)$/,
            enFmt: (m) => `Official Update Available (v${m[1]})`,
            enRe: /^Official Update Available \(v(.+)\)$/,
            deFmt: (m) => `Offizielles Update verfügbar (v${m[1]})`,
        },
        {
            deRe: /^(\d+) Verbesserungen · (\d+) Fehlerbehebungen$/,
            enFmt: (m) => `${m[1]} improvements · ${m[2]} bug fixes`,
            enRe: /^(\d+) improvements · (\d+) bug fixes$/,
            deFmt: (m) => `${m[1]} Verbesserungen · ${m[2]} Fehlerbehebungen`,
        },
        {
            deRe: /^Aktueller Patch-Status: (.+)$/,
            enFmt: (m) => `Current Patch Status: ${m[1]}`,
            enRe: /^Current Patch Status: (.+)$/,
            deFmt: (m) => `Aktueller Patch-Status: ${m[1]}`,
        },
        {
            deRe: /^Anti-Gravity v(.+) erfolgreich mit dem UI-Modifier abgeglichen und verifiziert\.$/,
            enFmt: (m) => `Anti-Gravity v${m[1]} successfully reconciled and verified with the UI modifier.`,
            enRe: /^Anti-Gravity v(.+) successfully reconciled and verified with the UI modifier\.$/,
            deFmt: (m) => `Anti-Gravity v${m[1]} erfolgreich mit dem UI-Modifier abgeglichen und verifiziert.`,
        },
        {
            deRe: /^· (\d+) s gesamt$/,
            enFmt: (m) => `· ${m[1]} s total`,
            enRe: /^· (\d+) s total$/,
            deFmt: (m) => `· ${m[1]} s gesamt`,
        },
        {
            deRe: /^· Versuch (\d+)$/,
            enFmt: (m) => `· Attempt ${m[1]}`,
            enRe: /^· Attempt (\d+)$/,
            deFmt: (m) => `· Versuch ${m[1]}`,
        },
        {
            deRe: /^✓ Privates GitHub-Repository verbunden & synchronisiert!$/,
            enFmt: () => `✓ Private GitHub repository connected & synced!`,
            enRe: /^✓ Private GitHub repository connected & synced!$/,
            deFmt: () => `✓ Privates GitHub-Repository verbunden & synchronisiert!`,
        },
        {
            deRe: /^✗ Fehler beim Erstellen\/Verbinden des Repositories\.$/,
            enFmt: () => `✗ Failed to create/connect repository.`,
            enRe: /^✗ Failed to create\/connect repository\.$/,
            deFmt: () => `✗ Fehler beim Erstellen/Verbinden des Repositories.`,
        },
        {
            deRe: /^✓ Config & Nutzungsdaten erfolgreich importiert!$/,
            enFmt: () => `✓ Config & usage stats imported successfully!`,
            enRe: /^✓ Config & usage stats imported successfully!$/,
            deFmt: () => `✓ Config & Nutzungsdaten erfolgreich importiert!`,
        },
        {
            deRe: /^✗ Import fehlgeschlagen\.$/,
            enFmt: () => `✗ Import failed.`,
            enRe: /^✗ Import failed\.$/,
            deFmt: () => `✗ Import fehlgeschlagen.`,
        },
        {
            deRe: /^✓ Remote verbunden und synchronisiert!$/,
            enFmt: () => `✓ Remote connected and synced!`,
            enRe: /^✓ Remote connected and synced!$/,
            deFmt: () => `✓ Remote verbunden und synchronisiert!`,
        },
        {
            deRe: /^✗ Verbindung fehlgeschlagen\.$/,
            enFmt: () => `✗ Connection failed.`,
            enRe: /^✗ Connection failed\.$/,
            deFmt: () => `✗ Verbindung fehlgeschlagen.`,
        },
        {
            deRe: /^✗ Ausnahmefehler(?:\s+beim Import)?:\s*(.+)$/,
            enFmt: (m) => `✗ Exception: ${m[1]}`,
            enRe: /^✗ Exception:\s*(.+)$/,
            deFmt: (m) => `✗ Ausnahmefehler: ${m[1]}`,
        },
        {
            deRe: /^✗ Fehler:\s*(.+)$/,
            enFmt: (m) => `✗ Error: ${m[1]}`,
            enRe: /^✗ Error:\s*(.+)$/,
            deFmt: (m) => `✗ Fehler: ${m[1]}`,
        },
        {
            deRe: /^Fehler:\s*(.+)$/,
            enFmt: (m) => `Error: ${m[1]}`,
            enRe: /^Error:\s*(.+)$/,
            deFmt: (m) => `Fehler: ${m[1]}`,
        },
        {
            deRe: /^Ausnahmefehler bei der Generierung:\s*(.+)$/,
            enFmt: (m) => `Generation exception: ${m[1]}`,
            enRe: /^Generation exception:\s*(.+)$/,
            deFmt: (m) => `Ausnahmefehler bei der Generierung: ${m[1]}`,
        },
        {
            deRe: /^(\d+) Einträge \| (.+) Tokens$/,
            enFmt: (m) => `${m[1]} entries | ${m[2]} tokens`,
            enRe: /^(\d+) entries \| (.+) tokens$/,
            deFmt: (m) => `${m[1]} Einträge | ${m[2]} Tokens`,
        },
        {
            deRe: /^Datei nicht gefunden:\s*(.+)$/,
            enFmt: (m) => `File not found: ${m[1]}`,
            enRe: /^File not found:\s*(.+)$/,
            deFmt: (m) => `Datei nicht gefunden: ${m[1]}`,
        },
        {
            deRe: /^Eintrag gespeichert, aber Kompilierung fehlgeschlagen:\s*(.+)$/,
            enFmt: (m) => `Entry saved, but compilation failed: ${m[1]}`,
            enRe: /^Entry saved, but compilation failed:\s*(.+)$/,
            deFmt: (m) => `Eintrag gespeichert, aber Kompilierung fehlgeschlagen: ${m[1]}`,
        },
        {
            deRe: /^Datenbank für Chat (.+) existiert nicht oder wurde bereinigt\.$/,
            enFmt: (m) => `Database for chat ${m[1]} does not exist or has been cleaned up.`,
            enRe: /^Database for chat (.+) does not exist or has been cleaned up\.$/,
            deFmt: (m) => `Datenbank für Chat ${m[1]} existiert nicht oder wurde bereinigt.`,
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
