import test from 'node:test';
import assert from 'node:assert/strict';

import { handleProChatRequestWithSse } from './proChatRequestWithSse.js';
import { clearAuthSession, storeAuthSession } from '../api/authSession.js';
import { API_BASE_URL } from '../config.js';
import { installAxiosMock } from '../testing/mockRuntime.js';

const encoder = new TextEncoder();

const createResponse = (chunks, status = 200, headers = { 'Content-Type': 'text/event-stream' }) => new Response(
  new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  }),
  {
    status,
    headers,
  },
);

test('handleProChatRequestWithSse forwards progress events and preserves final result metadata', async () => {
  const originalFetch = global.fetch;
  const progressEvents = [];

  global.fetch = async () => createResponse([
    'event: router\ndata: {"type":"router","message":"routing question"}\n\n',
    'event: retrieval\ndata: {"type":"retrieval","message":"retrieving documents","data":2}\n\n',
    'event: result\ndata: {"type":"result","status":"complete","blocks":[{"id":"b1","markdown":"Grounded answer.","source_ids":["chunk-1"]}],"sources":[{"chunk_id":"chunk-1","file_id":"file-1","name":"notes.pdf","page_start":5,"page_end":5,"content":"original evidence"}],"limitations":[],"trace_id":"trace-1"}\n\n',
  ]);

  try {
    const response = await handleProChatRequestWithSse(
      [{ content: 'Explain normalization' }],
      {
        requestBody: { selectedFileIds: ['file-1'] },
        onProgress: (event) => progressEvents.push(event),
      },
    );

    const content = JSON.parse(await response.text());

    assert.equal(progressEvents.length, 3);
    assert.deepEqual(progressEvents.map((event) => event.type), ['router', 'retrieval', 'result']);
    assert.equal(response.result.trace_id, 'trace-1');
    assert.deepEqual(content, [
      { type: 'text', value: 'Grounded answer.' },
      {
        type: 'citation',
        number: 1,
        details: {
          fileId: 'file-1',
          chunkId: 'chunk-1',
          source: 'notes.pdf',
          page: 5,
          pageEnd: 5,
          content: 'original evidence',
        },
      },
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse forwards rejected-route result events so progress can finish', async () => {
  const originalFetch = global.fetch;
  const progressEvents = [];

  global.fetch = async () => createResponse([
    'event: router\ndata: {"type":"router","message":"routing question"}\n\n',
    'event: result\ndata: {"type":"result","status":"unavailable","blocks":[{"id":"b1","markdown":"Sorry, this question cannot be answered reliably from the selected documents.","source_ids":[]}],"sources":[],"limitations":[],"trace_id":"trace-1"}\n\n',
  ]);

  try {
    const response = await handleProChatRequestWithSse(
      [{ content: 'hi' }],
      {
        requestBody: { selectedFileIds: ['file-1'] },
        onProgress: (event) => progressEvents.push(event),
      },
    );

    assert.equal(response.result.status, 'unavailable');
    assert.deepEqual(progressEvents.map((event) => event.type), ['router', 'result']);
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse returns backend 400 detail for fetch responses', async () => {
  const originalFetch = global.fetch;

  global.fetch = async () => new Response(
    JSON.stringify({ detail: { error: 'Please select at least one document for retrieval' } }),
    {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    },
  );

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);
    assert.equal(await response.text(), 'Please select at least one document for retrieval');
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse refreshes and retries when the stream request starts with 401', async () => {
  const originalFetch = global.fetch;
  storeAuthSession({ session_token: 'expired-access' });
  const fetchCalls = [];
  const refreshCalls = [];
  const axiosMock = installAxiosMock({
    post: async (url, body, config) => {
      refreshCalls.push({ url, body, config });
      return {
        data: {
          session_token: 'new-access',
          access_token: 'new-access',
        },
      };
    },
  });

  global.fetch = async (url, init) => {
    fetchCalls.push({ url, auth: init.headers.get('Authorization') });
    if (fetchCalls.length === 1) {
      return new Response(JSON.stringify({ detail: { error: 'Token expired' } }), { status: 401 });
    }
    return createResponse([
      'event: result\ndata: {"type":"result","status":"unavailable","blocks":[{"id":"b1","markdown":"Fresh answer.","source_ids":[]}],"sources":[],"limitations":[],"trace_id":"trace-1"}\n\n',
    ]);
  };

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);

    assert.equal(JSON.parse(await response.text())[0].value, 'Fresh answer.');
    assert.deepEqual(refreshCalls, [
      {
        url: `${API_BASE_URL}/auth/refresh`,
        body: {},
        config: { withCredentials: true },
      },
    ]);
    assert.deepEqual(fetchCalls, [
      {
        url: `${API_BASE_URL}/api/query-stream`,
        auth: 'Bearer expired-access',
      },
      {
        url: `${API_BASE_URL}/api/query-stream`,
        auth: 'Bearer new-access',
      },
    ]);
  } finally {
    global.fetch = originalFetch;
    clearAuthSession();
    axiosMock.restore();
  }
});

test('handleProChatRequestWithSse returns a service unavailable message for 503 responses', async () => {
  const originalFetch = global.fetch;

  global.fetch = async () => new Response('', { status: 503 });

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);
    assert.equal(await response.text(), 'Service temporarily unavailable, please try again later.');
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse falls back when the response body is not readable', async () => {
  const originalFetch = global.fetch;

  global.fetch = async () => ({
    ok: true,
    body: null,
  });

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);
    assert.equal(await response.text(), 'Sorry, something went wrong. Please try again later.');
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse falls back when the stream never returns a final result', async () => {
  const originalFetch = global.fetch;

  global.fetch = async () => createResponse([
    'event: router\ndata: {"type":"router","message":"routing question"}\n\n',
    'event: retrieval\ndata: {"type":"retrieval","message":"retrieving documents"}\n\n',
  ]);

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);
    assert.equal(await response.text(), 'Sorry, something went wrong. Please try again later.');
  } finally {
    global.fetch = originalFetch;
  }
});

test('handleProChatRequestWithSse returns a network error message for fetch failures', async () => {
  const originalFetch = global.fetch;

  global.fetch = async () => {
    throw new TypeError('Failed to fetch');
  };

  try {
    const response = await handleProChatRequestWithSse([{ content: 'Explain normalization' }]);
    assert.equal(await response.text(), 'Network connection error, please check your network settings.');
  } finally {
    global.fetch = originalFetch;
  }
});
