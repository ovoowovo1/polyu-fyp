-- Scope document deduplication to a class so one class cannot conflict with
-- a document that RLS hides in another class.
ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_hash_key;
DROP INDEX IF EXISTS public.idx_documents_hash;
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_class_hash ON public.documents(class_id, hash);
