import i18n from '../i18n/config.js';
import { apiPost } from '../api/apiClient.js';
import { buildStructuredContentFromResult } from './queryStreamSse.js';

const FALLBACK_MESSAGE = 'Sorry, something went wrong. Please try again later.';
const SERVICE_UNAVAILABLE_MESSAGE = 'Service temporarily unavailable, please try again later.';
const REQUEST_FORMAT_ERROR_MESSAGE = 'Request format error.';
const NETWORK_ERROR_MESSAGE = 'Network connection error, please check your network settings.';

const textResponse = (message, status = 200) => new Response(message, {
    status,
    headers: { 'Content-Type': 'text/plain' },
});

const extractQueryErrorMessage = (error) => {
    if (error.response?.status === 503) {
        return SERVICE_UNAVAILABLE_MESSAGE;
    }
    if (error.response?.status === 400) {
        return error.response.data?.error
            || error.response.data?.detail?.error
            || REQUEST_FORMAT_ERROR_MESSAGE;
    }
    if (error.code === 'NETWORK_ERROR' || error.request) {
        return NETWORK_ERROR_MESSAGE;
    }
    return FALLBACK_MESSAGE;
};

export const handleProChatRequest = async (messages, options = {}) => {
    const userQuestion = messages[messages.length - 1]?.content;
    if (!userQuestion) {
        return textResponse(FALLBACK_MESSAGE, 400);
    }

    try {
        const response = await apiPost('/query', {
            question: userQuestion,
            ...options.requestBody,
        });

        return new Response(JSON.stringify(buildStructuredContentFromResult(response.data)), {
            headers: { 'Content-Type': 'application/json' },
        });
    } catch (error) {
        return textResponse(extractQueryErrorMessage(error), error.response?.status || 500);
    }
};

export const generateWelcomeMessage = (documentCount, selectedCount = 0) => {
    if (documentCount === 0) {
        return i18n.t('chat.welcomeNoDocuments');
    }

    let baseMessage = i18n.t('chat.welcomeWithDocuments', { count: documentCount });

    if (selectedCount > 0 && selectedCount < documentCount) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedPartial', { count: selectedCount })}`;
    } else if (selectedCount === documentCount && documentCount > 1) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedAll')}`;
    } else {
        baseMessage += `\n\n${i18n.t('chat.welcomeNoSelection')}`;
    }

    return `${baseMessage}\n\n${i18n.t('chat.welcomeAskQuestions')}`;
};
