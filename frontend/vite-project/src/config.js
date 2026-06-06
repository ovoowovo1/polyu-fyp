const LOCAL_API_BASE_URL = 'http://localhost:3000';
const PRODUCTION_API_BASE_URL_ERROR = 'VITE_API_BASE_URL must be configured for production builds';

function configuredValue(value) {
    return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function resolveApiBaseUrl(viteEnv = import.meta?.env, processEnv = globalThis.process?.env) {
    const viteValue = configuredValue(viteEnv?.VITE_API_BASE_URL);
    if (viteValue) {
        return viteValue;
    }

    const processValue = configuredValue(processEnv?.VITE_API_BASE_URL);
    if (processValue) {
        return processValue;
    }

    if (viteEnv?.PROD === true) {
        throw new Error(PRODUCTION_API_BASE_URL_ERROR);
    }

    return LOCAL_API_BASE_URL;
}

const API_BASE_URL = resolveApiBaseUrl();

export { API_BASE_URL, LOCAL_API_BASE_URL, PRODUCTION_API_BASE_URL_ERROR, resolveApiBaseUrl };
