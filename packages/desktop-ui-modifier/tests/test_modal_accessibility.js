const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

class FakeWindow {
    constructor() {
        this.listeners = new Map();
    }

    addEventListener(type, listener, capture = false) {
        const entries = this.listeners.get(type) || [];
        entries.push({ listener, capture });
        this.listeners.set(type, entries);
    }

    removeEventListener(type, listener, capture = false) {
        const entries = this.listeners.get(type) || [];
        this.listeners.set(type, entries.filter((entry) => entry.listener !== listener || entry.capture !== capture));
    }

    getComputedStyle(element) {
        return element.computedStyle;
    }

    dispatchKey(event) {
        for (const entry of [...(this.listeners.get('keydown') || [])]) entry.listener(event);
    }
}

class FakeElement {
    constructor(document, name) {
        this.ownerDocument = document;
        this.name = name;
        this.attributes = new Map();
        this.computedStyle = { display: 'block', visibility: 'visible' };
        this.focusable = [];
        this.descendants = new Set();
        this.disabled = false;
        this.isConnected = true;
        this.removed = false;
    }

    querySelectorAll() {
        return this.focusable;
    }

    contains(element) {
        return element === this || this.descendants.has(element);
    }

    focus() {
        this.ownerDocument.activeElement = this;
    }

    remove() {
        this.removed = true;
        this.isConnected = false;
    }

    getAttribute(name) {
        return this.attributes.has(name) ? this.attributes.get(name) : null;
    }

    hasAttribute(name) {
        return this.attributes.has(name);
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }
}

function keyEvent(key, shiftKey = false) {
    return {
        key,
        shiftKey,
        defaultPrevented: false,
        propagationStopped: false,
        preventDefault() { this.defaultPrevented = true; },
        stopImmediatePropagation() { this.propagationStopped = true; },
    };
}

const fakeWindow = new FakeWindow();
const fakeDocument = { activeElement: null, defaultView: fakeWindow };
const context = {
    window: fakeWindow,
    document: fakeDocument,
    console,
    setTimeout,
    clearTimeout,
};
vm.createContext(context);

const sourcePath = path.resolve(__dirname, '../src/ui/modals.js');
const source = fs.readFileSync(sourcePath, 'utf8');
vm.runInContext(
    source + '\n;globalThis.__modalTestAPI = { createAmsModalController, getAmsModalFocusableElements };',
    context,
    { filename: sourcePath },
);

const { createAmsModalController, getAmsModalFocusableElements } = context.__modalTestAPI;
const opener = new FakeElement(fakeDocument, 'opener');
const overlay = new FakeElement(fakeDocument, 'overlay');
const modal = new FakeElement(fakeDocument, 'modal');
const releaseLink = new FakeElement(fakeDocument, 'release-link');
const cancelButton = new FakeElement(fakeDocument, 'cancel');
const okButton = new FakeElement(fakeDocument, 'ok');
modal.focusable = [releaseLink, cancelButton, okButton];
modal.descendants = new Set(modal.focusable);
fakeDocument.activeElement = opener;

assert.deepStrictEqual(
    Array.from(getAmsModalFocusableElements(modal), (element) => element.name),
    ['release-link', 'cancel', 'ok'],
);

const closeReasons = [];
const controller = createAmsModalController({
    overlay,
    modal,
    initialFocus: releaseLink,
    previouslyFocused: opener,
    onClose: (reason) => closeReasons.push(reason),
});

assert.strictEqual((fakeWindow.listeners.get('keydown') || [])[0].capture, true);
controller.focusInitial();
assert.strictEqual(fakeDocument.activeElement, releaseLink);

fakeDocument.activeElement = okButton;
const forwardTab = keyEvent('Tab');
fakeWindow.dispatchKey(forwardTab);
assert.strictEqual(forwardTab.defaultPrevented, true);
assert.strictEqual(fakeDocument.activeElement, releaseLink);

const reverseTab = keyEvent('Tab', true);
fakeWindow.dispatchKey(reverseTab);
assert.strictEqual(reverseTab.defaultPrevented, true);
assert.strictEqual(fakeDocument.activeElement, okButton);

const escape = keyEvent('Escape');
fakeWindow.dispatchKey(escape);
assert.strictEqual(escape.defaultPrevented, true);
assert.strictEqual(escape.propagationStopped, true);
assert.strictEqual(overlay.removed, true);
assert.strictEqual(fakeDocument.activeElement, opener);
assert.deepStrictEqual(closeReasons, ['escape']);
assert.strictEqual((fakeWindow.listeners.get('keydown') || []).length, 0);
assert.strictEqual(controller.close('second-close'), false);

console.log('modal accessibility tests passed');
