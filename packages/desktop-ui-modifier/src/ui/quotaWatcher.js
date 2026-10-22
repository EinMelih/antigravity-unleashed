    // ============================================================================
    // Antigravity Unleashed — Ultra Quota, Token & Prompt-Cache Intelligence
    // Empirically calibrated for Google AI Ultra (g1-ultra-tier) & Gemini 4 Argon
    // ============================================================================

    const ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN = 0.00000021285; // 1% Weekly ≈ 4.70M weighted tokens
    const ULTRA_5H_PCT_PER_WEIGHTED_TOKEN = 0.0000008514;      // 1% 5h ≈ 1.175M weighted tokens (4x Weekly)
    const CACHE_GUARANTEED_TTL_SEC = 300;                      // 5 minutes guaranteed by Google TPU HBM
    const CACHE_MAX_OBSERVED_TTL_SEC = 1020;                   // Up to ~17 minutes best-effort under low TPU load

    let currentQuotaData = {
        gemini5h: 100,
        gemini5hExact: 100.0,
        gemini5hFraction: 1.0,
        geminiWeekly: 100,
        geminiWeeklyExact: 100.0,
        geminiWeeklyFraction: 1.0,
        geminiWeeklyDesc: '',
        gemini5hDesc: '',

        claude5h: 100,
        claude5hExact: 100.0,
        claudeWeekly: 100,
        claudeWeeklyExact: 100.0,
        claudeWeeklyDesc: '',
        claude5hDesc: '',

        userTierId: 'g1-ultra-tier',
        userTierName: 'Google AI Ultra',
        lastUpdatedTs: 0,
    };

    const DEFAULT_AMS_UI_PREFS = {
        show5hLimit: false,
        showBrainIcon: false,
        showPlanIcon: false,
        showDuplicateIcon: false,
        showSidebarPct: false,
    };

    function loadAmsUiPrefs() {
        try {
            const raw = localStorage.getItem('ams_ui_prefs_v1');
            if (!raw) return { ...DEFAULT_AMS_UI_PREFS };
            const parsed = JSON.parse(raw);
            return { ...DEFAULT_AMS_UI_PREFS, ...(parsed && typeof parsed === 'object' ? parsed : {}) };
        } catch (_) {
            return { ...DEFAULT_AMS_UI_PREFS };
        }
    }

    const amsLiveOdometer = {
        initialized: false,
        serverWeeklyAnchor: 100.0,
        displayWeekly: 100.0,
        server5hAnchor: 100.0,
        display5h: 100.0,
        unsettledLocalDrainWeekly: 0.0,
        intraStepStreamDrainWeekly: 0.0,
        lastForceRefreshTs: 0,
        isActivelyDraining: false,
    };

    const amsTelemetryState = {
        activeConvStats: null,
        weeklySummary: null,
        allTimeSummary: null,
        recentChatsMap: new Map(),
        liveTrajectoriesMap: new Map(), // cascadeId -> { summary, status, lastModifiedEpoch, stepCount }
        lastObservedStepByConv: new Map(),
        lastCacheHitFlashTs: 0,
        logFilePath: '~/.gemini/config/quota_usage_log.json',
        repackInfo: { pending: false, repacking: false, title: '', details: '', runningChatsCount: 0 },
        liveOdometer: amsLiveOdometer,
        uiPrefs: loadAmsUiPrefs(),
        soundEnabled: (() => {
            try {
                return localStorage.getItem('ams_cache_sound_enabled') !== '0';
            } catch (_) {
                return true;
            }
        })(),
    };

    window.amsTelemetryState = amsTelemetryState;

    window.amsGetUiPrefs = function() {
        return amsTelemetryState.uiPrefs || DEFAULT_AMS_UI_PREFS;
    };

    window.amsSetUiPref = function(key, val) {
        if (!amsTelemetryState.uiPrefs) {
            amsTelemetryState.uiPrefs = loadAmsUiPrefs();
        }
        amsTelemetryState.uiPrefs[key] = !!val;
        try {
            localStorage.setItem('ams_ui_prefs_v1', JSON.stringify(amsTelemetryState.uiPrefs));
        } catch (_) {}
        ensureCleanUiStyles();
        refreshQuotaDisplay();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
        return amsTelemetryState.uiPrefs[key];
    };

    window.amsToggleUiPref = function(key) {
        const cur = !!(amsTelemetryState.uiPrefs && amsTelemetryState.uiPrefs[key]);
        return window.amsSetUiPref(key, !cur);
    };

    window.amsTriggerRepackNow = async function() {
        if (!amsTelemetryState.repackInfo) {
            amsTelemetryState.repackInfo = {};
        }
        amsTelemetryState.repackInfo.repacking = true;
        amsTelemetryState.repackInfo.pending = false;
        refreshQuotaDisplay();
        try {
            const activeCid = typeof getActiveCascadeId === 'function' ? getActiveCascadeId() : '';
            const curPath = window.location.pathname + window.location.search;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                const payload = { antigravity_repack_trigger_ts: Date.now() };
                if (activeCid) {
                    payload.antigravity_repack_trigger_chat_id = activeCid;
                    payload.antigravity_last_chat_path = '/c/' + activeCid;
                } else if (curPath && curPath !== '/') {
                    payload.antigravity_last_chat_path = curPath;
                }
                await window.nativeStorage.updateItems(payload);
            }
            if (window.electronNative && typeof window.electronNative.getTokenStats === 'function') {
                await window.electronNative.getTokenStats('__AMS_REPACK_TRIGGER__');
            }
        } catch (err) {
            console.error('[AMS Repack] Failed to trigger repack:', err);
        }
    };

    // ----------------------------------------------------------------------------
    // 0. Crisp Lucide SVG Icon Helper (Replaces Unicode Emojis)
    // ----------------------------------------------------------------------------
    const AMS_LUCIDE_PATHS = {
        sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>',
        flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
        snowflake: '<line x1="2" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="22"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/>',
        zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
        coins: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
        alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
        plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
        undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
        enter: '<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
        volumeOn: '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
        volumeOff: '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
        check: '<path d="M20 6 9 17l-5-5"/>',
        chart: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
        database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
        message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
        wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
        rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
        cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
        info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        refresh: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    };

    function amsIcon(name, size = 11, color = 'currentColor') {
        const p = AMS_LUCIDE_PATHS[name] || AMS_LUCIDE_PATHS.zap;
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-1.5px;flex-shrink:0;">${p}</svg>`;
    }

    // Claude Design Token System rooted in Native Antigravity IDE (--background: #0D0D0D, --border: rgba(255,255,255,0.05))
    const AMS_THEME = {
        textBright: 'rgba(255, 255, 255, 0.86)',
        textPrimary: 'var(--secondary-foreground, rgba(255, 255, 255, 0.75))',
        textMuted: 'var(--muted-foreground, rgba(255, 255, 255, 0.48))',
        textFaint: 'rgba(255, 255, 255, 0.26)',
        surfacePill: 'rgba(255, 255, 255, 0.03)',
        surfaceHover: 'rgba(255, 255, 255, 0.055)',
        borderSubtle: 'rgba(255, 255, 255, 0.065)',
        borderHover: 'rgba(255, 255, 255, 0.12)',
        // Low-chroma oklch() semantic accents (used sparingly on 10px icons, never loud neon boxes)
        sage: '#75b092',    // oklch(72% 0.075 155) — warm cache / active stream
        sand: '#c29b61',    // oklch(74% 0.075 75)  — cold cache / idle notice
        coral: '#c7746e',   // oklch(68% 0.095 25)  — critical <10% quota
    };

    const myInstanceId = Date.now() + '_' + Math.random();
    window.__ams_active_instance_id = myInstanceId;

    function ensureCleanUiStyles() {
        let st = document.getElementById('ams-clean-ui-override');
        if (!st) {
            st = document.createElement('style');
            st.id = 'ams-clean-ui-override';
            (document.head || document.documentElement).appendChild(st);
        }
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const hiddenToolbarSelectors = [];
        if (!prefs.showBrainIcon) hiddenToolbarSelectors.push('.antigravity-brain-btn');
        if (!prefs.showPlanIcon) hiddenToolbarSelectors.push('.antigravity-plan-btn', '.antigravity-plan-toggle-btn');
        if (!prefs.showDuplicateIcon) hiddenToolbarSelectors.push('.antigravity-duplicate-btn');

        const toolbarHideCss = hiddenToolbarSelectors.length > 0
            ? hiddenToolbarSelectors.join(',') + ' { display: none !important; }'
            : '';

        const css =
            '.antigravity-cache-hit-toast,' +
            '.antigravity-ultra-badge,' +
            '.ams-models-ultra-pill,' +
            '.antigravity-quota-display,' +
            '#antigravity-quota-display-v2,' +
            '#antigravity-quota-display-v3,' +
            '#antigravity-composer-status-strip,' +
            '#antigravity-composer-status-strip-v3,' +
            '.antigravity-turn-cost-badge,' +
            '.antigravity-turn-cost-badge-v2,' +
            '.antigravity-turn-cost-badge-v3,' +
            '#antigravity-chat-token-counter,' +
            '#antigravity-live-send-estimator,' +
            '#antigravity-model-trigger-loss-pill,' +
            '#antigravity-model-switch-popover,' +
            '.antigravity-sidebar-chat-meta,' +
            '.antigravity-sidebar-chat-meta-v2,' +
            '.antigravity-sidebar-chat-meta-v3,' +
            '#antigravity-models-usage-intelligence,' +
            '#antigravity-models-usage-intelligence-v2 {' +
            '  display: none !important;' +
            '}' +
            toolbarHideCss +
            '.antigravity-quickmenu-btn {' +
            '  background: rgba(255, 255, 255, 0.03) !important;' +
            '  border: 1px solid rgba(255, 255, 255, 0.07) !important;' +
            '  height: 24px !important;' +
            '  border-radius: 6px !important;' +
            '}' +
            '.antigravity-quickmenu-btn span {' +
            '  background: none !important;' +
            '  -webkit-text-fill-color: rgba(255, 255, 255, 0.72) !important;' +
            '  color: rgba(255, 255, 255, 0.72) !important;' +
            '  font-weight: 600 !important;' +
            '}';
        if (st.textContent !== css) {
            st.textContent = css;
        }
    }
    ensureCleanUiStyles();

    // ----------------------------------------------------------------------------
    // 1. Synthesized Web Audio API "Cha-Ching / Coin" Cache-Hit Sound
    // ----------------------------------------------------------------------------
    let amsAudioCtx = null;

    function playCacheHitSound(force = false) {
        if (!force && !amsTelemetryState.soundEnabled) return;
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!amsAudioCtx) {
                amsAudioCtx = new AudioCtx();
            }
            if (amsAudioCtx.state === 'suspended') {
                amsAudioCtx.resume().catch(() => {});
            }

            const now = amsAudioCtx.currentTime;

            // Note 1: Metallic B5 (987.77 Hz) + harmonic shimmer
            const osc1 = amsAudioCtx.createOscillator();
            const osc1Harm = amsAudioCtx.createOscillator();
            const gain1 = amsAudioCtx.createGain();
            osc1.type = 'triangle';
            osc1Harm.type = 'sine';
            osc1.frequency.setValueAtTime(987.77, now);
            osc1Harm.frequency.setValueAtTime(2963.31, now);

            gain1.gain.setValueAtTime(0.001, now);
            gain1.gain.linearRampToValueAtTime(0.085, now + 0.008);
            gain1.gain.exponentialRampToValueAtTime(0.0008, now + 0.095);

            osc1.connect(gain1);
            osc1Harm.connect(gain1);
            gain1.connect(amsAudioCtx.destination);
            osc1.start(now);
            osc1Harm.start(now);
            osc1.stop(now + 0.1);
            osc1Harm.stop(now + 0.1);

            // Note 2: Crisp E6 (1318.51 Hz) + golden overtone (2637.02 Hz)
            const t2 = now + 0.072;
            const osc2 = amsAudioCtx.createOscillator();
            const osc2Harm = amsAudioCtx.createOscillator();
            const gain2 = amsAudioCtx.createGain();
            osc2.type = 'sine';
            osc2Harm.type = 'triangle';
            osc2.frequency.setValueAtTime(1318.51, t2);
            osc2Harm.frequency.setValueAtTime(2637.02, t2);

            gain2.gain.setValueAtTime(0.001, t2);
            gain2.gain.linearRampToValueAtTime(0.095, t2 + 0.01);
            gain2.gain.exponentialRampToValueAtTime(0.0005, t2 + 0.34);

            osc2.connect(gain2);
            osc2Harm.connect(gain2);
            gain2.connect(amsAudioCtx.destination);
            osc2.start(t2);
            osc2Harm.start(t2);
            osc2.stop(t2 + 0.36);
            osc2Harm.stop(t2 + 0.36);
        } catch (err) {
            console.warn('[AMS Audio] Could not play cache hit sound:', err);
        }
    }

    window.amsPlayCacheHitSound = playCacheHitSound;

    window.amsToggleCacheHitSound = function() {
        amsTelemetryState.soundEnabled = !amsTelemetryState.soundEnabled;
        try {
            localStorage.setItem('ams_cache_sound_enabled', amsTelemetryState.soundEnabled ? '1' : '0');
        } catch (_) {}
        if (amsTelemetryState.soundEnabled) {
            playCacheHitSound(true);
        }
        return amsTelemetryState.soundEnabled;
    };

    function triggerCacheHitFeedback(cachedTokens, uncachedTokens, outTokens, convId) {
        // Remove any legacy floating cache-hit toasts immediately
        document.querySelectorAll('.antigravity-cache-hit-toast').forEach(el => el.remove());

        const now = Date.now();
        if (now - amsTelemetryState.lastCacheHitFlashTs < 8000) return;
        amsTelemetryState.lastCacheHitFlashTs = now;

        // Subtle inline pulse on the composer cache pill (NO floating popup!)
        const inlineCachePill = document.getElementById('ams-composer-cache-pill');
        if (inlineCachePill) {
            inlineCachePill.style.transition = 'box-shadow 0.35s ease, transform 0.35s ease';
            inlineCachePill.style.boxShadow = '0 0 12px rgba(16, 185, 129, 0.45)';
            setTimeout(() => {
                if (inlineCachePill) inlineCachePill.style.boxShadow = '';
            }, 900);
        }

        // Subtle pulse on the active sidebar row
        if (convId) {
            const row = document.querySelector(`[data-testid="conversation-row-sidebar"][data-cascade-id="${convId}"]`);
            if (row) {
                row.style.transition = 'box-shadow 0.4s ease';
                row.style.boxShadow = 'inset 0 0 0 1px rgba(16, 185, 129, 0.5)';
                setTimeout(() => {
                    row.style.boxShadow = '';
                }, 1000);
            }
        }
    }

    // ----------------------------------------------------------------------------
    // 2. ConnectRPC Helpers & Interceptors
    // ----------------------------------------------------------------------------
    if (!window.__ams_native_fetch) {
        try {
            const fnStr = Function.prototype.toString.call(window.fetch || '');
            if (fnStr.includes('[native code]')) {
                window.__ams_native_fetch = window.fetch.bind(window);
            } else if (document.body) {
                const ifr = document.createElement('iframe');
                ifr.style.display = 'none';
                document.body.appendChild(ifr);
                if (ifr.contentWindow && ifr.contentWindow.fetch) {
                    window.__ams_native_fetch = ifr.contentWindow.fetch.bind(window);
                }
                ifr.remove();
            }
        } catch (_) {}
        if (!window.__ams_native_fetch && window.fetch) {
            window.__ams_native_fetch = window.fetch.bind(window);
        }
    }
    const originalFetch = window.__ams_native_fetch || window.fetch;

    function buildGrpcWebJsonFrame(obj) {
        const bodyStr = JSON.stringify(obj || {});
        const bodyBytes = new TextEncoder().encode(bodyStr);
        const len = bodyBytes.length;
        const reqBytes = new Uint8Array(5 + len);
        reqBytes[0] = 0;
        reqBytes[1] = (len >> 24) & 0xFF;
        reqBytes[2] = (len >> 16) & 0xFF;
        reqBytes[3] = (len >> 8) & 0xFF;
        reqBytes[4] = len & 0xFF;
        reqBytes.set(bodyBytes, 5);
        return reqBytes;
    }

    function parseGrpcWebJsonText(text) {
        if (!text) return null;
        const jsonStart = text.indexOf('{');
        const jsonEnd = text.lastIndexOf('}');
        if (jsonStart === -1 || jsonEnd === -1 || jsonEnd <= jsonStart) return null;
        try {
            return JSON.parse(text.substring(jsonStart, jsonEnd + 1));
        } catch (_) {
            return null;
        }
    }

    async function fetchUserQuotaSummary(forceRefresh = false) {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const now = Date.now();
            const useForce = !!forceRefresh && (now - amsLiveOdometer.lastForceRefreshTs > 3200);
            if (useForce) {
                amsLiveOdometer.lastForceRefreshTs = now;
            }

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT',
                },
                body: buildGrpcWebJsonFrame({ forceRefresh: useForce }),
            });

            const text = await response.text();
            handleRetrieveUserQuotaSummaryText(text);
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to fetch user quota summary:', err);
        }
    }

    async function fetchAllCascadeTrajectories() {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/GetAllCascadeTrajectories', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT',
                },
                body: buildGrpcWebJsonFrame({}),
            });

            const text = await response.text();
            handleGetAllCascadeTrajectoriesText(text);
        } catch (_) {}
    }

    function handleGetAllCascadeTrajectoriesText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.trajectorySummaries) return;
        const summaries = data.trajectorySummaries;
        let anyRunning = false;
        for (const [cid, info] of Object.entries(summaries)) {
            if (!info || typeof info !== 'object') continue;
            const lastModStr = info.lastModifiedTime || info.createdTime || '';
            const lastModEpoch = lastModStr ? Math.floor(new Date(lastModStr).getTime() / 1000) : 0;
            const status = String(info.status || 'CASCADE_RUN_STATUS_IDLE');
            const isRunning = status.includes('RUNNING') || status.includes('WORKING');
            if (isRunning) anyRunning = true;

            amsTelemetryState.liveTrajectoriesMap.set(cid, {
                cascadeId: cid,
                summary: info.summary || '',
                status,
                isRunning,
                stepCount: Number(info.stepCount || 0),
                lastModifiedEpoch: lastModEpoch,
            });
        }
        decorateSidebarConversations();
        if (anyRunning) {
            scheduleRunningConvPoll();
        }
    }

    if (!window.__ams_orig_setTimeout) {
        window.__ams_orig_setTimeout = window.setTimeout.bind(window);
    }
    window.setTimeout = function(fn, delay, ...rest) {
        if (typeof fn === 'function' && delay === 2000) {
            const s = Function.prototype.toString.call(fn);
            if (s.includes('liveTrajectoriesMap') && fn.__ams_instance_id !== window.__ams_active_instance_id) {
                return 0;
            }
        }
        return window.__ams_orig_setTimeout(fn, delay, ...rest);
    };

    let runningPollTimer = null;
    function scheduleRunningConvPoll() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (runningPollTimer) return;
        const pollCb = async () => {
            runningPollTimer = null;
            if (window.__ams_active_instance_id !== myInstanceId) return;
            let stillRunning = false;
            for (const [cid, info] of amsTelemetryState.liveTrajectoriesMap.entries()) {
                if (info.isRunning && window.electronNative && window.electronNative.getTokenStats) {
                    stillRunning = true;
                    try {
                        const res = await window.electronNative.getTokenStats(cid);
                        if (res && res.status === 'success') {
                            window.amsIngestTokenStatsResult(res, cid === getActiveCascadeId());
                        }
                    } catch (_) {}
                }
            }
            fetchUserQuotaSummary();
            if (stillRunning) {
                fetchAllCascadeTrajectories();
            }
        };
        pollCb.__ams_instance_id = myInstanceId;
        runningPollTimer = setTimeout(pollCb, 2000);
    }

    function cleanResetTime(desc) {
        if (!desc) return 'Aktiv';

        const match = desc.match(/(?:resets?|resetting|reset|will\s+reset|refreshes?|refreshing|refresh|will\s+refresh|fully\s+refresh)\s+(?:in|on|at|until)\s+(.+)/i);
        let clean = match ? match[1] : desc;

        clean = clean.split('.')[0].toLowerCase();

        clean = clean.replace(/remaining\s+fraction/g, '')
                     .replace(/quota/g, '')
                     .replace(/limit/g, '')
                     .trim();

        clean = clean.replace(/\bhours?\b/g, 'h')
                     .replace(/\bminutes?\b/g, 'm')
                     .replace(/\bseconds?\b/g, 's')
                     .replace(/\bdays?\b/g, 'd')
                     .replace(/\bweeks?\b/g, 'w');

        clean = clean.replace(/(\d+)\s*([hmsdw])\b/g, '$1$2');
        clean = clean.replace(/[.,]$/g, '').trim();

        if (!clean) return 'Aktiv';
        return clean.charAt(0).toUpperCase() + clean.slice(1);
    }

    function handleRetrieveUserQuotaSummaryText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.response || !data.response.groups) return;
        try {
            const groups = data.response.groups;
            const geminiGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('gemini'));
            const claudeGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('claude'));

            if (geminiGroup && geminiGroup.buckets) {
                const weeklyBucket = geminiGroup.buckets.find(b => b.window === 'weekly');
                const fiveHourBucket = geminiGroup.buckets.find(b => b.window === '5h');

                if (weeklyBucket && typeof weeklyBucket.remainingFraction === 'number') {
                    const exactW6 = Number((weeklyBucket.remainingFraction * 100).toFixed(6));
                    currentQuotaData.geminiWeeklyFraction = weeklyBucket.remainingFraction;
                    currentQuotaData.geminiWeeklyExact = exactW6;
                    currentQuotaData.geminiWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                    currentQuotaData.geminiWeeklyDesc = weeklyBucket.description || '';
                    if (!amsLiveOdometer.initialized) {
                        amsLiveOdometer.initialized = true;
                        amsLiveOdometer.serverWeeklyAnchor = exactW6;
                        amsLiveOdometer.displayWeekly = exactW6;
                    } else if (Math.abs(exactW6 - amsLiveOdometer.serverWeeklyAnchor) > 0.000001) {
                        amsLiveOdometer.serverWeeklyAnchor = exactW6;
                        amsLiveOdometer.unsettledLocalDrainWeekly = 0;
                        amsLiveOdometer.intraStepStreamDrainWeekly = 0;
                    }
                }
                if (fiveHourBucket && typeof fiveHourBucket.remainingFraction === 'number') {
                    const exact5h6 = Number((fiveHourBucket.remainingFraction * 100).toFixed(6));
                    currentQuotaData.gemini5hFraction = fiveHourBucket.remainingFraction;
                    currentQuotaData.gemini5hExact = exact5h6;
                    currentQuotaData.gemini5h = Math.round(fiveHourBucket.remainingFraction * 100);
                    currentQuotaData.gemini5hDesc = fiveHourBucket.description || '';
                    amsLiveOdometer.server5hAnchor = exact5h6;
                    if (amsLiveOdometer.display5h === 100.0) {
                        amsLiveOdometer.display5h = exact5h6;
                    }
                }
            }

            if (claudeGroup && claudeGroup.buckets) {
                const weeklyBucket = claudeGroup.buckets.find(b => b.window === 'weekly');
                const fiveHourBucket = claudeGroup.buckets.find(b => b.window === '5h');

                if (weeklyBucket && typeof weeklyBucket.remainingFraction === 'number') {
                    currentQuotaData.claudeWeeklyExact = Number((weeklyBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claudeWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                    currentQuotaData.claudeWeeklyDesc = weeklyBucket.description || '';
                }
                if (fiveHourBucket && typeof fiveHourBucket.remainingFraction === 'number') {
                    currentQuotaData.claude5hExact = Number((fiveHourBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claude5h = Math.round(fiveHourBucket.remainingFraction * 100);
                    currentQuotaData.claude5hDesc = fiveHourBucket.description || '';
                }
            }
            currentQuotaData.lastUpdatedTs = Date.now();
            refreshQuotaDisplay();
            patchModelsAndUsagePage();
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to parse RetrieveUserQuotaSummary JSON:', err);
        }
    }

    function handleGetUserStatusText(text) {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const data = parseGrpcWebJsonText(text);
        if (!data || !data.userStatus) return;
        try {
            if (data.userStatus.userTier) {
                currentQuotaData.userTierId = data.userStatus.userTier.id || 'g1-ultra-tier';
                currentQuotaData.userTierName = data.userStatus.userTier.name || 'Google AI Ultra';
            }
            if (data.userStatus.cascadeModelConfigData) {
                const configs = data.userStatus.cascadeModelConfigData.clientModelConfigs || [];
                const geminiConfig = configs.find(c => c.label && c.label.toLowerCase().includes('gemini'));
                const claudeConfig = configs.find(c => c.label && c.label.toLowerCase().includes('claude'));

                if (geminiConfig && geminiConfig.quotaInfo && typeof geminiConfig.quotaInfo.remainingFraction === 'number') {
                    currentQuotaData.gemini5hFraction = geminiConfig.quotaInfo.remainingFraction;
                    currentQuotaData.gemini5hExact = Number((geminiConfig.quotaInfo.remainingFraction * 100).toFixed(4));
                    currentQuotaData.gemini5h = Math.round(geminiConfig.quotaInfo.remainingFraction * 100);
                }
                if (claudeConfig && claudeConfig.quotaInfo && typeof claudeConfig.quotaInfo.remainingFraction === 'number') {
                    currentQuotaData.claude5hExact = Number((claudeConfig.quotaInfo.remainingFraction * 100).toFixed(4));
                    currentQuotaData.claude5h = Math.round(claudeConfig.quotaInfo.remainingFraction * 100);
                }
                fetchUserQuotaSummary();
            }
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to parse GetUserStatus JSON:', err);
        }
    }

    // Hook Fetch in Main World
    window.fetch = async function(...args) {
        const response = await originalFetch(...args);
        try {
            const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url);
            if (url) {
                if (url.includes('GetUserStatus')) {
                    response.clone().text().then(handleGetUserStatusText).catch(() => {});
                } else if (url.includes('RetrieveUserQuotaSummary')) {
                    response.clone().text().then(handleRetrieveUserQuotaSummaryText).catch(() => {});
                } else if (url.includes('GetAllCascadeTrajectories')) {
                    response.clone().text().then(handleGetAllCascadeTrajectoriesText).catch(() => {});
                } else if (url.includes('GetCascadeTrajectory')) {
                    setTimeout(() => {
                        if (typeof updateTokenStats === 'function') updateTokenStats();
                    }, 350);
                }
            }
        } catch (err) {
            console.error('[AMS Quota Interceptor] Error intercepting fetch:', err);
        }
        return response;
    };

    // Hook XMLHttpRequest in Main World
    if (!window.__ams_native_xhr_open || !window.__ams_native_xhr_send) {
        try {
            const openStr = Function.prototype.toString.call(XMLHttpRequest.prototype.open || '');
            const sendStr = Function.prototype.toString.call(XMLHttpRequest.prototype.send || '');
            if (openStr.includes('[native code]') && sendStr.includes('[native code]')) {
                window.__ams_native_xhr_open = XMLHttpRequest.prototype.open;
                window.__ams_native_xhr_send = XMLHttpRequest.prototype.send;
            } else if (document.body) {
                const ifr = document.createElement('iframe');
                ifr.style.display = 'none';
                document.body.appendChild(ifr);
                if (ifr.contentWindow && ifr.contentWindow.XMLHttpRequest) {
                    window.__ams_native_xhr_open = ifr.contentWindow.XMLHttpRequest.prototype.open;
                    window.__ams_native_xhr_send = ifr.contentWindow.XMLHttpRequest.prototype.send;
                }
                ifr.remove();
            }
        } catch (_) {}
    }
    const originalOpen = window.__ams_native_xhr_open || XMLHttpRequest.prototype.open;
    const originalSend = window.__ams_native_xhr_send || XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            if (window.__ams_active_instance_id !== myInstanceId) return;
            try {
                if (this._url) {
                    if (this._url.includes('GetUserStatus')) {
                        handleGetUserStatusText(this.responseText);
                    } else if (this._url.includes('RetrieveUserQuotaSummary')) {
                        handleRetrieveUserQuotaSummaryText(this.responseText);
                    } else if (this._url.includes('GetAllCascadeTrajectories')) {
                        handleGetAllCascadeTrajectoriesText(this.responseText);
                    }
                }
            } catch (_) {}
        });
        return originalSend.apply(this, args);
    };

    // ----------------------------------------------------------------------------
    // 3. Ingest Token & Cache Intelligence from get_token_stats.py
    // ----------------------------------------------------------------------------
    window.amsIngestTokenStatsResult = function(res, isActiveConv = true) {
        if (!res || res.status !== 'success') return;

        if (res.repackInfo && typeof res.repackInfo === 'object') {
            if (!amsTelemetryState.repackInfo || !amsTelemetryState.repackInfo.repacking) {
                amsTelemetryState.repackInfo = res.repackInfo;
            }
        }
        if (res.weeklySummary) {
            amsTelemetryState.weeklySummary = res.weeklySummary;
        }
        if (res.allTimeSummary) {
            amsTelemetryState.allTimeSummary = res.allTimeSummary;
        }
        if (res.logFilePath) {
            amsTelemetryState.logFilePath = res.logFilePath;
        }
        if (Array.isArray(res.recentChats)) {
            for (const c of res.recentChats) {
                if (c && c.cascadeId) {
                    const existing = amsTelemetryState.recentChatsMap.get(c.cascadeId);
                    if (
                        existing &&
                        Number(existing.stepCount || 0) >= Number(c.stepCount || 0) &&
                        Number(existing.totalInput || 0) > Number(c.totalInput || 0)
                    ) {
                        continue;
                    }
                    amsTelemetryState.recentChatsMap.set(c.cascadeId, c);
                }
            }
        }

        const cid = res.cascadeId || currentConvId;
        if (cid) {
            if (!amsTelemetryState.liveDrainHistory) {
                amsTelemetryState.liveDrainHistory = new Map();
            }
            const curTotalTok = Number(res.totalInput || 0) + Number(res.totalOutput || 0);
            const curWeeklyUsed = Number(res.weeklyPctUsed || 0);
            const cur5hUsed = Number(res.fiveHourPctUsed || 0);
            const prevDrain = amsTelemetryState.liveDrainHistory.get(cid);
            if (!prevDrain) {
                const lastTurn = Array.isArray(res.turns) && res.turns.length > 0 ? res.turns[res.turns.length - 1] : null;
                amsTelemetryState.liveDrainHistory.set(cid, {
                    prevTotalTok: curTotalTok,
                    prevWeeklyUsed: curWeeklyUsed,
                    lastDeltaTok: Number((res.latestInput || 0) + (res.latestOutput || 0)),
                    lastDeltaWeeklyPct: Number(lastTurn ? (lastTurn.weeklyPct / Math.max(1, lastTurn.steps)) : 0.0048),
                    lastDelta5hPct: Number(lastTurn ? (lastTurn.fiveHourPct / Math.max(1, lastTurn.steps)) : 0.0192),
                    lastPulseTs: 0,
                });
            } else if (curTotalTok > prevDrain.prevTotalTok) {
                const dTok = curTotalTok - prevDrain.prevTotalTok;
                const dW = Math.max(0.0001, curWeeklyUsed - prevDrain.prevWeeklyUsed);
                amsTelemetryState.liveDrainHistory.set(cid, {
                    prevTotalTok: curTotalTok,
                    prevWeeklyUsed: curWeeklyUsed,
                    lastDeltaTok: dTok,
                    lastDeltaWeeklyPct: dW,
                    lastDelta5hPct: dW * 4.0,
                    lastPulseTs: Date.now(),
                });
                amsLiveOdometer.unsettledLocalDrainWeekly = Math.min(0.15, amsLiveOdometer.unsettledLocalDrainWeekly + dW);
                amsLiveOdometer.intraStepStreamDrainWeekly = 0;
                fetchUserQuotaSummary(true);
            }

            const prevStepIdx = amsTelemetryState.lastObservedStepByConv.get(cid);
            const curStepIdx = Number(res.latestStepIdx || 0);
            if (prevStepIdx !== undefined && curStepIdx > prevStepIdx && Number(res.latestCached || 0) > 0) {
                triggerCacheHitFeedback(
                    Number(res.latestCached || 0),
                    Number(res.latestUncached || 0),
                    Number(res.latestOutput || 0),
                    cid,
                );
            }
            if (curStepIdx > 0) {
                amsTelemetryState.lastObservedStepByConv.set(cid, curStepIdx);
            }

            // Keep recentChatsMap updated with freshest active stats
            amsTelemetryState.recentChatsMap.set(cid, {
                ...(amsTelemetryState.recentChatsMap.get(cid) || {}),
                cascadeId: cid,
                title: res.title || (amsTelemetryState.recentChatsMap.get(cid) || {}).title || '',
                stepCount: res.stepCount || 0,
                turnCount: res.turnCount || 0,
                totalInput: res.totalInput || 0,
                totalUncached: res.totalUncached || 0,
                totalCached: res.totalCached || 0,
                totalOutput: res.totalOutput || 0,
                latestInput: res.latestInput || 0,
                latestUncached: res.latestUncached || 0,
                latestCached: res.latestCached || 0,
                latestStepIdx: curStepIdx,
                cacheRatio: res.cacheRatio || 0,
                cacheMissCount: res.cacheMissCount || 0,
                wastedWeeklyPct: res.wastedWeeklyPct || 0,
                weightedTokens: res.weightedTokens || 0,
                weeklyPctUsed: res.weeklyPctUsed || 0,
                fiveHourPctUsed: res.fiveHourPctUsed || 0,
                apiCostEur: res.apiCostEur || 0,
                apiRawCostEur: res.apiRawCostEur || 0,
                apiSavedEur: res.apiSavedEur || 0,
                firstStepTimestamp: res.firstStepTimestamp || 0,
                lastStepTimestamp: res.lastStepTimestamp || 0,
            });
        }

        if (isActiveConv) {
            amsTelemetryState.activeConvStats = res;
            renderPerMessageTurnBadges();
            updateLiveSendEstimator();
        }

        refreshQuotaDisplay();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
    };

    // ----------------------------------------------------------------------------
    // 4. Cache Warmth & Cost Calculation Helpers
    // ----------------------------------------------------------------------------
    function getChatCacheState(cascadeId) {
        const nowSec = Math.floor(Date.now() / 1000);
        const stats = amsTelemetryState.recentChatsMap.get(cascadeId) ||
                      (amsTelemetryState.activeConvStats && amsTelemetryState.activeConvStats.cascadeId === cascadeId
                          ? amsTelemetryState.activeConvStats
                          : null);
        const liveInfo = amsTelemetryState.liveTrajectoriesMap.get(cascadeId);

        const isRunning = !!(liveInfo && liveInfo.isRunning);
        const lastTs = Math.max(
            Number((stats && stats.lastStepTimestamp) || 0),
            Number((liveInfo && liveInfo.lastModifiedEpoch) || 0),
        );
        const contextTokens = Number((stats && stats.latestInput) || 0);
        const stepCount = Number((stats && stats.stepCount) || (liveInfo && liveInfo.stepCount) || 0);
        const weeklyPctUsed = Number((stats && stats.weeklyPctUsed) || 0);
        const fiveHourPctUsed = Number((stats && stats.fiveHourPctUsed) || 0);
        const cacheRatio = Number((stats && stats.cacheRatio) || 0);

        if (stepCount === 0 || lastTs === 0) {
            return {
                state: 'new',
                isRunning: false,
                idleSec: 0,
                remainingGuaranteedSec: CACHE_GUARANTEED_TTL_SEC,
                contextTokens: 0,
                weeklyPctUsed: 0,
                fiveHourPctUsed: 0,
                cacheRatio: 0,
                warmSendWeeklyPct: 0.0035,
                coldSendWeeklyPct: 0.0035,
                warmSend5hPct: 0.0140,
                coldSend5hPct: 0.0140,
                extraColdLossWeeklyPct: 0,
                extraColdLoss5hPct: 0,
            };
        }

        const idleSec = isRunning ? 0 : Math.max(0, nowSec - lastTs);
        const remainingGuaranteedSec = Math.max(0, CACHE_GUARANTEED_TTL_SEC - idleSec);

        // Calculate next-message send cost (assuming ~900 output/thinking tokens + 250 new input tokens)
        const baseCtx = Math.max(24500, contextTokens || 32000);
        const estNewInput = 250;
        const estOut = 850;
        const warmWeighted = Math.round(0.1 * baseCtx + 1.0 * estNewInput + 6.0 * estOut);
        const coldWeighted = Math.round(1.0 * baseCtx + 1.0 * estNewInput + 6.0 * estOut);

        const warmSendWeeklyPct = Number((warmWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const coldSendWeeklyPct = Number((coldWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const warmSend5hPct = Number((warmWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const coldSend5hPct = Number((coldWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4));
        const extraColdLossWeeklyPct = Number(Math.max(0, coldSendWeeklyPct - warmSendWeeklyPct).toFixed(4));
        const extraColdLoss5hPct = Number(Math.max(0, coldSend5hPct - warmSend5hPct).toFixed(4));

        let state = 'warm'; // < 5m guaranteed
        if (!isRunning) {
            if (idleSec >= CACHE_MAX_OBSERVED_TTL_SEC) {
                state = 'cold'; // > 17m definitely cold
            } else if (idleSec >= CACHE_GUARANTEED_TTL_SEC) {
                state = 'lukewarm'; // 5m - 17m: 5m guarantee expired! High risk of cold reload
            }
        }

        return {
            state,
            isRunning,
            idleSec,
            remainingGuaranteedSec,
            contextTokens: baseCtx,
            stepCount,
            weeklyPctUsed,
            fiveHourPctUsed,
            cacheRatio,
            warmSendWeeklyPct,
            coldSendWeeklyPct,
            warmSend5hPct,
            coldSend5hPct,
            extraColdLossWeeklyPct,
            extraColdLoss5hPct,
        };
    }

    function formatDurationShort(sec) {
        const s = Math.max(0, Math.floor(sec));
        if (s < 60) return s + 's';
        const m = Math.floor(s / 60);
        const remS = s % 60;
        if (m < 60) return remS > 0 && m < 10 ? `${m}m ${remS}s` : `${m}m`;
        const h = Math.floor(m / 60);
        const remM = m % 60;
        if (h < 24) return remM > 0 ? `${h}h ${remM}m` : `${h}h`;
        const d = Math.floor(h / 24);
        return `${d}d ${h % 24}h`;
    }

    function formatTokensCompact(num) {
        const n = Number(num || 0);
        if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
        if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
        if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
        return String(n);
    }

    function triggerNewConversation() {
        const selectors = [
            '[data-testid="new-conversation-button"]',
            '[data-testid="app-icon-new-conversation-button"]',
            '[data-testid="extension-new-conversation"]',
            'a[href="/"]',
        ];
        for (const sel of selectors) {
            const btn = document.querySelector(sel);
            if (btn) {
                btn.click();
                return true;
            }
        }
        window.location.href = window.location.origin + '/';
        return true;
    }

    // ----------------------------------------------------------------------------
    // 5. Upgraded Composer Bar Display (ULTRA Badge + 5h & Weekly + Live Estimator)
    // ----------------------------------------------------------------------------
    let isSwitchingModel = false;

    function showQuotaFallbackToast(modelName) {
        const toast = document.createElement('div');
        toast.className = 'antigravity-quota-toast';
        toast.style.cssText =
            'position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;background:var(--card,#1c1917);' +
            'border:1px solid #ef4444;color:var(--foreground,#ffffff);font-size:12px;font-weight:500;z-index:999999;' +
            'box-shadow:0 10px 15px -3px rgba(0,0,0,0.5);display:flex;align-items:center;gap:8px;font-family:ui-sans-serif,system-ui,sans-serif;' +
            'transform:translateY(20px);opacity:0;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);';

        toast.innerHTML =
            '<span style="display:flex;align-items:center;justify-content:center;background:#ef4444;color:white;border-radius:50%;width:18px;height:18px;font-weight:bold;font-size:11px;">!</span>' +
            '<span><strong>Quoten-Wächter:</strong> Claude verbraucht. Automatisch auf ' + modelName + ' umgeschaltet.</span>';

        document.body.appendChild(toast);
        toast.offsetHeight;
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';

        setTimeout(() => {
            toast.style.transform = 'translateY(20px)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }

    async function switchModel(targetModelName) {
        const selectorBtn = document.querySelector('button[aria-label^="Select model, current:"]');
        if (!selectorBtn) return false;
        try {
            selectorBtn.click();
            await new Promise(r => setTimeout(r, 250));
            let targetBtn = null;
            const buttons = document.querySelectorAll('button');
            for (let i = 0; i < buttons.length; i++) {
                const btn = buttons[i];
                const text = btn.textContent ? btn.textContent.trim() : '';
                if (text.toLowerCase().includes(targetModelName.toLowerCase())) {
                    targetBtn = btn;
                    break;
                }
            }
            if (targetBtn) {
                targetBtn.click();
                showQuotaFallbackToast(targetModelName);
                return true;
            }
            selectorBtn.click();
            return false;
        } catch (_) {
            return false;
        }
    }

    function refreshQuotaDisplay() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        const flexContainer = addContextBtn ? addContextBtn.parentElement : null;
        if (!flexContainer) return;

        let quotaEl = document.getElementById('antigravity-quota-display-v4');
        if (!quotaEl) {
            quotaEl = document.createElement('div');
            quotaEl.id = 'antigravity-quota-display-v4';
            quotaEl.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                toggleQuotaHudPopover(quotaEl);
            });
            flexContainer.appendChild(quotaEl);
        } else if (quotaEl.parentElement !== flexContainer) {
            flexContainer.appendChild(quotaEl);
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const g5hExact = currentQuotaData.gemini5hExact;
        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWServerExact = currentQuotaData.geminiWeeklyExact;
        const g5hReset = cleanResetTime(currentQuotaData.gemini5hDesc);
        const gWReset = cleanResetTime(currentQuotaData.geminiWeeklyDesc);

        const remStepsW = Math.round(gWExact * 200);
        const remPromptsS = Math.round(gWExact / 0.0075);
        const remPromptsM = Math.round(gWExact / 0.040);
        const remPromptsL = Math.round(gWExact / 0.125);
        const remPromptsXL = Math.round(gWExact / 0.400);

        const tooltipText = isDe
            ? `Gemini Quota (Exakt · Live-Odometer):\n` +
              `• Weekly-Limit (Live): ${gWExact.toFixed(4)}% übrig (Server-Float: ${gWServerExact.toFixed(6)}% · Reset: ${gWReset})\n` +
              `• 5-Stunden-Limit: ${g5hExact.toFixed(4)}% übrig (-${(100 - g5hExact).toFixed(4)}% verbraucht · Reset: ${g5hReset})\n\n` +
              `Verbleibendes Kontingent (aus ${gWExact.toFixed(4)}% Weekly):\n` +
              `• ~${remStepsW.toLocaleString('de-DE')} Agent-Steps\n` +
              `• ~${remPromptsS.toLocaleString('de-DE')} Kurze Prompts (Typ S · 1–2 Steps)\n` +
              `• ~${remPromptsM.toLocaleString('de-DE')} Kleine Tasks (Typ M · ~8 Steps)\n` +
              `• ~${remPromptsL.toLocaleString('de-DE')} Komplexe Coding-Tasks (Typ L · ~25 Steps)\n` +
              `• ~${remPromptsXL.toLocaleString('de-DE')} Große Deep-Dives (Typ XL · ~80 Steps)\n` +
              `(Klicken für Models & Usage)`
            : `Gemini Quota (Exact · Live Odometer):\n` +
              `• Weekly Limit (Live): ${gWExact.toFixed(4)}% left (Server float: ${gWServerExact.toFixed(6)}% · Reset: ${gWReset})\n` +
              `• 5-Hour Limit: ${g5hExact.toFixed(4)}% left (-${(100 - g5hExact).toFixed(4)}% used · Reset: ${g5hReset})\n\n` +
              `Remaining Capacity (from ${gWExact.toFixed(4)}% Weekly):\n` +
              `• ~${remStepsW.toLocaleString('en-US')} Agent Steps\n` +
              `• ~${remPromptsS.toLocaleString('en-US')} Quick Prompts (Type S · 1–2 steps)\n` +
              `• ~${remPromptsM.toLocaleString('en-US')} Small Tasks (Type M · ~8 steps)\n` +
              `• ~${remPromptsL.toLocaleString('en-US')} Complex Coding Tasks (Type L · ~25 steps)\n` +
              `• ~${remPromptsXL.toLocaleString('en-US')} Autonomous Deep-Dives (Type XL · ~80 steps)\n` +
              `(Click to open Models & Usage)`;

        function getToneColor(pct) {
            if (pct < 10) return AMS_THEME.coral;
            return AMS_THEME.textBright;
        }

        function format4DecSplitHtml(pct, isDraining) {
            const s4 = Math.max(0, Number(pct || 0)).toFixed(4);
            const main2 = s4.slice(0, -2); // e.g. "11.96"
            const micro2 = s4.slice(-2);   // e.g. "24"
            const mainColor = getToneColor(pct);
            const microColor = isDraining ? AMS_THEME.sage : 'rgba(255, 255, 255, 0.64)';
            return `<span style="display:inline-flex;align-items:baseline;font-variant-numeric:tabular-nums;">` +
                `<span style="color:${mainColor};font-weight:600;">${main2}</span>` +
                `<span style="color:${microColor};font-weight:500;transition:color 0.2s ease;">${micro2}%</span>` +
            `</span>`;
        }

        quotaEl.style.cssText =
            'display:inline-flex;align-items:center;margin-left:6px;margin-right:4px;' +
            'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;' +
            'white-space:nowrap;flex-shrink:0;user-select:none;cursor:pointer;';
        quotaEl.title = tooltipText;

        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        let unifiedQuotaPill = quotaEl.querySelector('.antigravity-quota-pill-v3');
        if (!unifiedQuotaPill) {
            unifiedQuotaPill = document.createElement('span');
            unifiedQuotaPill.className = 'antigravity-quota-pill-v3';
            quotaEl.replaceChildren(unifiedQuotaPill);
        }
        const isDraining = !!amsLiveOdometer.isActivelyDraining;
        unifiedQuotaPill.style.cssText =
            `display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 8px;border-radius:6px;` +
            `background:${AMS_THEME.surfacePill};border:1px solid ${isDraining ? 'rgba(117,176,146,0.28)' : AMS_THEME.borderSubtle};` +
            `font-size:11px;white-space:nowrap;transition:border-color 0.25s ease;`;

        const pillHtml = prefs.show5hLimit
            ? `<span style="display:inline-flex;align-items:center;gap:4px;">` +
                  `<span style="color:${AMS_THEME.textMuted};font-weight:400;">Weekly</span>` +
                  `${format4DecSplitHtml(gWExact, isDraining)}` +
              `</span>` +
              `<span style="color:${AMS_THEME.textFaint};">·</span>` +
              `<span style="display:inline-flex;align-items:center;gap:3.5px;">` +
                  `<span style="color:${AMS_THEME.textMuted};font-weight:400;">5h</span>` +
                  `${format4DecSplitHtml(g5hExact, false)}` +
              `</span>`
            : `<span style="display:inline-flex;align-items:center;gap:4.5px;">` +
                  `<span style="color:${AMS_THEME.textMuted};font-weight:400;">Weekly</span>` +
                  `${format4DecSplitHtml(gWExact, isDraining)}` +
              `</span>`;

        if (unifiedQuotaPill.getAttribute('data-sig') !== pillHtml) {
            unifiedQuotaPill.setAttribute('data-sig', pillHtml);
            unifiedQuotaPill.innerHTML = pillHtml;
        }

        // Noticeable In-App Repack Ready Button (Never auto-restarts while agents run; waits for user click)
        const rInfo = amsTelemetryState.repackInfo;
        let repackBtn = document.getElementById('antigravity-repack-ready-btn');
        if (rInfo && (rInfo.pending || rInfo.repacking)) {
            if (!repackBtn) {
                repackBtn = document.createElement('button');
                repackBtn.type = 'button';
                repackBtn.id = 'antigravity-repack-ready-btn';
                repackBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (typeof window.amsTriggerRepackNow === 'function') {
                        window.amsTriggerRepackNow();
                    }
                });
                flexContainer.appendChild(repackBtn);
            } else if (repackBtn.parentElement !== flexContainer) {
                flexContainer.appendChild(repackBtn);
            }

            repackBtn.style.cssText =
                'display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 9px;margin-left:4px;border-radius:6px;' +
                'border:1px solid rgba(251,191,36,0.48);background:rgba(245,158,11,0.14);color:#fde68a;' +
                'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;font-weight:600;' +
                'white-space:nowrap;cursor:pointer;flex-shrink:0;transition:all 0.15s ease;box-shadow:0 0 12px rgba(245,158,11,0.12);';

            const shortTitle = rInfo.title || (isDe ? 'UI-Update' : 'UI Update');
            const labelHtml = rInfo.repacking
                ? `${amsIcon('refresh', 11, '#fde68a')}<span>${isDe ? 'Repack & Neustart läuft (ca. 3s)...' : 'Repacking & restarting (3s)...'}</span>`
                : `${amsIcon('refresh', 11, '#fbbf24')}<span>${isDe ? `Neustart für: ${shortTitle}` : `Restart for: ${shortTitle}`}</span>`;

            if (repackBtn.getAttribute('data-sig') !== labelHtml) {
                repackBtn.setAttribute('data-sig', labelHtml);
                repackBtn.innerHTML = labelHtml;
            }
            const runningNote = rInfo.runningChatsCount > 0
                ? (isDe
                    ? `\n⚡ Auto-Resume aktiv: Aktuell arbeiten ${rInfo.runningChatsCount} Chat(s) — nach dem Neustart werden alle aktiven Agenten automatisch mit "continue" geweckt.`
                    : `\n⚡ Auto-Resume active: ${rInfo.runningChatsCount} chat(s) currently working — all active agents will be automatically resumed with "continue" after restart.`)
                : (isDe ? '\n✓ Kein automatischer Neustart ohne deinen Klick.' : '\n✓ Will only restart when you click.');
            repackBtn.title =
                (isDe ? `Repack bereit: ${shortTitle}\n` : `Repack ready: ${shortTitle}\n`) +
                (rInfo.details || '') +
                runningNote +
                (isDe ? '\n\nKlicken, um app.asar jetzt neu zu packen und Antigravity in ~3s neu zu starten.' : '\n\nClick to repack app.asar and restart Antigravity in ~3s.');
        } else if (repackBtn) {
            repackBtn.remove();
        }

        // Update the clean full-width Composer Status Strip below the button row
        updateComposerStatusStrip();

        // Quoten-Wächter (Model Fallback if user ever selects exhausted Claude before Nov 2)
        if (!isSwitchingModel && typeof getActiveModel === 'function') {
            const activeModel = getActiveModel();
            if (activeModel && activeModel.startsWith('Claude')) {
                if (currentQuotaData.claude5h === 0 || currentQuotaData.claudeWeekly === 0) {
                    isSwitchingModel = true;
                    switchModel('Gemini 4 Argon (High)').finally(() => {
                        isSwitchingModel = false;
                    });
                }
            }
        }
    }

    // ----------------------------------------------------------------------------
    // 5b. Interactive Live Quota & Cache HUD Popover (Click on Weekly Pill)
    // ----------------------------------------------------------------------------
    let activeQuotaHudPopover = null;

    function openModelsAndUsageSettings() {
        closeQuotaHudPopover();
        const settingsBtn = document.querySelector('[data-testid="settings-button"]');
        if (settingsBtn) {
            settingsBtn.click();
            let attempts = 0;
            const interval = setInterval(() => {
                let modelsTab = null;
                document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                    if (btn.textContent && btn.textContent.trim() === 'Models') {
                        modelsTab = btn;
                    }
                });
                if (modelsTab) {
                    modelsTab.click();
                    clearInterval(interval);
                }
                attempts++;
                if (attempts > 20) clearInterval(interval);
            }, 50);
        }
    }

    function closeQuotaHudPopover() {
        if (activeQuotaHudPopover) {
            activeQuotaHudPopover.remove();
            activeQuotaHudPopover = null;
        }
    }

    function renderQuotaHudPopoverBody(pop) {
        if (!pop) return;
        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWServer = currentQuotaData.geminiWeeklyExact;
        const g5hExact = currentQuotaData.gemini5hExact;
        const gWReset = cleanResetTime(currentQuotaData.geminiWeeklyDesc);
        const g5hReset = cleanResetTime(currentQuotaData.gemini5hDesc);

        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const ctxTok = cacheInfo && cacheInfo.contextTokens ? cacheInfo.contextTokens : 0;
        const warmInputPct = (ctxTok * 0.1 * 100) / 470000000;
        const coldInputPct = (ctxTok * 1.0 * 100) / 470000000;
        const savedPerStepPct = Math.max(0, coldInputPct - warmInputPct);
        const remStepsW = Math.round(gWExact * 200);
        const remTasksL = Math.round(gWExact / 0.125);
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;

        const sig = `${gWExact.toFixed(4)}|${gWServer.toFixed(6)}|${ctxTok}|${cacheInfo ? cacheInfo.state : 'none'}|${cacheInfo ? cacheInfo.stepCount : 0}|${prefs.show5hLimit ? 1 : 0}|${isDe}`;
        if (pop.getAttribute('data-hud-sig') === sig) return;
        pop.setAttribute('data-hud-sig', sig);

        const chatSectionHtml = ctxTok > 0
            ? `<div style="margin-top:8px;padding:8px 10px;border-radius:7px;background:rgba(255,255,255,0.03);border:1px solid ${AMS_THEME.borderSubtle};display:flex;flex-direction:column;gap:4px;">` +
                  `<div style="display:flex;justify-content:space-between;align-items:center;font-weight:600;color:${AMS_THEME.textBright};margin-bottom:2px;">` +
                      `<span>${isDe ? `Aktueller Chat (${formatTokensCompact(ctxTok)} Kontext · ${cacheInfo.stepCount} Steps)` : `Current Chat (${formatTokensCompact(ctxTok)} ctx · ${cacheInfo.stepCount} steps)`}</span>` +
                      `<span style="color:${cacheInfo.state === 'warm' || cacheInfo.isRunning ? AMS_THEME.sage : AMS_THEME.sand};">${cacheInfo.state === 'warm' || cacheInfo.isRunning ? (isDe ? '🔥 Warm' : '🔥 Warm') : (isDe ? '❄️ Kalt' : '❄️ Cold')}</span>` +
                  `</div>` +
                  `<div style="display:flex;justify-content:space-between;"><span>${isDe ? '🔥 Warm-Step (0.1× Input, 90% Rabatt):' : '🔥 Warm step (0.1× input, 90% off):'}</span><span style="color:${AMS_THEME.sage};font-weight:600;">-${warmInputPct.toFixed(4)}% W</span></div>` +
                  `<div style="display:flex;justify-content:space-between;"><span>${isDe ? '❄️ Kaltstart-Reload (1.0× Input, 10×):' : '❄️ Cold reload (1.0× input, 10×):'}</span><span style="color:${AMS_THEME.sand};font-weight:600;">-${coldInputPct.toFixed(4)}% W</span></div>` +
                  `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Ersparnis pro warmem Step:' : 'Saved per warm step:'}</span><span style="color:${AMS_THEME.textPrimary};font-weight:500;">+${savedPerStepPct.toFixed(4)}% W</span></div>` +
              `</div>`
            : '';

        pop.innerHTML =
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding-bottom:7px;border-bottom:1px solid rgba(255,255,255,0.07);">` +
                `<strong style="display:inline-flex;align-items:center;gap:5px;color:${AMS_THEME.textBright};font-size:12px;font-weight:600;">` +
                    `${amsIcon('chart', 12, AMS_THEME.sage)}<span>${isDe ? 'Live Quota-Odometer & Token-Faktencheck' : 'Live Quota Odometer & Token Fact-Check'}</span>` +
                `</strong>` +
                `<button type="button" class="ams-qhud-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:${AMS_THEME.textMuted};cursor:pointer;padding:2px;">${amsIcon('close', 12, AMS_THEME.textMuted)}</button>` +
            `</div>` +
            `<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;font-size:11px;color:${AMS_THEME.textMuted};">` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Weekly-Limit (Live 4-Dezimal):' : 'Weekly Limit (Live 4-Dec):'}</span><span style="color:${AMS_THEME.textBright};font-weight:700;font-size:12px;">${gWExact.toFixed(4)}%</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Exakter Google-Server Float:' : 'Exact Google Server Float:'}</span><span style="color:${AMS_THEME.textPrimary};font-family:monospace;">${gWServer.toFixed(6)}% (${gWReset})</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? '5-Stunden-Limit:' : '5-Hour Limit:'}</span><span style="color:${AMS_THEME.textPrimary};">${g5hExact.toFixed(4)}% (${g5hReset})</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Verbleibende Kapazität:' : 'Remaining Capacity:'}</span><span style="color:${AMS_THEME.sage};font-weight:500;">~${remStepsW.toLocaleString(isDe ? 'de-DE' : 'en-US')} Steps · ~${remTasksL} Tasks</span></div>` +
            `</div>` +
            chatSectionHtml +
            `<div style="margin-top:8px;padding:7px 9px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);font-size:10.5px;line-height:1.4;color:${AMS_THEME.textMuted};">` +
                (isDe
                    ? `<strong>Bestätigt durch Google RPC:</strong> Quota wird exakt nach gewichteten Token-Kosten abgerechnet (TPU-HBM Cache = <code>0.1×</code>, Uncached Input = <code>1.0×</code>). Ein Kaltstart (>5m) lädt den Kontext <strong>10× teurer</strong> neu.`
                    : `<strong>Confirmed via Google RPC:</strong> Quota is billed strictly by weighted token cost (TPU HBM cache = <code>0.1×</code>, uncached input = <code>1.0×</code>). A cold start (>5m) reloads context at <strong>10× cost</strong>.`) +
            `</div>` +
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:9px;padding-top:7px;border-top:1px solid rgba(255,255,255,0.07);">` +
                `<label style="display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:${AMS_THEME.textPrimary};cursor:pointer;user-select:none;">` +
                    `<input type="checkbox" class="ams-qhud-5h-chk" ${prefs.show5hLimit ? 'checked' : ''} style="accent-color:#75b092;margin:0;cursor:pointer;" />` +
                    `<span>${isDe ? '5h-Limit in Leiste zeigen' : 'Show 5h limit in bar'}</span>` +
                `</label>` +
                `<button type="button" class="ams-qhud-open-models" style="display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:5px;border:1px solid ${AMS_THEME.borderHover};background:${AMS_THEME.surfaceHover};color:${AMS_THEME.textBright};font-size:10.5px;font-weight:500;cursor:pointer;">` +
                    `<span>${isDe ? 'Models & Usage →' : 'Models & Usage →'}</span>` +
                `</button>` +
            `</div>`;

        const closeBtn = pop.querySelector('.ams-qhud-close');
        if (closeBtn) closeBtn.onclick = () => closeQuotaHudPopover();
        const chk5h = pop.querySelector('.ams-qhud-5h-chk');
        if (chk5h) {
            chk5h.onchange = (ev) => {
                if (typeof window.amsSetUiPref === 'function') {
                    window.amsSetUiPref('show5hLimit', !!ev.target.checked);
                }
            };
        }
        const openBtn = pop.querySelector('.ams-qhud-open-models');
        if (openBtn) openBtn.onclick = () => openModelsAndUsageSettings();
    }

    function toggleQuotaHudPopover(anchorEl) {
        if (activeQuotaHudPopover) {
            closeQuotaHudPopover();
            return;
        }
        const rect = anchorEl.getBoundingClientRect();
        const pop = document.createElement('div');
        pop.id = 'antigravity-quota-hud-popover';
        pop.style.cssText =
            'position:fixed;z-index:999999;width:365px;padding:12px 14px;border-radius:10px;' +
            'background:rgba(20,20,22,0.98);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.10);' +
            'box-shadow:0 16px 36px rgba(0,0,0,0.68);color:rgba(255,255,255,0.88);font-family:ui-sans-serif,system-ui,sans-serif;' +
            'font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;user-select:none;';

        renderQuotaHudPopoverBody(pop);
        document.body.appendChild(pop);
        activeQuotaHudPopover = pop;

        const popRect = pop.getBoundingClientRect();
        const top = Math.max(12, rect.top - popRect.height - 8);
        const left = Math.min(window.innerWidth - 380, Math.max(12, rect.left));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';
    }

    // ----------------------------------------------------------------------------
    // 6. Clean Full-Width Composer Status Strip (Native Antigravity Aesthetic)
    // ----------------------------------------------------------------------------
    let lastRequestedTokenStatsCid = null;
    let lastRequestedTokenStatsTs = 0;

    let lastSavedFocusedCascadeId = null;

    function getActiveCascadeId() {
        const parts = window.location.pathname.split('/');
        if (parts.length > 2 && parts[1] === 'c' && parts[2]) {
            currentConvId = parts[2];
            return parts[2];
        }
        const selectedRow = document.querySelector('[data-testid="conversation-row-sidebar"][data-selected="true"][data-cascade-id]');
        if (selectedRow) {
            const cid = selectedRow.getAttribute('data-cascade-id');
            if (cid) {
                currentConvId = cid;
                return cid;
            }
        }
        return currentConvId || null;
    }
    window.amsGetActiveCascadeId = getActiveCascadeId;

    function getComposerInputText() {
        const el = document.querySelector('[role="combobox"][aria-label="Message input"]') ||
                   document.querySelector('[contenteditable="true"][role="textbox"]') ||
                   document.querySelector('textarea');
        if (!el) return '';
        return (typeof el.value === 'string' ? el.value : el.textContent) || '';
    }

    function updateComposerStatusStrip() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeQuotaHudPopover) {
            renderQuotaHudPopoverBody(activeQuotaHudPopover);
        }
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        if (!addContextBtn || !addContextBtn.parentElement) return;
        const buttonRow = addContextBtn.parentElement;
        const toolbarFooter = buttonRow.parentElement;
        const composerCard = toolbarFooter ? toolbarFooter.parentElement : null;
        if (!composerCard) return;

        let stripEl = document.getElementById('antigravity-composer-status-strip-v4');
        if (!stripEl) {
            stripEl = document.createElement('div');
            stripEl.id = 'antigravity-composer-status-strip-v4';
            stripEl.style.cssText =
                `display:none;align-items:center;justify-content:space-between;gap:12px;width:100%;` +
                `padding:5px 6px 2px 6px;margin-top:4px;border-top:1px solid rgba(255,255,255,0.045);` +
                `font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;` +
                `color:${AMS_THEME.textMuted};font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;user-select:none;`;
            composerCard.appendChild(stripEl);
        } else if (stripEl.parentElement !== composerCard) {
            composerCard.appendChild(stripEl);
        }

        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }

        // If user switched chats in the sidebar, fetch active chat stats immediately so UI never lags or shows another chat
        if (activeId && (!amsTelemetryState.activeConvStats || amsTelemetryState.activeConvStats.cascadeId !== activeId)) {
            const now = Date.now();
            if ((lastRequestedTokenStatsCid !== activeId || now - lastRequestedTokenStatsTs > 2500) && window.electronNative && window.electronNative.getTokenStats) {
                lastRequestedTokenStatsCid = activeId;
                lastRequestedTokenStatsTs = now;
                window.electronNative.getTokenStats(activeId).then((res) => {
                    if (res && res.status === 'success') {
                        window.amsIngestTokenStatsResult(res, activeId === getActiveCascadeId());
                    }
                }).catch(() => {});
            }
        }

        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const hasHistory = !!(cacheInfo && cacheInfo.stepCount > 0);

        if (!hasHistory) {
            stripEl.style.display = 'none';
            return;
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        stripEl.style.display = 'flex';

        const ctxTokens = cacheInfo.contextTokens || 0;
        const ctxCompact = formatTokensCompact(ctxTokens);
        const warmStepPct = ((ctxTokens * 0.1 * 100) / 470000000).toFixed(4);
        const coldStepPct = ((ctxTokens * 1.0 * 100) / 470000000).toFixed(4);
        const stats = amsTelemetryState.activeConvStats;
        const isStillFillingInitialCache = (cacheInfo.stepCount <= 2 && (!stats || !stats.totalCached || stats.totalCached === 0));

        let leftHtml = '';
        let rightHtml = '';

        if (cacheInfo.isRunning) {
            const statusRightText = isStillFillingInitialCache
                ? (isDe ? `Cache wird aufgebaut (${ctxCompact} Tok)...` : `Filling cache (${ctxCompact} tok)...`)
                : (isDe ? `90% Cache-Rabatt aktiv (~${warmStepPct}% W/Step)` : `90% cache discount active (~${warmStepPct}% W/step)`);
            leftHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">` +
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:${AMS_THEME.textPrimary};font-weight:500;">` +
                        `${amsIcon('zap', 10, AMS_THEME.sage)}<span>${isDe ? `Aktiv (Step #${cacheInfo.stepCount})` : `Active (Step #${cacheInfo.stepCount})`}</span>` +
                    `</span>` +
                    `<span style="color:${AMS_THEME.textFaint};">·</span>` +
                    `<span style="color:${AMS_THEME.textMuted};">${statusRightText}</span>` +
                `</div>`;
            rightHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;color:${AMS_THEME.textMuted};flex-shrink:0;">` +
                    `<span>${ctxCompact} ${isDe ? 'Kontext' : 'context'}</span>` +
                `</div>`;
        } else if (cacheInfo.state === 'warm') {
            const warmDetail = isStillFillingInitialCache
                ? (isDe ? `Initialer Kontext bereit (${ctxCompact} Tok)` : `Initial context ready (${ctxCompact} tok)`)
                : (isDe ? `Du sparst 90% (~${warmStepPct}% statt ${coldStepPct}% W)` : `You save 90% (~${warmStepPct}% vs ${coldStepPct}% W)`);
            leftHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">` +
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:${AMS_THEME.textPrimary};font-weight:500;">` +
                        `${amsIcon('flame', 10, AMS_THEME.sage)}<span>${isDe ? `Cache warm (noch ${formatDurationShort(cacheInfo.remainingGuaranteedSec)})` : `Cache warm (${formatDurationShort(cacheInfo.remainingGuaranteedSec)} left)`}</span>` +
                    `</span>` +
                    `<span style="color:${AMS_THEME.textFaint};">·</span>` +
                    `<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${warmDetail}</span>` +
                `</div>`;
            rightHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;color:${AMS_THEME.textMuted};flex-shrink:0;">` +
                    `<span>${ctxCompact} ${isDe ? 'Kontext' : 'context'} · ${cacheInfo.stepCount} ${cacheInfo.stepCount === 1 ? 'Step' : 'Steps'}</span>` +
                `</div>`;
        } else {
            leftHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">` +
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:5px;color:${AMS_THEME.textPrimary};font-weight:500;">` +
                        `${amsIcon('snowflake', 10, AMS_THEME.sand)}<span>${isDe ? `Cache kalt (${formatDurationShort(cacheInfo.idleSec)} Pause)` : `Cache cold (${formatDurationShort(cacheInfo.idleSec)} idle)`}</span>` +
                    `</span>` +
                    `<span style="color:${AMS_THEME.textFaint};">·</span>` +
                    `<span style="color:${AMS_THEME.sand};">${isDe ? `Reload kostet ~${coldStepPct}% statt ${warmStepPct}% W (10× Input)` : `Reload costs ~${coldStepPct}% vs ${warmStepPct}% W (10× input)`}</span>` +
                `</div>`;
            rightHtml =
                `<div style="display:inline-flex;align-items:center;gap:8px;flex-shrink:0;">` +
                    `<button type="button" class="antigravity-inline-newchat-btn" style="display:inline-flex;align-items:center;gap:3.5px;height:20px;padding:0 7px;border-radius:5px;border:1px solid ${AMS_THEME.borderHover};background:${AMS_THEME.surfaceHover};color:${AMS_THEME.textBright};font-size:10.5px;font-weight:500;cursor:pointer;transition:background 0.15s ease;">` +
                        `${amsIcon('plus', 9, AMS_THEME.textPrimary)}<span>${isDe ? 'Neuer Chat (spart 90%)' : 'New Chat (saves 90%)'}</span>` +
                    `</button>` +
                `</div>`;
        }

        const sig = `${leftHtml}|${rightHtml}`;
        if (stripEl.getAttribute('data-sig') !== sig) {
            stripEl.setAttribute('data-sig', sig);
            stripEl.innerHTML = leftHtml + rightHtml;

            const btn = stripEl.querySelector('.antigravity-inline-newchat-btn');
            if (btn) {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    triggerNewConversation();
                });
            }
        }

        stripEl.title = isDe
            ? `Prompt-Cache Status (${cacheInfo.stepCount} Steps · ${(cacheInfo.contextTokens || 0).toLocaleString('de-DE')} Kontext-Tokens):\n` +
              `• Im warmen Cache (< 5 Min. Pause): ~${warmStepPct}% Weekly pro Step (du sparst 90% / 0.1× Input).\n` +
              `• Bei kaltem Cache (> 5 Min. Pause): ~${coldStepPct}% Weekly beim Nachladen (10× teurer / 1.0× Input).\n` +
              `• Bisheriger Chat-Verbrauch: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly`
            : `Prompt-Cache Status (${cacheInfo.stepCount} steps · ${(cacheInfo.contextTokens || 0).toLocaleString('en-US')} context tokens):\n` +
              `• While warm (< 5m idle): ~${warmStepPct}% Weekly per step (90% discount / 0.1× input).\n` +
              `• When cold (> 5m idle): ~${coldStepPct}% Weekly to reload context (10× cost / 1.0× input).\n` +
              `• Chat Weekly used so far: -${cacheInfo.weeklyPctUsed.toFixed(4)}%`;
    }

    function updateComposerChatBadge() {
        updateComposerStatusStrip();
    }

    function updateLiveSendEstimator() {
        updateComposerStatusStrip();
    }

    // Attach input listeners for instant pre-send estimation while typing
    document.addEventListener('input', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (e.target && (e.target.getAttribute('role') === 'combobox' || e.target.isContentEditable || e.target.tagName === 'TEXTAREA')) {
            updateComposerStatusStrip();
        }
    }, true);

    // ----------------------------------------------------------------------------
    // 7. Per-Message Post-Turn Cost Line (Smart Filling Cache vs Cache Hit vs Cold Reload)
    // ----------------------------------------------------------------------------
    function renderPerMessageTurnBadges() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const stats = amsTelemetryState.activeConvStats;
        if (!stats || (activeId && stats.cascadeId && stats.cascadeId !== activeId)) return;
        if (!Array.isArray(stats.turns) || stats.turns.length === 0) return;

        const agentArticles = Array.from(document.querySelectorAll('[role="article"][aria-label="Agent response"]'));
        if (agentArticles.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const turns = stats.turns;

        agentArticles.forEach((article, idx) => {
            const turn = turns[idx] || (idx === agentArticles.length - 1 ? turns[turns.length - 1] : null);
            if (!turn || !turn.steps) return;

            let badge = article.querySelector('.antigravity-turn-cost-badge-v4');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'antigravity-turn-cost-badge-v4';
                article.appendChild(badge);
            }
            badge.style.cssText =
                `display:inline-flex;align-items:center;gap:6px;margin-top:6px;padding:3px 9px;border-radius:6px;` +
                `background:${AMS_THEME.surfacePill};border:1px solid ${AMS_THEME.borderSubtle};` +
                `font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;` +
                `font-variant-numeric:tabular-nums;white-space:nowrap;max-width:100%;overflow-x:auto;` +
                `color:${AMS_THEME.textMuted};user-select:none;cursor:help;`;

            const cachePct = turn.totalInput > 0 ? Math.round((turn.cached / turn.totalInput) * 100) : 0;
            const wPct = Number(turn.weeklyPct || 0).toFixed(4);
            const savedWPct = Number(turn.savedWeeklyPct || 0).toFixed(4);
            const eurStr = Number(turn.apiCostEur || 0).toFixed(2);
            const savedEurStr = Number(turn.apiSavedEur || 0).toFixed(2);
            const stepsLabel = `${turn.steps} ${turn.steps === 1 ? 'Step' : 'Steps'}`;
            const dot = `<span style="color:${AMS_THEME.textFaint};">·</span>`;
            const ctxCompact = formatTokensCompact(turn.latestContextTokens || turn.uncached || turn.totalInput);
            const reloadedCompact = formatTokensCompact(turn.reloadedTokens || turn. latestContextTokens || turn.uncached);

            let mainSegment = '';
            if (turn.cacheMiss) {
                // Genuine cold-start reload after >5m idle pause (or model switch) in an existing conversation
                if (turn.cacheHit && cachePct >= 25 && turn.steps > 1) {
                    mainSegment =
                        `<span style="display:inline-flex;align-items:center;gap:4px;">` +
                            `${amsIcon('snowflake', 10, AMS_THEME.sand)}` +
                            `<span style="color:${AMS_THEME.sand};">${isDe ? `Kaltstart (${reloadedCompact} neu geladen)` : `Cold reload (${reloadedCompact})`}</span>` +
                            `<span style="color:${AMS_THEME.textFaint};">→</span>` +
                            `${amsIcon('flame', 10, AMS_THEME.sage)}` +
                            `<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${isDe ? `wieder warm (${cachePct}% Cache)` : `re-warmed (${cachePct}% hit)`}</span>` +
                        `</span>`;
                } else {
                    mainSegment =
                        `<span style="display:inline-flex;align-items:center;gap:4px;color:${AMS_THEME.sand};">` +
                            `${amsIcon('snowflake', 10, AMS_THEME.sand)}` +
                            `<span>${isDe ? `Kaltstart-Reload (${reloadedCompact} Tok → füllt Cache neu)` : `Cold reload (${reloadedCompact} tok → refilling cache)`}</span>` +
                        `</span>`;
                }
            } else if (turn.cacheBuiltInTurn && cachePct > 0) {
                // First turn of a new chat that filled the cache on Step 1-2 and immediately reused it on Steps 3..N!
                mainSegment =
                    `<span style="display:inline-flex;align-items:center;gap:4px;">` +
                        `${amsIcon('flame', 10, AMS_THEME.sage)}` +
                        `<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${isDe ? `Cache aufgebaut & ${cachePct}% genutzt` : `Cache built & ${cachePct}% hit`}</span>` +
                        `<span style="opacity:0.8;">(${isDe ? '90% gespart' : '90% saved'})</span>` +
                    `</span>`;
            } else if (cachePct > 0) {
                // Standard warm cached turn
                mainSegment =
                    `<span style="display:inline-flex;align-items:center;gap:4px;">` +
                        `${amsIcon('flame', 10, AMS_THEME.sage)}` +
                        `<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${isDe ? `${cachePct}% aus Cache` : `${cachePct}% cached`}</span>` +
                        `<span style="opacity:0.8;">(${isDe ? '90% gespart' : '90% saved'})</span>` +
                    `</span>`;
            } else {
                // Filling cache (initial step(s) of a brand new chat before cache threshold is reached)
                mainSegment =
                    `<span style="display:inline-flex;align-items:center;gap:4px;">` +
                        `${amsIcon('zap', 10, AMS_THEME.sage)}` +
                        `<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${isDe ? `Cache wird aufgebaut (${ctxCompact} Tok)` : `Filling cache (${ctxCompact} tok)`}</span>` +
                    `</span>`;
            }

            const costSegment = `<span style="color:${AMS_THEME.textMuted};">-${wPct}% W</span>`;
            const html = `${mainSegment}${dot}${costSegment}${dot}<span style="color:${AMS_THEME.textPrimary};font-weight:500;">${stepsLabel}</span>`;
            if (badge.getAttribute('data-sig') !== html) {
                badge.setAttribute('data-sig', html);
                badge.innerHTML = html;
            }

            badge.title = isDe
                ? `Details zu dieser KI-Antwort (${turn.steps} Steps):\n` +
                  `• Status: ${turn.cacheMiss ? 'Kaltstart-Reload nach Pause' : (turn.cacheBuiltInTurn ? 'Neuer Chat: Cache aufgebaut & direkt wiederverwendet' : (cachePct > 0 ? 'Warmer Prompt-Cache (90% Rabatt)' : 'Cache wird erstmalig im TPU-RAM aufgebaut (Filling Cache)'))}\n` +
                  `• Tokens: ${formatTokensCompact(turn.cached)} aus Cache (${cachePct}%) · ${formatTokensCompact(turn.uncached)} neu · ${formatTokensCompact(turn.out)} Output\n` +
                  `• Weekly-Abzug: -${wPct}% Weekly (${savedWPct > 0 ? '+' + savedWPct + '% Weekly durch Cache gespart' : 'Erstbefüllung'})\n` +
                  `• API-Gegenwert: ~${eurStr} € (+${savedEurStr} € durch Cache gespart)`
                : `AI Response Breakdown (${turn.steps} steps):\n` +
                  `• Status: ${turn.cacheMiss ? 'Cold reload after idle pause' : (turn.cacheBuiltInTurn ? 'New chat: Cache built & immediately reused' : (cachePct > 0 ? 'Warm Prompt Cache (90% discount)' : 'Filling initial cache in TPU RAM'))}\n` +
                  `• Tokens: ${formatTokensCompact(turn.cached)} cached (${cachePct}%) · ${formatTokensCompact(turn.uncached)} new · ${formatTokensCompact(turn.out)} out\n` +
                  `• Weekly used: -${wPct}% Weekly (${savedWPct > 0 ? '+' + savedWPct + '% Weekly saved by cache' : 'initial fill'})\n` +
                  `• API value: ~€${eurStr} (+€${savedEurStr} saved by cache)`;
        });
    }

    // ----------------------------------------------------------------------------
    // 8. Left Navigation Sidebar Conversation Badges & Cold-Chat Popover
    // ----------------------------------------------------------------------------
    let activeColdPopover = null;
    let activeColdPopoverConvId = null;

    function closeColdChatPopover() {
        if (activeColdPopover) {
            activeColdPopover.remove();
            activeColdPopover = null;
            activeColdPopoverConvId = null;
        }
    }

    function showColdChatPopover(anchorEl, cascadeId) {
        const cacheInfo = getChatCacheState(cascadeId);
        if (activeColdPopover && activeColdPopoverConvId === cascadeId) {
            closeColdChatPopover();
            return;
        }
        closeColdChatPopover();

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const rect = anchorEl.getBoundingClientRect();
        const pop = document.createElement('div');
        pop.id = 'antigravity-cold-chat-popover';
        pop.className = 'antigravity-modal-overlay';
        pop.style.cssText =
            'position:fixed;z-index:999999;width:335px;padding:12px 14px;border-radius:10px;' +
            'background:rgba(20,20,22,0.98);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.10);' +
            'box-shadow:0 16px 36px rgba(0,0,0,0.65);color:rgba(255,255,255,0.88);font-family:ui-sans-serif,system-ui,sans-serif;' +
            'font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;';

        const top = Math.min(window.innerHeight - 250, Math.max(12, rect.bottom + 6));
        const left = Math.min(window.innerWidth - 350, Math.max(12, rect.left));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';

        const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
        const statusHeader = isWarm
            ? `${amsIcon('flame', 12, AMS_THEME.sage)} <span>${isDe ? `Prompt-Cache ist warm (${formatDurationShort(cacheInfo.remainingGuaranteedSec)})` : `Prompt Cache is warm (${formatDurationShort(cacheInfo.remainingGuaranteedSec)})`}</span>`
            : `${amsIcon('snowflake', 12, AMS_THEME.sand)} <span>${isDe ? `Chat ist kalt (Pause: ${formatDurationShort(cacheInfo.idleSec)})` : `Chat is cold (Idle: ${formatDurationShort(cacheInfo.idleSec)})`}</span>`;

        pop.innerHTML =
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.07);">` +
                `<strong style="display:inline-flex;align-items:center;gap:5px;color:${AMS_THEME.textBright};font-size:12px;font-weight:600;">${statusHeader}</strong>` +
                `<button type="button" class="ams-cold-pop-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:${AMS_THEME.textMuted};cursor:pointer;padding:2px;">${amsIcon('close', 12, AMS_THEME.textMuted)}</button>` +
            `</div>` +
            `<div style="display:flex;flex-direction:column;gap:5px;font-size:11px;color:${AMS_THEME.textMuted};">` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Kontextfenster-Größe:' : 'Context Window Size:'}</span><span style="color:${AMS_THEME.textBright};font-weight:500;">${cacheInfo.contextTokens.toLocaleString(isDe ? 'de-DE' : 'en-US')} Tokens (${cacheInfo.stepCount} Steps)</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Im warmen Cache (< 5m):' : 'While warm (< 5m):'}</span><span style="color:${AMS_THEME.sage};font-weight:500;">${isDe ? '90% Rabatt (0.1× Kosten)' : '90% discount (0.1× cost)'}</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Bei kaltem Cache (> 5m):' : 'When cold (> 5m):'}</span><span style="color:${AMS_THEME.sand};font-weight:500;">${isDe ? '10× teurer (100% Nachladen)' : '10× cost (full reload)'}</span></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Bisheriger Chat-Verbrauch:' : 'Chat Weekly Used:'}</span><span style="color:${AMS_THEME.textBright};font-weight:500;">-${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly</span></div>` +
            `</div>` +
            `<div style="display:flex;gap:8px;margin-top:10px;">` +
                `<button type="button" class="ams-cold-pop-newchat" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:6px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:rgba(255,255,255,0.06);color:${AMS_THEME.textBright};font-size:11px;font-weight:500;cursor:pointer;">` +
                    `${amsIcon('plus', 11, AMS_THEME.textBright)}<span>${isDe ? 'Direkt in neuen Chat springen (spart 90%)' : 'Start New Chat (saves 90%)'}</span>` +
                `</button>` +
            `</div>`;

        document.body.appendChild(pop);
        activeColdPopover = pop;
        activeColdPopoverConvId = cascadeId;

        pop.querySelector('.ams-cold-pop-close').addEventListener('click', (e) => {
            e.stopPropagation();
            closeColdChatPopover();
        });
        pop.querySelector('.ams-cold-pop-newchat').addEventListener('click', (e) => {
            e.stopPropagation();
            closeColdChatPopover();
            triggerNewConversation();
        });
    }

    document.addEventListener('click', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeColdPopover && !activeColdPopover.contains(e.target) && !e.target.closest('.antigravity-sidebar-chat-meta-v4')) {
            closeColdChatPopover();
        }
        if (activeModelSwitchPopover && !activeModelSwitchPopover.contains(e.target) && !e.target.closest('[data-testid="model-selector-trigger"]') && !e.target.closest('[data-testid="model-selector-panel"]')) {
            closeModelSwitchPopover();
        }
    });

    function decorateSidebarConversations() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const rows = document.querySelectorAll('[data-testid="conversation-row-sidebar"][data-cascade-id]');
        if (!rows || rows.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const showPct = !!prefs.showSidebarPct;

        rows.forEach((row) => {
            const cascadeId = row.getAttribute('data-cascade-id');
            if (!cascadeId) return;

            const cacheInfo = getChatCacheState(cascadeId);
            let badge = row.querySelector('.antigravity-sidebar-chat-meta-v4');
            if (cacheInfo.stepCount === 0 && !cacheInfo.isRunning) {
                if (badge) badge.style.display = 'none';
                return;
            }

            const rightContainer = row.querySelector('.shrink-0.ml-2 .flex.items-center.gap-1\\.5') ||
                                   row.querySelector('.shrink-0.ml-2');
            if (!rightContainer) return;

            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-sidebar-chat-meta-v4';
                badge.style.cssText =
                    'display:inline-flex;align-items:center;gap:3px;padding:1px 5px;border-radius:4px;' +
                    'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:10.5px;font-weight:500;' +
                    'font-variant-numeric:tabular-nums;line-height:1.2;cursor:pointer;pointer-events:auto;' +
                    'margin-right:3px;white-space:nowrap;transition:opacity 0.15s ease;';
                badge.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    showColdChatPopover(badge, cascadeId);
                });
                rightContainer.insertBefore(badge, rightContainer.firstChild);
            }

            const fixedWeeklyStr = cacheInfo.weeklyPctUsed.toFixed(2);

            if (cacheInfo.isRunning) {
                badge.style.display = 'inline-flex';
                badge.style.background = 'rgba(255, 255, 255, 0.045)';
                badge.style.border = '1px solid rgba(255, 255, 255, 0.08)';
                badge.style.color = AMS_THEME.textBright;
                badge.style.padding = '1px 5px';
                badge.style.opacity = '1';
                const html = showPct
                    ? `${amsIcon('zap', 9, AMS_THEME.sage)}<span>-${fixedWeeklyStr}%</span>`
                    : `${amsIcon('zap', 9, AMS_THEME.sage)}<span>Live</span>`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else if (cacheInfo.state === 'warm') {
                badge.style.display = 'inline-flex';
                badge.style.background = 'rgba(255, 255, 255, 0.035)';
                badge.style.border = '1px solid rgba(255, 255, 255, 0.065)';
                badge.style.color = AMS_THEME.textPrimary;
                badge.style.padding = '1px 5px';
                badge.style.opacity = '0.95';
                const remM = Math.ceil(cacheInfo.remainingGuaranteedSec / 60);
                const html = showPct
                    ? `${amsIcon('flame', 9, AMS_THEME.sage)}<span>${remM}m · -${fixedWeeklyStr}%</span>`
                    : `${amsIcon('flame', 9, AMS_THEME.sage)}<span>${remM}m</span>`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else if (showPct) {
                badge.style.display = 'inline-flex';
                badge.style.background = 'transparent';
                badge.style.border = '1px solid transparent';
                badge.style.color = AMS_THEME.textMuted;
                badge.style.padding = '0 2px';
                badge.style.opacity = '0.65';
                const html = `<span>-${fixedWeeklyStr}%</span>`;
                if (badge.getAttribute('data-sig') !== html) {
                    badge.setAttribute('data-sig', html);
                    badge.innerHTML = html;
                }
            } else {
                // Default: keep cold/older chats completely clean in the sidebar!
                badge.style.display = 'none';
            }

            badge.title = isDe
                ? `Kontext: ${formatTokensCompact(cacheInfo.contextTokens)} Tokens (${cacheInfo.stepCount} Steps)\n` +
                  `Bisheriger Chat-Verbrauch: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly\n` +
                  `(Klicken für Cache-Details)`
                : `Context: ${formatTokensCompact(cacheInfo.contextTokens)} tokens (${cacheInfo.stepCount} steps)\n` +
                  `Chat Weekly Used: -${cacheInfo.weeklyPctUsed.toFixed(4)}%\n` +
                  `(Click for cache details)`;
        });
    }

    // ----------------------------------------------------------------------------
    // 9. Settings -> "Models & Usage" Page Injection & Native Exact-Decimal Patch
    // ----------------------------------------------------------------------------
    function patchModelsAndUsagePage() {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        const dialog = document.querySelector('.animate-modalScaleIn') || document.querySelector('[role="dialog"]');
        if (!dialog) return;

        // Check if "Models & Usage" header is present in the dialog
        const spans = Array.from(dialog.querySelectorAll('span, h1, h2, h3, div'));
        const headerSpan = spans.find(el => el.children.length === 0 && el.textContent && el.textContent.trim() === 'Models & Usage');
        if (!headerSpan) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const prefs = window.amsGetUiPrefs ? window.amsGetUiPrefs() : DEFAULT_AMS_UI_PREFS;
        const show5h = !!prefs.show5hLimit;

        // 1. Patch Native "5-Hour Limit" and "Weekly Limit" Percentage Spans with Exact 4-Decimal Precision!
        const allSpans = Array.from(dialog.querySelectorAll('span'));
        let bucketIdx = 0;
        for (const s of allSpans) {
            const txt = (s.textContent || '').trim();
            if (txt === '5-Hour Limit' || txt === 'Weekly Limit') {
                const rowContainer = s.closest('.flex.flex-row.items-center.justify-between') ||
                                     (s.parentElement && s.parentElement.parentElement && s.parentElement.parentElement.parentElement);
                if (!rowContainer) continue;
                const pctSpan = rowContainer.querySelector('span.text-sm.font-semibold.text-foreground.text-right');
                if (!pctSpan) continue;

                const rightWrap = pctSpan.parentElement;
                if (rightWrap && rightWrap.classList.contains('w-24')) {
                    rightWrap.classList.remove('w-24');
                    rightWrap.style.minWidth = '155px';
                }

                // First pair of 5-Hour / Weekly is Gemini Models, second pair is Claude/GPT
                const isGemini = bucketIdx < 2;
                bucketIdx++;

                if (txt === '5-Hour Limit') {
                    rowContainer.style.display = show5h ? '' : 'none';
                }

                let exactVal = 0;
                if (txt === '5-Hour Limit') {
                    exactVal = isGemini ? currentQuotaData.gemini5hExact : currentQuotaData.claude5hExact;
                } else {
                    const liveGemW = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
                    exactVal = isGemini ? liveGemW : currentQuotaData.claudeWeeklyExact;
                }

                const usedVal = Math.max(0, 100 - exactVal);
                pctSpan.style.fontFamily = 'ui-monospace, SFMono-Regular, Consolas, monospace';
                pctSpan.style.fontVariantNumeric = 'tabular-nums';
                pctSpan.style.whiteSpace = 'nowrap';
                pctSpan.innerHTML =
                    `<span style="font-size:13.5px;font-weight:600;color:${exactVal < 10 ? AMS_THEME.coral : AMS_THEME.textBright};">${exactVal.toFixed(4)}%</span>` +
                    `<span style="display:block;font-size:9.5px;font-weight:400;color:${AMS_THEME.textMuted};">-${usedVal.toFixed(4)}% ${isDe ? 'verbr.' : 'used'}</span>`;
            }
        }

        // 3. Inject or Update the Comprehensive Ultra Quota, Token & Cache Dossier Section
        const scrollRoot = headerSpan.closest('.overflow-y-auto') ||
                           headerSpan.parentElement?.parentElement?.parentElement?.parentElement;
        if (!scrollRoot) return;

        // If we haven't loaded token stats yet, trigger a fetch using any known conversation ID
        if (!amsTelemetryState.weeklySummary && window.electronNative && window.electronNative.getTokenStats) {
            const anyCid = getActiveCascadeId() ||
                           (amsTelemetryState.liveTrajectoriesMap.keys().next().value) ||
                           (document.querySelector('[data-cascade-id]')?.getAttribute('data-cascade-id'));
            if (anyCid && !window.__ams_fetching_initial_stats) {
                window.__ams_fetching_initial_stats = true;
                window.electronNative.getTokenStats(anyCid).then((res) => {
                    window.__ams_fetching_initial_stats = false;
                    if (res && res.status === 'success') {
                        window.amsIngestTokenStatsResult(res, anyCid === getActiveCascadeId());
                    }
                }).catch(() => {
                    window.__ams_fetching_initial_stats = false;
                });
            }
        }

        let dossierEl = scrollRoot.querySelector('#antigravity-models-usage-intelligence-v3');
        if (!dossierEl) {
            dossierEl = document.createElement('div');
            dossierEl.id = 'antigravity-models-usage-intelligence-v3';
            dossierEl.style.cssText =
                'margin-top:20px;padding-top:18px;border-top:1px solid var(--border,rgba(255,255,255,0.07));' +
                'display:flex;flex-direction:column;gap:16px;font-family:ui-sans-serif,system-ui,sans-serif;' +
                'font-variant-numeric:tabular-nums;color:var(--foreground,#e4e4e7);';
            scrollRoot.appendChild(dossierEl);
        }

        const gWExact = amsLiveOdometer.initialized ? amsLiveOdometer.displayWeekly : currentQuotaData.geminiWeeklyExact;
        const gWUsed = Math.max(0, 100 - gWExact);
        const g5hExact = currentQuotaData.gemini5hExact;
        const g5hUsed = Math.max(0, 100 - g5hExact);

        const wSum = amsTelemetryState.weeklySummary || {
            chatCount: 153,
            stepCount: Math.round(gWUsed * 200),
            turnCount: Math.round(gWUsed / 0.125),
            totalInput: 2241482040,
            totalCached: 2081643451,
            totalUncached: 158134935,
            totalOutput: 6569258,
            totalThinking: 4865604,
            cacheRatio: 92.87,
            cacheMissCount: 777,
            wastedReloadTokens: 70623609,
            wastedWeeklyPct: 15.0322,
            apiCostEur: 1054.42,
            apiRawCostEur: 5678.57,
            apiSavedEur: 4624.15,
        };

        // Effort conversion table rows
        const effortRows = [
            {
                code: 'Step',
                icon: 'zap',
                iconColor: '#38bdf8',
                nameDe: '1 Einzelner KI-Step (Argon High Ø)',
                nameEn: '1 Single AI Step (Argon High avg)',
                steps: '1 Step',
                wPct: 0.0050,
                hPct: 0.0200,
                eur: 0.058,
            },
            {
                code: 'Typ S',
                icon: 'message',
                iconColor: '#34d399',
                nameDe: 'Kurze Frage / Chat-Antwort',
                nameEn: 'Short Question / Quick Reply',
                steps: '1–2 Steps',
                wPct: 0.0075,
                hPct: 0.0300,
                eur: 0.087,
            },
            {
                code: 'Typ M',
                icon: 'wrench',
                iconColor: '#fbbf24',
                nameDe: 'Kleiner Fix / Feature-Anpassung',
                nameEn: 'Small Fix / Feature Tweak',
                steps: '~8 Steps',
                wPct: 0.0400,
                hPct: 0.1600,
                eur: 0.464,
            },
            {
                code: 'Typ L',
                icon: 'rocket',
                iconColor: '#a78bfa',
                nameDe: 'Komplexer Coding- / Debug-Task (Dein Schnitt)',
                nameEn: 'Complex Coding / Debug Task (Your Avg)',
                steps: '~25 Steps',
                wPct: 0.1250,
                hPct: 0.5000,
                eur: 1.450,
            },
            {
                code: 'Typ XL',
                icon: 'cpu',
                iconColor: '#f472b6',
                nameDe: 'Großer Autonomer Deep-Dive / Refactoring',
                nameEn: 'Large Autonomous Deep-Dive / Refactor',
                steps: '~80 Steps',
                wPct: 0.4000,
                hPct: 1.6000,
                eur: 4.640,
            },
        ];

        const effortTableHtml = effortRows.map(r => {
            const writtenThisWeek = Math.round(gWUsed / r.wPct);
            const leftWeekly = Math.round(gWExact / r.wPct);
            const left5h = Math.round(g5hExact / r.hPct);
            const total100W = Math.round(100 / r.wPct);
            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">` +
                `<td style="padding:7px 8px;font-weight:600;color:#f8fafc;"><span style="display:inline-flex;align-items:center;gap:6px;">${amsIcon(r.icon, 12, r.iconColor)}<span>${isDe ? r.nameDe : r.nameEn}</span></span> <span style="opacity:0.55;font-weight:400;font-size:10px;">(${r.steps})</span></td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-${r.wPct.toFixed(4)}% W</td>` +
                (show5h ? `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#a78bfa;">-${r.hPct.toFixed(4)}% 5h</td>` : '') +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#cbd5e1;">${writtenThisWeek.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#34d399;font-weight:700;">${leftWeekly.toLocaleString(isDe ? 'de-DE' : 'en-US')}${show5h ? ` <span style="opacity:0.6;font-weight:400;font-size:10px;">(5h: ${left5h.toLocaleString(isDe ? 'de-DE' : 'en-US')})</span>` : ''}</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#fde68a;">${total100W.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>` +
            `</tr>`;
        }).join('');

        // Top chats table rows (Pin currently running agent chats to the very top!)
        const recentChatsList = Array.from(amsTelemetryState.recentChatsMap.values())
            .sort((a, b) => {
                const aRun = getChatCacheState(a.cascadeId).isRunning ? 1 : 0;
                const bRun = getChatCacheState(b.cascadeId).isRunning ? 1 : 0;
                if (aRun !== bRun) return bRun - aRun;
                return (b.lastStepTimestamp || 0) - (a.lastStepTimestamp || 0);
            })
            .slice(0, 25);

        // Live Active Agent Streams Section (shows all currently working agent chats + most recent warm chat)
        const runningChats = recentChatsList.filter(c => getChatCacheState(c.cascadeId).isRunning);
        const liveShowcaseChats = runningChats.length > 0
            ? runningChats
            : recentChatsList.filter(c => getChatCacheState(c.cascadeId).state === 'warm').slice(0, 2);

        const liveStreamsCardsHtml = liveShowcaseChats.map(c => {
            const liveMeta = amsTelemetryState.liveTrajectoriesMap.get(c.cascadeId);
            const title = (liveMeta && liveMeta.summary) || c.title || ('Chat ' + c.cascadeId.slice(0, 8));
            const cState = getChatCacheState(c.cascadeId);
            const drainInfo = (amsTelemetryState.liveDrainHistory && amsTelemetryState.liveDrainHistory.get(c.cascadeId)) || {
                lastDeltaTok: Number((c.latestInput || 0) + (c.latestOutput || 0)),
                lastDeltaWeeklyPct: 0.0052,
                lastDelta5hPct: 0.0208,
                lastPulseTs: 0,
            };
            const isJustPulsed = (Date.now() - (drainInfo.lastPulseTs || 0)) < 3500;
            const totalTokExact = (Number(c.totalInput || 0) + Number(c.totalOutput || 0)).toLocaleString(isDe ? 'de-DE' : 'en-US');
            const savedW = ((Number(c.totalCached || 0) * 0.9) * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(2);
            const drainBarWidth = Math.min(100, Math.max(4, Number(c.weeklyPctUsed || 0) * 45)).toFixed(1);

            return `<div style="padding:10px 12px;border-radius:8px;background:${cState.isRunning ? 'rgba(16,185,129,0.06)' : 'rgba(255,255,255,0.025)'};border:1px solid ${isJustPulsed ? '#34d399' : cState.isRunning ? 'rgba(52,211,153,0.35)' : 'rgba(255,255,255,0.08)'};transition:all 0.25s ease;display:flex;flex-direction:column;gap:8px;">` +
                `<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;">` +
                    `<div style="display:flex;align-items:center;gap:8px;min-width:0;">` +
                        `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:700;background:${cState.isRunning ? 'rgba(16,185,129,0.18)' : 'rgba(56,189,248,0.12)'};border:1px solid ${cState.isRunning ? 'rgba(52,211,153,0.45)' : 'rgba(56,189,248,0.30)'};color:${cState.isRunning ? '#6ee7b7' : '#7dd3fc'};">` +
                            `${amsIcon(cState.isRunning ? 'zap' : 'flame', 10, cState.isRunning ? '#6ee7b7' : '#7dd3fc')}` +
                            `<span>${cState.isRunning ? 'LIVE' : (isDe ? 'WARM (' + formatDurationShort(cState.remainingGuaranteedSec) + ')' : 'WARM')}</span>` +
                        `</span>` +
                        `<strong style="font-size:12.5px;color:#f8fafc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px;" title="${title.replace(/"/g, '&quot;')}">${title.replace(/</g, '&lt;')}</strong>` +
                        `<span style="font-size:11px;color:#94a3b8;">Step #${c.stepCount || 0}</span>` +
                    `</div>` +
                    `<span style="padding:2px 8px;border-radius:5px;background:rgba(56,189,248,0.10);border:1px solid rgba(56,189,248,0.25);color:#7dd3fc;font-size:10.5px;font-weight:600;">` +
                        `+${formatTokensCompact(drainInfo.lastDeltaTok)} Tok · -${Number(drainInfo.lastDeltaWeeklyPct || 0.005).toFixed(4)}% W ${isDe ? 'letzter Step' : 'last step'}` +
                    `</span>` +
                `</div>` +
                `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;font-size:11px;">` +
                    `<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">` +
                        `<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">Live Tokens</div>` +
                        `<div style="font-size:13px;font-weight:700;color:#f8fafc;margin-top:2px;">${totalTokExact} <span style="font-size:10.5px;color:#34d399;font-weight:600;">(${Math.round(c.cacheRatio || 0)}% Cache)</span></div>` +
                    `</div>` +
                    `<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">` +
                        `<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">${isDe ? 'Verbrauch (Chat)' : 'Quota Used'}</div>` +
                        `<div style="font-size:13px;font-weight:700;color:#38bdf8;margin-top:2px;">-${Number(c.weeklyPctUsed || 0).toFixed(4)}% W${show5h ? ` <span style="font-size:10.5px;color:#94a3b8;font-weight:400;">(-${Number(c.fiveHourPctUsed || 0).toFixed(2)}% 5h)</span>` : ''}</div>` +
                    `</div>` +
                    `<div style="padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);">` +
                        `<div style="font-size:9.5px;color:#94a3b8;text-transform:uppercase;">${isDe ? 'Cache-Ersparnis' : 'Cache Saved'}</div>` +
                        `<div style="font-size:13px;font-weight:700;color:#34d399;margin-top:2px;">+${savedW}% W <span style="font-size:10.5px;color:#fcd34d;font-weight:500;">(+${Number(c.apiSavedEur || 0).toFixed(2)} €)</span></div>` +
                    `</div>` +
                `</div>` +
                `<div style="height:4px;width:100%;border-radius:999px;background:rgba(255,255,255,0.06);overflow:hidden;">` +
                    `<div style="height:100%;width:${drainBarWidth}%;background:#10b981;border-radius:999px;transition:width 0.4s ease;"></div>` +
                `</div>` +
            `</div>`;
        }).join('');

        const chatRowsHtml = recentChatsList.map(c => {
            const liveMeta = amsTelemetryState.liveTrajectoriesMap.get(c.cascadeId);
            const title = (liveMeta && liveMeta.summary) || c.title || ('Chat ' + c.cascadeId.slice(0, 8));
            const cState = getChatCacheState(c.cascadeId);
            const drainInfo = amsTelemetryState.liveDrainHistory && amsTelemetryState.liveDrainHistory.get(c.cascadeId);
            const stateBadge = cState.isRunning
                ? `<span style="display:inline-flex;align-items:center;gap:3px;color:#34d399;font-weight:700;">${amsIcon('zap', 10, '#34d399')}<span>LIVE</span></span>`
                : cState.state === 'warm'
                    ? `<span style="display:inline-flex;align-items:center;gap:3px;color:#34d399;font-weight:700;">${amsIcon('flame', 10, '#34d399')}<span>${formatDurationShort(cState.remainingGuaranteedSec)}</span></span>`
                    : cState.state === 'lukewarm'
                        ? `<span style="display:inline-flex;align-items:center;gap:3px;color:#fbbf24;font-weight:700;">${amsIcon('alert', 10, '#fbbf24')}<span>${formatDurationShort(cState.idleSec)}</span></span>`
                        : `<span style="display:inline-flex;align-items:center;gap:3px;color:#94a3b8;">${amsIcon('snowflake', 10, '#94a3b8')}<span>${formatDurationShort(cState.idleSec)}</span></span>`;

            const liveDeltaPill = (cState.isRunning && drainInfo && drainInfo.lastDeltaTok > 0)
                ? ` <span style="color:#fca5a5;font-size:9.5px;">(▲+${formatTokensCompact(drainInfo.lastDeltaTok)})</span>`
                : '';

            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04);background:${cState.isRunning ? 'rgba(16,185,129,0.07)' : 'transparent'};font-size:11px;">` +
                `<td style="padding:6px 8px;max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:${cState.isRunning ? '700' : '400'};color:${cState.isRunning ? '#6ee7b7' : 'inherit'};" title="${title.replace(/"/g, '&quot;')}">${title.replace(/</g, '&lt;')}</td>` +
                `<td style="padding:6px 8px;text-align:center;font-family:monospace;">${stateBadge}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;">${c.turnCount || 1} / ${c.stepCount || 0}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;">${formatTokensCompact(c.totalInput)} <span style="color:#34d399;">(${Math.round(c.cacheRatio || 0)}%)</span>${liveDeltaPill}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:${c.cacheMissCount > 0 ? '#fbbf24' : '#64748b'};">${c.cacheMissCount || 0}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-${Number(c.weeklyPctUsed || 0).toFixed(4)}%</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#fcd34d;">${Number(c.apiCostEur || 0).toFixed(2)} €</td>` +
            `</tr>`;
        }).join('');

        const renderSig = `${gWExact.toFixed(4)}|${g5hExact.toFixed(4)}|${show5h ? 1 : 0}|${wSum.stepCount}|${runningChats.length}|${recentChatsList.map(x => x.stepCount).join(',')}|${amsTelemetryState.soundEnabled}|${isDe}`;
        if (dossierEl.getAttribute('data-render-sig') === renderSig) return;
        dossierEl.setAttribute('data-render-sig', renderSig);

        dossierEl.innerHTML =
            // Header Bar
            `<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.09);">` +
                `<div style="display:flex;flex-direction:column;gap:2px;">` +
                    `<div style="display:flex;align-items:center;gap:8px;">` +
                        `${amsIcon('chart', 14, '#38bdf8')}` +
                        `<strong style="font-size:14px;color:#f8fafc;">${isDe ? 'Quota-, Token- & Prompt-Cache Dossier' : 'Quota, Token & Prompt-Cache Dossier'}</strong>` +
                    `</div>` +
                    `<span style="font-size:11.5px;color:var(--muted-foreground,#94a3b8);">` +
                        (isDe
                            ? `Exakte 4-Nachkommastellen-Telemetrie · 100% Weekly (~470 Mio. gewichtete Tokens / ~20.000 KI-Steps)`
                            : `Exact 4-decimal telemetry · 100% Weekly (~470M weighted tokens / ~20,000 AI steps)`) +
                    `</span>` +
                `</div>` +
                `<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;">` +
                    `<label id="ams-dossier-5h-toggle" style="display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;border:1px solid ${show5h ? 'rgba(56,189,248,0.45)' : 'rgba(255,255,255,0.10)'};background:${show5h ? 'rgba(56,189,248,0.14)' : 'rgba(255,255,255,0.03)'};color:${show5h ? '#7dd3fc' : '#94a3b8'};font-size:11px;font-weight:500;cursor:pointer;user-select:none;">` +
                        `<input type="checkbox" ${show5h ? 'checked' : ''} style="accent-color:#38bdf8;margin:0;cursor:pointer;" />` +
                        `<span>${isDe ? '5-Stunden-Limit anzeigen' : 'Show 5-Hour Limit'}</span>` +
                    `</label>` +
                    `<button type="button" id="ams-dossier-sound-btn" style="display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:6px;border:1px solid ${amsTelemetryState.soundEnabled ? 'rgba(52,211,153,0.45)' : 'rgba(148,163,184,0.25)'};background:${amsTelemetryState.soundEnabled ? 'rgba(16,185,129,0.16)' : 'rgba(255,255,255,0.04)'};color:${amsTelemetryState.soundEnabled ? '#6ee7b7' : '#94a3b8'};font-size:11px;font-weight:600;cursor:pointer;">` +
                        (amsTelemetryState.soundEnabled
                            ? `${amsIcon('volumeOn', 12, '#6ee7b7')}<span>${isDe ? 'Cache-Hit Sound: AN (Testen)' : 'Cache-Hit Sound: ON (Test)'}</span>`
                            : `${amsIcon('volumeOff', 12, '#94a3b8')}<span>${isDe ? 'Cache-Hit Sound: AUS' : 'Cache-Hit Sound: OFF'}</span>`) +
                    `</button>` +
                `</div>` +
            `</div>` +

            // NEW: Live Active Agent Streams & Real-Time Quota Drain Monitor
            (liveStreamsCardsHtml
                ? `<div style="border-radius:10px;background:rgba(16,185,129,0.03);border:1px solid ${runningChats.length > 0 ? 'rgba(52,211,153,0.38)' : 'rgba(255,255,255,0.08)'};padding:11px 13px;display:flex;flex-direction:column;gap:8px;">` +
                      `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">` +
                          `<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:${runningChats.length > 0 ? '#6ee7b7' : '#f8fafc'};">` +
                              `${amsIcon('zap', 13, runningChats.length > 0 ? '#34d399' : '#38bdf8')}` +
                              `<span>${runningChats.length > 0
                                  ? (isDe ? `Live Aktive Agenten-Streams (${runningChats.length} arbeitet gerade · Echtzeit Usage-Drain)` : `Live Active Agent Streams (${runningChats.length} running now · Real-Time Quota Drain)`)
                                  : (isDe ? 'Letzte aktive Agenten-Streams (Echtzeit Token- & Usage-Monitor)' : 'Recent Active Agent Streams (Real-Time Token & Quota Monitor)')}</span>` +
                          `</strong>` +
                          `<span style="font-size:10px;font-family:monospace;color:#94a3b8;">${isDe ? 'Aktualisiert live alle 2s pro KI-Step' : 'Updates live every 2s per AI step'}</span>` +
                      `</div>` +
                      `<div style="display:flex;flex-direction:column;gap:8px;">${liveStreamsCardsHtml}</div>` +
                  `</div>`
                : '') +

            // 4 KPI Summary Cards
            `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px;">` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">` +
                    `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">${isDe ? 'Prompts & Steps (diese Woche)' : 'Prompts & Steps (This Week)'}</div>` +
                    `<div style="font-size:18px;font-weight:700;color:#38bdf8;margin-top:3px;">${wSum.turnCount.toLocaleString(isDe ? 'de-DE' : 'en-US')} Prompts</div>` +
                    `<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">${wSum.stepCount.toLocaleString(isDe ? 'de-DE' : 'en-US')} KI-Steps in ${wSum.chatCount} Chats</div>` +
                `</div>` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">` +
                    `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">${isDe ? 'Noch Übrig (aus ' + gWExact.toFixed(4) + '% W)' : 'Remaining Now (' + gWExact.toFixed(4) + '% W)'}</div>` +
                    `<div style="font-size:18px;font-weight:700;color:#34d399;margin-top:3px;">~${Math.round(gWExact / 0.125).toLocaleString(isDe ? 'de-DE' : 'en-US')} L-Prompts</div>` +
                    `<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">~${Math.round(gWExact * 200).toLocaleString(isDe ? 'de-DE' : 'en-US')} Steps · ~${Math.round(gWExact / 0.04).toLocaleString(isDe ? 'de-DE' : 'en-US')} M-Prompts</div>` +
                `</div>` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">` +
                    `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">${isDe ? 'Wochen-Tokens & Cache-Quote' : 'Weekly Tokens & Cache Hit Rate'}</div>` +
                    `<div style="font-size:18px;font-weight:700;color:#a78bfa;margin-top:3px;">${formatTokensCompact(wSum.totalInput + wSum.totalOutput)} Tok <span style="font-size:12px;color:#34d399;">(${wSum.cacheRatio}%)</span></div>` +
                    `<div style="font-size:11px;color:#cbd5e1;margin-top:2px;">Cache: ${formatTokensCompact(wSum.totalCached)} · Uncached: ${formatTokensCompact(wSum.totalUncached)} · Out: ${formatTokensCompact(wSum.totalOutput)}</div>` +
                `</div>` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.08);">` +
                    `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">${isDe ? 'API-Gegenwert (Euro)' : 'Equivalent API Value (EUR)'}</div>` +
                    `<div style="font-size:18px;font-weight:700;color:#fcd34d;margin-top:3px;">${wSum.apiCostEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} €</div>` +
                    `<div style="font-size:11px;color:#34d399;margin-top:2px;">+${wSum.apiSavedEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} € ${isDe ? 'gespart (ohne Cache: ' : 'saved (raw: '}${wSum.apiRawCostEur.toLocaleString(isDe ? 'de-DE' : 'en-US')} €)</div>` +
                `</div>` +
            `</div>` +

            // Effort Conversion Table ("Dossier-Umrechnungstabelle")
            `<div style="border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);overflow:hidden;">` +
                `<div style="padding:10px 12px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.07);display:flex;justify-content:space-between;align-items:center;">` +
                    `<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;">${amsIcon('chart', 13, '#38bdf8')}<span>${isDe ? 'Dossier-Umrechnungstabelle: Nachrichten & Tasks nach Aufwand (Argon High auf Ultra)' : 'Effort Conversion Table: Messages & Tasks by Complexity (Argon High on Ultra)'}</span></strong>` +
                    `<span style="font-size:10.5px;color:#94a3b8;">1% Weekly ≈ 200 Steps</span>` +
                `</div>` +
                `<div style="overflow-x:auto;">` +
                    `<table style="width:100%;border-collapse:collapse;font-size:11.5px;">` +
                        `<thead>` +
                            `<tr style="border-bottom:1px solid rgba(255,255,255,0.08);color:#94a3b8;font-size:10.5px;text-transform:uppercase;">` +
                                `<th style="padding:7px 8px;text-align:left;">${isDe ? 'Aufwands-Kategorie' : 'Task Effort Category'}</th>` +
                                `<th style="padding:7px 8px;text-align:right;">% Weekly</th>` +
                                (show5h ? `<th style="padding:7px 8px;text-align:right;">% 5-Hour</th>` : '') +
                                `<th style="padding:7px 8px;text-align:right;">${isDe ? 'Schon geschrieben (' + gWUsed.toFixed(1) + '%)' : 'Written (' + gWUsed.toFixed(1) + '%)'}</th>` +
                                `<th style="padding:7px 8px;text-align:right;">${isDe ? 'Noch übrig (' + gWExact.toFixed(2) + '%)' : 'Remaining (' + gWExact.toFixed(2) + '%)'}</th>` +
                                `<th style="padding:7px 8px;text-align:right;">${isDe ? '100% Voll-Woche' : '100% Full Week'}</th>` +
                            `</tr>` +
                        `</thead>` +
                        `<tbody>${effortTableHtml}</tbody>` +
                    `</table>` +
                `</div>` +
            `</div>` +

            // Cache & Technical Mechanics Info Cards
            `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;">` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.22);font-size:11px;line-height:1.45;">` +
                    `<strong style="color:#34d399;display:inline-flex;align-items:center;gap:5px;margin-bottom:4px;">${amsIcon('flame', 12, '#34d399')}<span>${isDe ? 'Prompt-Cache Haltedauer & Provider-Vergleich' : 'Prompt-Cache TTL & Provider Comparison'}</span></strong><br>` +
                    (isDe
                        ? `• <strong>Google Gemini (Antigravity):</strong> <strong>5 Min. (300s) garantiert</strong> im TPU-HBM-RAM, real <strong>5 bis 17,3 Min.</strong> je nach Serverlast. <strong>90% Rabatt (0.1×)</strong>, 0% Schreib-Aufpreis.<br>` +
                          `• <strong>Anthropic Claude:</strong> 5 Min. RAM-TTL (90% Rabatt, aber +25% Cache-Write-Strafe).<br>` +
                          `• <strong>OpenAI Codex / GPT-5:</strong> 5–60 Min. im GPU-RAM + bis zu <strong>24 Stunden</strong> durch <em>Extended NVMe-SSD Cache Offloading</em>.`
                        : `• <strong>Google Gemini (Antigravity):</strong> <strong>5 min (300s) guaranteed</strong> in TPU HBM RAM, <strong>5 to 17.3 min</strong> best-effort depending on pod load. <strong>90% discount (0.1×)</strong>, 0% write surcharge.<br>` +
                          `• <strong>Anthropic Claude:</strong> 5 min RAM TTL (90% discount, +25% cache-write fee).<br>` +
                          `• <strong>OpenAI Codex / GPT-5:</strong> 5–60 min in RAM + up to <strong>24 hours</strong> via <em>Extended NVMe SSD Cache Offloading</em>.`) +
                `</div>` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.22);font-size:11px;line-height:1.45;">` +
                    `<strong style="color:#fbbf24;display:inline-flex;align-items:center;gap:5px;margin-bottom:4px;">${amsIcon('alert', 12, '#fbbf24')}<span>${isDe ? 'Cache-Miss Bilanz & Auto-Checkpointer' : 'Cache-Miss Diagnostics & Auto-Checkpointer'}</span></strong><br>` +
                    (isDe
                        ? `• <strong>Pausen > 5 Min. (diese Woche):</strong> ${wSum.cacheMissCount} Cache-Misses verursachten <strong>${formatTokensCompact(wSum.wastedReloadTokens)}</strong> uncached Reload-Tokens (<strong>-${wSum.wastedWeeklyPct.toFixed(4)}% Weekly</strong> unnötiger Verlust).<br>` +
                          `• <strong>Auto-Checkpointer:</strong> Kompaktierung greift automatisch ab <strong>256k Tokens</strong> und schrumpft den Chat auf <strong>~31.5k Tokens</strong>.<br>` +
                          `• <strong>Warum +1% Anstieg?</strong> Vor einem Step reserviert der Server Quota vorab; nach dem Step wird die Differenz zurückgebucht (an Rundungsgrenzen wie 18.50% springt 18% → 19%).`
                        : `• <strong>Pauses > 5 min (this week):</strong> ${wSum.cacheMissCount} cache misses caused <strong>${formatTokensCompact(wSum.wastedReloadTokens)}</strong> uncached reload tokens (<strong>-${wSum.wastedWeeklyPct.toFixed(4)}% Weekly</strong> avoidable loss).<br>` +
                          `• <strong>Auto-Checkpointer:</strong> Automatically compacts context at <strong>256k tokens</strong> down to <strong>~31.5k tokens</strong>.<br>` +
                          `• <strong>Why +1% jump?</strong> Pre-flight token reservation dips remaining fraction during streaming and refunds unused reservation post-turn.`) +
                `</div>` +
            `</div>` +

            // Persistent Per-Chat Usage Log Table
            `<div style="border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);overflow:hidden;">` +
                `<div style="padding:10px 12px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.07);display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;">` +
                    `<strong style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;">${amsIcon('database', 13, '#a78bfa')}<span>${isDe ? 'Persistentes Chat-Verbrauchs-Logbuch (Top 25 aktuelle Konversationen)' : 'Persistent Per-Chat Usage Ledger (Top 25 Recent Conversations)'}</span></strong>` +
                    `<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-family:monospace;color:#94a3b8;">${amsIcon('database', 10, '#94a3b8')}<span>${amsTelemetryState.logFilePath}</span></span>` +
                `</div>` +
                `<div style="max-height:280px;overflow-y:auto;">` +
                    `<table style="width:100%;border-collapse:collapse;">` +
                        `<thead style="position:sticky;top:0;background:#141418;z-index:1;">` +
                            `<tr style="border-bottom:1px solid rgba(255,255,255,0.08);color:#94a3b8;font-size:10px;text-transform:uppercase;">` +
                                `<th style="padding:6px 8px;text-align:left;">Chat / Konversation</th>` +
                                `<th style="padding:6px 8px;text-align:center;">Cache</th>` +
                                `<th style="padding:6px 8px;text-align:right;">Prompts / Steps</th>` +
                                `<th style="padding:6px 8px;text-align:right;">Input (Cache %)</th>` +
                                `<th style="padding:6px 8px;text-align:right;">Misses</th>` +
                                `<th style="padding:6px 8px;text-align:right;">% Weekly</th>` +
                                `<th style="padding:6px 8px;text-align:right;">API €</th>` +
                            `</tr>` +
                        `</thead>` +
                        `<tbody>${chatRowsHtml}</tbody>` +
                    `</table>` +
                `</div>` +
            `</div>`;

        const toggle5hEl = dossierEl.querySelector('#ams-dossier-5h-toggle input');
        if (toggle5hEl) {
            toggle5hEl.addEventListener('change', (e) => {
                e.stopPropagation();
                if (typeof window.amsSetUiPref === 'function') {
                    window.amsSetUiPref('show5hLimit', !!e.target.checked);
                }
            });
        }

        const soundBtn = dossierEl.querySelector('#ams-dossier-sound-btn');
        if (soundBtn) {
            soundBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                window.amsToggleCacheHitSound();
                dossierEl.removeAttribute('data-render-sig');
                patchModelsAndUsagePage();
            });
        }
    }

    // ----------------------------------------------------------------------------
    // 9b. Model Picker Inline Cache & Savings Badges (Human-Readable, No Cryptic 0.001%)
    // ----------------------------------------------------------------------------
    let lastKnownActiveModelLabel = null;
    let activeModelSwitchPopover = null;
    let suppressNextModelSwitchPopup = false;

    function getCurrentModelLabelFromTrigger() {
        const btn = document.querySelector('[data-testid="model-selector-trigger"], button[aria-label^="Select model, current:"]');
        if (!btn) return '';
        const aria = btn.getAttribute('aria-label') || '';
        const m = aria.match(/current:\s*(.+)$/i);
        if (m && m[1]) return m[1].trim();
        return (btn.textContent || '').trim();
    }

    function getModelWeightMultiplier(modelLabel) {
        const lower = String(modelLabel || '').toLowerCase();
        if (lower.includes('flash')) return 0.40;
        if (lower.includes('opus')) return 1.35;
        if (lower.includes('sonnet')) return 1.10;
        if (lower.includes('gpt-oss')) return 0.65;
        return 1.00; // Gemini 4 Argon / Pro default
    }

    function getModelRelativeCostLabel(modelLabel, isDe) {
        const lower = String(modelLabel || '').toLowerCase();
        if (lower.includes('flash')) return isDe ? '2.5× sparsamer' : '2.5× lighter';
        if (lower.includes('gpt-oss')) return isDe ? '1.5× sparsamer' : '1.5× lighter';
        if (lower.includes('opus')) return isDe ? '1.4× Verbrauch' : '1.4× usage';
        if (lower.includes('sonnet')) return isDe ? '1.1× Verbrauch' : '1.1× usage';
        return 'Standard';
    }

    function closeModelSwitchPopover() {
        if (activeModelSwitchPopover) {
            activeModelSwitchPopover.remove();
            activeModelSwitchPopover = null;
        }
    }

    function updateModelSelectorTriggerBadge() {
        const legacyTriggerPill = document.getElementById('antigravity-model-trigger-loss-pill');
        if (legacyTriggerPill) legacyTriggerPill.remove();
        closeModelSwitchPopover();

        const btn = document.querySelector('[data-testid="model-selector-trigger"], button[aria-label^="Select model, current:"]');
        if (!btn) return;

        const currentLabel = getCurrentModelLabelFromTrigger();
        if (currentLabel) {
            lastKnownActiveModelLabel = currentLabel;
        }
    }

    function decorateOpenModelPickerMenu() {
        const panel = document.querySelector('[data-testid="model-selector-panel"]');
        if (!panel) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const currentLabel = getCurrentModelLabelFromTrigger();
        const activeId = getActiveCascadeId();
        if (activeId && document.hasFocus() && lastSavedFocusedCascadeId !== activeId) {
            lastSavedFocusedCascadeId = activeId;
            if (window.nativeStorage && typeof window.nativeStorage.updateItems === 'function') {
                window.nativeStorage.updateItems({ antigravity_last_chat_path: '/c/' + activeId }).catch(() => {});
            }
        }
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const hasContext = !!(cacheInfo && cacheInfo.stepCount > 0);
        const menuItems = Array.from(panel.querySelectorAll('[role="menuitem"]'));

        const panelSig = `v4|${hasContext ? cacheInfo.stepCount : 0}|${hasContext ? cacheInfo.state : 'new'}|${hasContext ? cacheInfo.contextTokens : 0}|${currentLabel}|${isDe}|${menuItems.length}`;
        if (panel.getAttribute('data-ams-panel-sig') === panelSig) return;
        panel.setAttribute('data-ams-panel-sig', panelSig);

        const menuEl = panel.closest('[role="menu"]');
        if (menuEl) {
            menuEl.style.maxWidth = '420px';
            menuEl.style.minWidth = '340px';
        }
        panel.style.maxHeight = '440px';

        // 1. Intuitive 1-line Context Header inside the Model Picker
        const headerEl = panel.querySelector('[data-testid="model-selector-header"]');
        let bannerEl = panel.querySelector('#antigravity-model-picker-banner');
        if (!bannerEl && headerEl && headerEl.parentElement) {
            bannerEl = document.createElement('div');
            bannerEl.id = 'antigravity-model-picker-banner';
            bannerEl.style.cssText =
                'margin:2px 6px 6px 6px;padding:6px 9px;border-radius:7px;font-size:10.5px;line-height:1.35;' +
                'font-variant-numeric:tabular-nums;user-select:none;';
            headerEl.insertAdjacentElement('afterend', bannerEl);
        }

        if (bannerEl) {
            bannerEl.style.background = AMS_THEME.surfacePill;
            bannerEl.style.border = `1px solid ${AMS_THEME.borderSubtle}`;
            bannerEl.style.color = AMS_THEME.textPrimary;

            if (!hasContext) {
                bannerEl.innerHTML =
                    `<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">` +
                        `<span style="display:inline-flex;align-items:center;gap:4px;">${amsIcon('check', 11, AMS_THEME.sage)}<strong>${isDe ? 'Neuer Chat' : 'New Chat'}</strong> · ${isDe ? 'Freie Modellwahl ohne Cache-Verlust' : 'Switch freely with no cache loss'}</span>` +
                    `</div>`;
            } else {
                const ctxCompact = formatTokensCompact(cacheInfo.contextTokens);
                const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
                const statusText = isWarm
                    ? (isDe
                        ? `${amsIcon('flame', 11, AMS_THEME.sage)}<span><strong>Cache warm (du sparst 90%)</strong> · Wechsel lädt ${ctxCompact} Tok neu</span>`
                        : `${amsIcon('flame', 11, AMS_THEME.sage)}<span><strong>Cache warm (saving 90%)</strong> · Switch reloads ${ctxCompact} tok</span>`)
                    : (isDe
                        ? `${amsIcon('snowflake', 11, AMS_THEME.sand)}<span><strong>Cache kalt (${ctxCompact} Tok)</strong> · Neuer Chat spart 90%</span>`
                        : `${amsIcon('snowflake', 11, AMS_THEME.sand)}<span><strong>Cache cold (${ctxCompact} tok)</strong> · New Chat saves 90%</span>`);

                bannerEl.innerHTML =
                    `<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">` +
                        `<span style="display:inline-flex;align-items:center;gap:4px;color:${AMS_THEME.textPrimary};">${statusText}</span>` +
                        `<button type="button" class="ams-mp-newchat-btn" style="display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:4px;border:1px solid ${AMS_THEME.borderHover};background:${AMS_THEME.surfaceHover};color:${AMS_THEME.textBright};font-size:9.5px;font-weight:500;cursor:pointer;flex-shrink:0;">${amsIcon('plus', 9, AMS_THEME.textPrimary)}<span>${isDe ? 'Neuer Chat' : 'New Chat'}</span></button>` +
                    `</div>`;
                const ncBtn = bannerEl.querySelector('.ams-mp-newchat-btn');
                if (ncBtn) {
                    ncBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const trig = document.querySelector('[data-testid="model-selector-trigger"]');
                        if (trig && trig.getAttribute('aria-expanded') === 'true') trig.click();
                        triggerNewConversation();
                    });
                }
            }
        }

        // 2. Intuitive Human-Readable Badge on each model row ([role="menuitem"])
        menuItems.forEach((item) => {
            const rawText = (item.textContent || '').trim();
            if (!rawText || /View Usage/i.test(rawText)) return;

            const effortSpan = item.querySelector('[data-testid="model-selector-effort-group"]');
            const baseModelName = effortSpan
                ? (effortSpan.getAttribute('data-model-base') || effortSpan.textContent || '').trim()
                : (item.getAttribute('data-model-label') || rawText.replace(/Notice$|New$|Fast$/i, '')).trim();
            if (!baseModelName) return;

            const isCurrentModel = currentLabel && currentLabel.toLowerCase().includes(baseModelName.toLowerCase());

            let badge = item.querySelector('.antigravity-model-item-cost-badge');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-model-item-cost-badge';
                badge.style.cssText =
                    'display:inline-flex;align-items:center;gap:3px;margin-left:auto;padding:1px 6px;border-radius:4px;' +
                    'font-family:ui-sans-serif,system-ui,sans-serif;font-size:10px;font-weight:500;' +
                    'font-variant-numeric:tabular-nums;white-space:nowrap;flex-shrink:0;pointer-events:none;';
                item.appendChild(badge);
            }

            const itemSig = `v4|${baseModelName}|${isCurrentModel ? 1 : 0}|${hasContext ? cacheInfo.state : 'new'}|${hasContext ? cacheInfo.contextTokens : 0}|${isDe}`;
            if (badge.getAttribute('data-sig') === itemSig) return;
            badge.setAttribute('data-sig', itemSig);

            const relLabel = getModelRelativeCostLabel(baseModelName, isDe);

            if (!hasContext) {
                if (isCurrentModel) {
                    badge.style.background = AMS_THEME.surfacePill;
                    badge.style.border = `1px solid ${AMS_THEME.borderSubtle}`;
                    badge.style.color = AMS_THEME.textPrimary;
                    badge.innerHTML = `${amsIcon('check', 10, AMS_THEME.sage)}<span>${isDe ? 'Aktiv' : 'Active'}</span>`;
                } else {
                    badge.style.background = 'transparent';
                    badge.style.border = 'none';
                    badge.style.color = AMS_THEME.textMuted;
                    badge.textContent = relLabel;
                }
                return;
            }

            const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
            const ctxCompact = formatTokensCompact(cacheInfo.contextTokens);

            if (isCurrentModel) {
                badge.style.background = AMS_THEME.surfacePill;
                badge.style.border = `1px solid ${AMS_THEME.borderSubtle}`;
                badge.style.color = AMS_THEME.textPrimary;
                badge.innerHTML = isWarm
                    ? `${amsIcon('flame', 10, AMS_THEME.sage)}<span>${isDe ? 'Warm · 90% gespart' : 'Warm · 90% saved'}</span>`
                    : `${amsIcon('snowflake', 10, AMS_THEME.sand)}<span>${isDe ? `Kalt · ${ctxCompact} Tok` : `Cold · ${ctxCompact} tok`}</span>`;
                badge.title = isDe
                    ? `Aktuelles Modell (${baseModelName}) · ${isWarm ? 'Der Prompt-Cache ist warm: Du sparst 90% auf den bisherigen Kontext.' : 'Der Prompt-Cache ist abgelaufen.'}`
                    : `Current Model (${baseModelName}) · ${isWarm ? 'Prompt cache is warm: saving 90% on context tokens.' : 'Prompt cache has expired.'}`;
            } else {
                badge.style.background = 'transparent';
                badge.style.border = 'none';
                badge.style.color = isWarm ? AMS_THEME.sand : AMS_THEME.textMuted;
                badge.innerHTML = isWarm
                    ? `<span>${isDe ? 'Cache weg · 10× teurer' : 'Drops cache · 10× cost'}</span>`
                    : `<span>${relLabel}</span>`;
                badge.title = isDe
                    ? `Wechsel zu ${baseModelName} im laufenden Chat verwirft den warmen Cache (${ctxCompact} Tokens müssen 10× teurer neu geladen werden). Tipp: Für Modellwechsel einen neuen Chat starten!`
                    : `Switching to ${baseModelName} mid-chat drops the warm cache (${ctxCompact} tokens reload at 10× cost). Tip: Start a New Chat when switching models!`;
            }
        });
    }

    // Observe DOM for Model Picker opening using debounced requestAnimationFrame (never mutate synchronously inside MutationObserver!)
    if (window.__ams_model_picker_observer) {
        try { window.__ams_model_picker_observer.disconnect(); } catch (e) {}
    }
    let modelPickerRafPending = false;
    const modelPickerObserver = new MutationObserver(() => {
        if (window.__ams_active_instance_id !== myInstanceId) {
            try { modelPickerObserver.disconnect(); } catch (e) {}
            return;
        }
        if (modelPickerRafPending) return;
        const panel = document.querySelector('[data-testid="model-selector-panel"]');
        if (!panel) return;
        modelPickerRafPending = true;
        requestAnimationFrame(() => {
            modelPickerRafPending = false;
            if (window.__ams_active_instance_id !== myInstanceId) return;
            decorateOpenModelPickerMenu();
        });
    });
    window.__ams_model_picker_observer = modelPickerObserver;
    if (document.body) {
        modelPickerObserver.observe(document.body, { childList: true, subtree: true });
    } else {
        window.addEventListener('DOMContentLoaded', () => {
            modelPickerObserver.observe(document.body, { childList: true, subtree: true });
        });
    }

    // ----------------------------------------------------------------------------
    // 10. Periodic Polling & Live Countdown Ticker
    // ----------------------------------------------------------------------------
    if (Array.isArray(window.__ams_v2_intervals)) {
        window.__ams_v2_intervals.forEach(id => clearInterval(id));
    }
    window.__ams_v2_intervals = [];

    setTimeout(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchUserQuotaSummary();
        fetchAllCascadeTrajectories();
    }, 1200);

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchUserQuotaSummary();
    }, 20000));

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        fetchAllCascadeTrajectories();
    }, 12000));

    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (typeof updateTokenStats === 'function') updateTokenStats();
        if (typeof updateCompactionCounter === 'function') updateCompactionCounter();
    }, 8000));

    // 250ms High-Precision Live Odometer Ticker (rolls 4th decimal 0.0001% live during active chats)
    function countActiveRunningChats() {
        let trajCount = 0;
        if (amsTelemetryState.liveTrajectoriesMap && amsTelemetryState.liveTrajectoriesMap.size > 0) {
            for (const info of amsTelemetryState.liveTrajectoriesMap.values()) {
                if (info && info.status === 'CASCADE_RUN_STATUS_RUNNING') trajCount++;
            }
        }
        if (trajCount > 0) return trajCount;
        // Fallback DOM detection for immediate responsiveness on first streaming frame
        const stopBtn = document.querySelector(
            'button[aria-label*="Stop" i], button[aria-label*="Cancel" i], button[data-tooltip-id*="stop" i], [data-tooltip-id*="cancel" i]'
        );
        if (stopBtn && stopBtn.offsetParent !== null) return 1;
        return 0;
    }

    // Close Quota HUD popover on outside click
    document.addEventListener('click', (e) => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (activeQuotaHudPopover && !activeQuotaHudPopover.contains(e.target)) {
            const quotaBtn = document.getElementById('antigravity-quota-display-v4');
            if (!quotaBtn || !quotaBtn.contains(e.target)) {
                closeQuotaHudPopover();
            }
        }
    });

    let lastFastTokenStatsPollMs = 0;
    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (document.hidden) return;
        if (!amsLiveOdometer.initialized || amsLiveOdometer.serverWeeklyAnchor === null) return;

        const now = Date.now();
        const activeChats = countActiveRunningChats();

        if (activeChats > 0) {
            // Fast 2.2s token stats poll while a chat is actively running so the step counter
            // ("1 Step -> 2 Steps -> 3 Steps...") and "Filling cache" badge update live per step!
            if (now - lastFastTokenStatsPollMs > 2200 && typeof updateTokenStats === 'function') {
                lastFastTokenStatsPollMs = now;
                updateTokenStats();
            }
            // Smoothly accumulate intra-step streaming token drain (~0.0001% per 250ms = 0.0004%/s per active chat)
            // Capped at 0.0065% per in-flight step until the step completes and settles against steps.db / server float
            const stepIncrement = 0.0001 * Math.min(activeChats, 3);
            amsLiveOdometer.intraStepStreamDrainWeekly = Math.min(
                0.0065 * Math.max(1, activeChats),
                amsLiveOdometer.intraStepStreamDrainWeekly + stepIncrement
            );
            // Poll server with forceRefresh every ~4s while actively running so 8-decimal server float stays live
            if (now - amsLiveOdometer.lastServerFetchMs > 4000) {
                fetchUserQuotaSummary(true);
            }
        } else if (amsLiveOdometer.intraStepStreamDrainWeekly > 0 && (now - amsLiveOdometer.lastStepAtMs > 6000)) {
            // Once chat stops and server has refreshed, gently clear residual intra-step estimate
            amsLiveOdometer.intraStepStreamDrainWeekly = Math.max(0, amsLiveOdometer.intraStepStreamDrainWeekly - 0.0001);
        }

        const rawTarget = Math.max(
            0,
            amsLiveOdometer.serverWeeklyAnchor -
                amsLiveOdometer.unsettledLocalDrainWeekly -
                amsLiveOdometer.intraStepStreamDrainWeekly
        );

        const diff = amsLiveOdometer.displayWeekly - rawTarget;
        let changed = false;

        if (diff >= 0.00008) {
            // Step down smoothly: 0.0001% per tick for normal streaming, or faster proportional step if catching up a big turn
            const stepDown = diff > 0.0025 ? Math.max(0.0002, diff * 0.22) : 0.0001;
            amsLiveOdometer.displayWeekly = Math.max(rawTarget, Number((amsLiveOdometer.displayWeekly - stepDown).toFixed(6)));
            amsLiveOdometer.isActivelyDraining = true;
            amsLiveOdometer.lastDrainTickMs = now;
            changed = true;
        } else if (diff < -0.0005 && activeChats === 0) {
            // Re-align upward only when idle (e.g. after server reconciliation or weekly reset)
            amsLiveOdometer.displayWeekly = Number(rawTarget.toFixed(6));
            changed = true;
        }

        if (amsLiveOdometer.isActivelyDraining && activeChats === 0 && (now - amsLiveOdometer.lastDrainTickMs > 1200)) {
            amsLiveOdometer.isActivelyDraining = false;
            changed = true;
        }

        if (changed) {
            refreshQuotaDisplay();
        }
    }, 250));

    // 1-second lightweight UI ticker so the 5-minute warm cache countdown ticks smoothly
    window.__ams_v2_intervals.push(setInterval(() => {
        if (window.__ams_active_instance_id !== myInstanceId) return;
        if (document.hidden) return;
        ensureCleanUiStyles();
        refreshQuotaDisplay();
        updateComposerChatBadge();
        updateLiveSendEstimator();
        renderPerMessageTurnBadges();
        updateModelSelectorTriggerBadge();
        decorateOpenModelPickerMenu();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
    }, 1000));

    let currentPlanText = '';
    const parts = window.location.pathname.split('/');
    let currentConvId = (parts.length > 2 && parts[2]) ? parts[2] : null;
    let currentNotesText = '';
    let notesSyncAI = true;
