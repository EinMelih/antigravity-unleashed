"use strict";

const activeLoads = new WeakMap();
const retryDelays = [500, 1500, 3000];

function isLocalNetworkChange(url, error) {
    try {
        const target = new URL(url);
        if (target.protocol !== 'https:' || target.hostname !== '127.0.0.1' || target.username || target.password) {
            return false;
        }
    }
    catch (_) {
        return false;
    }
    return error?.errno === -21 || error?.code === 'ERR_NETWORK_CHANGED' ||
        /\bERR_NETWORK_CHANGED\b/.test(error?.message || '');
}

/** Recover only a failed local navigation, without replacing a newer one. */
async function loadWindowUrl(win, url) {
    const state = { cancelled: false };
    activeLoads.set(win, state);
    const cancel = () => { state.cancelled = true; };
    win.webContents.on('will-navigate', cancel);
    const current = () => !state.cancelled && !win.isDestroyed() && activeLoads.get(win) === state;
    try {
        for (let attempt = 0; current(); attempt++) {
            try {
                await win.loadURL(url);
                return current();
            }
            catch (error) {
                if (!current() || error?.errno === -3 || error?.code === 'ERR_ABORTED') {
                    return false;
                }
                if (!isLocalNetworkChange(url, error) || attempt >= retryDelays.length) {
                    console.error('[AMS Window] Navigation failed:', error);
                    const { dialog } = require('electron');
                    dialog.showErrorBox('Antigravity – Ladefehler',
                        'Die Oberfläche konnte nicht geladen werden. Bitte laden Sie das Fenster erneut oder starten Sie Antigravity neu.\n\n' +
                        'Fehler: ' + (error.code || error.errno || 'Unbekannter Ladefehler'));
                    return false;
                }
                console.warn(`[AMS Window] Retrying local navigation after ERR_NETWORK_CHANGED (${attempt + 1}/${retryDelays.length}).`);
                await new Promise(resolve => setTimeout(resolve, retryDelays[attempt]));
            }
        }
        return false;
    }
    finally {
        win.webContents.removeListener('will-navigate', cancel);
        if (activeLoads.get(win) === state) activeLoads.delete(win);
    }
}

exports.isLocalNetworkChange = isLocalNetworkChange;
exports.loadWindowUrl = loadWindowUrl;
