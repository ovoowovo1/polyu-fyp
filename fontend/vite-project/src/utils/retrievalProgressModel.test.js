import test from 'node:test';
import assert from 'node:assert/strict';

import {
  STAGE_ORDER,
  buildRetrievalProgressModel,
  normalizeProgressType,
} from './retrievalProgressModel.js';

const t = (key, params = {}) => {
  if (key === 'retrieval.attempt') {
    return `attempt ${params.count}`;
  }
  return key;
};

test('normalizeProgressType maps legacy event names to adaptive stages', () => {
  assert.equal(normalizeProgressType('vectorProgress'), 'retrieval');
  assert.equal(normalizeProgressType('fulltextProgress'), 'retrieval');
  assert.equal(normalizeProgressType('aiProgress'), 'generation');
  assert.equal(normalizeProgressType('grader'), 'grader');
});

test('buildRetrievalProgressModel tracks adaptive stage progression to completion', () => {
  const model = buildRetrievalProgressModel([
    { type: 'router', message: 'routing question' },
    { type: 'retrieval', message: 'retrieving documents', data: 4 },
    { type: 'grader', message: 'grading documents', data: 2 },
    { type: 'rewrite', message: 'rewriting query', data: 1 },
    { type: 'generation', message: 'generating answer' },
    { type: 'result', message: 'finished' },
  ], t);

  assert.deepEqual(model.stages.map((stage) => stage.key), STAGE_ORDER);
  assert.equal(model.isCompleted, true);
  assert.equal(model.percent, 100);
  assert.equal(model.stages.find((stage) => stage.key === 'retrieval').hits, 4);
  assert.equal(model.stages.find((stage) => stage.key === 'grader').hits, 2);
  assert.equal(model.stages.find((stage) => stage.key === 'rewrite').count, 1);
  assert.equal(model.stages.find((stage) => stage.key === 'generation').status, 'completed');
});

test('buildRetrievalProgressModel leaves rewrite idle when no rewrite event occurs', () => {
  const model = buildRetrievalProgressModel([
    { type: 'vectorProgress', message: 'vector search complete', data: 3 },
    { type: 'aiProgress', message: 'answer generation started' },
    { type: 'result', message: 'finished' },
  ], t);

  assert.equal(model.isCompleted, true);
  assert.equal(model.percent, 100);
  assert.equal(model.stages.find((stage) => stage.key === 'rewrite').status, 'waiting');
  assert.equal(model.latestMessage, 'answer generation started');
});
