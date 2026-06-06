import test from 'node:test';
import assert from 'node:assert/strict';

import {
    createClass,
    inviteStudent,
    listMyClasses,
    listMyEnrolledClasses,
} from './classes.js';
import { clearAuthSession, storeAuthSession } from './authSession.js';
import { API_BASE_URL } from '../config.js';
import i18n from '../i18n/config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('class APIs reject with the localized not-logged-in message when no token exists', async () => {
    const storage = installLocalStorageMock();
    clearAuthSession();
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
    storeAuthSession({ session_token: 'class-token' });
    const axiosMock = installAxiosMock({
        get: async () => ({ data: [{ id: 'class-1' }] }),
    });

    try {
        const owned = await listMyClasses();
        const enrolled = await listMyEnrolledClasses();

        assert.deepEqual(owned, [{ id: 'class-1' }]);
        assert.deepEqual(enrolled, [{ id: 'class-1' }]);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
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
        clearAuthSession();
        axiosMock.restore();
    }
});

test('createClass posts the class name with Authorization', async () => {
    storeAuthSession({ session_token: 'class-token' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { id: 'class-2', name: 'COMP 101' } }),
    });

    try {
        const result = await createClass('COMP 101');

        assert.deepEqual(result, { id: 'class-2', name: 'COMP 101' });
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/classes/`,
                body: { name: 'COMP 101' },
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});

test('inviteStudent posts the invited email with Authorization', async () => {
    storeAuthSession({ session_token: 'class-token' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { invited: true } }),
    });

    try {
        const result = await inviteStudent('class-3', 'student@example.com');

        assert.deepEqual(result, { invited: true });
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/classes/class-3/invite`,
                body: { email: 'student@example.com' },
                config: { headers: { Authorization: 'Bearer class-token' } },
            },
        ]);
    } finally {
        clearAuthSession();
        axiosMock.restore();
    }
});
