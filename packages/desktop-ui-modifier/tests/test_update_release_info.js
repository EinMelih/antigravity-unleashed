const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sourcePath = path.resolve(__dirname, '../src/ui/updateReleaseInfo.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const context = { URL };
vm.createContext(context);
vm.runInContext(
    source + '\n;globalThis.__releaseInfoTestAPI = {' +
    'normalizeUpdateVersion, normalizeReleaseNotes, extractReleaseHighlights, ' +
    'buildOfficialReleaseUrl, isAllowedOfficialAntigravityUrl, resolveOfficialReleaseInfo' +
    '};',
    context,
    { filename: sourcePath },
);

const api = context.__releaseInfoTestAPI;

assert.strictEqual(api.normalizeUpdateVersion(' v2.9.1 '), '2.9.1');
assert.strictEqual(api.normalizeUpdateVersion('<img>'), 'img');

const stringNotes = api.normalizeReleaseNotes('<h3>Neu</h3><ul><li>Remote Control</li><li>Faster startup</li></ul>');
assert.ok(stringNotes.includes('Remote Control'));
assert.ok(!stringNotes.includes('<li>'));

const arrayNotes = api.normalizeReleaseNotes([
    { version: '2.9.1', note: 'First improvement' },
    { version: '2.9.0', note: '<script>alert(1)</script>Second fix' },
]);
assert.ok(arrayNotes.includes('First improvement'));
assert.ok(arrayNotes.includes('Second fix'));
assert.ok(!arrayNotes.includes('<script>'));

const official = api.resolveOfficialReleaseInfo('2.9.1', null);
assert.strictEqual(official.detailsStatus, 'official-fallback');
assert.strictEqual(official.publishedAt, '20. August 2026');
assert.strictEqual(official.improvements, 11);
assert.strictEqual(official.fixes, 15);
assert.strictEqual(official.highlights.length, 5);
assert.ok(official.highlights[0].includes('Remote Control'));

const feed = api.resolveOfficialReleaseInfo('2.9.1', '- Official first change\n- Official second change');
assert.strictEqual(feed.detailsStatus, 'feed');
assert.deepStrictEqual(Array.from(feed.highlights), ['Official first change', 'Official second change']);

const unknown = api.resolveOfficialReleaseInfo('9.9.9', null);
assert.strictEqual(unknown.detailsStatus, 'unavailable');
assert.strictEqual(unknown.highlights.length, 0);

const metadata = api.resolveOfficialReleaseInfo('9.9.9', null, {
    releaseName: '<b>Official release title</b>\nwith details',
    releaseDate: '2026-08-20T12:00:00.000Z',
});
assert.strictEqual(metadata.title, 'Official release title with details');
assert.strictEqual(metadata.publishedAt, '20. August 2026');
assert.ok(!metadata.title.includes('<b>'));

assert.strictEqual(api.isAllowedOfficialAntigravityUrl('https://www.antigravity.google/changelog'), true);
assert.strictEqual(api.isAllowedOfficialAntigravityUrl('https://antigravity.google/releases?version=2.9.1'), true);
assert.strictEqual(api.isAllowedOfficialAntigravityUrl('http://antigravity.google/changelog'), false);
assert.strictEqual(api.isAllowedOfficialAntigravityUrl('https://antigravity.google.evil.example/changelog'), false);
assert.strictEqual(api.isAllowedOfficialAntigravityUrl('javascript:alert(1)'), false);

console.log('updateReleaseInfo tests passed');
