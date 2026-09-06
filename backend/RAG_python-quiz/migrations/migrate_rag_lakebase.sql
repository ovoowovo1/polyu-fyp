-- Neon only. Test on an isolated branch first; run via a direct connection.
-- Run after data loading. Failure leaves the previous index intact (one transaction).
BEGIN;
CREATE EXTENSION IF NOT EXISTS lakebase_text;
DROP INDEX IF EXISTS public.idx_chunks_bm25;
-- Intentionally no CASCADE: unexpected dependencies must be reviewed explicitly.
DROP EXTENSION IF EXISTS pg_search;
CREATE INDEX IF NOT EXISTS idx_chunks_lakebase_bm25 ON public.chunks USING lakebase_bm25(tsv);
COMMIT;
-- Also run this after a batch of user-initiated reimports, outside a transaction.
VACUUM (ANALYZE) public.chunks;
