import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  buildStructuredContentFromResult,
  parseSseFrame,
  readSseStream,
  splitSseFrames,
} from './queryStreamSse.js';

const encoder = new TextEncoder();
const cases = JSON.parse(readFileSync(new URL('../../../shared-test-data/rag-display.json', import.meta.url), 'utf8'));

for (const { id, result } of cases) {
  test(`RAG display preserves every block and source: ${id}`, () => {
    const parts = buildStructuredContentFromResult(result);
    assert.deepEqual(parts.filter(p => p.type === 'text').map(p => p.value), result.blocks.map(b => b.markdown));
    const order = [...new Set(result.blocks.flatMap(b => b.source_ids))];
    for (const part of parts.filter(p => p.type === 'citation')) {
      assert.equal(part.number, order.indexOf(part.details.chunkId) + 1);
      assert.equal(part.details.content, result.sources.find(s => s.chunk_id === part.details.chunkId).content);
    }
  });
}

test('RAG display rejects missing sources and old payloads instead of losing content', () => {
  assert.throws(() => buildStructuredContentFromResult({ answer: 'old' }));
  const result = structuredClone(cases[0].result);
  result.sources = [];
  assert.throws(() => buildStructuredContentFromResult(result), /source is missing/);
  result.blocks = [{ id: 'b', markdown: 'literal array [1, 2]', source_ids: [] }];
  assert.equal(buildStructuredContentFromResult(result)[0].value, 'literal array [1, 2]');
});

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
    'event: result\ndata: {"type":"result","status":"unavailable","blocks":[],"sources":[],"limitations":[],"trace_id":"t"}\n\n',
  ]), {
    onEvent: (event) => seen.push(event),
  });

  assert.equal(events.length, 2);
  assert.equal(events[0].type, 'retrieval');
  assert.equal(events[0].message, 'searching');
  assert.equal(events[1].type, 'result');
  assert.deepEqual(seen, events);
});
