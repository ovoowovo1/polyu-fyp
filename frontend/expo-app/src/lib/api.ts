import EventSource, { type EventSourceListener } from 'react-native-sse';

import type {
  ClassesResponse,
  DocumentDetails,
  DocumentsResponse,
  ExamDetail,
  ExamStartResponse,
  ExamSubmitPayload,
  ExamSubmissionSummary,
  ExamSummary,
  LoginResponse,
  LoginRole,
  ProgressEvent,
  QuizDetail,
  QuizResultSummary,
  QuizSummary,
  QuizSubmitPayload,
  StructuredPart,
} from '@/lib/types';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:3000';
const QUERY_TIMEOUT_MS = 120_000;
type QueryStreamEvent = 'retrieval' | 'router' | 'generation' | 'progress' | 'result';

let sessionToken: string | null = null;

export function setApiSessionToken(token: string | null) {
  sessionToken = token;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    throw new Error(extractErrorMessage(payload, response.status));
  }

  return payload as T;
}

export function login(email: string, password: string, role: LoginRole) {
  return requestJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, role }),
  });
}

export function verifyToken(token: string) {
  return fetch(`${API_BASE_URL}/auth/verify`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (response) => {
    const text = await response.text();
    const payload = text ? safeJsonParse(text) : null;
    if (!response.ok) {
      throw new Error(extractErrorMessage(payload, response.status));
    }
    return payload as { user?: LoginResponse['user'] };
  });
}

export function listMyClasses() {
  return requestJson<ClassesResponse>('/classes/mine');
}

export function listMyEnrolledClasses() {
  return requestJson<ClassesResponse>('/classes/enrolled');
}

export function listDocuments(classId: string) {
  const params = new URLSearchParams({ class_id: classId });
  return requestJson<DocumentsResponse>(`/files?${params.toString()}`);
}

export function getDocumentContent(fileId: string) {
  return requestJson<DocumentDetails>(`/files/${fileId}`);
}

export function listQuizzes(classId: string) {
  const params = new URLSearchParams({ class_id: classId });
  return requestJson<{ quizzes: QuizSummary[]; total: number }>(`/quiz/list?${params.toString()}`);
}

export function listExams(classId: string) {
  const params = new URLSearchParams({ class_id: classId });
  return requestJson<{ exams: ExamSummary[]; total: number }>(`/exam/list?${params.toString()}`);
}

export function getQuizById(quizId: string) {
  return requestJson<{ quiz: QuizDetail }>(`/quiz/${quizId}`);
}

export function getExamById(examId: string, includeAnswers = false) {
  const params = new URLSearchParams({ include_answers: String(includeAnswers) });
  return requestJson<{ exam: ExamDetail }>(`/exam/${examId}?${params.toString()}`);
}

export function getMyQuizResult(quizId: string) {
  return requestJson<{ submission: QuizResultSummary | null }>(`/quiz/${quizId}/my-result`);
}

export function getMyExamSubmissions(examId: string) {
  return requestJson<{ submissions: ExamSubmissionSummary[]; total: number }>(`/exam/${examId}/my-submissions`);
}

