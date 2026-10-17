# Project: Antigravity Unleashed

## Architecture
Antigravity Unleashed is a unified, privacy-sanitized, high-impact open-source showcase monorepo bringing together two complementary systems:
1. **Desktop UI Modifier (`packages/desktop-ui-modifier/`)**: Electron ASAR unpacker/patcher/repacker injecting advanced productivity HUDs into Antigravity desktop (v2.24.0 verified): Quota Watcher HUD (5h & weekly limits), Brain button with conflict detection, API Monitor status popup, Task/Plan Tracker panel, and Reviews Dashboard modal.
2. **Web Control Plane & API Bridge (`packages/web-hub/`)**: Multi-service local web hub (Port 8000), 36-tool FastMCP stdio server (`src/mcp_server.py`), and local OpenAI-compatible `/v1/chat/completions` API bridge (Port 8001) with CDP integration.
3. **Core Governance & Branding (`docs/`, root)**: Dark-mode "Anti-Gravity Core / Orbital Prism" identity (`docs/assets/branding/`), 13 privacy-safe visual showcase screenshots (`docs/assets/screenshots/`), star-magnet `README.md`, candid vibe-coded post-mortem, creator CTAs (`@EinMelih`), launch kit (`docs/LAUNCH_KIT.md`), and governance files (`LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `.gitignore`, `*.example.*`).

## Code Layout
```
antigravity-unleashed/
├── packages/
│   ├── desktop-ui-modifier/      # Antigravity v2.24.0 Electron UI injection & repacker
│   │   ├── src/                  # Injector logic (ui/, ipcHandlers.js, main.js)
│   │   ├── scripts/              # Repack, validate, and restore scripts
│   │   └── tests/                # 14 isolated Node.js and Python test suites
│   ├── web-hub/                  # Web Control Plane, FastMCP server, OpenAI bridge
│   │   ├── src/                  # Backend services, control center, mcp_server.py
│   │   ├── frontend/             # React 19 dashboard UI
│   │   └── tests/                # Unit & regression tests for API & MCP protocol
│   └── ams-framework/            # Standalone autonomy & memory coordinator utilities
├── docs/
│   ├── assets/
│   │   ├── branding/             # logo.svg, logo.png, social-preview.png (1280x640)
│   │   └── screenshots/          # 8 Hub screenshots + 5 Desktop UI modifier screenshots
│   └── LAUNCH_KIT.md             # Reddit, HN, X launch posts & GitHub metadata
├── tests/
│   └── test_privacy_compliance.py# Automated regex & forbidden file scanner
├── .gitignore                    # Comprehensive privacy & runtime ignore rules
├── config.example.json           # Generic sanitized configuration template
├── USER.example.md               # Generic persona & user preference template
├── MEMORY.example.md             # Generic memory & state sync template
├── LICENSE                       # Apache 2.0 with Google Antigravity trademark disclaimer
├── SECURITY.md                   # Security reporting & loopback isolation policy
├── CONTRIBUTING.md               # Contribution guidelines & co-maintainer invitation
└── README.md                     # Flagship English hero showcase & post-mortem
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Monorepo Structure Assembly | Create `packages/desktop-ui-modifier`, `packages/web-hub`, `packages/ams-framework` | M1 | Survey |
| 2 | Codebase Sanitization | Replace hardcoded user profile paths in `ipcHandlers.js` with `%LOCALAPPDATA%`, scrub test fixtures in `chat-components.test.tsx` and `chat-model.test.ts` | M1 | Survey |
| 3 | File Exclusion Enforcement | Exclude all `*.db`, `*.jsonl`, `artifacts/`, `logs/`, `projects/`, `scratch/`, `.runtime/` | M1 | Survey |
| 4 | Clean Git Repo Initialization | Initialize `git init -b main` with single clean initial commit, no historical commits | M1 | Survey |
| 5 | Config Example Templates | Author `config.example.json`, `USER.example.md`, `MEMORY.example.md` | M1 | Survey |
| 6 | Brand Identity Vector (SVG) | Design dark-mode "Anti-Gravity Core / Orbital Prism" `docs/assets/branding/logo.svg` | M2 | Survey |
| 7 | Brand Identity Raster (PNG) | Generate high-res `docs/assets/branding/logo.png` (512x512) | M2 | Survey |
| 8 | Social Preview Banner | Generate exact 1280x640 `docs/assets/branding/social-preview.png` for GitHub/socials | M2 | Survey |
| 9 | Web Hub Screenshots (8 assets) | Migrate and verify 8 existing privacy-safe PNG screenshots from `antigravity-web` | M2 | Survey |
| 10 | Desktop UI Screenshots (5 assets) | Render 5 privacy-redacted Desktop UI feature screenshots (Quota HUD, Brain Button, API Monitor, Task Tracker, Reviews) | M2 | Survey |
| 11 | Centered Hero Header | Author README hero with logo, title, tagline, shields.io badges, quick navigation | M3 | Survey |
| 12 | Visual Tour Section | Embed and explain all 13 screenshots across Web Hub and Desktop UI Modifier | M3 | Survey |
| 13 | Candid Post-Mortem | Author "Why I'm Passing the Torch / Vibe-Coded Post-Mortem" narrative | M3 | Survey |
| 14 | Creator & Community CTAs | Prominent @EinMelih GitHub profile links, Star, Follow, Sponsor, Handover CTAs | M3 | Survey |
| 15 | Viral Launch Kit | Author `docs/LAUNCH_KIT.md` with Reddit, HN, X/Twitter copy & repo metadata | M3 | Survey |
| 16 | Open-Source License & Disclaimer | Author `LICENSE` (Apache 2.0) with explicit Google Antigravity trademark disclaimer | M4 | Survey |
| 17 | Security & Privacy Policy | Author `SECURITY.md` detailing credential safety and local loopback security | M4 | Survey |
| 18 | Contribution Guidelines | Author `CONTRIBUTING.md` inviting co-maintainers and defining PR standards | M4 | Survey |
| 19 | Monorepo .gitignore | Author root `.gitignore` blocking `.db`, `.log`, `.jsonl`, `.conflict`, secrets | M4 | Survey |
| 20 | Portable Desktop Modifier Tests | Run and verify 14 Node.js/Python tests in `packages/desktop-ui-modifier/tests/` | M5 | Survey |
| 21 | Portable Web Hub Security Tests | Run and verify non-destructive Python tests in `packages/web-hub/tests/` | M5 | Survey |
| 22 | Automated Privacy Compliance Scanner | Implement and run `tests/test_privacy_compliance.py` (0 forbidden string matches) | M5 | Survey |
| 23 | Asset Link & Integrity Gate | Verify all image links in README/docs resolve to non-empty valid files | M5 | Survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Monorepo Assembly & Sanitization | Features 1–5: Assemble packages, sanitize code/fixtures, exclude secrets, init clean Git repo | none | DONE |
| M2 | Branding & Visual Showcase Assets | Features 6–10: Vector logo, raster logo, 1280x640 social preview, 8 Hub + 5 Desktop screenshots | M1 | DONE |
| M3 | Star-Magnet README & Launch Kit | Features 11–15: Hero, visual tour, candid post-mortem, @EinMelih CTAs, docs/LAUNCH_KIT.md | M2 | DONE |
| M4 | Open-Source Governance & Safety | Features 16–19: LICENSE with trademark disclaimer, SECURITY.md, CONTRIBUTING.md, .gitignore | M1 | DONE |
| M5 | Final Verification & Privacy Forensics | Features 20–23: Portable tests, automated privacy scanner, image resolution check, git log check | M1, M2, M3, M4 | DONE |

## Interface Contracts
### Desktop UI Modifier ↔ Antigravity Upstream
- Target Version: Exactly pinned to v2.24.0 in `SUPPORTED_UPSTREAM_VERSION`.
- Patch boundary: `packages/desktop-ui-modifier/src/` overlays on extracted ASAR.
- Path Resolution: Environment variables (`process.env.LOCALAPPDATA`, `process.env.APPDATA`) instead of hardcoded user profile paths.

### Web Hub ↔ Antigravity Desktop
- Gateway Port: 8000 (HTTP/REST & Web UI).
- OpenAI Bridge Port: 8001 (`/v1/chat/completions` SSE streaming, `/v1/models`).
- MCP Transport: FastMCP stdio transport (`python -m src.mcp_server`).
- Loopback binding: Strictly bound to `127.0.0.1` / `localhost`.
