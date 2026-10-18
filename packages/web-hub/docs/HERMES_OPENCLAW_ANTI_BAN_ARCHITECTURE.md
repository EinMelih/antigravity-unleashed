# Anti-Gravity API Bridge (`v2.24.0`) — Hermes & OpenClaw Anti-Ban-Architektur & Sicherheits-Dokumentation

> [!IMPORTANT]
> Diese Dokumentation beschreibt sämtliche Schutzmechanismen, Architektur-Entscheidungen und Reverse-Engineering-Erkenntnisse aus **Anti-Gravity `v2.24.0`**, die in `packages/web-hub` implementiert wurden, um **Hermes**, **OpenClaw** und andere OpenAI-/Anthropic-kompatible Clients mit maximaler Geschwindigkeit, bis zu **10 gleichzeitigen Requests** und **minimalem Bannrisiko** zu betreiben.

---

## 1. Hintergrund: Warum kam es im Februar 2026 zur OpenClaw-Banwelle?

Bei der Analyse der `google-antigravity-auth` / OpenClaw-Sperrwelle und dem vollständigen Reverse-Engineering von Anti-Gravity `v2.24.0` (`language_server.exe` + `main_root.formatted.js`) wurden **8 konkrete Erkennungsvektoren** identifiziert. Accounts wurden **nicht** gesperrt, weil jemand intensiv programmiert oder mehrere Projekte parallel genutzt hat, sondern weil Drittanbieter-Proxys folgende Fehler begangen haben:

1. **Direct-Cloud-Spoofing:** Eigene Python/Node.js-Skripte haben das `ya29...` OAuth-Token ausgelesen und direkt an `daily-cloudcode-pa.googleapis.com` gesendet (falscher TLS/JA3-Fingerprint, fehlender Go-HTTP/2-Stack, fehlende interne Depot-Revision `1000335682`).
2. **`[System: ...]` Prompt-Injection & Framework-Signaturen:** System-Prompts wurden als `[System: You are OpenClaw/Hermes...]` direkt in `<USER_REQUEST>` kopiert, inklusive verräterischer Dateinamen (`SOUL.md`, `HEARTBEAT.md`, `TOOLS.md`).
3. **24/7 Heartbeat-Endlosschleifen:** Automatische Hintergrund-Pings liefen 24 Stunden am Tag im Minutentakt durch.
4. **Nackte 1-Turn-Wegwerf-Chats (`step_count == 1`):** Für jede einzelne API-Anfrage wurde ein neuer Chat ohne Workspace-Pfad erstellt.
5. **Unvollständige lokale RPC-Payloads:** Bei lokalen Aufrufen an `language_server.exe` fehlten `messageOrigin: 1` (`AGENT_MESSAGE_ORIGIN_IDE`), `clientType: 1`, `metadata`, `experimentConfig` und `editorState`.
6. **429-Spam bei leerem Quota:** Nachdem das 5-Stunden-Kontingent eines Modells (z. B. Claude Opus) auf `0 %` gefallen war, feuerten Bots im Sekundentakt weiter gegen Googles `RESOURCE_EXHAUSTED`-Endpunkt.
7. **DOM-CSP-Violations & Telemetrie-Leaks:** Unsaubere DOM-Injektionen lösten Berichte an `https://csp.withgoogle.com/csp/JetskiWeb` und `https://play.googleapis.com/log` aus.
8. **Unkoordinierte 0ms-Bot-Spikes:** 10–20 Requests wurden in exakt derselben Millisekunde (`Δt = 0 ms`) ohne jeglichen Start-Versatz abgefeuert.

---

## 2. Dual-Engine-Architektur: `rpc` (Standard) vs. `ui` (Backup)

Unsere API-Bridge unterstützt zwei Ausführungs-Engines, die jederzeit live im Dashboard (`#/api-logs`) oder in `config.json` (`api.mode`) umgeschaltet werden können:

```mermaid
flowchart LR
    Client["Hermes / OpenClaw\n(bis zu 10 Requests parallel)"] --> API["API Bridge (:8001)\nsrc/api_server.py"]
    API --> Shields["8 Anti-Ban-Schutzschilde\nsrc/antigravity_shields.py"]
    Shields -->|api.mode = 'rpc' (Standard)| Pool["10-Slot Workspace Pool\nws-00 .. ws-09 (src/rpc_pool.py)"]
    Shields -->|api.mode = 'ui' (Backup)| UI["CDP / Electron Preload Bridge\n(src/cdp_PreloadBridge)"]
    Pool -->|127.0.0.1 ConnectRPC\n1:1 React-UI Payload| LS["Original language_server.exe\n(Isoliertes API-Profil)"]
    UI --> LS
    LS -->|Echter Go TLS-Stack\nOffizielles Protobuf| Google["Google Cloud\n(daily-cloudcode-pa.googleapis.com)"]
```

- **`mode: "rpc"` (Standard – Zero-CDP Direct ConnectRPC):**
  Kommuniziert lokal über `https://127.0.0.1:<PORT>/exa.language_server_pb.LanguageServerService/*` direkt mit dem originalen `language_server.exe`-Prozess des isolierten API-Profils. Kein langsames DOM-Klicken, kein Fokus-Verlust, volle Multi-Turn-Verfolgung über `cascadeId` und native Unterstützung für Linux/Container/Dokploy (`--standalone --headless`).
