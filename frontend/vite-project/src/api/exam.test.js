import test from 'node:test';
import assert from 'node:assert/strict';

import {
    generateExam,
    getExamById,
    getExamList,
    getExamPdfUrl,
    publishExam,
} from './exam.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('generateExam posts params with authorization when a token exists', async () => {
    const storage = installLocalStorageMock({ session_token: 'exam-token' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { id: 'exam-1' } }),
    });

    try {
        const params = {
            file_ids: ['file-1'],
            topic: 'Recursion',
            difficulty: 'medium',
            num_questions: 3,
        };
        await generateExam(params);

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/exam/generate`,
                body: params,
                config: { headers: { Authorization: 'Bearer exam-token' } },
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});

test('getExamList and getExamById pass query params and auth header', async () => {
    const storage = installLocalStorageMock({ session_token: 'exam-token' });
    const axiosMock = installAxiosMock({
        get: async () => ({ data: [] }),
    });

    try {
        await getExamList('class-1');
        await getExamById('exam-1', true);

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
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
        axiosMock.restore();
        storage.restore();
    }
});

test('publishExam posts the published state and omits auth when no token exists', async () => {
    const storage = installLocalStorageMock();
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { ok: true } }),
    });

    try {
        await publishExam('exam-2', false);

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/exam/exam-2/publish`,
                body: { is_published: false },
                config: {},
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});

test('getExamPdfUrl returns the direct PDF endpoint', () => {
    assert.equal(getExamPdfUrl('exam-3'), `${API_BASE_URL}/exam/exam-3/pdf`);
});
