import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import {
    createClass,
    inviteStudent,
    listMyClasses,
    listMyEnrolledClasses,
} from './classes.js';
import { API_BASE_URL } from '../config.js';
import i18n from '../i18n/config.js';

test('class APIs reject with the localized not-logged-in message when no token exists', async () => {
    const storage = installLocalStorage();
    await i18n.changeLanguage('en');
    const expected = i18n.t('auth.notLoggedIn');

    try {
        await assert.rejects(() => listMyClasses(), { message: expected });
        await assert.rejects(() => listMyEnrolledClasses(), { message: expected });
        await assert.rejects(() => createClass('COMP 101'), { message: expected });
        await assert.rejects(() => inviteStudent('class-1', 'student@example.com'), { message: expected });
    } finally {
        storage.restore();
    }
});

test('list class APIs use Authorization and return response data', async () => {
    const originalGet = axios.get;
    const storage = installLocalStorage({ session_token: 'class-token' });
    const calls = [];

    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: [{ id: 'class-1' }] };
    };

    try {
        const owned = await listMyClasses();
        const enrolled = await listMyEnrolledClasses();

        assert.deepEqual(owned, [{ id: 'class-1' }]);
        assert.deepEqual(enrolled, [{ id: 'class-1' }]);
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/classes/mine`,
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
            {
                url: `${API_BASE_URL}/classes/enrolled`,
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
        ]);
    } finally {
        axios.get = originalGet;
        storage.restore();
    }
});

test('createClass posts the class name with Authorization', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage({ session_token: 'class-token' });
    const calls = [];

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { id: 'class-2', name: 'COMP 101' } };
    };

    try {
        const result = await createClass('COMP 101');

        assert.deepEqual(result, { id: 'class-2', name: 'COMP 101' });
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/classes/`,
                body: { name: 'COMP 101' },
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
        ]);
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('inviteStudent posts the invited email with Authorization', async () => {
    const originalPost = axios.post;
    const storage = installLocalStorage({ session_token: 'class-token' });
    const calls = [];

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { invited: true } };
    };

    try {
        const result = await inviteStudent('class-3', 'student@example.com');

        assert.deepEqual(result, { invited: true });
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/classes/class-3/invite`,
                body: { email: 'student@example.com' },
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
        ]);
    } finally {
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
