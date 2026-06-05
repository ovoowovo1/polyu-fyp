import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import { apiGet, apiPost } from './apiClient.js';
import { API_BASE_URL } from '../config.js';

test('api client refreshes once and retries the original request with the new access token', async () => {
    const originalGet = axios.get;
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'expired-access',
        refresh_token: 'refresh-123',
        user: JSON.stringify({ id: 'user-1' }),
    });
    const calls = [];

    axios.get = async (url, config) => {
        calls.push({ method: 'get', url, config });
        if (calls.filter((call) => call.method === 'get').length === 1) {
            throw { response: { status: 401, data: { detail: { error: 'Token expired' } } } };
        }
        return { data: { ok: true } };
    };
    axios.post = async (url, body) => {
        calls.push({ method: 'post', url, body });
        return {
            data: {
                session_token: 'new-access',
                access_token: 'new-access',
                refresh_token: 'new-refresh',
                user: { id: 'user-1', role: 'student' },
            },
        };
    };

    try {
        const result = await apiGet('/classes/mine');

        assert.deepEqual(result.data, { ok: true });
        assert.deepEqual(calls, [
            {
                method: 'get',
                url: `${API_BASE_URL}/classes/mine`,
                config: { headers: { Authorization: 'Bearer expired-access' } },
            },
            {
                method: 'post',
                url: `${API_BASE_URL}/auth/refresh`,
                body: { refresh_token: 'refresh-123' },
            },
            {
                method: 'get',
                url: `${API_BASE_URL}/classes/mine`,
                config: { headers: { Authorization: 'Bearer new-access' } },
            },
        ]);
        assert.equal(localStorage.getItem('session_token'), 'new-access');
        assert.equal(localStorage.getItem('refresh_token'), 'new-refresh');
    } finally {
        axios.get = originalGet;
        axios.post = originalPost;
        storage.restore();
    }
});

test('api client clears auth storage when refresh fails', async () => {
    const originalGet = axios.get;
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'expired-access',
        refresh_token: 'bad-refresh',
        user: JSON.stringify({ id: 'user-1' }),
    });

    axios.get = async () => {
        throw { response: { status: 401, data: { detail: { error: 'Token expired' } } } };
    };
    axios.post = async () => {
        throw { response: { status: 401, data: { detail: { error: 'Invalid refresh token' } } } };
    };

    try {
        await assert.rejects(() => apiPost('/quiz/quiz-1/submit', { answers: [] }));
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.equal(localStorage.getItem('user'), null);
    } finally {
        axios.get = originalGet;
        axios.post = originalPost;
        storage.restore();
    }
});

test('api client shares one refresh request across concurrent 401 responses', async () => {
    const originalGet = axios.get;
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'expired-access',
        refresh_token: 'refresh-123',
    });
    let refreshCalls = 0;

    axios.get = async (url, config) => {
        if (config.headers?.Authorization === 'Bearer expired-access') {
            throw { response: { status: 401, data: {} } };
        }
        return { data: { url } };
    };
    axios.post = async () => {
        refreshCalls += 1;
        await Promise.resolve();
        return {
            data: {
                session_token: 'new-access',
                access_token: 'new-access',
                refresh_token: 'new-refresh',
            },
        };
    };

    try {
        await Promise.all([
            apiGet('/exam/list'),
            apiGet('/quiz/list'),
        ]);

        assert.equal(refreshCalls, 1);
    } finally {
        axios.get = originalGet;
        axios.post = originalPost;
        storage.restore();
    }
});

function installLocalStorage(initialValues = {}) {
    const originalLocalStorage = global.localStorage;
    const map = new Map(Object.entries(initialValues));

    global.localStorage = {
        getItem(key) {
            return map.has(key) ? map.get(key) : null;
        },
        setItem(key, value) {
            map.set(key, String(value));
        },
        removeItem(key) {
            map.delete(key);
        },
    };

    return {
        restore() {
            if (originalLocalStorage === undefined) {
                delete global.localStorage;
            } else {
                global.localStorage = originalLocalStorage;
            }
        },
    };
}
