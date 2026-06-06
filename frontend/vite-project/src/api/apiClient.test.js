import test from 'node:test';
import assert from 'node:assert/strict';

import { apiGet, apiPost } from './apiClient.js';
import { clearAuthSession, getToken, storeAuthSession } from './authSession.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('api client refreshes once and retries the original request with the new access token', async () => {
    const storage = installLocalStorageMock({
        session_token: 'legacy-access',
        refresh_token: 'legacy-refresh',
    });
    storeAuthSession({ session_token: 'expired-access', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        get: async () => {
            const getCalls = axiosMock.calls.filter((call) => call.method === 'get');
            if (getCalls.length === 1) {
                throw { response: { status: 401, data: { detail: { error: 'Token expired' } } } };
            }
            return { data: { ok: true } };
        },
        post: async () => ({
            data: {
                session_token: 'new-access',
                access_token: 'new-access',
                user: { id: 'user-1', role: 'student' },
            },
        }),
    });

    try {
        const result = await apiGet('/classes/mine');

        assert.deepEqual(result.data, { ok: true });
        assert.deepEqual(axiosMock.calls.map(({ method, args }) => ({
            method,
            url: args[0],
            body: method === 'post' ? args[1] : undefined,
            config: method === 'post' ? args[2] : args[1],
        })), [
            {
                method: 'get',
                url: `${API_BASE_URL}/classes/mine`,
                body: undefined,
                config: { headers: { Authorization: 'Bearer expired-access' } },
            },
            {
                method: 'post',
                url: `${API_BASE_URL}/auth/refresh`,
                body: {},
                config: { withCredentials: true },
            },
            {
                method: 'get',
                url: `${API_BASE_URL}/classes/mine`,
                body: undefined,
                config: { headers: { Authorization: 'Bearer new-access' } },
            },
        ]);
        assert.equal(getToken(), 'new-access');
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
    } finally {
        clearAuthSession();
        axiosMock.restore();
        storage.restore();
    }
});

test('api client clears auth memory and legacy storage when refresh fails', async () => {
    const storage = installLocalStorageMock({
        session_token: 'legacy-access',
        refresh_token: 'legacy-refresh',
        user: JSON.stringify({ id: 'legacy-user' }),
    });
    storeAuthSession({ session_token: 'expired-access', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        post: async (url) => {
            if (url.endsWith('/auth/refresh')) {
                throw { response: { status: 401, data: { detail: { error: 'Invalid refresh token' } } } };
            }
            throw { response: { status: 401, data: { detail: { error: 'Token expired' } } } };
        },
    });

    try {
        await assert.rejects(() => apiPost('/quiz/quiz-1/submit', { answers: [] }));
        assert.equal(getToken(), null);
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.equal(localStorage.getItem('user'), null);
    } finally {
        clearAuthSession();
        axiosMock.restore();
        storage.restore();
    }
});

test('api client shares one refresh request across concurrent 401 responses', async () => {
    storeAuthSession({ session_token: 'expired-access' });
    let refreshCalls = 0;
    const axiosMock = installAxiosMock({
        get: async (url, config) => {
            if (config.headers?.Authorization === 'Bearer expired-access') {
                throw { response: { status: 401, data: {} } };
            }
            return { data: { url } };
        },
        post: async () => {
            refreshCalls += 1;
            await Promise.resolve();
            return {
                data: {
                    session_token: 'new-access',
                    access_token: 'new-access',
                },
            };
        },
    });

    try {
        await Promise.all([
            apiGet('/exam/list'),
            apiGet('/quiz/list'),
        ]);

        assert.equal(refreshCalls, 1);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});
