import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildStructuredContentFromResult,
  buildStructuredContentFromTextCitations,
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

test('buildStructuredContentFromTextCitations parses a single bracket citation', () => {
  const structured = buildStructuredContentFromTextCitations(
    'Known fact [1] and more text.',
    [
      {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        pageNumber: 2,
      },
    ],
  );

  assert.deepEqual(structured, [
    { type: 'text', value: 'Known fact ' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        page: 2,
      },
    },
    { type: 'text', value: ' and more text.' },
  ]);
});

test('buildStructuredContentFromTextCitations parses multiple citations in one bracket', () => {
  const structured = buildStructuredContentFromTextCitations(
    'Line one [1, 2, 2]\nLine two.',
    [
      {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        pageNumber: 2,
      },
      {
        fileId: 'file-2',
        chunkId: 'chunk-2',
        source: 'slides.pdf',
        pageNumber: 5,
      },
    ],
  );

  assert.deepEqual(structured, [
    { type: 'text', value: 'Line one ' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        page: 2,
      },
    },
    {
      type: 'citation',
      number: 2,
      details: {
        fileId: 'file-2',
        chunkId: 'chunk-2',
        source: 'slides.pdf',
        page: 5,
      },
    },
    { type: 'text', value: '\nLine two.' },
  ]);
});

test('buildStructuredContentFromResult keeps answer_with_citations as the priority path', () => {
  const structured = buildStructuredContentFromResult({
    answer: 'Plain fallback [1]',
    answer_with_citations: [
      {
        content_segments: [
          {
            segment_text: 'Structured answer.',
            source_references: [{ file_chunk_id: 'chunk-9' }],
          },
        ],
      },
    ],
    raw_sources: [
      {
        fileId: 'file-9',
        chunkId: 'chunk-9',
        source: 'handbook.pdf',
        pageNumber: 11,
      },
    ],
  });

  assert.deepEqual(structured, [
    { type: 'text', value: 'Structured answer.' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-9',
        chunkId: 'chunk-9',
        source: 'handbook.pdf',
        page: 11,
      },
    },
  ]);
});

test('buildStructuredContentFromResult merges inline citations with incomplete structured references', () => {
  const structured = buildStructuredContentFromResult({
    answer: 'Fallback [1, 2]',
    answer_with_citations: [
      {
        content_segments: [
          {
            segment_text: 'Task explanation.',
            source_references: [
              { file_chunk_id: 'chunk-1' },
            ],
          },
          {
            segment_text: 'Released later [1, 2], and additional hours will be provided.',
            source_references: [
              { file_chunk_id: 'chunk-2' },
            ],
          },
        ],
      },
    ],
    raw_sources: [
      {
        fileId: 'file-2',
        chunkId: 'chunk-2',
        source: 'slides.pdf',
        pageNumber: 4,
      },
      {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        pageNumber: 3,
      },
    ],
  });

  assert.deepEqual(structured, [
    { type: 'text', value: 'Task explanation.' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        page: 3,
      },
    },
    { type: 'text', value: 'Released later, and additional hours will be provided.' },
    {
      type: 'citation',
      number: 1,
      details: {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        page: 3,
      },
    },
    {
      type: 'citation',
      number: 2,
      details: {
        fileId: 'file-2',
        chunkId: 'chunk-2',
        source: 'slides.pdf',
        page: 4,
      },
    },
  ]);
});

test('buildStructuredContentFromTextCitations leaves invalid citations as plain text', () => {
  const structured = buildStructuredContentFromTextCitations(
    'Example [1, 3] should stay plain text.',
    [
      {
        fileId: 'file-1',
        chunkId: 'chunk-1',
        source: 'notes.pdf',
        pageNumber: 2,
      },
    ],
  );

  assert.deepEqual(structured, [
    { type: 'text', value: 'Example [1, 3] should stay plain text.' },
  ]);
});
