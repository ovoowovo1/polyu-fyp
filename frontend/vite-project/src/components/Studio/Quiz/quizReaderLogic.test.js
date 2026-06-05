import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildExplanationPrompt,
    buildQuizAnswerPayload,
    buildQuizFeedbackPayload,
    calculateQuizScore,
    createEmptyAnswers,
    nextQuizNavigationState,
    previousQuizNavigationState,
    storedAnswerAt,
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

test('quiz answer and navigation helpers keep state transitions predictable', () => {
    assert.deepEqual(buildQuizAnswerPayload([1, null]), [
        { question_index: 0, answer_index: 1 },
        { question_index: 1, answer_index: null },
    ]);
    assert.equal(storedAnswerAt([null, 2], 0, 1), 1);
    assert.equal(storedAnswerAt([null, 2], 1, 1), 2);
    assert.deepEqual(
        nextQuizNavigationState({ currentIndex: 0, questions, userAnswers: [1, null] }),
        { currentIndex: 1, selectedAnswer: null, showResult: false, isFinished: false },
    );
    assert.deepEqual(
        nextQuizNavigationState({ currentIndex: 1, questions, userAnswers: [1, null] }),
        { isFinished: true },
    );
    assert.deepEqual(
        previousQuizNavigationState({ currentIndex: 1, userAnswers: [1, null] }),
        { currentIndex: 0, selectedAnswer: 1, showResult: true },
    );
});

test('buildExplanationPrompt includes selected and correct answers', () => {
    const prompt = buildExplanationPrompt({
        question: questions[1],
        userAnswerIndex: 0,
    });

    assert.match(prompt, /Choose a DDL command/);
    assert.match(prompt, /I chose the following answer:" A\. SELECT"/);
    assert.match(prompt, /The correct answer is " B\. CREATE "/);
});
