import test from 'node:test';
import assert from 'node:assert/strict';

import { formatStudioDate } from './studioCardLogic.js';

test('formatStudioDate handles empty and invalid values', () => {
    assert.equal(formatStudioDate(null), '');
    assert.equal(formatStudioDate('not-a-date'), '');
});

test('formatStudioDate formats ISO strings and numeric timestamps', () => {
    const iso = '2026-01-02T03:04:00';
    const numeric = new Date(iso).getTime();

    assert.match(formatStudioDate(iso), /^02\/01\/2026 03:04$/);
    assert.match(formatStudioDate(numeric), /^02\/01\/2026 03:04$/);
});
