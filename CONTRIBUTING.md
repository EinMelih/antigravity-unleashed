# Contributing to Antigravity Unleashed

Welcome, and thank you for your interest in contributing to **Antigravity Unleashed**! 

Whether you are fixing a bug, adding new MCP capabilities, updating Desktop UI patches for new upstream versions, improving documentation, or stepping up to help steer the project, we are thrilled to have you here.

---

## 1. Project Philosophy & Maintainer Handover

Antigravity Unleashed started as an ambitious, vibe-coded exploration pushing Google Antigravity and Electron desktop interfaces to their absolute limits. As the AI landscape evolves—with frontier reasoning models capable of native multi-step orchestration, Google's introduction of the headless Agent Control Protocol (`agy_acp_server.exe`), and multi-agent harnesses like T3 Code—original creator `@EinMelih` is transitioning active development to the broader open-source community.

### 🌟 Step Up as a Co-Maintainer or Sponsor
We are actively looking for passionate community members to step up as **co-maintainers**, **code owners**, or **sponsors**:
- **Co-Maintainers:** If you have experience with Electron ASAR internals, FastAPI/FastMCP, or React dashboards and want commit rights to shepherd issues and PRs, please reach out!
- **Collaborations & Sponsorships:** To sponsor ongoing infrastructure, propose commercial collaborations, or connect directly with the original author, visit **[@EinMelih on GitHub](https://github.com/EinMelih)** or open a discussion thread.

---

## 2. Code of Conduct

We are committed to providing a friendly, safe, and welcoming environment for everyone, regardless of experience level, background, or identity.
- Be respectful, constructive, and empathetic in all interactions.
- Focus on what is best for the community and users.
- Provide actionable, polite feedback during code reviews.

---

## 3. Development Setup

### 3.1 Prerequisites
- **Git** (version 2.30+)
- **Node.js** (v18.x or v20.x LTS) & **npm**
- **Python** (v3.10, v3.11, or v3.12)
- (Optional) Google Antigravity Desktop v2.24.0 for live Electron UI verification.

### 3.2 Monorepo Layout
```
antigravity-unleashed/
├── packages/
│   ├── desktop-ui-modifier/      # Electron ASAR patcher & injected UI HUDs
│   ├── web-hub/                  # Web Control Plane, FastMCP server & OpenAI bridge
│   └── ams-framework/            # Autonomy & memory coordination utilities
├── docs/                         # Brand identity, screenshots, and launch kit
├── tests/                        # Monorepo privacy & compliance test harness
└── config.example.json           # Exemplary configuration template
```

### 3.3 Initial Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/EinMelih/antigravity-unleashed.git
   cd antigravity-unleashed
   ```

2. Set up the Python virtual environment and Web Hub dependencies:
   ```bash
   cd packages/web-hub
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate

   pip install -r requirements.txt
   npm install --prefix frontend
   cd ../..
   ```

3. Set up Desktop UI Modifier dependencies:
   ```bash
   cd packages/desktop-ui-modifier
   npm install
   cd ../..
   ```

4. Configure local environment:
   ```bash
   cp config.example.json config.json
   ```
   *Note: `config.json` is ignored by Git. Never commit private credentials or personal tokens.*

---

## 4. Coding Standards

To keep the codebase maintainable, fast, and secure, please adhere to these conventions:

### 4.1 Frontend & CSS
- **Vanilla CSS by Default:** Favor clean, modern Vanilla CSS with CSS custom properties (`var(--...)`) for injected desktop HUDs and UI components. Avoid heavy utility CSS frameworks unless already integrated in specific packages.
- **Design Consistency:** Match the dark-mode aesthetic (deep obsidian `#090a11`, neon cyan `#00f0ff`, ultraviolet `#8b5cf6`, and glassmorphic translucent backdrops).

### 4.2 Python
- Adhere to **PEP 8** guidelines.
- Use explicit type annotations (`typing`) for all public function signatures.
- All network services must strictly bind to loopback (`127.0.0.1` / `localhost`). Never bind to `0.0.0.0`.

### 4.3 JavaScript & Node.js
- Use modern ECMAScript standards with clean `async`/`await` patterns.
- Always include robust error handling and fail-safes around file system operations and ASAR patching routines.
- Resolve user paths dynamically using standard environment variables (`process.env.LOCALAPPDATA`, `process.env.APPDATA`, `os.homedir()`). Never hardcode Windows usernames or absolute drive letters.

### 4.4 Privacy & Redaction Discipline
- **Zero Credentials:** Never commit API keys, GitHub tokens (e.g., PATs or OAuth tokens), or authorization headers.
- **Zero Local State Files:** Do not commit SQLite databases (`*.db`), chat logs (`*.jsonl`), DOM dumps, or personal memory files (`USER.md`, `MEMORY.md`).
- Ensure all automated tests run safely without reading or altering files outside the working directory.

---

## 5. Testing & Verification

Before submitting a Pull Request, verify that all test suites pass:

1. **Monorepo Privacy & Compliance Test:**
   ```bash
   python tests/test_privacy_compliance.py
   ```
   *Ensures zero private paths, leaked credentials, or forbidden files exist in the repository.*

2. **Web Hub Test Suite:**
   ```bash
   cd packages/web-hub
   pytest tests/
   cd ../..
   ```

3. **Desktop UI Modifier Test Suite:**
   ```bash
   cd packages/desktop-ui-modifier
   npm test
   cd ../..
   ```

---

## 6. Git Workflow & Pull Request Process

### 6.1 Branch Naming Conventions
- `feat/feature-name` — New capabilities, MCP tools, or UI enhancements
- `fix/bug-description` — Bug fixes and regression repairs
- `docs/topic-name` — Documentation improvements and guides
- `refactor/scope` — Code quality improvements without behavior changes
- `chore/task-name` — Tooling, dependency, or configuration updates

### 6.2 Commit Message Format
We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:
```text
<type>(<scope>): <short imperative summary>

[optional longer body explaining context and rationale]

[optional issue reference, e.g. Closes #12]
```
*Examples:*
- `feat(mcp): add local model inspection tool`
- `fix(quota): handle null expiry timestamp gracefully`
- `docs(readme): add troubleshooting section for electron repacking`

### 6.3 Pull Request Checklist
When opening a PR, ensure you have completed the following:
- [ ] Your code complies with the project's coding standards and privacy requirements.
- [ ] No personal paths (e.g. `C:\Users\...`), tokens, `.db`, `.log`, or `.jsonl` files are present in the diff.
- [ ] All relevant test suites pass locally.
- [ ] Documentation has been updated to reflect any new features or API changes.
- [ ] The PR description clearly explains the **what**, **why**, and **how** of your changes.

---

## 7. Licensing of Contributions

By submitting a Pull Request to Antigravity Unleashed, you agree that your contributions will be licensed under the project's [Apache License 2.0](LICENSE).
