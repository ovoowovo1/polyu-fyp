-- RLS smoke test for document INSERT ... RETURNING and chunk media access.
-- This script is executed as the postgres schema owner in CI and temporarily
-- switches to a non-owner app role so row-level security is actually enforced.

SELECT 'CREATE ROLE app_backend NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend')\gexec

GRANT USAGE ON SCHEMA public, app_security TO app_backend;
GRANT SELECT, INSERT, DELETE ON public.documents, public.chunks, public.chunk_media TO app_backend;

INSERT INTO public.users (id, email, password_hash, full_name, role)
VALUES
    ('00000000-0000-0000-0000-000000000081', 'rls-teacher@example.com', 'unused', 'RLS Teacher', 'teacher'),
    ('00000000-0000-0000-0000-000000000082', 'rls-student@example.com', 'unused', 'RLS Student', 'student')
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.teachers (user_id)
VALUES ('00000000-0000-0000-0000-000000000081')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO public.students (user_id)
VALUES ('00000000-0000-0000-0000-000000000082')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO public.classes (id, teacher_id, name, code)
VALUES ('00000000-0000-0000-0000-000000000083', '00000000-0000-0000-0000-000000000081', 'RLS Media Class', 'RLS-MEDIA')
ON CONFLICT (id) DO NOTHING;

BEGIN;
SET LOCAL ROLE app_backend;
SET LOCAL app.user_id = '00000000-0000-0000-0000-000000000081';

INSERT INTO public.documents (hash, name, size_bytes, mimetype, class_id)
VALUES ('rls-media-smoke', 'rls-media.pdf', 10, 'application/pdf', '00000000-0000-0000-0000-000000000083')
RETURNING id AS document_id\gset

INSERT INTO public.chunks (document_id, text, page_start, page_end, chunk_index)
VALUES (:'document_id', 'Image source: rls-media.pdf', 1, 1, 0)
RETURNING id AS chunk_id\gset

INSERT INTO public.chunk_media (chunk_id, mimetype, data)
VALUES (:'chunk_id', 'image/png', decode('aW1hZ2U=', 'base64'));

SELECT EXISTS (
    SELECT 1 FROM public.chunk_media WHERE chunk_id = :'chunk_id'::uuid
) AS teacher_can_read_chunk_media
\gset
\if :teacher_can_read_chunk_media
\else
    \echo 'teacher could not read inserted chunk media'
    \quit 1
\endif

SET LOCAL app.user_id = '00000000-0000-0000-0000-000000000082';
SELECT EXISTS (
    SELECT 1 FROM public.chunk_media WHERE chunk_id = :'chunk_id'::uuid
) AS student_can_read_chunk_media
\gset
\if :student_can_read_chunk_media
    \echo 'student could read teacher chunk media'
    \quit 1
\endif

ROLLBACK;

DELETE FROM public.classes WHERE id = '00000000-0000-0000-0000-000000000083';
DELETE FROM public.users WHERE id IN (
    '00000000-0000-0000-0000-000000000081',
    '00000000-0000-0000-0000-000000000082'
);
DROP OWNED BY app_backend;
DROP ROLE app_backend;
