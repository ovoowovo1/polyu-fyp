import { apiGet, apiPost } from './apiClient.js';
import { isAuthenticated } from './auth.js';
import i18n from '../i18n/config.js';

const requireAuth = () => {
    if (!isAuthenticated()) throw new Error(i18n.t('auth.notLoggedIn'));
};

export const listMyClasses = async () => {
    requireAuth();
    const res = await apiGet('/classes/mine');
    return res.data;
};

export const listMyEnrolledClasses = async () => {
    requireAuth();
    const res = await apiGet('/classes/enrolled');
    return res.data;
};

export const createClass = async (name) => {
    requireAuth();
    const res = await apiPost('/classes/', { name });
    return res.data;
};

export const inviteStudent = async (classId, email) => {
    requireAuth();
    const res = await apiPost(`/classes/${classId}/invite`, { email });
    return res.data;
};
