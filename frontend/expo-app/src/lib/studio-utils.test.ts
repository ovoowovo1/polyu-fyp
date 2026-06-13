import {
  buildExamGenerationPayload,
  buildQuizGenerationPayload,
  buildStudioItems,
  calculateExamTotals,
  calculateExamTypeCounts,
  clampQuestionCount,
  sanitizeCountInput,
} from '@/lib/studio-utils';

describe('studio-utils', () => {
  it('builds sorted studio items with fallback titles', () => {
    const items = buildStudioItems(
      [
        { id: 'quiz-1', name: 'Quiz A', created_at: '2026-01-01T00:00:00Z' },
        { id: 'quiz-2', created_at: 'bad-date' },
      ],
      [
        { id: 'exam-1', title: 'Exam A', created_at: '2026-01-02T00:00:00Z' },
      ],
    );

    expect(items.map((item) => `${item.type}:${item.id}:${item.title}`)).toEqual([
      'exam:exam-1:Exam A',
      'quiz:quiz-1:Quiz A',
      'quiz:quiz-2:Untitled quiz',
    ]);
  });

  it('sanitizes and clamps question counts before calculating exam totals', () => {
    expect(sanitizeCountInput('42 questions', 30)).toBe('30');
    expect(sanitizeCountInput('none', 30)).toBe('0');
    expect(clampQuestionCount('-3', 10)).toBe(0);
    expect(clampQuestionCount('99', 10)).toBe(10);

    const counts = calculateExamTypeCounts({
      mcCount: '31',
      shortAnswerCount: 'not-a-number',
      essayCount: '2',
    });

    expect(counts).toEqual({
      multipleChoice: 30,
      shortAnswer: 0,
      essay: 2,
    });
    expect(calculateExamTotals(counts)).toEqual({
      totalExamQuestions: 32,
      totalExamMarks: 40,
    });
  });

  it('builds quiz generation payload with safe defaults', () => {
    expect(buildQuizGenerationPayload({
      selectedIds: ['file-1'],
      difficulty: 'medium',
      quizQuestions: '',
      bloomLevels: [],
    })).toEqual({
      fileIds: ['file-1'],
      difficulty: 'medium',
      numQuestions: 5,
      bloomLevels: ['understand'],
    });
  });

  it('builds exam generation payload using backend field names', () => {
    expect(buildExamGenerationPayload({
      selectedIds: ['file-1'],
      topic: '  graphs  ',
      difficulty: 'difficult',
      totalQuestions: 6,
      typeCounts: {
        multipleChoice: 3,
        shortAnswer: 2,
        essay: 1,
      },
      examName: '  Final  ',
      includeImages: true,
      customPrompt: '  include diagrams  ',
    })).toEqual({
      fileIds: ['file-1'],
      topic: 'graphs',
      difficulty: 'difficult',
      numQuestions: 6,
      questionTypes: {
        multiple_choice: 3,
        short_answer: 2,
        essay: 1,
      },
      examName: 'Final',
      includeImages: true,
      customPrompt: 'include diagrams',
    });
  });
});
