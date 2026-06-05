import test from 'node:test';
import assert from 'node:assert/strict';

import { uploadLink, uploadMultiple } from './upload.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('uploadMultiple posts files with client and class query params', async () => {
    const storage = installLocalStorageMock({ session_token: 'upload-token' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { ok: true } }),
    });

    try {
        await uploadMultiple([
            { originFileObj: 'wrapped-file' },
            'plain-file',
        ], 'client-1', 'class-1');

        const call = axiosMock.calls[0];
        assert.equal(call.args[0], `${API_BASE_URL}/upload-multiple?clientId=client-1&class_id=class-1`);
        assert.deepEqual(call.args[1].getAll('files'), ['wrapped-file', 'plain-file']);
        assert.deepEqual(call.args[2], {
            headers: {
                'Content-Type': 'multipart/form-data',
                Authorization: 'Bearer upload-token',
            },
        });
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});

test('uploadLink posts the URL body and omits auth when no token exists', async () => {
    const storage = installLocalStorageMock();
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { ok: true } }),
    });

    try {
        await uploadLink('https://example.com/notes.pdf', 'client-2', 'class-2');

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/upload-link?clientId=client-2&class_id=class-2`,
                body: { url: 'https://example.com/notes.pdf' },
                config: {},
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});
