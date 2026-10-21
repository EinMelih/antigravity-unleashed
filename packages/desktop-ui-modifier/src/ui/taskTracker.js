    function generateSubtasks(item, type) {
        var tasks = [];
        if (item.body) {
            var lines = item.body.split('\n');
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var match = line.match(/^\s*[-*]\s*\[([ xX])\]\s*(.+)$/);
                if (match) {
                    tasks.push('- [ ] ' + match[2].trim());
                }
            }
        }
        if (tasks.length === 0) {
            tasks = [
                '- [ ] Anforderungen & Codebasis analysieren',
                '- [ ] Implementierung vorbereiten & Code anpassen',
                '- [ ] Änderungen lokal testen & verifizieren',
                '- [ ] Pull Request erstellen / Issue abschließen'
            ];
        }
        var titleClean = item.title.replace(/[#*`[\]]/g, '');
        return '# ' + type + ' #' + item.number + ': ' + titleClean + '\n\n' + tasks.join('\n');
    }


    async function loadNotesUI() {
        const textarea = document.getElementById('antigravity-notes-textarea');
        const checkbox = document.getElementById('antigravity-notes-sync-ai');
        if (!textarea || !checkbox) return;

        try {
            if (currentConvId && window.electronNative && window.electronNative.getNotes) {
                const res = await window.electronNative.getNotes(currentConvId);
                if (res && res.status === 'success') {
                    currentNotesText = res.notes || '';
                    notesSyncAI = res.syncAI;
                    textarea.value = currentNotesText;
                    checkbox.checked = notesSyncAI;
                    return;
                }
            }
        } catch (e) {
            console.error('[AMS] Failed to load notes from notes.txt:', e);
        }

        // Fallback to nativeStorage
        const storageKey = 'antigravity_notes_' + currentConvId;
        const syncKey = 'antigravity_notes_sync_ai_' + currentConvId;
        currentNotesText = nativeStorageItems[storageKey] || '';
        notesSyncAI = nativeStorageItems[syncKey] !== false; // default to true

        textarea.value = currentNotesText;
        checkbox.checked = notesSyncAI;
    }

    async function updateCompactionCounter() {
        const counterEl = document.getElementById('antigravity-compaction-counter');
        if (!counterEl) return;

        if (!currentConvId || !window.electronNative || !window.electronNative.getCompactionCount) {
            counterEl.style.display = 'none';
            return;
        }

        try {
            const res = await window.electronNative.getCompactionCount(currentConvId);
            if (res && res.status === 'success') {
                const count = res.count || 0;
                counterEl.querySelector('span').textContent = 'Compacts: ' + count;
                counterEl.style.display = 'inline-flex';
                if (count > 0) {
                    counterEl.style.color = '#3b82f6';
                    counterEl.style.borderColor = 'rgba(59, 130, 246, 0.2)';
                    counterEl.style.background = 'rgba(59, 130, 246, 0.05)';
                    counterEl.title = 'Dieses Gespräch wurde bereits ' + count + ' mal automatisch kompaktwert / bereinigt.';
                } else {
                    counterEl.style.color = 'var(--muted-foreground, #71717a)';
                    counterEl.style.borderColor = 'var(--border, rgba(255,255,255,0.05))';
                    counterEl.style.background = 'rgba(255,255,255,0.03)';
                    counterEl.title = 'Bisher wurden keine automatischen Kompaktierungen durchgeführt.';
                }
            } else {
                counterEl.style.display = 'none';
            }
        } catch (e) {
            console.error('[AMS] Failed to fetch compaction count:', e);
            counterEl.style.display = 'none';
        }
    }

    async function updateTokenStats() {
        const chatTokenEl = document.getElementById('antigravity-chat-token-counter');
        const footerTokenEl = document.getElementById('antigravity-token-counter');

        if (!window.electronNative || !window.electronNative.getTokenStats) {
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
            return;
        }

        const fallbackCid = (window.amsTelemetryState && window.amsTelemetryState.liveTrajectoriesMap && window.amsTelemetryState.liveTrajectoriesMap.keys().next().value) ||
                            (document.querySelector('[data-cascade-id]') && document.querySelector('[data-cascade-id]').getAttribute('data-cascade-id')) ||
                            null;
        const targetConvId = currentConvId || fallbackCid;

        if (!targetConvId) {
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
            return;
        }

        try {
            const res = await window.electronNative.getTokenStats(targetConvId);
            if (res && res.status === 'success') {
                if (typeof window.amsIngestTokenStatsResult === 'function') {
                    window.amsIngestTokenStatsResult(res, targetConvId === currentConvId);
                }

                if (targetConvId !== currentConvId) {
                    if (chatTokenEl) chatTokenEl.style.display = 'none';
                    if (footerTokenEl) footerTokenEl.style.display = 'none';
                    return;
                }

                const totalIn = res.totalInput || 0;
                const totalOut = res.totalOutput || 0;
                const totalUncached = res.totalUncached || 0;
                const totalCached = res.totalCached || 0;
                const cacheRatio = res.cacheRatio || 0.0;
                const weeklyPctUsed = Number(res.weeklyPctUsed || 0).toFixed(4);
                const fiveHourPctUsed = Number(res.fiveHourPctUsed || 0).toFixed(4);
                const apiCostEur = Number(res.apiCostEur || 0).toFixed(2);
                const apiSavedEur = Number(res.apiSavedEur || 0).toFixed(2);

                const latestIn = res.latestInput || 0;
                const latestOut = res.latestOutput || 0;
                const latestUncached = res.latestUncached || 0;
                const latestCached = res.latestCached || 0;

                function formatTokens(num) {
                    if (num >= 1000000) {
                        return (num / 1000000).toFixed(1) + 'M';
                    }
                    if (num >= 1000) {
                        return (num / 1000).toFixed(0) + 'k';
                    }
                    return num.toString();
                }

                const totalStr = formatTokens(totalIn);

                if (footerTokenEl) {
                    footerTokenEl.querySelector('span').textContent = 'Tokens: ' + totalStr + ' (-' + weeklyPctUsed + '% W)';
                    footerTokenEl.style.display = 'inline-flex';

                    const tooltip =
                        'Akkumulierter Verbrauch für dieses Gespräch:\n' +
                        '• Quota-Abzug: -' + weeklyPctUsed + '% Weekly / -' + fiveHourPctUsed + '% 5h\n' +
                        '• API-Gegenwert: ' + apiCostEur + ' € (+' + apiSavedEur + ' € durch Cache gespart)\n' +
                        '• Input (Gesamt): ' + totalIn.toLocaleString('de-DE') + '\n' +
                        '  - Aus Cache: ' + totalCached.toLocaleString('de-DE') + ' (' + cacheRatio + '%)\n' +
                        '  - Uncached: ' + totalUncached.toLocaleString('de-DE') + '\n' +
                        '• Output (Antworten): ' + totalOut.toLocaleString('de-DE') + '\n\n' +
                        'Letzter Schritt:\n' +
                        '• Input: ' + latestIn.toLocaleString('de-DE') + '\n' +
                        '  - Aus Cache: ' + latestCached.toLocaleString('de-DE') + '\n' +
                        '  - Uncached: ' + latestUncached.toLocaleString('de-DE') + '\n' +
                        '• Output: ' + latestOut.toLocaleString('de-DE');
                    footerTokenEl.title = tooltip;
                }
            } else {
                if (chatTokenEl) chatTokenEl.style.display = 'none';
                if (footerTokenEl) footerTokenEl.style.display = 'none';
            }
        } catch (e) {
            console.error('[AMS] Failed to fetch token stats:', e);
            if (chatTokenEl) chatTokenEl.style.display = 'none';
            if (footerTokenEl) footerTokenEl.style.display = 'none';
        }
    }

    async function loadInitialPlan() {
        try {
            if (currentConvId && window.electronNative && window.electronNative.getTaskPlan) {
                const res = await window.electronNative.getTaskPlan(currentConvId);
                if (res && res.status === 'success') {
                    console.log('[AMS] Loaded task plan from active task.md');
                    currentPlanText = res.plan;
                    updatePlanUI();
                    loadNotesUI();
                    updateCompactionCounter();
                    updateTokenStats();
                    return;
                }
            }
        } catch (e) {
            console.error('[AMS] Failed to load plan from task.md:', e);
        }
        currentPlanText = nativeStorageItems.antigravity_task_plan ||
            '# Active Tasks\n- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3';
        updatePlanUI();
        loadNotesUI();
        updateCompactionCounter();
        updateTokenStats();
    }

    window.getTaskPlan = function() {
        return currentPlanText;
    };

    window.setTaskPlan = async function(text) {
        currentPlanText = text;
        try {
            await window.nativeStorage.updateItems({ antigravity_task_plan: text });
        } catch (e) {}
        try {
            if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                await window.electronNative.setTaskPlan(text, currentConvId);
            }
        } catch (e) {
            console.error('[AMS] Failed to write plan to task.md:', e);
        }
        updatePlanUI();
    };

    // Load the plan asynchronously at boot
    setTimeout(loadInitialPlan, 50);

    function triggerSaveStatus() {
        const indicator = document.querySelector('.antigravity-save-indicator');
        if (!indicator) return;
        indicator.className = 'antigravity-save-indicator saving';
        const txt = indicator.querySelector('span');
        if (txt) txt.textContent = 'Speichert...';

        setTimeout(() => {
            indicator.className = 'antigravity-save-indicator saved';
            const txt2 = indicator.querySelector('span');
            if (txt2) txt2.textContent = 'Gespeichert';
        }, 500);
    }

    function togglePlanPanel() {
        const panel = ensurePlanPanel();
        const isOpen = panel.classList.toggle('open');
        if (isOpen) {
            updateCompactionCounter();
            updateTokenStats();
        }
    }

    function updatePlanUI() {
        const editor = document.getElementById('antigravity-plan-editor');
        if (editor) {
            editor.value = currentPlanText;
        }
        updateChecklistFromText();
    }

    function stopKeyPropagation(el) {
        if (!el) return;
        ['keydown', 'keyup', 'keypress'].forEach(eventType => {
            el.addEventListener(eventType, (e) => {
                e.stopPropagation();
            });
        });
    }

    function ensurePlanPanel() {
        let panel = document.getElementById('antigravity-plan-panel');
        if (panel) return panel;

        panel = document.createElement('div');
        panel.id = 'antigravity-plan-panel';
        stopKeyPropagation(panel);

        const styles =
            '#antigravity-plan-panel {' +
            '    position: fixed;' +
            '    top: 30px;' +
            '    right: 0;' +
            '    width: 350px;' +
            '    height: calc(100% - 30px);' +
            '    z-index: 10000;' +
            '    background-color: var(--background, #121214);' +
            '    border-left: 1px solid var(--border, #27272a);' +
            '    box-shadow: -8px 0 24px rgba(0, 0, 0, 0.5);' +
            '    transform: translateX(100%);' +
            '    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    color: var(--foreground, #ececec);' +
            '    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;' +
            '}' +
            '#antigravity-plan-panel.open {' +
            '    transform: translateX(0);' +
            '}' +
            '.antigravity-plan-header {' +
            '    display: flex;' +
            '    align-items: center;' +
            '    justify-content: space-between;' +
            '    padding: 16px;' +
            '    border-bottom: 1px solid var(--border, #27272a);' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-plan-title {' +
            '    font-weight: 600;' +
            '    font-size: 13px;' +
            '    margin: 0;' +
            '    color: var(--foreground, #ffffff);' +
            '    letter-spacing: 0.05em;' +
            '    text-transform: uppercase;' +
            '    opacity: 0.9;' +
            '}' +
            '.antigravity-plan-close {' +
            '    cursor: pointer;' +
            '    background: transparent;' +
            '    border: none;' +
            '    color: var(--muted-foreground, #a1a1aa);' +
            '    padding: 4px;' +
            '    border-radius: 4px;' +
            '    display: flex;' +
            '    align-items: center;' +
            '    justify-content: center;' +
            '    transition: background-color 0.2s, color 0.2s;' +
            '}' +
            '.antigravity-plan-close:hover {' +
            '    background-color: var(--secondary, #27272a);' +
            '    color: var(--foreground, #ffffff);' +
            '}' +
            '.antigravity-plan-content {' +
            '    flex: 1;' +
            '    overflow-y: auto;' +
            '    padding: 16px;' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    gap: 16px;' +
            '}' +
            '.antigravity-plan-mode-tabs {' +
            '    display: flex;' +
            '    border-bottom: 1px solid var(--border, #27272a);' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-plan-tab {' +
            '    flex: 1;' +
            '    text-align: center;' +
            '    padding: 10px;' +
            '    font-size: 13px;' +
            '    cursor: pointer;' +
            '    border-bottom: 2px solid transparent;' +
            '    transition: all 0.2s;' +
            '    font-weight: 500;' +
            '    color: var(--muted-foreground, #a1a1aa);' +
            '}' +
            '.antigravity-plan-tab.active {' +
            '    border-bottom-color: var(--foreground, #ffffff);' +
            '    color: var(--foreground, #ffffff);' +
            '    background-color: rgba(255, 255, 255, 0.03);' +
            '}' +
            '.antigravity-plan-textarea {' +
            '    flex: 1;' +
            '    width: 100%;' +
            '    background-color: var(--input, #09090b);' +
            '    border: 1px solid var(--border, #27272a);' +
            '    border-radius: 8px;' +
            '    padding: 12px;' +
            '    color: var(--foreground, #ececec);' +
            '    font-family: monospace;' +
            '    font-size: 13px;' +
            '    resize: none;' +
            '    line-height: 1.5;' +
            '    outline: none;' +
            '    transition: border-color 0.2s;' +
            '}' +
            '.antigravity-plan-textarea:focus {' +
            '    border-color: #3b82f6;' +
            '}' +
            '.antigravity-plan-checklist {' +
            '    display: flex;' +
            '    flex-direction: column;' +
            '    gap: 10px;' +
            '}' +
            '.antigravity-checklist-item {' +
            '    display: flex;' +
            '    align-items: flex-start;' +
            '    gap: 8px;' +
            '    padding: 6px;' +
            '    border-radius: 6px;' +
            '    transition: background-color 0.2s;' +
            '}' +
            '.antigravity-checklist-item:hover {' +
            '    background-color: rgba(255, 255, 255, 0.02);' +
            '}' +
            '.antigravity-checklist-cb {' +
            '    margin-top: 3px;' +
            '    cursor: pointer;' +
            '    accent-color: #3b82f6;' +
            '    width: 14px;' +
            '    height: 14px;' +
            '}' +
            '.antigravity-checklist-text {' +
            '    font-size: 13px;' +
            '    line-height: 1.4;' +
            '    cursor: pointer;' +
            '    user-select: none;' +
            '}' +
            '.antigravity-checklist-text.checked {' +
            '    text-decoration: line-through;' +
            '    opacity: 0.5;' +
            '}' +
            '.antigravity-checklist-item:hover .antigravity-checklist-delete {' +
            '    display: inline-flex !important;' +
            '}' +
            '.antigravity-checklist-delete:hover {' +
            '    color: #ef4444 !important;' +
            '}' +
            '.antigravity-checklist-add-btn:hover {' +
            '    background-color: var(--secondary, #27272a);' +
            '    color: var(--foreground, #ffffff) !important;' +
            '}' +
            '.antigravity-plan-footer {' +
            '    padding: 12px 16px;' +
            '    border-top: 1px solid var(--border, #27272a);' +
            '    font-size: 11px;' +
            '    color: var(--muted-foreground, #71717a);' +
            '    display: flex;' +
            '    justify-content: space-between;' +
            '    align-items: center;' +
            '    background-color: var(--card, #18181b);' +
            '}' +
            '.antigravity-save-indicator {' +
            '    display: flex;' +
            '    align-items: center;' +
            '    gap: 4px;' +
            '    opacity: 0.7;' +
            '    transition: opacity 0.3s;' +
            '}' +
            '.antigravity-save-indicator.saving {' +
            '    opacity: 1;' +
            '    color: #eab308;' +
            '}' +
            '.antigravity-save-indicator.saved {' +
            '    color: #22c55e;' +
            '}' +
            '@keyframes modalFadeIn {' +
            '    from { opacity: 0; transform: scale(0.97); }' +
            '    to { opacity: 1; transform: scale(1); }' +
            '}' +
            '@keyframes antigravity-spin {' +
            '    from { transform: rotate(0deg); }' +
            '    to { transform: rotate(360deg); }' +
            '}' +
            '.antigravity-spinner {' +
            '    animation: antigravity-spin 1s linear infinite;' +
            '}';

        const styleEl = document.createElement('style');
        styleEl.id = 'antigravity-plan-panel-styles';
        styleEl.innerHTML = styles;
        document.head.appendChild(styleEl);

        panel.innerHTML =
            '<div class="antigravity-plan-header">' +
            '    <h3 class="antigravity-plan-title" style="display:flex;align-items:center;gap:7px;">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
            '            <ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.8" stroke-opacity="0.9"/>' +
            '            <polygon points="12,3 19.4,12 12,21 4.6,12" fill="rgba(139,92,246,0.28)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
            '            <circle cx="12" cy="12" r="2.2" fill="#f8fafc"/>' +
            '        </svg>' +
            '        <span>Task & Plan Tracker</span>' +
            '    </h3>' +
            '    <button class="antigravity-plan-close" title="Schließen">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '            <line x1="18" y1="6" x2="6" y2="18"></line>' +
            '            <line x1="6" y1="6" x2="18" y2="18"></line>' +
            '        </svg>' +
            '    </button>' +
            '</div>' +
            '<div class="antigravity-plan-mode-tabs">' +
            '    <div class="antigravity-plan-tab active" data-tab="notes">Notizen</div>' +
            '    <div class="antigravity-plan-tab" data-tab="prs">Pull Requests</div>' +
            '    <div class="antigravity-plan-tab" data-tab="issues">Issues</div>' +
            '    <div class="antigravity-plan-tab" data-tab="reviews">Reviews</div>' +
            '</div>' +
            '<div class="antigravity-plan-content">' +
            '    <div id="antigravity-plan-notes-container" class="antigravity-plan-notes" style="display: flex; flex-direction: column; gap: 10px; height: 100%; flex: 1;">' +
            '        <textarea id="antigravity-notes-textarea" class="antigravity-plan-textarea" placeholder="Hinterlasse hier deine freien Notizen für dieses Gespräch..."></textarea>' +
            '        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; padding: 4px 0; color: var(--muted-foreground, #71717a);">' +
            '            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;">' +
            '                <input type="checkbox" id="antigravity-notes-sync-ai" style="cursor: pointer; accent-color: #3b82f6;" checked> ' +
            '                <span>Als AI-Kontext (notes.txt) freigeben</span>' +
            '            </label>' +
            '        </div>' +
            '    </div>' +
            '    <div id="antigravity-plan-prs-container" class="antigravity-plan-prs" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '    <div id="antigravity-plan-issues-container" class="antigravity-plan-issues" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '    <div id="antigravity-plan-reviews-container" class="antigravity-plan-reviews" style="display: none; flex-direction: column; gap: 12px; height: 100%; overflow-y: auto;"></div>' +
            '</div>' +
            '<div class="antigravity-plan-footer" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-top: 1px solid var(--border, #27272a); background-color: var(--card, #18181b);">' +
            '    <button class="antigravity-git-sync-btn" title="Mit GitHub synchronisieren" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: inline-flex; align-items: center; gap: 4px; transition: background-color 0.2s; outline: none;">' +
            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>' +
            '        Git Sync' +
            '    </button>' +
            '    <div style="display: flex; align-items: center; gap: 8px;">' +
            '        <span id="antigravity-compaction-counter" style="font-size: 10px; color: var(--muted-foreground, #71717a); display: none; align-items: center; gap: 3px; cursor: help; background: rgba(255,255,255,0.03); border: 1px solid var(--border, rgba(255,255,255,0.05)); padding: 2px 6px; border-radius: 4px;" title="Anzahl der durchgeführten Kontext-Kompaktierungen für dieses Gespräch">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="14" x2="20" y2="14"></line><line x1="4" y1="6" x2="20" y2="6"></line><line x1="4" y1="10" x2="20" y2="10"></line><line x1="4" y1="18" x2="20" y2="18"></line></svg>' +
            '            <span>Compacts: 0</span>' +
            '        </span>' +
            '        <span id="antigravity-token-counter" style="font-size: 10px; color: var(--muted-foreground, #71717a); display: none; align-items: center; gap: 3px; cursor: help; background: rgba(255,255,255,0.03); border: 1px solid var(--border, rgba(255,255,255,0.05)); padding: 2px 6px; border-radius: 4px;" title="Token-Verbrauch für dieses Gespräch (Details per Hover)">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>' +
            '            <span>Tokens: -</span>' +
            '        </span>' +
            '        <span class="antigravity-save-indicator saved">' +
            '            <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">' +
            '                <polyline points="20 6 9 17 4 12"></polyline>' +
            '            </svg>' +
            '            <span>Gespeichert</span>' +
            '        </span>' +
            '    </div>' +
            '</div>';

        document.body.appendChild(panel);

        panel.querySelector('.antigravity-plan-close').addEventListener('click', togglePlanPanel);

        const syncBtn = panel.querySelector('.antigravity-git-sync-btn');
        let gitCheckInterval = null;

        async function updateGitSyncButtonStatus() {
            const btn = panel.querySelector('.antigravity-git-sync-btn');
            if (!btn) return;
            try {
                const parts = window.location.pathname.split('/');
                const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

                const res = await window.electronNative.getGitStatus(conversationId);
                if (res && res.status === 'success') {
                    const count = res.totalChanges;
                    if (count === 0) {
                        btn.disabled = true;
                        btn.style.opacity = '0.5';
                        btn.style.cursor = 'not-allowed';
                        btn.title = 'Keine uncommitted Änderungen im Workspace vorhanden';
                        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Git Sync';
                    } else {
                        btn.disabled = false;
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';
                        btn.title = count + ' geänderte Datei(en) im Workspace. Klicken zum Synchronisieren.';
                        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Git Sync (' + count + ')';
                    }
                }
            } catch (err) {
                console.error('[AMS UI] Failed to check git status for badge:', err);
            }
        }

        if (syncBtn) {
            // Initial check after rendering
            setTimeout(updateGitSyncButtonStatus, 500);
            gitCheckInterval = setInterval(updateGitSyncButtonStatus, 15000);

            syncBtn.addEventListener('click', (e) => {
                e.stopPropagation();

                const parts = window.location.pathname.split('/');
                const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

                showGitSyncModal(conversationId, async (commitMsg) => {
                    syncBtn.disabled = true;
                    syncBtn.textContent = 'Syncing...';

                    try {
                        const res = await window.electronNative.commitAndPush(commitMsg || 'wip: sync tasks', conversationId);
                        if (res.status === 'success') {
                            showCustomAlert('Synchronisation erfolgreich abgeschlossen!\n\n' + res.details);
                            updateGitSyncButtonStatus();
                        } else {
                            showCustomAlert('Fehler bei der Synchronisation:\n\n' + (res.message || 'Unbekannter Fehler'));
                        }
                    } catch (err) {
                        showCustomAlert('Ausnahmefehler bei der Synchronisation: ' + err.message);
                    } finally {
                        syncBtn.disabled = false;
                        updateGitSyncButtonStatus();
                    }
                });
            });
        }

        const textarea = panel.querySelector('#antigravity-notes-textarea');
        const checkbox = panel.querySelector('#antigravity-notes-sync-ai');

        const saveNotes = async () => {
            const text = textarea.value;
            const syncAI = checkbox.checked;
            currentNotesText = text;
            notesSyncAI = syncAI;

            const storageKey = 'antigravity_notes_' + currentConvId;
            const syncKey = 'antigravity_notes_sync_ai_' + currentConvId;
            const updateObj = {};
            updateObj[storageKey] = text;
            updateObj[syncKey] = syncAI;
            window.nativeStorage.updateItems(updateObj);

            if (currentConvId && window.electronNative && window.electronNative.setNotes) {
                await window.electronNative.setNotes(text, syncAI, currentConvId);
            }
            triggerSaveStatus();
        };

        if (textarea && checkbox) {
            textarea.addEventListener('input', saveNotes);
            checkbox.addEventListener('change', saveNotes);
        }

        // Initial load for notes
        setTimeout(loadNotesUI, 50);

        const tabs = panel.querySelectorAll('.antigravity-plan-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const mode = tab.getAttribute('data-tab');
                const notesContainer = panel.querySelector('#antigravity-plan-notes-container');
                const prsContainer = panel.querySelector('#antigravity-plan-prs-container');
                const issuesContainer = panel.querySelector('#antigravity-plan-issues-container');
                const reviewsContainer = panel.querySelector('#antigravity-plan-reviews-container');

                if (mode === 'notes') {
                    notesContainer.style.display = 'flex';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'none';
                    loadNotesUI();
                } else if (mode === 'prs') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'flex';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'none';
                    updatePRsUI();
                } else if (mode === 'issues') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'flex';
                    reviewsContainer.style.display = 'none';
                    updateIssuesUI();
                } else if (mode === 'reviews') {
                    notesContainer.style.display = 'none';
                    prsContainer.style.display = 'none';
                    issuesContainer.style.display = 'none';
                    reviewsContainer.style.display = 'flex';
                    updateReviewsUI();
                }
            });
        });

        return panel;
    }


    function updateChecklistFromText() {
        const container = document.getElementById('antigravity-plan-preview-container');
        if (!container) return;

        container.innerHTML = '';
        const lines = currentPlanText.split('\n');
        let hasTasks = false;

        lines.forEach((line, index) => {
            const match = line.match(/^(\s*)-\s*\[([ xX])\]\s*(.*)$/);
            if (match) {
                hasTasks = true;
                const indent = match[1] || '';
                const checked = match[2].toLowerCase() === 'x';
                const text = match[3].trim();

                const item = document.createElement('div');
                item.className = 'antigravity-checklist-item';
                item.style.paddingLeft = (indent.length * 8 + 6) + 'px';
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.width = '100%';

                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'antigravity-checklist-cb';
                cb.checked = checked;

                const label = document.createElement('span');
                label.className = 'antigravity-checklist-text' + (checked ? ' checked' : '');
                label.textContent = text;
                label.style.flex = '1';
                label.style.marginLeft = '8px';

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'antigravity-checklist-delete';
                deleteBtn.title = 'Task löschen';
                deleteBtn.style.marginLeft = 'auto';
                deleteBtn.style.background = 'transparent';
                deleteBtn.style.border = 'none';
                deleteBtn.style.color = 'var(--muted-foreground, #71717a)';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.style.padding = '2px';
                deleteBtn.style.display = 'none';
                deleteBtn.style.alignItems = 'center';
                deleteBtn.style.justifyContent = 'center';
                deleteBtn.style.outline = 'none';
                deleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

                const toggleItem = () => {
                    cb.checked = !cb.checked;
                    label.classList.toggle('checked', cb.checked);
                    const newChar = cb.checked ? 'x' : ' ';
                    lines[index] = indent + '- [' + newChar + '] ' + text;
                    currentPlanText = lines.join('\n');
                    window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                    if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                        window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                    }

                    const editor = document.getElementById('antigravity-plan-editor');
                    if (editor) {
                        editor.value = currentPlanText;
                    }
                    triggerSaveStatus();

                    // Auto-Git-commit on check
                    if (cb.checked && currentConvId) {
                        triggerAutoGitCommitAndPush(currentConvId, text.trim());
                    }
                };

                cb.addEventListener('change', (e) => {
                    e.stopPropagation();
                    const checkedState = cb.checked;
                    label.classList.toggle('checked', checkedState);
                    const newChar = checkedState ? 'x' : ' ';
                    lines[index] = indent + '- [' + newChar + '] ' + text;
                    currentPlanText = lines.join('\n');
                    window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                    if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                        window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                    }

                    const editor = document.getElementById('antigravity-plan-editor');
                    if (editor) {
                        editor.value = currentPlanText;
                    }
                    triggerSaveStatus();

                    // Auto-Git-commit on check
                    if (checkedState && currentConvId) {
                        triggerAutoGitCommitAndPush(currentConvId, text.trim());
                    }
                });

                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCustomConfirm('Möchtest du diesen Task wirklich löschen?', (confirmed) => {
                        if (confirmed) {
                            lines.splice(index, 1);
                            currentPlanText = lines.join('\n');
                            window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                            if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                                window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                            }

                            const editor = document.getElementById('antigravity-plan-editor');
                            if (editor) {
                                editor.value = currentPlanText;
                            }
                            updateChecklistFromText();
                            triggerSaveStatus();
                        }
                    });
                });

                label.addEventListener('click', toggleItem);

                item.appendChild(cb);
                item.appendChild(label);
                item.appendChild(deleteBtn);
                container.appendChild(item);
            } else {
                if (line.trim().startsWith('#')) {
                    const headerContainer = document.createElement('div');
                    headerContainer.className = 'antigravity-checklist-header-container';
                    headerContainer.style.display = 'flex';
                    headerContainer.style.alignItems = 'center';
                    headerContainer.style.justifyContent = 'space-between';
                    headerContainer.style.marginTop = '16px';
                    headerContainer.style.marginBottom = '6px';

                    const level = line.match(/^#+/)[0].length;
                    headerContainer.style.borderBottom = level === 1 ? '1px solid var(--border, #27272a)' : 'none';
                    headerContainer.style.paddingBottom = level === 1 ? '4px' : '0';

                    const headerText = document.createElement('span');
                    headerText.style.fontWeight = 'bold';
                    headerText.style.fontSize = (18 - level) + 'px';
                    headerText.textContent = line.replace(/^#+\s*/, '');

                    const addBtn = document.createElement('button');
                    addBtn.className = 'antigravity-checklist-add-btn';
                    addBtn.title = 'Task hinzufügen';
                    addBtn.style.background = 'transparent';
                    addBtn.style.border = 'none';
                    addBtn.style.color = 'var(--muted-foreground, #71717a)';
                    addBtn.style.cursor = 'pointer';
                    addBtn.style.display = 'inline-flex';
                    addBtn.style.alignItems = 'center';
                    addBtn.style.padding = '4px';
                    addBtn.style.borderRadius = '4px';
                    addBtn.style.outline = 'none';
                    addBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>';

                    addBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const titleClean = headerText.textContent;
                        showCustomPrompt("Neuen Task unter '" + titleClean + "' hinzufügen:", "", (taskText) => {
                            if (taskText && taskText.trim()) {
                                let insertIdx = index + 1;
                                while (insertIdx < lines.length) {
                                    const nextLine = lines[insertIdx];
                                    if (nextLine.trim().startsWith('#')) {
                                        break;
                                    }
                                    insertIdx++;
                                }

                                lines.splice(insertIdx, 0, '- [ ] ' + taskText.trim());
                                currentPlanText = lines.join('\n');
                                window.nativeStorage.updateItems({ antigravity_task_plan: currentPlanText });
                                if (currentConvId && window.electronNative && window.electronNative.setTaskPlan) {
                                    window.electronNative.setTaskPlan(currentPlanText, currentConvId);
                                }

                                const editor = document.getElementById('antigravity-plan-editor');
                                if (editor) {
                                    editor.value = currentPlanText;
                                }
                                updateChecklistFromText();
                                triggerSaveStatus();
                            }
                        });
                    });

                    headerContainer.appendChild(headerText);
                    headerContainer.appendChild(addBtn);
                    container.appendChild(headerContainer);
                } else if (line.trim()) {
                    const txt = document.createElement('div');
                    txt.style.fontSize = '13px';
                    txt.style.opacity = '0.8';
                    txt.style.marginTop = '4px';
                    txt.textContent = line;
                    container.appendChild(txt);
                }
            }
        });

        if (!hasTasks) {
            const emptyMsg = document.createElement('div');
            emptyMsg.style.fontSize = '12px';
            emptyMsg.style.color = 'var(--muted-foreground, #71717a)';
            emptyMsg.style.textAlign = 'center';
            emptyMsg.style.marginTop = '20px';
            emptyMsg.innerHTML = 'Keine Tasks gefunden.<br>Nutze das "Bearbeiten"-Tab, um einen Plan im Markdown-Checklisten-Format hinzuzufügen.';
            container.appendChild(emptyMsg);
        }
    }

    let autoCommitTimeout = null;
    let pendingSteps = [];

    function triggerAutoGitCommitAndPush(convoId, stepText) {
        if (!window.electronNative || !window.electronNative.commitAndPush) return;

        pendingSteps.push(stepText);

        if (autoCommitTimeout) {
            clearTimeout(autoCommitTimeout);
        }

        autoCommitTimeout = setTimeout(async () => {
            const stepsList = pendingSteps.join(', ');
            pendingSteps = [];
            autoCommitTimeout = null;

            console.log('[AMS Auto-Sync] Triggering auto-commit for completed steps:', stepsList);
            const commitMsg = `docs(tasks): completed steps: ${stepsList}`;
            try {
                const res = await window.electronNative.commitAndPush(commitMsg, convoId);
                if (res && res.status === 'success') {
                    console.log('[AMS Auto-Sync] Auto-commit and push successful.');
                } else {
                    console.warn('[AMS Auto-Sync] Auto-commit failed:', res ? res.message : 'unknown error');
                }
            } catch (err) {
                console.error('[AMS Auto-Sync] Error during auto-commit:', err);
            }
        }, 5000);
    }
