const API_BASE_URL =
    import.meta?.env?.VITE_API_BASE_URL ||
    globalThis.process?.env?.VITE_API_BASE_URL ||
    'http://localhost:3000';

export { API_BASE_URL };
