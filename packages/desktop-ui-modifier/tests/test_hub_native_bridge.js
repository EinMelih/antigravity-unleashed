"use strict";

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const handlers = fs.readFileSync(path.join(root, 'src', 'ipcHandlers.js'), 'utf8');
const bridge = fs.readFileSync(path.join(root, 'src', 'ui', 'antigravityHubBridge.js'), 'utf8');
const main = fs.readFileSync(path.join(root, 'src', 'ui', 'main.js'), 'utf8');
const dashboard = fs.readFileSync(path.join(root, 'src', 'ui', 'reviewsDashboard.js'), 'utf8');
const preloadHeader = fs.readFileSync(path.join(root, 'src', 'ui', 'preload_header.txt'), 'utf8');

assert.match(handlers, /handle\('hub:request', async \(event, token, operation, payload = \{\}\)/);
assert.match(handlers, /validateOrigin\(event\);\s*validateToken\(event, token\);/);
assert.match(handlers, /host: '127\.0\.0\.1'/);
assert.match(handlers, /operation === 'services:status'/);
assert.match(handlers, /operation === 'services:start'/);
assert.doesNotMatch(handlers, /['"]custom-models:/);
assert.doesNotMatch(handlers, /['"]codex:/);
assert.doesNotMatch(handlers, /host:\s*safePayload/);
assert.doesNotMatch(handlers, /path:\s*safePayload/);

assert.match(preloadHeader, /hubRequest: \(_token, operation, payload\) => securityTokenPromise\.then/);
assert.match(bridge, /getStatus: \(\) => amsHubCall\('services:status'\)/);
assert.match(bridge, /startServices: \(restart = false\) => amsHubCall\('services:start'/);
assert.match(bridge, /openHub: \(\) =>/);
assert.doesNotMatch(bridge, /Codex|Custom API|custom-model|OAuth|MutationObserver|agent-turn/i);
assert.doesNotMatch(main, /amsActiveExternalModel|codex-project|codex-sidecar|Custom API/);
assert.doesNotMatch(dashboard, /openCustomModels|Modell-Provider hinzufügen/);

console.log('native Hub-only bridge contract tests passed');
