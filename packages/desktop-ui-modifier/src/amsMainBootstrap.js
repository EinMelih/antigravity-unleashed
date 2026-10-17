"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.configureProfile = configureProfile;
exports.getProfileInfo = getProfileInfo;
exports.startHubServices = startHubServices;
exports.resolveInitialWindowUrl = resolveInitialWindowUrl;
exports.openRepackTriggerWindow = openRepackTriggerWindow;

const electron_1 = require("electron");
const child_process_1 = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const SAFE_PROFILE_NAME = /^[A-Za-z0-9_-]{1,48}$/;
const SAFE_CONVERSATION_ID = /^[A-Za-z0-9_-]{1,160}$/;
let configuredProfile = 'default';

function configureProfile(pathsModule) {
    const profile = electron_1.app.commandLine?.getSwitchValue?.('ams-profile') || process.env.ANTIGRAVITY_PROFILE;
    if (!profile) {
        return;
    }
    if (!SAFE_PROFILE_NAME.test(profile)) {
        console.warn("[AMS Profile] Ignoring invalid ANTIGRAVITY_PROFILE.");
        return;
    }
    const defaultUserData = electron_1.app.getPath("userData");
    if (profile === 'api') {
        const profileHome = process.env.ANTIGRAVITY_PROFILE_HOME;
        if (!profileHome || !path.isAbsolute(profileHome) ||
            path.resolve(profileHome).toLowerCase() !== path.resolve(os.homedir()).toLowerCase()) {
            throw new Error('API profile requires an independent process home.');
        }
        const appData = path.join(profileHome, 'AppData', 'Roaming');
        const userData = path.join(appData, 'Antigravity-api');
        electron_1.app.setPath('home', profileHome);
        electron_1.app.setPath('appData', appData);
        electron_1.app.setPath('userData', userData);
        electron_1.app.setPath('logs', path.join(userData, 'logs'));
    } else {
        electron_1.app.setPath("userData", path.join(path.dirname(defaultUserData), "Antigravity-" + profile));
    }
    const profileDataName = pathsModule.getAppDataDirName() + '-' + profile;
    const profileDataDir = path.join(os.homedir(), '.gemini', profileDataName);
    pathsModule.getAppDataDirName = () => profileDataName;
    // Compiled upstream functions close over their original getter. Override
    // both exported paths instead of assuming they call the patched export.
    pathsModule.getAppDataDir = () => profileDataDir;
    pathsModule.getSettingsPbPath = () => profile === 'api'
        ? path.join(os.homedir(), '.gemini', 'config', 'config.json')
        : path.join(profileDataDir, 'config.json');
    process.env.ANTIGRAVITY_DATA_DIR = profileDataDir;
    configuredProfile = profile;
}

function getProfileInfo(pathsModule) {
    return {
        profile_contract_version: 2,
        profile: configuredProfile,
        process_id: process.pid,
        user_data_dir: electron_1.app.getPath('userData'),
        app_data_dir: pathsModule.getAppDataDir(),
        settings_path: pathsModule.getSettingsPbPath(),
        home_dir: os.homedir(),
        config_dir: path.join(os.homedir(), '.gemini', 'config'),
        process_cwd: process.cwd(),
    };
}

function startHubServices() {
    if (process.env.ANTIGRAVITY_NO_HUB_AUTOSTART === '1') return;
    if (process.platform !== "win32") {
        return;
    }
    try {
        const runtimeConfigPath = path.join(os.homedir(), ".gemini", "config", "antigravity-hub", "config.json");
        let hubRoot = typeof process.env.ANTIGRAVITY_HUB_ROOT === "string"
            ? process.env.ANTIGRAVITY_HUB_ROOT.trim()
            : "";
        if (!hubRoot && fs.existsSync(runtimeConfigPath)) {
            const runtimeConfig = JSON.parse(fs.readFileSync(runtimeConfigPath, "utf8"));
            hubRoot = typeof runtimeConfig.hub_root === "string" ? runtimeConfig.hub_root.trim() : "";
        }
        if (!hubRoot || !fs.existsSync(hubRoot)) {
            console.warn("[AMS Autostart] Hub root is not configured or does not exist.");
            return;
        }
        const resolvedHubRoot = fs.realpathSync(hubRoot);
        const scriptPath = path.join(resolvedHubRoot, "start_services.ps1");
        if (!fs.existsSync(scriptPath) || !fs.statSync(scriptPath).isFile()) {
            console.warn("[AMS Autostart] start_services.ps1 was not found in the configured Hub root.");
            return;
        }
        console.log("[AMS Autostart] Launching dashboard services from:", resolvedHubRoot);
        const child = (0, child_process_1.spawn)("powershell.exe", [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            scriptPath,
        ], {
            cwd: resolvedHubRoot,
            windowsHide: true,
            detached: true,
            stdio: "ignore",
        });
        child.once("error", (error) => {
            console.error("[AMS Autostart] Dashboard service launcher failed:", error);
        });
        child.unref();
    }
    catch (error) {
        console.error("[AMS Autostart] Could not launch dashboard services:", error);
    }
}

function resolveInitialWindowUrl(baseUrl, storageManager) {
    try {
        const storageItems = storageManager.getItems();
        const lastPath = storageItems && storageItems.antigravity_last_chat_path;
        if (typeof lastPath !== "string" ||
            lastPath.length === 0 ||
            lastPath.length > 2048 ||
            !lastPath.startsWith("/") ||
            lastPath.startsWith("//")) {
            return baseUrl;
        }
        const base = new URL(baseUrl);
        const restored = new URL(lastPath, base);
        if (restored.origin !== base.origin) {
            return baseUrl;
        }
        console.log("[AMS State Restore] Restoring last active page:", restored.href);
        return restored.href;
    }
    catch (error) {
        console.warn("[AMS State Restore] Could not restore the last active page:", error);
        return baseUrl;
    }
}

function openRepackTriggerWindow(baseUrl, storageManager, createWindow) {
    const conversationId = process.env.REPACK_TRIGGER_CHAT_ID;
    if (!conversationId) {
        return undefined;
    }
    if (!SAFE_CONVERSATION_ID.test(conversationId)) {
        console.warn("[AMS Repack] Ignoring invalid REPACK_TRIGGER_CHAT_ID.");
        return undefined;
    }
    try {
        const targetUrl = new URL("/c/" + encodeURIComponent(conversationId), baseUrl).href;
        console.log("[AMS Repack] Opening minimized trigger conversation:", targetUrl);
        const win = createWindow(targetUrl, storageManager);
        win.__antigravityWindowRole = "duplicate";
        win.webContents.setBackgroundThrottling(false);
        win.hide();
        win.once("ready-to-show", () => {
            if (win.isDestroyed()) {
                return;
            }
            win.showInactive();
            win.minimize();
        });
        return win;
    }
    catch (error) {
        console.error("[AMS Repack] Could not open the trigger conversation:", error);
        return undefined;
    }
}
