import test from 'node:test';
import assert from 'node:assert/strict';

import {
    getCurrentUser,
    getRefreshToken,
    getToken,
    isAuthenticated,
    login,
    logout,
    register,
    verifyToken,
} from './auth.js';
import { clearAuthSession, storeAuthSession } from './authSession.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('login stores access token in memory and relies on HttpOnly refresh cookie', async () => {
    const storage = installLocalStorageMock();
    const user = { id: 'user-1', email: 'student@example.com' };
    const axiosMock = installAxiosMock({
        post: async () => ({
            data: {
                session_token: 'access-token-123',
                access_token: 'access-token-123',
                user,
            },
        }),
    });

    try {
        const result = await login('student@example.com', 'secret', 'student');

        assert.equal(result.session_token, 'access-token-123');
        assert.equal(getToken(), 'access-token-123');
        assert.equal(getRefreshToken(), null);
        assert.deepEqual(getCurrentUser(), user);
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/auth/login`,
                body: {
                    email: 'student@example.com',
                    password: 'secret',
                    role: 'student',
                },
                config: { withCredentials: true },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
        storage.restore();
    }
});

test('login uses backend response errors when authentication fails', async () => {
    const axiosMock = installAxiosMock({
        post: async () => {
            throw { response: { data: { detail: { error: 'Invalid credentials' } } } };
        },
    });

    try {
        await assert.rejects(
            () => login('student@example.com', 'wrong'),
            { message: 'Invalid credentials' },
        );
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('login converts request errors into a network message', async () => {
    const axiosMock = installAxiosMock({
        post: async () => {
            throw { request: {} };
        },
    });

    try {
        await assert.rejects(
            () => login('student@example.com', 'secret'),
            { message: 'Network connection failed. Please check your server connection.' },
        );
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('register posts the expected body and returns response data', async () => {
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { id: 'user-2' } }),
    });

    try {
        const result = await register('teacher@example.com', 'secret', 'Teacher One', 'teacher');

        assert.deepEqual(result, { id: 'user-2' });
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1] })), [
            {
                url: `${API_BASE_URL}/auth/register`,
                body: {
                    email: 'teacher@example.com',
                    password: 'secret',
                    full_name: 'Teacher One',
                    role: 'teacher',
                },
            },
        ]);
    } finally {
        axiosMock.restore();
    }
});

test('register uses backend error messages when registration fails', async () => {
    const axiosMock = installAxiosMock({
        post: async () => {
            throw { response: { data: { error: 'Email already exists' } } };
        },
    });

    try {
        await assert.rejects(
            () => register('student@example.com', 'secret', 'Student One'),
            { message: 'Email already exists' },
        );
    } finally {
        axiosMock.restore();
    }
});

test('verifyToken sends the in-memory access token and returns verified user data', async () => {
    storeAuthSession({ session_token: 'access-token-456', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        get: async () => ({ data: { valid: true, user: { id: 'user-1' } } }),
    });

    try {
        const result = await verifyToken();

        assert.deepEqual(result, { valid: true, user: { id: 'user-1' } });
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
            {
                url: `${API_BASE_URL}/auth/verify`,
                config: {
                    headers: {
                        Authorization: 'Bearer access-token-456',
                    },
                    withCredentials: true,
                },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('verifyToken refreshes from cookie and stores only the new access token in memory', async () => {
    const storage = installLocalStorageMock({
        session_token: 'legacy-access',
        refresh_token: 'legacy-refresh',
        user: JSON.stringify({ id: 'legacy-user' }),
    });
    storeAuthSession({ session_token: 'expired-access', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        get: async () => {
            throw { response: { data: { detail: { error: 'Token expired' } } } };
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
        const result = await verifyToken();

        assert.equal(result.session_token, 'new-access');
        assert.equal(getToken(), 'new-access');
        assert.equal(getRefreshToken(), null);
        assert.deepEqual(getCurrentUser(), { id: 'user-1', role: 'student' });
        assert.deepEqual(axiosMock.calls.filter(({ method }) => method === 'post').map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/auth/refresh`,
                body: {},
                config: { withCredentials: true },
            },
        ]);
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
    } finally {
        clearAuthSession();
        axiosMock.restore();
        storage.restore();
    }
});

test('verifyToken clears memory and legacy storage when access verification and refresh both fail', async () => {
    const storage = installLocalStorageMock({
        session_token: 'legacy-access',
        refresh_token: 'legacy-refresh',
        user: JSON.stringify({ id: 'legacy-user' }),
    });
    storeAuthSession({ session_token: 'expired-token', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        get: async () => {
            throw { response: { data: { detail: { error: 'Token expired' } } } };
        },
        post: async () => {
            throw { response: { data: { detail: { error: 'Invalid refresh token' } } } };
        },
    });

    try {
        await assert.rejects(
            () => verifyToken(),
            { message: 'Invalid refresh token' },
        );
        assert.equal(getToken(), null);
        assert.equal(getCurrentUser(), null);
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.equal(localStorage.getItem('user'), null);
    } finally {
        clearAuthSession();
        axiosMock.restore();
        storage.restore();
    }
});

test('verifyToken uses refresh cookie when access token is missing', async () => {
    clearAuthSession();
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { session_token: 'new-access', user: { id: 'user-1' } } }),
    });

    try {
        const result = await verifyToken();

        assert.equal(result.session_token, 'new-access');
        assert.equal(getToken(), 'new-access');
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/auth/refresh`,
                body: {},
                config: { withCredentials: true },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('logout clears memory and asks backend to clear the refresh cookie', () => {
    storeAuthSession({ session_token: 'token-789', user: { id: 'user-1' } });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { message: 'ok' } }),
    });

    try {
        logout();

        assert.equal(getToken(), null);
        assert.equal(getCurrentUser(), null);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/auth/logout`,
                body: {},
                config: { withCredentials: true },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('auth helpers expose memory-backed access token, user, and auth status only', () => {
    const storage = installLocalStorageMock({
        session_token: 'legacy-token',
        refresh_token: 'legacy-refresh',
        user: JSON.stringify({ id: 'legacy-user' }),
    });

    try {
        assert.equal(getToken(), null);
        assert.equal(getRefreshToken(), null);
        assert.equal(getCurrentUser(), null);
        assert.equal(isAuthenticated(), false);

        storeAuthSession({ session_token: 'token-abc', user: { id: 'user-1', role: 'student' } });

        assert.equal(getToken(), 'token-abc');
        assert.equal(getRefreshToken(), null);
        assert.deepEqual(getCurrentUser(), { id: 'user-1', role: 'student' });
        assert.equal(isAuthenticated(), true);

        clearAuthSession();

        assert.equal(getToken(), null);
        assert.equal(getCurrentUser(), null);
        assert.equal(isAuthenticated(), false);
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
    } finally {
        clearAuthSession();
        storage.restore();
    }
});
