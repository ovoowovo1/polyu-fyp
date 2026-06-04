import axios from 'axios';
import { API_BASE_URL } from '../config.js';

const TOKEN_KEY = 'session_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

const hasStorage = () => typeof localStorage !== 'undefined';

const extractErrorMessage = (error, fallback) => {
    if (error.response) {
        return error.response.data?.error || error.response.data?.detail?.error || fallback;
    }
    if (error.request) {
        return 'Network connection failed. Please check your server connection.';
    }
    return `${fallback}: ${error.message}`;
};

const storeAuthSession = (data) => {
    if (!hasStorage()) return;

    const accessToken = data.access_token || data.session_token;
    if (accessToken) {
        localStorage.setItem(TOKEN_KEY, accessToken);
    }
    if (data.refresh_token) {
        localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    }
    if (data.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    }
};

const clearAuthSession = () => {
    if (!hasStorage()) return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
};

export const login = async (email, password, role = null) => {
    try {
        const body = { email, password };
        if (role) body.role = role;
        const response = await axios.post(`${API_BASE_URL}/auth/login`, body);
        storeAuthSession(response.data);
        return response.data;
    } catch (error) {
        throw new Error(extractErrorMessage(error, 'Login failed'));
    }
};

export const register = async (email, password, fullName, role = 'student') => {
    try {
        const response = await axios.post(`${API_BASE_URL}/auth/register`, {
            email,
            password,
            full_name: fullName,
            role,
        });
        return response.data;
    } catch (error) {
        throw new Error(extractErrorMessage(error, 'Register failed'));
    }
};

export const refreshToken = async () => {
    const refreshTokenValue = getRefreshToken();
    if (!refreshTokenValue) {
        throw new Error('Refresh token missing');
    }

    const response = await axios.post(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refreshTokenValue,
    });
    storeAuthSession(response.data);
    return response.data;
};

export const verifyToken = async () => {
    const token = getToken();
    if (!token) {
        try {
            return await refreshToken();
        } catch (error) {
            logout();
            throw new Error(extractErrorMessage(error, 'Token verification failed'));
        }
    }

    try {
        const response = await axios.get(`${API_BASE_URL}/auth/verify`, {
            headers: {
                Authorization: `Bearer ${token}`,
            },
        });
        return response.data;
    } catch (error) {
        try {
            return await refreshToken();
        } catch (refreshError) {
            logout();
            throw new Error(extractErrorMessage(refreshError, extractErrorMessage(error, 'Token verification failed')));
        }
    }
};

export const logout = () => {
    const refreshTokenValue = getRefreshToken();
    clearAuthSession();
    if (refreshTokenValue) {
        void axios.post(`${API_BASE_URL}/auth/logout`, {
            refresh_token: refreshTokenValue,
        }).catch(() => {});
    }
};

export const getToken = () => {
    if (!hasStorage()) {
        return null;
    }
    return localStorage.getItem(TOKEN_KEY);
};

export const getRefreshToken = () => {
    if (!hasStorage()) {
        return null;
    }
    return localStorage.getItem(REFRESH_TOKEN_KEY);
};

export const getCurrentUser = () => {
    if (!hasStorage()) {
        return null;
    }
    const userStr = localStorage.getItem(USER_KEY);
    if (userStr) {
        try {
            return JSON.parse(userStr);
        } catch (e) {
            return null;
        }
    }
    return null;
};

export const isAuthenticated = () => {
    return !!(getToken() || getRefreshToken());
};
