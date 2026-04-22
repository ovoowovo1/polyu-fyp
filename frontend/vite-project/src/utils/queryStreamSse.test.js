import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildStructuredContentFromResult,
  parseSseFrame,
  readSseStream,
  splitSseFrames,
} from './queryStreamSse.js';

const encoder = new TextEncoder();

const createStream = (chunks) => new ReadableStream({
  start(controller) {
    chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
    controller.close();
  },
});

test('splitSseFrames returns complete frames and trailing remainder', () => {
  const { frames, remainder } = splitSseFrames(
    'event: retrieval\r\ndata: {"type":"retrieval"}\r\n\r\nevent: grader\r\ndata: {"type":"grader"}',
  );

  assert.deepEqual(frames, [
    'event: retrieval\ndata: {"type":"retrieval"}',
  ]);
  assert.equal(remainder, 'event: grader\ndata: {"type":"grader"}');
});

test('parseSseFrame uses the event name when the payload has no type', () => {
  const parsed = parseSseFrame('event: rewrite\ndata: {"message":"retrying","data":1}');

  assert.deepEqual(parsed, {
    type: 'rewrite',
    message: 'retrying',
    data: 1,
  });
});

test('readSseStream reconstructs fragmented SSE frames and notifies listeners', async () => {
  const seen = [];
  const events = await readSseStream(createStream([
    'event: retrieval\ndata: {"type":"retrie',
    'val","message":"searching","data":2}\n\n',
    'event: result\ndata: {"type":"result","answer":"done","answer_with_citations":[],"raw_sources":[]}\n\n',
  ]), {
    onEvent: (event) => seen.push(event),
  });

  assert.equal(events.length, 2);
  assert.equal(events[0].type, 'retrieval');
  assert.equal(events[0].message, 'searching');
  assert.equal(events[1].type, 'result');
  assert.deepEqual(seen, events);
});

test('buildStructuredContentFromResult produces text and citation parts', () => {
  const structured = buildStructuredContentFromResult({
    answer: 'Grounded answer.',
    answer_with_citations: [
      {
        content_segments: [
          {
            segment_text: 'Grounded answer.',
            source_references: [{ file_chunk_id: 'chunk-1' }],
          },
        ],
      },
    ],
    raw_sources: [
      {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        pageNumber: 7,
      },
    ],
  });

  assert.deepEqual(structured, [
    { type: 'text', value: 'Grounded answer.' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        page: 7,
      },
    },
  ]);
});
