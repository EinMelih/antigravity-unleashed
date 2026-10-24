"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.registerIpcHandlers = registerIpcHandlers;
const electron_1 = require("electron");
const electron_updater_1 = require("electron-updater");
const types_1 = require("./types");
const updater_1 = require("./updater");
const main_1 = __importDefault(require("electron-log/main"));
const fs = __importStar(require("fs/promises"));
const customScheme_1 = require("./customScheme");
const tray_1 = require("./tray");
const constants_1 = require("./ideInstall/constants");
const url_1 = require("url");
const wsl_1 = require("./wsl");
const menu_1 = require("./menu");
const runtimePaths = require('./paths');
const amsMainBootstrap = require('./amsMainBootstrap');
function profileDataPath(...parts) {
    return require('path').join(runtimePaths.getAppDataDir(), ...parts);
}
function buildContextMenuTemplate(items, onSelect) {
    return items.map((item) => {
        if (item.type === 'separator') {
            return { type: 'separator' };
        }
        if (item.type === 'submenu' || (item.submenu && item.submenu.length > 0)) {
            return {
                id: item.id,
                label: item.label ?? '',
                type: 'submenu',
                enabled: !item.disabled,
                submenu: buildContextMenuTemplate(item.submenu ?? [], onSelect),
            };
        }
        return {
            id: item.id,
            label: item.label ?? '',
            type: item.type ?? 'normal',
            checked: item.checked,
            enabled: !item.disabled,
            accelerator: item.accelerator,
            click: () => onSelect(item.id),
        };
    });
}
/**
 * Registers all IPC handlers for the main process.
 */
