    const loadedPRs = Object.create(null);
    const loadedIssues = Object.create(null);


    async function updateReviewsUI() {
        const container = document.getElementById('antigravity-plan-reviews-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Reviews...</div>';

        try {
            const runsGrouped = await window.electronNative.getReviews();
            if (!runsGrouped || runsGrouped.length === 0) {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine nächtlichen Läufe protokolliert.</div>';
                return;
            }

            let html = '<div style="display: flex; flex-direction: column; gap: 14px; padding-bottom: 10px;">';

            runsGrouped.forEach(group => {
                html += '<div style="display: flex; flex-direction: column; gap: 8px;">';
                html += '  <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-foreground, #71717a); border-bottom: 1px solid var(--border, #27272a); padding-bottom: 4px; margin-top: 8px;">Lauf: ' + escapeHtml(group.date) + '</div>';

                group.runs.forEach(run => {
                    const runStatus = String(run.status || 'Unknown');
                    const safeConversationId = String(run.conversationId || '');
                    const safePrUrl = safeExternalUrl(run.prUrl);
                    let statusColor = '#3b82f6';
                    let statusBg = 'rgba(59, 130, 246, 0.1)';
                    if (runStatus === 'Success') {
                        statusColor = '#22c55e';
                        statusBg = 'rgba(34, 197, 94, 0.1)';
                    } else if (runStatus === 'Loop Detected') {
                        statusColor = '#eab308';
                        statusBg = 'rgba(234, 179, 8, 0.1)';
                    } else if (runStatus.startsWith('Failed') || runStatus === 'Failed to launch') {
                        statusColor = '#ef4444';
                        statusBg = 'rgba(239, 68, 68, 0.1)';
                    }

                    html += '<div style="background-color: var(--card, #1c1c1e); border: 1px solid var(--border, #27272a); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px;">';
                    html += '  <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">';
                    html += '    <div style="font-size: 12px; font-weight: 500; color: var(--foreground, #ffffff); line-height: 1.3;">Issue #' + escapeHtml(run.issueNumber) + ': ' + escapeHtml(run.title) + '</div>';
                    html += '    <span style="font-size: 9px; font-weight: 600; text-transform: uppercase; color: ' + statusColor + '; background-color: ' + statusBg + '; padding: 2px 6px; border-radius: 4px; shrink-0;">' + escapeHtml(runStatus) + '</span>';
                    html += '  </div>';
                    html += '  <div style="font-size: 11px; color: var(--muted-foreground, #71717a); display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">';
                    html += '    <span>Branch: <code style="background-color: rgba(255,255,255,0.05); padding: 1px 4px; border-radius: 3px; font-family: monospace;">' + escapeHtml(run.branch) + '</code></span>';
                    if (run.startTime) {
                        html += '    <span>| Start: ' + escapeHtml(String(run.startTime).split(' ')[1] || run.startTime) + '</span>';
                    }
                    if (run.endTime) {
                        html += '    <span>| Ende: ' + escapeHtml(String(run.endTime).split(' ')[1] || run.endTime) + '</span>';
                    }
                    html += '  </div>';
                    html += '  <div style="display: flex; gap: 8px; margin-top: 4px;">';
                    if (safeConversationId) {
                        html += '    <button class="antigravity-review-log-btn" data-convoid="' + escapeHtml(safeConversationId) + '" style="background: transparent; border: 1px solid var(--border, #27272a); color: var(--foreground, #ffffff); border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; transition: background-color 0.2s; outline: none;">Log ansehen</button>';
                    }
                    if (safePrUrl) {
                        html += '    <a href="' + escapeHtml(safePrUrl) + '" target="_blank" rel="noopener noreferrer" style="text-decoration: none; border: 1px solid var(--border, #27272a); color: var(--foreground, #ffffff); background-color: rgba(255,255,255,0.02); border-radius: 4px; padding: 3px 8px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px; transition: background-color 0.2s;"><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>PR ansehen</a>';
                    }
                    html += '  </div>';
                    html += '</div>';
                });
                html += '</div>';
            });
            html += '</div>';
            container.innerHTML = html;

            container.querySelectorAll('.antigravity-review-log-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const convoId = btn.getAttribute('data-convoid');
                    showReviewLogModal(convoId);
                });
            });

        } catch (e) {
            console.error('[AMS UI Reviews] Failed to render reviews:', e);
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Fehler beim Laden der Reviews.</div>';
        }
    }

    async function showReviewLogModal(convoId) {
        const previouslyFocused = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'antigravity-modal-overlay';
        stopKeyPropagation(overlay);
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
        overlay.style.backdropFilter = 'blur(4px)';
        overlay.style.zIndex = '9999';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';

        const modal = document.createElement('div');
        modal.style.width = '80vw';
        modal.style.maxWidth = '700px';
        modal.style.height = '80vh';
        modal.style.maxHeight = '600px';
        modal.style.backgroundColor = 'var(--background, #0a0a0a)';
        modal.style.border = '1px solid var(--border, #27272a)';
        modal.style.borderRadius = '12px';
        modal.style.display = 'flex';
        modal.style.flexDirection = 'column';
        modal.style.overflow = 'hidden';
        modal.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5)';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');

        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.padding = '12px 16px';
        header.style.borderBottom = '1px solid var(--border, #27272a)';
        header.style.backgroundColor = 'var(--card, #18181b)';

        const title = document.createElement('span');
        title.textContent = 'Ausführungs-Log für ' + String(convoId || '').substring(0, 8) + '...';
        title.style.fontSize = '12px';
        title.style.fontWeight = '600';
        title.style.color = 'var(--foreground, #ffffff)';
        title.style.textTransform = 'uppercase';
        title.style.letterSpacing = '0.05em';
        title.style.fontFamily = 'system-ui, sans-serif';
        title.id = 'antigravity-review-log-title-' + Date.now();
        modal.setAttribute('aria-labelledby', title.id);

        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = 'var(--muted-foreground, #71717a)';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.display = 'flex';
        closeBtn.style.alignItems = 'center';
        closeBtn.style.justifyContent = 'center';
        closeBtn.style.padding = '4px';
        closeBtn.style.borderRadius = '4px';
        closeBtn.setAttribute('aria-label', 'Ausführungs-Log schließen');

        header.appendChild(title);
        header.appendChild(closeBtn);
        modal.appendChild(header);

        const body = document.createElement('div');
        body.style.flex = '1';
        body.style.overflowY = 'auto';
        body.style.padding = '16px';
        body.style.display = 'flex';
        body.style.flexDirection = 'column';
        body.style.gap = '12px';
        body.style.fontSize = '12px';
        body.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 40px;">Lade Log-Details aus SQLite-Datenbank...</div>';
        modal.appendChild(body);

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const controller = createAmsModalController({
            overlay,
            modal,
            initialFocus: closeBtn,
            previouslyFocused,
        });
        closeBtn.addEventListener('click', () => controller.close('close-button'));
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) controller.close('backdrop');
        });
        controller.focusInitial();

        try {
            const logs = await window.electronNative.getRunLog(convoId);
            if (controller.isClosed()) return;
            if (!logs || logs.length === 0) {
                body.innerHTML = '<div style="color: var(--muted-foreground, #71717a); text-align: center; margin-top: 40px;">Keine Einträge in der Datenbank gefunden.</div>';
                return;
            }

            let logHtml = '';
            logs.forEach(log => {
                if (log.role === 'user') {
                    logHtml += '<div style="align-self: flex-end; background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 12px 12px 0 12px; padding: 10px; max-width: 85%; white-space: pre-wrap; line-height: 1.4; text-align: left;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'agent') {
                    logHtml += '<div style="align-self: flex-start; background-color: rgba(255,255,255,0.02); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); border-radius: 12px 12px 12px 0; padding: 10px; max-width: 85%; white-space: pre-wrap; line-height: 1.4; text-align: left;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'tool') {
                    logHtml += '<div style="align-self: center; background-color: rgba(59,130,246,0.05); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); border-radius: 6px; padding: 6px 12px; font-family: monospace; font-size: 11px; max-width: 95%; text-align: left; word-break: break-all;">' + escapeHtml(log.content) + '</div>';
                } else if (log.role === 'system') {
                    logHtml += '<div style="align-self: center; color: var(--muted-foreground, #71717a); font-style: italic;">' + escapeHtml(log.content) + '</div>';
                }
            });
            body.innerHTML = logHtml;
            body.scrollTop = body.scrollHeight;
        } catch (e) {
            console.error('[AMS UI Reviews] Failed to fetch log details:', e);
            body.innerHTML = '<div style="color: #ef4444; text-align: center; margin-top: 40px;">Fehler beim Laden des Logs.</div>';
        }
    }

    function escapeHtml(text) {
        return String(text ?? '')
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function safeExternalUrl(value) {
        try {
            const raw = String(value || '');
            if (!raw || raw.length > 2048) return '';
            const parsed = new URL(raw);
            return parsed.protocol === 'https:' ? parsed.href : '';
        } catch (_) {
            return '';
        }
    }

    async function updatePRsUI() {
        const container = document.getElementById('antigravity-plan-prs-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Pull Requests...</div>';

        try {
            const parts = window.location.pathname.split('/');
            const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

            const res = await window.electronNative.getPRs(conversationId);
            if (res.status === 'success') {
                if (res.prs.length === 0) {
                    container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine Pull Requests gefunden.</div>';
                    return;
                }

                let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                res.prs.forEach(pr => {
                    const prNumber = String(pr.number ?? '');
                    const prUrl = safeExternalUrl(pr.url);
                    loadedPRs[prNumber] = pr;
                    let stateColor = '#22c55e';
                    let stateLabel = 'Open';
                    if (pr.state === 'MERGED') {
                        stateColor = '#a855f7';
                        stateLabel = 'Merged';
                    } else if (pr.state === 'CLOSED') {
                        stateColor = '#ef4444';
                        stateLabel = 'Closed';
                    }

                    html += '<div class="antigravity-pr-card" style="border: 1px solid var(--border, #27272a); border-radius: 8px; background-color: var(--card, #18181b); display: flex; flex-direction: column; overflow: hidden;">' +
                            '  <div class="antigravity-card-header" style="padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; user-select: none;">' +
                            '    <div style="font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--foreground, #ffffff);">' + escapeHtml(pr.title) + '</div>' +
                            '    <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted-foreground, #71717a);">' +
                            '      <div style="display: flex; align-items: center; gap: 6px;">' +
                            '        <span style="background-color: ' + stateColor + '20; color: ' + stateColor + '; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 10px;">' + stateLabel + '</span>' +
                            '        <span>#' + escapeHtml(prNumber) + '</span>' +
                            '        <span>by ' + escapeHtml(pr.author?.login || 'unknown') + '</span>' +
                            '      </div>' +
                            '      <span class="antigravity-toggle-indicator" style="font-size: 10px; opacity: 0.7;">Details anzeigen ▾</span>' +
                            '    </div>' +
                            '  </div>' +
                            '  <div class="antigravity-body-details" style="display: none; border-top: 1px solid var(--border, #27272a); padding: 10px; background-color: rgba(0,0,0,0.15); flex-direction: column; gap: 8px;">' +
                            '    <div style="font-size: 12px; color: var(--muted-foreground, #a1a1aa); white-space: pre-wrap; max-height: 200px; overflow-y: auto; line-height: 1.5; font-family: ui-sans-serif, system-ui, sans-serif; padding-right: 4px;">' + escapeHtml(pr.body || '*Keine Beschreibung vorhanden.*') + '</div>' +
                            '    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">' +
                            '      <button class="antigravity-plan-subtasks" data-type="PR" data-number="' + escapeHtml(prNumber) + '" style="background-color: #2563eb; color: white; border: none; padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4z"></path></svg>' +
                            '        Subtasks planen' +
                            '      </button>' +
                            '      <button class="antigravity-send-to-ai" data-type="PR" data-number="' + escapeHtml(prNumber) + '" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>' +
                            '        An Chat senden' +
                            '      </button>' +
                            '      <button class="antigravity-open-web" data-url="' + escapeHtml(prUrl) + '" style="background-color: transparent; color: var(--muted-foreground, #a1a1aa); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500;">Im Browser öffnen</button>' +
                            '    </div>' +
                            '  </div>' +
                            '</div>';
                });
                html += '</div>';
                container.innerHTML = html;

                container.querySelectorAll('.antigravity-card-header').forEach(header => {
                    header.addEventListener('click', () => {
                        const details = header.parentElement.querySelector('.antigravity-body-details');
                        const indicator = header.querySelector('.antigravity-toggle-indicator');
                        if (details.style.display === 'none') {
                            details.style.display = 'flex';
                            indicator.textContent = 'Details verbergen ▴';
                        } else {
                            details.style.display = 'none';
                            indicator.textContent = 'Details anzeigen ▾';
                        }
                    });
                });

                container.querySelectorAll('.antigravity-plan-subtasks').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = type === 'PR' ? loadedPRs[number] : loadedIssues[number];
                        if (!item) {
                            alert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const newPlan = generateSubtasks(item, type);
                        const editor = document.getElementById('antigravity-plan-editor');
                        if (editor) {
                            editor.value = newPlan;
                            const event = new Event('input', { bubbles: true });
                            editor.dispatchEvent(event);

                            const previewTab = document.querySelector('.antigravity-plan-tab[data-tab="preview"]');
                            if (previewTab) {
                                previewTab.click();
                            }
                        }
                    });
                });

                container.querySelectorAll('.antigravity-send-to-ai').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = loadedPRs[number];
                        if (!item) {
                            alert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const promptText = `Bitte bearbeite folgendes GitHub-${type}:\n\n` +
                                           `**Titel:** ${item.title} (#${item.number})\n` +
                                           `**Link:** ${item.url}\n\n` +
                                           `**Beschreibung:**\n${item.body || 'Keine Beschreibung.'}`;

                        const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                        if (input) {
                            input.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, promptText);
                            const event = new Event('input', { bubbles: true });
                            input.dispatchEvent(event);
                        } else {
                            alert('Chat-Eingabefeld nicht gefunden!');
                        }
                    });
                });

                container.querySelectorAll('.antigravity-open-web').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const url = safeExternalUrl(btn.getAttribute('data-url'));
                        if (url && window.electronNative && window.electronNative.openExternal) {
                            window.electronNative.openExternal(url);
                        }
                    });
                });
            } else if (res.status === 'no_remote') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px; line-height: 1.5;">' +
                                      '  Kein GitHub-Remote-Repository konfiguriert.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7;">Füge ein Remote-Repository hinzu (z.B. git remote add origin &lt;url&gt;), um Pull Requests anzuzeigen.</span>' +
                                      '</div>';
            } else if (res.status === 'no_git') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Kein Git-Repository in diesem Workspace gefunden.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7; word-break: break-all;">Pfad: ' + escapeHtml(res.repoPath) + '</span>' +
                                      '</div>';
            } else {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Fehler beim Laden: ' + escapeHtml(res.message || 'Unbekannter Fehler') +
                                      '</div>';
            }
        } catch (err) {
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: #ef4444;">Ausnahmefehler: ' + escapeHtml(err.message) + '</div>';
        }
    }

    async function updateIssuesUI() {
        const container = document.getElementById('antigravity-plan-issues-container');
        if (!container) return;

        container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Lade Issues...</div>';

        try {
            const parts = window.location.pathname.split('/');
            const conversationId = (parts.length > 2 && parts[2]) ? parts[2] : null;

            const res = await window.electronNative.getIssues(conversationId);
            if (res.status === 'success') {
                if (res.issues.length === 0) {
                    container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a);">Keine offenen Issues gefunden.</div>';
                    return;
                }

                let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                res.issues.forEach(issue => {
                    const issueNumber = String(issue.number ?? '');
                    const issueUrl = safeExternalUrl(issue.url);
                    loadedIssues[issueNumber] = issue;
                    let stateColor = '#22c55e';
                    let stateLabel = 'Open';
                    if (issue.state && issue.state.toLowerCase() === 'closed') {
                        stateColor = '#ef4444';
                        stateLabel = 'Closed';
                    }

                    html += '<div class="antigravity-issue-card" style="border: 1px solid var(--border, #27272a); border-radius: 8px; background-color: var(--card, #18181b); display: flex; flex-direction: column; overflow: hidden;">' +
                            '  <div class="antigravity-card-header" style="padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; user-select: none;">' +
                            '    <div style="font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--foreground, #ffffff);">' + escapeHtml(issue.title) + '</div>' +
                            '    <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted-foreground, #71717a);">' +
                            '      <div style="display: flex; align-items: center; gap: 6px;">' +
                            '        <span style="background-color: ' + stateColor + '20; color: ' + stateColor + '; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 10px;">' + stateLabel + '</span>' +
                            '        <span>#' + escapeHtml(issueNumber) + '</span>' +
                            '        <span>by ' + escapeHtml(issue.author?.login || 'unknown') + '</span>' +
                            '      </div>' +
                            '      <span class="antigravity-toggle-indicator" style="font-size: 10px; opacity: 0.7;">Details anzeigen ▾</span>' +
                            '    </div>' +
                            '  </div>' +
                            '  <div class="antigravity-body-details" style="display: none; border-top: 1px solid var(--border, #27272a); padding: 10px; background-color: rgba(0,0,0,0.15); flex-direction: column; gap: 8px;">' +
                            '    <div style="font-size: 12px; color: var(--muted-foreground, #a1a1aa); white-space: pre-wrap; max-height: 200px; overflow-y: auto; line-height: 1.5; font-family: ui-sans-serif, system-ui, sans-serif; padding-right: 4px;">' + escapeHtml(issue.body || '*Keine Beschreibung vorhanden.*') + '</div>' +
                            '    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">' +
                            '      <button class="antigravity-plan-subtasks" data-type="Issue" data-number="' + escapeHtml(issueNumber) + '" style="background-color: #2563eb; color: white; border: none; padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4z"></path></svg>' +
                            '        Subtasks planen' +
                            '      </button>' +
                            '      <button class="antigravity-send-to-ai" data-type="Issue" data-number="' + escapeHtml(issueNumber) + '" style="background-color: var(--secondary, #27272a); color: var(--foreground, #ffffff); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 4px;">' +
                            '        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>' +
                            '        An Chat senden' +
                            '      </button>' +
                            '      <button class="antigravity-open-web" data-url="' + escapeHtml(issueUrl) + '" style="background-color: transparent; color: var(--muted-foreground, #a1a1aa); border: 1px solid var(--border, #27272a); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: 500;">Im Browser öffnen</button>' +
                            '    </div>' +
                            '  </div>' +
                            '</div>';
                });
                html += '</div>';
                container.innerHTML = html;

                container.querySelectorAll('.antigravity-card-header').forEach(header => {
                    header.addEventListener('click', () => {
                        const details = header.parentElement.querySelector('.antigravity-body-details');
                        const indicator = header.querySelector('.antigravity-toggle-indicator');
                        if (details.style.display === 'none') {
                            details.style.display = 'flex';
                            indicator.textContent = 'Details verbergen ▴';
                        } else {
                            details.style.display = 'none';
                            indicator.textContent = 'Details anzeigen ▾';
                        }
                    });
                });

                container.querySelectorAll('.antigravity-plan-subtasks').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = type === 'PR' ? loadedPRs[number] : loadedIssues[number];
                        if (!item) {
                            alert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const newPlan = generateSubtasks(item, type);
                        const editor = document.getElementById('antigravity-plan-editor');
                        if (editor) {
                            editor.value = newPlan;
                            const event = new Event('input', { bubbles: true });
                            editor.dispatchEvent(event);

                            const previewTab = document.querySelector('.antigravity-plan-tab[data-tab="preview"]');
                            if (previewTab) {
                                previewTab.click();
                            }
                        }
                    });
                });

                container.querySelectorAll('.antigravity-send-to-ai').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const type = btn.getAttribute('data-type');
                        const number = btn.getAttribute('data-number');
                        const item = loadedIssues[number];
                        if (!item) {
                            alert('Daten im Speicher nicht gefunden!');
                            return;
                        }

                        const promptText = `Bitte bearbeite folgendes GitHub-${type}:\n\n` +
                                           `**Titel:** ${item.title} (#${item.number})\n` +
                                           `**Link:** ${item.url}\n\n` +
                                           `**Beschreibung:**\n${item.body || 'Keine Beschreibung.'}`;

                        const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
                        if (input) {
                            input.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, promptText);
                            const event = new Event('input', { bubbles: true });
                            input.dispatchEvent(event);
                        } else {
                            alert('Chat-Eingabefeld nicht gefunden!');
                        }
                    });
                });

                container.querySelectorAll('.antigravity-open-web').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const url = safeExternalUrl(btn.getAttribute('data-url'));
                        if (url && window.electronNative && window.electronNative.openExternal) {
                            window.electronNative.openExternal(url);
                        }
                    });
                });
            } else if (res.status === 'no_remote') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px; line-height: 1.5;">' +
                                      '  Kein GitHub-Remote-Repository konfiguriert.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7;">Füge ein Remote-Repository hinzu, um Issues anzuzeigen.</span>' +
                                      '</div>';
            } else if (res.status === 'no_git') {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Kein Git-Repository in diesem Workspace gefunden.<br>' +
                                      '  <span style="font-size: 11px; opacity: 0.7; word-break: break-all;">Pfad: ' + escapeHtml(res.repoPath) + '</span>' +
                                      '</div>';
            } else {
                container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                      '  Fehler beim Laden: ' + escapeHtml(res.message || 'Unbekannter Fehler') +
                                      '</div>';
            }
        } catch (e) {
            container.innerHTML = '<div style="font-size: 12px; text-align: center; margin-top: 20px; color: var(--muted-foreground, #71717a); padding: 10px;">' +
                                  '  Exception beim Laden: ' + escapeHtml(e.message) +
                                  '</div>';
        }
    }


    async function renderAppLogViewer() {
        const logsTab = document.getElementById('antigravity-settings-logs-tab');
        if (!logsTab) return;
        const sidebar = logsTab.parentElement;
        if (!sidebar) return;

        const sidebarContainer = sidebar.closest('.bg-sidebar');
        if (!sidebarContainer) return;

        const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
        if (!layoutContainer) return;

        const rightPanel = layoutContainer.children[1];
        if (!rightPanel) return;

        let container = document.getElementById('antigravity-log-viewer-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'antigravity-log-viewer-container';
            container.className = 'antigravity-log-viewer-main flex-grow flex flex-col gap-4 min-w-0 bg-transparent p-6';
            container.style.height = '100%';
            container.style.width = '100%';
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.boxSizing = 'border-box';
            container.style.flexGrow = '1';
            container.style.minHeight = '0';
            rightPanel.appendChild(container);
        }

        // Hide all other elements in rightPanel to avoid vertical split/squeezing
        for (let i = 0; i < rightPanel.children.length; i++) {
            const child = rightPanel.children[i];
            if (child !== container) {
                child.style.display = 'none';
            }
        }
        container.style.display = 'flex';

        // Only reconstruct UI if needed
        if (!container.querySelector('#log-rows-container')) {
            container.innerHTML =
                '<div class="flex items-center justify-between border-b pb-3 border-border" style="border-bottom: 1px solid var(--border);">' +
                    '<h2 class="text-xl font-semibold text-foreground">Log Viewer</h2>' +
                    '<div class="flex gap-2" style="margin-right: 28px; align-items: center;">' +
                        '<button id="ams-consolidate-btn" class="text-xs bg-primary text-primary-foreground px-2.5 py-1 rounded-md" style="background: var(--primary, #3b82f6); color: var(--primary-foreground, #ffffff); border: none; cursor: pointer; display: flex; align-items: center; gap: 4px; font-weight: 500; font-family: inherit; font-size: 11px; height: 24px; transition: opacity 0.2s;" title="Langzeitgedächtnis aus dem Chatverlauf aktualisieren">🧠 Lernen</button>' +
                        '<span class="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground" style="background: var(--muted); color: var(--muted-foreground); height: 24px; display: flex; align-items: center;" title="IPC token is isolated in the preload context">IPC geschützt</span>' +
                        '<span class="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground" id="log-stats-count" style="background: var(--muted); color: var(--muted-foreground); height: 24px; display: flex; align-items: center;">Loading...</span>' +
                    '</div>' +
                '</div>' +
                '<div class="flex gap-2 items-center">' +
                    '<input type="text" id="log-search" placeholder="Search logs..." class="flex-1 px-3 py-1.5 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none" style="background: var(--background); color: var(--foreground); border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px;" />' +
                    '<select id="log-source" class="px-2 py-1.5 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none" style="background: var(--background); color: var(--foreground); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 13px;">' +
                        '<option value="">All Sources</option>' +
                        '<option value="USER">User</option>' +
                        '<option value="AGENT">Agent</option>' +
                        '<option value="SYSTEM">System</option>' +
                    '</select>' +
                '</div>' +
                '<div id="log-rows-container" class="flex-grow overflow-y-auto pr-1 flex flex-col gap-2" style="overflow-y: auto; scrollbar-width: thin; display: flex; flex-direction: column; gap: 8px; flex-grow: 1; min-height: 0;">' +
                    '<div class="text-sm text-muted-foreground p-8 text-center" style="color: var(--muted-foreground);">Loading log history...</div>' +
                '</div>';

            container.querySelector('#log-search').addEventListener('input', () => renderRows());
            container.querySelector('#log-source').addEventListener('change', () => renderRows());

            const consolidateBtn = container.querySelector('#ams-consolidate-btn');
            if (consolidateBtn) {
                consolidateBtn.addEventListener('click', () => triggerConsolidation());
            }
        }

        const rowsContainer = container.querySelector('#log-rows-container');
        const statsEl = container.querySelector('#log-stats-count');

        let res;
        try {
            res = await window.electronNative.getHistory();
        } catch (ipcErr) {
            rowsContainer.innerHTML = '<div class="text-sm text-red-500 p-8 text-center">Failed to invoke logs IPC handler: ' + escapeHtml(ipcErr.message) + '</div>';
            statsEl.textContent = 'Error';
            return;
        }

        if (res.status !== 'success') {
            rowsContainer.innerHTML = '<div class="text-sm text-red-500 p-8 text-center">Failed to load log history: ' + escapeHtml(res.message || 'File not found') + '</div>';
            statsEl.textContent = 'Error';
            return;
        }

        const logsData = res.logs || [];
        logsData.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        let totalTokens = 0;
        logsData.forEach(log => {
            if (typeof log.tokens === 'number') {
                totalTokens += log.tokens;
            } else {
                totalTokens += estimateTokenCount(log.content);
            }
        });

        statsEl.textContent = logsData.length + ' entries | ' + formatTokenCount(totalTokens) + ' tokens';

        function formatLogMessage(text) {
            if (!text) return '';
            text = String(text);

            let userRequest = '';
            let metadata = '';
            let isStructuredUser = false;

            if (text.includes('<USER_REQUEST>') && text.includes('</USER_REQUEST>')) {
                isStructuredUser = true;
                const reqStart = text.indexOf('<USER_REQUEST>') + 14;
                const reqEnd = text.indexOf('</USER_REQUEST>');
                userRequest = text.substring(reqStart, reqEnd).trim();

                if (text.includes('<ADDITIONAL_METADATA>') && text.includes('</ADDITIONAL_METADATA>')) {
                    const metaStart = text.indexOf('<ADDITIONAL_METADATA>') + 21;
                    const metaEnd = text.indexOf('</ADDITIONAL_METADATA>');
                    metadata = text.substring(metaStart, metaEnd).trim();
                }
            }

            let displayText = isStructuredUser ? userRequest : text;

            let escaped = displayText
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");

            let html = escaped;

            if (isStructuredUser && metadata) {
                let escapedMeta = metadata
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");

                html += '<details style="margin-top: 8px; font-size: 11px; color: var(--muted-foreground, #8c8c8c); cursor: pointer;" onclick="event.stopPropagation()">' +
                        '<summary style="user-select: none;">Show Metadata</summary>' +
                        '<pre style="margin-top: 4px; padding: 6px; background: rgba(0,0,0,0.15); border-radius: 4px; overflow-x: auto; white-space: pre-wrap; font-family: monospace;">' + escapedMeta + '</pre>' +
                        '</details>';
            }

            return html;
        }

        function renderRows() {
            const searchQuery = container.querySelector('#log-search').value.toLowerCase();
            const sourceFilter = container.querySelector('#log-source').value;

            const filtered = logsData.filter(log => {
                const content = String(log.content || '');
                const matchesSearch = content.toLowerCase().includes(searchQuery);
                const matchesSource = !sourceFilter || log.source === sourceFilter;
                return matchesSearch && matchesSource;
            });

            rowsContainer.innerHTML = '';
            if (filtered.length === 0) {
                rowsContainer.innerHTML = '<div class="text-sm text-muted-foreground p-8 text-center" style="color: var(--muted-foreground);">No logs found.</div>';
                return;
            }

            filtered.slice(0, 150).forEach(log => {
                const source = String(log.source || 'SYSTEM');
                const sessionId = String(log.session_id || 'unknown');
                const eventName = String(log.event || 'unknown');
                const content = String(log.content || '');
                const row = document.createElement('div');
                row.style.background = 'var(--muted, rgba(255,255,255,0.03))';
                row.style.border = '1px solid var(--border, rgba(255,255,255,0.08))';
                row.style.borderRadius = '8px';
                row.style.padding = '8px 12px';
                row.style.display = 'flex';
                row.style.flexDirection = 'column';
                row.style.gap = '4px';
                row.style.cursor = 'pointer';
                row.style.transition = 'background 0.2s';

                row.addEventListener('mouseover', () => {
                    row.style.background = 'var(--sidebar-muted, rgba(255,255,255,0.06))';
                });
                row.addEventListener('mouseout', () => {
                    row.style.background = 'var(--muted, rgba(255,255,255,0.03))';
                });

                const timeStr = new Date(log.timestamp).toLocaleString('de-DE');

                const details = document.createElement('div');
                details.style.display = 'none';
                details.style.fontSize = '11px';
                details.style.color = 'var(--text-secondary, #9ca3af)';
                details.style.marginTop = '6px';
                details.style.borderTop = '1px solid var(--border, rgba(255,255,255,0.08))';
                details.style.paddingTop = '6px';
                details.style.fontFamily = 'monospace';
                details.innerHTML =
                    '<div><strong>Session:</strong> ' + escapeHtml(sessionId) + '</div>' +
                    '<div><strong>Event:</strong> ' + escapeHtml(eventName) + '</div>' +
                    (log.metadata ? '<div><strong>Metadata:</strong> ' + escapeHtml(JSON.stringify(log.metadata)) + '</div>' : '');

                row.addEventListener('click', (e) => {
                    const isExpanded = details.style.display === 'block';
                    details.style.display = isExpanded ? 'none' : 'block';
                });

                const badgeColor = source === 'USER' ? '#3b82f6' : (source === 'AGENT' ? '#8b5cf6' : '#9ca3af');

                const tokensVal = typeof log.tokens === 'number' ? log.tokens : estimateTokenCount(log.content);
                const isEstimated = typeof log.tokens !== 'number';
                const tokenStr = (isEstimated ? '~' : '') + formatTokenCount(tokensVal) + ' tokens';
                const modelStr = String(log.model || 'Gemini 3.5 Flash (High)');

                row.innerHTML =
                    '<div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px;">' +
                        '<div style="display: flex; align-items: center; gap: 6px;">' +
                            '<span style="background: ' + badgeColor + '; color: white; padding: 1px 4px; border-radius: 4px; font-weight: bold; font-size: 9px;">' + escapeHtml(source) + '</span>' +
                            '<span style="opacity: 0.6;">' + escapeHtml(timeStr) + '</span>' +
                        '</div>' +
                        '<div style="display: flex; align-items: center; gap: 8px;">' +
                            '<span style="opacity: 0.5; background: var(--muted, rgba(255,255,255,0.05)); border: 1px solid var(--border, rgba(255,255,255,0.1)); padding: 1px 6px; border-radius: 4px; font-size: 10px;" title="Model and token count">' + escapeHtml(modelStr) + ' • ' + escapeHtml(tokenStr) + '</span>' +
                            '<span style="opacity: 0.4; font-family: monospace;">' + escapeHtml(sessionId.substring(0, 8)) + '...</span>' +
                        '</div>' +
                    '</div>' +
                    '<div style="font-size: 13px; color: var(--foreground, #f3f4f6); word-break: break-word; white-space: pre-wrap; margin-top: 4px;">' + formatLogMessage(content) + '</div>';

                row.appendChild(details);
                rowsContainer.appendChild(row);
            });
        }

        renderRows();

        async function triggerConsolidation() {
            const btn = document.getElementById('ams-consolidate-btn');
            if (!btn) return;

            if (!currentConvId) {
                showToast('Keine aktive Konversation geladen.', 'error');
                return;
            }

            const oldText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '🧠 Analysiere...';
            btn.style.opacity = '0.7';

            try {
                const csrfToken = window.__APP_CONFIG__ ? window.__APP_CONFIG__.csrfToken : '';
                const res = await window.electronNative.consolidateMemory(currentConvId, csrfToken);

                if (res && res.found) {
                    showConsolidationModal(res.type, res.proposed_text, res.convoId);
                } else {
                    showToast('Keine neuen Erkenntnisse im aktuellen Verlauf gefunden.', 'info');
                }
            } catch (e) {
                console.error('[AMS UI] Consolidation failed:', e);
                showToast('Fehler bei der Analyse: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = oldText;
                btn.style.opacity = '1';
            }
        }

        function showToast(message, type) {
            const toast = document.createElement('div');
            toast.style.position = 'fixed';
            toast.style.bottom = '20px';
            toast.style.right = '20px';
            toast.style.padding = '12px 18px';
            toast.style.borderRadius = '8px';
            toast.style.fontSize = '13px';
            toast.style.zIndex = '99999';
            toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
            toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            toast.style.transform = 'translateY(20px)';
            toast.style.opacity = '0';

            if (type === 'error') {
                toast.style.background = '#ef4444';
                toast.style.color = '#ffffff';
            } else if (type === 'success') {
                toast.style.background = '#10b981';
                toast.style.color = '#ffffff';
            } else {
                toast.style.background = 'var(--popover, #1e1e24)';
                toast.style.color = 'var(--popover-foreground, #ffffff)';
                toast.style.border = '1px solid var(--border, #3f3f46)';
            }

            toast.textContent = message;
            document.body.appendChild(toast);

            setTimeout(() => {
                toast.style.transform = 'translateY(0)';
                toast.style.opacity = '1';
            }, 50);

            setTimeout(() => {
                toast.style.transform = 'translateY(20px)';
                toast.style.opacity = '0';
                setTimeout(() => {
                    toast.remove();
                }, 300);
            }, 4000);
        }

        function showConsolidationModal(type, proposedText, tempConvoId) {
            const previouslyFocused = document.activeElement;
            const overlay = document.createElement('div');
            overlay.className = 'antigravity-modal-overlay';
            stopKeyPropagation(overlay);
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.background = 'rgba(9, 9, 11, 0.7)';
            overlay.style.backdropFilter = 'blur(4px)';
            overlay.style.display = 'flex';
            overlay.style.alignItems = 'center';
            overlay.style.justifyContent = 'center';
            overlay.style.zIndex = '99998';
            overlay.style.opacity = '0';
            overlay.style.transition = 'opacity 0.2s ease';

            const modal = document.createElement('div');
            modal.style.background = 'var(--popover, #1e1e24)';
            modal.style.border = '1px solid var(--border, #3f3f46)';
            modal.style.borderRadius = '12px';
            modal.style.padding = '24px';
            modal.style.width = '450px';
            modal.style.maxWidth = '90vw';
            modal.style.boxShadow = '0 20px 25px -5px rgba(0,0,0,0.5)';
            modal.style.display = 'flex';
            modal.style.flexDirection = 'column';
            modal.style.gap = '16px';
            modal.style.transform = 'scale(0.95)';
            modal.style.transition = 'transform 0.2s ease';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');

            const optionSelect = type === 'preference'
                ? '<option value="lesson_learned">Gelernte Technik (MEMORY.pc.md)</option><option value="preference" selected>Benutzerpräferenz (USER.pc.md)</option>'
                : '<option value="lesson_learned" selected>Gelernte Technik (MEMORY.pc.md)</option><option value="preference">Benutzerpräferenz (USER.pc.md)</option>';

            modal.innerHTML =
                '<div style="display: flex; align-items: center; gap: 8px;">' +
                    '<span style="font-size: 24px;">🧠</span>' +
                    '<h3 style="font-size: 18px; font-weight: 600; color: var(--foreground, #ffffff); margin: 0;">Neues Wissen sichern</h3>' +
                '</div>' +
                '<p style="font-size: 13px; color: var(--muted-foreground, #a1a1aa); margin: 0; line-height: 1.4;">' +
                    'Die KI hat eine neue Erkenntnis oder Präferenz in diesem Chat erkannt. Du kannst sie vor dem Speichern bearbeiten:' +
                '</p>' +
                '<div style="display: flex; flex-direction: column; gap: 6px;">' +
                    '<label style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--muted-foreground, #71717a);">Gedächtnistyp</label>' +
                    '<select id="ams-memory-type" style="background: var(--background, #09090b); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 8px; font-size: 13px; outline: none;">' +
                        optionSelect +
                    '</select>' +
                '</div>' +
                '<div style="display: flex; flex-direction: column; gap: 6px;">' +
                    '<label style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--muted-foreground, #71717a);">Erkenntnis / Bulletpoint</label>' +
                    '<textarea id="ams-memory-text" style="background: var(--background, #09090b); color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 10px; font-size: 13px; font-family: inherit; resize: vertical; min-height: 80px; outline: none; line-height: 1.4;"></textarea>' +
                '</div>' +
                '<div style="display: flex; justify-content: end; gap: 12px; margin-top: 8px;">' +
                    '<button id="ams-cancel-modal" style="background: transparent; color: var(--foreground, #ffffff); border: 1px solid var(--border, #3f3f46); border-radius: 6px; padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 500;">Verwerfen</button>' +
                    '<button id="ams-save-modal" style="background: var(--primary, #3b82f6); color: var(--primary-foreground, #ffffff); border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 500; display: flex; align-items: center; gap: 6px;">Speichern & Kompilieren</button>' +
                '</div>';

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            const textarea = modal.querySelector('#ams-memory-text');
            textarea.value = proposedText;
            const modalTitle = modal.querySelector('h3');
            modalTitle.id = 'ams-memory-modal-title-' + Date.now();
            modal.setAttribute('aria-labelledby', modalTitle.id);

            setTimeout(() => {
                overlay.style.opacity = '1';
                modal.style.transform = 'scale(1)';
            }, 50);

            let isSaving = false;
            let tempCleanupStarted = false;
            const cleanupTempConversation = () => {
                if (!tempConvoId || tempCleanupStarted) return Promise.resolve();
                tempCleanupStarted = true;
                return deleteTempConversation(tempConvoId);
            };
            const controller = createAmsModalController({
                overlay,
                modal,
                initialFocus: textarea,
                previouslyFocused,
                removeDelay: 200,
                animateClose: () => {
                    overlay.style.opacity = '0';
                    modal.style.transform = 'scale(0.95)';
                },
                onClose: (reason) => {
                    if (reason !== 'saved') {
                        cleanupTempConversation().catch((error) => {
                            console.warn('[AMS UI] Failed to clean up discarded memory conversation:', error);
                        });
                    }
                },
            });
            const closeModal = (reason = 'discard') => controller.close(reason);
            controller.focusInitial();
            textarea.select();

            modal.querySelector('#ams-cancel-modal').addEventListener('click', () => {
                closeModal('discard');
            });

            modal.querySelector('#ams-save-modal').addEventListener('click', async () => {
                if (isSaving || controller.isClosed()) return;
                const saveBtn = modal.querySelector('#ams-save-modal');
                const selectedType = modal.querySelector('#ams-memory-type').value;
                const textToSave = textarea.value.trim();

                if (!textToSave) {
                    alert('Bitte trage eine Erkenntnis ein.');
                    return;
                }

                isSaving = true;
                saveBtn.disabled = true;
                saveBtn.innerHTML = '💾 Speichere...';
                saveBtn.style.opacity = '0.7';

                try {
                    const res = await window.electronNative.applyMemorySuggestion(selectedType, textToSave);
                    if (res && res.status === 'success') {
                        showToast('Gedächtnis erfolgreich aktualisiert und kompiliert!', 'success');
                        closeModal('saved');
                    } else if (res && res.status === 'warning') {
                        showToast('Erkenntnis gespeichert, Kompilierung fehlgeschlagen: ' + res.message, 'error');
                        closeModal('saved');
                    } else {
                        alert('Fehler beim Speichern: ' + (res ? res.message : 'Unbekannter Fehler'));
                        saveBtn.disabled = false;
                        saveBtn.innerHTML = 'Speichern & Kompilieren';
                        saveBtn.style.opacity = '1';
                    }

                    if (res && (res.status === 'success' || res.status === 'warning')) {
                        await cleanupTempConversation();
                    }
                } catch (saveErr) {
                    console.error('[AMS UI] Failed to save memory suggestion:', saveErr);
                    alert('Speicherfehler: ' + saveErr.message);
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = 'Speichern & Kompilieren';
                    saveBtn.style.opacity = '1';
                } finally {
                    isSaving = false;
                }
            });
        }
    }

    // ----------------------------------------------------

    // React changes are observed and coalesced instead of scanning the full DOM twice per second.
    let lastSyncStatusCheck = 0;
    let injectionScanInFlight = false;
    const runInjectionScan = async () => {
        if (document.hidden || injectionScanInFlight) return;
        injectionScanInFlight = true;
        try {
        // Modal-Off-Check: Reset active tab state if modal is closed
        const isModalOpen = !!document.querySelector('.animate-modalScaleIn') || !!document.querySelector('[role="dialog"]');
        if (!isModalOpen) {
            window.__antigravity_active_tab = '';
        }

        const logsTab = document.getElementById('antigravity-settings-logs-tab');
        if (logsTab) {
            if (window.__antigravity_active_tab === 'logs') {
                if (!logsTab.classList.contains('bg-sidebar-secondary')) {
                    logsTab.classList.add('bg-sidebar-secondary');
                    logsTab.classList.remove('hover:bg-sidebar-muted');
                }
                const sidebar = logsTab.parentElement;
                if (sidebar) {
                    sidebar.querySelectorAll('button, [role="tab"]').forEach(btn => {
                        if (btn !== logsTab && btn.classList.contains('bg-sidebar-secondary')) {
                            btn.classList.remove('bg-sidebar-secondary');
                            btn.classList.add('hover:bg-sidebar-muted');
                        }
                    });
                }
            } else {
                if (logsTab.classList.contains('bg-sidebar-secondary')) {
                    logsTab.classList.remove('bg-sidebar-secondary');
                    logsTab.classList.add('hover:bg-sidebar-muted');
                }
            }
        }

        if (window.__antigravity_active_tab === 'logs') {
            const logsTab = document.getElementById('antigravity-settings-logs-tab');
            if (logsTab) {
                const sidebar = logsTab.parentElement;
                if (sidebar) {
                    const sidebarContainer = sidebar.closest('.bg-sidebar');
                    if (sidebarContainer) {
                        const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                                (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
                        const rightPanel = layoutContainer ? layoutContainer.children[1] : null;
                        if (rightPanel) {
                            const container = document.getElementById('antigravity-log-viewer-container');
                            const isRendered = container && container.style.display === 'flex' && container.querySelector('#log-rows-container');

                            // Check if React re-rendered other elements and made them visible
                            let othersVisible = false;
                            for (let i = 0; i < rightPanel.children.length; i++) {
                                const child = rightPanel.children[i];
                                if (child !== container && child.style.display !== 'none') {
                                    othersVisible = true;
                                    break;
                                }
                            }

                            if (!isRendered || othersVisible) {
                                renderAppLogViewer();
                            }
                        }
                    }
                }
            }
        }
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        let btn = document.querySelector('.antigravity-brain-btn');
        let quotaEl = document.querySelector('.antigravity-quota-display');
        let planToggleBtn = document.querySelector('.antigravity-plan-btn');
        let duplicateBtn = document.querySelector('.antigravity-duplicate-btn');
        let chatTokenEl = document.querySelector('#antigravity-chat-token-counter');

        if (addContextBtn && !btn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'antigravity-brain-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                btn.title = 'Brain-Ordner öffnen';
                btn.style.marginLeft = '6px';
                btn.style.padding = '0';
                btn.style.background = 'transparent';
                btn.style.border = 'none';
                btn.style.outline = 'none';
                btn.style.display = 'inline-flex';

                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                '<path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2Z"/>' +
                                '<path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2Z"/>' +
                                '</svg>';

                btn.addEventListener('click', () => {
                    try {
                        if (window.electronNative && window.electronNative.openBrain) {
                            window.electronNative.openBrain();
                        }
                    } catch (err) {
                        console.error('[AMS UI] Call to openBrain failed:', err);
                    }
                });

                flexContainer.appendChild(btn);
                console.log('[AMS UI] Brain shortcut button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !planToggleBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                planToggleBtn = document.createElement('button');
                planToggleBtn.type = 'button';
                planToggleBtn.className = 'antigravity-plan-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                planToggleBtn.title = 'Task- & Plan-Tracker öffnen';
                planToggleBtn.style.marginLeft = '4px';
                planToggleBtn.style.padding = '0';
                planToggleBtn.style.background = 'transparent';
                planToggleBtn.style.border = 'none';
                planToggleBtn.style.outline = 'none';
                planToggleBtn.style.display = 'inline-flex';

                planToggleBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                          '<path d="M12 20h9"/>' +
                                          '<path d="M3 20h.01"/>' +
                                          '<path d="M3 14h.01"/>' +
                                          '<path d="M3 8h.01"/>' +
                                          '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>' +
                                          '<path d="m9 11 2 2 4-4"/>' +
                                          '</svg>';

                planToggleBtn.addEventListener('click', () => {
                    togglePlanPanel();
                });

                if (btn) {
                    btn.after(planToggleBtn);
                } else {
                    flexContainer.appendChild(planToggleBtn);
                }
                console.log('[AMS UI] Plan shortcut button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !duplicateBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                duplicateBtn = document.createElement('button');
                duplicateBtn.type = 'button';
                duplicateBtn.className = 'antigravity-duplicate-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                duplicateBtn.title = 'Fenster duplizieren';
                duplicateBtn.style.marginLeft = '4px';
                duplicateBtn.style.padding = '0';
                duplicateBtn.style.background = 'transparent';
                duplicateBtn.style.border = 'none';
                duplicateBtn.style.outline = 'none';
                duplicateBtn.style.display = 'inline-flex';

                duplicateBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                                         '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>' +
                                         '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
                                         '</svg>';

                duplicateBtn.addEventListener('click', () => {
                    try {
                        if (window.electronNative && window.electronNative.openDuplicateWindow) {
                            window.electronNative.openDuplicateWindow(amsToken);
                        } else {
                            window.open(window.location.href, '_blank');
                        }
                    } catch (err) {
                        console.error('[AMS UI] Call to openDuplicateWindow failed:', err);
                    }
                });

                if (planToggleBtn) {
                    planToggleBtn.after(duplicateBtn);
                } else if (btn) {
                    btn.after(duplicateBtn);
                } else {
                    flexContainer.appendChild(duplicateBtn);
                }
                console.log('[AMS UI] Duplicate shortcut button successfully appended to flex container.');
            }
        }

        let quickMenuBtn = document.querySelector('.antigravity-quickmenu-btn');
        if (addContextBtn && !quickMenuBtn) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                quickMenuBtn = document.createElement('button');
                quickMenuBtn.type = 'button';
                quickMenuBtn.className = 'antigravity-quickmenu-btn flex items-center justify-center h-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                quickMenuBtn.title = 'Antigravity Unleashed · Quick Menu (Ctrl+Shift+B)';
                quickMenuBtn.style.marginLeft = '4px';
                quickMenuBtn.style.padding = '0 7px';
                quickMenuBtn.style.gap = '5px';
                quickMenuBtn.style.background = 'rgba(139, 92, 246, 0.08)';
                quickMenuBtn.style.border = '1px solid rgba(139, 92, 246, 0.24)';
                quickMenuBtn.style.outline = 'none';
                quickMenuBtn.style.display = 'inline-flex';
                quickMenuBtn.style.alignItems = 'center';

                quickMenuBtn.innerHTML =
                    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
                    '<ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.7" stroke-opacity="0.85"/>' +
                    '<polygon points="12,3.2 19.2,12 12,20.8 4.8,12" fill="rgba(139,92,246,0.22)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
                    '<circle cx="12" cy="12" r="2.1" fill="#f8fafc"/>' +
                    '</svg>' +
                    '<span style="font-size:10px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Unleashed</span>';

                quickMenuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (window.toggleQuickMenu) {
                        window.toggleQuickMenu();
                    }
                });

                if (duplicateBtn) {
                    duplicateBtn.after(quickMenuBtn);
                } else if (planToggleBtn) {
                    planToggleBtn.after(quickMenuBtn);
                } else if (btn) {
                    btn.after(quickMenuBtn);
                } else {
                    flexContainer.appendChild(quickMenuBtn);
                }
                console.log('[AMS UI] Quick menu button successfully appended to flex container.');
            }
        }

        if (addContextBtn && !quotaEl) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                quotaEl = document.createElement('div');
                quotaEl.className = 'antigravity-quota-display';
                quotaEl.style.display = 'inline-flex';
                quotaEl.style.alignItems = 'center';
                quotaEl.style.gap = '6px';
                quotaEl.style.fontSize = '10px';
                quotaEl.style.color = 'var(--muted-foreground, #9d9d9d)';
                quotaEl.style.marginLeft = '8px';
                quotaEl.style.marginRight = '4px';
                quotaEl.style.fontFamily = 'monospace';
                quotaEl.style.userSelect = 'none';
                quotaEl.style.cursor = 'pointer';

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
                            if (attempts > 20) {
                                clearInterval(interval);
                            }
                        }, 50);
                    }
                });

                flexContainer.appendChild(quotaEl);
                refreshQuotaDisplay();
                console.log('[AMS UI] Quota display successfully appended to flex container.');
            }
        }

        if (addContextBtn && !chatTokenEl) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                chatTokenEl = document.createElement('span');
                chatTokenEl.id = 'antigravity-chat-token-counter';
                chatTokenEl.style.display = 'none';
                chatTokenEl.style.alignItems = 'center';
                chatTokenEl.style.fontSize = '10px';
                chatTokenEl.style.color = 'var(--muted-foreground, #9d9d9d)';
                chatTokenEl.style.marginLeft = '8px';
                chatTokenEl.style.marginRight = '4px';
                chatTokenEl.style.fontFamily = 'monospace';
                chatTokenEl.style.userSelect = 'none';
                chatTokenEl.style.cursor = 'help';

                if (quotaEl) {
                    quotaEl.after(chatTokenEl);
                } else {
                    flexContainer.appendChild(chatTokenEl);
                }
                console.log('[AMS UI] Chat token counter successfully appended to flex container.');
            }
        }

        const settingsBtn = document.querySelector('[data-testid="settings-button"]');
        let customSidebarBtn = document.querySelector('.antigravity-custom-sidebar-btn');
        if (settingsBtn && !customSidebarBtn) {
            customSidebarBtn = document.createElement('div');
            customSidebarBtn.role = 'button';
            customSidebarBtn.tabIndex = 0;
            customSidebarBtn.className = 'antigravity-custom-sidebar-btn flex-grow flex items-center gap-1.5 group px-2 py-1 rounded-lg cursor-pointer h-8 min-w-0 bg-transparent hover:bg-sidebar-muted text-secondary-foreground';
            customSidebarBtn.style.outline = 'none';
            customSidebarBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"></path><path d="M12 6v6l4 2"></path></svg>' +
                                         '<span class="select-none truncate text-sm font-normal">History</span>';

            customSidebarBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    const settingsBtn = document.querySelector('[data-testid="settings-button"]');
                    if (settingsBtn) {
                        settingsBtn.click();
                        let attempts = 0;
                        const interval = setInterval(() => {
                            let logViewerTab = null;
                            document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                                if (btn.textContent && btn.textContent.trim().toLowerCase() === 'log viewer') {
                                    logViewerTab = btn;
                                }
                            });
                            if (logViewerTab) {
                                logViewerTab.click();
                                clearInterval(interval);
                            }
                            attempts++;
                            if (attempts > 20) {
                                clearInterval(interval);
                            }
                        }, 50);
                    }
                } catch (err) {
                    console.error('[AMS UI] Custom sidebar button click failed:', err);
                }
            });

            settingsBtn.before(customSidebarBtn);
            console.log('[AMS UI] Custom sidebar button successfully injected above settings.');
        }

        if (btn) {
            const now = Date.now();
            if (now - lastSyncStatusCheck >= 30_000) {
                lastSyncStatusCheck = now;
                try {
                    if (window.electronNative && window.electronNative.getSyncStatus) {
                        const statusInfo = await window.electronNative.getSyncStatus();

                        if (!document.getElementById('antigravity-brain-styles')) {
                            const style = document.createElement('style');
                            style.id = 'antigravity-brain-styles';
                            style.innerHTML = '@keyframes brain-pulse {' +
                                              '  0%, 100% { opacity: 1; transform: scale(1); }' +
                                              '  50% { opacity: .65; transform: scale(1.05); }' +
                                              '}' +
                                              '.antigravity-brain-conflict {' +
                                              '  color: #f97316 !important;' +
                                              '  animation: brain-pulse 2s infinite ease-in-out;' +
                                              '}';
                            document.head.appendChild(style);
                        }

                        if (statusInfo && statusInfo.status === 'conflict') {
                            btn.classList.add('antigravity-brain-conflict');
                            const cleanNames = statusInfo.conflictFiles.map(f => {
                                if (f.startsWith('- [CONFLICT]')) {
                                    return f.replace('- [CONFLICT] Conflict in ', '').split(' at ')[0];
                                }
                                return f;
                            });
                            const filesStr = cleanNames.slice(0, 3).join(', ') + (cleanNames.length > 3 ? '...' : '');
                            btn.title = 'Achtung: Git-Konflikte/Backups im Brain-Ordner erkannt! (' + filesStr + '). Klicke hier zum Öffnen.';
                        } else {
                            btn.classList.remove('antigravity-brain-conflict');
                            btn.title = 'Brain-Ordner öffnen';
                        }
                    }
                } catch (err) {
                    console.error('[AMS UI] Failed to fetch sync status:', err);
                }
            }
        }

        // ----------------------------------------------------
        // Log Viewer Tab Injection inside Settings modal
        // ----------------------------------------------------
        try {
            let modelsTab = null;
            document.querySelectorAll('button, [role="tab"], [role="button"]').forEach(btn => {
                if (btn.textContent) {
                    const txt = btn.textContent.trim().toLowerCase();
                    if (txt === 'models' || txt === 'modelle') {
                        modelsTab = btn;
                    }
                }
            });

            if (modelsTab) {
                const sidebar = modelsTab.parentElement;
                if (sidebar && !document.getElementById('antigravity-settings-logs-tab')) {
                    const logsTab = document.createElement('button');
                    logsTab.type = 'button';
                    logsTab.id = 'antigravity-settings-logs-tab';
                    logsTab.className = modelsTab.className;
                    logsTab.innerHTML = modelsTab.innerHTML;

                    const textSpan = logsTab.querySelector('span');
                    if (textSpan) {
                        textSpan.textContent = 'Log Viewer';
                    }

                    const svg = logsTab.querySelector('svg');
                    if (svg) {
                        svg.innerHTML = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9">';
                    }

                    logsTab.addEventListener('click', async (e) => {
                        e.preventDefault();
                        e.stopPropagation();

                        sidebar.querySelectorAll('button, [role="tab"]').forEach(btn => {
                            btn.classList.remove('bg-sidebar-secondary');
                            btn.classList.add('hover:bg-sidebar-muted');
                        });
                        logsTab.classList.add('bg-sidebar-secondary');
                        logsTab.classList.remove('hover:bg-sidebar-muted');

                        window.__antigravity_active_tab = 'logs';
                        renderAppLogViewer();
                    });

                    sidebar.appendChild(logsTab);

                    // Robust event delegation on the sidebar container to catch all clicks to other tabs
                    const sidebarContainer = sidebar.closest('.bg-sidebar');
                    if (sidebarContainer && !sidebarContainer.hasAttribute('antigravity-listener-added')) {
                        sidebarContainer.setAttribute('antigravity-listener-added', 'true');
                        sidebarContainer.addEventListener('click', (e) => {
                            const btn = e.target.closest('button, [role="tab"]');
                            if (btn && btn !== logsTab) {
                                logsTab.classList.remove('bg-sidebar-muted', 'text-sidebar-accent-foreground');
                                logsTab.style.background = '';
                                window.__antigravity_active_tab = '';

                                const container = document.getElementById('antigravity-log-viewer-container');
                                if (container) {
                                    container.style.display = 'none';
                                }

                                const dialog = document.querySelector('.animate-modalScaleIn') || document.querySelector('[role="dialog"]');
                                if (dialog) {
                                    const layoutContainer = sidebarContainer.closest('.flex.w-full.h-full.outline-none') ||
                                                            (sidebarContainer.parentElement ? sidebarContainer.parentElement.parentElement : null);
                                    const rightPanel = layoutContainer ? layoutContainer.children[1] : null;
                                    if (rightPanel) {
                                        for (let i = 0; i < rightPanel.children.length; i++) {
                                            const child = rightPanel.children[i];
                                            if (child !== container) {
                                                child.style.display = '';
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }
                }
            }
        } catch (settingsErr) {
            console.error('[AMS UI] Error injecting Log Viewer tab:', settingsErr);
        }
        } finally {
            injectionScanInFlight = false;
        }
    };

    let injectionScanTimer = null;
    const scheduleInjectionScan = () => {
        if (document.hidden) return;
        if (injectionScanTimer !== null) clearTimeout(injectionScanTimer);
        injectionScanTimer = setTimeout(() => {
            injectionScanTimer = null;
            runInjectionScan().catch((error) => console.error('[AMS UI] DOM injection scan failed:', error));
        }, 120);
    };
    const injectionObserver = new MutationObserver((records) => {
        if (records.some((record) => record.addedNodes.length > 0 || record.removedNodes.length > 0)) {
            scheduleInjectionScan();
        }
    });
    injectionObserver.observe(document.documentElement || document, { childList: true, subtree: true });
    const injectionFallbackInterval = setInterval(scheduleInjectionScan, 10_000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) scheduleInjectionScan();
    });
    scheduleInjectionScan();

    // Real-time Chat Monitor

    window.toggleQuickMenu = function() {
        const existing = document.getElementById('antigravity-quick-menu-overlay');
        if (existing) {
            existing.style.opacity = '0';
            existing.style.transform = 'translateY(10px) scale(0.95)';
            setTimeout(() => existing.remove(), 200);
            return;
        }

        // Create overlay
        const overlay = document.createElement('div');
        overlay.id = 'antigravity-quick-menu-overlay';

        overlay.style.position = 'fixed';
        overlay.style.bottom = '80px';
        overlay.style.right = '20px';
        overlay.style.width = '320px';
        overlay.style.background = 'rgba(20, 20, 23, 0.85)';
        overlay.style.backdropFilter = 'blur(16px)';
        overlay.style.border = '1px solid rgba(255, 255, 255, 0.08)';
        overlay.style.borderRadius = '12px';
        overlay.style.boxShadow = '0 20px 40px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05)';
        overlay.style.zIndex = '999999';
        overlay.style.padding = '16px';
        overlay.style.color = '#fafafa';
        overlay.style.fontFamily = 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        overlay.style.display = 'flex';
        overlay.style.flexDirection = 'column';
        overlay.style.gap = '12px';
        overlay.style.opacity = '0';
        overlay.style.transform = 'translateY(10px) scale(0.95)';
        overlay.style.transition = 'opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1), transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)';

        // Header
        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.alignItems = 'center';
        header.style.justifyContent = 'space-between';
        header.style.borderBottom = '1px solid rgba(255, 255, 255, 0.08)';
        header.style.paddingBottom = '8px';

        const title = document.createElement('span');
        title.style.display = 'inline-flex';
        title.style.alignItems = 'center';
        title.style.gap = '7px';
        title.style.fontSize = '13px';
        title.style.fontWeight = '600';
        title.style.letterSpacing = '0.3px';
        title.style.color = '#f8fafc';
        title.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">' +
            '<ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)" stroke="#38bdf8" stroke-width="1.8" stroke-opacity="0.9"/>' +
            '<polygon points="12,3 19.4,12 12,21 4.6,12" fill="rgba(139,92,246,0.28)" stroke="#a78bfa" stroke-width="1.8" stroke-linejoin="round"/>' +
            '<circle cx="12" cy="12" r="2.2" fill="#f8fafc"/>' +
            '</svg>' +
            '<strong>Antigravity Unleashed</strong>' +
            '<span style="font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;background:rgba(139,92,246,0.18);border:1px solid rgba(139,92,246,0.35);color:#c4b5fd;letter-spacing:0.06em;">MOD</span>';

        const closeBtn = document.createElement('button');
        closeBtn.textContent = '✕';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = 'rgba(255, 255, 255, 0.4)';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.fontSize = '12px';
        closeBtn.style.padding = '4px';
        closeBtn.addEventListener('click', () => window.toggleQuickMenu());

        header.appendChild(title);
        header.appendChild(closeBtn);
        overlay.appendChild(header);

        // Status section
        const statusSection = document.createElement('div');
        statusSection.style.fontSize = '11px';
        statusSection.style.display = 'flex';
        statusSection.style.flexDirection = 'column';
        statusSection.style.gap = '6px';
        statusSection.style.background = 'rgba(255, 255, 255, 0.03)';
        statusSection.style.padding = '10px';
        statusSection.style.borderRadius = '8px';
        statusSection.style.border = '1px solid rgba(255, 255, 255, 0.03)';

        const activeModel = getActiveModel ? getActiveModel() : 'Gemini 3.5 Flash';
        const modelRow = document.createElement('div');
        modelRow.style.display = 'flex';
        modelRow.style.justifyContent = 'space-between';
        modelRow.innerHTML = '<span style="color: rgba(255,255,255,0.5)">Model:</span>';
        const modelValue = document.createElement('span');
        modelValue.style.fontWeight = '500';
        modelValue.textContent = String(activeModel || 'Unknown');
        modelRow.appendChild(modelValue);
        statusSection.appendChild(modelRow);

        const syncRow = document.createElement('div');
        syncRow.style.display = 'flex';
        syncRow.style.justifyContent = 'space-between';
        syncRow.innerHTML = `<span style="color: rgba(255,255,255,0.5)">Sync Status:</span><span id="ams-sync-indicator" style="font-weight: 500">Checking...</span>`;
        statusSection.appendChild(syncRow);

        const hubRow = document.createElement('div');
        hubRow.style.display = 'flex';
        hubRow.style.justifyContent = 'space-between';
        hubRow.innerHTML = `<span style="color: rgba(255,255,255,0.5)">Anti-Gravity Hub:</span><span id="ams-antigravity-hub-indicator" style="font-weight:500;color:#fbbf24">● Checking…</span>`;
        statusSection.appendChild(hubRow);

        const bridgeRow = document.createElement('div');
        bridgeRow.style.display = 'flex';
        bridgeRow.style.justifyContent = 'space-between';
        bridgeRow.innerHTML = `<span style="color: rgba(255,255,255,0.5)">Anti-Gravity API Bridge:</span><span id="ams-antigravity-bridge-indicator" style="font-weight:500;color:#fbbf24">● Checking…</span>`;
        statusSection.appendChild(bridgeRow);

        overlay.appendChild(statusSection);

        // Actions Section
        const actionsSection = document.createElement('div');
        actionsSection.style.display = 'flex';
        actionsSection.style.flexDirection = 'column';
        actionsSection.style.gap = '6px';

        const createMenuItem = (label, iconSvg, onClick) => {
            const item = document.createElement('button');
            item.style.display = 'flex';
            item.style.alignItems = 'center';
            item.style.gap = '10px';
            item.style.width = '100%';
            item.style.padding = '8px 12px';
            item.style.background = 'transparent';
            item.style.border = 'none';
            item.style.borderRadius = '6px';
            item.style.color = 'rgba(255, 255, 255, 0.8)';
            item.style.fontSize = '12px';
            item.style.textAlign = 'left';
            item.style.cursor = 'pointer';
            item.style.transition = 'background 0.2s, color 0.2s';

            item.innerHTML = iconSvg;
            const labelSpan = document.createElement('span');
            labelSpan.textContent = String(label || '');
            item.appendChild(labelSpan);

            item.addEventListener('mouseenter', () => {
                item.style.background = 'rgba(255, 255, 255, 0.08)';
                item.style.color = '#ffffff';
            });
            item.addEventListener('mouseleave', () => {
                item.style.background = 'transparent';
                item.style.color = 'rgba(255, 255, 255, 0.8)';
            });
            item.addEventListener('click', () => {
                window.toggleQuickMenu();
                onClick();
            });
            return item;
        };

        const brainSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2Z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2Z"/></svg>`;
        actionsSection.appendChild(createMenuItem('Brain-Ordner öffnen', brainSvg, () => {
            if (window.electronNative && window.electronNative.openBrain) {
                window.electronNative.openBrain();
            }
        }));

        const webSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/></svg>`;
        actionsSection.appendChild(createMenuItem('Anti-Gravity Hub öffnen', webSvg, () => {
            if (window.amsAntigravityHub && window.amsAntigravityHub.openHub) {
                window.amsAntigravityHub.openHub();
            }
        }));

        const startSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        const restartSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38"/></svg>`;
        const servicesItem = createMenuItem('Hub & API Bridge starten', startSvg, async () => {
            const restart = servicesItem.dataset.restart === 'true';
            try {
                if (window.amsAntigravityHub && window.amsAntigravityHub.startServices) {
                    await window.amsAntigravityHub.startServices(restart);
                }
            } catch (err) {
                console.error(`[AMS Services] ${restart ? 'Restart' : 'Start'} failed:`, err);
            }
        });
        servicesItem.id = 'ams-services-menu-item';
        servicesItem.dataset.restart = 'false';
        actionsSection.appendChild(servicesItem);

        const planSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M3 20h.01"/><path d="M3 14h.01"/><path d="M3 8h.01"/><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="m9 11 2 2 4-4"/></svg>`;
        actionsSection.appendChild(createMenuItem('Task-Plan öffnen', planSvg, () => {
            if (typeof togglePlanPanel === 'function') {
                togglePlanPanel();
            }
        }));

        const duplicateSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
        actionsSection.appendChild(createMenuItem('Fenster duplizieren', duplicateSvg, () => {
            if (window.electronNative && window.electronNative.openDuplicateWindow) {
                window.electronNative.openDuplicateWindow(amsToken);
            } else {
                window.open(window.location.href, '_blank');
            }
        }));

        const syncSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`;
        actionsSection.appendChild(createMenuItem('Manuelles Git Sync & Cloud-Backup', syncSvg, () => {
            const convoId = getSessionId ? getSessionId() : '';
            if (typeof showGitSyncModal === 'function') {
                showGitSyncModal(convoId, async (commitMsg) => {
                    if (window.electronNative && window.electronNative.commitAndPush) {
                        await window.electronNative.commitAndPush(commitMsg || 'wip: sync tasks', convoId);
                    }
                });
            }
        }));

        const autoSyncSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>`;
        let currentAutoSyncMinutes = Number(window.__ams_config_auto_sync_minutes || 0);
        const autoSyncItem = createMenuItem(
            currentAutoSyncMinutes > 0
                ? `Auto-Sync (Config): Alle ${currentAutoSyncMinutes} Min. ✓`
                : 'Auto-Sync (Config): Aus (klicken für 15 Min.)',
            autoSyncSvg,
            async () => {
                const nextMinutes = currentAutoSyncMinutes > 0 ? 0 : 15;
                if (window.electronNative && window.electronNative.setConfigAutoSync) {
                    try {
                        await window.electronNative.setConfigAutoSync(nextMinutes);
                        if (typeof window.applyConfigAutoSyncTimer === 'function') {
                            window.applyConfigAutoSyncTimer(nextMinutes);
                        }
                    } catch (err) {
                        console.error('[AMS Auto-Sync] Failed to toggle auto-sync:', err);
                    }
                }
            },
        );
        actionsSection.appendChild(autoSyncItem);
        if (window.electronNative && window.electronNative.getConfigSyncInfo) {
            window.electronNative.getConfigSyncInfo().then((info) => {
                if (!info || info.status === 'error') return;
                currentAutoSyncMinutes = Number(info.auto_sync_minutes || 0);
                if (typeof window.applyConfigAutoSyncTimer === 'function') {
                    window.applyConfigAutoSyncTimer(currentAutoSyncMinutes);
                }
                const label = autoSyncItem.querySelector('span');
                if (label) {
                    label.textContent = currentAutoSyncMinutes > 0
                        ? `Auto-Sync (Config): Alle ${currentAutoSyncMinutes} Min. ✓`
                        : 'Auto-Sync (Config): Aus (klicken für 15 Min.)';
                    label.style.color = currentAutoSyncMinutes > 0 ? '#4ade80' : '';
                }
            }).catch(() => {});
        }

        const historySvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/></svg>`;
        actionsSection.appendChild(createMenuItem('Update- & Patch-Log', historySvg, () => {
            if (typeof showUpdateHistoryModal === 'function') {
                showUpdateHistoryModal();
            } else if (typeof window.showUpdateHistoryModal === 'function') {
                window.showUpdateHistoryModal();
            }
        }));

        const apiWindowSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8"/></svg>`;
        let apiWindowVisible = false;
        const apiWindowItem = createMenuItem('API-Fenster: wird geladen ...', apiWindowSvg, () => {
            const bridge = window.electronNative;
            if (bridge && bridge.setApiWindowVisible) {
                bridge.setApiWindowVisible(!apiWindowVisible);
            }
        });
        actionsSection.appendChild(apiWindowItem);
        if (window.electronNative && window.electronNative.getApiWindowVisible) {
            window.electronNative.getApiWindowVisible().then((result) => {
                apiWindowVisible = !!(result && result.visible);
                const label = apiWindowItem.querySelector('span');
                if (label) {
                    label.textContent = apiWindowVisible
                        ? 'API-Fenster: sichtbar (klicken zum Verstecken)'
                        : 'API-Fenster: versteckt (klicken zum Anzeigen)';
                }
            }).catch(() => {});
        }
        overlay.appendChild(actionsSection);

        // Signature Footer ("Markenzeichen")
        const signatureFooter = document.createElement('div');
        signatureFooter.style.display = 'flex';
        signatureFooter.style.alignItems = 'center';
        signatureFooter.style.justifyContent = 'space-between';
        signatureFooter.style.borderTop = '1px solid rgba(255, 255, 255, 0.07)';
        signatureFooter.style.paddingTop = '8px';
        signatureFooter.style.marginTop = '2px';
        signatureFooter.style.fontSize = '10px';
        signatureFooter.style.color = 'rgba(255, 255, 255, 0.45)';

        const brandTag = document.createElement('span');
        brandTag.textContent = 'Antigravity Unleashed · v2.24';
        signatureFooter.appendChild(brandTag);

        const repoLink = document.createElement('button');
        repoLink.type = 'button';
        repoLink.textContent = 'GitHub @EinMelih ↗';
        repoLink.style.background = 'transparent';
        repoLink.style.border = 'none';
        repoLink.style.padding = '0';
        repoLink.style.color = '#38bdf8';
        repoLink.style.fontSize = '10px';
        repoLink.style.fontWeight = '500';
        repoLink.style.cursor = 'pointer';
        repoLink.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.electronNative && typeof window.electronNative.openExternal === 'function') {
                window.electronNative.openExternal('https://github.com/EinMelih/antigravity-unleashed');
            }
        });
        signatureFooter.appendChild(repoLink);
        overlay.appendChild(signatureFooter);

        document.body.appendChild(overlay);

        if (window.amsAntigravityHub && window.amsAntigravityHub.getStatus) {
            window.amsAntigravityHub.getStatus().then((status) => {
                const renderService = (elementId, service) => {
                    const indicator = document.getElementById(elementId);
                    if (!indicator) return;
                    indicator.style.color = service && service.online ? '#4ade80' : '#f87171';
                    indicator.textContent = service && service.online
                        ? `● Online · ${service.latency_ms} ms`
                        : '● Offline';
                    indicator.title = service && service.error ? service.error : '';
                };
                renderService('ams-antigravity-hub-indicator', status.hub);
                renderService('ams-antigravity-bridge-indicator', status.bridge);

                const svcItem = document.getElementById('ams-services-menu-item');
                if (svcItem) {
                    const isOnline = (status.hub && status.hub.online) || (status.bridge && status.bridge.online);
                    svcItem.dataset.restart = isOnline ? 'true' : 'false';
                    const labelSpan = svcItem.querySelector('span');
                    const iconSlot = svcItem.querySelector('svg');
                    if (labelSpan) {
                        labelSpan.textContent = isOnline ? 'Hub & API Bridge neustarten' : 'Hub & API Bridge starten';
                    }
                    if (iconSlot && isOnline) {
                        iconSlot.outerHTML = restartSvg;
                    }
                }
            }).catch((error) => {
                for (const id of ['ams-antigravity-hub-indicator', 'ams-antigravity-bridge-indicator']) {
                    const indicator = document.getElementById(id);
                    if (indicator) {
                        indicator.style.color = '#f87171';
                        indicator.textContent = '● Offline';
                        indicator.title = error.message;
                    }
                }
            });
        }

        // Open animation
        requestAnimationFrame(() => {
            overlay.style.opacity = '1';
            overlay.style.transform = 'translateY(0) scale(1)';
        });

        // Query Git Sync status
        if (window.electronNative && window.electronNative.getSyncStatus) {
            window.electronNative.getSyncStatus()
                .then(statusInfo => {
                    const ind = document.getElementById('ams-sync-indicator');
                    if (ind) {
                        if (statusInfo.status === 'ok') {
                            ind.textContent = 'Sync OK';
                            ind.style.color = '#10b981';
                        } else if (statusInfo.status === 'conflict') {
                            ind.textContent = 'Konflikt ⚠️';
                            ind.style.color = '#f59e0b';
                            ind.title = 'Konfliktdateien: ' + statusInfo.conflictFiles.join(', ');
                        } else {
                            ind.textContent = 'Fehler';
                            ind.style.color = '#ef4444';
                        }
                    }
                })
                .catch(() => {
                    const ind = document.getElementById('ams-sync-indicator');
                    if (ind) ind.textContent = 'Fehler';
                });
        }
    };

    function getAttachedContextItems() {
        const items = [];
        const chips = document.querySelectorAll('[aria-label^="Remove "], .context-chip, [data-testid*="chip"]');
        chips.forEach(chip => {
            const label = chip.getAttribute('aria-label') || '';
            let filename = label.replace(/^Remove\s+/i, '').trim();
            if (!filename) {
                filename = chip.textContent.trim();
            }
            if (filename && !items.includes(filename)) {
                items.push(filename);
            }
        });
        return items;
    }

    window.syncSessionConfig = async function() {
        try {
            const model = getActiveModel ? getActiveModel() : '';
            const contextItems = getAttachedContextItems();
            const config = {
                model: model,
                contextItems: contextItems,
                updatedAt: Date.now()
            };

            if (window.nativeStorage && window.nativeStorage.updateItems) {
                await window.nativeStorage.updateItems({ antigravity_session_config: config });
            }

            if (window.electronNative && window.electronNative.writeStatus) {
                await window.electronNative.writeStatus(amsToken, model);
            }
        } catch (err) {
            // silent fail
        }
    };

    window.checkModelSwitchRequest = async function() {
        if (!window.electronNative || !window.electronNative.readSwitchRequest) return;
        try {
            const request = await window.electronNative.readSwitchRequest(amsToken);
            if (request && request.model) {
                console.log('[AMS Model Switch] Switched requested to:', request.model);
                const modelBtn = document.querySelector('button[aria-label^="Select model, current:"]');
                if (modelBtn) {
                    modelBtn.click();
                    setTimeout(() => {
                        const options = document.querySelectorAll('[role="option"], [role="menuitem"], button');
                        for (const opt of options) {
                            if (opt.textContent && opt.textContent.trim().toLowerCase().includes(request.model.toLowerCase())) {
                                opt.click();
                                break;
                            }
                        }
                    }, 150);
                }
            }
        } catch (err) {
            // silent fail
        }
    };

    // Periodische Überwachung der Modell- und Kontext-Änderungen sowie Switch-Anfragen
    setInterval(() => {
        if (window.syncSessionConfig) window.syncSessionConfig();
        if (window.checkModelSwitchRequest) window.checkModelSwitchRequest();
    }, 4000);

    // Hintergrund-Auto-Sync für ~/.gemini/config (inkl. usage_stats.json)
    window.applyConfigAutoSyncTimer = function(minutes) {
        const mins = Math.max(0, Number(minutes || 0));
        window.__ams_config_auto_sync_minutes = mins;
        if (window.__ams_config_auto_sync_interval) {
            clearInterval(window.__ams_config_auto_sync_interval);
            window.__ams_config_auto_sync_interval = null;
        }
        if (mins > 0) {
            window.__ams_config_auto_sync_interval = setInterval(() => {
                if (window.electronNative && window.electronNative.syncConfigOnly) {
                    window.electronNative.syncConfigOnly('chore(config): background auto-sync').catch(() => {});
                }
            }, mins * 60 * 1000);
        }
    };

    if (window.electronNative && window.electronNative.getConfigSyncInfo) {
        setTimeout(() => {
            window.electronNative.getConfigSyncInfo().then((info) => {
                if (info && info.auto_sync_minutes > 0 && typeof window.applyConfigAutoSyncTimer === 'function') {
                    window.applyConfigAutoSyncTimer(info.auto_sync_minutes);
                }
            }).catch(() => {});
        }, 4500);
    }
