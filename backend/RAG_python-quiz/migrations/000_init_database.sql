-- Initialize the PolyU FYP backend database in the current Postgres database.
--
-- Run this file as the schema owner/admin role, for example:
--   psql "<connection-string>" -f backend/RAG_python-quiz/migrations/000_init_database.sql
--
-- This file creates application tables, indexes, RLS policies, and
-- app_security helper functions. It does not create a Neon project/database,
-- seed users, or store any real credentials.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_search;

CREATE SCHEMA IF NOT EXISTS app_security;

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    full_name text NOT NULL,
    role text NOT NULL CHECK (role IN ('teacher', 'student')),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.teachers (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.students (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.classes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id uuid NOT NULL REFERENCES public.teachers(user_id) ON DELETE CASCADE,
    name text NOT NULL,
    code text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.class_students (
    class_id uuid NOT NULL REFERENCES public.classes(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES public.students(user_id) ON DELETE CASCADE,
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS public.documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hash text,
    class_id uuid REFERENCES public.classes(id) ON DELETE SET NULL,
    name text NOT NULL,
    size_bytes bigint DEFAULT 0,
    mimetype text DEFAULT 'application/octet-stream',
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS hash text;

CREATE TABLE IF NOT EXISTS public.chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    text text NOT NULL,
    page_start int,
    page_end int,
    chunk_index int NOT NULL DEFAULT 0,
    embedding vector(3072),
    embedding_v2 vector(3072),
    entities_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(text, ''))) STORED,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS embedding vector(3072);
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS embedding_v2 vector(3072);
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS entities_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(text, ''))) STORED;

