    let currentQuotaData = {
        gemini5h: 100,
        geminiWeekly: 100,
        geminiWeeklyDesc: '',
        gemini5hDesc: '',

        claude5h: 100,
        claudeWeekly: 100,
        claudeWeeklyDesc: '',
        claude5hDesc: ''
    };


    const originalFetch = window.fetch;

    async function fetchUserQuotaSummary() {
        try {
            const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
            if (!csrfToken) return;

            const bodyStr = '{"forceRefresh":false}';
            const len = bodyStr.length;
            const header = new Uint8Array(5);
            header[0] = 0;
            header[1] = (len >> 24) & 0xFF;
            header[2] = (len >> 16) & 0xFF;
            header[3] = (len >> 8) & 0xFF;
            header[4] = len & 0xFF;

            const bodyBytes = new TextEncoder().encode(bodyStr);
            const reqBytes = new Uint8Array(5 + bodyBytes.length);
            reqBytes.set(header, 0);
            reqBytes.set(bodyBytes, 5);

            const response = await originalFetch('/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary', {
                method: 'POST',
                headers: {
                    'content-type': 'application/grpc-web+json',
                    'x-codeium-csrf-token': csrfToken,
                    'x-grpc-web': '1',
                    'x-user-agent': 'CONNECT_ES_USER_AGENT'
                },
                body: reqBytes
            });

            const text = await response.text();
            handleRetrieveUserQuotaSummaryText(text);
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to fetch user quota summary:', err);
        }
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
        if (!text) return;
        try {
            const jsonStart = text.indexOf('{');
            const jsonEnd = text.lastIndexOf('}');
            if (jsonStart !== -1 && jsonEnd !== -1) {
                const jsonStr = text.substring(jsonStart, jsonEnd + 1);
                const data = JSON.parse(jsonStr);
                if (data && data.response && data.response.groups) {
                    const groups = data.response.groups;

                    const geminiGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('gemini'));
                    const claudeGroup = groups.find(g => g.displayName && g.displayName.toLowerCase().includes('claude'));

                    if (geminiGroup && geminiGroup.buckets) {
                        const weeklyBucket = geminiGroup.buckets.find(b => b.window === 'weekly');
                        const fiveHourBucket = geminiGroup.buckets.find(b => b.window === '5h');

                        if (weeklyBucket) {
                            currentQuotaData.geminiWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                            currentQuotaData.geminiWeeklyDesc = weeklyBucket.description || '';
                        } else {
                            currentQuotaData.geminiWeekly = 100;
                            currentQuotaData.geminiWeeklyDesc = '';
                        }
                        if (fiveHourBucket) {
                            currentQuotaData.gemini5h = Math.round(fiveHourBucket.remainingFraction * 100);
                            currentQuotaData.gemini5hDesc = fiveHourBucket.description || '';
                        } else {
                            currentQuotaData.gemini5h = 100;
                            currentQuotaData.gemini5hDesc = '';
                        }
                    }

                    if (claudeGroup && claudeGroup.buckets) {
                        const weeklyBucket = claudeGroup.buckets.find(b => b.window === 'weekly');
                        const fiveHourBucket = claudeGroup.buckets.find(b => b.window === '5h');

                        if (weeklyBucket) {
                            currentQuotaData.claudeWeekly = Math.round(weeklyBucket.remainingFraction * 100);
                            currentQuotaData.claudeWeeklyDesc = weeklyBucket.description || '';
                        } else {
                            currentQuotaData.claudeWeekly = 0;
                            currentQuotaData.claudeWeeklyDesc = '0%';
                        }
                        if (fiveHourBucket) {
                            currentQuotaData.claude5h = Math.round(fiveHourBucket.remainingFraction * 100);
                            currentQuotaData.claude5hDesc = fiveHourBucket.description || '';
                        } else {
                            currentQuotaData.claude5h = 0;
                            currentQuotaData.claude5hDesc = '0%';
                        }
                    } else {
                        currentQuotaData.claudeWeekly = 0;
                        currentQuotaData.claudeWeeklyDesc = 'Ablauf';
                        currentQuotaData.claude5h = 0;
                        currentQuotaData.claude5hDesc = 'Ablauf';
                    }
                    refreshQuotaDisplay();
                }
            }
        } catch (err) {
            console.error('[AMS Quota Interceptor] Failed to parse RetrieveUserQuotaSummary JSON:', err);
        }
    }

    function handleGetUserStatusText(text) {
        if (!text) return;
        try {
            const jsonStart = text.indexOf('{');
            const jsonEnd = text.lastIndexOf('}');
            if (jsonStart !== -1 && jsonEnd !== -1) {
                const jsonStr = text.substring(jsonStart, jsonEnd + 1);
                const data = JSON.parse(jsonStr);
                if (data && data.userStatus && data.userStatus.cascadeModelConfigData) {
                    const configs = data.userStatus.cascadeModelConfigData.clientModelConfigs || [];
                    const geminiConfig = configs.find(c => c.label && c.label.toLowerCase().includes('gemini'));
                    const claudeConfig = configs.find(c => c.label && c.label.toLowerCase().includes('claude'));

                    if (geminiConfig && geminiConfig.quotaInfo) {
                        currentQuotaData.gemini5h = Math.round(geminiConfig.quotaInfo.remainingFraction * 100);
                    }
                    if (claudeConfig && claudeConfig.quotaInfo) {
                        currentQuotaData.claude5h = Math.round(claudeConfig.quotaInfo.remainingFraction * 100);
                    } else {
                        currentQuotaData.claude5h = 0;
                    }
                    fetchUserQuotaSummary();
                }
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
                    const clone = response.clone();
                    const text = await clone.text();
                    handleGetUserStatusText(text);
                } else if (url.includes('RetrieveUserQuotaSummary')) {
                    const clone = response.clone();
                    const text = await clone.text();
                    handleRetrieveUserQuotaSummaryText(text);
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
                        const text = this.responseText;
                        handleGetUserStatusText(text);
                    } else if (this._url.includes('RetrieveUserQuotaSummary')) {
                        const text = this.responseText;
                        handleRetrieveUserQuotaSummaryText(text);
                    }
                }
            } catch (err) {
                console.error('[AMS Quota Interceptor] Error intercepting XHR:', err);
            }
        });
        return originalSend.apply(this, args);
    };

    let isSwitchingModel = false;

    function showQuotaFallbackToast(modelName) {
        const toast = document.createElement('div');
        toast.className = 'antigravity-quota-toast';
        toast.style.position = 'fixed';
        toast.style.bottom = '24px';
        toast.style.right = '24px';
        toast.style.padding = '12px 20px';
        toast.style.borderRadius = '8px';
        toast.style.background = 'var(--card, #1c1917)';
        toast.style.border = '1px solid #ef4444';
        toast.style.color = 'var(--foreground, #ffffff)';
        toast.style.fontSize = '12px';
        toast.style.fontWeight = '500';
        toast.style.zIndex = '999999';
        toast.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.5)';
        toast.style.display = 'flex';
        toast.style.alignItems = 'center';
        toast.style.gap = '8px';
        toast.style.fontFamily = 'ui-sans-serif, system-ui, sans-serif';
        toast.style.transform = 'translateY(20px)';
        toast.style.opacity = '0';
        toast.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';

        toast.innerHTML =
            '<span style="display: flex; align-items: center; justify-content: center; background: #ef4444; color: white; border-radius: 50%; width: 18px; height: 18px; font-weight: bold; font-size: 11px;">!</span>' +
            '<span><strong>Quoten-Wächter:</strong> Claude verbraucht. Automatisch auf ' + modelName + ' umgeschaltet.</span>';

        document.body.appendChild(toast);

        // Force reflow
        toast.offsetHeight;

        // Animate in
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';

        setTimeout(() => {
            toast.style.transform = 'translateY(20px)';
            toast.style.opacity = '0';
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 5000);
    }

    async function switchModel(targetModelName) {
        console.log('[AMS Quota Watchdog] Attempting to switch model to:', targetModelName);
        const selectorBtn = document.querySelector('button[aria-label^="Select model, current:"]');
        if (!selectorBtn) {
            console.error('[AMS Quota Watchdog] Model selector button not found.');
            return false;
        }

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
                console.log('[AMS Quota Watchdog] Found target model button, clicking...');
                targetBtn.click();
                showQuotaFallbackToast(targetModelName);
                return true;
            } else {
                console.error('[AMS Quota Watchdog] Target model button not found for text:', targetModelName);
                selectorBtn.click();
                return false;
            }
        } catch (e) {
            console.error('[AMS Quota Watchdog] Error switching model:', e);
            return false;
        }
    }

    function refreshQuotaDisplay() {
        const quotaEl = document.querySelector('.antigravity-quota-display');
        if (!quotaEl) return;

        const g5h = currentQuotaData.gemini5h;
        const gW = currentQuotaData.geminiWeekly;
        const c5h = currentQuotaData.claude5h;
        const cW = currentQuotaData.claudeWeekly;

        const gDisplay = (gW === 0) ? 0 : g5h;
        const cDisplay = (cW === 0) ? 0 : c5h;

        function getTooltipLine(label, pct, desc) {
            const cleaned = cleanResetTime(desc);
            if (!cleaned || cleaned === 'Aktiv' || cleaned === pct + '%') {
                return '• ' + label + ': ' + pct + '%';
            }
            return '• ' + label + ': ' + pct + '% (' + cleaned + ')';
        }

        let gTooltip = 'Gemini:\n' +
                       getTooltipLine('5h', g5h, currentQuotaData.gemini5hDesc) + '\n' +
                       getTooltipLine('Weekly', gW, currentQuotaData.geminiWeeklyDesc);

        let cTooltip = 'Claude:\n' +
                       getTooltipLine('5h', c5h, currentQuotaData.claude5hDesc) + '\n' +
                       getTooltipLine('Weekly', cW, currentQuotaData.claudeWeeklyDesc);

        function getPercentColor(pct) {
            if (pct > 50) return '';
            if (pct > 20) return 'color: #eab308;';
            return 'color: #ef4444; font-weight: bold;';
        }

        const createQuotaValue = (label, display, tooltip) => {
            const value = document.createElement('span');
            value.title = String(tooltip || '');
            value.style.cssText = getPercentColor(display);
            value.textContent = label + ': ' + String(display) + '%';
            return value;
        };
        const separator = document.createElement('span');
        separator.style.opacity = '0.4';
        separator.textContent = '|';
        quotaEl.replaceChildren(
            createQuotaValue('G', gDisplay, gTooltip),
            separator,
            createQuotaValue('C', cDisplay, cTooltip)
        );

        // Quoten-Wächter (Model Fallback)
        if (!isSwitchingModel) {
            const activeModel = getActiveModel();
            if (activeModel.startsWith('Claude')) {
                if (cDisplay === 0 || c5h === 0 || cW === 0) {
                    console.log('[AMS Quota Watchdog] Claude quota depleted! Triggering automatic fallback to Gemini...');
                    isSwitchingModel = true;
                    switchModel('Gemini 3.5 Flash (High)').finally(() => {
                        isSwitchingModel = false;
                    });
                }
            }
        }
    }


    // Start Polling for weekly quota
    setTimeout(() => {
        fetchUserQuotaSummary();
    }, 1500);

    setInterval(() => {
        fetchUserQuotaSummary();
    }, 30000);

    setInterval(() => {
        updateTokenStats();
        updateCompactionCounter();
    }, 10000);

    let currentPlanText = '';
    const parts = window.location.pathname.split('/');
    let currentConvId = (parts.length > 2 && parts[2]) ? parts[2] : null;
    let currentNotesText = '';
    let notesSyncAI = true;
