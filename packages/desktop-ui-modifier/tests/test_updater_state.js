const assert = require('assert');
const { EventEmitter } = require('events');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.resolve(__dirname, '../src/updater.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const exported = {};
const states = [];
const autoUpdater = new EventEmitter();
autoUpdater.checkForUpdates = () => Promise.resolve();
autoUpdater.quitAndInstall = () => {};

const updateState = {
    Idle: 'idle',
    Disabled: 'disabled',
    CheckingForUpdates: 'checking for updates',
    AvailableForDownload: 'available for download',
    Downloading: 'downloading',
    Downloaded: 'downloaded',
    Updating: 'updating',
    Ready: 'ready',
};
const fakeElectron = {
    app: {
        isPackaged: true,
        getAppPath: () => 'C:\\Antigravity\\resources\\app.asar',
        getVersion: () => '2.9.1',
    },
    BrowserWindow: {
        getAllWindows: () => [{
            webContents: {
                send: (_channel, state) => states.push(state),
            },
        }],
        getFocusedWindow: () => null,
    },
    Menu: {
        getApplicationMenu: () => null,
    },
    dialog: {
        showMessageBox: () => Promise.resolve(),
    },
};
const fakeProcess = {
    platform: 'win32',
    arch: 'x64',
    env: {},
    pid: 123,
    execPath: 'C:\\Antigravity\\Antigravity.exe',
};
const context = {
    console: {
        log: () => {},
        warn: () => {},
        error: () => {},
    },
    exports: exported,
    module: { exports: exported },
    process: fakeProcess,
    __dirname: path.dirname(sourcePath),
    setTimeout: () => 1,
    setInterval: () => 2,
    clearInterval: () => {},
    require: (id) => {
        if (id === 'electron-updater') return { autoUpdater };
        if (id === 'electron') return fakeElectron;
        if (id === './types') return { UpdateState: updateState };
        if (id === './services/settingsService') {
            return {
                SettingKey: { AUTO_CHECK_FOR_UPDATES: 'autoCheckForUpdates' },
            };
        }
        if (id === 'child_process') return { spawn: () => ({ unref: () => {} }) };
        return require(id);
    },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

const settingsService = {
    getSetting: () => Promise.resolve(true),
    onSettingChanged: () => {},
};
context.exports.initAutoUpdater(false, settingsService);
assert.strictEqual(autoUpdater.autoDownload, true);
assert.strictEqual(autoUpdater.autoInstallOnAppQuit, true);
assert.strictEqual(autoUpdater.requestHeaders['x-app-version'], fakeElectron.app.getVersion());

autoUpdater.emit('update-available', {
    version: '3.0.0',
    releaseNotes: '- Faster startup',
    releaseDate: '2026-09-01T00:00:00.000Z',
    releaseName: 'September release',
});
autoUpdater.emit('download-progress', { percent: 50 });
autoUpdater.emit('update-downloaded', { version: '3.0.0' });

assert.strictEqual(states.length, 3);
assert.strictEqual(states[0].type, 'available for download');
assert.strictEqual(states[1].type, 'downloading');
assert.strictEqual(states[2].type, 'ready');
assert.strictEqual(states[1].update.releaseNotes, '- Faster startup');
assert.strictEqual(states[2].update.releaseName, 'September release');
assert.strictEqual(states[2].update.releaseDate, '2026-09-01T00:00:00.000Z');
assert.strictEqual(context.exports.getLastState().update.version, '3.0.0');

console.log('updater state tests passed');
