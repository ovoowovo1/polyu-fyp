import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildQuizFeedbackPayload,
    calculateQuizScore,
    createEmptyAnswers,
} from './quizReaderLogic.js';

const questions = [
    {
        question: 'What is normalization?',
        choices: ['A', 'B', 'C'],
        answer_index: 1,
        bloom_level: 'understand',
        rationale: 'Because B is correct.',
    },
    {
        question: 'Choose a DDL command.',
        choices: ['SELECT', 'CREATE'],
        answer_index: 1,
        bloom_level: 'apply',
        rationale: 'CREATE defines schema objects.',
    },
];

test('createEmptyAnswers creates a null answer slot per question', () => {
    assert.deepEqual(createEmptyAnswers(3), [null, null, null]);
});

test('calculateQuizScore returns correct count and percentage', () => {
    assert.deepEqual(calculateQuizScore(questions, [0, 1]), {
        correct: 1,
        total: 2,
        percentage: 50,
    });
    assert.deepEqual(calculateQuizScore([], []), {
        correct: 0,
        total: 0,
        percentage: 0,
    });
});

test('buildQuizFeedbackPayload summarizes bloom accuracy and question snapshots', () => {
    const score = calculateQuizScore(questions, [1, 0]);
    const payload = buildQuizFeedbackPayload({
        quizName: 'Database Quiz',
        questions,
        userAnswers: [1, 0],
        score,
    });

    assert.equal(payload.quiz_name, 'Database Quiz');
    assert.equal(payload.score, 1);
    assert.deepEqual(payload.bloom_summary, [
        { level: 'understand', correct: 1, total: 1, accuracy: 100 },
        { level: 'apply', correct: 0, total: 1, accuracy: 0 },
    ]);
    assert.deepEqual(payload.questions[0], {
        question: 'What is normalization?',
        choices: ['A', 'B', 'C'],
        correct_answer_index: 1,
        user_answer_index: 1,
        bloom_level: 'understand',
        rationale: 'Because B is correct.',
    });
});
