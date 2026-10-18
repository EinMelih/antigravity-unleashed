# Antigravity Unleashed — Repository Guidelines

## Architecture & Packages
- **`packages/web-hub`**: Local control plane, dashboard (`:8000`), OpenAI-compatible API bridge (`:8001`), Direct ConnectRPC pool (`src/rpc_pool.py`), 8 Anti-Ban Shields (`src/antigravity_shields.py`), and 2-stage source fingerprinting (`src/api_audit_logger.py`).
- **`packages/desktop-ui-modifier`**: Windows Antigravity desktop Electron modifier (`server.asar` / UI patches).

## Git & Development Workflow
Für alle Git-Commits gilt verbindlich der **„Sweet-Spot Senior-Dev-Stil“**:
1. **Commit-Nachricht:** Immer nur EINE kurze, knackige Zeile auf Englisch mit **3–6 Wörtern** (z. B. `fix(inbox): pause sync on ad view` oder `fix rate limiter and session vault`).
2. **Kein AI-Slop:** Schreibe NIEMALS mehrzeilige Commit-Bodies, Aufzählungen oder lange Erklärtexte in die Commit-Message.
3. **Keine extrem vagen Nachrichten (`fix stuff`):** Immer das betroffene Modul + was gemacht wurde in 3–6 Wörtern nennen, damit Mensch und KI in `git log --oneline` sofort Bescheid wissen.
4. **Sauberes Staging:** Nutze niemals `git add -A` oder `git add .`, sondern stage immer nur exakt die Dateien, die du in deinem Task selbst bearbeitet hast (`git add <pfade>`), prüfe vorab mit `git diff --cached --stat` und committe + pushe dann.
