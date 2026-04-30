export type LoginRole = 'student' | 'teacher';

export type User = {
  id?: string | number;
  email: string;
  full_name?: string;
  role: LoginRole;
};

export type LoginResponse = {
  session_token: string;
  user: User;
};

export type ClassSummary = {
  id: string | number;
  name: string;
  student_count?: number;
  created_at?: string;
};

export type ClassesResponse = {
  classes: ClassSummary[];
};

export type DocumentSummary = {
  id: string | number;
  filename?: string;
  original_name?: string;
  status?: string;
  source_url?: string;
  url?: string;
  file_url?: string;
};

export type DocumentsResponse = {
  files: DocumentSummary[];
};

export type DocumentChunk = {
  id?: string | number;
  chunkId?: string | number;
  file_chunk_id?: string | number;
  page?: string | number;
  pageNumber?: string | number;
  content?: string;
  [key: string]: unknown;
};

export type DocumentDetails = {
  file?: DocumentSummary;
  chunks?: DocumentChunk[];
};

export type CitationDetails = {
  fileId?: string | number;
  chunkId?: string | number;
  source?: string;
  page?: string | number;
};

export type StructuredPart =
  | { type: 'text'; value: string }
  | { type: 'citation'; number: number; details?: CitationDetails };

export type ProgressEvent = {
  type?: string;
  message?: string;
  status?: string;
  done?: number;
  total?: number;
  currentFile?: string;
  lastFileStatus?: string;
  summary?: {
    total?: number;
    succeeded?: number;
    failed?: number;
  };
  [key: string]: unknown;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  parts?: StructuredPart[];
};

export type UploadProgressState = {
  status: 'idle' | 'running' | 'success' | 'partial' | 'failed';
  visible: boolean;
  progress: number;
  done: number;
  total: number;
  currentFile?: string;
  lastFileStatus?: string;
  message?: string;
  summary?: {
    total?: number;
    succeeded?: number;
    failed?: number;
  };
};

export type QuizSummary = {
  id: string;
  name?: string;
  num_questions?: number;
  created_at?: string;
  documents?: { id?: string; name?: string }[];
};

export type ExamSummary = {
  id: string;
  title?: string;
  num_questions?: number;
  is_published?: boolean;
  created_at?: string;
  documents?: { id?: string; name?: string }[];
};

export type QuizQuestion = {
  question_type?: string;
  question?: string;
  question_text?: string;
  choices?: string[];
  options?: string[];
  correct_answer?: string;
  answer_index?: number;
  correct_answer_index?: number;
  bloom_level?: string;
  explanation?: string;
  rationale?: string;
};

export type QuizDetail = {
  id: string;
  name?: string;
  questions?: QuizQuestion[];
  documents?: { id?: string; name?: string }[];
  created_at?: string;
};

export type ExamQuestion = {
  question_id?: string;
  question_type?: string;
  question_text?: string;
  choices?: string[];
  correct_answer_index?: number;
  model_answer?: string;
  marks?: number;
  bloom_level?: string;
};

export type ExamDetail = {
  id: string;
  title?: string;
  description?: string;
  num_questions?: number;
  is_published?: boolean;
  duration_minutes?: number;
  created_at?: string;
  questions?: ExamQuestion[];
  documents?: { id?: string; name?: string }[];
};

export type QuizResultSummary = {
  id?: string;
  score?: number;
  total_questions?: number;
  submitted_at?: string;
  answers?: { question_index?: number; answer_index?: number }[];
};

export type ExamSubmissionSummary = {
  id?: string;
  submission_id?: string;
  score?: number;
  total_marks?: number;
  started_at?: string;
  submitted_at?: string;
  status?: string;
};

export type QuizSubmitPayload = {
  answers: { question_index: number; answer_index: number | null }[];
  score: number;
  total_questions: number;
};

export type ExamStartResponse = {
  submission_id: string;
  started_at: string;
  attempt_no: number;
  duration_minutes?: number | null;
};

export type ExamAnswerPayload = {
  question_id?: string;
  exam_question_id?: string;
  answer_index?: number | null;
  answer_text?: string;
};

export type ExamSubmitPayload = {
  answers: ExamAnswerPayload[];
  time_spent_seconds?: number | null;
};
