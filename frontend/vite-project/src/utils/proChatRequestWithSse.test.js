import test from 'node:test';
import assert from 'node:assert/strict';

import { handleProChatRequestWithSse } from './proChatRequestWithSse.js';

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
    'event: result\ndata: {"type":"result","answer":"Grounded answer.","answer_with_citations":[{"content_segments":[{"segment_text":"Grounded answer.","source_references":[{"file_chunk_id":"chunk-1"}]}]}],"raw_sources":[{"fileId":"file-1","chunkId":"chunk-1","source":"notes.pdf","pageNumber":5}],"result_reason":"no_relevant_documents"}\n\n',
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
    assert.equal(response.result.result_reason, 'no_relevant_documents');
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
    'event: result\ndata: {"type":"result","answer":"Sorry, this question cannot be answered reliably from the selected documents.","answer_with_citations":[],"raw_sources":[],"result_reason":"unsupported_question"}\n\n',
  ]);

  try {
    const response = await handleProChatRequestWithSse(
      [{ content: 'hi' }],
      {
        requestBody: { selectedFileIds: ['file-1'] },
        onProgress: (event) => progressEvents.push(event),
      },
    );

    assert.equal(response.result.result_reason, 'unsupported_question');
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