CREATE TABLE IF NOT EXISTS public.chunk_media (
    chunk_id uuid PRIMARY KEY REFERENCES public.chunks(id) ON DELETE CASCADE,
    mimetype text NOT NULL,
    data bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quizzes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text,
    questions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_text_length int,
    was_summarized boolean NOT NULL DEFAULT false,
    num_questions int NOT NULL DEFAULT 0,
    class_id uuid REFERENCES public.classes(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quiz_documents (
    quiz_id uuid NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    PRIMARY KEY (quiz_id, document_id)
);

CREATE TABLE IF NOT EXISTS public.quiz_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id uuid NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES public.students(user_id) ON DELETE CASCADE,
    score int NOT NULL DEFAULT 0,
    total_questions int NOT NULL DEFAULT 0,
    answers_json jsonb DEFAULT '[]'::jsonb,
    attempt_no int NOT NULL DEFAULT 1,
    submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.exams (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id uuid REFERENCES public.classes(id) ON DELETE SET NULL,
    owner_id uuid REFERENCES public.teachers(user_id) ON DELETE SET NULL,
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

CREATE TABLE IF NOT EXISTS public.exam_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id uuid NOT NULL REFERENCES public.exams(id) ON DELETE CASCADE,
    position int NOT NULL DEFAULT 0,
    question_snapshot jsonb NOT NULL,
    max_marks int NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.exam_documents (
    exam_id uuid NOT NULL REFERENCES public.exams(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    PRIMARY KEY (exam_id, document_id)
);

CREATE TABLE IF NOT EXISTS public.exam_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id uuid NOT NULL REFERENCES public.exams(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES public.students(user_id) ON DELETE CASCADE,
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
    graded_by uuid REFERENCES public.teachers(user_id) ON DELETE SET NULL,
    graded_at timestamptz,
    grading_source text DEFAULT NULL CHECK (grading_source IS NULL OR grading_source IN ('ai', 'teacher'))
);

ALTER TABLE public.exam_submissions
    ADD COLUMN IF NOT EXISTS grading_source text DEFAULT NULL
    CHECK (grading_source IS NULL OR grading_source IN ('ai', 'teacher'));

CREATE TABLE IF NOT EXISTS public.exam_answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id uuid NOT NULL REFERENCES public.exam_submissions(id) ON DELETE CASCADE,
    exam_question_id uuid NOT NULL REFERENCES public.exam_questions(id) ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by_token_id uuid REFERENCES public.auth_refresh_tokens(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_classes_teacher_id ON public.classes(teacher_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_class_hash ON public.documents(class_id, hash);
CREATE INDEX IF NOT EXISTS idx_documents_class_id ON public.documents(class_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON public.chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON public.chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON public.chunks USING gin(text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_entities_trgm ON public.chunks USING gin ((entities_json::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_bm25 ON public.chunks
    USING bm25 (id, text)
    WITH (key_field='id');
CREATE INDEX IF NOT EXISTS idx_quizzes_class_id ON public.quizzes(class_id);
CREATE INDEX IF NOT EXISTS idx_quiz_documents_document_id ON public.quiz_documents(document_id);
CREATE INDEX IF NOT EXISTS idx_quiz_submissions_quiz_id ON public.quiz_submissions(quiz_id);
CREATE INDEX IF NOT EXISTS idx_quiz_submissions_student_id ON public.quiz_submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_exams_class_id ON public.exams(class_id);
CREATE INDEX IF NOT EXISTS idx_exams_owner_id ON public.exams(owner_id);
CREATE INDEX IF NOT EXISTS idx_exams_created_at ON public.exams(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exams_is_published ON public.exams(is_published);
CREATE INDEX IF NOT EXISTS idx_exam_questions_exam_id ON public.exam_questions(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_questions_position ON public.exam_questions(exam_id, position);
CREATE INDEX IF NOT EXISTS idx_exam_documents_document_id ON public.exam_documents(document_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_id ON public.exam_submissions(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_student_id ON public.exam_submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_student ON public.exam_submissions(exam_id, student_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_status ON public.exam_submissions(status);
CREATE INDEX IF NOT EXISTS idx_exam_answers_submission_id ON public.exam_answers(submission_id);
CREATE INDEX IF NOT EXISTS idx_exam_answers_question_id ON public.exam_answers(exam_question_id);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_user_id ON public.auth_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_active_lookup
    ON public.auth_refresh_tokens(token_hash)
    WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION public.update_exams_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_exams_updated_at ON public.exams;
CREATE TRIGGER trigger_exams_updated_at
    BEFORE UPDATE ON public.exams
    FOR EACH ROW
    EXECUTE FUNCTION public.update_exams_updated_at();

CREATE OR REPLACE FUNCTION app_security.request_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_security.is_request_user(target_user_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT target_user_id IS NOT NULL AND target_user_id = app_security.request_user_id()
$$;

CREATE OR REPLACE FUNCTION app_security.is_teacher(user_id uuid DEFAULT app_security.request_user_id())
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = user_id AND u.role = 'teacher'
    )
$$;

CREATE OR REPLACE FUNCTION app_security.is_student(user_id uuid DEFAULT app_security.request_user_id())
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = user_id AND u.role = 'student'
    )
$$;

CREATE OR REPLACE FUNCTION app_security.owns_class(target_class_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.classes c
        WHERE c.id = target_class_id
          AND c.teacher_id = app_security.request_user_id()
    )
$$;

CREATE OR REPLACE FUNCTION app_security.is_class_owned_by_teacher(target_class_id uuid, target_teacher_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.classes c
        WHERE c.id = target_class_id
          AND c.teacher_id = target_teacher_id
    )
$$;

CREATE OR REPLACE FUNCTION app_security.enrolled_in_class(target_class_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.class_students cs
        WHERE cs.class_id = target_class_id
          AND cs.student_id = app_security.request_user_id()
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_read_user(target_user_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT app_security.is_request_user(target_user_id)
        OR (
            app_security.is_teacher()
            AND EXISTS (
                SELECT 1
                FROM public.users u
                JOIN public.class_students cs ON cs.student_id = u.id
                JOIN public.classes c ON c.id = cs.class_id
                WHERE u.id = target_user_id
                  AND u.role = 'student'
                  AND c.teacher_id = app_security.request_user_id()
            )
        )
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_class(target_class_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT app_security.owns_class(target_class_id)
        OR app_security.enrolled_in_class(target_class_id)
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_document_class(target_class_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT app_security.is_teacher()
       AND (target_class_id IS NULL OR app_security.owns_class(target_class_id))
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_document(target_document_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.documents d
        WHERE d.id = target_document_id
          AND (
              (d.class_id IS NULL AND app_security.is_teacher())
              OR app_security.owns_class(d.class_id)
              OR app_security.enrolled_in_class(d.class_id)
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_document(target_document_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.documents d
        WHERE d.id = target_document_id
          AND app_security.can_manage_document_class(d.class_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_chunk_media(target_chunk_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.chunks c
        WHERE c.id = target_chunk_id
          AND app_security.can_access_document(c.document_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_chunk_media(target_chunk_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.chunks c
        WHERE c.id = target_chunk_id
          AND app_security.can_manage_document(c.document_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_quiz(target_quiz_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.quizzes q
        WHERE q.id = target_quiz_id
          AND (
              (q.class_id IS NULL AND app_security.is_teacher())
              OR app_security.owns_class(q.class_id)
              OR app_security.enrolled_in_class(q.class_id)
              OR EXISTS (
                  SELECT 1
                  FROM public.quiz_documents qd
                  WHERE qd.quiz_id = q.id
                    AND app_security.can_access_document(qd.document_id)
              )
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_quiz(target_quiz_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.quizzes q
        WHERE q.id = target_quiz_id
          AND app_security.is_teacher()
          AND (
              q.class_id IS NULL
              OR app_security.owns_class(q.class_id)
              OR EXISTS (
                  SELECT 1
                  FROM public.quiz_documents qd
                  WHERE qd.quiz_id = q.id
                    AND app_security.can_manage_document(qd.document_id)
              )
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_exam(target_exam_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.exams e
        WHERE e.id = target_exam_id
          AND (
              (app_security.is_teacher() AND (
                  e.owner_id = app_security.request_user_id()
                  OR app_security.owns_class(e.class_id)
                  OR (e.owner_id IS NULL AND e.class_id IS NULL)
              ))
              OR (
                  e.is_published
                  AND e.class_id IS NOT NULL
                  AND app_security.enrolled_in_class(e.class_id)
              )
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_exam(target_exam_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.exams e
        WHERE e.id = target_exam_id
          AND app_security.is_teacher()
          AND (
              e.owner_id = app_security.request_user_id()
              OR app_security.owns_class(e.class_id)
              OR (e.owner_id IS NULL AND e.class_id IS NULL)
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_access_exam_submission(target_submission_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.exam_submissions es
        WHERE es.id = target_submission_id
          AND (
              es.student_id = app_security.request_user_id()
              OR app_security.can_access_exam(es.exam_id)
          )
    )
$$;

CREATE OR REPLACE FUNCTION app_security.can_manage_exam_submission(target_submission_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.exam_submissions es
        WHERE es.id = target_submission_id
          AND app_security.can_manage_exam(es.exam_id)
    )
$$;

CREATE OR REPLACE FUNCTION app_security.auth_email_exists(lookup_email text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT EXISTS (SELECT 1 FROM public.users WHERE email = lookup_email)
$$;

CREATE OR REPLACE FUNCTION app_security.auth_lookup_user(lookup_email text)
RETURNS TABLE (
    id uuid,
    email text,
    password_hash text,
    full_name text,
    role text,
    created_at timestamptz,
    last_login_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT u.id, u.email, u.password_hash, u.full_name, u.role, u.created_at, u.last_login_at
    FROM public.users u
    WHERE u.email = lookup_email
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION app_security.auth_mark_last_login(target_user_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    UPDATE public.users
    SET last_login_at = now()
    WHERE id = target_user_id
$$;

CREATE OR REPLACE FUNCTION app_security.auth_register_user(
    new_email text,
    new_password_hash text,
    new_full_name text,
    new_role text
)
RETURNS TABLE (
    id uuid,
    email text,
    full_name text,
    role text,
    created_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
DECLARE
    inserted_user_id uuid;
BEGIN
    IF new_role NOT IN ('teacher', 'student') THEN
        RAISE EXCEPTION 'Invalid role: %', new_role;
    END IF;

    INSERT INTO public.users (email, password_hash, full_name, role)
    VALUES (new_email, new_password_hash, new_full_name, new_role)
    RETURNING users.id INTO inserted_user_id;

    IF new_role = 'teacher' THEN
        INSERT INTO public.teachers (user_id) VALUES (inserted_user_id);
    ELSE
        INSERT INTO public.students (user_id) VALUES (inserted_user_id);
    END IF;

    RETURN QUERY
    SELECT u.id, u.email, u.full_name, u.role, u.created_at
    FROM public.users u
    WHERE u.id = inserted_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION app_security.lookup_student_for_invite(lookup_email text)
RETURNS TABLE (
    id uuid,
    email text,
    full_name text,
    role text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    SELECT u.id, u.email, u.full_name, u.role
    FROM public.users u
    WHERE u.email = lookup_email
      AND app_security.is_teacher()
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION app_security.auth_store_refresh_token(
    target_user_id uuid,
    new_token_hash text,
    new_expires_at timestamptz
)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    INSERT INTO public.auth_refresh_tokens (user_id, token_hash, expires_at)
    VALUES (target_user_id, new_token_hash, new_expires_at)
    RETURNING id
$$;

CREATE OR REPLACE FUNCTION app_security.auth_rotate_refresh_token(
    current_token_hash text,
    next_token_hash text,
    next_expires_at timestamptz
)
RETURNS TABLE (
    id uuid,
    email text,
    full_name text,
    role text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
DECLARE
    current_token public.auth_refresh_tokens%ROWTYPE;
    next_token_id uuid;
BEGIN
    SELECT *
    INTO current_token
    FROM public.auth_refresh_tokens
    WHERE token_hash = current_token_hash
    FOR UPDATE;

    IF current_token.id IS NULL
       OR current_token.revoked_at IS NOT NULL
       OR current_token.expires_at <= now() THEN
        RETURN;
    END IF;

    INSERT INTO public.auth_refresh_tokens (user_id, token_hash, expires_at)
    VALUES (current_token.user_id, next_token_hash, next_expires_at)
    RETURNING auth_refresh_tokens.id INTO next_token_id;

    UPDATE public.auth_refresh_tokens
    SET revoked_at = now(),
        replaced_by_token_id = next_token_id,
        last_used_at = now()
    WHERE auth_refresh_tokens.id = current_token.id;

    RETURN QUERY
    SELECT u.id, u.email, u.full_name, u.role
    FROM public.users u
    WHERE u.id = current_token.user_id;
END;
$$;

CREATE OR REPLACE FUNCTION app_security.auth_revoke_refresh_token(current_token_hash text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
BEGIN
    UPDATE public.auth_refresh_tokens
    SET revoked_at = now(),
        last_used_at = now()
    WHERE token_hash = current_token_hash
      AND revoked_at IS NULL
      AND expires_at > now();

    RETURN FOUND;
END;
$$;

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.teachers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.class_students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunk_media ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quizzes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exams ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exam_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exam_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exam_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exam_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_refresh_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_read_allowed ON public.users;
CREATE POLICY users_read_allowed ON public.users
FOR SELECT USING (app_security.can_read_user(id));

DROP POLICY IF EXISTS users_update_self ON public.users;
CREATE POLICY users_update_self ON public.users
FOR UPDATE USING (app_security.is_request_user(id))
WITH CHECK (app_security.is_request_user(id));

DROP POLICY IF EXISTS teachers_read_allowed ON public.teachers;
CREATE POLICY teachers_read_allowed ON public.teachers
FOR SELECT USING (
    app_security.is_request_user(user_id)
    OR app_security.is_teacher(user_id)
    OR app_security.is_teacher()
);

DROP POLICY IF EXISTS students_read_allowed ON public.students;
CREATE POLICY students_read_allowed ON public.students
FOR SELECT USING (
    app_security.is_request_user(user_id)
    OR app_security.can_read_user(user_id)
);

DROP POLICY IF EXISTS classes_select_allowed ON public.classes;
CREATE POLICY classes_select_allowed ON public.classes
FOR SELECT USING (app_security.can_access_class(id));

DROP POLICY IF EXISTS classes_insert_teacher ON public.classes;
CREATE POLICY classes_insert_teacher ON public.classes
FOR INSERT WITH CHECK (
    app_security.is_teacher()
    AND teacher_id = app_security.request_user_id()
);

DROP POLICY IF EXISTS classes_update_owner ON public.classes;
CREATE POLICY classes_update_owner ON public.classes
FOR UPDATE USING (app_security.owns_class(id))
WITH CHECK (
    app_security.is_teacher()
    AND teacher_id = app_security.request_user_id()
);

DROP POLICY IF EXISTS classes_delete_owner ON public.classes;
CREATE POLICY classes_delete_owner ON public.classes
FOR DELETE USING (app_security.owns_class(id));

DROP POLICY IF EXISTS class_students_select_allowed ON public.class_students;
CREATE POLICY class_students_select_allowed ON public.class_students
FOR SELECT USING (
    app_security.owns_class(class_id)
    OR student_id = app_security.request_user_id()
);

DROP POLICY IF EXISTS class_students_insert_owner ON public.class_students;
CREATE POLICY class_students_insert_owner ON public.class_students
FOR INSERT WITH CHECK (app_security.owns_class(class_id));

DROP POLICY IF EXISTS class_students_delete_owner ON public.class_students;
CREATE POLICY class_students_delete_owner ON public.class_students
FOR DELETE USING (app_security.owns_class(class_id));

DROP POLICY IF EXISTS documents_select_allowed ON public.documents;
CREATE POLICY documents_select_allowed ON public.documents
FOR SELECT USING (
    app_security.can_access_document(id)
    OR app_security.can_manage_document_class(class_id)
);

DROP POLICY IF EXISTS documents_insert_teacher ON public.documents;
CREATE POLICY documents_insert_teacher ON public.documents
FOR INSERT WITH CHECK (app_security.can_manage_document_class(class_id));

DROP POLICY IF EXISTS documents_update_teacher ON public.documents;
CREATE POLICY documents_update_teacher ON public.documents
FOR UPDATE USING (app_security.can_manage_document(id))
WITH CHECK (app_security.can_manage_document_class(class_id));

DROP POLICY IF EXISTS documents_delete_teacher ON public.documents;
CREATE POLICY documents_delete_teacher ON public.documents
FOR DELETE USING (app_security.can_manage_document(id));

DROP POLICY IF EXISTS chunks_select_allowed ON public.chunks;
CREATE POLICY chunks_select_allowed ON public.chunks
FOR SELECT USING (app_security.can_access_document(document_id));

DROP POLICY IF EXISTS chunks_insert_teacher ON public.chunks;
CREATE POLICY chunks_insert_teacher ON public.chunks
FOR INSERT WITH CHECK (app_security.can_manage_document(document_id));

DROP POLICY IF EXISTS chunks_update_teacher ON public.chunks;
CREATE POLICY chunks_update_teacher ON public.chunks
FOR UPDATE USING (app_security.can_manage_document(document_id))
WITH CHECK (app_security.can_manage_document(document_id));

DROP POLICY IF EXISTS chunks_delete_teacher ON public.chunks;
CREATE POLICY chunks_delete_teacher ON public.chunks
FOR DELETE USING (app_security.can_manage_document(document_id));

DROP POLICY IF EXISTS chunk_media_select_allowed ON public.chunk_media;
CREATE POLICY chunk_media_select_allowed ON public.chunk_media
FOR SELECT USING (app_security.can_access_chunk_media(chunk_id));

DROP POLICY IF EXISTS chunk_media_insert_teacher ON public.chunk_media;
CREATE POLICY chunk_media_insert_teacher ON public.chunk_media
FOR INSERT WITH CHECK (app_security.can_manage_chunk_media(chunk_id));

DROP POLICY IF EXISTS chunk_media_delete_teacher ON public.chunk_media;
CREATE POLICY chunk_media_delete_teacher ON public.chunk_media
FOR DELETE USING (app_security.can_manage_chunk_media(chunk_id));

DROP POLICY IF EXISTS quizzes_select_allowed ON public.quizzes;
CREATE POLICY quizzes_select_allowed ON public.quizzes
FOR SELECT USING (app_security.can_access_quiz(id));

DROP POLICY IF EXISTS quizzes_insert_teacher ON public.quizzes;
CREATE POLICY quizzes_insert_teacher ON public.quizzes
FOR INSERT WITH CHECK (
    app_security.is_teacher()
    AND (class_id IS NULL OR app_security.owns_class(class_id))
);

DROP POLICY IF EXISTS quizzes_update_teacher ON public.quizzes;
CREATE POLICY quizzes_update_teacher ON public.quizzes
FOR UPDATE USING (app_security.can_manage_quiz(id))
WITH CHECK (
    app_security.is_teacher()
    AND (class_id IS NULL OR app_security.owns_class(class_id))
);

DROP POLICY IF EXISTS quizzes_delete_teacher ON public.quizzes;
CREATE POLICY quizzes_delete_teacher ON public.quizzes
FOR DELETE USING (app_security.can_manage_quiz(id));

DROP POLICY IF EXISTS quiz_documents_select_allowed ON public.quiz_documents;
CREATE POLICY quiz_documents_select_allowed ON public.quiz_documents
FOR SELECT USING (app_security.can_access_quiz(quiz_id));

DROP POLICY IF EXISTS quiz_documents_insert_teacher ON public.quiz_documents;
CREATE POLICY quiz_documents_insert_teacher ON public.quiz_documents
FOR INSERT WITH CHECK (
    app_security.can_manage_quiz(quiz_id)
    AND app_security.can_manage_document(document_id)
);

DROP POLICY IF EXISTS quiz_documents_delete_teacher ON public.quiz_documents;
CREATE POLICY quiz_documents_delete_teacher ON public.quiz_documents
FOR DELETE USING (app_security.can_manage_quiz(quiz_id));

DROP POLICY IF EXISTS quiz_submissions_select_allowed ON public.quiz_submissions;
CREATE POLICY quiz_submissions_select_allowed ON public.quiz_submissions
FOR SELECT USING (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_quiz(quiz_id)
);

DROP POLICY IF EXISTS quiz_submissions_insert_student ON public.quiz_submissions;
CREATE POLICY quiz_submissions_insert_student ON public.quiz_submissions
FOR INSERT WITH CHECK (
    student_id = app_security.request_user_id()
    AND app_security.can_access_quiz(quiz_id)
);

DROP POLICY IF EXISTS quiz_submissions_update_owner_or_teacher ON public.quiz_submissions;
CREATE POLICY quiz_submissions_update_owner_or_teacher ON public.quiz_submissions
FOR UPDATE USING (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_quiz(quiz_id)
)
WITH CHECK (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_quiz(quiz_id)
);

DROP POLICY IF EXISTS exams_select_allowed ON public.exams;
CREATE POLICY exams_select_allowed ON public.exams
FOR SELECT USING (app_security.can_access_exam(id));

DROP POLICY IF EXISTS exams_insert_teacher ON public.exams;
CREATE POLICY exams_insert_teacher ON public.exams
FOR INSERT WITH CHECK (
    app_security.is_teacher()
    AND (owner_id IS NULL OR owner_id = app_security.request_user_id())
    AND (class_id IS NULL OR app_security.owns_class(class_id))
);

DROP POLICY IF EXISTS exams_update_teacher ON public.exams;
CREATE POLICY exams_update_teacher ON public.exams
FOR UPDATE USING (app_security.can_manage_exam(id))
WITH CHECK (
    app_security.is_teacher()
    AND (owner_id IS NULL OR owner_id = app_security.request_user_id())
    AND (class_id IS NULL OR app_security.owns_class(class_id))
);

DROP POLICY IF EXISTS exams_delete_teacher ON public.exams;
CREATE POLICY exams_delete_teacher ON public.exams
FOR DELETE USING (app_security.can_manage_exam(id));

DROP POLICY IF EXISTS exam_questions_select_allowed ON public.exam_questions;
CREATE POLICY exam_questions_select_allowed ON public.exam_questions
FOR SELECT USING (app_security.can_access_exam(exam_id));

DROP POLICY IF EXISTS exam_questions_insert_teacher ON public.exam_questions;
CREATE POLICY exam_questions_insert_teacher ON public.exam_questions
FOR INSERT WITH CHECK (app_security.can_manage_exam(exam_id));

DROP POLICY IF EXISTS exam_questions_update_teacher ON public.exam_questions;
CREATE POLICY exam_questions_update_teacher ON public.exam_questions
FOR UPDATE USING (app_security.can_manage_exam(exam_id))
WITH CHECK (app_security.can_manage_exam(exam_id));

DROP POLICY IF EXISTS exam_questions_delete_teacher ON public.exam_questions;
CREATE POLICY exam_questions_delete_teacher ON public.exam_questions
FOR DELETE USING (app_security.can_manage_exam(exam_id));

DROP POLICY IF EXISTS exam_documents_select_allowed ON public.exam_documents;
CREATE POLICY exam_documents_select_allowed ON public.exam_documents
FOR SELECT USING (app_security.can_access_exam(exam_id));

DROP POLICY IF EXISTS exam_documents_insert_teacher ON public.exam_documents;
CREATE POLICY exam_documents_insert_teacher ON public.exam_documents
FOR INSERT WITH CHECK (
    app_security.can_manage_exam(exam_id)
    AND app_security.can_manage_document(document_id)
);

DROP POLICY IF EXISTS exam_documents_delete_teacher ON public.exam_documents;
CREATE POLICY exam_documents_delete_teacher ON public.exam_documents
FOR DELETE USING (app_security.can_manage_exam(exam_id));

DROP POLICY IF EXISTS exam_submissions_select_allowed ON public.exam_submissions;
CREATE POLICY exam_submissions_select_allowed ON public.exam_submissions
FOR SELECT USING (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_exam(exam_id)
);

DROP POLICY IF EXISTS exam_submissions_insert_student ON public.exam_submissions;
CREATE POLICY exam_submissions_insert_student ON public.exam_submissions
FOR INSERT WITH CHECK (
    student_id = app_security.request_user_id()
    AND app_security.can_access_exam(exam_id)
);

DROP POLICY IF EXISTS exam_submissions_update_owner_or_teacher ON public.exam_submissions;
CREATE POLICY exam_submissions_update_owner_or_teacher ON public.exam_submissions
FOR UPDATE USING (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_exam(exam_id)
)
WITH CHECK (
    student_id = app_security.request_user_id()
    OR app_security.can_manage_exam(exam_id)
);

DROP POLICY IF EXISTS exam_answers_select_allowed ON public.exam_answers;
CREATE POLICY exam_answers_select_allowed ON public.exam_answers
FOR SELECT USING (app_security.can_access_exam_submission(submission_id));

DROP POLICY IF EXISTS exam_answers_insert_student ON public.exam_answers;
CREATE POLICY exam_answers_insert_student ON public.exam_answers
FOR INSERT WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.exam_submissions es
        WHERE es.id = submission_id
          AND es.student_id = app_security.request_user_id()
    )
);

DROP POLICY IF EXISTS exam_answers_update_owner_or_teacher ON public.exam_answers;
CREATE POLICY exam_answers_update_owner_or_teacher ON public.exam_answers
FOR UPDATE USING (
    app_security.can_access_exam_submission(submission_id)
    OR app_security.can_manage_exam_submission(submission_id)
)
WITH CHECK (
    app_security.can_access_exam_submission(submission_id)
    OR app_security.can_manage_exam_submission(submission_id)
);

DROP POLICY IF EXISTS auth_refresh_tokens_no_direct_access ON public.auth_refresh_tokens;
CREATE POLICY auth_refresh_tokens_no_direct_access ON public.auth_refresh_tokens
FOR ALL USING (false)
WITH CHECK (false);

DO $$
DECLARE
    app_role text := NULLIF(current_setting('app.rls_app_role', true), '');
BEGIN
    IF app_role IS NOT NULL AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
        EXECUTE format('GRANT USAGE ON SCHEMA app_security TO %I', app_role);
        EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_security TO %I', app_role);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', app_role);
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', app_role);
    END IF;
END $$;
