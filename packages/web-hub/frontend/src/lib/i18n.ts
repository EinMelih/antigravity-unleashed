import { useEffect, useSyncExternalStore } from "react";

export type HubLanguage = "de" | "en";

const STORAGE_KEY = "antigravity_hub_lang";
const EVENT_NAME = "antigravity-hub-lang-change";

const HUB_EXACT_PAIRS: ReadonlyArray<readonly [string, string]> = [
  // --- App Shell, Navigation & Command Palette ---
  ["Zum Inhalt springen", "Skip to main content"],
  ["Hauptnavigation", "Main navigation"],
  ["Mobile Navigation", "Mobile navigation"],
  ["Navigation öffnen", "Open navigation"],
  ["Navigation schließen", "Close navigation"],
  ["Befehlspalette", "Command palette"],
  ["Befehlspalette schließen", "Close command palette"],
  ["Ansichten und Projekte im Anti-Gravity Hub öffnen", "Open views and projects in Anti-Gravity Hub"],
  ["Hub durchsuchen", "Search Hub"],
  ["Ansicht oder Projekt öffnen …", "Open view or project …"],
  ["Keine passende Ansicht oder kein passendes Projekt.", "No matching view or project."],
  ["öffnet diese Palette überall.", "opens this palette anywhere."],
  [" + ", " + "],
  ["Strg", "Ctrl"],
  ["Pausiert – Bugfixes nach Updates ausstehend", "Paused – bugfixes pending after updates"],
  ["Conversations und aktive Agenten", "Conversations and active agents"],
  ["Geplante Agentenaufgaben", "Scheduled agent tasks"],
  ["GitHub und Custom API", "GitHub and Custom API"],
  ["Verbindungen und Diagnose", "Connections and diagnostics"],
  ["Sprache auf Englisch umstellen", "Switch language to English"],
  ["Sprache auf Deutsch umstellen", "Switch language to German"],
  ["Details schließen", "Close details"],
  ["Detailbereiche", "Detail sections"],

  // --- Common Actions & Labels ---
  ["Schließen", "Close"],
  ["Abbrechen", "Cancel"],
  ["Speichern", "Save"],
  ["Aktualisieren", "Refresh"],
  ["Erneut laden", "Reload"],
  ["Neu laden", "Reload"],
  ["Erneut versuchen", "Try again"],
  ["Erneut prüfen", "Check again"],
  ["Zurücksetzen", "Reset"],
  ["Filter zurücksetzen", "Reset filters"],
  ["Löschen", "Delete"],
  ["Ja, löschen", "Yes, delete"],
  ["Dauerhaft löschen?", "Delete permanently?"],
  ["Nichts zu löschen", "Nothing to delete"],
  ["Wird gelöscht …", "Deleting …"],
  ["Bearbeiten", "Edit"],
  ["Erstellen", "Create"],
  ["Öffnen", "Open"],
  ["Verwalten", "Manage"],
  ["Verknüpfen", "Link"],
  ["Wiederherstellen", "Restore"],
  ["Entfernen", "Remove"],
  ["Auswählen", "Select"],
  ["Sichtbare auswählen", "Select visible"],
  ["Sichtbare abwählen", "Deselect visible"],
  ["Starten", "Start"],
  ["Stoppen", "Stop"],
  ["Pausieren", "Pause"],
  ["Aktivieren", "Enable"],
  ["Testen", "Test"],
  ["Abmelden", "Sign out"],
  ["Alle", "All"],
  ["Keine", "None"],
  ["Aktiv", "Active"],
  ["Inaktiv", "Inactive"],
  ["Bereit", "Ready"],
  ["Pausiert", "Paused"],
  ["Fehler", "Error"],
  ["Prüfen", "Check"],
  ["Extern", "External"],
  ["Gesund", "Healthy"],
  ["Aufmerksamkeit", "Attention"],
  ["Blockiert", "Blocked"],
  ["Archiviert", "Archived"],
  ["Unbekannt", "Unknown"],
  ["Als Nächstes", "Up Next"],
  ["Danach", "Then"],
  ["Jetzt wichtig", "Important now"],
  ["Nächste Schritte", "Next Steps"],

  // --- States (Loading / Error / Offline) ---
  ["Einen Moment bitte", "One moment please"],
  ["Die aktuellen Informationen werden geladen.", "Loading the latest information."],
  ["Das hat nicht funktioniert", "Something went wrong"],
  ["Hub nicht erreichbar", "Hub unreachable"],
  ["Verbindung erneut prüfen", "Check connection again"],
  ["Der lokale Python-Hub antwortet nicht. Deine Eingaben bleiben erhalten; prüfe den Dienst und versuche es erneut.", "The local Python Hub is not responding. Your inputs are preserved; check the service and try again."],

  // --- System Connection & Fleet Dropdown ---
  ["Verbindung wird geprüft", "Checking connection"],
  ["Hub online · Anti-Gravity wartet", "Hub online · Waiting for Anti-Gravity"],
  ["Instanzen werden geprüft", "Checking instances"],
  ["Instanzstatus nicht verfügbar", "Instance status unavailable"],
  ["Anti-Gravity offline", "Anti-Gravity offline"],
  ["Zuordnung prüfen", "Check binding"],
  ["Status unklar", "Status unclear"],
  ["Freigabe nötig", "Approval needed"],
  ["Anti-Gravity verbunden", "Anti-Gravity connected"],
  ["Anti-Gravity Instanzen", "Anti-Gravity Instances"],
  ["Teilweise erreichbar", "Partially reachable"],
  ["Nicht erreichbar", "Unreachable"],
  ["Hauptfenster", "Main window"],
  ["Wird vorbereitet", "Preparing"],
  ["Sendet", "Sending"],
  ["Arbeitet", "Working"],
  ["Dein Hauptfenster", "Your main window"],
  ["Kein Chat zugeordnet", "No chat assigned"],
  ["Noch keine native Instanz erkannt.", "No native instance detected yet."],

  // --- Domain Labels (`domain-labels.ts`) ---
  ["Akzeptiert", "Accepted"],
  ["Freigegeben", "Approved"],
  ["Beendet", "Cancelled"],
  ["Vollständig", "Complete"],
  ["Unvollständig", "Incomplete"],
  ["Abgeschlossen", "Completed"],
  ["Veraltet", "Deprecated"],
  ["Entwurf", "Draft"],
  ["Fehlgeschlagen", "Failed"],
  ["Fehlerfrei", "Healthy"],
  ["Im Eingang", "In Inbox"],
  ["Als Datei gespeichert", "Saved as file"],
  ["Zusammengeführt", "Merged"],
  ["Nicht angefordert", "Not requested"],
  ["Aus dem Plan genommen", "Removed from plan"],
  ["Ausstehend", "Pending"],
  ["Geplant", "Planned"],
  ["Vorgeschlagen", "Proposed"],
  ["Bereit zur Prüfung", "Ready for review"],
  ["Aufgezeichnet", "Recorded"],
  ["Abgelehnt", "Rejected"],
  ["Prüfung offen", "Review pending"],
  ["In Arbeit", "In progress"],
  ["Ersetzt", "Superseded"],
  ["Entscheidung nötig", "Decision needed"],
  ["Unbekannter Zustand", "Unknown state"],
  ["Architekturentscheidung", "Architecture Decision (ADR)"],
  ["Entscheidungsprotokoll", "Decision Ledger"],
  ["Technisches Konzept", "Technical Design"],
  ["Ideen-Dokument", "Idea Document"],
  ["Umsetzungsplan", "Implementation Plan"],
  ["Weiteres Dokument", "Other Document"],
  ["enthält", "contains"],
  ["entschieden durch", "decided by"],
  ["weiterentwickelt zu", "developed into"],
  ["dokumentiert", "documents"],
  ["folgt der Entscheidung", "follows decision"],
  ["setzt um", "implements"],
  ["setzt das Konzept um", "implements design"],
  ["liefert die Grundlage für", "informs"],
  ["berücksichtigt", "informed by"],
  ["verweist auf", "references"],
  ["ersetzt", "supersedes"],
  ["inhaltlich verknüpft mit", "related to"],
  ["Von Anti-Gravity", "From Anti-Gravity"],
  ["Aus einem Chat", "From a chat"],
  ["Von dir", "From you"],
  ["Aus der Planung", "From planning"],
  ["Über Telegram", "Via Telegram"],
  ["Quelle aufgezeichnet", "Source recorded"],
  ["Entwicklung", "Development"],
  ["Lokal", "Local"],
  ["Vorschau", "Preview"],
  ["Produktion", "Production"],
  ["Testumgebung", "Staging"],
  ["Weitere Umgebung", "Other environment"],
  ["Abnahmekriterien", "Acceptance criteria"],
  ["Startregeln", "Activation policy"],
  ["Annahmen", "Assumptions"],
  ["Codebasis", "Base SHA"],
  ["Vorgaben", "Constraints"],
  ["Ziel", "Goal"],
  ["Nicht-Ziele", "Non-goals"],
  ["Zentrale Entscheidung", "Pivotal decision"],
  ["Planungstiefe", "Planning depth"],
  ["Maximale geplante PRs", "Max planned PRs"],
  ["Risiko", "Risk level"],
  ["Rückkehrplan", "Rollback plan"],
  ["Auslieferungsplan", "Rollout plan"],
  ["Erfolgskriterien", "Success metrics"],
  ["Titel", "Title"],
  ["Weitere Planeinstellung", "Other plan setting"],

  // --- Chats Page & Components ---
  ["Chats", "Chats"],
  ["Chats und Anti-Gravity-Zustand werden synchronisiert.", "Synchronizing chats and Anti-Gravity state."],
  ["Chatliste öffnen", "Open chat list"],
  ["Chatkontext öffnen", "Open chat context"],
  ["Chats aktualisieren", "Refresh chats"],
  ["Neuer Chat", "New Chat"],
  ["Die native Anti-Gravity-Verbindung ist noch nicht bereit. Lokale Provider-Chats bleiben verfügbar.", "Native Anti-Gravity connection is not ready yet. Local provider chats remain available."],
  ["Ersten Chat starten", "Start first chat"],
  ["Starte eine Conversation oder arbeite direkt in einem verknüpften Projekt.", "Start a conversation or work directly inside a linked project."],
  ["Noch keine Chats", "No chats yet"],
  ["Chatliste", "Chat list"],
  ["Conversation auswählen oder durchsuchen", "Select or search conversation"],
  ["Chatkontext", "Chat context"],
  ["Status, Projekt und technische Informationen", "Status, project, and technical details"],
  ["Chats durchsuchen", "Search chats"],
  ["Chatfilter", "Chat filter"],
  ["Chattyp", "Chat type"],
  ["Alle Typen", "All types"],
  ["Normalchats", "Normal chats"],
  ["Projektchats", "Project chats"],
  ["Projekt filtern", "Filter project"],
  ["Alle Projekte", "All projects"],
  ["Chatauswahl", "Chat selection"],
  ["Unbenannter Chat", "Untitled chat"],
  ["Unbekanntes Projekt", "Unknown project"],
  ["Projekt", "Project"],
  ["Normalchat", "Normal chat"],
  ["Arbeitet gerade", "Currently working"],
  ["Keine passenden Chats.", "No matching chats."],
  ["jetzt", "just now"],
  ["Fokus", "Focus"],
  ["Mehrere", "Grid"],
  ["Chat-Arbeitsbereich", "Chat workspace"],
  ["Fensterlayout", "Window layout"],
  ["Aktive Ansicht", "Active view"],
  ["Wähle links einen Chat aus.", "Select a chat on the left."],
  ["Dediziertes AG-Fenster wird hochgefahren …", "Starting dedicated AG window …"],
  ["Nachricht wird an Anti-Gravity übergeben …", "Handing message over to Anti-Gravity …"],
  ["Zugestellt · Persistenz wird verifiziert …", "Delivered · Verifying persistence …"],
  ["Zustellung bestätigt", "Delivery confirmed"],
  ["Zustellung fehlgeschlagen", "Delivery failed"],
  ["Provider wird vorbereitet …", "Preparing provider …"],
  ["Nachricht wird verarbeitet …", "Processing message …"],
  ["In Anti-Gravity öffnen", "Open in Anti-Gravity"],
  ["Lokaler Provider-Chat", "Local provider chat"],
  ["Brain-Ordner öffnen", "Open Brain folder"],
  ["Arbeitsordner öffnen", "Open workspace folder"],
  ["Kein Brain-Ordner bei lokalen Provider-Chats", "No Brain folder for local provider chats"],
  ["Chat wiederherstellen", "Restore chat"],
  ["Chat archivieren", "Archive chat"],
  ["Chat löschen", "Delete chat"],
  ["Laufenden Chat zuerst abschließen", "Finish running chat first"],
  ["Chat dauerhaft löschen", "Delete chat permanently"],
  ["Chat dauerhaft löschen?", "Delete chat permanently?"],
  ["Diese Aktion kann nicht rückgängig gemacht werden.", "This action cannot be undone."],
  ["Dieser Chat ist archiviert.", "This chat is archived."],
  ["Der Verlauf bleibt lesbar. Stelle ihn wieder her, bevor du schreibst.", "History remains readable. Restore the chat before sending messages."],
  ["Dieser Chat ist archiviert. Stelle ihn zuerst wieder her.", "This chat is archived. Restore it first."],
  ["Verlauf wird geladen …", "Loading history …"],
  ["Dieser Chat enthält noch keine Nachrichten.", "This chat contains no messages yet."],
  ["Du", "You"],
  ["Denkprozess", "Thought process"],
  ["Angehängtes Bild", "Attached image"],
  ["Anhang", "Attachment"],
  ["Warteschlange für Nachrichten", "Message queue"],
  ["Wird gesendet, sobald der Agent fertig ist", "Will be sent as soon as the agent finishes"],
  ["Bereit zum Senden", "Ready to send"],
  ["Warteschlange ausklappen", "Expand queue"],
  ["Warteschlange einklappen", "Collapse queue"],
  ["(Nur Anhang)", "(Attachment only)"],
  ["Jetzt sofort senden", "Send immediately"],
  ["Sofort senden", "Send now"],
  ["Nachricht bearbeiten", "Edit message"],
  ["Aus Warteschlange löschen", "Remove from queue"],
  ["Modell wird gewechselt …", "Switching model …"],
  ["Diktatfenster wird gestartet …", "Starting dictation window …"],
  ["Aufnahme wird beendet …", "Stopping recording …"],
  ["Bilder anhängen", "Attach images"],
  ["Nachricht an Anti-Gravity", "Message to Anti-Gravity"],
  ["Nachricht schreiben …", "Write a message …"],
  ["Spracheingabe starten", "Start voice input"],
  ["Aufnahme beenden", "Stop recording"],
  ["Nachricht senden", "Send message"],
  ["Modell auswählen", "Select model"],
  ["Modell wird erkannt …", "Detecting model …"],
  ["Kontext", "Context"],
  ["Aktiver Chat", "Active Chat"],
  ["Status", "Status"],
  ["AG-Fenster", "AG Window"],
  ["Nicht benötigt", "Not required"],
  ["Bei Bedarf", "On demand"],
  ["Ohne Projekt", "No project"],
  ["Quelle", "Source"],
  ["Die Instanz zeigt einen anderen Chat als ihre letzte Hub-Zuordnung. Der Live-Chat wird verwendet.", "The instance shows a different chat than its last Hub binding. Using the live chat."],
  ["Projektübersicht öffnen", "Open project overview"],
  ["Technische Details", "Technical details"],
  ["Chat-ID", "Chat ID"],
  ["Schritte", "Steps"],
  ["Workspace", "Workspace"],
  ["Starte eine freie Conversation oder arbeite direkt in einem verknüpften Projekt.", "Start a free-form conversation or work directly in a linked project."],
  ["Ohne Projektkontext", "Without project context"],
  ["Projektchat", "Project chat"],
  ["Im verknüpften Workspace", "In linked workspace"],
  ["Projekt auswählen", "Select project"],
  ["Wähle ein mit Anti-Gravity verknüpftes Projekt.", "Select a project linked with Anti-Gravity."],
  ["Es ist noch kein Projekt mit Anti-Gravity verknüpft.", "No project is linked with Anti-Gravity yet."],
  ["Modell", "Model"],
  ["Modelle werden geladen …", "Loading models …"],
  ["Standardmodell verwenden", "Use default model"],
  ["Die Modellliste konnte nicht geladen werden. Der Chat kann mit dem Standardmodell starten.", "Model list could not be loaded. The chat can start with the default model."],
  ["Codex und Custom API laufen lokal im Hub; Anti-Gravity-Modelle nutzen ein App-Fenster.", "Codex and Custom API run locally in the Hub; Anti-Gravity models use an app window."],
  ["Erste Nachricht", "First message"],
  ["Womit soll Anti-Gravity beginnen?", "What should Anti-Gravity start with?"],
  ["Chat wird gestartet", "Starting chat"],
  ["Projekt, Modell und erste Antwort werden geprüft.", "Checking project, model, and initial response."],
  ["Chat starten", "Start chat"],
  ["Keine löschbaren Chats", "No deletable chats"],
  ["Alle ausgewählten Chats arbeiten gerade und bleiben geschützt.", "All selected chats are currently working and remain protected."],
  ["Die ausgewählten Chats arbeiten gerade und können nicht gesammelt gelöscht werden.", "The selected chats are currently working and cannot be bulk-deleted."],
  ["Ausgewählte Chats", "Selected chats"],
  ["1 laufender Chat bleibt geschützt und wird nicht gelöscht.", "1 running chat remains protected and will not be deleted."],

  // --- Scheduled Tasks Page & Components ---
  ["Native Anti-Gravity-Zeitpläne werden geladen.", "Loading native Anti-Gravity schedules."],
  ["Anti-Gravity Scheduled Tasks nicht bereit", "Anti-Gravity Scheduled Tasks not ready"],
  ["Native Anti-Gravity-Zeitpläne zentral erstellen, überwachen und pausieren.", "Centrally create, monitor, and pause native Anti-Gravity schedules."],
  ["Tasks aktualisieren", "Refresh tasks"],
  ["Neuer Task", "New Task"],
  ["Tasks durchsuchen", "Search tasks"],
  ["Taskfilter", "Task filter"],
  ["Projektliste momentan nicht verfügbar. Bestehende Tasks bleiben sichtbar.", "Project list currently unavailable. Existing tasks remain visible."],
  ["Keine passenden Tasks", "No matching tasks"],
  ["Noch keine Scheduled Tasks", "No Scheduled Tasks yet"],
  ["Passe Suche oder Filter an.", "Adjust search or filter."],
  ["Erstelle den ersten nativen Anti-Gravity-Zeitplan.", "Create your first native Anti-Gravity schedule."],
  ["Ersten Task erstellen", "Create first task"],
  ["Globaler Task", "Global task"],
  ["Projektbezogen", "Project-scoped"],
  ["Kein Projekt", "No project"],
  ["Nach Cron-Zeitplan", "Per Cron schedule"],
  ["Scheduled Task bearbeiten", "Edit Scheduled Task"],
  ["Neuer Scheduled Task", "New Scheduled Task"],
  ["Name, Zeitplan, Projekt und Prompt vollständig im Hub steuern.", "Control name, schedule, project, and prompt completely inside the Hub."],
  ["Name", "Name"],
  ["Zum Beispiel: Täglicher Projektcheck", "For example: Daily project check"],
  ["Die stabile ID wird aus dem Namen erzeugt.", "The stable ID is generated from the name."],
  ["Häufigkeit", "Frequency"],
  ["Täglich", "Daily"],
  ["Wöchentlich", "Weekly"],
  ["Benutzerdefiniert (Cron)", "Custom (Cron)"],
  ["Cron-Ausdruck", "Cron expression"],
  ["Uhrzeit", "Time"],
  ["Wochentag", "Weekday"],
  ["Montag", "Monday"],
  ["Dienstag", "Tuesday"],
  ["Mittwoch", "Wednesday"],
  ["Donnerstag", "Thursday"],
  ["Freitag", "Friday"],
  ["Samstag", "Saturday"],
  ["Sonntag", "Sunday"],
  ["Für alle Projekte", "For all projects"],
  ["Nach dem Speichern aktiv", "Active after saving"],
  ["Was soll der Agent zum geplanten Zeitpunkt tun?", "What should the agent do at the scheduled time?"],
  ["Task speichern", "Save task"],
  ["Zeit unbekannt", "Time unknown"],
  ["Übersicht", "Overview"],
  ["Zeitplan", "Schedule"],
  ["Nächster Lauf", "Next run"],
  ["Stabile ID", "Stable ID"],
  ["Letzter Fehler", "Last error"],
  ["Events werden geladen …", "Loading events …"],
  ["Für diesen Task sind noch keine Events vorhanden.", "No events recorded for this task yet."],
  ["Scheduler neu starten", "Restart scheduler"],
  ["Systemtask", "System task"],

  // --- More Page ---
  ["Weitere Bereiche", "More Sections"],
  ["Mehr", "More"],
  ["Seltenere Funktionen bleiben erreichbar, ohne die Hauptnavigation zu überladen.", "Less frequent tools remain accessible without crowding the main navigation."],
  ["API-Logs & Anti-Ban-Schilde", "API Logs & Anti-Ban Shields"],
  ["Hilfe & Dokumentation", "Help & Documentation"],
  ["Systemstatus & Diagnose", "System Status & Diagnostics"],
  ["Einstellungen", "Settings"],
  ["Wissen & Lessons Learned", "Knowledge & Lessons Learned"],

  // --- Help Page ---
  ["Anti-Ban & Hermes/OpenClaw Architektur", "Anti-Ban & Hermes/OpenClaw Architecture"],
  ["Operator-Handbuch", "Operator Manual"],
  ["API-Referenz", "API Reference"],
  ["Datenbank", "Database"],
  ["Konfiguration", "Configuration"],
  ["Betrieb", "Operations"],
  ["Wissenskette", "Knowledge Chain"],
  ["Planänderungen", "Plan Amendments"],
  ["Generierte HTTP-Routen", "Generated HTTP Routes"],
  ["Generiertes SQLite-Schema", "Generated SQLite Schema"],
  ["Python-Importgraph", "Python Import Graph"],
  ["Frontend-Importgraph", "Frontend Import Graph"],
  ["Anti-Gravity sicher steuern", "Operate Anti-Gravity safely"],
  ["Handbuch, API, Datenbank, Codebase und generierte Referenzen an einem Ort.", "Manual, API, database, codebase, and generated references in one place."],
  ["Rohfassung öffnen", "Open raw document"],
  ["1. Studio", "1. Studio"],
  ["Projektzustand und nächste Schritte prüfen.", "Check project health and next steps."],
  ["2. Automation", "2. Automation"],
  ["Plan, Änderungen, Tests und Evidence vor Freigaben kontrollieren.", "Inspect plan, changes, tests, and evidence before approvals."],
  ["3. Projekt", "3. Project"],
  ["Runtime starten, Vorschau prüfen und erst danach mergen oder deployen.", "Start runtime, verify preview, and only then merge or deploy."],
  ["Dokument", "Document"],
  ["Dokumentation aktualisieren", "Refresh documentation"],
  ["Dokumentation nicht verfügbar", "Documentation unavailable"],

  // --- System Status Page & Backend Overview Strings ---
  ["Dienste, Datenbank und Deployment werden geprüft.", "Checking services, database, and deployment."],
  ["System & Stack", "System & Stack"],
  ["Dienste, Datenbank, Laufzeit und Container-Kapselung auf einen Blick – ohne Secrets oder gespeicherte Inhalte offenzulegen.", "Services, database, runtime, and container isolation at a glance — without exposing secrets or stored row contents."],
  ["Gesamtzustand", "Overall health"],
  ["Betriebsbereit", "Operational"],
  ["Aufmerksamkeit nötig", "Attention required"],
  ["Laufender Stack", "Running Stack"],
  ["Fünf Kerndienste", "Five Core Services"],
  ["Live-Prüfung alle 30 Sekunden", "Live check every 30 seconds"],
  ["React-Oberfläche und API-Gateway", "React UI and API gateway"],
  ["Agenten- und Modellzugriff", "Agent and model access"],
  ["Sitzungen und Routing", "Sessions and routing"],
  ["Recovery und Selbstheilung", "Recovery and self-healing"],
  ["Health, Uptime und Alerts", "Health, uptime, and alerts"],
  ["Latenz", "Latency"],
  ["Persistenz", "Persistence"],
  ["Integrität OK", "Integrity OK"],
  ["Größe", "Size"],
  ["Tabellen", "Tables"],
  ["Wichtige Datenbankzähler", "Key database counters"],
  ["Projekte", "Projects"],
  ["Agentenläufe", "Agent runs"],
  ["PR-Kandidaten", "PR candidates"],
  ["Agentenaufgaben", "Agent tasks"],
  ["Human-Gates", "Human gates"],
  ["Review-Befunde", "Review findings"],
  ["Audit-Ereignisse", "Audit events"],
  ["Nur Metadaten und freigegebene Zähler – keine Zeileninhalte.", "Metadata and allowlisted counters only — no row contents."],
  ["Architektur", "Architecture"],
  ["So fließt die Arbeit", "How work flows"],
  ["Aktuell nativ · optional als ein Docker-Stack betreibbar", "Currently running natively · optionally deployable as a single Docker stack"],
  ["Anti-Gravity Stackfluss", "Anti-Gravity stack flow"],
  ["Bedienung", "Interface"],
  ["API & Routing", "API & Routing"],
  ["Planung & Ausführung", "Planning & Execution"],
  ["Audit & Zustand", "Audit & State"],
  ["PR, CI & Review", "PR, CI & Review"],
  ["Laufzeit und Deployment", "Runtime and deployment"],
  ["Laufzeit", "Runtime"],
  ["Lokale Engine", "Local Engine"],
  ["Hub-Version", "Hub version"],
  ["Installationsmodus", "Installation mode"],
  ["Plattform", "Platform"],
  ["Monitoring-Historie", "Monitoring retention"],
  ["API-Inhalte im Log", "API content logging"],
  ["Opt-in aktiv", "Opt-in active"],
  ["Aus · nur Metadaten", "Off · metadata only"],
  ["Nicht verbunden", "Not connected"],
  ["Optional / offline", "Optional / offline"],
  ["Optionales Deployment", "Optional Deployment"],
  ["Docker-Profil & Persistenz", "Docker Profile & Persistence"],
  ["Multi-Stage Dockerfile", "Multi-stage Dockerfile"],
  ["React-Build und schlankes Python-Runtime-Image", "React build and slim Python runtime image"],
  ["Non-Root Container", "Non-root container"],
  ["Runtime läuft ohne Root-Rechte", "Runtime executes without root privileges"],
  ["Reduzierte Containerrechte", "Reduced container privileges"],
  ["Keine Linux-Capabilities und kein Zugriff auf Host-PIDs", "Dropped Linux capabilities and no host PID access"],
  ["Container-Healthcheck", "Container healthcheck"],
  ["Alle fünf Kerndienste werden geprüft", "All five core services are health-checked"],
  ["Abhängigkeiten gelockt", "Locked dependencies"],
  ["Python- und Node-Versionen reproduzierbar", "Reproducible Python and Node dependency versions"],
  ["Externe Konfiguration", "External configuration"],
  ["Secrets bleiben außerhalb des Images", "Secrets remain outside the container image"],
  ["Persistente Datenbank", "Persistent database"],
  ["SQLite-Daten liegen in einem benannten Volume", "SQLite data stored in a named volume"],
  ["Persistente Logs", "Persistent logs"],
  ["Diagnose- und Auditlogs überleben Neustarts", "Diagnostic and audit logs survive restarts"],
  ["Persistente Projekte", "Persistent projects"],
  ["Geklonte Repositories überleben Containerwechsel", "Cloned repositories survive container replacements"],
  ["Container-Laufzeit erkannt und verifiziert.", "Container runtime detected and verified."],
  ["Docker-Dateien geprüft; ein echter Containerlauf ist auf diesem Host noch nicht verifiziert.", "Docker manifests verified; an active container runtime has not been verified on this host yet."],
  ["Letzte vollständige Prüfung:", "Last full check:"],

  // --- Settings Page, Codex & Custom Models ---
  ["Integrationen und Modelle werden geladen.", "Loading integrations and models."],
  ["Einstellungen konnten nicht geladen werden.", "Settings could not be loaded."],
  ["Integrationen & Laufzeit", "Integrations & Runtime"],
  ["Seltene Konfigurationen bleiben zentral; projektbezogene Ports und Startbefehle stehen direkt im jeweiligen Projekt.", "Global configurations stay centralized; project-specific ports and start commands live directly inside each project."],
  ["Nicht verbunden oder Zugangsdaten ungültig", "Not connected or invalid credentials"],
  ["Verbunden", "Connected"],
  ["Projektbasis", "Projects base directory"],
  ["Nicht konfiguriert", "Not configured"],
  ["Hub-Konfiguration", "Hub configuration"],
  ["Außerhalb des Repositories unter", "Stored outside the repository under"],
  ["Custom API nicht verfügbar", "Custom API unavailable"],
  ["Mit deinem Codex-/ChatGPT-Konto anmelden. Anti-Gravity erhält keine Tokens.", "Sign in with your Codex / ChatGPT account. Anti-Gravity receives no tokens."],
  ["Nicht angemeldet", "Not signed in"],
  ["Nicht installiert", "Not installed"],
  ["Codex ist einsatzbereit", "Codex is ready"],
  ["Codex lokal verbinden", "Connect Codex locally"],
  ["Die Anmeldung öffnet die offizielle Codex-Seite.", "Signing in opens the official Codex page."],
  ["Die lokale Codex-App wurde nicht gefunden.", "Local Codex app was not found."],
  ["Modelle laden", "Load models"],
  ["Codex abmelden", "Sign out of Codex"],
  ["Codex abmelden?", "Sign out of Codex?"],
  ["Die lokale Codex-Sitzung wird beendet. Gespeicherte Chatverläufe im Hub bleiben erhalten.", "The local Codex session will be terminated. Saved chat histories in the Hub are preserved."],
  ["Anmeldung öffnen", "Open sign-in"],
  ["Codex-Anmeldung abbrechen", "Cancel Codex sign-in"],
  ["Mit Codex anmelden", "Sign in with Codex"],
  ["Schließe die Anmeldung im geöffneten Fenster ab. Diese Seite erkennt den Erfolg automatisch.", "Complete sign-in in the opened window. This page detects completion automatically."],
  ["Modelle", "Models"],
  ["OpenAI-kompatible Provider. Schlüssel bleiben verschlüsselt auf diesem Windows-PC.", "OpenAI-compatible providers. Keys remain encrypted on this Windows PC."],
  ["Modell hinzufügen", "Add model"],
  ["Key geschützt", "Key protected"],
  ["Ohne Key", "No key"],
  ["Custom Model löschen?", "Delete Custom Model?"],
  ["Noch kein eigener Provider. Anti-Gravity-Modelle bleiben unabhängig davon verfügbar.", "No custom provider configured yet. Anti-Gravity models remain available independently."],
  ["Modell sicher gespeichert.", "Model saved securely."],
  ["Modell bearbeiten", "Edit model"],
  ["Eigenes Modell hinzufügen", "Add custom model"],
  ["Die Base URL muss absolut sein; eingebettete Zugangsdaten werden abgelehnt.", "The Base URL must be absolute; embedded credentials are rejected."],
  ["Anzeigename", "Display name"],
  ["Modell-ID", "Model ID"],
  ["(leer = beibehalten)", "(empty = keep existing)"],
  ["Timeout (Sekunden)", "Timeout (seconds)"],
  ["Temperatur", "Temperature"],
  ["TLS-Zertifikat prüfen", "Verify TLS certificate"],
  ["Zusätzliche Header (JSON)", "Extra headers (JSON)"],
  ["Gespeicherte Werte erscheinen als null. null behält den Wert; entferne den Schlüssel zum Löschen.", "Stored values appear as null. null preserves the existing value; remove the key to delete it."],
  ["System-Prompt (optional)", "System prompt (optional)"],

  // --- Knowledge Page & Knowledge Chain ---
  ["Wissen", "Knowledge"],
  ["Wissenskette & Erfahrungen", "Knowledge Chain & Lessons"],
  ["Von der ursprünglichen Idee über Entscheidungen und PRs bis zu Prüfnachweisen und aufgezeichneten Auslieferungen.", "From the initial idea through decisions and PRs to verification evidence and recorded deployments."],
  ["Projekt für Wissen", "Project for knowledge"],
  ["Wissensansicht", "Knowledge view"],
  ["Erfahrungen", "Lessons Learned"],
  ["Wissensketten durchsuchen", "Search knowledge chains"],
  ["Idee, Artefakt, Campaign oder PR suchen", "Search idea, artifact, campaign, or PR"],
  ["Wissensketten werden geladen.", "Loading knowledge chains."],
  ["Wissenskette nicht verfügbar", "Knowledge chain unavailable"],
  ["Lessons durchsuchen", "Search lessons"],
  ["Technik, Lösung oder Projekt suchen", "Search technique, solution, or project"],
  ["Erfahrungen werden geladen.", "Loading lessons learned."],
  ["Erfahrungen nicht verfügbar", "Lessons learned unavailable"],
  ["Projektübergreifend", "Cross-project"],
  ["Passe Suche oder Projektfilter an.", "Adjust search or project filter."],
  ["Abgeschlossene Arbeiten können hier künftig wiederverwendbares Wissen hinterlassen.", "Completed work items can leave reusable knowledge here in the future."],
  ["Keine passenden Erfahrungen", "No matching lessons"],
  ["Noch keine Erfahrungen", "No lessons yet"],
  ["Vorhanden", "Present"],
  ["Fehlt", "Missing"],
  ["Nicht erforderlich", "Not required"],
  ["Unklar", "Unclear"],
  ["Nicht aufgezeichnet", "Not recorded"],
  ["Ungültiger Zeitwert", "Invalid timestamp"],
  ["Details anzeigen", "Show details"],
  ["Details ausblenden", "Hide details"],
  ["Interner Typ", "Internal type"],
  ["Interner Status", "Internal status"],
  ["Datei", "File"],
  ["Materialisierter SHA-256", "Materialized SHA-256"],
  ["Materialisiert", "Materialized"],
  ["Noch kein verknüpftes Artefakt aufgezeichnet.", "No linked artifact recorded yet."],
  ["Interne Umgebung", "Internal environment"],
  ["Vorheriger stabiler SHA", "Previous stable SHA"],
  ["Rollback von", "Rollback of"],
  ["Gestartet", "Started"],
  ["Beendet", "Finished"],
  ["Geplanter PR", "Planned PR"],
  ["Technische Referenz", "Technical reference"],
  ["GitHub-Aufgabe", "GitHub Issue"],
  ["Noch keine GitHub-Aufgabe aufgezeichnet.", "No GitHub issue recorded yet."],
  ["Noch kein Pull Request aufgezeichnet.", "No Pull Request recorded yet."],
  ["Aktuell", "Current"],
  ["Gemergt", "Merged"],
  ["Prüfnachweise", "Verification evidence"],
  ["Noch keine Prüfnachweise aufgezeichnet.", "No verification evidence recorded yet."],
  ["Auslieferung", "Deployment"],
  ["Vom Control Center aufgezeichneter Zustand – kein Nachweis einer externen Auslieferung.", "State recorded by Control Center — not proof of an external live deployment."],
  ["Noch keine Auslieferung aufgezeichnet.", "No deployment recorded yet."],
  ["Abdeckung der Wissenskette", "Knowledge chain coverage"],
  ["Ideen-Dokumente", "Idea documents"],
  ["Verknüpfte Artefakte", "Linked artifacts"],
  ["Lose Artefakte", "Unlinked artifacts"],
  ["Verknüpfte PR-Slices", "Linked PR slices"],
  ["Lose PR-Slices", "Unlinked PR slices"],
  ["Ursprüngliche Idee", "Original idea"],
  ["Keine Herkunftsidee verknüpft.", "No origin idea linked."],
  ["Design & Entscheidungen", "Design & Decisions"],
  ["Technische Planreferenz", "Technical plan reference"],
  ["Noch kein Umsetzungsplan aufgezeichnet.", "No implementation plan recorded yet."],
  ["Geplante PRs", "Planned PRs"],
  ["Noch keine geplanten PRs verknüpft.", "No planned PRs linked yet."],
  ["Diese Einträge sind gespeichert, gehören aber noch nicht zu einer vollständigen Wissenskette.", "These items are saved but do not belong to a complete knowledge chain yet."],
  ["Ursprüngliche Ideen", "Original ideas"],
  ["Dokumente", "Documents"],
  ["Mit einem Umsetzungsplan verknüpft", "Linked to an implementation plan"],
  ["Nicht mit einem Umsetzungsplan verknüpft", "Not linked to an implementation plan"],
  ["Keine passende Wissenskette", "No matching knowledge chain"],
  ["Noch keine Wissenskette", "No knowledge chain yet"],
  ["Passe den Suchbegriff an.", "Adjust your search query."],
  ["Sobald Ideen, Artefakte und PR-Slices verbunden sind, erscheint hier ihre nachvollziehbare Kette.", "Once ideas, artifacts, and PR slices are connected, their traceable chain will appear here."],

  // --- Project Onboarding & Project Overview Pages ---
  ["Projekt einrichten", "Set up project"],
  ["Das Repository ist im Hub registriert. Jetzt folgt nur noch die optionale Anti-Gravity-Verknüpfung.", "The repository is registered in the Hub. Now only the optional Anti-Gravity link remains."],
  ["1 Schritt offen", "1 step remaining"],
  ["Einrichtungsfortschritt", "Setup progress"],
  ["Lokal bereit", "Local ready"],
  ["Repository und lokaler Projektordner sind bereit.", "Repository and local project folder are ready."],
  ["Du kannst diesen Schritt überspringen und später in der Projektübersicht nachholen.", "You can skip this step and complete it later in the project overview."],
  ["Projekt, Repository und Anti-Gravity-Arbeitsbereich gehören jetzt zusammen.", "Project, repository, and Anti-Gravity workspace are now linked together."],
  ["Projekt öffnen", "Open project"],
  ["Zurück zum Studio", "Back to Studio"],
  ["Woran möchtest du arbeiten?", "What would you like to work on?"],
  ["Der Hub legt Repository, lokalen Ordner und Anti-Gravity-Verknüpfung in einer nachvollziehbaren Reihenfolge an.", "The Hub sets up your repository, local folder, and Anti-Gravity link in a clear step-by-step sequence."],
  ["Bestehendes Repository", "Existing repository"],
  ["Ein eigenes GitHub-Repository auswählen und lokal klonen.", "Select one of your GitHub repositories and clone it locally."],
  ["Neues Projekt", "New project"],
  ["Repository und lokalen Projektordner gemeinsam neu anlegen.", "Create a new repository and local project folder together."],
  ["Repository auswählen", "Select repository"],
  ["Es werden nur Repositories deines verbundenen GitHub-Kontos angezeigt.", "Only repositories from your connected GitHub account are shown."],
  ["GitHub-Repositories werden geladen.", "Loading GitHub repositories."],
  ["GitHub-Repositories nicht verfügbar", "GitHub repositories unavailable"],
  ["Repositories durchsuchen", "Search repositories"],
  ["Repository durchsuchen", "Search repository"],
  ["Keine Beschreibung", "No description"],
  ["Im Hub", "In Hub"],
  ["Privat", "Private"],
  ["Öffentlich", "Public"],
  ["Kein passendes Repository gefunden.", "No matching repository found."],
  ["Standardmäßig wird ein privates GitHub-Repository erstellt.", "A private GitHub repository is created by default."],
  ["Projektname", "Project name"],
  ["Zum Beispiel: Katzen-Finder", "For example: Cat-Finder"],
  ["Sichtbarkeit", "Visibility"],
  ["Lokaler Projektordner", "Local project folder"],
  ["Vorgeschlagen aus deiner zentralen Hub-Konfiguration.", "Suggested from your central Hub configuration."],
  ["Leer lassen, um den konfigurierten Projektstamm zu verwenden.", "Leave empty to use the configured projects base directory."],
  ["Windows-Pfad", "Windows path"],
  ["(optional)", "(optional)"],
  ["Wird automatisch festgelegt", "Assigned automatically"],
  ["Erweiterte Einstellungen", "Advanced settings"],
  ["Testbefehl", "Test command"],
  ["Beim Import wird das Repository in den gewählten Ordner geklont.", "Importing clones the repository into the selected folder."],
  ["Repository und lokaler Ordner werden atomar vorbereitet.", "Repository and local folder are prepared atomically."],
  ["Repository importieren", "Import repository"],
  ["Projekt erstellen", "Create project"],
  ["In Anti-Gravity erstellen", "Create in Anti-Gravity"],
  ["Der lokale Repository-Ordner wird automatisch verwendet. Du musst keinen Workspace-Pfad erneut eingeben.", "The local repository folder is used automatically. You do not need to re-enter a workspace path."],
  ["Projekt anlegen", "Create project"],
  ["Vorhandenes Projekt verknüpfen", "Link existing project"],
  ["Wähle ein Projekt direkt aus der laufenden Anti-Gravity-App.", "Select a project directly from the running Anti-Gravity app."],
  ["Projekte werden geladen …", "Loading projects …"],
  ["Anti-Gravity ist gerade nicht erreichbar. Das Hub-Projekt bleibt sicher gespeichert.", "Anti-Gravity is currently unreachable. The Hub project remains safely stored."],
  ["Anti-Gravity-Projekt", "Anti-Gravity project"],
  ["Anti-Gravity-Projekt auswählen", "Select Anti-Gravity project"],
  ["Projektübersicht wird aufgebaut.", "Building project overview."],
  ["Projekt nicht gefunden", "Project not found"],
  ["Neu verknüpfen", "Relink"],
  ["Verknüpfung offen", "Link pending"],
  ["Verbindung nicht prüfbar", "Connection unverifiable"],
  ["Bestätigung beim ersten Chat", "Confirmed on first chat"],
  ["Lokales Projekt · Pfad geschützt", "Local project · Path protected"],
  ["Projekt aktualisieren", "Refresh project"],
  ["Verknüpfung", "Link"],
  ["Verbindung reparieren", "Repair connection"],
  ["Mit Anti-Gravity verbinden", "Connect with Anti-Gravity"],
  ["Mit Anti-Gravity verknüpfen", "Link with Anti-Gravity"],
  ["Projektkontext für Chats und Agenten herstellen.", "Establish project context for chats and agents."],
  ["Frontend starten", "Start frontend"],
  ["Projekt ist bereit", "Project is ready"],
  ["Keine unmittelbare Blockade. Neue Arbeit kann geplant werden.", "No immediate blockers. New work can be planned."],
  ["Für Projekt-Chats und Agentensteuerung", "For project chats and agent control"],
  ["Das gespeicherte Anti-Gravity-Projekt ist in der laufenden App nicht mehr vorhanden. Lege es aus diesem Repository neu an oder wähle das richtige vorhandene Projekt.", "The saved Anti-Gravity project no longer exists in the running app. Recreate it from this repository or select the matching existing project."],
  ["Projektstatus", "Project status"],
  ["Offene PRs", "Open PRs"],
  ["Tests offen", "Open tests"],
  ["Aktive Agenten", "Active agents"],
  ["Blockaden", "Blockers"],
  ["Projekt-Runtime wird erkannt.", "Detecting project runtime."],
  ["Projekt-Runtime nicht verfügbar", "Project runtime unavailable"],
  ["Die sicheren Stack-Metadaten konnten momentan nicht geladen werden.", "Safe stack metadata could not be loaded right now."],
  ["Arbeit", "Work"],
  ["Pull Requests & Work Items", "Pull Requests & Work Items"],
  ["Automation öffnen", "Open Automation"],
  ["Für dieses Projekt gibt es aktuell keine geplanten oder laufenden PR-Slices.", "There are currently no planned or active PR slices for this project."],
  ["Keine Work Items", "No Work Items"],
  ["Kommunikation", "Communication"],
  ["Alle Chats", "All chats"],
  ["Agent arbeitet", "Agent working"],
  ["Keine projektbezogenen Chats.", "No project-scoped chats."],
  ["Zeitpläne", "Schedules"],
  ["Keine Tasks für dieses Projekt.", "No tasks for this project."],
  ["Verlauf", "History"],
  ["Letzte Aktivität", "Recent activity"],
  ["Keine Aktivität protokolliert.", "No activity logged."],
  ["Projekt- und Runtime-Einstellungen", "Project and runtime settings"],
  ["Startbefehle, Verknüpfung und Hub-Registrierung", "Start commands, linking, and Hub registration"],
  ["Projektverwaltung", "Project management"],
  ["Diese Aktionen löschen weder das GitHub-Repository noch Dateien im lokalen Projektordner.", "These actions do not delete the GitHub repository or files in the local project folder."],
  ["Verknüpfung lösen", "Unlink"],
  ["Anti-Gravity-Verknüpfung lösen?", "Unlink Anti-Gravity project?"],
  ["Projekt-Chats und Automationen verlieren ihre Zuordnung. Das Projekt kann anschließend erneut verknüpft werden.", "Project chats and automations will lose their association. The project can be linked again afterwards."],
  ["Aus Hub entfernen", "Remove from Hub"],
  ["GitHub löschen & entfernen", "Delete GitHub & remove"],
  ["Projekt aus Anti-Gravity entfernen?", "Remove project from Anti-Gravity?"],
  ["Abhängigkeiten werden geprüft …", "Checking dependencies …"],
  ["Das wird geordnet abgeschlossen", "These items will be cleanly closed"],
  ["Keine abhängigen Einträge.", "No dependent entries."],
  ["GitHub-Repository ebenfalls löschen", "Also delete GitHub repository"],
  ["GitHub-Repository bestätigen", "Confirm GitHub repository"],
  ["Nicht gelöscht: lokaler Ordner, lokales Git-Repository und Hub-Historie.", "Not deleted: local folder, local Git repository, and Hub history."],
  ["Aufgaben", "Issues"],
  ["Agent-Läufe", "Agent runs"],
  ["Teilschritte", "Subtasks"],
  ["Kampagnen", "Campaigns"],
  ["Pull-Request-Pläne", "Pull request plans"],
  ["Arbeitsaufträge", "Work orders"],
  ["Automationsaufgaben", "Automation tasks"],
  ["Planungsläufe", "Planning jobs"],
  ["Hinweise", "Notices"],
  ["Lokale Chats", "Local chats"],

  // --- Runtime Cockpit, Stack Panel & Runtime Settings ---
  ["Einrichtung läuft", "Setup running"],
  ["Wird aktualisiert", "Updating"],
  ["Startet", "Starting"],
  ["Extern aktiv", "Externally active"],
  ["Gestoppt", "Stopped"],
  ["Einrichtung erforderlich", "Setup required"],
  ["Adresse", "Address"],
  ["Arbeitsordner", "Working directory"],
  ["Prozess", "Process"],
  ["Externer Prozess", "External process"],
  ["Nicht gestartet", "Not started"],
  ["Abhängigkeiten einrichten", "Set up dependencies"],
  ["Letzte Logs", "Recent logs"],
  ["Lokale Umgebung", "Local environment"],
  ["Frontend & Backend", "Frontend & Backend"],
  ["Konfiguriert", "Configured"],
  ["Automatisch erkannt", "Auto-detected"],
  ["Frontend-Vorschau", "Frontend preview"],
  ["Starte das Frontend, um die Vorschau hier zu sehen.", "Start the frontend to see the live preview here."],
  ["Im Browser öffnen", "Open in browser"],
  ["Frontend noch nicht gestartet", "Frontend not started yet"],
  ["Automatisch erfasste Projektvorschau", "Automatically captured project preview"],
  ["Falls ein Framework Einbettung blockiert, nutze „Im Browser öffnen“ oder den serverseitigen Screenshot.", "If a framework blocks iframe embedding, use “Open in browser” or the server-side screenshot."],
  ["Runtime aktiviert", "Runtime enabled"],
  ["Startbefehl", "Start command"],
  ["Arbeitsordner im Projekt", "Working directory in project"],
  ["Health-/Preview-Pfad", "Health / preview path"],
  ["Gespeicherte Runtime-Konfiguration", "Saved runtime configuration"],
  ["Automatisch erkannter Vorschlag", "Auto-detected suggestion"],
  ["Konfiguration speichern", "Save configuration"],
  ["Erkannt", "Detected"],
  ["Ungültig", "Invalid"],
  ["Übersprungen", "Skipped"],
  ["In Ordnung", "OK"],
  ["Begrenzt geprüft", "Partially checked"],
  ["Nicht verfügbar", "Unavailable"],
  ["Nicht vorhanden", "Absent"],
  ["Nicht ermittelt", "Not determined"],
  ["Status unbekannt", "Status unknown"],
  ["Die Datei konnte nicht sicher ausgewertet werden.", "The file could not be safely parsed."],
  ["Die Datei überschreitet das sichere Scan-Limit.", "The file exceeds the safe scan size limit."],
  ["Pfad ausgeblendet", "Path hidden"],
  ["Unbekannte Technologie", "Unknown technology"],
  ["Technologie", "Technology"],
  ["Erkannt durch", "Detected via"],
  ["Abhängigkeiten", "Dependencies"],
  ["Unbenannter Service", "Unnamed service"],
  ["Ohne Healthcheck", "No healthcheck"],
  ["Ausgeblendet", "Hidden"],
  ["Build aus Projekt", "Build from project"],
  ["Externer Kontext ausgeblendet", "External context hidden"],
  ["Projektwurzel", "Project root"],
  ["Externe Quelle ausgeblendet", "External source hidden"],
  ["Anonymes Volume", "Anonymous volume"],
  ["Keine Services erkannt.", "No services detected."],
  ["Benannte Volumes", "Named volumes"],
  ["Netzwerke", "Networks"],
  ["Tabellen gesamt", "total tables"],
  ["angezeigt", "shown"],
  ["Datenbanktabellen und begrenzte Zählwerte", "Database tables and bounded row counts"],
  ["Tabelle", "Table"],
  ["Einträge", "Rows"],
  ["Unbenannte Tabelle", "Unnamed table"],
  ["Keine Tabellennamen verfügbar.", "No table names available."],
  ["Die Tabellenliste wurde am sicheren Anzeigelimit gekürzt.", "The table list was truncated at the safe display limit."],
  ["Projekt-Inventar", "Project Inventory"],
  ["Technik & Daten", "Tech Stack & Data"],
  ["Nur lesend geprüft", "Read-only scan"],
  ["Scanstatus unbekannt", "Scan status unknown"],
  ["Technologien, Container und Datenbank-Metadaten werden sicher eingelesen.", "Safely scanning technologies, containers, and database metadata."],
  ["Projekt-Stack wird geprüft", "Scanning project stack"],
  ["Projekt-Stack nicht verfügbar", "Project stack unavailable"],
  ["Im sicheren Scan wurden keine unterstützten Manifeste, Container oder Datenbanken erkannt.", "No supported manifests, containers, or databases were found in the safe scan."],
  ["Noch keine Stack-Daten erkannt", "No stack data detected yet"],
  ["Stack-Zusammenfassung", "Stack summary"],
  ["Technologien", "Technologies"],
  ["Manifeste", "Manifests"],
  ["Compose-Services", "Compose services"],
  ["Datenbanken", "Databases"],
  ["Datenschutz und Scan-Grenzen", "Privacy and scan boundaries"],
  ["Struktur sichtbar, Inhalte geschützt", "Structure visible, contents protected"],
  ["Anti-Gravity zeigt hier keine Secrets, `.env`-Werte, Tabellenzeilen, SQL oder absoluten Pfade. Datenbank-Zählwerte sind begrenzt und ausschließlich lesend ermittelt.", "Anti-Gravity never exposes secrets, `.env` values, table rows, SQL, or absolute paths here. Database counts are bounded and read-only."],
  ["Erkannte Technologien", "Detected technologies"],
  ["Datenbank-Treiber", "Database drivers"],
  ["Manifeste & Abhängigkeiten", "Manifests & Dependencies"],
  ["Basis-Images", "Base images"],
  ["Exponierte Ports", "Exposed ports"],
  ["Datenbank-Metadaten", "Database metadata"],
  ["Prozesse", "Processes"],
  ["Unbenannter Prozess", "Unnamed process"],
  ["Topologie", "Topology"],
  ["Komponente", "Component"],
  ["Knoten", "Node"],
  ["Dateianzahl nicht gemeldet", "File count not reported"],
  ["Der Scan wurde an einem Sicherheitslimit gekürzt.", "The scan was truncated at a safety limit."],
  ["Scan innerhalb der konfigurierten Sicherheitslimits.", "Scan completed within configured safety limits."],

  // --- Studio & Automation Pages ---
  ["Studio-Daten werden aus den bestehenden Hub-APIs geladen.", "Loading Studio data from Hub APIs."],
  ["Projekte und laufende Arbeit auf einen Blick.", "Projects and active work at a glance."],
  ["Projekt hinzufügen", "Add project"],
  ["Arbeitsbereiche", "Workspaces"],
  ["Importiere ein bestehendes GitHub-Repository oder erstelle Projekt, Repository und lokalen Ordner gemeinsam.", "Import an existing GitHub repository or create a project, repository, and local folder together."],
  ["Noch keine Projekte", "No projects yet"],
  ["Mit Anti-Gravity verknüpft", "Linked with Anti-Gravity"],
  ["Noch nicht mit Anti-Gravity verknüpft", "Not linked with Anti-Gravity yet"],
  ["Laufende Arbeit", "Active Work"],
  ["Aktive Aufgaben", "Active Tasks"],
  ["Zurzeit ist kein Work Item aktiv.", "No work item is currently active."],
  ["Aufgabe in Automation öffnen", "Open task in Automation"],
  ["Vorbereitung", "Preparing"],
  ["Tests laufen", "Running tests"],
  ["Review offen", "Review pending"],
  ["Reparatur", "Repair"],
  ["Eine Entscheidung ist erforderlich.", "A decision is required."],
  ["Entscheidung prüfen", "Review decision"],
  ["In Automation prüfen", "Review in Automation"],
  ["Repository oder lokaler Projektordner benötigt Aufmerksamkeit.", "Repository or local project folder requires attention."],
  ["Ordne das Repository einem Anti-Gravity-Projekt zu, damit Chats und Arbeit zusammengehören.", "Link the repository to an Anti-Gravity project so chats and work belong together."],
  ["Fortschritt, Blockaden und Evidence sind in der Automation gebündelt.", "Progress, blockers, and evidence are bundled in Automation."],
  ["Öffne die Chats, um laufende Antworten und Zustellungen zu verfolgen.", "Open Chats to follow active responses and message delivery."],
  ["Chats öffnen", "Open Chats"],
  ["Erstes Repository hinzufügen", "Add first repository"],
  ["Importiere ein bestehendes GitHub-Repository oder erstelle ein neues Projekt.", "Import an existing GitHub repository or create a new project."],
  ["Conversation fortsetzen", "Continue conversation"],
  ["Es liegt keine dringende Entscheidung oder Blockade vor.", "There are no urgent decisions or blockers."],
  ["Umsetzung und Prüfnachweise werden geladen.", "Loading execution and verification evidence."],
  ["Der aktuelle Stand der Automation konnte nicht geladen werden.", "The current Automation state could not be loaded."],
  ["Automation nicht verfügbar", "Automation unavailable"],
  ["Arbeitssteuerung", "Work Control"],
  ["Beschreibe dein Ziel. Anti-Gravity erstellt einen Plan, setzt freigegebene PRs in Reihenfolge um und legt sie dir zur Prüfung vor.", "Describe your goal. Anti-Gravity creates a plan, executes approved PRs in sequence, and presents them for your review."],
  ["Idee beschreiben", "Describe idea"],
  ["Umsetzung & PRs", "Execution & PRs"],
  ["Umsetzung und PRs filtern", "Filter execution and PRs"],
  ["Umsetzung durchsuchen", "Search execution"],
  ["Sobald ein Plan freigegeben ist, erscheinen seine geplanten PRs hier.", "Once a plan is approved, its planned PRs appear here."],
  ["Beschreibe oben eine Idee. Anti-Gravity untersucht das Projekt und schlägt einen geordneten Plan vor.", "Describe an idea above. Anti-Gravity inspects the project and proposes a structured plan."],
  ["Noch keine PRs in Umsetzung", "No PRs in execution yet"],
  ["Keine PRs passen zu Filter und Suche.", "No PRs match your filter and search."],

  // --- API & Logs Page Attributes ---
  ["Aktive Streams", "Active Streams"],
  ["IP-Adresse für Quellen-Zuordnung", "IP address for source mapping"],
  ["Ziel-Quelle für IP", "Target source for IP"],
  ["Logs durchsuchen", "Search logs"],
  ["Quelle filtern", "Filter by source"],
  ["Status filtern", "Filter by status"],
  ["Modell filtern", "Filter by model"],
  ["Antigravity Web API Dokumentation", "Antigravity Web API Documentation"],
] as const;

