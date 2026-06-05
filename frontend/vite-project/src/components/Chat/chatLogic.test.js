import test from 'node:test';
import assert from 'node:assert/strict';

import {
    appendProgressMessage,
    buildChatRequest,
    getAutofillChatPayload,
    parseChatResponseText,
} from './chatLogic.js';

test('buildChatRequest includes selected document metadata', () => {
    const result = buildChatRequest({
        userMessage: 'Explain this',
        selectedFileIds: ['doc-1', 'doc-2'],
        documentCount: 3,
    });

    assert.deepEqual(result, {
        messagesForAPI: [{ content: 'Explain this' }],
        requestOptions: {
            requestBody: {
                selectedFileIds: ['doc-1', 'doc-2'],
                documentCount: 3,
                selectedCount: 2,
            },
        },
    });
});

test('buildChatRequest omits selectedFileIds when no documents are selected', () => {
    const result = buildChatRequest({
        userMessage: 'Summarize',
        selectedFileIds: [],
        documentCount: 4,
    });

    assert.deepEqual(result.requestOptions.requestBody, {
        selectedFileIds: undefined,
        documentCount: 4,
        selectedCount: 0,
    });
});

test('parseChatResponseText returns JSON payloads or raw text', () => {
    assert.deepEqual(parseChatResponseText('{"answer":"ok"}'), { answer: 'ok' });
    assert.equal(parseChatResponseText('plain text'), 'plain text');
});

test('appendProgressMessage returns a new progress list', () => {
    const existing = [{ type: 'route' }];
    const next = appendProgressMessage(existing, { type: 'answer' });

    assert.deepEqual(next, [{ type: 'route' }, { type: 'answer' }]);
    assert.notEqual(next, existing);
});

test('getAutofillChatPayload normalizes autofill event details', () => {
    assert.deepEqual(getAutofillChatPayload({ detail: { text: 'Question', send: true } }), {
        text: 'Question',
        autoSend: true,
        hasText: true,
    });
    assert.deepEqual(getAutofillChatPayload({ detail: { text: '   ', send: false } }), {
        text: '   ',
        autoSend: false,
        hasText: false,
    });
});