function registerIpcHandlers(storageManager) {
    amsMainBootstrap.hardenStorageManager(storageManager);
    const crypto = require('crypto');
    const path = require('path');
    const fs_std = require('fs');
    const { execFile } = require('child_process');
    const util = require('util');
    const execFilePromise = util.promisify(execFile);
    const {
        TemporaryConversationRegistry,
        OneShotPathLeaseRegistry,
        extractGrpcStatus,
    } = require('./amsIpcSecurity');
    const preparedWorkspaceLeases = new OneShotPathLeaseRegistry({ ttlMs: 30_000 });

    function verifyHubWorkspacePath(workspacePath) {
        const http = require('http');
        return new Promise((resolve, reject) => {
            const body = Buffer.from(JSON.stringify({ path: workspacePath }), 'utf8');
            const request = http.request({
                host: '127.0.0.1',
                port: 8000,
                path: '/api/internal/workspace-authorization',
                method: 'POST',
                timeout: 4_000,
                headers: {
                    Accept: 'application/json',
                    'Content-Type': 'application/json',
                    'Content-Length': String(body.length),
                },
            }, (response) => {
                const chunks = [];
                let size = 0;
                let failed = false;
                response.on('data', (chunk) => {
                    size += chunk.length;
                    if (size > 64 * 1024) {
                        failed = true;
                        response.destroy();
                        reject(new Error('Anti-Gravity Hub workspace response exceeded 64 KiB.'));
                        return;
                    }
                    chunks.push(chunk);
                });
                response.on('end', () => {
                    if (failed) return;
                    if (response.statusCode !== 200) {
                        reject(new Error(`Anti-Gravity Hub project verification failed (${response.statusCode}).`));
                        return;
                    }
                    try {
                        const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
                        if (!payload || payload.authorized !== true) {
                            throw new Error('The workspace is not authorized by the local Anti-Gravity Hub.');
                        }
                        resolve(true);
                    } catch (error) {
                        reject(new Error(`Anti-Gravity Hub workspace response was invalid: ${error.message}`));
                    }
                });
            });
            request.on('timeout', () => request.destroy(new Error('Anti-Gravity Hub project verification timed out.')));
            request.on('error', reject);
            request.write(body);
            request.end();
        });
    }

    let cachedPythonPath = null;

    function getPythonPath() {
        if (cachedPythonPath) return cachedPythonPath;

        const fs_std = require('fs');
        const path = require('path');
        const os = require('os');

        let candidates = [];

        if (process.platform === 'win32') {
            const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
            const pythonDir = path.join(localAppData, 'Programs', 'Python');
            if (fs_std.existsSync(pythonDir)) {
                try {
                    const dirs = fs_std.readdirSync(pythonDir);
                    const pythonDirs = dirs.filter(d => d.startsWith('Python')).sort().reverse();
                    for (const dir of pythonDirs) {
                        const pyPath = path.join(pythonDir, dir, 'python.exe');
                        if (fs_std.existsSync(pyPath)) {
                            candidates.push(pyPath);
                        }
                    }
                } catch (e) {}
            }
            const standardPaths = [
                path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Python312', 'python.exe'),
                path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Python311', 'python.exe'),
                path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Python310', 'python.exe'),
                path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Python39', 'python.exe')
            ];
            for (const p of standardPaths) {
                if (fs_std.existsSync(p)) {
                    try {
                        if (fs_std.statSync(p).size > 0) {
                            candidates.push(p);
                        }
                    } catch (e) {}
                }
            }
        }

        let fallback = null;
        for (const py of candidates) {
            const sitePackagesAiohttp = path.join(path.dirname(py), 'Lib', 'site-packages', 'aiohttp');
            if (fs_std.existsSync(sitePackagesAiohttp)) {
                cachedPythonPath = py;
                return py;
            }
            if (fallback === null && fs_std.existsSync(py)) {
                fallback = py;
            }
        }

        cachedPythonPath = fallback || 'python';
        return cachedPythonPath;
    }


    const securityTokens = new Map();
    const CONVERSATION_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
    const temporaryConversationIds = new TemporaryConversationRegistry();

    function normalizeConversationId(value, optional = false) {
        if ((value === undefined || value === null || value === '') && optional) {
            return null;
        }
        if (typeof value !== 'string' || !CONVERSATION_ID_PATTERN.test(value)) {
            throw new Error('Invalid conversation ID.');
        }
        return value;
    }

    const WORKSPACE_LOOKUP_SCRIPT = [
        'import sqlite3, sys',
        'db_path = sys.argv[1]',
        'db_uri = db_path.replace(chr(92), "/")',
        'conn = sqlite3.connect("file:" + db_uri + "?mode=ro", uri=True, timeout=1.0)',
        'row = conn.execute("SELECT data FROM trajectory_metadata_blob WHERE id = \'main\'").fetchone()',
        'data = row[0] if row else b""',
        'index = data.find(b"file:///")',
        'end = index',
        'limit = min(len(data), index + 4096) if index >= 0 else 0',
        'while end < limit and 32 <= data[end] <= 126: end += 1',
        'print(data[index:end].decode("utf-8", errors="ignore") if index >= 0 else "")',
    ].join('\n');

    async function readWorkspaceUriFromDatabase(dbPath) {
        const { stdout } = await execFilePromise(
            getPythonPath(),
            ['-c', WORKSPACE_LOOKUP_SCRIPT, dbPath],
            { timeout: 5000, windowsHide: true, maxBuffer: 1024 * 1024 },
        );
        return stdout.trim();
    }

    function validateOrigin(event, options = {}) {
        const senderUrl = event.sender.getURL();
        if (senderUrl === 'about:blank' || senderUrl === '') {
            if (options.allowUncommittedWindow && electron_1.BrowserWindow.fromWebContents(event.sender)) {
                return;
            }
            throw new Error('IPC Security check failed: sender has no committed app origin');
        }
        try {
            const parsed = new URL(senderUrl);
            let trustedDevOrigin = null;
            if (process.env.DEV_URL) {
                try {
                    const devUrl = new URL(process.env.DEV_URL);
                    if (devUrl.protocol === 'https:' || devUrl.protocol === 'http:') {
                        trustedDevOrigin = devUrl.origin;
                    }
                } catch (_err) {
                    // An invalid DEV_URL must never broaden the production allowlist.
                }
            }
            const isConfiguredDevOrigin = trustedDevOrigin !== null && parsed.origin === trustedDevOrigin;
            let productionOrigin = null;
            try {
                const languageServer = require('./languageServer');
                const appConstants = require('./constants');
                const port = languageServer.getLsPort();
                if (port) {
                    productionOrigin = new URL(appConstants.WINDOW_ORIGIN + ':' + port).origin;
                }
            } catch (_err) {
                // Before the LS has started only the narrow uncommitted-window
                // token bootstrap above is allowed.
            }
            const isProductionOrigin = productionOrigin !== null && parsed.origin === productionOrigin;
            if (!isConfiguredDevOrigin && !isProductionOrigin) {
                throw new Error('Forbidden sender origin: ' + senderUrl);
            }
        } catch (err) {
            throw new Error('IPC Security check failed: ' + err.message);
        }
    }

    function getOrCreateSecurityToken(event) {
        const senderId = event.sender.id;
        let token = securityTokens.get(senderId);
        if (!token) {
            token = crypto.randomUUID();
            securityTokens.set(senderId, token);
            event.sender.once('destroyed', () => {
                securityTokens.delete(senderId);
            });
        }
        return token;
    }

    function validateToken(event, token) {
        const expectedToken = securityTokens.get(event.sender.id);
        if (typeof token !== 'string' || typeof expectedToken !== 'string') {
            throw new Error('Invalid or missing security token');
        }
        const supplied = Buffer.from(token, 'utf8');
        const expected = Buffer.from(expectedToken, 'utf8');
        if (supplied.length !== expected.length || !crypto.timingSafeEqual(supplied, expected)) {
            throw new Error('Invalid or missing security token');
        }
    }

    function isPathInside(rootPath, targetPath) {
        const relativePath = path.relative(path.resolve(rootPath), path.resolve(targetPath));
        return relativePath === '' ||
            (relativePath !== '..' && !relativePath.startsWith(`..${path.sep}`) && !path.isAbsolute(relativePath));
    }

    async function resolveWorkspacePath(conversationId) {
        const os = require('os');
        let repoPath = path.join(os.homedir(), '.gemini', 'config');

        if (conversationId) {
            const safeConversationId = normalizeConversationId(conversationId);
            const dbPath = profileDataPath('conversations', safeConversationId + '.db');
            if (fs_std.existsSync(dbPath)) {
                try {
                    const uri = await readWorkspaceUriFromDatabase(dbPath);
                    if (uri) {
                        const parsedPath = decodeURIComponent(uri.replace('file:///', ''));
                        if (fs_std.existsSync(parsedPath)) {
                            repoPath = parsedPath;
                        }
                    }
                } catch (e) {
                    console.error('[AMS IPC] Error getting path via python:', e);
                }
            }
        }
        return path.resolve(repoPath);
    }

    // Security Token Retrieval
    electron_1.ipcMain.handle('security:get-token', (event) => {
        // During the earliest preload phase Electron may not have committed the
        // destination URL yet. Only token issuance gets this narrow fallback;
        // every privileged operation still requires a committed trusted origin.
        validateOrigin(event, { allowUncommittedWindow: true });
        return getOrCreateSecurityToken(event);
    });

    // Open duplicate window
    electron_1.ipcMain.handle('window:open-duplicate', async (event, token) => {
        try {
            validateOrigin(event);
            validateToken(event, token);
            const senderUrl = event.sender.getURL();
            const { createWindow } = require('./utils');
            const win = createWindow(senderUrl, storageManager);
            win.__antigravityWindowRole = 'duplicate';
            win.webContents.setBackgroundThrottling(false);
            return { success: true, status: 'success' };
        } catch (err) {
            console.error('[IPC Window] window:open-duplicate failed:', err);
            return { success: false, status: 'error', message: err.message };
        }
    });

    // One-shot folder selection for the Hub's native project wizard. The main
    // process independently verifies that the exact canonical folder is
    // already registered in the local Hub before it can bypass one dialog.
    electron_1.ipcMain.handle('dialog:prepare-workspace', async (event, token, workspacePath) => {
        validateOrigin(event);
        validateToken(event, token);
        if (typeof workspacePath !== 'string' || !workspacePath.trim() || workspacePath.length > 32_768) {
            throw new Error('A bounded workspace path is required.');
        }
        let resolvedPath;
        try {
            const realpath = fs_std.realpathSync.native || fs_std.realpathSync;
            resolvedPath = realpath(workspacePath);
            if (!fs_std.statSync(resolvedPath).isDirectory()) {
                throw new Error('The workspace path is not a directory.');
            }
            await verifyHubWorkspacePath(resolvedPath);
        } catch (error) {
            preparedWorkspaceLeases.delete(event.sender.id);
            throw error;
        }
        preparedWorkspaceLeases.issue(event.sender.id, resolvedPath);
        event.sender.once('destroyed', () => preparedWorkspaceLeases.delete(event.sender.id));
        return { success: true, expires_in_ms: 30_000 };
    });

    // Dialog
    async function dialogDefaultPath() {
        const distro = (0, wsl_1.getActiveWslDistro)();
        if (!distro) return undefined;
        try {
            return (0, wsl_1.distroToWindowsPath)(await (0, wsl_1.getDistroHome)(distro), distro);
        } catch {
            return undefined;
        }
    }
    function mapPickedPath(picked) {
        const distro = (0, wsl_1.getActiveWslDistro)();
        if (!distro) return picked;
        const translated = (0, wsl_1.windowsToDistroPath)(picked, distro);
        if (translated.error) {
            electron_1.dialog.showErrorBox('Cannot open folder', translated.error);
            return undefined;
        }
        if (translated.warning) {
            void electron_1.dialog.showMessageBox({
                type: 'warning',
                message: 'Folder is on the Windows filesystem',
                detail: translated.warning,
            });
        }
        return translated.path;
    }
    electron_1.ipcMain.handle('dialog:open-workspace', async (event) => {
        validateOrigin(event);
        const preparedPath = preparedWorkspaceLeases.consume(event.sender.id);
        if (preparedPath) return mapPickedPath(preparedPath);
        const result = await electron_1.dialog.showOpenDialog({
            properties: ['openDirectory', 'createDirectory'],
            title: 'Open workspace',
            defaultPath: await dialogDefaultPath(),
        });
        if (result.canceled || result.filePaths.length === 0) {
            return undefined;
        }
        return mapPickedPath(result.filePaths[0]);
    });
    // Like 'dialog:open-workspace' but allows selecting multiple folders,
    // returning an array of paths (empty if cancelled).
    electron_1.ipcMain.handle('dialog:open-workspaces', async (event) => {
        validateOrigin(event);
        const result = await electron_1.dialog.showOpenDialog({
            properties: ['openDirectory', 'createDirectory', 'multiSelections'],
            title: 'Open workspaces',
            defaultPath: await dialogDefaultPath(),
        });
        if (result.canceled || result.filePaths.length === 0) {
            return [];
        }
        return result.filePaths.map(mapPickedPath).filter((picked) => picked !== undefined);
    });
    // Auto-updater
    electron_1.ipcMain.handle('updater:get-state', () => {
        return (0, updater_1.getLastState)();
    });
    electron_1.ipcMain.handle('updater:apply', async () => {
        (0, updater_1.broadcastState)({ type: types_1.UpdateState.Ready });
    });
    electron_1.ipcMain.handle('updater:quit-and-install', () => {
        if (!electron_1.app.isPackaged) {
            console.log('[AutoUpdater] Skipping quitAndInstall (requires a packaged app).');
            return;
        }
        electron_updater_1.autoUpdater.quitAndInstall();
    });
    // Notifications
    electron_1.ipcMain.handle('notification:send', (_, options) => {
        const notification = new electron_1.Notification({
            title: options.title,
            body: options.body,
            silent: options.silent ?? false,
        });
        notification.on('click', () => {
            const win = electron_1.BrowserWindow.getAllWindows()[0];
            if (win) {
                if (win.isMinimized()) {
                    win.restore();
                }
                win.show();
                win.focus();
                if (options.payload) {
                    win.webContents.send('notification:clicked', options.payload);
                }
            }
        });
        notification.show();
    });
    // Note: copied from our desktop AGY implementation:
    // vs/platform/nativeNotification/electron-main/electronNotificationService.ts
    electron_1.ipcMain.handle('notification:open-system-preferences', async () => {
        if (process.platform === 'darwin') {
            void electron_1.shell.openExternal('x-apple.systempreferences:com.apple.preference.notifications');
        }
        else if (process.platform === 'win32') {
            void electron_1.shell.openExternal('ms-settings:notifications');
        }
        else if (process.platform === 'linux') {
            const { exec } = await Promise.resolve().then(() => __importStar(require('child_process')));
            const commands = [
                'gnome-control-center notifications',
                'systemsettings kcm_notifications',
                'xfce4-notifyd-config',
                'gnome-control-center',
                'systemsettings',
            ];
            for (const command of commands) {
                try {
                    exec(command);
                    return; // If one command executes without immediate error, assume success for now
                }
                catch {
                    // Try next
                }
            }
        }
    });
    // Storage
    electron_1.ipcMain.handle('storage:get-items', async () => {
        return storageManager.getItems();
    });
    electron_1.ipcMain.handle('storage:update-items', async (_event, changes) => {
        await storageManager.updateItems(changes);
    });
    // Model Bridge File System Access (Bypass contextIsolation/sandbox restrictions)
    electron_1.ipcMain.handle('bridge:read-switch-request', async (event, token) => {
        try {
            validateOrigin(event);
            validateToken(event, token);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const switchFile = profileDataPath('model_switch_request.json');
            if (fs_std.existsSync(switchFile)) {
                const content = fs_std.readFileSync(switchFile, 'utf-8');
                try {
                    fs_std.unlinkSync(switchFile);
                } catch (e) {}
                return JSON.parse(content);
            }
        } catch (err) {
            console.error('[AMS Bridge IPC] read-switch-request failed:', err);
        }
        return null;
    });
    electron_1.ipcMain.handle('bridge:write-status', async (event, token, modelName) => {
        try {
            validateOrigin(event);
            validateToken(event, token);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const statusFile = profileDataPath('active_model_status.json');
            const dir = path.dirname(statusFile);
            if (!fs_std.existsSync(dir)) {
                fs_std.mkdirSync(dir, { recursive: true });
            }
            fs_std.writeFileSync(statusFile, JSON.stringify({ model: modelName, timestamp: Date.now() }), 'utf-8');
            return true;
        } catch (err) {
            console.error('[AMS Bridge IPC] write-status failed:', err);
        }
        return false;
    });
    // Anti-Gravity Hub bridge. The renderer selects from fixed local operations;
    // it can neither choose a host nor forward arbitrary headers.
    electron_1.ipcMain.handle('hub:request', async (event, token, operation, payload = {}) => {
        validateOrigin(event);
        validateToken(event, token);

        const http = require('http');
        const safePayload = payload && typeof payload === 'object' ? payload : {};

        const requestJson = (spec, allowText = false) => new Promise((resolve, reject) => {
            const body = spec.body === undefined ? null : Buffer.from(JSON.stringify(spec.body), 'utf8');
            const request = http.request({
                host: '127.0.0.1',
                port: spec.port,
                path: spec.path,
                method: spec.method || 'GET',
                timeout: Number(spec.timeoutMs || 120000),
                headers: body ? {
                    'Content-Type': 'application/json',
                    'Content-Length': String(body.length),
                    ...(spec.headers || {}),
                } : (spec.headers || {}),
            }, (response) => {
                const chunks = [];
                let size = 0;
                response.on('data', (chunk) => {
                    size += chunk.length;
                    if (size > 6 * 1024 * 1024) {
                        request.destroy(new Error('Anti-Gravity Hub response exceeded 6 MiB.'));
                        return;
                    }
                    chunks.push(chunk);
                });
                response.on('end', () => {
                    const text = Buffer.concat(chunks).toString('utf8');
                    let data = {};
                    if (text) {
                        try {
                            data = JSON.parse(text);
                        } catch (_) {
                            if (!allowText) {
                                reject(new Error('Anti-Gravity Hub returned invalid JSON.'));
                                return;
                            }
                            data = { text };
                        }
                    }
                    if ((response.statusCode || 500) < 200 || (response.statusCode || 500) >= 300) {
                        const detail = data.error && typeof data.error === 'object' ? data.error.message : data.error;
                        const error = new Error(detail || `Anti-Gravity Hub request failed (${response.statusCode}).`);
                        error.httpStatus = response.statusCode;
                        error.errorType = data.error && typeof data.error === 'object' ? data.error.type : 'http_error';
                        reject(error);
                        return;
                    }
                    resolve(data);
                });
            });
            request.on('timeout', () => request.destroy(new Error('Anti-Gravity Hub request timed out.')));
            request.on('error', reject);
            if (body) request.write(body);
            request.end();
        });

        if (operation === 'api:monitor') {
            try {
                const runtimeConfigPath = require('path').join(require('os').homedir(), '.gemini', 'config', 'antigravity-hub', 'config.json');
                const runtimeConfig = JSON.parse(require('fs').readFileSync(runtimeConfigPath, 'utf8'));
                const keys = runtimeConfig.api_keys && typeof runtimeConfig.api_keys === 'object' ? Object.keys(runtimeConfig.api_keys) : [];
                const token = keys.length ? keys[0] : String(runtimeConfig.auth_token || '');
                const headers = token ? { Authorization: 'Bearer ' + token } : {};
                const data = await requestJson({ port: 8001, path: '/api/monitor', headers, timeoutMs: 5000 });
                return { ok: true, data, checked_at: Date.now() };
            } catch (error) {
                return { ok: false, data: null, error: { message: error.message, type: error.errorType || error.code || 'monitor_error', http_status: error.httpStatus || null }, checked_at: Date.now() };
            }
        }

        if (operation === 'services:status') {
            const probe = async (port, path, allowText = false) => {
                const startedAt = Date.now();
                try {
                    await requestJson({ port, path, method: 'GET' }, allowText);
                    return { online: true, latency_ms: Date.now() - startedAt };
                } catch (error) {
                    return { online: false, latency_ms: null, error: error.message };
                }
            };
            const [hub, bridge] = await Promise.all([
                probe(8000, '/health'),
                probe(8001, '/health'),
            ]);
            return { hub, bridge, checked_at: Date.now() };
        }

        if (operation === 'services:start') {
            const { spawn } = require('child_process');
            const nodeFs = require('fs');
            const os = require('os');
            const path = require('path');
            const runtimeConfigPath = path.join(
                os.homedir(),
                '.gemini',
                'config',
                'antigravity-hub',
                'config.json'
            );
            let hubRoot = String(process.env.ANTIGRAVITY_HUB_ROOT || '').trim();
            if (!hubRoot && nodeFs.existsSync(runtimeConfigPath)) {
                try {
                    const runtimeConfig = JSON.parse(nodeFs.readFileSync(runtimeConfigPath, 'utf8'));
                    hubRoot = typeof runtimeConfig.hub_root === 'string' ? runtimeConfig.hub_root.trim() : '';
                } catch (error) {
                    return { success: false, error: `Could not read Hub runtime config: ${error.message}` };
                }
            }
            const scriptPath = hubRoot ? path.join(hubRoot, 'start_services.ps1') : '';
            if (!scriptPath || !nodeFs.existsSync(scriptPath)) {
                return {
                    success: false,
                    error: 'Hub root is not configured. Set ANTIGRAVITY_HUB_ROOT or config.json -> hub_root.'
                };
            }
            const restart = safePayload.restart === true;
            const args = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', scriptPath];
            if (restart) args.push('-Restart');
            try {
                const child = spawn('powershell.exe', args, {
                    cwd: hubRoot,
                    stdio: 'ignore',
                    windowsHide: true,
                });
                child.once('error', (error) => {
                    console.error('[IPC Hub] Service start failed:', error);
                });
                child.once('exit', (code) => {
                    if (code !== 0) {
                        console.error(`[IPC Hub] Service start exited with code ${code}.`);
                    }
                });
                return { success: true, restart, pid: child.pid };
            } catch (error) {
                return { success: false, restart, error: error.message };
            }
        }

        throw new Error('Unsupported Anti-Gravity Hub operation.');
    });
    // Logs
    electron_1.ipcMain.handle('logs:electron', async () => {
        try {
            const logPath = main_1.default.transports.file.getFile().path;
            const contents = await fs.readFile(logPath, 'utf-8');
            return contents;
        }
        catch (err) {
            return `Failed to read logs: ${String(err)}`;
        }
    });
    // Sidecar extension custom scheme
    electron_1.ipcMain.handle('extensions:send-authorities', async (_event, authorities) => {
        customScheme_1.extensionAuthorities.clear();
        for (const [key, value] of Object.entries(authorities)) {
            customScheme_1.extensionAuthorities.set(key, value);
        }
    });
    // Agent
    electron_1.ipcMain.handle('agent:update-active-count', async (_event, count) => {
        (0, tray_1.updateTrayAgentCount)(count);
    });
    // Window
    const getSenderWindow = (event) => electron_1.BrowserWindow.fromWebContents(event.sender)
        || electron_1.BrowserWindow.getFocusedWindow()
        || electron_1.BrowserWindow.getAllWindows()[0];
    electron_1.ipcMain.handle('window:set-title-bar-overlay', async (event, options) => {
        const win = getSenderWindow(event);
        if (win && process.platform === 'win32') {
            win.setTitleBarOverlay({
                color: options.color,
                symbolColor: options.symbolColor,
                height: 30,
            });
        }
    });
    electron_1.ipcMain.handle('window:minimize', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.minimize();
        }
    });
    electron_1.ipcMain.handle('window:maximize', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.maximize();
        }
    });
    electron_1.ipcMain.handle('window:unmaximize', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.unmaximize();
        }
    });
    electron_1.ipcMain.handle('window:is-maximized', async (event) => {
        const win = getSenderWindow(event);
        return win ? win.isMaximized() : false;
    });
    electron_1.ipcMain.handle('window:get-role', async (event) => {
        const win = getSenderWindow(event);
        return win && win.__antigravityWindowRole === 'duplicate'
            ? 'duplicate'
            : 'primary';
    });
    electron_1.ipcMain.handle('window:get-profile-info', (event) => {
        validateOrigin(event);
        return amsMainBootstrap.getProfileInfo(runtimePaths);
    });
    electron_1.ipcMain.handle('window:prepare-automation', async (event) => {
        const win = getSenderWindow(event);
        if (!win) {
            return { success: false, error: 'window_not_found' };
        }
        win.webContents.setBackgroundThrottling(false);
        if (win.isMinimized()) {
            win.restore();
        }
        win.showInactive();
        return { success: true, minimized: win.isMinimized() };
    });
    electron_1.ipcMain.handle('window:close', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.close();
        }
    });
    electron_1.ipcMain.handle('window:toggle-devtools', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.webContents.toggleDevTools();
        }
    });
    let activeContextMenu = null;
    electron_1.ipcMain.handle('window:show-context-menu', async (event, items) => {
        validateOrigin(event);
        const win = getSenderWindow(event);
        if (!win || !Array.isArray(items) || items.length === 0) return null;
        activeContextMenu?.closePopup?.(win);
        return new Promise((resolve) => {
            let settled = false;
            const template = buildContextMenuTemplate(items, (id) => {
                if (!settled) {
                    settled = true;
                    activeContextMenu = null;
                    resolve(id);
                }
            });
            const menu = electron_1.Menu.buildFromTemplate(template);
            activeContextMenu = menu;
            menu.popup({
                window: win,
                callback: () => {
                    setImmediate(() => {
                        if (activeContextMenu === menu) activeContextMenu = null;
                        if (!settled) {
                            settled = true;
                            resolve(null);
                        }
                    });
                },
            });
        });
    });
    electron_1.ipcMain.handle('window:close-context-menu', (event) => {
        validateOrigin(event);
        const win = getSenderWindow(event);
        activeContextMenu?.closePopup?.(win);
        activeContextMenu = null;
    });
    // Main-process zoom is persisted by the official storage layer.
    const ZOOM_LEVEL_KEY = 'zoomLevel';
    const ZOOM_STEP = 0.5;
    electron_1.ipcMain.handle('window:zoom-in', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            const newLevel = win.webContents.getZoomLevel() + ZOOM_STEP;
            win.webContents.setZoomLevel(newLevel);
            await storageManager.updateItems({ [ZOOM_LEVEL_KEY]: String(newLevel) });
        }
    });
    electron_1.ipcMain.handle('window:zoom-out', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            const newLevel = win.webContents.getZoomLevel() - ZOOM_STEP;
            win.webContents.setZoomLevel(newLevel);
            await storageManager.updateItems({ [ZOOM_LEVEL_KEY]: String(newLevel) });
        }
    });
    electron_1.ipcMain.handle('window:reset-zoom', async (event) => {
        const win = getSenderWindow(event);
        if (win) {
            win.webContents.setZoomLevel(0);
            await storageManager.updateItems({ [ZOOM_LEVEL_KEY]: String(0) });
        }
    });
    // Auto-updater manual check
    electron_1.ipcMain.handle('updater:check-for-updates', () => {
        (0, updater_1.checkForUpdates)(true);
    });
    // Safe external shell launch
    electron_1.ipcMain.handle('shell:open-external', async (_event, url) => {
        if (url.startsWith('https://') ||
            url.startsWith('http://') ||
            url.startsWith('antigravity-ide://')) {
            await electron_1.shell.openExternal(url);
        }
    });
    electron_1.ipcMain.handle('shell:reveal-in-file-picker', (event, fileUrl) => {
        validateOrigin(event);
        const distro = (0, wsl_1.getActiveWslDistro)();
        if (distro) {
            const posixPath = (0, url_1.fileURLToPath)(fileUrl, { windows: false });
            electron_1.shell.showItemInFolder((0, wsl_1.distroToWindowsPath)(posixPath, distro));
            return;
        }
        electron_1.shell.showItemInFolder((0, url_1.fileURLToPath)(fileUrl));
    });
    electron_1.ipcMain.handle('shell:open-brain', async (event) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const brainPath = profileDataPath('brain');
            const logPath = profileDataPath('scratch', 'ipc_brain.log');

            // Verzeichnis sicherstellen
            const scratchDir = path.dirname(logPath);
            if (!fs_std.existsSync(scratchDir)) {
                fs_std.mkdirSync(scratchDir, { recursive: true });
            }

            fs_std.appendFileSync(logPath, `[${new Date().toISOString()}] IPC shell:open-brain invoked. Target path: ${brainPath}\n`, 'utf-8');

            if (!fs_std.existsSync(brainPath)) {
                fs_std.appendFileSync(logPath, `[${new Date().toISOString()}] Target path does not exist!\n`, 'utf-8');
                return;
            }

            const result = await electron_1.shell.openPath(brainPath);
            fs_std.appendFileSync(logPath, `[${new Date().toISOString()}] shell.openPath result (empty string means success): "${result}"\n`, 'utf-8');
        } catch (err) {
            try {
                const os = require('os');
                const path = require('path');
                const fs_std = require('fs');
                const errLogPath = profileDataPath('scratch', 'ipc_brain_error.log');
                fs_std.appendFileSync(errLogPath, `[${new Date().toISOString()}] Handler error: ${err.message}\nStack: ${err.stack}\n`, 'utf-8');
            } catch (e) {}
            console.error('[AMS IPC] shell:open-brain failed:', err);
        }
    });
    electron_1.ipcMain.handle('shell:get-sync-status', async (event) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const configDir = path.join(os.homedir(), '.gemini', 'config');
            const conflictFiles = [];

            const scanDirs = [
                configDir,
                path.join(configDir, 'scripts'),
                path.join(configDir, 'skills'),
                path.join(configDir, 'plugins', 'science', 'skills'),
                path.join(configDir, 'plugins', 'science', 'skills', 'science_skills_common')
            ];

            for (const dir of scanDirs) {
                if (fs_std.existsSync(dir)) {
                    const items = fs_std.readdirSync(dir);
                    for (const item of items) {
                        if (item.includes('.conflict')) {
                            conflictFiles.push(item);
                        }
                    }
                }
            }

            // Check MEMORY.md file content for conflicts as a fallback/additional check
            const memoryPath = path.join(configDir, 'MEMORY.md');
            if (fs_std.existsSync(memoryPath)) {
                try {
                    const memoryContent = fs_std.readFileSync(memoryPath, 'utf-8');
                    if (memoryContent.includes('[CONFLICT]')) {
                        const match = memoryContent.match(/- \[CONFLICT\][^\n]*/g);
                        if (match) {
                            for (const m of match) {
                                if (!conflictFiles.includes(m)) {
                                    conflictFiles.push(m);
                                }
                            }
                        }
                    }
                } catch (e) {}
            }

            return {
                status: conflictFiles.length > 0 ? 'conflict' : 'ok',
                conflictFiles: conflictFiles
            };
        } catch (err) {
            console.error('[AMS Sync Status IPC] shell:get-sync-status failed:', err);
            return { status: 'error', error: err.message, conflictFiles: [] };
        }
    });
    electron_1.ipcMain.handle('debug:write-dom', async (event, html) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const dumpPath = profileDataPath('scratch', 'dom_dump.html');

            const scratchDir = path.dirname(dumpPath);
            if (!fs_std.existsSync(scratchDir)) {
                fs_std.mkdirSync(scratchDir, { recursive: true });
            }

            fs_std.writeFileSync(dumpPath, html, 'utf-8');
        } catch (err) {
            console.error('[AMS Debug IPC] debug:write-dom failed:', err);
        }
    });
    // IDE installation check
    electron_1.ipcMain.handle('ide:is-installed', async () => {
        try {
            // Check standard installation path (works even if the app has never been launched).
            await fs.stat((0, constants_1.getIdeInstallPath)());
            return true;
        }
        catch {
            return false;
        }
    });
    // Git PRs listing
    electron_1.ipcMain.handle('git:get-prs', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            let repoPath = await resolveWorkspacePath(conversationId);

            let gitDir = path.join(repoPath, '.git');
            let hasGit = fs_std.existsSync(gitDir);
            let remotes = '';

            if (hasGit) {
                try {
                    const { stdout } = await execFilePromise('git', ['remote'], { cwd: repoPath });
                    remotes = stdout.trim();
                } catch (e) {}
            }

            // Fallback to ~/.gemini/config if workspace lacks git or remotes
            if (!hasGit || !remotes) {
                const configRepoPath = path.join(os.homedir(), '.gemini', 'config');
                const configGitDir = path.join(configRepoPath, '.git');
                if (fs_std.existsSync(configGitDir)) {
                    try {
                        const { stdout } = await execFilePromise('git', ['remote'], { cwd: configRepoPath });
                        if (stdout.trim()) {
                            repoPath = configRepoPath;
                            remotes = stdout.trim();
                            hasGit = true;
                        }
                    } catch (e) {}
                }
            }

            if (!hasGit) {
                return { status: 'no_git', repoPath };
            }
            if (!remotes) {
                return { status: 'no_remote', repoPath };
            }

            try {
                const { stdout } = await execFilePromise(
                    'gh',
                    ['pr', 'list', '--state', 'all', '--limit', '25', '--json', 'number,title,state,url,author,updatedAt,body'],
                    { cwd: repoPath },
                );
                const prs = JSON.parse(stdout);
                return { status: 'success', prs, repoPath };
            } catch (e) {
                return { status: 'gh_error', message: e.message, repoPath };
            }
        } catch (err) {
            console.error('[AMS IPC PRs] git:get-prs failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Git Issues listing
    electron_1.ipcMain.handle('git:get-issues', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            let repoPath = await resolveWorkspacePath(conversationId);

            let gitDir = path.join(repoPath, '.git');
            let hasGit = fs_std.existsSync(gitDir);
            let remotes = '';

            if (hasGit) {
                try {
                    const { stdout } = await execFilePromise('git', ['remote'], { cwd: repoPath });
                    remotes = stdout.trim();
                } catch (e) {}
            }

            // Fallback to ~/.gemini/config if workspace lacks git or remotes
            if (!hasGit || !remotes) {
                const configRepoPath = path.join(os.homedir(), '.gemini', 'config');
                const configGitDir = path.join(configRepoPath, '.git');
                if (fs_std.existsSync(configGitDir)) {
                    try {
                        const { stdout } = await execFilePromise('git', ['remote'], { cwd: configRepoPath });
                        if (stdout.trim()) {
                            repoPath = configRepoPath;
                            remotes = stdout.trim();
                            hasGit = true;
                        }
                    } catch (e) {}
                }
            }

            if (!hasGit) {
                return { status: 'no_git', repoPath };
            }
            if (!remotes) {
                return { status: 'no_remote', repoPath };
            }

            try {
                const { stdout } = await execFilePromise(
                    'gh',
                    ['issue', 'list', '--state', 'all', '--limit', '25', '--json', 'number,title,state,url,author,updatedAt,body'],
                    { cwd: repoPath },
                );
                const issues = JSON.parse(stdout);
                return { status: 'success', issues, repoPath };
            } catch (e) {
                return { status: 'gh_error', message: e.message, repoPath };
            }
        } catch (err) {
            console.error('[AMS IPC Issues] git:get-issues failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Git Commit and Push handler
    electron_1.ipcMain.handle('git:commit-and-push', async (event, commitMessage, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const normalizedCommitMessage = typeof commitMessage === 'string' ? commitMessage.trim() : '';
            if (normalizedCommitMessage.length > 2000) {
                throw new Error('Commit message is too long.');
            }
            const safeConversationId = normalizeConversationId(conversationId, true);

            const configRepoPath = path.join(os.homedir(), '.gemini', 'config');
            const syncScript = path.join(configRepoPath, 'scripts', 'sync_config.py');

            let details = '';

            // 1. Sync the config repository (which also compiles memory and pushes configs)
            if (fs_std.existsSync(syncScript)) {
                try {
                    const { stdout, stderr } = await execFilePromise(
                        getPythonPath(),
                        [syncScript, '--msg', normalizedCommitMessage],
                        { timeout: 30000, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
                    );
                    details += `Config Sync Output:\n${stdout}\n${stderr}\n`;
                } catch (e) {
                    details += `Config Sync Error: ${e.message}\n`;
                }
            } else {
                details += `Config sync script not found at ${syncScript}.\n`;
            }

            // 2. Identify workspace path
            let workspaceRepoPath = '';
            if (safeConversationId) {
                const dbPath = profileDataPath('conversations', safeConversationId + '.db');
                if (fs_std.existsSync(dbPath)) {
                    try {
                        const uri = await readWorkspaceUriFromDatabase(dbPath);
                        if (uri) {
                            const parsedPath = decodeURIComponent(uri.replace('file:///', ''));
                            if (fs_std.existsSync(parsedPath)) {
                                workspaceRepoPath = parsedPath;
                            }
                        }
                    } catch (e) {
                        console.error('[AMS IPC Commit] Error getting path via python:', e);
                    }
                }
            }

            // 3. Commit & push active workspace if different from config path and is git repo
            if (workspaceRepoPath && workspaceRepoPath !== configRepoPath) {
                const gitDir = path.join(workspaceRepoPath, '.git');
                if (fs_std.existsSync(gitDir)) {
                    try {
                        const statusCheck = await execFilePromise('git', ['status', '--porcelain'], { cwd: workspaceRepoPath });
                        if (statusCheck.stdout.trim()) {
                            details += `Workspace (${workspaceRepoPath}): Committing changes...\n`;
                            await execFilePromise('git', ['add', '.'], { cwd: workspaceRepoPath });
                            const msg = normalizedCommitMessage || 'Auto-commit: ' + new Date().toISOString();
                            await execFilePromise('git', ['commit', '-m', msg], { cwd: workspaceRepoPath });

                            const remoteCheck = await execFilePromise('git', ['remote'], { cwd: workspaceRepoPath });
                            if (remoteCheck.stdout.trim()) {
                                details += `Workspace (${workspaceRepoPath}): Pushing changes...\n`;
                                const branchCheck = await execFilePromise('git', ['branch', '--show-current'], { cwd: workspaceRepoPath });
                                const branch = branchCheck.stdout.trim() || 'main';
                                if (!/^[A-Za-z0-9._/-]{1,240}$/.test(branch)) {
                                    throw new Error('Git returned an invalid branch name.');
                                }
                                await execFilePromise('git', ['push', 'origin', branch], { cwd: workspaceRepoPath });
                                details += `Workspace (${workspaceRepoPath}): Successfully pushed to origin.\n`;
                            } else {
                                details += `Workspace (${workspaceRepoPath}): No remote configured.\n`;
                            }
                        } else {
                            details += `Workspace (${workspaceRepoPath}): No changes to commit.\n`;
                        }
                    } catch (e) {
                        details += `Workspace Commit Error: ${e.message}\n`;
                    }
                }
            }

            return { status: 'success', details };
        } catch (err) {
            console.error('[AMS IPC Commit] git:commit-and-push failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    const parseLastJsonLine = (outputText) => {
        const lines = String(outputText || '').trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
        for (let i = lines.length - 1; i >= 0; i--) {
            if (lines[i].startsWith('{') && lines[i].endsWith('}')) {
                try {
                    return JSON.parse(lines[i]);
                } catch (_) {}
            }
        }
        return JSON.parse(String(outputText || '{}'));
    };

    // Config Cloud-Sync Info & Usage Stats (~/.gemini/config)
    electron_1.ipcMain.handle('git:get-config-sync-info', async (event) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const syncScript = path.join(os.homedir(), '.gemini', 'config', 'scripts', 'sync_config.py');
            if (!fs_std.existsSync(syncScript)) {
                return { status: 'error', message: `sync_config.py nicht gefunden unter ${syncScript}` };
            }
            const { stdout } = await execFilePromise(
                getPythonPath(),
                [syncScript, '--status-json'],
                { timeout: 25000, windowsHide: true, maxBuffer: 5 * 1024 * 1024 },
            );
            return parseLastJsonLine(stdout);
        } catch (err) {
            console.error('[AMS IPC] git:get-config-sync-info failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Setup or 1-click create private GitHub repo for ~/.gemini/config
    electron_1.ipcMain.handle('git:setup-config-remote', async (event, target, createPrivate) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const syncScript = path.join(os.homedir(), '.gemini', 'config', 'scripts', 'sync_config.py');
            if (!fs_std.existsSync(syncScript)) {
                return { status: 'error', message: `sync_config.py nicht gefunden unter ${syncScript}` };
            }
            const cleanTarget = typeof target === 'string' && target.trim() ? target.trim().slice(0, 300) : 'antigravity-config';
            const args = [syncScript, '--setup-remote', cleanTarget];
            if (createPrivate) args.push('--create-private');
            const { stdout } = await execFilePromise(
                getPythonPath(),
                args,
                { timeout: 60000, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
            );
            return parseLastJsonLine(stdout);
        } catch (err) {
            console.error('[AMS IPC] git:setup-config-remote failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Import existing ~/.gemini/config remote onto a 2nd PC / laptop
    electron_1.ipcMain.handle('git:import-config-remote', async (event, target) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const syncScript = path.join(os.homedir(), '.gemini', 'config', 'scripts', 'sync_config.py');
            if (!fs_std.existsSync(syncScript)) {
                return { status: 'error', message: `sync_config.py nicht gefunden unter ${syncScript}` };
            }
            const cleanTarget = typeof target === 'string' ? target.trim().slice(0, 300) : '';
            const args = cleanTarget ? [syncScript, '--import-remote', cleanTarget] : [syncScript, '--import-remote'];
            const { stdout } = await execFilePromise(
                getPythonPath(),
                args,
                { timeout: 60000, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
            );
            return parseLastJsonLine(stdout);
        } catch (err) {
            console.error('[AMS IPC] git:import-config-remote failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Toggle background auto-sync interval for ~/.gemini/config
    electron_1.ipcMain.handle('git:set-config-auto-sync', async (event, minutes) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const syncScript = path.join(os.homedir(), '.gemini', 'config', 'scripts', 'sync_config.py');
            if (!fs_std.existsSync(syncScript)) {
                return { status: 'error', message: `sync_config.py nicht gefunden unter ${syncScript}` };
            }
            const safeMinutes = Math.max(0, Math.min(1440, parseInt(minutes, 10) || 0));
            const { stdout } = await execFilePromise(
                getPythonPath(),
                [syncScript, '--set-auto-sync', String(safeMinutes)],
                { timeout: 15000, windowsHide: true },
            );
            return parseLastJsonLine(stdout);
        } catch (err) {
            console.error('[AMS IPC] git:set-config-auto-sync failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Background sync of ~/.gemini/config only (does not touch active coding workspace)
    electron_1.ipcMain.handle('git:sync-config-only', async (event, message) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const syncScript = path.join(os.homedir(), '.gemini', 'config', 'scripts', 'sync_config.py');
            if (!fs_std.existsSync(syncScript)) {
                return { status: 'error', message: `sync_config.py nicht gefunden` };
            }
            const safeMsg = typeof message === 'string' && message.trim()
                ? message.trim().slice(0, 300)
                : 'chore(config): background auto-sync';
            const { stdout, stderr } = await execFilePromise(
                getPythonPath(),
                [syncScript, '--msg', safeMsg],
                { timeout: 45000, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
            );
            return { status: 'success', details: `${stdout}\n${stderr}`.trim() };
        } catch (err) {
            console.error('[AMS IPC] git:sync-config-only failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Launch interactive GitHub CLI web login
    electron_1.ipcMain.handle('git:gh-auth-login', async (event) => {
        try {
            validateOrigin(event);
            const { spawn } = require('child_process');
            if (process.platform === 'win32') {
                const child = spawn(
                    'cmd.exe',
                    ['/c', 'start', '""', 'powershell', '-NoExit', '-Command', 'Write-Host "=== Antigravity GitHub Cloud-Sync Login ===" -ForegroundColor Cyan; gh auth login --web -p https'],
                    { detached: true, stdio: 'ignore', windowsHide: false },
                );
                child.unref();
            } else {
                const child = spawn('gh', ['auth', 'login', '--web', '-p', 'https'], {
                    detached: true,
                    stdio: 'ignore',
                });
                child.unref();
            }
            return { status: 'launched' };
        } catch (err) {
            console.error('[AMS IPC] git:gh-auth-login failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get Task Plan from active brain/task.md
    electron_1.ipcMain.handle('task:get-plan', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const safeConversationId = normalizeConversationId(conversationId, true);
            if (safeConversationId) {
                const brainDir = profileDataPath('brain', safeConversationId);
                const taskPath = path.join(brainDir, 'task.md');
                if (fs_std.existsSync(taskPath)) {
                    const content = fs_std.readFileSync(taskPath, 'utf-8');
                    return { status: 'success', plan: content };
                }
            }
            return { status: 'fallback' };
        } catch (err) {
            console.error('[AMS IPC Task] task:get-plan failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Set Task Plan to active brain/task.md
    electron_1.ipcMain.handle('task:set-plan', async (event, text, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            if (typeof text !== 'string' || Buffer.byteLength(text, 'utf8') > 2 * 1024 * 1024) {
                throw new Error('Invalid task plan.');
            }
            const safeConversationId = normalizeConversationId(conversationId, true);
            if (safeConversationId) {
                const brainDir = profileDataPath('brain', safeConversationId);
                if (fs_std.existsSync(brainDir)) {
                    const taskPath = path.join(brainDir, 'task.md');
                    fs_std.writeFileSync(taskPath, text, 'utf-8');
                    return { status: 'success', path: taskPath };
                }
            }
            return { status: 'no_brain_dir' };
        } catch (err) {
            console.error('[AMS IPC Task] task:set-plan failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get compaction count for the conversation from parent_references table in sqlite db
    electron_1.ipcMain.handle('trajectory:get-compaction-count', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const safeConversationId = normalizeConversationId(conversationId, true);
            if (!safeConversationId) {
                return { status: 'success', count: 0 };
            }

            const dbPath = profileDataPath('conversations', safeConversationId + '.db');
            if (!fs_std.existsSync(dbPath)) {
                return { status: 'success', count: 0 };
            }

            const countScript = [
                'import sqlite3, sys',
                'db_uri = sys.argv[1].replace(chr(92), "/")',
                'conn = sqlite3.connect("file:" + db_uri + "?mode=ro", uri=True, timeout=1.0)',
                'table = conn.execute("SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'parent_references\'").fetchone()',
                'print(conn.execute("SELECT count(*) FROM parent_references").fetchone()[0] if table else 0)',
            ].join('\n');
            const { stdout } = await execFilePromise(
                getPythonPath(),
                ['-c', countScript, dbPath],
                { timeout: 5000, windowsHide: true },
            );
            const count = parseInt(stdout.trim(), 10) || 0;
            return { status: 'success', count };
        } catch (err) {
            console.error('[AMS IPC] trajectory:get-compaction-count failed:', err);
            return { status: 'error', message: err.message, count: 0 };
        }
    });

    // Get token stats for the conversation
    electron_1.ipcMain.handle('trajectory:get-token-stats', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const safeConversationId = normalizeConversationId(conversationId, true);
            if (!safeConversationId) {
                return { status: 'success', totalInput: 0, totalOutput: 0, cacheRatio: 0 };
            }

            const dbPath = profileDataPath('conversations', safeConversationId + '.db');
            if (!fs_std.existsSync(dbPath)) {
                return { status: 'success', totalInput: 0, totalOutput: 0, cacheRatio: 0 };
            }

            const candidateScriptPaths = [
                'Y:\\Projects\\antigravity-unleashed\\packages\\desktop-ui-modifier\\scripts\\get_token_stats.py',
                'Y:\\Vault\\90_KI\\Skills\\antigravity_desktop_ui_modifier\\scripts\\get_token_stats.py',
                path.join(os.homedir(), '.gemini', 'config', 'skills', 'antigravity_desktop_ui_modifier', 'scripts', 'get_token_stats.py'),
            ];
            const scriptPath = candidateScriptPaths.find((p) => fs_std.existsSync(p));
            if (!scriptPath) {
                console.error('[AMS IPC] get_token_stats.py script not found in candidates:', candidateScriptPaths);
                return { status: 'error', message: 'Script not found' };
            }

            const { stdout } = await execFilePromise(
                getPythonPath(),
                [scriptPath, dbPath],
                { timeout: 15000, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
            );
            const data = JSON.parse(stdout.trim());

            if (data.error) {
                return { status: 'error', message: data.error };
            }

            return { status: 'success', ...data };
        } catch (err) {
            console.error('[AMS IPC] trajectory:get-token-stats failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get Notes from active brain/notes.txt
    electron_1.ipcMain.handle('notes:get-notes', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const safeConversationId = normalizeConversationId(conversationId, true);
            if (safeConversationId) {
                const brainDir = profileDataPath('brain', safeConversationId);
                const notesPath = path.join(brainDir, 'notes.txt');
                if (fs_std.existsSync(notesPath)) {
                    const content = fs_std.readFileSync(notesPath, 'utf-8');
                    return { status: 'success', notes: content, syncAI: true };
                }
            }
            return { status: 'fallback', syncAI: false };
        } catch (err) {
            console.error('[AMS IPC Notes] notes:get-notes failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Set Notes to active brain/notes.txt
    electron_1.ipcMain.handle('notes:set-notes', async (event, text, syncAI, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            if (typeof text !== 'string' || Buffer.byteLength(text, 'utf8') > 2 * 1024 * 1024) {
                throw new Error('Invalid notes payload.');
            }
            const safeConversationId = normalizeConversationId(conversationId, true);
            if (safeConversationId) {
                const brainDir = profileDataPath('brain', safeConversationId);
                if (fs_std.existsSync(brainDir)) {
                    const notesPath = path.join(brainDir, 'notes.txt');
                    if (syncAI) {
                        fs_std.writeFileSync(notesPath, text, 'utf-8');
                        return { status: 'success', path: notesPath, action: 'written' };
                    } else {
                        if (fs_std.existsSync(notesPath)) {
                            fs_std.unlinkSync(notesPath);
                        }
                        return { status: 'success', action: 'deleted' };
                    }
                }
            }
            return { status: 'no_brain_dir' };
        } catch (err) {
            console.error('[AMS IPC Notes] notes:set-notes failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Write text to system clipboard
    electron_1.ipcMain.handle('clipboard:write-text', async (event, text) => {
        try {
            validateOrigin(event);
            const { clipboard } = require('electron');
            if (text && text.trim()) {
                clipboard.writeText(text);
                return { status: 'success' };
            }
            return { status: 'empty' };
        } catch (err) {
            console.error('[AMS IPC Clipboard] clipboard:write-text failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Write a single log entry to the JSONL log file
    electron_1.ipcMain.handle('logs:write-entry', async (event, entry) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const logDir = path.join(os.homedir(), '.gemini', 'config', 'logs');
            if (!fs_std.existsSync(logDir)) {
                fs_std.mkdirSync(logDir, { recursive: true });
            }

            const hostname = os.hostname().toLowerCase().replace(/ /g, '_');
            const logPath = path.join(logDir, `global_ai_history_${hostname}.jsonl`);

            // Format log entry as a single line JSON and append newline
            const logLine = JSON.stringify(entry) + '\n';
            fs_std.appendFileSync(logPath, logLine, 'utf-8');

            return { status: 'success' };
        } catch (err) {
            console.error('[AMS IPC Logs] logs:write-entry failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Read upgrade history from disk and return to renderer
    electron_1.ipcMain.handle('updater:get-upgrade-history', async (event) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const historyPath = path.join(os.homedir(), '.gemini', 'config', 'skills', 'antigravity_desktop_ui_modifier', 'UPGRADE_HISTORY.json');
            if (fs_std.existsSync(historyPath)) {
                const data = JSON.parse(fs_std.readFileSync(historyPath, 'utf8'));
                return { status: 'success', history: data };
            }
            return { status: 'success', history: [] };
        } catch (err) {
            console.error('[AMS IPC Updater] updater:get-upgrade-history failed:', err);
            return { status: 'error', message: err.message, history: [] };
        }
    });

    // API window visibility preference (applied by the Hub's window enforcer).
    const apiWindowStatePath = () => {
        const os = require('os');
        const path = require('path');
        return path.join(os.homedir(), '.gemini', 'antigravity', 'scratch', 'api_window_visibility.json');
    };
    electron_1.ipcMain.handle('api-window:get-visible', async (event) => {
        try {
            validateOrigin(event);
            const fs_std = require('fs');
            const data = JSON.parse(fs_std.readFileSync(apiWindowStatePath(), 'utf8'));
            return { status: 'success', visible: data.visible === true };
        } catch (err) {
            // Missing file means the default: hidden.
            return { status: 'success', visible: false };
        }
    });
    electron_1.ipcMain.handle('api-window:set-visible', async (event, visible) => {
        try {
            validateOrigin(event);
            const fs_std = require('fs');
            const path = require('path');
            const target = apiWindowStatePath();
            fs_std.mkdirSync(path.dirname(target), { recursive: true });
            const temporary = target + '.tmp';
            fs_std.writeFileSync(temporary, JSON.stringify({ visible: visible === true, updated_at: Date.now() / 1000 }), 'utf8');
            fs_std.renameSync(temporary, target);
            return { status: 'success', visible: visible === true };
        } catch (err) {
            console.error('[AMS IPC] api-window:set-visible failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Read log history from disk and return to renderer
    electron_1.ipcMain.handle('logs:get-history', async (event) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const logDir = path.join(os.homedir(), '.gemini', 'config', 'logs');
            if (!fs_std.existsSync(logDir)) {
                fs_std.mkdirSync(logDir, { recursive: true });
            }
            const hostname = os.hostname().toLowerCase().replace(/ /g, '_');
            const logPath = path.join(logDir, `global_ai_history_${hostname}.jsonl`);

            // 1. Read existing JSONL logs
            const logs = [];
            const existingKeys = new Set();
            if (fs_std.existsSync(logPath)) {
                const content = fs_std.readFileSync(logPath, 'utf-8');
                const lines = content.split('\n');
                for (const line of lines) {
                    if (line.trim()) {
                        try {
                            const entry = JSON.parse(line);
                            logs.push(entry);
                            // Generate unique key to avoid duplicates
                            const key = entry.session_id + '_' + entry.source + '_' + (entry.content || '').trim().substring(0, 100);
                            existingKeys.add(key);
                        } catch (e) {
                            // ignore corrupt lines
                        }
                    }
                }
            }

            // 2. Scan SQLite databases for offline/older chats
            const tempScriptPath = path.join(os.tmpdir(), `sync_logs_${Date.now()}.py`);
            const logPathForPython = logPath.replace(/\\/g, '/');
            const pythonCode =
                "import subprocess\n" +
                "import json\n" +
                "import time\n" +
                "import os\n" +
                "import sqlite3\n" +
                "import sys\n" +
                "import re\n\n" +
                "sys.stdout.reconfigure(encoding='utf-8')\n" +
                "existing_keys = set()\n" +
                "if len(sys.argv) > 1:\n" +
                "    log_path = sys.argv[1]\n" +
                "    if os.path.exists(log_path):\n" +
                "        try:\n" +
                "            with open(log_path, 'r', encoding='utf-8') as f:\n" +
                "                for line in f:\n" +
                "                    if line.strip():\n" +
                "                        try:\n" +
                "                            entry = json.loads(line)\n" +
                "                            key = entry.get('session_id', '') + '_' + entry.get('source', '') + '_' + (entry.get('content', '') or '').strip()[:100]\n" +
                "                            existing_keys.add(key)\n" +
                "                        except: pass\n" +
                "        except: pass\n\n" +
                "def decode_varint(data, pos):\n" +
                "    res = 0\n" +
                "    shift = 0\n" +
                "    while True:\n" +
                "        if pos >= len(data): return None, pos\n" +
                "        b = data[pos]\n" +
                "        res |= (b & 0x7f) << shift\n" +
                "        pos += 1\n" +
                "        if not (b & 0x80): break\n" +
                "        shift += 7\n" +
                "    return res, pos\n\n" +
                "def parse_protobuf(data):\n" +
                "    pos = 0\n" +
                "    fields = []\n" +
                "    while pos < len(data):\n" +
                "        key, pos = decode_varint(data, pos)\n" +
                "        if key is None: break\n" +
                "        wire_type = key & 0x07\n" +
                "        field_number = key >> 3\n" +
                "        if wire_type == 0:\n" +
                "            val, pos = decode_varint(data, pos)\n" +
                "            if val is None: break\n" +
                "            fields.append((field_number, wire_type, val))\n" +
                "        elif wire_type == 1:\n" +
                "            if pos + 8 > len(data): break\n" +
                "            val = data[pos:pos+8]\n" +
                "            pos += 8\n" +
                "            fields.append((field_number, wire_type, val))\n" +
                "        elif wire_type == 2:\n" +
                "            length, pos = decode_varint(data, pos)\n" +
                "            if length is None or pos + length > len(data): break\n" +
                "            val = data[pos:pos+length]\n" +
                "            pos += length\n" +
                "            fields.append((field_number, wire_type, val))\n" +
                "        elif wire_type == 5:\n" +
                "            if pos + 4 > len(data): break\n" +
                "            val = data[pos:pos+4]\n" +
                "            pos += 4\n" +
                "            fields.append((field_number, wire_type, val))\n" +
                "        else: break\n" +
                "    return fields\n\n" +
                "def get_text_from_payload(payload, step_type):\n" +
                "    outer_fields = parse_protobuf(payload)\n" +
                "    if not outer_fields: return None\n" +
                "    if step_type == 15:\n" +
                "        for fn, wt, val in outer_fields:\n" +
                "            if fn == 20 and wt == 2:\n" +
                "                inner_fields = parse_protobuf(val)\n" +
                "                if inner_fields:\n" +
                "                    for inner_fn, inner_wt, inner_val in inner_fields:\n" +
                "                        if inner_fn == 1 and inner_wt == 2:\n" +
                "                            try: return inner_val.decode('utf-8')\n" +
                "                            except: pass\n" +
                "    elif step_type == 14:\n" +
                "        for fn, wt, val in outer_fields:\n" +
                "            if fn == 19 and wt == 2:\n" +
                "                inner_fields = parse_protobuf(val)\n" +
                "                if inner_fields:\n" +
                "                    for inner_fn, inner_wt, inner_val in inner_fields:\n" +
                "                        if inner_fn == 2 and inner_wt == 2:\n" +
                "                            try: return inner_val.decode('utf-8')\n" +
                "                            except: pass\n" +
                "    for fn, wt, val in outer_fields:\n" +
                "        if wt == 2 and len(val) > 2:\n" +
                "            try:\n" +
                "                decoded = val.decode('utf-8')\n" +
                "                if any(c.isalnum() for c in decoded) and len(decoded) < 5000:\n" +
                "                    if not decoded.startswith('file://') and not re.match(r'^[a-f0-9-]{36}$', decoded):\n" +
                "                        return decoded\n" +
                "            except: pass\n" +
                "    return None\n\n" +
                "convo_dir = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations')\n" +
                "if not os.path.exists(convo_dir):\n" +
                "    convo_dir = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations')\n\n" +
                "logs = []\n" +
                "if os.path.exists(convo_dir):\n" +
                "    for fname in os.listdir(convo_dir):\n" +
                "        if fname.endswith('.db') and not fname.endswith('-shm') and not fname.endswith('-wal'):\n" +
                "            convo_id = fname[:-3]\n" +
                "            db_path = os.path.join(convo_dir, fname)\n" +
                "            try:\n" +
                "                mtime = os.path.getmtime(db_path)\n" +
                "                import datetime\n" +
                "                dt = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)\n" +
                "                file_iso = dt.isoformat()\n" +
                "                conn = sqlite3.connect(db_path)\n" +
                "                rows = conn.execute(\"SELECT idx, step_type, step_payload FROM steps WHERE step_type IN (14, 15) AND status = 3 ORDER BY idx ASC\").fetchall()\n" +
                "                for idx, step_type, payload in rows:\n" +
                "                    txt = get_text_from_payload(payload, step_type)\n" +
                "                    if txt:\n" +
                "                        role = 'USER' if step_type == 14 else 'AGENT'\n" +
                "                        key = convo_id + '_' + role + '_' + txt.strip()[:100]\n" +
                "                        if key not in existing_keys:\n" +
                "                            logs.append({\n" +
                "                                'session_id': convo_id,\n" +
                "                                'event': 'message',\n" +
                "                                'source': role,\n" +
                "                                'content': txt,\n" +
                "                                'timestamp': file_iso,\n" +
                "                                'model': 'Gemini 3.5 Flash (High)' if role == 'USER' else 'Detected from SQLite',\n" +
                "                                'tokens': len(txt) // 4 + 1\n" +
                "                            })\n" +
                "                conn.close()\n" +
                "            except Exception as e: pass\n\n" +
                "print(json.dumps(logs))\n" +
                "sys.exit(0)\n";

            fs_std.writeFileSync(tempScriptPath, pythonCode, 'utf-8');

            let sqliteLogs = [];
            try {
                const { stdout } = await execFilePromise(
                    getPythonPath(),
                    [tempScriptPath, logPathForPython],
                    { maxBuffer: 100 * 1024 * 1024, windowsHide: true, timeout: 30000 },
                );
                sqliteLogs = JSON.parse(stdout.trim());
            } catch (err) {
                console.error('[AMS IPC Logs] SQLite logs sync failed:', err);
            } finally {
                try {
                    fs_std.unlinkSync(tempScriptPath);
                } catch (e) {}
            }

            // 3. Merge new entries and append to JSONL
            const newEntries = sqliteLogs.filter(entry => {
                const key = entry.session_id + '_' + entry.source + '_' + (entry.content || '').trim().substring(0, 100);
                if (!existingKeys.has(key)) {
                    existingKeys.add(key);
                    return true;
                }
                return false;
            });

            if (newEntries.length > 0) {
                let appendContent = '';
                for (const entry of newEntries) {
                    appendContent += JSON.stringify(entry) + '\n';
                    logs.push(entry);
                }
                fs_std.appendFileSync(logPath, appendContent, 'utf-8');
                console.log(`[AMS IPC Logs] Synced ${newEntries.length} new entries from SQLite to JSONL.`);
            }

            return { status: 'success', logs, logDir };
        } catch (err) {
            console.error('[AMS IPC Logs] logs:get-history failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get current Git Status for Workspace and Config Repo
    electron_1.ipcMain.handle('git:get-status', async (event, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const configRepoPath = path.join(os.homedir(), '.gemini', 'config');
            const workspaceRepoPath = await resolveWorkspacePath(conversationId);

            let workspaceChanges = [];
            let configChanges = [];

            // Check workspace
            if (workspaceRepoPath && fs_std.existsSync(path.join(workspaceRepoPath, '.git'))) {
                try {
                    const { stdout } = await execFilePromise('git', ['status', '--porcelain'], { cwd: workspaceRepoPath });
                    workspaceChanges = stdout.split('\n')
                        .map(line => line.trim())
                        .filter(line => line.length > 0)
                        .map(line => {
                            const status = line.substring(0, 2).trim();
                            const file = line.substring(2).trim();
                            return { file, status, repo: 'workspace' };
                        });
                } catch (e) {}
            }

            // Check config repo
            if (configRepoPath && fs_std.existsSync(path.join(configRepoPath, '.git'))) {
                try {
                    const { stdout } = await execFilePromise('git', ['status', '--porcelain'], { cwd: configRepoPath });
                    configChanges = stdout.split('\n')
                        .map(line => line.trim())
                        .filter(line => line.length > 0)
                        .map(line => {
                            const status = line.substring(0, 2).trim();
                            const file = line.substring(2).trim();
                            return { file, status, repo: 'config' };
                        });
                } catch (e) {}
            }

            return {
                status: 'success',
                workspacePath: workspaceRepoPath,
                configPath: configRepoPath,
                workspaceChanges,
                configChanges,
                totalChanges: workspaceChanges.length + configChanges.length
            };
        } catch (err) {
            console.error('[AMS IPC Git] git:get-status failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get Git Diff for a specific file in Workspace or Config Repo
    electron_1.ipcMain.handle('git:get-diff', async (event, filePath, repoType, conversationId) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');

            let repoPath = path.join(os.homedir(), '.gemini', 'config');
            if (repoType === 'workspace') {
                repoPath = await resolveWorkspacePath(conversationId);
            } else if (repoType !== 'config') {
                throw new Error('Invalid repository type.');
            }
            if (typeof filePath !== 'string' || filePath.length === 0 || filePath.length > 4096 || filePath.includes('\0')) {
                throw new Error('Invalid repository file path.');
            }
            const fullFilePath = path.resolve(repoPath, filePath);
            if (!isPathInside(repoPath, fullFilePath) || fullFilePath === path.resolve(repoPath)) {
                throw new Error('Repository file path escapes the selected repository.');
            }
            const relativeFilePath = path.relative(repoPath, fullFilePath);

            let diffOutput = '';
            try {
                const statusCheck = await execFilePromise('git', ['status', '--porcelain', '--', relativeFilePath], { cwd: repoPath });
                const status = statusCheck.stdout.trim();

                if (status.startsWith('??')) {
                    const fs_std = require('fs');
                    if (fs_std.existsSync(fullFilePath)) {
                        if (fs_std.statSync(fullFilePath).size > 5 * 1024 * 1024) {
                            throw new Error('File is too large to display.');
                        }
                        const content = fs_std.readFileSync(fullFilePath, 'utf-8');
                        diffOutput = content.split('\n').map(line => '+' + line).join('\n');
                    } else {
                        diffOutput = 'File not found.';
                    }
                } else {
                    const { stdout } = await execFilePromise('git', ['diff', 'HEAD', '--', relativeFilePath], { cwd: repoPath });
                    diffOutput = stdout;
                    if (!diffOutput.trim()) {
                        const unstaged = await execFilePromise('git', ['diff', '--', relativeFilePath], { cwd: repoPath });
                        diffOutput = unstaged.stdout;
                    }
                }
            } catch (e) {
                diffOutput = `Error getting diff: ${e.message}`;
            }

            return { status: 'success', diff: diffOutput };
        } catch (err) {
            console.error('[AMS IPC Git] git:get-diff failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    // =========================================================================
    // Unleashed AI Engine & Configuration (Server API + Local UI + Rule-based)
    // =========================================================================
    const UNLEASHED_AI_MODES = new Set(['auto', 'unleashed_api', 'local_ui', 'off']);
    const UNLEASHED_COMMIT_STYLES = new Set(['concise', 'detailed']);

    function getUnleashedAiConfigPath() {
        const os = require('os');
        const path = require('path');
        return path.join(os.homedir(), '.gemini', 'config', 'unleashed_ai_config.json');
    }

    function normalizeUnleashedBaseUrl(rawUrl) {
        let url = String(rawUrl || '').trim().replace(/\/+$/, '');
        if (!url) return process.env.UNLEASHED_API_URL || 'http://127.0.0.1:8001/v1';
        if (url.endsWith('/chat/completions')) {
            url = url.slice(0, -'/chat/completions'.length).replace(/\/+$/, '');
        }
        if (!url.endsWith('/v1') && !url.includes('/v1/')) {
            url += '/v1';
        }
        return url;
    }

    function readDefaultHubToken() {
        try {
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const hubCfgPath = path.join(os.homedir(), '.gemini', 'config', 'antigravity-hub', 'config.json');
            if (fs_std.existsSync(hubCfgPath)) {
                const parsed = JSON.parse(fs_std.readFileSync(hubCfgPath, 'utf-8'));
                if (parsed && typeof parsed.auth_token === 'string' && parsed.auth_token.trim()) {
                    return parsed.auth_token.trim();
                }
            }
        } catch (_e) {}
        return 'ag-local-token';
    }

    function loadUnleashedAiConfig() {
        const fs_std = require('fs');
        const defaults = {
            mode: 'auto',
            apiUrl: process.env.UNLEASHED_API_URL || 'http://127.0.0.1:8001/v1',
            apiKey: readDefaultHubToken(),
            model: 'gemini-3.8-flash-medium',
            commitStyle: 'concise',
            revertEphemeral: true,
        };
        try {
            const cfgPath = getUnleashedAiConfigPath();
            if (!fs_std.existsSync(cfgPath)) {
                return defaults;
            }
            const parsed = JSON.parse(fs_std.readFileSync(cfgPath, 'utf-8'));
            if (!parsed || typeof parsed !== 'object') return defaults;
            const mode = UNLEASHED_AI_MODES.has(parsed.mode) ? parsed.mode : defaults.mode;
            const apiUrl = normalizeUnleashedBaseUrl(parsed.apiUrl || defaults.apiUrl);
            const apiKey = typeof parsed.apiKey === 'string' ? parsed.apiKey.trim() : defaults.apiKey;
            const model = (typeof parsed.model === 'string' && parsed.model.trim()) ? parsed.model.trim() : defaults.model;
            const commitStyle = UNLEASHED_COMMIT_STYLES.has(parsed.commitStyle) ? parsed.commitStyle : defaults.commitStyle;
            const revertEphemeral = parsed.revertEphemeral !== false;
            return { mode, apiUrl, apiKey, model, commitStyle, revertEphemeral };
        } catch (_e) {
            return defaults;
        }
    }

    function saveUnleashedAiConfig(patch) {
        const fs_std = require('fs');
        const path = require('path');
        const current = loadUnleashedAiConfig();
        const incoming = (patch && typeof patch === 'object') ? patch : {};
        const updated = {
            mode: UNLEASHED_AI_MODES.has(incoming.mode) ? incoming.mode : current.mode,
            apiUrl: incoming.apiUrl !== undefined ? normalizeUnleashedBaseUrl(incoming.apiUrl) : current.apiUrl,
            apiKey: typeof incoming.apiKey === 'string' ? incoming.apiKey.trim() : current.apiKey,
            model: (typeof incoming.model === 'string' && incoming.model.trim()) ? incoming.model.trim() : current.model,
            commitStyle: UNLEASHED_COMMIT_STYLES.has(incoming.commitStyle) ? incoming.commitStyle : current.commitStyle,
            revertEphemeral: incoming.revertEphemeral !== undefined ? Boolean(incoming.revertEphemeral) : current.revertEphemeral,
            updatedAt: new Date().toISOString(),
        };
        const cfgPath = getUnleashedAiConfigPath();
        fs_std.mkdirSync(path.dirname(cfgPath), { recursive: true });
        fs_std.writeFileSync(cfgPath, JSON.stringify(updated, null, 2), 'utf-8');
        return updated;
    }

    function httpJsonRequest(urlString, options = {}) {
        return new Promise((resolve, reject) => {
            let parsedUrl;
            try {
                parsedUrl = new URL(urlString);
            } catch (err) {
                reject(new Error('Ungültige URL: ' + String(urlString)));
                return;
            }
            const isHttps = parsedUrl.protocol === 'https:';
            const client = isHttps ? require('https') : require('http');
            const method = options.method || (options.body !== undefined ? 'POST' : 'GET');
            const bodyString = options.body !== undefined
                ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body))
                : null;
            const headers = Object.assign({
                'Accept': 'application/json',
            }, options.headers || {});
            if (bodyString !== null) {
                if (!headers['Content-Type'] && !headers['content-type']) {
                    headers['Content-Type'] = 'application/json';
                }
                headers['Content-Length'] = String(Buffer.byteLength(bodyString, 'utf-8'));
            }

            const req = client.request({
                protocol: parsedUrl.protocol,
                hostname: parsedUrl.hostname,
                port: parsedUrl.port || (isHttps ? 443 : 80),
                path: parsedUrl.pathname + (parsedUrl.search || ''),
                method,
                headers,
                rejectUnauthorized: options.rejectUnauthorized !== undefined ? options.rejectUnauthorized : !isHttps,
            }, (res) => {
                const chunks = [];
                res.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
                res.on('error', reject);
                res.on('end', () => {
                    const statusCode = Number(res.statusCode || 0);
                    const rawText = Buffer.concat(chunks).toString('utf-8');
                    let data = null;
                    try {
                        data = rawText ? JSON.parse(rawText) : {};
                    } catch (_e) {
                        data = { rawText };
                    }
                    if (statusCode < 200 || statusCode >= 300) {
                        const detail = (data && (data.detail || (data.error && (data.error.message || data.error)))) || rawText.slice(0, 300) || `HTTP ${statusCode}`;
                        const err = new Error(`HTTP ${statusCode}: ${detail}`);
                        err.statusCode = statusCode;
                        err.responseData = data;
                        reject(err);
                        return;
                    }
                    resolve({ statusCode, data, rawText, headers: res.headers });
                });
            });

            const timeoutMs = Number(options.timeoutMs || 45000);
            req.setTimeout(timeoutMs, () => {
                req.destroy(new Error(`Zeitüberschreitung nach ${Math.round(timeoutMs / 1000)}s (${parsedUrl.host})`));
            });
            req.on('error', reject);
            if (bodyString !== null) {
                req.write(bodyString);
            }
            req.end();
        });
    }

    async function deleteLocalCascadeTrajectory(cascadeId, csrfToken) {
        const os = require('os');
        const path = require('path');
        const fs_std = require('fs');
        if (!cascadeId) return { status: 'skipped' };

        let lsPort = 0;
        try {
            const languageServer = require('./languageServer');
            lsPort = Number(languageServer.getLsPort() || 0);
        } catch (_e) {}

        const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN || '';
        let rpcDeleted = false;
        let grpcStatus = 0;

        if (lsPort && finalCsrf) {
            // Try Connect JSON over HTTPS on lsPort first (Antigravity v2.24+)
            try {
                await httpJsonRequest(`https://127.0.0.1:${lsPort}/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Connect-Protocol-Version': '1',
                        'x-codeium-csrf-token': finalCsrf,
                    },
                    body: { cascadeId },
                    rejectUnauthorized: false,
                    timeoutMs: 6000,
                });
                rpcDeleted = true;
            } catch (_httpsErr) {
                // Fallback to gRPC-Web binary frame on HTTPS lsPort or HTTP lsPort+1
                const uuidBytes = Buffer.from(cascadeId, 'utf-8');
                const body = Buffer.alloc(5 + 2 + uuidBytes.length);
                body[0] = 0;
                const length = 2 + uuidBytes.length;
                body[1] = (length >> 24) & 0xff;
                body[2] = (length >> 16) & 0xff;
                body[3] = (length >> 8) & 0xff;
                body[4] = length & 0xff;
                body[5] = 0x0a;
                body[6] = uuidBytes.length;
                uuidBytes.copy(body, 7);

                for (const candidate of [
                    { proto: 'https', port: lsPort },
                    { proto: 'http', port: lsPort + 1 },
                ]) {
                    try {
                        const mod = candidate.proto === 'https' ? require('https') : require('http');
                        await new Promise((resolve, reject) => {
                            const req = mod.request({
                                hostname: '127.0.0.1',
                                port: candidate.port,
                                path: '/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory',
                                method: 'POST',
                                rejectUnauthorized: false,
                                headers: {
                                    'content-type': 'application/grpc-web+proto',
                                    'x-grpc-web': '1',
                                    'x-codeium-csrf-token': finalCsrf,
                                    'content-length': String(body.length),
                                },
                            }, (res) => {
                                const chunks = [];
                                res.on('data', (c) => chunks.push(Buffer.from(c)));
                                res.on('error', reject);
                                res.on('end', () => {
                                    const status = Number(res.statusCode || 0);
                                    const buf = Buffer.concat(chunks);
                                    if (status !== 200) {
                                        reject(new Error(`HTTP ${status}`));
                                        return;
                                    }
                                    const extracted = extractGrpcStatus(buf, res.headers, res.trailers);
                                    if (extracted !== 0 && extracted !== null) {
                                        reject(new Error(`gRPC ${extracted}`));
                                        return;
                                    }
                                    grpcStatus = extracted || 0;
                                    resolve();
                                });
                            });
                            req.setTimeout(5000, () => req.destroy(new Error('timeout')));
                            req.on('error', reject);
                            req.write(body);
                            req.end();
                        });
                        rpcDeleted = true;
                        break;
                    } catch (_e) {}
                }
            }
        }

        const conversationsRoot = profileDataPath('conversations');
        const convoPbPath = path.join(conversationsRoot, cascadeId + '.pb');
        const convoDbPath = path.join(conversationsRoot, cascadeId + '.db');
        const cleanupErrors = [];
        let quarantinedFiles = 0;

        if (isPathInside(conversationsRoot, convoPbPath) && isPathInside(conversationsRoot, convoDbPath)) {
            const localFiles = [
                convoPbPath,
                convoDbPath,
                convoDbPath + '-shm',
                convoDbPath + '-wal',
            ].filter((candidate) => fs_std.existsSync(candidate));
            if (localFiles.length) {
                const quarantineRoot = profileDataPath('scratch', 'deleted-temp-conversations');
                const quarantineDir = path.join(quarantineRoot, cascadeId + '-' + String(Date.now()));
                if (isPathInside(quarantineRoot, quarantineDir)) {
                    try {
                        fs_std.mkdirSync(quarantineDir, { recursive: true });
                        for (const localFile of localFiles) {
                            const quarantineFile = path.join(quarantineDir, path.basename(localFile));
                            try {
                                fs_std.renameSync(localFile, quarantineFile);
                                quarantinedFiles += 1;
                            } catch (error) {
                                try {
                                    fs_std.unlinkSync(localFile);
                                    quarantinedFiles += 1;
                                } catch (_unlinkErr) {
                                    cleanupErrors.push(path.basename(localFile) + ': ' + error.message);
                                }
                            }
                        }
                    } catch (_dirErr) {}
                }
            }
        }

        return {
            status: cleanupErrors.length ? 'warning' : 'success',
            rpcDeleted,
            grpcStatus,
            quarantinedFiles,
            cleanupErrors,
        };
    }

    async function callUnleashedServerApi({ baseUrl, apiKey, model, systemPrompt, userPrompt, revertEphemeral, onProgress }) {
        const normalizedUrl = normalizeUnleashedBaseUrl(baseUrl);
        if (typeof onProgress === 'function') {
            onProgress(`Unleashed API (${normalizedUrl.replace(/^https?:\/\//, '')}) · Modell ${model}...`);
        }
        const headers = {
            'Content-Type': 'application/json',
            'X-Source-Framework': 'unleashed-desktop',
        };
        if (apiKey) {
            headers['Authorization'] = `Bearer ${apiKey}`;
            headers['X-Antigravity-Token'] = apiKey;
        }
        const messages = [];
        if (systemPrompt) {
            messages.push({ role: 'system', content: systemPrompt });
        }
        messages.push({ role: 'user', content: userPrompt });

        const response = await httpJsonRequest(`${normalizedUrl}/chat/completions`, {
            method: 'POST',
            headers,
            body: {
                model: model || 'gemini-3.8-flash-medium',
                messages,
                stream: false,
            },
            timeoutMs: 45000,
        });

        const payload = response.data || {};
        const choice = Array.isArray(payload.choices) && payload.choices.length > 0 ? payload.choices[0] : null;
        const msgObj = (choice && choice.message) || {};
        const text = String(msgObj.content || '').trim();
        const reasoning = String(msgObj.reasoning_content || '').trim();
        const conversationId = String(payload.conversation_id || '').trim();

        if (reasoning && typeof onProgress === 'function') {
            const firstReasoningLine = reasoning.split('\n').map(l => l.trim()).find(Boolean);
            if (firstReasoningLine) {
                onProgress('AI-Analyse: ' + firstReasoningLine.slice(0, 110));
            }
        }

        if (!text) {
            throw new Error('Unleashed API lieferte eine leere Antwort.');
        }

        if (conversationId && revertEphemeral !== false) {
            httpJsonRequest(`${normalizedUrl}/chat/revert`, {
                method: 'POST',
                headers,
                body: {
                    conversation_id: conversationId,
                    steps_back: 1,
                    reason: 'ephemeral_desktop_helper',
                },
                timeoutMs: 8000,
            }).catch(() => {});
        }

        return {
            text,
            provider: 'unleashed_api',
            endpoint: normalizedUrl,
            conversationId: '',
        };
    }

    async function callLocalUiCompletion({ csrfToken, model, systemPrompt, userPrompt, onProgress }) {
        let lsPort = 0;
        try {
            const languageServer = require('./languageServer');
            lsPort = Number(languageServer.getLsPort() || 0);
        } catch (_e) {}
        if (!lsPort) {
            throw new Error('Lokaler Antigravity LanguageServer-Port konnte nicht ermittelt werden.');
        }
        const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN || '';
        if (!finalCsrf) {
            throw new Error('Kein lokaler CSRF-Token für ConnectRPC verfügbar.');
        }

        const rpcHeaders = {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            'x-codeium-csrf-token': finalCsrf,
        };
        const rpcCall = async (methodName, bodyObj, timeoutMs = 15000) => {
            const res = await httpJsonRequest(
                `https://127.0.0.1:${lsPort}/exa.language_server_pb.LanguageServerService/${methodName}`,
                {
                    method: 'POST',
                    headers: rpcHeaders,
                    body: bodyObj || {},
                    rejectUnauthorized: false,
                    timeoutMs,
                },
            );
            return res.data || {};
        };

        if (typeof onProgress === 'function') {
            onProgress('Direkte lokale Antigravity-UI (ConnectRPC) wird verbunden...');
        }

        let modelEnum = 'MODEL_PLACEHOLDER_M319';
        try {
            const modelData = await rpcCall('GetCascadeModelConfigData', {}, 6000);
            const configs = Array.isArray(modelData.clientModelConfigs) ? modelData.clientModelConfigs : [];
            const needle = String(model || 'flash').toLowerCase();
            let matched = configs.find((c) => {
                const lbl = String(c.label || '').toLowerCase();
                const mEnum = String((c.modelOrAlias && c.modelOrAlias.model) || '').toLowerCase();
                return lbl.includes(needle) || mEnum === needle;
            });
            if (!matched) {
                matched = configs.find((c) => String(c.label || '').toLowerCase().includes('flash'));
            }
            if (matched && matched.modelOrAlias && matched.modelOrAlias.model) {
                modelEnum = matched.modelOrAlias.model;
            }
        } catch (_e) {}

        const startRes = await rpcCall('StartCascade', {
            metadata: {
                ideName: 'antigravity',
                apiKey: '',
                locale: 'de',
                ideVersion: '2.26.0',
                extensionName: 'antigravity',
            },
            source: 'CORTEX_TRAJECTORY_SOURCE_CASCADE_CLIENT',
            workspaceUris: [],
            customAgent: {
                name: 'Unleashed Helper',
                systemPrompt: systemPrompt || '',
                toolNames: [],
                excludeDefaultComponents: true,
                systemPromptConfig: { includeSections: [] },
            },
            knowledgeConfig: { enabled: false },
            conversationHistoryConfig: { enabled: false },
        }, 12000);

        const cascadeId = String(startRes.cascadeId || '').trim();
        if (!cascadeId) {
            throw new Error('StartCascade hat keine cascadeId zurückgegeben.');
        }

        try {
            temporaryConversationIds.register(cascadeId);
        } catch (_e) {}

        const combinedPrompt = systemPrompt ? `${systemPrompt}\n\n${userPrompt}` : userPrompt;
        try {
            if (typeof onProgress === 'function') {
                onProgress('Lokale AI analysiert Änderungen...');
            }
            await rpcCall('SendUserCascadeMessage', {
                cascadeId,
                items: [{ text: combinedPrompt }],
                metadata: {
                    ideName: 'antigravity',
                    apiKey: '',
                    locale: 'de',
                    ideVersion: '2.26.0',
                    extensionName: 'antigravity',
                },
                cascadeConfig: {
                    plannerConfig: {
                        conversational: {
                            plannerMode: 'CONVERSATIONAL_PLANNER_MODE_DEFAULT',
                            agenticMode: false,
                        },
                        toolConfig: {},
                        requestedModel: { model: modelEnum },
                        ephemeralMessagesConfig: { enabled: false },
                        knowledgeConfig: { enabled: false },
                    },
                    checkpointConfig: {},
                    conversationHistoryConfig: { enabled: false },
                },
                blocking: false,
                clientType: 1,
                messageOrigin: 1,
            }, 15000);

            let finalResponseText = '';
            let emittedThinking = false;
            for (let attempt = 0; attempt < 75; attempt++) {
                await new Promise((r) => setTimeout(r, 450));
                try {
                    const stepData = await rpcCall('GetCascadeTrajectorySteps', { cascadeId, stepOffset: 0 }, 8000);
                    const steps = Array.isArray(stepData.steps) ? stepData.steps : [];
                    for (let i = steps.length - 1; i >= 0; i--) {
                        const st = steps[i];
                        if (st && st.type === 'CORTEX_STEP_TYPE_PLANNER_RESPONSE') {
                            const pr = st.plannerResponse || {};
                            const thinking = String(pr.thinking || pr.Thinking || '').trim();
                            if (thinking && !emittedThinking && typeof onProgress === 'function') {
                                emittedThinking = true;
                                const line = thinking.split('\n').map(l => l.trim()).find(Boolean);
                                if (line) onProgress('AI denkt nach: ' + line.slice(0, 100));
                            }
                            const respText = String(pr.modifiedResponse || pr.response || pr.ModifiedResponse || pr.Response || '').trim();
                            if (respText && (st.status === 'CORTEX_STEP_STATUS_DONE' || st.status === 3)) {
                                finalResponseText = respText;
                                break;
                            }
                        }
                    }
                    if (finalResponseText) break;
                } catch (_pollErr) {}
            }

            if (!finalResponseText) {
                throw new Error('Zeitüberschreitung beim Warten auf lokale Antigravity-Antwort.');
            }

            return {
                text: finalResponseText,
                provider: 'local_ui',
                endpoint: `https://127.0.0.1:${lsPort}`,
                conversationId: '',
            };
        } finally {
            try {
                await deleteLocalCascadeTrajectory(cascadeId, finalCsrf);
                temporaryConversationIds.delete(cascadeId);
            } catch (_cleanupErr) {}
        }
    }

    async function runUnleashedAiCompletion({ systemPrompt, userPrompt, csrfToken, onProgress }) {
        const cfg = loadUnleashedAiConfig();
        if (cfg.mode === 'off') {
            return { text: '', provider: 'off', config: cfg };
        }

        if (cfg.mode === 'unleashed_api') {
            const res = await callUnleashedServerApi({
                baseUrl: cfg.apiUrl,
                apiKey: cfg.apiKey,
                model: cfg.model,
                systemPrompt,
                userPrompt,
                revertEphemeral: cfg.revertEphemeral,
                onProgress,
            });
            return Object.assign(res, { config: cfg });
        }

        if (cfg.mode === 'local_ui') {
            const res = await callLocalUiCompletion({
                csrfToken,
                model: cfg.model,
                systemPrompt,
                userPrompt,
                onProgress,
            });
            return Object.assign(res, { config: cfg });
        }

        // Mode === 'auto': Try configured Unleashed API -> Localhost 8001 -> Local UI ConnectRPC
        const candidateUrls = [cfg.apiUrl];
        const localBridgeUrl = 'http://127.0.0.1:8001/v1';
        if (normalizeUnleashedBaseUrl(cfg.apiUrl) !== localBridgeUrl) {
            candidateUrls.push(localBridgeUrl);
        }

        let lastApiError = null;
        for (const candidateUrl of candidateUrls) {
            try {
                const res = await callUnleashedServerApi({
                    baseUrl: candidateUrl,
                    apiKey: cfg.apiKey,
                    model: cfg.model,
                    systemPrompt,
                    userPrompt,
                    revertEphemeral: cfg.revertEphemeral,
                    onProgress,
                });
                return Object.assign(res, { config: cfg });
            } catch (apiErr) {
                lastApiError = apiErr;
            }
        }

        if (typeof onProgress === 'function') {
            onProgress('Unleashed API nicht erreichbar – wechsle automatisch auf direkte lokale UI...');
        }
        try {
            const res = await callLocalUiCompletion({
                csrfToken,
                model: cfg.model,
                systemPrompt,
                userPrompt,
                onProgress,
            });
            return Object.assign(res, { config: cfg });
        } catch (localErr) {
            const combinedMsg = lastApiError
                ? `Unleashed API (${lastApiError.message}) & Lokal UI (${localErr.message})`
                : localErr.message;
            throw new Error(combinedMsg);
        }
    }

    function generateRuleBasedCommitMessage(workspaceChanges, configChanges, commitStyle = 'concise') {
        const path = require('path');
        const all = [
            ...(Array.isArray(workspaceChanges) ? workspaceChanges : []),
            ...(Array.isArray(configChanges) ? configChanges : []),
        ];
        if (all.length === 0) {
            return 'chore: sync workspace updates';
        }

        const hasWorkspace = Array.isArray(workspaceChanges) && workspaceChanges.length > 0;
        const hasConfig = Array.isArray(configChanges) && configChanges.length > 0;

        const statuses = all.map(c => String(c.status || '').trim());
        const addedCount = statuses.filter(s => s === 'A' || s === '??').length;
        const deletedCount = statuses.filter(s => s === 'D').length;

        let commitType = 'chore';
        if (hasWorkspace) {
            const files = workspaceChanges.map(c => String(c.file || '').toLowerCase());
            if (files.every(f => f.endsWith('.md'))) {
                commitType = 'docs';
            } else if (files.every(f => f.includes('test'))) {
                commitType = 'test';
            } else if (addedCount > workspaceChanges.length / 2) {
                commitType = 'feat';
            } else if (deletedCount === workspaceChanges.length) {
                commitType = 'chore';
            } else {
                commitType = 'fix';
            }
        } else if (hasConfig) {
            commitType = 'chore';
        }

        let scope = 'sync';
        const primaryList = hasWorkspace ? workspaceChanges : configChanges;
        if (!hasWorkspace && hasConfig) {
            scope = 'config';
        } else if (primaryList.length > 0) {
            const firstFile = String(primaryList[0].file || '').replace(/\\/g, '/');
            const parts = firstFile.split('/').filter(Boolean);
            const base = path.basename(firstFile, path.extname(firstFile));
            if (parts.includes('ui')) scope = 'ui';
            else if (parts.includes('web-hub')) scope = 'hub';
            else if (parts.includes('desktop-ui-modifier')) scope = 'desktop';
            else if (parts.includes('skills')) scope = 'skills';
            else if (base && base.length <= 16) scope = base.toLowerCase().replace(/[^a-z0-9-_]/g, '');
        }

        const uniqueNames = [];
        for (const item of primaryList) {
            const base = path.basename(String(item.file || '').replace(/\\/g, '/'), path.extname(String(item.file || '')));
            if (base && !uniqueNames.includes(base)) {
                uniqueNames.push(base);
            }
            if (uniqueNames.length >= 2) break;
        }

        let actionVerb = 'update';
        if (addedCount === primaryList.length) actionVerb = 'add';
        else if (deletedCount === primaryList.length) actionVerb = 'remove';

        const targetDesc = uniqueNames.length > 0
            ? uniqueNames.join(' and ')
            : `${primaryList.length} files`;
        const extraSuffix = primaryList.length > 2 ? ` (+${primaryList.length - 2} more)` : '';
        const headerLine = `${commitType}(${scope}): ${actionVerb} ${targetDesc}${extraSuffix}`.slice(0, 72);

        if (commitStyle !== 'detailed') {
            return headerLine;
        }

        const bullets = all.slice(0, 4).map((item) => {
            const st = item.status === '??' || item.status === 'A' ? 'add' : (item.status === 'D' ? 'remove' : 'update');
            return `- ${st} ${String(item.file || '').replace(/\\/g, '/')}`;
        });
        return `${headerLine}\n\n${bullets.join('\n')}`;
    }

    electron_1.ipcMain.handle('ai:get-config', async (event) => {
        try {
            validateOrigin(event);
            const config = loadUnleashedAiConfig();
            return {
                status: 'success',
                config,
                presets: [
                    { id: 'server_lan', label: 'Auto (Unleashed API -> Local UI)', mode: 'auto', apiUrl: config.apiUrl },
                    { id: 'local_bridge', label: 'Lokaler API-Server (127.0.0.1:8001)', mode: 'unleashed_api', apiUrl: 'http://127.0.0.1:8001/v1' },
                    { id: 'local_ui', label: 'Direkt über Antigravity UI (Ohne API-Server)', mode: 'local_ui', apiUrl: config.apiUrl },
                    { id: 'off', label: 'Ohne AI (Regelbasiert)', mode: 'off', apiUrl: config.apiUrl },
                ],
            };
        } catch (err) {
            return { status: 'error', message: err.message };
        }
    });

    electron_1.ipcMain.handle('ai:save-config', async (event, patch) => {
        try {
            validateOrigin(event);
            const config = saveUnleashedAiConfig(patch);
            return { status: 'success', config };
        } catch (err) {
            return { status: 'error', message: err.message };
        }
    });

    electron_1.ipcMain.handle('ai:test-connection', async (event, overrideCfg, csrfToken) => {
        try {
            validateOrigin(event);
            const current = loadUnleashedAiConfig();
            const cfg = Object.assign({}, current, (overrideCfg && typeof overrideCfg === 'object') ? overrideCfg : {});
            const startedAt = Date.now();

            if (cfg.mode === 'off') {
                return {
                    status: 'success',
                    provider: 'off',
                    latencyMs: 0,
                    models: [],
                    message: 'AI deaktiviert – Regelbasierter Commit-Generator ist aktiv.',
                };
            }

            const testUnleashedUrl = async (rawUrl) => {
                const baseUrl = normalizeUnleashedBaseUrl(rawUrl);
                const headers = {};
                if (cfg.apiKey) {
                    headers['Authorization'] = `Bearer ${cfg.apiKey}`;
                    headers['X-Antigravity-Token'] = cfg.apiKey;
                }
                const t0 = Date.now();
                const res = await httpJsonRequest(`${baseUrl}/models`, {
                    method: 'GET',
                    headers,
                    timeoutMs: 6000,
                });
                const latencyMs = Date.now() - t0;
                const list = Array.isArray(res.data && res.data.data) ? res.data.data : [];
                const models = list.map(m => String(m.id || '')).filter(Boolean);
                return {
                    status: 'success',
                    provider: 'unleashed_api',
                    endpoint: baseUrl,
                    latencyMs,
                    models,
                    message: `Unleashed API online (${latencyMs} ms · ${models.length} Modelle)`,
                };
            };

            const testLocalUi = async () => {
                let lsPort = 0;
                try {
                    const languageServer = require('./languageServer');
                    lsPort = Number(languageServer.getLsPort() || 0);
                } catch (_e) {}
                if (!lsPort) {
                    throw new Error('LanguageServer-Port nicht gefunden.');
                }
                const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN || '';
                const t0 = Date.now();
                const res = await httpJsonRequest(
                    `https://127.0.0.1:${lsPort}/exa.language_server_pb.LanguageServerService/GetCascadeModelConfigData`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Connect-Protocol-Version': '1',
                            'x-codeium-csrf-token': finalCsrf,
                        },
                        body: {},
                        rejectUnauthorized: false,
                        timeoutMs: 6000,
                    },
                );
                const latencyMs = Date.now() - t0;
                const configs = Array.isArray(res.data && res.data.clientModelConfigs) ? res.data.clientModelConfigs : [];
                const models = configs.map(c => String(c.label || (c.modelOrAlias && c.modelOrAlias.model) || '')).filter(Boolean);
                return {
                    status: 'success',
                    provider: 'local_ui',
                    endpoint: `https://127.0.0.1:${lsPort}`,
                    latencyMs,
                    models,
                    message: `Lokale Antigravity UI bereit (${latencyMs} ms · Port ${lsPort})`,
                };
            };

            if (cfg.mode === 'unleashed_api') {
                return await testUnleashedUrl(cfg.apiUrl);
            }
            if (cfg.mode === 'local_ui') {
                return await testLocalUi();
            }

            // mode === 'auto'
            try {
                return await testUnleashedUrl(cfg.apiUrl);
            } catch (primaryErr) {
                const localUrl = 'http://127.0.0.1:8001/v1';
                if (normalizeUnleashedBaseUrl(cfg.apiUrl) !== localUrl) {
                    try {
                        return await testUnleashedUrl(localUrl);
                    } catch (_e) {}
                }
                const localRes = await testLocalUi();
                localRes.message = `Auto-Fallback → ${localRes.message} (API offline: ${primaryErr.message})`;
                return localRes;
            }
        } catch (err) {
            return { status: 'error', message: err.message };
        }
    });

    // Generate AI Commit Message via Unleashed API / Local UI / Rule-based fallback
    electron_1.ipcMain.handle('git:generate-commit-msg', async (event, conversationId, csrfToken) => {
        console.log('[AMS IPC Git] git:generate-commit-msg CALLED with convoId:', conversationId);
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');
            const sender = event.sender;
            const sendProgress = (msg) => {
                try {
                    if (sender && (!sender.isDestroyed || !sender.isDestroyed())) {
                        sender.send('git:generate-commit-progress', String(msg || ''));
                    }
                } catch (_e) {}
            };

            const configRepoPath = path.join(os.homedir(), '.gemini', 'config');
            const workspaceRepoPath = await resolveWorkspacePath(conversationId);
            const hasWorkspaceGit = Boolean(workspaceRepoPath && fs_std.existsSync(path.join(workspaceRepoPath, '.git')));
            const hasConfigGit = Boolean(configRepoPath && fs_std.existsSync(path.join(configRepoPath, '.git')));

            if (!hasWorkspaceGit && !hasConfigGit) {
                return { status: 'error', message: 'Kein aktiver Workspace oder Git-Repository vorhanden.' };
            }

            let workspaceChanges = [];
            let configChanges = [];
            const diffSections = [];

            const collectRepoDiff = async (repoPath, label, repoTag) => {
                const changes = [];
                try {
                    const { stdout } = await execFilePromise('git', ['status', '--porcelain'], { cwd: repoPath });
                    const lines = stdout.split('\n').map(l => l.trim()).filter(Boolean);
                    for (const line of lines) {
                        changes.push({
                            status: line.substring(0, 2).trim(),
                            file: line.substring(2).trim(),
                            repo: repoTag,
                        });
                    }
                    if (changes.length > 0) {
                        let repoDiff = '';
                        try {
                            const dHead = await execFilePromise('git', ['diff', 'HEAD'], { cwd: repoPath });
                            repoDiff = dHead.stdout || '';
                        } catch (_e) {}
                        if (!repoDiff.trim()) {
                            try {
                                const dUnstaged = await execFilePromise('git', ['diff'], { cwd: repoPath });
                                repoDiff = dUnstaged.stdout || '';
                            } catch (_e) {}
                        }
                        const statusSummary = changes.map(c => `${c.status} ${c.file}`).join('\n');
                        const truncatedDiff = repoDiff.length > 4500 ? repoDiff.substring(0, 4500) + '\n... (Diff gekürzt)' : repoDiff;
                        diffSections.push(
                            `=== ${label} (${path.basename(repoPath)}) ===\nGeänderte Dateien:\n${statusSummary}\n\nDiff:\n${truncatedDiff || '(Neue/ungetrackte Dateien)'}`
                        );
                    }
                } catch (_e) {}
                return changes;
            };

            if (hasWorkspaceGit) {
                workspaceChanges = await collectRepoDiff(workspaceRepoPath, 'Workspace Repository', 'workspace');
            }
            if (hasConfigGit) {
                configChanges = await collectRepoDiff(configRepoPath, 'Config Repository (~/.gemini/config)', 'config');
            }

            if (workspaceChanges.length === 0 && configChanges.length === 0) {
                return { status: 'error', message: 'Keine Änderungen gefunden' };
            }

            const aiCfg = loadUnleashedAiConfig();
            sendProgress(
                `${workspaceChanges.length + configChanges.length} geänderte Datei(en) analysiert · Modus: ${
                    aiCfg.mode === 'auto' ? 'Auto (Unleashed API → Lokal UI)' :
                    aiCfg.mode === 'unleashed_api' ? 'Unleashed Server API' :
                    aiCfg.mode === 'local_ui' ? 'Lokal (Antigravity UI)' : 'Regelbasiert (Ohne AI)'
                }`
            );

            if (aiCfg.mode === 'off') {
                const ruleMsg = generateRuleBasedCommitMessage(workspaceChanges, configChanges, aiCfg.commitStyle);
                sendProgress('Regelbasierte Commit-Message aus Git-Status erstellt.');
                return { status: 'success', commitMessage: ruleMsg, provider: 'off', convoId: '' };
            }

            const diffPayload = diffSections.join('\n\n').slice(0, 7500);
            const isDetailed = aiCfg.commitStyle === 'detailed';
            const systemPrompt = isDetailed
                ? 'You are a senior developer assistant that writes clean, accurate Conventional Commit messages in English. Reply ONLY with the raw commit message (no markdown code blocks, no intro text).'
                : 'You are a senior developer assistant that writes ultra-concise, accurate one-line Conventional Commit messages in English (3 to 8 words, max 72 characters). Never output markdown backticks, quotes, or multi-line explanations.';

            const userPrompt = isDetailed
                ? (
                    'Write a Conventional Commit message in English for the following Git changes:\n' +
                    '1. A concise imperative title line (e.g. "feat(ui): add unleashed ai api selector", max 72 chars).\n' +
                    '2. A blank line.\n' +
                    '3. 2 to 4 brief bullet points ("- ") summarizing the key changes.\n\n' +
                    'Output ONLY the raw commit message:\n\n' + diffPayload
                )
                : (
                    'Write ONE single, concise Conventional Commit line in English (3 to 8 words, max 72 chars, e.g. "feat(git): use unleashed api for commit messages" or "fix(ipc): support local ui fallback").\n' +
                    'Output ONLY the single line without quotes or backticks:\n\n' + diffPayload
                );

            let commitMessage = '';
            let providerUsed = aiCfg.mode;
            try {
                const aiRes = await runUnleashedAiCompletion({
                    systemPrompt,
                    userPrompt,
                    csrfToken,
                    onProgress: sendProgress,
                });
                commitMessage = String(aiRes.text || '').trim();
                providerUsed = aiRes.provider || aiCfg.mode;
            } catch (aiErr) {
                if (aiCfg.mode === 'auto') {
                    sendProgress(`AI-Endpunkte nicht erreichbar (${aiErr.message}) – nutze regelbasierten Fallback...`);
                    commitMessage = generateRuleBasedCommitMessage(workspaceChanges, configChanges, aiCfg.commitStyle);
                    providerUsed = 'rule_fallback';
                } else {
                    throw aiErr;
                }
            }

            commitMessage = commitMessage
                .replace(/^```[a-z]*\n?/i, '')
                .replace(/\n?```$/i, '')
                .replace(/^['"`]+|['"`]+$/g, '')
                .replace(/^conventional commit:\s*/i, '')
                .trim();

            if (!isDetailed && commitMessage.includes('\n')) {
                commitMessage = commitMessage.split('\n').map(l => l.trim()).find(Boolean) || commitMessage;
            }

            sendProgress('Bereinigung abgeschlossen.');
            return { status: 'success', commitMessage, provider: providerUsed, convoId: '' };
        } catch (err) {
            console.error('[AMS IPC Git] git:generate-commit-msg failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    electron_1.ipcMain.handle('git:consolidate-memory', async (event, conversationId, csrfToken) => {
        try {
            validateOrigin(event);
            const path = require('path');
            const fs_std = require('fs');

            const aiCfg = loadUnleashedAiConfig();
            if (aiCfg.mode === 'off') {
                return { found: false };
            }

            // Collect last conversation messages either via local ConnectRPC or SQLite .db fallback
            const historyEntries = [];
            let lsPort = 0;
            try {
                const languageServer = require('./languageServer');
                lsPort = Number(languageServer.getLsPort() || 0);
            } catch (_e) {}
            const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN || '';

            if (lsPort && finalCsrf && conversationId) {
                try {
                    const stepRes = await httpJsonRequest(
                        `https://127.0.0.1:${lsPort}/exa.language_server_pb.LanguageServerService/GetCascadeTrajectorySteps`,
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Connect-Protocol-Version': '1',
                                'x-codeium-csrf-token': finalCsrf,
                            },
                            body: { cascadeId: conversationId, stepOffset: 0 },
                            rejectUnauthorized: false,
                            timeoutMs: 8000,
                        },
                    );
                    const steps = Array.isArray(stepRes.data && stepRes.data.steps) ? stepRes.data.steps : [];
                    for (const st of steps.slice(-14)) {
                        if (!st) continue;
                        if (st.type === 'CORTEX_STEP_TYPE_USER_INPUT' && st.userInput) {
                            const items = Array.isArray(st.userInput.items) ? st.userInput.items : [];
                            const txt = items.map(it => it.text || '').join(' ').trim();
                            if (txt) historyEntries.push(`User: ${txt.slice(0, 1200)}`);
                        } else if (st.type === 'CORTEX_STEP_TYPE_PLANNER_RESPONSE' && st.plannerResponse) {
                            const txt = String(st.plannerResponse.modifiedResponse || st.plannerResponse.response || '').trim();
                            if (txt) historyEntries.push(`Assistant: ${txt.slice(0, 1200)}`);
                        }
                    }
                } catch (_rpcErr) {}
            }

            if (historyEntries.length === 0) {
                return { found: false };
            }

            const convoText = historyEntries.slice(-10).join('\n\n');
            const systemPrompt =
                'Du bist ein Programmier-Assistent, der das Langzeitgedächtnis eines Entwicklers pflegt. Antworte AUSSCHLIESSLICH mit validem JSON ohne Markdown-Backticks.';
            const userPrompt =
                'Analysiere den folgenden Verlauf der Konversation. Bestimme, ob darin wichtige technische Erkenntnisse (z.B. Fehlerbehebungen, Escaping-Tricks, CSS-Verhalten, spezielle Parameter) oder neue Benutzerpräferenzen erarbeitet wurden.\n' +
                'Falls ja, formuliere einen kurzen, prägnanten Bulletpoint im Markdown-Format (max. 150 Zeichen), der diese Erkenntnis beschreibt.\n' +
                'Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt:\n' +
                '{\n' +
                '  "found": true,\n' +
                '  "type": "lesson_learned" oder "preference",\n' +
                '  "proposed_text": "Der Bulletpoint-Text"\n' +
                '}\n' +
                'Wenn keine nennenswerten Erkenntnisse oder Präferenzen erarbeitet wurden, antworte exakt mit:\n' +
                '{\n' +
                '  "found": false\n' +
                '}\n\n' +
                'Verlauf der Konversation:\n' + convoText;

            const aiRes = await runUnleashedAiCompletion({
                systemPrompt,
                userPrompt,
                csrfToken: finalCsrf,
            });

            let txtClean = String(aiRes.text || '').trim();
            if (txtClean.startsWith('```json')) {
                txtClean = txtClean.split('```json')[1].split('```')[0].trim();
            } else if (txtClean.startsWith('```')) {
                txtClean = txtClean.split('```')[1].split('```')[0].trim();
            }

            try {
                const parsed = JSON.parse(txtClean);
                return {
                    found: Boolean(parsed.found),
                    type: parsed.type || 'lesson_learned',
                    proposed_text: parsed.proposed_text || '',
                };
            } catch (_parseErr) {
                return { found: false };
            }
        } catch (err) {
            console.error('[AMS IPC Memory] Outer handle failed:', err);
            return { found: false, error: err.message };
        }
    });

    electron_1.ipcMain.handle('memory:apply-suggestion', async (event, type, text) => {
        try {
            validateOrigin(event);
            const path = require('path');
            const fs_std = require('fs');
            const os = require('os');

            const configDir = path.join(os.homedir(), '.gemini', 'config');
            let filename = '';
            let targetSection = '';

            if (type === 'preference') {
                filename = 'USER.pc.md';
                targetSection = '## 2. Dialectical Preference History';
            } else {
                filename = 'MEMORY.pc.md';
                targetSection = '## 5. Gelernte Techniken (Lessons Learned)';
            }

            const filePath = path.join(configDir, filename);
            if (!fs_std.existsSync(filePath)) {
                return { status: 'error', message: `Datei nicht gefunden: ${filename}` };
            }

            let content = fs_std.readFileSync(filePath, 'utf-8');
            let bulletText = text.trim();
            if (!bulletText.startsWith('-')) {
                bulletText = `- ${bulletText}`;
            }

            const sectionIdx = content.indexOf(targetSection);
            if (sectionIdx === -1) {
                content += `\n\n${targetSection}\n${bulletText}\n`;
            } else {
                const insertPos = sectionIdx + targetSection.length;
                let endOfLine = content.indexOf('\n', insertPos);
                if (endOfLine === -1) endOfLine = content.length;

                content = content.slice(0, endOfLine) + `\n${bulletText}` + content.slice(endOfLine);
            }

            fs_std.writeFileSync(filePath, content, 'utf-8');
            console.log(`[AMS IPC Memory] Updated ${filename} successfully.`);

            const compileScriptPath = path.join(configDir, 'scripts', 'compile_memory.py');
            if (fs_std.existsSync(compileScriptPath)) {
                try {
                    await execFilePromise(
                        getPythonPath(),
                        [compileScriptPath],
                        { cwd: configDir, windowsHide: true, timeout: 30000 },
                    );
                    console.log('[AMS IPC Memory] Memory compiled successfully.');
                } catch (compileErr) {
                    console.error('[AMS IPC Memory] Failed to compile memory:', compileErr);
                    return { status: 'warning', message: 'Eintrag gespeichert, aber Kompilierung fehlgeschlagen: ' + compileErr.message };
                }
            } else {
                console.warn('[AMS IPC Memory] compile_memory.py not found.');
            }

            return { status: 'success' };
        } catch (err) {
            console.error('[AMS IPC Memory] memory:apply-suggestion failed:', err);
            return { status: 'error', message: err.message };
        }
    });

    electron_1.ipcMain.handle('git:delete-temp-conversation', async (event, convoId, csrfToken) => {
        try {
            validateOrigin(event);
            const safeConvoId = temporaryConversationIds.require(convoId);
            if (typeof csrfToken !== 'string' || csrfToken.length === 0 || csrfToken.length > 512) {
                throw new Error('Invalid CSRF token.');
            }
            const res = await deleteLocalCascadeTrajectory(safeConvoId, csrfToken);
            temporaryConversationIds.delete(safeConvoId);
            return res;
        } catch (err) {
            console.error('[AMS IPC Git] Failed to delete temp conversation:', err);
            return { status: 'error', message: err.message };
        }
    });

    // Get nightly runs list
    electron_1.ipcMain.handle('wsl:get-state', async (event) => {
        validateOrigin(event);
        if (!(0, wsl_1.isWslAvailable)()) {
            return { available: false, activeDistro: null, distros: [] };
        }
        try {
            const distros = await (0, wsl_1.listWslDistros)();
            return {
                available: true,
                activeDistro: (0, wsl_1.getActiveWslDistro)() ?? null,
                distros: distros.map((distro) => ({ name: distro.name, isDefault: distro.isDefault })),
            };
        } catch (error) {
            main_1.default.error('wsl:get-state failed:', error);
            return { available: false, activeDistro: null, distros: [] };
        }
    });
    electron_1.ipcMain.handle('wsl:connect', (event, distro) => {
        validateOrigin(event);
        (0, menu_1.relaunchWithWslDistro)(distro || '');
    });
    // Execute JavaScript inside an Electron <webview> guest's isolated world.
    // Only the renderer that hosts the <webview> may target it, and worldId is
    // bounded to [MIN, MAX] so it can never hit the main (0) or preload worlds
    // and stays well below Chromium's fatal ISOLATED_WORLD_ID_MAX CHECK.
    const MIN_ISOLATED_WORLD_ID = 1000;
    const MAX_ISOLATED_WORLD_ID = 100000;
    electron_1.ipcMain.handle('webview:execute-js-isolated-world', async (event, webContentsId, worldId, code) => {
        validateOrigin(event);
        if (typeof webContentsId !== 'number' ||
            !Number.isInteger(webContentsId) ||
            webContentsId <= 0) {
            throw new Error(`Invalid webContentsId: ${String(webContentsId)}`);
        }
        if (typeof worldId !== 'number' ||
            !Number.isInteger(worldId) ||
            worldId < MIN_ISOLATED_WORLD_ID ||
            worldId > MAX_ISOLATED_WORLD_ID) {
            throw new Error(`Invalid isolated worldId: ${String(worldId)} (must be in [${MIN_ISOLATED_WORLD_ID}, ${MAX_ISOLATED_WORLD_ID}])`);
        }
        if (typeof code !== 'string') {
            throw new Error('code must be a string');
        }
        const wc = electron_1.webContents.fromId(webContentsId);
        if (!wc || wc.isDestroyed() || wc.getType() !== 'webview') {
            throw new Error(`Invalid or non-webview webContents id: ${webContentsId}`);
        }
        const sender = event?.sender;
        if (!sender ||
            sender.isDestroyed() ||
            wc.hostWebContents?.id !== sender.id) {
            throw new Error(`WebContents ${webContentsId} is not owned by the calling renderer`);
        }
        return wc.executeJavaScriptInIsolatedWorld(worldId, [{ code }], false);
    });

    electron_1.ipcMain.handle('reviews:get-runs', async (event) => {
        try {
            validateOrigin(event);
            const path = require('path');
            const fs_std = require('fs');
            const os = require('os');

            const logDir = profileDataPath('sidecar_data', 'nightly-autonomic-coding', 'data');
            if (!fs_std.existsSync(logDir)) {
                return [];
            }

            const files = fs_std.readdirSync(logDir);
            const allRuns = [];
            for (const file of files) {
                if (file.startsWith('run_') && file.endsWith('.json')) {
                    try {
                        const content = fs_std.readFileSync(path.join(logDir, file), 'utf-8');
                        const data = JSON.parse(content);
                        allRuns.push(data);
                    } catch (e) {
                        console.error('[AMS IPC Reviews] Error reading run file:', file, e);
                    }
                }
            }
            // Sort runs by date descending
            allRuns.sort((a, b) => new Date(b.date) - new Date(a.date));
            return allRuns;
        } catch (err) {
            console.error('[AMS IPC Reviews] reviews:get-runs failed:', err);
            return [];
        }
    });

    // Get logs for a specific run conversation
    electron_1.ipcMain.handle('reviews:get-run-log', async (event, convoId) => {
        try {
            validateOrigin(event);
            const path = require('path');
            const fs_std = require('fs');
            const os = require('os');

            if (!convoId) return [];
            const safeConvoId = normalizeConversationId(convoId);
            const conversationsRoot = profileDataPath('conversations');

            const dbPath = path.join(conversationsRoot, safeConvoId + '.db');
            if (!isPathInside(conversationsRoot, dbPath)) {
                throw new Error('Conversation database path escapes the conversation store.');
            }
            if (!fs_std.existsSync(dbPath)) {
                return [{ role: 'system', content: 'Datenbank für Chat ' + safeConvoId + ' existiert nicht oder wurde bereinigt.' }];
            }

            // Build Python script to extract log
            const pythonScript = `
import sqlite3
import json
import re
import sys

def parse_protobuf(data):
    fields = []
    pos = 0
    while pos < len(data):
        try:
            val_start = pos
            header = 0
            shift = 0
            while True:
                b = data[pos]
                header |= (b & 0x7f) << shift
                pos += 1
                if not (b & 0x80): break
                shift += 7
            field_number = header >> 3
            wire_type = header & 0x07
        except IndexError:
            break
        if wire_type == 0:
            shift = 0
            val = 0
            while True:
                try:
                    b = data[pos]
                    val |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                except IndexError:
                    break
            fields.append((field_number, wire_type, val))
        elif wire_type == 2:
            length = 0
            shift = 0
            while True:
                try:
                    b = data[pos]
                    length |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                except IndexError:
                    break
            val = data[pos:pos+length]
            pos += length
            fields.append((field_number, wire_type, val))
        else:
            break
    return fields

def get_text_from_payload(payload, step_type):
    outer_fields = parse_protobuf(payload)
    if not outer_fields: return None
    if step_type == 15:
        for fn, wt, val in outer_fields:
            if fn == 20 and wt == 2:
                inner_fields = parse_protobuf(val)
                if inner_fields:
                    for inner_fn, inner_wt, inner_val in inner_fields:
                        if inner_fn == 1 and inner_wt == 2:
                            try: return inner_val.decode('utf-8')
                            except: pass
    elif step_type == 14:
        for fn, wt, val in outer_fields:
            if fn == 19 and wt == 2:
                inner_fields = parse_protobuf(val)
                if inner_fields:
                    for inner_fn, inner_wt, inner_val in inner_fields:
                        if inner_fn == 2 and inner_wt == 2:
                            try: return inner_val.decode('utf-8')
                            except: pass
    for fn, wt, val in outer_fields:
        if wt == 2 and len(val) > 2:
            try:
                decoded = val.decode('utf-8')
                if any(c.isalnum() for c in decoded) and len(decoded) < 5000:
                    if not decoded.startswith('file://') and not re.match(r'^[a-f0-9-]{36}$', decoded):
                        return decoded
            except: pass
    return None

conn = sqlite3.connect(sys.argv[1])
rows = conn.execute("SELECT step_type, status, metadata, step_payload FROM steps ORDER BY idx ASC").fetchall()
chat_log = []
for step_type, status, metadata, payload in rows:
    if step_type in (14, 15):
        txt = get_text_from_payload(payload, step_type)
        if txt:
            chat_log.append({
                'role': 'user' if step_type == 14 else 'agent',
                'content': txt
            })
    elif step_type == 9:
        try:
            outer = parse_protobuf(payload)
            cmd_str = None
            for fn, wt, val in outer:
                if wt == 2 and len(val) > 1:
                    try:
                        decoded = val.decode('utf-8')
                        if decoded.startswith('git ') or decoded.startswith('python ') or decoded.startswith('pip ') or decoded.startswith('gh '):
                            cmd_str = decoded
                            break
                    except: pass
            if cmd_str:
                chat_log.append({
                    'role': 'tool',
                    'content': f"Executed: {cmd_str}"
                })
        except: pass

print(json.dumps(chat_log))
`;
            const scriptPath = path.join(os.tmpdir(), 'antigravity-review-' + crypto.randomUUID() + '.py');
            fs_std.writeFileSync(scriptPath, pythonScript, 'utf-8');

            let output = '[]';
            try {
                const { stdout } = await execFilePromise(
                    getPythonPath(),
                    [scriptPath, dbPath],
                    { maxBuffer: 10 * 1024 * 1024, encoding: 'utf-8', windowsHide: true, timeout: 30000 },
                );
                output = stdout;
            } catch (e) {
                console.error('[AMS IPC Reviews] Python extractor failed:', e);
            } finally {
                try { fs_std.unlinkSync(scriptPath); } catch (e) {}
            }

            return JSON.parse(output.trim() || '[]');
        } catch (err) {
            console.error('[AMS IPC Reviews] reviews:get-run-log failed:', err);
            return [];
        }
    });
}
