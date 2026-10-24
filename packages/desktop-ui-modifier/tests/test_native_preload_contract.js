"use strict";

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const exposed = new Map();
const calls = [];
const handlers = new Map();
const sender = { id: 42, getURL: () => 'http://127.0.0.1:1234/', once() {} };
const window = { webContents: sender };
let selectedWindow;
let connectedDistro;
const electron = {
    contextBridge: { exposeInMainWorld: (name, api) => exposed.set(name, api) },
    ipcRenderer: {
        invoke: async (channel, ...args) => {
            calls.push([channel, ...args]);
            return channel === 'security:get-token' ? 'test-token' : undefined;
        },
    },
    ipcMain: { handle: (channel, callback) => {
        assert.ok(!handlers.has(channel), `Duplicate handler: ${channel}`);
        handlers.set(channel, callback);
    } },
    BrowserWindow: { fromWebContents: (contents) => contents === sender ? window : null },
    Menu: { buildFromTemplate: (template) => ({
        popup: ({ window: target }) => {
            selectedWindow = target;
            template[0].click();
        },
        closePopup() {},
    }) },
    webUtils: {
        getPathForFile: (file) => (file && file.path) ? file.path : '/mock/file/path',
    },
    webContents: {
        fromId: (id) => id === 77 ? {
            isDestroyed: () => false,
            getType: () => 'webview',
            hostWebContents: { id: sender.id },
            executeJavaScriptInIsolatedWorld: async (worldId, scripts, userGesture) => ({
                worldId,
                code: scripts[0].code,
                userGesture,
            }),
        } : null,
    },
};

vm.runInNewContext(fs.readFileSync(path.join(root, 'src/ui/preload_header.txt'), 'utf8'), {
    exports: {},
    require: (name) => {
        assert.equal(name, 'electron');
        return electron;
    },
});

const dependencies = {
    electron,
    'electron-updater': {},
    './types': {},
    './updater': {},
    'electron-log/main': { error() {} },
    './customScheme': {},
    './tray': {},
    './ideInstall/constants': {},
    './wsl': {
        isWslAvailable: () => true,
        getActiveWslDistro: () => 'Ubuntu',
        listWslDistros: async () => [{ name: 'Ubuntu', isDefault: true }],
    },
    './menu': { relaunchWithWslDistro: (distro) => { connectedDistro = distro; } },
    './paths': { getAppDataDir: () => 'C:/Users/Test/.gemini/antigravity' },
    './amsMainBootstrap': { getProfileInfo: () => ({ profile: 'default' }), hardenStorageManager() {} },
    './languageServer': { getLsPort: () => 1234 },
    './constants': { WINDOW_ORIGIN: 'http://127.0.0.1' },
};
const moduleExports = {};
vm.runInNewContext(fs.readFileSync(path.join(root, 'src/ipcHandlers.js'), 'utf8'), {
    exports: moduleExports,
    process,
    Buffer,
    URL,
    console,
    setImmediate,
    require: (name) => {
        if (Object.hasOwn(dependencies, name)) return dependencies[name];
        if (name.startsWith('./')) return require(path.join(root, 'src', name));
        return require(name);
    },
});
moduleExports.registerIpcHandlers({});

async function run() {
    const native = exposed.get('electronNative');
    await native.showContextMenu([{ id: 'copy', label: 'Copy' }]);
    await native.closeContextMenu();
    await native.executeJavaScriptInIsolatedWorld(77, 1000, '1 + 1');
    await exposed.get('wsl').getState();
    await exposed.get('wsl').connect('Ubuntu');
    for (const channel of ['window:show-context-menu', 'window:close-context-menu', 'webview:execute-js-isolated-world', 'wsl:get-state', 'wsl:connect']) {
        assert.ok(calls.some(([called]) => called === channel), `Preload did not call ${channel}`);
        assert.ok(handlers.has(channel), `Main process did not register ${channel}`);
    }
    const isolatedRes = await handlers.get('webview:execute-js-isolated-world')({ sender: { ...sender, isDestroyed: () => false } }, 77, 1000, '1 + 1');
    assert.deepEqual(isolatedRes, { worldId: 1000, code: '1 + 1', userGesture: false });
    const selection = await handlers.get('window:show-context-menu')({ sender }, [{ id: 'copy', label: 'Copy' }]);
    assert.equal(selection, 'copy');
    assert.equal(selectedWindow, window, 'The menu must belong to the requesting window');
    const state = await handlers.get('wsl:get-state')({ sender });
    assert.equal(state.activeDistro, 'Ubuntu');
    assert.equal(state.distros[0].name, 'Ubuntu');
    handlers.get('wsl:connect')({ sender }, 'Ubuntu');
    assert.equal(connectedDistro, 'Ubuntu');
    await assert.rejects(
        handlers.get('window:show-context-menu')({ sender: { getURL: () => 'https://untrusted.example/' } }, []),
        /Security check failed/,
    );
    assert.equal(typeof native.hubRequest, 'function');
    assert.equal(typeof native.openBrain, 'function');
    assert.equal(typeof native.getPathForFile, 'function');
    assert.equal(typeof native.getAiConfig, 'function');
    assert.equal(typeof native.saveAiConfig, 'function');
    assert.equal(typeof native.testAiConnection, 'function');
    await native.getAiConfig();
    await native.saveAiConfig({ mode: 'auto' });
    await native.testAiConnection({ mode: 'off' }, 'csrf-test');
    for (const channel of ['ai:get-config', 'ai:save-config', 'ai:test-connection']) {
        assert.ok(calls.some(([called]) => called === channel), `Preload did not call ${channel}`);
        assert.ok(handlers.has(channel), `Main process did not register ${channel}`);
    }
    const aiCfgRes = await handlers.get('ai:get-config')({ sender });
    assert.equal(aiCfgRes.status, 'success');
    assert.ok(aiCfgRes.config && typeof aiCfgRes.config.mode === 'string');
    const aiTestOffRes = await handlers.get('ai:test-connection')({ sender }, { mode: 'off' }, 'csrf-test');
    assert.equal(aiTestOffRes.status, 'success');
    assert.equal(aiTestOffRes.provider, 'off');
    assert.equal(native.getPathForFile({ path: '/tmp/test-file.txt' }), '/tmp/test-file.txt');
    console.log('native preload, context menu and WSL contract tests passed');
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