interface HubPatternPair {
  deRegex: RegExp;
  enTemplate: string;
  enRegex: RegExp;
  deTemplate: string;
}

const HUB_PATTERN_PAIRS: ReadonlyArray<HubPatternPair> = [
  {
    deRegex: /^IP-Regel (.+) löschen$/,
    enTemplate: "Delete IP rule $1",
    enRegex: /^Delete IP rule (.+)$/,
    deTemplate: "IP-Regel $1 löschen",
  },
  {
    deRegex: /^(\d+) geöffnet · (\d+) aktiv$/,
    enTemplate: "$1 open · $2 active",
    enRegex: /^(\d+) open · (\d+) active$/,
    deTemplate: "$1 geöffnet · $2 aktiv",
  },
  {
    deRegex: /^(\d+) geöffnet$/,
    enTemplate: "$1 open",
    enRegex: /^(\d+) open$/,
    deTemplate: "$1 geöffnet",
  },
  {
    deRegex: /^Maximal (\d+) Chatansichten sind geöffnet\. Schließe zuerst eine Ansicht mit ×\.$/,
    enTemplate: "Maximum of $1 chat panes are open. Close a pane with × first.",
    enRegex: /^Maximum of (\d+) chat panes are open\. Close a pane with × first\.$/,
    deTemplate: "Maximal $1 Chatansichten sind geöffnet. Schließe zuerst eine Ansicht mit ×.",
  },
  {
    deRegex: /^(\d+) Chats$/,
    enTemplate: "$1 chats",
    enRegex: /^(\d+) chats$/,
    deTemplate: "$1 Chats",
  },
  {
    deRegex: /^(\d+) archiviert$/,
    enTemplate: "$1 archived",
    enRegex: /^(\d+) archived$/,
    deTemplate: "$1 archiviert",
  },
  {
    deRegex: /^(\d+) ausgewählt$/,
    enTemplate: "$1 selected",
    enRegex: /^(\d+) selected$/,
    deTemplate: "$1 ausgewählt",
  },
  {
    deRegex: /^(.+) auswählen$/,
    enTemplate: "Select $1",
    enRegex: /^Select (.+)$/,
    deTemplate: "$1 auswählen",
  },
  {
    deRegex: /^(.+) Chatansicht$/,
    enTemplate: "$1 chat pane",
    enRegex: /^(.+) chat pane$/,
    deTemplate: "$1 Chatansicht",
  },
  {
    deRegex: /^Ansicht (.+) schließen$/,
    enTemplate: "Close pane $1",
    enRegex: /^Close pane (.+)$/,
    deTemplate: "Ansicht $1 schließen",
  },
  {
    deRegex: /^vor (\d+) Min\.$/,
    enTemplate: "$1m ago",
    enRegex: /^(\d+)m ago$/,
    deTemplate: "vor $1 Min.",
  },
  {
    deRegex: /^vor (\d+) Std\.$/,
    enTemplate: "$1h ago",
    enRegex: /^(\d+)h ago$/,
    deTemplate: "vor $1 Std.",
  },
  {
    deRegex: /^Enter senden · Shift\+Enter Zeilenumbruch · (\d+)\/5 Bilder$/,
    enTemplate: "Enter to send · Shift+Enter for newline · $1/5 images",
    enRegex: /^Enter to send · Shift\+Enter for newline · (\d+)\/5 images$/,
    deTemplate: "Enter senden · Shift+Enter Zeilenumbruch · $1/5 Bilder",
  },
  {
    deRegex: /^(.+) · Aufnahme läuft$/,
    enTemplate: "$1 · Recording",
    enRegex: /^(.+) · Recording$/,
    deTemplate: "$1 · Aufnahme läuft",
  },
  {
    deRegex: /^(.+) entfernen$/,
    enTemplate: "Remove $1",
    enRegex: /^Remove (.+)$/,
    deTemplate: "$1 entfernen",
  },
  {
    deRegex: /^(\d+) Instanz(en)? · (.+)$/,
    enTemplate: "$1 instance(s) · $3",
    enRegex: /^(\d+) instance\(s\) · (.+)$/,
    deTemplate: "$1 Instanzen · $2",
  },
  {
    deRegex: /^(.+) · Nicht erreichbar$/,
    enTemplate: "$1 · Unreachable",
    enRegex: /^(.+) · Unreachable$/,
    deTemplate: "$1 · Nicht erreichbar",
  },
  {
    deRegex: /^(.+) · Hauptfenster$/,
    enTemplate: "$1 · Main window",
    enRegex: /^(.+) · Main window$/,
    deTemplate: "$1 · Hauptfenster",
  },
  {
    deRegex: /^(.+) · Bereit$/,
    enTemplate: "$1 · Ready",
    enRegex: /^(.+) · Ready$/,
    deTemplate: "$1 · Bereit",
  },
  {
    deRegex: /^(.+) · Wird vorbereitet$/,
    enTemplate: "$1 · Preparing",
    enRegex: /^(.+) · Preparing$/,
    deTemplate: "$1 · Wird vorbereitet",
  },
  {
    deRegex: /^(.+) · Sendet$/,
    enTemplate: "$1 · Sending",
    enRegex: /^(.+) · Sending$/,
    deTemplate: "$1 · Sendet",
  },
  {
    deRegex: /^(.+) · Arbeitet$/,
    enTemplate: "$1 · Working",
    enRegex: /^(.+) · Working$/,
    deTemplate: "$1 · Arbeitet",
  },
  {
    deRegex: /^(.+) · Freigabe nötig$/,
    enTemplate: "$1 · Approval needed",
    enRegex: /^(.+) · Approval needed$/,
    deTemplate: "$1 · Freigabe nötig",
  },
  {
    deRegex: /^(.+) · Fehler$/,
    enTemplate: "$1 · Error",
    enRegex: /^(.+) · Error$/,
    deTemplate: "$1 · Fehler",
  },
  {
    deRegex: /^(\d+) von (\d+) Tasks · (Live|Getrennt)$/,
    enTemplate: "$1 of $2 tasks · $3",
    enRegex: /^(\d+) of (\d+) tasks · (Live|Getrennt|Disconnected)$/,
    deTemplate: "$1 von $2 Tasks · $3",
  },
  {
    deRegex: /^Nächster Lauf: (.+)$/,
    enTemplate: "Next run: $1",
    enRegex: /^Next run: (.+)$/,
    deTemplate: "Nächster Lauf: $1",
  },
  {
    deRegex: /^Täglich · (.+)$/,
    enTemplate: "Daily · $1",
    enRegex: /^Daily · (.+)$/,
    deTemplate: "Täglich · $1",
  },
  {
    deRegex: /^Wöchentlich · (.+)$/,
    enTemplate: "Weekly · $1",
    enRegex: /^Weekly · (.+)$/,
    deTemplate: "Wöchentlich · $1",
  },
  {
    deRegex: /^Stabile ID: (.+) · bleibt beim Umbenennen erhalten$/,
    enTemplate: "Stable ID: $1 · preserved when renaming",
    enRegex: /^Stable ID: (.+) · preserved when renaming$/,
    deTemplate: "Stabile ID: $1 · bleibt beim Umbenennen erhalten",
  },
  {
    deRegex: /^Automatische ID: (.+)$/,
    enTemplate: "Automatic ID: $1",
    enRegex: /^Automatic ID: (.+)$/,
    deTemplate: "Automatische ID: $1",
  },
  {
    deRegex: /^(\d+)\/(\d+) Dienste online · SQLite (konsistent|prüfen) · optionales Docker-Profil (geprüft|prüfen)$/,
    enTemplate: "$1/$2 services online · SQLite $3 · optional Docker profile $4",
    enRegex: /^(\d+)\/(\d+) services online · SQLite (.+) · optional Docker profile (.+)$/,
    deTemplate: "$1/$2 Dienste online · SQLite $3 · optionales Docker-Profil $4",
  },
  {
    deRegex: /^(\d+) Tabellen$/,
    enTemplate: "$1 tables",
    enRegex: /^(\d+) tables$/,
    deTemplate: "$1 Tabellen",
  },
  {
    deRegex: /^(\d+) FK-Verletzungen$/,
    enTemplate: "$1 FK violations",
    enRegex: /^(\d+) FK violations$/,
    deTemplate: "$1 FK-Verletzungen",
  },
  {
    deRegex: /^(\d+) FK-Probleme$/,
    enTemplate: "$1 FK issues",
    enRegex: /^(\d+) FK issues$/,
    deTemplate: "$1 FK-Probleme",
  },
  {
    deRegex: /^(.+) logische Kerne$/,
    enTemplate: "$1 logical cores",
    enRegex: /^(.+) logical cores$/,
    deTemplate: "$1 logische Kerne",
  },
  {
    deRegex: /^(\d+) Tage$/,
    enTemplate: "$1 days",
    enRegex: /^(\d+) days$/,
    deTemplate: "$1 Tage",
  },
  {
    deRegex: /^Verbunden · Port (\d+)$/,
    enTemplate: "Connected · Port $1",
    enRegex: /^Connected · Port (\d+)$/,
    deTemplate: "Verbunden · Port $1",
  },
  {
    deRegex: /^Online · Port (\d+)$/,
    enTemplate: "Online · Port $1",
    enRegex: /^Online · Port (\d+)$/,
    deTemplate: "Online · Port $1",
  },
  {
    deRegex: /^Letzte vollständige Prüfung: (.+)$/,
    enTemplate: "Last full check: $1",
    enRegex: /^Last full check: (.+)$/,
    deTemplate: "Letzte vollständige Prüfung: $1",
  },
  {
    deRegex: /^Verbunden als (.+)$/,
    enTemplate: "Connected as $1",
    enRegex: /^Connected as (.+)$/,
    deTemplate: "Verbunden als $1",
  },
  {
    deRegex: /^(\d+) Modelle verfügbar(.*)$/,
    enTemplate: "$1 models available$2",
    enRegex: /^(\d+) models available(.*)$/,
    deTemplate: "$1 Modelle verfügbar$2",
  },
  {
    deRegex: /^(.+) testen$/,
    enTemplate: "Test $1",
    enRegex: /^Test (.+)$/,
    deTemplate: "$1 testen",
  },
  {
    deRegex: /^(.+) bearbeiten$/,
    enTemplate: "Edit $1",
    enRegex: /^Edit (.+)$/,
    deTemplate: "$1 bearbeiten",
  },
  {
    deRegex: /^(.+) löschen$/,
    enTemplate: "Delete $1",
    enRegex: /^Delete (.+)$/,
    deTemplate: "$1 löschen",
  },
  {
    deRegex: /^(.+) wird geladen\.$/,
    enTemplate: "Loading $1.",
    enRegex: /^Loading (.+)\.$/,
    deTemplate: "$1 wird geladen.",
  },
  {
    deRegex: /^(\d+) nicht verbundene Wissenselemente$/,
    enTemplate: "$1 unlinked knowledge items",
    enRegex: /^(\d+) unlinked knowledge items$/,
    deTemplate: "$1 nicht verbundene Wissenselemente",
  },
  {
    deRegex: /^(\d+) geplanter? PRs?$/,
    enTemplate: "$1 planned PR(s)",
    enRegex: /^(\d+) planned PR\(s\)$/,
    deTemplate: "$1 geplante PRs",
  },
  {
    deRegex: /^Geplanter PR · Priorität (.+)$/,
    enTemplate: "Planned PR · Priority $1",
    enRegex: /^Planned PR · Priority (.+)$/,
    deTemplate: "Geplanter PR · Priorität $1",
  },
  {
    deRegex: /^(.+) auf GitHub öffnen$/,
    enTemplate: "Open $1 on GitHub",
    enRegex: /^Open (.+) on GitHub$/,
    deTemplate: "$1 auf GitHub öffnen",
  },
  {
    deRegex: /^(\d+) aktiv$/,
    enTemplate: "$1 active",
    enRegex: /^(\d+) active$/,
    deTemplate: "$1 aktiv",
  },
  {
    deRegex: /^(\d+) Projekte$/,
    enTemplate: "$1 projects",
    enRegex: /^(\d+) projects$/,
    deTemplate: "$1 Projekte",
  },
  {
    deRegex: /^(\d+) von (\d+)$/,
    enTemplate: "$1 of $2",
    enRegex: /^(\d+) of (\d+)$/,
    deTemplate: "$1 von $2",
  },
  {
    deRegex: /^(\d+) Dateien berücksichtigt$/,
    enTemplate: "$1 files considered",
    enRegex: /^(\d+) files considered$/,
    deTemplate: "$1 Dateien berücksichtigt",
  },
  {
    deRegex: /^Vom Hub · PID (\d+)$/,
    enTemplate: "Managed by Hub · PID $1",
    enRegex: /^Managed by Hub · PID (\d+)$/,
    deTemplate: "Vom Hub · PID $1",
  },
  {
    deRegex: /^(.+) starten$/,
    enTemplate: "Start $1",
    enRegex: /^Start (.+)$/,
    deTemplate: "$1 starten",
  },
  {
    deRegex: /^Lokale Vorschau auf Port (\d+) öffnen\.$/,
    enTemplate: "Open local preview on port $1.",
    enRegex: /^Open local preview on port (\d+)\.$/,
    deTemplate: "Lokale Vorschau auf Port $1 öffnen.",
  },
];

