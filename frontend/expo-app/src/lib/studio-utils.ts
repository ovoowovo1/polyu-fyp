import type { ExamSummary, QuizSummary } from '@/lib/types';

export const difficultyOptions = ['easy', 'medium', 'difficult'] as const;
export const bloomOptions = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'] as const;

export type DifficultyOption = typeof difficultyOptions[number];

export type StudioItem =
  | { id: string; createdAt: number; type: 'exam'; title: string; raw: ExamSummary }
  | { id: string; createdAt: number; type: 'quiz'; title: string; raw: QuizSummary };

export type ExamTypeCounts = {
  multipleChoice: number;
  shortAnswer: number;
  essay: number;
};

export type ExamTotals = {
  totalExamQuestions: number;
  totalExamMarks: number;
};

export type QuizGenerationPayload = {
  fileIds: string[];
  difficulty: DifficultyOption;
  numQuestions: number;
  bloomLevels: string[];
};

export type ExamGenerationPayload = {
  fileIds: string[];
  topic?: string;
  difficulty: DifficultyOption;
  numQuestions: number;
  questionTypes: {
    multiple_choice: number;
    short_answer: number;
    essay: number;
  };
  examName?: string;
  includeImages: boolean;
  customPrompt?: string;
};

export const QUESTION_LIMITS = {
  multipleChoice: { max: 30, marks: 1 },
  shortAnswer: { max: 15, marks: 2 },
  essay: { max: 10, marks: 5 },
} as const;

export function buildStudioItems(quizzes: QuizSummary[], exams: ExamSummary[]): StudioItem[] {
  const quizItems = quizzes.map((quiz) => ({
    id: quiz.id,
    createdAt: Date.parse(quiz.created_at || '') || 0,
    type: 'quiz' as const,
    title: quiz.name || 'Untitled quiz',
    raw: quiz,
  }));
  const examItems = exams.map((exam) => ({
    id: exam.id,
    createdAt: Date.parse(exam.created_at || '') || 0,
    type: 'exam' as const,
    title: exam.title || 'Untitled exam',
    raw: exam,
  }));
  return [...examItems, ...quizItems].sort((a, b) => b.createdAt - a.createdAt);
}

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

export function calculateExamTypeCounts({
  mcCount,
  shortAnswerCount,
  essayCount,
}: {
  mcCount: string;
  shortAnswerCount: string;
  essayCount: string;
}): ExamTypeCounts {
  return {
    multipleChoice: clampQuestionCount(mcCount, QUESTION_LIMITS.multipleChoice.max),
    shortAnswer: clampQuestionCount(shortAnswerCount, QUESTION_LIMITS.shortAnswer.max),
    essay: clampQuestionCount(essayCount, QUESTION_LIMITS.essay.max),
  };
}

export function calculateExamTotals(counts: ExamTypeCounts): ExamTotals {
  return {
    totalExamQuestions: counts.multipleChoice + counts.shortAnswer + counts.essay,
    totalExamMarks: (
      counts.multipleChoice * QUESTION_LIMITS.multipleChoice.marks +
      counts.shortAnswer * QUESTION_LIMITS.shortAnswer.marks +
      counts.essay * QUESTION_LIMITS.essay.marks
    ),
  };
}

export function buildQuizGenerationPayload({
  selectedIds,
  difficulty,
  quizQuestions,
  bloomLevels,
}: {
  selectedIds: string[];
  difficulty: DifficultyOption;
  quizQuestions: string;
  bloomLevels: string[];
}): QuizGenerationPayload {
  return {
    fileIds: [...selectedIds],
    difficulty,
    numQuestions: Math.max(1, Number(quizQuestions) || 5),
    bloomLevels: bloomLevels.length > 0 ? [...bloomLevels] : ['understand'],
  };
}

export function buildExamGenerationPayload({
  selectedIds,
  topic,
  difficulty,
  totalQuestions,
  typeCounts,
  examName,
  includeImages,
  customPrompt,
}: {
  selectedIds: string[];
  topic: string;
  difficulty: DifficultyOption;
  totalQuestions: number;
  typeCounts: ExamTypeCounts;
  examName: string;
  includeImages: boolean;
  customPrompt: string;
}): ExamGenerationPayload {
  return {
    fileIds: [...selectedIds],
    topic: topic.trim() || undefined,
    difficulty,
    numQuestions: totalQuestions,
    questionTypes: {
      multiple_choice: typeCounts.multipleChoice,
      short_answer: typeCounts.shortAnswer,
      essay: typeCounts.essay,
    },
    examName: examName.trim() || undefined,
    includeImages,
    customPrompt: customPrompt.trim() || undefined,
  };
}
