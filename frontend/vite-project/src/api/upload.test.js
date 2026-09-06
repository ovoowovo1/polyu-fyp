import test from 'node:test';
import assert from 'node:assert/strict';

import { uploadLink, uploadMultiple, reingestPdf } from './upload.js';
import { clearAuthSession, storeAuthSession } from './authSession.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('reingestPdf posts the original PDF and preserves backend failure reasons', async () => {
    storeAuthSession({ session_token: 'upload-token' });
    const mock = installAxiosMock({ post: async () => ({ data: { status: 'success', chunksCount: 4 } }) });
    try {
        const result = await reingestPdf('file-1', 'original-pdf', 'client');
        const call = mock.calls[0];
        assert.equal(call.args[0], `${API_BASE_URL}/api/files/file-1/reingest?clientId=client`);
        assert.deepEqual(call.args[1].getAll('file'), ['original-pdf']);
        assert.equal(call.args[2].headers.Authorization, 'Bearer upload-token');
        assert.equal(result.data.chunksCount, 4);
    } finally { mock.restore(); clearAuthSession(); }
    const failure = new Error('Original PDF hash does not match.');
    const failing = installAxiosMock({ post: async () => { throw failure; } });
    try { await assert.rejects(reingestPdf('file-1', 'wrong', 'client'), /hash/); }
    finally { failing.restore(); }
});

test('uploadMultiple posts files with client and class query params', async () => {
    storeAuthSession({ session_token: 'upload-token' });
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
        clearAuthSession();
        axiosMock.restore();
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
