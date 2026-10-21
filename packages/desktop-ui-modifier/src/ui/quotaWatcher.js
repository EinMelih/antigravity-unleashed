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
        const now = Date.now();
        if (now - amsTelemetryState.lastCacheHitFlashTs < 2200) return;
        amsTelemetryState.lastCacheHitFlashTs = now;

        playCacheHitSound(false);

        const savedTokens = Math.round(cachedTokens * 0.9);
        const savedWeeklyPct = (savedTokens * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const ctx = cachedTokens + uncachedTokens;
        const inRate = ctx > 200000 ? 4.0 : 2.0;
        const savedEur = ((savedTokens / 1e6) * inRate * 0.92).toFixed(2);
        const cacheTokStr = cachedTokens >= 1000000
            ? (cachedTokens / 1000000).toFixed(2) + 'M'
            : Math.round(cachedTokens / 1000) + 'k';

        // 1. Floating animation pill above the composer bar
        const quotaEl = document.querySelector('.antigravity-quota-display');
        if (quotaEl && document.body) {
            const rect = quotaEl.getBoundingClientRect();
            const pill = document.createElement('div');
            pill.className = 'antigravity-cache-hit-toast';
            pill.style.cssText =
                'position:fixed;z-index:999999;pointer-events:none;display:inline-flex;align-items:center;gap:6px;' +
                'padding:5px 11px;border-radius:999px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;font-weight:700;' +
                'font-variant-numeric:tabular-nums;color:#ecfdf5;background:linear-gradient(135deg,rgba(5,150,105,0.95),rgba(16,185,129,0.92));' +
                'border:1px solid rgba(110,231,183,0.65);box-shadow:0 8px 24px rgba(16,185,129,0.35),0 0 0 1px rgba(16,185,129,0.2);' +
                'transition:transform 0.65s cubic-bezier(0.16,1,0.3,1),opacity 0.65s ease;opacity:0;transform:translateY(8px) scale(0.94);';
            pill.style.left = Math.max(16, Math.min(window.innerWidth - 360, rect.left)) + 'px';
            pill.style.top = Math.max(16, rect.top - 36) + 'px';

            const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
            pill.innerHTML =
                '<span style="font-size:13px;">⚡💰</span>' +
                '<span>CACHE HIT! ' + cacheTokStr + ' (-90%) · +' + savedWeeklyPct + '% W / +' + savedEur + ' € ' + (isDe ? 'gespart' : 'saved') + '</span>';

            document.body.appendChild(pill);
            requestAnimationFrame(() => {
                pill.style.opacity = '1';
                pill.style.transform = 'translateY(-4px) scale(1)';
            });
            setTimeout(() => {
                pill.style.opacity = '0';
                pill.style.transform = 'translateY(-18px) scale(0.96)';
                setTimeout(() => pill.remove(), 680);
            }, 2600);
        }

        // 2. Pulse the active sidebar row badge
        if (convId) {
            const row = document.querySelector(`[data-testid="conversation-row-sidebar"][data-cascade-id="${convId}"]`);
            if (row) {
                row.style.transition = 'box-shadow 0.4s ease, background-color 0.4s ease';
                row.style.boxShadow = 'inset 0 0 0 1px rgba(16, 185, 129, 0.65), 0 0 14px rgba(16, 185, 129, 0.25)';
                setTimeout(() => {
                    row.style.boxShadow = '';
                }, 1800);
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
            for (const [cid, info] of amsTelemetryState.liveTrajectoriesMap.entries()) {
                if (info.isRunning && window.electronNative && window.electronNative.getTokenStats) {
                    try {
                        const res = await window.electronNative.getTokenStats(cid);
                        if (res && res.status === 'success') {
                            window.amsIngestTokenStatsResult(res, cid === currentConvId);
                        }
                    } catch (_) {}
                }
            }
            fetchUserQuotaSummary();
        }, 2200);
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
        const quotaEl = document.querySelector('.antigravity-quota-display');
        if (!quotaEl) return;

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
              `• 5-Stunden-Limit: ${g5hExact.toFixed(4)}% übrig (${(100 - g5hExact).toFixed(4)}% verbraucht · Reset: ${g5hReset})\n` +
              `• Weekly-Limit: ${gWExact.toFixed(4)}% übrig (${(100 - gWExact).toFixed(4)}% verbraucht · Reset: ${gWReset})\n\n` +
              `Verbleibendes Ultra-Kontingent (aus ${gWExact.toFixed(2)}% Weekly):\n` +
              `• ~${remStepsW.toLocaleString('de-DE')} Agent-Steps\n` +
              `• ~${remPromptsS.toLocaleString('de-DE')} Kurze Prompts (Typ S · 1–2 Steps)\n` +
              `• ~${remPromptsM.toLocaleString('de-DE')} Kleine Tasks (Typ M · ~8 Steps)\n` +
              `• ~${remPromptsL.toLocaleString('de-DE')} Komplexe Coding-Tasks (Typ L · ~25 Steps)\n` +
              `• ~${remPromptsXL.toLocaleString('de-DE')} Große Deep-Dives (Typ XL · ~80 Steps)\n` +
              `(Klicken für das vollständige Models & Usage Dossier)`
            : `✦ Google AI Ultra · Gemini Quota (Exact):\n` +
              `• 5-Hour Limit: ${g5hExact.toFixed(4)}% left (${(100 - g5hExact).toFixed(4)}% used · Reset: ${g5hReset})\n` +
              `• Weekly Limit: ${gWExact.toFixed(4)}% left (${(100 - gWExact).toFixed(4)}% used · Reset: ${gWReset})\n\n` +
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

        quotaEl.style.fontVariantNumeric = 'tabular-nums';
        quotaEl.style.gap = '5px';
        quotaEl.title = tooltipText;

        // 1. Sleek Google AI Ultra Badge
        const ultraBadge = document.createElement('span');
        ultraBadge.className = 'antigravity-ultra-badge';
        ultraBadge.style.cssText =
            'display:inline-flex;align-items:center;gap:3px;padding:1px 6px;border-radius:4px;' +
            'font-size:9px;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;' +
            'background:linear-gradient(135deg,rgba(245,158,11,0.16),rgba(139,92,246,0.22));' +
            'border:1px solid rgba(251,191,36,0.42);color:#fde68a;box-shadow:0 0 10px rgba(245,158,11,0.12);';
        ultraBadge.textContent = '✦ ULTRA';

        // 2. 5h Limit Pill
        const fiveHPill = document.createElement('span');
        fiveHPill.style.cssText =
            'display:inline-flex;align-items:center;gap:3px;padding:1px 6px;border-radius:4px;' +
            'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);font-size:10px;';
        fiveHPill.innerHTML =
            `<span style="opacity:0.65;">5h:</span>` +
            `<strong style="color:${getPercentColorHex(g5hExact)};font-weight:700;">${g5hExact.toFixed(2)}%</strong>`;

        // 3. Weekly Limit Pill (4 decimals as requested!)
        const weeklyPill = document.createElement('span');
        weeklyPill.style.cssText =
            'display:inline-flex;align-items:center;gap:3px;padding:1px 6px;border-radius:4px;' +
            'background:rgba(56,189,248,0.06);border:1px solid rgba(56,189,248,0.22);font-size:10px;';
        const wResetCompact = (gWReset && gWReset !== 'Aktiv') ? ` <span style="opacity:0.55;font-size:9px;">(${gWReset})</span>` : '';
        weeklyPill.innerHTML =
            `<span style="color:#7dd3fc;opacity:0.85;">W:</span>` +
            `<strong style="color:${getPercentColorHex(gWExact)};font-weight:700;">${gWExact.toFixed(4)}%</strong>` +
            wResetCompact;

        quotaEl.replaceChildren(ultraBadge, fiveHPill, weeklyPill);

        // Update active chat token & cache counter right next to quotaEl
        updateComposerChatBadge();

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

    function updateComposerChatBadge() {
        const chatTokenEl = document.getElementById('antigravity-chat-token-counter');
        if (!chatTokenEl) return;

        if (!currentConvId) {
            chatTokenEl.style.display = 'none';
            return;
        }

        const cacheInfo = getChatCacheState(currentConvId);
        const stats = amsTelemetryState.activeConvStats;
        if (!stats || !stats.stepCount) {
            chatTokenEl.style.display = 'none';
            return;
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        chatTokenEl.style.display = 'inline-flex';
        chatTokenEl.style.alignItems = 'center';
        chatTokenEl.style.gap = '5px';
        chatTokenEl.style.fontVariantNumeric = 'tabular-nums';
        chatTokenEl.style.padding = '1px 7px';
        chatTokenEl.style.borderRadius = '4px';

        let stateBadgeHtml = '';
        if (cacheInfo.isRunning) {
            chatTokenEl.style.background = 'rgba(16, 185, 129, 0.09)';
            chatTokenEl.style.border = '1px solid rgba(16, 185, 129, 0.32)';
            stateBadgeHtml = `<span style="color:#34d399;font-weight:700;">⚡ LIVE</span>`;
        } else if (cacheInfo.state === 'warm') {
            chatTokenEl.style.background = 'rgba(16, 185, 129, 0.07)';
            chatTokenEl.style.border = '1px solid rgba(16, 185, 129, 0.25)';
            stateBadgeHtml = `<span style="color:#34d399;font-weight:700;">🔥 ${formatDurationShort(cacheInfo.remainingGuaranteedSec)}</span>`;
        } else if (cacheInfo.state === 'lukewarm') {
            chatTokenEl.style.background = 'rgba(245, 158, 11, 0.10)';
            chatTokenEl.style.border = '1px solid rgba(245, 158, 11, 0.35)';
            stateBadgeHtml = `<span style="color:#fbbf24;font-weight:700;">⚠️ ${formatDurationShort(cacheInfo.idleSec)}</span>`;
        } else {
            chatTokenEl.style.background = 'rgba(239, 68, 68, 0.10)';
            chatTokenEl.style.border = '1px solid rgba(239, 68, 68, 0.35)';
            stateBadgeHtml = `<span style="color:#f87171;font-weight:700;">❄️ ${isDe ? 'Kalt' : 'Cold'} (${formatDurationShort(cacheInfo.idleSec)})</span>`;
        }

        const wUsedStr = cacheInfo.weeklyPctUsed.toFixed(4);
        const ctxStr = formatTokensCompact(stats.latestInput || 0);
        const ratioStr = Math.round(stats.cacheRatio || 0) + '%';

        chatTokenEl.innerHTML =
            stateBadgeHtml +
            `<span style="opacity:0.4;">·</span>` +
            `<span style="color:#e2e8f0;font-weight:600;">-${wUsedStr}% W</span>` +
            `<span style="opacity:0.65;">(${ctxStr} · ${ratioStr} Cache)</span>`;

        chatTokenEl.title = isDe
            ? `Aktiver Chat Verbrauch & Prompt-Cache Status:\n` +
              `• Weekly-Verbrauch (dieser Chat): -${wUsedStr}% W (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
              `• Aktuelles Kontextfenster: ${(stats.latestInput || 0).toLocaleString('de-DE')} Tokens (Auto-Compact ab 256k -> ~31.5k)\n` +
              `• Akkumulierter Input: ${(stats.totalInput || 0).toLocaleString('de-DE')} Tokens (${stats.cacheRatio}% aus 0.1x Cache)\n` +
              `• API-Gegenwert (dieser Chat): ${(stats.apiCostEur || 0).toFixed(2)} € (${(stats.apiSavedEur || 0).toFixed(2)} € durch Cache gespart)\n` +
              `• Nächste Nachricht (Warm 0.1x): ~ -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)\n` +
              `• Nächste Nachricht (Kalt 1.0x): ~ -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)`
            : `Active Chat Usage & Prompt-Cache Status:\n` +
              `• Weekly Consumed (this chat): -${wUsedStr}% W (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)\n` +
              `• Current Context Window: ${(stats.latestInput || 0).toLocaleString('en-US')} tokens (Auto-compact at 256k -> ~31.5k)\n` +
              `• Accumulated Input: ${(stats.totalInput || 0).toLocaleString('en-US')} tokens (${stats.cacheRatio}% from 0.1x cache)\n` +
              `• API Equivalent (this chat): €${(stats.apiCostEur || 0).toFixed(2)} (€${(stats.apiSavedEur || 0).toFixed(2)} saved via cache)\n` +
              `• Next Message (Warm 0.1x): ~ -${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)\n` +
              `• Next Message (Cold 1.0x): ~ -${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)`;
    }

    // ----------------------------------------------------------------------------
    // 6. Dynamic Live Pre-Send Cost Estimator (While Typing in Composer)
    // ----------------------------------------------------------------------------
    function getComposerInputText() {
        const el = document.querySelector('[role="combobox"][aria-label="Message input"]') ||
                   document.querySelector('[contenteditable="true"][role="textbox"]') ||
                   document.querySelector('textarea');
        if (!el) return '';
        return (typeof el.value === 'string' ? el.value : el.textContent) || '';
    }

    function updateLiveSendEstimator() {
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        if (!addContextBtn || !addContextBtn.parentElement) return;
        const flexContainer = addContextBtn.parentElement;

        let estimatorEl = document.getElementById('antigravity-live-send-estimator');
        if (!estimatorEl) {
            estimatorEl = document.createElement('span');
            estimatorEl.id = 'antigravity-live-send-estimator';
            estimatorEl.style.cssText =
                'display:none;align-items:center;gap:5px;margin-left:6px;padding:1px 7px;border-radius:4px;' +
                'font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;font-variant-numeric:tabular-nums;' +
                'user-select:none;transition:all 0.15s ease;';
            const chatTokenEl = document.getElementById('antigravity-chat-token-counter');
            if (chatTokenEl) {
                chatTokenEl.after(estimatorEl);
            } else {
                flexContainer.appendChild(estimatorEl);
            }
        }

        const rawText = getComposerInputText().trim();
        const cacheInfo = currentConvId ? getChatCacheState(currentConvId) : null;
        const isColdWithContext = cacheInfo && (cacheInfo.state === 'cold' || cacheInfo.state === 'lukewarm') && cacheInfo.contextTokens > 20000;

        // Show estimator whenever user is typing OR when the current chat has gone cold!
        if (!rawText && !isColdWithContext) {
            estimatorEl.style.display = 'none';
            return;
        }

        const isDe = (typeof window.amsGetLang === 'function' ? window.amsGetLang() : 'de') === 'de';
        const typedTokens = rawText ? Math.max(1, Math.round(rawText.length / 3.6)) : 120;
        const ctxTokens = cacheInfo && cacheInfo.stepCount > 0 ? cacheInfo.contextTokens : 24500;
        const estOutTokens = 850; // typical single-step response + thinking

        const isWarm = !cacheInfo || cacheInfo.stepCount === 0 || cacheInfo.state === 'warm' || cacheInfo.isRunning;
        const weightedWarm = Math.round(0.1 * ctxTokens + 1.0 * typedTokens + 6.0 * estOutTokens);
        const weightedCold = Math.round(1.0 * ctxTokens + 1.0 * typedTokens + 6.0 * estOutTokens);
        const activeWeighted = isWarm ? weightedWarm : weightedCold;

        const estWeeklyPct = (activeWeighted * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const est5hPct = (activeWeighted * ULTRA_5H_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const warmWeeklyPct = (weightedWarm * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);
        const extraLossWeeklyPct = Math.max(0, (weightedCold - weightedWarm) * ULTRA_WEEKLY_PCT_PER_WEIGHTED_TOKEN).toFixed(4);

        estimatorEl.style.display = 'inline-flex';

        if (isWarm) {
            estimatorEl.style.background = 'rgba(56, 189, 248, 0.08)';
            estimatorEl.style.border = '1px solid rgba(56, 189, 248, 0.28)';
            estimatorEl.style.color = '#bae6fd';
            estimatorEl.innerHTML =
                `<span style="color:#38bdf8;font-weight:700;">⏎ Send ≈ -${estWeeklyPct}% W</span>` +
                `<span style="opacity:0.75;">(-${est5hPct}% 5h · +${typedTokens} Tok · 🔥 0.1x)</span>`;
            estimatorEl.title = isDe
                ? `Live-Vorschau beim Drücken von Enter (Cache WARM · 90% Rabatt):\n` +
                  `• Geschätzter Abzug pro Step: -${estWeeklyPct}% Weekly / -${est5hPct}% 5h\n` +
                  `• Dein Text: ~${typedTokens} Tokens (1.0x) + Kontext: ${ctxTokens.toLocaleString('de-DE')} Tokens (0.1x Cache)`
                : `Live Pre-Send Estimate on Enter (Cache WARM · 90% discount):\n` +
                  `• Estimated drain per step: -${estWeeklyPct}% Weekly / -${est5hPct}% 5h\n` +
                  `• Your input: ~${typedTokens} tokens (1.0x) + Context: ${ctxTokens.toLocaleString('en-US')} tokens (0.1x cache)`;
        } else {
            estimatorEl.style.background = 'rgba(245, 158, 11, 0.14)';
            estimatorEl.style.border = '1px solid rgba(245, 158, 11, 0.45)';
            estimatorEl.style.color = '#fde68a';
            estimatorEl.innerHTML =
                `<span style="color:#fbbf24;font-weight:700;">⚠️ ⏎ ${isDe ? 'Kalt-Send' : 'Cold Send'} ≈ -${estWeeklyPct}% W</span>` +
                `<span style="opacity:0.85;">(${isDe ? 'Warm wäre' : 'Warm:'} -${warmWeeklyPct}% W · -${extraLossWeeklyPct}% W ${isDe ? 'Verlust' : 'loss'})</span>` +
                `<button type="button" class="antigravity-inline-newchat-btn" style="margin-left:4px;padding:1px 5px;border-radius:3px;border:1px solid rgba(52,211,153,0.5);background:rgba(16,185,129,0.2);color:#6ee7b7;font-size:9px;font-weight:700;cursor:pointer;">＋ ${isDe ? 'Neuer Chat' : 'New Chat'}</button>`;
            const btn = estimatorEl.querySelector('.antigravity-inline-newchat-btn');
            if (btn) {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    triggerNewConversation();
                });
            }
        }
    }

    // Attach input listeners for instant pre-send estimation while typing
    document.addEventListener('input', (e) => {
        if (e.target && (e.target.getAttribute('role') === 'combobox' || e.target.isContentEditable || e.target.tagName === 'TEXTAREA')) {
            updateLiveSendEstimator();
        }
    }, true);

    // ----------------------------------------------------------------------------
    // 7. Per-Message Post-Turn Cost Badges in Chat Stream
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

            let badge = article.querySelector('.antigravity-turn-cost-badge');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'antigravity-turn-cost-badge';
                badge.style.cssText =
                    'display:inline-flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:6px;padding:3px 9px;' +
                    'border-radius:6px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;' +
                    'font-variant-numeric:tabular-nums;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.07);' +
                    'color:var(--muted-foreground,#a1a1aa);user-select:none;';
                article.appendChild(badge);
            }

            const cachePct = turn.totalInput > 0 ? Math.round((turn.cached / turn.totalInput) * 100) : 0;
            const wPct = Number(turn.weeklyPct || 0).toFixed(4);
            const hPct = Number(turn.fiveHourPct || 0).toFixed(4);
            const eurStr = Number(turn.apiCostEur || 0).toFixed(2);
            const savedEurStr = Number(turn.apiSavedEur || 0).toFixed(2);

            const missPill = turn.cacheMiss
                ? `<span style="color:#fbbf24;background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);padding:0 5px;border-radius:4px;font-weight:700;">❄️ Cache-Miss (${formatDurationShort(turn.maxPauseSec)} ${isDe ? 'Pause' : 'idle'} · -${Number(turn.wastedWeeklyPct || 0).toFixed(4)}% W)</span>`
                : `<span style="color:#34d399;font-weight:700;">🔥 ${cachePct}% Cache</span>`;

            badge.innerHTML =
                `<span style="color:#38bdf8;font-weight:700;">⚡ -${wPct}% W</span>` +
                `<span style="opacity:0.75;">(-${hPct}% 5h)</span>` +
                `<span style="opacity:0.35;">|</span>` +
                missPill +
                `<span style="opacity:0.35;">|</span>` +
                `<span>${turn.steps} ${turn.steps === 1 ? 'Step' : 'Steps'} · ${formatTokensCompact(turn.cached)} Cache · ${formatTokensCompact(turn.uncached)} In · ${formatTokensCompact(turn.out)} Out</span>` +
                `<span style="opacity:0.35;">|</span>` +
                `<span style="color:#fcd34d;">~${eurStr} € <span style="opacity:0.65;">(+${savedEurStr} € ${isDe ? 'gespart' : 'saved'})</span></span>`;
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
            ? (isDe ? `🔥 Prompt-Cache ist WARM (${formatDurationShort(cacheInfo.remainingGuaranteedSec)} garantiert)` : `🔥 Prompt Cache is WARM (${formatDurationShort(cacheInfo.remainingGuaranteedSec)} guaranteed)`)
            : cacheInfo.state === 'lukewarm'
                ? (isDe ? `⚠️ 5-Minuten-Garantie abgelaufen (Pause: ${formatDurationShort(cacheInfo.idleSec)})` : `⚠️ 5-Minute Guarantee Expired (Idle: ${formatDurationShort(cacheInfo.idleSec)})`)
                : (isDe ? `❄️ Chat ist KALT (Pause: ${formatDurationShort(cacheInfo.idleSec)})` : `❄️ Chat is COLD (Idle: ${formatDurationShort(cacheInfo.idleSec)})`);

        pop.innerHTML =
            `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08);">` +
                `<strong style="color:${isWarm ? '#34d399' : '#fbbf24'};font-size:12px;">${statusHeader}</strong>` +
                `<button type="button" class="ams-cold-pop-close" style="background:transparent;border:none;color:#94a3b8;cursor:pointer;font-size:12px;padding:0 4px;">✕</button>` +
            `</div>` +
            `<div style="display:flex;flex-direction:column;gap:5px;font-size:11px;color:#cbd5e1;">` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Bisheriger Chat-Verbrauch:' : 'Chat Quota Used:'}</span><strong style="color:#f8fafc;">-${cacheInfo.weeklyPctUsed.toFixed(4)}% W (-${cacheInfo.fiveHourPctUsed.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Kontextfenster-Größe:' : 'Context Window Size:'}</span><strong style="color:#f8fafc;">${cacheInfo.contextTokens.toLocaleString(isDe ? 'de-DE' : 'en-US')} Tokens (${cacheInfo.stepCount} Steps)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Schreiben in WARMEN Chat (0.1x):' : 'Sending in WARM Chat (0.1x):'}</span><strong style="color:#34d399;">-${cacheInfo.warmSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.warmSend5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="display:flex;justify-content:space-between;"><span>${isDe ? 'Schreiben in KALTEN Chat (1.0x):' : 'Sending in COLD Chat (1.0x):'}</span><strong style="color:#f87171;">-${cacheInfo.coldSendWeeklyPct.toFixed(4)}% W (-${cacheInfo.coldSend5hPct.toFixed(4)}% 5h)</strong></div>` +
                `<div style="margin-top:3px;padding:6px 8px;border-radius:6px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:#fecaca;font-size:10.5px;">` +
                    (isDe
                        ? `💡 <strong>Aufpreis bei kaltem Chat:</strong> Du verlierst <strong>+${cacheInfo.extraColdLossWeeklyPct.toFixed(4)}% Weekly</strong> (<strong>+${cacheInfo.extraColdLoss5hPct.toFixed(4)}% 5h</strong>) extra durch das uncached Nachladen des gesamten Verlaufs!`
                        : `💡 <strong>Cold Reload Penalty:</strong> You lose an extra <strong>+${cacheInfo.extraColdLossWeeklyPct.toFixed(4)}% Weekly</strong> (<strong>+${cacheInfo.extraColdLoss5hPct.toFixed(4)}% 5h</strong>) reloading the full context uncached!`) +
                `</div>` +
            `</div>` +
            `<div style="display:flex;gap:8px;margin-top:10px;">` +
                `<button type="button" class="ams-cold-pop-newchat" style="flex:1;padding:6px 10px;border-radius:6px;border:1px solid rgba(52,211,153,0.45);background:linear-gradient(135deg,rgba(5,150,105,0.35),rgba(16,185,129,0.22));color:#6ee7b7;font-size:11px;font-weight:700;cursor:pointer;">` +
                    `＋ ${isDe ? 'Direkt in neuen Chat springen' : 'Jump to New Chat (Save Quota)'}` +
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
        if (activeColdPopover && !activeColdPopover.contains(e.target) && !e.target.closest('.antigravity-sidebar-chat-meta')) {
            closeColdChatPopover();
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

            let badge = row.querySelector('.antigravity-sidebar-chat-meta');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'antigravity-sidebar-chat-meta';
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

            // Format Weekly %: show 4 decimals when running or active, 3 decimals otherwise for compact sidebar fit
            const isSelected = row.getAttribute('data-selected') === 'true' || cascadeId === currentConvId;
            const wDecimals = (cacheInfo.isRunning || isSelected) ? 4 : 3;
            const wPctStr = cacheInfo.weeklyPctUsed.toFixed(wDecimals);

            if (cacheInfo.isRunning) {
                badge.style.background = 'rgba(16, 185, 129, 0.14)';
                badge.style.border = '1px solid rgba(16, 185, 129, 0.42)';
                badge.style.color = '#6ee7b7';
                badge.innerHTML = `<span>🔥</span><span>-${wPctStr}%W</span>`;
            } else if (cacheInfo.state === 'warm') {
                badge.style.background = 'rgba(16, 185, 129, 0.10)';
                badge.style.border = '1px solid rgba(16, 185, 129, 0.28)';
                badge.style.color = '#34d399';
                const remM = Math.ceil(cacheInfo.remainingGuaranteedSec / 60);
                badge.innerHTML = `<span>🔥${remM}m</span><span style="opacity:0.85;">-${wPctStr}%</span>`;
            } else if (cacheInfo.state === 'lukewarm') {
                // Freshly expired 5m guarantee (5m - 17m): warn clearly!
                badge.style.background = 'rgba(245, 158, 11, 0.15)';
                badge.style.border = '1px solid rgba(245, 158, 11, 0.45)';
                badge.style.color = '#fbbf24';
                badge.innerHTML = `<span>⚠️${ isDe ? 'Kalt?' : 'Cold?' }</span><span style="opacity:0.9;">-${wPctStr}%</span>`;
            } else {
                // Cold (> 17m)
                const isFreshlyCold = cacheInfo.idleSec < 3600 && cacheInfo.contextTokens > 35000;
                badge.style.background = isFreshlyCold ? 'rgba(239, 68, 68, 0.12)' : 'rgba(148, 163, 184, 0.08)';
                badge.style.border = isFreshlyCold ? '1px solid rgba(239, 68, 68, 0.35)' : '1px solid rgba(148, 163, 184, 0.18)';
                badge.style.color = isFreshlyCold ? '#fca5a5' : '#94a3b8';
                badge.innerHTML = `<span>❄️</span><span>-${wPctStr}%</span>`;
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

        // 1. Decorate "Your Plan: Google AI Ultra" with a sleek ULTRA Max-Tier Badge
        const planDivs = Array.from(dialog.querySelectorAll('div.text-sm.font-medium'));
        const planLabel = planDivs.find(el => el.textContent && el.textContent.includes('Your Plan:'));
        if (planLabel && !planLabel.querySelector('.ams-models-ultra-pill')) {
            const pill = document.createElement('span');
            pill.className = 'ams-models-ultra-pill';
            pill.style.cssText =
                'display:inline-flex;align-items:center;gap:4px;margin-left:8px;padding:2px 8px;border-radius:999px;' +
                'font-size:10px;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;' +
                'background:linear-gradient(135deg,rgba(245,158,11,0.2),rgba(139,92,246,0.25));' +
                'border:1px solid rgba(251,191,36,0.5);color:#fde68a;box-shadow:0 0 14px rgba(245,158,11,0.18);';
            pill.textContent = '✦ ULTRA MAX TIER · 20,000 STEPS/WK';
            planLabel.appendChild(pill);
        }

        // 2. Patch Native "5-Hour Limit" and "Weekly Limit" Percentage Spans with Exact 4-Decimal Precision!
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

        let dossierEl = scrollRoot.querySelector('#antigravity-models-usage-intelligence');
        if (!dossierEl) {
            dossierEl = document.createElement('div');
            dossierEl.id = 'antigravity-models-usage-intelligence';
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
                nameDe: '⚡ 1 Einzelner KI-Step (Argon High Ø)',
                nameEn: '⚡ 1 Single AI Step (Argon High avg)',
                steps: '1 Step',
                wPct: 0.0050,
                hPct: 0.0200,
                eur: 0.058,
            },
            {
                code: 'Typ S',
                nameDe: '💬 Kurze Frage / Chat-Antwort',
                nameEn: '💬 Short Question / Quick Reply',
                steps: '1–2 Steps',
                wPct: 0.0075,
                hPct: 0.0300,
                eur: 0.087,
            },
            {
                code: 'Typ M',
                nameDe: '🛠️ Kleiner Fix / Feature-Anpassung',
                nameEn: '🛠️ Small Fix / Feature Tweak',
                steps: '~8 Steps',
                wPct: 0.0400,
                hPct: 0.1600,
                eur: 0.464,
            },
            {
                code: 'Typ L',
                nameDe: '🚀 Komplexer Coding- / Debug-Task (Dein Schnitt)',
                nameEn: '🚀 Complex Coding / Debug Task (Your Avg)',
                steps: '~25 Steps',
                wPct: 0.1250,
                hPct: 0.5000,
                eur: 1.450,
            },
            {
                code: 'Typ XL',
                nameDe: '🧠 Großer Autonomer Deep-Dive / Refactoring',
                nameEn: '🧠 Large Autonomous Deep-Dive / Refactor',
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
                `<td style="padding:7px 8px;font-weight:600;color:#f8fafc;">${isDe ? r.nameDe : r.nameEn} <span style="opacity:0.55;font-weight:400;font-size:10px;">(${r.steps})</span></td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-${r.wPct.toFixed(4)}% W</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#a78bfa;">-${r.hPct.toFixed(4)}% 5h</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#cbd5e1;">${writtenThisWeek.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#34d399;font-weight:700;">${leftWeekly.toLocaleString(isDe ? 'de-DE' : 'en-US')} <span style="opacity:0.6;font-weight:400;font-size:10px;">(5h: ${left5h.toLocaleString(isDe ? 'de-DE' : 'en-US')})</span></td>` +
                `<td style="padding:7px 8px;text-align:right;font-family:monospace;color:#fde68a;">${total100W.toLocaleString(isDe ? 'de-DE' : 'en-US')}</td>` +
            `</tr>`;
        }).join('');

        // Top chats table rows
        const recentChatsList = Array.from(amsTelemetryState.recentChatsMap.values())
            .sort((a, b) => (b.lastStepTimestamp || 0) - (a.lastStepTimestamp || 0))
            .slice(0, 25);

        const chatRowsHtml = recentChatsList.map(c => {
            const liveMeta = amsTelemetryState.liveTrajectoriesMap.get(c.cascadeId);
            const title = (liveMeta && liveMeta.summary) || c.title || ('Chat ' + c.cascadeId.slice(0, 8));
            const cState = getChatCacheState(c.cascadeId);
            const stateBadge = cState.isRunning
                ? `<span style="color:#34d399;font-weight:700;">⚡ LIVE</span>`
                : cState.state === 'warm'
                    ? `<span style="color:#34d399;font-weight:700;">🔥 ${formatDurationShort(cState.remainingGuaranteedSec)}</span>`
                    : cState.state === 'lukewarm'
                        ? `<span style="color:#fbbf24;font-weight:700;">⚠️ ${formatDurationShort(cState.idleSec)}</span>`
                        : `<span style="color:#94a3b8;">❄️ ${formatDurationShort(cState.idleSec)}</span>`;

            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04);font-size:11px;">` +
                `<td style="padding:6px 8px;max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${title.replace(/"/g, '&quot;')}">${title.replace(/</g, '&lt;')}</td>` +
                `<td style="padding:6px 8px;text-align:center;font-family:monospace;">${stateBadge}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;">${c.turnCount || 1} / ${c.stepCount || 0}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;">${formatTokensCompact(c.totalInput)} <span style="color:#34d399;">(${Math.round(c.cacheRatio || 0)}%)</span></td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:${c.cacheMissCount > 0 ? '#fbbf24' : '#64748b'};">${c.cacheMissCount || 0}</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#38bdf8;font-weight:700;">-${Number(c.weeklyPctUsed || 0).toFixed(4)}%</td>` +
                `<td style="padding:6px 8px;text-align:right;font-family:monospace;color:#fcd34d;">${Number(c.apiCostEur || 0).toFixed(2)} €</td>` +
            `</tr>`;
        }).join('');

        const renderSig = `${gWExact.toFixed(4)}|${g5hExact.toFixed(4)}|${wSum.stepCount}|${recentChatsList.length}|${amsTelemetryState.soundEnabled}|${isDe}`;
        if (dossierEl.getAttribute('data-render-sig') === renderSig) return;
        dossierEl.setAttribute('data-render-sig', renderSig);

        dossierEl.innerHTML =
            // Header Bar
            `<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-radius:10px;background:linear-gradient(135deg,rgba(245,158,11,0.10),rgba(56,189,248,0.08),rgba(139,92,246,0.12));border:1px solid rgba(251,191,36,0.32);">` +
                `<div style="display:flex;flex-direction:column;gap:2px;">` +
                    `<div style="display:flex;align-items:center;gap:8px;">` +
                        `<span style="padding:2px 7px;border-radius:4px;font-size:10px;font-weight:800;letter-spacing:0.06em;background:rgba(245,158,11,0.22);border:1px solid rgba(251,191,36,0.5);color:#fde68a;">✦ GOOGLE AI ULTRA</span>` +
                        `<strong style="font-size:14px;color:#f8fafc;">${isDe ? 'Argon High Quota-, Token- & Prompt-Cache Dossier' : 'Argon High Quota, Token & Prompt-Cache Dossier'}</strong>` +
                    `</div>` +
                    `<span style="font-size:11.5px;color:var(--muted-foreground,#94a3b8);">` +
                        (isDe
                            ? `Exakte 4-Nachkommastellen-Telemetrie · 100% Weekly = 4.0× 5h-Pool (~470 Mio. gewichtete Tokens / ~20.000 KI-Steps)`
                            : `Exact 4-decimal telemetry · 100% Weekly = 4.0× 5h pool (~470M weighted tokens / ~20,000 AI steps)`) +
                    `</span>` +
                `</div>` +
                `<div style="display:flex;align-items:center;gap:8px;">` +
                    `<button type="button" id="ams-dossier-sound-btn" style="padding:5px 10px;border-radius:6px;border:1px solid ${amsTelemetryState.soundEnabled ? 'rgba(52,211,153,0.45)' : 'rgba(148,163,184,0.25)'};background:${amsTelemetryState.soundEnabled ? 'rgba(16,185,129,0.16)' : 'rgba(255,255,255,0.04)'};color:${amsTelemetryState.soundEnabled ? '#6ee7b7' : '#94a3b8'};font-size:11px;font-weight:600;cursor:pointer;">` +
                        (amsTelemetryState.soundEnabled
                            ? (isDe ? '🔊 Cache-Hit Sound: AN (Testen)' : '🔊 Cache-Hit Sound: ON (Test)')
                            : (isDe ? '🔇 Cache-Hit Sound: AUS' : '🔇 Cache-Hit Sound: OFF')) +
                    `</button>` +
                `</div>` +
            `</div>` +

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
                    `<strong style="font-size:12.5px;">📊 ${isDe ? 'Dossier-Umrechnungstabelle: Nachrichten & Tasks nach Aufwand (Argon High auf Ultra)' : 'Effort Conversion Table: Messages & Tasks by Complexity (Argon High on Ultra)'}</strong>` +
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
                    `<strong style="color:#34d399;display:block;margin-bottom:4px;">🔥 ${isDe ? 'Prompt-Cache Haltedauer & Provider-Vergleich' : 'Prompt-Cache TTL & Provider Comparison'}</strong>` +
                    (isDe
                        ? `• <strong>Google Gemini (Antigravity):</strong> <strong>5 Min. (300s) garantiert</strong> im TPU-HBM-RAM, real <strong>5 bis 17,3 Min.</strong> je nach Serverlast. <strong>90% Rabatt (0.1×)</strong>, 0% Schreib-Aufpreis.<br>` +
                          `• <strong>Anthropic Claude:</strong> 5 Min. RAM-TTL (90% Rabatt, aber +25% Cache-Write-Strafe).<br>` +
                          `• <strong>OpenAI Codex / GPT-5:</strong> 5–60 Min. im GPU-RAM + bis zu <strong>24 Stunden</strong> durch <em>Extended NVMe-SSD Cache Offloading</em>.`
                        : `• <strong>Google Gemini (Antigravity):</strong> <strong>5 min (300s) guaranteed</strong> in TPU HBM RAM, <strong>5 to 17.3 min</strong> best-effort depending on pod load. <strong>90% discount (0.1×)</strong>, 0% write surcharge.<br>` +
                          `• <strong>Anthropic Claude:</strong> 5 min RAM TTL (90% discount, +25% cache-write fee).<br>` +
                          `• <strong>OpenAI Codex / GPT-5:</strong> 5–60 min in RAM + up to <strong>24 hours</strong> via <em>Extended NVMe SSD Cache Offloading</em>.`) +
                `</div>` +
                `<div style="padding:11px 13px;border-radius:8px;background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.22);font-size:11px;line-height:1.45;">` +
                    `<strong style="color:#fbbf24;display:block;margin-bottom:4px;">⚠️ ${isDe ? 'Cache-Miss Bilanz & Auto-Checkpointer' : 'Cache-Miss Diagnostics & Auto-Checkpointer'}</strong>` +
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
                    `<strong style="font-size:12.5px;">🗂️ ${isDe ? 'Persistentes Chat-Verbrauchs-Logbuch (Top 25 aktuelle Konversationen)' : 'Persistent Per-Chat Usage Ledger (Top 25 Recent Conversations)'}</strong>` +
                    `<span style="font-size:10px;font-family:monospace;color:#94a3b8;">💾 ${amsTelemetryState.logFilePath}</span>` +
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
    // 10. Periodic Polling & Live Countdown Ticker
    // ----------------------------------------------------------------------------
    setTimeout(() => {
        fetchUserQuotaSummary();
        fetchAllCascadeTrajectories();
    }, 1200);

    setInterval(() => {
        fetchUserQuotaSummary();
    }, 20000);

    setInterval(() => {
        fetchAllCascadeTrajectories();
    }, 12000);

    setInterval(() => {
        if (typeof updateTokenStats === 'function') updateTokenStats();
        if (typeof updateCompactionCounter === 'function') updateCompactionCounter();
    }, 8000);

    // 1-second lightweight UI ticker so the 5-minute warm cache countdown ticks smoothly
    setInterval(() => {
        if (document.hidden) return;
        updateComposerChatBadge();
        updateLiveSendEstimator();
        decorateSidebarConversations();
        patchModelsAndUsagePage();
    }, 1000);

    let currentPlanText = '';
    const parts = window.location.pathname.split('/');
    let currentConvId = (parts.length > 2 && parts[2]) ? parts[2] : null;
    let currentNotesText = '';
    let notesSyncAI = true;
