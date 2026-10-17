<script>
// ============================================================
// Antigravity Browser Shim v5
// ============================================================

// --- Native Storage Bridge (localStorage backend) ---
window.nativeStorage = {
  _data: JSON.parse(localStorage.getItem('__ag_storage') || '{}'),
  _listeners: [],
  async getItems() { return this._data; },
  async setItems(items) {
    Object.assign(this._data, items);
    for (const [k, v] of Object.entries(items)) { if (v === null) delete this._data[k]; }
    localStorage.setItem('__ag_storage', JSON.stringify(this._data));
    for (const cb of this._listeners) { try { cb(items); } catch(e) {} }
  },
  onChanged(cb) {
    this._listeners.push(cb);
    return () => { this._listeners = this._listeners.filter(l => l !== cb); };
  }
};

// --- Native Notifications Bridge ---
window.nativeNotifications = {
  async requestPermission() { return 'granted'; },
  async showNotification(t, b) {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(t, { body: b });
    }
  },
  onClicked(cb) { return () => {}; }
};

// --- Native File Dialog Bridge ---
// Replaces Tauri's native file dialog with a web-based file picker
window.nativeFileDialog = {
  async showOpenDialog(options) {
    return new Promise((resolve) => {
      window.__agFilePicker.show(options || {}, resolve);
    });
  }
};

// --- Auto-Retry Watchdog ---
(function() {
  const MAX_SOFT = 3;
  const MAX_HARD = 1;
  const BASE_WAIT = 5000;
  const softKey = '__ag_retry_soft';
  const hardKey = '__ag_retry_hard';
  let soft = parseInt(sessionStorage.getItem(softKey) || '0', 10);
  let hard = parseInt(sessionStorage.getItem(hardKey) || '0', 10);
  const waitMs = BASE_WAIT + (soft * 1500);
  
  function isBlank() {
    // Check if the app actually rendered - a fully loaded app has 100+ divs
    // A blank/error/partial mount has < 20
    const divs = document.querySelectorAll('div').length;
    const btns = document.querySelectorAll('button').length;
    return divs < 20 || btns < 3;
  }
  
  setTimeout(() => {
    if (isBlank()) {
      if (soft < MAX_SOFT) {
        sessionStorage.setItem(softKey, String(soft + 1));
        console.log('[Watchdog] Soft retry ' + (soft+1) + '/' + MAX_SOFT + ' (divs=' + document.querySelectorAll('div').length + ')');
        location.reload();
      } else if (hard < MAX_HARD) {
        console.log('[Watchdog] Final reload; retaining browser drafts and preferences');
        sessionStorage.setItem(hardKey, String(hard + 1));
        location.replace(location.origin + location.pathname);
      } else {
        console.warn('[Watchdog] Exhausted. Ctrl+Shift+R or new tab.');
      }
    } else {
      sessionStorage.removeItem(softKey);
      sessionStorage.removeItem(hardKey);
    }
  }, waitMs);
})();

