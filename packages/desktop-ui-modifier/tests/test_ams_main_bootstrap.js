const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.resolve(__dirname, '../src/amsMainBootstrap.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const exported = {};
const assignedUserDataPaths = [];
const fakeProcess = {
    env: {},
    platform: 'win32',
    cwd: () => 'C:\\API\\workspace',
};
const fakeApp = {
    getPath: () => assignedUserDataPaths.at(-1) || 'C:\\Users\\Test\\AppData\\Roaming\\Antigravity',
    setPath: (name, value) => { if (name === 'userData') assignedUserDataPaths.push(value); },
};
const context = {
    URL,
    console: {
        log: () => {},
        warn: () => {},
        error: () => {},
    },
    exports: exported,
    module: { exports: exported },
    process: fakeProcess,
    require: (id) => {
        if (id === 'electron') return { app: fakeApp };
        if (id === 'child_process') return { spawn: () => { throw new Error('unexpected spawn'); } };
        if (id === 'os') return { homedir: () => fakeProcess.env.USERPROFILE || require('os').homedir() };
        return require(id);
    },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

fakeProcess.env.ANTIGRAVITY_PROFILE = '../../unsafe';
context.exports.configureProfile({ getAppDataDirName: () => 'Antigravity' });
assert.strictEqual(assignedUserDataPaths.length, 0);

fakeProcess.env.ANTIGRAVITY_PROFILE = 'review_1';
const pathsModule = { getAppDataDirName: () => 'Antigravity' };
context.exports.configureProfile(pathsModule);
assert.strictEqual(assignedUserDataPaths.length, 1);
assert.ok(assignedUserDataPaths[0].endsWith('Antigravity-review_1'));
assert.strictEqual(pathsModule.getAppDataDirName(), 'Antigravity-review_1');

fakeProcess.env.ANTIGRAVITY_PROFILE = 'api';
assert.throws(() => context.exports.configureProfile({ getAppDataDirName: () => 'antigravity' }), /independent process home/);
fakeProcess.env.ANTIGRAVITY_PROFILE_HOME = 'C:\\API\\home';
fakeProcess.env.USERPROFILE = fakeProcess.env.ANTIGRAVITY_PROFILE_HOME;
const apiPaths = {
    getAppDataDirName: () => 'antigravity',
    getAppDataDir: () => path.join(require('os').homedir(), '.gemini', 'antigravity'),
    getSettingsPbPath: () => path.join(require('os').homedir(), '.gemini', 'config', 'config.json'),
};
context.exports.configureProfile(apiPaths);
assert.ok(apiPaths.getAppDataDir().endsWith('antigravity-api'), 'API state must have its own directory');
assert.strictEqual(apiPaths.getSettingsPbPath(), path.join(fakeProcess.env.USERPROFILE, '.gemini', 'config', 'config.json'), 'Native API settings must resolve inside its own home');
const apiInfo = context.exports.getProfileInfo(apiPaths);
assert.strictEqual(apiInfo.profile, 'api');
assert.strictEqual(apiInfo.profile_contract_version, 2);
assert.ok(apiInfo.user_data_dir.endsWith('Antigravity-api'));
assert.strictEqual(apiInfo.app_data_dir, apiPaths.getAppDataDir());
assert.strictEqual(apiInfo.home_dir, fakeProcess.env.USERPROFILE);
assert.strictEqual(apiInfo.process_cwd, fakeProcess.cwd());

const baseUrl = 'http://127.0.0.1:43123/';
const restored = context.exports.resolveInitialWindowUrl(baseUrl, {
    getItems: () => ({ antigravity_last_chat_path: '/c/abc?view=review' }),
});
assert.strictEqual(restored, 'http://127.0.0.1:43123/c/abc?view=review');

const rejected = context.exports.resolveInitialWindowUrl(baseUrl, {
    getItems: () => ({ antigravity_last_chat_path: '//evil.example/steal' }),
});
assert.strictEqual(rejected, baseUrl);

let created;
const fakeWindow = {
    webContents: {
        setBackgroundThrottling: (value) => {
            fakeWindow.backgroundThrottling = value;
        },
    },
    hide: () => {
        fakeWindow.hidden = true;
    },
    once: (event, callback) => {
        fakeWindow.readyEvent = event;
        fakeWindow.readyCallback = callback;
    },
    isDestroyed: () => false,
    showInactive: () => {},
    minimize: () => {},
};
fakeProcess.env.REPACK_TRIGGER_CHAT_ID = 'abc_123';
const triggerWindow = context.exports.openRepackTriggerWindow(
    baseUrl,
    { marker: 'storage' },
    (url, storageManager) => {
        created = { url, storageManager };
        return fakeWindow;
    },
);
assert.strictEqual(triggerWindow, fakeWindow);
assert.strictEqual(created.url, 'http://127.0.0.1:43123/c/abc_123');
assert.strictEqual(created.storageManager.marker, 'storage');
assert.strictEqual(fakeWindow.__antigravityWindowRole, 'duplicate');
assert.strictEqual(fakeWindow.backgroundThrottling, false);
assert.strictEqual(fakeWindow.hidden, true);
assert.strictEqual(fakeWindow.readyEvent, 'ready-to-show');

fakeProcess.env.REPACK_TRIGGER_CHAT_ID = '../unsafe';
assert.strictEqual(
    context.exports.openRepackTriggerWindow(baseUrl, {}, () => {
        throw new Error('invalid ID must not create a window');
    }),
    undefined,
);

console.log('amsMainBootstrap tests passed');
