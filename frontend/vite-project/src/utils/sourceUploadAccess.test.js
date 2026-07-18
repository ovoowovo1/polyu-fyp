import assert from 'node:assert/strict';
import test from 'node:test';

import { canUploadSources } from './sourceUploadAccess.js';

test('only teachers can access source upload controls', () => {
    assert.equal(canUploadSources({ role: 'teacher' }), true);
    assert.equal(canUploadSources({ role: 'student' }), false);
    assert.equal(canUploadSources(null), false);
});
