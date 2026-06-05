import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildExamSubmitPayload,
    createEmptyExamAnswers,
    examImageUrl,
    nextExamIndex,
    previousExamIndex,
    questionInputMode,
    restoreExamAnswer,
} from './examReaderLogic.js';

const questions = [
    {
        question_id: 'q-1',
        exam_question_id: 'eq-1',
        question_type: 'multiple_choice',
        choices: ['A', 'B'],
    },
    {
        question_id: 'q-2',
        exam_question_id: 'eq-2',
        question_type: 'short_answer',
        choices: [],
    },
];

test('exam reader helpers build URLs and restore navigation state', () => {
    assert.equal(examImageUrl('', 'http://api'), '');
    assert.equal(examImageUrl('https://cdn/image.png', 'http://api'), 'https://cdn/image.png');
    assert.equal(examImageUrl('/static/image.png', 'http://api'), 'http://api/static/image.png');
    assert.deepEqual(createEmptyExamAnswers(2), [null, null]);
    assert.equal(restoreExamAnswer([1, 'text'], 1), 'text');
    assert.equal(restoreExamAnswer([1], 3), null);
    assert.equal(nextExamIndex(0, questions), 1);
    assert.equal(nextExamIndex(1, questions), 1);
    assert.equal(previousExamIndex(0), 0);
    assert.equal(previousExamIndex(2), 1);
});

test('questionInputMode and buildExamSubmitPayload preserve backend answer shape', () => {
    assert.equal(questionInputMode(questions[0]), 'multiple_choice');
    assert.equal(questionInputMode(questions[1]), 'short_answer');
    assert.equal(questionInputMode({ question_type: 'essay', marks: 5 }), 'essay');
    assert.deepEqual(buildExamSubmitPayload({ questions, userAnswers: [1, 'Because'] }), {
        answers: [
            { question_id: 'q-1', exam_question_id: 'eq-1', answer_index: 1 },
            { question_id: 'q-2', exam_question_id: 'eq-2', answer_text: 'Because' },
        ],
        time_spent_seconds: null,
    });
});
