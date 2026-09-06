-- Only for the confirmed empty document store. Never discard newly uploaded data.
BEGIN;
LOCK TABLE public.documents, public.chunks, public.chunk_media IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.documents)
       OR EXISTS (SELECT 1 FROM public.chunks)
       OR EXISTS (SELECT 1 FROM public.chunk_media) THEN
        RAISE EXCEPTION 'Single embedding migration requires an empty document store';
    END IF;
END $$;
ALTER TABLE public.chunks DROP COLUMN IF EXISTS embedding_v2;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS embedding vector(3072);
ALTER TABLE public.chunks ALTER COLUMN embedding TYPE vector(3072);
COMMIT;
