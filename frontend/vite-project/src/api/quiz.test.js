import test from 'node:test';
import assert from 'node:assert/strict';

import {
    createQuiz,
    deleteQuiz,
    generateQuiz,
    generateQuizFeedback,
    getAllQuizzes,
    getQuizById,
    getMyQuizResult,
    getQuizResults,
    submitQuiz,
    updateQuiz,
} from './quiz.js';
import { API_BASE_URL } from '../config.js';
import { clearDedupeCache } from '../utils/requestDeduper.js';
import { installAxiosMock, installLocalStorageMock } from '../testing/mockRuntime.js';

test('generateQuiz posts multipart form data with selected files and options', async () => {
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { id: 'quiz-1' } }),
    });

    try {
        await generateQuiz(['file-1', 'file-2'], {
            bloomLevels: ['remember', 'apply'],
            difficulty: 'medium',
            numQuestions: 5,
        });

        const call = axiosMock.calls[0];
        assert.equal(call.args[0], `${API_BASE_URL}/quiz/generate`);
        assert.deepEqual(call.args[2], {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        assert.deepEqual(call.args[1].getAll('file_ids'), ['file-1', 'file-2']);
        assert.deepEqual(call.args[1].getAll('bloom_levels'), ['remember', 'apply']);
        assert.equal(call.args[1].get('difficulty'), 'medium');
        assert.equal(call.args[1].get('num_questions'), '5');
    } finally {
        axiosMock.restore();
    }
});

test('getAllQuizzes uses the quiz list endpoint and dedupes repeated calls', async () => {
    const storage = installLocalStorageMock({ session_token: 'quiz-token' });
    const axiosMock = installAxiosMock({
        get: async () => ({ data: [{ id: 'quiz-1' }] }),
    });
    clearDedupeCache('quiz:list:class-1');

    try {
        const first = await getAllQuizzes('class-1', { headers: { 'X-Test': 'yes' } });
        const second = await getAllQuizzes('class-1', { headers: { 'X-Test': 'yes' } });

        assert.strictEqual(first, second);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
            {
                url: `${API_BASE_URL}/quiz/list`,
                config: {
                    params: { class_id: 'class-1' },
                    headers: { Authorization: 'Bearer quiz-token', 'X-Test': 'yes' },
                },
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
        clearDedupeCache('quiz:list:class-1');
    }
});

test('quiz management APIs include auth when a session token exists', async () => {
    const storage = installLocalStorageMock({ session_token: 'teacher-token' });
    const axiosMock = installAxiosMock({
        get: async () => ({ data: { ok: true } }),
        post: async () => ({ data: { ok: true } }),
        put: async () => ({ data: { ok: true } }),
        delete: async () => ({ data: { ok: true } }),
    });

    try {
        await getQuizById('quiz-1');
        await createQuiz({ questions: [] });
        await updateQuiz('quiz-1', { questions: [] });
        await deleteQuiz('quiz-1');

        assert.deepEqual(axiosMock.calls.map(({ method, args }) => ({
            method,
            url: args[0],
            body: method === 'post' || method === 'put' ? args[1] : undefined,
            config: method === 'post' || method === 'put' ? args[2] : args[1],
        })), [
            {
                method: 'get',
                url: `${API_BASE_URL}/quiz/quiz-1`,
                body: undefined,
                config: { headers: { Authorization: 'Bearer teacher-token' } },
            },
            {
                method: 'post',
                url: `${API_BASE_URL}/quiz`,
                body: { questions: [] },
                config: { headers: { Authorization: 'Bearer teacher-token' } },
            },
            {
                method: 'put',
                url: `${API_BASE_URL}/quiz/quiz-1`,
                body: { questions: [] },
                config: { headers: { Authorization: 'Bearer teacher-token' } },
            },
            {
                method: 'delete',
                url: `${API_BASE_URL}/quiz/quiz-1`,
                body: undefined,
                config: { headers: { Authorization: 'Bearer teacher-token' } },
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});

test('quiz submission and feedback APIs include auth when a session token exists', async () => {
    const storage = installLocalStorageMock({ session_token: 'token-123' });
    const axiosMock = installAxiosMock({
        post: async () => ({ data: { ok: true } }),
    });

    try {
        await submitQuiz('quiz-1', { answers: ['A'], score: 1, total_questions: 1 });
        await generateQuizFeedback('quiz-1', { score: 1, total_questions: 1 });

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/quiz/quiz-1/submit`,
                body: { answers: ['A'], score: 1, total_questions: 1 },
                config: { headers: { Authorization: 'Bearer token-123' } },
            },
            {
                url: `${API_BASE_URL}/quiz/quiz-1/feedback`,
                body: { score: 1, total_questions: 1 },
                config: { headers: { Authorization: 'Bearer token-123' } },
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});

test('quiz result APIs omit auth config when no token exists', async () => {
    const storage = installLocalStorageMock();
    const axiosMock = installAxiosMock({
        get: async () => ({ data: { ok: true } }),
    });

    try {
        await getQuizResults('quiz-2');
        await getMyQuizResult('quiz-2');

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
            {
                url: `${API_BASE_URL}/quiz/quiz-2/results`,
                config: {},
            },
            {
                url: `${API_BASE_URL}/quiz/quiz-2/my-result`,
                config: {},
            },
        ]);
    } finally {
        axiosMock.restore();
        storage.restore();
    }
});
