import axios from 'axios';

const AXIOS_METHODS = ['get', 'post', 'put', 'delete'];

export function installAxiosMock(handlers = {}) {
    const originalMethods = {};
    const calls = [];

    for (const method of AXIOS_METHODS) {
        originalMethods[method] = axios[method];
        if (handlers[method]) {
            axios[method] = async (...args) => {
                const call = { method, args };
                calls.push(call);
                return handlers[method](...args, call);
            };
        }
    }

    return {
        calls,
        restore() {
            for (const method of AXIOS_METHODS) {
                axios[method] = originalMethods[method];
            }
        },
    };
}

export function installLocalStorageMock(initialValues = {}) {
    const originalLocalStorage = global.localStorage;
    const map = new Map(Object.entries(initialValues));

    global.localStorage = {
        getItem(key) {
            return map.has(key) ? map.get(key) : null;
        },
        setItem(key, value) {
            map.set(key, String(value));
        },
        removeItem(key) {
            map.delete(key);
        },
    };

    return {
        map,
        restore() {
            if (originalLocalStorage === undefined) {
                delete global.localStorage;
            } else {
                global.localStorage = originalLocalStorage;
            }
        },
    };
}
