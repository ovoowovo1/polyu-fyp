-- Enable PostgreSQL Row-Level Security for Neon deployments.
--
-- Run this as the schema owner/admin role. The application should connect with a
-- non-owner role without BYPASSRLS for these policies to be enforced.

CREATE SCHEMA IF NOT EXISTS app_security;

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
          AND app_security.is_teacher()
          AND (d.class_id IS NULL OR app_security.owns_class(d.class_id))
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
