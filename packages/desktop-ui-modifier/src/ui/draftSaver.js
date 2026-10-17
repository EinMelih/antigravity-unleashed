    function saveMessageDraft() {
        try {
            const input = document.querySelector('[role="combobox"][aria-label="Message input"]');
            if (input) {
                const val = input.value !== undefined ? input.value : (input.innerText || '');
                if (val.trim()) {
                    window.nativeStorage.updateItems({ antigravity_message_input_draft: val });
                } else {
                    window.nativeStorage.updateItems({ antigravity_message_input_draft: '' });
                }
            }
        } catch (e) {
            // ignore
        }
    }

    // Clear any leftover draft in storage on startup so we start fresh
    try {
        window.nativeStorage.updateItems({ antigravity_message_input_draft: '' });
    } catch (e) {
        // ignore
    }

    document.addEventListener('input', (e) => {
        const target = e.target;
        if (target && target.matches && target.matches('[role="combobox"][aria-label="Message input"]')) {
            saveMessageDraft();
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
