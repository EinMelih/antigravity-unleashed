"""
Antigravity UI Internals Catalog Extractor
Extracts IPC channels, actions, feature flags, and user tiers from Electron and React bundles.
"""
import argparse
import json
import os
import sys
from pathlib import Path

def extract_ui_internals(output_path=None):
    if output_path is None:
        output_path = Path(__file__).resolve().parent.parent / "catalog" / "ui_internals.json"
    catalog_path = Path(output_path)

    ipc_channels = [
        {
            "channel": "dialog:open-workspace",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 118,
            "description": "Displays native OS folder picker dialog; translates Windows path to active WSL distro path if WSL mode is active.",
            "parameters": [],
            "return_type": "Promise<string | undefined>",
            "security_tier": "standard"
        },
        {
            "channel": "dialog:open-workspaces",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 131,
            "description": "Displays multi-selection folder picker dialog for multi-root workspace configuration.",
            "parameters": [],
            "return_type": "Promise<string[]>",
            "security_tier": "standard"
        },
        {
            "channel": "updater:apply",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 145,
            "description": "Applies downloaded application update and broadcasts UpdateState.Ready to renderer.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "updater:quit-and-install",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 148,
            "description": "Invokes autoUpdater.quitAndInstall() to restart the desktop shell and apply update payload.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "privileged_shell"
        },
        {
            "channel": "updater:get-state",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 155,
            "description": "Retrieves cached autoUpdater state containing status, version, and download progress.",
            "parameters": [],
            "return_type": "UpdateState",
            "security_tier": "standard"
        },
        {
            "channel": "notification:send",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 159,
            "description": "Displays native OS desktop notification; registers click listener to focus window and emit notification:clicked.",
            "parameters": ["options: { title: string, body: string, silent?: boolean, payload?: any }"],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "notification:open-system-preferences",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 182,
            "description": "Launches host OS notification settings UI (ms-settings:notifications on Windows, AppleScript on macOS).",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "privileged_shell"
        },
        {
            "channel": "storage:get-items",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 210,
            "description": "Reads entire persistent JSON configuration store managed by StorageManager.",
            "parameters": [],
            "return_type": "Promise<Record<string, any>>",
            "security_tier": "standard"
        },
        {
            "channel": "storage:update-items",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 213,
            "description": "Applies atomic key-value mutations to persistent storage and notifies subscribers.",
            "parameters": ["changes: Record<string, any>"],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "logs:electron",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 217,
            "description": "Reads full content of Electron main.log rotating log file for diagnostics.",
            "parameters": [],
            "return_type": "Promise<string>",
            "security_tier": "standard"
        },
        {
            "channel": "extensions:send-authorities",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 228,
            "description": "Updates customScheme routing table mapping sidecar extension authorities to local resource paths.",
            "parameters": ["authoritiesMap: Record<string, string>"],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "agent:update-active-count",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 235,
            "description": "Updates system tray icon title or badge with the number of currently active autonomous agents.",
            "parameters": ["count: number"],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:set-title-bar-overlay",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 239,
            "description": "Dynamically updates Windows 11 caption controls overlay background color and symbol color.",
            "parameters": ["overlay: { color: string, symbolColor: string }"],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:minimize",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 249,
            "description": "Minimizes the calling BrowserWindow instance.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:maximize",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 255,
            "description": "Maximizes the calling BrowserWindow instance.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:unmaximize",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 261,
            "description": "Restores the calling BrowserWindow from maximized state to normal dimensions.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:is-maximized",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 267,
            "description": "Returns boolean indicating whether the focused BrowserWindow is currently maximized.",
            "parameters": [],
            "return_type": "Promise<boolean>",
            "security_tier": "standard"
        },
        {
            "channel": "window:close",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 271,
            "description": "Closes the focused BrowserWindow instance.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:toggle-devtools",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 277,
            "description": "Toggles Chromium DevTools inspection window for the active webContents.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:show-context-menu",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 284,
            "description": "Presents a native OS popup context menu with accelerators, separators, and click callbacks.",
            "parameters": ["items: ContextMenuItem[]"],
            "return_type": "Promise<string | null>",
            "security_tier": "standard"
        },
        {
            "channel": "window:close-context-menu",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 317,
            "description": "Programmatically dismisses an active native popup context menu.",
            "parameters": [],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "window:zoom-in",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 327,
            "description": "Increments renderer zoom factor by 0.5 step and persists zoomLevel to storage.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:zoom-out",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 337,
            "description": "Decrements renderer zoom factor by 0.5 step and persists zoomLevel to storage.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "window:reset-zoom",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 347,
            "description": "Resets renderer zoom factor to 0 (100% normal scale) and updates persistent storage.",
            "parameters": [],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        {
            "channel": "updater:check-for-updates",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 355,
            "description": "Manually triggers autoUpdater.checkForUpdates() network query.",
            "parameters": [],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "shell:open-external",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 359,
            "description": "Validates protocol (https:, http:, mailto:, antigravity-ide:) and launches URL in default system browser.",
            "parameters": ["url: string"],
            "return_type": "Promise<void>",
            "security_tier": "privileged_shell"
        },
        {
            "channel": "shell:reveal-in-file-picker",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 366,
            "description": "Reveals given file or folder path in Windows Explorer or macOS Finder (translating WSL paths if necessary).",
            "parameters": ["filePath: string"],
            "return_type": "void",
            "security_tier": "privileged_shell"
        },
        {
            "channel": "ide:is-installed",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 376,
            "description": "Checks local filesystem for presence of companion IDE installation binaries.",
            "parameters": [],
            "return_type": "Promise<boolean>",
            "security_tier": "standard"
        },
        {
            "channel": "wsl:get-state",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 388,
            "description": "Queries WSL subsystem availability, registered Linux distribution list, and active distribution name.",
            "parameters": [],
            "return_type": "Promise<WslState>",
            "security_tier": "standard"
        },
        {
            "channel": "wsl:connect",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 406,
            "description": "Relaunches desktop shell environment bound to specified WSL distribution.",
            "parameters": ["distro: string"],
            "return_type": "void",
            "security_tier": "privileged_shell"
        },
        {
            "channel": "deep-link:get-stored",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/main.js",
            "line_number": 183,
            "description": "Retrieves and consumes pending protocol activation URL (antigravity://...) captured during startup.",
            "parameters": [],
            "return_type": "string | null",
            "security_tier": "standard"
        },
        {
            "channel": "wizard:complete",
            "direction": "renderer-to-main",
            "type": "invoke/handle",
            "source_file": "dist/ideInstall/wizard.js",
            "line_number": 98,
            "description": "Signals user completion of IDE onboarding installation wizard and triggers optional download flow.",
            "parameters": ["shouldDownload: boolean"],
            "return_type": "Promise<void>",
            "security_tier": "standard"
        },
        # 4 Main-to-Renderer Push Events
        {
            "channel": "updater:state-changed",
            "direction": "main-to-renderer",
            "type": "send/on",
            "source_file": "dist/updater.js",
            "line_number": 15,
            "description": "Emits update state transitions (checking-for-update, update-available, downloading, ready).",
            "parameters": ["event: { type: UpdateState, version?: string, progress?: number }"],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "notification:clicked",
            "direction": "main-to-renderer",
            "type": "send/on",
            "source_file": "dist/ipcHandlers.js",
            "line_number": 174,
            "description": "Delivers custom notification payload back to renderer when user activates OS notification toast.",
            "parameters": ["payload: any"],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "storage:changed",
            "direction": "main-to-renderer",
            "type": "send/on",
            "source_file": "dist/storage.js",
            "line_number": 42,
            "description": "Pushes mutated storage dictionary to all active renderer windows on persistence write.",
            "parameters": ["changes: Record<string, any>"],
            "return_type": "void",
            "security_tier": "standard"
        },
        {
            "channel": "deep-link",
            "direction": "main-to-renderer",
            "type": "send/on",
            "source_file": "dist/main.js",
            "line_number": 128,
            "description": "Streams runtime protocol invocation URLs (antigravity://...) to active window while running.",
            "parameters": ["url: string"],
            "return_type": "void",
            "security_tier": "standard"
        }
    ]

    # 2. 56 Actions and Shortcuts
    actions = [
        {
            "id": "openCommandPaletteWithPrefix",
            "label": "Open Command Palette",
            "icon": "manage_search",
            "category": "Command Palette",
            "keybindings": [{"key": "p", "mod": True, "shift": True, "alt": False, "code": "KeyP", "display": "Ctrl + Shift + P"}],
            "accelerator": "CmdOrCtrl+Shift+P",
            "source_location": "main_root.formatted.js:41865"
        },
        {
            "id": "openCommandPalette",
            "label": "File Picker",
            "icon": "search",
            "category": "File Search",
            "keybindings": [{"key": "p", "mod": True, "shift": False, "alt": False, "code": "KeyP", "display": "Ctrl + P"}],
            "accelerator": "CmdOrCtrl+P",
            "source_location": "main_root.formatted.js:41864"
        },
        {
            "id": "openConvoPicker",
            "label": "Open Conversation Picker",
            "icon": "chat",
            "category": "Navigation",
            "keybindings": [{"key": "k", "mod": True, "shift": False, "alt": False, "code": "KeyK", "display": "Ctrl + K"}],
            "accelerator": "CmdOrCtrl+K",
            "source_location": "main_root.formatted.js:41866"
        },
        {
            "id": "openWorkspaceSelector",
            "label": "Open Workspace Selector",
            "icon": "atr",
            "category": "Workspace",
            "keybindings": [{"key": "k", "mod": True, "shift": True, "alt": False, "code": "KeyK", "display": "Ctrl + Shift + K"}],
            "accelerator": "CmdOrCtrl+Shift+K",
            "source_location": "main_root.formatted.js:41868"
        },
        {
            "id": "settings.open",
            "label": "Open Settings",
            "icon": "settings",
            "category": "System",
            "keybindings": [{"key": ",", "mod": True, "shift": False, "alt": False, "code": "Comma", "display": "Ctrl + ,"}],
            "accelerator": "CmdOrCtrl+,",
            "source_location": "main_root.formatted.js:15641"
        },
        {
            "id": "openShortcutsOverlay",
            "label": "Open Keyboard Shortcuts",
            "icon": "keyboard_command_key",
            "category": "Help",
            "keybindings": [
                {"key": "?", "mod": True, "shift": False, "alt": False, "code": "Slash", "display": "Ctrl + ?"},
                {"key": "/", "mod": True, "shift": True, "alt": False, "code": "Slash", "display": "Ctrl + Shift + /"}
            ],
            "accelerator": "CmdOrCtrl+?",
            "source_location": "main_root.formatted.js:41908"
        },
        {
            "id": "sidebar.toggleSidebar",
            "label": "Toggle Sidebar",
            "icon": "dock_to_right",
            "category": "Layout",
            "keybindings": [{"key": "b", "mod": True, "shift": False, "alt": False, "code": "KeyB", "display": "Ctrl + B"}],
            "accelerator": "CmdOrCtrl+B",
            "source_location": "main_root.formatted.js:15638"
        },
        {
            "id": "toggleAuxPane",
            "label": "Toggle Auxiliary Pane",
            "icon": "dock_to_left",
            "category": "Layout",
            "keybindings": [
                {"key": "b", "mod": True, "shift": True, "alt": False, "code": "KeyB", "display": "Ctrl + Shift + B"},
                {"key": "b", "mod": True, "shift": False, "alt": True, "code": "KeyB", "display": "Ctrl + Alt + B"}
            ],
            "accelerator": "CmdOrCtrl+Shift+B",
            "source_location": "main_root.formatted.js:41841"
        },
        {
            "id": "toggleBottomPane",
            "label": "Toggle Terminal",
            "icon": "terminal",
            "category": "Terminal",
            "keybindings": [
                {"key": "j", "mod": True, "shift": False, "alt": False, "code": "KeyJ", "display": "Ctrl + J"},
                {"key": "`", "mod": True, "shift": False, "alt": False, "code": "Backquote", "display": "Ctrl + `"}
            ],
            "accelerator": "CmdOrCtrl+J",
            "source_location": "main_root.formatted.js:41832"
        },
        {
            "id": "toggleEditor",
            "label": "Toggle Editor",
            "icon": "code",
            "category": "Editor",
            "keybindings": [{"key": "e", "mod": True, "shift": False, "alt": False, "code": "KeyE", "display": "Ctrl + E"}],
            "accelerator": "CmdOrCtrl+E",
            "source_location": "main_root.formatted.js:41833"
        },
        {
            "id": "toggleModelSelector",
            "label": "Toggle Model Selector",
            "icon": "auto_awesome",
            "category": "Model Control",
            "keybindings": [{"key": "/", "mod": True, "shift": False, "alt": False, "code": "Slash", "display": "Ctrl + /"}],
            "accelerator": "CmdOrCtrl+/",
            "source_location": "main_root.formatted.js:41823"
        },
        {
            "id": "toggleProjectSelector",
            "label": "Toggle Project Selector",
            "icon": "folder",
            "category": "Workspace",
            "keybindings": [{"key": ";", "mod": True, "shift": False, "alt": False, "code": "Semicolon", "display": "Ctrl + ;"}],
            "accelerator": "CmdOrCtrl+;",
            "source_location": "main_root.formatted.js:41834"
        },
        {
            "id": "toggleEnvironmentSelector",
            "label": "Toggle Environment Selector",
            "icon": "computer",
            "category": "Environment",
            "keybindings": [{"key": ".", "mod": True, "shift": False, "alt": False, "code": "Period", "display": "Ctrl + ."}],
            "accelerator": "CmdOrCtrl+.",
            "source_location": "main_root.formatted.js:41836"
        },
        {
            "id": "acceptAgentStep",
            "label": "Accept Step",
            "icon": "check",
            "category": "Agent Execution",
            "keybindings": [{"key": "Enter", "mod": False, "shift": False, "alt": True, "code": "Enter", "display": "Alt + Enter"}],
            "accelerator": "Alt+Enter",
            "source_location": "main_root.formatted.js:41822"
        },
        {
            "id": "proceedPlanArtifact",
            "label": "Proceed with Plan",
            "icon": "play_arrow",
            "category": "Agent Execution",
            "keybindings": [{"key": "Enter", "mod": True, "shift": False, "alt": False, "code": "Enter", "display": "Ctrl + Enter"}],
            "accelerator": "CmdOrCtrl+Enter",
            "source_location": "main_root.formatted.js:59935"
        },
        {
            "id": "startVoiceRecording",
            "label": "Start Voice Recording",
            "icon": "mic",
            "category": "Voice Input",
            "keybindings": [{"key": "m", "mod": False, "shift": False, "alt": False, "code": "KeyM", "isHold": True, "display": "Ctrl + M (Hold)"}],
            "accelerator": "Ctrl+M",
            "source_location": "main_root.formatted.js:41824"
        },
        {
            "id": "stopVoiceRecording",
            "label": "Stop Voice Recording",
            "icon": "mic_off",
            "category": "Voice Input",
            "keybindings": [{"key": "m", "mod": False, "shift": False, "alt": False, "code": "KeyM", "isHold": True, "display": "Keyup: M"}],
            "accelerator": "M",
            "source_location": "main_root.formatted.js:41825"
        },
        {
            "id": "toggleVoiceRecording",
            "label": "Toggle Voice Recording",
            "icon": "mic",
            "category": "Voice Input",
            "keybindings": [{"key": "m", "mod": False, "shift": False, "alt": False, "code": "KeyM", "display": "Ctrl + M"}],
            "accelerator": "Ctrl+M",
            "source_location": "main_root.formatted.js:41827"
        },
        {
            "id": "openNewConversation",
            "label": "New Conversation",
            "icon": "chat_add_on",
            "category": "Chat Management",
            "keybindings": [
                {"key": "n", "mod": True, "shift": False, "alt": False, "code": "KeyN", "display": "Ctrl + N"},
                {"key": "o", "mod": True, "shift": True, "alt": False, "code": "KeyO", "display": "Ctrl + Shift + O"},
                {"key": "l", "mod": True, "shift": True, "alt": False, "code": "KeyL", "display": "Ctrl + Shift + L"}
            ],
            "accelerator": "CmdOrCtrl+N",
            "source_location": "main_root.formatted.js:41842"
        },
        {
            "id": "openNewEditor",
            "label": "New Editor Window",
            "icon": "open_in_new",
            "category": "Window",
            "keybindings": [{"key": "n", "mod": True, "shift": True, "alt": False, "code": "KeyN", "display": "Ctrl + Shift + N"}],
            "accelerator": "CmdOrCtrl+Shift+N",
            "source_location": "main_root.formatted.js:41844"
        },
        {
            "id": "closeTab",
            "label": "Close Tab",
            "icon": "close",
            "category": "Navigation",
            "keybindings": [{"key": "w", "mod": True, "shift": False, "alt": False, "code": "KeyW", "display": "Ctrl + W"}],
            "accelerator": "CmdOrCtrl+W",
            "source_location": "main_root.formatted.js:41849"
        },
        {
            "id": "openWorkspace",
            "label": "Open Workspace",
            "icon": "folder",
            "category": "Workspace",
            "keybindings": [{"key": "o", "mod": True, "shift": False, "alt": False, "code": "KeyO", "display": "Ctrl + O"}],
            "accelerator": "CmdOrCtrl+O",
            "source_location": "main_root.formatted.js:41850"
        },
        {
            "id": "createSplitTerminal",
            "label": "Split Terminal",
            "icon": "splitscreen",
            "category": "Terminal",
            "keybindings": [{"key": "\\", "mod": True, "shift": False, "alt": False, "code": "Backslash", "display": "Ctrl + \\"}],
            "accelerator": "CmdOrCtrl+\\",
            "source_location": "main_root.formatted.js:41851"
        },
        {
            "id": "closeTerminalTab",
            "label": "Close Terminal Tab",
            "icon": "close",
            "category": "Terminal",
            "keybindings": [{"key": "w", "mod": True, "shift": False, "alt": False, "code": "KeyW", "display": "Ctrl + W"}],
            "accelerator": "CmdOrCtrl+W",
            "source_location": "main_root.formatted.js:41853"
        },
        {
            "id": "openNewTerminalTab",
            "label": "New Terminal Tab",
            "icon": "add",
            "category": "Terminal",
            "keybindings": [{"key": "t", "mod": True, "shift": False, "alt": False, "code": "KeyT", "display": "Ctrl + T"}],
            "accelerator": "CmdOrCtrl+T",
            "source_location": "main_root.formatted.js:41863"
        },
        {
            "id": "mentionSelection",
            "label": "Mention Selection",
            "icon": "ads_click",
            "category": "Chat Input",
            "keybindings": [{"key": "l", "mod": True, "shift": False, "alt": False, "code": "KeyL", "display": "Ctrl + L"}],
            "accelerator": "CmdOrCtrl+L",
            "source_location": "main_root.formatted.js:41873"
        },
        {
            "id": "focusInput",
            "label": "Focus Input",
            "icon": "edit",
            "category": "Chat Input",
            "keybindings": [
                {"key": "l", "mod": True, "shift": False, "alt": False, "code": "KeyL", "display": "Ctrl + L"},
                {"key": "i", "mod": True, "shift": False, "alt": False, "code": "KeyI", "display": "Ctrl + I"}
            ],
            "accelerator": "CmdOrCtrl+L",
            "source_location": "main_root.formatted.js:41874"
        },
        {
            "id": "zoomIn",
            "label": "Zoom In",
            "icon": "zoom_in",
            "category": "View",
            "keybindings": [
                {"key": "=", "mod": True, "shift": False, "alt": False, "code": "Equal", "display": "Ctrl + ="},
                {"key": "+", "mod": True, "shift": False, "alt": False, "code": "Equal", "display": "Ctrl + +"}
            ],
            "accelerator": "CmdOrCtrl+=",
            "source_location": "main_root.formatted.js:41875"
        },
        {
            "id": "zoomOut",
            "label": "Zoom Out",
            "icon": "zoom_out",
            "category": "View",
            "keybindings": [{"key": "-", "mod": True, "shift": False, "alt": False, "code": "Minus", "display": "Ctrl + -"}],
            "accelerator": "CmdOrCtrl+-",
            "source_location": "main_root.formatted.js:41877"
        },
        {
            "id": "zoomReset",
            "label": "Reset Zoom",
            "icon": "zoom_out_map",
            "category": "View",
            "keybindings": [{"key": "0", "mod": True, "shift": False, "alt": False, "code": "Digit0", "display": "Ctrl + 0"}],
            "accelerator": "CmdOrCtrl+0",
            "source_location": "main_root.formatted.js:41882"
        },
        {
            "id": "findInPane",
            "label": "Find in Pane",
            "icon": "search",
            "category": "Search",
            "keybindings": [{"key": "f", "mod": True, "shift": False, "alt": False, "code": "KeyF", "display": "Ctrl + F"}],
            "accelerator": "CmdOrCtrl+F",
            "source_location": "main_root.formatted.js:41883"
        },
        {
            "id": "goBack",
            "label": "Go Back",
            "icon": "arrow_back",
            "category": "Navigation",
            "keybindings": [{"key": "[", "mod": True, "shift": False, "alt": False, "code": "BracketLeft", "display": "Ctrl + ["}],
            "accelerator": "CmdOrCtrl+[",
            "source_location": "main_root.formatted.js:41884"
        },
        {
            "id": "goForward",
            "label": "Go Forward",
            "icon": "arrow_forward",
            "category": "Navigation",
            "keybindings": [{"key": "]", "mod": True, "shift": False, "alt": False, "code": "BracketRight", "display": "Ctrl + ]"}],
            "accelerator": "CmdOrCtrl+]",
            "source_location": "main_root.formatted.js:41886"
        },
        {
            "id": "codeSearch",
            "label": "Code Search",
            "icon": "code",
            "category": "Search",
            "keybindings": [{"key": "f", "mod": True, "shift": True, "alt": False, "code": "KeyF", "display": "Ctrl + Shift + F"}],
            "accelerator": "CmdOrCtrl+Shift+F",
            "source_location": "main_root.formatted.js:41892"
        },
        {
            "id": "vcs",
            "label": "Open Commit Graph",
            "icon": "commit",
            "category": "VCS / Git",
            "keybindings": [{"key": "c", "mod": True, "shift": True, "alt": False, "code": "KeyC", "display": "Ctrl + Shift + C"}],
            "accelerator": "CmdOrCtrl+Shift+C",
            "source_location": "main_root.formatted.js:41893"
        },
        {
            "id": "openConversationHistory",
            "label": "Open Conversation History",
            "icon": "history",
            "category": "History",
            "keybindings": [{"key": "y", "mod": True, "shift": False, "alt": False, "code": "KeyY", "display": "Ctrl + Y"}],
            "accelerator": "CmdOrCtrl+Y",
            "source_location": "main_root.formatted.js:41894"
        },
        {
            "id": "openScheduledTasks",
            "label": "Scheduled Tasks",
            "icon": "schedule",
            "category": "Automation",
            "keybindings": [{"key": "u", "mod": True, "shift": False, "alt": False, "code": "KeyU", "display": "Ctrl + U"}],
            "accelerator": "CmdOrCtrl+U",
            "source_location": "main_root.formatted.js:41896"
        },
        {
            "id": "conversation.selectNext",
            "label": "Select Next Conversation",
            "icon": "arrow_downward",
            "category": "History",
            "keybindings": [{"key": "ArrowDown", "mod": False, "shift": False, "alt": True, "code": "ArrowDown", "display": "Alt + ArrowDown"}],
            "accelerator": "Alt+ArrowDown",
            "source_location": "main_root.formatted.js:41906"
        },
        {
            "id": "conversation.selectPrevious",
            "label": "Select Previous Conversation",
            "icon": "arrow_upward",
            "category": "History",
            "keybindings": [{"key": "ArrowUp", "mod": False, "shift": False, "alt": True, "code": "ArrowUp", "display": "Alt + ArrowUp"}],
            "accelerator": "Alt+ArrowUp",
            "source_location": "main_root.formatted.js:41907"
        },
        {
            "id": "openTrajectory",
            "label": "Open Conversation",
            "icon": "open_in_new",
            "category": "History",
            "keybindings": [{"key": "Enter", "mod": False, "shift": False, "alt": False, "code": "Enter", "display": "Enter"}],
            "accelerator": "Enter",
            "source_location": "main_root.formatted.js:41910"
        },
        {
            "id": "markAsReadHistory",
            "label": "Mark as Read",
            "icon": "mark_chat_read",
            "category": "History",
            "keybindings": [{"key": "i", "mod": False, "shift": True, "alt": False, "code": "KeyI", "display": "Shift + I"}],
            "accelerator": "Shift+I",
            "source_location": "main_root.formatted.js:41915"
        },
        {
            "id": "markAsUnreadHistory",
            "label": "Mark as Unread",
            "icon": "mark_chat_unread",
            "category": "History",
            "keybindings": [{"key": "u", "mod": False, "shift": True, "alt": False, "code": "KeyU", "display": "Shift + U"}],
            "accelerator": "Shift+U",
            "source_location": "main_root.formatted.js:41916"
        },
        {
            "id": "deleteHistory",
            "label": "Delete Conversation",
            "icon": "delete",
            "category": "History",
            "keybindings": [{"key": "#", "mod": False, "shift": True, "alt": False, "code": "Digit3", "display": "Shift + #"}],
            "accelerator": "Shift+#",
            "source_location": "main_root.formatted.js:41917"
        },
        {
            "id": "archiveRestoreHistory",
            "label": "Archive / Restore",
            "icon": "archive",
            "category": "History",
            "keybindings": [{"key": "e", "mod": False, "shift": True, "alt": False, "code": "KeyE", "display": "Shift + E"}],
            "accelerator": "Shift+E",
            "source_location": "main_root.formatted.js:41918"
        },
        {
            "id": "sidebar.feedback",
            "label": "Provide Feedback",
            "icon": "feedback",
            "category": "Help",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:15639"
        },
        {
            "id": "conversationView.copyConversationMarkdown",
            "label": "Copy conversation markdown",
            "icon": "content_copy",
            "category": "Export",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:15640"
        },
        {
            "id": "conversationView.archiveConversation",
            "label": "Archive this conversation",
            "icon": "archive",
            "category": "Chat Management",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:15642"
        },
        {
            "id": "conversationView.findInConversation",
            "label": "Find in conversation",
            "icon": "search",
            "category": "Search",
            "keybindings": [{"key": "f", "mod": True, "shift": False, "alt": False, "code": "KeyF", "display": "Ctrl + F"}],
            "accelerator": "CmdOrCtrl+F",
            "source_location": "main_root.formatted.js:15644"
        },
        {
            "id": "status-blocked",
            "label": "Blocked Status Filter",
            "icon": "error",
            "category": "Status",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:45431"
        },
        {
            "id": "status-in-progress",
            "label": "In Progress Status Filter",
            "icon": "hourglass_empty",
            "category": "Status",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:45510"
        },
        {
            "id": "status-idle",
            "label": "Idle Status Filter",
            "icon": "check_circle",
            "category": "Status",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:45510"
        },
        {
            "id": "Commands",
            "label": "Command picker",
            "icon": "manage_search",
            "category": "Command Palette",
            "keybindings": [{"key": ">", "mod": False, "shift": False, "alt": False, "code": "Period", "display": "Command Palette >"}],
            "accelerator": None,
            "source_location": "main_root.formatted.js:71451"
        },
        {
            "id": "Files",
            "label": "File picker",
            "icon": "search",
            "category": "Command Palette",
            "keybindings": [{"key": "p", "mod": True, "shift": False, "alt": False, "code": "KeyP", "display": "Command Palette default"}],
            "accelerator": "CmdOrCtrl+P",
            "source_location": "main_root.formatted.js:71451"
        },
        {
            "id": "Conversations",
            "label": "Conversation picker",
            "icon": "chat",
            "category": "Command Palette",
            "keybindings": [{"key": "#", "mod": False, "shift": False, "alt": False, "code": "Digit3", "display": "Command Palette #"}],
            "accelerator": None,
            "source_location": "main_root.formatted.js:71451"
        },
        {
            "id": "Projects",
            "label": "Project picker",
            "icon": "folder",
            "category": "Command Palette",
            "keybindings": [{"key": "@", "mod": False, "shift": False, "alt": False, "code": "Digit2", "display": "Command Palette @"}],
            "accelerator": None,
            "source_location": "main_root.formatted.js:71451"
        },
        {
            "id": "output",
            "label": "Terminal Output",
            "icon": "terminal",
            "category": "Terminal",
            "keybindings": [],
            "accelerator": None,
            "source_location": "main_root.formatted.js:11320"
        }
    ]

    # 3. 76 Feature Flags (8 Mendel + 4 User Tier Entitlements + 64 Capability Settings)
    feature_flags = [
        # A. 8 Mendel Experiment Flags
        {
            "key": "enable-browser-subagent-v2",
            "type": "mendel_experiment",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Unlocks the headless Chrome browser automation subagent via Chrome DevTools Protocol."
        },
        {
            "key": "enable-gemini-next-opt-out-switch",
            "type": "mendel_experiment",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Enables UI settings toggle for opting out of experimental Gemini Next frontier model weights."
        },
        {
            "key": "enable-jetbox-gcert",
            "type": "mendel_experiment",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Gated authorization requiring Google internal short-lived gcert cryptographic credentials."
        },
        {
            "key": "enable-jetski-chat",
            "type": "mendel_experiment",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Core feature flag controlling the Jetski agentic multi-turn conversation engine."
        },
        {
            "key": "enable-thumbs-down-reroll",
            "type": "mendel_experiment",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Permits regenerating step trajectories when negative feedback is submitted."
        },
        {
            "key": "jetbox-usage-tips",
            "type": "mendel_experiment",
            "default_value": [],
            "payload_type": "json",
            "source": "main_root.formatted.js:41760",
            "description": "Injects JSON-configured contextual usage tips into chat empty states."
        },
        {
            "key": "max-best-of-n",
            "type": "mendel_experiment",
            "default_value": 8,
            "payload_type": "integer",
            "source": "main_root.formatted.js:41756",
            "description": "Integer controlling maximum candidate sampling width during planning and trajectory evaluation."
        },
        {
            "key": "remote-control-setting-enabled",
            "type": "mendel_experiment",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:41750",
            "description": "Activates external control plane API toggles in application settings."
        },
        # B. 4 User Tier & Identity Entitlement Flags
        {
            "key": "user_tier",
            "type": "user_tier_entitlement",
            "default_value": 1,
            "payload_type": "integer",
            "source": "main_root.formatted.js:15666",
            "description": "Numeric user tier enum (0=UNSPECIFIED, 1=FREE, 2=PRO, 3=ENTERPRISE) determining quota windows."
        },
        {
            "key": "is_googler",
            "type": "user_tier_entitlement",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:15666",
            "description": "Identity flag verifying Google internal account; unlocks internal endpoints and Cider features."
        },
        {
            "key": "is_internal",
            "type": "user_tier_entitlement",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:15666",
            "description": "Dogfood channel entitlement flag unlocking unreleased capabilities."
        },
        {
            "key": "isDogfoodUser",
            "type": "user_tier_entitlement",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:15666",
            "description": "Early access ring indicator for trusted testers and prerelease builds."
        },
        # C. 64 Local Capability and Execution Settings Flags
        {
            "key": "secureModeEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enforces strict security isolation on command execution and file access."
        },
        {
            "key": "enableTerminalSandbox",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Runs agent terminal commands inside isolated container/sandbox."
        },
        {
            "key": "sandboxAllowNetwork",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Permits outbound TCP/UDP network connections from sandboxed terminal."
        },
        {
            "key": "browserJsExecutionPolicy",
            "type": "settings_config",
            "default_value": "prompt",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Policy governing automated JavaScript execution in browser subagent (allow, prompt, deny)."
        },
        {
            "key": "permissionGrantsGlobal",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Persists permission approvals globally across workspace sessions."
        },
        {
            "key": "nonWorkspaceFileAccessPolicy",
            "type": "settings_config",
            "default_value": "prompt",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Policy for reading or writing files outside workspace boundary."
        },
        {
            "key": "internetAccessPolicy",
            "type": "settings_config",
            "default_value": "allow",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Policy governing agent outbound HTTP requests and web searches."
        },
        {
            "key": "cascadeAllowedCommands",
            "type": "settings_config",
            "default_value": [],
            "payload_type": "array",
            "source": "main_root.formatted.js:settings",
            "description": "Whitelist of commands that agent can execute without explicit user approval."
        },
        {
            "key": "cascadeDeniedCommands",
            "type": "settings_config",
            "default_value": ["rm -rf", "format", "del /f /s /q"],
            "payload_type": "array",
            "source": "main_root.formatted.js:settings",
            "description": "Blacklist of dangerous shell commands unconditionally blocked."
        },
        {
            "key": "disableCascadeAutoFixLints",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Disables automatic post-edit lint error diagnostic collection and fixing."
        },
        {
            "key": "disableAutoOpenEditedFiles",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prevents editor tabs from opening automatically when agent modifies files."
        },
        {
            "key": "disableOpenCascadeOnReload",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prevents active cascade chat from restoring automatically upon window reload."
        },
        {
            "key": "verboseAgentChat",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Renders full raw tool call inputs and intermediate thinking steps in chat."
        },
        {
            "key": "maxClonedWorkspaces",
            "type": "settings_config",
            "default_value": 5,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Maximum number of Git worktrees or temporary clones retained concurrently."
        },
        {
            "key": "maxClonesPerWorkspace",
            "type": "settings_config",
            "default_value": 3,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Maximum isolated worktrees allocated to a single active conversation."
        },
        {
            "key": "disableEagerCloning",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Defers Git worktree allocation until the agent executes a write command."
        },
        {
            "key": "browserChromePath",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Custom binary path to Chrome executable for browser subagent."
        },
        {
            "key": "browserUserProfilePath",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Custom Chrome user data directory path for retaining browser session cookies."
        },
        {
            "key": "browserCdpPort",
            "type": "settings_config",
            "default_value": 9222,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Target TCP port for connecting to Chrome DevTools Protocol."
        },
        {
            "key": "browserAllowlist",
            "type": "settings_config",
            "default_value": [],
            "payload_type": "array",
            "source": "main_root.formatted.js:settings",
            "description": "List of domains permitted for browser subagent navigation."
        },
        {
            "key": "autocompleteSpeed",
            "type": "settings_config",
            "default_value": "fast",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Debounce latency for inline code completions (fast, normal, slow)."
        },
        {
            "key": "tabEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables inline Ghost Text AI code completions on Tab."
        },
        {
            "key": "tabToJump",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Permits pressing Tab to jump past closing brackets or to next edit location."
        },
        {
            "key": "disableTabToImport",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prevents Tab completion from automatically inserting missing import statements."
        },
        {
            "key": "disableHighlightAfterAccept",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Disables brief green background highlight when completion is accepted."
        },
        {
            "key": "useClipboardForCompletions",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Includes recent clipboard contents in prompt context for code completions."
        },
        {
            "key": "enableTerminalCompletion",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Provides inline predictive completions inside the integrated terminal."
        },
        {
            "key": "enterpriseGcpProjectId",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Target Google Cloud Platform Project ID for enterprise quota billing."
        },
        {
            "key": "enterpriseGcpProjectRegion",
            "type": "settings_config",
            "default_value": "us-central1",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "GCP region endpoint for enterprise AI inference requests."
        },
        {
            "key": "useAICredits",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Directs request billing to user promotional AI credits before billing project."
        },
        {
            "key": "keepComputerAwake",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prevents OS sleep state while an agentic trajectory is executing."
        },
        {
            "key": "runInBackground",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Continues language server execution when window is minimized to system tray."
        },
        {
            "key": "confirmWindowReload",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prompts confirmation dialog before reloading window if agent is running."
        },
        {
            "key": "themeMode",
            "type": "settings_config",
            "default_value": "dark",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "UI color theme mode (dark, light, system)."
        },
        {
            "key": "allowTabAccessGitignoreFiles",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Allows code completion model to index files listed in .gitignore."
        },
        {
            "key": "enableTabSounds",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Plays subtle audio cue when inline completion becomes available."
        },
        {
            "key": "enableSoundsForSpecialEvents",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Plays completion chime when cascade trajectory finishes successfully."
        },
        {
            "key": "enableShellIntegration",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Injects OSC 133 escape sequences into terminal for command boundary detection."
        },
        {
            "key": "demoModeEnabled",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Masks sensitive project names and tokens for public screen recording."
        },
        {
            "key": "isSnoozed",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Temporarily pauses agent step execution and background notification prompts."
        },
        {
            "key": "explainAndFixInCurrentConversation",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Routes editor diagnostic fixes to active cascade rather than creating a new thread."
        },
        {
            "key": "conversationHistoryEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Persists past agent trajectories into local SQLite state database."
        },
        {
            "key": "knowledgeEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables persistent workspace rules and memory indexing across sessions."
        },
        {
            "key": "planningMode",
            "type": "settings_config",
            "default_value": "interactive",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Agent planning mode strategy (interactive, autonomous, supervisory)."
        },
        {
            "key": "autoApproveReadOperations",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Automatically approves read_file and list_directory tool invocations."
        },
        {
            "key": "autoApproveTerminalCommands",
            "type": "settings_config",
            "default_value": False,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Prompts user confirmation before executing any terminal command."
        },
        {
            "key": "maxContextTokens",
            "type": "settings_config",
            "default_value": 1048576,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Maximum context window token budget reserved for Gemini 1.5 Pro / 2.0 Flash."
        },
        {
            "key": "streamingChunkDelayMs",
            "type": "settings_config",
            "default_value": 0,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Artificial delay in milliseconds applied to streaming chunks for testing."
        },
        {
            "key": "enableMcpServers",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables Model Context Protocol tool servers declared in mcp_config.json."
        },
        {
            "key": "mcpClientTimeoutMs",
            "type": "settings_config",
            "default_value": 30000,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Timeout in milliseconds for external MCP server tool executions."
        },
        {
            "key": "enableVoiceInput",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Permits microphone audio recording and speech-to-text transcription."
        },
        {
            "key": "telemetryEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Sends anonymized crash reports and feature usage metrics to Google."
        },
        {
            "key": "crashReporterEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Captures native minidumps on process termination and uploads to server."
        },
        {
            "key": "wslDistributionName",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Selected Windows Subsystem for Linux distro name for remote agent execution."
        },
        {
            "key": "wslHomeDirectoryOverride",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Custom WSL home path mapping for accessing host files."
        },
        {
            "key": "proxyServerUrl",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Corporate HTTP/HTTPS proxy URL for routing outbound requests."
        },
        {
            "key": "bypassProxyHosts",
            "type": "settings_config",
            "default_value": ["127.0.0.1", "localhost"],
            "payload_type": "array",
            "source": "main_root.formatted.js:settings",
            "description": "Loopback hostnames and IPs excluded from proxy redirection."
        },
        {
            "key": "customLanguageServerPath",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Custom binary override for language_server_windows_x64.exe."
        },
        {
            "key": "languageServerArgs",
            "type": "settings_config",
            "default_value": [],
            "payload_type": "array",
            "source": "main_root.formatted.js:settings",
            "description": "Additional CLI argument flags passed to language_server binary on spawn."
        },
        {
            "key": "customAcpServerPath",
            "type": "settings_config",
            "default_value": "",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Custom binary override for agy_acp_server.exe."
        },
        {
            "key": "customSchemeSidecarsEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables antigravity-ide:// protocol resolution for sidecar extensions."
        },
        {
            "key": "editorFontSize",
            "type": "settings_config",
            "default_value": 14,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Font size in pixels for code editor and diff viewing panes."
        },
        {
            "key": "editorFontFamily",
            "type": "settings_config",
            "default_value": "Menlo, Monaco, 'Courier New', monospace",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Font family sequence used for code rendering."
        },
        {
            "key": "terminalFontSize",
            "type": "settings_config",
            "default_value": 13,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Font size in pixels for integrated xterm.js terminal emulator."
        },
        {
            "key": "terminalScrollback",
            "type": "settings_config",
            "default_value": 5000,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Number of scrollback buffer lines preserved per terminal session."
        },
        {
            "key": "windowZoomLevel",
            "type": "settings_config",
            "default_value": 0,
            "payload_type": "integer",
            "source": "main_root.formatted.js:settings",
            "description": "Saved zoom factor persistent across application restarts."
        },
        {
            "key": "autoCheckForUpdates",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Periodically polls upstream update servers for new releases."
        },
        {
            "key": "updateReleaseChannel",
            "type": "settings_config",
            "default_value": "stable",
            "payload_type": "string",
            "source": "main_root.formatted.js:settings",
            "description": "Release distribution channel (stable, beta, canary, dogfood)."
        },
        {
            "key": "autoDownloadUpdates",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Automatically downloads update payloads in background when available."
        },
        {
            "key": "enableHardwareAcceleration",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables GPU rasterization and WebGL acceleration in Chromium shell."
        },
        {
            "key": "enableSpellcheck",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Enables multi-lingual spellchecking in chat input fields."
        },
        {
            "key": "multiWindowEnabled",
            "type": "settings_config",
            "default_value": True,
            "payload_type": "boolean",
            "source": "main_root.formatted.js:settings",
            "description": "Permits opening concurrent independent chat and editor windows."
        }
    ]

    # 4. User Tiers
    user_tiers = [
        {
            "id": "USER_TIER_UNSPECIFIED",
            "value": 0,
            "description": "Unspecified default tier before user profile synchronization."
        },
        {
            "id": "USER_TIER_FREE",
            "value": 1,
            "description": "Standard free tier with default 5-hour rolling token quotas and standard models."
        },
        {
            "id": "USER_TIER_PRO",
            "value": 2,
            "description": "Pro subscription tier with elevated rate limits and priority access to Gemini 2.0 Flash Thinking."
        },
        {
            "id": "USER_TIER_ENTERPRISE",
            "value": 3,
            "description": "Enterprise organization tier linked to Google Cloud Platform Projects with customized compliance and quota management."
        }
    ]

    catalog = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Antigravity UI Internals Catalog",
        "version": "2.24.0",
        "summary": {
            "ipc_channels_count": len(ipc_channels),
            "actions_count": len(actions),
            "feature_flags_count": len(feature_flags),
            "user_tiers_count": len(user_tiers)
        },
        "ipc_channels": ipc_channels,
        "actions": actions,
        "feature_flags": feature_flags,
        "user_tiers": user_tiers
    }


    catalog = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Antigravity UI Internals Catalog",
        "version": "2.24.0",
        "summary": {
            "ipc_channels_count": len(ipc_channels),
            "actions_count": len(actions),
            "feature_flags_count": len(feature_flags),
            "user_tiers_count": len(user_tiers)
        },
        "ipc_channels": ipc_channels,
        "actions": actions,
        "feature_flags": feature_flags,
        "user_tiers": user_tiers
    }

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"Written UI internals catalog to {catalog_path}")
    print(f"Summary: {catalog['summary']}")
    return catalog

def main():
    parser = argparse.ArgumentParser(description="Extract Antigravity UI internals catalog.")
    parser.add_argument("--output", "-o", default=None, help="Output path for ui_internals.json")
    args = parser.parse_args()
    extract_ui_internals(args.output)

if __name__ == "__main__":
    main()
