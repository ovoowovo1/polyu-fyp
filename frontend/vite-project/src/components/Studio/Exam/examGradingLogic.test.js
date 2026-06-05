import test from 'node:test';
import assert from 'node:assert/strict';

import { buildManualGradePayload, mergeAiGradingResults } from './examGradingLogic.js';

test('mergeAiGradingResults applies only AI graded answers and records changed ids', () => {
    const result = mergeAiGradingResults(
        [
            { id: 'a-1', exam_question_id: 'eq-1', marks_earned: 0 },
            { id: 'a-2', exam_question_id: 'eq-2', marks_earned: 0 },
        ],
        [
            { answer_id: 'a-1', exam_question_id: 'eq-1', ai_graded: true, marks_earned: 2, teacher_feedback: 'Good' },
            { answer_id: 'a-2', exam_question_id: 'eq-2', ai_graded: false, marks_earned: 1, teacher_feedback: 'Skip' },
        ],
    );

    assert.deepEqual(result.answers, [
        { id: 'a-1', exam_question_id: 'eq-1', marks_earned: 2, teacher_feedback: 'Good' },
        { id: 'a-2', exam_question_id: 'eq-2', marks_earned: 0 },
    ]);
    assert.deepEqual([...result.aiGradedIds], ['a-1']);
});

test('buildManualGradePayload maps modal state to backend request shape', () => {
    assert.deepEqual(
        buildManualGradePayload({
            answers: [{ id: 'a-1', exam_question_id: 'eq-1', marks_earned: undefined, teacher_feedback: 'Review' }],
            teacherComment: 'Overall',
        }),
        {
            answers_grades: [
                { answer_id: 'a-1', exam_question_id: 'eq-1', marks_earned: 0, teacher_feedback: 'Review' },
            ],
            teacher_comment: 'Overall',
        },
    );
});
