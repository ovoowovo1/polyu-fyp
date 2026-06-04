import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

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
import { API_BASE_URL } from '../config.js';

test('login stores access token, refresh token, and user when authentication succeeds', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage();
    const calls = [];
    const user = { id: 'user-1', email: 'student@example.com' };

    axios.post = async (url, body) => {
        calls.push({ url, body });
        return {
            data: {
                session_token: 'access-token-123',
                access_token: 'access-token-123',
                refresh_token: 'refresh-token-123',
                user,
            },
        };
    };

    try {
        const result = await login('student@example.com', 'secret', 'student');

        assert.equal(result.session_token, 'access-token-123');
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/auth/login`,
                body: {
                    email: 'student@example.com',
                    password: 'secret',
                    role: 'student',
                },
            },
        ]);
        assert.equal(localStorage.getItem('session_token'), 'access-token-123');
        assert.equal(localStorage.getItem('refresh_token'), 'refresh-token-123');
        assert.equal(localStorage.getItem('user'), JSON.stringify(user));
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('login uses backend response errors when authentication fails', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage();

    axios.post = async () => {
        throw { response: { data: { detail: { error: 'Invalid credentials' } } } };
    };

    try {
        await assert.rejects(
            () => login('student@example.com', 'wrong'),
            { message: 'Invalid credentials' },
        );
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('login converts request errors into a network message', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage();

    axios.post = async () => {
        throw { request: {} };
    };

    try {
        await assert.rejects(
            () => login('student@example.com', 'secret'),
            { message: 'Network connection failed. Please check your server connection.' },
        );
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('register posts the expected body and returns response data', async () => {
    const originalPost = axios.post;
    const calls = [];

    axios.post = async (url, body) => {
        calls.push({ url, body });
        return { data: { id: 'user-2' } };
    };

    try {
        const result = await register('teacher@example.com', 'secret', 'Teacher One', 'teacher');

        assert.deepEqual(result, { id: 'user-2' });
        assert.deepEqual(calls, [
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
        axios.post = originalPost;
    }
});

test('register uses backend error messages when registration fails', async () => {
    const originalPost = axios.post;

    axios.post = async () => {
        throw { response: { data: { error: 'Email already exists' } } };
    };

    try {
        await assert.rejects(
            () => register('student@example.com', 'secret', 'Student One'),
            { message: 'Email already exists' },
        );
    } finally {
        axios.post = originalPost;
    }
});

test('verifyToken sends the stored access token and returns verified user data', async () => {
    const originalGet = axios.get;
    const storage = installLocalStorage({
        session_token: 'access-token-456',
        refresh_token: 'refresh-token-456',
        user: JSON.stringify({ id: 'user-1' }),
    });
    const calls = [];

    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: { valid: true, user: { id: 'user-1' } } };
    };

    try {
        const result = await verifyToken();

        assert.deepEqual(result, { valid: true, user: { id: 'user-1' } });
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/auth/verify`,
                config: {
                    headers: {
                        Authorization: 'Bearer access-token-456',
                    },
                },
            },
        ]);
    } finally {
        axios.get = originalGet;
        storage.restore();
    }
});

test('verifyToken refreshes and stores new tokens when access token verification fails', async () => {
    const originalGet = axios.get;
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'expired-access',
        refresh_token: 'refresh-token-456',
        user: JSON.stringify({ id: 'user-1' }),
    });
    const postCalls = [];

    axios.get = async () => {
        throw { response: { data: { detail: { error: 'Token expired' } } } };
    };
    axios.post = async (url, body) => {
        postCalls.push({ url, body });
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
        const result = await verifyToken();

        assert.equal(result.session_token, 'new-access');
        assert.deepEqual(postCalls, [
            {
                url: `${API_BASE_URL}/auth/refresh`,
                body: { refresh_token: 'refresh-token-456' },
            },
        ]);
        assert.equal(localStorage.getItem('session_token'), 'new-access');
        assert.equal(localStorage.getItem('refresh_token'), 'new-refresh');
        assert.equal(localStorage.getItem('user'), JSON.stringify({ id: 'user-1', role: 'student' }));
    } finally {
        axios.get = originalGet;
        axios.post = originalPost;
        storage.restore();
    }
});

test('verifyToken logs out when access verification and refresh both fail', async () => {
    const originalGet = axios.get;
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'expired-token',
        refresh_token: 'bad-refresh',
        user: JSON.stringify({ id: 'user-1' }),
    });
    const postCalls = [];

    axios.get = async () => {
        throw { response: { data: { detail: { error: 'Token expired' } } } };
    };
    axios.post = async (url, body) => {
        postCalls.push({ url, body });
        throw { response: { data: { detail: { error: 'Invalid refresh token' } } } };
    };

    try {
        await assert.rejects(
            () => verifyToken(),
            { message: 'Invalid refresh token' },
        );
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.equal(localStorage.getItem('user'), null);
        assert.deepEqual(postCalls[0], {
            url: `${API_BASE_URL}/auth/refresh`,
            body: { refresh_token: 'bad-refresh' },
        });
        assert.deepEqual(postCalls[1], {
            url: `${API_BASE_URL}/auth/logout`,
            body: { refresh_token: 'bad-refresh' },
        });
    } finally {
        axios.get = originalGet;
        axios.post = originalPost;
        storage.restore();
    }
});

test('verifyToken uses refresh token when access token is missing', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage({ refresh_token: 'refresh-only' });

    axios.post = async () => ({ data: { session_token: 'new-access', refresh_token: 'new-refresh' } });

    try {
        const result = await verifyToken();

        assert.equal(result.session_token, 'new-access');
        assert.equal(localStorage.getItem('session_token'), 'new-access');
        assert.equal(localStorage.getItem('refresh_token'), 'new-refresh');
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('logout clears stored authentication data and revokes refresh token', () => {
    const originalPost = axios.post;
    const storage = installLocalStorage({
        session_token: 'token-789',
        refresh_token: 'refresh-789',
        user: JSON.stringify({ id: 'user-1' }),
    });
    const calls = [];

    axios.post = async (url, body) => {
        calls.push({ url, body });
        return { data: { message: 'ok' } };
    };

    try {
        logout();

        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('refresh_token'), null);
        assert.equal(localStorage.getItem('user'), null);
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/auth/logout`,
                body: { refresh_token: 'refresh-789' },
            },
        ]);
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('auth localStorage helpers expose tokens, user, and auth status', () => {
    const storage = installLocalStorage({
        session_token: 'token-abc',
        refresh_token: 'refresh-abc',
        user: JSON.stringify({ id: 'user-1', role: 'student' }),
    });

    try {
        assert.equal(getToken(), 'token-abc');
        assert.equal(getRefreshToken(), 'refresh-abc');
        assert.deepEqual(getCurrentUser(), { id: 'user-1', role: 'student' });
        assert.equal(isAuthenticated(), true);

        localStorage.removeItem('session_token');
        assert.equal(isAuthenticated(), true);

        localStorage.removeItem('refresh_token');
        localStorage.setItem('user', '{not valid json');

        assert.equal(getToken(), null);
        assert.equal(getRefreshToken(), null);
        assert.equal(getCurrentUser(), null);
        assert.equal(isAuthenticated(), false);
    } finally {
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
