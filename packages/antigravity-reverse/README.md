# Antigravity Reverse Engineering Toolkit

[![Upstream Version](https://img.shields.io/badge/Antigravity-v2.24.0-blue.svg)](https://github.com/EinMelih/antigravity-unleashed)
[![Python Tests](https://img.shields.io/badge/tests-23%20passed-brightgreen.svg)]()
[![Reconstructed Services](https://img.shields.io/badge/Connect%20Services-16-purple.svg)]()
[![RPC Methods](https://img.shields.io/badge/RPC%20Methods-650-orange.svg)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

An exhaustive, reproducible reverse engineering specification, reconstructed Protobuf/gRPC-Web schema repository, standalone zero-CDP headless client library, command-line interface, and automated extraction pipeline for **Google Antigravity IDE `v2.24.0`**.

> [!IMPORTANT]
> **Frozen Clean Baseline (`v2.24.0`) — Do Not Modify In-Place:**  
> This folder (`packages/antigravity-reverse`) represents a clean, unmodified 1:1 reverse-engineering snapshot of **Google Antigravity `v2.24.0`**. Do **not** alter the extracted dumps, schemas, catalogs, or baseline scripts in this directory. For experimental modifications, custom builds, or future upstream versions, create a separate, explicitly named directory (e.g., `packages/antigravity-reverse-v2.25.0` or `packages/antigravity-direct-api`).

---

## Architecture Overview

The package decomposes Google Antigravity into five architectural pillars:

```
packages/antigravity-reverse/
├── catalog/                      # Machine-readable JSON specifications
│   ├── ui_internals.json         # 36 IPC channels, 56 actions, 84 feature flags, 4 user tiers
│   ├── rpc_schema.json           # 16 services, 650 RPC methods, 3,028 messages, 445 enums
│   └── binary_analysis.json      # 29 CLI flags, 18 env vars, 342 ConnectRPC methods, SQLite schemas
├── docs/                         # In-depth architectural documentation
│   ├── ARCHITECTURE.md           # Multi-process architecture, IPC routing matrix, lifecycle
│   ├── GRPC_WEB_PROTOCOL.md      # Connect-Web framing, streaming trajectories, 159 step types
│   └── LANGUAGE_SERVER.md        # Language server binary internals, CSRF auth, local DBs, ACP
├── proto/                        # 104 reconstructed .proto schema files (92 packages + 12 mirrors)
│   ├── language_server.proto     # Primary language server RPC definitions (342 methods)
│   ├── cortex.proto              # Model reasoning, thinking, and plan execution schemas
│   ├── trajectory.proto          # Agent trajectory state machine and 159 step types
│   ├── api_server.proto          # Local API server schemas (114 methods)
│   ├── extension_server.proto    # IDE extension bridge schemas (53 methods)
│   ├── jetski_service.proto      # Google Cloud upstream AI companion integration
│   └── host_bridge.proto         # Electron host bridge update and provisioning RPCs
├── extracted/                    # Deobfuscated and formatted source tree
│   ├── electron/                 # 26 Electron main modules (main.js, preload.js, ipcHandlers.js, etc.)
│   └── frontend/                 # 111,933 lines beautified React bundle + ES module slices
├── src/                          # Standalone headless client library & CLI
│   ├── __init__.py               # Package exports
│   ├── client.py                 # AntigravityClient: Direct Connect-Web HTTP/1.1 client
│   └── cli.py                    # Standalone CLI tool (status, models, quota, conversations)
├── scripts/                      # Reproducible automated extraction pipeline
│   ├── extract_all.py            # Single-command end-to-end extraction orchestrator
│   ├── extract_ui_internals.py   # Generates catalog/ui_internals.json
│   ├── extract_proto_schemas.py  # Decodes descriptors and regenerates proto/ + rpc_schema.json
│   └── extract_binary_analysis.py# Inspects language_server.exe and generates binary_analysis.json
└── tests/                        # Programmatic verification test suite (23 tests)
    ├── test_ui_internals.py      # UI internals schema assertions
    ├── test_catalogs.py          # Catalog thresholds and schema completeness
    ├── test_proto_syntax.py      # Proto3 syntax validation and balanced braces
    ├── test_headless_client.py   # Live read-only calls to active Language Server
    └── test_host_safety.py       # Host integrity (%LOCALAPPDATA% pristine, zero terminations)
```

---

## Machine-Readable Catalogs

| Catalog File | Metrics | Key Content |
|---|---|---|
| `catalog/ui_internals.json` | 36 IPC channels, 56 actions, 84 feature flags, 4 user tiers | Exact channel names, call directions (`renderer-to-main`, `push-event`), source line numbers in `dist/ipcHandlers.js`, shortcut modifiers, Mendel flags, and tier enums (`FREE`, `PRO`, `ENTERPRISE`). |
| `catalog/rpc_schema.json` | 16 services, 650 methods, 3,028 messages, 445 enums | Full Connect-Web / gRPC-Web method signatures, request/response type mappings, field numbers, wire types, and streaming flags reconstructed from 92 embedded `FileDescriptorProto` descriptors. |
| `catalog/binary_analysis.json` | 29 CLI flags, 18 env vars, 342 ConnectRPC methods | Complete disassembly findings for `language_server.exe`, `webm_encoder.exe`, `elevate.exe`, `agy_acp_server.exe`, SQLite/FTS5 database DDLs, prompt assembly templates, and upstream GCP endpoints. |

---

## Reconstructed Protobuf Schemas (`proto/`)

The `proto/` directory houses **104 self-contained `.proto` files** reconstructed with 100% syntactically valid proto3/proto2 definitions and resolved cross-file `import` statements.

Primary entry-point mirrors:
- `proto/language_server.proto`: Core `exa.language_server_pb.LanguageServerService` containing all 342 methods for chat, code completion, cascade lifecycle, tool execution, model switching, and MCP integration.
- `proto/cortex.proto`: Cortex reasoning engine and agent thinking steps.
- `proto/trajectory.proto`: Full taxonomy of all 159 agent trajectory step types.
- `proto/api_server.proto`: Local API server service with 114 endpoints.
- `proto/extension_server.proto`: IDE bridge service with 53 endpoints.
- `proto/jetski_service.proto`: Upstream Google Cloud AI Companion protocol.
- `proto/host_bridge.proto`: Electron host updater and native bridge.

---

## Headless Client Library (`src/client.py`)

The `AntigravityClient` communicates **directly** with the local Antigravity Language Server over loopback HTTPS (`https://127.0.0.1:<PORT>/...`) using Connect Protocol v1 and JSON framing. It requires **no Electron renderer, no Chrome DevTools Protocol (CDP), and no DOM clicking**.

### Key Features
- **Auto-Discovery:** Automatically discovers the active Language Server port and cryptographically random CSRF token from the running OS process command line.
- **Self-Signed TLS:** Transparently handles in-memory self-signed TLS certificates generated by `language_server.exe`.
- **Connect-Web Framing:** Uses `Connect-Protocol-Version: 1`, `Content-Type: application/json`, and `x-codeium-csrf-token: <TOKEN>` headers.
- **Read-Only SQLite Storage:** Safely queries `conversation_summaries.db` in `?mode=ro` with `PRAGMA query_only = ON`.

### Quickstart Example

```python
from src.client import AntigravityClient

# Initialize client (auto-discovers port and CSRF token)
client = AntigravityClient()

# 1. Check server health
health = client.get_status()
print("Health:", health)

# 2. Inspect authenticated user identity & tier
user_stat = client.get_user_status()
u = user_stat["userStatus"]
print(f"User: {u['name']} ({u['email']}), Tier: {u['planStatus']['planInfo']['teamsTier']}")

# 3. Query available LLM models
models_resp = client.get_available_models()
models = models_resp["response"]["models"]
print(f"Available models ({len(models)}):", list(models.keys()))

# 4. Query live 5-hour and weekly token limits
quota = client.get_user_quota_summary()
for group in quota["response"]["groups"]:
    print(f"\nGroup: {group['displayName']}")
    for b in group["buckets"]:
        print(f"  - {b['displayName']}: {b['remainingFraction'] * 100:.1f}% remaining (resets at {b['resetTime']})")

# 5. List recent conversations from local SQLite database
conversations = client.list_conversations(limit=5)
for c in conversations:
    print(f"[{c['last_modified_time']}] {c['conversation_id']} — {c['title']}")

# 6. Retrieve trajectory steps for a cascade session
if conversations:
    traj = client.get_cascade_trajectory(conversations[0]["conversation_id"])
    print("Trajectory steps:", traj.get("numTotalSteps"))
```

---

## Headless CLI Tool (`src/cli.py`)

The toolkit provides a command-line interface for inspecting and operating Antigravity:

```bash
# Display server health, user identity, and plan tier
python src/cli.py status

# List all available AI models with provider, max tokens, and internal tags
python src/cli.py models

# Display live user 5-hour and weekly quota progress bars
python src/cli.py quota

# List recent conversation summaries from local SQLite storage
python src/cli.py conversations --limit 10

# Inspect cascade trajectory steps for a session
python src/cli.py trajectory <CASCADE_UUID>

# Output raw JSON for pipeline integration (compatible with jq)
python src/cli.py quota --json
python src/cli.py models --json
```

### Sample CLI Quota Output

```text
============================================================
ANTIGRAVITY USER QUOTA SUMMARY
============================================================

[Group] Gemini Models
  Info: Models within this group: Gemini Flash, Gemini Pro
  * Weekly Limit Remaining (weekly):
    [=====================    ]  83.8% remaining
    Resets at: 2026-10-23T22:01:00Z
  * Five Hour Limit Remaining (5h):
    [====================     ]  81.9% remaining
    Resets at: 2026-10-18T03:09:04Z

[Group] Claude and GPT models
  Info: Models within this group: Claude Opus, Claude Sonnet, GPT-OSS
  * Weekly Limit Remaining (weekly):
    [=========================] 100.0% remaining
    Resets at: 2026-10-24T14:59:09Z
  * Five Hour Limit Remaining (5h):
    [=========================] 100.0% remaining
    Resets at: 2026-10-18T06:29:06Z
```

---

## Automated Extraction Pipeline (`scripts/extract_all.py`)

A single command completely extracts, deobfuscates, decodes Protobuf descriptors, and regenerates all `.proto` files and machine-readable catalogs:

```bash
# Run extraction pipeline with default auto-detection
python scripts/extract_all.py

# Run extraction targeting a custom Antigravity installation
python scripts/extract_all.py --antigravity-dir "C:/path/to/Antigravity" --output-dir "."
```

Pipeline steps:
1. **Source Tree Verification:** Validates `extracted/electron/dist/` (26 modules) and `extracted/frontend/`.
2. **UI Internals Generation:** Scans IPC handlers, keybindings, and feature flags into `catalog/ui_internals.json`.
3. **Protobuf & Connect Reconstruction:** Extracts all 92 binary `FileDescriptorProto` objects, computes symbol dependency graph, emits 104 `.proto` files, and writes `catalog/rpc_schema.json`.
4. **Binary Disassembly:** Scans native binaries for CLI flags, env vars, and ConnectRPC methods into `catalog/binary_analysis.json`.

---

## Test Suite & Quality Verification

Run the comprehensive programmatic test suite:

```bash
# Run full unittest suite across all test modules
python -m unittest discover -s tests -p "test_*.py"

# Or run individual verification suites
python -m unittest tests/test_ui_internals.py
python -m unittest tests/test_catalogs.py
python -m unittest tests/test_proto_syntax.py
python -m unittest tests/test_headless_client.py
python -m unittest tests/test_host_safety.py
```

### Test Suite Inventory (23 Programmatic Tests)
1. **`test_ui_internals.py` (5 tests):** Validates JSON schema, 36 IPC channels, 56 actions, 84 feature flags, and 4 user tiers.
2. **`test_catalogs.py` (3 tests):** Validates minimum thresholds for UI internals (>= 15 IPC, >= 25 actions, >= 20 flags), Connect RPC catalog (>= 5 services, >= 40 methods, >= 40 messages), and binary analysis (29 flags, 18 env vars, 342 methods, SQLite/FTS5 schemas).
3. **`test_proto_syntax.py` (5 tests):** Scans all 104 `.proto` files, validates proto3 syntax declarations, verifies 100% balanced curly braces and quotes, checks cross-file import resolution, and asserts core service definitions.
4. **`test_headless_client.py` (7 tests):** Executes real live read-only calls against active local Language Server (`GetStatus`, `GetUserStatus`, `GetAvailableModels`, `RetrieveUserQuotaSummary`, `GetCascadeTrajectory`, `list_conversations`), and asserts HTTP 401 CSRF rejection on invalid tokens.
5. **`test_host_safety.py` (3 tests):** Verifies `%LOCALAPPDATA%\Programs\Antigravity` has zero modified files, running processes were never terminated, and package write isolation is preserved.

---

## Host Safety Guarantees (R5)

This toolkit operates under strict non-destructive host safety constraints:
- **Read-Only Host Access:** `%LOCALAPPDATA%\Programs\Antigravity` and `%APPDATA%\Antigravity` are treated strictly as read-only inputs.
- **Zero Process Disruption:** Active `Antigravity.exe` and `language_server.exe` processes are never terminated, restarted, or altered.
- **Read-Only Database Connections:** All local SQLite database queries use SQLite URI mode `?mode=ro` with `PRAGMA query_only = ON` to prevent locking or WAL write operations.
