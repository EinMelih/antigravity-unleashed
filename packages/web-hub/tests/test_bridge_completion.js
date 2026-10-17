const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function stepNode(text, status, running, reviewCard = '') {
  const segment = {memoizedProps: {segment: {steps: [{status}]}, isRunning: running}};
  const step = {memoizedProps: {status, step: {}}, return: segment};
  return {
    textContent: text,
    __reactFiber$fixture: {memoizedProps: {}, return: step},
    cloneNode() {
      const clone = {textContent: text + reviewCard};
      clone.querySelectorAll = selector => reviewCard && selector.includes('turn-cards-container') ? [{remove() { clone.textContent = text; }}] : [];
      return clone;
    },
  };
}

function article(label, planners = [], steps = [], legacyText = '') {
  return {
    textContent: legacyText,
    getAttribute: name => name === 'aria-label' ? label : null,
    querySelector: () => null,
    querySelectorAll: selector => selector === '[data-testid="planner-response-text"]' ? planners : selector === '[data-testid$="-step"]' ? steps : [],
    cloneNode: () => ({textContent: legacyText, querySelectorAll: () => []}),
  };
}

let articles = [];
const context = {window: {}, document: {querySelectorAll: () => articles}, console: {log() {}}, URL};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../src/bridge.js'), 'utf8'), context);
const bridge = context.window.__agBridge;

articles = [article('User message', [], [], 'This is the request')];
assert.strictEqual(bridge.pollResponse(0, '').started, false, 'A user echo is not an assistant response');

articles = [article('User message'), article('Agent response', [stepNode('OK', 3, false)])];
let result = bridge.pollResponse(0, '');
assert.strictEqual(result.text, 'OK');
assert.strictEqual(result.finished, true, 'Completed native text needs no feedback button');
assert.strictEqual(result.native_observed, true);

articles = [article('User message'), article('Agent response', [stepNode('C:\\API\\workspace\\file.txt', 3, false, '1 file changed+3-0')])];
assert.strictEqual(bridge.pollResponse(0, '').text, 'C:\\API\\workspace\\file.txt', 'Review-card counters are not model response content');

articles = [article('User message'), article('Agent response', [stepNode('Partial answer', 2, true)])];
result = bridge.pollResponse(0, '');
assert.strictEqual(result.finished, false, 'A streaming answer must not finish early');
assert.strictEqual(result.is_running, true);

articles = [article('User message'), article('Agent response', [stepNode('Before the command', 3, false)], [stepNode('Waiting for user input', 9, false)], 'Thoughts and command contents')];
result = bridge.pollResponse(0, '');
assert.strictEqual(result.finished, false);
assert.strictEqual(result.requires_user_input, true);
assert.strictEqual(result.text, 'Before the command', 'Tool/thinking content is not an answer');

articles = [article('User message'), article('Agent response', [], [stepNode('Command awaiting approval', 9, false)])];
result = bridge.pollResponse(0, '');
assert.strictEqual(result.text, '');
assert.strictEqual(result.requires_user_input, true);
assert.strictEqual(result.finished, false);

console.log('native completion and approval-gate tests passed');
