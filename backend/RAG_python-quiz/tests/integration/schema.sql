CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    full_name text NOT NULL,
    role text NOT NULL CHECK (role IN ('teacher', 'student')),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE IF NOT EXISTS teachers (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS students (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS classes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id uuid NOT NULL REFERENCES teachers(user_id) ON DELETE CASCADE,
    name text NOT NULL,
    code text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS class_students (
    class_id uuid NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id uuid REFERENCES classes(id) ON DELETE SET NULL,
    hash text,
    name text NOT NULL,
    size_bytes bigint DEFAULT 0,
    mimetype text DEFAULT 'application/octet-stream',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_class_hash ON documents(class_id, hash);

CREATE TABLE IF NOT EXISTS chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text text NOT NULL,
    page_start int,
    page_end int,
    chunk_index int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk_media (
    chunk_id uuid PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    mimetype text NOT NULL,
    data bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quizzes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text,
    questions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_text_length int,
    was_summarized boolean NOT NULL DEFAULT false,
    num_questions int NOT NULL DEFAULT 0,
    class_id uuid REFERENCES classes(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quiz_documents (
    quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (quiz_id, document_id)
);

CREATE TABLE IF NOT EXISTS quiz_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    score int NOT NULL DEFAULT 0,
    total_questions int NOT NULL DEFAULT 0,
    answers_json jsonb DEFAULT '[]'::jsonb,
    attempt_no int NOT NULL DEFAULT 1,
    submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exams (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id uuid REFERENCES classes(id) ON DELETE SET NULL,
    owner_id uuid REFERENCES teachers(user_id) ON DELETE SET NULL,
    title text NOT NULL,
    description text,
    duration_minutes int,
    is_published boolean NOT NULL DEFAULT false,
    start_at timestamptz,
    end_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    difficulty text DEFAULT 'medium',
    total_marks int DEFAULT 0,
    pdf_path text,
    questions_json jsonb DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS exam_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    position int NOT NULL DEFAULT 0,
    question_snapshot jsonb NOT NULL,
    max_marks int NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exam_documents (
    exam_id uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (exam_id, document_id)
);

CREATE TABLE IF NOT EXISTS exam_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    started_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    status text NOT NULL DEFAULT 'in_progress',
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    attempt_no int NOT NULL DEFAULT 1,
    score int,
    total_marks int,
    time_spent_seconds int,
    teacher_comment text,
    graded_by uuid REFERENCES teachers(user_id) ON DELETE SET NULL,
    graded_at timestamptz,
    grading_source text
);

CREATE TABLE IF NOT EXISTS exam_answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id uuid NOT NULL REFERENCES exam_submissions(id) ON DELETE CASCADE,
    exam_question_id uuid NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
    question_snapshot jsonb,
    answer_text text,
    selected_options jsonb,
    attachments jsonb DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    time_spent_seconds int,
    is_correct boolean,
    marks_earned int,
    teacher_feedback text
);

CREATE INDEX IF NOT EXISTS idx_classes_teacher_id ON classes(teacher_id);
CREATE INDEX IF NOT EXISTS idx_documents_class_id ON documents(class_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_class_id ON quizzes(class_id);
CREATE INDEX IF NOT EXISTS idx_exams_class_id ON exams(class_id);
CREATE INDEX IF NOT EXISTS idx_exams_owner_id ON exams(owner_id);
