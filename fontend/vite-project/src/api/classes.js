import axios from 'axios';
import { API_BASE_URL } from '../config.js';
import { getToken } from './auth';
import i18n from '../i18n/config';

export const listMyClasses = async () => {
    const token = getToken();
    if (!token) throw new Error(i18n.t('auth.notLoggedIn'));
    const res = await axios.get(`${API_BASE_URL}/classes/mine`, {
        headers: { Authorization: `Bearer ${token}` }
    });
    return res.data;
};

export const listMyEnrolledClasses = async () => {
    const token = getToken();
    if (!token) throw new Error(i18n.t('auth.notLoggedIn'));
    const res = await axios.get(`${API_BASE_URL}/classes/enrolled`, {
        headers: { Authorization: `Bearer ${token}` }
    });
    return res.data;
};

export const createClass = async (name) => {
    const token = getToken();
    if (!token) throw new Error(i18n.t('auth.notLoggedIn'));
    const res = await axios.post(`${API_BASE_URL}/classes/`, { name }, {
        headers: { Authorization: `Bearer ${token}` }
    });
    return res.data;
};

export const inviteStudent = async (classId, email) => {
    const token = getToken();
    if (!token) throw new Error(i18n.t('auth.notLoggedIn'));
    const res = await axios.post(`${API_BASE_URL}/classes/${classId}/invite`, { email }, {
        headers: { Authorization: `Bearer ${token}` }
    });
    return res.data;
};


