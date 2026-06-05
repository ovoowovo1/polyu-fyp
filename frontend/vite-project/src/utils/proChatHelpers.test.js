import test from 'node:test';
import assert from 'node:assert/strict';

import { handleProChatRequest, generateWelcomeMessage } from './proChatHelpers.js';
import { API_BASE_URL } from '../config.js';
import i18n from '../i18n/config.js';
import { installAxiosMock } from '../testing/mockRuntime.js';

test('handleProChatRequest posts the query and returns structured content', async () => {
    const axiosMock = installAxiosMock({
        post: async () => ({
            data: {
                answer: 'Grounded answer [1].',
                raw_sources: [{ fileId: 'file-1', chunkId: 'chunk-1', source: 'notes.pdf', pageNumber: 2 }],
            },
        }),
    });

    try {
        const response = await handleProChatRequest(
            [{ content: 'Explain normalization' }],
            { requestBody: { selectedFileIds: ['file-1'] } },
        );
        const content = JSON.parse(await response.text());

        assert.deepEqual(axiosMock.calls.map(({ args }) => ({ url: args[0], body: args[1], config: args[2] })), [
            {
                url: `${API_BASE_URL}/query`,
                body: {
                    question: 'Explain normalization',
                    selectedFileIds: ['file-1'],
                },
                config: {},
            },
        ]);
        assert.equal(content[0].type, 'text');
        assert.equal(content[1].type, 'citation');
    } finally {
        axiosMock.restore();
    }
});

test('handleProChatRequest maps service errors to user-facing messages', async () => {
    const axiosMock = installAxiosMock({
        post: async () => {
            throw { response: { status: 503, data: {} } };
        },
    });

    try {
        const response = await handleProChatRequest([{ content: 'hi' }]);
        assert.equal(response.status, 503);
        assert.equal(await response.text(), 'Service temporarily unavailable, please try again later.');
    } finally {
        axiosMock.restore();
    }
});

test('generateWelcomeMessage describes empty and selected document states', async () => {
    await i18n.changeLanguage('en');

    assert.equal(generateWelcomeMessage(0), i18n.t('chat.welcomeNoDocuments'));
    assert.match(generateWelcomeMessage(3, 1), /1/);
    assert.match(generateWelcomeMessage(3, 3), /selected/i);
});
