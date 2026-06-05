# -*- coding: utf-8 -*-
"""Keyword retrieval SQL helpers."""

import psycopg2.extras

from app.services.pg.pg_retrieval_vectors import map_context_row


def build_keyword_query(backend: str, keywords: str):
    if backend == "postgres":
        return (
            """
                WITH query AS (
                    SELECT websearch_to_tsquery('simple', %s) AS ts_query,
                           %s::text AS raw_query
                )
                SELECT
                    c.text,
                    (
                        ts_rank_cd(c.tsv, query.ts_query)
                        + GREATEST(
                            similarity(COALESCE(c.text, ''), query.raw_query),
                            similarity(COALESCE(c.entities_json::text, ''), query.raw_query)
                        )
                    ) AS score,
                    d.name AS source,
                    c.page_start,
                    c.document_id AS fileid,
                    c.id AS chunkid
                FROM public.chunks AS c
                JOIN public.documents AS d ON d.id = c.document_id
                CROSS JOIN query
                WHERE c.tsv @@ query.ts_query
                   OR similarity(COALESCE(c.text, ''), query.raw_query) > 0
                   OR similarity(COALESCE(c.entities_json::text, ''), query.raw_query) > 0
            """,
            [keywords, keywords],
        )

    return (
        """
                SELECT
                    c.text,
                    paradedb.score(c.id) AS score,
                    d.name AS source,
                    c.page_start,
                    c.document_id AS fileid,
                    c.id AS chunkid
                FROM public.chunks AS c
                JOIN public.documents AS d ON d.id = c.document_id
                WHERE c.text @@@ %s
            """,
        [keywords],
    )


def retrieve_context_by_keywords(
    *,
    get_conn,
    backend: str,
    keywords: str,
    selected_file_ids: list[str],
    k: int,
) -> list[dict]:
    base_sql, params = build_keyword_query(backend, keywords)
    if selected_file_ids:
        base_sql += " AND c.document_id = ANY(%s::uuid[]) "
        params.append(selected_file_ids)

    base_sql += " ORDER BY score DESC NULLS LAST LIMIT %s "
    params.append(k)

    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(base_sql, params)
        return [map_context_row(row) for row in cur.fetchall()]
