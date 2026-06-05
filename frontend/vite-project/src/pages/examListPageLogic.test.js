import test from 'node:test';
import assert from 'node:assert/strict';

import {
    formatExamCreatedAt,
    getExamStatusKey,
    getStudentExamActionKeys,
    getTeacherExamActionKeys,
    resolveExamListRole,
} from './examListPageLogic.js';

test('resolveExamListRole prefers current user and falls back to local storage', () => {
    assert.equal(resolveExamListRole({ currentUser: { role: 'teacher' }, storage: null }), 'teacher');
    assert.equal(resolveExamListRole({ currentUser: null, storage: { getItem: () => 'student' } }), 'student');
    assert.equal(resolveExamListRole({ currentUser: null, storage: { getItem: () => null } }), 'student');
});

test('formatExamCreatedAt uses formatter when a date exists', () => {
    assert.equal(formatExamCreatedAt('2026-01-01', (value) => `formatted:${value}`), 'formatted:2026-01-01');
    assert.equal(formatExamCreatedAt(null, () => 'unused'), '-');
});

test('exam status and action helpers describe table behavior', () => {
    assert.equal(getExamStatusKey(true), 'published');
    assert.equal(getExamStatusKey(false), 'unpublished');
    assert.deepEqual(getTeacherExamActionKeys(true), ['view', 'unpublish', 'submissions', 'delete']);
    assert.deepEqual(getTeacherExamActionKeys(false), ['view', 'publish', 'submissions', 'delete']);
    assert.deepEqual(getStudentExamActionKeys(true), ['take', 'myScore']);
    assert.deepEqual(getStudentExamActionKeys(false), ['notPublished', 'myScore']);
});
