    let lastSavedDraft = (typeof nativeStorageItems === 'object' && nativeStorageItems && typeof nativeStorageItems.antigravity_message_input_draft === 'string')
        ? nativeStorageItems.antigravity_message_input_draft
        : '';
    let draftDebounceTimer = null;

    function saveMessageDraft() {
        try {
            const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
            if (input) {
                const rawVal = input.value !== undefined ? input.value : (input.innerText || '');
                const normalized = rawVal.trim() ? rawVal : '';
                if (normalized !== lastSavedDraft) {
                    lastSavedDraft = normalized;
                    window.nativeStorage.updateItems({ antigravity_message_input_draft: normalized });
                }
            }
        } catch (e) {
            // ignore
        }
    }

    // Clear any leftover draft in storage on startup only if one actually exists
    try {
        if (lastSavedDraft !== '') {
            lastSavedDraft = '';
            window.nativeStorage.updateItems({ antigravity_message_input_draft: '' });
        }
    } catch (e) {
        // ignore
    }

    document.addEventListener('input', (e) => {
        const target = e.target;
        if (target && target.matches && target.matches('[role="combobox"][aria-label="Message input"]')) {
            if (draftDebounceTimer) {
                clearTimeout(draftDebounceTimer);
            }
            draftDebounceTimer = setTimeout(() => {
                draftDebounceTimer = null;
                saveMessageDraft();
            }, 300);
        }
    });

    const draftInterval = setInterval(() => {
        saveMessageDraft();
    }, 1000);

    window.addEventListener('beforeunload', () => {
        try {
            const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
            if (input) {
                const val = input.value !== undefined ? input.value : (input.innerText || '');
                if (val.trim()) {
                    window.electronNative.writeToClipboard(val);
                }
            }
        } catch (e) {
            // ignore
        }
    });
