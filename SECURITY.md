# Security Policy & Isolation Architecture

The Antigravity Unleashed maintainers and community take security, local privacy, and user isolation seriously. This document describes our security guarantees, local loopback isolation architecture, credential handling policies, and instructions for reporting vulnerabilities.

---

## 1. Supported Versions & Scope

| Component | Version / Scope | Security Support Status |
| :--- | :--- | :--- |
| **Antigravity Unleashed Monorepo** | Latest commit on `main` branch | :white_check_mark: Actively Supported |
| **Target Upstream Antigravity** | v2.26.0 (Electron Desktop) | :white_check_mark: Verified Baseline |
| **Web Hub (`packages/web-hub`)** | Python 3.10+ / React 19 / FastMCP | :white_check_mark: Actively Supported |
| **Desktop Modifier (`packages/desktop-ui-modifier`)** | ASAR patcher & UI overlays | :white_check_mark: Actively Supported |
| **Legacy Releases / Forks** | Untracked forks or unreleased tags | :x: Not Supported |

---

## 2. Local Loopback Isolation Architecture

Antigravity Unleashed is architected strictly as an **in-process and local-workstation developer utility**. By design, none of its services are intended to be exposed to external local-area networks (LAN) or the public Internet.

### 2.1 Loopback-Only Network Binding (`127.0.0.1`)
- **Web Control Plane (Port 8000):** The web dashboard and REST API bind strictly to `127.0.0.1` (`localhost`). Any attempt to bind to `0.0.0.0` or public network interfaces is forbidden by default configuration.
- **OpenAI API Bridge (Port 8001):** The `/v1/chat/completions` and `/v1/models` emulation proxy binds strictly to `127.0.0.1`.
- **FastMCP Server (`src/mcp_server.py`):** Utilizes standard I/O streams (`stdio`) for process communication. It does not open network sockets or listen on external TCP/UDP ports.
- **Chrome DevTools Protocol (CDP) & Browser Shim:** Connects solely to local loopback debugging ports opened by the local Antigravity Electron runtime.

### 2.2 Host Header Validation & Anti-DNS Rebinding
- The HTTP servers validate incoming `Host` request headers and drop requests that do not match `localhost`, `127.0.0.1`, or configured loopback aliases.
- This mitigates DNS rebinding attacks that attempt to exploit browser-based access to local services from malicious third-party websites.

### 2.3 Warning on Public Exposure & Reverse Proxies
If you choose to route external traffic to Antigravity Unleashed (for example, via Tailscale, ngrok, Cloudflare Tunnels, or an Nginx/Caddy reverse proxy), **you assume full responsibility** for implementing robust authentication (mTLS, API bearer tokens, or HTTP Basic Auth) and TLS encryption. **Never expose port 8000 or 8001 directly to the open Internet without an authenticated security gateway.**

---

## 3. Credential, Token & Privacy Protection Policy

### 3.1 Strict Anti-Leak Principles
- **No Hardcoded Secrets:** No API keys (e.g. OpenAI, Anthropic, Gemini, GitHub Personal Access Tokens), session cookies, or private credentials must ever be committed to the repository.
- **Configuration Templates:** All configurations containing sensitive tokens must use `.example` templates (`config.example.json`, `.env.example`). Real configuration files (`config.json`, `.env`) are permanently ignored via `.gitignore`.
- **Automated Memory Isolation:** Personal AI memory files (`USER.md`, `MEMORY.md`, and `knowledge/` vaults) contain personal user preferences, dialectical history, and private work context. These files are strictly excluded from source control. Example templates (`USER.example.md`, `MEMORY.example.md`) are provided for educational and onboarding purposes only.

### 3.2 Token Redaction in Telemetry & Logs
- The Web Hub and Desktop UI Modifier employ runtime redaction filters to prevent tokens and authorization headers from appearing in console logs, error stack traces, or diagnostic dumps.
- Known token prefixes (including `sk-`, `ghp_`, GitHub OAuth tokens, `github_pat_`, and bearer authorization headers) are automatically masked before any payload is recorded or displayed in the UI monitor.

### 3.3 Transactional ASAR Modification & Fail-Safe Backups
- The Desktop UI Modifier operates on Electron's `app.asar` archive.
- To prevent host application corruption, the unpack-patch-repack workflow enforces **transactional staging**: modifications are compiled into a temporary staging directory and sanity-checked before swapping into production.
- A pristine backup copy (`app.asar.backup`) is created prior to any file manipulation. In the event of a validation failure or version mismatch, the modification fails fast and provides an automated rollback mechanism (`scripts/restore.js`).

---

## 4. Reporting a Security Vulnerability

If you discover a potential security flaw, vulnerability, or accidental privacy exposure in Antigravity Unleashed, please report it promptly through private channels. **Do not create public GitHub issues or public pull requests for security vulnerabilities.**

### 4.1 How to Submit a Vulnerability Report
1. **GitHub Security Advisory (Preferred):**
   Navigate to the repository on GitHub, open the **Security** tab, and click **"Report a vulnerability"** to submit a private draft advisory.
2. **Direct Maintainer Contact:**
   If GitHub Advisories are unavailable, contact the project maintainer directly via GitHub profile message or email at:
   - **Maintainer:** `@EinMelih` ([https://github.com/EinMelih](https://github.com/EinMelih))
   - **Subject Line:** `[SECURITY] Antigravity Unleashed Vulnerability Report`

### 4.2 Information to Include
To help us triage and resolve the issue quickly, please provide:
- A descriptive summary of the vulnerability and its potential impact.
- Clear, step-by-step reproduction instructions or a minimal Proof of Concept (PoC).
- Affected components (e.g., Web Hub API bridge, Desktop ASAR patcher, MCP server).
- Operating system and environment details (Windows, Node.js version, Python version).
- Proposed remediation or patch, if available.

### 4.3 Triage & Disclosure Timeline
- **Acknowledgement:** We aim to acknowledge receipt of security reports within **48 hours**.
- **Assessment & Status Updates:** We will provide an initial assessment and timeline within **7 business days**.
- **Coordinated Disclosure:** We kindly request that you adhere to coordinated vulnerability disclosure practices, giving maintainers reasonable time to issue a fix and release a security advisory before public disclosure.
