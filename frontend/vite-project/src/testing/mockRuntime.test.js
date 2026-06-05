import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import { installAxiosMock, installLocalStorageMock } from './mockRuntime.js';

test('installAxiosMock captures calls and restores original axios methods', async () => {
    const originalGet = axios.get;
    const axiosMock = installAxiosMock({
        get: async (url, config) => ({ data: { url, config } }),
    });

    try {
        const result = await axios.get('/path', { headers: { A: 'B' } });

        assert.deepEqual(result.data, { url: '/path', config: { headers: { A: 'B' } } });
        assert.equal(axiosMock.calls.length, 1);
        assert.equal(axiosMock.calls[0].method, 'get');
        assert.deepEqual(axiosMock.calls[0].args, ['/path', { headers: { A: 'B' } }]);
    } finally {
        axiosMock.restore();
    }

    assert.strictEqual(axios.get, originalGet);
});

test('installLocalStorageMock stores values and restores the previous global', () => {
    const originalLocalStorage = global.localStorage;
    const storage = installLocalStorageMock({ session_token: 'token-1' });

    try {
        assert.equal(localStorage.getItem('session_token'), 'token-1');
        localStorage.setItem('refresh_token', 'refresh-1');
        assert.equal(localStorage.getItem('refresh_token'), 'refresh-1');
        localStorage.removeItem('session_token');
        assert.equal(localStorage.getItem('session_token'), null);
    } finally {
        storage.restore();
    }

    assert.strictEqual(global.localStorage, originalLocalStorage);
});
