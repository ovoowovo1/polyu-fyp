import { API_BASE_URL } from '../config.js';
import {
  buildStructuredContentFromResult,
  readSseStream,
} from './queryStreamSse.js';

const DEFAULT_ERROR_MESSAGE = 'Sorry, something went wrong. Please try again later.';
const SERVICE_UNAVAILABLE_MESSAGE = 'Service temporarily unavailable, please try again later.';
const REQUEST_FORMAT_ERROR_MESSAGE = 'Request format error.';
const NETWORK_ERROR_MESSAGE = 'Network connection error, please check your network settings.';

const createTextOnlyResponse = (message) => ({
  text: () => Promise.resolve(message),
});

const extractErrorMessage = async (response) => {
  const fallbackByStatus = {
    400: REQUEST_FORMAT_ERROR_MESSAGE,
    503: SERVICE_UNAVAILABLE_MESSAGE,
  };

  let payload;
  try {
    payload = await response.clone().json();
  } catch {
    try {
      payload = await response.clone().text();
    } catch {
      payload = null;
    }
  }

  if (response.status === 400 && payload && typeof payload === 'object') {
    const detail = payload.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === 'object' && typeof detail.error === 'string' && detail.error.trim()) {
      return detail.error;
    }
    if (typeof payload.error === 'string' && payload.error.trim()) {
      return payload.error;
    }
  }

  if (typeof payload === 'string' && payload.trim()) {
    return payload;
  }

  return fallbackByStatus[response.status] || DEFAULT_ERROR_MESSAGE;
};

export const handleProChatRequestWithSse = async (messages, options = {}) => {
  const { requestBody = {}, onProgress } = options;

  try {
    const lastMessage = messages[messages.length - 1];
    const userQuestion = lastMessage?.content;

    if (!userQuestion) {
      throw new Error('Missing user question.');
    }

    const requestData = {
      question: userQuestion,
      ...requestBody,
    };

    const response = await fetch(`${API_BASE_URL}/api/query-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(requestData),
    });

    if (!response.ok) {
      return createTextOnlyResponse(await extractErrorMessage(response));
    }
    if (!response.body) {
      throw new Error('Response body is not readable.');
    }

    let finalResult = null;
    await readSseStream(response.body, {
      onEvent: (event) => {
        if (onProgress) {
          onProgress(event);
        }

        if (event?.type === 'result') {
          finalResult = event;
        }
      },
    });

    if (!finalResult) {
      throw new Error('No final result was returned from the query stream.');
    }

    const structuredContent = buildStructuredContentFromResult(finalResult);
    return {
      result: finalResult,
      text: () => Promise.resolve(JSON.stringify(structuredContent)),
    };
  } catch (error) {
    console.error('ProChat SSE request failed:', error);

    const isNetworkError = error instanceof TypeError
      || String(error?.message || '').toLowerCase().includes('network');

    return createTextOnlyResponse(
      isNetworkError ? NETWORK_ERROR_MESSAGE : DEFAULT_ERROR_MESSAGE,
    );
  }
};