- **`mode: "ui"` (Backup – Electron/CDP):**
  Nutzt weiterhin das isolierte Electron-Fenster über die Preload-Bridge als Fallback.

---

## 3. Die 8 Anti-Ban-Schutzschilde im Detail (`src/antigravity_shields.py`)

### Schild 1: 100 % Routing über die echte `language_server.exe`
- Die Python-Bridge baut **niemals** eine Verbindung zu `googleapis.com` auf.
- Alle Anfragen gehen ausschließlich lokal (`127.0.0.1`) an den unveränderten Go-Prozess `language_server.exe`, der mit den offiziellen IDE-Flags gestartet wird (`--override_ide_name antigravity --subclient_type hub --override_ide_version 2.24.0`).
- Dadurch stammen TLS-Handshake (JA3/JA4), HTTP/2-Framing, OAuth-Token-Refresh und Depot-CL-Header zu 100 % vom offiziellen Google-Binary.

### Schild 2: Keyword-Firewall & Offizielle `AGENTS.md`-Systemprompt-Injektion
- **Kein `[System: ...]` mehr im User-Prompt:** In früheren Versionen wurde `role == "system"` als `[System: ...]` vor die User-Nachricht geklebt. Das landet innerhalb von `<USER_REQUEST>` und sieht für Googles Klassifizierer wie ein Prompt-Injection-/Proxy-Angriff aus.
- **Offizielle `<RULE[AGENTS.md]>`-Engine:** Der System-Prompt von Hermes/OpenClaw wird bereinigt und vor dem Senden als strukturierte Projekt-Richtlinie in `<workspace_slot>/AGENTS.md` (max. 24 KB) geschrieben. `language_server.exe` liest diese Datei nativ über seine eigene Rule-Engine (`0x3267C05`) als offizielles System-Rule-Tag ein.
- **Keyword-Firewall:** Verräterische Begriffe (`OpenClaw`, `Hermes`, `Cline`, `RooCode`, `SOUL.md`, `HEARTBEAT.md`, `TOOLS.md`, `Ignore previous instructions`, `You are no longer Antigravity`) werden automatisch neutralisiert, bevor sie `language_server.exe` erreichen.

### Schild 3: Lokaler Heartbeat-Blocker & Smart Adaptive Pacing
- **Lokaler Heartbeat-Abfangjäger (`0 ms`):** Periodische Hintergrund-Pings von OpenClaw/Hermes (z. B. `HEARTBEAT_OK`, leere Cron-Checks) werden von `HeartbeatAndPacingGuard` erkannt und direkt lokal von der Bridge beantwortet – sie verbrauchen **0 Tokens** und erzeugen keinen Traffic bei Google.
- **Smart Adaptive Pacing (Schnell im Alltag, sicher bei Bot-Loops):**
  - Liegt der letzte Request auf einem Slot mehr als `3 Sekunden` zurück (normales interaktives Arbeiten), startet der Request **sofort** mit minimalem Mikro-Jitter (`0.1s–0.4s`).
  - Feuert ein Agent jedoch in einer engen Endlosschleife (`< 2.0s` nach Antwortende), schaltet sich automatisch ein menschlicher Pacing-Jitter (`1.5s–4.5s`) sowie das konfigurierbare RPM-Limit ein.

### Schild 4: Multi-Turn Session-Reuse & Echte Workspace-Struktur
- Statt für jeden Request einen verdächtigen 1-Turn-Chat (`step_count == 1`) ohne Projektbezug anzulegen, verwaltet `src/rpc_pool.py` **10 echte Workspace-Ordner** (`ws-00` bis `ws-09`).
- Jeder Workspace-Slot besitzt echte Projektdateien (`README.md`, `src/main.py`, `AGENTS.md`), sodass `workspaceUris` und `editorState` immer auf reale Dateien zeigen.
- Zusammengehörige Konversationen von Hermes/OpenClaw werden über das `messages`-Präfix (oder `X-Conversation-Id`) automatisch derselben `cascadeId` zugeordnet und erst nach `20 Turns` (konfigurierbar) sauber rotiert.

### Schild 5: 1:1 React-UI Payload-Klon (`main_root.formatted.js`)
Alle lokalen ConnectRPC-Aufrufe in `src/rpc_client.py` bilden exakt die Payloads der echten React-Oberfläche nach:
- **`StartCascade` (`main_root.formatted.js:80423`):**
  - `source: 1` (`CORTEX_TRAJECTORY_SOURCE_CASCADE_CLIENT`)
  - `workspaceUris: ["file:///.../ws-XX"]`
  - `requestedModel: <ModelEnum>`