export function submitQuiz(quizId: string, payload: QuizSubmitPayload) {
  return requestJson(`/quiz/${quizId}/submit`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function generateQuizFeedback(quizId: string, payload: Record<string, unknown>) {
  return requestJson<{ feedback?: string }>(`/quiz/${quizId}/feedback`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function startExam(examId: string) {
  return requestJson<ExamStartResponse>(`/exam/${examId}/start`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export function submitExam(submissionId: string, payload: ExamSubmitPayload) {
  return requestJson(`/exam/submission/${submissionId}/submit`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function generateQuiz(payload: {
  fileIds: string[];
  difficulty: 'easy' | 'medium' | 'difficult';
  numQuestions: number;
  bloomLevels: string[];
}) {
  const formData = new FormData();
  payload.fileIds.forEach((id) => formData.append('file_ids', id));
  payload.bloomLevels.forEach((level) => formData.append('bloom_levels', level));
  formData.append('difficulty', payload.difficulty);
  formData.append('num_questions', String(payload.numQuestions));

  const headers = new Headers();
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }

  return fetch(`${API_BASE_URL}/quiz/generate`, {
    method: 'POST',
    headers,
    body: formData,
  }).then(async (response) => {
    const text = await response.text();
    const payloadBody = text ? safeJsonParse(text) : null;
    if (!response.ok) {
      throw new Error(extractErrorMessage(payloadBody, response.status));
    }
    return payloadBody;
  });
}

export function generateExam(payload: {
  fileIds: string[];
  topic?: string;
  difficulty: 'easy' | 'medium' | 'difficult';
  numQuestions: number;
  questionTypes?: {
    multiple_choice: number;
    short_answer: number;
    essay: number;
  };
  examName?: string;
  includeImages: boolean;
  customPrompt?: string;
}) {
  return requestJson('/exam/generate', {
    method: 'POST',
    body: JSON.stringify({
      file_ids: payload.fileIds,
      topic: payload.topic || undefined,
      difficulty: payload.difficulty,
      num_questions: payload.numQuestions,
      question_types: payload.questionTypes,
      exam_name: payload.examName || undefined,
      include_images: payload.includeImages,
      custom_prompt: payload.customPrompt || undefined,
    }),
  });
}

export async function uploadMultiple(
  files: { uri: string; name: string; mimeType?: string }[],
  clientId: string,
  classId: string,
) {
  const params = new URLSearchParams({ clientId, class_id: classId });
  const formData = new FormData();

  files.forEach((file, index) => {
    formData.append('files', {
      uri: file.uri,
      name: file.name || `document-${index + 1}.pdf`,
      type: file.mimeType || 'application/pdf',
    } as unknown as Blob);
  });

  const headers = new Headers();
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }

  const response = await fetch(`${API_BASE_URL}/upload-multiple?${params.toString()}`, {
    method: 'POST',
    headers,
    body: formData,
  });
  const text = await response.text();
  const payload = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    throw new Error(extractErrorMessage(payload, response.status));
  }

  return payload;
}

export function uploadLink(url: string, clientId: string, classId: string) {
  const params = new URLSearchParams({ clientId, class_id: classId });
  return requestJson(`/upload-link?${params.toString()}`, {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export function subscribeUploadProgress(
  clientId: string,
  handlers: {
    onProgress?: (event: ProgressEvent) => void;
    onFinished?: (event: ProgressEvent) => void;
    onError?: (event: ProgressEvent) => void;
  },
) {
  const eventSource = new EventSource(`${API_BASE_URL}/sse/progress?clientId=${encodeURIComponent(clientId)}`, {
    headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : undefined,
    pollingInterval: 0,
  });

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

  const onError: EventSourceListener<string, 'error'> = (event) => {
    handlers.onError?.({
      type: 'error',
      message: 'message' in event && typeof event.message === 'string' ? event.message : 'Upload stream failed.',
    });
  };

  eventSource.addEventListener('message', onMessage);
  eventSource.addEventListener('error', onError);

  return () => {
    eventSource.removeAllEventListeners();
    eventSource.close();
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
    const eventSource = new EventSource<QueryStreamEvent>(`${API_BASE_URL}/api/query-stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
        selectedFileIds,
        documentCount,
        selectedCount,
      }),
      pollingInterval: 0,
    });

    const cleanup = () => {
      clearTimeout(timeoutId);
      eventSource.removeAllEventListeners();
      eventSource.close();
    };

    const fail = (error: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error);
    };

    const succeed = (result: Record<string, unknown>) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(buildStructuredContentFromResult(result));
    };

    const timeoutId = setTimeout(() => {
      fail(new Error('Request timed out. Please try again.'));
    }, QUERY_TIMEOUT_MS);

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

    const handleErrorEvent: EventSourceListener<QueryStreamEvent, 'error'> = (event) => {
      const message = 'message' in event && typeof event.message === 'string' && event.message.trim()
        ? event.message
        : 'Network connection error, please check your network settings.';
      fail(new Error(message));
    };

    eventSource.addEventListener('retrieval', handleProgressEvent);
    eventSource.addEventListener('router', handleProgressEvent);
    eventSource.addEventListener('generation', handleProgressEvent);
    eventSource.addEventListener('progress', handleProgressEvent);
    eventSource.addEventListener('result', handleResultEvent);
    eventSource.addEventListener('error', handleErrorEvent);
  });
}

function parseEventSourceData(event: { data?: string | null; type?: string }): Record<string, unknown> {
  const data = event.data;
  if (!data) {
    return { type: event.type || 'message' };
  }

  const parsed = safeJsonParse(data);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return parsed as Record<string, unknown>;
  }

  return {
    type: event.type || 'message',
    message: String(parsed),
  };
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
        if (!chunkId) {
          return;
        }

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

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function extractErrorMessage(payload: unknown, status: number) {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const detail = record.detail;
    if (typeof record.error === 'string') return record.error;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && typeof (detail as Record<string, unknown>).error === 'string') {
      return String((detail as Record<string, unknown>).error);
    }
  }
  if (typeof payload === 'string' && payload.trim()) {
    return payload;
  }
  return `HTTP ${status}`;
}
