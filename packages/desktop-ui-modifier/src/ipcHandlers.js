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

            const scriptPath = path.join(os.homedir(), '.gemini', 'config', 'skills', 'antigravity_desktop_ui_modifier', 'scripts', 'get_token_stats.py');
            if (!fs_std.existsSync(scriptPath)) {
                console.error('[AMS IPC] get_token_stats.py script not found at:', scriptPath);
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

    // Generate AI Commit Message using agentapi CLI
    electron_1.ipcMain.handle('git:generate-commit-msg', async (event, conversationId, csrfToken) => {
        console.log('[AMS IPC Git] git:generate-commit-msg CALLED with convoId:', conversationId);
        try {
            validateOrigin(event);
            console.log('[AMS IPC Git] validateOrigin passed');
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const workspaceRepoPath = await resolveWorkspacePath(conversationId);
            console.log('[AMS IPC Git] resolveWorkspacePath:', workspaceRepoPath);
            if (!workspaceRepoPath || !fs_std.existsSync(path.join(workspaceRepoPath, '.git'))) {
                return { status: 'error', message: 'Kein aktiver Workspace oder Git-Repository vorhanden.' };
            }

            let diffText = '';
            try {
                const { stdout } = await execFilePromise('git', ['diff', 'HEAD'], { cwd: workspaceRepoPath });
                diffText = stdout;
                if (!diffText.trim()) {
                    const unstaged = await execFilePromise('git', ['diff'], { cwd: workspaceRepoPath });
                    diffText = unstaged.stdout;
                }
                if (!diffText.trim()) {
                    const statusCheck = await execFilePromise('git', ['status', '--porcelain'], { cwd: workspaceRepoPath });
                    diffText = "Geänderte Dateien:\n" + statusCheck.stdout;
                }
            } catch (e) {
                diffText = 'Konnte Diff nicht lesen.';
            }

            if (diffText.length > 6000) {
                diffText = diffText.substring(0, 6000) + '\n... (Diff gekürzt)';
            }

            const agentapiPath = profileDataPath('bin', 'agentapi.bat');
            if (!fs_std.existsSync(agentapiPath)) {
                return { status: 'error', message: 'agentapi.bat wurde nicht gefunden.' };
            }

            const prompt = "Schreibe eine detaillierte, aber präzise Git-Commit-Message in englischer Sprache für das folgende Git-Diff. Der Aufbau MUSS dem Conventional-Commits-Standard entsprechen:\n" +
                           "1. Eine kurze, aussagekräftige Titelzeile im Imperativ (z. B. 'feat(tracker): add diff viewer', maximal 72 Zeichen).\n" +
                           "2. Eine Leerzeile.\n" +
                           "3. Ein detaillierter Body mit kurzen, stichpunktartigen Erklärungen der konkreten Code-Änderungen (jeweils mit einem Spiegelstrich '- ' eingeleitet). Beschreibe knapp, was geändert wurde und warum, aber fasse dich kurz und übertreibe nicht (maximal 2 bis 4 Spiegelstriche).\n\n" +
                           "Antworte AUSSCHLIESSLICH mit der fertigen Git-Commit-Message und absolut nichts anderem (keine Markdown-Backticks, kein einleitender Text, direkt der reine Text):\n\n" + diffText;

            const tempScriptPath = path.join(os.tmpdir(), `gen_commit_${Date.now()}.py`);
            const escapedPrompt = prompt.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
            const pythonCode =
                "import subprocess\n" +
                "import json\n" +
                "import time\n" +
                "import os\n" +
                "import sqlite3\n" +
                "import sys\n" +
                "import re\n\n" +
                "sys.stdout.reconfigure(encoding='utf-8')\n" +
                "print('PROGRESS: Workspace-Status und Git-Projekt ermitteln...', flush=True)\n" +
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
                "def get_text(payload):\n" +
                "    outer_fields = parse_protobuf(payload)\n" +
                "    for fn, wt, val in outer_fields:\n" +
                "        if fn == 20 and wt == 2:\n" +
                "            inner_fields = parse_protobuf(val)\n" +
                "            for inner_fn, inner_wt, inner_val in inner_fields:\n" +
                "                if inner_fn == 1 and inner_wt == 2:\n" +
                "                    try: return inner_val.decode('utf-8')\n" +
                "                    except Exception: pass\n" +
                "    return None\n\n" +
                "prompt = \"\"\"" + escapedPrompt + "\"\"\"\n" +
                "for k in list(os.environ.keys()):\n" +
                "    if any(x in k.upper() for x in ['GEMINI', 'WORKSPACE', 'PROJECT', 'CODEIUM']):\n" +
                "        if k not in ('ANTIGRAVITY_LS_ADDRESS', 'ANTIGRAVITY_CSRF_TOKEN', 'ANTIGRAVITY_DATA_DIR'):\n" +
                "            del os.environ[k]\n" +
                "active_convo_id = \"" + conversationId + "\"\n" +
                "db_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{active_convo_id}.db')\n" +
                "project_id = ''\n" +
                "workspace_id = ''\n" +
                "if os.path.exists(db_path):\n" +
                "    try:\n" +
                "        db_uri = db_path.replace('\\\\\\\\', '/').replace('\\\\', '/')\n" +
                "        conn = sqlite3.connect(f'file:{db_uri}?mode=ro', uri=True, timeout=1.0)\n" +
                "        row = conn.execute(\"SELECT data FROM trajectory_metadata_blob WHERE id = 'main'\").fetchone()\n" +
                "        conn.close()\n" +
                "        if row:\n" +
                "            blob = row[0]\n" +
                "            ascii_text = ''.join(chr(b) if 32 <= b <= 126 else '\\x00' for b in blob)\n" +
                "            uuids = re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', ascii_text, re.IGNORECASE)\n" +
                "            if len(uuids) >= 2:\n" +
                "                workspace_id = uuids[0]\n" +
                "                project_id = uuids[1]\n" +
                "            elif len(uuids) == 1:\n" +
                "                workspace_id = uuids[0]\n" +
                "                project_id = uuids[0]\n" +
                "    except Exception: pass\n" +
                "if project_id: os.environ['ANTIGRAVITY_PROJECT_ID'] = project_id\n" +
                "if workspace_id: os.environ['ANTIGRAVITY_WORKSPACE_ID'] = workspace_id\n" +
                "print('PROGRESS: Projekt- und Workspace-IDs aufgelöst.', flush=True)\n" +
                "print('PROGRESS: Neue AI-Konversation wird initiiert...', flush=True)\n" +
                "ls_exe = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local'), 'Programs', 'Antigravity', 'resources', 'bin', 'language_server.exe')\n" +
                "cmd = [ls_exe, 'agentapi', 'new-conversation', '--model=flash', prompt]\n" +
                "res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', cwd=os.path.expanduser('~'))\n" +
                "try:\n" +
                "    out = json.loads(res.stdout)\n" +
                "    convo_id = out['response']['newConversation']['conversationId']\n" +
                "except Exception as e:\n" +
                "    print('ERROR: Failed to start conversation:', res.stderr, res.stdout)\n" +
                "    sys.exit(1)\n\n" +
                "print('PROGRESS: Konversation gestartet. Warte auf AI-Denkvorgänge...', flush=True)\n" +
                "db_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{convo_id}.db')\n" +
                "txt = None\n" +
                "seen_steps = set()\n" +
                "for _ in range(80):\n" +
                "    if os.path.exists(db_path):\n" +
                "        try:\n" +
                "            db_uri = db_path.replace('\\\\\\\\', '/').replace('\\\\', '/')\n" +
                "            conn = sqlite3.connect(f'file:{db_uri}?mode=ro', uri=True, timeout=1.0)\n" +
                "            rows = conn.execute('SELECT idx, step_type, status, step_payload FROM steps ORDER BY idx ASC').fetchall()\n" +
                "            for idx, step_type, status, payload in rows:\n" +
                "                if idx in seen_steps:\n" +
                "                    continue\n" +
                "                seen_steps.add(idx)\n" +
                "                if step_type == 17:\n" +
                "                    strings = []\n" +
                "                    for match in re.finditer(rb'[\\\\x20-\\\\x7E]{4,}', payload):\n" +
                "                        try: strings.append(match.group(0).decode('ascii'))\n" +
                "                        except: pass\n" +
                "                    tool_name = None\n" +
                "                    args_json = None\n" +
                "                    known_tools = ['view_file', 'write_to_file', 'replace_file_content', 'multi_replace_file_content', 'run_command', 'grep_search', 'list_dir', 'read_file']\n" +
                "                    for s in strings:\n" +
                "                        if s in known_tools:\n" +
                "                            tool_name = s\n" +
                "                        elif s.startswith('{') and s.endswith('}'):\n" +
                "                            args_json = s\n" +
                "                    if tool_name:\n" +
                "                        target_info = ''\n" +
                "                        if args_json:\n" +
                "                            try:\n" +
                "                                args = json.loads(args_json)\n" +
                "                                target_path = args.get('TargetFile') or args.get('AbsolutePath') or args.get('CommandLine') or args.get('SearchPath') or args.get('DirectoryPath')\n" +
                "                                if target_path:\n" +
                "                                    if tool_name == 'run_command':\n" +
                "                                        target_info = f' ({target_path[:40]}...)'\n" +
                "                                    else:\n" +
                "                                        target_info = f' ({os.path.basename(target_path)})'\n" +
                "                            except: pass\n" +
                "                        print(f'PROGRESS: AI führt Tool aus: {tool_name}{target_info}', flush=True)\n" +
                "                elif step_type == 15 and status == 5:\n" +
                "                    print('PROGRESS: AI analysiert Änderungen und denkt nach...', flush=True)\n" +
                "            rows_final = conn.execute('SELECT idx, step_payload FROM steps WHERE step_type=15 AND status=3').fetchall()\n" +
                "            if rows_final:\n" +
                "                payload = rows_final[-1][1]\n" +
                "                txt = get_text(payload)\n" +
                "                if txt:\n" +
                "                    conn.close()\n" +
                "                    break\n" +
                "            conn.close()\n" +
                "        except Exception: pass\n" +
                "    time.sleep(0.5)\n\n" +
                "if txt:\n" +
                "    print('PROGRESS: Commit-Message empfangen, schließe Chat...', flush=True)\n" +
                "    convo_pb_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{convo_id}.pb')\n" +
                "    try:\n" +
                "        with open(convo_pb_path, 'wb') as f: f.write(b'')\n" +
                "    except: pass\n" +
                "    ls_address = os.environ.get('ANTIGRAVITY_LS_ADDRESS', '')\n" +
                "    csrf_token = os.environ.get('ANTIGRAVITY_CSRF_TOKEN', '')\n" +
                "    if ls_address:\n" +
                "        try:\n" +
                "            import urllib.request\n" +
                "            uuidBytes = convo_id.encode('utf-8')\n" +
                "            body = bytearray(5 + 2 + len(uuidBytes))\n" +
                "            body[0] = 0\n" +
                "            length = 2 + len(uuidBytes)\n" +
                "            body[1] = (length >> 24) & 0xff\n" +
                "            body[2] = (length >> 16) & 0xff\n" +
                "            body[3] = (length >> 8) & 0xff\n" +
                "            body[4] = length & 0xff\n" +
                "            body[5] = 0x0a\n" +
                "            body[6] = len(uuidBytes)\n" +
                "            body[7:] = uuidBytes\n" +
                "            req = urllib.request.Request(\n" +
                "                f'http://{ls_address}/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory',\n" +
                "                data=bytes(body),\n" +
                "                headers={\n" +
                "                    'content-type': 'application/grpc-web+proto',\n" +
                "                    'x-grpc-web': '1',\n" +
                "                    'x-codeium-csrf-token': csrf_token\n" +
                "                },\n" +
                "                method='POST'\n" +
                "            )\n" +
                "            with urllib.request.urlopen(req) as response: pass\n" +
                "        except: pass\n" +
                "    time.sleep(1.5)\n" +
                "    for suffix in ['', '-shm', '-wal']:\n" +
                "        fpath = db_path + suffix\n" +
                "        if os.path.exists(fpath):\n" +
                "            try: os.remove(fpath)\n" +
                "            except: pass\n" +
                "    if os.path.exists(convo_pb_path):\n" +
                "        try: os.remove(convo_pb_path)\n" +
                "        except: pass\n" +
                "    print('PROGRESS: Bereinigung abgeschlossen.', flush=True)\n" +
                "    out_data = {'commitMessage': txt.strip(), 'convoId': convo_id}\n" +
                "    print(json.dumps(out_data))\n" +
                "    sys.exit(0)\n" +
                "for suffix in ['', '-shm', '-wal']:\n" +
                "    fpath = db_path + suffix\n" +
                "    if os.path.exists(fpath):\n" +
                "        try: os.remove(fpath)\n" +
                "        except: pass\n" +
                "print('ERROR: Timeout waiting for response')\n" +
                "sys.exit(1)\n";

            fs_std.writeFileSync(tempScriptPath, pythonCode, 'utf-8');

            let commitMessage = '';
            let convoId = '';

            let lsAddress = '';
            try {
                const languageServer = require('./languageServer');
                const lsPort = languageServer.getLsPort();
                if (lsPort) {
                    lsAddress = `127.0.0.1:${lsPort + 1}`;
                }
            } catch (e) {
                console.error('[AMS IPC Git] Failed to determine LS Port:', e);
            }

            const envCopy = Object.assign({}, process.env);
            envCopy.ANTIGRAVITY_DATA_DIR = profileDataPath();
            if (lsAddress) {
                envCopy.ANTIGRAVITY_LS_ADDRESS = lsAddress;
            }
            const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN;
            if (finalCsrf) {
                envCopy.ANTIGRAVITY_CSRF_TOKEN = finalCsrf;
            }

            try {
                const { spawn } = require('child_process');
                console.log('[AMS IPC Git] Spawning Python:', getPythonPath(), tempScriptPath);
                const child = spawn(getPythonPath(), [tempScriptPath], { env: envCopy });
                console.log('[AMS IPC Git] Child PID:', child.pid);

                let stdoutData = '';
                let stderrData = '';
                const sender = event.sender;

                child.stdout.on('data', (data) => {
                    const lines = data.toString().split('\n');
                    lines.forEach(line => {
                        const trimmed = line.trim();
                        if (trimmed.startsWith('PROGRESS:')) {
                            const progressMsg = trimmed.replace('PROGRESS:', '').trim();
                            try {
                                sender.send('git:generate-commit-progress', progressMsg);
                            } catch (e) {
                                console.error('[AMS IPC Git] Failed to send progress:', e);
                            }
                        } else if (trimmed) {
                            stdoutData += line + '\n';
                        }
                    });
                });

                child.stderr.on('data', (data) => {
                    stderrData += data.toString();
                });

                const exitCode = await new Promise((resolve, reject) => {
                    const killTimer = setTimeout(() => {
                        try { child.kill('SIGTERM'); } catch(e) {}
                        setTimeout(() => { try { child.kill('SIGKILL'); } catch(e) {} }, 2000);
                        reject(new Error('Python script timed out after 120 seconds'));
                    }, 120000);
                    child.on('close', (code) => {
                        clearTimeout(killTimer);
                        resolve(code);
                    });
                    child.on('error', (err) => {
                        clearTimeout(killTimer);
                        reject(err);
                    });
                });

                if (exitCode !== 0 || stdoutData.trim().startsWith('ERROR:')) {
                    throw new Error(stdoutData + '\n' + stderrData);
                }

                const parsedResult = JSON.parse(stdoutData.trim());
                commitMessage = parsedResult.commitMessage || '';
                convoId = parsedResult.convoId ? temporaryConversationIds.register(parsedResult.convoId) : '';
            } finally {
                try {
                    fs_std.unlinkSync(tempScriptPath);
                } catch (e) {}
            }

            commitMessage = commitMessage.replace(/^['"`]+|['"`]+$/g, '').trim();
            commitMessage = commitMessage.replace(/^conventional commit:\s*/i, '').trim();

            return { status: 'success', commitMessage, convoId };
        } catch (err) {
            console.error('[AMS IPC Git] git:generate-commit-msg failed:', err);
            const detailedMessage = err.message + '\nStdout: ' + (err.stdout || '') + '\nStderr: ' + (err.stderr || '');
            return { status: 'error', message: detailedMessage };
        }
    });

    electron_1.ipcMain.handle('git:consolidate-memory', async (event, conversationId, csrfToken) => {
        try {
            validateOrigin(event);
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const agentapiPath = profileDataPath('bin', 'agentapi.bat');
            if (!fs_std.existsSync(agentapiPath)) {
                return { status: 'error', message: 'agentapi.bat wurde nicht gefunden.' };
            }

            const tempScriptPath = path.join(os.tmpdir(), `consolidate_${Date.now()}.py`);
            const pythonCode =
                "import subprocess\n" +
                "import json\n" +
                "import time\n" +
                "import os\n" +
                "import sqlite3\n" +
                "import sys\n" +
                "import re\n\n" +
                "sys.stdout.reconfigure(encoding='utf-8')\n" +
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
                "convo_id = \"" + conversationId + "\"\n" +
                "db_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{convo_id}.db')\n" +
                "if not os.path.exists(db_path):\n" +
                "    db_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{convo_id}.db')\n\n" +
                "history_entries = []\n" +
                "project_id = ''\n" +
                "workspace_id = ''\n\n" +
                "if os.path.exists(db_path):\n" +
                "    try:\n" +
                "        conn = sqlite3.connect(db_path)\n" +
                "        row = conn.execute(\"SELECT data FROM trajectory_metadata_blob WHERE id = 'main'\").fetchone()\n" +
                "        if row:\n" +
                "            blob = row[0]\n" +
                "            ascii_text = ''.join(chr(b) if 32 <= b <= 126 else '\\\\x00' for b in blob)\n" +
                "            uuids = re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', ascii_text, re.IGNORECASE)\n" +
                "            if len(uuids) >= 2:\n" +
                "                workspace_id = uuids[0]\n" +
                "                project_id = uuids[1]\n" +
                "            elif len(uuids) == 1:\n" +
                "                workspace_id = uuids[0]\n" +
                "                project_id = uuids[0]\n" +
                "        rows = conn.execute(\"SELECT step_type, step_payload FROM steps WHERE step_type IN (14, 15) AND status = 3 ORDER BY idx DESC LIMIT 10\").fetchall()\n" +
                "        rows.reverse()\n" +
                "        for step_type, payload in rows:\n" +
                "            txt = get_text_from_payload(payload, step_type)\n" +
                "            if txt:\n" +
                "                role = 'User' if step_type == 14 else 'Assistant'\n" +
                "                history_entries.append(f'{role}: {txt}')\n" +
                "        conn.close()\n" +
                "    except Exception as e: pass\n\n" +
                "if project_id: os.environ['ANTIGRAVITY_PROJECT_ID'] = project_id\n" +
                "if workspace_id: os.environ['ANTIGRAVITY_WORKSPACE_ID'] = workspace_id\n\n" +
                "convo_text = '\\n\\n'.join(history_entries)\n" +
                "prompt = ( \n" +
                "    'Du bist ein Programmier-Assistent, der das Langzeitgedächtnis eines Entwicklers pflegt.\\n' \n" +
                "    'Analysiere den folgenden Verlauf der Konversation. Bestimme, ob darin wichtige technische Erkenntnisse (z.B. Fehlerbehebungen, Escaping-Tricks, CSS-Verhalten, spezielle Parameter) oder neue Benutzerpräferenzen erarbeitet wurden.\\n' \n" +
                "    'Falls ja, formuliere einen kurzen, prägnanten Bulletpoint im Markdown-Format (max. 150 Zeichen), der diese Erkenntnis beschreibt.\\n' \n" +
                "    'Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt. Verwende keine Backticks oder Markdown-Formatting um das JSON herum. Das JSON muss exakt dieses Schema haben:\\n' \n" +
                "    '{\\n' \n" +
                "    '  \\\"found\\\": true,\\n' \n" +
                "    '  \\\"type\\\": \\\"lesson_learned\\\" oder \\\"preference\\\",\\n' \n" +
                "    '  \\\"proposed_text\\\": \\\"Der Bulletpoint-Text\\\"\\n' \n" +
                "    '}\\n' \n" +
                "    'Wenn keine nennenswerten Erkenntnisse oder Präferenzen erarbeitet wurden, antworte exakt mit:\\n' \n" +
                "    '{\\n' \n" +
                "    '  \\\"found\\\": false\\n' \n" +
                "    '}\\n\\n' \n" +
                "    'Verlauf der Konversation:\\n' \n" +
                "    ) + convo_text\n\n" +
                "ls_exe = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local'), 'Programs', 'Antigravity', 'resources', 'bin', 'language_server.exe')\n" +
                "cmd = [ls_exe, 'agentapi', 'new-conversation', '--model=flash', prompt]\n" +
                "res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', cwd=os.path.expanduser('~'))\n" +
                "try:\n" +
                "    out = json.loads(res.stdout)\n" +
                "    new_convo_id = out['response']['newConversation']['conversationId']\n" +
                "except Exception as e:\n" +
                "    print(json.dumps({'found': False, 'error': 'Failed to start conversation'}))\n" +
                "    sys.exit(0)\n\n" +
                "new_db_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{new_convo_id}.db')\n" +
                "txt = None\n" +
                "for _ in range(40):\n" +
                "    if os.path.exists(new_db_path):\n" +
                "        try:\n" +
                "            conn = sqlite3.connect(new_db_path)\n" +
                "            rows = conn.execute('SELECT idx, step_payload FROM steps WHERE step_type=15 AND status=3').fetchall()\n" +
                "            if rows:\n" +
                "                payload = rows[-1][1]\n" +
                "                txt = get_text_from_payload(payload, 15)\n" +
                "                if txt:\n" +
                "                    conn.close()\n" +
                "                    break\n" +
                "        except Exception: pass\n" +
                "    time.sleep(0.5)\n\n" +
                "if txt:\n" +
                "    convo_pb_path = os.path.join(os.environ.get('ANTIGRAVITY_DATA_DIR', os.path.expanduser('~/.gemini/antigravity')), 'conversations', f'{new_convo_id}.pb')\n" +
                "    try:\n" +
                "        with open(convo_pb_path, 'wb') as f: f.write(b'')\n" +
                "    except: pass\n" +
                "    ls_address = os.environ.get('ANTIGRAVITY_LS_ADDRESS', '')\n" +
                "    csrf_token = os.environ.get('ANTIGRAVITY_CSRF_TOKEN', '')\n" +
                "    if ls_address:\n" +
                "        try:\n" +
                "            import urllib.request\n" +
                "            uuidBytes = new_convo_id.encode('utf-8')\n" +
                "            body = bytearray(5 + 2 + len(uuidBytes))\n" +
                "            body[0] = 0\n" +
                "            length = 2 + len(uuidBytes)\n" +
                "            body[1] = (length >> 24) & 0xff\n" +
                "            body[2] = (length >> 16) & 0xff\n" +
                "            body[3] = (length >> 8) & 0xff\n" +
                "            body[4] = length & 0xff\n" +
                "            body[5] = 0x0a\n" +
                "            body[6] = len(uuidBytes)\n" +
                "            body[7:] = uuidBytes\n" +
                "            req = urllib.request.Request(\n" +
                "                f'http://{ls_address}/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory',\n" +
                "                data=bytes(body),\n" +
                "                headers={\n" +
                "                    'content-type': 'application/grpc-web+proto',\n" +
                "                    'x-grpc-web': '1',\n" +
                "                    'x-codeium-csrf-token': csrf_token\n" +
                "                },\n" +
                "                method='POST'\n" +
                "            )\n" +
                "            with urllib.request.urlopen(req) as response: pass\n" +
                "        except: pass\n" +
                "    time.sleep(1.5)\n" +
                "    for suffix in ['', '-shm', '-wal']:\n" +
                "        fpath = new_db_path + suffix\n" +
                "        if os.path.exists(fpath):\n" +
                "            try: os.remove(fpath)\n" +
                "            except: pass\n" +
                "    if os.path.exists(convo_pb_path):\n" +
                "        try: os.remove(convo_pb_path)\n" +
                "        except: pass\n" +
                "    txt_clean = txt.strip()\n" +
                "    if txt_clean.startswith('```json'):\n" +
                "        txt_clean = txt_clean.split('```json')[1].split('```')[0].strip()\n" +
                "    elif txt_clean.startswith('```'):\n" +
                "        txt_clean = txt_clean.split('```')[1].split('```')[0].strip()\n" +
                "    try:\n" +
                "        parsed = json.loads(txt_clean)\n" +
                "        parsed['convoId'] = new_convo_id\n" +
                "        print(json.dumps(parsed))\n" +
                "    except Exception as parse_err:\n" +
                "        print(json.dumps({'found': True, 'type': 'lesson_learned', 'proposed_text': txt_clean, 'convoId': new_convo_id}))\n" +
                "    sys.exit(0)\n" +
                "for suffix in ['', '-shm', '-wal']:\n" +
                "    fpath = new_db_path + suffix\n" +
                "    if os.path.exists(fpath):\n" +
                "        try: os.remove(fpath)\n" +
                "        except: pass\n" +
                "print(json.dumps({'found': False, 'error': 'Timeout waiting for response'}))\n" +
                "sys.exit(0)\n";

            fs_std.writeFileSync(tempScriptPath, pythonCode, 'utf-8');

            let lsAddress = '';
            try {
                const languageServer = require('./languageServer');
                const lsPort = languageServer.getLsPort();
                if (lsPort) {
                    lsAddress = `127.0.0.1:${lsPort + 1}`;
                }
            } catch (e) {}

            const envCopy = Object.assign({}, process.env);
            envCopy.ANTIGRAVITY_DATA_DIR = profileDataPath();
            if (lsAddress) {
                envCopy.ANTIGRAVITY_LS_ADDRESS = lsAddress;
            }
            const finalCsrf = csrfToken || process.env.ANTIGRAVITY_CSRF_TOKEN;
            if (finalCsrf) {
                envCopy.ANTIGRAVITY_CSRF_TOKEN = finalCsrf;
            }

            let result = { found: false };
            try {
                const { stdout, stderr } = await execFilePromise(
                    getPythonPath(),
                    [tempScriptPath],
                    { env: envCopy, windowsHide: true, timeout: 30000, maxBuffer: 10 * 1024 * 1024 },
                );
                result = JSON.parse(stdout.trim());
            } catch (err) {
                console.error('[AMS IPC Memory] Memory consolidation failed:', err);
                result = { found: false, error: err.message };
            } finally {
                try {
                    fs_std.unlinkSync(tempScriptPath);
                } catch (e) {}
            }

            if (result && result.convoId) {
                result.convoId = temporaryConversationIds.register(result.convoId);
            }
            return result;
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
            const os = require('os');
            const path = require('path');
            const fs_std = require('fs');

            const safeConvoId = temporaryConversationIds.require(convoId);
            if (typeof csrfToken !== 'string' || csrfToken.length === 0 || csrfToken.length > 512) {
                throw new Error('Invalid CSRF token.');
            }
            const conversationsRoot = profileDataPath('conversations');
            const convoPbPath = path.join(conversationsRoot, safeConvoId + '.pb');
            const convoDbPath = path.join(conversationsRoot, safeConvoId + '.db');
            if (!isPathInside(conversationsRoot, convoPbPath) || !isPathInside(conversationsRoot, convoDbPath)) {
                throw new Error('Conversation path escapes the conversation store.');
            }

            let lsAddress = '';
            try {
                const languageServer = require('./languageServer');
                const lsPort = languageServer.getLsPort();
                if (lsPort) {
                    lsAddress = '127.0.0.1:' + String(lsPort + 1);
                }
            } catch (e) {
                console.error('[AMS IPC Git] Failed to determine LS Port:', e);
            }

            if (!lsAddress) {
                return { status: 'error', message: 'Failed to determine LS Port.' };
            }

            const uuidBytes = Buffer.from(safeConvoId, 'utf-8');
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

            const http = require('http');
            const deletePromise = () => new Promise((resolve, reject) => {
                const req = http.request({
                    hostname: '127.0.0.1',
                    port: parseInt(lsAddress.split(':')[1]),
                    path: '/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory',
                    method: 'POST',
                    headers: {
                        'content-type': 'application/grpc-web+proto',
                        'x-grpc-web': '1',
                        'x-codeium-csrf-token': csrfToken,
                        'content-length': String(body.length),
                    }
                }, (res) => {
                    const responseChunks = [];
                    res.on('data', (chunk) => responseChunks.push(Buffer.from(chunk)));
                    res.on('error', reject);
                    res.on('end', () => {
                        const httpStatus = Number(res.statusCode || 0);
                        const responseBody = Buffer.concat(responseChunks);
                        if (httpStatus !== 200) {
                            reject(new Error('Temporary conversation deletion returned HTTP ' + String(httpStatus) + '.'));
                            return;
                        }
                        const grpcStatus = extractGrpcStatus(responseBody, res.headers, res.trailers);
                        if (grpcStatus !== 0) {
                            reject(new Error('Temporary conversation deletion returned gRPC status ' + String(grpcStatus) + '.'));
                            return;
                        }
                        resolve({ httpStatus, grpcStatus });
                    });
                });
                req.setTimeout(10000, () => req.destroy(new Error('Temporary conversation deletion timed out.')));
                req.on('error', reject);
                req.write(body);
                req.end();
            });

            const deleteResult = await deletePromise();
            temporaryConversationIds.delete(safeConvoId);

            const localFiles = [
                convoPbPath,
                convoDbPath,
                convoDbPath + '-shm',
                convoDbPath + '-wal',
            ].filter((candidate) => fs_std.existsSync(candidate));
            const cleanupErrors = [];
            let quarantinedFiles = 0;
            if (localFiles.length) {
                const quarantineRoot = profileDataPath('scratch',
                    'deleted-temp-conversations',
                );
                const quarantineDir = path.join(quarantineRoot, safeConvoId + '-' + String(Date.now()));
                if (!isPathInside(quarantineRoot, quarantineDir)) {
                    throw new Error('Temporary conversation quarantine path escaped its root.');
                }
                fs_std.mkdirSync(quarantineDir, { recursive: true });
                for (const localFile of localFiles) {
                    const quarantineFile = path.join(quarantineDir, path.basename(localFile));
                    try {
                        fs_std.renameSync(localFile, quarantineFile);
                        quarantinedFiles += 1;
                    } catch (error) {
                        cleanupErrors.push(path.basename(localFile) + ': ' + error.message);
                    }
                }
            }

            console.log('[AMS IPC Git] Deleted registered temporary conversation ' + safeConvoId + ' via confirmed gRPC status 0.');
            return {
                status: cleanupErrors.length ? 'warning' : 'success',
                grpcStatus: deleteResult.grpcStatus,
                quarantinedFiles,
                cleanupErrors,
            };
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
