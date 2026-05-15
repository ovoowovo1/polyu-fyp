import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import { uploadLink, uploadMultiple } from './upload.js';
import { API_BASE_URL } from '../config.js';

test('uploadMultiple posts files with client and class query params', async () => {
    const originalPost = axios.post;
    const calls = [];
    const storage = installLocalStorage({ session_token: 'upload-token' });

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { ok: true } };
    };

    try {
        await uploadMultiple([
            { originFileObj: 'wrapped-file' },
            'plain-file',
        ], 'client-1', 'class-1');

        assert.equal(calls.length, 1);
        assert.equal(
            calls[0].url,
            `${API_BASE_URL}/upload-multiple?clientId=client-1&class_id=class-1`,
        );
        assert.deepEqual(calls[0].body.getAll('files'), ['wrapped-file', 'plain-file']);
        assert.deepEqual(calls[0].config, {
            headers: {
                'Content-Type': 'multipart/form-data',
                Authorization: 'Bearer upload-token',
            },
        });
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('uploadLink posts the URL body and omits auth when no token exists', async () => {
    const originalPost = axios.post;
    const calls = [];
    const storage = installLocalStorage();

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { ok: true } };
    };

    try {
        await uploadLink('https://example.com/notes.pdf', 'client-2', 'class-2');

        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/upload-link?clientId=client-2&class_id=class-2`,
                body: { url: 'https://example.com/notes.pdf' },
                config: {},
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
