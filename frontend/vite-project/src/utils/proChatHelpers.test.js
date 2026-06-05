import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';

import { handleProChatRequest, generateWelcomeMessage } from './proChatHelpers.js';
import { API_BASE_URL } from '../config.js';
import i18n from '../i18n/config.js';

test('handleProChatRequest posts the query and returns structured content', async () => {
    const originalPost = axios.post;
    const calls = [];

    axios.post = async (url, body, config) => {
        calls.push({ url, body, config });
        return {
            data: {
                answer: 'Grounded answer [1].',
                raw_sources: [{ fileId: 'file-1', chunkId: 'chunk-1', source: 'notes.pdf', pageNumber: 2 }],
            },
        };
    };

    try {
        const response = await handleProChatRequest(
            [{ content: 'Explain normalization' }],
            { requestBody: { selectedFileIds: ['file-1'] } },
        );
        const content = JSON.parse(await response.text());

        assert.deepEqual(calls, [
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
        axios.post = originalPost;
    }
});

test('handleProChatRequest maps service errors to user-facing messages', async () => {
    const originalPost = axios.post;
    axios.post = async () => {
        throw { response: { status: 503, data: {} } };
    };

    try {
        const response = await handleProChatRequest([{ content: 'hi' }]);
        assert.equal(response.status, 503);
        assert.equal(await response.text(), 'Service temporarily unavailable, please try again later.');
    } finally {
        axios.post = originalPost;
    }
});

test('generateWelcomeMessage describes empty and selected document states', async () => {
    await i18n.changeLanguage('en');

    assert.equal(generateWelcomeMessage(0), i18n.t('chat.welcomeNoDocuments'));
    assert.match(generateWelcomeMessage(3, 1), /1/);
    assert.match(generateWelcomeMessage(3, 3), /selected/i);
});
