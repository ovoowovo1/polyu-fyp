import test from 'node:test';
import assert from 'node:assert/strict';

import {
    areAllFilteredDocumentsSelected,
    filterDocumentsBySearch,
    findDocumentById,
    getFilteredDocumentIds,
    getNextSourceModalVisibility,
    isDocumentSelected,
} from './documentListLogic.js';

const documents = [
    { id: 'doc-1', filename: 'Lecture Notes.pdf' },
    { id: 'doc-2', filename: 'assignment.md' },
];

test('filterDocumentsBySearch matches filenames case-insensitively', () => {
    assert.deepEqual(filterDocumentsBySearch(documents, 'lecture'), [documents[0]]);
    assert.deepEqual(filterDocumentsBySearch(documents, 'ASSIGN'), [documents[1]]);
    assert.deepEqual(filterDocumentsBySearch(documents, ''), documents);
});

test('document selection helpers preserve existing selected-all behavior', () => {
    assert.equal(isDocumentSelected(['doc-1'], 'doc-1'), true);
    assert.equal(isDocumentSelected(['doc-1'], 'doc-2'), false);
    assert.equal(areAllFilteredDocumentsSelected(documents, ['doc-1', 'doc-2']), true);
    assert.equal(areAllFilteredDocumentsSelected(documents, ['doc-1']), false);
    assert.equal(areAllFilteredDocumentsSelected([], []), false);
});

test('findDocumentById returns the matching document or null', () => {
    assert.deepEqual(findDocumentById(documents, 'doc-2'), documents[1]);
    assert.equal(findDocumentById(documents, 'missing'), null);
});

test('getFilteredDocumentIds returns ids for select all', () => {
    assert.deepEqual(getFilteredDocumentIds(documents), ['doc-1', 'doc-2']);
});

test('getNextSourceModalVisibility maps source type to the next modal', () => {
    assert.deepEqual(getNextSourceModalVisibility('pdf'), {
        uploadModalVisible: true,
        linkModalVisible: false,
    });
    assert.deepEqual(getNextSourceModalVisibility('link'), {
        uploadModalVisible: false,
        linkModalVisible: true,
    });
    assert.deepEqual(getNextSourceModalVisibility('other'), {
        uploadModalVisible: false,
        linkModalVisible: false,
    });
});
