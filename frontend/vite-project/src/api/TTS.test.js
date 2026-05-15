import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import { getTTS } from './TTS.js';
import { API_BASE_URL } from '../config.js';

test('getTTS posts text to the TTS endpoint and returns blob data', async () => {
    const originalPost = axios.post;
    const calls = [];
    const blob = new Blob(['audio-bytes'], { type: 'audio/mpeg' });

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: blob };
    };

    try {
        const result = await getTTS('Hello world');

        assert.strictEqual(result, blob);
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/tts`,
                body: { text: 'Hello world' },
                config: { responseType: 'blob' },
            },
        ]);
    } finally {
        axios.post = originalPost;
    }
});
