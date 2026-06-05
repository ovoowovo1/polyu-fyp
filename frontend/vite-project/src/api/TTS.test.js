import test from 'node:test';
import assert from 'node:assert/strict';

import { getTTS } from './TTS.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock } from '../testing/mockRuntime.js';

test('getTTS posts text to the TTS endpoint and returns blob data', async () => {
    const blob = new Blob(['audio-bytes'], { type: 'audio/mpeg' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: blob }),
    });

    try {
        const result = await getTTS('Hello world');

        assert.strictEqual(result, blob);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/tts`,
                body: { text: 'Hello world' },
                config: { responseType: 'blob' },
            },
        ]);
    } finally {
        axiosMock.restore();
    }
});
