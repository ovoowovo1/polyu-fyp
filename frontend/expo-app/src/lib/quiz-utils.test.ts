import {
  buildQuizFeedbackPayload,
  buildQuizSubmitPayload,
  calculateQuizScore,
  createEmptyQuizAnswers,
  resolveCorrectAnswerIndex,
} from '@/lib/quiz-utils';
import type { QuizDetail, QuizQuestion } from '@/lib/types';

const questions: QuizQuestion[] = [
  {
    question_text: 'Pick a DDL command',
    choices: ['SELECT', 'CREATE'],
    correct_answer_index: 1,
    bloom_level: 'apply',
    rationale: 'CREATE defines schema objects.',
  },
  {
    question: 'What is normalization?',
    options: ['Duplicating data', 'Reducing redundancy'],
    answer_index: 1,
    bloom_level: 'understand',
  },
];

describe('quiz-utils', () => {
  it('creates empty answer slots and resolves supported answer index fields', () => {
    expect(createEmptyQuizAnswers(3)).toEqual([null, null, null]);
    expect(resolveCorrectAnswerIndex(questions[0])).toBe(1);
    expect(resolveCorrectAnswerIndex(questions[1])).toBe(1);
    expect(resolveCorrectAnswerIndex(null)).toBeNull();
    expect(resolveCorrectAnswerIndex({ question: 'Missing answer' })).toBeNull();
  });

  it('calculates quiz score and submit payload from user answers', () => {
    const score = calculateQuizScore(questions, [1, 0]);

    expect(score).toEqual({
      correct: 1,
      total: 2,
      percentage: 50,
    });
    expect(calculateQuizScore([], [])).toEqual({
      correct: 0,
      total: 0,
      percentage: 0,
    });
    expect(buildQuizSubmitPayload([1, null], score)).toEqual({
      answers: [
        { question_index: 0, answer_index: 1 },
        { question_index: 1, answer_index: null },
      ],
      score: 1,
      total_questions: 2,
    });
  });

  it('builds feedback payload with backend field names and bloom summaries', () => {
    const quiz: QuizDetail = {
      id: 'quiz-1',
      name: 'Database quiz',
      questions,
    };
    const score = calculateQuizScore(questions, [1, 0]);

    expect(buildQuizFeedbackPayload(quiz, [1, 0], score)).toEqual({
      quiz_name: 'Database quiz',
      score: 1,
      total_questions: 2,
      percentage: 50,
      bloom_summary: [
        { level: 'apply', correct: 1, total: 1, accuracy: 100 },
        { level: 'understand', correct: 0, total: 1, accuracy: 0 },
      ],
      questions: [
        {
          question: 'Pick a DDL command',
          choices: ['SELECT', 'CREATE'],
          correct_answer_index: 1,
          user_answer_index: 1,
          bloom_level: 'apply',
          rationale: 'CREATE defines schema objects.',
        },
        {
          question: 'What is normalization?',
          choices: ['Duplicating data', 'Reducing redundancy'],
          correct_answer_index: 1,
          user_answer_index: 0,
          bloom_level: 'understand',
          rationale: undefined,
        },
      ],
    });
  });
});
