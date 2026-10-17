# User Persona & Coding Preferences (Example Template)

> This is a generalized template for configuring your persona, architectural rules, and dialectical preference history with the Antigravity Memory System (AMS). Copy this file to `USER.md` (or `USER.pc.md`) in your working configuration directory.

## 1. Core Profile & Interaction Standards
- **Preferred Communication Language:** English (or your preferred language for explanations and commit messages).
- **Code Standards:**
  - Modern TypeScript / ECMAScript (ES2024+) with strict typing.
  - Python 3.11+ with comprehensive type annotations (`typing.Optional`, `typing.Dict`, `typing.List`).
  - **CSS:** Use Vanilla CSS by default with CSS custom properties (design tokens). Avoid utility frameworks unless requested.
- **Tone & Style:** Concise, technically rigorous, direct, and solution-focused. Avoid conversational filler.

## 2. Dialectical Preference History
Document evolving architectural choices and reasoning over time:
- *2026-01-15:* Adopted strict loopback binding (`127.0.0.1`) across all background microservices for security.
- *2026-03-20:* Standardized on SQLite WAL mode (`PRAGMA journal_mode=WAL`) for concurrent multi-process access.
- *2026-06-10:* Deprecated polling loops in favor of reactive event listeners and WebSocket streams.

## 3. Tooling & Workspace Rules
- Always show exact terminal commands before execution.
- Maintain atomic Git commits with semantic commit message conventions (`feat:`, `fix:`, `docs:`, `refactor:`).
- Always verify changes with unit and integration tests before submitting PRs.
