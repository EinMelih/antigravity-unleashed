    // Read-only API health and request details in the normal desktop profile (opt-in only; off by default).
    (async () => {
        try {
            if (
                window.__ANTIGRAVITY_ENABLE_API_MONITOR !== true &&
                window.localStorage?.getItem?.('antigravity_enable_desktop_api_monitor') !== '1'
            ) {
                return;
            }
        } catch (_) {
            return;
        }
        let profile = null;
        try { profile = await window.electronNative?.getProfileInfo?.(); } catch (_) { /* Health still reports the verified server-side profile. */ }
        if (profile?.profile === 'api') return;
        const state = { data: null, error: null, pending: false, open: false, checkedAt: null };
        const style = document.createElement('style');
        style.id = 'antigravity-api-monitor-style';
        style.textContent = `
            #antigravity-api-status {position:fixed;right:18px;bottom:18px;z-index:11000;display:flex;align-items:center;gap:7px;padding:7px 11px;border-radius:9px;border:1px solid #ffffff24;background:#20232c;color:#f1f3f8;font:12px system-ui;box-shadow:0 3px 14px #0003;cursor:pointer}
            #antigravity-api-status .api-dot {width:7px;height:7px;border-radius:50%;background:#9aa4b4}
            #antigravity-api-status[data-state=ready] .api-dot {background:#65d4a8}
            #antigravity-api-status[data-state=waiting] .api-dot {background:#edbf66}
            #antigravity-api-status[data-state=error] .api-dot {background:#f18484}
            #antigravity-api-panel {position:fixed;right:18px;bottom:60px;width:min(520px,calc(100vw - 36px));max-height:min(660px,calc(100vh - 110px));overflow:auto;z-index:11001;background:#191c24;color:#edf0f7;border:1px solid #ffffff26;border-radius:14px;box-shadow:0 16px 60px #0007;padding:18px;font:12px/1.5 system-ui}
            #antigravity-api-panel[hidden] {display:none}
            #antigravity-api-panel .api-header {display:flex;align-items:center;justify-content:space-between;gap:12px}
            #antigravity-api-panel h2 {font-size:16px;margin:0}
            #antigravity-api-panel button {color:inherit;background:#ffffff0c;border:1px solid #ffffff22;border-radius:7px;padding:5px 9px;cursor:pointer}
            #antigravity-api-panel .api-summary {margin:12px 0;padding:10px 12px;background:#ffffff06;border-radius:9px;overflow-wrap:anywhere}
            #antigravity-api-panel .api-muted {color:#a6afbf}
            #antigravity-api-panel .api-request {padding:11px 0;border-top:1px solid #ffffff13}
            #antigravity-api-panel .api-request-top {display:flex;align-items:center;justify-content:space-between;gap:10px}
            #antigravity-api-panel .api-state {font-size:11px;border-radius:5px;padding:2px 6px;background:#ffffff10}
            #antigravity-api-panel .api-state[data-state=success] {color:#80dfb8;background:#65d4a812}
            #antigravity-api-panel .api-state[data-state=error] {color:#ffabab;background:#f1848412}
            #antigravity-api-panel .api-preview {white-space:pre-wrap;overflow-wrap:anywhere;color:#c9d1e1;margin-top:6px}
            #antigravity-api-panel .api-error {color:#ffabab;overflow-wrap:anywhere;margin-top:7px}
            @media(prefers-color-scheme:light) {#antigravity-api-panel,#antigravity-api-status {background:#fbfcff;color:#222936;border-color:#d8dce5} #antigravity-api-panel .api-muted {color:#657084} #antigravity-api-panel .api-preview {color:#47536a}}
        `;
        (document.head || document.documentElement).appendChild(style);
        const button = document.createElement('button');
        button.id = 'antigravity-api-status';
        button.type = 'button';
        button.setAttribute('aria-label', 'API-Status und letzte Requests anzeigen');
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', 'antigravity-api-panel');
        const dot = document.createElement('span');
        dot.className = 'api-dot';
        dot.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        button.append(dot, label);
        const panel = document.createElement('section');
        panel.id = 'antigravity-api-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-labelledby', 'antigravity-api-panel-title');
        const mount = () => {
            if (!document.body) return false;
            document.body.append(button, panel);
            return true;
        };
        if (!mount()) document.addEventListener('DOMContentLoaded', mount, { once: true });

        const node = (tag, text, className) => {
            const element = document.createElement(tag);
            if (text !== undefined) element.textContent = String(text);
            if (className) element.className = className;
            return element;
        };
        const homeIsolated = () => state.data?.isolated && state.data?.health?.cdp?.home_isolated;
        const statusLabel = () => state.error ? 'API offline' : !state.data ? 'API wird geprüft' : state.data.health?.ready && homeIsolated() ? 'API bereit' : 'API wartet';
        const formatTime = value => {
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        };
        function render() {
            label.textContent = statusLabel();
            button.dataset.state = state.error ? 'error' : state.data?.health?.ready && homeIsolated() ? 'ready' : 'waiting';
            button.title = 'Eigenes API-Profil · Health und Request-Details';
            if (!state.open) return;
            panel.replaceChildren();
            const header = node('div', undefined, 'api-header');
            const title = node('h2', 'API-Status');
            title.id = 'antigravity-api-panel-title';
            const close = node('button', '×');
            close.setAttribute('aria-label', 'API-Details schließen');
            close.onclick = () => toggle(false);
            header.append(title, close);
            panel.append(header);
            const summary = node('div', undefined, 'api-summary');
            summary.append(node('strong', statusLabel()));
            summary.append(node('div', homeIsolated() ? 'Profil api · Home, Regeln, Memory und Chats getrennt' : 'Profil api · Trennung wird geprüft', 'api-muted'));
            if (homeIsolated() && state.data?.profile_paths?.home_dir) summary.append(node('div', 'API-Home: ' + state.data.profile_paths.home_dir, 'api-muted'));
            if (state.data) summary.append(node('div', `${state.data.total_requests} Requests seit API-Start · ${state.data.active_requests} aktiv · ${state.data.failed_requests} Fehler`, 'api-muted'));
            panel.append(summary);
            const error = state.error || state.data?.last_error;
            if (error) panel.append(node('div', error, 'api-error'));
            if (state.error && state.checkedAt) panel.append(node('div', 'Letzter bekannter Stand: ' + formatTime(state.checkedAt), 'api-muted'));
            panel.append(node('div', 'Letzte API-Requests', 'api-muted'));
            if (!state.data) panel.append(node('p', state.pending ? 'Status wird geladen …' : 'Keine aktuellen API-Daten verfügbar.', 'api-muted'));
            else if (!state.data.requests.length) panel.append(node('p', 'Seit diesem API-Start wurden noch keine Chat-Requests ausgeführt.', 'api-muted'));
            for (const row of (state.data?.requests || []).slice(0, 8)) {
                const item = node('div', undefined, 'api-request');
                const top = node('div', undefined, 'api-request-top');
                const badge = node('span', ({ success: 'Erfolgreich', error: 'Fehler', queued: 'Wartet', running: 'Läuft' })[row.state] || row.state, 'api-state');
                badge.dataset.state = row.state;
                top.append(node('strong', row.native_model || row.requested_model || 'Native Modellauswahl'), badge);
                item.append(top, node('div', `${row.request_id} · ${row.path} · ${formatTime(row.started_at)}`, 'api-muted'));
                const details = [row.reasoning_effort ? `Reasoning: ${row.reasoning_effort}` : null, Number.isFinite(row.duration_ms) ? `${(row.duration_ms / 1000).toFixed(1)} s` : null, row.http_status ? `HTTP ${row.http_status}` : null].filter(Boolean).join(' · ');
                if (details) item.append(node('div', details, 'api-muted'));
                if (row.prompt_preview) item.append(node('div', row.prompt_preview, 'api-preview'));
                if (row.response_preview) item.append(node('div', 'Antwort: ' + row.response_preview, 'api-preview'));
                if (row.error) item.append(node('div', row.error, 'api-error'));
                panel.append(item);
            }
            panel.append(node('p', 'Anzeige ist lesend. Requests laufen im separaten API-Fenster.', 'api-muted'));
        }
        async function refresh() {
            if (state.pending) return;
            state.pending = true;
            render();
            try {
                const result = await window.amsAntigravityHub.getApiStatus();
                if (!result?.ok) throw new Error(result?.error?.message || 'API-Monitor ist nicht erreichbar.');
                if (!result.data?.health || !Array.isArray(result.data.requests)) throw new Error('API-Monitor liefert ungültige Statusdaten.');
                state.data = result.data;
                state.checkedAt = result.checked_at;
                state.error = null;
            } catch (error) {
                state.error = error.message || String(error);
            } finally {
                state.pending = false;
                render();
            }
        }
        function toggle(open = !state.open) {
            state.open = open;
            panel.hidden = !open;
            button.setAttribute('aria-expanded', String(open));
            render();
            if (open) refresh();
        }
        button.onclick = () => toggle();
        window.addEventListener('keydown', event => { if (event.key === 'Escape' && state.open) toggle(false); });
        window.amsApiMonitor = Object.freeze({ refresh, show: () => toggle(true), hide: () => toggle(false) });
        render();
        refresh();
        setInterval(refresh, 5000);
    })();
