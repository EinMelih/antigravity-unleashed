    // Minimal native bridge for operating the local Anti-Gravity Hub.
    // Model providers and chat routing intentionally stay inside the Hub.
    async function amsHubCall(operation, payload = {}) {
        if (!window.electronNative || typeof window.electronNative.hubRequest !== 'function') {
            throw new Error('Anti-Gravity Hub bridge is not installed. Please run the repack once.');
        }
        return window.electronNative.hubRequest(amsToken, operation, payload);
    }

    window.amsAntigravityHub = Object.freeze({
        getStatus: () => amsHubCall('services:status'),
        getApiStatus: () => amsHubCall('api:monitor'),
        startServices: (restart = false) => amsHubCall('services:start', { restart: restart === true }),
        openHub: () => {
            if (!window.electronNative || typeof window.electronNative.openExternal !== 'function') {
                throw new Error('External link bridge is unavailable.');
            }
            return window.electronNative.openExternal('http://127.0.0.1:8000/dashboard/');
        },
    });
