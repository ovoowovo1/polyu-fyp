import {
  generateExam,
  generateQuiz,
  generateQuizFeedback,
  getDocumentContent,
  getExamById,
  getMyExamSubmissions,
  getMyQuizResult,
  getQuizById,
  listDocuments,
  listExams,
  listMyClasses,
  listMyEnrolledClasses,
  listQuizzes,
  startExam,
  submitExam,
  submitQuiz,
  uploadLink,
  uploadMultiple,
} from '@/lib/workspaceApi';
import { setApiTokens } from '@/lib/apiClient';

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

function lastRequest() {
  const call = fetchMock().mock.calls.at(-1);
  if (!call) {
    throw new Error('No fetch call captured');
  }
  return call;
}

function expectAuthHeader(init: RequestInit | undefined) {
  expect((init?.headers as Headers).get('Authorization')).toBe('Bearer access-token');
}

describe('workspaceApi', () => {
  beforeEach(() => {
    setApiTokens(null, null);
  });

  it.each([
    ['listMyClasses', () => listMyClasses(), '/classes/mine'],
    ['listMyEnrolledClasses', () => listMyEnrolledClasses(), '/classes/enrolled'],
    ['listDocuments', () => listDocuments('class-1'), '/files?class_id=class-1'],
    ['getDocumentContent', () => getDocumentContent('file-1'), '/files/file-1'],
    ['listQuizzes', () => listQuizzes('class-1'), '/quiz/list?class_id=class-1'],
    ['listExams', () => listExams('class-1'), '/exam/list?class_id=class-1'],
    ['getQuizById', () => getQuizById('quiz-1'), '/quiz/quiz-1'],
    ['getExamById default', () => getExamById('exam-1'), '/exam/exam-1?include_answers=false'],
    ['getExamById include answers', () => getExamById('exam-1', true), '/exam/exam-1?include_answers=true'],
    ['getMyQuizResult', () => getMyQuizResult('quiz-1'), '/quiz/quiz-1/my-result'],
    ['getMyExamSubmissions', () => getMyExamSubmissions('exam-1'), '/exam/exam-1/my-submissions'],
  ])('%s uses shared JSON client auth and expected GET path', async (_name, request, expectedPath) => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ ok: true }));

    await request();

    const [url, init] = lastRequest();
    expect(String(url)).toBe(`http://localhost:3000${expectedPath}`);
    expect(init?.method).toBeUndefined();
    expectAuthHeader(init);
  });

  it.each([
    [
      'submitQuiz',
      () => submitQuiz('quiz-1', {
        answers: [{ question_index: 0, answer_index: 1 }],
        score: 1,
        total_questions: 1,
      }),
      '/quiz/quiz-1/submit',
      {
        answers: [{ question_index: 0, answer_index: 1 }],
        score: 1,
        total_questions: 1,
      },
    ],
    [
      'generateQuizFeedback',
      () => generateQuizFeedback('quiz-1', { score: 1, total_questions: 2 }),
      '/quiz/quiz-1/feedback',
      { score: 1, total_questions: 2 },
    ],
    [
      'startExam',
      () => startExam('exam-1'),
      '/exam/exam-1/start',
      {},
    ],
    [
      'submitExam',
      () => submitExam('submission-1', {
        answers: [{ question_id: 'q1', answer_text: 'answer' }],
        time_spent_seconds: 30,
      }),
      '/exam/submission/submission-1/submit',
      {
        answers: [{ question_id: 'q1', answer_text: 'answer' }],
        time_spent_seconds: 30,
      },
    ],
    [
      'uploadLink',
      () => uploadLink('https://example.com/doc.pdf', 'client-1', 'class-1'),
      '/upload-link?clientId=client-1&class_id=class-1',
      { url: 'https://example.com/doc.pdf' },
    ],
  ])('%s posts JSON to the expected endpoint', async (_name, request, expectedPath, expectedBody) => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ ok: true }));

    await request();

    const [url, init] = lastRequest();
    expect(String(url)).toBe(`http://localhost:3000${expectedPath}`);
    expect(init?.method).toBe('POST');
    expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
    expectAuthHeader(init);
    expect(JSON.parse(String(init?.body))).toEqual(expectedBody);
  });

  it('maps generateExam payload to backend field names', async () => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ exam_id: 'exam-1' }));

    await generateExam({
      fileIds: ['file-1'],
      topic: 'algebra',
      difficulty: 'medium',
      numQuestions: 3,
      questionTypes: { multiple_choice: 1, short_answer: 1, essay: 1 },
      examName: 'Midterm',
      includeImages: true,
      customPrompt: 'focus on proofs',
    });

    const [url, init] = lastRequest();
    expect(String(url)).toBe('http://localhost:3000/exam/generate');
    expect(init?.method).toBe('POST');
    expectAuthHeader(init);
    expect(JSON.parse(String(init?.body))).toEqual({
      file_ids: ['file-1'],
      topic: 'algebra',
      difficulty: 'medium',
      num_questions: 3,
      question_types: { multiple_choice: 1, short_answer: 1, essay: 1 },
      exam_name: 'Midterm',
      include_images: true,
      custom_prompt: 'focus on proofs',
    });
  });

  it('uses shared FormData request auth for quiz generation', async () => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ quiz_id: 'quiz-1' }));

    await generateQuiz({
      fileIds: ['file-1'],
      difficulty: 'easy',
      numQuestions: 2,
      bloomLevels: ['remember'],
    });

    const [url, init] = lastRequest();
    expect(String(url)).toBe('http://localhost:3000/quiz/generate');
    expect(init?.method).toBe('POST');
    expectAuthHeader(init);
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it('uses shared FormData request auth for multi-file upload', async () => {
    setApiTokens('access-token', 'refresh-token');
    fetchMock().mockResolvedValueOnce(jsonResponse({ files: [] }));

    await uploadMultiple([{ uri: 'file://a.pdf', name: 'a.pdf' }], 'client-1', 'class-1');

    const [url, init] = lastRequest();
    expect(String(url)).toBe('http://localhost:3000/upload-multiple?clientId=client-1&class_id=class-1');
    expect(init?.method).toBe('POST');
    expectAuthHeader(init);
    expect(init?.body).toBeInstanceOf(FormData);
  });
});
