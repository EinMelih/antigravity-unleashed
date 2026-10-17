(() => {
  if (window.__AMS_WEB_MIRROR) return;
  window.__AMS_WEB_MIRROR = true;
  const readMethods = new Set([
    'getProfileInfo', 'getWindowRole', 'getSyncStatus', 'getReviews', 'getHistory', 'isMaximized',
    'getPRs', 'getIssues', 'getGitStatus', 'getRunLog', 'getTaskPlan', 'getNotes', 'getCompactionCount', 'getTokenStats', 'getGitDiff',
    'nativeStorage.getItems', 'electronUpdater.getState', 'ide.isInstalled', 'wsl.getState',
  ]);
  const readHubOperations = new Set(['services:status', 'api:monitor']);
  async function rpc(operation, args = []) {
    const readonly = readMethods.has(operation) || (operation === 'hubRequest' && readHubOperations.has(args[1]));
    const endpoint = '/api/desktop/ams/' + encodeURIComponent(operation);
    const response = await fetch(readonly ? endpoint + '?args=' + encodeURIComponent(JSON.stringify(args)) : endpoint, {
      method: readonly ? 'GET' : 'POST',
      ...(readonly ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ args }) }),
    });
    const result = await response.json();
    if (!response.ok || result.ok !== true) {
      // Preserve the desktop's explicit status/error object while the HTTP
      // status correctly marks the control-plane operation as failed.
      if (result.native_result !== undefined) return result.native_result;
      const error = new Error(result.error?.message || 'Desktop-Erweiterung ist nicht erreichbar.');
      error.code = result.error?.code || 'AMS_UNAVAILABLE';
      throw error;
    }
    return result.data;
  }
  const api = {};
  const methods = [
    'getProfileInfo', 'getWindowRole', 'getSyncStatus', 'getReviews', 'getHistory', 'isMaximized',
    'getPRs', 'getIssues', 'getGitStatus', 'getRunLog', 'getTaskPlan', 'getNotes', 'getCompactionCount', 'getTokenStats', 'getGitDiff',
    'openBrain', 'minimize', 'maximize', 'unmaximize', 'close', 'zoomIn', 'zoomOut', 'resetZoom',
    'openExternal', 'writeToClipboard', 'applyMemorySuggestion', 'setTitleBarOverlay',
    'commitAndPush', 'setTaskPlan', 'generateCommitMsg', 'deleteTempConversation', 'consolidateMemory', 'setNotes',
    'readSwitchRequest', 'writeStatus', 'hubRequest',
  ];
  for (const method of methods) api[method] = (...args) => rpc(method, args.map(value => value === undefined ? null : value));
  api.getZoomLevel = () => 1;
  // Duplicate the current browser conversation without navigating the user's
  // native primary window to whichever chat this browser is displaying.
  api.openDuplicateWindow = async () => {
    const opened = window.open(location.href, '_blank');
    if (!opened) throw new Error('Der Browser hat das neue Chatfenster blockiert.');
    opened.opener = null;
  };
  const progressListeners = new Set();
  api.onGenerateCommitProgress = callback => { if (typeof callback === 'function') progressListeners.add(callback); };
  api.removeGenerateCommitProgressListener = callback => progressListeners.delete(callback);
  api.generateCommitMsg = async (...args) => {
    for (const callback of progressListeners) callback('Anforderung an den Desktop wird gesendet …');
    try { return await rpc('generateCommitMsg', args.map(value => value === undefined ? null : value)); }
    finally { for (const callback of progressListeners) callback('Desktop-Aufruf beendet.'); }
  };
  window.electronNative = Object.freeze(api);

  const browserStorage = window.nativeStorage;
  let nativeSeed;
  const seed = () => nativeSeed ||= rpc('nativeStorage.getItems');
  browserStorage.getItems = async () => ({ ...(await seed()), ...browserStorage._data });
  browserStorage.updateItems = changes => browserStorage.setItems(changes);

  const updaterListeners = new Set();
  let updaterTimer;
  let lastUpdaterState;
  window.electronUpdater = {
    getState: () => rpc('electronUpdater.getState'),
    checkForUpdates: () => rpc('electronUpdater.checkForUpdates'),
    applyUpdate: () => rpc('electronUpdater.applyUpdate'),
    quitAndInstall: () => rpc('electronUpdater.quitAndInstall'),
    onStateChanged(callback) {
      updaterListeners.add(callback);
      if (!updaterTimer) updaterTimer = setInterval(async () => {
        try {
          const state = await rpc('electronUpdater.getState');
          const signature = JSON.stringify(state);
          if (signature !== lastUpdaterState) {
            lastUpdaterState = signature;
            for (const listener of updaterListeners) listener(state);
          }
        } catch (error) { console.warn('[AMS Web] Update status:', error.message); }
      }, 10000);
      return () => {
        updaterListeners.delete(callback);
        if (!updaterListeners.size) { clearInterval(updaterTimer); updaterTimer = null; }
      };
    },
  };
  window.dialog = {
    showOpenDialog: () => rpc('dialog.showOpenDialog'),
    showOpenMultipleFolderDialog: () => rpc('dialog.showOpenMultipleFolderDialog'),
  };
  window.ide = { isInstalled: () => rpc('ide.isInstalled') };
  window.wsl = { getState: () => rpc('wsl.getState'), connect: distro => rpc('wsl.connect', [distro]) };
  window.nativeNotifications.send = options => rpc('nativeNotifications.send', [options]);
  window.nativeNotifications.openSystemPreferences = () => rpc('nativeNotifications.openSystemPreferences');
  const loadAMS = () => {
    const script = document.createElement('script');
    script.src = '/ams/desktop.js';
    script.dataset.amsDesktopMirror = 'true';
    script.onerror = () => {
      const warning = document.createElement('div');
      warning.setAttribute('role', 'alert');
      warning.id = 'ams-web-load-error';
      warning.textContent = 'Die Desktop-Erweiterungen konnten nicht geladen werden. Bitte den Desktop-Status im Hub prüfen.';
      warning.style.cssText = 'position:fixed;right:16px;bottom:16px;max-width:360px;padding:12px;border:1px solid #ef4444;border-radius:8px;background:#191c24;color:#ffabab;font:13px system-ui;z-index:11000';
      document.body.append(warning);
    };
    document.head.append(script);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadAMS, { once: true });
  else loadAMS();
})();
