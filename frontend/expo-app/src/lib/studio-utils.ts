import type { ExamSummary, QuizSummary } from '@/lib/types';

export type StudioItem =
  | { id: string; createdAt: number; type: 'exam'; title: string; raw: ExamSummary }
  | { id: string; createdAt: number; type: 'quiz'; title: string; raw: QuizSummary };

export const QUESTION_LIMITS = {
  multipleChoice: { max: 30, marks: 1 },
  shortAnswer: { max: 15, marks: 2 },
  essay: { max: 10, marks: 5 },
} as const;

export function formatStudioDate(value: number) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${day}/${month}/${year} ${hours}:${minutes}`;
}

export function sanitizeCountInput(value: string, max: number) {
  const digits = value.replace(/[^0-9]/g, '');
  if (!digits) {
    return '0';
  }
  return String(Math.min(max, Number(digits)));
}

export function clampQuestionCount(value: string, max: number) {
  return Math.min(max, Math.max(0, Number(value) || 0));
}
