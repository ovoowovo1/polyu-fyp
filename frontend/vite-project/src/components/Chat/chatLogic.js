export const EMPTY_COPY_WARNING = 'There is no text to copy.';
export const CHAT_REQUEST_ERROR_MESSAGE = 'Sorry, something went wrong. Please try again later.';

export function buildChatRequest({ userMessage, selectedFileIds = [], documentCount = 0 }) {
    return {
        messagesForAPI: [{ content: userMessage }],
        requestOptions: {
            requestBody: {
                selectedFileIds: selectedFileIds.length > 0 ? selectedFileIds : undefined,
                documentCount,
                selectedCount: selectedFileIds.length,
            },
        },
    };
}

export function parseChatResponseText(responseText) {
    try {
        return JSON.parse(responseText);
    } catch {
        return responseText;
    }
}

export function appendProgressMessage(progressMessages, progressEvent) {
    return [...progressMessages, progressEvent];
}

export function getAutofillChatPayload(event) {
    const text = event?.detail?.text || '';
    return {
        text,
        autoSend: Boolean(event?.detail?.send),
        hasText: typeof text === 'string' && text.trim().length > 0,
    };
}
