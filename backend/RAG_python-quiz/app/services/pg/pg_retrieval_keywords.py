"""Independent lexical and trigram ranks, always bounded by file scope and RLS."""
import psycopg2
import psycopg2.extras

from app.logger import get_logger
from app.services.pg.pg_retrieval_vectors import map_context_row

logger = get_logger(__name__)

SELECT = """
    SELECT c.text, {score} AS score, d.name AS source, c.page_start,
        c.page_end, c.chunk_index, c.document_id AS fileid, c.id AS chunkid,
        media.data AS image_data, media.mimetype AS image_mimetype
    FROM chunks c JOIN documents d ON d.id = c.document_id
    LEFT JOIN chunk_media media ON media.chunk_id = c.id
    CROSS JOIN (SELECT websearch_to_tsquery('simple', %s) AS ts_query,
        %s::text AS raw_query) query
    WHERE ({match}) AND c.document_id = ANY(%s::uuid[])
        AND app_security.can_access_document(c.document_id)
    ORDER BY score {order} NULLS LAST, c.id LIMIT %s
"""


def build_keyword_query(backend: str, keywords: str):
    score = "ts_rank_cd(c.tsv, query.ts_query)"
    if backend == "lakebase_text":
        score = "c.tsv <@> to_bm25query(to_tsvector('simple', query.raw_query), 'public.idx_chunks_lakebase_bm25'::regclass)"
    return SELECT.format(score=score, match="c.tsv @@ query.ts_query",
                         order="ASC" if backend == "lakebase_text" else "DESC"), [keywords, keywords]


def retrieve_context_by_keywords(*, get_conn, backend: str, keywords: str,
                                selected_file_ids: list[str], k: int) -> list[dict]:
    if not selected_file_ids or not keywords.strip():
        return []

    def lexical(search_backend):
        sql, params = build_keyword_query(search_backend, keywords)
        with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if search_backend == "lakebase_text":
                cur.execute("SELECT set_config('lakebase_bm25.prefilter', 'on', true), "
                            "set_config('lakebase_bm25.default_limit', %s, true)", (str(k),))
            cur.execute(sql, params + [selected_file_ids, k])
            return [map_context_row(row) for row in cur.fetchall()]

    try:
        lexical_rows = lexical(backend)
    except psycopg2.Error:
        if backend != "lakebase_text":
            raise
        logger.warning("Lakebase BM25 unavailable; using scoped PostgreSQL full text search", exc_info=True)
        lexical_rows = lexical("postgres")

    fuzzy_sql = SELECT.format(score="word_similarity(query.raw_query, c.text)",
        match="(query.raw_query <% c.text OR c.text ILIKE '%%' || query.raw_query || '%%')", order="DESC")
    # psycopg2 requires literal percent operators escaped separately from placeholders.
    fuzzy_sql = fuzzy_sql.replace(" <% ", " <%% ")
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(fuzzy_sql, [keywords, keywords, selected_file_ids, k])
        fuzzy_rows = [map_context_row(row) for row in cur.fetchall()]
    merged = {}
    for channel, rows in (("lexical_rank", lexical_rows), ("fuzzy_rank", fuzzy_rows)):
        for rank, row in enumerate(rows, 1):
            merged.setdefault(row["chunkId"], row)[channel] = rank
    return sorted(merged.values(), key=lambda d: sum(1 / (60 + d[key])
                  for key in ("lexical_rank", "fuzzy_rank") if key in d), reverse=True)
