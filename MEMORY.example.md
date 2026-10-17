# Persistent Memory & System State (Example Template)

> This is a generalized template demonstrating how persistent state, multi-agent coordination records, and consolidated lessons learned are stored in the Antigravity Memory System (AMS). Copy this file to `MEMORY.md` (or `MEMORY.pc.md`) in your working configuration directory.

## 1. Environment & Infrastructure Index
- **Host Architecture:** Windows 11 / Linux container runtime.
- **Microservices Deployment:**
  - Web Hub Gateway: `http://127.0.0.1:8000`
  - Local OpenAI API Bridge: `http://127.0.0.1:8001`
  - Multi-Session Manager: `http://127.0.0.1:8002`
  - CDP Auto-Healer: `http://127.0.0.1:8007`
  - Watchdog Monitor: `http://127.0.0.1:8010`
- **FastMCP Transport:** `python -m src.mcp_server` (Standard I/O, 36 tools).

## 2. Synchronization State & Multi-Agent Metadata
- **Git Sync Strategy:** Atomic branch creation per feature wave with verified merge gates.
- **Active Conflict Detection:** Monitored via the Desktop UI Modifier Brain button with animated pulse alerts on merge conflicts.
- **Memory Compaction Budget:**
  - `USER.md`: Target < 1,500 characters (excluding code blocks).
  - `MEMORY.md`: Target < 2,500 characters (excluding comments).

## 3. Technical Lessons Learned (Consolidated Knowledge)
Document reusable solutions discovered during development:
- **Electron ASAR Repacking:** Always acquire an exclusive file lock prior to unpacking `app.asar`. Terminate only target application process trees matching the installation path to avoid disrupting unrelated background services.
- **CDP Injection:** Hook `window.fetch` at preload time to intercept telemetry endpoints without altering application network stacks.
- **OpenAI Streaming Compatibility:** Deliver SSE chunks matching `chat.completion.chunk` specifications with explicit `data: [DONE]\n\n` termination.