// --- Web File Picker UI ---
window.__agFilePicker = {
  show(options, callback) {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.id = '__ag_file_picker_overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,sans-serif;';
    
    const dialog = document.createElement('div');
    dialog.style.cssText = 'background:#1e1e1e;border:1px solid #3c3c3c;border-radius:12px;width:600px;max-height:80vh;display:flex;flex-direction:column;color:#ccc;box-shadow:0 20px 60px rgba(0,0,0,0.5);';
    
    // Header
    const header = document.createElement('div');
    header.style.cssText = 'padding:16px 20px;border-bottom:1px solid #3c3c3c;display:flex;align-items:center;justify-content:space-between;';
    header.innerHTML = '<div style="font-size:14px;font-weight:600;color:#fff;">Select Folder</div>';
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'background:none;border:none;color:#888;font-size:16px;cursor:pointer;padding:4px 8px;border-radius:4px;';
    closeBtn.onmouseenter = () => closeBtn.style.color = '#fff';
    closeBtn.onmouseleave = () => closeBtn.style.color = '#888';
    closeBtn.onclick = () => { overlay.remove(); callback(null); };
    header.appendChild(closeBtn);
    
    // Path bar
    const pathBar = document.createElement('div');
    pathBar.style.cssText = 'padding:8px 20px;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:8px;';
    const pathInput = document.createElement('input');
    pathInput.style.cssText = 'flex:1;background:#2a2a2a;border:1px solid #3c3c3c;border-radius:6px;padding:6px 12px;color:#fff;font-size:13px;outline:none;';
    pathInput.value = 'C:\\\\Users';
    const goBtn = document.createElement('button');
    goBtn.textContent = 'Go';
    goBtn.style.cssText = 'background:#0e639c;color:#fff;border:none;border-radius:6px;padding:6px 16px;cursor:pointer;font-size:13px;';
    goBtn.onclick = () => loadDir(pathInput.value);
    pathInput.onkeydown = (e) => { if (e.key === 'Enter') loadDir(pathInput.value); };
    pathBar.appendChild(pathInput);
    pathBar.appendChild(goBtn);
    
    // File list
    const fileList = document.createElement('div');
    fileList.style.cssText = 'flex:1;overflow-y:auto;max-height:400px;padding:8px 0;';
    
    // Footer
    const footer = document.createElement('div');
    footer.style.cssText = 'padding:12px 20px;border-top:1px solid #3c3c3c;display:flex;justify-content:space-between;align-items:center;';
    const selectedLabel = document.createElement('span');
    selectedLabel.style.cssText = 'font-size:12px;color:#888;';
    selectedLabel.textContent = 'No folder selected';
    const selectBtn = document.createElement('button');
    selectBtn.textContent = 'Select Folder';
    selectBtn.style.cssText = 'background:#0e639c;color:#fff;border:none;border-radius:6px;padding:8px 24px;cursor:pointer;font-size:13px;font-weight:500;opacity:0.5;';
    selectBtn.disabled = true;
    footer.appendChild(selectedLabel);
    footer.appendChild(selectBtn);
    
    dialog.appendChild(header);
    dialog.appendChild(pathBar);
    dialog.appendChild(fileList);
    dialog.appendChild(footer);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    
    let selectedPath = null;
    
    function loadDir(dirPath) {
      fileList.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">Loading...</div>';
      pathInput.value = dirPath;
      
      fetch('/api/browse?path=' + encodeURIComponent(dirPath))
        .then(r => r.json())
        .then(data => {
          fileList.innerHTML = '';
          if (data.error) {
            fileList.innerHTML = '<div style="padding:20px;text-align:center;color:#f44;">Error: ' + data.error + '</div>';
            return;
          }
          
          // Parent dir button
          if (data.parent) {
            const parentEl = createItem('..', 'folder', data.parent);
            fileList.appendChild(parentEl);
          }
          
          // Folders first, then files
          const folders = data.items.filter(i => i.type === 'folder');
          const files = data.items.filter(i => i.type === 'file');
          
          folders.forEach(item => {
            fileList.appendChild(createItem(item.name, 'folder', item.path));
          });
          files.forEach(item => {
            fileList.appendChild(createItem(item.name, 'file', item.path));
          });
          
          if (data.items.length === 0) {
            fileList.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">Empty folder</div>';
          }
        })
        .catch(err => {
          fileList.innerHTML = '<div style="padding:20px;text-align:center;color:#f44;">Network error</div>';
        });
    }
    
    function createItem(name, type, path) {
      const el = document.createElement('div');
      const icon = type === 'folder' ? '📁' : '📄';
      el.style.cssText = 'padding:6px 20px;display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;';
      el.innerHTML = '<span>' + icon + '</span><span style="flex:1;">' + name + '</span>';
      
      el.onmouseenter = () => el.style.background = '#2a2a2a';
      el.onmouseleave = () => { if (selectedPath !== path) el.style.background = 'none'; };
      
      el.onclick = () => {
        if (type === 'folder') {
          // Select this folder
          document.querySelectorAll('#__ag_file_picker_overlay [data-selected]').forEach(s => {
            s.style.background = 'none';
            delete s.dataset.selected;
          });
          el.style.background = '#094771';
          el.dataset.selected = 'true';
          selectedPath = path;
          selectedLabel.textContent = path;
          selectBtn.disabled = false;
          selectBtn.style.opacity = '1';
        }
      };
      
      el.ondblclick = () => {
        if (type === 'folder') loadDir(path);
      };
      
      return el;
    }
    
    selectBtn.onclick = () => {
      if (selectedPath) {
        overlay.remove();
        callback(selectedPath);
      }
    };
    
    // Start at user home
    loadDir(data_home_dir);
  }
};
var data_home_dir = '{HOME_DIR}';

