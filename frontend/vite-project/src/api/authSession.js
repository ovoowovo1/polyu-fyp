const TOKEN_KEY = 'session_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

let accessToken = null;
let currentUser = null;

export const hasStorage = () => typeof localStorage !== 'undefined';

const clearLegacyStorage = () => {
    if (!hasStorage()) return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
};

export const storeAuthSession = (data) => {
    clearLegacyStorage();
    const nextAccessToken = data.access_token || data.session_token;
    if (nextAccessToken) {
        accessToken = nextAccessToken;
    }
    if (data.user) {
        currentUser = data.user;
    }
};

export const clearAuthSession = () => {
    accessToken = null;
    currentUser = null;
    clearLegacyStorage();
};

export const getToken = () => {
    return accessToken;
};

export const getRefreshToken = () => {
    return null;
};

export const getCurrentUser = () => {
    return currentUser;
};

export const isAuthenticated = () => {
    return !!getToken();
};
