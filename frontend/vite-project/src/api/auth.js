import axios from 'axios';
import { API_BASE_URL } from '../config.js';
import { extractErrorMessage, refreshAccessToken } from './apiClient.js';
import {
    clearAuthSession,
    getCurrentUser,
    getRefreshToken,
    getToken,
    isAuthenticated,
    storeAuthSession,
} from './authSession.js';

export const login = async (email, password, role = null) => {
    try {
        const body = { email, password };
        if (role) body.role = role;
        const response = await axios.post(`${API_BASE_URL}/auth/login`, body, {
            withCredentials: true,
        });
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
    return refreshAccessToken();
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
            withCredentials: true,
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
    clearAuthSession();
    void axios.post(`${API_BASE_URL}/auth/logout`, {}, {
        withCredentials: true,
    }).catch(() => {});
};

export { getCurrentUser, getRefreshToken, getToken, isAuthenticated };
