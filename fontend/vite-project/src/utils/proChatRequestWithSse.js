import { API_BASE_URL } from '../config.js';
import {
  buildStructuredContentFromResult,
  readSseStream,
} from './queryStreamSse.js';

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
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    if (!response.body) {
      throw new Error('Response body is not readable.');
    }

    let finalResult = null;
    await readSseStream(response.body, {
      onEvent: (event) => {
        if (event?.type === 'result') {
          finalResult = event;
          return;
        }

        if (onProgress) {
          onProgress(event);
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

    let errorMessage = 'Sorry, something went wrong. Please try again later.';
    if (error.response?.status === 503) {
      errorMessage = 'Service temporarily unavailable, please try again later.';
    } else if (error.response?.status === 400) {
      errorMessage = error.response.data?.error || 'Request format error.';
    } else if (error.code === 'NETWORK_ERROR') {
      errorMessage = 'Network connection error, please check your network settings.';
    }

    return {
      text: () => Promise.resolve(errorMessage),
    };
  }
};
