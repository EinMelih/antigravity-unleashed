"use strict";

const assert = require("assert");
const EventEmitter = require("events");
const fs = require("fs");
const path = require("path");
const Module = require("module");

const navModulePath = path.join(__dirname, "..", "src", "amsWindowNavigation.js");
const mainPath = path.join(__dirname, "..", "src", "main.js");
const utilsPath = path.join(__dirname, "..", "src", "utils.js");

function createFakeWin(loadImpl) {
    const webContents = new EventEmitter();
    return {
        destroyed: false,
        isDestroyed() {
            return this.destroyed;
        },
        webContents,
        loadURL: loadImpl,
    };
}

async function runTests() {
    const dialogErrors = [];
    const originalLoad = Module._load;
    Module._load = function (request, parent, isMain) {
        if (request === "electron") {
            return {
                dialog: {
                    showErrorBox(title, content) {
                        dialogErrors.push({ title, content });
                    },
                },
            };
        }
        return originalLoad.call(this, request, parent, isMain);
    };

    try {
        delete require.cache[require.resolve(navModulePath)];
        const { isLocalNetworkChange, loadWindowUrl } = require(navModulePath);

        assert.strictEqual(
            isLocalNetworkChange("https://127.0.0.1:60512/", { code: "ERR_NETWORK_CHANGED", errno: -21 }),
            true,
            "Expected local 127.0.0.1 ERR_NETWORK_CHANGED to be retryable"
        );
        assert.strictEqual(
            isLocalNetworkChange("https://example.com/", { code: "ERR_NETWORK_CHANGED", errno: -21 }),
            false,
            "Expected external host not to be treated as local network change"
        );
        assert.strictEqual(
            isLocalNetworkChange("https://127.0.0.1:60512/", { code: "ERR_CONNECTION_REFUSED", errno: -102 }),
            false,
            "Expected non-ERR_NETWORK_CHANGED error not to match"
        );

        let attempts = 0;
        const winRetry = createFakeWin(async () => {
            attempts += 1;
            if (attempts === 1) {
                const err = new Error("ERR_NETWORK_CHANGED (-21) loading 'https://127.0.0.1:60512/'");
                err.code = "ERR_NETWORK_CHANGED";
                err.errno = -21;
                throw err;
            }
        });
        const retryResult = await loadWindowUrl(winRetry, "https://127.0.0.1:60512/");
        assert.strictEqual(retryResult, true, "Expected loadWindowUrl to recover after transient ERR_NETWORK_CHANGED");
        assert.strictEqual(attempts, 2, "Expected exactly 2 loadURL attempts");
        assert.strictEqual(dialogErrors.length, 0, "Expected no error box on successful retry");

        const winAbort = createFakeWin(async () => {
            const err = new Error("ERR_ABORTED (-3)");
            err.code = "ERR_ABORTED";
            err.errno = -3;
            throw err;
        });
        const abortResult = await loadWindowUrl(winAbort, "https://127.0.0.1:60512/");
        assert.strictEqual(abortResult, false, "Expected ERR_ABORTED to return false quietly");
        assert.strictEqual(dialogErrors.length, 0, "Expected no error box on ERR_ABORTED");

        const winFatal = createFakeWin(async () => {
            const err = new Error("ERR_CONNECTION_REFUSED (-102)");
            err.code = "ERR_CONNECTION_REFUSED";
            err.errno = -102;
            throw err;
        });
        const fatalResult = await loadWindowUrl(winFatal, "https://127.0.0.1:60512/");
        assert.strictEqual(fatalResult, false, "Expected non-retryable failure to return false");
        assert.strictEqual(dialogErrors.length, 1, "Expected error box on non-retryable failure");

        const mainSource = fs.readFileSync(mainPath, "utf8");
        const utilsSource = fs.readFileSync(utilsPath, "utf8");
        assert.ok(
            mainSource.includes("amsWindowNavigation_1.loadWindowUrl"),
            "Expected src/main.js to delegate port-change window reloads to amsWindowNavigation.loadWindowUrl"
        );
        assert.ok(
            utilsSource.includes("amsWindowNavigation_1.loadWindowUrl"),
            "Expected src/utils.js to delegate initial window load to amsWindowNavigation.loadWindowUrl"
        );
    } finally {
        Module._load = originalLoad;
    }

    console.log("amsWindowNavigation tests passed");
}

runTests().catch((err) => {
    console.error(err);
    process.exit(1);
});
