import type { QuizDetail, QuizQuestion, QuizSubmitPayload } from '@/lib/types';

export type QuizScore = {
  correct: number;
  total: number;
  percentage: number;
};

export type QuizFeedbackPayload = {
  quiz_name: string;
  score: number;
  total_questions: number;
  percentage: number;
  bloom_summary: {
    level: string;
    correct: number;
    total: number;
    accuracy: number;
  }[];
  questions: {
    question: string | undefined;
    choices: string[] | undefined;
    correct_answer_index: number | null;
    user_answer_index: number | null;
    bloom_level: string;
    rationale: string | undefined;
  }[];
};

export function createEmptyQuizAnswers(questionCount: number) {
  return new Array<number | null>(questionCount).fill(null);
}

export function resolveCorrectAnswerIndex(question: QuizQuestion | null) {
  if (!question) {
    return null;
  }
  if (typeof question.correct_answer_index === 'number') {
    return question.correct_answer_index;
  }
  if (typeof question.answer_index === 'number') {
    return question.answer_index;
  }
  return null;
}

export function calculateQuizScore(questions: QuizQuestion[], userAnswers: (number | null)[]): QuizScore {
  const correct = questions.reduce((total, question, index) => {
    const answer = userAnswers[index];
    const correctIndex = resolveCorrectAnswerIndex(question);
    return answer !== null && correctIndex === answer ? total + 1 : total;
  }, 0);
  const total = questions.length;
  return {
    correct,
    total,
    percentage: total > 0 ? Math.round((correct / total) * 100) : 0,
  };
}

export function buildQuizSubmitPayload(
  userAnswers: (number | null)[],
  score: QuizScore,
): QuizSubmitPayload {
  return {
    answers: userAnswers.map((answer, index) => ({
      question_index: index,
      answer_index: answer,
    })),
    score: score.correct,
    total_questions: score.total,
  };
}

export function buildQuizFeedbackPayload(
  quiz: QuizDetail,
  answers: (number | null)[],
  score: QuizScore,
): QuizFeedbackPayload {
  const questions = quiz.questions ?? [];
  const bloomStats: Record<string, { correct: number; total: number }> = {};

  questions.forEach((question, index) => {
    const level = question.bloom_level || 'general';
    if (!bloomStats[level]) {
      bloomStats[level] = { correct: 0, total: 0 };
    }
    bloomStats[level].total += 1;
    const correctIndex = resolveCorrectAnswerIndex(question);
    if (answers[index] !== null && correctIndex === answers[index]) {
      bloomStats[level].correct += 1;
    }
  });

  return {
    quiz_name: quiz.name || 'Quiz',
    score: score.correct,
    total_questions: score.total,
    percentage: score.percentage,
    bloom_summary: Object.entries(bloomStats).map(([level, stats]) => ({
      level,
      correct: stats.correct,
      total: stats.total,
      accuracy: stats.total ? Math.round((stats.correct / stats.total) * 100) : 0,
    })),
    questions: questions.map((question, index) => ({
      question: question.question_text || question.question,
      choices: question.choices || question.options,
      correct_answer_index: resolveCorrectAnswerIndex(question),
      user_answer_index: answers[index],
      bloom_level: question.bloom_level || 'general',
      rationale: question.rationale,
    })),
  };
}