const deToEnMap = new Map<string, string>();
const enToDeMap = new Map<string, string>();

for (const [de, en] of HUB_EXACT_PAIRS) {
  if (!deToEnMap.has(de)) deToEnMap.set(de, en);
  if (!enToDeMap.has(en)) enToDeMap.set(en, de);
}

export function hubTranslateString(
  raw: string,
  targetLang: HubLanguage = getHubLanguage(),
): string {
  if (!raw || typeof raw !== "string") return raw;
  const match = raw.match(/^(\s*)([\s\S]*?)(\s*)$/);
  if (!match) return raw;
  const [, leading, core, trailing] = match;
  if (!core) return raw;

  if (targetLang === "en") {
    const exact = deToEnMap.get(core);
    if (exact !== undefined) return leading + exact + trailing;
    for (const p of HUB_PATTERN_PAIRS) {
      if (p.deRegex.test(core)) {
        return leading + core.replace(p.deRegex, p.enTemplate) + trailing;
      }
    }
  } else {
    const exact = enToDeMap.get(core);
    if (exact !== undefined) return leading + exact + trailing;
    for (const p of HUB_PATTERN_PAIRS) {
      if (p.enRegex.test(core)) {
        return leading + core.replace(p.enRegex, p.deTemplate) + trailing;
      }
    }
  }
  return raw;
}

