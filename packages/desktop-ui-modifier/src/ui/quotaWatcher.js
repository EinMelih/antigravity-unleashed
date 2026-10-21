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

    const amsTelemetryState = {
        activeConvStats: null,
        weeklySummary: null,
        allTimeSummary: null,
        recentChatsMap: new Map(),
        liveTrajectoriesMap: new Map(), // cascadeId -> { summary, status, lastModifiedEpoch, stepCount }
        lastObservedStepByConv: new Map(),
        lastCacheHitFlashTs: 0,
        logFilePath: '~/.gemini/config/quota_usage_log.json',
        soundEnabled: (() => {
            try {
                return localStorage.getItem('ams_cache_sound_enabled') !== '0';
            } catch (_) {
                return true;
            }
        })(),
    };

    window.amsTelemetryState = amsTelemetryState;

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
    };

    function amsIcon(name, size = 11, color = 'currentColor') {
        const p = AMS_LUCIDE_PATHS[name] || AMS_LUCIDE_PATHS.zap;
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-1.5px;flex-shrink:0;">${p}</svg>`;
    }

    function ensureCleanUiStyles() {
        let st = document.getElementById('ams-clean-ui-override');
        if (!st) {
            st = document.createElement('style');
            st.id = 'ams-clean-ui-override';
            (document.head || document.documentElement).appendChild(st);
        }
        const css =
            '.antigravity-cache-hit-toast,' +
            '.antigravity-ultra-badge,' +
            '.ams-models-ultra-pill,' +
            '.antigravity-quota-display,' +
            '.antigravity-turn-cost-badge,' +
            '#antigravity-chat-token-counter,' +
            '#antigravity-live-send-estimator,' +
            '#antigravity-model-trigger-loss-pill,' +
            '#antigravity-model-switch-popover,' +
            '.antigravity-sidebar-chat-meta,' +
            '#antigravity-models-usage-intelligence {' +
            '  display: none !important;' +
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
    const originalFetch = window.fetch;

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

    async function fetchUserQuotaSummary() {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT',
                },
                body: buildGrpcWebJsonFrame({ forceRefresh: false }),
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

    let runningPollTimer = null;
    function scheduleRunningConvPoll() {
        if (runningPollTimer) return;
        runningPollTimer = setTimeout(async () => {
            runningPollTimer = null;
            let stillRunning = false;
            for (const [cid, info] of amsTelemetryState.liveTrajectoriesMap.entries()) {
                if (info.isRunning && window.electronNative && window.electronNative.getTokenStats) {
                    stillRunning = true;
                    try {
                        const res = await window.electronNative.getTokenStats(cid);
                        if (res && res.status === 'success') {
                            window.amsIngestTokenStatsResult(res, cid === currentConvId);
                        }
                    } catch (_) {}
                }
            }
            fetchUserQuotaSummary();
            // Keep polling every 2s while any agent chat is actively working so the user sees tokens & % climb live!
            if (stillRunning) {
                fetchAllCascadeTrajectories();
            }
        }, 2000);
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
                    currentQuotaData.geminiWeeklyFraction = weeklyBucket.remainingFraction;
                    currentQuotaData.geminiWeeklyExact = Number((weeklyBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.geminiWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                    currentQuotaData.geminiWeeklyDesc = weeklyBucket.description || '';
                }
                if (fiveHourBucket && typeof fiveHourBucket.remainingFraction === 'number') {
                    currentQuotaData.gemini5hFraction = fiveHourBucket.remainingFraction;
                    currentQuotaData.gemini5hExact = Number((fiveHourBucket.remainingFraction * 100).toFixed(4));
                    currentQuotaData.gemini5h = Math.round(fiveHourBucket.remainingFraction * 100);
                    currentQuotaData.gemini5hDesc = fiveHourBucket.description || '';
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
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
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
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        const flexContainer = addContextBtn ? addContextBtn.parentElement : null;
        if (!flexContainer) return;

        let quotaEl = document.getElementById('antigravity-quota-display-v2');
        if (!quotaEl) {
            quotaEl = document.createElement('div');
            quotaEl.id = 'antigravity-quota-display-v2';
            quotaEl.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
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
            });
            flexContainer.appendChild(quotaEl);
        } else if (quotaEl.parentElement !== flexContainer) {
            flexContainer.appendChild(quotaEl);
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const g5hExact = currentQuotaData.gemini5hExact;
        const gWExact = currentQuotaData.geminiWeeklyExact;
        const g5hReset = cleanResetTime(currentQuotaData.gemini5hDesc);
        const gWReset = cleanResetTime(currentQuotaData.geminiWeeklyDesc);

        const remStepsW = Math.round(gWExact * 200);
        const remPromptsS = Math.round(gWExact / 0.0075);
        const remPromptsM = Math.round(gWExact / 0.040);
        const remPromptsL = Math.round(gWExact / 0.125);
        const remPromptsXL = Math.round(gWExact / 0.400);

        const tooltipText = isDe
            ? `✦ Google AI Ultra · Gemini Quota (Exakt):\n` +
              `• Weekly-Limit: ${gWExact.toFixed(4)}% übrig (-${(100 - gWExact).toFixed(4)}% verbraucht · Reset: ${gWReset})\n` +
              `• 5-Stunden-Limit: ${g5hExact.toFixed(4)}% übrig (-${(100 - g5hExact).toFixed(4)}% verbraucht · Reset: ${g5hReset})\n\n` +
              `Verbleibendes Ultra-Kontingent (aus ${gWExact.toFixed(2)}% Weekly):\n` +
              `• ~${remStepsW.toLocaleString('de-DE')} Agent-Steps\n` +
              `• ~${remPromptsS.toLocaleString('de-DE')} Kurze Prompts (Typ S · 1–2 Steps)\n` +
              `• ~${remPromptsM.toLocaleString('de-DE')} Kleine Tasks (Typ M · ~8 Steps)\n` +
              `• ~${remPromptsL.toLocaleString('de-DE')} Komplexe Coding-Tasks (Typ L · ~25 Steps)\n` +
              `• ~${remPromptsXL.toLocaleString('de-DE')} Große Deep-Dives (Typ XL · ~80 Steps)\n` +
              `(Klicken für das vollständige Models & Usage Dossier)`
            : `✦ Google AI Ultra · Gemini Quota (Exact):\n` +
              `• Weekly Limit: ${gWExact.toFixed(4)}% left (-${(100 - gWExact).toFixed(4)}% used · Reset: ${gWReset})\n` +
              `• 5-Hour Limit: ${g5hExact.toFixed(4)}% left (-${(100 - g5hExact).toFixed(4)}% used · Reset: ${g5hReset})\n\n` +
              `Remaining Ultra Capacity (from ${gWExact.toFixed(2)}% Weekly):\n` +
              `• ~${remStepsW.toLocaleString('en-US')} Agent Steps\n` +
              `• ~${remPromptsS.toLocaleString('en-US')} Quick Prompts (Type S · 1–2 steps)\n` +
              `• ~${remPromptsM.toLocaleString('en-US')} Small Tasks (Type M · ~8 steps)\n` +
              `• ~${remPromptsL.toLocaleString('en-US')} Complex Coding Tasks (Type L · ~25 steps)\n` +
              `• ~${remPromptsXL.toLocaleString('en-US')} Autonomous Deep-Dives (Type XL · ~80 steps)\n` +
              `(Click to open full Models & Usage Dossier)`;

        function getPercentColorHex(pct) {
            if (pct > 45) return '#34d399';
            if (pct > 20) return '#fbbf24';
            return '#f87171';
        }

        quotaEl.style.cssText =
            'display:inline-flex;align-items:center;gap:5px;margin-left:6px;margin-right:4px;' +
            'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;' +
            'white-space:nowrap;flex-shrink:0;user-select:none;cursor:pointer;';
        quotaEl.title = tooltipText;

        // Unified Single-Line Quota Pill (Weekly + 5h — never wraps, never collides with right buttons)
        const unifiedQuotaPill = document.createElement('span');
        unifiedQuotaPill.className = 'antigravity-quota-pill-v2';
        unifiedQuotaPill.style.cssText =
            'display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 8px;border-radius:5px;' +
            'background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.09);font-size:10.5px;white-space:nowrap;';
        unifiedQuotaPill.innerHTML =
            `<span style="display:inline-flex;align-items:center;gap:3px;">` +
                `<span style="color:#94a3b8;font-weight:500;">W</span>` +
                `<strong style="color:${getPercentColorHex(gWExact)};font-weight:700;">${gWExact.toFixed(2)}%</strong>` +
            `</span>` +
            `<span style="opacity:0.25;">·</span>` +
            `<span style="display:inline-flex;align-items:center;gap:3px;">` +
                `<span style="color:#94a3b8;font-weight:500;">5h</span>` +
                `<strong style="color:${getPercentColorHex(g5hExact)};font-weight:600;">${g5hExact.toFixed(1)}%</strong>` +
            `</span>`;

        quotaEl.replaceChildren(unifiedQuotaPill);

        // Keep legacy inline toolbar elements hidden so the button row never overflows
        const legacyChatTokenEl = document.getElementById('antigravity-chat-token-counter');
        if (legacyChatTokenEl) legacyChatTokenEl.style.display = 'none';
        const legacyEstimatorEl = document.getElementById('antigravity-live-send-estimator');
        if (legacyEstimatorEl) legacyEstimatorEl.style.display = 'none';
        const legacyTriggerPill = document.getElementById('antigravity-model-trigger-loss-pill');
        if (legacyTriggerPill) legacyTriggerPill.style.display = 'none';

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
    // 6. Clean Full-Width Composer Status Strip (Below Toolbar — Zero Overlap!)
    // ----------------------------------------------------------------------------
    function getActiveCascadeId() {
        if (currentConvId) return currentConvId;
        const selectedRow = document.querySelector('[data-testid="conversation-row-sidebar"][data-selected="true"][data-cascade-id]');
        if (selectedRow) return selectedRow.getAttribute('data-cascade-id');
        if (amsTelemetryState.activeConvStats && amsTelemetryState.activeConvStats.cascadeId) {
            return amsTelemetryState.activeConvStats.cascadeId;
        }
        return null;
    }

    function getComposerInputText() {
        const el = document.querySelector('[role="combobox"][aria-label="Message input"]') ||
                   document.querySelector('[contenteditable="true"][role="textbox"]') ||
                   document.querySelector('textarea');
        if (!el) return '';
        return (typeof el.value === 'string' ? el.value : el.textContent) || '';
    }

    function updateComposerStatusStrip() {
        // Hide any legacy inline items inside the narrow button row
        const legacyChatTokenEl = document.getElementById('antigravity-chat-token-counter');
        if (legacyChatTokenEl) legacyChatTokenEl.style.display = 'none';
        const legacyEstimatorEl = document.getElementById('antigravity-live-send-estimator');
        if (legacyEstimatorEl) legacyEstimatorEl.style.display = 'none';

        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        if (!addContextBtn || !addContextBtn.parentElement) return;
        const buttonRow = addContextBtn.parentElement;
        const toolbarFooter = buttonRow.parentElement;
        const composerCard = toolbarFooter ? toolbarFooter.parentElement : null;
        if (!composerCard) return;

        let stripEl = document.getElementById('antigravity-composer-status-strip');
        if (!stripEl) {
            stripEl = document.createElement('div');
            stripEl.id = 'antigravity-composer-status-strip';
            stripEl.style.cssText =
                'display:none;align-items:center;justify-content:space-between;gap:10px;width:100%;' +
                'padding:5px 8px 3px 8px;margin-top:2px;border-top:1px solid rgba(255,255,255,0.06);' +
                'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;' +
                'font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;user-select:none;';
            composerCard.appendChild(stripEl);
        } else if (stripEl.parentElement !== composerCard) {
            composerCard.appendChild(stripEl);
        }

        const rawText = getComposerInputText().trim();
        const activeId = currentConvId || getActiveCascadeId();
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const stats = amsTelemetryState.activeConvStats;
        const hasHistory = !!(cacheInfo && cacheInfo.stepCount > 0);

        // If brand new chat and nothing typed yet, keep composer completely clean
        if (!hasHistory && !rawText) {
            stripEl.style.display = 'none';
            return;
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        stripEl.style.display = 'flex';

        // Left Side: Human-readable Chat Warmth & Total Chat Usage
        let leftHtml = '';
        if (!hasHistory) {
            leftHtml =
                `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:4px;background:rgba(16,185,129,0.10);border:1px solid rgba(16,185,129,0.28);color:#34d399;font-weight:600;font-size:10.5px;">` +
                    `${amsIcon('sparkles', 10, '#34d399')}<span>${isDe ? 'Neuer Chat · Bereit' : 'New Chat · Ready'}</span>` +
                `</span>`;
        } else {
            let statusChip = '';
            if (cacheInfo.isRunning) {
                statusChip =
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:4px;background:rgba(16,185,129,0.14);border:1px solid rgba(16,185,129,0.40);color:#34d399;font-weight:700;font-size:10.5px;">` +
                        `${amsIcon('zap', 10, '#34d399')}<span>${isDe ? `Arbeitet live · Step #${cacheInfo.stepCount}` : `Working live · Step #${cacheInfo.stepCount}`}</span>` +
                    `</span>`;
            } else if (cacheInfo.state === 'warm') {
                statusChip =
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:4px;background:rgba(16,185,129,0.10);border:1px solid rgba(16,185,129,0.28);color:#34d399;font-weight:600;font-size:10.5px;">` +
                        `${amsIcon('flame', 10, '#34d399')}<span>${isDe ? `Cache warm (${formatDurationShort(cacheInfo.remainingGuaranteedSec)})` : `Cache warm (${formatDurationShort(cacheInfo.remainingGuaranteedSec)})`}</span>` +
                    `</span>`;
            } else if (cacheInfo.state === 'lukewarm') {
                statusChip =
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:4px;background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.38);color:#fbbf24;font-weight:600;font-size:10.5px;">` +
                        `${amsIcon('alert', 10, '#fbbf24')}<span>${isDe ? `5m-Garantie um (${formatDurationShort(cacheInfo.idleSec)} Pause)` : `5m TTL expired (${formatDurationShort(cacheInfo.idleSec)} idle)`}</span>` +
                    `</span>`;
            } else {
                statusChip =
                    `<span id="ams-composer-cache-pill" style="display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:4px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.35);color:#f87171;font-weight:600;font-size:10.5px;">` +
                        `${amsIcon('snowflake', 10, '#f87171')}<span>${isDe ? `Chat kalt (${formatDurationShort(cacheInfo.idleSec)} Pause)` : `Chat cold (${formatDurationShort(cacheInfo.idleSec)} idle)`}</span>` +
                    `</span>`;
            }

            const wUsedStr = cacheInfo.weeklyPctUsed.toFixed(4);
            const ratioStr = Math.round((stats && stats.cacheRatio) || cacheInfo.cacheRatio || 0);
            leftHtml =
                `<div style="display:inline-flex;align-items:center;gap:8px;min-width:0;overflow:hidden;">` +
                    statusChip +
                    `<span style="color:#94a3b8;font-size:10.5px;">` +
                        `${isDe ? 'Chat bisher:' : 'Chat used:'} <strong style="color:#e2e8f0;font-weight:600;">-${wUsedStr}% W</strong> ` +
                        `<span style="opacity:0.7;">(${ratioStr}% Cache)</span>` +
                    `</span>` +
                `</div>`;
        }

        // Right Side: What happens on Next Send (1 clear number + 1 button if cold)
        const typedTokens = rawText ? Math.max(1, Math.round(rawText.length / 3.6)) : 120;
        const ctxTokens = hasHistory ? cacheInfo.contextTokens : 24500;
        const estOutTokens = 850;
        const isWarm = !hasHistory || cacheInfo.state === 'warm' || cacheInfo.isRunning;
        const weightedWarm = Math.round(0.1 * ctxTokens + 1.0 * typedTokens + 6.0 * estOutTokens);
        const weightedCold = Math.round(1.0 * ctxTokens + 1.0 * typedTokens + 6.0 * estOutTokens);
        const activeWeighted = isWarm ? weightedWarm : weightedCold;

        const estWeeklyPct = (activeWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const est5hPct = (activeWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const extraLossWeeklyPct = Math.max(0, (weightedCold - weightedWarm) * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);

        let rightHtml = '';
        if (isWarm) {
            rightHtml =
                `<div style="display:inline-flex;align-items:center;gap:6px;color:#94a3b8;font-size:10.5px;flex-shrink:0;">` +
                    `<span style="display:inline-flex;align-items:center;gap:3px;color:#7dd3fc;">` +
                        `${amsIcon('enter', 10, '#7dd3fc')}` +
                        `<span>${rawText ? (isDe ? 'Senden:' : 'Send:') : (isDe ? 'Nächste Nachricht:' : 'Next msg:')}</span>` +
                        `<strong style="color:#bae6fd;font-weight:600;">~ -${estWeeklyPct}% W</strong>` +
                    `</span>` +
                    `<span style="opacity:0.6;">(-${est5hPct}% 5h)</span>` +
                `</div>`;
        } else {
            rightHtml =
                `<div style="display:inline-flex;align-items:center;gap:7px;font-size:10.5px;flex-shrink:0;">` +
                    `<span style="display:inline-flex;align-items:center;gap:4px;color:#fbbf24;">` +
                        `${amsIcon('alert', 10, '#fbbf24')}` +
                        `<span>${isDe ? 'Kalt-Senden:' : 'Cold send:'} <strong>-${estWeeklyPct}% W</strong> <span style="opacity:0.85;">(-${extraLossWeeklyPct}% W ${isDe ? 'Verlust' : 'loss'})</span></span>` +
                    `</span>` +
                    `<button type="button" class="antigravity-inline-newchat-btn" style="display:inline-flex;align-items:center;gap:3px;height:20px;padding:0 7px;border-radius:4px;border:1px solid rgba(52,211,153,0.45);background:rgba(16,185,129,0.16);color:#6ee7b7;font-size:10px;font-weight:700;cursor:pointer;transition:background 0.15s ease;">` +
                        `${amsIcon('plus', 9, '#6ee7b7')}<span>${isDe ? 'Neuer Chat' : 'New Chat'}</span>` +
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

        if (hasHistory) {
            stripEl.title = isDe
                ? `Details zu diesem Chat (${cacheInfo.stepCount} Steps · ${(cacheInfo.contextTokens || 0).toLocaleString('de-DE')} Kontext-Tokens):\n` +
                  `• Bisher verbraucht: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
                  `• Nächste Nachricht im warmen Cache (0.1x): -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)\n` +
                  `• Nächste Nachricht kalt ohne Cache (1.0x): -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)`
                : `Chat Details (${cacheInfo.stepCount} steps · ${(cacheInfo.contextTokens || 0).toLocaleString('en-US')} context tokens):\n` +
                  `• Used so far: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
                  `• Next message Warm (0.1x): -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)\n` +
                  `• Next message Cold (1.0x): -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)`;
        }
    }

    function updateComposerChatBadge() {
        updateComposerStatusStrip();
    }

    function updateLiveSendEstimator() {
        updateComposerStatusStrip();
    }

    // Attach input listeners for instant pre-send estimation while typing
    document.addEventListener('input', (e) => {
        if (e.target && (e.target.getAttribute('role') === 'combobox' || e.target.isContentEditable || e.target.tagName === 'TEXTAREA')) {
            updateComposerStatusStrip();
        }
    }, true);

    // ----------------------------------------------------------------------------
    // 7. Per-Message Post-Turn Cost Badges in Chat Stream (Clean 3-Chip Single-Line)
    // ----------------------------------------------------------------------------
    function renderPerMessageTurnBadges() {
        const stats = amsTelemetryState.activeConvStats;
        if (!stats || !Array.isArray(stats.turns) || stats.turns.length === 0) return;

        const agentArticles = Array.from(document.querySelectorAll('[role="article"][aria-label="Agent response"]'));
        if (agentArticles.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const turns = stats.turns;

        agentArticles.forEach((article, idx) => {
            const turn = turns[idx] || (idx === agentArticles.length - 1 ? turns[turns.length - 1] : null);
            if (!turn || !turn.steps) return;

            let badge = article.querySelector('.antigravity-turn-cost-badge-v2');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'antigravity-turn-cost-badge-v2';
                article.appendChild(badge);
            }
            badge.style.cssText =
                'display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:0;' +
                'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:11px;' +
                'font-variant-numeric:tabular-nums;white-space:nowrap;max-width:100%;overflow-x:auto;' +
                'color:var(--muted-foreground,#94a3b8);user-select:none;cursor:help;';

            const cachePct = turn.totalInput > 0 ? Math.round((turn.cached / turn.totalInput) * 100) : 0;
            const wPct = Number(turn.weeklyPct || 0).toFixed(4);
            const hPct = Number(turn.fiveHourPct || 0).toFixed(2);
            const eurStr = Number(turn.apiCostEur || 0).toFixed(2);
            const savedEurStr = Number(turn.apiSavedEur || 0).toFixed(2);
            const savedTurnTokens = Math.round(Number(turn.cached || 0) * 0.9);
            const savedTurnW = (savedTurnTokens * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(2);
            const savedTurn5h = (savedTurnTokens * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(2);

            // Chip 1: Quota Used
            const quotaChip =
                `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.22);color:#e2e8f0;">` +
                    `${amsIcon('zap', 10, '#38bdf8')}` +
                    `<strong style="color:#38bdf8;font-weight:700;">-${wPct}% W</strong>` +
                    `<span style="opacity:0.65;font-size:10px;">(-${hPct}% 5h)</span>` +
                `</span>`;

            // Chip 2: Cache Hit / Miss Status
            const cacheChip = turn.cacheMiss
                ? `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;background:rgba(245,158,11,0.10);border:1px solid rgba(245,158,11,0.28);color:#fbbf24;font-weight:600;">` +
                      `${amsIcon('snowflake', 10, '#fbbf24')}` +
                      `<span>Cache-Miss · -${Number(turn.wastedWeeklyPct || 0).toFixed(3)}% W ${isDe ? 'verloren' : 'lost'}</span>` +
                  `</span>`
                : `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.22);color:#34d399;font-weight:600;">` +
                      `${amsIcon('flame', 10, '#34d399')}` +
                      `<span>${cachePct}% Cache · +${savedTurnW}% W ${isDe ? 'gespart' : 'saved'}</span>` +
                  `</span>`;

            // Chip 3: Steps & Euro Summary
            const metaChip =
                `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:5px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);color:#94a3b8;font-size:10.5px;">` +
                    `<span>${turn.steps} ${turn.steps === 1 ? 'Step' : 'Steps'}</span>` +
                    `<span style="opacity:0.4;">·</span>` +
                    `<span style="color:#fcd34d;font-weight:600;">~${eurStr} €</span>` +
                `</span>`;

            badge.innerHTML = quotaChip + cacheChip + metaChip;

            badge.title = isDe
                ? `Details zu dieser KI-Antwort (${turn.steps} Steps):\n` +
                  `• Abzug: -${wPct}% Weekly / -${Number(turn.fiveHourPct || 0).toFixed(4)}% 5-Stunden-Limit\n` +
                  `• Durch Cache gespart: +${(savedTurnTokens * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4)}% Weekly (+${savedTurn5h}% 5h)\n` +
                  `• Tokens: ${formatTokensCompact(turn.cached)} aus Cache (${cachePct}%) · ${formatTokensCompact(turn.uncached)} neu · ${formatTokensCompact(turn.out)} Output\n` +
                  `• API-Wert: ~${eurStr} € (+${savedEurStr} € durch Cache gespart)`
                : `AI Response Breakdown (${turn.steps} steps):\n` +
                  `• Quota used: -${wPct}% Weekly / -${Number(turn.fiveHourPct || 0).toFixed(4)}% 5h\n` +
                  `• Saved by cache: +${(savedTurnTokens * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4)}% Weekly (+${savedTurn5h}% 5h)\n` +
                  `• Tokens: ${formatTokensCompact(turn.cached)} cached (${cachePct}%) · ${formatTokensCompact(turn.uncached)} new · ${formatTokensCompact(turn.out)} out\n` +
                  `• API value: ~€${eurStr} (+€${savedEurStr} saved)`;
        });
    }

    // ----------------------------------------------------------------------------
    // 8. Left Navigation Sidebar Conversation Badges & Cold-Chat Warning Popover
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
            'background:rgba(18,18,22,0.97);backdrop-filter:blur(16px);border:1px solid rgba(245,158,11,0.42);' +
            'box-shadow:0 16px 36px rgba(0,0,0,0.65);color:#f8fafc;font-family:ui-sans-serif,system-ui,sans-serif;' +
            'font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;';

        const top = Math.min(window.innerHeight - 250, Math.max(12, rect.bottom + 6));
        const left = Math.min(window.innerWidth - 350, Math.max(12, rect.left));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';

        const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
        const statusHeader = isWarm
            ? `${amsIcon('flame', 12, '#34d399')} <span>${isDe ? `Prompt-Cache ist WARM (${formatDurationShort(cacheInfo.remainingGuaranteedSec)} garantiert)` : `Prompt Cache is WARM (${formatDurationShort(cacheInfo.remainingGuaranteedSec)} guaranteed)`}</span>`
            : cacheInfo.state === 'lukewarm'
                ? `${amsIcon('alert', 12, '#fbbf24')} <span>${isDe ? `5-Minuten-Garantie abgelaufen (Pause: ${formatDurationShort(cacheInfo.idleSec)})` : `5-Minute Guarantee Expired (Idle: ${formatDurationShort(cacheInfo.idleSec)})`}</span>`
                : `${amsIcon('snowflake', 12, '#f87171')} <span>${isDe ? `Chat ist KALT (Pause: ${formatDurationShort(cacheInfo.idleSec)})` : `Chat is COLD (Idle: ${formatDurationShort(cacheInfo.idleSec)})`}</span>`;

        pop.innerHTML =
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08);">` +
                `<strong style="display:inline-flex;align-items:center;gap:5px;color:${isWarm ? '#34d399' : '#fbbf24'};font-size:12px;">${statusHeader}</strong>` +
                `<button type="button" class="ams-cold-pop-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:#94a3b8;cursor:pointer;padding:2px;">${amsIcon('close', 12, '#94a3b8')}</button>` +
            `</div>` +
            `<div style="display:flex;flex-direction:column;gap:5px;font-size:11px;color:#cbd5e1;">` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Bisheriger Chat-Verbrauch:' : 'Chat Quota Used:'}</span><strong style="color:#f8fafc;">-${cacheInfo.weeklyPctUsed.toFixed(4)}% W (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Kontextfenster-Größe:' : 'Context Window Size:'}</span><strong style="color:#f8fafc;">${cacheInfo.contextTokens.toLocaleString(isDe ? 'de-DE' : 'en-US')} Tokens (${cacheInfo.stepCount} Steps)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Schreiben in WARMEN Chat (0.1x):' : 'Sending in WARM Chat (0.1x):'}</span><strong style="color:#34d399;">-${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Schreiben in KALTEN Chat (1.0x):' : 'Sending in COLD Chat (1.0x):'}</span><strong style="color:#f87171;">-${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="margin-top:3px;padding:6px 8px;border-radius:6px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:#fecaca;font-size:10.5px;">` +
                    (isDe
                        ? `${amsIcon('info', 11, '#fca5a5')} <strong>Aufpreis bei kaltem Chat:</strong> Du verlierst <strong>+${cacheInfo.extraColdLossWeeklyPct.toFixed(4)}% Weekly</strong> (<strong>+${cacheInfo.extraColdLoss5hPct.toFixed(4)}% 5h</strong>) extra durch das uncached Nachladen des gesamten Verlaufs!`
                        : `${amsIcon('info', 11, '#fca5a5')} <strong>Cold Reload Penalty:</strong> You lose an extra <strong>+${cacheInfo.extraColdLossWeeklyPct.toFixed(4)}% Weekly</strong> (<strong>+${cacheInfo.extraColdLoss5hPct.toFixed(4)}% 5h</strong>) reloading the full context uncached!`) +
                `</div>` +
            `</div>` +
            `<div style="display:flex;gap:8px;margin-top:10px;">` +
                `<button type="button" class="ams-cold-pop-newchat" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:6px 10px;border-radius:6px;border:1px solid rgba(52,211,153,0.45);background:linear-gradient(135deg,rgba(5,150,105,0.35),rgba(16,185,129,0.22));color:#6ee7b7;font-size:11px;font-weight:700;cursor:pointer;">` +
                    `${amsIcon('plus', 11, '#6ee7b7')}<span>${isDe ? 'Direkt in neuen Chat springen' : 'Jump to New Chat (Save Quota)'}</span>` +
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
        if (activeColdPopover && !activeColdPopover.contains(e.target) && !e.target.closest('.antigravity-sidebar-chat-meta-v2')) {
            closeColdChatPopover();
        }
        if (activeModelSwitchPopover && !activeModelSwitchPopover.contains(e.target) && !e.target.closest('[data-testid="model-selector-trigger"]') && !e.target.closest('[data-testid="model-selector-panel"]')) {
            closeModelSwitchPopover();
        }
    });

    function decorateSidebarConversations() {
        const rows = document.querySelectorAll('[data-testid="conversation-row-sidebar"][data-cascade-id]');
        if (!rows || rows.length === 0) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';

        rows.forEach((row) => {
            const cascadeId = row.getAttribute('data-cascade-id');
            if (!cascadeId) return;

            const cacheInfo = getChatCacheState(cascadeId);
            if (cacheInfo.stepCount === 0 && !cacheInfo.isRunning) return;

            // Locate the right-side container holding the loading spinner / timestamp
            const rightContainer = row.querySelector('.shrink-0.ml-2 .flex.items-center.gap-1\\.5') ||
                                   row.querySelector('.shrink-0.ml-2');
            if (!rightContainer) return;

            let badge = row.querySelector('.antigravity-sidebar-chat-meta-v2');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-sidebar-chat-meta-v2';
                badge.style.cssText =
                    'display:inline-flex;align-items:center;gap:3px;padding:1px 5px;border-radius:4px;' +
                    'font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:9.5px;font-weight:600;' +
                    'font-variant-numeric:tabular-nums;line-height:1.2;cursor:pointer;pointer-events:auto;' +
                    'margin-right:3px;white-space:nowrap;transition:all 0.15s ease;';
                badge.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    showColdChatPopover(badge, cascadeId);
                });
                rightContainer.insertBefore(badge, rightContainer.firstChild);
            }

            const isSelected = row.getAttribute('data-selected') === 'true' || cascadeId === currentConvId;

            if (cacheInfo.isRunning) {
                // LIVE Running Chat: High-visibility emerald pill with 4 decimals
                badge.style.background = 'rgba(16, 185, 129, 0.15)';
                badge.style.border = '1px solid rgba(16, 185, 129, 0.45)';
                badge.style.color = '#6ee7b7';
                badge.style.padding = '1px 5px';
                badge.style.opacity = '1';
                badge.innerHTML = `${amsIcon('zap', 10, '#6ee7b7')}<span>-${cacheInfo.weeklyPctUsed.toFixed(4)}%</span>`;
            } else if (cacheInfo.state === 'warm') {
                // WARM Chat (< 5m): Emerald pill with countdown + %
                badge.style.background = 'rgba(16, 185, 129, 0.10)';
                badge.style.border = '1px solid rgba(16, 185, 129, 0.30)';
                badge.style.color = '#34d399';
                badge.style.padding = '1px 5px';
                badge.style.opacity = '1';
                const remM = Math.ceil(cacheInfo.remainingGuaranteedSec / 60);
                const wDec = isSelected ? 4 : 2;
                badge.innerHTML = `${amsIcon('flame', 10, '#34d399')}<span>${remM}m · -${cacheInfo.weeklyPctUsed.toFixed(wDec)}%</span>`;
            } else if (cacheInfo.state === 'lukewarm' || (cacheInfo.idleSec < 1800 && cacheInfo.contextTokens > 25000)) {
                // Freshly Cold (5m - 30m): Subtle Amber Pill so user knows it just cooled down
                badge.style.background = 'rgba(245, 158, 11, 0.12)';
                badge.style.border = '1px solid rgba(245, 158, 11, 0.35)';
                badge.style.color = '#fbbf24';
                badge.style.padding = '1px 5px';
                badge.style.opacity = '0.95';
                badge.innerHTML = `${amsIcon('snowflake', 9, '#fbbf24')}<span>-${cacheInfo.weeklyPctUsed.toFixed(2)}%</span>`;
            } else {
                // Old Cold Chats (> 30m ago): Quiet, borderless label so the sidebar stays clean and uncluttered!
                badge.style.background = isSelected ? 'rgba(255,255,255,0.06)' : 'transparent';
                badge.style.border = isSelected ? '1px solid rgba(255,255,255,0.12)' : '1px solid transparent';
                badge.style.color = '#94a3b8';
                badge.style.padding = isSelected ? '1px 5px' : '0 2px';
                badge.style.opacity = isSelected ? '0.9' : '0.55';
                badge.innerHTML = `<span>-${cacheInfo.weeklyPctUsed.toFixed(isSelected ? 3 : 2)}%</span>`;
            }

            badge.title = isDe
                ? `Chat-Verbrauch: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
                  `Kontext: ${formatTokensCompact(cacheInfo.contextTokens)} Tokens (${cacheInfo.stepCount} Steps)\n` +
                  `Nächste Nachricht Warm (0.1x): -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W | Kalt (1.0x): -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W\n` +
                  `(Klicken für Kalt/Warm-Vergleich & 1-Klick Neuer Chat)`
                : `Chat Usage: -${cacheInfo.weeklyPctUsed.toFixed(4)}% Weekly (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
                  `Context: ${formatTokensCompact(cacheInfo.contextTokens)} tokens (${cacheInfo.stepCount} steps)\n` +
                  `Next message Warm (0.1x): -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W | Cold (1.0x): -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W\n` +
                  `(Click for Cold/Warm comparison & 1-click New Chat)`;
        });
    }

    // ----------------------------------------------------------------------------
    // 9. Settings -> "Models & Usage" Page Injection & Native Exact-Decimal Patch
    // ----------------------------------------------------------------------------
    function patchModelsAndUsagePage() {
        const dialog = document.querySelector('.animate-modalScaleIn') || document.querySelector('[role="dialog"]');
        if (!dialog) return;

        // Check if "Models & Usage" header is present in the dialog
        const spans = Array.from(dialog.querySelectorAll('span, h1, h2, h3, div'));
        const headerSpan = spans.find(el => el.children.length === 0 && el.textContent && el.textContent.trim() === 'Models & Usage');
        if (!headerSpan) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';

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

                let exactVal = 0;
                if (txt === '5-Hour Limit') {
                    exactVal = isGemini ? currentQuotaData.gemini5hExact : currentQuotaData.claude5hExact;
                } else {
                    exactVal = isGemini ? currentQuotaData.geminiWeeklyExact : currentQuotaData.claudeWeeklyExact;
                }

                const usedVal = Math.max(0, 100 - exactVal);
                pctSpan.style.fontFamily = 'ui-monospace, SFMono-Regular, Consolas, monospace';
                pctSpan.style.fontVariantNumeric = 'tabular-nums';
                pctSpan.style.whiteSpace = 'nowrap';
                pctSpan.innerHTML =
                    `<span style="font-size:13.5px;font-weight:700;color:${exactVal > 45 ? '#34d399' : exactVal > 20 ? '#fbbf24' : '#f87171'};">${exactVal.toFixed(4)}%</span>` +
                    `<span style="display:block;font-size:9.5px;font-weight:500;color:var(--muted-foreground,#94a3b8);">-${usedVal.toFixed(4)}% ${isDe ? 'verbr.' : 'used'}</span>`;
            }
        }

        // 3. Inject or Update the Comprehensive Ultra Quota, Token & Cache Dossier Section
        const scrollRoot = headerSpan.closest('.overflow-y-auto') ||
                           headerSpan.parentElement?.parentElement?.parentElement?.parentElement;
        if (!scrollRoot) return;

        // If we haven't loaded token stats yet, trigger a fetch using any known conversation ID
        if (!amsTelemetryState.weeklySummary && window.electronNative && window.electronNative.getTokenStats) {
            const anyCid = currentConvId ||
                           (amsTelemetryState.liveTrajectoriesMap.keys().next().value) ||
                           (document.querySelector('[data-cascade-id]')?.getAttribute('data-cascade-id'));
            if (anyCid && !window.__ams_fetching_initial_stats) {
                window.__ams_fetching_initial_stats = true;
                window.electronNative.getTokenStats(anyCid).then((res) => {
                    window.__ams_fetching_initial_stats = false;
                    if (res && res.status === 'success') {
                        window.amsIngestTokenStatsResult(res, anyCid === currentConvId);
                    }
                }).catch(() => {
                    window.__ams_fetching_initial_stats = false;
                });
            }
        }

        let dossierEl = scrollRoot.querySelector('#antigravity-models-usage-intelligence-v2');
        if (!dossierEl) {
            dossierEl = document.createElement('div');
            dossierEl.id = 'antigravity-models-usage-intelligence-v2';
            dossierEl.style.cssText =
                'margin-top:20px;padding-top:18px;border-top:1px solid var(--border,rgba(255,255,255,0.09));' +
                'display:flex;flex-direction:column;gap:16px;font-family:ui-sans-serif,system-ui,sans-serif;' +
                'font-variant-numeric:tabular-nums;color:var(--foreground,#f8fafc);';
            scrollRoot.appendChild(dossierEl);
        }

        const gWExact = currentQuotaData.geminiWeeklyExact;
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
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#a78bfa;">-${r.hPct.toFixed(4)}% 5h</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#cbd5e1;">${writtenThisWeek.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#34d399;font-weight:700;">${leftWeekly.toLocaleString(isDe ? 'de-DE' : 'en-US')} <span style="opacity:0.6;font-weight:400;font-size:10px;">(5h: ${left5h.toLocaleString(isDe ? 'de-DE' : 'en-US')})</span></td>` +
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
                        `<div style="font-size:13px;font-weight:700;color:#38bdf8;margin-top:2px;">-${Number(c.weeklyPctUsed || 0).toFixed(4)}% W <span style="font-size:10.5px;color:#94a3b8;font-weight:400;">(-${Number(c.fiveHourPctUsed || 0).toFixed(2)}% 5h)</span></div>` +
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

        const renderSig = `${gWExact.toFixed(4)}|${g5hExact.toFixed(4)}|${wSum.stepCount}|${runningChats.length}|${recentChatsList.map(x => x.stepCount).join(',')}|${amsTelemetryState.soundEnabled}|${isDe}`;
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
                            ? `Exakte 4-Nachkommastellen-Telemetrie · 100% Weekly = 4.0× 5h-Pool (~470 Mio. gewichtete Tokens / ~20.000 KI-Steps)`
                            : `Exact 4-decimal telemetry · 100% Weekly = 4.0× 5h pool (~470M weighted tokens / ~20,000 AI steps)`) +
                    `</span>` +
                `</div>` +
                `<div style="display:flex;align-items:center;gap:8px;">` +
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
                    `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;color:#94a3b8;">${isDe ? 'Noch Übrig (aus ' + gWExact.toFixed(2) + '% W)' : 'Remaining Now (' + gWExact.toFixed(2) + '% W)'}</div>` +
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
                    `<span style="font-size:10.5px;color:#94a3b8;">1% Weekly = 4.0% 5h ≈ 200 Steps</span>` +
                `</div>` +
                `<div style="overflow-x:auto;">` +
                    `<table style="width:100%;border-collapse:collapse;font-size:11.5px;">` +
                        `<thead>` +
                            `<tr style="border-bottom:1px solid rgba(255,255,255,0.08);color:#94a3b8;font-size:10.5px;text-transform:uppercase;">` +
                                `<th style="padding:7px 8px;text-align:left;">${isDe ? 'Aufwands-Kategorie' : 'Task Effort Category'}</th>` +
                                `<th style="padding:7px 8px;text-align:right;">% Weekly</th>` +
                                `<th style="padding:7px 8px;text-align:right;">% 5-Hour</th>` +
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
    // 9b. Model Picker Inline Cache-Loss Badges & Post-Switch Warning Popover
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

    function closeModelSwitchPopover() {
        if (activeModelSwitchPopover) {
            activeModelSwitchPopover.remove();
            activeModelSwitchPopover = null;
        }
    }

    function showModelSwitchWarningPopover(oldModelLabel, newModelLabel, cacheInfo) {
        closeModelSwitchPopover();
        if (!cacheInfo || cacheInfo.stepCount === 0) return;

        const btn = document.querySelector('[data-testid="model-selector-trigger"], button[aria-label^="Select model, current:"]');
        if (!btn) return;

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const rect = btn.getBoundingClientRect();

        const mult = getModelWeightMultiplier(newModelLabel);
        const newColdWeeklyPct = Number((cacheInfo.coldSendWeeklyPct * mult).toFixed(4));
        const newCold5hPct = Number((cacheInfo.coldSend5hPct * mult).toFixed(4));
        const stayWarmWeeklyPct = cacheInfo.warmSendWeeklyPct;
        const stayWarm5hPct = cacheInfo.warmSend5hPct;
        const lossWeeklyPct = Number(Math.max(0.0001, newColdWeeklyPct - stayWarmWeeklyPct).toFixed(4));
        const loss5hPct = Number(Math.max(0.0004, newCold5hPct - stayWarm5hPct).toFixed(4));

        const pop = document.createElement('div');
        pop.id = 'antigravity-model-switch-popover';
        pop.style.cssText =
            'position:fixed;z-index:999999;width:365px;padding:12px 14px;border-radius:11px;' +
            'background:rgba(18,18,24,0.98);backdrop-filter:blur(16px);border:1px solid rgba(245,158,11,0.55);' +
            'box-shadow:0 18px 42px rgba(0,0,0,0.72),0 0 18px rgba(245,158,11,0.14);color:#f8fafc;' +
            'font-family:ui-sans-serif,system-ui,sans-serif;font-size:11.5px;line-height:1.45;font-variant-numeric:tabular-nums;';

        const top = Math.max(12, rect.top - 235);
        const left = Math.min(window.innerWidth - 380, Math.max(12, rect.left - 40));
        pop.style.top = top + 'px';
        pop.style.left = left + 'px';

        pop.innerHTML =
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08);">` +
                `<strong style="display:inline-flex;align-items:center;gap:5px;color:#fbbf24;font-size:12px;">${amsIcon('alert', 13, '#fbbf24')}<span>${isDe ? 'Modellwechsel im laufenden Chat (KV-Cache Verlust!)' : 'Mid-Chat Model Switch (KV-Cache Loss!)'}</span></strong>` +
                `<button type="button" class="ams-ms-close" style="display:inline-flex;align-items:center;background:transparent;border:none;color:#94a3b8;cursor:pointer;padding:2px;">${amsIcon('close', 12, '#94a3b8')}</button>` +
            `</div>` +
            `<div style="font-size:11px;color:#cbd5e1;margin-bottom:7px;">` +
                (isDe
                    ? `Wechsel von <strong style="color:#38bdf8;">${oldModelLabel}</strong> zu <strong style="color:#fde68a;">${newModelLabel}</strong>:<br>Der bisherige Kontext (<strong>${cacheInfo.contextTokens.toLocaleString('de-DE')} Tokens</strong> · ${cacheInfo.stepCount} Steps) liegt nur im VRAM-Cache von <em>${oldModelLabel}</em> und muss beim nächsten Senden zu <strong>100% uncached (1.0x)</strong> neu eingelesen werden!`
                    : `Switched from <strong style="color:#38bdf8;">${oldModelLabel}</strong> to <strong style="color:#fde68a;">${newModelLabel}</strong>:<br>Existing context (<strong>${cacheInfo.contextTokens.toLocaleString('en-US')} tokens</strong> · ${cacheInfo.stepCount} steps) must be reloaded <strong>100% uncached (1.0x)</strong> on the next message!`) +
            `</div>` +
            `<div style="display:flex;flex-direction:column;gap:4px;padding:7px 9px;border-radius:7px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);font-size:11px;">` +
                `<div style="display:flex;justify-content:space-between;"><span style="display:inline-flex;align-items:center;gap:4px;">${amsIcon('flame', 11, '#34d399')}<span>${isDe ? `Auf ${oldModelLabel} bleiben (0.1x Cache):` : `Stay on ${oldModelLabel} (0.1x Cache):`}</span></span><strong style="color:#34d399;">-${stayWarmWeeklyPct.toFixed(4)}% W (-${stayWarm5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span style="display:inline-flex;align-items:center;gap:4px;">${amsIcon('snowflake', 11, '#f87171')}<span>${isDe ? `Hier mit ${newModelLabel} senden (1.0x):` : `Send here with ${newModelLabel} (1.0x):`}</span></span><strong style="color:#f87171;">-${newColdWeeklyPct.toFixed(4)}% W (-${newCold5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;padding-top:3px;border-top:1px dashed rgba(255,255,255,0.1);color:#fde68a;"><span style="display:inline-flex;align-items:center;gap:4px;">${amsIcon('coins', 11, '#fbbf24')}<strong>${isDe ? 'Direkter Wechsel-Verlust:' : 'Direct Switch Penalty:'}</strong></span><strong style="color:#fbbf24;">-${lossWeeklyPct.toFixed(4)}% W (-${loss5hPct.toFixed(4)}% 5h)</strong></div>` +
            `</div>` +
            `<div style="display:flex;gap:6px;margin-top:9px;">` +
                `<button type="button" class="ams-ms-newchat" style="flex:1.25;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:6px 8px;border-radius:6px;border:1px solid rgba(52,211,153,0.5);background:linear-gradient(135deg,rgba(5,150,105,0.38),rgba(16,185,129,0.22));color:#6ee7b7;font-size:10.5px;font-weight:700;cursor:pointer;">` +
                    `${amsIcon('plus', 11, '#6ee7b7')}<span>${isDe ? `Neuer Chat mit ${newModelLabel} (0% Verlust)` : `New Chat with ${newModelLabel} (0% Loss)`}</span>` +
                `</button>` +
                `<button type="button" class="ams-ms-revert" style="flex:0.85;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:6px 8px;border-radius:6px;border:1px solid rgba(56,189,248,0.45);background:rgba(56,189,248,0.12);color:#7dd3fc;font-size:10.5px;font-weight:700;cursor:pointer;">` +
                    `${amsIcon('undo', 11, '#7dd3fc')}<span>${isDe ? `Zurück (${oldModelLabel.split(' ').slice(0, 3).join(' ')})` : `Revert`}</span>` +
                `</button>` +
            `</div>`;

        document.body.appendChild(pop);
        activeModelSwitchPopover = pop;

        pop.querySelector('.ams-ms-close').addEventListener('click', (e) => {
            e.stopPropagation();
            closeModelSwitchPopover();
        });
        pop.querySelector('.ams-ms-newchat').addEventListener('click', (e) => {
            e.stopPropagation();
            closeModelSwitchPopover();
            triggerNewConversation();
        });
        pop.querySelector('.ams-ms-revert').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeModelSwitchPopover();
            suppressNextModelSwitchPopup = true;
            await switchModel(oldModelLabel);
            setTimeout(() => { suppressNextModelSwitchPopup = false; }, 800);
        });
    }

    function updateModelSelectorTriggerBadge() {
        // Keep the narrow toolbar button row clean: remove any legacy trigger pill or floating switch popover
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
        const cacheInfo = activeId ? getChatCacheState(activeId) : null;
        const hasContext = !!(cacheInfo && cacheInfo.stepCount > 0);

        const menuEl = panel.closest('[role="menu"]');
        if (menuEl) {
            menuEl.style.maxWidth = '420px';
            menuEl.style.minWidth = '340px';
        }
        panel.style.maxHeight = '440px';

        // 1. Clean 1-line Context Header inside the Model Picker
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
            const sig = `${hasContext ? cacheInfo.stepCount : 0}-${hasContext ? cacheInfo.state : 'new'}-${currentLabel}-${isDe}`;
            if (bannerEl.getAttribute('data-sig') !== sig) {
                bannerEl.setAttribute('data-sig', sig);
                if (!hasContext) {
                    bannerEl.style.background = 'rgba(16,185,129,0.08)';
                    bannerEl.style.border = '1px solid rgba(52,211,153,0.25)';
                    bannerEl.style.color = '#a7f3d0';
                    bannerEl.innerHTML =
                        `<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">` +
                            `<span style="display:inline-flex;align-items:center;gap:4px;">${amsIcon('check', 11, '#34d399')}<strong>${isDe ? 'Neuer Chat' : 'New Chat'}</strong> · ${isDe ? 'Modellwechsel ohne Verlust (0%)' : 'Switch penalty: 0%'}</span>` +
                        `</div>`;
                } else {
                    const lossW = cacheInfo.extraColdLossWeeklyPct.toFixed(4);
                    bannerEl.style.background = 'rgba(245,158,11,0.10)';
                    bannerEl.style.border = '1px solid rgba(245,158,11,0.32)';
                    bannerEl.style.color = '#fde68a';
                    bannerEl.innerHTML =
                        `<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">` +
                            `<span style="display:inline-flex;align-items:center;gap:4px;color:#fbbf24;font-weight:600;">${amsIcon('alert', 11, '#fbbf24')}<span>${isDe ? `Wechsel verwirft Cache (-${lossW}% W)` : `Switch drops cache (-${lossW}% W)`}</span></span>` +
                            `<button type="button" class="ams-mp-newchat-btn" style="display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:4px;border:1px solid rgba(52,211,153,0.45);background:rgba(16,185,129,0.18);color:#6ee7b7;font-size:9.5px;font-weight:700;cursor:pointer;">${amsIcon('plus', 9, '#6ee7b7')}<span>${isDe ? 'Neuer Chat' : 'New Chat'}</span></button>` +
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
        }

        // 2. Clean 1-number badge on each model row ([role="menuitem"])
        const menuItems = Array.from(panel.querySelectorAll('[role="menuitem"]'));
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
                    'font-family:ui-sans-serif,system-ui,sans-serif;font-size:10px;font-weight:600;' +
                    'font-variant-numeric:tabular-nums;white-space:nowrap;flex-shrink:0;';
                const firstSpan = item.querySelector('span');
                if (firstSpan && firstSpan.nextSibling) {
                    item.insertBefore(badge, firstSpan.nextSibling);
                } else {
                    item.appendChild(badge);
                }
            }

            if (!hasContext) {
                if (isCurrentModel) {
                    badge.style.background = 'rgba(16,185,129,0.12)';
                    badge.style.border = '1px solid rgba(52,211,153,0.30)';
                    badge.style.color = '#34d399';
                    badge.innerHTML = `${amsIcon('check', 10, '#34d399')}<span>${isDe ? 'Aktiv' : 'Active'}</span>`;
                } else {
                    badge.style.background = 'transparent';
                    badge.style.border = 'none';
                    badge.style.color = '#64748b';
                    badge.textContent = '0% W';
                }
                return;
            }

            const mult = getModelWeightMultiplier(baseModelName);
            const switchColdW = Number((cacheInfo.coldSendWeeklyPct * mult).toFixed(4));
            const switchCold5h = Number((cacheInfo.coldSend5hPct * mult).toFixed(4));
            const stayWarmW = cacheInfo.warmSendWeeklyPct;
            const lossW = Number(Math.max(0.0001, switchColdW - stayWarmW).toFixed(4));
            const loss5h = Number(Math.max(0.0004, switchCold5h - cacheInfo.warmSend5hPct).toFixed(4));

            if (isCurrentModel) {
                const isWarm = cacheInfo.state === 'warm' || cacheInfo.isRunning;
                badge.style.background = isWarm ? 'rgba(16,185,129,0.12)' : 'rgba(245,158,11,0.12)';
                badge.style.border = isWarm ? '1px solid rgba(52,211,153,0.32)' : '1px solid rgba(245,158,11,0.32)';
                badge.style.color = isWarm ? '#34d399' : '#fbbf24';
                badge.innerHTML = isWarm
                    ? `${amsIcon('flame', 10, '#34d399')}<span>Cache warm</span>`
                    : `${amsIcon('snowflake', 10, '#fbbf24')}<span>Kalt</span>`;
                badge.title = isDe
                    ? `Aktuelles Modell (${baseModelName}) · Nächster Send: -${stayWarmW.toFixed(4)}% W`
                    : `Current Model (${baseModelName}) · Next send: -${stayWarmW.toFixed(4)}% W`;
            } else {
                badge.style.background = 'rgba(245,158,11,0.10)';
                badge.style.border = '1px solid rgba(245,158,11,0.28)';
                badge.style.color = '#fcd34d';
                badge.innerHTML = `<span>-${lossW.toFixed(4)}% W</span>`;
                badge.title = isDe
                    ? `Wechsel zu ${baseModelName} verwirft den KV-Cache:\n• Verlust beim nächsten Senden: -${lossW.toFixed(4)}% Weekly (-${loss5h.toFixed(4)}% 5h)`
                    : `Switching to ${baseModelName} drops KV-Cache:\n• Next send loss: -${lossW.toFixed(4)}% Weekly (-${loss5h.toFixed(4)}% 5h)`;
            }
        });
    }

    // Observe DOM for instant decoration as soon as the Model Picker opens
    const modelPickerObserver = new MutationObserver(() => {
        if (document.querySelector('[data-testid="model-selector-panel"]')) {
            decorateOpenModelPickerMenu();
        }
    });
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
        fetchUserQuotaSummary();
        fetchAllCascadeTrajectories();
    }, 1200);

    window.__ams_v2_intervals.push(setInterval(() => {
        fetchUserQuotaSummary();
    }, 20000));

    window.__ams_v2_intervals.push(setInterval(() => {
        fetchAllCascadeTrajectories();
    }, 12000));

    window.__ams_v2_intervals.push(setInterval(() => {
        if (typeof updateTokenStats === 'function') updateTokenStats();
        if (typeof updateCompactionCounter === 'function') updateCompactionCounter();
    }, 8000));

    // 1-second lightweight UI ticker so the 5-minute warm cache countdown ticks smoothly
    window.__ams_v2_intervals.push(setInterval(() => {
        if (document.hidden) return;
        ensureCleanUiStyles();
        if (!document.getElementById('antigravity-quota-display-v2')) {
            refreshQuotaDisplay();
        }
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
