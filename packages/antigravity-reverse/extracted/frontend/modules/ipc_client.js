/**
 * Antigravity Frontend - Electron IPC Bridge Client Module
 * Maps contextBridge window.electronBridge calls to main process channels
 */

export class ElectronBridgeClient {
  constructor(
    bridge = typeof window !== "undefined" ? window.electronBridge : null,
  ) {
    this.bridge = bridge;
  }

  isAvailable() {
    return !!this.bridge;
  }

  // Windows & UI Management
  minimize() {
    return this.bridge?.invoke("window:minimize");
  }
  maximize() {
    return this.bridge?.invoke("window:maximize");
  }
  unmaximize() {
    return this.bridge?.invoke("window:unmaximize");
  }
  isMaximized() {
    return this.bridge?.invoke("window:is-maximized");
  }
  close() {
    return this.bridge?.invoke("window:close");
  }
  toggleDevTools() {
    return this.bridge?.invoke("window:toggle-devtools");
  }
  setTitleBarOverlay(overlay) {
    return this.bridge?.invoke("window:set-title-bar-overlay", overlay);
  }
  showContextMenu(items) {
    return this.bridge?.invoke("window:show-context-menu", items);
  }
  zoomIn() {
    return this.bridge?.invoke("window:zoom-in");
  }
  zoomOut() {
    return this.bridge?.invoke("window:zoom-out");
  }
  resetZoom() {
    return this.bridge?.invoke("window:reset-zoom");
  }

  // Workspaces & Dialogs
  openWorkspace() {
    return this.bridge?.invoke("dialog:open-workspace");
  }
  openWorkspaces() {
    return this.bridge?.invoke("dialog:open-workspaces");
  }
  revealInFilePicker(path) {
    return this.bridge?.invoke("shell:reveal-in-file-picker", path);
  }
  openExternal(url) {
    return this.bridge?.invoke("shell:open-external", url);
  }

  // Updater Lifecycle
  getUpdateState() {
    return this.bridge?.invoke("updater:get-state");
  }
  checkForUpdates() {
    return this.bridge?.invoke("updater:check-for-updates");
  }
  applyUpdate() {
    return this.bridge?.invoke("updater:apply");
  }
  quitAndInstall() {
    return this.bridge?.invoke("updater:quit-and-install");
  }

  // System Storage & Logs
  getStorageItems() {
    return this.bridge?.invoke("storage:get-items");
  }
  updateStorageItems(changes) {
    return this.bridge?.invoke("storage:update-items", changes);
  }
  getElectronLogs() {
    return this.bridge?.invoke("logs:electron");
  }

  // Notifications & Agents
  sendNotification(notif) {
    return this.bridge?.invoke("notification:send", notif);
  }
  updateActiveAgentCount(count) {
    return this.bridge?.invoke("agent:update-active-count", count);
  }

  // WSL Integration
  getWslState() {
    return this.bridge?.invoke("wsl:get-state");
  }
  connectWsl(distro) {
    return this.bridge?.invoke("wsl:connect", distro);
  }
}
