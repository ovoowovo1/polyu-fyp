import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import {
    generateExam,
    getExamById,
    getExamList,
    getExamPdfUrl,
    publishExam,
} from './exam.js';
import { API_BASE_URL } from '../config.js';

test('generateExam posts params with authorization when a token exists', async () => {
    const originalPost = axios.post;
    const calls = [];
    const storage = installLocalStorage({ session_token: 'exam-token' });

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { id: 'exam-1' } };
    };

    try {
        const params = {
            file_ids: ['file-1'],
            topic: 'Recursion',
            difficulty: 'medium',
            num_questions: 3,
        };
        await generateExam(params);

        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/exam/generate`,
                body: params,
                config: { headers: { Authorization: 'Bearer exam-token' } },
            },
        ]);
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('getExamList and getExamById pass query params and auth header', async () => {
    const originalGet = axios.get;
    const calls = [];
    const storage = installLocalStorage({ session_token: 'exam-token' });

    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: [] };
    };

    try {
        await getExamList('class-1');
        await getExamById('exam-1', true);

        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/exam/list`,
                config: {
                    params: { class_id: 'class-1' },
                    headers: { Authorization: 'Bearer exam-token' },
                },
            },
            {
                url: `${API_BASE_URL}/exam/exam-1`,
                config: {
                    params: { include_answers: true },
                    headers: { Authorization: 'Bearer exam-token' },
                },
            },
        ]);
    } finally {
        axios.get = originalGet;
        storage.restore();
    }
});

test('publishExam posts the published state and omits auth when no token exists', async () => {
    const originalPost = axios.post;
    const calls = [];
    const storage = installLocalStorage();

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { ok: true } };
    };

    try {
        await publishExam('exam-2', false);

        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/exam/exam-2/publish`,
                body: { is_published: false },
                config: {},
            },
        ]);
    } finally {
        axios.post = originalPost;
        storage.restore();
    }
});

test('getExamPdfUrl returns the direct PDF endpoint', () => {
    assert.equal(getExamPdfUrl('exam-3'), `${API_BASE_URL}/exam/exam-3/pdf`);
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
