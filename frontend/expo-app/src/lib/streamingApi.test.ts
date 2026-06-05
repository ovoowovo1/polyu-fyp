import EventSource from 'react-native-sse';

import { setApiTokens } from '@/lib/apiClient';
import { askQuestion, subscribeUploadProgress } from '@/lib/streamingApi';

type MockEventSource = {
  url: string;
  options: { headers?: Record<string, string>; body?: string; method?: string };
  closed: boolean;
  emit: (type: string, event?: Record<string, unknown>) => void;
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: jest.fn(() => Promise.resolve(JSON.stringify(body))),
  } as unknown as Response;
}

function fetchMock() {
  return global.fetch as jest.MockedFunction<typeof fetch>;
}

function eventSources() {
  return (EventSource as unknown as { instances: MockEventSource[] }).instances;
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function waitForEventSourceCount(count: number) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (eventSources().length >= count) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
  }
  throw new Error(`Expected ${count} EventSource instances, got ${eventSources().length}`);
}

describe('streamingApi', () => {
  beforeEach(() => {
    setApiTokens(null, null);
    (EventSource as unknown as { reset: () => void }).reset();
  });

  it('refreshes and reconnects upload progress after an initial unauthorized stream error', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({
      session_token: 'new-access',
      access_token: 'new-access',
      refresh_token: 'new-refresh',
      user: { email: 'teacher@example.com', role: 'teacher' },
    }));

    const cleanup = subscribeUploadProgress('client-1', {});
    expect(eventSources()[0].options.headers?.Authorization).toBe('Bearer old-access');

    eventSources()[0].emit('error', { status: 401, message: 'unauthorized' });
    await waitForEventSourceCount(2);

    expect(eventSources()).toHaveLength(2);
    expect(eventSources()[0].closed).toBe(true);
    expect(eventSources()[1].options.headers?.Authorization).toBe('Bearer new-access');

    cleanup();
  });

  it('dispatches upload progress and finished events, and reports ordinary stream errors', () => {
    setApiTokens('access-token', 'refresh-token');
    const onProgress = jest.fn();
    const onFinished = jest.fn();
    const onError = jest.fn();

    const cleanup = subscribeUploadProgress('client-1', { onProgress, onFinished, onError });

    expect(eventSources()[0].url).toBe('http://localhost:3000/sse/progress?clientId=client-1');
    expect(eventSources()[0].options.headers?.Authorization).toBe('Bearer access-token');
    eventSources()[0].emit('message', {
      data: JSON.stringify({ type: 'progress', done: 1, total: 2 }),
    });
    eventSources()[0].emit('message', {
      data: JSON.stringify({ type: 'finished', status: 'success' }),
    });
    eventSources()[0].emit('error', { message: 'connection closed' });

    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ type: 'progress', done: 1, total: 2 }));
    expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ type: 'finished', status: 'success' }));
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', message: 'connection closed' }));

    cleanup();
    expect(eventSources()[0].closed).toBe(true);
  });

  it('refreshes and reconnects query stream after an initial unauthorized error', async () => {
    setApiTokens('old-access', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({
      session_token: 'new-access',
      access_token: 'new-access',
      refresh_token: 'new-refresh',
      user: { email: 'teacher@example.com', role: 'teacher' },
    }));

    const answer = askQuestion({
      question: 'What is RAG?',
      selectedFileIds: ['file-1'],
      documentCount: 1,
      selectedCount: 1,
    });

    expect(eventSources()[0].options.headers?.Authorization).toBe('Bearer old-access');
    eventSources()[0].emit('error', { status: 401, message: 'unauthorized' });
    await waitForEventSourceCount(2);

    expect(eventSources()).toHaveLength(2);
    expect(eventSources()[1].options.headers?.Authorization).toBe('Bearer new-access');
    eventSources()[1].emit('result', {
      data: JSON.stringify({
        answer: 'RAG combines retrieval and generation.',
        answer_with_citations: [],
      }),
    });

    await expect(answer).resolves.toEqual([
      { type: 'text', value: 'RAG combines retrieval and generation.' },
    ]);
  });

  it('sends query-stream request body, forwards progress, and parses citation result events', async () => {
    setApiTokens('access-token', 'refresh-token');
    const onProgress = jest.fn();

    const answer = askQuestion({
      question: 'Explain vectors',
      selectedFileIds: ['file-1'],
      documentCount: 2,
      selectedCount: 1,
      onProgress,
    });

    expect(eventSources()[0].url).toBe('http://localhost:3000/api/query-stream');
    expect(eventSources()[0].options.method).toBe('POST');
    expect(eventSources()[0].options.headers?.Authorization).toBe('Bearer access-token');
    expect(JSON.parse(String(eventSources()[0].options.body))).toEqual({
      question: 'Explain vectors',
      selectedFileIds: ['file-1'],
      documentCount: 2,
      selectedCount: 1,
    });

    eventSources()[0].emit('retrieval', {
      data: JSON.stringify({ type: 'retrieval', message: 'Searching' }),
    });
    eventSources()[0].emit('result', {
      data: JSON.stringify({
        answer: 'unused fallback',
        raw_sources: [{ chunkId: 'chunk-1', fileId: 'file-1', source: 'Doc.pdf', pageNumber: 2 }],
        answer_with_citations: [{
          content_segments: [{
            segment_text: 'Vectors store semantic meaning.',
            source_references: [{ file_chunk_id: 'chunk-1' }],
          }],
        }],
      }),
    });

    await expect(answer).resolves.toEqual([
      { type: 'text', value: 'Vectors store semantic meaning.' },
      {
        type: 'citation',
        number: 1,
        details: {
          chunkId: 'chunk-1',
          fileId: 'file-1',
          source: 'Doc.pdf',
          page: 2,
        },
      },
    ]);
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ type: 'retrieval', message: 'Searching' }));
    expect(eventSources()[0].closed).toBe(true);
  });

  it('rejects query stream ordinary errors without retrying when they are not unauthorized', async () => {
    setApiTokens('access-token', 'refresh-token');

    const answer = askQuestion({
      question: 'Will this fail?',
      documentCount: 0,
      selectedCount: 0,
    });

    eventSources()[0].emit('error', { message: 'network down' });

    await expect(answer).rejects.toThrow('network down');
    expect(eventSources()).toHaveLength(1);
    expect(eventSources()[0].closed).toBe(true);
  });
});
