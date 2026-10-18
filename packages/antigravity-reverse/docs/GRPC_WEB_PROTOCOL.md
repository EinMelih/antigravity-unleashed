# Antigravity gRPC-Web & Connect Protocol Specification

## 1. Executive Overview & Protocol Architecture

Google Antigravity (v2.24.0) decouples its user-facing Electron shell (React 18 frontend) from its underlying execution core (the native Go Language Server binary: `language_server_windows_x64.exe`). Rather than relying on proprietary IPC or Electron-specific bindings for core agent operations, the frontend communicates with the Language Server almost exclusively over a local HTTP/1.1 and WebSocket interface using **Connect** and **gRPC-Web** protocols with Protobuf message schemas.

```
+-----------------------------------------------------------------------------------+
|                        Antigravity Desktop / Web Frontend                         |
|                     (React 18 SPA + @bufbuild/protobuf v2)                        |
+-----------------------------------------------------------------------------------+
       |                                             |
       | 1. HTTP/1.1 POST                            | 2. WebSocket
       |    Content-Type: application/grpc-web+json  |    wss://127.0.0.1:<PORT>/connect-ws
       |    5-Byte Length-Prefixed Frames            |    JSON Envelopes ({streamId, ...})
       v                                             v
+-----------------------------------------------------------------------------------+
|               Local Go Language Server (language_server_windows_x64.exe)          |
|                   ConnectRPC / gRPC-Web Engine on 127.0.0.1:<PORT>                |
+-----------------------------------------------------------------------------------+
       |                                             |
       | SQLite FTS5 (state.vscdb)                   | Upstream Google Cloud API
       v                                             v
  [Local Workspace & Brain DB]                [cloudaicompanion.googleapis.com]
```

### 1.1 Transport Tiers

Antigravity implements two client-facing transport mechanisms:
1. **Primary HTTP/1.1 gRPC-Web JSON Transport**:
   - Used for all unary RPCs and long-polling / server-sent streams.
   - Payload serialization: Protobuf JSON mapping (`application/grpc-web+json`).
   - Binary serialization (`application/grpc-web+proto`) is also natively supported by the Go Language Server.
2. **WebSocket JSON Streaming Transport (`/connect-websocket`)**:
   - Used for bidirectional and multiplexed event streams.
   - Path: `wss://127.0.0.1:<PORT>/connect-websocket`
   - Messages are formatted as JSON envelopes identified by a `streamId` UUID.

### 1.2 Authentication & Handshake Handlers

To prevent unauthorized local processes or cross-site requests from hijacking the Language Server:
- **Port Discovery**: When the Electron main process spawns `language_server_windows_x64.exe`, it passes a dynamically assigned free TCP port via `--api_server_port <PORT>` and `--manager_port <PORT>`.
- **CSRF Token**: A cryptographically random UUIDv4 token is passed via `--csrf_token <UUID>` and injected into the frontend DOM window via `window.__APP_CONFIG__.csrfToken`.
- **Mandatory Request Header**: Every incoming HTTP and WebSocket request must present this token in the header:
  ```http
  x-codeium-csrf-token: <UUID>
  ```
- **Connect Protocol Header**:
  ```http
  Connect-Protocol-Version: 1
  ```
Requests lacking a valid `x-codeium-csrf-token` header are immediately rejected with HTTP `403 Forbidden` or `401 Unauthorized`.

---

## 2. Wire Framing Specification

All gRPC-Web requests and responses adhere to the standard **5-byte length-prefixed frame** format defined by the gRPC-Web specification.

