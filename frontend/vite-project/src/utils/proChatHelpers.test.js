import test from 'node:test';
import assert from 'node:assert/strict';

import { generateWelcomeMessage } from './proChatHelpers.js';
import i18n from '../i18n/config.js';

test('generateWelcomeMessage describes empty and selected document states', async () => {
    await i18n.changeLanguage('en');

    assert.equal(generateWelcomeMessage(0), i18n.t('chat.welcomeNoDocuments'));
    assert.match(generateWelcomeMessage(3, 1), /1/);
    assert.match(generateWelcomeMessage(3, 3), /selected/i);
});
