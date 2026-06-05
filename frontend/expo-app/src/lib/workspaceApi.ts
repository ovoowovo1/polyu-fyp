import { requestFormData, requestJson } from '@/lib/apiClient';
import type {
  ClassesResponse,
  DocumentDetails,
  DocumentsResponse,
  ExamDetail,
  ExamStartResponse,
  ExamSubmitPayload,
  ExamSubmissionSummary,
  ExamSummary,
  QuizDetail,
  QuizResultSummary,
  QuizSubmitPayload,
  QuizSummary,
} from '@/lib/types';

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

  return requestFormData('/quiz/generate', formData);
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

  return requestFormData(`/upload-multiple?${params.toString()}`, formData);
}

export function uploadLink(url: string, clientId: string, classId: string) {
  const params = new URLSearchParams({ clientId, class_id: classId });
  return requestJson(`/upload-link?${params.toString()}`, {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}
