import axios from 'axios';
import { API_BASE_URL } from '../config.js';

/**
 * 登入 API
 * @param {string} email - 用戶郵箱
 * @param {string} password - 密碼
 * @returns {Promise} 返回登入結果，包含 session_token 和用戶信息
 */
export const login = async (email, password, role = null) => {
    try {
        const body = { email, password };
        if (role) body.role = role;
        const response = await axios.post(`${API_BASE_URL}/auth/login`, body);

        // 如果登入成功，將 session_token 存儲到 localStorage
        if (response.data.session_token) {
            localStorage.setItem('session_token', response.data.session_token);
            localStorage.setItem('user', JSON.stringify(response.data.user));
        }

        return response.data;
    } catch (error) {
        // 處理錯誤響應
        if (error.response) {
            // 服務器返回了錯誤狀態碼
            const errorMessage = error.response.data?.error || error.response.data?.detail?.error || '登入失敗';
            throw new Error(errorMessage);
        } else if (error.request) {
            // 請求已發送但沒有收到響應
            throw new Error('無法連接到服務器，請檢查網絡連接');
        } else {
            // 請求設置時出錯
            throw new Error('登入請求失敗：' + error.message);
        }
    }
};

/**
 * 註冊 API
 * @param {string} email - 用戶郵箱
 * @param {string} password - 密碼
 * @param {string} fullName - 用戶全名
 * @param {string} role - 用戶角色 ('student' 或 'teacher')
 * @returns {Promise} 返回註冊結果
 */
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
        if (error.response) {
            const errorMessage = error.response.data?.error || error.response.data?.detail?.error || '註冊失敗';
            throw new Error(errorMessage);
        } else if (error.request) {
            throw new Error('無法連接到服務器，請檢查網絡連接');
        } else {
            throw new Error('註冊請求失敗：' + error.message);
        }
    }
};

/**
 * 驗證 token 是否有效
 * @returns {Promise} 返回驗證結果
 */
export const verifyToken = async () => {
    try {
        const token = localStorage.getItem('session_token');
        if (!token) {
            throw new Error('未找到 token');
        }

        const response = await axios.get(`${API_BASE_URL}/auth/verify`, {
            headers: {
                Authorization: `Bearer ${token}`,
            },
        });
        return response.data;
    } catch (error) {
        // 如果 token 無效，清除存儲
        logout();
        if (error.response) {
            const errorMessage = error.response.data?.error || error.response.data?.detail?.error || 'Token 驗證失敗';
            throw new Error(errorMessage);
        } else {
            throw new Error('Token 驗證失敗：' + error.message);
        }
    }
};

/**
 * 登出，清除本地存儲的 token 和用戶信息
 */
export const logout = () => {
    localStorage.removeItem('session_token');
    localStorage.removeItem('user');
};

/**
 * 獲取當前存儲的 token
 * @returns {string|null} 返回 token 或 null
 */
export const getToken = () => {
    return localStorage.getItem('session_token');
};

/**
 * 獲取當前存儲的用戶信息
 * @returns {object|null} 返回用戶信息或 null
 */
export const getCurrentUser = () => {
    const userStr = localStorage.getItem('user');
    if (userStr) {
        try {
            return JSON.parse(userStr);
        } catch (e) {
            return null;
        }
    }
    return null;
};

/**
 * 檢查用戶是否已登入
 * @returns {boolean} 返回是否已登入
 */
export const isAuthenticated = () => {
    return !!getToken();
};