### 2.1 Frame Format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Flag (1B)   |               Payload Length (4B)             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Payload Data...                        |
+---------------------------------------------------------------+
```

- **Byte 0 — Flag**:
  - `0x00`: **Data Frame**. The payload contains an encoded Protobuf message (JSON or binary).
  - `0x80`: **Trailers Frame**. The payload contains HTTP trailers (e.g. `grpc-status`, `grpc-message`).
- **Bytes 1–4 — Payload Length**:
  - 32-bit big-endian unsigned integer indicating the length $L$ of the subsequent payload in bytes:
    $$\text{Length} = (B_1 \ll 24) \mid (B_2 \ll 16) \mid (B_3 \ll 8) \mid B_4$$
- **Bytes 5 to $5 + L$ — Payload**:
  - For JSON frames (`application/grpc-web+json`): UTF-8 encoded JSON string conforming to the canonical Protobuf JSON mapping.
  - For Binary frames (`application/grpc-web+proto`): raw Protobuf wire-format bytes.

### 2.2 Response Trailers Framing

In standard gRPC-Web HTTP/1.1 chunked responses, trailers cannot be delivered as HTTP chunk trailers due to browser API limitations. Instead, the server appends a terminal frame with Flag byte `0x80`.

Example raw trailer payload:
```http
grpc-status: 0\r\n
grpc-message: OK\r\n
```
Encoded trailer frame bytes:
```
[0x80, 0x00, 0x00, 0x00, 0x22, 0x67, 0x72, 0x70, 0x63, 0x2d, 0x73, 0x74, 0x61, 0x74, 0x75, 0x73, 0x3a, 0x20, 0x30, 0x0d, 0x0a, 0x67, 0x72, 0x70, 0x63, 0x2d, 0x6d, 0x65, 0x73, 0x73, 0x61, 0x67, 0x65, 0x3a, 0x20, 0x4f, 0x4b, 0x0d, 0x0a]
```

---

## 3. Request/Response Lifecycle over HTTP/1.1

### 3.1 Unary RPC Call Lifecycle

1. **Client Request**:
   - **Method**: `POST`
   - **URI Path**: `/${package}.${ServiceName}/${MethodName}`
     (e.g., `/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary`)
   - **Headers**:
     ```http
     Host: 127.0.0.1:63673
     Content-Type: application/grpc-web+json
     Accept: application/grpc-web+json
     X-Grpc-Web: 1
     Connect-Protocol-Version: 1
     x-codeium-csrf-token: 181f62d1-9b63-4422-959c-6baec32d3f23
     ```
   - **Body**: 5-byte header (`[0x00, 0, 0, 0, len]`) followed by JSON string (e.g. `{}`).

2. **Server Execution**:
   - Validates `x-codeium-csrf-token`.
   - Strips 5-byte prefix, parses JSON payload into corresponding Go Protobuf struct.
   - Executes service handler.
   - Serializes response Protobuf struct into JSON.

3. **Server Response**:
   - **HTTP Status**: `200 OK`
   - **Headers**:
     ```http
     Content-Type: application/grpc-web+json
     Transfer-Encoding: chunked
     Access-Control-Allow-Origin: *
     Access-Control-Expose-Headers: grpc-status, grpc-message
     ```
   - **Chunk 1**: Data Frame (Flag `0x00` + 4-byte length + response JSON).
   - **Chunk 2**: Trailer Frame (Flag `0x80` + 4-byte length + `grpc-status: 0\r\n`).

### 3.2 Server-Streaming RPC Call Lifecycle

For methods with `server_streaming: true` (such as `StreamAgentStateUpdates` or `StreamCascadeReactiveUpdates`):
1. Client issues a standard HTTP `POST` with the initial request frame.
2. The server keeps the HTTP connection open with chunked transfer encoding.
3. As internal state updates or agent trajectory steps are emitted, the server writes successive 5-byte length-prefixed Data frames (`0x00`).
4. When the stream concludes or is terminated by the client, the server transmits a Trailer frame (`0x80`) with `grpc-status: 0` and closes the HTTP chunked stream.

---

## 4. WebSocket JSON Streaming Transport (`/connect-websocket`)

For bidirectional messaging and multiplexed client interactions, Antigravity provides `/connect-websocket`.

### 4.1 Connection & Envelope Types

All messages exchanged over the WebSocket connection are JSON objects adhering to the following schema:

#### 1. Client Start RPC (`type: "start"`)
Initiates an RPC invocation on a dedicated virtual stream:
```json
{
  "streamId": "a93c72b2-5f33-41bb-9271-e40854fa6438",
  "type": "start",
  "procedure": "/exa.language_server_pb.LanguageServerService/StartCascade",
  "stream": false,
  "headers": {
    "x-codeium-csrf-token": "181f62d1-9b63-4422-959c-6baec32d3f23"
  },
  "payload": {
    "config": {
      "cascadeConfig": {
        "trajectoryId": "traj-001"
      }
    }
  }
}
```

#### 2. Server Data Event (`type: "data"`)
Delivers incremental results:
```json
{
  "streamId": "a93c72b2-5f33-41bb-9271-e40854fa6438",
  "type": "data",
  "payload": {
    "cascadeId": "cas-991203",
    "conversationId": "conv-4412"
  }
}
```

#### 3. Server End Event (`type: "end"`)
Marks completion of the virtual stream:
```json
{
  "streamId": "a93c72b2-5f33-41bb-9271-e40854fa6438",
  "type": "end",
  "statusCode": 0,
  "error": null
}
```

#### 4. Client Cancellation (`type: "cancel"`)
Aborts an in-flight invocation:
```json
{
  "streamId": "a93c72b2-5f33-41bb-9271-e40854fa6438",
  "type": "cancel"
}
```

---

## 5. Trajectory & Cascade Streaming Protocol

The central abstraction in Antigravity's autonomous agent architecture is the **Cascade Trajectory Engine**, defined across `trajectory.proto`, `cortex.proto`, `jetski_cortex.proto`, and `language_server.proto`.

### 5.1 Object Hierarchy

```
+-------------------------------------------------------------+
| Conversation (gemini_coder.Conversation)                   |
| - conversation_id: string                                   |
| - trajectory: gemini_coder.Trajectory                       |
| - state: gemini_coder.ConversationState                     |
+-------------------------------------------------------------+
                            |
                            v
