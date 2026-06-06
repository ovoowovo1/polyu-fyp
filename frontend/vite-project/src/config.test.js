import test from 'node:test';
import assert from 'node:assert/strict';

import {
    LOCAL_API_BASE_URL,
    PRODUCTION_API_BASE_URL_ERROR,
    resolveApiBaseUrl,
} from './config.js';

test('resolveApiBaseUrl uses explicit Vite env value', () => {
    const result = resolveApiBaseUrl(
        { VITE_API_BASE_URL: 'https://api.example.com', PROD: true },
        { VITE_API_BASE_URL: 'http://localhost:3000' },
    );

    assert.equal(result, 'https://api.example.com');
});

test('resolveApiBaseUrl uses process env value for Node tests', () => {
    const result = resolveApiBaseUrl({}, { VITE_API_BASE_URL: 'http://test-api.local' });

    assert.equal(result, 'http://test-api.local');
});

test('resolveApiBaseUrl falls back to localhost outside production', () => {
    const result = resolveApiBaseUrl({ PROD: false }, {});

    assert.equal(result, LOCAL_API_BASE_URL);
});

test('resolveApiBaseUrl rejects missing production API base URL', () => {
    assert.throws(
        () => resolveApiBaseUrl({ PROD: true }, {}),
        new RegExp(PRODUCTION_API_BASE_URL_ERROR),
    );
});

test('resolveApiBaseUrl prefers Vite env over process env', () => {
    const result = resolveApiBaseUrl(
        { VITE_API_BASE_URL: 'https://vite-api.example.com', PROD: false },
        { VITE_API_BASE_URL: 'http://process-api.local' },
    );

    assert.equal(result, 'https://vite-api.example.com');
});
