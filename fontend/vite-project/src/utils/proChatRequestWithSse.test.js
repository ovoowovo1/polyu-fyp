import test from 'node:test';
import assert from 'node:assert/strict';

import { handleProChatRequestWithSse } from './proChatRequestWithSse.js';

const encoder = new TextEncoder();

const createResponse = (chunks, status = 200) => new Response(
  new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  }),
  {
    status,
    headers: {
      'Content-Type': 'text/event-stream',
    },
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

    assert.equal(progressEvents.length, 2);
    assert.deepEqual(progressEvents.map((event) => event.type), ['router', 'retrieval']);
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
