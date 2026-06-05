import axios from 'axios';

import { API_BASE_URL } from '../config.js';
import {
    clearAuthSession,
    getRefreshToken,
    getToken,
    storeAuthSession,
} from './authSession.js';

let refreshPromise = null;

export const extractErrorMessage = (error, fallback) => {
    if (error.response) {
        return error.response.data?.error || error.response.data?.detail?.error || fallback;
    }
    if (error.request) {
        return 'Network connection failed. Please check your server connection.';
    }
    return `${fallback}: ${error.message}`;
};

export const withAuthConfig = (axiosConfig = {}) => {
    const token = getToken();
    const headers = {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(axiosConfig.headers || {}),
    };
    return {
        ...axiosConfig,
        ...(Object.keys(headers).length > 0 ? { headers } : {}),
    };
};

const isUnauthorized = (errorOrResponse) => (
    errorOrResponse?.response?.status === 401 || errorOrResponse?.status === 401
);

const isAuthPath = (path) => {
    const value = String(path);
    return value.startsWith('/auth/') || value.startsWith(`${API_BASE_URL}/auth/`);
};

export const refreshAccessToken = async () => {
    const refreshTokenValue = getRefreshToken();
    if (!refreshTokenValue) {
        throw new Error('Refresh token missing');
    }

    if (!refreshPromise) {
        refreshPromise = axios.post(`${API_BASE_URL}/auth/refresh`, {
            refresh_token: refreshTokenValue,
        }).then((response) => {
            storeAuthSession(response.data);
            return response.data;
        }).catch((error) => {
            clearAuthSession();
            throw error;
        }).finally(() => {
            refreshPromise = null;
        });
    }

    return refreshPromise;
};

const requestWithRetry = async (method, path, body, config = {}, retryOnUnauthorized = true) => {
    const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
    const requestConfig = withAuthConfig(config);

    try {
        if (method === 'get' || method === 'delete') {
            return await axios[method](url, requestConfig);
        }
        return await axios[method](url, body, requestConfig);
    } catch (error) {
        if (!retryOnUnauthorized || !isUnauthorized(error) || isAuthPath(path)) {
            throw error;
        }
        await refreshAccessToken();
        return requestWithRetry(method, path, body, config, false);
    }
};

export const apiGet = (path, config = {}) => requestWithRetry('get', path, undefined, config);
export const apiDelete = (path, config = {}) => requestWithRetry('delete', path, undefined, config);
export const apiPost = (path, body, config = {}) => requestWithRetry('post', path, body, config);
export const apiPut = (path, body, config = {}) => requestWithRetry('put', path, body, config);

const fetchWithRetry = async (path, init = {}, retryOnUnauthorized = true) => {
    const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
    const headers = new Headers(init.headers);
    const token = getToken();
    if (token) {
        headers.set('Authorization', `Bearer ${token}`);
    }

    const response = await fetch(url, { ...init, headers });
    if (response.ok || !retryOnUnauthorized || response.status !== 401 || isAuthPath(path)) {
        return response;
    }

    await refreshAccessToken();
    return fetchWithRetry(path, init, false);
};

export const apiFetch = (path, init = {}) => fetchWithRetry(path, init);
