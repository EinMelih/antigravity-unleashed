# Antigravity Architecture & Internals Specification

**Target Version:** Google Antigravity `v2.24.0`  
**Document Status:** Production Reference Specification  
**Classification:** Reverse Engineering & Systems Architecture Documentation  

---

## Table of Contents
1. [Executive Architecture Overview](#1-executive-architecture-overview)
2. [Host Environment & Process Lifecycle](#2-host-environment--process-lifecycle)
3. [Electron Main Process Subsystems](#3-electron-main-process-subsystems)
4. [IPC Contract & Security Boundary](#4-ipc-contract--security-boundary)
5. [Renderer SPA Architecture (`main_root.js`)](#5-renderer-spa-architecture-main_rootjs)
6. [Feature Flags, A/B Testing & User Gating](#6-feature-flags-ab-testing--user-gating)
7. [Communication Protocols & gRPC-Web Streaming](#7-communication-protocols--grpc-web-streaming)
8. [Reverse Engineering & Extensibility Guide](#8-reverse-engineering--extensibility-guide)

---

## 1. Executive Architecture Overview

Google Antigravity is an agentic, multi-process desktop IDE engineered around a decoupled client-server paradigm. Unlike traditional monolithic Electron applications where business logic executes directly in the Node.js Main process or renderer DOM, Antigravity delegates all code intelligence, workspace indexing, terminal supervision, agent orchestration, and Google Cloud telemetry to an autonomous native Go/C++ binary: the **Antigravity Language Server** (`language_server.exe` / `language_server_windows_x64.exe`).

The Electron desktop layer functions strictly as a native windowing shell, hardware integration bridge, and high-performance React SPA container.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                OS Desktop Host Window                                  │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                    Chromium Renderer SPA (main_root.js - 7.78 MB)                │  │
│  │  - React 19 Virtual DOM / Component Tree (ChatDesk, Multi-Pane, Terminal, Diff)  │  │
│  │  - Redux Toolkit Reactive Store (agentTab, conversation, workspace)             │  │
│  │  - Connect-Web / gRPC-Web Client over Loopback HTTPS                            │  │
│  └──────────────────────────────────────┬───────────────────────────────────────────┘  │
│                                         │                                              │
│                  ContextBridge API      │ (x-codeium-csrf-token)                       │
│                  (window.electronBridge)│ Direct Loopback HTTPS                        │
│                                         │ Connect-RPC Streams                          │
│                                         ▼                                              │
│  ┌──────────────────────────────────┐   │   ┌───────────────────────────────────────┐  │
│  │     Electron Main Process        │   │   │     Native Language Server            │  │
│  │     (dist/*.js - Node.js)        │   └──►│     (language_server.exe - 171 MB)    │  │
│  │  - Window Management (utils.js)  │       │  - Workspace AST Indexer & SQLite FTS5│  │
│  │  - IPC Dispatch (ipcHandlers.js) │       │  - Autonomous Cascade Execution Engine│  │
│  │  - Updater Lifecycle (updater.js)│       │  - Sandboxed Shell Process Supervisor │  │
│  │  - Tray & OS Shell Integration   │       │  - gRPC-Web / HTTP Connect Gateway    │  │
│  │  - WSL2 Bridge & Spawner (wsl.js)│       │  - Local Loopback CSRF Verifier       │  │
│  └──────────────────┬───────────────┘       └───────────────────┬───────────────────┘  │
│                     │ (Spawns & Monitors)                       │                      │
│                     └───────────────────────────────────────────┘                      │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │ Encrypted TLS / OAuth2
                                          ▼
                      ┌───────────────────────────────────────┐
                      │    Google Cloud AI Companion Backend   │
                      │    - Gemini 1.5 Pro / 2.0 Flash       │
                      │    - Mendel Experiment Registry       │
                      │    - Enterprise GCP Quota & Policies  │
                      └───────────────────────────────────────┘
```

### Core Design Principles
1. **Decoupled Language Server Core:** The native `language_server.exe` owns the source of truth for all conversation states, model quotas, workspace symbol indices, and trajectory executions. Even if the Electron window reloads, the Language Server retains execution state.
2. **Ephemeral Dynamic Port Allocation:** To eliminate port conflicts and prevent external cross-process port collisions, the Language Server binds to `127.0.0.1` on an ephemeral OS-assigned TCP port (`constants.DYNAMIC_PORT = 0`).
3. **Defense-in-Depth CSRF Token Binding:** Every local HTTP/Connect-Web RPC invocation requires a session-bound cryptographic UUID token transmitted via the `x-codeium-csrf-token` header, generated on startup and shared only with authorized child processes.
4. **Thin Native Electron Shell:** The Electron Main process remains strictly focused on OS-specific capabilities: native file picker dialogs, window titlebar styling, multi-window lifecycles, WSL distro translation, system notifications, and desktop auto-updating.

---

## 2. Host Environment & Process Lifecycle

### 2.1 Spawning & Dynamic Port Handshake (`dist/languageServer.js`)

On startup, `dist/main.js` initializes `LanguageServerManager` (`dist/languageServer.js`). The lifecycle proceeds as follows:

```
[Electron Main: app.on('ready')]
       │
       ▼
[Generate Cryptographic CSRF Token]
`csrfToken = crypto.randomUUID()`
       │
       ▼
[Spawn language_server.exe Process]
Arguments:
  --dynamic_port=true
  --csrf_token=<UUID>
  --extension_server_port=<PORT>
  --parent_pid=<PID>
  --log_dir=<LOCALAPPDATA>/Antigravity/logs
       │
       ▼
[Read Stdout / Port Discovery]
Language server writes handshake line:
  "Language server started on https://127.0.0.1:<PORT>"
       │
       ▼
[Capture HTTPS Port & Verify Health]
POST https://127.0.0.1:<PORT>/exa.language_server_pb.LanguageServerService/GetStatus
Header: `x-codeium-csrf-token: <UUID>`
       │
       ▼
[Load Renderer URL]
`mainWindow.loadURL("https://127.0.0.1:<PORT>/")`
```

If the Language Server process exits unexpectedly, `dist/languageServer.js` captures the exit code, restarts the binary up to a maximum retry limit, and notifies the renderer via IPC.

### 2.2 Host Bridge Loopback Server (`dist/hostBridgeServer.js`)

To enable native binaries (`language_server.exe`) to query or trigger Electron host actions (such as initiating an update check or querying host version) without relying on Electron IPC, the Main process spawns an internal HTTP loopback server implementing ConnectRPC:
- **Service:** `exa.host_bridge_pb.HostBridgeService`
- **Interface Methods:**
  - `GetUpdateStatus(Empty): UpdateStatusResponse`
  - `ApplyUpdate(Empty): Empty`
- **Security:** Bound strictly to `127.0.0.1`, validates incoming CSRF token matching the session token.

### 2.3 WSL2 Bridge Architecture (`dist/wsl.js`)

Antigravity features native integration with the Windows Subsystem for Linux (WSL2):
1. **Distribution Discovery:** Executes `wsl.exe -l -v` to detect installed Linux distributions and identify the default distribution.
2. **Server Auto-Provisioning:** When launched in WSL mode, Antigravity deploys and launches the Linux-native `language_server_linux_x64` binary inside the WSL distribution, while retaining the Windows Chromium desktop UI shell.
3. **Path Translation:** Automatically converts paths between Windows UNC syntax (`\\wsl$\Ubuntu\home\...`) and POSIX paths (`/home/...`) via `wsl.exe wslpath`.
4. **Provisioning Splash Window:** Displays `dist/provisionSplash.js` showing real-time progress while unpacking or downloading WSL server components.

---

## 3. Electron Main Process Subsystems

The pristine upstream Electron application package (`app.asar`) contains 26 core application modules under `dist/`:

### Subsystem Directory Map
| Module Path | Size (Lines) | Primary Responsibility |
|:---|:---|:---|
| `dist/main.js` | 491 | Application entry point: single-instance lock, deep-link routing, LS lifecycle orchestration. |
| `dist/preload.js` | 117 | Secure ContextBridge isolation exposing `window.electronBridge` to the renderer. |
| `dist/ipcHandlers.js` | 409 | Primary IPC routing table handling 32 `ipcMain.handle` channels. |
| `dist/utils.js` | 322 | `BrowserWindow` factory, Content Security Policy (CSP), window zoom persistence, caption controls. |
| `dist/updater.js` | 357 | Auto-update lifecycle managing `electron-updater` background queries and downloads. |
| `dist/languageServer.js` | 468 | Process supervisor for `language_server.exe` (spawn, port discovery, health checks). |
| `dist/hostBridgeServer.js` | 212 | Loopback HTTP ConnectRPC server for host update commands. |
| `dist/keybindings.js` | 19 | Main-process accelerator registrations (Ctrl+Shift+N, Ctrl+Q). |
| `dist/menu.js` | 176 | Application menu bar, Dock menu (macOS), and WSL distro switcher. |
| `dist/paths.js` | 52 | Canonical filesystem path resolution (`userData`, `logs`, `settings.pb`). |
| `dist/storage.js` | 128 | Persistent JSON configuration storage (`StorageManager`). |
| `dist/tray.js` | 95 | System tray icon with active agent count overlay badge. |
| `dist/wsl.js` | 338 | WSL2 discovery, Linux server bootstrap, and path translation. |
| `dist/customScheme.js` | 55 | Protocol handler for `antigravity-ide://` extension assets. |
| `dist/loadingOverlay.js` | 90 | Pre-render splash screen displayed during window boot. |
| `dist/provisionSplash.js`| 100 | Progress splash screen shown during WSL server provisioning. |
| `dist/constants.js` | 7 | Global constants (`WINDOW_ORIGIN`, `DYNAMIC_PORT = 0`). |
| `dist/types.js` | 26 | TypeScript enums for update states and window modes. |
| `dist/ideInstall/*` | 821 | Onboarding wizard, download manager, and IDE installation checks. |
| `dist/services/settingsService.js` | 60 | Default capability and settings dictionary. |

### Deep-Link Architecture (`antigravity://`)
`dist/main.js` registers Antigravity as the default OS protocol handler for `antigravity://`:
- **Cold Start:** The URL is passed via `process.argv` on Windows/Linux or `open-url` on macOS, stored in `pendingDeepLinkUrl`, and queried via `deep-link:get-stored`.
- **Warm Invocation:** If a second instance is launched with a protocol URL, the single-instance lock handler (`app.on('second-instance')`) focuses the existing window and streams the URL via `webContents.send('deep-link', url)`.

---

## 4. IPC Contract & Security Boundary

### 4.1 Context Isolation & Security Hardening
The Electron shell enforces strict Chromium security boundaries:
- `contextIsolation: true`: Isolates renderer execution contexts; DOM cannot access Node.js globals directly.
- `nodeIntegration: false`: Renderer scripts cannot call `require()`, `process`, or native Node modules.
- `webSecurity: true`: Enforces same-origin policy and standard CORS checks.
- `sandbox: true`: Chromium renderer sandbox is active.
- `Content-Security-Policy`: Strictly restricts script execution, style sources, and prevents inline unsafe eval.

### 4.2 Comprehensive IPC Routing Matrix

The application defines **32 request-response channels** (`ipcMain.handle`) and **4 push event streams** (`webContents.send`).

```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│                                IPC Matrix: Renderer ↔ Main Process                             │
├───────────────────────────────┬─────────────────────────────┬──────────────┬──────────────────┤
│ Channel Name                  │ Direction & Pattern         │ Parameters   │ Return Type      │
├───────────────────────────────┼─────────────────────────────┼──────────────┼──────────────────┤
│ dialog:open-workspace         │ Renderer -> Main (invoke)   │ ()           │ Promise<string?> │
│ dialog:open-workspaces        │ Renderer -> Main (invoke)   │ ()           │ Promise<string[]>│
│ updater:apply                 │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ updater:quit-and-install      │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ updater:get-state             │ Renderer -> Main (invoke)   │ ()           │ UpdateState      │
│ updater:check-for-updates     │ Renderer -> Main (invoke)   │ ()           │ void             │
│ notification:send             │ Renderer -> Main (invoke)   │ ({options})  │ void             │
│ notification:open-sys-prefs   │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ storage:get-items             │ Renderer -> Main (invoke)   │ ()           │ Promise<Record>  │
│ storage:update-items          │ Renderer -> Main (invoke)   │ (changes)    │ Promise<void>    │
│ logs:electron                 │ Renderer -> Main (invoke)   │ ()           │ Promise<string>  │
│ extensions:send-authorities   │ Renderer -> Main (invoke)   │ (map)        │ Promise<void>    │
│ agent:update-active-count     │ Renderer -> Main (invoke)   │ (count)      │ Promise<void>    │
│ window:set-title-bar-overlay  │ Renderer -> Main (invoke)   │ ({overlay})  │ Promise<void>    │
│ window:minimize               │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:maximize               │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:unmaximize             │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:is-maximized           │ Renderer -> Main (invoke)   │ ()           │ Promise<boolean> │
│ window:close                  │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:toggle-devtools        │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:show-context-menu      │ Renderer -> Main (invoke)   │ (items)      │ Promise<string?> │
│ window:close-context-menu     │ Renderer -> Main (invoke)   │ ()           │ void             │
│ window:zoom-in                │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:zoom-out               │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ window:reset-zoom             │ Renderer -> Main (invoke)   │ ()           │ Promise<void>    │
│ shell:open-external           │ Renderer -> Main (invoke)   │ (url)        │ Promise<void>    │
│ shell:reveal-in-file-picker   │ Renderer -> Main (invoke)   │ (path)       │ void             │
│ ide:is-installed              │ Renderer -> Main (invoke)   │ ()           │ Promise<boolean> │
│ wsl:get-state                 │ Renderer -> Main (invoke)   │ ()           │ Promise<WslState>│
│ wsl:connect                   │ Renderer -> Main (invoke)   │ (distro)     │ void             │
│ deep-link:get-stored          │ Renderer -> Main (invoke)   │ ()           │ string | null    │
│ wizard:complete               │ Renderer -> Main (invoke)   │ (download)   │ Promise<void>    │
├───────────────────────────────┼─────────────────────────────┼──────────────┼──────────────────┤
│ updater:state-changed         │ Main -> Renderer (push)     │ (stateEvent) │ void             │
│ notification:clicked          │ Main -> Renderer (push)     │ (payload)    │ void             │
│ storage:changed               │ Main -> Renderer (push)     │ (changes)    │ void             │
│ deep-link                     │ Main -> Renderer (push)     │ (url)        │ void             │
└───────────────────────────────┴─────────────────────────────┴──────────────┴──────────────────┘
```

---

## 5. Renderer SPA Architecture (`main_root.js`)

The React application bundle (`main_root.js`, 7.78 MB, 111,933 beautified lines) is compiled using Google Closure Compiler with advanced optimizations. It serves as the rich UI frontend rendered inside Chromium.

### 5.1 Primary Layout & Component Tree
The application workspace is structured around a flexible multi-pane layout:
- **ChatDesk & Trajectory Stream View:** Renders autonomous agent turns, user prompts, live thinking steps, and artifact feedback cards.
- **Diff Reviewer & Code Zones:** Visualizes side-by-side and inline diffs generated by cascade edits, with one-click Accept/Reject controls.
- **Bottom Terminal Dock:** Integrated `xterm.js` terminal supporting shell integration (OSC 133), split panes, and agent command observation.
- **Command Palette & Pickers:** Universal quick-jump modal supporting file navigation (`Ctrl+P`), command execution (`Ctrl+Shift+P`), conversation picking (`Ctrl+K`), and workspace switching (`Ctrl+Shift+K`).

### 5.2 Centralized Action & Shortcut Registry
Antigravity defines a declarative action table evaluated by the keybinding context provider (`QK`) and modifier resolver (`SK`/`TK`):

| Action Identifier | UI Label | Category | Default Keybinding (Win/Linux) | macOS Binding |
|:---|:---|:---|:---|:---|
| `openCommandPaletteWithPrefix` | Open Command Palette | Command Palette | `Ctrl + Shift + P` | `Cmd + Shift + P` |
| `openCommandPalette` | File Picker | File Search | `Ctrl + P` | `Cmd + P` |
| `openConvoPicker` | Open Conversation Picker | Navigation | `Ctrl + K` | `Cmd + K` |
| `openWorkspaceSelector` | Open Workspace Selector | Workspace | `Ctrl + Shift + K` | `Cmd + Shift + K` |
| `settings.open` | Open Settings | System | `Ctrl + ,` | `Cmd + ,` |
| `openShortcutsOverlay` | Open Keyboard Shortcuts | Help | `Ctrl + ?` / `Ctrl + Shift + /` | `Cmd + ?` |
| `sidebar.toggleSidebar` | Toggle Sidebar | Layout | `Ctrl + B` | `Cmd + B` |
| `toggleAuxPane` | Toggle Auxiliary Pane | Layout | `Ctrl + Shift + B` / `Ctrl + Alt + B` | `Cmd + Alt + B` |
| `toggleBottomPane` | Toggle Terminal | Terminal | `Ctrl + J` / `Ctrl + \`` | `Cmd + J` / `Cmd + \`` |
| `toggleEditor` | Toggle Editor | Editor | `Ctrl + E` | `Cmd + E` |
| `toggleModelSelector` | Toggle Model Selector | Model Control | `Ctrl + /` | `Cmd + /` |
| `toggleProjectSelector` | Toggle Project Selector | Workspace | `Ctrl + ;` | `Cmd + ;` |
| `toggleEnvironmentSelector` | Toggle Environment Selector | Environment | `Ctrl + .` | `Cmd + .` |
| `acceptAgentStep` | Accept Step | Agent Execution | `Alt + Enter` | `Alt + Enter` |
| `proceedPlanArtifact` | Proceed with Plan | Agent Execution | `Ctrl + Enter` | `Cmd + Enter` |
| `startVoiceRecording` | Start Voice Recording | Voice Input | `Ctrl + M` (Hold) | `Ctrl + M` (Hold) |
| `stopVoiceRecording` | Stop Voice Recording | Voice Input | `Keyup: M` | `Keyup: M` |
| `toggleVoiceRecording` | Toggle Voice Recording | Voice Input | `Ctrl + M` (Click) | `Ctrl + M` |
| `openNewConversation` | New Conversation | Chat Management | `Ctrl + N` | `Cmd + N` |
| `openNewEditor` | New Editor Window | Window | `Ctrl + Shift + N` | `Cmd + Shift + N` |
| `closeTab` | Close Tab | Navigation | `Ctrl + W` | `Cmd + W` |
| `openWorkspace` | Open Workspace | Workspace | `Ctrl + O` | `Cmd + O` |
| `createSplitTerminal` | Split Terminal | Terminal | `Ctrl + \\` | `Cmd + \\` |
| `closeTerminalTab` | Close Terminal Tab | Terminal | `Ctrl + W` | `Cmd + W` |
| `openNewTerminalTab` | New Terminal Tab | Terminal | `Ctrl + T` | `Cmd + T` |
| `mentionSelection` | Mention Selection | Chat Input | `Ctrl + L` | `Cmd + L` |
| `focusInput` | Focus Input | Chat Input | `Ctrl + L` / `Ctrl + I` | `Cmd + L` / `Cmd + I` |
| `zoomIn` | Zoom In | View | `Ctrl + =` / `Ctrl + +` | `Cmd + =` / `Cmd + +` |
| `zoomOut` | Zoom Out | View | `Ctrl + -` | `Cmd + -` |
| `zoomReset` | Reset Zoom | View | `Ctrl + 0` | `Cmd + 0` |
| `findInPane` | Find in Pane | Search | `Ctrl + F` | `Cmd + F` |
| `goBack` | Go Back | Navigation | `Ctrl + [` | `Cmd + [` |
| `goForward` | Go Forward | Navigation | `Ctrl + ]` | `Cmd + ]` |
| `codeSearch` | Code Search | Search | `Ctrl + Shift + F` | `Cmd + Shift + F` |
| `vcs` | Open Commit Graph | VCS / Git | `Ctrl + Shift + C` | `Cmd + Shift + C` |
| `openConversationHistory` | Open Conversation History | History | `Ctrl + Y` | `Cmd + Y` |
| `openScheduledTasks` | Scheduled Tasks | Automation | `Ctrl + U` | `Cmd + U` |
| `conversation.selectNext` | Select Next Conversation | History | `Alt + ArrowDown` | `Alt + ArrowDown` |
| `conversation.selectPrevious`| Select Previous Conversation | History | `Alt + ArrowUp` | `Alt + ArrowUp` |
| `openTrajectory` | Open Conversation | History | `Enter` | `Enter` |
| `markAsReadHistory` | Mark as Read | History | `Shift + I` | `Shift + I` |
| `markAsUnreadHistory` | Mark as Unread | History | `Shift + U` | `Shift + U` |
| `deleteHistory` | Delete Conversation | History | `Shift + #` | `Shift + #` |
| `archiveRestoreHistory` | Archive / Restore | History | `Shift + E` | `Shift + E` |

---

## 6. Feature Flags, A/B Testing & User Gating

Antigravity employs a three-tier gating hierarchy that controls UI rendering, agent reasoning depth, and enterprise capabilities.

### 6.1 Google Mendel Experiment Engine (`main_root.formatted.js:41750`)
The React frontend hooks into Mendel flags via `MK(flagName)`:
- **Caching Mechanism:** Flags are fetched via the Connect method `getMendelFlags()` and cached globally for **300,000 ms (5 minutes)**.
- **Active Experiments:**
  1. `enable-browser-subagent-v2`: Enables autonomous headless Chrome subagent via CDP.
  2. `enable-gemini-next-opt-out-switch`: Renders settings toggle to disable preview model weights.
  3. `enable-jetbox-gcert`: Gated authorization requiring Google internal `gcert` tokens.
  4. `enable-jetski-chat`: Master toggle for the multi-turn agent conversation runtime.
  5. `enable-thumbs-down-reroll`: Unlocks step regeneration upon negative user feedback.
  6. `jetbox-usage-tips`: Injects JSON-configured contextual productivity tips in empty states.
  7. `max-best-of-n`: Integer controlling maximum parallel candidate sampling width (default: 8).
  8. `remote-control-setting-enabled`: Activates external control plane API toggles in settings.

### 6.2 User Tiers & Entitlements
The runtime parses user identity from the Language Server's `GetUserStatus` response:
- `USER_TIER_UNSPECIFIED (0)`: Default uninitialized tier.
- `USER_TIER_FREE (1)`: Standard free tier with 5-hour rolling token quotas.
- `USER_TIER_PRO (2)`: Pro subscription tier with elevated limits and priority access.
- `USER_TIER_ENTERPRISE (3)`: Enterprise organization tier billed to a Google Cloud Project ID.
- **Identity Gating:** `is_googler` / `isGoogler` flags bypass external rate limits and unlock internal Cider workspace tools.

### 6.3 Feature Cohort Evaluator (`main_root.formatted.js:15666`)
The `ho(feature, env)` gating function evaluates features before rendering:
```javascript
function isFeatureGated(feature, env) {
  // User cohort check (google internal vs external)
  if (feature.userCohortGating && feature.userCohortGating !== "all") {
    if (feature.userCohortGating === "google" && !env.isGoogleInternal) return true;
    if (feature.userCohortGating === "external" && env.isGoogleInternal) return true;
  }
  // Build environment check (desktop vs web vs cider)
  if (feature.buildEnvGating && !feature.buildEnvGating.includes("all")) {
    if (!feature.buildEnvGating.includes(env.environment)) return true;
  }
  // Layout screen size check (narrow mobile vs wide desktop)
  if (feature.runtimeGating?.supportedScreenSizes) {
    const current = env.isNarrowLayout ? "narrow" : "wide";
    if (!feature.runtimeGating.supportedScreenSizes.includes("all") &&
        !feature.runtimeGating.supportedScreenSizes.includes(current)) {
      return true;
    }
  }
  return false;
}
```

---

## 7. Communication Protocols & gRPC-Web Streaming

### 7.1 Protocol Architecture & Connect Framing
Antigravity utilizes the **Connect Protocol** (an open-source HTTP/1.1 and HTTP/2 RPC protocol compatible with gRPC and gRPC-Web) over loopback HTTPS:
- **Wire Framing:** Connect binary or JSON payloads over HTTP POST.
- **Streaming Messages:** Trajectory updates, terminal streams, and agent observations are delivered as streaming chunks prefixed by a 5-byte Connect-Web framing header:
  - Byte 0: Flags (`0x00` = data frame, `0x02` = end-of-stream trailer frame).
  - Bytes 1–4: 32-bit big-endian unsigned integer indicating message length.
- **Required Headers:**
  - `Connect-Protocol-Version: 1`
  - `Content-Type: application/json` or `application/proto`
  - `x-codeium-csrf-token: <UUID>`

### 7.2 Embedded Protobuf Schema Descriptors
The frontend bundle embeds **81 discrete base64-encoded Protobuf FileDescriptorProto** definitions decoded via `@bufbuild/protobuf`. Key service namespaces include:

1. `exa.language_server_pb.LanguageServerService`:
   - `GetStatus`, `GetUserStatus`, `GetAvailableModels`, `RetrieveUserQuotaSummary`
   - `StartCascade`, `CancelCascade`, `HandleCascadeUserInteraction`
   - `GetCascadeTrajectory`, `GetConversationHistory`, `DeleteConversation`
2. `exa.extension_server_pb.ExtensionServerService`:
   - `LanguageServerStarted`, `OpenFilePointer`, `InsertCodeAtCursor`, `ExecuteCommand`
   - `GetLintErrors`, `OpenDiffZones`, `StartAudioRecording`, `EndAudioRecording`
3. `exa.cortex_pb`:
   - Agent cognitive model: step execution, planning trees, observation parsing, tool dispatch.
4. `exa.unified_state_sync_pb`:
   - Real-time reactive state synchronization between language server and UI.

---

## 8. Reverse Engineering & Extensibility Guide

### 8.1 Safe ASAR Repacking Contract (Desktop UI Modifier)
When injecting custom features into the Antigravity desktop application, the repacking pipeline must satisfy strict host safety rules:
1. **Preserve `app.asar.unpacked`:** Native binaries and packages (e.g. `chrome-devtools-mcp`) must remain untouched in the external unpacked directory.
2. **Read-Only Upstream Preservation:** Never modify the original baseline files in `%LOCALAPPDATA%\Programs\Antigravity` without verifying digital signatures and maintaining an isolated `.bak` copy.
3. **Staging Isolation:** Always assemble modified trees in a temporary directory (e.g., `repack-staging`) and perform atomic replacement only after the running `Antigravity.exe` process has safely exited.

### 8.2 Headless Integration Pattern (Zero-CDP)
Antigravity can be controlled headlessly without launching Electron or driving Chromium DOM via Chrome DevTools Protocol:
1. **Discover Server Credentials:**
   - Scan running processes for `language_server_windows_x64.exe`.
   - Extract `--dynamic_port=<PORT>` and `--csrf_token=<UUID>` from process command line (or from `dist/languageServer.js` spawner log).
2. **Execute Direct Connect-Web Invocations:**
   - Send HTTP/1.1 POST requests directly to `https://127.0.0.1:<PORT>/exa.language_server_pb.LanguageServerService/<METHOD>`.
   - Pass `x-codeium-csrf-token: <UUID>` header.
3. **Stream Trajectories:**
   - Consume server-sent Connect chunks directly from the response stream to observe agent planning, code modifications, and tool calls in real time.

---
*Document generated as part of Antigravity Unleashed reverse engineering milestone.*
