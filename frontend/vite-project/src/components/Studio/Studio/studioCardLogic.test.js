import test from 'node:test';
import assert from 'node:assert/strict';

import {
    examPdfFilename,
    formatStudioDate,
    isCanceledRequest,
    mergeStudioItems,
    studioItemTimestamp,
} from './studioCardLogic.js';

test('formatStudioDate handles empty and invalid values', () => {
    assert.equal(formatStudioDate(null), '');
    assert.equal(formatStudioDate('not-a-date'), '');
});

test('formatStudioDate formats ISO strings and numeric timestamps', () => {
    const iso = '2026-01-02T03:04:00';
    const numeric = new Date(iso).getTime();

    assert.match(formatStudioDate(iso), /^02\/01\/2026 03:04$/);
    assert.match(formatStudioDate(numeric), /^02\/01\/2026 03:04$/);
});

test('studioItemTimestamp normalizes invalid and mixed created_at values', () => {
    const timestamp = new Date('2026-01-02T03:04:00').getTime();

    assert.equal(studioItemTimestamp({ created_at: null }), 0);
    assert.equal(studioItemTimestamp({ created_at: 'not-a-date' }), 0);
    assert.equal(studioItemTimestamp({ created_at: String(timestamp) }), timestamp);
    assert.equal(studioItemTimestamp({ created_at: timestamp }), timestamp);
});

test('mergeStudioItems tags and sorts quizzes and exams by newest first', () => {
    const items = mergeStudioItems(
        [{ id: 'exam-old', created_at: '2026-01-01T00:00:00Z' }],
        [{ id: 'quiz-new', created_at: '2026-01-02T00:00:00Z' }],
    );

    assert.deepEqual(items.map((item) => [item.id, item._type]), [
        ['quiz-new', 'quiz'],
        ['exam-old', 'exam'],
    ]);
});

test('examPdfFilename prefers exam title and falls back to id', () => {
    assert.equal(examPdfFilename('exam-1', [{ id: 'exam-1', title: 'Midterm' }]), 'Midterm.pdf');
    assert.equal(examPdfFilename('exam-2', [{ id: 'exam-1', title: 'Midterm' }]), 'exam_exam-2.pdf');
});

test('isCanceledRequest detects axios cancel errors only', () => {
    assert.equal(isCanceledRequest({ name: 'CanceledError' }), true);
    assert.equal(isCanceledRequest({ message: 'canceled' }), true);
    assert.equal(isCanceledRequest(new Error('boom')), false);
});
