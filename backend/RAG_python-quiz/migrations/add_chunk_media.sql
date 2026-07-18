-- Store embedded PDF images associated with individual retrieval chunks.
-- Run this as the schema owner/admin role before applying RLS policies.

CREATE TABLE IF NOT EXISTS public.chunk_media (
    chunk_id uuid PRIMARY KEY REFERENCES public.chunks(id) ON DELETE CASCADE,
    mimetype text NOT NULL,
    data bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
