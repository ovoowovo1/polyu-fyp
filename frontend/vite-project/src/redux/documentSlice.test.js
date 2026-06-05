import test from 'node:test';
import assert from 'node:assert/strict';

import reducer, {
    deleteDocument,
    fetchDocumentContent,
    fetchDocuments,
    renameDocument,
    resetDocumentState,
    setCurrentClassId,
    setSearchTerm,
    setSelectedShowDocumentContentID,
    toggleDocumentListCollapse,
    toggleFileSelection,
    toggleSelectAll,
} from './documentSlice.js';
import { API_BASE_URL } from '../config.js';
import { clearDedupeCache } from '../utils/requestDeduper.js';
import { installAxiosMock } from '../testing/mockRuntime.js';

function createThunkHarness(state = { documents: { currentClassId: null } }) {
    const actions = [];
    return {
        actions,
        dispatch(action) {
            actions.push(action);
            return action;
        },
        getState() {
            return state;
        },
    };
}

test('fetchDocuments uses the new /files endpoint', async () => {
    clearDedupeCache('docs:list:class-1');

    const axiosMock = installAxiosMock({
        get: async () => ({ data: { files: [{ id: 'doc-1' }] } }),
    });

    try {
        const harness = createThunkHarness();
        const result = await fetchDocuments('class-1')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'documents/fetchDocuments/fulfilled');
        assert.deepEqual(result.payload, [{ id: 'doc-1' }]);
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], config: args[1] })), [
            {
                url: `${API_BASE_URL}/files`,
                config: { params: { class_id: 'class-1' } },
            },
        ]);
    } finally {
        axiosMock.restore();
        clearDedupeCache('docs:list:class-1');
    }
});

test('deleteDocument uses the new /files endpoint', async () => {
    const axiosMock = installAxiosMock({
        delete: async () => ({ data: {} }),
    });

    try {
        const harness = createThunkHarness();
        const result = await deleteDocument('doc-2')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'documents/deleteDocument/fulfilled');
        assert.equal(result.payload, 'doc-2');
        assert.deepEqual(axiosMock.calls.map(({ args }) => args[0]), [`${API_BASE_URL}/files/doc-2`]);
    } finally {
        axiosMock.restore();
    }
});

test('renameDocument uses the new /files endpoint', async () => {
    const axiosMock = installAxiosMock({
        put: async () => ({ data: {} }),
    });

    try {
        const harness = createThunkHarness();
        const result = await renameDocument({ docId: 'doc-3', newName: 'renamed.pdf' })(
            harness.dispatch,
            harness.getState,
            undefined,
        );

        assert.equal(result.type, 'documents/renameDocument/fulfilled');
        assert.deepEqual(result.payload, { docId: 'doc-3', newName: 'renamed.pdf' });
        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/files/doc-3`,
                body: null,
                config: { params: { new_name: 'renamed.pdf' } },
            },
        ]);
    } finally {
        axiosMock.restore();
    }
});

test('fetchDocumentContent uses the new /files endpoint', async () => {
    const axiosMock = installAxiosMock({
        get: async () => ({ data: { file: { id: 'doc-4' }, content: 'hello' } }),
    });

    try {
        const harness = createThunkHarness();
        const result = await fetchDocumentContent('doc-4')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'document/fetchDocumentContent/fulfilled');
        assert.deepEqual(result.payload, { file: { id: 'doc-4' }, content: 'hello' });
        assert.deepEqual(axiosMock.calls.map(({ args }) => args[0]), [`${API_BASE_URL}/files/doc-4`]);
    } finally {
        axiosMock.restore();
    }
});

test('document reducer exposes the expected initial state', () => {
    assert.deepEqual(reducer(undefined, { type: '@@INIT' }), {
        items: [],
        documentsById: {},
        currentClassId: null,
        loading: false,
        contentLoading: false,
        error: null,
        selectedFileIds: [],
        selectedShowDocumentContentID: null,
        searchTerm: '',
        isDocumentListCollapsed: false,
    });
});

test('document reducer updates simple view state', () => {
    let state = reducer(undefined, setSearchTerm('lecture'));
    state = reducer(state, setSelectedShowDocumentContentID('doc-1'));
    state = reducer(state, setCurrentClassId('class-1'));
    state = reducer(state, toggleDocumentListCollapse());

    assert.equal(state.searchTerm, 'lecture');
    assert.equal(state.selectedShowDocumentContentID, 'doc-1');
    assert.equal(state.currentClassId, 'class-1');
    assert.equal(state.isDocumentListCollapsed, true);
});

test('toggleFileSelection selects and deselects one file id', () => {
    const selected = reducer(undefined, toggleFileSelection('file-1'));
    const deselected = reducer(selected, toggleFileSelection('file-1'));

    assert.deepEqual(selected.selectedFileIds, ['file-1']);
    assert.deepEqual(deselected.selectedFileIds, []);
});

test('toggleSelectAll selects every file and clears when already selected', () => {
    const allIds = ['file-1', 'file-2'];
    const selected = reducer(undefined, toggleSelectAll(allIds));
    const cleared = reducer(selected, toggleSelectAll(allIds));

    assert.deepEqual(selected.selectedFileIds, allIds);
    assert.deepEqual(cleared.selectedFileIds, []);
});

test('renameDocument fulfilled updates filename and original name in state', () => {
    const state = reducer({
        ...reducer(undefined, { type: '@@INIT' }),
        items: [
            { id: 'doc-1', filename: 'old.pdf', original_name: 'old.pdf' },
            { id: 'doc-2', filename: 'keep.pdf', original_name: 'keep.pdf' },
        ],
    }, renameDocument.fulfilled({ docId: 'doc-1', newName: 'new.pdf' }));

    assert.deepEqual(state.items, [
        { id: 'doc-1', filename: 'new.pdf', original_name: 'new.pdf' },
        { id: 'doc-2', filename: 'keep.pdf', original_name: 'keep.pdf' },
    ]);
});

test('fetchDocumentContent fulfilled stores document content by file id', () => {
    const payload = {
        file: { id: 'doc-1', filename: 'notes.pdf' },
        content: 'document body',
    };
    const state = reducer(undefined, fetchDocumentContent.fulfilled(payload));

    assert.equal(state.contentLoading, false);
    assert.deepEqual(state.documentsById, {
        'doc-1': payload,
    });
});

test('fetchDocuments pending and rejected update loading and error state', () => {
    const pending = reducer(undefined, fetchDocuments.pending());
    const rejected = reducer({
        ...pending,
        items: [{ id: 'doc-1' }],
    }, fetchDocuments.rejected(null, 'request-1', 'class-1', 'load failed'));

    assert.equal(pending.loading, true);
    assert.equal(pending.error, null);
    assert.equal(rejected.loading, false);
    assert.equal(rejected.error, 'load failed');
    assert.deepEqual(rejected.items, []);
});

test('fetchDocumentContent with no doc id resolves to a null payload', async () => {
    const harness = createThunkHarness();
    const result = await fetchDocumentContent(null)(harness.dispatch, harness.getState, undefined);

    assert.equal(result.type, 'document/fetchDocumentContent/fulfilled');
    assert.equal(result.payload, null);
});

test('resetDocumentState restores the initial state', () => {
    const dirtyState = {
        ...reducer(undefined, { type: '@@INIT' }),
        items: [{ id: 'doc-1' }],
        currentClassId: 'class-1',
        selectedFileIds: ['file-1'],
        searchTerm: 'lecture',
        isDocumentListCollapsed: true,
    };

    assert.deepEqual(reducer(dirtyState, resetDocumentState()), reducer(undefined, { type: '@@INIT' }));
});
