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

type QueryStreamEvent = 'retrieval' | 'router' | 'generation' | 'progress' | 'result';

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
      settled = true;
      cleanup();
      resolve(buildStructuredContentFromResult(result));
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

function buildStructuredContentFromResult(result: Record<string, unknown>): StructuredPart[] {
  const answerWithCitations = Array.isArray(result.answer_with_citations)
    ? result.answer_with_citations as Record<string, unknown>[]
    : [];
  const rawSources = Array.isArray(result.raw_sources) ? result.raw_sources as Record<string, unknown>[] : [];

  if (answerWithCitations.length === 0) {
    return [{ type: 'text', value: String(result.answer || 'Sorry, no answer was returned.') }];
  }

  const sourceByChunkId = new Map(rawSources.map((source) => [String(source.chunkId), source]));
  const citationRefs = new Map<string, number>();
  const parts: StructuredPart[] = [];
  let citationCounter = 1;

  answerWithCitations.forEach((segment) => {
    const contentSegments = Array.isArray(segment.content_segments)
      ? segment.content_segments as Record<string, unknown>[]
      : [];

    contentSegments.forEach((contentSegment) => {
      const text = String(contentSegment.segment_text || '').trim();
      if (text) {
        parts.push({ type: 'text', value: text });
      }

      const refs = Array.isArray(contentSegment.source_references)
        ? contentSegment.source_references as Record<string, unknown>[]
        : contentSegment.source_reference
          ? [contentSegment.source_reference as Record<string, unknown>]
          : [];

      refs.forEach((ref) => {
        const chunkId = String(ref.file_chunk_id || '');
        if (!chunkId) return;

        const number = citationRefs.get(chunkId) ?? citationCounter++;
        citationRefs.set(chunkId, number);
        const source = sourceByChunkId.get(chunkId);
        parts.push({
          type: 'citation',
          number,
          details: {
            chunkId,
            fileId: source?.fileId as string | number | undefined,
            source: source?.source as string | undefined,
            page: source?.pageNumber as string | number | undefined,
          },
        });
      });
    });
  });

  return parts.length > 0 ? parts : [{ type: 'text', value: String(result.answer || '') }];
}
