import test from 'node:test';
import assert from 'node:assert/strict';

import { clearDedupeCache, dedupe } from './requestDeduper.js';

test('dedupe reuses the same pending promise for the same key', async () => {
    const key = 'pending-key';
    let calls = 0;
    let resolveRequest;
    const request = () => {
        calls += 1;
        return new Promise((resolve) => {
            resolveRequest = resolve;
        });
    };

    try {
        const first = dedupe(key, request);
        const second = dedupe(key, request);

        assert.strictEqual(first, second);
        await Promise.resolve();
        assert.equal(calls, 1);

        resolveRequest('done');
        assert.equal(await first, 'done');
        assert.equal(await second, 'done');
    } finally {
        clearDedupeCache(key);
    }
});

test('dedupe returns a cached value while the TTL is fresh', async () => {
    const key = 'ttl-key';
    const originalNow = Date.now;
    let calls = 0;
    let now = 1000;
    Date.now = () => now;

    try {
        const first = await dedupe(key, async () => {
            calls += 1;
            return { value: 'first' };
        }, { ttl: 500 });

        now = 1200;
        const second = await dedupe(key, async () => {
            calls += 1;
            return { value: 'second' };
        }, { ttl: 500 });

        assert.equal(calls, 1);
        assert.strictEqual(second, first);
    } finally {
        Date.now = originalNow;
        clearDedupeCache(key);
    }
});

test('clearDedupeCache removes a cached value for the selected key', async () => {
    const key = 'clear-key';
    let calls = 0;

    try {
        const first = await dedupe(key, async () => {
            calls += 1;
            return 'first';
        }, { ttl: 1000 });

        clearDedupeCache(key);

        const second = await dedupe(key, async () => {
            calls += 1;
            return 'second';
        }, { ttl: 1000 });

        assert.equal(first, 'first');
        assert.equal(second, 'second');
        assert.equal(calls, 2);
    } finally {
        clearDedupeCache(key);
    }
});

test('dedupe keeps pending and cached values isolated by key', async () => {
    const firstKey = 'isolated-a';
    const secondKey = 'isolated-b';
    let calls = 0;

    try {
        const first = await dedupe(firstKey, async () => {
            calls += 1;
            return 'a';
        }, { ttl: 1000 });
        const second = await dedupe(secondKey, async () => {
            calls += 1;
            return 'b';
        }, { ttl: 1000 });

        assert.equal(first, 'a');
        assert.equal(second, 'b');
        assert.equal(calls, 2);
    } finally {
        clearDedupeCache(firstKey);
        clearDedupeCache(secondKey);
    }
});
