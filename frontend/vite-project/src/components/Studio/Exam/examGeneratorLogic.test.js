import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildExamGenerationPayload,
    examGenerationTotals,
    examQuestionTypeColor,
    examQuestionTypeLabel,
    examResultQuestionPreview,
    getExamProgressStage,
} from './examGeneratorLogic.js';

test('buildExamGenerationPayload maps form state into backend request shape', () => {
    assert.deepEqual(
        buildExamGenerationPayload({
            selectedFileIds: ['file-1'],
            topic: '',
            difficulty: 'hard',
            mcCount: 3,
            shortAnswerCount: 2,
            essayCount: 1,
            examName: 'Midterm',
            includeImages: false,
            customPrompt: '',
        }),
        {
            file_ids: ['file-1'],
            topic: undefined,
            difficulty: 'hard',
            num_questions: 6,
            question_types: {
                multiple_choice: 3,
                short_answer: 2,
                essay: 1,
            },
            exam_name: 'Midterm',
            include_images: false,
            custom_prompt: undefined,
        },
    );
});

test('getExamProgressStage returns the next progress milestone', () => {
    const t = (key) => key;

    assert.deepEqual(getExamProgressStage(39, t), {
        p: 40,
        s: 'exam.generator.generating',
    });
    assert.equal(getExamProgressStage(90, t), undefined);
});

test('exam generation helpers derive labels, totals, and preview slices', () => {
    const t = (key) => key;

    assert.equal(examQuestionTypeLabel('multiple_choice', t), 'exam.generator.questionTypeMultipleChoice');
    assert.equal(examQuestionTypeLabel('short_answer', t), 'exam.generator.questionTypeShortAnswer');
    assert.equal(examQuestionTypeLabel('essay', t), 'exam.generator.questionTypeEssay');
    assert.equal(examQuestionTypeColor('multiple_choice'), 'blue');
    assert.equal(examQuestionTypeColor('short_answer'), 'orange');
    assert.equal(examQuestionTypeColor('essay'), 'purple');
    assert.deepEqual(examGenerationTotals({ mcCount: 3, shortAnswerCount: 2, essayCount: 1 }), {
        questions: 6,
        marks: 12,
    });
    assert.deepEqual(examResultQuestionPreview([{ id: 1 }, { id: 2 }, { id: 3 }], 2), {
        questions: [{ id: 1 }, { id: 2 }],
        remainingCount: 1,
    });
});