export function hubT(deText: string, enText?: string): string {
  const lang = getHubLanguage();
  if (lang === "en") {
    return enText !== undefined ? enText : hubTranslateString(deText, "en");
  }
  return deText;
}

const textNodeCache = new WeakMap<Text, { de: string; en: string }>();
const attrNodeCache = new WeakMap<
  Element,
  Record<string, { de: string; en: string }>
>();
const TRANSLATABLE_ATTRS = ["placeholder", "title", "aria-label"] as const;
const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "CODE", "PRE"]);

let isApplyingDomI18n = false;
let hasTranslatedToEn = false;

export function applyHubI18nToDom(
  root: Node | null = typeof document !== "undefined" ? document.body : null,
  lang: HubLanguage = getHubLanguage(),
): void {
  if (!root || typeof document === "undefined") return;
  if (lang === "de" && !hasTranslatedToEn) return;
  if (isApplyingDomI18n) return;

  isApplyingDomI18n = true;
  if (lang === "en") {
    hasTranslatedToEn = true;
  }

  try {
    if (document.documentElement) {
      document.documentElement.lang = lang;
    }

    const translateElementAttrs = (el: Element) => {
      let cache = attrNodeCache.get(el);
      for (const attr of TRANSLATABLE_ATTRS) {
        const val = el.getAttribute(attr);
        if (!val) continue;
        if (lang === "en") {
          const cached = cache?.[attr];
          if (cached && val === cached.en) continue;
          const baseDe = cached && val === cached.de ? cached.de : val;
          const nextEn = hubTranslateString(baseDe, "en");
          if (nextEn !== val) {
            if (!cache) {
              cache = {};
              attrNodeCache.set(el, cache);
            }
            cache[attr] = { de: baseDe, en: nextEn };
            el.setAttribute(attr, nextEn);
          }
        } else {
          const cached = cache?.[attr];
          if (cached && val === cached.en) {
            el.setAttribute(attr, cached.de);
          } else {
            const nextDe = hubTranslateString(val, "de");
            if (nextDe !== val) {
              el.setAttribute(attr, nextDe);
            }
          }
        }
      }
    };

    if (root.nodeType === Node.ELEMENT_NODE) {
      translateElementAttrs(root as Element);
      const elements = (root as Element).querySelectorAll(
        "[placeholder],[title],[aria-label]",
      );
      elements.forEach(translateElementAttrs);
    }

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode() as Text | null;
    while (current) {
      const parent = current.parentElement;
      if (parent && !SKIP_TAGS.has(parent.tagName)) {
        const val = current.nodeValue;
        if (val && val.trim().length > 0) {
          const cached = textNodeCache.get(current);
          if (lang === "en") {
            if (!cached || val !== cached.en) {
              const baseDe = cached && val === cached.de ? cached.de : val;
              const nextEn = hubTranslateString(baseDe, "en");
              if (nextEn !== val) {
                textNodeCache.set(current, { de: baseDe, en: nextEn });
                current.nodeValue = nextEn;
              }
            }
          } else {
            if (cached && val === cached.en) {
              current.nodeValue = cached.de;
            } else {
              const nextDe = hubTranslateString(val, "de");
              if (nextDe !== val) {
                current.nodeValue = nextDe;
              }
            }
          }
        }
      }
      current = walker.nextNode() as Text | null;
    }
  } finally {
    isApplyingDomI18n = false;
  }
}

