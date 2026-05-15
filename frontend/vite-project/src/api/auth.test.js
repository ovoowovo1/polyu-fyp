import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import {
    getCurrentUser,
    getToken,
    isAuthenticated,
    login,
    logout,
    register,
    verifyToken,
} from './auth.js';
import { API_BASE_URL } from '../config.js';

test('login stores session token and user when authentication succeeds', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage();
    const calls = [];
    const user = { id: 'user-1', email: 'student@example.com' };

    axios.post = async (url, body) => {
        calls.push({ url, body });
        return {
            data: {
                session_token: 'token-123',
                user,
            },
        };
    };

    try {
        const result = await login('student@example.com', 'secret', 'student');

        assert.deepEqual(result, {
            session_token: 'token-123',
            user,
        });
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
        assert.equal(localStorage.getItem('session_token'), 'token-123');
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
            { message: '無法連接到服務器，請檢查網絡連接' },
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

test('verifyToken sends the stored token and returns verified user data', async () => {
    const originalGet = axios.get;
    const storage = installLocalStorage({
        session_token: 'token-456',
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
                        Authorization: 'Bearer token-456',
                    },
                },
            },
        ]);
    } finally {
        axios.get = originalGet;
        storage.restore();
    }
});

test('verifyToken logs out and exposes backend errors when verification fails', async () => {
    const originalGet = axios.get;
    const storage = installLocalStorage({
        session_token: 'expired-token',
        user: JSON.stringify({ id: 'user-1' }),
    });

    axios.get = async () => {
        throw { response: { data: { detail: { error: 'Token expired' } } } };
    };

    try {
        await assert.rejects(
            () => verifyToken(),
            { message: 'Token expired' },
        );
        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('user'), null);
    } finally {
        axios.get = originalGet;
        storage.restore();
    }
});

test('logout clears stored authentication data', () => {
    const storage = installLocalStorage({
        session_token: 'token-789',
        user: JSON.stringify({ id: 'user-1' }),
    });

    try {
        logout();

        assert.equal(localStorage.getItem('session_token'), null);
        assert.equal(localStorage.getItem('user'), null);
    } finally {
        storage.restore();
    }
});

test('auth localStorage helpers expose token, user, and auth status', () => {
    const storage = installLocalStorage({
        session_token: 'token-abc',
        user: JSON.stringify({ id: 'user-1', role: 'student' }),
    });

    try {
        assert.equal(getToken(), 'token-abc');
        assert.deepEqual(getCurrentUser(), { id: 'user-1', role: 'student' });
        assert.equal(isAuthenticated(), true);

        localStorage.removeItem('session_token');
        localStorage.setItem('user', '{not valid json');

        assert.equal(getToken(), null);
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
