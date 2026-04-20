ALTER TABLE public.chunks
ADD COLUMN IF NOT EXISTS embedding_v2 vector(3072);
