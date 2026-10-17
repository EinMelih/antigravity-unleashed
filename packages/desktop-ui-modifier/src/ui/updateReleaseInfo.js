    const ANTIGRAVITY_CHANGELOG_URL = 'https://www.antigravity.google/changelog';
    const ANTIGRAVITY_RELEASES_URL = 'https://www.antigravity.google/releases?tab=hub';
    const MAX_RELEASE_NOTES_LENGTH = 8000;
    const MAX_RELEASE_HIGHLIGHTS = 5;

    const OFFICIAL_RELEASE_FALLBACKS = Object.freeze({
        '2.9.1': Object.freeze({
            publishedAt: '20. August 2026',
            title: 'Remote Control, schnellerer Projektwechsel und mehr',
            summary: 'Remote Control, spürbare Performance-Verbesserungen, eine übersichtlichere Navigation und robustere Fehlerbehandlung.',
            improvements: 11,
            fixes: 15,
            highlights: Object.freeze([
                'Remote Control steuert und überwacht lokale Agent-Sitzungen sicher aus jedem Browser und sendet Benachrichtigungen bei Abschluss oder Rückfragen.',
                'Schnellerer App-Start, Projektwechsel und Aufbau langer Unterhaltungen sowie weniger Verzögerungen während aktiver Sitzungen.',
                'Einklappbare Hauptbereiche, bis zu 30 ungruppierte Unterhaltungen und sofort sichtbare Aktionen verbessern die Sidebar.',
                'Die Customizations-Einstellungen für Skills, Regeln, Plugins, Custom Agents und MCP-Server wurden übersichtlicher gestaltet.',
                'Retry setzt fehlgeschlagene Agent-Aufgaben direkt fort; Custom Agents können vorhandene Customizations über inheritCustomizations übernehmen.',
                'WebP-Anhänge sowie PowerShell- und Zsh-Syntaxhervorhebung werden jetzt unterstützt.',
            ]),
        }),
    });

    function normalizeUpdateVersion(version) {
        return String(version || 'unbekannt')
            .trim()
            .replace(/^v/i, '')
            .replace(/[^0-9A-Za-z.+-]/g, '')
            .slice(0, 32) || 'unbekannt';
    }

    function normalizeReleaseNotes(releaseNotes) {
        let notesText = '';
        if (typeof releaseNotes === 'string') {
            notesText = releaseNotes;
        } else if (Array.isArray(releaseNotes)) {
            notesText = releaseNotes
                .map((entry) => {
                    if (typeof entry === 'string') return entry;
                    return entry && typeof entry.note === 'string' ? entry.note : '';
                })
                .filter(Boolean)
                .join('\n');
        }

        return notesText
            .replace(/<br\s*\/?\s*>/gi, '\n')
            .replace(/<\/(?:p|li|h[1-6])\s*>/gi, '\n')
            .replace(/<[^>]*>/g, '')
            .replace(/\r\n?/g, '\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim()
            .slice(0, MAX_RELEASE_NOTES_LENGTH);
    }

    function extractReleaseHighlights(notesText) {
        if (!notesText) return [];
        return notesText
            .split('\n')
            .map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, '').trim())
            .filter((line) => line.length >= 12)
            .slice(0, MAX_RELEASE_HIGHLIGHTS);
    }

    function buildOfficialReleaseUrl(version) {
        const normalizedVersion = normalizeUpdateVersion(version);
        if (normalizedVersion === 'unbekannt') return ANTIGRAVITY_CHANGELOG_URL;
        return ANTIGRAVITY_RELEASES_URL + '&version=' + encodeURIComponent(normalizedVersion);
    }

    function normalizeReleaseTitle(value) {
        return normalizeReleaseNotes(value)
            .replace(/\n+/g, ' ')
            .trim()
            .slice(0, 160) || null;
    }

    function normalizeReleaseDate(value) {
        if (!value) return null;
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return null;
        return new Intl.DateTimeFormat('de-DE', {
            day: 'numeric',
            month: 'long',
            year: 'numeric',
        }).format(parsed);
    }

    function isAllowedOfficialAntigravityUrl(value) {
        try {
            const url = new URL(value);
            const allowedHost = url.hostname === 'antigravity.google' || url.hostname === 'www.antigravity.google';
            const allowedPath = url.pathname === '/changelog' || url.pathname === '/releases';
            return url.protocol === 'https:' && allowedHost && allowedPath;
        } catch (_error) {
            return false;
        }
    }

    function resolveOfficialReleaseInfo(version, releaseNotes, releaseMetadata) {
        const normalizedVersion = normalizeUpdateVersion(version);
        const knownRelease = OFFICIAL_RELEASE_FALLBACKS[normalizedVersion] || null;
        const notesText = normalizeReleaseNotes(releaseNotes);
        const feedHighlights = extractReleaseHighlights(notesText);
        const fallbackHighlights = knownRelease ? Array.from(knownRelease.highlights) : [];
        const metadata = releaseMetadata && typeof releaseMetadata === 'object' ? releaseMetadata : {};
        const feedTitle = normalizeReleaseTitle(metadata.releaseName);
        const feedDate = normalizeReleaseDate(metadata.releaseDate);

        return {
            version: normalizedVersion,
            publishedAt: feedDate || (knownRelease ? knownRelease.publishedAt : null),
            title: feedTitle || (knownRelease ? knownRelease.title : null),
            summary: knownRelease ? knownRelease.summary : null,
            improvements: knownRelease ? knownRelease.improvements : null,
            fixes: knownRelease ? knownRelease.fixes : null,
            highlights: feedHighlights.length ? feedHighlights : fallbackHighlights.slice(0, MAX_RELEASE_HIGHLIGHTS),
            notesText,
            detailsStatus: notesText ? 'feed' : (knownRelease ? 'official-fallback' : 'unavailable'),
            releaseUrl: buildOfficialReleaseUrl(normalizedVersion),
            changelogUrl: ANTIGRAVITY_CHANGELOG_URL,
        };
    }
