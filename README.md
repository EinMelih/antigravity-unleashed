<div align="center">

<img src="docs/assets/branding/logo.svg" alt="Antigravity Unleashed" width="96" height="96" />

# Antigravity Unleashed

**Desktop UI modifier (`app.asar`), local OpenAI API bridge, and Web Hub for Google Antigravity IDE.**

[![Stars](https://img.shields.io/github/stars/EinMelih/antigravity-unleashed?style=flat-square&color=8B5CF6)](https://github.com/EinMelih/antigravity-unleashed/stargazers)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Target](https://img.shields.io/badge/Antigravity-v2.24.0-06B6D4?style=flat-square)](packages/desktop-ui-modifier/SUPPORTED_UPSTREAM_VERSION)

</div>

---

> **Status: Open-Source Release / Community Handover**  
> I built this setup for my own daily workflow with Google Antigravity (`v2.24.0`), but I'm no longer actively developing it. Between newer models needing less custom scaffolding, Google shipping the headless ACP server (`agy_acp_server.exe`), and tools like T3 Code handling multi-agent worktrees natively, I moved on.  
> Several parts of this repo were vibe-coded and some features are unfinished. Feel free to fork it, fix rough edges, or open Pull Requests.

> [!CAUTION]
> **⚠️ Disclaimer — Terms of Service & Account Ban Risk (Use at Your Own Risk):**  
> Running the standalone Headless ConnectRPC / gRPC API Bridge (`packages/web-hub`) with an exported Google OAuth token (`JETSKI_OAUTH_TOKEN` / `oauth_token.json`) or using automated third-party agents (OpenClaw, Hermes, etc.) bypasses the official Antigravity IDE client and **violates Google's Terms of Service**.  
> Although an 8-layer anti-detection shield (adaptive pacing, 10-slot workspace rotation, keyword firewall, heartbeat blocker, and 5% quota circuit-breaker) is included, **your Google account can be rate-limited, suspended, or permanently banned at any time**. The authors assume zero liability for account suspensions or data loss.

---

## Overview

This monorepo is cleanly split into **two independent operating modes**:
- **Windows Desktop (`packages/desktop-ui-modifier`)** — Pure Electron UI mod (`app.asar`). Localhost background servers (`:8000` / `:8001`) and the floating API badge are **OFF by default** so your desktop IDE stays 100% clean (with an optional switch if you ever want to turn them on).
- **Linux / Docker Headless API (`packages/web-hub`)** — Standalone 24/7 Direct-ConnectRPC OpenAI-compatible API server (`:8001/v1`) + pure **API-Logs & Shield Monitor (`:8000/#/api-logs`)** without any Electron/GUI or legacy chat bloat.

```text
antigravity-unleashed/
├── install.bat / install.ps1       # Windows setup: configures ~/.gemini/config & patches app.asar
├── packages/
│   ├── desktop-ui-modifier/        # Clean Electron v2.24.0 app.asar UI mod (localhost autostart OFF by default)
│   ├── web-hub/                    # Headless Linux Docker API (:8001) + pure API-Logs Monitor (:8000)
│   └── ams-framework/              # Global agent rules, memory compiler (USER/MEMORY) & helper skills
└── tests/                          # Privacy & portability verification suite
```

### 1. Desktop UI Modifier (`packages/desktop-ui-modifier` — Windows)

Patches Antigravity's local Electron bundle (`%LOCALAPPDATA%\Programs\Antigravity\resources\app.asar`) to inject custom UI controls directly into the IDE's composer bar **without starting any background localhost servers by default**:

- **`Unleashed` Quick Menu (`Ctrl+Shift+B`)** — Adds an Orbital Prism **`Unleashed`** button to the bottom composer bar for quick access to Git sync and patch logs.
- **Live Quota Watcher (`src/ui/quotaWatcher.js`)** — Intercepts `GetUserStatus` / `RetrieveUserQuotaSummary` responses in the renderer to show live 5-hour and weekly quota percentages (`G: 100% | C: 100%`) in the composer bar and falls back to Gemini when Claude quota hits `0%`.
- **Task & Plan Side-Panel (`src/ui/taskTracker.js`)** — Toggleable slide-out panel (`Ctrl+Shift+P`) synced with the active session's `brain/<id>/task.md`, session notes (`notes.txt`), token/cache stats, and GitHub PR/Issue lists.
- **Brain Folder & Conflict Indicator (`src/ui/reviewsDashboard.js`)** — One-click button in the composer bar to open the current conversation's local `brain/` folder in Explorer, pulsing orange when `.conflict` files are detected.
- **Transactional ASAR Repacker (`scripts/repack_and_restart.py`)** — Verifies upstream SHA-256 hashes (`UPSTREAM_COMPATIBILITY.json`), compiles `src/ui/*.js` into `src/preload.js`, backs up `app.asar` + `app.asar.unpacked`, extracts and repacks via `@electron/asar`, and rolls back automatically if anything fails.
- **Optional Localhost Switch (Off by Default):**
  - Localhost Web-Hub (`:8000`) and API Bridge (`:8001`) are **disabled by default** on Windows (`"web_hub_enabled": false`, `"hub_autostart_enabled": false`, `"api_bridge_enabled": false`).
  - If you explicitly want to start them on Windows, run `powershell -ExecutionPolicy Bypass -File packages/web-hub/start_services.ps1 -EnableLocalHub -EnableLocalApi` or set `"web_hub_enabled": true` in `~/.gemini/config/antigravity-hub/config.json`.

### 2. Headless Linux Docker API & API-Logs Server (`packages/web-hub`)

Designed to run 24/7 in a lightweight Linux Docker container (`python:3.12-slim` + standalone `language_server_linux_x64`, zero Electron/Xvfb overhead):

- **Direct-ConnectRPC OpenAI API (`:8001/v1/chat/completions`, `/v1/models`)** — Full OpenAI SDK, **OpenClaw** (`/openclaw/v1`), and **Hermes Agent** (`/hermes/v1`) compatibility with SSE streaming, automatic Markdown-fenced `tool_calls` extraction, and headless Google OAuth `refresh_token` auto-renewal (`/v1/auth/status`, `/v1/auth/token`).
- **8-Layer Anti-Detection Shields (`src/antigravity_shields.py`)** — 0ms Heartbeat Blocker (`HEARTBEAT_OK`), Keyword Firewall (scrubs `OpenClaw`, `Hermes`, `SOUL.md`, `HEARTBEAT.md`), `AGENTS.md` workspace rule injection, Smart Adaptive Pacing, 10-slot workspace pool (`ws-00`..`ws-09`) with multi-turn session affinity, and 5% Quota Circuit-Breaker (`HTTP 429` for automatic client model fallback).
- **Pure API-Logs Monitor (`:8000/#/api-logs`)** — In `headless_linux` / Docker mode, the web interface strips out all legacy Studio/Chat views and renders **exclusively the API-Logs, Token/Quota Telemetry, and Shield Controls**.

### 3. AMS Memory Framework & Multi-PC Cloud Sync (`packages/ams-framework`)

- Compiles host-specific `USER.pc.md` and `MEMORY.pc.md` notes into `USER.md` and `MEMORY.md` under `~/.gemini/config/` while enforcing character budgets.
- **Usage Data Persistence (`usage_stats.json`)** — Automatically aggregates token counts, message counts, active chat sessions, skill counts, and per-model usage per device (`hosts.<hostname>`) plus a combined multi-device total (`combined`) inside `~/.gemini/config/usage_stats.json` on every sync.
- **1-Click Private GitHub Backup & Multi-PC Import (`sync_config.py` + UI Modal)** — Open the **`Unleashed`** Quick Menu (`Ctrl+Shift+B` -> **Manuelles Git Sync & Cloud-Backup**) or press `Ctrl+Shift+P` -> **Git Sync**:
  1. **First PC (Setup):** Click **`🔑 1. GitHub Login`** (authenticates `gh` via browser), then click **`🔒 2. Privates Repo erstellen & verbinden`**. This creates a private `antigravity-config` repository on your GitHub account and pushes your memory, skills, and `usage_stats.json` (while `.gitignore` excludes local API keys in `antigravity-hub/config.json`).
  2. **Second PC / Laptop (Import & Restore):** After running `install.bat`, open the Git Sync modal, enter `YourGitHubUser/antigravity-config` (or paste the repo URL), and click **`📥 Auf 2. PC importieren (Pull & Restore)`** (or run `python ~/.gemini/config/scripts/sync_config.py --import-remote YourGitHubUser/antigravity-config`). Any existing local default files are backed up first to `~/.gemini/config/backups/pre-import-<timestamp>/`, the remote history is merged automatically, and `usage_stats.json` combines usage across all synced PCs.
  3. **Optional Background Auto-Sync:** In the `Ctrl+Shift+B` Quick Menu, click **`Auto-Sync (Config)`** to toggle automatic background syncing of `~/.gemini/config` every 15 minutes without touching your coding workspace repositories.

---

## Quick Start

### A. Windows Desktop UI Modifier Only (`app.asar`)
- **Windows 10/11** with **Google Antigravity IDE `v2.24.0`** installed in `%LOCALAPPDATA%\Programs\Antigravity`
- **Python 3.11+** and **Node.js 20+** (`node` and `npx` on `PATH`)

```powershell
git clone https://github.com/EinMelih/antigravity-unleashed.git
cd antigravity-unleashed
python packages/desktop-ui-modifier/scripts/build_preload.py
python packages/desktop-ui-modifier/scripts/repack_and_restart.py
```

### B. Headless Linux / Docker API Server (`packages/web-hub`)

1. **Export your Google OAuth token on a logged-in machine (one-time):**
   ```bash
   python packages/web-hub/scripts/export_linux_auth_seed.py --output-dir ./docker-data
   ```
2. **Start the Docker container on your Linux server:**
   ```bash
   cd packages/web-hub
   docker compose up -d --build
   ```
3. **Read your generated API key & connect OpenClaw / Hermes / OpenAI SDK:**
   ```bash
   docker compose logs | grep -E "API KEY|GOOGLE AUTH"
   # API Endpoint:  http://<linux-server-ip>:8001/v1 (or /openclaw/v1, /hermes/v1)
   # Pure API-Logs: http://<linux-server-ip>:8000/dashboard/react/index.html#/api-logs
   ```

---

## Known Limitations & What's Unfinished

If you want to contribute or build on top of this, here is where things stand:

- **Upstream Version Pinning (`v2.24.0`)**: The ASAR injector checks SHA-256 hashes of `dist/main.js`, `dist/ipcHandlers.js`, `dist/preload.js`, `dist/updater.js`, and `dist/utils.js`. When Google ships a new Antigravity version, `SUPPORTED_UPSTREAM_VERSION` and `UPSTREAM_COMPATIBILITY.json` need to be rebased.
- **Renderer Selectors**: Several UI hooks rely on DOM selectors (`button[aria-label="Add context"]`, `[data-testid="settings-button"]`) and CDP script evaluation that can break if upstream changes its React layout.
- **Windows-Specific Process Management**: Process tree discovery, WMI/CIM queries, and PowerShell service launchers (`start_services.ps1`) are built for Windows and haven't been ported to macOS or Linux.
- **Localization (`src/ui/i18n.js`)**: The injected UI defaults to **English (`en`)** out of the box and includes a 1-click **English ↔ Deutsch (`de`)** toggle inside the `Ctrl+Shift+B` Quick Menu (`🌐 Language`). Some backend error messages or legacy log strings may still appear in German.

Pull Requests, cleanups, and ports to newer Antigravity versions are very welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Contact & Maintainer

Created by **[@EinMelih](https://github.com/EinMelih)**.

- If you find the code useful, feel free to leave a ⭐ on the repo.
- For questions, collaborations, or if you want to help maintain the project, open an [Issue](https://github.com/EinMelih/antigravity-unleashed/issues) or reach out via my GitHub profile **[@EinMelih](https://github.com/EinMelih)**.

---

## License & Disclaimer

Released under the [MIT License](LICENSE).  
*Unofficial community project. Not affiliated with, endorsed by, or sponsored by Google LLC.*
