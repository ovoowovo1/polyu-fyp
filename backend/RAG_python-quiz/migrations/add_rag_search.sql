-- Portable retrieval schema, also used by local/CI integration databases.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS embedding vector(3072);
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS entities_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(text, ''))) STORED;
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON public.chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON public.chunks USING gin(text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_document_order ON public.chunks(document_id, chunk_index);
ANALYZE public.chunks;
