import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import {
    generateQuiz,
    generateQuizFeedback,
    getAllQuizzes,
    getMyQuizResult,
    getQuizResults,
    submitQuiz,
} from './quiz.js';
import { API_BASE_URL } from '../config.js';
import { clearDedupeCache } from '../utils/requestDeduper.js';

test('generateQuiz posts multipart form data with selected files and options', async () => {
    const originalPost = axios.post;
    const calls = [];
    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { id: 'quiz-1' } };
    };

    try {
        await generateQuiz(['file-1', 'file-2'], {
            bloomLevels: ['remember', 'apply'],
            difficulty: 'medium',
            numQuestions: 5,
        });

        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, `${API_BASE_URL}/quiz/generate`);
        assert.deepEqual(calls[0].config, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        assert.deepEqual(calls[0].body.getAll('file_ids'), ['file-1', 'file-2']);
        assert.deepEqual(calls[0].body.getAll('bloom_levels'), ['remember', 'apply']);
        assert.equal(calls[0].body.get('difficulty'), 'medium');
        assert.equal(calls[0].body.get('num_questions'), '5');
    } finally {
        axios.post = originalPost;
    }
});

test('getAllQuizzes uses the quiz list endpoint and dedupes repeated calls', async () => {
    const originalGet = axios.get;
    const calls = [];
    clearDedupeCache('quiz:list:class-1');

    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: [{ id: 'quiz-1' }] };
    };

    try {
        const first = await getAllQuizzes('class-1', { headers: { 'X-Test': 'yes' } });
        const second = await getAllQuizzes('class-1', { headers: { 'X-Test': 'yes' } });

        assert.strictEqual(first, second);
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/quiz/list`,
                config: {
                    params: { class_id: 'class-1' },
                    headers: { 'X-Test': 'yes' },
                },
            },
        ]);
    } finally {
        axios.get = originalGet;
        clearDedupeCache('quiz:list:class-1');
    }
});

test('quiz submission and feedback APIs include auth when a session token exists', async () => {
    const originalPost = axios.post;
    const calls = [];
    const storage = installLocalStorage({ session_token: 'token-123' });

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: { ok: true } };
    };

    try {
        await submitQuiz('quiz-1', { answers: ['A'], score: 1, total_questions: 1 });
        await generateQuizFeedback('quiz-1', { score: 1, total_questions: 1 });

        assert.deepEqual(calls, [
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
        axios.post = originalPost;
        storage.restore();
    }
});

test('quiz result APIs omit auth config when no token exists', async () => {
    const originalGet = axios.get;
    const calls = [];
    const storage = installLocalStorage();

    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: { ok: true } };
    };

    try {
        await getQuizResults('quiz-2');
        await getMyQuizResult('quiz-2');

        assert.deepEqual(calls, [
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
        axios.get = originalGet;
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