// --- "Open IDE" + "Add Folder" Intercept ---
(function() {
  const CODE_SERVER_URL = 'http://' + location.hostname + ':{CODE_SERVER_PORT}';
  
  function intercept() {
    document.querySelectorAll('a, button, [role="button"]').forEach(el => {
      const txt = el.textContent.trim();
      
      // Open IDE button
      if (txt.includes('Open IDE') && !el.dataset.agIntercepted) {
        el.dataset.agIntercepted = 'true';
        el.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          window.open(CODE_SERVER_URL, '_blank');
        }, true);
      }
    });
  }
  
  setInterval(intercept, 2000);
  setTimeout(() => {
    if (document.body) new MutationObserver(intercept).observe(document.body, { childList: true, subtree: true });
  }, 3000);
})();

console.log('[Shim] v5 loaded: Storage + Notifications + FileDialog + Watchdog + IDE');

// ============================================================
// Antigravity Web -- Live Token Widget
// ============================================================
(function() {
  const API_STATS_URL = location.origin + '/api/stats';
  // The original desktop AMS script supplies the toolbar and counters.
  if (window.__AMS_WEB_MIRROR_PENDING) return;
  let expanded = false;
  let lastStats = null;
  let currency = localStorage.getItem('__ag_currency') || 'USD';
  const USD_TO_EUR = 0.92;

  function fmtCost(usdAmount) {
    if (currency === 'EUR') {
      return '€' + (usdAmount * USD_TO_EUR).toFixed(5);
    }
    return '$' + usdAmount.toFixed(5);
  }

  // Create widget container
  const widget = document.createElement('div');
  widget.id = '__ag_token_widget';

  // Badge (collapsed view)
  const badge = document.createElement('div');
  badge.id = '__ag_token_badge';
  badge.innerHTML = '<span style="font-size:14px">⚡</span><span id="__ag_token_count">0 tokens</span>';

  // Panel (expanded view)
  const panel = document.createElement('div');
  panel.id = '__ag_token_panel';
  panel.onclick = (e) => { e.stopPropagation(); };

  widget.appendChild(badge);
  widget.appendChild(panel);

  function adjustWidgetStyle() {
    const parent = widget.parentElement;
    const isInSidebar = parent && parent.classList.contains('bg-sidebar');
    
    if (isInSidebar) {
      widget.style.cssText = 'position:relative;margin-left:auto;height:100%;display:flex;align-items:center;z-index:99998;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:13px;user-select:none;';
      badge.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 8px;height:28px;font-size:13px;font-weight:400;color:#cccccc;cursor:pointer;border-radius:4px;transition:background-color 0.15s ease,color 0.15s ease;user-select:none;';
      if (expanded) {
        badge.style.background = 'rgba(255, 255, 255, 0.08)';
        badge.style.color = '#ffffff';
      } else {
        badge.style.background = 'transparent';
        badge.style.color = '#cccccc';
      }
      panel.style.cssText = (expanded ? 'display:block;' : 'display:none;') + 'position:fixed;top:33px;right:8px;z-index:99999;background:rgba(20,20,24,0.95);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:16px;color:#e0e0e0;min-width:300px;box-shadow:0 10px 30px rgba(0,0,0,0.5);font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;';
    } else {
      widget.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:99998;font-family:system-ui,-apple-system,sans-serif;font-size:12px;cursor:pointer;user-select:none;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);';
      badge.style.cssText = (expanded ? 'display:none;' : 'display:flex;') + 'background:rgba(30,30,35,0.75);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:6px 14px;color:#e0e0e0;align-items:center;gap:8px;box-shadow:0 4px 20px rgba(0,0,0,0.4);transition:all 0.2s ease;';
      panel.style.cssText = (expanded ? 'display:block;' : 'display:none;') + 'background:rgba(22,22,26,0.95);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:16px 20px;color:#e0e0e0;min-width:280px;box-shadow:0 12px 40px rgba(0,0,0,0.6);position:absolute;bottom:40px;right:0;';
    }
  }

  badge.onmouseenter = () => {
    const parent = widget.parentElement;
    const isInSidebar = parent && parent.classList.contains('bg-sidebar');
    if (isInSidebar) {
      badge.style.background = 'rgba(255, 255, 255, 0.08)';
      badge.style.color = '#ffffff';
    } else {
      badge.style.transform = 'scale(1.03) translateY(-2px)';
      badge.style.background = 'rgba(40,40,45,0.85)';
      badge.style.border = '1px solid rgba(14,99,156,0.4)';
      badge.style.boxShadow = '0 6px 25px rgba(0,0,0,0.5)';
    }
  };
  badge.onmouseleave = () => {
    const parent = widget.parentElement;
    const isInSidebar = parent && parent.classList.contains('bg-sidebar');
    if (isInSidebar) {
      if (!expanded) {
        badge.style.background = 'transparent';
        badge.style.color = '#cccccc';
      }
    } else {
      badge.style.transform = 'scale(1)';
      badge.style.background = 'rgba(30,30,35,0.75)';
      badge.style.border = '1px solid rgba(255,255,255,0.08)';
      badge.style.boxShadow = '0 4px 20px rgba(0,0,0,0.4)';
    }
  };

  // Toggle expanded
  widget.onclick = (e) => {
    e.stopPropagation();
    expanded = !expanded;
    adjustWidgetStyle();
  };

  // Click away to close panel
  document.addEventListener('click', (e) => {
    if (expanded && !widget.contains(e.target)) {
      expanded = false;
      panel.style.display = 'none';
      adjustWidgetStyle();
    }
  });

  const PRICING = {
    'gemini-3.5-flash-medium': { input: 0.075, output: 0.30 },
    'gemini-3.5-flash-high':   { input: 0.075, output: 0.30 },
    'gemini-3.5-flash-low':    { input: 0.075, output: 0.30 },
    'gemini-3.1-pro-high':     { input: 1.25, output: 5.00 },
    'gemini-3.1-pro-low':      { input: 1.25, output: 5.00 },
    'claude-sonnet-4.6':       { input: 3.00, output: 15.00 },
    'claude-opus-4.6':         { input: 15.00, output: 75.00 },
    'gpt-oss-120b':            { input: 2.50, output: 10.00 }
  };

  function getModelPricing(modelName) {
    const m = (modelName || 'gemini-3.5-flash-high').toLowerCase();
    if (m.includes('opus') || m.includes('opsu')) return PRICING['claude-opus-4.6'];
    if (m.includes('sonnet')) return PRICING['claude-sonnet-4.6'];
    if (m.includes('pro')) return PRICING['gemini-3.1-pro-high'];
    if (m.includes('gpt') || m.includes('oss')) return PRICING['gpt-oss-120b'];
    if (m.includes('flash') || m.includes('gemini')) return PRICING['gemini-3.5-flash-high'];
    return PRICING['gemini-3.5-flash-high'];
  }

  function calculateStatsCost(s) {
    let totalCost = 0;
    Object.entries(s.requests_by_model || {}).forEach(([name, info]) => {
      const price = getModelPricing(name);
      const promptTok = info.prompt_tokens || Math.floor((info.tokens || 0) * 0.4);
      const complTok = info.completion_tokens || Math.floor((info.tokens || 0) * 0.6);
      totalCost += (promptTok * price.input + complTok * price.output) / 1000000;
    });
    return totalCost;
  }

  function fmt(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
  }

  // Active temporary tokens (for instant updates during streaming)
  let activeTempTokens = 0;
  let activeTempCost = 0;

  function fmtTime(seconds) {
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
  }

  // Update widget
  function updateWidget(data) {
    if (!data) return;
    const s = data.session;
    const committedCost = calculateStatsCost(s);

    const displayTokens = s.total_tokens + activeTempTokens;
    const displayCost = committedCost + activeTempCost;
    const displayRequests = s.total_requests + (activeTempTokens > 0 ? 1 : 0);

    // Active uncounted elements
    const activePromptEl = document.querySelector('[role="article"][aria-label="User message"]:not([__ag_counted])');
    const activeComplEl = document.querySelector('[role="article"][aria-label="Agent response"]:not([__ag_counted])');
    const activePromptTok = activePromptEl ? Math.max(1, Math.floor(activePromptEl.textContent.trim().length / 4)) : 0;
    const activeComplTok = activeComplEl ? Math.max(1, Math.floor(activeComplEl.textContent.trim().length / 4)) : 0;

    const displayPromptTokens = s.total_prompt_tokens + activePromptTok;
    const displayCompletionTokens = s.total_completion_tokens + activeComplTok;

    const countEl = document.getElementById('__ag_token_count');
    if (countEl) {
      countEl.textContent = fmt(displayTokens) + ' tokens (' + fmtCost(displayCost) + ')';
    }

    // Build model breakdown rows
    const modelRows = {};
    Object.entries(s.requests_by_model || {}).forEach(([name, info]) => {
      modelRows[name] = {
        requests: info.requests,
        tokens: info.tokens,
        prompt_tokens: info.prompt_tokens,
        completion_tokens: info.completion_tokens
      };
    });

    if (activeTempTokens > 0) {
      const activeModel = getModelName();
      if (!modelRows[activeModel]) {
        modelRows[activeModel] = { requests: 0, tokens: 0, prompt_tokens: 0, completion_tokens: 0 };
      }
      modelRows[activeModel].requests += 1;
      modelRows[activeModel].tokens += activeTempTokens;
      modelRows[activeModel].prompt_tokens += activePromptTok;
      modelRows[activeModel].completion_tokens += activeComplTok;
    }

    const modelsHtml = Object.entries(modelRows)
      .map(([name, info]) => {
        const price = getModelPricing(name);
        const cost = (info.prompt_tokens * price.input + info.completion_tokens * price.output) / 1000000;
        return `
          <div style="display:flex;flex-direction:column;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="color:#93c5fd;font-weight:600;">${name}</span>
              <span style="color:#facc15;">${fmtCost(cost)}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:10px;color:#888;margin-top:2px;">
              <span>${fmt(info.tokens)} tot (${info.requests}x)</span>
              <span>In: ${fmt(info.prompt_tokens)} | Out: ${fmt(info.completion_tokens)}</span>
            </div>
          </div>
        `;
      }).join('') || '<div style="color:#666;text-align:center;padding:8px;">Noch keine Requests</div>';

    panel.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <span style="font-weight:600;font-size:13px;color:#fff;">⚡ Token Usage</span>
        <div style="display:flex;align-items:center;gap:4px;background:rgba(255,255,255,0.05);padding:2px;border-radius:6px;border:1px solid rgba(255,255,255,0.08);">
          <button id="__ag_btn_usd" style="background:${currency==='USD'?'#3b82f6':'transparent'};color:${currency==='USD'?'#fff':'#888'};border:none;border-radius:4px;padding:2px 6px;font-size:10px;font-weight:600;cursor:pointer;transition:all 0.15s;outline:none;">USD</button>
          <button id="__ag_btn_eur" style="background:${currency==='EUR'?'#3b82f6':'transparent'};color:${currency==='EUR'?'#fff':'#888'};border:none;border-radius:4px;padding:2px 6px;font-size:10px;font-weight:600;cursor:pointer;transition:all 0.15s;outline:none;">EUR</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
        <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 10px;text-align:center;">
          <div style="font-size:18px;font-weight:700;color:#60a5fa;">${fmt(displayTokens)}</div>
          <div style="font-size:10px;color:#888;margin-top:2px;">Total Tokens</div>
        </div>
        <div style="background:rgba(16,185,129,0.05);border:1px solid rgba(16,185,129,0.15);border-radius:8px;padding:8px 10px;text-align:center;">
          <div style="font-size:18px;font-weight:700;color:#34d399;">${fmtCost(displayCost)}</div>
          <div style="font-size:10px;color:#888;margin-top:2px;">Est. Cost (${currency})</div>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:10px;padding:0 4px;">
        <span>⬆ Prompt: ${fmt(displayPromptTokens)}</span>
        <span>⬇ Completion: ${fmt(displayCompletionTokens)}</span>
      </div>
      <div style="font-size:11px;font-weight:600;color:#999;margin-bottom:6px;border-top:1px solid rgba(255,255,255,0.1);padding-top:8px;">Kosten pro Modell</div>
      ${modelsHtml}
      <div style="text-align:center;margin-top:10px;font-size:10px;color:#555;">Klicke zum Schliessen</div>
    `;

    const btnUsd = document.getElementById('__ag_btn_usd');
    const btnEur = document.getElementById('__ag_btn_eur');
    if (btnUsd && btnEur) {
      btnUsd.onclick = (e) => {
        e.stopPropagation();
        if (currency !== 'USD') {
          currency = 'USD';
          localStorage.setItem('__ag_currency', 'USD');
          updateWidget(data);
        }
      };
      btnEur.onclick = (e) => {
        e.stopPropagation();
        if (currency !== 'EUR') {
          currency = 'EUR';
          localStorage.setItem('__ag_currency', 'EUR');
          updateWidget(data);
        }
      };
    }
  }

  // Poll stats
  async function pollStats() {
    try {
      // Keep overlays outside the native sidebar's flex layout.
      const container = document.body;
      if (container) {
        const currentWidget = document.getElementById('__ag_token_widget');
        if (!currentWidget) {
          container.appendChild(widget);
        } else if (currentWidget.parentElement !== container) {
          container.appendChild(widget);
        }
      }
      adjustWidgetStyle();

      const resp = await fetch(API_STATS_URL);
      if (resp.ok) {
        lastStats = await resp.json();
        updateWidget(lastStats);
      }
    } catch(e) {
      const countEl = document.getElementById('__ag_token_count');
      if (countEl) countEl.textContent = 'offline';
    }
  }

  // --- Client-Side Manual Chat Token Tracker ---
  let lastHref = location.href;
  let disableTrackingUntil = Date.now() + 2000; // block initial load

  function getModelName() {
    const btn = document.querySelector('[aria-label^="Select model"]');
    if (btn) {
      const label = btn.getAttribute('aria-label') || '';
      return label.replace('Select model, current: ', '').trim();
    }
    return 'Gemini 3.5 Flash (High)';
  }

  async function reportTransaction(promptText, completionText) {
    const model = getModelName();
    const promptTokens = Math.max(1, Math.floor(promptText.length / 4));
    const completionTokens = Math.max(1, Math.floor(completionText.length / 4));
    
    console.log('[Token Tracker] Manual chat transaction:', { promptTokens, completionTokens, model });
    
    activeTempTokens = 0;
    activeTempCost = 0;

    try {
      await fetch(API_STATS_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          prompt_tokens: promptTokens,
          completion_tokens: completionTokens,
          model: model
        })
      });
      pollStats();
    } catch (e) {
      console.error('[Token Tracker] Failed to report transaction:', e);
    }
  }

  function monitorChat() {
    if (location.href !== lastHref) {
      lastHref = location.href;
      disableTrackingUntil = Date.now() + 2000;
      activeTempTokens = 0;
      activeTempCost = 0;
      document.querySelectorAll('[role="article"]').forEach(el => {
        el.__ag_counted = true;
      });
      return;
    }

    const articles = Array.from(document.querySelectorAll('[role="article"]'));

    if (Date.now() < disableTrackingUntil) {
      activeTempTokens = 0;
      activeTempCost = 0;
      articles.forEach(el => {
        el.__ag_counted = true;
        if (el.getAttribute('aria-label') === 'Agent response') {
          el.__ag_last_text = el.textContent.trim();
        }
      });
      return;
    }

    let uncountedPairs = 0;
    for (let i = 0; i < articles.length; i++) {
      const el = articles[i];
      if (el.getAttribute('aria-label') === 'User message' && !el.__ag_counted) {
        const nextEl = articles[i + 1];
        if (nextEl && nextEl.getAttribute('aria-label') === 'Agent response') {
          uncountedPairs++;
        }
      }
    }

    if (uncountedPairs > 1) {
      console.log('[Token Tracker] History load detected, marking all as counted');
      activeTempTokens = 0;
      activeTempCost = 0;
      articles.forEach(el => {
        el.__ag_counted = true;
        if (el.getAttribute('aria-label') === 'Agent response') {
          el.__ag_last_text = el.textContent.trim();
        }
      });
      return;
    }

    let foundActive = false;
    for (let i = 0; i < articles.length; i++) {
      const el = articles[i];
      const label = el.getAttribute('aria-label') || '';

      if (label === 'User message' && !el.__ag_counted) {
        const nextEl = articles[i + 1];
        if (nextEl && nextEl.getAttribute('aria-label') === 'Agent response') {
          foundActive = true;
          const promptText = el.textContent.trim();
          const responseText = nextEl.textContent.trim();
          const isLast = (i + 1 === articles.length - 1);

          const promptTok = Math.max(1, Math.floor(promptText.length / 4));
          const complTok = Math.max(1, Math.floor(responseText.length / 4));
          const price = getModelPricing(getModelName());
          
          activeTempTokens = promptTok + complTok;
          activeTempCost = (promptTok * price.input + complTok * price.output) / 1000000;

          if (!isLast) {
            el.__ag_counted = true;
            nextEl.__ag_counted = true;
            reportTransaction(promptText, responseText);
          } else {
            if (responseText !== nextEl.__ag_last_text) {
              nextEl.__ag_last_text = responseText;
              nextEl.__ag_last_change = Date.now();
              updateWidget(lastStats);
            } else if (responseText.length > 0 && Date.now() - nextEl.__ag_last_change > 3000) {
              el.__ag_counted = true;
              nextEl.__ag_counted = true;
              reportTransaction(promptText, responseText);
            }
          }
        }
      }
    }

    if (!foundActive && activeTempTokens > 0) {
      activeTempTokens = 0;
      activeTempCost = 0;
      updateWidget(lastStats);
    }
  }

  function init() {
    const container = document.body;
    if (container) {
      container.appendChild(widget);
    }
    adjustWidgetStyle();
    pollStats();
    setInterval(pollStats, 5000);

    document.querySelectorAll('[role="article"]').forEach(el => {
      el.__ag_counted = true;
      if (el.getAttribute('aria-label') === 'Agent response') {
        el.__ag_last_text = el.textContent.trim();
      }
    });

    setInterval(monitorChat, 300);
  }

  function initBrainShortcut() {
    setInterval(() => {
        const addContextBtn = document.querySelector('button[aria-label="Add context"]');
        if (addContextBtn && !document.querySelector('.antigravity-brain-btn')) {
            const flexContainer = addContextBtn.parentElement;
            if (flexContainer) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'antigravity-brain-btn flex items-center justify-center h-7 w-7 rounded-lg cursor-pointer hover:bg-secondary transition-colors text-secondary-foreground';
                btn.title = 'Brain-Ordner öffnen';
                btn.style.marginLeft = '6px';
                btn.style.padding = '0';
                btn.style.background = 'transparent';
                btn.style.border = 'none';
                btn.style.outline = 'none';
                btn.style.display = 'inline-flex';
                
                btn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2Z"/>
                        <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2Z"/>
                    </svg>
                `;
                
                btn.addEventListener('click', () => {
                    try {
                        if (window.electronNative && typeof window.electronNative.openBrain === 'function') {
                            window.electronNative.openBrain();
                        } else if (window.__agFilePicker && typeof window.__agFilePicker.show === 'function') {
                            window.__agFilePicker.show({ title: 'Brain-Ordner picken' }, (selectedPath) => {
                                console.log('[AMS Web UI] Picked path:', selectedPath);
                            });
                        }
                    } catch (err) {
                        console.error('[AMS UI] Brain click failed:', err);
                    }
                });
                
                flexContainer.appendChild(btn);
            }
        }
    }, 500);
  }

  if (document.body) {
    init();
    initBrainShortcut();
  } else {
    document.addEventListener('DOMContentLoaded', () => {
      init();
      initBrainShortcut();
    });
  }
})();
</script>