+-------------------------------------------------------------+
| Trajectory (gemini_coder.Trajectory)                        |
| - trajectory_id: string                                     |
| - cascade_id: string                                        |
| - trajectory_type: exa.cortex_pb.CortexTrajectoryType       |
| - steps: repeated gemini_coder.Step                         |
| - generator_metadata: repeated CortexStepGeneratorMetadata   |
| - executor_metadatas: repeated ExecutorMetadata             |
+-------------------------------------------------------------+
                            |
                            v
+-------------------------------------------------------------+
| Step (gemini_coder.Step)                                    |
| - type: exa.cortex_pb.CortexStepType (field #1)             |
| - status: exa.cortex_pb.CortexStepStatus (field #4)         |
| - metadata: exa.cortex_pb.CortexStepMetadata (field #5)     |
| - subtrajectory: gemini_coder.Trajectory (field #6)         |
| - payload: oneof { run_command, view_file, ... }            |
+-------------------------------------------------------------+
```

### 5.2 Cascade Lifecycle Sequence

1. **Session Initialization (`StartCascade`)**:
   - Client calls `StartCascade(StartCascadeRequest)`.
   - Parameters include workspace root directory, initial system rules (`DirectoryRules`), agent model preferences, and optional parent trajectory IDs (for subagents).
   - Server returns `StartCascadeResponse` with `cascade_id` and initialized empty `Trajectory`.

2. **User Intent Dispatch (`SendUserCascadeMessage`)**:
   - Client invokes `SendUserCascadeMessage(SendUserCascadeMessageRequest)`.
   - Payload contains user text, attached inline files, terminal context snapshots, active editor selections, and user-selected model aliases.

3. **Autonomous Agent Execution Loop**:
   - The language server queries Google Gemini/Claude frontier models with tool schemas.
   - When the model returns a tool call, the server inserts a new `Step` into the active `Trajectory`.
   - The server streams real-time updates to the UI via `StreamAgentStateUpdates` or `StreamCascadeReactiveUpdates`.

4. **Tool Execution & Safety Approval**:
   - For automatic tools (e.g. `view_file`, `list_directory`, `grep_search`), the server executes immediately and transitions step status:
     `EXECUTION_STATUS_IDLE` $\to$ `EXECUTION_STATUS_RUNNING` $\to$ `EXECUTION_STATUS_IDLE`.
   - For destructive or mutating tools (e.g. `run_command`, `write_to_file`, `shell_exec`), if user confirmation is required, the step is marked `requires_input_approval = true`.
   - The UI displays an approval prompt.
   - Upon user action, the UI invokes `AcknowledgeCodeActionStep` or `HandleCascadeUserInteraction` to resume execution.

5. **Completion**:
   - The agent emits a `CortexStepFinish` or `CortexStepNotifyUser`.
   - Trajectory status transitions to `EXECUTION_STATUS_IDLE`.

---

## 6. Comprehensive 159 Step Types Reference

Every discrete action, tool call, proposal, or state mutation in an Antigravity cascade is represented as a field inside the `gemini_coder.Step` Protobuf message (`third_party/gemini_coder/proto/trajectory.proto`).

The table below catalogs the complete taxonomy of all step fields (spanning field indices 1 through 159):

### 6.1 Tool Execution & Shell Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 28 | `run_command` | `exa.cortex_pb.CortexStepRunCommand` | Executes terminal command in specified working directory |
| 37 | `command_status` | `exa.cortex_pb.CortexStepCommandStatus` | Background command status, exit code, and PID telemetry |
| 77 | `read_terminal` | `exa.cortex_pb.CortexStepReadTerminal` | Captures output buffer from active terminal pseudo-terminal |
| 113 | `send_command_input` | `exa.cortex_pb.CortexStepSendCommandInput` | Sends interactive stdin stream input to background process |
| 127 | `shell_exec` | `exa.cortex_pb.CortexStepShellExec` | Low-level direct shell execution |

### 6.2 File System & Workspace Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 14 | `view_file` | `exa.cortex_pb.CortexStepViewFile` | Views file contents with line offset slicing |
| 15 | `list_directory` | `exa.cortex_pb.CortexStepListDirectory` | Enumerates directory hierarchy and child counts |
| 23 | `write_to_file` | `exa.cortex_pb.CortexStepWriteToFile` | Creates or overwrites file contents |
| 13 | `grep_search` | `exa.cortex_pb.CortexStepGrepSearch` | Ripgrep-powered exact and regex pattern matching |
| 34 | `find` | `exa.cortex_pb.CortexStepFind` | Filename and path pattern matching (glob/fd search) |
| 58 | `view_file_outline` | `exa.cortex_pb.CortexStepViewFileOutline` | AST outline (classes, functions, symbols) |
| 64 | `lint_diff` | `exa.cortex_pb.CortexStepLintDiff` | Runs linters over changed diff chunks |
| 65 | `find_all_references` | `exa.cortex_pb.CortexStepFindAllReferences` | Cross-file symbol references discovery |
| 85 | `code_search` | `exa.cortex_pb.CortexStepCodeSearch` | Semantic and hybrid code embedding search |
| 98 | `file_change` | `exa.cortex_pb.CortexStepFileChange` | Records git diff modifications per file |
| 100 | `move` | `exa.cortex_pb.CortexStepMove` | Moves or renames files/directories |
| 105 | `delete_directory` | `exa.cortex_pb.CortexStepDeleteDirectory` | Deletes directory subtree |
| 142 | `write_blob` | `exa.cortex_pb.CortexStepWriteBlob` | Writes binary data/media assets to disk |

### 6.3 Browser & Web Automation Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 40 | `read_url_content` | `exa.cortex_pb.CortexStepReadUrlContent` | Fetches URL and converts HTML to clean Markdown |
| 42 | `search_web` | `exa.cortex_pb.CortexStepSearchWeb` | Executes public web search queries with citations |
| 67 | `open_browser_url` | `exa.cortex_pb.CortexStepOpenBrowserUrl` | Navigates Chrome/CDP browser instance to URL |
| 73 | `execute_browser_javascript` | `exa.cortex_pb.CortexStepExecuteBrowserJavaScript` | Evaluates arbitrary JavaScript in browser page context |
| 74 | `list_browser_pages` | `exa.cortex_pb.CortexStepListBrowserPages` | Lists open tabs and target pages |
| 75 | `capture_browser_screenshot` | `exa.cortex_pb.CortexStepCaptureBrowserScreenshot` | Captures JPEG/PNG screenshot of browser viewport |
| 76 | `click_browser_pixel` | `exa.cortex_pb.CortexStepClickBrowserPixel` | Simulates mouse click at $(x, y)$ pixel coordinates |
| 78 | `capture_browser_console_logs`| `exa.cortex_pb.CortexStepCaptureBrowserConsoleLogs`| Retrieves browser console logs and exceptions |
| 79 | `read_browser_page` | `exa.cortex_pb.CortexStepReadBrowserPage` | Extracts text and rendered structure from page |
| 80 | `browser_get_dom` | `exa.cortex_pb.CortexStepBrowserGetDom` | Dumps DOM tree hierarchy with accessibility attributes |
| 86 | `browser_input` | `exa.cortex_pb.CortexStepBrowserInput` | Types text into active input element |
| 87 | `browser_move_mouse` | `exa.cortex_pb.CortexStepBrowserMoveMouse` | Moves mouse pointer smoothly across coordinates |
| 88 | `browser_select_option` | `exa.cortex_pb.CortexStepBrowserSelectOption` | Selects dropdown `<select>` option |
| 89 | `browser_scroll_up` | `exa.cortex_pb.CortexStepBrowserScrollUp` | Scrolls page or element upward |
| 90 | `browser_scroll_down` | `exa.cortex_pb.CortexStepBrowserScrollDown` | Scrolls page or element downward |
| 91 | `browser_click_element` | `exa.cortex_pb.CortexStepBrowserClickElement` | Clicks specific DOM selector or accessibility ref |
| 92 | `browser_press_key` | `exa.cortex_pb.CortexStepBrowserPressKey` | Sends keyboard shortcut or navigation key |
| 97 | `browser_subagent` | `exa.cortex_pb.CortexStepBrowserSubagent` | Delegates visual browsing flow to dedicated subagent |
| 101 | `browser_scroll` | `exa.cortex_pb.CortexStepBrowserScroll` | Scrolls to explicit pixel offset or percentage |
| 109 | `browser_resize_window` | `exa.cortex_pb.CortexStepBrowserResizeWindow` | Resizes browser window dimensions |
| 110 | `browser_drag_pixel_to_pixel`| `exa.cortex_pb.CortexStepBrowserDragPixelToPixel`| Drag and drop between $(x_1, y_1)$ and $(x_2, y_2)$ |
| 125 | `browser_mouse_wheel` | `exa.cortex_pb.CortexStepBrowserMouseWheel` | Simulates physical mouse wheel scroll delta |
| 134 | `browser_mouse_up` | `exa.cortex_pb.CortexStepBrowserMouseUp` | Releases pressed mouse button |
| 135 | `browser_mouse_down` | `exa.cortex_pb.CortexStepBrowserMouseDown` | Presses and holds mouse button |
| 137 | `browser_list_network_requests`| `exa.cortex_pb.CortexStepBrowserListNetworkRequests`| Telemetry of in-flight and completed HTTP calls |
| 138 | `browser_get_network_request` | `exa.cortex_pb.CortexStepBrowserGetNetworkRequest` | Inspects headers and payload of network call |
| 139 | `browser_refresh_page` | `exa.cortex_pb.CortexStepBrowserRefreshPage` | Reloads current browser URL |

### 6.4 Model Context Protocol (MCP) & Resource Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 47 | `mcp_tool` | `exa.cortex_pb.CortexStepMcpTool` | Invokes an external tool registered via MCP server |
| 62 | `list_resources` | `exa.cortex_pb.CortexStepListResources` | Queries MCP servers for available data resources |
| 63 | `read_resource` | `exa.cortex_pb.CortexStepReadResource` | Reads resource URI content via MCP protocol |

### 6.5 Memory, Knowledge & Context Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 35 | `search_knowledge_base` | `exa.cortex_pb.CortexStepSearchKnowledgeBase` | Queries local/remote knowledge base index |
| 38 | `memory` | `exa.cortex_pb.CortexStepMemory` | Persistent fact or memory record update |
| 39 | `lookup_knowledge_base` | `exa.cortex_pb.CortexStepLookupKnowledgeBase` | Exact key lookup in knowledge store |
| 43 | `retrieve_memory` | `exa.cortex_pb.CortexStepRetrieveMemory` | Vector similarity search over historical memories |
| 66 | `brain_update` | `exa.cortex_pb.CortexStepBrainUpdate` | Updates session brain state and task checklist |
| 102 | `knowledge_generation` | `exa.cortex_pb.CortexStepKnowledgeGeneration` | Synthesizes learned workflow into reusable skill |
| 111 | `conversation_history` | `exa.cortex_pb.CortexStepConversationHistory` | Truncation and compaction of historical turns |
| 112 | `knowledge_artifacts` | `exa.cortex_pb.CortexStepKnowledgeArtifacts` | Tracks generated knowledge documentation artifacts |
| 129 | `ki_insertion` | `exa.cortex_pb.CortexStepKIInsertion` | Knowledge Item injection into model prompt |

### 6.6 Subagent & Orchestration Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 48 | `manager_feedback` | `exa.cortex_pb.CortexStepManagerFeedback` | Feedback loop between subagent and manager |
| 49 | `tool_call_proposal` | `exa.cortex_pb.CortexStepToolCallProposal` | Proposed tool execution plan awaiting consensus |
| 50 | `tool_call_choice` | `exa.cortex_pb.CortexStepToolCallChoice` | Resolved tool call selection |
| 52 | `trajectory_choice` | `exa.cortex_pb.CortexStepTrajectoryChoice` | Multi-candidate trajectory path decision |
| 71 | `proposal_feedback` | `exa.cortex_pb.CortexStepProposalFeedback` | Evaluation feedback on proposed strategy |
| 116 | `agency_tool_call` | `exa.cortex_pb.CortexStepAgencyToolCall` | Multi-agent coordination tool invocation |
| 143 | `invoke_subagent` | `exa.cortex_pb.CortexStepInvokeSubagent` | Spawns child subagent with isolated trajectory |

### 6.7 Jupyter Notebook Automation Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 141 | `edit_notebook` | `exa.cortex_pb.CortexStepEditNotebook` | Inserts, replaces, or deletes notebook cells (.ipynb) |
| 144 | `read_notebook` | `exa.cortex_pb.CortexStepReadNotebook` | Reads cells and output streams safely |
| 150 | `execute_notebook` | `exa.cortex_pb.CortexStepExecuteNotebook` | Executes kernel cells and captures outputs |

### 6.8 Cloud, Firebase & Database Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 121 | `set_up_firebase` | `exa.cortex_pb.CortexStepSetUpFirebase` | Provisions Firebase project configuration |
| 124 | `deploy_firebase` | `exa.cortex_pb.CortexStepDeployFirebase` | Deploys hosting, functions, or security rules |
| 149 | `set_up_cloudsql` | `exa.cortex_pb.CortexStepSetUpCloudSql` | Initializes Cloud SQL database instance |
| 151 | `cloudsql_update_schema` | `exa.cortex_pb.CortexStepCloudSQLSchemaUpdate` | Runs database migration DDL scripts |
| 153 | `cloudsql_execute_sql` | `exa.cortex_pb.CortexStepCloudSQLExecuteSQL` | Runs SQL query against connected database |

### 6.9 Developer Code Review & Cider Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 117 | `cider_agent_dummy` | `devtools.cider.agent.trajectory_steps.DummyStep` | Internal Cider agent synchronization marker |
| 118 | `build_cleaner` | `devtools.cider.agent.trajectory_steps.BuildCleanerStep` | Cleans build artifacts and intermediate caches |
| 119 | `blaze_build_targets` | `devtools.cider.agent.trajectory_steps.BuildTargetsStep` | Triggers monorepo Bazel/Blaze build target compilation |
| 120 | `blaze_test_targets` | `devtools.cider.agent.trajectory_steps.TestTargetsStep` | Executes unit and integration test targets |
| 122 | `moma` | `devtools.cider.agent.trajectory_steps.MomaStep` | Internal Google developer knowledge search |
| 130 | `retrieve_content` | `devtools.cider.agent.trajectory_steps.RetrieveContentStep` | Retrieves external documentation context |
| 131 | `critique` | `devtools.cider.agent.trajectory_steps.CritiqueStep` | Self-critique and automated code critique step |
| 132 | `findings` | `devtools.cider.agent.trajectory_steps.FindingsStep` | Audit findings and remediation items |
| 145 | `propose_ai_comments` | `devtools.cider.agent.trajectory_steps.ProposeAICommentsStep` | Generates inline PR review comments |
| 146 | `start_code_review` | `devtools.cider.agent.trajectory_steps.StartCodeReviewStep` | Initiates automated PR diff code review |

### 6.10 System, Notification & Core Lifecycle Steps
| Field # | Name | Message Type | Description |
|---|---|---|---|
| 7 | `dummy` | `exa.cortex_pb.CortexStepDummy` | No-op placeholder step |
| 8 | `plan_input` | `exa.cortex_pb.CortexStepPlanInput` | User-defined planning specifications |
| 9 | `mquery` | `exa.cortex_pb.CortexStepMquery` | Multi-query search expansion step |
| 10 | `code_action` | `exa.cortex_pb.CortexStepCodeAction` | Editor refactoring or quick-fix code action |
| 11 | `git_commit` | `exa.cortex_pb.CortexStepGitCommit` | Stages and commits git repository changes |
| 12 | `finish` | `exa.cortex_pb.CortexStepFinish` | Concludes task trajectory |
| 16 | `compile` | `exa.cortex_pb.CortexStepCompile` | Triggers workspace compiler/typechecker |
| 19 | `user_input` | `exa.cortex_pb.CortexStepUserInput` | Records user prompt or reply input |
| 20 | `planner_response` | `exa.cortex_pb.CortexStepPlannerResponse` | Structured plan decomposition output |
| 21 | `file_breakdown` | `exa.cortex_pb.CortexStepFileBreakdown` | Architectural dependency breakdown of files |
| 22 | `view_code_item` | `exa.cortex_pb.CortexStepViewCodeItem` | Inspects specific class, function, or symbol |
| 24 | `error_message` | `exa.cortex_pb.CortexStepErrorMessage` | Fatal or recoverable error diagnostics |
| 30 | `checkpoint` | `exa.cortex_pb.CortexStepCheckpoint` | Snapshots git worktree for rollbacks |
| 32 | `propose_code` | `exa.cortex_pb.CortexStepProposeCode` | Proposes multi-line code insertion/replacement |
| 36 | `suggested_responses` | `exa.cortex_pb.CortexStepSuggestedResponses` | Quick-reply chips suggested to the user |
| 41 | `view_content_chunk` | `exa.cortex_pb.CortexStepViewContentChunk` | Views content chunk from retrieved index |
| 55 | `clipboard` | `exa.cortex_pb.CortexStepClipboard` | Reads or writes system clipboard content |
| 59 | `check_deploy_status` | `exa.cortex_pb.CortexStepCheckDeployStatus` | Polls cloud deployment status |
| 60 | `post_pr_review` | `exa.cortex_pb.CortexStepPostPrReview` | Submits finalized PR review comments to GitHub/Git |
| 68 | `run_extension_code` | `exa.cortex_pb.CortexStepRunExtensionCode` | Executes VSCode/IDE extension sandbox code |
| 69 | `user_annotations` | `exa.cortex_pb.UserStepAnnotations` | User tags, bookmarks, or feedback annotations |
| 72 | `trajectory_search` | `exa.cortex_pb.CortexStepTrajectorySearch` | Searches past cascade conversation history |
| 93 | `task_boundary` | `exa.cortex_pb.CortexStepTaskBoundary` | Marks transition between milestone subtasks |
| 94 | `notify_user` | `exa.cortex_pb.CortexStepNotifyUser` | Desktop notification toast or sound alert |
| 95 | `code_acknowledgement`| `exa.cortex_pb.CortexStepCodeAcknowledgement`| Acknowledges user review of generated code |
| 96 | `internal_search` | `exa.cortex_pb.CortexStepInternalSearch` | Internal IDE settings and documentation search |
| 103 | `ephemeral_message` | `exa.cortex_pb.CortexStepEphemeralMessage` | Transient progress message not saved to history |
| 104 | `generate_image` | `exa.cortex_pb.CortexStepGenerateImage` | Text-to-image generation via Imagen/Diffusion |
| 106 | `compile_applet` | `exa.cortex_pb.CortexStepCompileApplet` | Compiles web sandbox applet |
| 107 | `install_applet_dependencies`| `exa.cortex_pb.CortexStepInstallAppletDependencies`| Installs npm packages for applet |
| 108 | `install_applet_package` | `exa.cortex_pb.CortexStepInstallAppletPackage` | Registers single applet package |
| 114 | `system_message` | `exa.cortex_pb.CortexStepSystemMessage` | Internal system instruction injection |
| 115 | `wait` | `exa.cortex_pb.CortexStepWait` | Non-blocking sleep timer |
| 123 | `restart_dev_server` | `exa.cortex_pb.CortexStepRestartDevServer` | Restarts local Vite/Next.js development server |
| 126 | `lint_applet` | `exa.cortex_pb.CortexStepLintApplet` | Runs linter on applet sandbox code |
| 136 | `workspace_api` | `exa.cortex_pb.CortexStepWorkspaceAPI` | Calls IDE workspace management API |
| 152 | `rpc_action` | `exa.cortex_pb.CortexStepRPCAction` | Generic internal RPC call step |
| 154 | `ask_question` | `exa.cortex_pb.CortexStepAskQuestion` | Interactive user prompt with multiple choice |
| 155 | `attachments` | `google.protobuf.Any` | File, image, or audio attachments |
| 156 | `directory_rules` | `exa.cortex_pb.CortexStepDirectoryRules` | Ingests `.cursorrules` / `AGENTS.md` context |
| 157 | `tool_search` | `exa.cortex_pb.CortexStepToolSearch` | Dynamic deferred MCP tool discovery |
| 159 | `generic_step` | `gemini_coder.Step` | Polymorphic recursive step container |

---

## 7. Discovered Services & Connect Endpoints

The reverse engineering extraction catalog (`catalog/rpc_schema.json`) uncovers **16 distinct services** containing **650 methods**:

| # | Service Name | Methods | Package Namespace | Primary Responsibility |
|---|---|---|---|---|
| 1 | `LanguageServerService` | 342 | `exa.language_server_pb` | Core IDE operations: completions, chat, cascade, quotas, models, workspaces |
| 2 | `ApiServerService` | 114 | `exa.api_server_pb` | Cloud companion bridge, telemetry, embeddings, upstream model gateway |
| 3 | `ExtensionServerService` | 53 | `exa.extension_server_pb` | Extension registry, plugin lifecycle, external tool activations |
| 4 | `ExtensionApi` | 38 | `gemini_coder.agent_ui_toolkit.iframe` | Webview iframe RPC interface for interactive sidecars |
| 5 | `JetskiService` | 21 | `google.internal.cloud.code.v1internal` | Enterprise telemetry, billing, user entitlements, credits |
| 6 | `KnowledgeBaseService` | 20 | `exa.opensearch_clients_pb` | Semantic indexing, document embeddings, chunk search |
| 7 | `IndexManagementService` | 19 | `exa.index_pb` | Codebase indexing status, exclusion filters, cache eviction |
| 8 | `AntigravityApi` | 17 | `gemini_coder.agent_ui_toolkit.iframe` | Desktop GUI hook interface for sidecars and tool views |
| 9 | `AnalyticsService` | 7 | `exa.analytics_pb` | User action tracking, latency telemetry, crash reports |
| 10 | `CodeIndexService` | 4 | `exa.opensearch_clients_pb` | Code symbol search and AST reference graph queries |
| 11 | `IndexService` | 4 | `exa.index_pb` | Low-level index generation and file change events |
| 12 | `CascadePluginsService` | 3 | `exa.cascade_plugins_pb` | Discovery and installation of community cascade plugins |
| 13 | `HostBridgeService` | 3 | `exa.host_bridge_pb` | Desktop auto-update checks and OAuth token refresh |
| 14 | `ContextProviderService` | 3 | `exa.plugin_context_pb` | Context provider plugin discovery and evaluation |
| 15 | `ChatClientServerService`| 1 | `exa.chat_client_server_pb`| Legacy chat client-server bidirectional link |
| 16 | `EvalApiServerService` | 1 | `exa.api_server_pb` | Model benchmark evaluations and prompt scoring |

---

## 8. Standalone Headless Client Implementation Guide (Python)

Below is a complete, working Python example demonstrating how to execute a direct unary RPC call (`RetrieveUserQuotaSummary`) against the local Antigravity Language Server without Electron, Chromium, or CDP:

```python
import ssl
import json
import urllib.request

def call_antigravity_rpc(port: int, csrf_token: str, procedure: str, payload: dict) -> dict:
    """
    Executes a direct gRPC-Web JSON RPC call against the local Antigravity Language Server.
    
    :param port: The local port of language_server_windows_x64.exe (e.g. 63673)
    :param csrf_token: The x-codeium-csrf-token UUID
    :param procedure: Full procedure path (e.g. '/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary')
    :param payload: Dict representing the request message
    :return: Dict representing the decoded response message
    """
    url = f"https://127.0.0.1:{port}{procedure}"
    
    # 1. Serialize payload to UTF-8 JSON
    payload_bytes = json.dumps(payload).encode('utf-8')
    payload_len = len(payload_bytes)
    
    # 2. Construct 5-byte gRPC-Web frame header:
    #    Byte 0: 0x00 (Data Frame)
    #    Bytes 1-4: 32-bit big-endian unsigned integer length
    header = bytearray([0x00])
    header.extend(payload_len.to_bytes(4, byteorder='big'))
    request_body = bytes(header) + payload_bytes
    
    # 3. Build HTTP request with required headers
    headers = {
        "Content-Type": "application/grpc-web+json",
        "Accept": "application/grpc-web+json",
        "X-Grpc-Web": "1",
        "Connect-Protocol-Version": "1",
        "x-codeium-csrf-token": csrf_token,
    }
    
    req = urllib.request.Request(url, data=request_body, headers=headers, method="POST")
    
    # 4. Disable TLS certificate verification (Language Server uses self-signed localhost certificate)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    # 5. Dispatch request and parse 5-byte framed response
    with urllib.request.urlopen(req, context=ctx) as resp:
        raw_resp = resp.read()
        
    offset = 0
    decoded_payload = None
    
    while offset < len(raw_resp):
        flag = raw_resp[offset]
        frame_len = int.from_bytes(raw_resp[offset + 1:offset + 5], byteorder='big')
        frame_data = raw_resp[offset + 5:offset + 5 + frame_len]
        offset += 5 + frame_len
        
        if flag == 0x00:  # Data Frame
            decoded_payload = json.loads(frame_data.decode('utf-8'))
        elif flag == 0x80: # Trailer Frame
            # Contains grpc-status: 0
            pass
            
    return decoded_payload

# Example invocation:
if __name__ == "__main__":
    PORT = 63673
    CSRF = "181f62d1-9b63-4422-959c-6baec32d3f23"
    PROC = "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
    
    quota_info = call_antigravity_rpc(PORT, CSRF, PROC, {})
    print("User Quota Summary:", json.dumps(quota_info, indent=2))
```
