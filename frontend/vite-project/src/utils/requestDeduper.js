// Simple request deduper utility
// - dedupe(key, fn, options)
//   - key: string key identifying the request
//   - fn: function returning a Promise (the actual request)
//   - options: { ttl } optional cache TTL in ms
// Returns a Promise resolving to fn() result. If another call with same key
// happens while the first is pending, the same Promise is returned.

const _pending = new Map();
const _cache = new Map();

export function dedupe(key, fn, options = {}) {
    const { ttl = 0 } = options;
    const now = Date.now();

    // return cached value if still fresh
    const cached = _cache.get(key);
    if (cached && ttl > 0 && now - cached.ts < ttl) {
        console.debug(`[dedupe] cache hit for ${key}`);
        return Promise.resolve(cached.value);
    }

    // return pending promise if already running
    if (_pending.has(key)) {
        console.debug(`[dedupe] pending promise reused for ${key}`);
        return _pending.get(key);
    }

    console.debug(`[dedupe] creating new request for ${key}`);
    const p = Promise.resolve()
        .then(() => fn())
        .then((res) => {
            if (ttl > 0) {
                try { _cache.set(key, { ts: Date.now(), value: res }); } catch (e) { /* ignore */ }
            }
            return res;
        })
        .finally(() => {
            _pending.delete(key);
        });

    _pending.set(key, p);
    return p;
}

export function clearDedupeCache(key) {
    _cache.delete(key);
}
