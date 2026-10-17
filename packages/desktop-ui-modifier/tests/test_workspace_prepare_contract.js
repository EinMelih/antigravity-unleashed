"use strict";

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const handlers = fs.readFileSync(path.join(root, 'src', 'ipcHandlers.js'), 'utf8');
const preloadHeader = fs.readFileSync(path.join(root, 'src', 'ui', 'preload_header.txt'), 'utf8');

assert.match(handlers, /handle\('dialog:prepare-workspace', async \(event, token, workspacePath\)/);
assert.match(handlers, /validateToken\(event, token\)/);
assert.match(handlers, /verifyHubWorkspacePath\(resolvedPath\)/);
assert.match(handlers, /path: '\/api\/internal\/workspace-authorization'/);
assert.match(handlers, /payload\.authorized !== true/);
assert.match(handlers, /preparedWorkspaceLeases\.issue\(event\.sender\.id, resolvedPath\)/);
assert.match(handlers, /preparedWorkspaceLeases\.consume\(event\.sender\.id\)/);
assert.doesNotMatch(handlers, /preparedWorkspacePaths\s*=\s*new Map/);

assert.match(
    preloadHeader,
    /prepareWorkspaceOpen: \(workspacePath\) => securityTokenPromise\.then\(\(token\) => electron_1\.ipcRenderer\.invoke\('dialog:prepare-workspace', token, workspacePath\)\)/,
);
assert.doesNotMatch(
    preloadHeader,
    /invoke\('dialog:prepare-workspace', workspacePath\)/,
);

console.log('workspace prepare contract tests passed');