let observerInitialized = false;

export function initHubI18nObserver(): void {
  if (observerInitialized || typeof window === "undefined" || typeof document === "undefined") {
    return;
  }
  observerInitialized = true;

  let rafPending = false;
  const scheduleApply = () => {
    if (rafPending) return;
    const currentLang = getHubLanguage();
    if (currentLang === "de" && !hasTranslatedToEn) return;
    rafPending = true;
    const run = () => {
      rafPending = false;
      applyHubI18nToDom(document.body, getHubLanguage());
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 0);
    }
  };

  if (typeof MutationObserver !== "undefined" && document.body) {
    const observer = new MutationObserver(() => {
      if (isApplyingDomI18n) return;
      scheduleApply();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["placeholder", "title", "aria-label"],
    });
  }

  if (getHubLanguage() === "en") {
    scheduleApply();
  }
}

export function getHubLanguage(): HubLanguage {
  if (typeof window === "undefined") return "de";
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "en" || raw === "de") return raw;
  } catch {
    // Ignore storage errors in restricted environments
  }
  return "de";
}

export function setHubLanguage(lang: HubLanguage): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Ignore storage errors
  }
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: lang }));
  applyHubI18nToDom(document.body, lang);
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(() => applyHubI18nToDom(document.body, lang));
  }
  // Notify any embedded iframes (such as /docs)
  try {
    const iframes = document.querySelectorAll("iframe");
    iframes.forEach((frame) => {
      frame.contentWindow?.postMessage(
        { type: "antigravity-lang", lang },
        "*",
      );
    });
  } catch {
    // Ignore cross-frame errors
  }
}

function subscribeToLanguage(onStoreChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const handler = () => onStoreChange();
  window.addEventListener(EVENT_NAME, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT_NAME, handler);
    window.removeEventListener("storage", handler);
  };
}

export function useHubLanguage(): [HubLanguage, (lang: HubLanguage) => void] {
  const lang = useSyncExternalStore<HubLanguage>(
    subscribeToLanguage,
    getHubLanguage,
    () => "de",
  );
  useEffect(() => {
    initHubI18nObserver();
    applyHubI18nToDom(document.body, lang);
  }, [lang]);
  return [lang, setHubLanguage];
}
