/**
 * Antigravity Frontend - Action & Shortcut Registry Module
 * Extracted and deobfuscated from main_root.formatted.js (lines ~15638, ~41798-41918, ~59935, ~71451)
 *
 * This module defines the centralized action table, keyboard shortcut handlers,
 * command palette items, and execution callbacks across the Antigravity React SPA.
 */

// Keybinding modifier mapping and evaluation (lines 41801-41812)
export function evaluateModifiers(binding, isMac = false) {
  const shift = !!binding.shift;
  const alt = !!binding.alt;
  let ctrl = !!binding.ctrl;
  let meta = !!binding.mod;
  if (!isMac) {
    ctrl = !!binding.ctrl || !!binding.mod;
    meta = false;
  }
  return { ctrl, shift, alt, meta };
}

export function matchesKeybinding(event, bindingConfig, disableInWeb = false) {
  const isMac =
    typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
  if (bindingConfig.disableInWeb && disableInWeb) return false;
  const loose = bindingConfig.looseMatch;
  const mods = evaluateModifiers(bindingConfig.binding, isMac);

  if (bindingConfig.binding.isMacOnly && !isMac) return false;
  if (
    bindingConfig.binding.key &&
    event.key.toLowerCase() !== bindingConfig.binding.key.toLowerCase()
  )
    return false;
  if (bindingConfig.binding.code && event.code !== bindingConfig.binding.code)
    return false;

  if (loose) {
    if (mods.ctrl && !event.ctrlKey) return false;
    if (mods.shift && !event.shiftKey) return false;
    if (mods.alt && !event.altKey) return false;
    if (mods.meta && !event.metaKey) return false;
    return true;
  }
  return (
    !!event.ctrlKey === mods.ctrl &&
    !!event.shiftKey === mods.shift &&
    !!event.altKey === mods.alt &&
    !!event.metaKey === mods.meta
  );
}

