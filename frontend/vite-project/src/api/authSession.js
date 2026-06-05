const TOKEN_KEY = 'session_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

export const hasStorage = () => typeof localStorage !== 'undefined';

export const storeAuthSession = (data) => {
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

export const clearAuthSession = () => {
    if (!hasStorage()) return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
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
        } catch {
            return null;
        }
    }
    return null;
};

export const isAuthenticated = () => {
    return !!(getToken() || getRefreshToken());
};