- **`SendUserCascadeMessage` (`main_root.formatted.js:75508` & `80308`):**
  - `messageOrigin: 1` (`AGENT_MESSAGE_ORIGIN_IDE` statt `0 = UNSPECIFIED` oder `2 = SDK`)
  - `clientType: 1`
  - `metadata`: `{"ideName": "antigravity", "ideVersion": "2.24.0", "extensionName": "antigravity"}`
  - `cascadeConfig.plannerConfig`:
    - `autoExecutionPolicy: 3` (Eager/Turbo) & `artifactReviewMode: 2` -> **0 Approval-Hänger!**
    - `effectiveGrants`: Voller Lese-/Schreib-/Command-Zugriff im Slot-Workspace.
    - `knowledgeConfig: {"enabled": false}` & `conversationHistoryConfig: {"enabled": false}` -> **100 % Kontext-Isolation** (kein Lesen fremder Chats oder Memories).

### Schild 6: Pre-Flight Quota Circuit Breaker (Nahtloser Hermes-Fallback)
- Vor jedem Request prüft `QuotaCircuitBreaker` über `RetrieveUserQuotaSummary` (mit 30s Cache) die `remainingFraction` des angefragten Modells.
- Fällt das Modell-Quota unter den Sicherheitswert (Standard: **`5 %`**), schickt unsere Bridge den Request **nicht** an Google, sondern gibt lokal sofort einen standardkonformen OpenAI-Fehler zurück:
  - Status: `HTTP 429 Too Many Requests`
  - Code: `"model_quota_exhausted"` / `"insufficient_quota"`
- **Vorteil für Hermes / OpenClaw:** Da Hermes eine eigene Fallback-Kette besitzt, erkennt Hermes den lokalen `429`-Status sofort und wechselt in Millisekunden automatisch auf das in Hermes hinterlegte Fallback-Modell (z. B. von Claude Opus auf Sonnet oder Gemini 3.1 Pro), ohne dass Google jemals mit `RESOURCE_EXHAUSTED`-Fehlern bombardiert wird!

### Schild 7: Null-CSP-Leak & Telemetrie-Sperre
- Im `rpc`-Modus wird kein Chromium-DOM manipuliert -> `0` CSP-Violation-Reports an `csp.withgoogle.com/csp/JetskiWeb`.
- `src/api_profile.py` erzwingt in der `config.json` und `state.json` des isolierten API-Profils `disableTelemetry: true`, `telemetryEnabled: false` und `crashReporterEnabled: false`.

### Schild 8: Multi-Projekt IDE-Parallelität (`maxClonedWorkspaces`) + Start-Stagger
- Warum mehrere gleichzeitige Streams in der echten IDE normal sind:
  - In Anti-Gravity `v2.24.0` unterstützt der Client nativ mehrere parallele Projektfenster, Subagenten (`invoke_subagent`), Battle Mode (`StartBattleMode`) sowie `maxClonedWorkspaces = 5` (`catalog/ui_internals.json`).
- Wie unsere Bridge 10 gleichzeitige Requests balanciert:
  - Alle **10 gleichzeitigen HTTP-Verbindungen** von Hermes/OpenClaw werden sofort angenommen und auf die 10 isolierten Workspace-Slots (`ws-00`..`ws-09`) verteilt.
  - Ein konfigurierbarer Semaphore (`max_parallel_streams`, Standard: **`4`**, im Dashboard von `1` bis `10` einstellbar) lässt bis zu 4 Streams echt gleichzeitig generieren.
  - Zwischen zwei gleichzeitigen Stream-Starts liegt immer ein **zufälliger Start-Versatz (`0.4s–1.2s`)**, sodass niemals zwei Requests in derselben Millisekunde (`Δt = 0 ms`) bei Google eintreffen.

---

## 4. „Zurück zur vorherigen Nachricht“ (Revert), Token-Genauigkeit & API-Funktionen

1. **Automatisches & Manuelles Revert (`RevertToCascadeStep`):**
   - Wenn du in Hermes eine Nachricht bearbeitest, löschst oder neu generierst („Zurück zur vorherigen Nachricht“), erkennt `src/rpc_pool.py` anhand des verkürzten `messages`-Arrays automatisch den Ziel-Step und ruft vor dem neuen Prompt `RevertToCascadeStep(cascadeId, stepIndex, conversationOnly=True)` auf.
   - Zusätzlich steht `POST /v1/chat/revert` für gezieltes Zurückspulen um `steps_back` Turns bereit.
2. **Exakte Token- & Kontext-Metriken (`GetCascadeTrajectoryGeneratorMetadata`):**
   - Nach jedem Turn liest `src/api_token_reader.py` die echten Werte aus `chatModelMetadata.usage` (`inputTokens`, `outputTokens`, `cacheReadInputTokens`, `thinkingOutputTokens`) sowie `contextWindowMetadata` (`estimatedTokensUsed`, `maxContextTokens`) aus und gibt sie im OpenAI-`usage`-Objekt zurück.
3. **Persistentes Audit-Logging (`#/api-logs`):**
   - Jeder Request, jedes Revert-Event und jede Schild-Aktion wird dauerhaft in SQLite (`api_request_logs`, `api_revert_events`) und `~/.antigravity-hub/api_audit_logs.jsonl` gespeichert und ist im Dashboard unter `#/api-logs` einsehbar und exportierbar.