// Action Table Declarations (extracted from main_root.formatted.js:41822-41918)
export const ACTIONS = {
  // Command Palette & Navigation
  openCommandPaletteWithPrefix: {
    id: "openCommandPaletteWithPrefix",
    label: "Open Command Palette",
    icon: "manage_search",
    keybindings: { binding: { mod: true, shift: true, key: "p" } },
    category: "Command Palette",
  },
  openCommandPalette: {
    id: "openCommandPalette",
    label: "File Picker",
    icon: "search",
    keybindings: { binding: { mod: true, key: "p" } },
    category: "File Search",
  },
  openConvoPicker: {
    id: "openConvoPicker",
    label: "Open Conversation Picker",
    icon: "chat",
    keybindings: { binding: { mod: true, key: "k" } },
    category: "Navigation",
  },
  openWorkspaceSelector: {
    id: "openWorkspaceSelector",
    label: "Open Workspace Selector",
    icon: "atr",
    keybindings: { binding: { mod: true, shift: true, key: "k" } },
    category: "Workspace",
  },

  // Application Controls
  "settings.open": {
    id: "settings.open",
    label: "Open Settings",
    icon: "settings",
    keybindings: { binding: { mod: true, key: "," } },
    category: "System",
  },
  openShortcutsOverlay: {
    id: "openShortcutsOverlay",
    label: "Open Keyboard Shortcuts",
    icon: "keyboard_command_key",
    keybindings: [
      { binding: { mod: true, key: "?" } },
      { binding: { mod: true, shift: true, key: "/" } },
      { binding: { mod: true, shift: true, key: "?" } },
    ],
    category: "Help",
  },
  "sidebar.toggleSidebar": {
    id: "sidebar.toggleSidebar",
    label: "Toggle Sidebar",
    icon: "dock_to_right",
    keybindings: { binding: { mod: true, key: "b" } },
    category: "Layout",
  },
  toggleAuxPane: {
    id: "toggleAuxPane",
    label: "Toggle Auxiliary Pane",
    icon: "dock_to_left",
    keybindings: [
      { binding: { mod: true, shift: true, key: "b" }, disableInWeb: true },
      { binding: { mod: true, alt: true, key: "b" } },
      { binding: { mod: true, alt: true, code: "KeyB", isMacOnly: true } },
    ],
    category: "Layout",
  },
  toggleBottomPane: {
    id: "toggleBottomPane",
    label: "Toggle Terminal",
    icon: "terminal",
    keybindings: [
      { binding: { mod: true, key: "j" } },
      { binding: { mod: true, key: "`" } },
    ],
    category: "Terminal",
  },
  toggleEditor: {
    id: "toggleEditor",
    label: "Toggle Editor",
    icon: "code",
    keybindings: { binding: { mod: true, key: "e" } },
    category: "Editor",
  },
  toggleModelSelector: {
    id: "toggleModelSelector",
    label: "Toggle Model Selector",
    icon: "auto_awesome",
    keybindings: { binding: { mod: true, key: "/" } },
    category: "Model Control",
  },
  toggleProjectSelector: {
    id: "toggleProjectSelector",
    label: "Toggle Project Selector",
    icon: "folder",
    keybindings: { binding: { mod: true, key: ";" } },
    category: "Workspace",
  },
  toggleEnvironmentSelector: {
    id: "toggleEnvironmentSelector",
    label: "Toggle Environment Selector",
    icon: "computer",
    keybindings: { binding: { mod: true, key: "." } },
    category: "Environment",
  },

  // Execution & Agent Lifecycle
  acceptAgentStep: {
    id: "acceptAgentStep",
    label: "Accept Step",
    keybindings: { binding: { alt: true, key: "Enter" } },
    category: "Agent Execution",
  },
  proceedPlanArtifact: {
    id: "proceedPlanArtifact",
    label: "Proceed with Plan",
    keybindings: { binding: { mod: true, key: "Enter" }, useCapture: false },
    category: "Agent Execution",
  },
  startVoiceRecording: {
    id: "startVoiceRecording",
    label: "Start Voice Recording",
    icon: "mic",
    keybindings: [{ binding: { ctrl: true, key: "m" }, isHold: true }],
    category: "Voice Input",
  },
  stopVoiceRecording: {
    id: "stopVoiceRecording",
    label: "Stop Voice Recording",
    icon: "mic_off",
    keybindings: [
      {
        binding: { key: "m" },
        looseMatch: true,
        eventType: "keyup",
        isHold: true,
      },
    ],
    category: "Voice Input",
  },
  toggleVoiceRecording: {
    id: "toggleVoiceRecording",
    label: "Toggle Voice Recording",
    icon: "mic",
    keybindings: [{ binding: { ctrl: true, key: "m" } }],
    category: "Voice Input",
  },
  openNewConversation: {
    id: "openNewConversation",
    label: "New Conversation",
    icon: "chat_add_on",
    keybindings: [
      { binding: { mod: true, key: "n" }, disableInWeb: true },
      { binding: { mod: true, shift: true, key: "o" } },
      { binding: { mod: true, shift: true, key: "l" } },
    ],
    category: "Chat Management",
  },
  openNewEditor: {
    id: "openNewEditor",
    label: "New Editor Window",
    icon: "open_in_new",
    keybindings: { binding: { mod: true, shift: true, key: "n" } },
    category: "Window",
  },
  closeTab: {
    id: "closeTab",
    label: "Close Tab",
    icon: "close",
    keybindings: { binding: { mod: true, key: "w" }, disableInWeb: true },
    category: "Navigation",
  },
  openWorkspace: {
    id: "openWorkspace",
    label: "Open Workspace",
    icon: "folder",
    keybindings: { binding: { mod: true, key: "o" } },
    category: "Workspace",
  },

  // Terminal Controls
  createSplitTerminal: {
    id: "createSplitTerminal",
    label: "Split Terminal",
    icon: "splitscreen",
    keybindings: { binding: { mod: true, key: "\\" } },
    category: "Terminal",
  },
  closeTerminalTab: {
    id: "closeTerminalTab",
    label: "Close Terminal Tab",
    icon: "close",
    keybindings: { binding: { mod: true, key: "w" } },
    category: "Terminal",
  },
  openNewTerminalTab: {
    id: "openNewTerminalTab",
    label: "New Terminal Tab",
    icon: "add",
    keybindings: { binding: { mod: true, key: "t" } },
    category: "Terminal",
  },

  // Chat Input & Mentions
  mentionSelection: {
    id: "mentionSelection",
    label: "Mention Selection",
    icon: "ads_click",
    keybindings: { binding: { mod: true, key: "l" }, disableInWeb: true },
    accelerator: "CmdOrCtrl+L",
    category: "Chat Input",
  },
  focusInput: {
    id: "focusInput",
    label: "Focus Input",
    icon: "edit",
    keybindings: [
      { binding: { mod: true, key: "l" }, disableInWeb: true },
      { binding: { mod: true, key: "i" } },
    ],
    category: "Chat Input",
  },

  // View & Zoom
  zoomIn: {
    id: "zoomIn",
    label: "Zoom In",
    icon: "zoom_in",
    keybindings: [
      { binding: { mod: true, key: "=" }, disableInWeb: true },
      { binding: { mod: true, key: "+" }, disableInWeb: true },
    ],
    category: "View",
  },
  zoomOut: {
    id: "zoomOut",
    label: "Zoom Out",
    icon: "zoom_out",
    keybindings: [{ binding: { mod: true, key: "-" }, disableInWeb: true }],
    category: "View",
  },
  zoomReset: {
    id: "zoomReset",
    label: "Reset Zoom",
    icon: "zoom_out_map",
    keybindings: [{ binding: { mod: true, key: "0" }, disableInWeb: true }],
    category: "View",
  },
  findInPane: {
    id: "findInPane",
    label: "Find in Pane",
    icon: "search",
    keybindings: { binding: { mod: true, key: "f" } },
    accelerator: "CmdOrCtrl+F",
    category: "Search",
  },
  goBack: {
    id: "goBack",
    label: "Go Back",
    icon: "arrow_back",
    keybindings: { binding: { mod: true, key: "[" }, disableInWeb: true },
    accelerator: "CmdOrCtrl+[",
    category: "Navigation",
  },
  goForward: {
    id: "goForward",
    label: "Go Forward",
    icon: "arrow_forward",
    keybindings: { binding: { mod: true, key: "]" }, disableInWeb: true },
    accelerator: "CmdOrCtrl+]",
    category: "Navigation",
  },

  // Search & VCS
  codeSearch: {
    id: "codeSearch",
    label: "Code Search",
    icon: "code",
    keybindings: { binding: { mod: true, shift: true, key: "f" } },
    category: "Search",
  },
  vcs: {
    id: "vcs",
    label: "Open Commit Graph",
    icon: "commit",
    keybindings: { binding: { mod: true, shift: true, key: "c" } },
    category: "VCS / Git",
  },
  openConversationHistory: {
    id: "openConversationHistory",
    label: "Open Conversation History",
    icon: "history",
    keybindings: { binding: { mod: true, key: "y" } },
    category: "History",
  },
  openScheduledTasks: {
    id: "openScheduledTasks",
    label: "Scheduled Tasks",
    icon: "schedule",
    keybindings: { binding: { mod: true, key: "u" } },
    category: "Automation",
  },
  "conversation.selectNext": {
    id: "conversation.selectNext",
    label: "Select Next Conversation",
    keybindings: { binding: { alt: true, key: "ArrowDown" } },
    category: "History",
  },
  "conversation.selectPrevious": {
    id: "conversation.selectPrevious",
    label: "Select Previous Conversation",
    keybindings: { binding: { alt: !0, key: "ArrowUp" } },
    category: "History",
  },
  openTrajectory: {
    id: "openTrajectory",
    label: "Open Conversation",
    icon: "open_in_new",
    keybindings: { binding: { key: "Enter" } },
    category: "History",
  },
  markAsReadHistory: {
    id: "markAsReadHistory",
    label: "Mark as Read",
    icon: "mark_chat_read",
    keybindings: { binding: { shift: true, key: "i" } },
    category: "History",
  },
  markAsUnreadHistory: {
    id: "markAsUnreadHistory",
    label: "Mark as Unread",
    icon: "mark_chat_unread",
    keybindings: { binding: { shift: true, key: "u" } },
    category: "History",
  },
  deleteHistory: {
    id: "deleteHistory",
    label: "Delete Conversation",
    icon: "delete",
    keybindings: { binding: { shift: true, key: "#" } },
    category: "History",
  },
  archiveRestoreHistory: {
    id: "archiveRestoreHistory",
    label: "Archive / Restore",
    icon: "archive",
    keybindings: { binding: { shift: true, key: "e" } },
    category: "History",
  },

  // Command Palette Top-Level Modes (lines 71451)
  Commands: {
    id: "Commands",
    label: "Command picker",
    icon: "manage_search",
    prefix: ">",
    category: "Command Palette",
  },
  Files: {
    id: "Files",
    label: "File picker",
    icon: "search",
    prefix: "",
    category: "Command Palette",
  },
  Conversations: {
    id: "Conversations",
    label: "Conversation picker",
    icon: "chat",
    prefix: "#",
    category: "Command Palette",
  },
  Projects: {
    id: "Projects",
    label: "Project picker",
    icon: "folder",
    prefix: "@",
    category: "Command Palette",
  },
};
