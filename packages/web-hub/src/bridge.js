(function() {
  if (window.__agBridge && window.__agBridge._version === 45) return 'already_injected';

  window.__agBridge = {
    _ready: true,
    _version: 45,
    _debug: [],
    _voiceState: { isRecording: false, text: '', preRecordingText: '' },
    _lastInputKind: null,
    _composerProbe: { input: null, stableSamples: 0, signature: '' },

    log(msg) {
      this._debug.push('[' + new Date().toISOString().slice(11,19) + '] ' + msg);
      if (this._debug.length > 100) this._debug.shift();
      console.log('[AgBridge] ' + msg);
    },

    // --- Find chat input (Antigravity uses role=combobox contenteditable) ---
    findInput() {
      const remember = (element, kind) => {
        if (this._lastInputKind !== kind) {
          this._lastInputKind = kind;
          this.log('Input found: ' + kind);
        }
        return element;
      };
      // Primary: Antigravity's exact selector
      const combobox = document.querySelector('[role="combobox"][aria-label="Message input"]');
      if (combobox && combobox.offsetParent !== null) {
        return remember(combobox, 'combobox[aria-label="Message input"]');
      }
      // Fallback 1: Any contenteditable combobox
      const anyCombo = document.querySelector('[role="combobox"][contenteditable="true"]');
      if (anyCombo && anyCombo.offsetParent !== null) {
        return remember(anyCombo, 'combobox contenteditable');
      }
      // Fallback 2: Any visible contenteditable
      const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'));
      for (const el of editables) {
        if (el.offsetParent !== null && el.offsetHeight > 20) {
          return remember(el, 'contenteditable fallback');
        }
      }
      // Fallback 3: Textarea
      const textareas = Array.from(document.querySelectorAll('textarea'));
      for (const ta of textareas) {
        if (ta.offsetParent !== null && !ta.disabled) {
          return remember(ta, 'textarea fallback');
        }
      }

      if (this._lastInputKind !== 'missing') {
        this._lastInputKind = 'missing';
        this.log('Input NOT found!');
      }
      return null;
    },

    getComposerState() {
      const input = this.findInput();
      if (!input) {
        this._composerProbe = { input: null, stableSamples: 0, signature: 'missing' };
        return {
          ready: false,
          inputFound: false,
          stableSamples: 0,
          reason: 'input-missing'
        };
      }

      const contentEditable = input.getAttribute('contenteditable');
      const editable = !input.disabled
        && input.getAttribute('aria-disabled') !== 'true'
        && contentEditable !== 'false'
        && (contentEditable === 'true' || input.matches('textarea, input'));
      const busy = Boolean(input.closest('[aria-busy="true"]'));
      const modelLoading = Array.from(
        document.querySelectorAll('button, [role="button"]')
      ).some(element => {
        if (element.offsetParent === null) return false;
        const label = [
          element.getAttribute('aria-label'),
          element.getAttribute('title'),
          element.textContent
        ].filter(Boolean).join(' ').trim().toLowerCase();
        return label.includes('modell wird geladen')
          || label.includes('model is loading')
          || label.includes('loading model');
      });
      const sameInput = this._composerProbe?.input === input;
      const baseReady = editable && !busy && !modelLoading;
      const stableSamples = baseReady
        ? (
          sameInput && this._composerProbe?.baseReady
            ? Number(this._composerProbe.stableSamples || 0) + 1
            : 1
        )
        : 0;
      const ready = baseReady && stableSamples >= 3;
      const reason = !editable
        ? 'input-disabled'
        : busy
          ? 'composer-busy'
          : modelLoading
            ? 'model-loading'
            : stableSamples < 3
              ? 'composer-stabilizing'
              : 'ready';
      const signature = [
        reason,
        String(stableSamples),
        input.getAttribute('aria-disabled') || '',
        contentEditable || ''
      ].join(':');
      const previousSignature = this._composerProbe?.signature || '';
      this._composerProbe = {
        input,
        stableSamples,
        signature,
        baseReady
      };
      if (previousSignature !== signature) {
        this.log('Composer state: ' + signature);
      }
      return {
        ready,
        inputFound: true,
        editable,
        busy,
        modelLoading,
        stableSamples,
        reason
      };
    },

    // --- Set input text (Lexical Editor compatible) ---
    setInputText(input, text) {
      input.focus();

      const isLexical = input.hasAttribute('data-lexical-editor');

      if (isLexical) {
        // Lexical Editor: Use ClipboardEvent / Paste simulation for robust multiline insertion
        // Step 1: Clear existing content by selecting all and deleting
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(input);
        selection.removeAllRanges();
        selection.addRange(range);

        // Delete selected content
        const deleteEvent = new InputEvent('beforeinput', {
          inputType: 'deleteContentBackward',
          bubbles: true,
          cancelable: true,
          composed: true
        });
        input.dispatchEvent(deleteEvent);

        // Step 2: Insert new text via Clipboard paste simulation
        selection.collapseToStart();

        try {
          const dataTransfer = new DataTransfer();
          dataTransfer.setData('text/plain', text);
          const pasteEvent = new ClipboardEvent('paste', {
            clipboardData: dataTransfer,
            bubbles: true,
            cancelable: true,
            composed: true
          });
          input.dispatchEvent(pasteEvent);
          this.log('Text set via Lexical paste simulation (' + text.length + ' chars)');
        } catch (e) {
          // Fallback to InputEvent insertText
          const insertEvent = new InputEvent('beforeinput', {
            inputType: 'insertText',
            data: text,
            bubbles: true,
            cancelable: true,
            composed: true
          });
          input.dispatchEvent(insertEvent);
          this.log('Text set via Lexical InputEvent fallback (' + text.length + ' chars): ' + e.message);
        }

        // Verify
        const content = input.textContent || '';
        this.log('Input content after set: "' + content.substring(0, 40) + '"');
      } else if (input.contentEditable === 'true' || input.contentEditable === 'plaintext-only') {
        // Standard contenteditable fallback
        input.innerHTML = '';
        input.focus();
        document.execCommand('selectAll', false, null);
        document.execCommand('delete', false, null);
        document.execCommand('insertText', false, text);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        this.log('Text set via execCommand (' + text.length + ' chars)');
      } else if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
        const proto = input.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype;
        const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value');
        if (nativeSetter && nativeSetter.set) {
          nativeSetter.set.call(input, text);
        } else {
          input.value = text;
        }
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        this.log('Text set via native setter (' + text.length + ' chars)');
      }
    },

    async waitForComposerReady(input, expectedText, timeoutMs) {
      const deadline = Date.now() + (timeoutMs || 3000);
      const normalizedExpected = String(expectedText || '').trim();
      while (Date.now() < deadline) {
        const actualText = String(
          input?.innerText || input?.textContent || input?.value || ''
        ).trim();
        const sendButton = Array.from(document.querySelectorAll('button')).find(button => {
          const label = (button.getAttribute('aria-label') || '').toLowerCase();
          return label.includes('send')
            && button.offsetParent !== null
            && !button.disabled
            && button.getAttribute('aria-disabled') !== 'true';
        });
        if (actualText === normalizedExpected && sendButton) {
          this.log('Composer ready after Lexical state update');
          return true;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      this.log('Composer did not become ready before timeout');
      return false;
    },

    // --- Get messages using role=article (Antigravity's message elements) ---
    getMessages() {
      const articles = Array.from(document.querySelectorAll('[role="article"]'));
      return articles.map(a => {
        const clone = a.cloneNode(true);
        clone.querySelectorAll('style, script, button, .hidden, [style*="display: none"]').forEach(el => el.remove());
        clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(el => {
          if (/^\d{2}:\d{2}$/.test(el.textContent.trim())) el.remove();
        });
        return {
          text: clone.textContent.trim(),
          html: a.innerHTML.substring(0, 200)
        };
      });
    },

    getMessageCount() {
      return document.querySelectorAll('[role="article"]').length;
    },

    getLastMessageText() {
      const articles = document.querySelectorAll('[role="article"]');
      if (articles.length === 0) {
        // Fallback: use scrollable container
        const scrollable = document.querySelector('.overflow-y-auto');
        if (scrollable && scrollable.children.length > 0) {
          const last = scrollable.children[scrollable.children.length - 1];
          const clone = last.cloneNode(true);
          clone.querySelectorAll('style, script, button, .hidden, [style*="display: none"]').forEach(el => el.remove());
          clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(el => {
            if (/^\d{2}:\d{2}$/.test(el.textContent.trim())) el.remove();
          });
          return clone.textContent.trim().substring(0, 10000);
        }
        return '';
      }
      const last = articles[articles.length - 1];
      const clone = last.cloneNode(true);
      clone.querySelectorAll('style, script, button, .hidden, [style*="display: none"]').forEach(el => el.remove());
      clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(el => {
        if (/^\d{2}:\d{2}$/.test(el.textContent.trim())) el.remove();
      });
      return clone.textContent.trim().substring(0, 10000);
    },

    // --- Programmatic Model Selector ---
    _modelSelector() {
      return document.querySelector(
        '[data-testid="model-selector-trigger"], [aria-label^="Select model"]'
      );
    },

    _modelLabel(selector) {
      return String(
        selector?.getAttribute('aria-label')
        || selector?.innerText
        || selector?.textContent
        || ''
      )
        .replace(/^Select model,\s*current:\s*/i, '')
        .trim();
    },

    _normalizeModelLabel(value) {
      return String(value || '')
        .replace(/\s+/g, ' ')
        .replace(/\s+Fast(?:\s*[ⓘℹ︎i])?\s*$/i, '')
        .replace(/\s*\((low|medium|high)\)\s*$/i, ' $1')
        .trim()
        .toLocaleLowerCase();
    },

    _isVisibleElement(element) {
      if (!(element instanceof Element)) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0;
    },

    _isActionableElement(element) {
      if (!this._isVisibleElement(element)) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return !element.disabled
        && element.getAttribute('aria-disabled') !== 'true'
        && !element.closest('[aria-hidden="true"],[inert],[data-state="closed"]')
        && style.pointerEvents !== 'none'
        && (element.offsetParent !== null || style.position === 'fixed')
        && rect.bottom > 0
        && rect.right > 0
        && rect.top < window.innerHeight
        && rect.left < window.innerWidth;
    },

    _activateElement(element) {
      if (!(element instanceof HTMLElement)) return false;
      element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      element.focus({ preventScroll: true });
      const eventOptions = { bubbles: true, cancelable: true, composed: true };
      if (typeof window.PointerEvent === 'function') {
        element.dispatchEvent(new PointerEvent('pointerdown', eventOptions));
      }
      element.dispatchEvent(new MouseEvent('mousedown', eventOptions));
      if (typeof window.PointerEvent === 'function') {
        element.dispatchEvent(new PointerEvent('pointerup', eventOptions));
      }
      element.dispatchEvent(new MouseEvent('mouseup', eventOptions));
      element.click();
      return true;
    },

    _closeModelMenu() {
      const target = document.activeElement || document.body;
      target.dispatchEvent(new KeyboardEvent('keydown', {
        bubbles: true,
        cancelable: true,
        composed: true,
        key: 'Escape',
      }));
    },

    _visibleModelOptions(selector) {
      const modelPattern = /^(Gemini|Claude|GPT(?:-|\s)|DeepSeek|o\d\b)/i;
      return Array.from(document.querySelectorAll(
        'button,[role="button"],[role="option"],[role="menuitem"],[role="menuitemradio"]'
      )).filter(candidate => {
        if (candidate === selector || selector?.contains(candidate)) return false;
        if (!this._isVisibleElement(candidate)) return false;
        const text = String(candidate.innerText || candidate.textContent || '')
          .replace(/\s+/g, ' ')
          .trim();
        return modelPattern.test(text);
      });
    },

    async _waitForModelOptions(selector, timeoutMs = 2500) {
      const deadline = Date.now() + timeoutMs;
      do {
        const options = this._visibleModelOptions(selector);
        if (options.length) return options;
        await new Promise(resolve => setTimeout(resolve, 80));
      } while (Date.now() < deadline);
      return [];
    },

    async _findEffortOption(targetName, timeoutMs = 2500) {
      const normalizedTarget = String(targetName || '').trim();
      const effortMatch = normalizedTarget.match(/\s*(?:\((low|medium|high)\)|(low|medium|high))\s*$/i);
      if (!effortMatch) return null;

      const effort = String(effortMatch[1] || effortMatch[2] || '').toLowerCase();
      const baseName = normalizedTarget.slice(0, effortMatch.index).trim();
      const wantedBase = this._normalizeModelLabel(baseName);
      const groups = Array.from(document.querySelectorAll(
        '[data-testid="model-selector-effort-group"][data-model-base]'
      ));
      const group = groups.find(candidate =>
        this._normalizeModelLabel(candidate.getAttribute('data-model-base')) === wantedBase
      );
      const groupItem = group?.closest('[role="menuitem"]');
      if (!groupItem || !this._isVisibleElement(groupItem)) return null;

      groupItem.focus({ preventScroll: true });
      groupItem.dispatchEvent(new KeyboardEvent('keydown', {
        bubbles: true,
        cancelable: true,
        composed: true,
        code: 'ArrowRight',
        key: 'ArrowRight',
      }));

      const deadline = Date.now() + timeoutMs;
      do {
        const effortLabel = Array.from(document.querySelectorAll(
          '[data-testid="model-selector-effort-option"][data-effort]'
        )).find(candidate =>
          String(candidate.getAttribute('data-effort') || '').toLowerCase() === effort
          && this._isVisibleElement(candidate)
        );
        const effortItem = effortLabel?.closest(
          '[role="menuitemradio"], [role="menuitem"], [role="option"]'
        );
        if (effortItem && this._isVisibleElement(effortItem)) return effortItem;
        await new Promise(resolve => setTimeout(resolve, 80));
      } while (Date.now() < deadline);
      return null;
    },

    async getAvailableModels() {
      const selector = this._modelSelector();
      if (!selector) {
        this.log('getAvailableModels: Selector button not found');
        return { success: false, current: '', models: [], error: 'selector_not_found' };
      }

      const current = this._modelLabel(selector);
      this._activateElement(selector);
      const options = await this._waitForModelOptions(selector);
      const modelPattern = /^(Gemini|Claude|GPT(?:-|\s)|DeepSeek|o\d\b)/i;

      const seen = new Set();
      const models = [];
      const effortGroups = Array.from(document.querySelectorAll(
        '[data-testid="model-selector-effort-group"][data-model-base]'
      )).filter(group => this._isVisibleElement(group.closest('[role="menuitem"]') || group));
      const groupedBases = new Set(effortGroups.map(group => this._normalizeModelLabel(group.getAttribute('data-model-base'))));
      for (const option of options) {
        const rawText = (option.innerText || option.textContent || '')
          .replace(/\s+/g, ' ')
          .trim();
        if (!modelPattern.test(rawText)) continue;

        const hasFastBadge = /\sFast(?:\s|$)/i.test(rawText);
        const label = rawText
          .replace(/\s+Fast(?:\s*[ⓘℹ︎i])?\s*$/i, '')
          .trim();
        const key = label.toLocaleLowerCase();
        if (groupedBases.has(this._normalizeModelLabel(label))) continue;
        if (!label || seen.has(key)) continue;
        seen.add(key);
        models.push({
          label,
          badge: hasFastBadge ? 'Fast' : '',
          source: 'native'
        });
      }

      for (const group of effortGroups) {
        const base = String(group.getAttribute('data-model-base') || '').trim();
        const item = group.closest('[role="menuitem"]');
        if (!base || !item) continue;
        item.focus({ preventScroll: true });
        item.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, composed: true, code: 'ArrowRight', key: 'ArrowRight' }));
        const deadline = Date.now() + 1500;
        let efforts = [];
        do {
          efforts = Array.from(document.querySelectorAll('[data-testid="model-selector-effort-option"][data-effort]'))
            .filter(option => this._isVisibleElement(option.closest('[role="menuitemradio"], [role="menuitem"], [role="option"]') || option));
          if (efforts.length) break;
          await new Promise(resolve => setTimeout(resolve, 80));
        } while (Date.now() < deadline);
        for (const option of efforts) {
          const effort = String(option.getAttribute('data-effort') || '').toLowerCase();
          if (!['low', 'medium', 'high'].includes(effort)) continue;
          const label = `${base} (${effort[0].toUpperCase()}${effort.slice(1)})`;
          if (seen.has(label.toLowerCase())) continue;
          seen.add(label.toLowerCase());
          models.push({ label, base_label: base, reasoning_effort: effort, source: 'native', badge: '' });
        }
        item.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, composed: true, code: 'ArrowLeft', key: 'ArrowLeft' }));
      }

      if (current && !seen.has(current.toLocaleLowerCase())) {
        models.unshift({ label: current, badge: '', source: 'native' });
      }

      this._closeModelMenu();
      return {
        success: models.length > 0,
        current,
        models,
        error: models.length > 0 ? '' : 'no_model_options'
      };
    },

    async selectModel(targetModel) {
      this.log('selectModel: requested "' + targetModel + '"');
      const btn = this._modelSelector();
      if (!btn) {
        this.log('selectModel: Selector button not found!');
        return false;
      }

      const current = this._modelLabel(btn);

      // Exact native labels are authoritative. Aliases only preserve older callers.
      let targetName = String(targetModel || '').trim();
      const t = targetName.toLowerCase();

      if (t === 'default' || t === 'antigravity' || t === '') {
        this.log('selectModel: Using default/current model');
        return true;
      }

      // Map API model IDs to native Antigravity UI labels
      const MODEL_ALIASES = {
        // Gemini 3.6
        'gemini-3.6-flash-high':   'Gemini 3.6 Flash (High)',
        'gemini-3.6-flash-medium': 'Gemini 3.6 Flash (Medium)',
        'gemini-3.6-flash-low':    'Gemini 3.6 Flash (Low)',
        'gemini-3.6-pro-high':     'Gemini 3.6 Pro (High)',
        'gemini-3.6-pro-low':      'Gemini 3.6 Pro (Low)',
        // Gemini 3.5
        'gemini-3.5-flash-high':   'Gemini 3.5 Flash (High)',
        'gemini-3.5-flash-medium': 'Gemini 3.5 Flash (Medium)',
        'gemini-3.5-flash-low':    'Gemini 3.5 Flash (Low)',
        // Gemini 3.1
        'gemini-3.1-pro-high':     'Gemini 3.1 Pro (High)',
        'gemini-3.1-pro-low':      'Gemini 3.1 Pro (Low)',
        // Claude
        'claude-sonnet-4.6':       'Claude Sonnet 4.6 (Thinking)',
        'claude-opus-4.6':         'Claude Opus 4.6 (Thinking)',
        // GPT
        'gpt-oss-120b':            'GPT-OSS 120B (Medium)',
      };

      // Direct alias lookup first
      if (MODEL_ALIASES[t]) {
        targetName = MODEL_ALIASES[t];
      }
      // Legacy versionless fallbacks for older callers
      else if (!/\d/.test(t) && t.includes('medium')) {
        targetName = 'Gemini 3.6 Flash (Medium)';
      } else if (!/\d/.test(t) && t.includes('high')) {
        targetName = 'Gemini 3.6 Flash (High)';
      } else if (!/\d/.test(t) && t.includes('low')) {
        targetName = 'Gemini 3.6 Flash (Low)';
      } else if (!/\d/.test(t) && t.includes('sonnet')) {
        targetName = 'Claude Sonnet 4.6 (Thinking)';
      } else if (!/\d/.test(t) && t.includes('opus')) {
        targetName = 'Claude Opus 4.6 (Thinking)';
      } else if (!/\d/.test(t) && t.includes('pro') && t.includes('high')) {
        targetName = 'Gemini 3.6 Pro (High)';
      } else if (!/\d/.test(t) && t.includes('pro') && t.includes('low')) {
        targetName = 'Gemini 3.6 Pro (Low)';
      } else if (!/\d/.test(t) && (t.includes('gpt') || t.includes('oss'))) {
        targetName = 'GPT-OSS 120B (Medium)';
      }

      if (!targetName) {
        this.log('selectModel: No matching model found for mapping: ' + targetModel);
        return false;
      }

      if (this._normalizeModelLabel(current) === this._normalizeModelLabel(targetName)) {
        this.log('selectModel: Already selected: ' + current);
        return true;
      }

      this._activateElement(btn);
      const candidates = await this._waitForModelOptions(btn);
      const wanted = this._normalizeModelLabel(targetName);
      let targetBtn = candidates.find(candidate =>
        this._normalizeModelLabel(candidate.innerText || candidate.textContent) === wanted
      ) || candidates.find(candidate =>
        this._normalizeModelLabel(candidate.innerText || candidate.textContent).includes(wanted)
      );
      if (!targetBtn) {
        targetBtn = await this._findEffortOption(targetName);
      }

      if (targetBtn) {
        this._activateElement(targetBtn);
        const deadline = Date.now() + 5000;
        do {
          const newCurrent = this._modelLabel(btn);
          if (this._normalizeModelLabel(newCurrent) === wanted) {
            this.log('selectModel: Successfully changed to ' + newCurrent);
            return true;
          }
          await new Promise(resolve => setTimeout(resolve, 100));
        } while (Date.now() < deadline);
        this._closeModelMenu();
        this.log('selectModel: Click was not confirmed for ' + targetName);
        return false;
      } else {
        this._closeModelMenu();
        this.log('selectModel: Dropdown option not found for ' + targetName);
        return false;
      }
    },

    async startNewConversation() {
      this.log('startNewConversation: requested');
      const newChatAction = this._globalNewConversationAction();
      if (newChatAction) {
        newChatAction.click();
        this.log('startNewConversation: Clicked New Conversation action');
        await new Promise(r => setTimeout(r, 1000));
        return true;
      }

      this.log('startNewConversation: New Conversation element not found!');
      return false;
    },

    hasNewConversationAction() {
      return Boolean(this._globalNewConversationAction());
    },

    _globalNewConversationAction() {
      const normalize = value => String(value || '').trim().toLowerCase();
      const isGlobalAction = element => {
        const labels = [
          element.getAttribute('aria-label'),
          element.getAttribute('title'),
          element.innerText,
          element.textContent
        ].map(normalize).filter(Boolean);
        if (labels.some(label => label.includes('in project'))) return false;
        return labels.some(label => label.includes('new conversation'));
      };
      const semanticMatches = Array.from(document.querySelectorAll(
        'button,a,[role="button"],[role="menuitem"]'
      )).filter(element => (
        this._isActionableElement(element) && isGlobalAction(element)
      ));
      const preferred = semanticMatches.filter(element => (
        element.getAttribute('data-testid') === 'new-conversation-button'
      ));
      if (preferred.length === 1) return preferred[0];
      if (preferred.length > 1) return null;
      if (semanticMatches.length === 1) return semanticMatches[0];
      if (semanticMatches.length > 1) return null;

      const legacyMatches = Array.from(document.querySelectorAll('div')).filter(element => (
        this._isActionableElement(element)
        && normalize(element.textContent) === 'new conversation'
      ));
      return legacyMatches.length === 1 ? legacyMatches[0] : null;
    },

    _projectEntries() {
      const controls = Array.from(document.querySelectorAll(
        'button[aria-label="New Conversation in Project"], '
        + 'a[aria-label="New Conversation in Project"]'
      ));
      const orderedHeaders = Array.from(document.querySelectorAll(
        'button[data-project-card="true"]'
      ));
      const hasOrderedHeaders = orderedHeaders.length === controls.length
        && orderedHeaders.every(header => (header.innerText || '').trim());
      return controls.map((control, index) => {
        let container = control.parentElement;
        let header = null;
        while (container) {
          const headers = Array.from(container.querySelectorAll(
            'button[data-project-card="true"]'
          ));
          if (headers.length === 1) {
            header = headers[0];
            break;
          }
          if (headers.length > 1) break;
          container = container.parentElement;
        }
        header = header
          || control.parentElement?.closest('[role="button"]')
          || null;
        if (!(header?.innerText || '').trim() && hasOrderedHeaders) {
          header = orderedHeaders[index] || null;
        }
        const text = (header?.innerText || '').trim();
        return { control, text };
      }).filter(entry => entry.text);
    },

    async startNewConversationForProject(projectName) {
      this.log('startNewConversationForProject: requested for ' + projectName);
      if (typeof projectName !== 'string' || !projectName.trim()) {
        this.log('startNewConversationForProject: Invalid or empty projectName provided');
        return false;
      }
      const normalize = value => (value || '')
        .trim()
        .replace(/\//g, '\\')
        .replace(/\\+$/, '')
        .toLowerCase();
      const wanted = normalize(projectName);
      const wantedName = wanted.split('\\').pop();
      const entries = this._projectEntries().map(entry => ({
        ...entry,
        normalized: normalize(entry.text)
      }));

      let match = entries.find(entry => entry.normalized === wanted);
      if (!match) {
        const nameMatches = entries.filter(entry =>
          entry.normalized === wantedName ||
          entry.normalized.endsWith('\\' + wantedName)
        );
        if (nameMatches.length === 1) match = nameMatches[0];
      }
      if (
        !match
        || match.control.disabled
        || match.control.getAttribute('aria-disabled') === 'true'
      ) {
        this.log(
          'startNewConversationForProject: No unique project row for ' +
          projectName + '; visible rows=' + entries.map(entry => entry.text).join(' | ')
        );
        return false;
      }

      match.control.click();
      this.log('startNewConversationForProject: Clicked project-specific plus button for ' + match.text);
      await new Promise(r => setTimeout(r, 1000));
      return true;
    },

    // --- Submit via Send button (aria-label="Send message") ---
    submitMessage(input) {
      // Primary: Find the actual Send message button
      const sendBtn = document.querySelector('button[aria-label="Send message"]');
      if (sendBtn && sendBtn.offsetParent !== null) {
        if (sendBtn.disabled || sendBtn.getAttribute('aria-disabled') === 'true') {
          this.log('Send message button is disabled; refusing to report a false submission');
          return { success: false, error: 'Send message button is disabled' };
        }
        sendBtn.click();
        this.log('Clicked Send message button');
        return { success: true, method: 'send-button' };
      }
      // Fallback: Any button with send in aria-label
      const allBtns = document.querySelectorAll('button');
      for (const btn of allBtns) {
        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('send') && btn.offsetParent !== null) {
          if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
            continue;
          }
          btn.click();
          this.log('Clicked send button: ' + btn.getAttribute('aria-label'));
          return { success: true, method: 'aria-send-button' };
        }
      }
      this.log('No enabled visible send button was found');
      return { success: false, error: 'No enabled visible send button was found' };
    },

    // --- Send message and wait for response ---
    async sendAndWait(text, timeoutMs) {
      timeoutMs = timeoutMs || 120000;
      this.log('sendAndWait: "' + text.substring(0, 50) + '..."');

      // Step 1: Find input
      const input = this.findInput();
      if (!input) {
        return { error: 'Chat input element not found. Is the chat UI visible?', debug: this._debug };
      }

      // Step 2: Snapshot before
      const beforeCount = this.getMessageCount();
      const beforeLastText = this.getLastMessageText();
      this.log('Before: ' + beforeCount + ' messages, lastText=' + beforeLastText.substring(0, 40) + '...');

      // Step 3: Set text
      if (text) {
        this.setInputText(input, text);
        if (!await this.waitForComposerReady(input, text, 3000)) {
          return { error: 'Composer did not accept the message text', debug: this._debug };
        }
      }

      // Step 4: Verify text was set
      const inputText = input.textContent || input.value || '';
      this.log('Input contains: "' + inputText.substring(0, 40) + '"');

      // Step 5: Submit
      const submission = this.submitMessage(input);
      if (!submission.success) {
        return { error: submission.error, debug: this._debug };
      }
      await new Promise(r => setTimeout(r, 500));

      // Step 6: Wait for response
      this.log('Waiting for AI response...');
      return new Promise((resolve, reject) => {
        let lastText = beforeLastText;
        let stableCount = 0;
        let responseStarted = false;
        const startTime = Date.now();

        const check = () => {
          const elapsed = Date.now() - startTime;
          if (elapsed > timeoutMs) {
            this.log('TIMEOUT after ' + elapsed + 'ms');
            resolve({
              error: 'Response timeout after ' + Math.round(elapsed/1000) + 's. beforeCount=' + beforeCount + ' afterCount=' + this.getMessageCount(),
              partial: this.getLastMessageText(),
              debug: this._debug.slice(-20)
            });
            return;
          }

          const currentCount = this.getMessageCount();
          const currentText = this.getLastMessageText();

          // Detect response started
          if (!responseStarted) {
            // New message appeared OR last message text changed significantly
            if (currentCount > beforeCount ||
                (currentText !== beforeLastText && currentText.length > beforeLastText.length + 5)) {
              responseStarted = true;
              this.log('Response started! (count: ' + beforeCount + ' -> ' + currentCount + ')');
              stableCount = 0;
              lastText = currentText;
            }
            setTimeout(check, 500);
            return;
          }

          // Check if response is stable (streaming finished)
          if (currentText && currentText === lastText && currentText.length > 0) {
            stableCount++;
            if (stableCount >= 16) {  // Stable for 8 seconds (16 * 500ms) — long JSON needs more time
              // Extract just the NEW response (not the old messages)
              let responseText = currentText;

              this.log('Response complete after ' + elapsed + 'ms (' + responseText.length + ' chars)');
              resolve({
                response: responseText,
                duration_ms: elapsed,
                messageCount: currentCount,
                debug: this._debug.slice(-15)
              });
              return;
            }
          } else {
            stableCount = 0;
            lastText = currentText;
          }

          setTimeout(check, 500);
        };

        // Start checking after delay to let the UI process
        setTimeout(check, 1500);
      });
    },

    // --- Streaming-Vorbereitung: Nachricht senden, ohne auf Antwort zu warten ---
    async prepareAndSend(text) {
      this.log('prepareAndSend: "' + text.substring(0, 50) + '..."');

      // Step 1: Find input
      const input = this.findInput();
      if (!input) {
        return { error: 'Chat input element not found. Is the chat UI visible?', debug: this._debug };
      }

      // Step 2: Snapshot before
      const beforeCount = this.getMessageCount();
      const beforeLastText = this.getLastMessageText();

      // Step 3: Set text
      if (text) {
        this.setInputText(input, text);
        if (!await this.waitForComposerReady(input, text, 3000)) {
          return { error: 'Composer did not accept the message text', debug: this._debug };
        }
      }

      // Step 4: Submit
      const submission = this.submitMessage(input);
      if (!submission.success) {
        return { error: submission.error, debug: this._debug };
      }
      this.log('Message submitted for streaming');

      return {
        success: true,
        submissionMethod: submission.method,
        beforeCount: beforeCount,
        beforeLastText: beforeLastText
      };
    },

    // --- Streaming-Poll: Aktuellen Antworttext abrufen ---
    _currentReactFiber(node) {
      if (!node) return null;
      const key = Object.keys(node).find(key => key.startsWith('__reactFiber$'));
      const fiber = key ? node[key] : null;
      if (!fiber) return null;
      let root = fiber;
      while (root.return) root = root.return;
      return root.stateNode?.current && root.stateNode.current !== root
        ? (fiber.alternate || fiber)
        : fiber;
    },

    _nativeResponseState(article) {
      const planners = Array.from(article.querySelectorAll('[data-testid="planner-response-text"]'));
      const steps = Array.from(article.querySelectorAll('[data-testid$="-step"]'));
      let observed = false;
      let running = false;
      let requiresUserInput = false;
      let plannerDone = false;
      const latestPlanner = planners[planners.length - 1];
      for (const node of [...planners, ...steps]) {
        let fiber = this._currentReactFiber(node);
        let stepStatus = null;
        for (let depth = 0; fiber && depth < 20; depth++, fiber = fiber.return) {
          const props = fiber.memoizedProps || {};
          if (stepStatus === null && typeof props.status === 'number' && props.step) stepStatus = props.status;
          if (stepStatus === null && typeof props.step?.status === 'number') stepStatus = props.step.status;
          if (props.segment && typeof props.isRunning === 'boolean') {
            observed = true;
            running ||= props.isRunning;
            const segmentSteps = Array.isArray(props.segment.steps) ? props.segment.steps : [];
            requiresUserInput ||= segmentSteps.some(step => step.status === 9);
            break;
          }
        }
        requiresUserInput ||= stepStatus === 9;
        if (node === latestPlanner) plannerDone = stepStatus === 3;
      }
      return {observed,running,requiresUserInput,finished:observed && !running && !requiresUserInput && plannerDone,planners};
    },

    pollResponse(beforeCount, beforeLastText) {
      const articles = Array.from(document.querySelectorAll('[role="article"]'));
      const currentCount = articles.length;

      if (currentCount <= beforeCount) {
        return {
          text: '',
          count: currentCount,
          started: false,
          finished: false
        };
      }

      // Determine which article is the assistant's response.
      // In Antigravity Tauri UI, the user message is at beforeCount, and the assistant message is at beforeCount + 1.
      let assistantArticle = null;
      const newArticles = articles.slice(beforeCount);
      const explicitRoles = newArticles.some(article => ['User message','Agent response'].includes(article.getAttribute('aria-label')));
      if (explicitRoles) {
        assistantArticle = newArticles.filter(article => article.getAttribute('aria-label') === 'Agent response').at(-1) || null;
      } else if (currentCount > beforeCount + 1) {
        assistantArticle = articles[beforeCount + 1];
      } else {
        // Only one new article. Check if it's the assistant's message or user's message.
        const singleNew = articles[beforeCount];
        const text = singleNew.textContent.trim();
        // If the text is substantially different from the prompt, it is the assistant's message
        if (text && text !== beforeLastText && !text.includes(beforeLastText.substring(0, 30))) {
          assistantArticle = singleNew;
        }
      }

      if (!assistantArticle) {
        return {
          text: '',
          count: currentCount,
          started: false,
          finished: false
        };
      }

      const native = this._nativeResponseState(assistantArticle);
      if (native.observed) {
        const text = native.planners.map(node => {
          const clone = node.cloneNode(true);
          clone.querySelectorAll('style,script,button,.hidden,[style*="display: none"],[data-testid="turn-cards-container"]').forEach(element => element.remove());
          return clone.textContent.trim();
        }).filter(Boolean).join('\n\n');
        return {text,count:currentCount,started:true,finished:native.finished,native_observed:true,is_running:native.running,requires_user_input:native.requiresUserInput};
      }

      const clone = assistantArticle.cloneNode(true);
      clone.querySelectorAll('style, script, button, .hidden, [style*="display: none"]').forEach(el => el.remove());
      clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(el => {
        if (/^\d{2}:\d{2}$/.test(el.textContent.trim())) el.remove();
      });
      const currentText = clone.textContent.trim();

      const hasFeedback = assistantArticle.querySelector('button[aria-label="Good response"]') ||
                          assistantArticle.querySelector('button[aria-label="Bad response"]');
      const hasReview = assistantArticle.querySelector('.review-button') ||
                        assistantArticle.querySelector('button[aria-label="Undo changes up to this point"]');
      const finished = !!(hasFeedback || hasReview);

      return {
        text: currentText,
        count: currentCount,
        started: true,
        finished: finished
      };
    },

    // =========================================================
    // NEW: Message Type Detection
    // =========================================================

    detectMessageType(el) {
      // Check for thinking block: Antigravity wraps thinking in <details> or data-thinking
      if (el.tagName === 'DETAILS' || el.querySelector('details')) return 'thinking';
      if (el.hasAttribute('data-thinking')) return 'thinking';
      // Check class names for thinking indicators
      const classStr = (el.className || '').toLowerCase();
      if (classStr.includes('thinking') || classStr.includes('reasoning')) return 'thinking';
      // Check for thinking summary element
      if (el.querySelector('[data-thinking]')) return 'thinking';
      // Check for summary element that says "Thinking" or "Reasoning"
      const summaryEl = el.querySelector('summary');
      if (summaryEl) {
        const st = summaryEl.textContent.trim().toLowerCase();
        if (st.includes('thinking') || st.includes('reasoning') || st.includes('thought')) return 'thinking';
      }

      // Tool call detection: code blocks with function-like patterns
      const codeBlocks = el.querySelectorAll('pre code, code');
      for (const code of codeBlocks) {
        const txt = code.textContent.trim();
        // Matches patterns like: tool_name(arg=val) or {"tool": "name"}
        if (/^[a-z_][a-z0-9_]*\s*\(/.test(txt) || /"tool"\s*:/.test(txt) || /"name"\s*:/.test(txt)) {
          return 'tool_call';
        }
      }

      // Tool result detection: follows tool_call pattern, has <pre> with result
      const preEls = el.querySelectorAll('pre');
      if (preEls.length > 0) {
        const preText = preEls[0].textContent.trim();
        // If it looks like JSON or structured output (not code), it's a tool result
        if (preText.startsWith('{') || preText.startsWith('[') || preText.startsWith('Error') || preText.startsWith('Result:')) {
          return 'tool_result';
        }
      }

      // System message detection: elements outside normal chat flow
      if (classStr.includes('system') || el.getAttribute('data-role') === 'system') return 'system';

      return 'text';
    },

    // =========================================================
    // NEW: Get Full Chat History with Type Detection
    // =========================================================

    getFullHistory() {
      const articles = Array.from(document.querySelectorAll('[role="article"]'));
      const messages = [];

      for (let i = 0; i < articles.length; i++) {
        const el = articles[i];
        // Determine role from structure (user messages typically have no buttons in them initially)
        const hasFeedbackBtns = el.querySelector('button[aria-label="Good response"]') ||
                                el.querySelector('button[aria-label="Bad response"]');
        const hasEditBtn = el.querySelector('button[aria-label*="Edit"]');

        let role = 'assistant';
        if (hasEditBtn && !hasFeedbackBtns) role = 'user';
        // Heuristic: user messages tend to be shorter and lack feedback buttons
        if (!hasFeedbackBtns && !hasEditBtn) {
          const textLen = (el.textContent || '').trim().length;
          if (textLen < 500 && i % 2 === 0) role = 'user';
        }

        // Detect sub-types within assistant messages
        const subEls = el.querySelectorAll('details, [data-thinking], pre code');
        let type = 'text';
        if (role === 'user') {
          type = 'text';
        } else {
          type = this.detectMessageType(el);
        }

        // Clone and clean
        const clone = el.cloneNode(true);
        clone.querySelectorAll('style, script, button, .hidden, [style*="display: none"]').forEach(e => e.remove());
        clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(e => {
          if (/^\d{2}:\d{2}$/.test(e.textContent.trim())) e.remove();
        });

        // For thinking blocks, try to extract thinking content separately
        let thinkingContent = null;
        if (type === 'thinking' || role === 'assistant') {
          const detailsEl = el.querySelector('details');
          if (detailsEl) {
            const detailsClone = detailsEl.cloneNode(true);
            detailsClone.querySelectorAll('style, script, button').forEach(e => e.remove());
            thinkingContent = detailsClone.textContent.trim().substring(0, 5000);
          }
        }

        messages.push({
          index: i,
          role: role,
          type: type,
          content: clone.textContent.trim().substring(0, 8000),
          thinking: thinkingContent,
          has_code: el.querySelectorAll('pre').length > 0,
          is_finished: !!(hasFeedbackBtns || el.querySelector('[aria-label="Undo changes up to this point"]'))
        });
      }

      return {
        messages: messages,
        total: messages.length,
        url: location.href,
        chat_id: (location.href.match(/\/c\/([a-f0-9\-]{36})/) || [])[1] || null
      };
    },

    // =========================================================
    // Get the projects that currently exist in the Anti-Gravity sidebar.
    // Historical conversation metadata is deliberately not used here.
    // =========================================================

    getProjectList() {
      const seen = new Set();
      const projects = [];

      for (const entry of this._projectEntries()) {
        const displayName = entry.text;
        const normalized = displayName.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
        if (!displayName || seen.has(normalized)) continue;
        seen.add(normalized);
        projects.push({
          id: normalized,
          name: displayName,
          display_name: displayName
        });
      }

      return { projects, count: projects.length };
    },

    // =========================================================
    // NEW: Get Sidebar Chat List
    // =========================================================

    _isCollapsedProject(button) {
      const expanded = String(button?.getAttribute('aria-expanded') || '')
        .trim()
        .toLowerCase();
      const state = String(button?.getAttribute('data-state') || '')
        .trim()
        .toLowerCase();
      return expanded === 'false' || state === 'closed' || state === 'collapsed';
    },

    _projectAttemptKey(button) {
      const values = [
        button?.getAttribute('data-project-id'),
        button?.getAttribute('data-project-path'),
        button?.getAttribute('aria-controls'),
        button?.getAttribute('title'),
        button?.textContent
      ];
      const identity = values.find(value => String(value || '').trim());
      return String(identity || '__anonymous_project__')
        .trim()
        .replace(/\s+/g, ' ')
        .toLowerCase();
    },

    async _waitForSidebarRender() {
      await new Promise(resolve => {
        let observer = null;
        let quietTimer = null;
        let deadlineTimer = null;
        let finished = false;
        const finish = () => {
          if (finished) return;
          finished = true;
          if (observer) observer.disconnect();
          if (quietTimer) clearTimeout(quietTimer);
          if (deadlineTimer) clearTimeout(deadlineTimer);
          resolve();
        };
        const scheduleQuietFinish = () => {
          if (quietTimer) clearTimeout(quietTimer);
          quietTimer = setTimeout(finish, 60);
        };
        const settleRoot = document.querySelector(
          '[data-testid="conversation-list-sidebar"]'
        ) || document.documentElement || document.body;
        if (typeof MutationObserver === 'function' && settleRoot) {
          observer = new MutationObserver(scheduleQuietFinish);
          observer.observe(settleRoot, {
            attributes: true,
            childList: true,
            subtree: true
          });
          deadlineTimer = setTimeout(finish, 250);
          scheduleQuietFinish();
        } else {
          setTimeout(finish, 0);
        }
      });
    },

    _mergeSidebarChat(chatById, candidate) {
      const id = String(candidate?.id || '').trim().toLowerCase();
      if (!/^[a-f0-9-]{36}$/i.test(id)) return false;
      const normalized = { ...candidate, id };
      const titlePriority = Math.max(0, Number(normalized._title_priority || 0));
      normalized._title_priority = titlePriority;
      const existing = chatById.get(id);
      if (!existing) {
        chatById.set(id, normalized);
        return true;
      }
      const existingTitlePriority = Math.max(
        0,
        Number(existing._title_priority || 0)
      );
      if (normalized.title && titlePriority >= existingTitlePriority) {
        existing.title = normalized.title;
      }
      existing._title_priority = Math.max(existingTitlePriority, titlePriority);
      if (normalized.href && !existing.href) existing.href = normalized.href;
      existing.active = Boolean(existing.active || normalized.active);
      existing.project_chat = Boolean(
        existing.project_chat || normalized.project_chat
      );
      return false;
    },

    _collectVisibleSidebarChats(chatById, activeChatId, allowLegacy = false) {
      const before = chatById.size;
      const rows = Array.from(document.querySelectorAll(
        '[data-testid="conversation-row-sidebar"][data-cascade-id]'
      ));
      for (const row of rows) {
        const id = String(row.getAttribute('data-cascade-id') || '').trim();
        const pill = row.querySelector('[data-testid^="convo-pill-"]');
        const titleSource = pill || row;
        this._mergeSidebarChat(chatById, {
          id,
          title: String(titleSource.textContent || '').trim().substring(0, 5000),
          active: id.toLowerCase() === activeChatId,
          project_chat: String(row.className || '').includes('ml-[22px]'),
          _title_priority: pill ? 2 : 1
        });
      }

      const pills = Array.from(document.querySelectorAll(
        '[data-testid^="convo-pill-"]'
      ));
      for (const pill of pills) {
        const testId = pill.getAttribute('data-testid') || '';
        const match = testId.match(/^convo-pill-([a-f0-9-]{36})$/i);
        if (!match) continue;
        const id = match[1];
        const row = pill.closest('[role="button"]');
        this._mergeSidebarChat(chatById, {
          id,
          title: String(pill.textContent || '').trim().substring(0, 5000),
          active: id.toLowerCase() === activeChatId,
          project_chat: Boolean(
            row && String(row.className || '').includes('ml-[22px]')
          ),
          _title_priority: 2
        });
      }

      // Older Anti-Gravity releases expose links or data attributes instead.
      // Collect these per viewport as well so legacy virtualized lists work.
      if (allowLegacy && rows.length === 0 && pills.length === 0) {
        const links = Array.from(document.querySelectorAll('a[href*="/c/"]'));
        for (const link of links) {
          const href = link.getAttribute('href') || '';
          const match = href.match(/\/c\/([a-f0-9\-]{36})/i);
          if (!match) continue;
          const clone = link.cloneNode(true);
          clone.querySelectorAll('svg, time, .text-xs, [aria-hidden]').forEach(
            element => element.remove()
          );
          this._mergeSidebarChat(chatById, {
            id: match[1],
            title: String(clone.textContent || '').trim().substring(0, 5000),
            href,
            active: match[1].toLowerCase() === activeChatId,
            project_chat: false,
            _title_priority: 1
          });
        }

        if (links.length === 0) {
          const items = document.querySelectorAll(
            '[data-conversation-id], [data-chat-id]'
          );
          for (const item of items) {
            const id = item.getAttribute('data-conversation-id')
              || item.getAttribute('data-chat-id');
            this._mergeSidebarChat(chatById, {
              id,
              title: String(item.textContent || '').trim().substring(0, 100),
              active: String(id || '').toLowerCase() === activeChatId,
              project_chat: false,
              _title_priority: 1
            });
          }
        }
      }
      return chatById.size - before;
    },

    async _materializeSidebarChats(chatById, activeChatId) {
      const startedAt = Date.now();
      const deadlineMs = 7000;
      const maxPasses = 6;
      const maxPositionsPerPass = 32;
      const maxExpansions = 200;
      let expansions = 0;
      let complete = false;
      let limitReached = false;
      const attemptedProjectButtons = new WeakSet();
      const projectAttemptCounts = new Map();
      const unresolvedProjectKeys = new Set();
      const maxAttemptsPerProject = 2;

      let sidebar = document.querySelector(
        '[data-testid="conversation-list-sidebar"]'
      );
      for (let attempt = 0; !sidebar && attempt < 8; attempt += 1) {
        await this._waitForSidebarRender();
        sidebar = document.querySelector(
          '[data-testid="conversation-list-sidebar"]'
        );
      }
      const allowLegacy = !sidebar;

      const withinLimits = () => (
        Date.now() - startedAt < deadlineMs && expansions < maxExpansions
      );
      const collect = () => this._collectVisibleSidebarChats(
        chatById,
        activeChatId,
        allowLegacy
      );
      const expandCurrentViewport = async () => {
        collect();
        while (withinLimits()) {
          const collapsed = Array.from(document.querySelectorAll(
            'button[data-project-card="true"]'
          )).find(button => (
            this._isCollapsedProject(button)
            && !attemptedProjectButtons.has(button)
            && Number(
              projectAttemptCounts.get(this._projectAttemptKey(button)) || 0
            ) < maxAttemptsPerProject
          ));
          if (!collapsed) break;
          const projectKey = this._projectAttemptKey(collapsed);
          attemptedProjectButtons.add(collapsed);
          projectAttemptCounts.set(
            projectKey,
            Number(projectAttemptCounts.get(projectKey) || 0) + 1
          );
          collapsed.click();
          expansions += 1;
          await this._waitForSidebarRender();
          collect();
          const stillMaterialized = Array.from(document.querySelectorAll(
            'button[data-project-card="true"]'
          )).includes(collapsed);
          if (stillMaterialized && this._isCollapsedProject(collapsed)) {
            unresolvedProjectKeys.add(projectKey);
          } else {
            unresolvedProjectKeys.delete(projectKey);
          }
        }
        const visibleProjectStates = new Map();
        for (const button of document.querySelectorAll(
          'button[data-project-card="true"]'
        )) {
          const key = this._projectAttemptKey(button);
          visibleProjectStates.set(
            key,
            Boolean(visibleProjectStates.get(key))
              || this._isCollapsedProject(button)
          );
        }
        for (const [key, isCollapsed] of visibleProjectStates) {
          if (isCollapsed) unresolvedProjectKeys.add(key);
          else unresolvedProjectKeys.delete(key);
        }
        collect();
      };

      if (!sidebar) {
        let quietPasses = 0;
        while (withinLimits() && quietPasses < 2) {
          const beforeChats = chatById.size;
          const beforeExpansions = expansions;
          await expandCurrentViewport();
          if (beforeChats === chatById.size && beforeExpansions === expansions) {
            quietPasses += 1;
            if (quietPasses < 2) await this._waitForSidebarRender();
          } else {
            quietPasses = 0;
          }
        }
        complete = false;
        limitReached = true;
        return {
          complete,
          expansions,
          sidebar_available: false,
          stalled_projects: unresolvedProjectKeys.size,
          limit_reached: limitReached
        };
      }

      const originalScrollTop = Number(sidebar.scrollTop || 0);
      const moveTo = async position => {
        const maxScroll = Math.max(
          0,
          Number(sidebar.scrollHeight || 0) - Number(sidebar.clientHeight || 0)
        );
        sidebar.scrollTop = Math.max(0, Math.min(Number(position || 0), maxScroll));
        sidebar.dispatchEvent(new Event('scroll', { bubbles: true }));
        await this._waitForSidebarRender();
      };

      try {
        for (let pass = 0; pass < maxPasses && withinLimits(); pass += 1) {
          const beforeChats = chatById.size;
          const beforeExpansions = expansions;
          let reachedBottom = false;
          await moveTo(0);

          for (
            let positionIndex = 0;
            positionIndex < maxPositionsPerPass && withinLimits();
            positionIndex += 1
          ) {
            await expandCurrentViewport();
            const clientHeight = Math.max(0, Number(sidebar.clientHeight || 0));
            const maxScroll = Math.max(
              0,
              Number(sidebar.scrollHeight || 0) - clientHeight
            );
            const current = Math.max(0, Number(sidebar.scrollTop || 0));
            if (current >= maxScroll - 1) {
              reachedBottom = true;
              break;
            }
            const step = Math.max(120, clientHeight * 0.75);
            await moveTo(Math.min(maxScroll, current + step));
          }

          if (!reachedBottom) {
            limitReached = true;
            break;
          }
          if (beforeChats === chatById.size && beforeExpansions === expansions) {
            complete = unresolvedProjectKeys.size === 0;
            if (!complete) limitReached = true;
            break;
          }
        }
        if (!complete) limitReached = true;
      } finally {
        const maxScroll = Math.max(
          0,
          Number(sidebar.scrollHeight || 0) - Number(sidebar.clientHeight || 0)
        );
        sidebar.scrollTop = Math.max(0, Math.min(originalScrollTop, maxScroll));
        sidebar.dispatchEvent(new Event('scroll', { bubbles: true }));
        await this._waitForSidebarRender();
      }

      return {
        complete,
        expansions,
        sidebar_available: true,
        stalled_projects: unresolvedProjectKeys.size,
        limit_reached: limitReached
      };
    },

    async getChatList() {
      const activeChatId = String(
        (location.href.match(/\/c\/([a-f0-9\-]{36})/) || [])[1] || ''
      ).toLowerCase() || null;
      const chatById = new Map();
      const scan = await this._materializeSidebarChats(chatById, activeChatId);
      this._collectVisibleSidebarChats(
        chatById,
        activeChatId,
        !scan.sidebar_available
      );
      const chats = Array.from(chatById.values()).map(chat => {
        const publicChat = { ...chat };
        delete publicChat._title_priority;
        return publicChat;
      });
      return {
        chats,
        active_id: activeChatId,
        count: chats.length,
        complete: scan.complete,
        project_expansions: scan.expansions,
        sidebar_available: scan.sidebar_available,
        stalled_projects: scan.stalled_projects,
        limit_reached: scan.limit_reached
      };
    },

    async _activateActiveConversationMenuAction(chatId, acceptedLabels) {
      const activeChatId = (
        location.href.match(/\/c\/([a-f0-9\-]{36})/) || []
      )[1] || null;
      if (activeChatId !== chatId) return false;

      const normalizedLabels = new Set(
        acceptedLabels.map(label => String(label || '').trim().toLowerCase())
      );
      const findActions = () => Array.from(
        document.querySelectorAll('[role="menuitem"]')
      ).filter(element => {
        if (!this._isActionableElement(element)) return false;
        const labels = [
          element.getAttribute('aria-label'),
          element.getAttribute('title'),
          element.innerText,
          element.textContent
        ].map(value => String(value || '').trim().toLowerCase())
          .filter(Boolean);
        return labels.some(label => normalizedLabels.has(label));
      });

      const titlebarMenu = document.querySelector(
        '[data-testid="titlebar-more-actions"]'
      );
      if (!this._isActionableElement(titlebarMenu)) return false;

      const controlledMenuIds = new Set(
        [
          titlebarMenu.getAttribute('aria-controls'),
          titlebarMenu.getAttribute('aria-owns')
        ].flatMap(value => String(value || '').trim().split(/\s+/))
          .filter(Boolean)
      );
      const controlledActions = actions => actions.filter(element => {
        let current = element;
        while (current) {
          const id = current.getAttribute && current.getAttribute('id');
          if (id && controlledMenuIds.has(id)) return true;
          current = current.parentElement;
        }
        return false;
      });

      const initialActions = findActions();
      const initialControlledActions = controlledActions(initialActions);
      if (initialControlledActions.length === 1) {
        initialControlledActions[0].click();
        return true;
      }

      const preexistingActions = new Set(initialActions);
      titlebarMenu.click();

      let action = null;
      for (let attempt = 0; attempt < 50; attempt += 1) {
        const currentActions = findActions();
        const currentControlledActions = controlledActions(currentActions);
        const newlyAvailableActions = currentActions.filter(
          element => !preexistingActions.has(element)
        );
        if (currentControlledActions.length === 1) {
          action = currentControlledActions[0];
          break;
        }
        if (newlyAvailableActions.length === 1) {
          action = newlyAvailableActions[0];
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (!action) return false;
      action.click();
      return true;
    },

    async archiveChat(chatId) {
      if (await this._activateActiveConversationMenuAction(
        chatId,
        ['archive', 'archiv', 'archivieren']
      )) {
        return {
          success: true,
          chat_id: chatId,
          archived: true,
          method: 'active-titlebar-menu'
        };
      }

      let row = null;
      let pill = null;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        row = document.querySelector(
          '[data-testid="conversation-row-sidebar"]'
          + '[data-cascade-id="' + chatId + '"]'
        );
        if (row) break;
        pill = document.querySelector(
          '[data-testid="convo-pill-' + chatId + '"]'
        );
        row = pill && pill.closest('[role="button"]');
        if (row) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (!row) {
        return {
          success: false,
          chat_id: chatId,
          error: 'The conversation is not visible in the Antigravity sidebar.'
        };
      }

      const archiveButton = row.querySelector(
        '[data-testid="conversation-archive-button"]'
      ) || Array.from(row.querySelectorAll('button')).find(button => {
        const label = [
          button.getAttribute('aria-label'),
          button.getAttribute('title'),
          button.textContent
        ].filter(Boolean).join(' ').trim().toLowerCase();
        if (label.includes('archive') || label.includes('archiv')) return true;
        return Array.from(button.querySelectorAll('path')).some(path => {
          const data = path.getAttribute('d') || '';
          return data.includes('M480-256.16L626.15-402.31')
            && data.includes('M200-643.85');
        });
      });
      if (!this._isActionableElement(archiveButton)) {
        return {
          success: false,
          chat_id: chatId,
          error: 'The native Archive button was not found.'
        };
      }

      archiveButton.click();
      return {
        success: true,
        chat_id: chatId,
        archived: true,
        method: pill ? 'legacy-sidebar-pill' : 'sidebar-row'
      };
    },

    async restoreChat(chatId) {
      const activeChatId = (
        location.href.match(/\/c\/([a-f0-9\-]{36})/) || []
      )[1] || null;
      if (activeChatId !== chatId) {
        return {
          success: false,
          chat_id: chatId,
          error: 'The archived conversation is not active in this window.'
        };
      }

      if (await this._activateActiveConversationMenuAction(
        chatId,
        ['restore', 'wiederherstellen']
      )) {
        return {
          success: true,
          chat_id: chatId,
          archived: false,
          method: 'active-titlebar-menu'
        };
      }

      const restoreButton = Array.from(document.querySelectorAll('button')).find(button => {
        if (!this._isActionableElement(button)) return false;
        const label = (button.textContent || '').trim().toLowerCase();
        return label === 'restore' || label === 'wiederherstellen';
      });
      if (!restoreButton) {
        return {
          success: false,
          chat_id: chatId,
          error: 'The native Restore button was not found.'
        };
      }

      restoreButton.click();
      return {
        success: true,
        chat_id: chatId,
        archived: false,
        method: 'legacy-restore-button'
      };
    },

    // =========================================================
    // NEW: Get Active Chat Metadata
    // =========================================================

    getActiveChatMeta() {
      const activeChatId = (location.href.match(/\/c\/([a-f0-9\-]{36})/) || [])[1] || null;

      // Model detection
      const modelBtn = document.querySelector('[aria-label^="Select model"]');
      let model = null;
      if (modelBtn) {
        model = (modelBtn.getAttribute('aria-label') || '').replace('Select model, current: ', '').trim();
      }

      // Is the AI currently generating?
      const stopBtn = document.querySelector('button[aria-label="Stop generating"]') ||
                      document.querySelector('button[aria-label*="Stop"]');
      const lastResponse = Array.from(document.querySelectorAll('[role="article"][aria-label="Agent response"]')).at(-1);
      const native = lastResponse ? this._nativeResponseState(lastResponse) : null;
      const isRunning = native?.observed ? native.running : !!stopBtn && stopBtn.offsetParent !== null;

      // Message count
      const msgCount = document.querySelectorAll('[role="article"]').length;

      // Title
      let title = document.title || '';
      if (title.includes(' - ')) title = title.split(' - ')[0].trim();

      // Last activity: check if there's a streaming element
      const streamingEl = document.querySelector('.animate-pulse, [data-streaming="true"]');
      const isStreaming = native?.observed ? native.running : !!streamingEl || isRunning;

      return {
        chat_id: activeChatId,
        title: title,
        model: model,
        message_count: msgCount,
        is_running: isRunning,
        is_streaming: isStreaming,
        requires_user_input: !!native?.requiresUserInput,
        url: location.href
      };
    },

    // =========================================================
    // NEW: Poll New Tokens (incremental, for SSE streaming)
    // =========================================================

    pollNewTokens(lastIndex, lastLen) {
      const articles = Array.from(document.querySelectorAll('[role="article"]'));
      const currentCount = articles.length;

      // No new messages yet
      if (currentCount <= lastIndex) {
        const stopBtn = document.querySelector('button[aria-label="Stop generating"]') ||
                        document.querySelector('button[aria-label*="Stop"]');
        return {
          has_new: false,
          is_running: !!(stopBtn && stopBtn.offsetParent !== null),
          message_index: lastIndex,
          current_len: lastLen,
          delta: '',
          type: 'text',
          finished: false
        };
      }

      const lastArticle = articles[currentCount - 1];
      const clone = lastArticle.cloneNode(true);
      clone.querySelectorAll('style, script, button, .hidden').forEach(e => e.remove());
      clone.querySelectorAll('.text-muted-foreground, .text-xs').forEach(e => {
        if (/^\d{2}:\d{2}$/.test(e.textContent.trim())) e.remove();
      });
      const fullText = clone.textContent.trim();
      const currentLen = fullText.length;

      // Detect type
      const msgType = this.detectMessageType(lastArticle);

      // Is finished?
      const hasFeedback = lastArticle.querySelector('button[aria-label="Good response"]') ||
                          lastArticle.querySelector('button[aria-label="Bad response"]') ||
                          lastArticle.querySelector('[aria-label="Undo changes up to this point"]');
      const stopBtn = document.querySelector('button[aria-label="Stop generating"]') ||
                      document.querySelector('button[aria-label*="Stop"]');
      const isRunning = !!(stopBtn && stopBtn.offsetParent !== null);
      const finished = !!hasFeedback && !isRunning;

      // New article appeared
      if (currentCount > lastIndex) {
        const delta = currentLen > lastLen ? fullText.substring(lastLen) : '';
        return {
          has_new: true,
          is_running: isRunning,
          message_index: currentCount - 1,
          current_len: currentLen,
          delta: delta,
          type: msgType,
          finished: finished
        };
      }

      // Same article, more tokens
      if (currentLen > lastLen) {
        return {
          has_new: true,
          is_running: isRunning,
          message_index: lastIndex,
          current_len: currentLen,
          delta: fullText.substring(lastLen),
          type: msgType,
          finished: finished
        };
      }

      return {
        has_new: false,
        is_running: isRunning,
        message_index: lastIndex,
        current_len: lastLen,
        delta: '',
        type: msgType,
        finished: finished
      };
    },

    // =========================================================
    // NEW: Navigate to a specific chat by ID
    // =========================================================

    async navigateToChat(chatId, section) {
      this.log('navigateToChat: ' + chatId);
      // Find the link in the sidebar
      const link = document.querySelector('a[href*="/c/' + chatId + '"]');
      if (link) {
        link.click();
        await new Promise(r => setTimeout(r, 800));
        const newId = (location.href.match(/\/c\/([a-f0-9\-]{36})/) || [])[1] || null;
        return { success: newId === chatId, chat_id: newId, url: location.href };
      }
      // Fallback: direct navigation
      const currentUrl = location.href;
      const targetUrl = new URL(currentUrl);
      targetUrl.pathname = '/c/' + encodeURIComponent(chatId);
      targetUrl.search = '';
      targetUrl.hash = '';
      if (section) targetUrl.searchParams.set('section', section);
      return {
        success: false,
        reload_required: true,
        chat_id: chatId,
        target_url: targetUrl.href,
        url: currentUrl
      };
    },

    // --- Diagnostics ---
    diagnose() {
      const input = this.findInput();
      const msgCount = this.getMessageCount();
      const lastMsg = this.getLastMessageText();
      return {
        inputFound: !!input,
        inputTag: input ? input.tagName : null,
        inputRole: input ? input.getAttribute('role') : null,
        inputAriaLabel: input ? input.getAttribute('aria-label') : null,
        messageCount: msgCount,
        lastMessagePreview: lastMsg.substring(0, 200),
        totalDivs: document.querySelectorAll('div').length,
        totalButtons: document.querySelectorAll('button').length,
        articlesCount: document.querySelectorAll('[role="article"]').length,
        url: location.href,
        title: document.title,
        debug: this._debug
      };
    },

    // --- Voice Recording (uses Antigravity's built-in mic button) ---
    _readVoiceComposerText(input) {
      if (!input) return '';
      if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
        return String(input.value || '').replace(/\u200B/g, '');
      }
      const clone = input.cloneNode(true);
      clone.querySelectorAll(
        '[class*="placeholder"], [id*="placeholder"], .placeholder, '
        + '[data-placeholder], [style*="display: none"], [style*="display:none"], '
        + '[aria-hidden="true"]'
      ).forEach(element => element.remove());
      return String(clone.textContent || '').replace(/\u200B/g, '');
    },

    _findMicButton() {
      // The mic button has aria-label="Record voice memo"
      const btn = document.querySelector('button[aria-label="Record voice memo"]');
      if (btn && btn.offsetParent !== null) return btn;
      // Fallback: look for any button with a microphone SVG near the input
      const allBtns = Array.from(document.querySelectorAll('button'));
      for (const b of allBtns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('voice') || label.includes('record') || label.includes('mic')) {
          if (b.offsetParent !== null) return b;
        }
      }
      return null;
    },

    _findStopButton() {
      const buttons = Array.from(
        document.querySelectorAll('button[aria-label="Stop recording"]')
      );
      return buttons.find(button => button.offsetParent !== null)
        || buttons[0]
        || null;
    },

    _hasVoiceIndicator(input) {
      if (this._findStopButton()) return true;
      if (!input || typeof input.querySelector !== 'function') return false;
      return Boolean(
        input.querySelector('span[style*="opacity: 0.5"]')
        || input.querySelector('span[style*="opacity:0.5"]')
        || input.querySelector('[data-lexical-decorator]')
      );
    },

    startVoiceRecording(initialText) {
      this.log('Voice: startVoiceRecording called');
      const input = this.findInput();
      if (!input) {
        this.log('Voice: Composer not found!');
        return false;
      }
      const micBtn = this._findMicButton();
      if (!micBtn) {
        this.log('Voice: Mic button not found!');
        return false;
      }

      const seedText = initialText === undefined || initialText === null
        ? this._readVoiceComposerText(input)
        : String(initialText);
      this.setInputText(input, seedText);
      const currentText = this._readVoiceComposerText(input);
      this._voiceState = {
        isRecording: true,
        text: currentText,
        preRecordingText: currentText
      };

      // Click the mic button to start recording
      micBtn.click();
      this.log('Voice: Mic button clicked, recording started');
      return true;
    },

    getVoiceState() {
      const input = this.findInput();
      const fullText = this._readVoiceComposerText(input);
      const nativeActive = this._hasVoiceIndicator(input);
      this._voiceState.isRecording = nativeActive;
      this._voiceState.text = fullText || this._voiceState.text || '';
      return {
        isRecording: nativeActive,
        text: this._voiceState.text
      };
    },

    stopVoiceRecording() {
      this.log('Voice: stopVoiceRecording called');
      const stopBtn = this._findStopButton();
      if (!stopBtn) {
        this.log('Voice: Stop recording button not found');
        return false;
      }
      stopBtn.click();
      this.log('Voice: Stop button clicked');

      const input = this.findInput();
      this._voiceState.text = this._readVoiceComposerText(input);
      this._voiceState.isRecording = false;
      this.log('Voice: Recording stopped, text: ' + this._voiceState.text.substring(0, 50));
      return true;
    },

    clearVoiceDraft() {
      const input = this.findInput();
      if (!input) return false;
      this.setInputText(input, '');
      this._voiceState = {
        isRecording: false,
        text: '',
        preRecordingText: ''
      };
      return this._readVoiceComposerText(input).trim() === '';
    }
  };

  return 'bridge_injected';
})();
