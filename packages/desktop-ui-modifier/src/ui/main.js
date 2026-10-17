(async function() {
    if (window.__antigravity_ams_loaded) {
        console.log('[AMS] Script already loaded. Skipping duplicate initialization.');
        return;
    }
    window.__antigravity_ams_loaded = true;

    // DevTools-Shortcut (F12 / Ctrl+Shift+I) abfangen und triggern
    window.addEventListener('keydown', (e) => {
        if (e.key === 'F12' || (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'i')) {
            try {
                if (window.electronNative && window.electronNative.toggleDevTools) {
                    e.preventDefault();
                    window.electronNative.toggleDevTools();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle DevTools via shortcut:', err);
            }
        }

        // Quick Menu Shortcut: Ctrl+Shift+B
        if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'b') {
            try {
                e.preventDefault();
                if (window.toggleQuickMenu) {
                    window.toggleQuickMenu();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle Quick Menu via shortcut:', err);
            }
        }

        // Plan Panel Shortcut: Ctrl+Shift+P
        if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'p') {
            try {
                e.preventDefault();
                if (typeof togglePlanPanel === 'function') {
                    togglePlanPanel();
                }
            } catch (err) {
                console.error('[AMS UI] Failed to toggle Plan Panel via shortcut:', err);
            }
        }
    });

    // Kept as a compatibility argument for the exposed API. The real token
    // remains inside the context-isolated preload and is never injected here.
    const amsToken = '';

    console.log('[AMS] Initializing Autonomy & Memory System in main world...');

    let nativeStorageItems = {};
    try {
        nativeStorageItems = await window.nativeStorage.getItems() || {};
    } catch (e) {
        console.error('[AMS] Failed to load nativeStorage:', e);
    }

    // Auto-restore last active session (any page: chats, settings, history, scheduled tasks, etc.)
    try {
        const savedPath = nativeStorageItems.antigravity_last_chat_path;
        const currentPath = window.location.pathname + window.location.search;
        if ((window.location.pathname === '/' || window.location.pathname === '') && savedPath && savedPath !== '/' && !savedPath.includes('blank') && currentPath !== savedPath) {
            console.log('[AMS] Restoring last active session:', savedPath);
            window.location.href = window.location.origin + savedPath;
            return;
        }
    } catch (e) {
        console.error('[AMS] Failed to restore last active session:', e);
    }

    // Save current page path on initial load (any non-root path)
    try {
        const initialPath = window.location.pathname + window.location.search;
        if (initialPath && initialPath !== '/' && initialPath !== '' && !initialPath.includes('blank')) {
            await window.nativeStorage.updateItems({ antigravity_last_chat_path: initialPath });
        }
    } catch (e) {
        // ignore
    }

    // Auto-save and auto-restore message input draft

    // === INSERT MODULES HERE ===

    console.log('[AMS Monitor] Initializing Real-time Chat Monitor...');
    const observedMessages = new Map();
    const messageDebounceTimers = new Map();
    let lastUrl = window.location.href;

    function getSessionId() {
        const parts = window.location.pathname.split('/');
        return (parts.length > 2 && parts[2]) ? parts[2] : 'global';
    }

    function estimateTokenCount(text) {
        if (!text) return 0;
        const chars = text.length;
        const cleanText = text.replace(/\s+/g, ' ');
        const words = cleanText.split(' ').filter(Boolean).length;
        return Math.max(1, Math.round((words * 1.3 + chars / 3.5) / 2));
    }

    function getActiveModel() {
        const modelBtn = document.querySelector('button[aria-label^="Select model, current:"]');
        if (modelBtn) {
            const text = modelBtn.textContent.trim();
            if (text) {
                window.__antigravity_last_model = text;
                return text;
            }
        }
        return window.__antigravity_last_model || 'Gemini 3.5 Flash (High)';
    }

    function formatTokenCount(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(2) + 'M';
        }
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }

    function writeLiveLog(source, content) {
        if (!window.electronNative || !window.electronNative.writeLogEntry) return;
        const session = getSessionId();
        const activeModel = getActiveModel();
        const tokensVal = estimateTokenCount(content);
        const entry = {
            session_id: session,
            event: 'message',
            source: source,
            content: content,
            timestamp: new Date().toISOString(),
            model: activeModel,
            tokens: tokensVal,
            metadata: {
                url: window.location.href
            }
        };
        window.electronNative.writeLogEntry(entry)
            .then(() => {
                console.log('[AMS Monitor] Live log entry written successfully.');
            })
            .catch(err => {
                console.error('[AMS Monitor] Failed to write live log entry:', err);
            });
    }

    function triggerMessageDebounce(el, source, content) {
        if (messageDebounceTimers.has(el)) {
            clearTimeout(messageDebounceTimers.get(el));
        }

        const timer = setTimeout(() => {
            messageDebounceTimers.delete(el);
            console.log('[AMS Monitor] Debounce finished. Writing final ' + source + ' message.');
            writeLiveLog(source, content);
        }, 2000);

        messageDebounceTimers.set(el, timer);
    }

    function scanMessages(isInitial = false) {
        const messageElements = document.querySelectorAll('[role="article"]');
        messageElements.forEach(el => {
            const label = el.getAttribute('aria-label') || '';
            const isUser = label.includes('User message');
            const isAgent = label.includes('Agent response');

            if (!isUser && !isAgent) return;

            const type = isUser ? 'User' : 'Agent';
            const textEl = isUser ? el.querySelector('.whitespace-pre-wrap') : el.querySelector('.select-text');
            if (!textEl) return;

            const text = textEl.textContent || '';
            if (!observedMessages.has(el)) {
                observedMessages.set(el, text);
                if (!isInitial) {
                    console.log('[AMS Monitor] New ' + type + ' Message detected (debouncing)...');
                    triggerMessageDebounce(el, type.toUpperCase(), text);
                }
            } else {
                const prevText = observedMessages.get(el);
                if (prevText !== text) {
                    observedMessages.set(el, text);
                    if (!isInitial) {
                        triggerMessageDebounce(el, type.toUpperCase(), text);
                    }
                }
            }
        });
    }

    // Safely initialize the MutationObserver and initial scan when document.body is ready
    function initMonitor() {
        if (!document.body) {
            setTimeout(initMonitor, 50);
            return;
        }

        scanMessages(true);

        const domObserver = new MutationObserver(() => {
            scheduleScan();
        });

        domObserver.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    let scanTimeout = null;
    function scheduleScan() {
        if (scanTimeout) return;
        scanTimeout = setTimeout(() => {
            scanTimeout = null;
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;

                // Update currentConvId dynamically on URL changes
                const urlParts = window.location.pathname.split('/');
                currentConvId = (urlParts.length > 2 && urlParts[2]) ? urlParts[2] : null;

                // Reload task plan for the new active chat
                loadInitialPlan();

                // Save last active session path (any non-root URL: chats, settings, history, scheduled tasks, etc.)
                try {
                    const path = window.location.pathname + window.location.search;
                    if (path && path !== '/' && path !== '') {
                        window.nativeStorage.updateItems({ antigravity_last_chat_path: path });
                    }
                } catch (e) {
                    console.error('[AMS] Failed to save active session path:', e);
                }

                observedMessages.clear();
                // Clear any pending debounces on URL change
                for (const timer of messageDebounceTimers.values()) {
                    clearTimeout(timer);
                }
                messageDebounceTimers.clear();

                scanMessages(true);
            } else {
                scanMessages(false);
            }

            // Clean up old elements
            if (document.body) {
                for (const [el, text] of observedMessages.entries()) {
                    if (!document.body.contains(el)) {
                        observedMessages.delete(el);
                        if (messageDebounceTimers.has(el)) {
                            clearTimeout(messageDebounceTimers.get(el));
                            messageDebounceTimers.delete(el);
                        }
                    }
                }
            }
        }, 100);
    }

    // Heartbeat transmitter (pings preload context every 2 seconds)
    setInterval(() => {
        try {
            window.postMessage({ type: 'antigravity-heartbeat-ping' }, window.location.origin);
        } catch (e) {}
    }, 2000);

    // Auto-Updater Check and Dialog
    if (window.electronUpdater && window.electronUpdater.onStateChanged) {
        let lastUpdateDetails = null;
        let lastDialogKey = null;
        const mergeUpdateDetails = (update) => {
            if (!update || typeof update !== 'object') return;
            const next = { ...(lastUpdateDetails || {}) };
            ['version', 'releaseNotes', 'releaseDate', 'releaseName'].forEach((key) => {
                if (update[key] !== undefined && update[key] !== null && update[key] !== '') {
                    next[key] = update[key];
                }
            });
            lastUpdateDetails = next;
        };
        const handleUpdateState = (state) => {
            console.log('[AMS Updater Watcher] State changed:', state);
            if (!state || typeof state.type !== 'string') return;
            mergeUpdateDetails(state.update);
            const details = lastUpdateDetails || {};
            const version = details.version || 'unbekannt';
            if (state.type === 'available for download' || state.type === 'downloading') {
                const dialogKey = 'background:' + version;
                if (lastDialogKey === dialogKey) return;
                lastDialogKey = dialogKey;
                showUpdateConfirm(version, details.releaseNotes || null, 'background', () => {}, details);
            } else if (state.type === 'ready') {
                const dialogKey = 'install:' + version;
                if (lastDialogKey === dialogKey) return;
                lastDialogKey = dialogKey;
                showUpdateConfirm(version, details.releaseNotes || null, 'install', (confirmed) => {
                    if (!confirmed) return;
                    console.log('[AMS Updater Watcher] Installing downloaded update.');
                    Promise.resolve(window.electronUpdater.quitAndInstall()).catch((error) => {
                        console.error('[AMS Updater Watcher] Could not install update:', error);
                    });
                }, details);
            }
        };
        window.electronUpdater.onStateChanged(handleUpdateState);
        if (typeof window.electronUpdater.getState === 'function') {
            Promise.resolve(window.electronUpdater.getState())
                .then(handleUpdateState)
                .catch((error) => {
                    console.warn('[AMS Updater Watcher] Could not restore update state:', error);
                });
        }
    }

    initMonitor();
})();
