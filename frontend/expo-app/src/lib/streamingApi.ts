import EventSource, { type EventSourceListener } from 'react-native-sse';

import {
  API_BASE_URL,
  QUERY_TIMEOUT_MS,
  authHeaders,
  getApiRefreshToken,
  isUnauthorizedEvent,
  parseEventSourceData,
  refreshSession,
} from '@/lib/apiClient';
import type { ProgressEvent, StructuredPart } from '@/lib/types';

type QueryStreamEvent = 'retrieval' | 'grader' | 'router' | 'generation' | 'progress' | 'result';

export function subscribeUploadProgress(
  clientId: string,
  handlers: {
    onProgress?: (event: ProgressEvent) => void;
    onFinished?: (event: ProgressEvent) => void;
    onError?: (event: ProgressEvent) => void;
  },
) {
  let eventSource: EventSource<string> | null = null;
  let closed = false;
  let retriedUnauthorized = false;

  const onMessage = (event: { data?: string | null; type?: string }) => {
    const parsed = parseEventSourceData(event);
    const type = String(parsed.type || event.type || 'message');

    if (type === 'progress' || type === 'keepalive') {
      handlers.onProgress?.({ type, ...parsed });
      return;
    }

    if (type === 'finished') {
      handlers.onFinished?.({ type, ...parsed });
    }
  };

  const onError: EventSourceListener<string, 'error'> = async (event) => {
    const refreshToken = getApiRefreshToken();
    if (!closed && !retriedUnauthorized && refreshToken && isUnauthorizedEvent(event)) {
      retriedUnauthorized = true;
      eventSource?.removeAllEventListeners();
      eventSource?.close();
      try {
        await refreshSession(refreshToken);
        if (!closed) {
          connect();
        }
      } catch {
        handlers.onError?.({
          type: 'error',
          message: 'Upload stream authentication expired.',
        });
      }
      return;
    }

    handlers.onError?.({
      type: 'error',
      message: 'message' in event && typeof event.message === 'string' ? event.message : 'Upload stream failed.',
    });
  };

  const connect = () => {
    const headers = authHeaders();
    eventSource = new EventSource(`${API_BASE_URL}/sse/progress?clientId=${encodeURIComponent(clientId)}`, {
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      pollingInterval: 0,
    });
    eventSource.addEventListener('message', onMessage);
    eventSource.addEventListener('error', onError);
  };

  connect();

  return () => {
    closed = true;
    eventSource?.removeAllEventListeners();
    eventSource?.close();
  };
}

export async function askQuestion({
  question,
  selectedFileIds,
  documentCount,
  selectedCount,
  onProgress,
}: {
  question: string;
  selectedFileIds?: string[];
  documentCount: number;
  selectedCount: number;
  onProgress?: (event: ProgressEvent) => void;
}): Promise<StructuredPart[]> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let eventSource: EventSource<QueryStreamEvent> | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const cleanup = () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      eventSource?.removeAllEventListeners();
      eventSource?.close();
    };

    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const succeed = (result: Record<string, unknown>) => {
      if (settled) return;
      try {
        const parts = buildStructuredContentFromResult(result);
        settled = true;
        cleanup();
        resolve(parts);
      } catch (error) {
        fail(error instanceof Error ? error : new Error('Invalid RAG result.'));
      }
    };

    const handleProgressEvent = (event: { data?: string | null; type?: string }) => {
      const parsed = parseEventSourceData(event);
      onProgress?.({
        type: String(parsed.type || event.type || 'progress'),
        ...parsed,
      });
    };

    const handleResultEvent = (event: { data?: string | null; type?: string }) => {
      const parsed = parseEventSourceData(event);
      if (parsed && typeof parsed === 'object') {
        succeed({ type: 'result', ...parsed });
        return;
      }
      fail(new Error('Invalid answer format returned from the server.'));
    };

    const connect = (retryOnUnauthorized: boolean) => {
      timeoutId = setTimeout(() => {
        fail(new Error('Request timed out. Please try again.'));
      }, QUERY_TIMEOUT_MS);

      eventSource = new EventSource<QueryStreamEvent>(`${API_BASE_URL}/api/query-stream`, {
        method: 'POST',
        headers: authHeaders({
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          question,
          selectedFileIds,
          documentCount,
          selectedCount,
        }),
        pollingInterval: 0,
      });

      eventSource.addEventListener('retrieval', handleProgressEvent);
      eventSource.addEventListener('router', handleProgressEvent);
      eventSource.addEventListener('grader', handleProgressEvent);
      eventSource.addEventListener('generation', handleProgressEvent);
      eventSource.addEventListener('progress', handleProgressEvent);
      eventSource.addEventListener('result', handleResultEvent);
      eventSource.addEventListener('error', (async (event) => {
        const refreshToken = getApiRefreshToken();
        if (!settled && retryOnUnauthorized && refreshToken && isUnauthorizedEvent(event)) {
          cleanup();
          try {
            await refreshSession(refreshToken);
            if (!settled) {
              connect(false);
            }
          } catch (error) {
            fail(error instanceof Error ? error : new Error('Authentication expired.'));
          }
          return;
        }

        const message = 'message' in event && typeof event.message === 'string' && event.message.trim()
          ? event.message
          : 'Network connection error, please check your network settings.';
        fail(new Error(message));
      }) as EventSourceListener<QueryStreamEvent, 'error'>);
    };

    connect(true);
  });
}

export function buildStructuredContentFromResult(result: Record<string, unknown>): StructuredPart[] {
  if (!['complete', 'partial', 'unavailable'].includes(String(result.status))
    || !Array.isArray(result.blocks) || !Array.isArray(result.sources)
    || !Array.isArray(result.limitations) || typeof result.trace_id !== 'string') {
    throw new Error('Invalid RAG result. Please retry.');
  }
  const sources = new Map<string, Record<string, unknown>>();
  for (const source of result.sources) {
    if (!source || typeof source.chunk_id !== 'string' || !source.file_id
      || typeof source.content !== 'string' || sources.has(source.chunk_id)) {
      throw new Error('Invalid RAG sources.');
    }
    sources.set(source.chunk_id, source);
  }
  const numbers = new Map<string, number>();
  const ids = new Set<string>();
  const parts: StructuredPart[] = [];
  for (const block of result.blocks) {
    if (!block || typeof block.id !== 'string' || !block.id || ids.has(block.id)
      || typeof block.markdown !== 'string' || !Array.isArray(block.source_ids)) {
      throw new Error('Invalid RAG block.');
    }
    ids.add(block.id);
    parts.push({ type: 'text', value: block.markdown });
    for (const id of new Set<string>(block.source_ids)) {
      const source = sources.get(id);
      if (!source) throw new Error('RAG citation source is missing.');
      const number = numbers.get(id) ?? numbers.size + 1;
      numbers.set(id, number);
      parts.push({ type: 'citation', number, details: {
        chunkId: id, fileId: String(source.file_id), source: String(source.name),
        page: source.page_start as number | string | undefined,
        pageEnd: source.page_end as number | string | undefined,
        content: source.content as string, imageData: source.image_data as string | undefined,
      } });
    }
  }
  return parts;
}
