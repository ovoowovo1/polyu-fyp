import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import {
    deleteDocument,
    fetchDocumentContent,
    fetchDocuments,
    renameDocument,
} from './documentSlice.js';
import { API_BASE_URL } from '../config.js';
import { clearDedupeCache } from '../utils/requestDeduper.js';

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

    const originalGet = axios.get;
    const calls = [];
    axios.get = async (url, config) => {
        calls.push({ url, config });
        return { data: { files: [{ id: 'doc-1' }] } };
    };

    try {
        const harness = createThunkHarness();
        const result = await fetchDocuments('class-1')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'documents/fetchDocuments/fulfilled');
        assert.deepEqual(result.payload, [{ id: 'doc-1' }]);
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/files`,
                config: { params: { class_id: 'class-1' } },
            },
        ]);
    } finally {
        axios.get = originalGet;
        clearDedupeCache('docs:list:class-1');
    }
});

test('deleteDocument uses the new /files endpoint', async () => {
    const originalDelete = axios.delete;
    const calls = [];
    axios.delete = async (url) => {
        calls.push(url);
        return { data: {} };
    };

    try {
        const harness = createThunkHarness();
        const result = await deleteDocument('doc-2')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'documents/deleteDocument/fulfilled');
        assert.equal(result.payload, 'doc-2');
        assert.deepEqual(calls, [`${API_BASE_URL}/files/doc-2`]);
    } finally {
        axios.delete = originalDelete;
    }
});

test('renameDocument uses the new /files endpoint', async () => {
    const originalPut = axios.put;
    const calls = [];
    axios.put = async (url, body, config) => {
        calls.push({ url, body, config });
        return { data: {} };
    };

    try {
        const harness = createThunkHarness();
        const result = await renameDocument({ docId: 'doc-3', newName: 'renamed.pdf' })(
            harness.dispatch,
            harness.getState,
            undefined,
        );

        assert.equal(result.type, 'documents/renameDocument/fulfilled');
        assert.deepEqual(result.payload, { docId: 'doc-3', newName: 'renamed.pdf' });
        assert.deepEqual(calls, [
            {
                url: `${API_BASE_URL}/files/doc-3`,
                body: null,
                config: { params: { new_name: 'renamed.pdf' } },
            },
        ]);
    } finally {
        axios.put = originalPut;
    }
});

test('fetchDocumentContent uses the new /files endpoint', async () => {
    const originalGet = axios.get;
    const calls = [];
    axios.get = async (url) => {
        calls.push(url);
        return { data: { file: { id: 'doc-4' }, content: 'hello' } };
    };

    try {
        const harness = createThunkHarness();
        const result = await fetchDocumentContent('doc-4')(harness.dispatch, harness.getState, undefined);

        assert.equal(result.type, 'document/fetchDocumentContent/fulfilled');
        assert.deepEqual(result.payload, { file: { id: 'doc-4' }, content: 'hello' });
        assert.deepEqual(calls, [`${API_BASE_URL}/files/doc-4`]);
    } finally {
        axios.get = originalGet;
    }
});
