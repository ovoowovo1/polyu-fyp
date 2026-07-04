import { apiGet, apiPost } from './apiClient.js';
import { isAuthenticated } from './auth.js';
import i18n from '../i18n/config.js';
import { clearDedupeCache, dedupe } from '../utils/requestDeduper.js';

const CLASS_LIST_DEDUPE_TTL_MS = 500;
const MY_CLASSES_KEY = 'classes:mine';
const ENROLLED_CLASSES_KEY = 'classes:enrolled';

const requireAuth = () => {
    if (!isAuthenticated()) throw new Error(i18n.t('auth.notLoggedIn'));
};

export const listMyClasses = async () => {
    requireAuth();
    return dedupe(MY_CLASSES_KEY, async () => {
        const res = await apiGet('/classes/mine');
        return res.data;
    }, { ttl: CLASS_LIST_DEDUPE_TTL_MS });
};

export const listMyEnrolledClasses = async () => {
    requireAuth();
    return dedupe(ENROLLED_CLASSES_KEY, async () => {
        const res = await apiGet('/classes/enrolled');
        return res.data;
    }, { ttl: CLASS_LIST_DEDUPE_TTL_MS });
};

export const createClass = async (name) => {
    requireAuth();
    const res = await apiPost('/classes/', { name });
    clearDedupeCache(MY_CLASSES_KEY);
    return res.data;
};

export const inviteStudent = async (classId, email) => {
    requireAuth();
    const res = await apiPost(`/classes/${classId}/invite`, { email });
    clearDedupeCache(MY_CLASSES_KEY);
    return res.data;
};
